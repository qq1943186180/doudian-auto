"""Native Ego transport, isolated by durable TaskSpace and unique script rounds."""

import hashlib
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from .bridge import Bridge
from .errors import DoudianError, WaitingHuman
from .jobs import DATA_ROOT, TransportLock

# Ego reclaims task spaces and later reuses their ids. A cached id that has been
# recycled fails while the space is being resolved, i.e. before any Page exists,
# so re-pointing state.json and retrying once cannot replay a page action.
SPACE_NOT_FOUND = 'task space not found'
SPACE_ALIGN_FAILED = 'ego_space_align_failed'


class EgoBridge(Bridge):
    def __init__(self, endpoint='ego', session='doudian-auto', timeout=25):
        self.endpoint, self.session, self.timeout = 'ego', session, timeout
        self.run_id = uuid.uuid4().hex[:12]
        # Last align_space() outcome, kept for callers that report why a command
        # needed a second round: {'old': 2, 'new': 1, 'changed': True}.
        self.space_alignment = None

    @property
    def session_dir(self):
        return DATA_ROOT / 'ego-sessions' / hashlib.sha256(self.session.encode()).hexdigest()[:24]

    def _check_pending(self, root):
        pending = root / 'pending-command.json'
        if not pending.exists():
            return
        try:
            record = json.loads(pending.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise DoudianError('ego_operation_unsettled', 'Ego待核查操作记录未完整读取，未发出新操作。') from exc
        token = record.get('token', '') if isinstance(record, dict) else ''
        if not re.fullmatch(r'[a-f0-9]{32}', token):
            raise DoudianError('ego_operation_unsettled', 'Ego待核查操作记录异常，未发出新操作。')
        output = root / f'{token}.result.json'
        settled = None
        if output.is_file():
            try:
                settled = json.loads(output.read_text(encoding='utf-8'))
            except (ValueError, OSError):
                pass  # A late result can still be in the middle of a write.
        if (not isinstance(settled, dict) or type(settled.get('ok')) is not bool or
                (settled.get('error') or {}).get('mayHaveLateEffects') is True):
            raise DoudianError('ego_operation_unsettled',
                'Ego上一操作尚未确认结束；未发出新操作，也未重放。请保留任务并核查晚到结果。')
        # The result remains on disk as evidence. Consuming it never replays it or
        # changes a product's unknown submission state. The marker itself is kept
        # instead of deleted: every browser command would otherwise delete a file,
        # which both wears out the filesystem and can be blocked mid-run by an
        # external delete guard. The next command overwrites it.
        return token

    @staticmethod
    def _error(code, message, raw, action, output):
        """Attach the runtime's own words; the wrapper text alone hides the cause."""
        error = DoudianError(code, message)
        error.details = {'action': action,
                         'raw_code': str((raw or {}).get('code') or ''),
                         'raw_message': str((raw or {}).get('message') or ''),
                         'result_file': str(output)}
        return error

    def _run(self, action, args=None):
        try:
            return self._execute(action, args)
        except DoudianError as error:
            if not space_stale(error):
                raise
            # One repair, one retry. A second failure surfaces with its own
            # message instead of looping over the same recycled space.
            try:
                self.align_space()
            except DoudianError as repair:
                details = dict(getattr(repair, 'details', None) or {})
                details['original_message'] = str((getattr(error, 'details', None) or {}).get('raw_message', ''))
                repair.details = details
                raise repair from error
            return self._execute(action, args)

    def _execute(self, action, args=None):
        executable = shutil.which('ego-browser.cmd') or shutil.which('ego-browser')
        if not executable:
            raise WaitingHuman('ego_not_installed', '未找到Ego原生浏览器工具。')
        root = self.session_dir
        root.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        request, output, script = (root / f'{token}{suffix}' for suffix in ('.json', '.result.json', '.mjs'))
        request.write_text(json.dumps({'action': action, 'args': args or {},
            'session': self.session, 'runId': self.run_id,
            'statePath': str(root / 'state.json')}, ensure_ascii=False), encoding='utf-8')
        runtime = Path(__file__).with_name('ego_runtime.mjs').resolve().as_uri()
        script.write_text(
            'const fs=await import("node:fs/promises");\n'
            'const {runEgo}=await import(' + json.dumps(runtime) + ');\n'
            'try { const result=await runEgo(JSON.parse(await fs.readFile(' + json.dumps(str(request)) + ',"utf8")));\n'
            'await fs.writeFile(' + json.dumps(str(output)) + ',JSON.stringify({ok:true,data:result}),"utf8");\n'
            '} catch(e) { await fs.writeFile(' + json.dumps(str(output)) +
            ',JSON.stringify({ok:false,error:{code:e.code||"ego_error",message:String(e.message),'
            'executionStopped:e.executionStopped,mayHaveLateEffects:e.mayHaveLateEffects,inputDispatched:e.inputDispatched}}),"utf8"); }', encoding='utf-8')
        # No shell interpolation of product text, selectors or code. Never replay this
        # subprocess after timeout: even a failed command may have dispatched a save.
        with TransportLock(root / 'transport.lock'):
            self._check_pending(root)
            pending = root / 'pending-command.json'
            pending.write_text(json.dumps({'token': token, 'action': action,
                                          'run_id': self.run_id}), encoding='utf-8')
            try:
                subprocess.run([executable, 'nodejs', '-e',
                    "await import('" + script.as_uri() + "')"],
                    # The JSON result is written by the script. On Windows a CLI
                    # child can inherit PIPE handles and keep communicate() stuck
                    # after its parent times out. No pipes are needed here.
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    encoding='utf-8', errors='replace', timeout=65 if action == 'upload' else 35)
            except subprocess.TimeoutExpired as exc:
                raise DoudianError('ego_transport_unknown', 'Ego操作超时，未重放；保存结果须只读核查。') from exc
            if not output.is_file():
                raise DoudianError('ego_transport_unknown', 'Ego未返回操作结果，未重放；请按队列状态核查。')
            result = json.loads(output.read_text(encoding='utf-8'))
            if (result.get('error') or {}).get('mayHaveLateEffects') is True:
                # The marker stays on disk so the next round still refuses to run
                # until this operation is confirmed settled.
                pass
        if not result.get('ok'):
            error = result.get('error') or {}
            message = str(error.get('message', ''))
            code = error.get('code') or 'ego_error'
            if any(word in message for word in ('EPERM', 'EACCES', 'refs.json')):
                code = 'ego_state_locked'
            if code in ('ego_control_required', 'EGO_TASK_SPACE_INACTIVE', 'EGO_TASK_SPACE_UNASSIGNED'):
                raise self._error('ego_control_required',
                                  'Ego任务控制已交给你，请完成当前页面后恢复任务。', error, action, output)
            if code == 'ego_session_finished':
                raise self._error(code, '上次Ego任务已结束，请使用新的 --session 任务名。', error, action, output)
            raise self._error(code, 'Ego未确认完成操作；没有自动重试。' +
                              (' 本地页面状态文件被占用。' if code == 'ego_state_locked' else ''),
                              error, action, output)
        return result.get('data')

    def _probe_space_result(self):
        """Ask the live browser which id this session's task space really has.

        The answer is written to a file, exactly like _execute(), because on
        Windows a CLI child can inherit pipe handles and wedge a read. Creating a
        missing space keeps the runtime's own lazy-creation rule (taskSpace(name))
        instead of inventing a second container mechanism.
        """
        executable = shutil.which('ego-browser.cmd') or shutil.which('ego-browser')
        if not executable:
            raise WaitingHuman('ego_not_installed', '未找到Ego原生浏览器工具。')
        root = self.session_dir
        root.mkdir(parents=True, exist_ok=True)
        token = uuid.uuid4().hex
        script = root / f'{token}.space.mjs'
        output = root / f'{token}.space.json'
        script.write_text(
            'const fs=await import("node:fs/promises");\n'
            'const name=' + json.dumps(self.session) + ';\n'
            'const write=obj=>fs.writeFile(' + json.dumps(str(output)) + ',JSON.stringify(obj),"utf8");\n'
            'try{\n'
            ' const all=await listTaskSpaces();\n'
            ' const list=Array.isArray(all)?all:(all&&all.taskSpaces)||[];\n'
            ' const nm=s=>String((s&&(s.name||s.taskId))||"");\n'
            # A space that went back to the user is ended; claiming it mid-run would
            # take the browser away from whoever owns it now.
            ' const agent=s=>String((s&&s.ownership)||"").toLowerCase()!=="user";\n'
            ' const live=list.filter(agent);\n'
            ' const exact=live.find(s=>nm(s)===name);\n'
            ' const prefixed=live.find(s=>nm(s).startsWith("doudian-auto "+name+" "));\n'
            ' const hit=exact||prefixed;\n'
            ' let id=hit?(hit.id??hit.spaceId):null;\n'
            ' let created=false;\n'
            ' if(id===null||id===undefined||id===""){\n'
            '  const create=(typeof useOrCreateTaskSpace==="function")?useOrCreateTaskSpace:taskSpace;\n'
            '  const t=await create(name);\n'
            '  id=t&&(t.id??t.spaceId??t.taskSpaceId);created=true;\n'
            ' }\n'
            ' await write({ok:true,spaceId:id,created,matched:hit?nm(hit):null,'
            'spaces:list.map(s=>({id:(s&&s.id)??null,name:nm(s)}))});\n'
            '}catch(e){await write({ok:false,error:{code:(e&&e.code)||"ego_space_probe_failed",'
            'message:String((e&&e.message)||e)}});}\n', encoding='utf-8')
        with TransportLock(root / 'transport.lock'):
            try:
                subprocess.run([executable, 'nodejs', '-e',
                    "await import('" + script.as_uri() + "')"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    encoding='utf-8', errors='replace', timeout=60)
            except subprocess.TimeoutExpired as exc:
                raise DoudianError(SPACE_ALIGN_FAILED,
                    'Ego任务空间探测超时，未改写本地页面状态；请确认浏览器窗口后重试。') from exc
            if not output.is_file():
                raise DoudianError(SPACE_ALIGN_FAILED,
                    'Ego任务空间探测未返回结果，未改写本地页面状态；请确认 ego-browser 可用。')
            try:
                result = json.loads(output.read_text(encoding='utf-8'))
            except (ValueError, OSError) as exc:
                raise DoudianError(SPACE_ALIGN_FAILED,
                    'Ego任务空间探测结果不完整，未改写本地页面状态。') from exc
        if not isinstance(result, dict) or result.get('ok') is not True:
            error = (result or {}).get('error') or {}
            raise DoudianError(SPACE_ALIGN_FAILED,
                'Ego任务空间探测失败：' + str(error.get('message') or '未知原因'))
        return result

    def align_space(self):
        """Return this session's live task-space id, repairing state.json if stale.

        Only the cached id is rewritten, and only when it differs: pages/active
        name tabs that died with the old space, so they are dropped. The previous
        file is kept as state.json.bak-auto for forensics.
        """
        state_path = self.session_dir / 'state.json'
        if not state_path.is_file():
            probe = self._probe_space_result()
            live = _space_id(probe)
            self.space_alignment = {'old': None, 'new': live, 'changed': False}
            return live
        try:
            state = json.loads(state_path.read_text(encoding='utf-8'))
        except (ValueError, OSError) as exc:
            raise DoudianError(SPACE_ALIGN_FAILED,
                'Ego本地页面状态文件无法读取，未改写；请人工核查 state.json。') from exc
        if not isinstance(state, dict):
            raise DoudianError(SPACE_ALIGN_FAILED,
                'Ego本地页面状态文件格式异常，未改写；请人工核查 state.json。')
        cached = state.get('spaceId')
        live = _space_id(self._probe_space_result())
        if _as_int(cached) == live:
            self.space_alignment = {'old': cached, 'new': live, 'changed': False}
            return live
        try:
            shutil.copyfile(state_path, state_path.with_name(state_path.name + '.bak-auto'))
            state['spaceId'] = live
            state['pages'] = {}
            state['active'] = None
            state_path.write_text(json.dumps(state, ensure_ascii=False), encoding='utf-8')
        except OSError as exc:
            raise DoudianError(SPACE_ALIGN_FAILED,
                f'Ego本地页面状态文件无法写入（{exc}），未完成空间对齐。') from exc
        self.space_alignment = {'old': cached, 'new': live, 'changed': True}
        return live

    def status(self):
        try:
            result = self._run('status')
            return {'running': result.get('connected') is True,
                    'extension_connected': result.get('connected') is True,
                    'version_mismatch': False, 'transport': 'ego-native'}
        except DoudianError as exc:
            return {'running': False, 'extension_connected': False,
                    'transport': 'ego-native', 'error': exc.code}

    def require_ready(self):
        status = self.status()
        if status.get('error') == 'ego_operation_unsettled':
            raise DoudianError('ego_operation_unsettled', 'Ego上一操作尚未确认结束；请核查晚到结果，未重放或恢复桌面。')
        if not status.get('running'):
            raise WaitingHuman('ego_not_connected', 'Ego原生浏览器连接尚未就绪。')

    def command(self, action, args=None):
        return self._run(action, args)


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _space_id(probe):
    """Validate the id the browser reported; a non-numeric answer is a hard failure."""
    raw = probe.get('spaceId')
    live = _as_int(raw)
    if live is None:
        raise DoudianError(SPACE_ALIGN_FAILED,
            f'Ego任务空间探测没有返回可用空间号（{raw!r}），未改写本地页面状态。')
    return live


def space_stale(error):
    """True when a failure happened while resolving a recycled task space."""
    if getattr(error, 'waiting', False):
        # A space handed over to the user is not stale; retrying would claim it back.
        return False
    if getattr(error, 'code', '') in ('ego_task_space_missing', 'EGO_TASK_SPACE_NOT_FOUND'):
        return True
    details = getattr(error, 'details', None) or {}
    if SPACE_NOT_FOUND in str(details.get('raw_message', '')):
        return True
    return SPACE_NOT_FOUND in str(error)


def align_space(session='doudian-auto'):
    """Align one session's cached task-space id and return the live id."""
    return EgoBridge(session=session).align_space()

"""Native Ego transport, isolated by durable TaskSpace and unique script rounds."""

import hashlib
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from .bridge import Bridge
from .errors import DoudianError, WaitingHuman
from .jobs import DATA_ROOT, Lock


class EgoBridge(Bridge):
    def __init__(self, endpoint='ego', session='doudian-auto', timeout=25):
        self.endpoint, self.session, self.timeout = 'ego', session, timeout
        self.run_id = uuid.uuid4().hex[:12]

    @property
    def session_dir(self):
        return DATA_ROOT / 'ego-sessions' / hashlib.sha256(self.session.encode()).hexdigest()[:24]

    def _run(self, action, args=None):
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
        with Lock(root / 'transport.lock'):
            try:
                subprocess.run([executable, 'nodejs', '-e',
                    "await import('" + script.as_uri() + "')"], capture_output=True,
                    encoding='utf-8', errors='replace', timeout=65 if action == 'upload' else 35)
            except subprocess.TimeoutExpired as exc:
                raise DoudianError('ego_transport_unknown', 'Ego操作超时，未重放；保存结果须只读核查。') from exc
            if not output.is_file():
                raise DoudianError('ego_transport_unknown', 'Ego未返回操作结果，未重放；请按队列状态核查。')
            result = json.loads(output.read_text(encoding='utf-8'))
        if not result.get('ok'):
            error = result.get('error') or {}
            message = str(error.get('message', ''))
            code = error.get('code') or 'ego_error'
            if any(word in message for word in ('EPERM', 'EACCES', 'refs.json')):
                code = 'ego_state_locked'
            if code in ('ego_control_required', 'EGO_TASK_SPACE_INACTIVE', 'EGO_TASK_SPACE_UNASSIGNED'):
                raise WaitingHuman('ego_control_required', 'Ego任务控制已交给你，请完成当前页面后恢复任务。')
            if code == 'ego_session_finished':
                raise DoudianError(code, '上次Ego任务已结束，请使用新的 --session 任务名。')
            raise DoudianError(code, 'Ego未确认完成操作；没有自动重试。' +
                               (' 本地页面状态文件被占用。' if code == 'ego_state_locked' else ''))
        return result.get('data')

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
        if not self.status().get('running'):
            raise WaitingHuman('ego_not_connected', 'Ego原生浏览器连接尚未就绪。')

    def command(self, action, args=None):
        return self._run(action, args)

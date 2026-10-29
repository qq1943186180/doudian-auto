import json
from pathlib import Path
import shutil
import time
from urllib.error import URLError
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen

from .errors import DoudianError, WaitingHuman


class Bridge:
    def __new__(cls, endpoint='http://127.0.0.1:10086', *args, **kwargs):
        if cls is Bridge and endpoint == 'ego':
            from .ego_bridge import EgoBridge
            return object.__new__(EgoBridge)
        return object.__new__(cls)

    def __init__(self, endpoint='http://127.0.0.1:10086', session='doudian-auto', timeout=25):
        parsed = urlparse(endpoint)
        if parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', 'localhost', '::1') or parsed.username or parsed.password:
            raise DoudianError('invalid_endpoint', '浏览器连接仅允许本机HTTP地址。')
        self.endpoint = endpoint.rstrip('/')
        self.session = session
        self.timeout = timeout

    def status(self):
        try:
            with urlopen(self.endpoint + '/status', timeout=5) as response:
                data = json.load(response)
            if not isinstance(data.get('running'), bool):
                raise ValueError('wrong service')
            return {key: data.get(key) for key in ('running', 'extension_connected', 'version', 'extension_version', 'version_mismatch')}
        except (OSError, ValueError, URLError):
            return {'running': False, 'extension_connected': False}

    def require_ready(self):
        status = self.status()
        if not status.get('running') or not status.get('extension_connected') or status.get('version_mismatch'):
            raise WaitingHuman('browser_not_connected', '请在Edge连接Kimi扩展本地控制，再查看任务状态继续。')

    def command(self, action, args=None):
        body = json.dumps({'action': action, 'args': args or {}, 'session': self.session}, ensure_ascii=True).encode()
        request = Request(self.endpoint + '/command', data=body, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=self.timeout) as response:
                result = json.load(response)
        except (OSError, ValueError) as exc:
            # Never replay a possibly delivered mutation after a network failure.
            raise DoudianError('bridge_transport', '浏览器请求未确认完成，请检查任务状态后重试。') from exc
        if not result.get('ok'):
            err = result.get('error') or {}
            code = str(err.get('code', 'bridge_error'))
            if any(word in code.lower() for word in ('connect', 'login', 'version', 'not_allowed')):
                raise WaitingHuman('browser_action_needed', '浏览器连接、版本或文件上传权限需要处理。')
            raise DoudianError('bridge_error', f'浏览器命令失败：{action}（{code}）。')
        data = result.get('data')
        if isinstance(data, dict) and data.get('success') is False:
            raise DoudianError('bridge_action_failed', f'浏览器未完成操作：{action}。请检查页面后继续。')
        return data

    def evaluate(self, code):
        result = self.command('evaluate', {'code': code})
        value = result.get('value') if isinstance(result, dict) and 'value' in result else result
        if isinstance(value, str):
            try:
                return json.loads(value)
            except ValueError:
                pass
        return value

    def open(self, url, *, fresh=False):
        self.require_ready()
        if not fresh:
            tabs = self.command('list_tabs') or {}
            pid = parse_qs(urlparse(url).query).get('product_id')
            for tab in reversed(tabs.get('tabs', [])):
                candidate = urlparse(tab.get('url', ''))
                if tab.get('url') == url or (pid and candidate.hostname == 'fxg.jinritemai.com' and candidate.path == '/ffa/g/create' and parse_qs(candidate.query).get('product_id') == pid):
                    # find_tab matches by host in some Bridge versions and can
                    # select a different same-host product page. Attach by the
                    # exact tab id returned by list_tabs instead.
                    if tab.get('tabId') is not None:
                        return self.command('attach_tab', {'tabId': tab['tabId']})
                    raise DoudianError('tab_id_missing', '匹配的浏览器标签没有可验证的标签ID。')
        return self.command('navigate', {'url': url, 'newTab': True, 'group_title': '抖店本地上传'})

    def screenshot(self, destination):
        result = self.command('screenshot', {'format': 'png', 'path': str(Path(destination).resolve())})
        source = Path(result.get('path', ''))
        dest = Path(destination).resolve()
        if not source.is_file():
            raise DoudianError('screenshot_missing', '截图文件未保存。')
        if source.resolve() != dest:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, dest)
        return str(dest)

    def wait(self, probe, predicate, message, seconds=60):
        deadline = time.monotonic() + seconds
        while True:
            result = probe()
            if predicate(result):
                return result
            if time.monotonic() >= deadline:
                raise DoudianError('page_timeout', message)
            time.sleep(0.4)

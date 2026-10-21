import json
from importlib.resources import files
from urllib.parse import urlparse

from .errors import DoudianError, WaitingHuman
from .jobs import HOST


class Editor:
    def __init__(self, bridge):
        self.bridge = bridge
        self.script = files('doudian_auto').joinpath('dom.js').read_text(encoding='utf-8').strip()

    def dom(self, op, manifest=None, **kwargs):
        args = {key: manifest[key] for key in ('product_id', 'shop')} if manifest else {}
        result = self.bridge.evaluate(self.script + '(' + json.dumps(op) + ',' + json.dumps({**args, **kwargs}, ensure_ascii=True) + ')')
        if not isinstance(result, dict):
            raise DoudianError('invalid_dom', '页面未返回有效数据。')
        error = result.get('error')
        if error:
            if error in ('verification_required', 'shop_not_confirmed', 'editor_not_ready'):
                raise WaitingHuman(error, '请确认登录、验证及店铺名称；页面准备好后继续。')
            raise DoudianError(error, f'页面结构或商品身份不匹配（{error}），已停止。')
        return result

    def open(self, manifest, fresh=False):
        self.bridge.open(manifest['edit_url'], fresh=fresh)
        # A loading page can be polled; no browser mutation is replayed here.
        def ready():
            try:
                return self.dom('snapshot', manifest)
            except WaitingHuman as exc:
                if exc.code != 'editor_not_ready':
                    raise
                return None
        result = self.bridge.wait(ready, lambda x: bool(x), '商品编辑页尚未加载。', seconds=30)
        if not result.get('success'):
            self.dom('scroll', manifest, kind='details')
        return result

    def read(self, manifest):
        return self.dom('snapshot', manifest)

    def replace(self, manifest, kind, before_upload):
        self.dom('scroll', manifest, kind=kind)
        count_key = 'main_delete_count' if kind == 'mains' else 'detail_delete_count'
        # Count based, bounded deletion tolerates a prior interrupted partial replacement.
        for _ in range(101):
            current = self.read(manifest)
            count = current[count_key]
            if count == 0:
                break
            self.dom('delete', manifest, kind=kind)
            self.bridge.wait(lambda: self.read(manifest), lambda s: s[count_key] < count, '删除图片未完成，请检查页面。', seconds=15)
        else:
            raise DoudianError('delete_limit', '原图数量超过本地上传模块上限。')
        if self.read(manifest)[kind]:
            raise DoudianError('delete_incomplete', '图片仍在页面中，未开始上传。')
        selector = self.dom('upload_selector', manifest, kind=kind)['selector']
        before_upload()
        self.bridge.command('upload', {'selector': selector, 'files': [r['path'] for r in manifest[kind]]})
        result = self.bridge.wait(lambda: self.read(manifest), lambda s: len(s[kind]) == len(manifest[kind]) and s[count_key] == len(manifest[kind]), '上传尚未完成或图片数量不匹配。', seconds=90)
        return result[kind]

    def fill_title(self, manifest):
        self.read(manifest)  # Guard identity before the only text write.
        self.bridge.command('fill', {'selector': '#pg-title-input', 'value': manifest['title']})
        self.bridge.wait(lambda: self.read(manifest), lambda s: s['title'] == manifest['title'], '标题未写入。', seconds=10)

    def check(self, manifest):
        self.dom('button', manifest, name='填写检查')
        snapshot = self.read(manifest)
        if snapshot.get('errors'):
            raise WaitingHuman('platform_validation', '平台填写检查发现问题：' + '；'.join(snapshot['errors']))
        return snapshot

    def publish(self, manifest):
        self.dom('button', manifest, name='发布商品')
        return self.bridge.wait(lambda: self.read(manifest), lambda s: s.get('success') or bool(s.get('errors')), '提交结果尚未确认；请先核验，勿重复发布。', seconds=60)

    def screenshot(self, path):
        return self.bridge.screenshot(path)

    def list_products(self, limit):
        self.bridge.open(f'https://{HOST}/ffa/g/list')
        return self.dom('list', limit=limit)

    def inspect(self, selector=None):
        snapshot = self.bridge.command('snapshot')
        if urlparse(snapshot.get('url', '')).hostname != HOST:
            raise DoudianError('wrong_host', '只允许检查抖店页面。')
        if selector:
            if 'password' in selector.lower():
                raise DoudianError('invalid_selector', '不读取密码字段。')
            return self.dom('inspect', selector=selector)
        return snapshot

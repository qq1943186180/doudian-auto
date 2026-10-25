import json
from importlib.resources import files
import time
from urllib.parse import urlparse

from .errors import DoudianError, WaitingHuman
from .jobs import HOST

# Kept apart from dom.js on purpose: this probe is polled while the page mounts, so it
# must stay small and cheap. Counting controls per block is enough to tell "still
# mounting" from "settled" -- the distinction the baseline depends on.
#
# Wire format is a flat "name|inputs|text|visible" string per block, joined by ';'.
# Two constraints came from probing the live bridge, and both are load-bearing:
# the selector is written without quotes around the attribute value, and the whole script
# stays on one line. Either form with quotes or newlines fails intermittently with a
# transport error while this form succeeds, and the probe runs in a polling loop -- a
# flaky call would turn into a flaky baseline.
_COUNT_SCRIPT = ("[...document.querySelectorAll('[id^=goodsEditScrollContainer-]')]"
                 ".map(function (s) { return [s.id.replace('goodsEditScrollContainer-', ''), "
                 "s.querySelectorAll('input,textarea,select').length, "
                 "(s.textContent || '').replace(/\\s+/g, '').length, "
                 "s.offsetParent !== null ? 1 : 0].join('|'); }).join(';')")


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
            except DoudianError as exc:
                # The title input mounts before the `[attr-field-id]` blocks do, so a
                # freshly opened editor legitimately reports `editor_layout_changed` for a
                # few frames. Treating that as a hard failure aborted every reopen. A
                # genuinely wrong layout never resolves and still fails at the deadline.
                if exc.code != 'editor_layout_changed':
                    raise
                return None
        try:
            result = self.bridge.wait(ready, lambda x: bool(x), '商品编辑页尚未加载。', seconds=30)
        except DoudianError as exc:
            if exc.code != 'page_timeout':
                raise
            # Re-raise the concrete shape so the caller sees why, not just a timeout.
            self.dom('snapshot', manifest)
            raise
        if not result.get('success'):
            self.dom('scroll', manifest, kind='details')
        return result

    def read(self, manifest):
        return self.dom('snapshot', manifest)

    def section_counts(self, manifest):
        """Per-section control counts: the readiness signal for the protected blocks.

        Cheaper than a full snapshot and sufficient to tell "still mounting" from
        "settled" -- measured on one listing the same page reported 88 price/stock inputs
        while still mounting and 98 once settled, next to 3 vs 7 service inputs.
        """
        payload = self.bridge.evaluate(_COUNT_SCRIPT)
        if not isinstance(payload, str) or not payload.strip():
            raise DoudianError('protected_incomplete', '页面未返回分区统计（{0}）。'.format(payload))
        counts = {}
        for row in payload.split(';'):
            parts = row.split('|')
            if len(parts) != 4:
                raise DoudianError('protected_incomplete', '分区统计格式异常：{0}'.format(row[:80]))
            counts[parts[0]] = {'inputs': int(parts[1]), 'text': int(parts[2]),
                                'visible': parts[3] == '1'}
        if not counts:
            raise DoudianError('protected_sections_missing', '商品页未找到任何保护分区。')
        return counts

    def wait_details(self, manifest, seconds=30):
        # Polling, deadline and final classification live here so read, replace, the
        # pre-publish check and verify all share one detail-read semantic.
        def ready(snapshot):
            return snapshot.get('detail_status') in ('ready', 'empty')
        try:
            return self.bridge.wait(lambda: self.read(manifest), ready, '详情图数据源未就绪。', seconds=seconds)
        except DoudianError as exc:
            if exc.code != 'page_timeout':
                raise
            snapshot = self.read(manifest)
            raise DoudianError('detail_source_not_ready', '详情图数据源未就绪：状态={0}，来源={1}，商详声明={2}，缩略卡片={3}，已加载={4}。{5}'.format(
                snapshot.get('detail_status'), snapshot.get('detail_source'), snapshot.get('detail_declared'),
                snapshot.get('detail_cards'), len(snapshot.get('details', [])), snapshot.get('detail_reason') or ''))

    def replace(self, manifest, kind, before_upload):
        assets = manifest.get(kind)
        if not isinstance(assets, list) or not assets:
            # Deletion runs before any asset is read, so a missing or empty list would strip
            # the listing's images and only then fail on the absent record. Nothing here is
            # recoverable once deleted, so refuse before touching the page at all.
            raise DoudianError('missing_assets', '{0} 素材清单缺失或为空，未删除任何图片。'.format(kind))
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
        if kind == 'details':
            # A stale source must stop the run instead of being ignored; matching
            # counts alone would let old URLs be recorded as the fresh upload result.
            # `empty` requires the standard area to be truly zeroed AND the live
            # preview to hold no slot; the stale decorate canvas never counts.
            def cleared(snapshot):
                return (snapshot.get('detail_status') == 'empty'
                        and snapshot.get('detail_declared') == 0
                        and snapshot.get('detail_cards') == 0
                        and snapshot.get('detail_delete_count') == 0)
            try:
                self.bridge.wait(lambda: self.read(manifest), cleared, '详情图未清空。', seconds=15)
            except DoudianError as exc:
                if exc.code != 'page_timeout':
                    raise
                snapshot = self.read(manifest)
                raise DoudianError('delete_incomplete', '详情图仍有残留：状态={0}，声明={1}，卡片={2}，删除钮={3}，槽位={4}，画布={5}。{6}'.format(
                    snapshot.get('detail_status'), snapshot.get('detail_declared'), snapshot.get('detail_cards'),
                    snapshot.get('detail_delete_count'), snapshot.get('detail_slots'), snapshot.get('canvas_count'),
                    snapshot.get('detail_reason') or ''))
        elif self.read(manifest)[kind]:
            raise DoudianError('delete_incomplete', '图片仍在页面中，未开始上传。')
        selector = self.dom('upload_selector', manifest, kind=kind)['selector']
        before_upload()
        self.bridge.command('upload', {'selector': selector, 'files': [r['path'] for r in manifest[kind]]})
        def uploaded(snapshot):
            expected = len(manifest[kind])
            if len(snapshot.get(kind, [])) != expected or snapshot.get(count_key) != expected:
                return False
            # Counts are necessary but not sufficient; the cross-check must agree too.
            if kind == 'details':
                return (snapshot.get('detail_status') == 'ready'
                        and snapshot.get('detail_declared') == expected
                        and snapshot.get('detail_cards') == expected
                        and snapshot.get('detail_delete_count') == expected
                        and snapshot.get('detail_slots') == expected)
            return True
        result = self.bridge.wait(lambda: self.read(manifest), uploaded, '上传尚未完成或图片数量不匹配。', seconds=90)
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

    def publish_state(self, manifest):
        """Classify the post-click page without raising on transient frames.

        Right after "发布商品" is pressed the page passes through frames where the editor
        is already gone but the result is not rendered yet. `read()` raises
        `editor_not_ready` on those frames, and an exception aborts `Bridge.wait` before
        its predicate ever runs -- which is exactly how a real successful submit was
        mistaken for a stall. This probe returns a classification instead, and is the only
        place allowed to tolerate the transition.
        """
        result = self.dom('publish_state', manifest)
        return {'state': result.get('state'), 'success': result.get('success'),
                'rejected': result.get('rejected'), 'errors': result.get('errors'),
                'rejection_reasons': result.get('rejection_reasons'),
                'rejection_count': result.get('rejection_count')}

    def publish(self, manifest):
        self.dom('button', manifest, name='发布商品')
        # The click happens exactly once, outside the poll. Never re-click on timeout.
        deadline = time.monotonic() + 90
        last = None
        while True:
            last = self.publish_state(manifest)
            if last['state'] in ('accepted', 'rejected', 'validation_failed'):
                return last
            if time.monotonic() >= deadline:
                # Unknown is persisted by the caller and must be resolved by verify().
                return {'state': 'unknown', 'success': False, 'rejected': None, 'errors': None}
            time.sleep(0.5)

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

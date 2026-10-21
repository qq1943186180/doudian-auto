from pathlib import Path
import time

from .errors import DoudianError
from .jobs import DATA_ROOT, Lock, load_job, read_json, write_json


def compare_protected(before, after):
    if not before.get('protected') or before['protected'] != after.get('protected'):
        raise DoudianError('commercial_changed', '类目、规格、价格库存、服务或其他保留字段与编辑前不一致，已停止提交。')


def match_content(manifest, state, snapshot):
    if snapshot.get('product_id') != manifest['product_id'] or not snapshot.get('shop_confirmed'):
        raise DoudianError('wrong_identity', '核验商品或店铺不匹配。')
    if snapshot.get('title') != manifest['title']:
        raise DoudianError('title_mismatch', '读回标题与任务不符。')
    for kind in ('mains', 'details'):
        expected = state.get(kind + '_urls')
        if not expected or len(expected) != len(manifest[kind]) or snapshot.get(kind) != expected:
            raise DoudianError('images_mismatch', '读回图片地址或顺序与上传记录不符。')


class Workflow:
    def __init__(self, job, editor, lock_root=None):
        self.job = Path(job).resolve()
        self.manifest = load_job(self.job)
        self.editor = editor
        # One stable browser session per immutable job, including separate CLI invocations.
        self.editor.bridge.session = 'doudian-auto-' + self.manifest['job_id']
        self.lock_root = Path(lock_root or DATA_ROOT)
        self.state = read_json(self.job / 'state.json')
        if self.state.get('content_hash') != self.manifest['content_hash']:
            raise DoudianError('state_mismatch', '任务状态与素材版本不一致。')

    def save(self, stage=None, **fields):
        self.state.update(fields)
        if stage:
            self.state['stage'] = stage
        self.state['updated_at'] = time.time()
        write_json(self.job / 'state.json', self.state)

    def baseline(self):
        return read_json(self.job / 'before.json')

    def reload(self):
        # A second process may have constructed this object before the first released its lock.
        current_manifest = load_job(self.job)
        if current_manifest['content_hash'] != self.manifest['content_hash']:
            raise DoudianError('manifest_changed', '等待操作期间任务内容改变，请重新读取任务。')
        self.state = read_json(self.job / 'state.json')
        if self.state.get('content_hash') != self.manifest['content_hash']:
            raise DoudianError('state_mismatch', '任务状态与素材版本不一致。')

    def upload(self, apply=False):
        if not apply:
            return {'dry_run': True, 'product_id': self.manifest['product_id'], 'title': self.manifest['title'], 'mains': 5, 'details': len(self.manifest['details']), 'writes': ['标题', '5张方主图', '标准详情'], 'job_dir': str(self.job)}
        with Lock(self.lock_root / 'browser.lock'), Lock(self.job / 'job.lock'):
            self.reload()
            if self.state['stage'] in ('submitting', 'submitted', 'saved'):
                raise DoudianError('verify_required', '任务已进入提交阶段，请运行verify；不重复上传或发布。')
            current = self.editor.open(self.manifest)
            if current.get('success'):
                raise DoudianError('verify_required', '当前是提交成功页，请先核验已有任务。')
            if not (self.job / 'before.json').exists():
                if self.state['stage'] != 'prepared':
                    raise DoudianError('baseline_missing', '缺少原商品快照，不能继续覆盖。')
                write_json(self.job / 'before.json', current)
            compare_protected(self.baseline(), current)
            self.save('editing')
            for kind in ('mains', 'details'):
                current = self.editor.read(self.manifest)
                expected = self.state.get(kind + '_urls')
                if expected and current[kind] == expected and len(expected) == len(self.manifest[kind]):
                    continue
                # An uncertain upload may leave remote images with unknown provenance.
                # Clear that slot and re-upload the exact immutable local set; never trust count alone.
                urls = self.editor.replace(self.manifest, kind, lambda: self.save('editing', pending_upload=kind))
                self.save('editing', **{kind + '_urls': urls, 'pending_upload': None})
            self.editor.fill_title(self.manifest)
            current = self.editor.read(self.manifest)
            compare_protected(self.baseline(), current)
            match_content(self.manifest, self.state, current)
            write_json(self.job / 'uploaded.json', current)
            self.save('uploaded', last_error=None)
            return {'stage': 'uploaded', 'job_dir': str(self.job), 'next': '确认预览后运行submit；尚未发布'}

    def submit(self, apply=False):
        if not apply:
            return {'dry_run': True, 'stage': self.state['stage'], 'action': '发布已上传任务，并重开核验'}
        with Lock(self.lock_root / 'browser.lock'), Lock(self.job / 'job.lock'):
            self.reload()
            if self.state['stage'] != 'uploaded':
                raise DoudianError('not_uploaded', '仅uploaded状态可发布；提交结果不明时先verify。')
            current = self.editor.open(self.manifest)
            compare_protected(self.baseline(), current)
            match_content(self.manifest, self.state, current)
            checked = self.editor.check(self.manifest)
            compare_protected(self.baseline(), checked)
            match_content(self.manifest, self.state, checked)
            # Persist before sending. Timeout/crash after this point must NEVER auto-republish.
            self.save('submitting', submitted_at=time.time())
            result = self.editor.publish(self.manifest)
            if not result.get('success'):
                self.save('uploaded', last_error='platform_validation')
                raise DoudianError('platform_validation', '平台未提交成功，请在页面检查必填项。')
            self.save('submitted')
            # A failed screenshot must not prevent the authoritative saved readback.
            try:
                self.editor.screenshot(self.job / 'submitted.png')
            except DoudianError as exc:
                self.save(screenshot_error=exc.code)
            return self._verify()

    def _verify(self):
        current = self.editor.open(self.manifest, fresh=True)
        # Give lazy detail images time to resolve their CDN addresses after scrolling.
        current = self.editor.bridge.wait(lambda: self.editor.read(self.manifest), lambda s: len(s.get('mains', [])) == 5 and len(s.get('details', [])) == len(self.manifest['details']) and s.get('detail_status') == 'ready', '重开后的商品图片尚未完整加载。', seconds=30)
        write_json(self.job / 'readback.json', current)
        try:
            match_content(self.manifest, self.state, current)
            compare_protected(self.baseline(), current)
        except DoudianError as exc:
            self.save('submitted', last_error=exc.code, verification_failed_at=time.time())
            raise
        self.save('saved', verified_at=time.time(), last_error=None)
        return {'stage': 'saved', 'verified': True, 'job_dir': str(self.job), 'coverage': current.get('coverage'), 'notice': '已重开编辑页核验；消费者端生效仍以平台审核为准。'}

    def verify(self):
        with Lock(self.lock_root / 'browser.lock'), Lock(self.job / 'job.lock'):
            self.reload()
            if self.state['stage'] not in ('submitting', 'submitted', 'saved'):
                raise DoudianError('not_submitted', '任务尚未进入提交阶段，不能宣称保存成功。')
            return self._verify()

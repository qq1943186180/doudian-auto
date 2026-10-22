from pathlib import Path
import time
from urllib.parse import urlparse

from .errors import DoudianError
from .jobs import DATA_ROOT, Lock, load_job, read_json, write_json

_MATERIAL_MARK = 'ecom-shop-material/'


def resource_key(url):
    """Normalize a material CDN URL to the identity of the underlying asset.

    The same asset is served under different path prefixes (`/obj/`, `/img/`, none),
    with different rendition suffixes (`~tplv-...q75.image|.avis`, `~750x0_q90_b0.jpg`),
    and from rotating CDN hosts (`p3-aio` / `p6-aio` / `p9-aio`). Measured on the live
    page, one asset id moved from `p3-aio` to `p6-aio` between two reads while the bytes
    were unchanged, so keeping the host produced false "commercial field changed" alarms.
    The asset id is content-addressed (`jpeg_m_<hash>_sx_<size>_www<W>-<H>`), which is
    what actually identifies the image, so identity is the asset id alone.
    Non-material strings (and already-normalised keys) are returned unchanged, which
    keeps older state.json / before.json records comparable.
    """
    if not isinstance(url, str) or not url:
        return url
    try:
        parsed = urlparse(url)
    except ValueError:
        return url
    index = parsed.path.find(_MATERIAL_MARK)
    if index < 0:
        return url
    asset = parsed.path[index + len(_MATERIAL_MARK):].split('~', 1)[0]
    return asset


def _normalize_images(value):
    if isinstance(value, str):
        return resource_key(value)
    if isinstance(value, list):
        return [_normalize_images(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalize_images(item) for key, item in value.items()}
    return value


_SECTION_PREFIX = 'goodsEditScrollContainer-'
# Blocks the platform is known to render for every product; their absence means the page
# is not the editor we think it is, not that the product has no such block.
_REQUIRED_SECTIONS = ('基础信息', '价格库存', '服务与履约')


def _section_index(snapshot):
    """Index a protected snapshot by section name, or raise on an unsafe shape.

    A list compared positionally is only valid while both reads enumerate the *same*
    blocks in the same order. The platform hides whole blocks lazily, so the visible set
    shrinks and grows between reads and positional comparison then reports every later
    index as a change. Keys are therefore section names, and a shape that cannot be
    aligned safely is rejected rather than guessed at.
    """
    sections = snapshot.get('protected')
    if not isinstance(sections, list) or not sections:
        raise DoudianError('protected_snapshot_incomplete', '保留字段快照缺失，已停止提交。')
    index = {}
    for section in sections:
        identifier = section.get('section') if isinstance(section, dict) else None
        if not isinstance(identifier, str) or not identifier:
            # Legacy fixtures and older before.json files carry no section name; falling
            # back to a positional key would silently reintroduce the misalignment bug.
            raise DoudianError('protected_snapshot_incomplete', '保留字段快照缺少分区标识，已停止提交。')
        key = identifier[len(_SECTION_PREFIX):] if identifier.startswith(_SECTION_PREFIX) else identifier
        if key in index:
            raise DoudianError('protected_snapshot_incomplete', '保留字段快照存在重复分区（{0}），已停止提交。'.format(key))
        index[key] = section
    return index


def _observations(index):
    """Read the per-section observation state, defaulting legacy records to `legacy_ready`.

    Snapshots written before observation state existed were produced by a collector that
    filtered on visibility (`filter(visible)`), so every block present in an old baseline
    was visible at capture time -- that is a fact about the old collector, not a guess
    about the data. Those records are marked `legacy_ready` so the caller can decide
    whether to trust them, and any block absent from the old baseline stays unobserved
    because the old collector cannot prove it was looked at.
    """
    return {name: (section.get('observation') or 'legacy_ready') for name, section in index.items()}


# Keys that describe how a block was read rather than what it holds. Observation state is
# compared separately, so leaving it in the content compare would report a block that
# merely became observable as a commercial change.
_METADATA_KEYS = ('section', 'observation')


def _content(section):
    return {key: value for key, value in section.items() if key not in _METADATA_KEYS}


# Stages that are known to be safe to leave behind. Everything else blocks: a new
# version must never write to a listing while an older job's outcome is unknown, and a
# stage this code does not recognise is not evidence that the job finished. Keeping the
# safe list short is what makes newly added stages fail closed rather than open.
#
# `abandoned` is here because it is a terminal stage reached only by a human stating a
# reason, with the baseline hash written down -- not because the job quietly drained away.
_SAFE_STAGES = ('prepared', 'saved', 'abandoned')


def unresolved_siblings(jobs_root, product_id, exclude=None):
    """Other jobs for the same product that are not safe to leave behind.

    Shared by the revision workflow and the title-only path: both write to the same
    listing, so both need the same answer. The manifest is content-addressed, so a new
    title produces a *new* job_id; per-job guards alone cannot stop a second publish,
    because the new version starts at `prepared` and would sail past the old job's
    `submitting` state. The global browser lock only prevents concurrent writes, not two
    versions shipping one after another.

    Enumerated by manifest rather than by `state.json`, because a job whose manifest
    identifies this product but whose state file is missing would otherwise not be seen
    at all. A missing, unreadable or unrecognised state blocks: none of them proves that
    the previous job reached a terminal outcome, and the cost of blocking is one extra
    human check while the cost of not blocking is a second publish.

    Records that carry no readable manifest are the only ones skipped -- there is no
    product to compare them against. That is also how the retrospective record stays
    invisible: it deliberately has no manifest.json.
    """
    blockers = []
    root = Path(jobs_root)
    if not root.is_dir():
        return blockers
    skip = Path(exclude).resolve() if exclude else None
    for entry in sorted(p for p in root.iterdir() if p.is_dir()):
        if skip and entry.resolve() == skip:
            continue
        manifest = _read_object(entry / 'manifest.json')
        if manifest is None or manifest.get('product_id') != product_id:
            continue
        if manifest.get('record_kind') == 'retrospective':
            # A written-up record of a past run, not a task holding the listing.
            continue
        state = _read_object(entry / 'state.json')
        stage = state.get('stage') if state else None
        if stage not in _SAFE_STAGES:
            blockers.append({'job_dir': str(entry),
                             'stage': 'unreadable' if state is None else stage,
                             'title': manifest.get('title'),
                             'submission_status': (state or {}).get('submission_status')})
    return blockers


def _read_object(path):
    """Read JSON that must be an object, or None.

    A parsed JSON array is not a manifest or a state file, and calling `.get()` on one
    raises AttributeError -- from a sibling belonging to a *different* product, which
    would break an unrelated run. Unreadable records are treated as unknown, never as
    safe.
    """
    try:
        data = read_json(path)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def guard_siblings(jobs_root, product_id, exclude=None):
    blockers = unresolved_siblings(jobs_root, product_id, exclude)
    if not blockers:
        return
    detail = '；'.join(
        '{0}（{1}{2}）'.format(Path(b['job_dir']).name, b['stage'],
                              '，提交结果未知' if b['submission_status'] == 'unknown' else '')
        for b in blockers
    )
    raise DoudianError(
        'product_job_conflict',
        '同商品还有未完成的任务：{0}。请先对它们运行verify或处理完，再开始新版本；'
        '新任务不能绕过旧任务的提交保护。'.format(detail))


def compare_protected(before, after):
    """Fail unless every field outside the writable scope is provably unchanged.

    Only three outcomes are allowed: a block is observed on both sides and equal, or the
    run stops. An unobserved block is never treated as unchanged -- `visibility:hidden`
    and an empty field list are not evidence that a block carries no data.
    """
    baseline = _section_index(before)
    current = _section_index(after)
    missing = [name for name in _REQUIRED_SECTIONS if name not in baseline or name not in current]
    if missing:
        raise DoudianError('protected_sections_missing', '商品页缺少必需分区（{0}），已停止提交。'.format('、'.join(missing)))
    before_state = _observations(baseline)
    after_state = _observations(current)
    # `empty_block` means the platform rendered the container with no fields in it at all
    # (verified: forcing it visible leaves heading-height only). Such a block holds nothing
    # this tool could overwrite, so it is exempt -- but only when *both* reads agree, since
    # a block that gained fields between reads must never be skipped.
    def exempt(name):
        return before_state.get(name) == 'empty_block' and after_state.get(name) == 'empty_block'
    # `legacy_ready` is accepted for the baseline only: the old collector emitted exactly
    # the blocks that were visible, so its membership is itself the observation evidence.
    # A live read never gets this allowance, because a live read always reports its state.
    def usable(state, name):
        return state.get(name) in ('ready', 'empty_block') or (
            state is before_state and state.get(name) == 'legacy_ready')
    unobserved = sorted(
        name for name in set(baseline) | set(current)
        if not exempt(name) and not (usable(before_state, name) and usable(after_state, name))
    )
    if unobserved:
        raise DoudianError('protected_snapshot_incomplete', '以下分区无法可靠观测（{0}），已停止提交。'.format('、'.join(unobserved)))
    absent = sorted(set(baseline) ^ set(current))
    if absent:
        raise DoudianError('protected_snapshot_incomplete', '分区在一次读取中存在、另一次缺失（{0}），已停止提交。'.format('、'.join(absent)))
    for name in sorted(current):
        if exempt(name):
            continue
        if _normalize_images(_content(baseline[name])) != _normalize_images(_content(current[name])):
            raise DoudianError('commercial_changed', '类目、规格、价格库存、服务或其他保留字段与编辑前不一致，已停止提交。')


def compare_images_unchanged(before, after):
    """Report how far image verification goes for a task that never replaces images.

    `compare_protected` deliberately excludes the image blocks, so for a title-only run
    this is the only place image state is judged. When both reads produced a decoded
    detail source the addresses must match. When either side could not be read, that is
    recorded as a gap: two empty lists comparing equal is not evidence, and the detail
    panel never rendering is a known state on some listings.
    """
    gaps = []
    mains_before = [resource_key(u) for u in before.get('mains') or []]
    mains_after = [resource_key(u) for u in after.get('mains') or []]
    if mains_before and mains_after:
        if mains_before != mains_after:
            raise DoudianError('images_changed', '主图地址或顺序与改标题前不一致，已停止提交。')
    elif mains_before or mains_after:
        # One side observed main images and the other did not; that gap is itself a change,
        # and it is exactly what a partially rendered page would look like.
        raise DoudianError('images_changed', '主图在两次读取之间从有到无（或反过来），已停止提交。')
    else:
        gaps.append('主图两次读取均为空列表，未观测到主图，不声称图片未变。')

    before_status = before.get('detail_status')
    after_status = after.get('detail_status')
    if before_status == 'ready' and after_status == 'ready':
        details_before = [resource_key(u) for u in before.get('details') or []]
        details_after = [resource_key(u) for u in after.get('details') or []]
        if details_before != details_after:
            raise DoudianError('images_changed', '详情图地址或顺序与改标题前不一致，已停止提交。')
    else:
        # The detail source never rendering is a known state on some listings, so this
        # is recorded as a limit on what was checked, never as proof of equality.
        gaps.append('详情图数据源一侧未就绪（改前={0}，改后={1}），本次不核验详情图。'.format(
            before_status, after_status))
    return ('verified_unchanged' if not gaps else 'not_verified', ' '.join(gaps) or None)


def match_content(manifest, state, snapshot):
    if snapshot.get('product_id') != manifest['product_id'] or not snapshot.get('shop_confirmed'):
        raise DoudianError('wrong_identity', '核验商品或店铺不匹配。')
    if snapshot.get('title') != manifest['title']:
        raise DoudianError('title_mismatch', '读回标题与任务不符。')
    if manifest.get('mode') == 'title_only':
        # A title-only task deliberately leaves images alone, and its manifest carries
        # no asset list to compare against. Image scope is recorded separately by the
        # caller instead of being silently skipped here.
        return
    for kind in ('mains', 'details'):
        expected = state.get(kind + '_urls')
        recorded = [resource_key(url) for url in snapshot.get(kind) or []]
        if not expected or len(expected) != len(manifest[kind]) or recorded != [resource_key(url) for url in expected]:
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

    def unresolved_siblings(self):
        return unresolved_siblings(self.job.parent, self.manifest['product_id'], self.job)

    def guard_sibling_jobs(self):
        guard_siblings(self.job.parent, self.manifest['product_id'], self.job)

    def reload(self):
        # A second process may have constructed this object before the first released its lock.
        current_manifest = load_job(self.job)
        if current_manifest['content_hash'] != self.manifest['content_hash']:
            raise DoudianError('manifest_changed', '等待操作期间任务内容改变，请重新读取任务。')
        self.state = read_json(self.job / 'state.json')
        if self.state.get('content_hash') != self.manifest['content_hash']:
            raise DoudianError('state_mismatch', '任务状态与素材版本不一致。')

    def upload(self, apply=False):
        if self.manifest.get('mode') == 'title_only':
            # A title-only job stages no assets. Letting it reach the replacement path would
            # delete the listing's images first and fail only afterwards on the missing
            # asset list. Refuse before any work, dry-run included.
            raise DoudianError('unsupported_mode', '该任务只改标题、不含素材，不能用 upload 换图。')
        if not apply:
            return {'dry_run': True, 'product_id': self.manifest['product_id'], 'title': self.manifest['title'], 'mains': 5, 'details': len(self.manifest['details']), 'writes': ['标题', '5张方主图', '标准详情'], 'job_dir': str(self.job)}
        with Lock(self.lock_root / 'browser.lock'), Lock(self.job / 'job.lock'):
            self.reload()
            if self.state['stage'] in ('submitting', 'submitted', 'saved', 'rejected'):
                raise DoudianError('verify_required', '任务已进入提交阶段，请运行verify；不重复上传或发布。')
            self.guard_sibling_jobs()
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
                # A trusted-ready snapshot first: the resume-skip below must not
                # compare against a panel that has not rendered yet.
                current = self.editor.wait_details(self.manifest)
                expected = self.state.get(kind + '_urls')
                recorded = [resource_key(url) for url in current.get(kind) or []]
                if expected and recorded == [resource_key(url) for url in expected] and len(expected) == len(self.manifest[kind]):
                    continue
                # An uncertain upload may leave remote images with unknown provenance.
                # Clear that slot and re-upload the exact immutable local set; never trust count alone.
                urls = self.editor.replace(self.manifest, kind, lambda: self.save('editing', pending_upload=kind))
                self.save('editing', **{kind + '_urls': urls, 'pending_upload': None})
            self.editor.fill_title(self.manifest)
            current = self.editor.wait_details(self.manifest)
            compare_protected(self.baseline(), current)
            match_content(self.manifest, self.state, current)
            write_json(self.job / 'uploaded.json', current)
            self.save('uploaded', last_error=None)
            return {'stage': 'uploaded', 'job_dir': str(self.job), 'next': '确认预览后运行submit；尚未发布'}

    def submit(self, apply=False):
        if self.manifest.get('mode') == 'title_only':
            # A title-only job publishes inside `title apply`. Routing it through the
            # generic submit would re-arm the publish click for a task that never staged
            # images, and would bypass the title gates.
            raise DoudianError('unsupported_mode', '该任务只改标题，发布请用 title apply；结果未知时用 verify。')
        if not apply:
            return {'dry_run': True, 'stage': self.state['stage'], 'action': '发布已上传任务，并重开核验'}
        with Lock(self.lock_root / 'browser.lock'), Lock(self.job / 'job.lock'):
            self.reload()
            if self.state['stage'] == 'rejected':
                raise DoudianError('platform_rejected', '商品已被平台驳回，需先处理驳回原因；不重复发布。')
            if self.state['stage'] != 'uploaded':
                raise DoudianError('not_uploaded', '仅uploaded状态可发布；提交结果不明时先verify。')
            self.guard_sibling_jobs()
            current = self.editor.open(self.manifest)
            if current.get('success'):
                raise DoudianError('verify_required', '当前是提交成功页，请先核验已有任务。')
            # The pre-publish comparison needs a trusted-ready snapshot, not the
            # first frame after reopening (the live panel may still be rendering).
            current = self.editor.wait_details(self.manifest)
            compare_protected(self.baseline(), current)
            match_content(self.manifest, self.state, current)
            checked = self.editor.check(self.manifest)
            compare_protected(self.baseline(), checked)
            match_content(self.manifest, self.state, checked)
            # Persist before sending. Timeout/crash after this point must NEVER auto-republish.
            self.save('submitting', submitted_at=time.time(), submission_status='unknown')
            result = self.editor.publish(self.manifest)
            state = result.get('state')
            if state == 'accepted':
                self.save('submitted', submission_status='accepted', review_status='pending')
            elif state == 'rejected':
                # The submit was accepted, then the review failed. Recording this as a
                # failed click would reopen publishing; the distinction is load-bearing.
                self.save('rejected', submission_status='accepted', review_status='rejected',
                          rejection_reasons=result.get('rejection_reasons') or [],
                          rejection_observed_at=time.time())
                raise DoudianError('platform_rejected', '商品已被平台驳回：' + ('；'.join(result.get('rejection_reasons') or []) or '详见页面驳回原因'))
            elif state == 'validation_failed':
                # Only an explicit validation failure proves the submit was NOT accepted.
                self.save('uploaded', submission_status='not_submitted',
                          last_error='platform_validation', validation_errors=result.get('errors') or [])
                raise DoudianError('platform_validation', '平台未提交成功，请在页面检查必填项。')
            else:
                # Unknown must stay unknown: falling back to `uploaded` would reopen the
                # publish button for a submit that may well have been accepted.
                self.save('submitting', submission_status='unknown', last_error='submit_result_unknown')
                raise DoudianError('submit_result_unknown', '提交结果尚未确认，请运行verify核对；不要重复发布。')
            # A failed screenshot must not prevent the authoritative saved readback.
            try:
                self.editor.screenshot(self.job / 'submitted.png')
            except DoudianError as exc:
                self.save(screenshot_error=exc.code)
            return self._verify()

    def _images_settled(self, snapshot):
        # A trustworthy readback: every count agrees with the task and the live
        # preview panel is fully decoded, not merely present.
        details = len(self.manifest['details'])
        return (len(snapshot.get('mains', [])) == 5
                and len(snapshot.get('details', [])) == details
                and snapshot.get('detail_status') == 'ready'
                and snapshot.get('detail_declared') == details
                and snapshot.get('detail_cards') == details
                and snapshot.get('detail_slots') == details)

    def _verdict(self, current, scope, draft):
        """Record the readback verdict once identity and protected fields have passed."""
        try:
            match_content(self.manifest, self.state, current)
            compare_protected(self.baseline(), current)
        except DoudianError as exc:
            self.save('submitted', last_error=exc.code, verification_failed_at=time.time(),
                      content_scope=scope)
            raise
        if draft:
            # Read the draft, not the listing. Claiming `saved` here would be a false
            # positive, so the draft result is recorded as its own, weaker fact.
            self.save('submitted', draft_verified=True, content_scope='draft', verified_at=time.time(),
                      last_error='draft_scope_only')
            return {'stage': 'submitted', 'verified': False, 'draft_verified': True,
                    'job_dir': str(self.job),
                    'notice': '核验读到的是草稿而非线上版本；线上是否生效需以平台审核结果为准。'}
        self.save('saved', verified_at=time.time(), last_error=None, content_scope='unknown',
                  # A clean page with no rejection mark means the resubmission cleared it;
                  # carrying a historical `rejected` forward would misreport the live state.
                  review_status='pending')
        return {'stage': 'saved', 'verified': True, 'job_dir': str(self.job),
                'coverage': current.get('coverage'),
                'notice': '已重开编辑页核验；消费者端生效仍以平台审核为准。'}

    def _verify_title(self):
        # Title-only tasks never wait for the detail panel: on listings where the live
        # preview never renders, waiting here would make every verification time out.
        current = self.editor.open(self.manifest, fresh=True)
        write_json(self.job / 'readback.json', current)
        draft = bool(current.get('draft_loaded'))
        rejected = bool(current.get('rejected'))
        scope = 'draft' if draft else 'unknown'
        if rejected:
            self.save('rejected', content_scope=scope, verified_at=time.time(),
                      review_status='rejected',
                      rejection_reasons=current.get('rejection_reasons') or self.state.get('rejection_reasons') or [],
                      rejection_observed_at=time.time(), last_error='platform_rejected')
            raise DoudianError('platform_rejected', '商品处于驳回状态，改动未生效：' + ('；'.join(current.get('rejection_reasons') or []) or '详见页面驳回原因'))
        note = None
        try:
            scope_flag, note = compare_images_unchanged(self.baseline(), current)
            self.save(image_scope=scope_flag, image_scope_note=note)
        except DoudianError as exc:
            self.save('submitted', last_error=exc.code, verification_failed_at=time.time(),
                      content_scope=scope)
            raise
        result = self._verdict(current, scope, draft)
        return dict(result, image_scope=scope_flag,
                    image_scope_note=note,
                    notice=(result['notice'] + ('　' + note if note else '')))

    def _verify(self):
        if self.manifest.get('mode') == 'title_only':
            return self._verify_title()
        current = self.editor.open(self.manifest, fresh=True)
        # Give lazy detail images time to resolve their CDN addresses after scrolling.
        current = self.editor.bridge.wait(lambda: self.editor.read(self.manifest), self._images_settled, '重开后的商品图片尚未完整加载。', seconds=30)
        write_json(self.job / 'readback.json', current)
        # A match against a draft proves nothing about the live listing: the editor loads
        # the latest draft automatically, so new images plus identical protected fields are
        # exactly what a *rejected, unpublished* draft looks like. The scope of what was
        # read is therefore recorded before any success is claimed.
        draft = bool(current.get('draft_loaded'))
        rejected = bool(current.get('rejected'))
        scope = 'draft' if draft else 'unknown'
        if rejected:
            self.save('rejected', content_scope=scope, verified_at=time.time(),
                      review_status='rejected',
                      rejection_reasons=current.get('rejection_reasons') or self.state.get('rejection_reasons') or [],
                      rejection_observed_at=time.time(), last_error='platform_rejected')
            raise DoudianError('platform_rejected', '商品处于驳回状态，改动未生效：' + ('；'.join(current.get('rejection_reasons') or []) or '详见页面驳回原因'))
        return self._verdict(current, scope, draft)

    def verify(self):
        with Lock(self.lock_root / 'browser.lock'), Lock(self.job / 'job.lock'):
            self.reload()
            if self.state['stage'] not in ('submitting', 'submitted', 'saved', 'rejected'):
                raise DoudianError('not_submitted', '任务尚未进入提交阶段，不能宣称保存成功。')
            return self._verify()

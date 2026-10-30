import argparse
import json
import os
from pathlib import Path
import sys
import time

from . import __version__
from .bridge import Bridge
from .editor import Editor
from .errors import DoudianError
from .jobs import DATA_ROOT, Lock, load_job, prepare, read_json, resolve_product, write_json
from .workflow import Workflow


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DoudianError('invalid_arguments', message)


def parser():
    root = Parser(prog='doudian-auto', description='抖店本地上传：校验素材 → 上传预览 → 发布并重开核验。')
    root.add_argument('--json', action='store_true', help='输出稳定JSON结果')
    root.add_argument('--version', action='version', version=__version__)
    root.add_argument('--endpoint', default=os.environ.get('DOUDIAN_BRIDGE_URL', 'http://127.0.0.1:10086'), help='本机Kimi连接地址，或ego使用Ego原生通道')
    sub = root.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='检查本地服务、扩展与安装；不操作商品')
    resolve = sub.add_parser('resolve', help='编辑链接或商品ID转稳定标识')
    resolve.add_argument('product')
    products = sub.add_parser('products', help='读取当前商品列表可见链接')
    products.add_argument('--limit', type=int, default=20)
    read = sub.add_parser('read', help='读取现有商品编辑页快照')
    read.add_argument('--url', required=True)
    read.add_argument('--shop', required=True)
    read.add_argument('--out')
    prep = sub.add_parser('prepare', help='离线校验素材并建立可恢复任务')
    prep.add_argument('--assets', required=True)
    prep.add_argument('--title', required=True)
    prep.add_argument('--url', required=True)
    prep.add_argument('--shop', required=True)
    jobs = sub.add_parser('jobs', help='列出最近任务')
    jobs.add_argument('--limit', type=int, default=20)
    status = sub.add_parser('status', help='检查任务与素材版本')
    status.add_argument('job')
    for command, description in [('upload','替换标题、主图及详情，保留在编辑页预览'), ('submit','发布已上传任务并重开核验'), ('verify','重新读取保存结果；不发布')]:
        action = sub.add_parser(command, help=description)
        action.add_argument('job')
        if command != 'verify':
            action.add_argument('--apply', action='store_true', help='执行页面写入；省略时只预览计划')
            action.add_argument('--dry-run', action='store_true', help='只输出计划')
    browser = sub.add_parser('browser', help='只读页面检查入口')
    browser.add_argument('action', choices=['snapshot', 'inspect'])
    # Release a job's hold on the listing after a human has confirmed the page. Without
    # this a revision that published but cannot verify leaves the product blocked for
    # every later version, with no supported way out.
    abandon = sub.add_parser('abandon', help='人工确认页面后放弃该任务对商品的占用')
    abandon.add_argument('job')
    abandon.add_argument('--reason', required=True, help='放弃原因，会落盘留存')
    abandon.add_argument('--operator', default=os.environ.get('USERNAME') or 'unknown')
    abandon.add_argument('--confirm-unverified', action='store_true',
                         help='任务已被平台受理但未核验内容时，仍确认结案（会解除版本互斥）')
    browser.add_argument('--selector')
    title = sub.add_parser('title', help='标题本地校验与诊断；不生成文案、不联网')
    title_sub = title.add_subparsers(dest='title_command', required=True)
    title_check = title_sub.add_parser('check', help='只跑确定性规则（长度/空白/控制字符）')
    title_check.add_argument('--title', required=True)
    title_diagnose = title_sub.add_parser('diagnose', help='在确定性规则外，对照已确认事实给出提示')
    title_diagnose.add_argument('--title', required=True)
    title_diagnose.add_argument('--facts', help='已确认事实JSON；省略时只做无事实对照的诊断')
    title_apply = title_sub.add_parser('apply', help='只改标题：校验→填写检查→发布，不换图')
    title_apply.add_argument('--url', required=True, help='商品编辑链接或商品ID')
    title_apply.add_argument('--shop', required=True)
    title_apply.add_argument('--title', required=True)
    title_apply.add_argument('--facts', help='已确认事实JSON，用于诊断')
    title_apply.add_argument('--apply', action='store_true', help='真正写入并发布；省略时只校验')
    # Resume exists because a title job that stops mid-write leaves the listing blocked:
    # starting a new job instead would not be blocked either, it would just be a second
    # change layered on an unfinished one. Recovery therefore has to reuse the same job.
    title_resume = title_sub.add_parser('resume', help='续跑中断的只改标题任务，复用原任务与原基线')
    title_resume.add_argument('job')
    title_resume.add_argument('--apply', action='store_true', help='真正写入并发布；省略时只输出计划')
    # Abandon is the deliberate, recorded exit when a human has checked the page and the
    # hold must be released. Never automatic, never without a stated reason.
    title_abandon = title_sub.add_parser('abandon', help='人工确认页面后放弃该任务对商品的占用')
    title_abandon.add_argument('job')
    title_abandon.add_argument('--reason', required=True, help='放弃原因，会落盘留存')
    title_abandon.add_argument('--operator', default=os.environ.get('USERNAME') or 'unknown',
                               help='操作者，默认当前本机用户名')
    title_abandon.add_argument('--confirm-unverified', action='store_true',
                               help='任务已被平台受理但未核验内容时，仍确认结案（会解除版本互斥）')
    sub.add_parser('gui', help='打开中文桌面窗口')
    batch = sub.add_parser('batch', help='批量全套优化任务队列')
    batch_sub = batch.add_subparsers(dest='batch_command', required=True)
    batch_create = batch_sub.add_parser('create', help='从JSON商品清单创建持久化批次')
    batch_create.add_argument('--input', required=True, help='含products数组的JSON文件')
    batch_create.add_argument('--shop', help='清单缺少店铺名时统一指定')
    batch_status = batch_sub.add_parser('status', help='查看批次进度与卡点')
    batch_status.add_argument('batch_id', nargs='?')
    batch_preflight = batch_sub.add_parser('preflight', help='生成素材前只读检查官方必填属性，不上传或保存')
    batch_preflight.add_argument('--product-id', action='append', dest='product_ids', required=True,
                                 help='明确指定待预检商品，可重复提供，最多20件')
    batch_preflight.add_argument('--batch-id')
    batch_preflight.add_argument('--limit', type=int, default=20)
    batch_preflight.add_argument('--session', default='miaoshou-auto-batch-20261028',
                                 help='沿用当前任务浏览器会话，不另建替代空间')
    batch_preflight.add_argument('--report-dir', help='保存本次只读报告和脱敏快照的目录')
    batch_quarantine = batch_sub.add_parser('quarantine', help='隔离已有编辑或保存结果未知的商品')
    batch_quarantine.add_argument('--product-id', required=True)
    batch_quarantine.add_argument('--reason', required=True)
    batch_reconcile = batch_sub.add_parser('reconcile', help='导入已有操作证据并隔离，防止重复写入')
    batch_reconcile.add_argument('--evidence', required=True)
    batch_reconcile.add_argument('--shop')
    batch_resume = batch_sub.add_parser('resume', help='检查可续办任务；加--apply后继续未提交或只读核查任务')
    batch_resume.add_argument('--batch-id')
    batch_resume.add_argument('--limit', type=int, default=1)
    batch_resume.add_argument('--owner', default='codex-miaoshou-writer')
    batch_resume.add_argument('--session', default='miaoshou-auto-batch-20261028',
                              help='本批次专用浏览器任务组，便于隔离旧编辑页')
    batch_resume.add_argument('--apply', action='store_true', help='执行续办；未知保存结果只做双端只读核查')
    batch_run = batch_sub.add_parser('run', help='按持久化队列串行运行妙手写入并双端核验')
    batch_run.add_argument('--batch-id')
    batch_run.add_argument('--product-id', action='append', dest='product_ids',
                           help='只运行指定商品；可重复提供')
    batch_run.add_argument('--limit', type=int, default=1)
    batch_run.add_argument('--owner', default='codex-miaoshou-writer')
    batch_run.add_argument('--session', default='miaoshou-auto-batch-20261028',
                           help='本批次专用浏览器任务组，便于隔离旧编辑页')
    batch_run.add_argument('--apply', action='store_true', help='执行页面编辑、一次保存及双端读回')
    batch_run.add_argument('--acceptance', action='store_true',
                           help='首次3件真实验收；仅可配合3个明确的商品ID')
    batch_repair = batch_sub.add_parser('repair-title', help='受理后标题仍旧时，仅在双端证据及货架模式通过后补救一次')
    batch_repair.add_argument('--product-id', action='append', dest='product_ids', required=True,
                              help='只检查指定商品；可重复提供，最多10件')
    batch_repair.add_argument('--owner', default='codex-miaoshou-title-repair')
    batch_repair.add_argument('--session', default='miaoshou-title-repair-20261028',
                              help='本次标题补救专用浏览器任务组')
    batch_repair.add_argument('--apply', action='store_true', help='执行一次严格受限的标题补救')
    agent = sub.add_parser('agent', help='agent商品事实与素材交接')
    agent_sub = agent.add_subparsers(dest='agent_command', required=True)
    agent_next = agent_sub.add_parser('next', help='原子领取一件素材准备任务')
    agent_next.add_argument('--owner', required=True)
    agent_next.add_argument('--batch-id')
    agent_next.add_argument('--product-id', help='原子领取指定商品素材任务')
    agent_next.add_argument('--lease-seconds', type=int, default=900)
    agent_renew = agent_sub.add_parser('heartbeat', help='为仍在准备中的素材任务续租')
    agent_renew.add_argument('--task-id', required=True, type=int)
    agent_renew.add_argument('--owner', required=True)
    agent_renew.add_argument('--token', required=True)
    agent_renew.add_argument('--lease-seconds', type=int, default=900)
    agent_done = agent_sub.add_parser('complete', help='校验标题和图片哈希后交付素材')
    agent_done.add_argument('--task-id', required=True, type=int)
    agent_done.add_argument('--owner', required=True)
    agent_done.add_argument('--token', required=True)
    agent_done.add_argument('--artifacts', required=True)
    unlock = sub.add_parser('unlock', help='仅清除所属进程已结束的操作锁')
    unlock.add_argument('--job', help='同时清理此任务的job.lock')
    return root


def process_alive(pid):
    if pid <= 0:
        return True
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() != 87  # Access denied is NOT proof of exit.
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259
        finally:
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def unlock(job=None):
    paths = [DATA_ROOT / 'browser.lock']
    if job:
        paths.append(Path(job).resolve() / 'job.lock')
    removed = []
    for path in paths:
        if not path.exists():
            continue
        try:
            pid = int(path.read_text())
        except ValueError:
            raise DoudianError('invalid_lock', '锁内容异常，请人工检查，未删除。') from None
        if process_alive(pid):
            raise DoudianError('busy', f'锁所属进程 {pid} 仍在运行，未删除。')
        # Recheck bytes immediately before removing, rather than delete a replaced lock.
        if path.read_text().strip() == str(pid):
            path.unlink()
            removed.append(str(path))
    return {'removed': removed}


def run_title(args):
    """Offline title checking. Never touches a browser, never writes a job.

    Deterministic errors raise so the exit code is non-zero; warnings alone pass. The
    payload states plainly that a local pass is not platform approval.
    """
    from . import title as title_rules

    facts = None
    if getattr(args, 'facts', None):
        payload = read_json(Path(args.facts))
        facts = title_rules.TitleFacts(payload)
    if args.title_command == 'check':
        units, errors = title_rules.validate_title(args.title)
        if errors:
            raise DoudianError('invalid_title', '；'.join(errors))
        return {'ok': True, 'title': args.title, 'units': units,
                'limits': {'min': title_rules.MIN_UNITS, 'max': title_rules.MAX_UNITS},
                'next': '仅通过本地确定性规则；平台合规以发布检查为准。'}
    if args.title_command == 'apply':
        return run_title_apply(args)
    if args.title_command == 'resume':
        return run_title_resume(args)
    if args.title_command == 'abandon':
        return run_title_abandon(args)
    report = title_rules.diagnose_title(args.title, facts)
    if report['errors']:
        raise DoudianError('invalid_title', '；'.join(report['errors']))
    return report


# A title-only job that stopped before publishing blocks its product on purpose. Two ways
# out, both deliberate: continue the same job, or record that a human checked the page and
# the hold can be released.
_RESUMABLE_STAGES = ('prepared', 'editing', 'uploaded')

# Releasing a hold is only legitimate from a stage whose outcome is already known. Each
# stage is paired with the submission statuses that are consistent with it, so an
# unrecognised stage -- or a state this version never wrote -- fails closed instead of
# quietly freeing the product.
_ABANDONABLE_STAGES = {
    'prepared': (None, 'not_submitted'),
    'editing': (None, 'not_submitted'),
    # In the title-only flow `uploaded` only ever comes from a platform refusal
    # (validation_failed); nothing was uploaded and nothing was accepted. A revision job
    # reaches `uploaded` after a real upload and may carry no submission_status at all,
    # so `None` is accepted here -- requiring the title-only marker would refuse a normal
    # revision for a field it never sets.
    'uploaded': (None, 'not_submitted'),
    # A rejection is a known outcome: the platform accepted the submission and refused
    # it. The basis for releasing is that the result is known and a human closed the
    # task, not that nothing was ever submitted.
    #
    # `unknown` reaches this stage through verify after a timed-out submit: the page
    # says the submission was rejected, but whether it landed before that is
    # unrecorded. Refusing to close it would block the product forever with no way out,
    # so it is closable -- but only against verify's evidence, and the unknown is
    # preserved in the record instead of being rewritten into a tidier `accepted`.
    'rejected': ('accepted', 'unknown'),
    # `submitted` means the platform accepted the publish but the readback could not
    # confirm the content -- on this listing because the effective version was still the
    # previous one while the new version sat in review, so every readback compared a
    # staged version against a different live one and failed. The outcome (published) is
    # known even though the content could not be verified, and leaving it unclosable
    # blocks every future version of the listing. Closable, but the record must say the
    # content was never verified.
    'submitted': ('accepted', 'unknown'),
}


def _state_writer(job, state):
    def save(stage=None, **fields):
        state.update(fields)
        if stage:
            state['stage'] = stage
        state['updated_at'] = time.time()
        write_json(job / 'state.json', state)

    return save


def _baseline(editor, manifest):
    """Read the listing in its own fresh tab, and refuse an unresolved page.

    `fresh=True` issues `navigate(newTab=True)` -- a new tab, not a reload or a close of
    the old one. The default `open()` reuses any existing tab for this product, and such a
    tab can hold inputs that were typed but never submitted, with no draft banner to show
    it. Capturing that as "before" would make every later comparison meaningless, and a
    publish would then ship those edits along with the title.
    """
    snapshot = editor.open(manifest, fresh=True)
    if snapshot.get('success'):
        raise DoudianError('verify_required', '当前是提交成功页，请先核验已有任务。')
    if snapshot.get('rejected'):
        raise DoudianError('platform_rejected', '商品存在未处理的驳回，先处理驳回再改标题：' + (
            '；'.join(snapshot.get('rejection_reasons') or []) or '详见页面驳回原因'))
    if snapshot.get('draft_loaded'):
        raise DoudianError('draft_pending',
                           '该商品有未发布的草稿，草稿里的改动（价格、图片等）会随本次发布一起提交。'
                           '请先人工确认草稿归属并处理，再运行 title apply。')
    return snapshot


def _write_and_publish_title(job, manifest, state, save, editor, before, report):
    """Fill the title, re-run every gate, then click publish exactly once.

    Shared by `apply` and `resume` so the two paths cannot drift apart: a resumed run
    must pass the same identity, protected-field, image and final-title checks as a
    fresh one. Every failure below leaves the job in a blocking stage, because the page
    already carries the typed title.
    """
    from .workflow import compare_images_unchanged, compare_protected, match_content

    save('editing')
    editor.fill_title(manifest)
    try:
        checked = editor.check(manifest)
    except DoudianError as exc:
        # Keep the platform's own code: a transport failure is not a validation failure.
        save('editing', submission_status='not_submitted', last_error=exc.code)
        raise
    write_json(job / 'checked.json', checked)
    try:
        scope, note = compare_images_unchanged(before, checked)
        save('editing', image_scope=scope, image_scope_note=note)
        compare_protected(before, checked)
        # The title is compared against the task, not merely accepted as typed: it is
        # the one field this run is allowed to change, so it is the one field that must
        # be provably right on the page before publishing.
        match_content(manifest, state, checked)
    except DoudianError as exc:
        save('editing', submission_status='not_submitted', last_error=exc.code)
        raise
    write_json(job / 'title_record.json', dict(report, before_title=before.get('title'),
                                               checked_title=checked.get('title'),
                               recorded_at=time.time()))
    # Persist before sending: a timeout past this point must reach verify, not re-publish.
    save('submitting', submission_status='unknown', submitted_at=time.time())
    result = editor.publish(manifest)
    result_state = result.get('state')
    if result_state == 'accepted':
        save('submitted', submission_status='accepted', review_status='pending')
    elif result_state == 'rejected':
        save('rejected', submission_status='accepted', review_status='rejected',
             rejection_reasons=result.get('rejection_reasons') or [],
             rejection_observed_at=time.time())
        raise DoudianError('platform_rejected', '商品已被平台驳回：{0}。任务：{1}'.format(
            '；'.join(result.get('rejection_reasons') or []) or '详见页面驳回原因', job))
    elif result_state == 'validation_failed':
        save('uploaded', submission_status='not_submitted', last_error='platform_validation',
             validation_errors=result.get('errors') or [])
        raise DoudianError('platform_validation',
                           '平台未提交成功，请在页面检查必填项；修好后用 title resume 续跑同一任务。任务：{0}'.format(job))
    else:
        save('submitting', submission_status='unknown', last_error='submit_result_unknown')
        raise DoudianError('submit_result_unknown',
                           '提交结果尚未确认，请运行verify核对，不要重复发布。任务：{0}'.format(job))
    try:
        editor.screenshot(job / 'submitted.png')
    except DoudianError:
        pass
    return state


def _title_already_current(job, state, save, report, was_noop):
    """Read-only exit when a resumed job finds the target title already on the page.

    Two very different situations look identical here: the interrupted run's input
    survived on the page, or somebody else already completed the same change. Neither
    justifies publishing again -- a second submit starts another review cycle on top of
    an outcome nobody has read back. So nothing is written to the page, no `accepted` is
    claimed, and the job keeps its stage. A job that was recorded as a no-op stays one.
    """
    if was_noop:
        save('prepared', submission_status='not_submitted', last_error=None,
             title_already_current=True)
        stage = 'noop'
    else:
        save(last_error='title_already_current', title_already_current=True)
        stage = state['stage']
    return dict(report, dry_run=False, job_dir=str(job), stage=stage,
                submission_status=state.get('submission_status'),
                review_status=state.get('review_status'),
                title_already_current=True,
                notice='重开的编辑页读回已是目标标题，本次未填写、未提交。这可能是上次中断的'
                       '输入被保留，也可能是第三方已完成同一目标；请人工核对线上结果，'
                       '确认后用 title abandon 记录结论，不要重复发布。')


def run_title_apply(args):
    """Change only the title of a live listing, leaving images untouched.

    The revision workflow always replaces images, so a listing that only needs a title
    change had no supported path and was being driven by ad-hoc scripts -- scripts that
    wrote to the listing without a job record and without the cross-job guard. This
    records the change the same way the revision path does, and holds the same gates:
    identity confirmation before any write, a baseline snapshot, protected-field and
    final-title comparison after the platform check, and one publish click only.
    """
    from . import title as title_rules
    from .jobs import make_title_job
    from .workflow import compare_protected, guard_siblings

    facts_payload = None
    if getattr(args, 'facts', None):
        facts_payload = read_json(Path(args.facts))
    facts = title_rules.TitleFacts(facts_payload) if facts_payload else None
    report = title_rules.diagnose_title(args.title, facts)
    if report['errors']:
        raise DoudianError('invalid_title', '；'.join(report['errors']))
    if not args.apply:
        return dict(report, dry_run=True, writes=['标题'],
                    next='加 --apply 才会写入并发布；本步未连接浏览器。')

    product = resolve_product(args.url)
    product_id = product['product_id']
    edit_url = product.get('edit_url') or ('https://fxg.jinritemai.com/ffa/g/create?product_id=' + product_id)
    shop = args.shop.strip()
    if not shop:
        raise DoudianError('missing_identity', '需要店铺名称。')
    if facts and facts.product_id and facts.product_id != product_id:
        raise DoudianError('facts_mismatch', '事实文件属于商品 {0}，与本次目标 {1} 不一致，已停止。'.format(
            facts.product_id, product_id))

    jobs_root = DATA_ROOT / 'jobs'
    bridge = Bridge(args.endpoint)
    bridge.require_ready()
    editor = Editor(bridge)
    editor.bridge.session = 'doudian-auto-title-' + product_id
    with Lock(DATA_ROOT / 'browser.lock'):
        # Re-checked inside the lock. A sibling can enter a blocking stage while this run
        # waits for the lock, so a check performed before acquiring it proves nothing.
        guard_siblings(jobs_root, product_id)
        job, manifest = make_title_job(product_id, shop, edit_url, args.title, jobs_root)
        with Lock(job / 'job.lock'):
            state = read_json(job / 'state.json')
            save = _state_writer(job, state)
            if facts_payload is not None:
                write_json(job / 'facts.json', facts_payload)
            # Independently reopened tab: the default open() reuses whatever tab exists for
            # this product, and that tab can carry inputs typed but never submitted with no
            # draft banner to show it.
            before = _baseline(editor, manifest)
            # Comparing the baseline with itself only proves the capture was complete. It
            # says nothing about where the values came from -- the fresh tab does that.
            compare_protected(before, before)
            write_json(job / 'before.json', before)
            write_json(job / 'title_record.json', dict(report, before_title=before.get('title'),
                                                       recorded_at=time.time()))
            if before.get('title') == manifest['title']:
                # Meaningful only on a clean page. Under a draft, returning success here
                # would claim a change that never reached the listing.
                save('prepared', submission_status='not_submitted', noop=True,
                     noop_reason='title_already_current')
                return dict(report, dry_run=False, job_dir=str(job), stage='noop',
                            submission_status='not_submitted',
                            notice='独立重开的编辑页读回已是目标标题，本次未填写、未提交；'
                                   '这不代表消费者端已生效。')
            final = _write_and_publish_title(job, manifest, state, save, editor, before, report)
    scope = final.get('image_scope')
    notice = ('已提交，审核周期以平台为准；图片未改动。' if scope == 'verified_unchanged'
              else '已提交，审核周期以平台为准；本次未核验图片，不能声称图片未变。')
    return dict(report, dry_run=False, job_dir=str(job), stage=final['stage'],
                submission_status=final['submission_status'],
                review_status=final.get('review_status'),
                image_scope=scope,
                image_scope_note=final.get('image_scope_note'),
                notice=notice)


def run_title_resume(args):
    """Continue a title-only job that stopped before it was published.

    A job interrupted mid-write blocks its product on purpose, because the page may still
    carry the typed title. Starting a fresh job would not be blocked either -- it would just
    be a second change layered on an unfinished one, which is the precise bypass the guard
    exists to prevent. So recovery reuses the same job: same manifest, same baseline. The
    title is typed again from the immutable manifest, which means resume does not depend on
    whether the previous tab's unsubmitted input happened to survive.

    Jobs already in `submitting` or later are refused: once the publish click is out, only
    `verify` may decide what happened.
    """
    from .jobs import sha_file
    from .workflow import compare_protected, guard_siblings

    job = Path(args.job).resolve()
    if not (job / 'manifest.json').is_file():
        raise DoudianError('job_missing', '任务目录不存在或没有 manifest.json：{0}'.format(job))
    manifest = load_job(job)
    if manifest.get('mode') != 'title_only':
        raise DoudianError('unsupported_mode', '该任务不是只改标题任务，不能续跑。')
    if not (job / 'before.json').is_file():
        raise DoudianError('baseline_missing', '缺少原商品快照，不能续跑：请重新运行 title apply 建立新任务。')
    before = read_json(job / 'before.json')
    if before.get('product_id') != manifest['product_id']:
        raise DoudianError('baseline_mismatch', '原商品快照属于另一个商品，已停止。')
    record_path = job / 'title_record.json'
    report = read_json(record_path) if record_path.is_file() else {}

    stage = read_json(job / 'state.json').get('stage')
    if not args.apply:
        return {'dry_run': True, 'job_dir': str(job), 'stage': stage,
                'action': '续跑该只改标题任务：重新核对身份与保留字段后发布一次'}
    if stage not in _RESUMABLE_STAGES:
        raise DoudianError(
            'not_resumable',
            '阶段 {0} 不能续跑：已进入提交阶段的任务请先运行 verify，不要重新发布。'.format(stage))

    bridge = Bridge(args.endpoint)
    bridge.require_ready()
    editor = Editor(bridge)
    editor.bridge.session = 'doudian-auto-title-' + manifest['product_id']
    with Lock(DATA_ROOT / 'browser.lock'), Lock(job / 'job.lock'):
        state = read_json(job / 'state.json')
        save = _state_writer(job, state)
        # Re-read under the lock: another process may have moved the job on while we waited.
        stage = state.get('stage')
        # The stage alone is not enough: a stage this code recognises paired with a
        # submission status it could not have produced (e.g. `editing` + `accepted`)
        # means the state was written by something else, and resuming would publish on
        # top of an outcome nobody has read.
        if (stage not in _RESUMABLE_STAGES
                or state.get('submission_status') not in (None, 'not_submitted')):
            raise DoudianError(
                'not_resumable',
                '任务阶段 {0}（提交状态 {1}）不能续跑：已进入提交阶段或状态不一致的任务请先'
                '运行 verify，不要重新发布。'.format(stage, state.get('submission_status')))
        guard_siblings(DATA_ROOT / 'jobs', manifest['product_id'], exclude=job)
        # The stored baseline must still describe the listing as it stands now. Protected
        # fields are compared, and so is the title: the title is excluded from
        # `compare_protected` precisely because this task changes it, so without this
        # check a title written by someone else in the meantime would be overwritten
        # silently. Two live titles are legitimate -- the baseline (nothing happened
        # since) and the target (the interrupted run's input survived on the page). Any
        # third value means the world moved, and only a human can say whose change it is.
        current = _baseline(editor, manifest)
        compare_protected(before, current)
        live_title = current.get('title')
        if live_title == manifest['title']:
            # The target is already on the page. That is not evidence that this job's
            # publish happened, and it is not permission to publish again: a second
            # submit starts another review cycle on top of an outcome nobody has read.
            # Stop before any write and leave the outcome to a human.
            return _title_already_current(job, state, save, report,
                                          was_noop=bool(state.get('noop')))
        if live_title != before.get('title'):
            raise DoudianError(
                'baseline_stale',
                '线上标题既不是建基线时的标题，也不是本次目标标题（基线={0!r}，现在={1!r}，'
                '目标={2!r}）：期间有人改过标题，请先人工确认该改动归属，再决定续跑还是新建任务。'.format(
                    before.get('title'), live_title, manifest['title']))
        final = _write_and_publish_title(job, manifest, state, save, editor, before, report)
    scope = final.get('image_scope')
    notice = ('续跑完成：已提交，审核周期以平台为准；图片未改动。' if scope == 'verified_unchanged'
              else '续跑完成：已提交，审核周期以平台为准；本次未核验图片，不能声称图片未变。')
    return dict(report, dry_run=False, job_dir=str(job), stage=final['stage'],
                submission_status=final['submission_status'],
                review_status=final.get('review_status'),
                image_scope=scope,
                image_scope_note=final.get('image_scope_note'),
                notice=notice)


def run_title_abandon(args):
    """Release a job's hold on its product, with the reason recorded.

    Only reachable from a stage whose outcome is already known, and the stage is
    re-read under the same locks `resume` uses: an abandon that read `editing` before a
    concurrent resume published and moved the job to `submitting` would otherwise
    overwrite that unknown result with a safe-looking `abandoned` and free the product
    for a second publish. It writes the decision to `abandon.json` and parks the job in
    the terminal `abandoned` stage. It does not touch the listing: any draft or dirty
    tab it left behind still has to be handled by the human who confirmed the page.
    """
    from .jobs import sha_file

    reason = (getattr(args, 'reason', None) or '').strip()
    if not reason:
        raise DoudianError('reason_required', '必须写明放弃原因（--reason），说明人工核对了什么。')
    job = Path(args.job).resolve()
    if not (job / 'manifest.json').is_file():
        raise DoudianError('job_missing', '任务目录不存在或没有 manifest.json：{0}'.format(job))
    manifest = load_job(job)
    # `prepare` writes no mode key for revisions; `title_only` jobs set it explicitly.
    if manifest.get('mode') not in (None, 'revision', 'title_only'):
        raise DoudianError('unsupported_mode', '该任务类型不能放弃。')
    baseline = job / 'before.json'
    # Same lock order as resume, and the state is read again after both are held: the
    # check that matters is the one made against the state as it stands now.
    with Lock(DATA_ROOT / 'browser.lock'), Lock(job / 'job.lock'):
        state = read_json(job / 'state.json')
        stage = state.get('stage')
        submission_status = state.get('submission_status')
        if submission_status not in _ABANDONABLE_STAGES.get(stage, ()):
            raise DoudianError(
                'not_abandonable',
                '阶段 {0}（提交状态 {1}）不能放弃：发布结果未知或已终结的任务请运行 verify，'
                '只读核对后由人工结束。'.format(stage, submission_status))
        # Closing a job whose submit result was never confirmed is the one case where the
        # hold is released without a known outcome, so it needs evidence: verify must
        # have read the page back, and that read must be the rejection being closed.
        #
        # `submitted/accepted` is the second such case, and a weaker one: the platform
        # accepted the publish, so something is live or queued, but the content was never
        # read back. Releasing it is a deliberate act -- it removes the version mutex that
        # keeps a second job from publishing over an unresolved review -- so it needs an
        # explicit flag from the human doing it, not just a reason string.
        if stage == 'submitted' and not getattr(args, 'confirm_unverified', False):
            raise DoudianError(
                'confirmation_required',
                '该任务已被平台受理但没有通过内容核验。放弃它会解除「同一商品不得并发发布」'
                '的限制，可能让待审版本与后续版本同时存在。确认要在核验前结案，请加 '
                '--confirm-unverified 并写明原因。任务：{0}'.format(job))
        readback = None
        if submission_status == 'unknown':
            readback_path = job / 'readback.json'
            if not readback_path.is_file():
                raise DoudianError(
                    'verify_required',
                    '提交结果为 unknown，不能仅凭人工判断放弃：请先运行 verify 读回页面，'
                    '再带核验结果放弃。任务：{0}'.format(job))
            readback = read_json(readback_path)
            if not readback.get('rejected'):
                raise DoudianError(
                    'verify_required',
                    'verify 读回的不是驳回状态，不能结案一个提交结果未知的任务：请先人工'
                    '确认页面实际状态。任务：{0}'.format(job))
        record = {
            'record_kind': 'abandon',
            'abandoned_at': time.time(),
            'reason': reason,
            'declared_by': args.operator,
            'stage_before': stage,
            'submission_status_before': submission_status,
            'manifest_content_hash': manifest.get('content_hash'),
            'before_sha256': sha_file(baseline) if baseline.is_file() else None,
            'note': '仅落盘放弃记录，未修改线上商品；遗留草稿与脏页由人工处理。',
        }
        if readback is not None:
            # The unknown is kept, not rewritten: the record says which evidence the
            # human acted on and that the submit result was never confirmed.
            record['closed_despite_unknown_submission'] = True
            record['readback_sha256'] = sha_file(job / 'readback.json')
            record['readback_rejection_reasons'] = readback.get('rejection_reasons') or []
        if stage == 'submitted':
            # Say plainly what this closure does and does not establish. The publish was
            # accepted; the content never was verified, and any queued version on the
            # platform side is still unresolved from this job's point of view.
            record['content_verified'] = False
            record['closed_despite_unverified_content'] = True
            record['note'] = ('提交已被平台受理，但内容未核验即结案；平台侧待审版本是否终结'
                              '不由本记录证明，需人工跟进。线上商品未被本命令修改。')
        write_json(job / 'abandon.json', record)
        state.update({'stage': 'abandoned', 'abandoned_at': record['abandoned_at'],
                      'last_error': 'abandoned_by_operator', 'updated_at': time.time()})
        write_json(job / 'state.json', state)
    return {'job_dir': str(job), 'stage': 'abandoned', 'record': str(job / 'abandon.json'),
            'notice': '已记录放弃原因与基线哈希；线上商品未改动，遗留草稿请人工确认后处理。'}


def run(args):
    if args.command == 'gui':
        from .gui import launch
        launch(args.endpoint)
        return {'closed': True}
    if args.command == 'resolve':
        return resolve_product(args.product)
    if args.command == 'prepare':
        return prepare(args.assets, args.title, args.url, args.shop)
    if args.command == 'jobs':
        if not 1 <= args.limit <= 100:
            raise DoudianError('invalid_limit', 'limit需1至100。')
        jobs = sorted((DATA_ROOT / 'jobs').glob('*/state.json'), key=lambda p:p.stat().st_mtime, reverse=True)
        return {'items': [{'job_dir': str(p.parent), **read_json(p)} for p in jobs[:args.limit]], 'has_more':len(jobs) > args.limit}
    if args.command == 'status':
        data = load_job(args.job)
        return {'job_dir': str(Path(args.job).resolve()), 'product_id': data['product_id'], 'state':read_json(Path(args.job) / 'state.json')}
    if args.command == 'unlock':
        return unlock(args.job)
    if args.command == 'title':
        # Handled before the bridge is constructed: title work is offline and must
        # not require a browser session.
        return run_title(args)
    if args.command in ('batch', 'agent'):
        from . import batch as batch_queue
        if args.command == 'batch':
            if args.batch_command == 'create':
                return batch_queue.create_batch(args.input, shop=args.shop)
            if args.batch_command == 'status':
                return batch_queue.batch_status(args.batch_id)
            if args.batch_command == 'preflight':
                from .preflight import preflight_products
                return preflight_products(args.endpoint, product_ids=args.product_ids, batch_id=args.batch_id,
                                          limit=args.limit, session=args.session, report_dir=args.report_dir)
            if args.batch_command == 'quarantine':
                return batch_queue.quarantine_product(args.product_id, args.reason)
            if args.batch_command == 'reconcile':
                return batch_queue.reconcile_observation(args.evidence, shop=args.shop)
            if args.batch_command == 'repair-title':
                if not 1 <= len(set(args.product_ids)) <= 10:
                    raise DoudianError('title_repair_scope', '标题补救必须指定1至10个不同商品ID。')
                if not args.apply:
                    status = batch_queue.batch_status()
                    requested = set(args.product_ids)
                    candidates = [p for p in status['products'] if p['product_id'] in requested and
                                  batch_queue.title_repair_candidate(p)]
                    return {'dry_run': True, 'candidate_count': len(candidates),
                            'candidates': candidates,
                            'next': '加 --apply 后先双端核验图片及商业字段，再经标题专用预览只保存标题。'}
                return batch_queue.repair_accepted_title_mismatches(
                    args.endpoint, product_ids=args.product_ids, owner=args.owner, session=args.session)
            if args.batch_command == 'resume':
                recovered = batch_queue.recover_expired_claims()
                status = recovered['status']
                scoped_products = [p for p in status['products']
                                   if not args.batch_id or p.get('batch_id') == args.batch_id]
                resumable = [p for p in scoped_products if p['state'] in ('editing', 'uploaded') or
                             (p['state'] == 'blocked' and p.get('submission_state') == 'not_attempted' and
                              p.get('last_error') in batch_queue.PREWRITE_RECOVERABLE_ERRORS)]
                readback = [p for p in scoped_products if p['state'] == 'submitted' or
                            (p['state'] == 'blocked' and p['submission_state'] in ('unknown', 'accepted'))]
                result = {'recovered_agent_leases': recovered.get('recovered_agent_leases', 0),
                          'status': status, 'resumable_count': len(resumable),
                          'readback_only_count': len(readback)}
                if not args.apply:
                    return {**result, 'dry_run': True,
                            'next': '加 --apply 续办中断任务；保存结果未知的商品只读核查，不会再次保存。'}
                if not 1 <= args.limit <= 20:
                    raise DoudianError('invalid_limit', '续办限制为1至20件。')
                readiness = batch_queue.execution_readiness(args.endpoint)
                if not readiness.get('writer_ready'):
                    if not readback:
                        raise DoudianError('writer_not_accepted', readiness.get('reason') or '写入器尚未完成验收。')
                    product_ids = [p['product_id'] for p in readback[:args.limit]]
                    run = batch_queue.run_batch(args.endpoint, batch_id=args.batch_id,
                                                product_ids=product_ids, limit=len(product_ids),
                                                owner=args.owner, resume_only=True, readback_only=True,
                                                session=args.session)
                    return {**result, 'readback_only': True, 'run': run,
                            'status': batch_queue.batch_status(args.batch_id), 'writer_ready': False}
                run = batch_queue.run_batch(args.endpoint, batch_id=args.batch_id, limit=args.limit,
                                            owner=args.owner, resume_only=True, session=args.session)
                return {**result, 'run': run, 'status': batch_queue.batch_status(args.batch_id)}
            readiness = batch_queue.execution_readiness(args.endpoint)
            if not args.apply:
                status = batch_queue.batch_status(args.batch_id)
                ready = [p for p in status['products'] if p['state'] == 'ready' and
                         (not args.product_ids or p['product_id'] in args.product_ids)]
                resumable = [p for p in status['products'] if p['state'] in ('editing', 'uploaded', 'submitted')]
                readback = [p for p in status['products'] if p['state'] == 'blocked' and
                            p.get('submission_state') in ('unknown', 'accepted')]
                return {**readiness, 'dry_run': True, 'ready_count': len(ready),
                        'resumable_count': len(resumable), 'readback_only_count': len(readback),
                        'next': '加 --apply 执行；首次真实验收需要明确指定3个商品ID并加 --acceptance。'}
            if args.acceptance:
                ids = list(dict.fromkeys(args.product_ids or []))
                if len(ids) != 3:
                    raise DoudianError('acceptance_scope', '首次验收必须明确指定3个不同商品ID。')
            elif not readiness.get('writer_ready'):
                raise DoudianError('writer_not_accepted', readiness.get('reason') or '妙手写入器尚未通过验收。')
            result = batch_queue.run_batch(args.endpoint, batch_id=args.batch_id,
                                           product_ids=args.product_ids,
                                           limit=max(args.limit, 3) if args.acceptance else args.limit,
                                           owner=args.owner, session=args.session,
                                           acceptance_product_ids=args.product_ids if args.acceptance else None)
            verified = batch_queue.verified_acceptance_results(args.product_ids)
            if args.acceptance and len(verified) >= 3:
                result['writer_acceptance'] = batch_queue.mark_writer_acceptance(verified)
            return {**result, **batch_queue.execution_readiness(args.endpoint)}
        if args.agent_command == 'next':
            if not 60 <= args.lease_seconds <= 7200:
                raise DoudianError('invalid_lease', '租约必须为60至7200秒。')
            return batch_queue.claim_next(args.owner, batch_id=args.batch_id, product_id=args.product_id,
                                          lease_seconds=args.lease_seconds)
        if args.agent_command == 'heartbeat':
            return batch_queue.renew_agent_task(args.task_id, args.owner, args.token,
                                                lease_seconds=args.lease_seconds)
        return batch_queue.complete_agent_task(args.task_id, args.owner, args.token, args.artifacts)
    bridge = Bridge(args.endpoint)
    if args.command == 'doctor':
        status = bridge.status()
        ready = bool(status.get('running') and status.get('extension_connected') and not status.get('version_mismatch'))
        return {'version': __version__, 'offline_ready': True, 'browser_ready':ready, 'auth_source':'当前浏览器登录态；不提取凭据', 'bridge':status, 'next': '可上传预览' if ready else '先完成本地准备；连接Edge Kimi扩展后再上传', 'data_root':str(DATA_ROOT)}
    editor = Editor(bridge)
    if args.command in ('upload','submit','verify'):
        workflow = Workflow(args.job, editor)
        if args.command == 'verify':
            return workflow.verify()
        return getattr(workflow, args.command)(apply=args.apply and not args.dry_run)
    if args.command == 'abandon':
        return run_title_abandon(args)
    with Lock(DATA_ROOT / 'browser.lock'):
        bridge.require_ready()
        if args.command == 'products':
            if not 1 <= args.limit <= 100:
                raise DoudianError('invalid_limit', 'limit需1至100。')
            return editor.list_products(args.limit)
        if args.command == 'read':
            identity = {**resolve_product(args.url), 'shop':args.shop}
            if 'edit_url' not in identity:
                raise DoudianError('missing_url', 'read需要完整编辑链接。')
            editor.open(identity)
            snapshot = editor.wait_details(identity)
            if args.out:
                write_json(args.out, snapshot)
            return snapshot
        if args.command == 'browser':
            return editor.inspect(args.selector if args.action == 'inspect' else None)
    raise DoudianError('unknown_command', '未知命令。')


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    json_mode = '--json' in arguments
    try:
        args = parser().parse_args(arguments)
        data = run(args)
        result = {'ok':True, 'data':data}
        code = 0
    except DoudianError as exc:
        result = {'ok':False, 'error':{'code':exc.code, 'message':str(exc), 'waiting_human':exc.waiting}}
        code = 3 if exc.waiting else 1
    except (OSError, ValueError, KeyError, TypeError) as exc:
        # Do not include response bodies, credential-bearing URLs or arbitrary exception strings.
        result = {'ok':False, 'error':{'code':'local_error', 'message':f'本地文件或数据异常（{type(exc).__name__}）。', 'waiting_human':False}}
        code = 1
    if json_mode:
        print(json.dumps(result, ensure_ascii=False))
    elif result['ok']:
        print(json.dumps(result['data'], ensure_ascii=False, indent=2))
    else:
        print(result['error']['message'], file=sys.stderr)
    return code


if __name__ == '__main__':
    raise SystemExit(main())

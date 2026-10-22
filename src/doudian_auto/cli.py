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
    root.add_argument('--endpoint', default=os.environ.get('DOUDIAN_BRIDGE_URL', 'http://127.0.0.1:10086'), help='本机Kimi连接地址')
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
    sub.add_parser('gui', help='打开中文桌面窗口')
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
    report = title_rules.diagnose_title(args.title, facts)
    if report['errors']:
        raise DoudianError('invalid_title', '；'.join(report['errors']))
    return report


def run_title_apply(args):
    """Change only the title of a live listing, leaving images untouched.

    The revision workflow always replaces images, so a listing that only needs a title
    change had no supported path and was being driven by ad-hoc scripts. This records a
    job the same way so the change is reproducible and the cross-job guard sees it.
    """
    from . import title as title_rules
    from .workflow import guard_siblings

    facts = None
    if getattr(args, 'facts', None):
        facts = title_rules.TitleFacts(read_json(Path(args.facts)))
    report = title_rules.diagnose_title(args.title, facts)
    if report['errors']:
        raise DoudianError('invalid_title', '；'.join(report['errors']))
    if not args.apply:
        return dict(report, dry_run=True, writes=['标题'],
                    next='加 --apply 才会写入并发布；本步未连接浏览器。')

    product = resolve_product(args.url)
    product_id = product['product_id']
    edit_url = product.get('edit_url') or ('https://fxg.jinritemai.com/ffa/g/create?product_id=' + product_id)
    jobs_root = DATA_ROOT / 'jobs'
    guard_siblings(jobs_root, product_id)

    job = jobs_root / 'title-{0}-{1}'.format(product_id, time.strftime('%Y%m%d-%H%M%S'))
    manifest = {'product_id': product_id, 'shop': args.shop.strip(), 'edit_url': edit_url,
                'title': args.title, 'mode': 'title_only'}
    write_json(job / 'manifest.json', manifest)
    write_json(job / 'state.json', {'stage': 'prepared', 'updated_at': time.time()})

    bridge = Bridge(args.endpoint)
    bridge.require_ready()
    editor = Editor(bridge)
    editor.bridge.session = 'doudian-auto-title-' + product_id
    with Lock(DATA_ROOT / 'browser.lock'), Lock(job / 'job.lock'):
        before = editor.read(manifest)
        write_json(job / 'before.json', before)
        write_json(job / 'title_record.json', dict(report, before_title=before.get('title'),
                                                   recorded_at=time.time()))
        editor.fill_title(manifest)
        editor.check(manifest)
        # Persist before sending: a timeout past this point must reach verify, not re-publish.
        write_json(job / 'state.json', {'stage': 'submitting', 'submission_status': 'unknown',
                                        'updated_at': time.time()})
        result = editor.publish(manifest)
        state = result.get('state')
        if state == 'accepted':
            final = {'stage': 'submitted', 'submission_status': 'accepted',
                     'review_status': 'pending'}
        elif state == 'rejected':
            final = {'stage': 'rejected', 'submission_status': 'accepted',
                     'review_status': 'rejected',
                     'rejection_reasons': result.get('rejection_reasons') or []}
        elif state == 'validation_failed':
            final = {'stage': 'prepared', 'submission_status': 'not_submitted',
                     'platform_errors': result.get('errors') or []}
        else:
            # Unknown stays unknown; falling back to `prepared` would re-arm publishing.
            write_json(job / 'state.json', {'stage': 'submitting', 'submission_status': 'unknown',
                                            'last_error': 'submit_result_unknown',
                                            'updated_at': time.time()})
            raise DoudianError('submit_result_unknown', '提交结果尚未确认；请人工核对页面，勿重复发布。')
        write_json(job / 'state.json', dict(final, job_dir=str(job), updated_at=time.time()))
        try:
            editor.screenshot(job / 'submitted.png')
        except DoudianError:
            pass
    return dict(report, dry_run=False, job_dir=str(job), stage=final['stage'],
                submission_status=final['submission_status'],
                review_status=final.get('review_status'),
                notice='已提交，审核周期以平台为准；图片未改动。')


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

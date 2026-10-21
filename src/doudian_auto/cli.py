import argparse
import json
import os
from pathlib import Path
import sys

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

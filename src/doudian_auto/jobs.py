import hashlib
import json
import os
from pathlib import Path
import re
import time
import uuid
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from PIL import Image

from .errors import DoudianError
from .title import validate_title

DATA_ROOT = Path.home() / '.doudian-auto'
HOST = 'fxg.jinritemai.com'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temp, path)


def resolve_product(value):
    if re.fullmatch(r'\d{16,22}', value):
        return {'product_id': value}
    url = urlparse(value)
    params = parse_qs(url.query)
    pid = params.get('product_id', [''])[0]
    if url.scheme != 'https' or url.hostname != HOST or url.path.rstrip('/') != '/ffa/g/create' or not re.fullmatch(r'\d{16,22}', pid):
        raise DoudianError('invalid_product', '需要抖店现有商品的编辑链接或商品ID。')
    query = {k: params[k][0] for k in ('product_id', 'cid', 'entrance') if params.get(k)}
    return {'product_id': pid, 'edit_url': urlunparse(('https', HOST, url.path, '', urlencode(query), ''))}


def sha_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def content_hash(manifest):
    # A title-only task writes no assets, so its identity is the listing plus the exact
    # title. Hashing it with the asset keys would make every manifest comparison fail on
    # keys that by design do not exist.
    keys = ('product_id', 'edit_url', 'shop', 'title')
    if manifest.get('mode') != 'title_only':
        keys += ('mains', 'details')
    payload = {k: manifest[k] for k in keys}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def image_record(path, main):
    path = Path(path).resolve()
    if path.stat().st_size >= 5 * 1024 * 1024:
        raise DoudianError('image_size', f'{path.name} 超过5MB。')
    with Image.open(path) as image:
        image.load()
        width, height = image.size
        if image.format not in ('JPEG', 'PNG'):
            raise DoudianError('image_format', '图片仅支持JPEG/PNG。')
    if main and (width != height or width < 600):
        raise DoudianError('image_dimensions', f'{path.name} 必须是至少600像素的方图。')
    if not main and not 620 <= width <= 1290:
        raise DoudianError('image_dimensions', f'{path.name} 详情宽度必须620至1290像素。')
    return {'path': str(path), 'sha256': sha_file(path), 'width': width, 'height': height, 'bytes': path.stat().st_size}


def prepare(asset_dir, title, edit_url, shop, jobs_root=None):
    product = resolve_product(edit_url)
    if 'edit_url' not in product or not shop.strip():
        raise DoudianError('missing_identity', '需要编辑链接和店铺名称。')
    # One source of truth for the length rule; see title.py for the official bounds.
    _, title_errors = validate_title(title)
    if title_errors:
        raise DoudianError('invalid_title', '；'.join(title_errors))
    folder = Path(asset_dir).resolve()
    if not folder.is_dir():
        raise DoudianError('missing_assets', '素材目录不存在。')
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.jpg', '.jpeg', '.png'))
    mains = [p for p in files if re.match(r'main_0[1-5](?:_|\.)', p.name)]
    details = sorted([p for p in files if re.match(r'detail_\d+(?:_|\.)', p.name)], key=lambda p:int(re.match(r'detail_(\d+)',p.name)[1]))
    slots = [p.name[5:7] for p in mains]
    detail_slots = [int(re.match(r'detail_(\d+)',p.name)[1]) for p in details]
    if slots != ['01', '02', '03', '04', '05'] or not 1 <= len(details) <= 50 or detail_slots != list(range(1,len(details)+1)):
        raise DoudianError('missing_assets', '需要main_01至05各一张，及1至50张detail图片。')
    manifest = {'schema_version': 1, **product, 'shop': shop.strip(), 'title': title,
                'mains': [image_record(p, True) for p in mains], 'details': [image_record(p, False) for p in details]}
    all_hashes = [r['sha256'] for r in manifest['mains'] + manifest['details']]
    if len(all_hashes) != len(set(all_hashes)):
        raise DoudianError('duplicate_assets', '素材包含内容完全相同的图片。')
    manifest['content_hash'] = content_hash(manifest)
    manifest['job_id'] = product['product_id'] + '-' + manifest['content_hash'][:12]
    job = Path(jobs_root or DATA_ROOT / 'jobs').resolve() / manifest['job_id']
    if (job / 'manifest.json').exists():
        current = load_job(job)
        if current != manifest:
            raise DoudianError('job_conflict', '已有任务与当前素材不一致。')
    else:
        write_json(job / 'manifest.json', manifest)
        write_json(job / 'state.json', {'stage': 'prepared', 'content_hash': manifest['content_hash'], 'updated_at': time.time()})
    return {'job_dir': str(job), 'manifest': manifest, 'state': read_json(job / 'state.json')}


def make_title_job(product_id, shop, edit_url, title, jobs_root=None, attempts=20):
    """Create a unique, exclusively owned job directory for a title-only change.

    Unlike `prepare` these are not content addressed on purpose: every title change is
    its own record, so repeating the same title still produces a new directory. That
    means the name cannot rely on a timestamp alone -- two runs starting in the same
    second would otherwise share a directory and overwrite each other's manifest and
    state. A random suffix plus an exclusive `mkdir` makes that collision impossible.
    """
    root = Path(jobs_root or DATA_ROOT / 'jobs').resolve()
    for _ in range(attempts):
        name = 'title-{0}-{1}-{2}'.format(product_id, time.strftime('%Y%m%d-%H%M%S'), uuid.uuid4().hex[:6])
        job = root / name
        try:
            job.mkdir(parents=True)
        except FileExistsError:
            continue
        manifest = {'schema_version': 1, 'product_id': product_id, 'edit_url': edit_url,
                    'shop': shop, 'title': title, 'mode': 'title_only', 'job_id': name}
        manifest['content_hash'] = content_hash(manifest)
        write_json(job / 'manifest.json', manifest)
        write_json(job / 'state.json', {'stage': 'prepared', 'content_hash': manifest['content_hash'],
                                        'updated_at': time.time()})
        return job, manifest
    raise DoudianError('job_create_failed', '无法创建唯一的任务目录，请重试。')


def load_job(job):
    data = read_json(Path(job) / 'manifest.json')
    if data.get('content_hash') != content_hash(data):
        raise DoudianError('manifest_changed', '任务内容已改变，请重新准备任务。')
    if data.get('mode') == 'title_only':
        # Nothing local to re-hash: the task changed a title on the page, it did not
        # stage files. Status and verify must still work, or an unknown result would
        # have no recovery path at all.
        return data
    for record in data['mains'] + data['details']:
        if not Path(record['path']).is_file() or sha_file(record['path']) != record['sha256']:
            raise DoudianError('asset_changed', '素材已改变或丢失，请重新准备任务。')
    return data


def process_alive(pid):
    """PID 是否仍在运行。

    无法证明进程已退出时一律按“仍在运行”处理：宁可拒绝操作，也不误抢别人的锁。
    """
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


class Lock:
    """排他文件锁，锁文件记录持有者 PID。

    只有已确认退出的进程留下的锁才会被回收，进程仍在运行时绝不抢占。回收用改名
    而不是删除：改名是一次原子交接，不会被删除动作的外部守卫拦下，交接后旧锁文件
    里留着的仍是死进程 PID，下次再遇到照旧回收。
    """

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in (0, 1):
            try:
                self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                break
            except FileExistsError:
                if attempt:
                    raise DoudianError('busy',
                                       f'已有操作锁：{self.path}。确认旧进程结束后再使用unlock。') from None
                self._take_over()
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def _take_over(self):
        """接管一个属于已退出进程的锁。活锁与异常锁一律拒绝。"""
        try:
            raw = self.path.read_text(encoding='ascii').strip()
            pid = int(raw)
        except (OSError, ValueError):
            raise DoudianError('invalid_lock',
                               f'操作锁内容异常：{self.path}。请人工确认后用unlock清理。') from None
        if process_alive(pid):
            raise DoudianError('busy', f'已有操作锁：{self.path}（进程 {pid} 仍在运行）。')
        # 判活期间锁可能被别的进程换掉，换名前再读一次确认内容没变。
        try:
            current = self.path.read_text(encoding='ascii').strip()
        except FileNotFoundError:
            return
        if current != str(pid):
            raise DoudianError('busy', f'已有操作锁：{self.path}（内容已变化，未接管）。')
        stale = self.path.with_name(f'{self.path.name}.stale-{pid}-{uuid.uuid4().hex[:8]}')
        try:
            os.replace(self.path, stale)
        except OSError:
            # 改名被拒时退回删除；删除同样失败就保持现状，交给下一次运行再试。
            try:
                self.path.unlink()
            except (OSError, SystemExit):
                raise DoudianError('busy',
                                   f'已有操作锁：{self.path}（进程 {pid} 已退出，但接管失败）。') from None
            return
        try:
            stale.unlink()
        except (OSError, SystemExit):
            pass  # 旧锁文件清不掉也不影响接管结果。

    def __exit__(self, *_):
        os.close(self.fd)
        try:
            self.path.unlink()
        except (OSError, SystemExit):
            # 释放被外部守卫拦下时不能把整条流程打断：文件里留的是本进程 PID，
            # 下一次运行会按“进程已退出”把它回收掉。
            pass


class TransportLock:
    """OS 级咨询锁：进程退出时由系统自动释放。

    浏览器会话的传输锁每条命令都要进出一次，用文件锁意味着每条命令都要删除一次
    锁文件；既容易被外部删除守卫拦下，也会把被杀死的进程留下的死锁留给下一次运行。
    咨询锁由操作系统在进程退出时释放，没有这两种失败模式。
    """

    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.fd = os.open(self.path, os.O_RDWR | os.O_CREAT)
        try:
            if os.fstat(self.fd).st_size == 0:
                os.write(self.fd, b'0')
            if os.name == 'nt':
                import msvcrt
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            os.close(self.fd)
            raise DoudianError('busy',
                               f'已有操作锁：{self.path}（另一个进程正在使用同一浏览器会话）。') from exc
        return self

    def __exit__(self, *_):
        try:
            if os.name == 'nt':
                import msvcrt
                os.lseek(self.fd, 0, os.SEEK_SET)
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.fd, fcntl.LOCK_UN)
        except OSError:
            pass
        finally:
            os.close(self.fd)

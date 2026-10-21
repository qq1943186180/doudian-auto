import hashlib
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from PIL import Image

from .errors import DoudianError

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
    payload = {k: manifest[k] for k in ('product_id', 'edit_url', 'shop', 'title', 'mains', 'details')}
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
    units = sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in title)
    if not 15 <= units <= 60:
        raise DoudianError('invalid_title', '标题需15至60个平台字符。')
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


def load_job(job):
    data = read_json(Path(job) / 'manifest.json')
    if data.get('content_hash') != content_hash(data):
        raise DoudianError('manifest_changed', '任务内容已改变，请重新准备任务。')
    for record in data['mains'] + data['details']:
        if not Path(record['path']).is_file() or sha_file(record['path']) != record['sha256']:
            raise DoudianError('asset_changed', '素材已改变或丢失，请重新准备任务。')
    return data


class Lock:
    def __init__(self, path):
        self.path = Path(path)

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        except FileExistsError:
            raise DoudianError('busy', f'已有操作锁：{self.path}。确认旧进程结束后再使用unlock。') from None
        os.write(self.fd, str(os.getpid()).encode())
        return self

    def __exit__(self, *_):
        os.close(self.fd)
        self.path.unlink(missing_ok=True)

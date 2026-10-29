"""Read-only checks tying an observed CDN image to its immutable local asset."""

import hashlib
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

from PIL import Image

from .errors import DoudianError
from .workflow import is_permanent_material_url, is_temporary_upload_url


def verify_material_content(url, path, *, timeout=15):
    if not (is_temporary_upload_url(url) or is_permanent_material_url(url)):
        raise DoudianError('material_url_invalid', '图片地址不是已观察到的妙手暂存或抖店素材地址。')
    source = Path(path).read_bytes()
    source_hash = hashlib.sha256(source).hexdigest()
    try:
        with urlopen(url, timeout=timeout) as response:
            remote = response.read(10 * 1024 * 1024 + 1)
        if len(remote) > 10 * 1024 * 1024:
            raise ValueError('oversized_image')
    except (OSError, ValueError) as exc:
        raise DoudianError('material_read_timeout', '远端图片读取未完成，未确认该上传槽位。') from exc
    remote_hash = hashlib.sha256(remote).hexdigest()
    match = 'bytes' if source_hash == remote_hash else None
    if not match:
        try:
            with Image.open(BytesIO(source)) as left, Image.open(BytesIO(remote)) as right:
                match = 'pixels' if (left.size == right.size and
                    left.convert('RGBA').tobytes() == right.convert('RGBA').tobytes()) else None
        except (OSError, ValueError):
            pass
    if not match:
        raise DoudianError('material_content_mismatch', '远端图片内容与本地目标素材不一致，未确认槽位。')
    return {'source_sha256': source_hash, 'remote_sha256': remote_hash,
            'remote_url': url, 'match': match}

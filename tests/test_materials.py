from io import BytesIO

import pytest
from PIL import Image, PngImagePlugin

from doudian_auto import materials
from doudian_auto.errors import DoudianError

URL = 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-10-29/test/asset.png?dy'


def test_remote_image_must_match_local_bytes_or_exact_pixels(tmp_path, monkeypatch):
    path = tmp_path / 'image.png'
    image = Image.new('RGB', (600, 600), 'red')
    image.save(path)
    buffer = BytesIO()
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text('origin', 'remote re-encode')
    image.save(buffer, format='PNG', pnginfo=metadata)
    monkeypatch.setattr(materials, 'urlopen', lambda *a, **k: BytesIO(buffer.getvalue()))
    result = materials.verify_material_content(URL, path)
    assert result['match'] == 'pixels'
    assert result['source_sha256'] != result['remote_sha256']


def test_a_different_slot_image_is_rejected_even_when_dimensions_match(tmp_path, monkeypatch):
    path = tmp_path / 'image.png'
    Image.new('RGB', (600, 600), 'red').save(path)
    buffer = BytesIO()
    Image.new('RGB', (600, 600), 'blue').save(buffer, format='PNG')
    monkeypatch.setattr(materials, 'urlopen', lambda *a, **k: BytesIO(buffer.getvalue()))
    with pytest.raises(DoudianError) as rejected:
        materials.verify_material_content(URL, path)
    assert rejected.value.code == 'material_content_mismatch'


def test_unobserved_image_host_is_rejected_before_download(tmp_path, monkeypatch):
    monkeypatch.setattr(materials, 'urlopen', lambda *a, **k: pytest.fail('unexpected download'))
    with pytest.raises(DoudianError) as rejected:
        materials.verify_material_content('http://127.0.0.1/private', tmp_path/'missing.png')
    assert rejected.value.code == 'material_url_invalid'

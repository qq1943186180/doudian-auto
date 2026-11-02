import pytest

from doudian_auto import batch, materials
from doudian_auto.errors import DoudianError


@pytest.mark.parametrize('mode', ['qualified', 'missing', 'wrong_hash', 'missing_paths', 'bad_remote'])
def test_unchanged_qualified_image_requires_review_hash_local_and_remote_content(tmp_path, monkeypatch, mode):
    paths = []
    mappings = []
    urls = []
    for index in range(9):
        path = tmp_path / f'{index}.png'
        path.write_bytes(f'qualified-output-{index}'.encode())
        paths.append(str(path))
        key = f'png_m_{index:032x}_sx_12345_www600-600'
        url = f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/{key}'
        urls.append(url)
        mappings.append({'slot': f'mains:{index + 1}' if index < 5 else f'details:{index - 4}',
                         'source_sha256': batch._digest(path), 'remote_key': key,
                         'remote_url': url, 'asset_state': 'permanent', 'confirmed': True})
    baseline = {'mains': urls[:5], 'details': urls[5:] + ['tail']}
    after = {'mains': list(baseline['mains']), 'details': list(baseline['details'])}
    reuse = {x['slot']: x['source_sha256'] for x in mappings}
    if mode == 'missing':
        reuse = {}
    if mode == 'wrong_hash':
        reuse['mains:1'] = 'f' * 64
    checked = []
    def verify(url, path):
        checked.append((url, path))
        if mode == 'bad_remote':
            raise DoudianError('material_content_mismatch', 'remote differs')
        return {'byte_exact': True, 'sha256': batch._digest(path)}
    monkeypatch.setattr(materials, 'verify_material_content', verify)
    if mode == 'qualified':
        result = batch._finalize_target_mappings(baseline, after, after, mappings,
            asset_paths=paths, qualified_reuse=reuse)
        assert len(checked) == 9
        assert all(x['reused_qualified_existing'] is True and x['content_verification']['byte_exact'] for x in result)
    else:
        with pytest.raises(DoudianError) as error:
            batch._finalize_target_mappings(baseline, after, after, mappings,
                asset_paths=None if mode == 'missing_paths' else paths, qualified_reuse=reuse)
        assert error.value.code == ('material_content_mismatch' if mode == 'bad_remote' else 'final_asset_unchanged')

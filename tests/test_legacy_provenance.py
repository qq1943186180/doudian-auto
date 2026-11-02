import json
import os
import shutil

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.visual_review import file_hash
from test_batch import _product_set


@pytest.mark.parametrize('mode', ['valid', 'product', 'hash', 'slot', 'generator', 'new-image'])
def test_legacy_reuse_remains_bound_to_product_slot_and_original_bytes(tmp_path, mode):
    current = tmp_path / 'current'
    current.mkdir()
    pid, path = _product_set(current, 'immutable-v1')
    data = json.loads(path.read_text(encoding='utf-8'))
    old = tmp_path / 'historical'
    old.mkdir()
    original = old / 'main_1.png'
    shutil.copyfile(data['mains'][0], original)
    manifest = old / 'manifest.json'
    manifest.write_text(json.dumps({'productId': pid if mode != 'product' else 'other',
        'imageGeneration': {'status': 'used built-in ImageGen fallback'},
        'assets': [{'file': 'main_2.png' if mode == 'slot' else 'main_1.png',
                    'sha256': file_hash(original)}]}), encoding='utf-8')
    os.utime(manifest, (1, 1))
    item = data['visual_review']['items'][0]
    item.pop('prompt')
    item['generator'] = 'builtin-imagegen' if mode == 'new-image' else 'existing-qualified'
    item['legacy_provenance'] = {'exact_prompt_unavailable': True,
        'manifest': {'path': str(manifest), 'sha256': file_hash(manifest)},
        'asset': {'path': str(original), 'sha256': file_hash(original)}}
    if mode == 'hash':
        original.write_bytes(b'changed after review')
    if mode == 'generator':
        content = json.loads(manifest.read_text())
        content['imageGeneration'] = 'unknown paid api'
        manifest.write_text(json.dumps(content))
        os.utime(manifest, (1, 1))
        item['legacy_provenance']['manifest']['sha256'] = file_hash(manifest)
    path.write_text(json.dumps(data), encoding='utf-8')
    if mode == 'valid':
        assert batch.validate_agent_artifacts(path, pid)['visual_review']['approved']
    else:
        with pytest.raises(DoudianError) as error:
            batch.validate_agent_artifacts(path, pid)
        assert error.value.code == 'legacy_image_provenance'

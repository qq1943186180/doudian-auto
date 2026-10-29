"""Bind an agent's visual judgement to exact product references and image bytes.

This is an evidence gate, not an automatic claim that a model recognized the item.
The reviewer must actually inspect every source and output before filling it.
"""

import hashlib
import json
import re
from pathlib import Path

from .errors import DoudianError


CHECKS = ('identity', 'color', 'quantity', 'printing', 'specification')
GENERATORS = {'builtin-imagegen', 'existing-qualified'}


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def facts_hash(facts):
    return hashlib.sha256(json.dumps(facts, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def _bound_file(record, base, code):
    if not isinstance(record, dict) or not record.get('path'):
        raise DoudianError(code, '缺少可追溯的本地原始资料。')
    path = Path(record['path'])
    path = (base / path).resolve() if not path.is_absolute() else path.resolve()
    expected = record.get('sha256')
    if not re.fullmatch(r'[0-9a-f]{64}', str(expected or '')) or not path.is_file():
        raise DoudianError(code, '原始资料或其SHA256缺失，不能确认图片身份。')
    if file_hash(path) != expected:
        raise DoudianError(code, '原始资料在目视检查后发生变化，需重新检查。')
    return path


def validate_visual_review(data, assets, *, manifest_path, product_id, shop=None):
    review = data.get('visual_review')
    if not isinstance(review, dict) or review.get('schema_version') != 1:
        raise DoudianError('visual_review_missing', '每张新图须完成商品身份、颜色、数量、印字和规格的逐项目视检查。')
    version = data.get('target_version')
    if (not isinstance(version, str) or not version.strip() or
            review.get('product_id') != str(product_id) or review.get('target_version') != version):
        raise DoudianError('visual_review_binding', '目视检查必须绑定当前商品和不可变目标版本。')
    if not isinstance(review.get('reviewer'), str) or not review['reviewer'].strip():
        raise DoudianError('visual_review_binding', '目视检查缺少执行agent署名。')
    base = Path(manifest_path).resolve().parent
    source_path = _bound_file(review.get('source_snapshot'), base, 'source_snapshot_changed')
    source = json.loads(source_path.read_text(encoding='utf-8'))
    if (not isinstance(source, dict) or source.get('product_id') != str(product_id)
            or (shop and source.get('shop') != shop)):
        raise DoudianError('visual_review_binding', '原商品资料的商品ID或店铺不匹配。')
    facts = source.get('facts')
    if (not isinstance(facts, dict) or any(not facts.get(key) for key in CHECKS)
            or review.get('facts_sha256') != facts_hash(facts)):
        raise DoudianError('visual_review_facts', '五类商品事实不完整或与目视检查所用版本不一致。')
    refs = source.get('references')
    if not isinstance(refs, list) or not refs:
        raise DoudianError('visual_review_references', '目视检查必须有原商品参考图片。')
    reference_hashes = set()
    for ref in refs:
        _bound_file(ref, source_path.parent, 'reference_image_changed')
        reference_hashes.add(ref['sha256'])
    items = review.get('items')
    expected = {(item['kind'], item['slot']): item for item in assets}
    if (not isinstance(items, list) or len(items) != len(expected) or
            any(not isinstance(item, dict) for item in items)):
        raise DoudianError('visual_review_slots', '目视检查须完整覆盖5张主图和4张详情，不能仅填整套通过。')
    reviewed = set()
    failed = []
    for item in items:
        key = (item.get('kind'), item.get('slot'))
        asset = expected.get(key)
        if asset is None or key in reviewed or item.get('asset_sha256') != asset['sha256']:
            raise DoudianError('visual_review_binding', '目视检查的槽位或图片哈希与目标素材不一致。')
        reviewed.add(key)
        if asset['sha256'] in reference_hashes:
            raise DoudianError('original_asset_not_revision', '原图测试素材不能计为全套换新图片。')
        if item.get('generator') not in GENERATORS:
            raise DoudianError('image_provenance_missing', '新图缺少内置生图或既有合格素材的来源记录。')
        _bound_file(item.get('prompt'), base, 'image_prompt_changed')
        checks = item.get('checks')
        if not isinstance(checks, dict) or set(checks) != set(CHECKS):
            raise DoudianError('visual_review_incomplete', '每张图必须逐项检查身份、颜色、数量、印字和规格。')
        failures = []
        for name in CHECKS:
            check = checks[name]
            if not isinstance(check, dict) or check.get('status') not in ('pass', 'fail'):
                raise DoudianError('visual_review_incomplete', '目视检查中存在未确定的项目。')
            observed = check.get('observed')
            if (not isinstance(observed, str) or not observed.strip() or
                    observed.strip().lower() in {'pass', 'ok', '通过', '一致', 'unknown', '待检查'}):
                raise DoudianError('visual_review_incomplete', '目视检查须写明实际看到的商品细节。')
            evidence = check.get('reference_sha256')
            if (not isinstance(evidence, list) or not evidence or
                    any(value not in reference_hashes for value in evidence)):
                raise DoudianError('visual_review_references', '检查项目未引用当前原商品图片。')
            if check['status'] == 'fail':
                failures.append(name)
        if failures:
            failed.append({'kind': key[0], 'slot': key[1], 'sha256': asset['sha256'], 'checks': failures})
    return {'approved': not failed, 'reviewer': review['reviewer'],
            'source_snapshot_sha256': review['source_snapshot']['sha256'],
            'facts_sha256': review['facts_sha256'], 'failed_slots': failed,
            'review_sha256': facts_hash(review)}

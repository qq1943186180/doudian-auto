"""Offline checks for Douyin product assets and captured editor snapshots."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def title_units(title):
    return sum(2 if unicodedata.east_asian_width(c) in 'WF' else 1 for c in title)

def asset_check(args):
    from PIL import Image
    root = Path(args.directory).resolve()
    if not root.is_dir():
        raise ValueError('Asset directory does not exist')
    records, errors, main_slots, hashes = [], [], {}, {}
    files = sorted(p for p in root.iterdir() if p.is_file() and p.suffix.lower() in ('.jpg', '.jpeg', '.png') and p.name.startswith(('main_', 'detail_')))
    main_count = detail_count = 0
    for p in files:
        raw = p.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        with Image.open(p) as im:
            im.load()
            width, height = im.size
        main = p.name.startswith('main_')
        if main:
            main_count += 1
            match = re.match(r'main_(0[1-5])(?:_|\.)', p.name)
            if not match:
                errors.append(f'{p.name}: invalid main slot')
            elif match[1] in main_slots:
                errors.append(f'{p.name}: duplicate main slot')
            else:
                main_slots[match[1]] = p.name
            if width != height or min(width, height) < 600:
                errors.append(f'{p.name}: main must be square and at least 600px')
        else:
            detail_count += 1
            if not 620 <= width <= 1290:
                errors.append(f'{p.name}: detail width must be 620..1290px')
        if len(raw) >= 5 * 1024 * 1024:
            errors.append(f'{p.name}: file must be below 5MB')
        if digest in hashes:
            errors.append(f'{p.name}: identical content to {hashes[digest]}')
        hashes[digest] = p.name
        records.append({'name': p.name, 'width': width, 'height': height, 'bytes': len(raw), 'sha256': digest})
    if main_count != 5 or len(main_slots) != 5:
        errors.append('Exactly five distinct main slots 01..05 are required')
    if detail_count == 0:
        errors.append('No detail images found')
    manifest = root / '素材校验.json'
    if manifest.exists():
        expected = read_json(manifest)
        if not isinstance(expected, list):
            errors.append('Asset manifest must be a list')
        else:
            actual = {r['name']: r for r in records}
            for record in expected:
                name = record.get('name') or record.get('file')
                if name not in actual or record.get('sha256') != actual[name]['sha256']:
                    errors.append(f'{name}: missing file or manifest hash mismatch')
    units = title_units(args.title) if args.title else None
    if units is not None and not 15 <= units <= 60:
        errors.append('Title must contain 15..60 platform character units')
    return {'ok': not errors, 'mode': 'offline_assets', 'directory': str(root), 'title_units': units, 'main_count': main_count, 'detail_count': detail_count, 'assets': records, 'errors': errors, 'requires_visual_review': True}

def snapshot_compare(args):
    before, after = read_json(args.before), read_json(args.after)
    old = {s['id']: s for s in before.get('sections', [])}
    new = {s['id']: s for s in after.get('sections', [])}
    errors, comparisons = [], []
    for sid in ['goodsEditScrollContainer-价格库存', 'goodsEditScrollContainer-服务与履约']:
        if sid not in old or sid not in new:
            errors.append(f'{sid}: missing snapshot section')
            continue
        inputs_equal = old[sid].get('inputs') == new[sid].get('inputs')
        if 'inputs' not in old[sid] or 'inputs' not in new[sid] or not old[sid]['inputs']:
            inputs_equal = False
        old_ids = sorted(set(re.findall(r'\b\d{16}\b', old[sid].get('text', ''))))
        new_ids = sorted(set(re.findall(r'\b\d{16}\b', new[sid].get('text', ''))))
        comparisons.append({'section': sid, 'captured_inputs_equal': inputs_equal, 'captured_sku_ids_equal': old_ids == new_ids, 'captured_sku_count': len(old_ids)})
        if not inputs_equal or old_ids != new_ids:
            errors.append(f'{sid}: captured commercial fields changed or incomplete')
    images = [i for s in after.get('sections', []) for i in s.get('images', [])]
    def urls(field):
        return list(dict.fromkeys(i.get('src') for i in images if i.get('field') == field and i.get('w', 0) >= 600 and i.get('src', '').startswith('https://') and 'ecom-shop-material/' in i.get('src', '')))
    mains, details = urls('主图'), urls('商品详情')
    if len(mains) != 5:
        errors.append('Saved snapshot must have five distinct remote main images')
    if len(details) != args.details:
        errors.append(f'Saved snapshot detail count differs from expected {args.details}')
    if not after.get('title') or (args.title is not None and after['title'] != args.title):
        errors.append('Saved title missing or differs from expected title')
    return {'ok': not errors, 'mode': 'captured_snapshot_compare', 'title': after.get('title'), 'main_count': len(mains), 'detail_count': len(details), 'comparisons': comparisons, 'errors': errors, 'coverage': 'Captured input values and SKU IDs only. Checkbox/switch state must be captured separately; virtualized or omitted SKU rows are not verified. This does not prove submission or consumer-side approval.'}

def main():
    parser = argparse.ArgumentParser(description='Offline Douyin product asset checks and captured-field comparisons; no login, upload or shop changes.')
    sub = parser.add_subparsers(dest='mode', required=True)
    asset = sub.add_parser('assets')
    asset.add_argument('directory')
    asset.add_argument('--title')
    compare = sub.add_parser('compare')
    compare.add_argument('before')
    compare.add_argument('after')
    compare.add_argument('--title')
    compare.add_argument('--details', type=int, required=True)
    for child in (asset, compare):
        child.add_argument('--out')
    args = parser.parse_args()
    try:
        result = asset_check(args) if args.mode == 'assets' else snapshot_compare(args)
    except Exception as exc:
        result = {'ok': False, 'errors': [f'{type(exc).__name__}: {exc}']}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.out:
        path = Path(args.out).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered + '\n', encoding='utf-8')
    print(rendered)
    return 0 if result['ok'] else 1

if __name__ == '__main__':
    sys.exit(main())

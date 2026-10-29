"""Full SKU evidence from a fresh response emitted by the official editor UI."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qs, urlparse

from .errors import DoudianError
from .workflow import resource_key


def _require(condition, message='官方SKU字段缺失或类型变化，未确认全部规格。'):
    if not condition:
        raise DoudianError('official_sku_incomplete', message)


def _id(value):
    _require(isinstance(value, (str, int)) and not isinstance(value, bool))
    result = str(value)
    _require(result.isdigit() and int(result) > 0)
    return result


def _price(value):
    _require(isinstance(value, (str, int, float)) and not isinstance(value, bool))
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise DoudianError('official_sku_incomplete', 'SKU价格不是有效数值。') from exc
    _require(amount.is_finite() and amount >= 0)
    return format(amount.normalize(), 'f')


def _stock(value):
    _require(type(value) is int and value >= 0)
    return value


def _normalize(value):
    if isinstance(value, dict):
        return {key: _normalize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, str) and value.startswith('https://') and 'ecom-shop-material/' in value:
        return resource_key(value)
    return value


def parse_official_skus(response, *, product_id):
    _require(isinstance(response, dict) and response.get('status') == 200 and response.get('completed') is True)
    _require(response.get('url') == 'https://fxg.jinritemai.com/product/tproduct/getSchema')
    _require(bool(response.get('requestId')))
    page = urlparse(str(response.get('page_url') or ''))
    _require(page.hostname == 'fxg.jinritemai.com' and page.path == '/ffa/g/create' and
             parse_qs(page.query).get('product_id') == [str(product_id)])
    try:
        data = json.loads(response['body'])
        context, model = data['data']['context'], data['data']['model']
        rows, specs = model['sku_detail']['value'], model['spec_detail']['value']
    except (ValueError, KeyError, TypeError) as exc:
        raise DoudianError('official_sku_incomplete', '未读到官方完整SKU响应。') from exc
    _require(data.get('errno') == 0 and data.get('code') == 0)
    _require(_id(context.get('product_id')) == str(product_id), '官方SKU响应商品ID不匹配。')
    shop_id = _id(context.get('shop_id'))
    _require(context.get('operation_type') == 'normal' and context.get('model_type') == 'normal')
    _require(isinstance(rows, list) and len(rows) > 0 and isinstance(specs, list))
    groups = []
    seen = set()
    for group in specs:
        _require(isinstance(group, dict) and isinstance(group.get('name'), str))
        values = group.get('spec_values')
        _require(isinstance(values, list) and len(values) > 0)
        ids = []
        for value in values:
            _require(isinstance(value, dict) and isinstance(value.get('name'), str))
            identity = _id(value.get('id'))
            _require(identity not in seen)
            seen.add(identity)
            ids.append(identity)
        groups.append(set(ids))
    normalized_rows = []
    required = {'sku_id', 'id', 'price', 'stock_info', 'step_stock_info', 'spec_detail_ids', 'code', 'sku_status'}
    seen_skus = set()
    for row in rows:
        _require(isinstance(row, dict) and required.issubset(row))
        sku_id = _id(row['sku_id'])
        _require(sku_id == _id(row['id']) and sku_id not in seen_skus)
        seen_skus.add(sku_id)
        ids = row['spec_detail_ids']
        _require(isinstance(ids, list) and len(ids) == len(groups))
        ids = [_id(value) for value in ids]
        _require(all(identity in group for identity, group in zip(ids, groups)))
        _require(isinstance(row['stock_info'], dict) and isinstance(row['step_stock_info'], dict))
        _require(type(row['sku_status']) is bool and isinstance(row['code'], str))
        normalized_rows.append({'sku_id': sku_id, 'spec_ids': ids, 'price': _price(row['price']),
            'stock': _stock(row['stock_info'].get('stock_num')),
            'step_stock': _stock(row['step_stock_info'].get('stock_num')),
            'code': row['code'], 'enabled': row['sku_status']})
    payload = {'rows': sorted(normalized_rows, key=lambda x: x['sku_id']),
               'raw_rows': _normalize(rows), 'specs': _normalize(specs)}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return {'complete': True, 'product_id': str(product_id), 'shop_id': shop_id,
            'source': 'doudian:observed-getSchema', 'request_id': response['requestId'],
            'count': len(rows), **payload, 'sha256': hashlib.sha256(encoded.encode()).hexdigest()}


def verify_miaoshou_skus(miaoshou, evidence):
    _validate_evidence(evidence)
    _require(str(miaoshou.get('product_id')) == evidence.get('product_id'))
    rows = miaoshou.get('protected', {}).get('specPrices')
    _require(isinstance(rows, list) and len(rows) == evidence.get('count'))
    result = []
    required = {'skuId', 'specDetailIds', 'price', 'stockNum', 'stepStockNum', 'code', 'skuStatus'}
    for row in rows:
        _require(isinstance(row, dict) and required.issubset(row))
        _require(isinstance(row['specDetailIds'], list) and type(row['skuStatus']) is bool and isinstance(row['code'], str))
        result.append({'sku_id': _id(row['skuId']), 'spec_ids': [_id(x) for x in row['specDetailIds']],
            'price': _price(row['price']), 'stock': _stock(row['stockNum']),
            'step_stock': _stock(row['stepStockNum']), 'code': row['code'], 'enabled': row['skuStatus']})
    if sorted(result, key=lambda x: x['sku_id']) != evidence['rows']:
        raise DoudianError('sku_sources_disagree', '妙手与抖店全部SKU的ID、规格、价格或库存不一致。')
    return {'complete': True, 'count': len(rows), 'official_sha256': evidence['sha256']}


def compare_official_skus(before, after):
    _validate_evidence(before)
    _validate_evidence(after)
    for key in ('product_id', 'shop_id', 'count', 'rows', 'raw_rows', 'specs', 'sha256'):
        if before.get(key) != after.get(key):
            raise DoudianError('commercial_changed', '官方完整SKU数据与编辑前不一致。')


def _validate_evidence(evidence):
    keys = {'product_id', 'shop_id', 'count', 'rows', 'raw_rows', 'specs', 'sha256'}
    _require(isinstance(evidence, dict) and evidence.get('complete') is True and keys.issubset(evidence))
    _require(type(evidence['count']) is int and evidence['count'] > 0 and
             isinstance(evidence['rows'], list) and len(evidence['rows']) == evidence['count'] and
             isinstance(evidence['raw_rows'], list) and len(evidence['raw_rows']) == evidence['count'] and
             isinstance(evidence['specs'], list))
    payload = {key: evidence[key] for key in ('rows', 'raw_rows', 'specs')}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    _require(evidence['sha256'] == hashlib.sha256(encoded.encode()).hexdigest())

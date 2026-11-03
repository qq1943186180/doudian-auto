"""Independently observed official UI merchant codes, bound to a fresh API reference.

This collector does not fill an API field or assert that the entire SKU response
is complete. Its caller must validate every API field and the returned UI proof.
"""

from __future__ import annotations

import hashlib
from importlib.resources import files
import json
import math
import re
from time import monotonic, sleep, time
from urllib.parse import parse_qs, urlparse

from .errors import DoudianError, WaitingHuman


SOURCE = 'official_editor_ui:merchant_code'
_BINDING = ('product_id', 'shop', 'api_request_id', 'api_body_sha256', 'page_url')


def _require(condition, code='official_sku_code_evidence_invalid',
             message='官方商家编码UI证据缺失、存在歧义或结构变化。'):
    if not condition:
        raise DoudianError(code, message)


def _reference(reference, identity=None):
    _require(isinstance(reference, dict))
    _require(all(isinstance(reference.get(key), str) and reference[key].strip() for key in _BINDING))
    _require(bool(re.fullmatch(r'[0-9a-f]{64}', reference['api_body_sha256'])))
    page = urlparse(reference['page_url'])
    _require(page.scheme == 'https' and page.hostname == 'fxg.jinritemai.com' and
             page.path == '/ffa/g/create' and not page.username and not page.password and
             parse_qs(page.query).get('product_id') == [reference['product_id']])
    ids = reference.get('expected_sku_ids')
    _require(isinstance(ids, list) and len(ids) > 0 and
             all(isinstance(sku, str) and re.fullmatch(r'[0-9]{16}', sku) for sku in ids) and
             len(ids) == len(set(ids)))
    if identity is not None:
        _require(isinstance(identity, dict) and all(identity.get(key) == reference[key]
                 for key in ('product_id', 'shop')), 'wrong_identity', 'UI编码补证与商品或店铺不匹配。')
    return set(ids)


def _stable_rows(rows):
    return sorted(({'sku_id': row['sku_id'], 'code': row['code'],
                    'observed': True, 'input_count': 1} for row in rows), key=lambda row: row['sku_id'])


def code_rows_sha256(rows):
    """Hash only stable observed values; request IDs and times are capture metadata."""
    payload = {'source': SOURCE, 'rows': _stable_rows(rows)}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':'))
    return hashlib.sha256(encoded.encode()).hexdigest()


def validate_sku_code_evidence(evidence, reference):
    """Return actual observed strings only after full identity/coverage validation."""
    expected = _reference(reference)
    _require(isinstance(evidence, dict) and evidence.get('schema_version') == 1 and
             evidence.get('source') == SOURCE and evidence.get('complete') is True and
             evidence.get('shop_confirmed') is True and evidence.get('code_column') == '商家编码')
    _require(all(evidence.get(key) == reference[key] for key in ('product_id', 'shop', 'page_url')),
             'wrong_identity', '官方UI商家编码证据属于其他商品、店铺或页面。')
    _require(all(evidence.get(key) == reference[key] for key in ('api_request_id', 'api_body_sha256')),
             'official_sku_code_stale', '官方UI编码证据不属于本次新鲜SKU请求。')
    nav = evidence.get('navigation_id')
    _require(type(nav) in (int, float) and math.isfinite(nav) and nav > 0)
    _require(type(evidence.get('observed_at')) in (int, float) and
             math.isfinite(evidence['observed_at']) and evidence['observed_at'] > 0)
    rows = evidence.get('rows')
    _require(isinstance(rows, list) and len(rows) == len(expected),
             'official_sku_code_incomplete', '官方UI商家编码没有覆盖全部SKU。')
    result = {}
    for row in rows:
        _require(isinstance(row, dict) and isinstance(row.get('sku_id'), str) and row['sku_id'] in expected and
                 isinstance(row.get('code'), str) and row.get('observed') is True and
                 type(row.get('input_count')) is int and row['input_count'] == 1)
        _require(row['sku_id'] not in result, 'official_sku_code_duplicate_row', '官方UI编码存在重复SKU行。')
        result[row['sku_id']] = row['code']
    _require(set(result) == expected, 'official_sku_code_incomplete', '官方UI商家编码遗漏SKU。')
    _require(evidence.get('rows_sha256') == code_rows_sha256(rows))
    return result


def _probe(editor, op, identity, navigation_id):
    script = files('doudian_auto').joinpath('official_sku_code_dom.js').read_text(encoding='utf-8').strip()
    args = {'product_id': identity['product_id'], 'shop': identity['shop'], 'navigation_id': navigation_id}
    result = editor.bridge.evaluate(script + '(' + json.dumps(op) + ',' +
                                    json.dumps(args, ensure_ascii=True) + ')')
    _require(isinstance(result, dict))
    error = result.get('error')
    if error:
        if error in ('verification_required', 'shop_not_confirmed'):
            raise WaitingHuman(error, '官方商家编码读取需要完成验证或确认当前店铺。')
        raise DoudianError(str(error), '官方商家编码UI读取未通过，未填充或保存任何字段。')
    return result


def collect_official_sku_codes(editor, identity, reference, *, seconds=30):
    """Read the measured SKU code column within a 30-second scrolling budget.

    The reference comes from the same fresh official response being parsed. This
    function never starts a session, opens/reloads a page, or writes a field. Empty
    strings count only when a unique real input was observed for that exact SKU.
    """
    expected = _reference(reference, identity)
    _require(type(seconds) in (int, float) and math.isfinite(seconds) and 0 < seconds <= 30,
             'invalid_sku_code_budget', '官方UI编码读取预算必须大于0且不超过30秒。')
    started = monotonic()
    deadline = started + seconds
    observed, navigation_id, rounds, operation = {}, None, 0, 'read'
    initial_shop_error = None
    while monotonic() < deadline:
        try:
            result = _probe(editor, operation, identity, navigation_id)
        except WaitingHuman as error:
            # The fresh SKU response can precede the asynchronously loaded badge.
            # Wait only before observing any rows/navigation; never hide a mid-read
            # identity change or a verification prompt, and keep the same deadline.
            if error.code != 'shop_not_confirmed' or navigation_id is not None or observed:
                raise
            initial_shop_error = error
            sleep(min(0.2, max(0, deadline - monotonic())))
            continue
        initial_shop_error = None
        rounds += 1
        _require(result.get('product_id') == identity['product_id'] and
                 result.get('page_url') == reference['page_url'] and result.get('shop_confirmed') is True,
                 'wrong_identity', '逐SKU编码读取时商品、页面或店铺改变。')
        nav = result.get('navigation_id')
        _require(type(nav) in (int, float) and math.isfinite(nav) and nav > 0)
        if navigation_id is None:
            navigation_id = nav
        _require(nav == navigation_id, 'official_sku_code_navigation_changed', '编码读取期间官方页面重新加载。')
        _require(type(result.get('ready')) is bool and isinstance(result.get('rows'), list))
        _require(not result['ready'] or result.get('code_column') == '商家编码')
        current = set()
        for row in result['rows']:
            _require(isinstance(row, dict) and isinstance(row.get('sku_id'), str) and row['sku_id'] in expected and
                     isinstance(row.get('code'), str) and row.get('observed') is True and
                     type(row.get('input_count')) is int and row['input_count'] == 1)
            sku = row['sku_id']
            _require(sku not in current, 'official_sku_code_duplicate_row', '当前UI读取存在重复SKU行。')
            current.add(sku)
            _require(sku not in observed or observed[sku] == row['code'],
                     'official_sku_code_conflict', '同一SKU在本次滚动读取中出现不同商家编码。')
            observed[sku] = row['code']
        if monotonic() >= deadline:
            break
        if set(observed) == expected:
            rows = _stable_rows([{'sku_id': sku, 'code': code} for sku, code in observed.items()])
            evidence = {'schema_version': 1, 'source': SOURCE, 'complete': True,
                        **{key: reference[key] for key in _BINDING}, 'shop_confirmed': True,
                        'code_column': '商家编码', 'navigation_id': navigation_id, 'observed_at': time(),
                        'rounds': rounds, 'elapsed_seconds': round(monotonic() - started, 6),
                        'rows': rows, 'rows_sha256': code_rows_sha256(rows)}
            validate_sku_code_evidence(evidence, reference)
            return evidence
        pending = result.get('pending_count')
        _require(type(pending) is int and pending >= 0)
        operation = 'scroll_pending' if result['ready'] and pending else 'read'
        sleep(min(0.2, max(0, deadline - monotonic())))
    if initial_shop_error is not None:
        raise initial_shop_error
    raise DoudianError('official_sku_code_incomplete',
                       f'官方UI商家编码在读取预算内仅确认{len(observed)}/{len(expected)}个SKU，缺失值未作为空值。')

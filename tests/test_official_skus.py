from copy import deepcopy
import json

import pytest

from doudian_auto.errors import DoudianError
from doudian_auto.official_skus import (parse_official_skus, verify_miaoshou_skus,
                                        compare_official_skus, sku_code_ui_reference)
from doudian_auto.official_sku_codes import SOURCE, code_rows_sha256
from doudian_auto.workflow import compare_protected

PID = '3850072653520044313'


def response(count=65):
    values = [{'id': str(100000 + i), 'name': f'规格{i}'} for i in range(count)]
    rows = [{'sku_id': str(3387918799208229 + i), 'id': str(3387918799208229 + i),
             'price': str(10 + i), 'stock_info': {'stock_num': 900 + i},
             'step_stock_info': {'stock_num': 0}, 'spec_detail_ids': [values[i]['id']],
             'code': f'code-{i}', 'sku_status': True} for i in range(count)]
    data = {'errno': 0, 'code': 0, 'data': {'context': {'product_id': PID, 'shop_id': '177970452',
            'operation_type': 'normal', 'model_type': 'normal'}, 'model': {
            'sku_detail': {'value': rows}, 'spec_detail': {'value': [{'name': '颜色', 'spec_values': values}]}}}}
    return {'status': 200, 'completed': True, 'requestId': 'p1:123:request',
            'url': 'https://fxg.jinritemai.com/product/tproduct/getSchema',
            'page_url': f'https://fxg.jinritemai.com/ffa/g/create?product_id={PID}', 'body': json.dumps(data)}


def miaoshou(evidence):
    return {'product_id': PID, 'protected': {'specPrices': [{
        'skuId': int(row['sku_id']), 'specDetailIds': [int(x) for x in row['spec_ids']],
        'price': float(row['price']), 'stockNum': row['stock'], 'stepStockNum': row['step_stock'],
        'code': row['code'], 'skuStatus': row['enabled']} for row in evidence['rows']]}}


def test_reads_all_65_skus_and_binds_fields_to_each_sku_id():
    evidence = parse_official_skus(response(), product_id=PID)
    assert evidence['count'] == 65
    assert evidence['product_id'] == PID
    assert verify_miaoshou_skus(miaoshou(evidence), evidence)['count'] == 65
    compare_official_skus(evidence, deepcopy(evidence))


@pytest.mark.parametrize('change', [
    lambda rows: rows[-1].update(stockNum=0),
    lambda rows: rows.pop(),
    lambda rows: rows[-1].pop('price'),
    lambda rows: (rows[0].update(price=11), rows[1].update(price=10)),
])
def test_hidden_sku_changes_missing_rows_and_price_swaps_never_pass(change):
    evidence = parse_official_skus(response(), product_id=PID)
    current = miaoshou(evidence)
    change(current['protected']['specPrices'])
    with pytest.raises(DoudianError):
        verify_miaoshou_skus(current, evidence)


@pytest.mark.parametrize('change', [
    lambda data: data['data']['context'].update(product_id='3850072653520044314'),
    lambda data: data['data']['context'].update(model_type='draft'),
    lambda data: data['data']['model']['sku_detail']['value'][0].pop('stock_info'),
    lambda data: data['data']['model']['sku_detail']['value'].__setitem__(1,
                  deepcopy(data['data']['model']['sku_detail']['value'][0])),
    lambda data: data['data']['model']['spec_detail']['value'][0]['spec_values'].pop(),
])
def test_schema_identity_draft_missing_fields_and_duplicate_ids_stop(change):
    observed = response()
    data = json.loads(observed['body'])
    change(data)
    observed['body'] = json.dumps(data)
    with pytest.raises(DoudianError):
        parse_official_skus(observed, product_id=PID)


def test_new_readback_requires_same_complete_official_evidence_and_detects_last_hidden_row_change():
    before = parse_official_skus(response(), product_id=PID)
    with pytest.raises(DoudianError):
        compare_protected({'sku_evidence': before}, {})
    with pytest.raises(DoudianError):
        compare_official_skus({'complete': True}, {'complete': True})
    observed = response()
    data = json.loads(observed['body'])
    data['data']['model']['sku_detail']['value'][-1]['price'] = '0.01'
    observed['body'] = json.dumps(data)
    with pytest.raises(DoudianError) as rejected:
        compare_official_skus(before, parse_official_skus(observed, product_id=PID))
    assert rejected.value.code == 'commercial_changed'


def _missing_code_response(request_id='p1:123:request'):
    observed = response(count=3)
    data = json.loads(observed['body'])
    for row in data['data']['model']['sku_detail']['value']:
        row.pop('code')
    observed.update(requestId=request_id, body=json.dumps(data, ensure_ascii=False))
    return observed


def _ui_code_proof(observed, product_id=PID, shop='销霁百货'):
    reference = sku_code_ui_reference(observed, product_id=product_id, shop=shop)
    rows = [{'sku_id': sku, 'code': f'actual-{index}', 'observed': True, 'input_count': 1}
            for index, sku in enumerate(reference['expected_sku_ids'])]
    return {**{key: reference[key] for key in ('product_id', 'shop', 'api_request_id',
                                                'api_body_sha256', 'page_url')},
            'schema_version': 1, 'source': SOURCE, 'shop_confirmed': True,
            'code_column': '商家编码', 'navigation_id': 100.0, 'observed_at': 1_800_000_000.0,
            'rounds': 2, 'elapsed_seconds': 0.1, 'complete': True, 'rows': rows,
            'rows_sha256': code_rows_sha256(rows)}


def test_missing_codes_require_complete_fresh_ui_evidence_and_are_hashed_by_sku():
    observed = _missing_code_response()
    proof = _ui_code_proof(observed)
    evidence = parse_official_skus(observed, product_id=PID, shop='销霁百货', code_ui_evidence=proof)
    assert [row['code'] for row in evidence['rows']] == ['actual-0', 'actual-1', 'actual-2']
    assert evidence['ui_code_rows'] == [
        {'sku_id': row['sku_id'], 'code': row['code'], 'observed': True, 'input_count': 1}
        for row in evidence['rows']]
    assert evidence['raw_rows'][0].get('code') is None

    with pytest.raises(DoudianError):
        parse_official_skus(observed, product_id=PID)
    stale = _ui_code_proof(_missing_code_response('p1:124:request'))
    with pytest.raises(DoudianError) as rejected:
        parse_official_skus(observed, product_id=PID, shop='销霁百货', code_ui_evidence=stale)
    assert rejected.value.code == 'official_sku_code_stale'


def test_explicit_null_codes_cannot_be_repaired_from_ui():
    observed = _missing_code_response()
    data = json.loads(observed['body'])
    data['data']['model']['sku_detail']['value'][0]['code'] = None
    observed['body'] = json.dumps(data, ensure_ascii=False)
    with pytest.raises(DoudianError):
        sku_code_ui_reference(observed, product_id=PID, shop='销霁百货')


def test_ui_code_hash_ignores_request_metadata_but_detects_changed_values():
    before_response = _missing_code_response('p1:123:request')
    before_proof = _ui_code_proof(before_response)
    before = parse_official_skus(before_response, product_id=PID, shop='销霁百货',
                                 code_ui_evidence=before_proof)

    after_response = _missing_code_response('p1:456:request')
    after_proof = _ui_code_proof(after_response)
    after_proof['observed_at'] += 1
    after = parse_official_skus(after_response, product_id=PID, shop='销霁百货',
                                code_ui_evidence=after_proof)
    compare_official_skus(before, after)

    after_proof['rows'][0]['code'] = 'changed'
    after_proof['rows_sha256'] = code_rows_sha256(after_proof['rows'])
    changed = parse_official_skus(after_response, product_id=PID, shop='销霁百货',
                                  code_ui_evidence=after_proof)
    with pytest.raises(DoudianError) as rejected:
        compare_official_skus(before, changed)
    assert rejected.value.code == 'commercial_changed'

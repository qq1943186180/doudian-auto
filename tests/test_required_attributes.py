import copy

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError


def observed():
    return {'observed': True, 'completion_percent':50, 'fields': [
        {'name': '品牌', 'required': True, 'values': ['原品牌']},
        {'name': '硬度', 'required': True, 'values': []},
        {'name': '可选项', 'required': False, 'values': []}], 'missing': ['硬度']}


def test_missing_required_facts_identify_the_field_before_upload():
    with pytest.raises(DoudianError, match='硬度.*未上传或保存') as error:
        batch.require_official_attributes({'required_attributes': observed()})
    assert error.value.code == 'required_attributes_missing'


def test_verified_values_and_empty_optional_fields_pass_without_filling_anything():
    proof=observed();proof['fields'][1]['values']=['中硬'];proof['missing']=[];proof['completion_percent']=100
    original=copy.deepcopy(proof)
    assert batch.require_official_attributes({'required_attributes':proof}) == original
    assert proof == original


@pytest.mark.parametrize('case',['missing','unobserved','empty','duplicate','forged_missing','missing_values','wrong_type','hidden_required'])
def test_absent_or_inconsistent_field_evidence_cannot_pass(case):
    proof=observed()
    if case=='missing': proof=None
    elif case=='unobserved': proof['observed']=False
    elif case=='empty': proof['fields']=[];proof['missing']=[]
    elif case=='duplicate': proof['fields'].append(proof['fields'][0])
    elif case=='forged_missing': proof['missing']=[]
    elif case=='missing_values': del proof['fields'][0]['values']
    elif case=='wrong_type': proof['fields'][0]['required']='true'
    elif case=='hidden_required': proof['fields'][1]['values']=['中硬'];proof['missing']=[]
    with pytest.raises(DoudianError) as error:
        batch.require_official_attributes({'required_attributes':proof})
    assert error.value.code=='required_attributes_unobserved'


def test_missing_fields_are_durable_and_visible_in_batch_status(tmp_path):
    from test_batch import _writer_task
    db,task,claim=_writer_task(tmp_path)
    detail={'code':'required_attributes_missing','message':'缺少硬度，未上传或保存。','required_attributes':observed()}
    batch.set_execution_state(task['id'],'blocked',error=detail['code'],error_detail=detail,db_path=db)
    row=batch.batch_status(task['batch_id'],db_path=db)['products'][0]
    assert row['last_error_details']==detail
    assert row['last_error_message']==detail['message']
    assert row['submission_attempts']==0

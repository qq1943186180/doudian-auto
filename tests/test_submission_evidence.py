import pytest

from doudian_auto.submission_evidence import classify_product_submission, request_product_ids


PID = '3850072653520044313'


def _request(path='/api/v2/product/product/saveEditProductInfo'):
    return {'requestId': 'r1', 'url': 'https://v2-dd.chengji-inc.com' + path,
            'method': 'POST', 'completed': True, 'status': 200}


@pytest.mark.parametrize('body', ['productId=' + PID, '{"productId":' + PID + '}',
                                  {'product_id': PID}, 'productIds=%5B%22' + PID + '%22%5D'])
def test_identity_keeps_all_nineteen_digits(body):
    assert request_product_ids(body) == {PID}


@pytest.mark.parametrize('observed,detail', [
    (_request('/analytics'), {'requestBody': 'productId=' + PID, 'body': {'code': 0}}),
    (_request('/api/v2/product/batch/saveTempBatchTask'), {'requestBody': 'productId=' + PID, 'body': {'success': True}}),
    (_request(), {'requestBody': 'productId=3850072653520044314', 'body': {'result': 'success'}}),
    (_request(), {'requestBody': 'note=' + PID, 'body': {'result': 'success'}}),
    (_request(), {'requestBody': 'productId=' + PID, 'body': {'code': 0}}),
    (_request(), {'requestBody': 'productId=' + PID, 'body': 'response lost'}),
])
def test_unrelated_staged_or_incomplete_responses_stay_unknown(observed, detail):
    assert classify_product_submission(observed, detail, PID) is None


def test_only_explicit_product_business_decision_classifies_save():
    detail = {'requestBody': 'productId=' + PID, 'body': {'result': 'success'}}
    assert classify_product_submission(_request(), detail, PID)['state'] == 'accepted'
    detail['body']['result'] = 'fail'
    assert classify_product_submission(_request(), detail, PID)['state'] == 'failed'
    request = _request()
    request['status'] = 500
    assert classify_product_submission(request, detail, PID) is None

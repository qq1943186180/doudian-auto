"""Classify only fresh, identity-bound product requests observed from page actions."""

import json
import re
from urllib.parse import parse_qs, urlparse


SAVE_PATH = '/api/v2/product/product/saveEditProductInfo'
INTERMEDIATE_PATH = '/api/v2/product/batch/saveTempBatchTask'


def request_fields(body):
    if isinstance(body, dict):
        return body
    if not isinstance(body, str):
        return {}
    try:
        value = json.loads(body)
        return value if isinstance(value, dict) else {}
    except ValueError:
        return {key: values[0] if len(values) == 1 else values
                for key, values in parse_qs(body, keep_blank_values=True).items()}


def request_product_ids(body):
    result = set()
    fields = request_fields(body)
    for key in ('productId', 'product_id', 'productIds', 'product_ids'):
        value = fields.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            if item is not None:
                result.update(re.findall(r'(?<!\d)\d{16,22}(?!\d)', str(item)))
    return result


def classify_product_submission(request, detail, product_id):
    url = urlparse(request.get('url', ''))
    if (url.hostname != 'v2-dd.chengji-inc.com' or url.path != SAVE_PATH or
            request.get('method') != 'POST' or not request.get('completed') or
            request_product_ids(detail.get('requestBody')) != {str(product_id)}):
        return None
    body = detail.get('body')
    try:
        payload = json.loads(body) if isinstance(body, str) else body
    except ValueError:
        return None
    # HTTP failure, empty content, timeout, analytics and task-staging responses do
    # not prove the product was not saved. Only explicit product business decisions
    # may classify this attempt; everything else stays unknown/readback-only.
    if request.get('status') != 200 or not isinstance(payload, dict):
        return None
    decision = payload.get('result')
    if decision not in ('success', 'SUCCESS', 'fail', 'failed', 'FAIL', 'error', 'ERROR'):
        return None
    accepted = decision in ('success', 'SUCCESS')
    return {'state': 'accepted' if accepted else 'failed',
            'error': None if accepted else 'explicit_platform_rejection',
            'evidence': {'http_status': 200, 'request_id': request.get('requestId'),
                         'url_path': url.path, 'response_result': decision,
                         'product_id': str(product_id)}}

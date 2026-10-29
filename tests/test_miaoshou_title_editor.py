import json
from urllib.parse import urlencode

import pytest

from doudian_auto.errors import DoudianError
from doudian_auto.miaoshou_title_editor import (MiaoshouTitleEditor, request_matches_title,
                                               validate_title_preview)
from doudian_auto.title import title_units

PID = '3848322422084337743'
TITLE = '厨房水槽挂式沥水篮不锈钢过滤篮地漏网多款'


def preview():
    return {'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=title',
            'shop': '销霁百货', 'product_ids': [PID], 'row_ids': [PID], 'count': 1,
            'checked_methods': ['new'], 'overlength': 'fail', 'repair_size': False,
            'shelf_unchanged': True, 'timer': False, 'old_title': 'old title',
            'input_title': TITLE, 'row_title': TITLE, 'rendered_units': title_units(TITLE),
            'save_buttons': 1, 'final_submit': True}


@pytest.mark.parametrize('delta', [{}, {'row_ids': [PID, '3848319372858884337']},
    {'checked_methods': ['new', 'ai']}, {'repair_size': True}, {'shelf_unchanged': False},
    {'timer': True}, {'old_title': 'another product'}, {'rendered_units': 0},
    {'row_title': 'old title'}, {'save_buttons': 2}, {'final_submit': False}])
def test_title_preview_limits_scope_and_forbids_side_effects(delta):
    state = {**preview(), **delta}
    if delta:
        with pytest.raises(DoudianError):
            validate_title_preview(state, PID, '销霁百货', 'old title', TITLE)
    else:
        assert validate_title_preview(state, PID, '销霁百货', 'old title', TITLE) == state


def test_observed_request_must_contain_the_exact_product_and_title():
    body = urlencode({'productId': PID, 'info': json.dumps({'title': TITLE})})
    assert request_matches_title(body, PID, TITLE)
    assert not request_matches_title(body, '3848319372858884337', TITLE)
    assert not request_matches_title(body, PID, 'old title')
    assert not request_matches_title(urlencode({'productId': '1' + PID, 'title': TITLE}), PID, TITLE)


@pytest.mark.parametrize('response_result', ['fail', 'success'])
def test_title_only_save_records_new_response_and_requires_readback(response_result):
    class Bridge:
        def __init__(self): self.clicks = 0
        def command(self, action, args):
            if action == 'click':
                self.clicks += 1
                return {}
            if args.get('cmd') == 'list':
                old = {'requestId': 'old', 'url': 'https://v2-dd.chengji-inc.com/api/v2/product/product/saveEditProductInfo',
                       'method': 'POST', 'completed': True, 'status': 200}
                temp = {**old, 'requestId': 'temp', 'url': 'https://v2-dd.chengji-inc.com/api/v2/product/batch/saveTempBatchTask'}
                return {'requests': [old, temp, {**old, 'requestId': 'new'}] if self.clicks else [old]}
            if args.get('cmd') == 'detail':
                assert args['requestId'] in ('temp', 'new')
                return {'requestBody': json.dumps({'productId': PID, 'title': TITLE}),
                        'body': {'result': 'success' if args['requestId'] == 'temp' else response_result,
                                 'message': '平台消息', 'token': 'not-retained'}}
            return {}
    bridge = Bridge()
    editor = MiaoshouTitleEditor(bridge, '销霁百货')
    editor.observe_title = preview
    result = editor.click_save_once({'product_id': PID, 'old_title': 'old title',
                                     'title': TITLE, 'marker': 'one'})
    assert result['state'] == ('failed' if response_result == 'fail' else 'unknown')
    assert result['request_id'] == 'new'
    assert result['platform_details'] == {'message': '平台消息'}
    assert bridge.clicks == 1


def test_failed_intermediate_task_response_cannot_authorize_resaving(monkeypatch):
    ticks = iter([0, 1, 61])
    monkeypatch.setattr('doudian_auto.miaoshou_title_editor.time.monotonic', lambda: next(ticks))
    monkeypatch.setattr('doudian_auto.miaoshou_title_editor.time.sleep', lambda seconds: None)
    class Bridge:
        clicked = False
        def command(self, action, args):
            if action == 'click':
                self.clicked = True
            if args.get('cmd') == 'list':
                return {'requests': [{'requestId': 'temp', 'url': 'https://v2-dd.chengji-inc.com/api/v2/product/batch/saveTempBatchTask',
                    'method': 'POST', 'completed': True, 'status': 200}] if self.clicked else []}
            if args.get('cmd') == 'detail':
                return {'requestBody': json.dumps({'productId': PID, 'title': TITLE}), 'body': {'result': 'fail'}}
            return {}
    editor = MiaoshouTitleEditor(Bridge(), '销霁百货')
    editor.observe_title = preview
    result = editor.click_save_once({'product_id': PID, 'old_title': 'old title', 'title': TITLE, 'marker': 'one'})
    assert result['state'] == 'unknown'

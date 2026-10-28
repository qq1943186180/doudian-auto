import pytest

from doudian_auto.errors import DoudianError, WaitingHuman
from doudian_auto.miaoshou_editor import MiaoshouEditor, parse_edit_response


def _response(product_id=3848319372858884337):
    return {'status': 200, 'body': {
        'result': 'success', 'productId': product_id, 'categoryId': 123,
        'brandName': 'test-brand',
        'productInfo': {
            'productId': product_id, 'name': 'verified title',
            'pic': [f'https://img.example/main-{i}.jpg' for i in range(5)],
            'descriptionImgList': [f'https://img.example/detail-{i}.jpg' for i in range(4)],
            'specPrices': [{'price': 1000, 'stock': 20}], 'freightId': 8,
            'status': 0, 'draftStatus': 0, 'specPics': [],
            'mainImageThreeToFour': [], 'whiteBackGroundPicUrl': '',
            'afterSaleService': {},
        },
    }}


def test_parse_miaoshou_read_keeps_long_product_id_exact_and_whitelists_fields():
    product_id = '3848319372858884337'
    result = parse_edit_response(_response(int(product_id)), expected_product_id=product_id,
                                 shop='销霁百货')
    assert result['product_id'] == product_id
    assert result['title'] == 'verified title'
    assert len(result['mains']) == 5
    assert len(result['details']) == 4
    assert result['protected_complete'] is True
    assert 'mobile' not in result['protected']


def test_parse_miaoshou_read_rejects_wrong_identity_and_missing_protected_field():
    with pytest.raises(DoudianError) as wrong_id:
        parse_edit_response(_response(3848319372858884338),
                            expected_product_id='3848319372858884337', shop='销霁百货')
    assert wrong_id.value.code == 'wrong_identity'

    payload = _response()
    del payload['body']['productInfo']['freightId']
    with pytest.raises(DoudianError) as missing:
        parse_edit_response(payload, expected_product_id='3848319372858884337', shop='销霁百货')
    assert missing.value.code == 'protected_incomplete'


class _TabBridge:
    def __init__(self, matches):
        self.matches = matches
        self.clicks = []
        self.evaluations = []

    def evaluate(self, code):
        self.evaluations.append(code)
        if 'querySelectorAll' in code:
            return {'count': self.matches, 'text': '主图' if self.matches == 1 else None}
        return True

    def command(self, action, args):
        self.clicks.append((action, args))
        return {'success': True}


def test_miaoshou_tab_click_scopes_to_a_unique_visible_dialog_tab():
    bridge = _TabBridge(1)
    editor = MiaoshouEditor(bridge, '销霁百货')

    editor._click_tab('主图')

    assert len(bridge.clicks) == 1
    assert bridge.clicks[0][0] == 'click'
    assert bridge.clicks[0][1]['selector'].startswith('[data-codex-miaoshou-tab="miaoshou-tab-')
    assert len(bridge.evaluations) == 2


def test_miaoshou_tab_click_refuses_ambiguous_visible_tabs():
    bridge = _TabBridge(2)
    editor = MiaoshouEditor(bridge, '销霁百货')

    with pytest.raises(DoudianError) as caught:
        editor._click_tab('主图')

    assert caught.value.code == 'miaoshou_tab_not_unique'
    assert bridge.clicks == []


def test_close_replace_popup_clicks_only_the_marked_visible_dialog_button():
    class CloseBridge:
        def __init__(self):
            self.clicks = []
            self.evaluations = []

        def evaluate(self, code):
            self.evaluations.append(code)
            if "return {open:dialogs.length>0" in code:
                return {'open': True, 'dialogs': 1, 'closeButtons': 1, 'x': 1402.5, 'y': 73.5}
            return True

        def command(self, action, args):
            self.clicks.append((action, args))
            return {'success': True}

        def wait(self, probe, predicate, message, seconds):
            result = probe()
            assert predicate(result)
            return result

    bridge = CloseBridge()
    editor = MiaoshouEditor(bridge, '销霁百货')

    editor._close_replace_popup()

    cdp = [args for action, args in bridge.clicks if action == 'cdp']
    assert [args['method'] for args in cdp] == [
        'Emulation.setFocusEmulationEnabled',
        'Input.dispatchMouseEvent', 'Input.dispatchMouseEvent', 'Input.dispatchMouseEvent',
        'Emulation.setFocusEmulationEnabled',
    ]
    assert cdp[0]['params']['enabled'] is True
    assert cdp[-1]['params']['enabled'] is False
    assert cdp[1]['params'] == {'type': 'mouseMoved', 'x': 1402.5, 'y': 73.5}
    assert any('removeAttribute(\'data-codex-miaoshou-close\')' in code
               for code in bridge.evaluations)


def test_close_replace_popup_refuses_multiple_visible_dialogs():
    class AmbiguousBridge:
        def __init__(self):
            self.clicks = []

        def evaluate(self, code):
            return {'open': True, 'dialogs': 2, 'closeButtons': 2, 'x': None, 'y': None}

        def command(self, action, args):
            self.clicks.append((action, args))

    bridge = AmbiguousBridge()
    editor = MiaoshouEditor(bridge, '销霁百货')

    with pytest.raises(DoudianError) as caught:
        editor._close_replace_popup()

    assert caught.value.code == 'miaoshou_replace_close_not_unique'
    assert bridge.clicks == []


def test_close_replace_popup_remeasures_once_after_a_transient_timeout():
    class RetryBridge:
        def __init__(self):
            self.state_reads = 0
            self.calls = []

        def evaluate(self, code):
            self.calls.append(('evaluate', code))
            if "return {open:dialogs.length>0" in code:
                self.state_reads += 1
                if self.state_reads == 1:
                    return {'open': True, 'dialogs': 1, 'closeButtons': 1, 'x': 100, 'y': 200}
                return {'open': False, 'dialogs': 0, 'closeButtons': 0, 'x': None, 'y': None}
            return True

        def command(self, action, args):
            self.calls.append((action, args))
            return {'success': True}

        def wait(self, probe, predicate, message, seconds):
            raise DoudianError('page_timeout', message)

    bridge = RetryBridge()
    editor = MiaoshouEditor(bridge, '销霁百货')

    editor._close_replace_popup()

    assert bridge.state_reads == 2
    assert sum(1 for action, args in bridge.calls
               if action == 'cdp' and args.get('method') == 'Input.dispatchMouseEvent') == 3


@pytest.mark.parametrize('counter_matches', [True, False])
def test_fill_title_requires_trusted_input_and_model_counter(counter_matches):
    from doudian_auto.title import title_units
    target = '厨房水槽挂式沥水篮不锈钢过滤篮'
    class TitleBridge:
        def __init__(self):
            self.calls = []

        def evaluate(self, code):
            self.calls.append(('evaluate', code))
            if "return {count:ms.length,text:ms.length===1" in code:
                return {'count': 1, 'text': '商品信息'}
            if "return {id:i.id,value:i.value,x:r.x+r.width/2,y:r.y+r.height/2}" in code:
                return {'id': 'title-input', 'value': 'old title', 'x': 100, 'y': 200}
            if "rendered_units:m?Number" in code:
                return {'title': target, 'identity': True,
                        'rendered_units': title_units(target) if counter_matches else 0}
            return True

        def command(self, action, args):
            self.calls.append((action, args))
            return {'success': True}

        def wait(self, probe, predicate, message, seconds):
            result = probe()
            if not predicate(result):
                raise DoudianError('page_timeout', message)
            return result

    bridge = TitleBridge()
    editor = MiaoshouEditor(bridge, '销霁百货')

    if counter_matches:
        editor.fill_title('3848319372858884337', target)
    else:
        with pytest.raises(DoudianError, match='实时字数没有同步'):
            editor.fill_title('3848319372858884337', target)

    methods = [args['method'] for action, args in bridge.calls
               if action == 'cdp' and 'method' in args]
    assert methods == [
        'Emulation.setFocusEmulationEnabled',
        'Input.dispatchMouseEvent', 'Input.dispatchMouseEvent', 'Input.dispatchMouseEvent',
        'Input.dispatchKeyEvent', 'Input.dispatchKeyEvent',
        'Input.insertText',
        'Input.dispatchKeyEvent', 'Input.dispatchKeyEvent',
        'Emulation.setFocusEmulationEnabled',
    ]
    insert = next(args for action, args in bridge.calls
                  if action == 'cdp' and args.get('method') == 'Input.insertText')
    assert insert['params']['text'] == '厨房水槽挂式沥水篮不锈钢过滤篮'
    tab_events = [args['params'] for action, args in bridge.calls
                  if action == 'cdp' and args.get('method') == 'Input.dispatchKeyEvent'][-2:]
    assert [event['key'] for event in tab_events] == ['Tab', 'Tab']


def test_save_ignores_previous_success_and_classifies_only_the_new_request():
    class SaveBridge:
        def __init__(self):
            self.clicks = 0
            self.details = []
        def command(self, action, args):
            if action == 'click':
                self.clicks += 1
                return {'success': True}
            if args.get('cmd') == 'list':
                old = {'requestId': 'old-success', 'method': 'POST', 'completed': True, 'status': 200}
                fresh = {'requestId': 'new-failure', 'method': 'POST', 'completed': True, 'status': 400}
                return {'requests': [old, fresh] if self.clicks else [old]}
            if args.get('cmd') == 'detail':
                self.details.append(args['requestId'])
                return {'body': {'result': 'fail'}}
            return {}
    bridge = SaveBridge()
    editor = MiaoshouEditor(bridge, '销霁百货')
    editor._snapshot = lambda: {'tree_text': '- button "保存到抖店(F)" [ref=e1]'}
    result = editor.click_save_once()
    assert result['state'] == 'failed'
    assert result['request_id'] == 'new-failure'
    assert bridge.clicks == 1
    assert bridge.details == ['new-failure']


def test_image_group_selectors_use_the_observed_main_and_detail_lists():
    assert MiaoshouEditor._image_list_selector('mains') == (
        '.imageUrls > .draggable-img-list', '主图', 5)
    assert MiaoshouEditor._image_list_selector('details') == (
        '.img-list > .draggable-img-list', '详情图', 4)
    with pytest.raises(DoudianError) as caught:
        MiaoshouEditor._image_list_selector('white-background')
    assert caught.value.code == 'invalid_image_slot'


@pytest.mark.parametrize(('kind', 'active', 'count', 'selector'), [
    ('mains', '主图', 5, '.imageUrls > .draggable-img-list'),
    ('details', '详情图', 16, '.img-list > .draggable-img-list'),
])
def test_wait_image_groups_reads_only_the_selected_image_list(kind, active, count, selector):
    class GroupBridge:
        def __init__(self):
            self.code = ''

        def evaluate(self, code):
            self.code = code
            return {'count': count, 'urls': [f'https://img.example/{i}.jpg' for i in range(count)],
                    'active': active}

        def wait(self, probe, predicate, message, seconds):
            result = None
            for _ in range(3):
                result = probe()
            assert predicate(result)
            return result

    bridge = GroupBridge()
    editor = MiaoshouEditor(bridge, '销霁百货')

    result = editor._wait_image_groups(kind)

    assert result['count'] == count
    assert result['active'] == active
    assert selector in bridge.code
    assert 'image_list_not_unique' in bridge.code
    assert 'all(result.get' not in bridge.code


def test_miaoshou_snapshot_pauses_on_shop_authorization_page():
    class AuthorizationBridge:
        def command(self, action, args):
            assert action == 'snapshot'
            return {
                'url': 'https://fuwu.jinritemai.com/authorize?service_id=234&from=isv.authorize',
                'tree_text': '确认授权',
            }

    editor = MiaoshouEditor(AuthorizationBridge(), '销霁百货')

    with pytest.raises(WaitingHuman) as caught:
        editor._snapshot()

    assert caught.value.code == 'miaoshou_authorization_required'


def test_shelf_mode_preflight_fails_closed_when_live_editor_has_no_control():
    class ShelfModeBridge:
        def evaluate(self, code):
            assert '审核.{0,8}上架' in code
            return {'dialog': True, 'labels': []}

    editor = MiaoshouEditor(ShelfModeBridge(), '销霁百货')

    with pytest.raises(DoudianError) as caught:
        editor.require_shelf_mode_preservable(0)

    assert caught.value.code == 'miaoshou_shelf_mode_not_editable'


def test_shelf_mode_preflight_requires_matching_selected_value():
    class ShelfModeBridge:
        def __init__(self, mode):
            self.mode = mode

        def evaluate(self, code):
            return {'dialog': True, 'controls': 1, 'mode': self.mode,
                    'label': '审核通过后上架'}

    editor = MiaoshouEditor(ShelfModeBridge(0), '销霁百货')
    assert editor.require_shelf_mode_preservable(0) == {
        'preservable': True, 'mode': 0, 'label': '审核通过后上架'}

    editor.bridge.mode = 1
    with pytest.raises(DoudianError) as caught:
        editor.require_shelf_mode_preservable(0)
    assert caught.value.code == 'miaoshou_shelf_mode_mismatch'

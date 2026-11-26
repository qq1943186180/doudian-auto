import pytest

from doudian_auto.errors import DoudianError
from doudian_auto.miaoshou_editor import MiaoshouEditor


def test_remembered_sku_tab_switches_once_inside_original_read_budget(monkeypatch):
    pid = '3848315786359865811'

    class Bridge:
        def __init__(self):
            self.calls = []

        def require_ready(self):
            pass

        def command(self, action, args):
            self.calls.append((action, args))
            return {'requests': []}

        def wait(self, read, predicate, message, seconds):
            assert seconds == 10
            for _ in range(2):
                value = read()
                if predicate(value):
                    return value
            raise AssertionError(message)

    bridge = Bridge()
    editor = MiaoshouEditor(bridge, '销霁百货', session='unit')
    monkeypatch.setattr(editor, '_mark_control', lambda op, product_id=None: op)
    dialog_reads = []
    def visible_dom(op, *args):
        if op == 'navigation_toggle':
            return {'count': 0}
        if op == 'dialog':
            dialog_reads.append(op)
            return {'count': 1, 'identity': len(dialog_reads) == 2}
        return {'count': 1, 'selector': 'information_tab', 'identity': True}
    monkeypatch.setattr(editor, '_visible_dom', visible_dom)
    budgets = []

    def wait_tree(predicate, message, seconds=30):
        budgets.append(seconds)
        texts = (['您好【销霁百货】'] if len(budgets) == 1 else
                 ['ID：9999999999999999999 SKU/价格库存', f'ID：{pid} SKU/价格库存',
                  f'ID：{pid} SKU/价格库存', f'ID：{pid} 商品标题：'])
        for text in texts:
            snap = {'tree_text': text}
            before = sum(c == ('click', {'selector': 'information_tab'}) for c in bridge.calls)
            if predicate(snap):
                return snap
            if pid not in text:
                assert before == sum(c == ('click', {'selector': 'information_tab'}) for c in bridge.calls)
        raise AssertionError('never ready')

    monkeypatch.setattr(editor, '_wait_tree', wait_tree)
    assert '商品标题：' in editor.open_product(pid)['tree_text']
    assert bridge.calls.count(('click', {'selector': 'information_tab'})) == 1
    assert budgets == [30, 30]
    assert len(dialog_reads) == 2
    assert all('save' not in str(args).lower() for action, args in bridge.calls)


def test_open_product_waits_for_query_loading_and_total_hint_before_edit_click(monkeypatch):
    pid = '3853482303460343870'
    events = []

    class Bridge:
        def require_ready(self):
            pass

        def command(self, action, args):
            events.append((action, args))
            return {'requests': []}

        def wait(self, read, predicate, message, seconds):
            value = read()
            if predicate(value):
                return value
            raise AssertionError(message)

    bridge = Bridge()
    editor = MiaoshouEditor(bridge, '销霁百货', session='unit')
    monkeypatch.setattr('doudian_auto.miaoshou_editor.time.sleep', lambda _s: None)
    monkeypatch.setattr(editor, '_mark_control', lambda op, product_id=None: (events.append(('mark', op)), op)[1])

    probe_states = iter([
        {'filter_applied': True, 'loading': False, 'errors': [], 'total_hint': 58, 'exact_rows': 1},
        {'filter_applied': True, 'loading': True, 'errors': [], 'total_hint': 58, 'exact_rows': 1},
        {'filter_applied': True, 'loading': False, 'errors': [], 'total_hint': 1, 'exact_rows': 1},
    ])

    def visible_dom(op, *args):
        if op == 'probe':
            state = next(probe_states)
            events.append(('probe', state['loading'], state['total_hint']))
            return state
        if op == 'navigation_toggle':
            return {'count': 0}
        if op == 'dialog':
            return {'count': 1, 'identity': True}
        return {'count': 1, 'selector': 'information_tab', 'identity': True}

    monkeypatch.setattr(editor, '_visible_dom', visible_dom)
    monkeypatch.setattr(
        editor,
        '_wait_tree',
        lambda predicate, message, seconds=30: (
            {'tree_text': '您好【销霁百货】'}
            if predicate({'tree_text': '您好【销霁百货】'})
            else {'tree_text': f'ID：{pid} 商品标题：'}
        ),
    )

    assert '商品标题：' in editor.open_product(pid)['tree_text']
    probe_indices = [i for i, e in enumerate(events) if e[0] == 'probe']
    edit_click_idx = events.index(('click', {'selector': 'edit_button'}))
    assert len(probe_indices) == 3
    assert max(probe_indices) < edit_click_idx
    assert ('click', {'selector': 'query_button'}) in events
    assert events.index(('click', {'selector': 'query_button'})) < min(probe_indices)


def test_close_replace_popup_uses_native_click_on_ego_endpoint():
    calls = []
    closed = {'value': False}

    class NativeBridge:
        endpoint = 'ego'

        def require_ready(self):
            pass

        def evaluate(self, code):
            calls.append(('evaluate', code))
            if 'removeAttribute' in code:
                return True
            if '.replace-image-dialog' in code and 'open:' in code:
                return {'open': True, 'dialogs': 1, 'closeButtons': 1, 'x': 120.0, 'y': 60.0}
            return closed['value']

        def command(self, action, args):
            calls.append((action, args))
            if action == 'click':
                assert args['selector'].startswith('[data-codex-miaoshou-close="miaoshou-close-')
                closed['value'] = True
            return {'success': True}

        def wait(self, read, predicate, message, seconds):
            value = read()
            if predicate(value):
                return value
            raise AssertionError(message)

    editor = MiaoshouEditor(NativeBridge(), '销霁百货', session='unit')
    editor._close_replace_popup()
    actions = [c[0] for c in calls]
    assert 'click' in actions
    assert 'cdp' not in actions


def _make_close_race_bridge(dialog_closed_on_recheck: bool):
    calls = []

    class RaceBridge:
        endpoint = 'ego'

        def require_ready(self):
            pass

        def evaluate(self, code):
            calls.append(('evaluate', code))
            if 'removeAttribute' in code:
                return True
            if '.replace-image-dialog' in code and 'open:' in code:
                return {'open': True, 'dialogs': 1, 'closeButtons': 1, 'x': 120.0, 'y': 60.0}
            return dialog_closed_on_recheck

        def command(self, action, args):
            calls.append((action, args))
            if action == 'click':
                raise DoudianError('ego_target_not_unique', 'No unique enabled native control.')
            return {'success': True}

        def wait(self, read, predicate, message, seconds):
            value = read()
            if predicate(value):
                return value
            raise AssertionError(message)

    return RaceBridge(), calls


def test_close_replace_popup_returns_when_dialog_auto_closes_before_native_click():
    bridge, calls = _make_close_race_bridge(dialog_closed_on_recheck=True)
    editor = MiaoshouEditor(bridge, '销霁百货', session='unit')
    editor._close_replace_popup()
    click_calls = [c for c in calls if c[0] == 'click']
    cleanup_evals = [c for c in calls if c[0] == 'evaluate' and 'removeAttribute' in c[1]]
    assert len(click_calls) == 1
    assert len(cleanup_evals) == 1


def test_close_replace_popup_raises_ego_target_not_unique_if_dialog_stays_open():
    bridge, calls = _make_close_race_bridge(dialog_closed_on_recheck=False)
    editor = MiaoshouEditor(bridge, '销霁百货', session='unit')
    with pytest.raises(DoudianError) as exc_info:
        editor._close_replace_popup()
    assert exc_info.value.code == 'ego_target_not_unique'
    assert len([c for c in calls if c[0] == 'click']) == 2



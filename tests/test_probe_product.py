"""Structured 妙手 probe: prove reachable, never invent a cause.

The old `row_present` collapsed four different situations into False. This probe
reports the query state instead, and only says `absent` when the query finished
cleanly *and* the pagination total is zero. Anything else is `reason_unknown`.
"""

import pytest

from doudian_auto import miaoshou_editor
from doudian_auto.miaoshou_editor import MiaoshouEditor

PID = '3848315893817934633'


class FakeBridge:
    def require_ready(self):
        pass

    def command(self, *args, **kwargs):
        return {'tree_text': '您好【销霁百货】'}

    def evaluate(self, *args, **kwargs):
        return {}


def editor_with(signals):
    ed = MiaoshouEditor.__new__(MiaoshouEditor)
    ed.bridge = FakeBridge()
    ed.shop = '销霁百货'
    ed._prior_edit_ids = set()
    ed._wait_tree = lambda predicate, message, seconds=30: {'tree_text': '您好【销霁百货】'}
    ed._mark_control = lambda op, product_id=None: '#marked'
    seq = list(signals)
    ed._visible_dom = lambda op, product_id=None, marker=None: (
        seq.pop(0) if len(seq) > 1 else seq[0])
    return ed


def signals(**overrides):
    base = {'filter_applied': True, 'loading': False, 'errors': [], 'total_hint': 1,
            'exact_rows': 1, 'row_status': '在售', 'buttons': [], 'url': 'u'}
    base.update(overrides)
    return base


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    monkeypatch.setattr(miaoshou_editor.time, 'sleep', lambda _s: None)
    monkeypatch.setattr(miaoshou_editor.time, 'monotonic', Clock())


def test_a_visible_row_is_present():
    result = editor_with([signals()]).probe_product(PID)
    assert result['verdict'] == 'present'
    assert result['reason'] == 'row_in_current_query'
    assert result['market'] == 'miaoshou_quick_edit'
    assert result['product_id'] == PID


def test_zero_rows_with_zero_total_is_absent():
    result = editor_with([signals(exact_rows=0, total_hint=0, row_status=None)]).probe_product(PID)
    assert result['verdict'] == 'absent'
    assert result['reason'] == 'absent_from_current_query'


def test_zero_rows_with_unreadable_total_is_unknown():
    # This is the exact trap: a stale/unreadable pagination total must not be read
    # as "the whole list is empty".
    result = editor_with([signals(exact_rows=0, total_hint=None, row_status=None)]).probe_product(PID)
    assert result['verdict'] == 'unknown'
    assert result['reason'] == 'reason_unknown'


@pytest.mark.parametrize('override', [
    {'loading': True}, {'errors': ['网络异常']}, {'filter_applied': False}])
def test_an_unsettled_query_is_unknown(override):
    result = editor_with([signals(exact_rows=0, total_hint=0, **override)]).probe_product(PID)
    assert result['verdict'] == 'unknown'
    assert result['reason'] == 'reason_unknown'


def test_wrong_shop_signal_is_unknown():
    result = editor_with([{'error': 'wrong_shop'}]).probe_product(PID)
    assert result['verdict'] == 'unknown'
    assert result['reason'] == 'reason_unknown'


def test_it_waits_for_two_identical_reads_before_concluding():
    first = signals(exact_rows=0, total_hint=0, row_status=None)
    second = dict(first)
    result = editor_with([first, second]).probe_product(PID)
    assert result['verdict'] == 'absent'
    assert result['signals']['exact_rows'] == 0


def test_a_non_numeric_product_id_is_refused():
    with pytest.raises(Exception) as exc:
        editor_with([signals()]).probe_product('abc')
    assert getattr(exc.value, 'code', '') == 'invalid_product'

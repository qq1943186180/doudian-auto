from types import SimpleNamespace

import pytest

from doudian_auto import batch
from doudian_auto.bridge import Bridge
from doudian_auto.errors import DoudianError, WaitingHuman


IDENTITY = {'product_id': '3850071689249554608', 'shop': '销霁百货'}


def editor_with(errors):
    attempts = []
    def dom(op, identity, **kwargs):
        assert (op, identity, kwargs) == ('scroll', IDENTITY, {'kind': 'details'})
        attempts.append(op)
        error = next(errors)
        if error:
            raise error
        return {'ok': True}
    bridge = SimpleNamespace()
    bridge.wait = lambda *a, **k: Bridge.wait(bridge, *a, **k)
    return SimpleNamespace(dom=dom, bridge=bridge), attempts


def test_schema_reload_waits_for_the_same_exact_identity_without_another_reload(monkeypatch):
    monkeypatch.setattr(batch.time, 'sleep', lambda _: None)
    editor, attempts = editor_with(iter([WaitingHuman('shop_not_confirmed', 'badge loading'),
        WaitingHuman('editor_not_ready', 'form loading'), DoudianError('editor_layout_changed', 'blocks loading'), None]))
    batch._scroll_details_after_schema_reload(editor, IDENTITY)
    assert attempts == ['scroll'] * 4


@pytest.mark.parametrize('code', ['verification_required', 'wrong_product', 'wrong_host', 'commercial_changed'])
def test_real_identity_validation_and_commercial_errors_stop_immediately(code):
    editor, attempts = editor_with(iter([WaitingHuman(code, 'must stop'), None]))
    with pytest.raises(DoudianError) as error:
        batch._scroll_details_after_schema_reload(editor, IDENTITY)
    assert error.value.code == code
    assert attempts == ['scroll']


def test_missing_shop_at_deadline_stays_unconfirmed(monkeypatch):
    clock = iter([0, 0, 31])
    monkeypatch.setattr(batch.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(batch.time, 'sleep', lambda _: None)
    editor, attempts = editor_with(iter([WaitingHuman('shop_not_confirmed', 'absent')] * 2))
    with pytest.raises(WaitingHuman) as error:
        batch._scroll_details_after_schema_reload(editor, IDENTITY)
    assert error.value.code == 'shop_not_confirmed'
    assert len(attempts) == 2

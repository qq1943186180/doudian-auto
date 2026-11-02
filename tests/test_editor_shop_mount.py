import pytest

from doudian_auto.editor import Editor
from doudian_auto.errors import DoudianError, WaitingHuman


IDENTITY = {'product_id': '3848316155827716392', 'shop': '销霁百货',
            'edit_url': 'https://fxg.jinritemai.com/ffa/g/create?product_id=3848316155827716392'}


class MountingBridge:
    def __init__(self, observations):
        self.observations = list(observations)
        self.calls = []

    def open(self, url, fresh=False):
        self.calls.append(('open', url, fresh))

    def evaluate(self, script):
        self.calls.append(('read',))
        value = self.observations[0]
        if len(self.observations) > 1:
            self.observations.pop(0)
        return value

    def wait(self, probe, predicate, message, seconds):
        self.calls.append(('wait', seconds))
        for _ in range(3):
            result = probe()
            if predicate(result):
                return result
        raise DoudianError('page_timeout', message)


@pytest.mark.parametrize('pending', ['shop_not_confirmed', 'editor_not_ready', 'editor_layout_changed'])
def test_open_polls_loading_without_repeating_navigation(pending):
    ready = {'success': True, 'shop_confirmed': True, 'product_id': IDENTITY['product_id']}
    bridge = MountingBridge([{'error': pending}, ready])
    assert Editor(bridge).open(IDENTITY, fresh=True) == ready
    assert [x for x in bridge.calls if x[0] == 'open'] == [('open', IDENTITY['edit_url'], True)]
    assert ('wait', 30) in bridge.calls
    assert len([x for x in bridge.calls if x[0] == 'read']) == 2


def test_absent_or_wrong_shop_still_fails_at_read_deadline():
    bridge = MountingBridge([{'error': 'shop_not_confirmed'}])
    with pytest.raises(WaitingHuman) as exc:
        Editor(bridge).open(IDENTITY, fresh=True)
    assert exc.value.code == 'shop_not_confirmed'
    assert ('wait', 30) in bridge.calls
    assert len([x for x in bridge.calls if x[0] == 'open']) == 1
    assert len([x for x in bridge.calls if x[0] == 'read']) == 4


@pytest.mark.parametrize('error', ['verification_required', 'wrong_product'])
def test_verification_and_product_mismatch_stop_immediately(error):
    bridge = MountingBridge([{'error': error}, {'success': True}])
    with pytest.raises(DoudianError) as exc:
        Editor(bridge).open(IDENTITY, fresh=True)
    assert exc.value.code == error
    assert len([x for x in bridge.calls if x[0] == 'read']) == 1

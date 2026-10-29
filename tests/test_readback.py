from doudian_auto.readback import wait_for_target_titles


def test_old_title_then_saved_title_is_rechecked_without_a_new_save(monkeypatch):
    monkeypatch.setattr('doudian_auto.readback.time.sleep', lambda seconds: None)
    observations = iter([({'title': 'old'}, {'title': 'old'}),
                         ({'title': 'target'}, {'title': 'target', 'protected': {'sku': 'unchanged'}})])
    result = wait_for_target_titles(lambda: next(observations), 'target')
    assert result[1]['protected']['sku'] == 'unchanged'


def test_old_titles_after_deadline_are_observation_not_permission_to_resave(monkeypatch):
    clock = iter([0, 31, 32])
    monkeypatch.setattr('doudian_auto.readback.time.monotonic', lambda: next(clock))
    monkeypatch.setattr('doudian_auto.readback.time.sleep', lambda seconds: None)
    calls = []
    def read():
        calls.append(True)
        return ({'title': 'old'}, {'title': 'old'})
    assert wait_for_target_titles(read, 'target')[0]['title'] == 'old'
    assert len(calls) == 1

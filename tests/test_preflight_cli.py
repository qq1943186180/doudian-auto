import json

from doudian_auto import cli, preflight


def test_preflight_cli_uses_the_explicit_read_only_scope_and_current_session(monkeypatch, capsys, tmp_path):
    observed = {}

    def inspect(endpoint, **kwargs):
        observed.update(endpoint=endpoint, **kwargs)
        return {'read_only': True, 'candidate_product_ids': ['3850072900438720563']}

    monkeypatch.setattr(preflight, 'preflight_products', inspect)
    assert cli.main(['--json', '--endpoint', 'ego', 'batch', 'preflight',
                     '--product-id', '3850072900438720563', '--session', 'existing-task',
                     '--limit', '1', '--report-dir', str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['ok'] and result['data']['read_only']
    assert observed == {'endpoint': 'ego', 'product_ids': ['3850072900438720563'],
                        'batch_id': None, 'limit': 1, 'session': 'existing-task',
                        'report_dir': str(tmp_path), 'recheck_blocked': False,
                        'check_miaoshou': False}


def test_recheck_blocked_reaches_the_reader_and_stays_off_by_default(monkeypatch, capsys):
    # The flag only widens which rows may be read; it must never turn preflight into a
    # write, so the default stays off and the connection stays read-only.
    observed = {}

    def inspect(endpoint, **kwargs):
        observed.update(endpoint=endpoint, **kwargs)
        return {'read_only': True, 'candidate_product_ids': []}

    monkeypatch.setattr(preflight, 'preflight_products', inspect)
    assert cli.main(['--json', 'batch', 'preflight', '--product-id', '3850072900438720563',
                     '--recheck-blocked']) == 0
    assert observed['recheck_blocked'] is True


def test_preflight_cannot_be_changed_into_an_apply_command(monkeypatch, capsys):
    monkeypatch.setattr(preflight, 'preflight_products', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not execute')))
    assert cli.main(['--json', 'batch', 'preflight', '--product-id', '3850072900438720563', '--apply']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['error']['code'] == 'invalid_arguments'


def test_requeue_cli_forwards_same_session_to_bridge_and_miaoshou_editor(monkeypatch, capsys, tmp_path):
    from doudian_auto import batch, miaoshou_editor
    seen = {}
    proof = tmp_path / 'art.json'
    proof.write_text('{}', encoding='utf-8')

    class DummyBridge:
        def __init__(self, endpoint, session='default', timeout=30):
            seen['bridge'] = (endpoint, session)

    class DummyMiaoshou:
        def __init__(self, bridge, shop, *, session='miaoshou-auto-batch-20261028'):
            seen['editor'] = (shop, session)

        def row_present(self, pid):
            seen['row_present'] = pid
            return True

    def fake_requeue(task_id, proof_path, *, miaoshou_probe=None, **kwargs):
        assert miaoshou_probe is not None
        assert miaoshou_probe('样板店', '3850072900438720563') is True
        return {'task_id': task_id, 'state': 'needs_agent'}

    monkeypatch.setattr(cli, 'Bridge', DummyBridge)
    monkeypatch.setattr(miaoshou_editor, 'MiaoshouEditor', DummyMiaoshou)
    monkeypatch.setattr(batch, 'requeue_visual_task', fake_requeue)

    assert cli.main(['--json', 'batch', 'requeue', '--task-id', '27', '--proof', str(proof), '--check-miaoshou']) == 0
    capsys.readouterr()
    assert seen['bridge'] == ('ego', 'miaoshou-requeue')
    assert seen['editor'] == ('样板店', 'miaoshou-requeue')

    assert cli.main(['--json', 'batch', 'requeue', '--task-id', '27', '--proof', str(proof),
                     '--check-miaoshou', '--session', 'unblock-p3']) == 0
    capsys.readouterr()
    assert seen['bridge'] == ('ego', 'unblock-p3')
    assert seen['editor'] == ('样板店', 'unblock-p3')

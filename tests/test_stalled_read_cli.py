import json

from doudian_auto import cli, stalled_read_recovery


def test_stalled_read_cli_binds_native_session_and_proof(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr('doudian_auto.jobs.DATA_ROOT', tmp_path)
    calls = []
    def recover(bridge, proof):
        assert (tmp_path / 'browser.lock').is_file()
        calls.append((bridge.endpoint, bridge.session, proof))
        return {'recovered': True, 'closed_page': 'p1'}
    monkeypatch.setattr(stalled_read_recovery, 'recover_stalled_read', recover)
    proof = str(tmp_path / 'proof.json')
    assert cli.main(['--json', '--endpoint', 'ego', 'batch', 'recover-read',
                     '--session', 'owned-task', '--proof', proof]) == 0
    assert calls == [('ego', 'owned-task', proof)]
    assert json.loads(capsys.readouterr().out)['data']['recovered'] is True


def test_stalled_read_cli_rejects_non_native_endpoint(monkeypatch, capsys):
    monkeypatch.setattr(stalled_read_recovery, 'recover_stalled_read',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not run')))
    assert cli.main(['--json', '--endpoint', 'http://127.0.0.1:10086', 'batch', 'recover-read',
                     '--session', 'owned-task', '--proof', 'proof.json']) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'ego_endpoint_required'


def test_default_endpoint_is_native_ego(monkeypatch):
    # The default browser channel is Ego native; Kimi HTTP is explicit-only.
    parsed = cli.parser().parse_args(['doctor'])
    assert parsed.endpoint == 'ego'

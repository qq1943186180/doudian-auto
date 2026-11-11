import json

from doudian_auto import cli, rebaseline


def test_recovery_cli_routes_only_the_bound_task_and_proof(monkeypatch, capsys, tmp_path):
    calls = []
    def recover(task_id, proof_path):
        calls.append((task_id, proof_path))
        return {'task_id': task_id, 'state': 'needs_agent'}
    monkeypatch.setattr(rebaseline, 'recover_preflight', recover)
    proof = str(tmp_path / 'proof.json')
    assert cli.main(['--json', 'batch', 'recover-preflight', '--task-id', '14', '--proof', proof]) == 0
    assert calls == [(14, proof)]
    assert json.loads(capsys.readouterr().out)['data']['state'] == 'needs_agent'


def test_recovery_cli_requires_proof_and_never_saves(monkeypatch, capsys):
    monkeypatch.setattr(rebaseline, 'recover_preflight',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not run')))
    assert cli.main(['--json', 'batch', 'recover-preflight', '--task-id', '14']) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'invalid_arguments'

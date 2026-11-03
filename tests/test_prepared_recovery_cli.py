import json

from doudian_auto import cli, prepared_recovery


def test_recovery_cli_routes_only_the_bound_task_and_proof(monkeypatch, capsys, tmp_path):
    calls = []
    def recover(task_id, proof_path):
        calls.append((task_id, proof_path))
        return {'task_id': task_id, 'state': 'ready'}
    monkeypatch.setattr(prepared_recovery, 'recover_prepared_after_reads', recover)
    proof = str(tmp_path / 'proof.json')
    assert cli.main(['--json', 'batch', 'recover-prepared', '--task-id', '14', '--proof', proof]) == 0
    assert calls == [(14, proof)]
    assert json.loads(capsys.readouterr().out)['data']['state'] == 'ready'


def test_recovery_cli_requires_proof_and_never_saves(monkeypatch, capsys):
    monkeypatch.setattr(prepared_recovery, 'recover_prepared_after_reads',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not run')))
    assert cli.main(['--json', 'batch', 'recover-prepared', '--task-id', '14']) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'invalid_arguments'

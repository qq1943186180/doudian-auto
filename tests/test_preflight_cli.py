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
                        'report_dir': str(tmp_path)}


def test_preflight_cannot_be_changed_into_an_apply_command(monkeypatch, capsys):
    monkeypatch.setattr(preflight, 'preflight_products', lambda *a, **k: (_ for _ in ()).throw(AssertionError('must not execute')))
    assert cli.main(['--json', 'batch', 'preflight', '--product-id', '3850072900438720563', '--apply']) == 1
    result = json.loads(capsys.readouterr().out)
    assert result['error']['code'] == 'invalid_arguments'

import json

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError


@pytest.fixture(params=['agent', 'execution'])
def lease(request, tmp_path, monkeypatch):
    clock = {'now': 10000.0}
    monkeypatch.setattr(batch.time, 'time', lambda: clock['now'])
    monkeypatch.setattr(batch, 'search_knowledge', lambda facts: {'available': False, 'results': []})
    monkeypatch.setattr(batch, '_active_doudian_job_conflict', lambda *args: None)
    source = tmp_path / 'products.json'
    source.write_text(json.dumps([{'shop': 'fixture', 'product_id': '3850072900438720563'}]), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch.create_batch(source, db_path=db)
    if request.param == 'agent':
        claim = batch.claim_next('worker', db_path=db, lease_seconds=7200)
        renew, token_key, expiry_key = batch.renew_agent_task, 'lease_token', 'lease_until'
    else:
        # Browser input is irrelevant to lease ownership; create a ready queue fixture.
        conn = batch._db(db)
        conn.execute("UPDATE products SET state='ready' WHERE id=1")
        conn.close()
        claim = batch.claim_execution(1, 'worker', db_path=db, lease_seconds=7200)
        renew, token_key, expiry_key = batch.renew_execution, 'execution_token', 'execution_until'
    def read_expiry():
        conn = batch._db(db)
        value = conn.execute(f'SELECT {expiry_key} FROM products WHERE id=1').fetchone()[expiry_key]
        conn.close()
        return value
    return clock, lambda token=claim[token_key]: renew(1, 'worker', token, db_path=db), expiry_key, read_expiry


def test_default_heartbeat_does_not_shorten_long_claim(lease):
    clock, renew, key, read = lease
    initial = read()
    clock['now'] += 100
    result = renew()
    assert result[key] == read() == initial == 17200


def test_heartbeat_extends_when_its_new_deadline_is_later(lease):
    clock, renew, key, read = lease
    clock['now'] = 17000
    result = renew()
    assert result[key] == read() == 17900


def test_heartbeat_does_not_revive_expired_or_reassigned_claim(lease):
    clock, renew, key, read = lease
    initial = read()
    with pytest.raises(DoudianError):
        renew('wrong-token')
    assert read() == initial
    clock['now'] = initial + 1
    with pytest.raises(DoudianError):
        renew()
    assert read() == initial

import json

import pytest
from PIL import Image

from doudian_auto import batch
from doudian_auto.errors import DoudianError


def _product_set(tmp_path, target_version=None, product_id='3850072900438720563'):
    images = []
    for idx in range(9):
        size = (600, 600) if idx < 5 else (620, 900)
        path = tmp_path / f'asset-{product_id[-2:]}-{idx}.png'
        Image.new('RGB', size, (idx * 20, 50, 100)).save(path)
        images.append(path)
    artifacts = tmp_path / f'artifacts-{product_id[-2:]}.json'
    data = {'product_id': product_id,
        'title': '男士平角内裤纯棉中腰透气五色可选日常穿着',
        'mains': [str(p) for p in images[:5]],
        'details': [str(p) for p in images[5:]]}
    if target_version:
        data['target_version'] = target_version
    artifacts.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return product_id, artifacts


def _batch(tmp_path):
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [
        {'shop': '销霁百货', 'product_id': '3850072900438720563', 'source_title': '原商品标题'}
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    created = batch.create_batch(source, db_path=db)
    return db, created['batch_id']


def _writer_task(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db, lease_seconds=600)
    _, artifacts = _product_set(tmp_path, task['target_version'])
    batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    claim = batch.claim_execution(task['id'], 'writer', db_path=db)
    batch.record_baseline(task['id'], 'writer', claim['execution_token'], {
        'product_id': task['product_id'], 'shop': '销霁百货', 'protected_complete': True,
        'protected': {'sku': [{'price': '10', 'stock': '20'}]},
        'mains': ['old-main-' + str(i) for i in range(5)],
        'details': ['old-detail-' + str(i) for i in range(6)],
    }, db_path=db)
    return db, task, claim


def _record_nine_uploads(db, task, claim):
    for kind, slots in (('mains', range(1, 6)), ('details', range(1, 5))):
        for slot in slots:
            index = slot + (100 if kind == 'details' else 0)
            remote_key = f'png_m_{index:032x}_sx_12345_www600-600'
            batch.record_upload_mapping(task['id'], 'writer', claim['execution_token'], kind, slot,
                                        {'source_sha256': f'{slot:064x}',
                                         'remote_key': remote_key,
                                         'remote_url': f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/{remote_key}',
                                         'confirmed': True}, db_path=db)


def test_agent_claim_is_atomic_and_completion_requires_current_token(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db, lease_seconds=600)
    assert task['product_id'] == '3850072900438720563'
    assert batch.claim_next('agent-b', batch_id=batch_id, db_path=db) is None
    _, artifacts = _product_set(tmp_path, task['target_version'])
    result = batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert result['state'] == 'ready'
    assert batch.batch_status(batch_id, db_path=db)['counts'] == {'ready': 1}


def test_stale_lease_cannot_submit_assets(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db, lease_seconds=60)
    conn = batch._db(db)
    conn.execute('UPDATE products SET lease_until=0 WHERE id=?', (task['id'],))
    conn.close()
    replacement = batch.claim_next('agent-b', batch_id=batch_id, db_path=db)
    _, artifacts = _product_set(tmp_path, task['target_version'])
    with pytest.raises(DoudianError, match='领取已过期'):
        batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert replacement['lease_owner'] == 'agent-b'


def test_agent_completion_binds_assets_to_claimed_target_version(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db, lease_seconds=600)
    _, artifacts = _product_set(tmp_path, 'wrong-target-version')
    with pytest.raises(DoudianError) as mismatch:
        batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert mismatch.value.code == 'target_version_mismatch'
    _, artifacts = _product_set(tmp_path, task['target_version'])
    result = batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert result['target_version'] == task['target_version']
    assert batch.load_ready_artifacts(task['id'], db_path=db)['target_version'] == task['target_version']


def _legacy_manifest_row(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db, lease_seconds=600)
    _, artifacts = _product_set(tmp_path, task['target_version'], product_id=task['product_id'])
    batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    payload = json.loads(artifacts.read_text(encoding='utf-8'))
    payload['target_version'] = 'miaoshou-batch-20261028-v1'
    artifacts.write_text(json.dumps(payload, ensure_ascii=False), encoding='utf-8')
    conn = batch._db(db)
    conn.execute('UPDATE products SET target_version=?,artifacts_hash=? WHERE id=?',
                 ('legacy-test-version', batch._digest(artifacts), task['id']))
    conn.close()
    return db, task, artifacts


def test_legacy_ready_artifact_version_is_adopted_once_before_baseline(tmp_path):
    db, task, artifacts = _legacy_manifest_row(tmp_path)

    ready = batch.load_ready_artifacts(task['id'], db_path=db)

    assert ready['target_version'] == 'miaoshou-batch-20261028-v1'
    persisted = batch.batch_status(task['batch_id'], db_path=db)['products'][0]
    assert persisted['target_version'] == ready['target_version']
    assert persisted['state'] == 'ready'


def test_blocked_legacy_version_mismatch_recovers_only_before_any_write(tmp_path):
    db, task, artifacts = _legacy_manifest_row(tmp_path)
    conn = batch._db(db)
    conn.execute("UPDATE products SET state='blocked',last_error='target_version_mismatch' WHERE id=?",
                 (task['id'],))
    conn.close()

    recovered = batch.recover_legacy_target_version_mismatch(task['id'], db_path=db)

    assert recovered['recovered_before_write'] is True
    assert recovered['target_version'] == 'miaoshou-batch-20261028-v1'
    assert batch.batch_status(task['batch_id'], db_path=db)['products'][0]['state'] == 'ready'

    conn = batch._db(db)
    conn.execute("UPDATE products SET state='blocked',last_error='target_version_mismatch',submission_attempts=1 WHERE id=?",
                 (task['id'],))
    conn.close()
    assert batch.recover_legacy_target_version_mismatch(task['id'], db_path=db) is None
    assert batch.batch_status(task['batch_id'], db_path=db)['products'][0]['state'] == 'blocked'


def test_blocked_prewrite_task_requires_fresh_dual_baseline_proof_to_resume(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    conn = batch._db(db)
    conn.execute("UPDATE products SET state='blocked',last_error='baseline_changed' WHERE id=?",
                 (task['id'],))
    conn.close()
    batch.release_execution(task['id'], 'writer', claim['execution_token'], db_path=db)

    recovery_claim = batch.claim_execution(task['id'], 'writer-b', db_path=db)

    assert recovery_claim['prewrite_recovery'] is True
    good = {'read_only': True, 'product_id': task['product_id'],
            'baseline_sha256': recovery_claim['baseline_hash'],
            'miaoshou_matches': True, 'doudian_matches': True}
    with pytest.raises(DoudianError) as unproven:
        batch.requeue_blocked_prewrite(task['id'], 'writer-b', recovery_claim['execution_token'],
                                       {**good, 'doudian_matches': False}, db_path=db)
    assert unproven.value.code == 'prewrite_recovery_not_proven'
    assert batch.requeue_blocked_prewrite(task['id'], 'writer-b', recovery_claim['execution_token'],
                                          good, db_path=db)['state'] == 'editing'


def test_target_slots_reset_details_to_one_through_four():
    assets = ([{'kind': 'main', 'path': f'main-{i}'} for i in range(5)] +
              [{'kind': 'detail', 'path': f'detail-{i}'} for i in range(4)])

    assert batch._target_asset_slots(assets) == (
        [('mains', i, f'main-{i - 1}') for i in range(1, 6)] +
        [('details', i, f'detail-{i - 1}') for i in range(1, 5)])


def test_miaoshou_protected_3x4_images_compare_by_asset_identity():
    old = {'status': 0, 'mainPic34': [
        'https://p3-aio.example/obj/ecom-shop-material/jpeg_m_same_sx_100_www600-800?old=1'],
        'mainImageThreeToFour': ['https://p3-aio.example/obj/ecom-shop-material/jpeg_m_same_sx_100_www600-800'],
        'checkStatus': 1, 'startSaleType': 0}
    current = {'status': 0, 'mainPic34': [
        'https://p6-aio.example/img/ecom-shop-material/jpeg_m_same_sx_100_www600-800?new=2'],
        'mainImageThreeToFour': ['https://p6-aio.example/img/ecom-shop-material/jpeg_m_same_sx_100_www600-800'],
        'checkStatus': 7, 'startSaleType': 0}

    assert batch._miaoshou_protected_matches(current, old) is True
    current['mainImageThreeToFour'] = ['https://p6-aio.example/img/ecom-shop-material/jpeg_m_changed_sx_100_www600-800']
    assert batch._miaoshou_protected_matches(current, old) is False
    current['mainImageThreeToFour'] = old['mainImageThreeToFour']
    current['startSaleType'] = 1
    assert batch._miaoshou_protected_matches(current, old) is False


def test_title_repair_precondition_allows_only_review_and_shelf_mode_deltas():
    baseline = {'status': 0, 'draftStatus': 0, 'checkStatus': 1, 'startSaleType': 0,
                'freightId': 7, 'mainPic34': ['https://img.example/a.jpg']}
    current = {'status': 0, 'draftStatus': 0, 'checkStatus': 7, 'startSaleType': 1,
               'freightId': 7, 'mainPic34': ['https://img.example/a.jpg']}

    assert batch._miaoshou_title_repair_fields_match(current, baseline) is True
    current['freightId'] = 8
    assert batch._miaoshou_title_repair_fields_match(current, baseline) is False


def _accepted_mismatch_title_repair_task(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    readback_hash = 'a' * 64
    conn = batch._db(db)
    mappings = json.loads(conn.execute('SELECT upload_map_json FROM products WHERE id=?',
                                       (task['id'],)).fetchone()[0])
    for mapping in mappings:
        mapping['asset_state'] = 'permanent'
    conn.execute('''UPDATE products SET state='blocked',submission_state='accepted',
                    submission_attempts=1,last_error='readback_mismatch',readback_json=?,
                    readback_hash=?,upload_map_json=? WHERE id=?''',
                 (json.dumps({'read_only': True}), readback_hash, json.dumps(mappings), task['id']))
    conn.close()
    row = batch.batch_status(task['batch_id'], db_path=db)['products'][0]
    proof = {
        'read_only': True, 'images_match': True, 'detail_tail_match': True,
        'official_protected_match': True, 'miao_other_fields_match': True,
        'shelf_status_matches': True, 'shelf_mode_matches_original': True,
        'current_title': 'old title', 'target_title': 'new title',
        'previous_readback_sha256': readback_hash,
        'product_id': row['product_id'], 'shop': row['shop'],
        'target_version': row['target_version'], 'manifest_sha256': claim['artifacts_hash'],
    }
    return db, task, claim, proof


def test_title_repair_requires_original_shelf_mode_before_save(tmp_path):
    db, task, claim, proof = _accepted_mismatch_title_repair_task(tmp_path)

    with pytest.raises(DoudianError) as unsafe:
        batch.begin_title_repair_submission(
            task['id'], 'writer', claim['execution_token'],
            {**proof, 'shelf_mode_matches_original': False}, db_path=db)

    assert unsafe.value.code == 'title_repair_unsafe'
    row = batch.batch_status(task['batch_id'], db_path=db)['products'][0]
    assert row['state'] == 'blocked'
    assert row['submission_attempts'] == 1


def test_title_repair_submission_is_durable_and_limited_to_one_repair(tmp_path):
    db, task, claim, proof = _accepted_mismatch_title_repair_task(tmp_path)

    intent = batch.begin_title_repair_submission(
        task['id'], 'writer', claim['execution_token'], proof, db_path=db)

    assert intent['repair_kind'] == 'title-only'
    assert intent['attempt'] == 2
    assert intent['save_click_count'] == 1
    row = batch.batch_status(task['batch_id'], db_path=db)['products'][0]
    assert row['state'] == 'submitting'
    assert row['submission_state'] == 'unknown'
    assert row['submission_attempts'] == 2


def test_artifact_validator_rejects_duplicates_and_wrong_product(tmp_path):
    product_id, artifacts = _product_set(tmp_path)
    data = json.loads(artifacts.read_text(encoding='utf-8'))
    data['mains'][1] = data['mains'][0]
    artifacts.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(DoudianError, match='重复'):
        batch.validate_agent_artifacts(artifacts, product_id)
    with pytest.raises(DoudianError, match='商品ID'):
        batch.validate_agent_artifacts(artifacts, '3848316916011762046')


def test_unknown_submission_cannot_return_to_write_state(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    batch.record_submission_result(task['id'], 'writer', claim['execution_token'],
                                   {'state': 'unknown', 'error': 'timeout'}, db_path=db)
    with pytest.raises(DoudianError, match='只读核查'):
        batch.set_execution_state(task['id'], 'editing', db_path=db)
    with pytest.raises(DoudianError) as blocked_again:
        batch.set_execution_state(task['id'], 'blocked', submission_state='failed', db_path=db)
    assert blocked_again.value.code == 'invalid_transition'
    persisted = batch.batch_status(db_path=db)['products'][0]
    assert persisted['state'] == 'blocked'
    assert persisted['submission_state'] == 'unknown'


def test_execution_claim_is_exclusive_and_expired_claim_survives_restart(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    assert batch.claim_execution(task['id'], 'writer-b', db_path=db) is None
    conn = batch._db(db)
    conn.execute('UPDATE products SET execution_until=0 WHERE id=?', (task['id'],))
    conn.close()
    reopened = batch.claim_execution(task['id'], 'writer-b', db_path=db)
    assert reopened['execution_owner'] == 'writer-b'
    assert reopened['execution_token'] != claim['execution_token']


def test_partial_upload_mapping_blocks_save_and_confirmed_slots_are_reusable(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    remote_key = 'png_m_00000000000000000000000000000001_sx_12345_www600-600'
    batch.record_upload_mapping(task['id'], 'writer', claim['execution_token'], 'mains', 1,
                                {'source_sha256': f'{1:064x}', 'remote_key': remote_key,
                                 'remote_url': f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/{remote_key}',
                                 'confirmed': True}, db_path=db)
    # Repeating the same confirmed mapping is idempotent and does not lose its slot.
    batch.record_upload_mapping(task['id'], 'writer', claim['execution_token'], 'mains', 1,
                                {'source_sha256': f'{1:064x}', 'remote_key': remote_key,
                                 'remote_url': f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/{remote_key}',
                                 'confirmed': True}, db_path=db)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    with pytest.raises(DoudianError) as incomplete:
        batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    assert incomplete.value.code == 'uploads_incomplete'
    _record_nine_uploads(db, task, claim)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    intent = batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    assert intent['save_click_count'] == 1
    assert batch.batch_status(db_path=db)['products'][0]['submission_attempts'] == 1


def test_temp_upload_url_is_recorded_as_staged_not_permanent(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    temp_url = 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/a.png?dy'
    mapping = {'slot': 'mains:1', 'source_sha256': f'{1:064x}', 'remote_key': temp_url,
               'remote_url': temp_url, 'asset_state': 'staged', 'confirmed': True}
    assert batch._confirmed_upload_mapping(mapping)
    assert batch.is_permanent_material_url(temp_url) is False
    batch.record_upload_mapping(task['id'], 'writer', claim['execution_token'], 'mains', 1,
                                mapping, db_path=db)
    conn = batch._db(db)
    stored = json.loads(conn.execute('SELECT upload_map_json FROM products WHERE id=?',
                                     (task['id'],)).fetchone()[0])
    conn.close()
    assert stored[0]['asset_state'] == 'staged'


def test_temp_url_without_readback_address_is_not_recorded(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    with pytest.raises(DoudianError) as caught:
        batch.record_upload_mapping(task['id'], 'writer', claim['execution_token'], 'mains', 1,
                                    {'source_sha256': f'{1:064x}',
                                     'remote_key': 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/a.png?dy',
                                     'remote_url': '', 'confirmed': True}, db_path=db)
    assert caught.value.code == 'invalid_upload_mapping'
    conn = batch._db(db)
    row = conn.execute('SELECT upload_map_json FROM products WHERE id=?', (task['id'],)).fetchone()
    conn.close()
    assert row[0] == '[]'


def test_verified_mapping_replaces_legacy_temp_url_and_records_migration(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    legacy = [{'slot': 'mains:1', 'source_sha256': f'{1:064x}',
               'remote_key': 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/a.png?dy',
               'remote_url': '', 'confirmed': True}]
    conn = batch._db(db)
    conn.execute('UPDATE products SET upload_map_json=? WHERE id=?',
                 (json.dumps(legacy), task['id']))
    conn.close()

    remote_key = 'png_m_00000000000000000000000000000001_sx_12345_www600-600'
    batch.record_upload_mapping(task['id'], 'writer', claim['execution_token'], 'mains', 1,
                                {'source_sha256': f'{1:064x}', 'remote_key': remote_key,
                                 'remote_url': f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/{remote_key}',
                                 'confirmed': True}, db_path=db)

    conn = batch._db(db)
    mappings = json.loads(conn.execute('SELECT upload_map_json FROM products WHERE id=?',
                                       (task['id'],)).fetchone()[0])
    events = []
    for row in conn.execute('SELECT detail FROM product_events WHERE task_id=?', (task['id'],)).fetchall():
        try:
            value = json.loads(row[0])
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            events.append(value)
    conn.close()
    assert len(mappings) == 1 and mappings[0]['remote_key'] == remote_key
    assert any(event.get('event') == 'legacy_untrusted_upload_mapping_replaced' for event in events)


def test_begin_submission_rejects_a_legacy_temp_mapping_even_if_marked_confirmed(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    conn = batch._db(db)
    mappings = json.loads(conn.execute('SELECT upload_map_json FROM products WHERE id=?',
                                       (task['id'],)).fetchone()[0])
    mappings[0]['remote_key'] = 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/a.png?dy'
    mappings[0]['remote_url'] = ''
    conn.execute('UPDATE products SET upload_map_json=? WHERE id=?',
                 (json.dumps(mappings), task['id']))
    conn.close()
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    with pytest.raises(DoudianError) as caught:
        batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    assert caught.value.code == 'uploads_incomplete'


def test_staged_urls_finalize_only_from_matching_permanent_dual_readback(tmp_path):
    baseline = {'mains': [f'old-main-{i}' for i in range(5)],
                'details': [f'old-detail-{i}' for i in range(6)]}
    main_urls, detail_urls, staged = [], [], []
    for kind, slots, offset, output in (('mains', range(1, 6), 0, main_urls),
                                        ('details', range(1, 5), 100, detail_urls)):
        for slot in slots:
            index = offset + slot
            key = f'png_m_{index:032x}_sx_12345_www600-600'
            output.append(f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/{key}')
            temp = f'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/{kind}-{slot}.png?dy'
            staged.append({'slot': f'{kind}:{slot}', 'source_sha256': f'{index:064x}',
                           'remote_key': temp, 'remote_url': temp, 'asset_state': 'staged',
                           'confirmed': True})
    details_after = detail_urls + baseline['details'][4:]
    miao = {'mains': main_urls, 'details': details_after}
    official = {'mains': list(main_urls), 'details': list(details_after)}

    final = batch._finalize_target_mappings(baseline, miao, official, staged)

    assert len(final) == 9
    assert all(item['asset_state'] == 'permanent' for item in final)
    assert [item['remote_key'] for item in final[:5]] == [
        batch.resource_key(url) for url in main_urls]
    official['mains'][0] = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/' + \
        'png_m_ffffffffffffffffffffffffffffffff_sx_12345_www600-600'
    with pytest.raises(DoudianError) as mismatch:
        batch._finalize_target_mappings(baseline, miao, official, staged)
    assert mismatch.value.code == 'final_asset_not_permanent'


def test_successful_dual_readback_promotes_staged_mapping_to_permanent(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    for kind, slots, offset in (('mains', range(1, 6), 0), ('details', range(1, 5), 100)):
        for slot in slots:
            index = offset + slot
            temp_url = f'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/{kind}-{slot}.png?dy'
            batch.record_upload_mapping(task['id'], 'writer', claim['execution_token'], kind, slot,
                                        {'source_sha256': f'{index:064x}', 'remote_key': temp_url,
                                         'remote_url': temp_url, 'asset_state': 'staged',
                                         'confirmed': True}, db_path=db)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    batch.record_submission_result(task['id'], 'writer', claim['execution_token'],
                                   {'state': 'accepted'}, db_path=db)
    final = []
    for kind, slots, offset in (('mains', range(1, 6), 0), ('details', range(1, 5), 100)):
        for slot in slots:
            index = offset + slot
            key = f'png_m_{index:032x}_sx_12345_www600-600'
            final.append({'slot': f'{kind}:{slot}', 'source_sha256': f'{index:064x}',
                          'remote_key': key,
                          'remote_url': f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/{key}',
                          'asset_state': 'permanent', 'confirmed': True})
    page = {'product_id': task['product_id'], 'shop': task['shop'], 'complete': True,
            'matches_target': True, 'protected_match': True,
            'shelf_mode_matches_original': True}
    result = batch.record_execution_readback(
        task['id'], 'writer', claim['execution_token'],
        {'read_only': True, 'miaoshou': dict(page), 'doudian': dict(page),
         'final_asset_mappings': final}, db_path=db)
    assert result['state'] == 'verified'
    conn = batch._db(db)
    stored = json.loads(conn.execute('SELECT upload_map_json FROM products WHERE id=?',
                                     (task['id'],)).fetchone()[0])
    conn.close()
    assert len(stored) == 9
    assert all(item['asset_state'] == 'permanent' for item in stored)
    assert {item['remote_key'] for item in stored} == {item['remote_key'] for item in final}


def test_staged_mapping_cannot_be_verified_without_final_asset_readback(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    # Change one already-complete permanent mapping back to a staged temp URL.
    conn = batch._db(db)
    mappings = json.loads(conn.execute('SELECT upload_map_json FROM products WHERE id=?',
                                       (task['id'],)).fetchone()[0])
    temp_url = 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/mains-1.png?dy'
    mappings[0].update(remote_key=temp_url, remote_url=temp_url, asset_state='staged')
    conn.execute('UPDATE products SET upload_map_json=? WHERE id=?',
                 (json.dumps(mappings), task['id']))
    conn.close()
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    batch.record_submission_result(task['id'], 'writer', claim['execution_token'],
                                   {'state': 'accepted'}, db_path=db)
    page = {'product_id': task['product_id'], 'shop': task['shop'], 'complete': True,
            'matches_target': True, 'protected_match': True,
            'shelf_mode_matches_original': True}
    result = batch.record_execution_readback(
        task['id'], 'writer', claim['execution_token'],
        {'read_only': True, 'miaoshou': dict(page), 'doudian': dict(page)}, db_path=db)
    assert result['state'] == 'blocked'
    assert result['matches'] is False


def test_readback_cannot_verify_if_post_review_shelf_mode_changed(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    batch.record_submission_result(task['id'], 'writer', claim['execution_token'],
                                   {'state': 'accepted'}, db_path=db)
    page = {'product_id': task['product_id'], 'shop': '销霁百货', 'complete': True,
            'matches_target': True, 'protected_match': True,
            'shelf_mode_matches_original': False}

    result = batch.record_execution_readback(
        task['id'], 'writer', claim['execution_token'],
        {'read_only': True, 'miaoshou': dict(page), 'doudian': dict(page)}, db_path=db)

    assert result['state'] == 'blocked'
    assert result['matches'] is False


def test_readback_detects_changed_sku_values(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    batch.record_submission_result(task['id'], 'writer', claim['execution_token'],
                                   {'state': 'accepted'}, db_path=db)
    page = {'product_id': task['product_id'], 'shop': '销霁百货', 'complete': True,
            'matches_target': True, 'protected_match': True,
            'shelf_mode_matches_original': True}
    evidence = {'read_only': True, 'miaoshou': dict(page), 'doudian': dict(page)}
    evidence['doudian']['protected_match'] = False
    result = batch.record_execution_readback(task['id'], 'writer', claim['execution_token'],
                                             evidence, db_path=db)
    assert result['state'] == 'blocked'
    assert result['matches'] is False


def test_unknown_save_can_only_be_closed_by_complete_dual_readback(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    batch.record_submission_result(task['id'], 'writer', claim['execution_token'],
                                   {'state': 'unknown', 'error': 'response_lost'}, db_path=db)
    page = {'product_id': task['product_id'], 'shop': '销霁百货', 'complete': True,
            'matches_target': True, 'protected_match': True,
            'shelf_mode_matches_original': True}
    result = batch.record_execution_readback(task['id'], 'writer', claim['execution_token'],
                                             {'read_only': True, 'miaoshou': dict(page),
                                              'doudian': dict(page)}, db_path=db)
    assert result['state'] == 'verified'
    assert result['submission_state'] == 'verified_by_readback'


def test_unknown_save_claim_is_readback_only_and_cannot_resume_uploads(tmp_path):
    db, task, claim = _writer_task(tmp_path)
    _record_nine_uploads(db, task, claim)
    batch.set_execution_state(task['id'], 'uploaded', db_path=db)
    batch.begin_submission(task['id'], 'writer', claim['execution_token'], db_path=db)
    batch.record_submission_result(task['id'], 'writer', claim['execution_token'],
                                   {'state': 'unknown', 'error': 'response_lost'}, db_path=db)
    conn = batch._db(db)
    conn.execute('UPDATE products SET execution_until=0 WHERE id=?', (task['id'],))
    conn.close()
    readback_claim = batch.claim_execution(task['id'], 'writer-readback', db_path=db)
    assert readback_claim['state'] == 'blocked'
    assert readback_claim['submission_state'] == 'unknown'
    with pytest.raises(DoudianError) as cannot_edit:
        batch.record_upload_mapping(task['id'], 'writer-readback', readback_claim['execution_token'],
                                    'mains', 1, {'source_sha256': f'{1:064x}',
                                                 'remote_key': 'new-image', 'confirmed': True}, db_path=db)
    assert cannot_edit.value.code == 'invalid_transition'


def test_ready_artifact_manifest_is_rehashed_before_use(tmp_path):
    db, batch_id = _batch(tmp_path)
    task = batch.claim_next('agent-a', batch_id=batch_id, db_path=db)
    _, artifacts = _product_set(tmp_path, task['target_version'])
    batch.complete_agent_task(task['id'], 'agent-a', task['lease_token'], artifacts, db_path=db)
    assert batch.load_ready_artifacts(task['id'], db_path=db)['manifest']['product_id'] == task['product_id']
    artifacts.write_text(artifacts.read_text(encoding='utf-8') + ' ', encoding='utf-8')
    with pytest.raises(DoudianError, match='发生变化'):
        batch.load_ready_artifacts(task['id'], db_path=db)


def test_one_product_in_two_batches_is_quarantined(tmp_path):
    db, _ = _batch(tmp_path)
    source = tmp_path / 'products-2.json'
    source.write_text(json.dumps({'products': [
        {'shop': '销霁百货', 'product_id': '3850072900438720563'}
    ]}, ensure_ascii=False), encoding='utf-8')
    created = batch.create_batch(source, db_path=db)
    assert created['blocked'] == 1
    assert batch.batch_status(created['batch_id'], db_path=db)['counts'] == {'blocked': 1}


def test_agent_preparation_parallelism_is_capped_at_three(tmp_path):
    source = tmp_path / 'four-products.json'
    source.write_text(json.dumps({'products': [
        {'shop': '测试店', 'product_id': f'385007290043872056{i}'} for i in range(1, 5)
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch_id = batch.create_batch(source, db_path=db)['batch_id']
    assert batch.claim_next('agent-1', batch_id=batch_id, db_path=db)
    assert batch.claim_next('agent-2', batch_id=batch_id, db_path=db)
    assert batch.claim_next('agent-3', batch_id=batch_id, db_path=db)
    assert batch.claim_next('agent-4', batch_id=batch_id, db_path=db) is None


def test_batch_continues_after_one_product_ui_exception(tmp_path, monkeypatch):
    ids = ['3850072900438720563', '3850072900438720564']
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [
        {'shop': '销霁百货', 'product_id': pid, 'source_title': 'original'} for pid in ids
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch_id = batch.create_batch(source, db_path=db)['batch_id']
    for index, pid in enumerate(ids):
        owner = f'agent-{index}'
        task = batch.claim_next(owner, batch_id=batch_id, product_id=pid, db_path=db)
        _, assets = _product_set(tmp_path, task['target_version'], product_id=pid)
        batch.complete_agent_task(task['id'], owner, task['lease_token'], assets, db_path=db)

    protected_sections = [
        {'section': name, 'observation': 'ready', 'inputs': [], 'selections': [],
         'static_fields': [], 'images': []}
        for name in ('基础信息', '价格库存', '服务与履约')
    ]
    baseline = lambda pid: {
        'product_id': pid, 'shop': '销霁百货', 'shop_confirmed': True,
        'title': 'original', 'mains': [f'main-{i}' for i in range(5)],
        'details': [f'detail-{i}' for i in range(4)], 'protected': protected_sections,
        'draft_loaded': False, 'rejected': False,
    }

    class FakeBridge:
        instances = []
        def __init__(self, *args, **kwargs):
            self.session = kwargs.get('session')
            self.commands = []
            self.instances.append(self)
        def require_ready(self):
            return None
        def command(self, action, args=None):
            self.commands.append(action)
            return {'success': True, 'closed': 0}

    class FakeEditor:
        def __init__(self, bridge):
            pass

    class FakeMiaoshou:
        def __init__(self, bridge, shop, **kwargs):
            self.product_id = None
        def open_product(self, product_id, *, fresh=True):
            self.product_id = product_id
        def read_product(self, product_id):
            return {**baseline(product_id), 'protected': {'specPrices': [{'price': '10'}], 'status': 0,
                                                          'startSaleType': 0},
                    'protected_complete': True}
        def require_shelf_mode_preservable(self, expected_mode):
            assert expected_mode == 0
            return {'preservable': True, 'mode': 0}
        def fill_title(self, product_id, title):
            raise DoudianError('fake_ui_failure', 'fake pre-save UI failure')

    monkeypatch.setattr('doudian_auto.bridge.Bridge', FakeBridge)
    monkeypatch.setattr('doudian_auto.editor.Editor', FakeEditor)
    monkeypatch.setattr('doudian_auto.miaoshou_editor.MiaoshouEditor', FakeMiaoshou)
    monkeypatch.setattr(batch, '_stable_doudian_snapshot', lambda editor, identity: baseline(identity['product_id']))
    result = batch.run_batch('http://127.0.0.1:10086', batch_id=batch_id, product_ids=ids,
                             limit=2, owner='test-writer', db_path=db)
    assert [item['product_id'] for item in result['run']] == ids
    assert all(item['state'] == 'editing' and item['resumable'] is True for item in result['run']), result
    assert FakeBridge.instances[0].commands == ['close_session', 'close_session']
    assert result['browser_session_cleanup'] == {'attempted': True, 'closed': 0}
    assert batch.batch_status(batch_id, db_path=db)['counts'] == {'editing': 2}


def test_batch_shelf_mode_preflight_stops_before_any_edit_or_upload(tmp_path, monkeypatch):
    pid = '3850072900438720565'
    source = tmp_path / 'products.json'
    source.write_text(json.dumps({'products': [
        {'shop': '销霁百货', 'product_id': pid, 'source_title': 'original'}
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch_id = batch.create_batch(source, db_path=db)['batch_id']
    task = batch.claim_next('asset-agent', batch_id=batch_id, product_id=pid, db_path=db)
    _, assets = _product_set(tmp_path, task['target_version'], product_id=pid)
    batch.complete_agent_task(task['id'], 'asset-agent', task['lease_token'], assets, db_path=db)

    def snapshot(product_id):
        return {'product_id': product_id, 'shop': '销霁百货', 'shop_confirmed': True,
                'title': 'original', 'mains': [f'old-main-{i}' for i in range(5)],
                'details': [f'old-detail-{i}' for i in range(4)],
                'protected': [], 'draft_loaded': False, 'rejected': False}

    class FakeBridge:
        def __init__(self, *args, **kwargs):
            self.commands = []
        def require_ready(self):
            return None
        def command(self, action, args=None):
            self.commands.append(action)
            return {'success': True, 'closed': 0}

    class FakeEditor:
        def __init__(self, bridge):
            pass

    class FakeMiaoshou:
        writes = []
        def __init__(self, bridge, shop, **kwargs):
            pass
        def open_product(self, product_id, *, fresh=True):
            return None
        def read_product(self, product_id):
            return {'product_id': product_id, 'shop': '销霁百货', 'title': 'original',
                    'mains': [f'old-main-{i}' for i in range(5)],
                    'details': [f'old-detail-{i}' for i in range(4)],
                    'protected': {'specPrices': [{'price': '10'}], 'status': 0, 'startSaleType': 0},
                    'protected_complete': True}
        def require_shelf_mode_preservable(self, expected_mode):
            assert expected_mode == 0
            raise DoudianError('miaoshou_shelf_mode_not_editable', 'missing shelf mode control')
        def fill_title(self, product_id, title):
            self.writes.append(('title', product_id, title))
        def replace_slot(self, *args, **kwargs):
            self.writes.append(('image', args))
        def click_save_once(self):
            self.writes.append(('save',))
            raise AssertionError('preflight must block save')

    monkeypatch.setattr('doudian_auto.bridge.Bridge', FakeBridge)
    monkeypatch.setattr('doudian_auto.editor.Editor', FakeEditor)
    monkeypatch.setattr('doudian_auto.miaoshou_editor.MiaoshouEditor', FakeMiaoshou)
    monkeypatch.setattr(batch, '_stable_doudian_snapshot', lambda editor, identity: snapshot(identity['product_id']))

    result = batch.run_batch('http://127.0.0.1:10086', batch_id=batch_id,
                             product_ids=[pid], limit=1, owner='test-writer', db_path=db)

    assert result['run'][0]['reason'] == 'miaoshou_shelf_mode_not_editable'
    assert result['run'][0]['state'] == 'ready'
    assert result['run'][0]['resumable'] is True
    assert FakeMiaoshou.writes == []
    current = batch.batch_status(batch_id, db_path=db)['products'][0]
    assert current['submission_state'] == 'not_attempted'
    assert current['submission_attempts'] == 0


def test_acceptance_results_include_only_persisted_dual_readback_verified_products(tmp_path):
    source = tmp_path / 'products.json'
    product_ids = ['3848319372858884337', '3848324080143040538', '3848322422084337743']
    source.write_text(json.dumps({'products': [
        {'shop': '销霁百货', 'product_id': pid, 'source_title': 'original'} for pid in product_ids
    ]}, ensure_ascii=False), encoding='utf-8')
    db = tmp_path / 'queue.sqlite3'
    batch.create_batch(source, db_path=db)
    conn = batch._db(db)
    try:
        conn.execute("UPDATE products SET state='verified',readback_hash=? WHERE product_id=?",
                     ('a' * 64, product_ids[0]))
        conn.execute("UPDATE products SET state='blocked',readback_hash=? WHERE product_id=?",
                     ('b' * 64, product_ids[1]))
        conn.execute("UPDATE products SET state='verified',readback_hash=NULL WHERE product_id=?",
                     (product_ids[2],))
    finally:
        conn.close()

    results = batch.verified_acceptance_results([*product_ids, product_ids[0]], db_path=db)

    assert results == [{'product_id': product_ids[0], 'state': 'verified',
                        'readback_sha256': 'a' * 64}]


def test_batch_resume_uses_readback_only_before_writer_acceptance(tmp_path, monkeypatch, capsys):
    import doudian_auto.cli as cli

    db, batch_id = _batch(tmp_path)
    task = batch.batch_status(batch_id, db_path=db)['products'][0]
    conn = batch._db(db)
    try:
        conn.execute("UPDATE products SET state='blocked',submission_state='accepted',"
                     "submission_attempts=1,last_error='readback_mismatch' WHERE id=?",
                     (task['id'],))
    finally:
        conn.close()
    monkeypatch.setattr(batch, 'DB_PATH', db)
    monkeypatch.setattr(batch, 'execution_readiness',
                        lambda endpoint: {'writer_ready': False, 'reason': 'acceptance pending'})
    calls = []
    monkeypatch.setattr(batch, 'run_batch', lambda *args, **kwargs:
                        calls.append((args, kwargs)) or {'run': []})

    exit_code = cli.main(['--json', 'batch', 'resume', '--apply', '--batch-id', batch_id])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload['data']['readback_only'] is True
    assert payload['data']['writer_ready'] is False
    assert len(calls) == 1
    assert calls[0][1]['readback_only'] is True
    assert calls[0][1]['resume_only'] is True
    assert calls[0][1]['product_ids'] == [task['product_id']]


def test_batch_resume_without_writer_or_readback_does_not_run_browser(tmp_path, monkeypatch, capsys):
    import doudian_auto.cli as cli

    db, batch_id = _batch(tmp_path)
    monkeypatch.setattr(batch, 'DB_PATH', db)
    monkeypatch.setattr(batch, 'execution_readiness',
                        lambda endpoint: {'writer_ready': False, 'reason': 'acceptance pending'})
    calls = []
    monkeypatch.setattr(batch, 'run_batch', lambda *args, **kwargs: calls.append((args, kwargs)))

    exit_code = cli.main(['--json', 'batch', 'resume', '--apply', '--batch-id', batch_id])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload['error']['code'] == 'writer_not_accepted'
    assert calls == []

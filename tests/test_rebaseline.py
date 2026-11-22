import json

import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.rebaseline import rebaseline_external
from doudian_auto.visual_review import file_hash
from test_preflight import queue, _snapshot


@pytest.mark.parametrize('mode', ['valid', 'unknown', 'attempted', 'missing', 'changed', 'price', 'unresolved',
                                  'saved_false', 'verified_readback', 'unknown_save',
                                  'saved_none', 'saved_negative', 'saved_str_zero', 'saved_no_counter',
                                  'uploads_started', 'status_conflict', 'status_unknown_pair'])
def test_external_rebaseline_requires_resolved_history_and_full_dual_read(queue, tmp_path, mode):
    # Historical agents wrote the same conclusion under different names. These shapes are
    # the ones seen in real queue data, plus the values a sloppy history could carry; only
    # `saved_false` and `verified_readback` may resolve a row.
    shapes = {
        'saved_false': {'phase': 'upload_unknown', 'saved': False, 'saveCount': 0},
        'verified_readback': {'stage': 'verified', 'submission_state': 'verified_by_readback'},
        'unknown_save': {'stage': 'submitting', 'submission_status': 'unknown', 'saveAttempts': 1},
        # A counter that is absent, null, negative or a string is not a zero.
        'saved_none': {'phase': 'upload_unknown', 'saved': False, 'saveCount': None},
        'saved_negative': {'phase': 'upload_unknown', 'saved': False, 'saveCount': -1},
        'saved_str_zero': {'phase': 'upload_unknown', 'saved': False, 'saveCount': '0'},
        'saved_no_counter': {'phase': 'upload_unknown', 'saved': False},
        # An upload that started leaves assets behind even when no save was recorded.
        'uploads_started': {'phase': 'upload_unknown', 'saved': False, 'saveCount': 0,
                            'saveAttempts': 0, 'uploadsStarted': True},
        # One status field must not outvote another, and "unknown" wins any tie.
        'status_conflict': {'stage': 'verified', 'submission_status': 'accepted',
                            'submission_state': 'unknown'},
        'status_unknown_pair': {'stage': 'verified', 'submission_status': 'unknown',
                                'submission_state': 'verified_by_readback'},
    }
    row = queue.rows[0]
    pid = row['product_id']
    history = tmp_path / 'history.json'
    body = {'product_id': pid, 'phase': 'editing', 'submission_status': 'not_attempted'}
    if mode in shapes:
        # Replace rather than merge: a leftover submission_status would shadow
        # submission_state and make this shape test the wrong thing.
        body = {'product_id': pid, **shapes[mode]}
    history.write_text(json.dumps(body))
    batch.reconcile_observation(history, shop=row['shop'], db_path=queue.db)
    official = _snapshot(row)
    sku = official['sku_evidence']['rows'][0]
    miao = {k: official[k] for k in ('product_id', 'title', 'mains', 'details')}
    miao.update(shop=row['shop'], protected_complete=True, protected={'status': 1,
        'specPrices': [{'skuId': sku['sku_id'], 'specDetailIds': sku['spec_ids'],
                       'price': sku['price'], 'stockNum': sku['stock'],
                       'stepStockNum': sku['step_stock'], 'code': sku['code'], 'skuStatus': sku['enabled']}]})
    if mode == 'price':
        miao['protected']['specPrices'][0]['price'] = '999.00'
    proof = {k: row[k] for k in ('product_id', 'shop', 'target_version')}
    resolution = {'unresolved': 'unknown', 'verified_readback': 'prior_revision_confirmed'
                  }.get(mode, 'no_save_attempted')
    proof.update(read_only=True, reviewer='test-reviewer', resolved_observations=[{
        'evidence': {'path': str(history), 'sha256': file_hash(history)},
        'resolution': resolution,
        'reason': 'No save input in historical observation; fresh server baseline recovered.'}])
    for key, data in (('miaoshou', miao), ('doudian', official)):
        path = tmp_path / (key + '.json')
        path.write_text(json.dumps(data), encoding='utf-8')
        proof[key] = {'path': str(path), 'sha256': file_hash(path)}
    if mode == 'missing':
        del proof['doudian']
    if mode == 'changed':
        history.write_text('{}')
    conn = batch._db(queue.db)
    if mode == 'unknown':
        conn.execute("UPDATE products SET submission_state='unknown' WHERE id=?", (row['id'],))
    if mode == 'attempted':
        conn.execute('UPDATE products SET submission_attempts=1 WHERE id=?', (row['id'],))
    conn.close()
    path = tmp_path / 'proof.json'
    path.write_text(json.dumps(proof), encoding='utf-8')
    succeeds = mode in ('valid', 'saved_false', 'verified_readback')
    if succeeds:
        result = rebaseline_external(row['id'], path, db_path=queue.db)
        assert result['state'] == 'needs_agent'
        assert result['target_version'] == row['target_version']
    else:
        with pytest.raises(DoudianError):
            rebaseline_external(row['id'], path, db_path=queue.db)
    conn = batch._db(queue.db)
    final = dict(conn.execute('SELECT * FROM products WHERE id=?', (row['id'],)).fetchone())
    assert final['state'] == ('needs_agent' if succeeds else 'blocked')
    assert conn.execute('SELECT count(*) FROM external_observations WHERE task_id=?', (row['id'],)).fetchone()[0] == 1
    assert final['submission_attempts'] == (1 if mode == 'attempted' else 0)
    conn.close()


@pytest.mark.parametrize('mode', ['valid','unknown','attempted','wrong_error','wrong_binding','baseline','artifact','intent','mapping','lease','history','missing_attribute','image_order','price','stale'])
def test_missing_attribute_recovery_only_reopens_untouched_proven_task(queue,tmp_path,mode):
    from doudian_auto.rebaseline import recover_preflight
    import time,os
    row=queue.rows[0]
    error='preflight_exception: required_attributes_missing; missing installation'
    conn=batch._db(queue.db)
    conn.execute("UPDATE products SET state='blocked',last_error=? WHERE id=?",(error,row['id']))
    updates={'unknown':("submission_state",'unknown'),'attempted':('submission_attempts',1),'wrong_error':('last_error','visual_quality_failed_after_retry'),'baseline':('baseline_json','{}'),'artifact':('artifacts_path','asset.json'),'intent':('submission_intent_json','{}'),'mapping':('upload_map_json','[{}]'),'lease':('lease_until',time.time()+60)}
    if mode in updates:
        key,value=updates[mode];conn.execute(f'UPDATE products SET {key}=? WHERE id=?',(value,row['id']))
    if mode=='history':conn.execute('INSERT INTO external_observations VALUES(?,?,?,?)',(row['id'],'history.json','x',time.time()))
    conn.close()
    official=_snapshot(row);sku=official['sku_evidence']['rows'][0]
    miao={k:official[k] for k in ('product_id','title','mains','details')}
    miao.update(shop=row['shop'],protected_complete=True,protected={'status':1,'specPrices':[{'skuId':sku['sku_id'],'specDetailIds':sku['spec_ids'],'price':sku['price'],'stockNum':sku['stock'],'stepStockNum':sku['step_stock'],'code':sku['code'],'skuStatus':sku['enabled']}]})
    miao['protected'].update({'root.categoryId':123,'root.brandName':'无品牌','freightId':1,
        'draftStatus':0,'checkStatus':1,'specPics':[], 'mainImageThreeToFour':[],
        'whiteBackGroundPicUrl':'','afterSaleService':{}})
    if mode=='missing_attribute':official['required_attributes']['missing']=['安装方式']
    if mode=='image_order':miao['mains']=list(reversed(miao['mains']))
    if mode=='price':miao['protected']['specPrices'][0]['price']='999'
    proof={k:row[k] for k in ('product_id','shop','target_version')}
    proof.update(read_only=True,reviewer='reviewer',prior_error='other' if mode=='wrong_binding' else error)
    for key,data in [('miaoshou',miao),('doudian',official)]:
        path=tmp_path/(key+'.json');path.write_text(json.dumps(data),encoding='utf-8')
        proof[key]={'path':str(path),'sha256':file_hash(path)}
        if mode=='stale':os.utime(path,(time.time()-1900,time.time()-1900))
    path=tmp_path/'proof.json';path.write_text(json.dumps(proof),encoding='utf-8')
    if mode=='valid':
        result=recover_preflight(row['id'],path,db_path=queue.db)
        assert result['state']=='needs_agent' and result['target_version']==row['target_version']
        assert result['prior_error']==error
    else:
        with pytest.raises(DoudianError):recover_preflight(row['id'],path,db_path=queue.db)
    conn=batch._db(queue.db)
    final=conn.execute('SELECT * FROM products WHERE id=?',(row['id'],)).fetchone()
    assert final['state']==('needs_agent' if mode=='valid' else 'blocked')
    conn.close()


def _dual_clean_snapshots(row, tmp_path, *, title='目标合规标题', mains=None, details=None):
    mains = mains or [
        f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www1024-1024'
        for i in range(1, 6)
    ]
    details = details or [
        f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www1024-1536'
        for i in range(11, 15)
    ]
    sku_rows = [{'sku_id': '1001', 'spec_ids': ['2001'], 'price': '39.88',
                 'stock': 100, 'step_stock': 0, 'enabled': True, 'code': 'C1'}]
    raw_rows = [{'sku_id': '1001', 'id': '1001', 'price': '39.88',
                 'stock_info': {'stock_num': 100}, 'step_stock_info': {'stock_num': 0},
                 'spec_detail_ids': ['2001'], 'sku_status': True, 'code': 'C1'}]
    specs = [{'name': '颜色', 'spec_values': [{'id': '2001', 'name': 'S1'}]}]
    from doudian_auto.official_skus import _normalize
    import hashlib
    payload = {'rows': sku_rows, 'raw_rows': _normalize(raw_rows), 'specs': _normalize(specs)}
    sku_sha = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    sku_ev = {'complete': True, 'product_id': row['product_id'], 'shop_id': '999', 'count': 1, **payload, 'sha256': sku_sha}
    official = {
        'product_id': row['product_id'], 'shop': row['shop'], 'shop_confirmed': True,
        'title': title, 'mains': mains, 'details': details, 'detail_status': 'ready',
        'draft_loaded': False, 'rejected': False,
        'required_attributes': {'observed': True, 'complete': True, 'missing': [], 'completion_percent': 100,
                                'fields': [{'name': '材质', 'required': True, 'values': ['ABS']}]},
        'sku_evidence': sku_ev,
        'protected': [
            {'section': 'goodsEditScrollContainer-基础信息', 'observation': 'ready',
             'inputs': [], 'selections': [], 'static_fields': [], 'images': []},
            {'section': 'goodsEditScrollContainer-价格库存', 'observation': 'ready',
             'inputs': [], 'selections': ['现货'], 'static_fields': [], 'images': []},
            {'section': 'goodsEditScrollContainer-服务与履约', 'observation': 'ready',
             'inputs': [], 'selections': ['7天无理由'], 'static_fields': [], 'images': []},
        ],
    }
    miao = {
        'product_id': row['product_id'], 'shop': row['shop'], 'protected_complete': True,
        'title': title, 'mains': mains, 'details': details,
        'protected': {
            'status': 1, 'root.categoryId': 123, 'root.brandName': '无品牌', 'freightId': 1,
            'draftStatus': 0, 'checkStatus': 1, 'specPics': [], 'mainImageThreeToFour': '',
            'whiteBackGroundPicUrl': '', 'afterSaleService': {},
            'specPrices': [{'skuId': 1001, 'specDetailIds': [2001], 'price': '39.88',
                            'stockNum': 100, 'stepStockNum': 0, 'code': 'C1', 'skuStatus': True}],
        },
    }
    d_path = tmp_path / 'official.json'
    m_path = tmp_path / 'miaoshou.json'
    d_path.write_text(json.dumps(official, ensure_ascii=False), encoding='utf-8')
    m_path.write_text(json.dumps(miao, ensure_ascii=False), encoding='utf-8')
    return (
        {'path': str(m_path), 'sha256': file_hash(m_path)},
        {'path': str(d_path), 'sha256': file_hash(d_path)},
    )


@pytest.mark.parametrize('mode', ['clean_live', 'no_live_audit', 'temp_url_present', 'tightened_not_attempted_fails'])
def test_rebaseline_live_server_audit_and_tightened_not_attempted(queue, tmp_path, mode):
    row = queue.rows[0]
    hist = tmp_path / 'hist_7.json'
    hist.write_text(json.dumps({
        'productId': row['product_id'], 'phase': 'upload_unknown',
        'submission_status': 'not_attempted' if mode == 'tightened_not_attempted_fails' else 'unknown',
        'uploadsStarted': True, 'saveCount': 0, 'saved': False,
    }), encoding='utf-8')
    batch.reconcile_observation(hist, shop=row['shop'], db_path=queue.db)
    mains = None
    if mode == 'temp_url_present':
        mains = ['https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-11-20/1/a.png?dy'] * 5
    m_ref, d_ref = _dual_clean_snapshots(row, tmp_path, mains=mains)
    proof = {
        'read_only': True, 'reviewer': 'reviewer',
        'product_id': row['product_id'], 'shop': row['shop'], 'target_version': row['target_version'],
        'miaoshou': m_ref, 'doudian': d_ref,
        'resolved_observations': [{
            'evidence': {'path': hist.name, 'sha256': file_hash(hist)},
            'resolution': 'no_save_attempted' if mode == 'tightened_not_attempted_fails' else 'live_server_baseline_verified',
            'reason': 'uploadsStarted=True but saveCount=0 verified clean on live server',
        }],
    }
    if mode not in ('no_live_audit', 'tightened_not_attempted_fails'):
        proof['live_audit'] = {
            'read_only': True, 'live_baseline_clean': True, 'temp_urls_absent': True,
            'shelf_status': 1, 'reviewer': 'reviewer', 'summary': 'dual snapshots matched cleanly',
        }
    p_path = tmp_path / 'proof.json'
    p_path.write_text(json.dumps(proof), encoding='utf-8')
    if mode == 'clean_live':
        res = rebaseline_external(row['id'], p_path, db_path=queue.db)
        assert res['state'] == 'needs_agent'
    else:
        with pytest.raises(DoudianError):
            rebaseline_external(row['id'], p_path, db_path=queue.db)


@pytest.mark.parametrize('mode', ['valid', 'wrong_title', 'short_mains', 'saved_false'])
def test_reconcile_external_verified_requires_exact_target_and_history(queue, tmp_path, mode):
    from doudian_auto.rebaseline import reconcile_external_verified
    row = queue.rows[0]
    target = '目标合规标题'
    hist = tmp_path / 'hist_verified.json'
    hist.write_text(json.dumps({
        'productId': row['product_id'], 'stage': 'verified', 'status': '下架',
        'title': target, 'saved': False if mode == 'saved_false' else True,
    }, ensure_ascii=False), encoding='utf-8')
    batch.reconcile_observation(hist, shop=row['shop'], db_path=queue.db)
    mains = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www1024-1024'
             for i in range(1, 5 if mode == 'short_mains' else 6)]
    m_ref, d_ref = _dual_clean_snapshots(
        row, tmp_path, title='别的标题' if mode == 'wrong_title' else target, mains=mains)
    proof = {
        'read_only': True, 'reviewer': 'reviewer', 'task_id': row['id'],
        'product_id': row['product_id'], 'shop': row['shop'], 'target_version': row['target_version'],
        'target_title': target, 'miaoshou': m_ref, 'doudian': d_ref,
        'resolved_observations': [{
            'evidence': {'path': hist.name, 'sha256': file_hash(hist)}, 'resolution': 'prior_revision_confirmed',
            'reason': 'external run finished and live dual snapshots match target',
        }],
    }
    p_path = tmp_path / 'proof.json'
    p_path.write_text(json.dumps(proof, ensure_ascii=False), encoding='utf-8')
    if mode == 'valid':
        res = reconcile_external_verified(row['id'], p_path, db_path=queue.db)
        assert res['state'] == 'verified'
        assert res['submission_state'] == 'verified_by_readback'
    else:
        with pytest.raises(DoudianError):
            reconcile_external_verified(row['id'], p_path, db_path=queue.db)


@pytest.mark.parametrize('mode', ['valid', 'duplicate_details', 'attempted'])
def test_reset_prewrite_source_collision_requires_deduped_details_and_zero_saves(queue, tmp_path, mode):
    from doudian_auto.rebaseline import reset_prewrite_source_collision
    row = queue.rows[0]
    conn = batch._db(queue.db)
    old_hash = 'a' * 64
    conn.execute(
        "UPDATE products SET state='blocked',last_error='writer_detail_source_collision',"
        "submission_state='not_attempted',submission_attempts=?,baseline_hash=?,upload_map_json='[{}]' WHERE id=?",
        (1 if mode == 'attempted' else 0, old_hash, row['id']))
    conn.commit()
    conn.close()
    details = ([f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{11:032x}_sx_100_www1024-1536'] * 4
               if mode == 'duplicate_details' else None)
    m_ref, d_ref = _dual_clean_snapshots(row, tmp_path, details=details)
    p_path = tmp_path / 'proof.json'
    p_path.write_text(json.dumps({
        'read_only': True, 'reviewer': 'reviewer',
        'product_id': row['product_id'], 'shop': row['shop'], 'target_version': row['target_version'],
        'prior_error': 'writer_detail_source_collision', 'prior_baseline_sha256': old_hash,
        'miaoshou': m_ref, 'doudian': d_ref,
    }), encoding='utf-8')
    if mode == 'valid':
        res = reset_prewrite_source_collision(row['id'], p_path, db_path=queue.db)
        assert res['state'] == 'needs_agent'
        conn = batch._db(queue.db)
        final = conn.execute('SELECT state,baseline_hash,artifacts_path,upload_map_json FROM products WHERE id=?', (row['id'],)).fetchone()
        conn.close()
        assert (final['state'], final['baseline_hash'], final['artifacts_path'], final['upload_map_json']) == ('needs_agent', None, None, '[]')
    else:
        with pytest.raises(DoudianError):
            reset_prewrite_source_collision(row['id'], p_path, db_path=queue.db)


@pytest.mark.parametrize('mode', [
    'valid_ack', 'modified_warning', 'blank_reason', 'duplicate_ack',
    'arbitrary_unresolved', 'swapped_visual_keys', 'missing_visual_verif',
])
def test_reconcile_external_verified_acknowledged_unresolved_strict(queue, tmp_path, mode):
    from doudian_auto.rebaseline import reconcile_external_verified
    from doudian_auto.workflow import resource_key
    row = queue.rows[0]
    target = '目标合规标题'
    cache_warn = '妙手列表摘要仍可能显示旧标题缓存；独立编辑器字段与官方抖店页均已读回新标题，作为权威结果。'
    unresolved_val = '别的未决问题' if mode == 'arbitrary_unresolved' else cache_warn
    hist = tmp_path / 'hist_warn.json'
    hist.write_text(json.dumps({
        'productId': row['product_id'], 'stage': 'verified', 'status': '下架',
        'title': target, 'save': {'attempt1': {'result': 'fail'}, 'attempt2': {'result': 'success'}},
        'unresolved': unresolved_val,
    }, ensure_ascii=False), encoding='utf-8')
    batch.reconcile_observation(hist, shop=row['shop'], db_path=queue.db)
    mains = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www1024-1024'
             for i in range(1, 6)]
    details = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/png_m_{i:032x}_sx_100_www1024-1536'
               for i in range(11, 16)]
    m_ref, d_ref = _dual_clean_snapshots(row, tmp_path, title=target, mains=mains, details=details)
    ack_text = cache_warn + 'extra' if mode == 'modified_warning' else unresolved_val
    ack_list = [{'kind': 'stale_list_summary', 'text': ack_text, 'reason': '   ' if mode == 'blank_reason' else 'Independent readbacks confirmed identical title and images.'}]
    if mode == 'duplicate_ack':
        ack_list.append(dict(ack_list[0]))
    vv_mains = [resource_key(u) for u in (list(reversed(mains)) if mode == 'swapped_visual_keys' else mains)]
    vv_details = [resource_key(u) for u in details[:4]]
    proof = {
        'read_only': True, 'reviewer': 'reviewer', 'task_id': row['id'],
        'product_id': row['product_id'], 'shop': row['shop'], 'target_version': row['target_version'],
        'target_title': target, 'expected_mains_count': 5, 'expected_details_count': 5,
        'miaoshou': m_ref, 'doudian': d_ref,
        'resolved_observations': [{
            'evidence': {'path': hist.name, 'sha256': file_hash(hist)},
            'resolution': 'prior_revision_confirmed',
            'reason': 'attempt2 succeeded and live dual readbacks match target.',
        }],
        'acknowledged_unresolved': ack_list,
    }
    if mode != 'missing_visual_verif':
        proof['visual_verification'] = {
            'reviewer': 'reviewer', 'all_clean_verified': True,
            'mains_keys': vv_mains, 'details_keys': vv_details,
        }
    p_path = tmp_path / 'proof.json'
    p_path.write_text(json.dumps(proof, ensure_ascii=False), encoding='utf-8')
    if mode == 'valid_ack':
        res = reconcile_external_verified(row['id'], p_path, db_path=queue.db)
        assert res['state'] == 'verified'
        assert res['submission_state'] == 'verified_by_readback'
        assert res['acknowledged_unresolved'][0]['kind'] == 'stale_list_summary'
    else:
        with pytest.raises(DoudianError):
            reconcile_external_verified(row['id'], p_path, db_path=queue.db)

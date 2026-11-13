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

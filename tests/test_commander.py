"""Commander routing and attribute-write guards.

These cover the decisions that must not silently go wrong: a verified product is never
re-saved, a product missing real facts is never guessed, and the attribute writer refuses
the control shapes it cannot verify.
"""

import json

import pytest

from doudian_auto import attributes, commander
from doudian_auto.errors import DoudianError


def row(**kw):
    base = {'product_id': '1', 'state': 'blocked', 'submission_state': 'not_attempted',
            'last_error': None, 'title': 't'}
    base.update(kw)
    return base


def test_verified_is_skipped_not_resaved():
    outcome, _ = commander.decide(row(state='verified'))
    assert outcome == commander.SKIP_VERIFIED
    outcome, _ = commander.decide(row(submission_state='verified_by_readback'))
    assert outcome == commander.SKIP_VERIFIED


@pytest.mark.parametrize('submission', ['unknown', 'accepted'])
def test_unconfirmed_submission_only_reads_back(submission):
    # Re-sending here risks a duplicate listing; the only safe action is a read.
    outcome, _ = commander.decide(row(submission_state=submission))
    assert outcome == commander.READ_ONLY


def test_missing_attribute_waits_for_a_human():
    outcome, _ = commander.decide(row(last_error=(
        'preflight_exception: required_attributes_missing; 平台必填类目属性缺失：尺寸；'
        '需真实资料补齐后续办。; missing_fields=["尺寸"]')))
    assert outcome == commander.WAIT_FACTS


def test_missing_fields_are_extracted_for_the_checklist():
    fields = commander._missing_fields(
        'x; missing_fields=["材质", "适用年龄"]')
    assert fields == ['材质', '适用年龄']


def test_rebaseline_is_not_silently_signed_off():
    # The proof file declares past submissions resolved. Generating that itself would be
    # the machine vouching for its own evidence, so it stays a human confirmation.
    outcome, _ = commander.decide(row(last_error='external_work_requires_rebaseline'))
    assert outcome == commander.WAIT_REBASELINE


def test_rejected_product_needs_a_decision():
    outcome, _ = commander.decide(
        row(last_error='preflight_exception: doudian_draft_or_rejected; ...'))
    assert outcome == commander.WAIT_DECISION


def test_unknown_error_holds_rather_than_guesses():
    outcome, _ = commander.decide(row(last_error='something_new'))
    assert outcome == commander.HOLD_ERROR


def test_facts_loader_drops_blanks_and_placeholders(tmp_path):
    path = tmp_path / 'facts.json'
    path.write_text(json.dumps({'items': [
        {'product_id': '1', 'attributes': {'尺寸': '30cm', '厚度': ''}},
        {'product_id': '2', 'attributes': {'安装方式': '待确认'}},
    ]}, ensure_ascii=False), encoding='utf-8')
    loaded = commander.load_facts(path)
    assert loaded == {'1': {'尺寸': '30cm'}}


class StubBridge:
    def __init__(self):
        self.calls = []

    def command(self, action, args):
        self.calls.append((action, args))
        return {'success': True}


class StubEditor:
    """Minimal editor double: returns queued control descriptions, records writes."""

    def __init__(self, controls):
        self.controls = list(controls)
        self.bridge = StubBridge()
        self.fills = []

    def dom(self, op, manifest, **kwargs):
        if op == 'attribute_control':
            return self.controls.pop(0) if self.controls else {'error': 'attribute_not_found'}
        if op == 'attribute_options':
            return {'ok': True, 'selector': '[data-doudian-option="x"]'}
        return {}

    def command(self, action, args):
        return self.bridge.command(action, args)


def test_multi_select_is_refused_not_attempted():
    editor = StubEditor([{'kind': 'multi', 'name': '材质', 'current': '请选择'}])
    out = attributes.apply_attributes(editor, {'product_id': '1'},
                                      {'材质': '塑料'})
    assert out[0]['written'] is False
    assert '多选' in out[0]['reason']
    assert editor.bridge.calls == []          # nothing was clicked


def test_placeholder_value_is_skipped():
    editor = StubEditor([])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '待确认'})
    assert out[0]['written'] is False
    assert editor.bridge.calls == []


def test_existing_different_value_is_not_overwritten():
    editor = StubEditor([{'kind': 'text', 'name': '尺寸', 'current': '20cm', 'marked': 'x'}])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '30cm'})
    assert out[0]['written'] is False
    assert '不覆盖' in out[0]['reason']
    assert editor.bridge.calls == []


def test_text_write_reads_back_and_confirms():
    editor = StubEditor([
        {'kind': 'text', 'name': '尺寸', 'current': '', 'marked': '[data-x]'},
        {'kind': 'text', 'name': '尺寸', 'current': '30cm', 'marked': '[data-x]'},
    ])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '30cm'})
    assert out[0]['written'] is True
    assert out[0]['readback'] == '30cm'


def test_text_write_that_does_not_stick_is_reported():
    # The readback is the authority, not the click returning successfully.
    editor = StubEditor([
        {'kind': 'text', 'name': '尺寸', 'current': '', 'marked': '[data-x]'},
        {'kind': 'text', 'name': '尺寸', 'current': '', 'marked': '[data-x]'},
    ])
    out = attributes.apply_attributes(editor, {'product_id': '1'}, {'尺寸': '30cm'})
    assert out[0]['written'] is False
    assert '读回值' in out[0]['reason']


def test_existing_facts_survive_template_refresh(tmp_path):
    path = tmp_path / 'facts.json'
    path.write_text(json.dumps({'items':[{'product_id':'1','attributes':{'尺寸':'30cm'},
                                         'confirmed_by':'owner'}]}), encoding='utf-8')
    report = {'facts_checklist':[{'product_id':'1','title':'t','fields':['尺寸','材质']},
                                {'product_id':'2','title':'u','fields':['厚度']}]}
    commander.write_facts_template(report, path)
    assert commander.load_facts(path) == {'1':{'尺寸':'30cm'}}
    data = json.loads(path.read_text(encoding='utf-8'))
    assert data['items'][0]['confirmed_by'] == 'owner'
    assert data['items'][0]['attributes']['材质'] == ''
    assert data['items'][1]['product_id'] == '2'


def test_broken_existing_facts_never_overwritten(tmp_path):
    path = tmp_path / 'facts.json'
    path.write_text('invalid', encoding='utf-8')
    with pytest.raises(ValueError):
        commander.write_facts_template({'facts_checklist':[]}, path)
    assert path.read_text() == 'invalid'


def test_survey_uses_live_missing_fields_not_old_queue(monkeypatch):
    monkeypatch.setattr(commander,'_ensure_session',lambda *a:None)
    from doudian_auto import preflight
    monkeypatch.setattr(commander.batch,'batch_status',lambda **kw:{'products':[
        row(last_error='required_attributes_missing; missing_fields=["尺寸"]')]})
    monkeypatch.setattr(commander,'_titles_by_product',lambda *a:{})
    monkeypatch.setattr(commander,'_readiness',lambda *a,**k:{})
    monkeypatch.setattr(preflight,'preflight_products',lambda *a,**k:{'products':[
        {'product_id':'1','eligible':True,'evidence':{'snapshot_read':True}}]})
    result=commander.survey(live=True)
    assert result['facts_checklist']==[]
    assert result['buckets'][commander.READ_ONLY][0]['observation']=='fresh'


def test_auto_reads_facts_before_refresh_and_does_not_claim_write_on_plan(tmp_path,monkeypatch):
    from types import SimpleNamespace
    facts=tmp_path/'facts-needed.json'
    facts.write_text(json.dumps({'items':[{'product_id':'1','attributes':{'尺寸':'30cm'}}]}))
    monkeypatch.setattr(commander,'survey',lambda **kw:{'total':1,'facts_checklist':[
        {'product_id':'1','fields':['尺寸'],'title':'t'}]})
    monkeypatch.setattr(commander.batch,'batch_status',lambda:{'counts':{'blocked':1}})
    result=commander.auto(SimpleNamespace(facts=str(facts),endpoint='ego',session='test',plan=True,
                         report_dir=str(tmp_path),apply=False,shop=None,limit=1))
    assert result['facts_loaded']==1
    assert commander.load_facts(facts)=={'1':{'尺寸':'30cm'}}
    assert result['actions']==[]

@pytest.mark.parametrize('ready_writer',[False,True])
def test_auto_unknown_is_readback_only_and_ready_obeys_writer(monkeypatch,ready_writer):
    from types import SimpleNamespace
    products=[row(product_id='1',shop='shop',submission_state='unknown'),
              row(product_id='2',shop='shop',state='ready')]
    monkeypatch.setattr(commander,'survey',lambda **kw:{'total':2,'facts_checklist':[]})
    monkeypatch.setattr(commander.batch,'batch_status',lambda:{'products':products,'counts':{}})
    monkeypatch.setattr(commander.batch,'execution_readiness',lambda endpoint:{'writer_ready':ready_writer})
    calls=[]
    monkeypatch.setattr(commander.batch,'run_batch',lambda endpoint,**kw:calls.append(kw) or {'run':[]})
    commander.auto(SimpleNamespace(facts=None,endpoint='ego',session='same',plan=False,
                     report_dir=None,apply=True,shop='shop',limit=1))
    assert calls[0]['product_ids']==['1'] and calls[0]['readback_only'] is True
    assert len(calls)==(2 if ready_writer else 1)
    if ready_writer:assert calls[1]['product_ids']==['2']


def test_auto_stops_dispatch_after_unknown_transport_failure(monkeypatch,tmp_path):
    from types import SimpleNamespace
    products=[row(product_id='1',shop='shop',submission_state='unknown'),row(product_id='2',shop='shop',state='ready')]
    monkeypatch.setattr(commander,'survey',lambda **kw:{'total':2,'facts_checklist':[]})
    monkeypatch.setattr(commander.batch,'batch_status',lambda:{'products':products,'counts':{}})
    monkeypatch.setattr(commander.batch,'execution_readiness',lambda endpoint:pytest.fail('must stop'))
    calls=[]
    def fail(endpoint,**kw):
        calls.append(kw);raise DoudianError('ego_operation_unsettled','pending')
    monkeypatch.setattr(commander.batch,'run_batch',fail)
    result=commander.auto(SimpleNamespace(facts=None,endpoint='ego',session='same',plan=False,
                     report_dir=str(tmp_path),apply=True,shop='shop',limit=1))
    assert len(calls)==1
    assert result['actions'][0]['error']=='ego_operation_unsettled'
    assert json.loads((tmp_path/'auto-result.json').read_text())['actions'][0]['error']=='ego_operation_unsettled'

def test_auto_attribute_consumes_write_budget_and_does_not_dispatch_ready(monkeypatch,tmp_path):
    from types import SimpleNamespace
    from doudian_auto import attribute_workflow,bridge,editor
    facts=tmp_path/'facts.json';facts.write_text(json.dumps({'items':[{'product_id':'1','attributes':{'尺寸':'30cm'}}]}))
    products=[row(product_id='1',shop='shop'),row(product_id='2',shop='shop',state='ready')]
    monkeypatch.setattr(commander,'survey',lambda **kw:{'total':2,'facts_checklist':[]})
    monkeypatch.setattr(commander.batch,'batch_status',lambda:{'products':products,'counts':{}})
    monkeypatch.setattr(commander.batch,'execution_readiness',lambda *a:{'writer_ready':True})
    monkeypatch.setattr(commander.batch,'run_batch',lambda *a,**k:pytest.fail('write budget exhausted'))
    monkeypatch.setattr(bridge,'Bridge',lambda *a,**k:object())
    monkeypatch.setattr(editor,'Editor',lambda *a:object())
    monkeypatch.setattr(attribute_workflow,'publish_attributes',lambda *a,**k:{'product_id':'1','persisted':True})
    result=commander.auto(SimpleNamespace(facts=str(facts),endpoint='ego',session='same',plan=False,
                     report_dir=None,apply=True,shop='shop',limit=1))
    assert len(result['actions'])==1 and result['actions'][0]['kind']=='attributes'


@pytest.mark.parametrize('existing',[False,True])
def test_auto_initializes_only_genuinely_new_session(tmp_path,monkeypatch,existing):
    from doudian_auto import bridge,jobs
    from types import SimpleNamespace
    root=tmp_path/'native-session'
    if existing:
        root.mkdir();(root/'pending-command.json').write_text('unsettled')
    calls=[]
    monkeypatch.setattr(bridge,'Bridge',lambda *a,**k:SimpleNamespace(session_dir=root,command=lambda *a:calls.append(a)))
    monkeypatch.setattr(jobs,'DATA_ROOT',tmp_path)
    commander._ensure_session('ego','isolated')
    assert len(calls)==(0 if existing else 1)
    if calls:assert calls[0][0]=='navigate'

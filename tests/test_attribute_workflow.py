from pathlib import Path

import pytest

from doudian_auto import attribute_workflow as flow
from doudian_auto.errors import DoudianError
from doudian_auto.jobs import read_json


class Editor:
    def __init__(self, root):
        self.root=root; self.current=''; self.stored=''; self.publishes=0; self.reloads=0
        self.title='原标题'; self.lost=False; self.bridge=self
    def open(self, *a, **k):
        self.current=self.stored
    def wait_details(self, *a): pass
    def read_skus(self, *a):
        self.reloads+=1
        self.current=self.stored  # Like the real reader, reloading discards unsaved fields.
        return {'complete':True}
    def dom(self, op, *a, **k):
        if op=='attribute_control':
            return {'kind':'text','marked':'input','current':self.current}
        if op=='snapshot':
            return {'product_id':'123','shop_confirmed':True,'detail_status':'ready',
                    'title':self.title,'mains':['one'],'details':['two'],
                    'required_attributes':{'fields':[{'name':'尺寸','values':[self.current]}]}}
        raise AssertionError(op)
    def command(self, action, args):
        assert action=='fill'; self.current=args['value']
    def check(self, *a): pass
    def publish(self, *a):
        state=read_json(next(self.root.glob('jobs/*/state.json')))
        assert state['stage']=='submitting' and state['submission_status']=='unknown'
        self.publishes+=1; self.stored=self.current
        if self.lost: raise DoudianError('transport_timeout','response lost')
        return {'state':'accepted'}


@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.setattr(flow,'compare_protected',lambda a,b:None)
    from doudian_auto import attributes
    monkeypatch.setattr(attributes.time,'sleep',lambda s:None)
    return Editor(tmp_path),{'product_id':'123','shop':'shop','edit_url':'https://example.test'},tmp_path


def test_publish_precedes_fresh_verification_and_does_not_reload_unsaved_fields(setup):
    editor, identity, root=setup
    result=flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert result['persisted'] and editor.stored=='30cm'
    assert editor.publishes==1 and editor.reloads==2
    flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert editor.publishes==1


def test_lost_publish_response_only_reads_back_never_republishes(setup):
    editor, identity, root=setup;editor.lost=True
    with pytest.raises(DoudianError):flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert read_json(next(root.glob('jobs/*/state.json')))['stage']=='submitting'
    result=flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert result['persisted'] and result['readback_only'] and editor.publishes==1


def test_partial_fill_does_not_publish_or_restart(setup):
    editor,identity,root=setup
    def no_write(action,args):pass
    editor.command=no_write
    with pytest.raises(DoudianError,match='填写不完整'):
        flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    with pytest.raises(DoudianError,match='尚未终结'):
        flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert editor.publishes==0


def test_non_target_change_stops_before_publish(setup):
    editor,identity,root=setup
    editor.check=lambda *a:setattr(editor,'title','被意外修改')
    with pytest.raises(DoudianError,match='标题或图片'):
        flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert editor.publishes==0


def test_another_attribute_revision_cannot_bypass_unknown(setup):
    editor,identity,root=setup;editor.lost=True
    with pytest.raises(DoudianError):flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    with pytest.raises(DoudianError) as exc:
        flow.publish_attributes(editor,identity,{'尺寸':'40cm'},root=root)
    assert exc.value.code=='product_job_conflict' and editor.publishes==1

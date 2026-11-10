from pathlib import Path

import pytest

from doudian_auto import attribute_workflow as flow
from doudian_auto.errors import DoudianError
from doudian_auto.jobs import read_json


class Editor:
    def __init__(self, root):
        self.root=root; self.current=''; self.stored=''; self.publishes=0; self.reloads=0
        self.title='原标题'; self.lost=False; self.bridge=self
        self.focused=False; self.details_ready=True
    def open(self, *a, **k):
        self.current=self.stored
    def wait_details(self, *a):
        if not self.details_ready:
            raise DoudianError('detail_source_not_ready','lazy preview pending')
    def wait(self, probe, predicate, *a, **k):
        result=probe()
        assert predicate(result)
        return result
    def read_skus(self, *a):
        self.reloads+=1
        self.current=self.stored  # Like the real reader, reloading discards unsaved fields.
        self.details_ready=False
        return {'complete':True}
    def dom(self, op, *a, **k):
        if op=='scroll':
            assert self.focused
            self.details_ready=True
            return {'ok':True}
        if op=='attribute_control':
            return {'kind':'text','marked':'input','current':self.current}
        if op=='snapshot':
            return {'product_id':'123','shop_confirmed':True,'detail_status':'ready',
                    'title':self.title,'mains':['one'],'details':['two'],
                    'required_attributes':{'fields':[{'name':'尺寸','values':[self.current]}]}}
        raise AssertionError(op)
    def command(self, action, args):
        if action=='cdp':
            assert args['method']=='Emulation.setFocusEmulationEnabled'
            self.focused=args['params']['enabled']
            return {}
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
    command=editor.command
    def no_write(action,args):
        if action!='fill':return command(action,args)
    editor.command=no_write
    with pytest.raises(DoudianError,match='填写不完整'):
        flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    with pytest.raises(DoudianError,match='尚未终结'):
        flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert editor.publishes==0


def test_unavailable_details_still_stop_before_fill_and_release_focus(setup):
    editor,identity,root=setup
    def pending(*a):
        raise DoudianError('detail_source_not_ready','preview never mounted')
    editor.wait_details=pending
    with pytest.raises(DoudianError) as exc:
        flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert exc.value.code=='detail_source_not_ready'
    assert editor.current=='' and editor.publishes==0 and not editor.focused
    assert not list(root.glob('jobs/*/state.json'))


def test_focus_released_when_snapshot_rejects_identity(setup):
    editor,identity,root=setup
    dom=editor.dom
    def wrong(op,*a,**k):
        if op=='snapshot':raise DoudianError('wrong_identity','different product')
        return dom(op,*a,**k)
    editor.dom=wrong
    with pytest.raises(DoudianError) as exc:
        flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
    assert exc.value.code=='wrong_identity'
    assert not editor.focused and editor.publishes==0


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


def test_cdn_rotation_preserves_image_identity_but_slot_changes_do_not(setup):
    editor,identity,_=setup
    before=editor.dom('snapshot')
    before['mains']=['https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_abc~q75.avis',
                     'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_def']
    from copy import deepcopy
    after=deepcopy(before)
    after['mains'][0]='https://p9-aio.ecombdimg.com/img/ecom-shop-material/jpeg_m_abc~750x0.jpg'
    flow._compare(before,after,{'尺寸':'30cm'})
    for changed in (list(reversed(after['mains'])),after['mains'][:1],
                    [after['mains'][0],after['mains'][0]],['new image',after['mains'][1]]):
        after['mains']=changed
        with pytest.raises(DoudianError) as exc:
            flow._compare(before,after,{'尺寸':'30cm'})
        assert exc.value.code=='attribute_non_target_changed'


def test_changed_readback_is_preserved_and_recovery_never_resubmits(setup):
    editor,identity,root=setup
    publish=editor.publish
    def changed(*a):
        result=publish(*a)
        editor.title='平台返回的不同标题'
        return result
    editor.publish=changed
    for _ in range(2):
        with pytest.raises(DoudianError) as exc:
            flow.publish_attributes(editor,identity,{'尺寸':'30cm'},root=root)
        assert exc.value.code=='attribute_non_target_changed'
        assert read_json(next(root.glob('jobs/*/state.json')))['stage']=='submitted'
        assert read_json(next(root.glob('jobs/*/observed-readback.json')))['title']==editor.title
        assert editor.publishes==1

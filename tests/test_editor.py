from copy import deepcopy
import json
import time

import pytest

from doudian_auto.editor import Editor
from doudian_auto.errors import DoudianError, WaitingHuman


class FakeBridge:
    def __init__(self, stale_details=False):
        self.snapshot = {'product_id':'3790019980637110699','title':'old','mains':['old1','old2'],'details':['d1'],
                         'main_delete_count':2,'detail_delete_count':1,
                         'detail_status':'ready','detail_declared':1,'detail_cards':1,'detail_slots':1,'canvas_count':1}
        self.calls = []
        self.fail = None
        self.stale_details = stale_details

    def evaluate(self,code):
        # Test Python-to-JS dispatch contract. Actual DOM selectors are tested with jsdom.
        op,args = json.loads('['+code.rsplit('\n})(',1)[1][:-1]+']')
        self.calls.append((op,args))
        if self.fail:
            return {'error':self.fail}
        if op == 'snapshot':
            return deepcopy(self.snapshot)
        if op == 'delete':
            kind = args['kind']
            self.snapshot[kind].pop(0)
            count_key = 'main_delete_count' if kind == 'mains' else 'detail_delete_count'
            self.snapshot[count_key] -= 1
            if kind == 'details' and not self.snapshot['details'] and not self.stale_details:
                # The live panel drops the list once the last image is deleted.
                self.snapshot.update({'detail_status':'empty','detail_declared':0,'detail_cards':0,'detail_slots':0})
        if op == 'upload_selector':
            return {'selector':f'input[data-doudian-auto-input="{args["kind"]}"]'}
        return {'ok':True}

    def command(self,action,args):
        self.calls.append((action,args))
        if action == 'upload':
            kind = 'mains' if 'mains' in args['selector'] else 'details'
            self.snapshot[kind] = ['https://cdn/'+str(i) for i,_ in enumerate(args['files'])]
            count_key = 'main_delete_count' if kind == 'mains' else 'detail_delete_count'
            self.snapshot[count_key] = len(args['files'])
            if kind == 'details':
                self.snapshot.update({'detail_status':'ready','detail_declared':len(args['files']),
                                      'detail_cards':len(args['files']),'detail_slots':len(args['files'])})
        if action == 'fill':
            self.snapshot['title'] = args['value']

    def wait(self,probe,predicate,message='timeout',seconds=60):
        # Mirror the real bridge: probe until the predicate holds, then time out.
        deadline = time.monotonic() + min(seconds,0.5)
        while True:
            result = probe()
            if predicate(result):
                return result
            if time.monotonic() >= deadline:
                raise DoudianError('page_timeout', message)
            time.sleep(0.01)


def test_adapter_clears_all_old_slots_then_uploads_absolute_manifest_paths():
    bridge = FakeBridge()
    editor = Editor(bridge)
    manifest = {'product_id':'3790019980637110699','shop':'样板店','mains':[{'path':f'C:/assets/{i}.jpg'} for i in range(5)]}
    checkpoint = []
    urls = editor.replace(manifest,'mains',lambda:checkpoint.append(True))
    assert len(urls) == 5
    assert len([c for c in bridge.calls if c[0]=='delete']) == 2
    upload = [c for c in bridge.calls if c[0]=='upload'][0]
    assert upload[1]['files'] == [r['path'] for r in manifest['mains']]
    assert checkpoint == [True]
    assert all(c[1].get('product_id') == manifest['product_id'] for c in bridge.calls if c[0] in ('delete','snapshot','upload_selector'))


def test_adapter_only_fills_title_and_verifies_value():
    bridge = FakeBridge()
    editor = Editor(bridge)
    editor.fill_title({'product_id':'3790019980637110699','shop':'样板店','title':'标题写入'})
    assert [c for c in bridge.calls if c[0]=='fill'] == [('fill',{'selector':'#pg-title-input','value':'标题写入'})]


def test_adapter_details_replace_requires_a_confirmed_empty_before_upload():
    bridge = FakeBridge()
    editor = Editor(bridge)
    manifest = {'product_id':'3790019980637110699','shop':'样板店','details':[{'path':f'C:/assets/d{i}.jpg'} for i in range(2)]}
    urls = editor.replace(manifest,'details',lambda:None)
    assert urls == ['https://cdn/0','https://cdn/1']
    upload = [c for c in bridge.calls if c[0]=='upload'][0]
    assert upload[1]['files'] == [r['path'] for r in manifest['details']]


def test_adapter_details_replace_stops_when_clear_is_not_confirmed():
    # Regression for the stale decorate canvas: counts zeroed but the live source
    # never confirms empty, so nothing may be uploaded.
    bridge = FakeBridge(stale_details=True)
    editor = Editor(bridge)
    manifest = {'product_id':'3790019980637110699','shop':'样板店','details':[{'path':f'C:/assets/d{i}.jpg'} for i in range(2)]}
    with pytest.raises(DoudianError) as exc:
        editor.replace(manifest,'details',lambda:None)
    assert exc.value.code == 'delete_incomplete'
    assert not any(c[0]=='upload' for c in bridge.calls)


@pytest.mark.parametrize('error,waiting',[('wrong_product',False),('editor_layout_changed',False),('shop_not_confirmed',True),('verification_required',True)])
def test_adapter_stops_on_identity_layout_and_human_gates(error,waiting):
    bridge = FakeBridge()
    bridge.fail = error
    with pytest.raises(DoudianError) as exc:
        Editor(bridge).read({'product_id':'3790019980637110699','shop':'样板店'})
    assert exc.value.waiting == waiting

from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest

from doudian_auto.cli import main, process_alive, unlock
from doudian_auto.errors import DoudianError
from doudian_auto.jobs import Lock, load_job, prepare, read_json, write_json
from doudian_auto.workflow import Workflow

PID = '3790019980637110699'
URL = 'https://fxg.jinritemai.com/ffa/g/create?product_id=' + PID
TITLE = '车载灭火器固定绑带魔术贴可调节三道绑带黑红两色'


@pytest.fixture
def job(tmp_path):
    assets = tmp_path / 'assets'
    assets.mkdir()
    for index,name in enumerate([f'main_{i:02}.jpg' for i in range(1,6)] + ['detail_01.jpg','detail_02.jpg']):
        Image.new('RGB',(640,640 if index < 5 else 960),(index*30,100,150)).save(assets/name)
    result = prepare(assets,TITLE,URL,'样板店',tmp_path/'jobs')
    return Path(result['job_dir'])


class FakeEditor:
    def __init__(self):
        self.bridge = SimpleNamespace(session='',wait=lambda probe,predicate,*a,**kw: probe())
        self.current = {'product_id':PID,'shop_confirmed':True,'title':'原有标题','mains':['old'+str(i) for i in range(5)],'details':['old-detail'], 'protected':[{'price':'20.88','checked':True,'shipping':'48h'}], 'coverage':'fixture'}
        self.saved = deepcopy(self.current)
        self.replacements = []
        self.publishes = 0
        self.fail = None

    def open(self, manifest, fresh=False):
        if fresh:
            self.current = deepcopy(self.saved)
        return deepcopy(self.current)

    def read(self, manifest):
        return deepcopy(self.current)

    def replace(self, manifest, kind, before_upload):
        self.replacements.append(kind)
        self.current[kind] = []
        before_upload()
        self.current[kind] = [f'https://cdn/ecom-shop-material/{kind}-{r["sha256"]}' for r in manifest[kind]]
        if self.fail == kind:
            self.fail = None
            raise DoudianError('bridge_transport','unknown upload')
        return list(self.current[kind])

    def fill_title(self, manifest):
        self.current['title'] = manifest['title']

    def check(self, manifest):
        if self.fail == 'commercial':
            self.current['protected'][0]['checked'] = False
        return self.read(manifest)

    def publish(self, manifest):
        self.publishes += 1
        self.saved = deepcopy(self.current)
        if self.fail == 'submit_timeout':
            raise DoudianError('bridge_transport','unknown submit')
        if self.fail == 'wrong_saved':
            self.saved['details'].reverse()
        return {'success':True}

    def screenshot(self, path):
        Path(path).write_bytes(b'fixture')


def flow(job, editor):
    return Workflow(job,editor,lock_root=job.parent)


def test_prepare_is_idempotent_and_checks_mutated_bytes(job):
    manifest = load_job(job)
    assets = Path(manifest['mains'][0]['path']).parent
    again = prepare(assets,TITLE,URL,'样板店',job.parent)
    assert again['job_dir'] == str(job)
    Path(manifest['mains'][0]['path']).write_bytes(b'changed')
    with pytest.raises(DoudianError,match='素材已改变'):
        load_job(job)


def test_missing_duplicate_and_numbered_detail_assets(job):
    manifest = load_job(job)
    assets = Path(manifest['mains'][0]['path']).parent
    (assets/'detail_02.jpg').rename(assets/'detail_10.jpg')
    with pytest.raises(DoudianError) as exc:
        prepare(assets,TITLE,URL,'样板店',job.parent)
    assert exc.value.code == 'missing_assets'
    (assets/'detail_10.jpg').rename(assets/'detail_02.jpg')
    (assets/'main_02.jpg').write_bytes((assets/'main_01.jpg').read_bytes())
    with pytest.raises(DoudianError) as exc:
        prepare(assets,TITLE,URL,'样板店',job.parent)
    assert exc.value.code == 'duplicate_assets'


def test_dry_run_no_browser_actions(job):
    editor = FakeEditor()
    assert flow(job,editor).upload()['dry_run']
    assert flow(job,editor).submit()['dry_run']
    assert not editor.replacements and editor.publishes == 0
    assert read_json(job/'state.json')['stage'] == 'prepared'


def test_upload_submit_reopen_and_repeat_verify(job):
    editor = FakeEditor()
    assert flow(job,editor).upload(True)['stage'] == 'uploaded'
    assert editor.publishes == 0
    assert flow(job,editor).submit(True)['verified']
    assert editor.publishes == 1


def test_stale_process_state_cannot_republish_after_lock_released(job):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    first,stale = flow(job,editor),flow(job,editor)
    first.submit(True)
    with pytest.raises(DoudianError):
        stale.submit(True)
    assert editor.publishes == 1
    assert flow(job,editor).verify()['stage'] == 'saved'
    with pytest.raises(DoudianError):
        flow(job,editor).submit(True)
    assert editor.publishes == 1


def test_interrupted_upload_replaces_unknown_images_then_resumes_verified_slot(job):
    editor = FakeEditor()
    editor.fail = 'details'
    with pytest.raises(DoudianError):
        flow(job,editor).upload(True)
    state = read_json(job/'state.json')
    assert state['mains_urls'] and state['pending_upload'] == 'details'
    flow(job,editor).upload(True)
    assert editor.replacements == ['mains','details','details']
    assert len(editor.current['details']) == 2


@pytest.mark.parametrize('field,value',[('price','999'),('checked',False),('shipping','90d')])
def test_changed_commercial_field_blocks_submit(job,field,value):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    editor.current['protected'][0][field] = value
    with pytest.raises(DoudianError) as exc:
        flow(job,editor).submit(True)
    assert exc.value.code == 'commercial_changed'
    assert editor.publishes == 0


def test_check_can_change_policy_and_is_checked_again(job):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    editor.fail = 'commercial'
    with pytest.raises(DoudianError):
        flow(job,editor).submit(True)
    assert editor.publishes == 0


def test_submit_timeout_must_verify_without_reclick(job):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    editor.fail = 'submit_timeout'
    with pytest.raises(DoudianError):
        flow(job,editor).submit(True)
    assert read_json(job/'state.json')['stage'] == 'submitting'
    with pytest.raises(DoudianError):
        flow(job,editor).submit(True)
    assert flow(job,editor).verify()['verified']
    assert editor.publishes == 1


def test_unknown_submit_not_saved_cannot_verify_or_repeat(job):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    task = flow(job,editor)
    task.save('submitting')
    with pytest.raises(DoudianError):
        flow(job,editor).verify()
    with pytest.raises(DoudianError):
        flow(job,editor).upload(True)
    assert editor.publishes == 0


def test_same_count_wrong_remote_order_rejected(job):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    editor.fail = 'wrong_saved'
    with pytest.raises(DoudianError) as exc:
        flow(job,editor).submit(True)
    assert exc.value.code == 'images_mismatch'
    assert read_json(job/'state.json')['stage'] == 'submitted'


@pytest.mark.parametrize('field,value',[('product_id','3793430313384935495'),('shop_confirmed',False),('title','错误标题')])
def test_identity_or_title_drift_blocks_submit(job,field,value):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    editor.current[field] = value
    with pytest.raises(DoudianError):
        flow(job,editor).submit(True)
    assert editor.publishes == 0


def test_state_content_hash_and_manifest_tamper_rejected(job):
    state = read_json(job/'state.json')
    state['content_hash'] = 'tampered'
    write_json(job/'state.json',state)
    with pytest.raises(DoudianError):
        flow(job,FakeEditor())
    manifest = read_json(job/'manifest.json')
    manifest['title'] = 'tampered'
    write_json(job/'manifest.json',manifest)
    with pytest.raises(DoudianError):
        load_job(job)


def test_locks_are_exclusive_and_live_pid_cannot_unlock(tmp_path,monkeypatch):
    import doudian_auto.cli as cli
    monkeypatch.setattr(cli,'DATA_ROOT',tmp_path)
    with Lock(tmp_path/'browser.lock'):
        with pytest.raises(DoudianError):
            with Lock(tmp_path/'browser.lock'):
                pass
        with pytest.raises(DoudianError):
            unlock()
    assert not (tmp_path/'browser.lock').exists()


def test_cli_json_and_url_scope(capsys):
    assert main(['--json','resolve',URL]) == 0
    assert json.loads(capsys.readouterr().out)['data']['product_id'] == PID
    assert main(['--json','resolve','https://evil.example/ffa/g/create?product_id='+PID]) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'invalid_product'
    assert main(['--json','missing-command']) == 1
    assert json.loads(capsys.readouterr().out)['error']['code'] == 'invalid_arguments'

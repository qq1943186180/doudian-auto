from copy import deepcopy
import json
from pathlib import Path
import time
from types import SimpleNamespace

from PIL import Image
import pytest

from doudian_auto.cli import main, process_alive, unlock
from doudian_auto.errors import DoudianError
from doudian_auto.jobs import Lock, load_job, prepare, read_json, write_json
from doudian_auto.workflow import Workflow, resource_key

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


def wait_probe(probe, predicate, message='timeout', seconds=60):
    # Mirror the real bridge: keep probing until the predicate holds, then time out.
    deadline = time.monotonic() + seconds
    while True:
        result = probe()
        if predicate(result):
            return result
        if time.monotonic() >= deadline:
            raise DoudianError('page_timeout', message)
        time.sleep(0.01)


class FakeEditor:
    def __init__(self, wait_seconds=0.2):
        self.wait_seconds = wait_seconds
        self.bridge = SimpleNamespace(session='', wait=wait_probe)
        self.current = {'product_id':PID,'shop_confirmed':True,'title':'原有标题',
                        'mains':['old'+str(i) for i in range(5)],
                        'details':['old-detail1','old-detail2'],
                        'detail_status':'ready','detail_declared':2,'detail_cards':2,
                        'detail_delete_count':2,'detail_slots':2,'canvas_count':2,
                        'protected':[
                            {'section':'goodsEditScrollContainer-基础信息','observation':'ready','inputs':[],'selections':['无品牌'],'static_fields':[],'images':[]},
                            {'section':'goodsEditScrollContainer-价格库存','observation':'ready','inputs':[],'selections':['规格'],'static_fields':[],'images':[],
                             'price':'20.88','checked':True,'shipping':'48h'},
                            {'section':'goodsEditScrollContainer-服务与履约','observation':'ready','inputs':[],'selections':['非偏远'],'static_fields':[],'images':[]},
                        ],
                        'coverage':'fixture',
                        'draft_loaded':False,'rejected':False,'rejection_reasons':[],'rejection_count':None}
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

    def wait_details(self, manifest, seconds=30):
        try:
            return self.bridge.wait(lambda: self.read(manifest),
                                    lambda s: s.get('detail_status') in ('ready','empty'),
                                    '详情图数据源未就绪。', seconds=self.wait_seconds)
        except DoudianError as exc:
            if exc.code != 'page_timeout':
                raise
            snapshot = self.read(manifest)
            raise DoudianError('detail_source_not_ready', '详情图数据源未就绪：状态={0}。'.format(snapshot.get('detail_status')))

    def replace(self, manifest, kind, before_upload):
        self.replacements.append(kind)
        self.current[kind] = []
        before_upload()
        self.current[kind] = [f'https://cdn/ecom-shop-material/{kind}-{r["sha256"]}' for r in manifest[kind]]
        if kind == 'details':
            self.current.update({'detail_status':'ready','detail_declared':len(manifest[kind]),
                                 'detail_cards':len(manifest[kind]),'detail_delete_count':len(manifest[kind]),
                                 'detail_slots':len(manifest[kind])})
        if self.fail == kind:
            self.fail = None
            raise DoudianError('bridge_transport','unknown upload')
        return list(self.current[kind])

    def fill_title(self, manifest):
        self.current['title'] = manifest['title']

    def check(self, manifest):
        if self.fail == 'commercial':
            self.current['protected'][1]['checked'] = False
        return self.read(manifest)

    def publish(self, manifest):
        self.publishes += 1
        self.saved = deepcopy(self.current)
        if self.fail == 'submit_timeout':
            raise DoudianError('bridge_transport','unknown submit')
        if self.fail == 'wrong_saved':
            self.saved['details'].reverse()
        if self.fail == 'rejected':
            self.saved = deepcopy(self.publish_rejection)
        return getattr(self, 'publish_result', None) or {'state':'accepted','success':True,'rejected':False}

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
    editor.current['protected'][1][field] = value
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


def test_resource_key_normalizes_material_url_variants():
    base = 'https://p3-aio.ecombdimg.com/ecom-shop-material/jpeg_m_abc_sx_487564_www1024-1536'
    assert resource_key('https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_abc_sx_487564_www1024-1536') == base
    assert resource_key('https://p3-aio.ecombdimg.com/img/ecom-shop-material/jpeg_m_abc_sx_487564_www1024-1536~750x0_q90_b0.jpg') == base
    assert resource_key(base + '~tplv-qzsgku4lz6-fxg-image:0:q75.image') == base
    assert resource_key(base + '~tplv-qzsgku4lz6-fxg-image:0:q75.avis') == base
    assert resource_key(base + '?resize=600') == base
    assert resource_key('https://other.example/ecom-shop-material/jpeg_m_abc_sx_487564_www1024-1536') != base
    assert resource_key('https://p3-aio.ecombdimg.com/ecom-shop-material/jpeg_m_xyz_sx_487564_www1024-1536') != base
    assert resource_key('plain-value') == 'plain-value'
    assert resource_key('') == ''


def test_resume_skips_slot_when_rendition_differs_but_asset_matches(job):
    editor = FakeEditor()
    flow(job,editor).upload(True)
    # The platform re-served the very same assets under different rendition suffixes.
    editor.current['mains'] = [u + '~tplv-qzsgku4lz6-fxg-image:0:q75.avis' for u in editor.current['mains']]
    editor.current['details'] = [u + '~750x0_q90_b0.jpg' for u in editor.current['details']]
    editor.replacements.clear()
    flow(job,editor).upload(True)
    assert editor.replacements == []


def test_upload_waits_for_a_trusted_ready_snapshot_before_comparing(job):
    editor = FakeEditor()
    editor.current['detail_status'] = 'pending'
    with pytest.raises(DoudianError) as exc:
        flow(job,editor).upload(True)
    assert exc.value.code == 'detail_source_not_ready'
    assert not editor.replacements


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


# --- protected snapshot alignment -------------------------------------------
# The platform hides whole form blocks lazily, so the set of visible blocks differs
# between reads. These tests pin the contract: align by section name, never by position,
# and stop rather than assume when a block cannot be observed.

def section(name, observation='ready', **fields):
    base = {'section': 'goodsEditScrollContainer-' + name, 'observation': observation,
            'inputs': [], 'selections': [], 'static_fields': [], 'images': []}
    base.update(fields)
    return base


def assert_code(code, before, after):
    from doudian_auto.workflow import compare_protected
    with pytest.raises(DoudianError) as exc:
        compare_protected(before, after)
    assert exc.value.code == code


def test_protected_sections_align_by_name_not_by_position():
    from doudian_auto.workflow import compare_protected
    # Same three blocks, but the live read no longer enumerates the hidden ones, so any
    # positional comparison would read 基础信息 against 价格库存.
    before = {'protected': [section('基础信息', selections=['无品牌']),
                            section('价格库存', selections=['规格']),
                            section('服务与履约', selections=['非偏远'])]}
    after = {'protected': [section('基础信息', selections=['无品牌']),
                           section('价格库存', selections=['规格']),
                           section('服务与履约', selections=['非偏远'])]}
    compare_protected(before, after)  # must not raise


def test_protected_reordered_sections_do_not_report_a_change():
    from doudian_auto.workflow import compare_protected
    before = {'protected': [section('基础信息', selections=['无品牌']),
                            section('价格库存', selections=['规格']),
                            section('服务与履约', selections=['非偏远'])]}
    after = {'protected': [section('服务与履约', selections=['非偏远']),
                           section('基础信息', selections=['无品牌']),
                           section('价格库存', selections=['规格'])]}
    compare_protected(before, after)


def test_protected_missing_required_section_blocks():
    before = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约')]}
    after = {'protected': [section('基础信息'), section('价格库存')]}
    assert_code('protected_sections_missing', before, after)


def test_protected_unobserved_section_blocks_instead_of_being_skipped():
    before = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                            section('权益', observation='unobserved')]}
    after = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                           section('权益', observation='unobserved')]}
    assert_code('protected_snapshot_incomplete', before, after)


def test_protected_empty_block_is_exempt_only_when_both_sides_agree():
    from doudian_auto.workflow import compare_protected
    exempt = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                            section('权益', observation='empty_block')]}
    same = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                          section('权益', observation='empty_block')]}
    compare_protected(exempt, same)
    # A block that gained fields between reads must never be skipped: the exemption is
    # withdrawn and the new content is compared, so the change surfaces as a change.
    gained = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                            section('权益', selections=['新权益'])]}
    assert_code('commercial_changed', exempt, gained)
    # Merely becoming observable while staying byte-identical is not a change.
    still_same = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                                section('权益', observation='ready')]}
    compare_protected(exempt, still_same)


def test_protected_legacy_baseline_without_observation_state_is_accepted():
    from doudian_auto.workflow import compare_protected
    # The old collector emitted only visible blocks, so its membership is the observation
    # evidence; such a baseline must not block the run.
    legacy = {'protected': [section('基础信息', observation=None, selections=['无品牌']),
                            section('价格库存', observation=None, selections=['规格']),
                            section('服务与履约', observation=None, selections=['非偏远'])]}
    live = {'protected': [section('基础信息', selections=['无品牌']),
                          section('价格库存', selections=['规格']),
                          section('服务与履约', selections=['非偏远'])]}
    compare_protected(legacy, live)
    # The allowance covers the baseline only. A live read that fails to report its own
    # state is an instrumentation fault and must stop the run rather than pass.
    swapped = {'protected': [section('基础信息', observation=None), section('价格库存'),
                             section('服务与履约')]}
    assert_code('protected_snapshot_incomplete', live, swapped)


def test_protected_section_present_on_one_side_only_blocks():
    before = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                            section('其他信息', selections=[''])]}
    after = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约')]}
    assert_code('protected_snapshot_incomplete', before, after)


def test_protected_duplicate_or_missing_section_key_is_rejected():
    dup = {'protected': [section('基础信息'), section('基础信息'),
                         section('价格库存'), section('服务与履约')]}
    ok = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约')]}
    assert_code('protected_snapshot_incomplete', dup, ok)
    unnamed = {'protected': [{'observation': 'ready'}]}
    assert_code('protected_snapshot_incomplete', unnamed, unnamed)


def test_protected_legacy_positional_list_without_section_is_rejected():
    legacy = {'protected': [{'price': '20.88', 'checked': True}]}
    assert_code('protected_snapshot_incomplete', legacy, legacy)


def test_protected_real_change_in_a_non_required_section_still_blocks():
    before = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                            section('其他信息', selections=['报关单'])]}
    after = {'protected': [section('基础信息'), section('价格库存'), section('服务与履约'),
                           section('其他信息', selections=['质检报告'])]}
    assert_code('commercial_changed', before, after)


# --- submit outcome classification ------------------------------------------
# A submit has three distinct outcomes beyond "it worked": accepted then rejected by
# review, an explicit validation failure, and genuinely unknown. Collapsing any of them
# into "click failed" reopens the publish button for a submit that may have landed.

def test_rejected_after_submit_is_recorded_as_rejected_not_a_failed_click(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.fail = 'rejected'
    editor.publish_rejection = dict(editor.current, rejected=True, draft_loaded=True,
                                    rejection_count=1,
                                    rejection_reasons=['您选择的商品类目与商品实际类目不符'])
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'platform_rejected'
    state = read_json(job/'state.json')
    # The submit was accepted; the review failed. Recording it as a failed click would
    # let the next submit press 发布商品 again.
    assert state['stage'] == 'rejected'
    assert state['submission_status'] == 'accepted'
    assert state['review_status'] == 'rejected'
    assert state['rejection_reasons']
    assert editor.publishes == 1


def test_rejected_job_cannot_be_reuploaded_or_resubmitted(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.fail = 'rejected'
    editor.publish_rejection = dict(editor.current, rejected=True, rejection_count=1,
                                    rejection_reasons=['类目不符'])
    with pytest.raises(DoudianError):
        flow(job, editor).submit(True)
    # Both write paths must close; a new stage must not bypass the existing guard.
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).upload(True)
    assert exc.value.code == 'verify_required'
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'platform_rejected'
    assert editor.publishes == 1


def test_explicit_validation_failure_returns_to_uploaded(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.publish_result = {'state':'validation_failed','success':False,
                             'errors':['该项为必填项，请上传图片']}
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'platform_validation'
    state = read_json(job/'state.json')
    # Only an explicit validation failure proves the submit was not accepted.
    assert state['stage'] == 'uploaded'
    assert state['submission_status'] == 'not_submitted'


def test_unknown_submit_result_never_returns_to_uploaded(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.publish_result = {'state':'unknown','success':False}
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'submit_result_unknown'
    state = read_json(job/'state.json')
    # Returning to `uploaded` would re-arm publishing for a submit that may have landed.
    assert state['stage'] == 'submitting'
    assert state['submission_status'] == 'unknown'
    with pytest.raises(DoudianError):
        flow(job, editor).submit(True)
    assert editor.publishes == 1


def test_verify_reading_a_draft_never_claims_saved(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    flow(job, editor).submit(True)
    # The editor auto-loads the latest draft, so a matching readback proves nothing
    # about the live listing.
    editor.saved['draft_loaded'] = True
    result = flow(job, editor).verify()
    assert result['stage'] == 'submitted'
    assert result['verified'] is False
    assert result['draft_verified'] is True
    state = read_json(job/'state.json')
    assert state['stage'] == 'submitted'
    assert state['content_scope'] == 'draft'


def test_verify_reading_a_rejection_marks_rejected_and_keeps_reasons(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    flow(job, editor).submit(True)
    editor.saved['rejected'] = True
    editor.saved['draft_loaded'] = True
    editor.saved['rejection_reasons'] = ['类目不符']
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).verify()
    assert exc.value.code == 'platform_rejected'
    state = read_json(job/'state.json')
    assert state['stage'] == 'rejected'
    assert state['rejection_reasons'] == ['类目不符']
    assert state['content_scope'] == 'draft'


def test_verify_on_a_clean_live_page_still_claims_saved(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    flow(job, editor).submit(True)
    result = flow(job, editor).verify()
    assert result['stage'] == 'saved'
    assert result['verified'] is True
    assert read_json(job/'state.json')['stage'] == 'saved'


# --- submit outcome classification ------------------------------------------
# A submit has three distinct outcomes beyond "it worked": accepted then rejected by
# review, an explicit validation failure, and genuinely unknown. Collapsing any of them
# into "click failed" reopens the publish button for a submit that may have landed.

def test_rejected_after_submit_is_recorded_as_rejected_not_a_failed_click(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.fail = 'rejected'
    editor.publish_rejection = dict(editor.current, rejected=True, draft_loaded=True,
                                    rejection_count=1,
                                    rejection_reasons=['您选择的商品类目与商品实际类目不符'])
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'platform_rejected'
    state = read_json(job/'state.json')
    # The submit was accepted; the review failed. Recording it as a failed click would
    # let the next submit press 发布商品 again.
    assert state['stage'] == 'rejected'
    assert state['submission_status'] == 'accepted'
    assert state['review_status'] == 'rejected'
    assert state['rejection_reasons']
    assert editor.publishes == 1


def test_rejected_job_cannot_be_reuploaded_or_resubmitted(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.fail = 'rejected'
    editor.publish_rejection = dict(editor.current, rejected=True, rejection_count=1,
                                    rejection_reasons=['类目不符'])
    with pytest.raises(DoudianError):
        flow(job, editor).submit(True)
    # Both write paths must close; a new stage must not bypass the existing guard.
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).upload(True)
    assert exc.value.code == 'verify_required'
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'platform_rejected'
    assert editor.publishes == 1


def test_explicit_validation_failure_returns_to_uploaded(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.publish_result = {'state':'validation_failed','success':False,
                             'errors':['该项为必填项，请上传图片']}
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'platform_validation'
    state = read_json(job/'state.json')
    # Only an explicit validation failure proves the submit was not accepted.
    assert state['stage'] == 'uploaded'
    assert state['submission_status'] == 'not_submitted'


def test_unknown_submit_result_never_returns_to_uploaded(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    editor.publish_result = {'state':'unknown','success':False}
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).submit(True)
    assert exc.value.code == 'submit_result_unknown'
    state = read_json(job/'state.json')
    # Returning to `uploaded` would re-arm publishing for a submit that may have landed.
    assert state['stage'] == 'submitting'
    assert state['submission_status'] == 'unknown'
    with pytest.raises(DoudianError):
        flow(job, editor).submit(True)
    assert editor.publishes == 1


def test_verify_reading_a_draft_never_claims_saved(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    flow(job, editor).submit(True)
    # The editor auto-loads the latest draft, so a matching readback proves nothing
    # about the live listing.
    editor.saved['draft_loaded'] = True
    result = flow(job, editor).verify()
    assert result['stage'] == 'submitted'
    assert result['verified'] is False
    assert result['draft_verified'] is True
    state = read_json(job/'state.json')
    assert state['stage'] == 'submitted'
    assert state['content_scope'] == 'draft'


def test_verify_reading_a_rejection_marks_rejected_and_keeps_reasons(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    flow(job, editor).submit(True)
    editor.saved['rejected'] = True
    editor.saved['draft_loaded'] = True
    editor.saved['rejection_reasons'] = ['类目不符']
    with pytest.raises(DoudianError) as exc:
        flow(job, editor).verify()
    assert exc.value.code == 'platform_rejected'
    state = read_json(job/'state.json')
    assert state['stage'] == 'rejected'
    assert state['rejection_reasons'] == ['类目不符']
    assert state['content_scope'] == 'draft'


def test_verify_on_a_clean_live_page_still_claims_saved(job):
    editor = FakeEditor()
    flow(job, editor).upload(True)
    flow(job, editor).submit(True)
    result = flow(job, editor).verify()
    assert result['stage'] == 'saved'
    assert result['verified'] is True
    assert read_json(job/'state.json')['stage'] == 'saved'

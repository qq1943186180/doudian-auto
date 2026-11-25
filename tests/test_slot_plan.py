"""Slot plans: how many fixed image slots a revision actually replaces.

The writer replaces images by matching the old one, so a listing with two detail images
has no third and fourth source picture. These tests pin the plan's defaults (a baseline
without one behaves exactly like the old nine-slot contract), its validation, and the
prefix semantics the readback comparison uses.
"""
import pytest

from doudian_auto import batch
from doudian_auto.errors import DoudianError
from doudian_auto.miaoshou_batch_editor import (
    MiaoshouBatchEditor,
    _plan_from_baseline,
    _plan_from_slots,
    require_distinct_detail_sources,
    validate_batch_form_state,
)


def test_a_baseline_without_a_plan_keeps_the_full_nine_slots():
    # Every baseline written before this contract must keep its old meaning: five mains
    # and four details. Nothing that used to be compared stops being compared.
    plan = batch._slot_plan({'doudian_baseline': {}})
    assert plan == {'mains': 5, 'details': 4}
    assert batch._expected_slots(plan) == {
        'mains:1', 'mains:2', 'mains:3', 'mains:4', 'mains:5',
        'details:1', 'details:2', 'details:3', 'details:4'}


def test_a_recorded_plan_is_used_verbatim():
    plan = batch._slot_plan({'slot_plan': {'mains': 5, 'details': 2}})
    assert batch._expected_slots(plan) == {
        'mains:1', 'mains:2', 'mains:3', 'mains:4', 'mains:5',
        'details:1', 'details:2'}


@pytest.mark.parametrize('plan', [
    {'mains': 0, 'details': 2},      # nothing to replace
    {'mains': 6, 'details': 2},      # beyond the five-main cap
    {'mains': 5, 'details': 0},
    {'mains': 5, 'details': 5},      # beyond the four-detail cap
    {'mains': True, 'details': 2},   # bool is not a slot count
    {'mains': 5, 'details': None},
])
def test_an_impossible_plan_stops_instead_of_guessing(plan):
    with pytest.raises(DoudianError) as caught:
        batch._slot_plan({'slot_plan': plan})
    assert caught.value.code == 'invalid_slot_plan'


def test_the_plan_comes_from_the_listing_itself():
    snapshot = {'mains': ['m'] * 5, 'details': ['d'] * 2}
    assert batch._plan_for_snapshot(snapshot) == {'mains': 5, 'details': 2}
    # More details than the writer replaces are clipped, not rejected: the extra images
    # stay untouched because the replacement is per slot.
    assert batch._plan_for_snapshot({'mains': ['m'] * 5, 'details': ['d'] * 15}) == {
        'mains': 5, 'details': 4}


@pytest.mark.parametrize('snapshot', [
    {'mains': [], 'details': ['d']},
    {'mains': ['m'] * 6, 'details': ['d']},
    {'mains': ['m'], 'details': []},
])
def test_a_listing_with_no_slots_stops(snapshot):
    with pytest.raises(DoudianError) as caught:
        batch._plan_for_snapshot(snapshot)
    assert caught.value.code == 'writer_image_slots_incomplete'


def test_slot_sets_must_be_contiguous_and_within_the_cap():
    assert _plan_from_slots({'mains:1', 'mains:2', 'details:1'}) == {'mains': 2, 'details': 1}
    with pytest.raises(DoudianError):
        _plan_from_slots({'mains:1', 'mains:3', 'details:1'})   # hole in the numbering
    with pytest.raises(DoudianError):
        _plan_from_slots({*(f'mains:{i}' for i in range(1, 7)), 'details:1'})
    with pytest.raises(DoudianError):
        _plan_from_slots({'mains:01', 'details:1'})  # leading zero is not canonical
    with pytest.raises(DoudianError):
        _plan_from_slots({'mains:1', 'details:1', 'unknown:1'})


@pytest.mark.parametrize('bad', [None, True, 0, [], '5x4'])
def test_a_present_but_malformed_plan_stops_instead_of_falling_back(bad):
    # A missing key means "legacy full slots"; a *present* but malformed value must
    # never be silently downgraded to 5/4 — that would build a wrong readback
    # expectation from corrupt data. Both the batch and editor readers agree.
    with pytest.raises(DoudianError) as caught:
        batch._slot_plan({'slot_plan': bad})
    assert caught.value.code == 'invalid_slot_plan'
    with pytest.raises(DoudianError) as caught:
        _plan_from_baseline({'slot_plan': bad})
    assert caught.value.code == 'invalid_slot_plan'


def test_editor_plan_reader_matches_batch_and_keeps_legacy_default():
    assert _plan_from_baseline({'mains': ['m'] * 5}) == {'mains': 5, 'details': 4}
    assert _plan_from_baseline({'slot_plan': {'mains': 4, 'details': 2}}) == {'mains': 4, 'details': 2}


def _variable_form(tmp_path, *, extra_rows=0):
    """Build a 5-main/2-detail form state; extra_rows appends empty placeholder rows."""
    old_mains = [f'https://p3.example/ecom-shop-material/m{i}' for i in range(1, 6)]
    old_details = [f'https://p3.example/ecom-shop-material/d{i}' for i in range(1, 4)]
    mains = [f'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/x/main{i}.png?dy' for i in range(1, 6)]
    targets = [f'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/x/det{i}.png?dy' for i in range(1, 3)]
    baseline = {'product_id': '1234567890123456789', 'shop': '销霁百货', 'title': '原标题',
                'mains': old_mains, 'details': old_details,
                'slot_plan': {'mains': 5, 'details': 2}, 'protected': {'startSaleType': 0}}
    active = [{'source': old_details[i], 'target': targets[i]} for i in range(2)]
    extras = [{'source': None, 'target': None} for _ in range(extra_rows)]
    state = {
        'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field',
        'shop': '销霁百货', 'product_ids': [baseline['product_id']],
        'result_product_ids': [baseline['product_id']], 'result_count': 1,
        'selected_top_fields': ['title', 'image_change', 'desc'],
        'selected_enabled_options': ['new', 'onlyPreview', 'replaceImgsByImgUrls'],
        'title': '新标题', 'main_mode': 'replaceImgByIndex', 'timer_checked': False,
        'overlength': 'fail', 'main_images': mains,
        'detail_pairs': active + extras,
        'preview_detail': {'visible': True, 'labels': ['商品标题', '详情图', '主图'],
                           'old_title': '原标题', 'new_title': '新标题',
                           'old_mains': old_mains, 'new_mains': mains,
                           'old_details': old_details, 'new_details': targets + old_details[2:]},
    }
    from PIL import Image
    paths = []
    for index in range(7):
        p = tmp_path / f'a{index}.png'
        Image.new('RGB', (600, 600), (index, 20, 40)).save(p)
        paths.append(str(p))
    return baseline, state, paths


@pytest.mark.parametrize('extra_rows', [0, 2])
def test_form_validation_accepts_a_variable_slot_plan(tmp_path, extra_rows):
    # prepare() pads the page to four replace rows, so observe() may report empty
    # placeholder rows beyond the plan. They must be ignored, but only while empty.
    baseline, state, paths = _variable_form(tmp_path, extra_rows=extra_rows)
    mappings = validate_batch_form_state(state, product_id=baseline['product_id'],
                                         shop='销霁百货', title='新标题',
                                         baseline=baseline, asset_paths=paths)
    assert [m['slot'] for m in mappings] == (
        [f'mains:{i}' for i in range(1, 6)] + ['details:1', 'details:2'])


def test_prepare_requires_the_plan_on_the_baseline_it_receives(tmp_path, monkeypatch):
    # A new task builds a baseline carrying slot_plan and must pass THAT baseline
    # to the writer. Passing the raw read (no plan) falls back to 5/4 and rejects
    # a variable-slot listing before upload. Pin the entry check on both shapes.
    from PIL import Image
    paths = []
    for index in range(7):
        p = tmp_path / f'p{index}.png'
        Image.new('RGB', (600, 600), (index, 10, 20)).save(p)
        paths.append(str(p))
    main_paths, detail_paths = paths[:5], paths[5:7]

    class _Sentinel(Exception):
        pass

    editor = MiaoshouBatchEditor(None, '销霁百货')
    for name in ('open', 'close_image_picker_if_open', 'close_preview_if_open'):
        monkeypatch.setattr(editor, name, lambda *a, **k: None)
    monkeypatch.setattr(editor, 'observe', lambda: (_ for _ in ()).throw(_Sentinel()))

    # No plan on the baseline → the 5/4 fallback rejects 5-main/2-detail assets.
    raw = {'mains': [f'https://p3.example/m{i}' for i in range(5)],
           'details': [f'https://p3.example/d{i}' for i in range(3)]}
    with pytest.raises(DoudianError) as caught:
        editor.prepare(product_id='1', title='t', baseline=raw,
                       main_paths=main_paths, detail_paths=detail_paths)
    assert caught.value.code == 'asset_manifest_incomplete'

    # Planned baseline → entry check passes (reaches observe, our sentinel).
    planned = {**raw, 'slot_plan': {'mains': 5, 'details': 2}}
    with pytest.raises(_Sentinel):
        editor.prepare(product_id='1', title='t', baseline=planned,
                       main_paths=main_paths, detail_paths=detail_paths)


def test_form_validation_rejects_a_nonempty_row_beyond_the_plan(tmp_path):
    baseline, state, paths = _variable_form(tmp_path, extra_rows=2)
    state['detail_pairs'][2]['source'] = 'https://p3.example/ecom-shop-material/unreviewed'
    with pytest.raises(DoudianError) as caught:
        validate_batch_form_state(state, product_id=baseline['product_id'],
                                  shop='销霁百货', title='新标题',
                                  baseline=baseline, asset_paths=paths)
    assert caught.value.code == 'miaoshou_batch_unexpected_detail_row'


def test_distinct_sources_only_checks_the_replaced_prefix():
    # With B=2, details 3 and 4 are preserved (never replaced); duplicates among
    # them are harmless. But a replaced source duplicated anywhere must still stop.
    def u(tag):
        return f'https://p3.example/ecom-shop-material/{tag}'
    require_distinct_detail_sources([u('a'), u('b'), u('x'), u('x')], replaced=2)
    with pytest.raises(DoudianError) as caught:
        require_distinct_detail_sources([u('a'), u('a'), u('x'), u('y')], replaced=2)
    assert caught.value.code == 'writer_detail_source_collision'
    # A replaced source equal to a preserved tail image is also a collision.
    with pytest.raises(DoudianError):
        require_distinct_detail_sources([u('a'), u('b'), u('a'), u('y')], replaced=2)
    # Legacy call (no replaced) still checks the first four.
    require_distinct_detail_sources([u('a'), u('b'), u('c'), u('d')])
    with pytest.raises(DoudianError):
        require_distinct_detail_sources([u('a'), u('b'), u('x'), u('x')])


def test_finalize_tail_check_uses_the_planned_boundary():
    # With a short plan and a preserved tail, changing the third detail (the tail)
    # must still be rejected. A hard-coded [4:] slice used to skip this image.
    from doudian_auto import batch as b

    def key(tag):
        return 'jpeg_m_' + tag * 32 + '_sx_123_www600-600'

    def url(tag):
        return 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/' + key(tag)

    plan = {'mains': 5, 'details': 2}
    old_mains = [url('a') for _ in range(5)]
    old_details = [url('b'), url('c'), url('d')]
    baseline = {'slot_plan': plan, 'mains': old_mains, 'details': old_details}
    # Each new slot needs its own permanent key so it reads back as "changed".
    # Tags must be hex digits: the material-key regex only accepts [0-9a-f].
    new_mains = [url(str(i + 1)) for i in range(5)]
    new_details = [url('a'), url('b')]
    def mk(slot, u):
        return {'slot': slot, 'remote_key': u.rsplit('/', 1)[-1], 'remote_url': u,
                'source_sha256': '0' * 64, 'asset_state': 'permanent', 'confirmed': True}
    mappings = ([mk(f'mains:{i}', new_mains[i - 1]) for i in range(1, 6)] +
                [mk(f'details:{i}', new_details[i - 1]) for i in range(1, 3)])
    after_details = new_details + [old_details[2]]
    common = {'mains': new_mains}
    miao_after = {**common, 'details': after_details}
    doudian_after = {**common, 'details': after_details}
    # No asset_paths → skip content verification; tail comparison still runs.
    b._finalize_target_mappings(baseline, miao_after, doudian_after, mappings)
    changed_tail = {**common, 'details': after_details[:2] + [url('z')]}
    with pytest.raises(DoudianError) as caught:
        b._finalize_target_mappings(baseline, changed_tail, changed_tail, mappings)
    assert caught.value.code == 'final_detail_tail_changed'


def test_readback_compares_only_the_planned_prefix(monkeypatch):
    # Two detail slots: the first two must match the targets and the rest must be the
    # baseline's own images. A shorter plan must not silently skip the tail comparison.
    monkeypatch.setattr('doudian_auto.workflow.compare_protected', lambda *a, **k: None)
    plan = {'mains': 5, 'details': 2}
    mappings = ([{'slot': f'mains:{i}', 'remote_key': f'key-main-{i}'} for i in range(1, 6)] +
                [{'slot': f'details:{i}', 'remote_key': f'key-det-{i}'} for i in range(1, 3)])
    before = {'mains': [f'https://p3.example/ecom-shop-material/key-main-old-{i}' for i in range(1, 6)],
              'details': ['https://p3.example/ecom-shop-material/key-det-old-1',
                          'https://p3.example/ecom-shop-material/key-det-old-2',
                          'https://p3.example/ecom-shop-material/key-tail-1']}
    after = {'title': '同标题', 'draft_loaded': False, 'rejected': False,
             'mains': [f'https://p3.example/ecom-shop-material/key-main-{i}' for i in range(1, 6)],
             'details': ['https://p3.example/ecom-shop-material/key-det-1',
                         'https://p3.example/ecom-shop-material/key-det-2',
                         'https://p3.example/ecom-shop-material/key-tail-1']}
    assert batch._matches_doudian_target(before, after, '同标题', mappings, plan) is True
    # The untouched tail changing is still a mismatch.
    changed_tail = {**after, 'details': after['details'][:2] +
                    ['https://p3.example/ecom-shop-material/key-tail-2']}
    assert batch._matches_doudian_target(before, changed_tail, '同标题', mappings, plan) is False


def test_legacy_slot_block_prefix_is_recheckable(tmp_path):
    import json
    import time

    db_path = tmp_path / 'batch.sqlite3'
    src_path = tmp_path / 'src.json'
    pid = '3767496214443065490'
    src_path.write_text(json.dumps({
        'shop': '销霁百货',
        'products': [{'product_id': pid, 'shop': '销霁百货', 'title': '门塞门堵'}],
    }, ensure_ascii=False), encoding='utf-8')
    created = batch.create_batch(str(src_path), shop='销霁百货', db_path=db_path)
    task_id = batch.batch_status(created['batch_id'], db_path=db_path)['products'][0]['id']
    conn = batch._db(db_path)
    try:
        conn.execute(
            "UPDATE products SET state='blocked', last_error=? WHERE id=?",
            ('writer_image_slots_incomplete: 官方及妙手均为4张主图/4张详情，v5要求5张原主图。', task_id),
        )
        conn.commit()
        row = conn.execute('SELECT * FROM products WHERE id=?', (task_id,)).fetchone()
        target_version = row['target_version']
        assert batch._preflight_blocked_reason(row) is True
    finally:
        conn.close()

    proof_path = tmp_path / 'summary.json'
    proof_path.write_text(json.dumps({
        'products': [{
            'task_id': task_id,
            'product_id': pid,
            'shop': '销霁百货',
            'target_version': target_version,
            'read_only': True,
            'state': 'eligible',
            'eligible': True,
            'evidence': {
                'snapshot_read': True,
                'observed_at': time.time(),
                'snapshot_sha256': 'a' * 64,
                'miaoshou_listed': True,
            },
        }],
    }, ensure_ascii=False), encoding='utf-8')
    out = batch.apply_preflight_report(task_id, str(proof_path), db_path=db_path)
    assert out['state'] == 'needs_agent'
    assert out['outcome'] == 'reopened'


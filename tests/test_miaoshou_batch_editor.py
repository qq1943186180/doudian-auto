import pytest
from PIL import Image

from doudian_auto.errors import DoudianError
from doudian_auto.miaoshou_batch_editor import (
    MiaoshouBatchEditor,
    _batch_page_ready,
    validate_batch_form_state,
    validate_submission_ready_state,
)


def _form(tmp_path):
    old_mains = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_old{i}_sx_123_www600-600'
                 for i in range(5)]
    old_details = [f'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/jpeg_m_detail{i}_sx_123_www600-600'
                   for i in range(6)]
    mains = [f'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-10-28/x/main{i}.png?dy'
             for i in range(5)]
    details = [f'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-10-28/x/detail{i}.png?dy'
               for i in range(4)]
    paths = []
    for index in range(9):
        path = tmp_path / f'asset-{index}.png'
        Image.new('RGB', (600, 600), (index, 30, 70)).save(path)
        paths.append(str(path))
    pid = '3848324080143040538'
    title = '折叠伸缩沥水篮可挂洗菜洗水果厨房多功能'
    baseline = {'product_id': pid, 'shop': '销霁百货', 'title': '原商品标题',
                'mains': old_mains, 'details': old_details,
                'protected': {'startSaleType': 0}}
    state = {
        'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field',
        'shop': '销霁百货', 'product_ids': [pid], 'result_product_ids': [pid],
        'result_count': 1, 'selected_top_fields': ['title', 'image_change', 'desc'],
        'selected_enabled_options': ['new', 'onlyPreview', 'replaceImgsByImgUrls'],
        'title': title, 'main_mode': 'replaceImgByIndex', 'timer_checked': False, 'overlength': 'fail',
        'main_images': mains,
        'detail_pairs': [{'source': old_details[i], 'target': details[i]} for i in range(4)],
        'preview_detail': {'visible': True, 'labels': ['商品标题', '详情图', '主图'],
                           'old_title': baseline['title'], 'new_title': title,
                           'old_mains': old_mains, 'new_mains': mains,
                           'old_details': list(old_details), 'new_details': details + old_details[4:]},
    }
    return pid, title, baseline, paths, state


def test_multi_field_form_accepts_exact_title_and_image_whitelist_without_quick_editor_control(tmp_path):
    pid, title, baseline, paths, state = _form(tmp_path)

    mappings = validate_batch_form_state(state, product_id=pid, shop='销霁百货',
                                         title=title, baseline=baseline, asset_paths=paths)

    assert [item['slot'] for item in mappings] == (
        [f'mains:{slot}' for slot in range(1, 6)] +
        [f'details:{slot}' for slot in range(1, 5)])
    assert all(item['asset_state'] == 'staged' for item in mappings)
    # The page has no startSaleType input. The intended shelf mode remains part of
    # the server-side baseline and is checked again after the independent readbacks.
    assert 'shelf_mode_control' not in state
    assert baseline['protected']['startSaleType'] == 0


def test_loaded_form_recognition_does_not_depend_on_exact_page_heading():
    snapshot = {
        'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field',
        'tree_text': '您好【销霁百货】 修改范围 按商品ID修改 请输入商品ID',
    }

    assert _batch_page_ready(snapshot, '销霁百货')
    snapshot['tree_text'] = '您好【另一家店】 修改范围 按商品ID修改 请输入商品ID'
    assert not _batch_page_ready(snapshot, '销霁百货')


def test_open_attaches_single_existing_user_owned_miaoshou_batch_tab():
    class FakeBridge:
        def __init__(self):
            self.calls = []

        def require_ready(self):
            self.calls.append(('require_ready', None))

        def command(self, action, args=None):
            self.calls.append((action, args))
            if action == 'list_tabs':
                return {'tabs': []}
            if action == 'list_browser_tabs':
                return {'tabs': [{'tabId': 12,
                                  'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field'}]}
            if action == 'attach_tab':
                return {'success': True, 'borrowed': True}
            if action == 'snapshot':
                return {'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field',
                        'tree_text': '您好【销霁百货】 修改范围 按商品ID修改 请输入商品ID'}
            raise AssertionError(f'unexpected browser command: {action}')

        def wait(self, probe, predicate, message, seconds):
            result = probe()
            assert predicate(result), message
            return result

    bridge = FakeBridge()
    editor = MiaoshouBatchEditor(bridge, '销霁百货')

    page = editor.open()

    assert page['url'].startswith('https://v2-dd.chengji-inc.com/product/batch/edit')
    assert [action for action, _ in bridge.calls].count('attach_tab') == 1
    assert 'navigate' not in [action for action, _ in bridge.calls]


def test_open_selects_exact_batch_tab_when_same_host_quick_editor_also_exists():
    class FakeBridge:
        def __init__(self):
            self.calls = []

        def require_ready(self):
            pass

        def command(self, action, args=None):
            self.calls.append((action, args))
            if action == 'list_tabs':
                return {'tabs': [
                    {'tabId': 21, 'url': 'https://v2-dd.chengji-inc.com/product/quick_edit'},
                    {'tabId': 22, 'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field'},
                ]}
            if action == 'attach_tab':
                return {'success': True, 'borrowed': True}
            if action == 'snapshot':
                return {'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field',
                        'tree_text': '您好【销霁百货】 修改范围 按商品ID修改 请输入商品ID'}
            raise AssertionError(f'unexpected browser command: {action}')

        def wait(self, probe, predicate, message, seconds):
            result = probe()
            assert predicate(result), message
            return result

    bridge = FakeBridge()
    editor = MiaoshouBatchEditor(bridge, '销霁百货')

    editor.open()

    assert ('attach_tab', {'tabId': 22}) in bridge.calls
    assert not any(action == 'find_tab' for action, _ in bridge.calls)


def test_submission_requires_fresh_page_preview_and_one_enabled_save_button(tmp_path):
    pid, title, baseline, paths, state = _form(tmp_path)
    mappings = validate_batch_form_state(state, product_id=pid, shop='销霁百货',
                                         title=title, baseline=baseline, asset_paths=paths)
    state['submit_control'] = {'button_count': 1, 'button_text': '开始批量修改',
                               'button_disabled': False, 'visible_modal_count': 0}

    assert validate_submission_ready_state(state, product_id=pid, shop='销霁百货',
                                           title=title, mappings=mappings)

    state['submit_control']['button_count'] = 0
    with pytest.raises(DoudianError) as rejected:
        validate_submission_ready_state(state, product_id=pid, shop='销霁百货',
                                        title=title, mappings=mappings)
    assert rejected.value.code == 'miaoshou_batch_submit_button_unavailable'


@pytest.mark.parametrize('change,code', [
    (lambda state: state.update(selected_top_fields=['title', 'image_change', 'desc', 'stock']),
     'miaoshou_batch_field_scope'),
    (lambda state: state.update(result_product_ids=['3848324080143040538', 'other']),
     'miaoshou_batch_scope_mismatch'),
    (lambda state: state['detail_pairs'][1].update(source=state['detail_pairs'][0]['source']),
     'miaoshou_batch_source_mismatch'),
    (lambda state: state.update(timer_checked=True), 'miaoshou_batch_timer_enabled'),
    (lambda state: state.update(overlength='cut'), 'miaoshou_batch_title_truncation'),
    (lambda state: state['preview_detail'].update(new_mains=['wrong'] * 5),
     'miaoshou_batch_preview_main_target_mismatch'),
    (lambda state: state['preview_detail']['old_details'].pop(),
     'miaoshou_batch_preview_detail_source_mismatch'),
    (lambda state: state['preview_detail']['new_details'].pop(),
     'miaoshou_batch_preview_detail_target_mismatch'),
    (lambda state: state['preview_detail']['new_details'].__setitem__(slice(4, None),
                     list(reversed(state['preview_detail']['new_details'][4:]))),
     'miaoshou_batch_preview_detail_target_mismatch'),
])
def test_multi_field_form_rejects_scope_or_preview_drift(tmp_path, change, code):
    pid, title, baseline, paths, state = _form(tmp_path)
    change(state)

    with pytest.raises(DoudianError) as rejected:
        validate_batch_form_state(state, product_id=pid, shop='销霁百货',
                                  title=title, baseline=baseline, asset_paths=paths)

    assert rejected.value.code == code


def test_default_adapter_cannot_submit_or_submit_outside_its_three_product_scope():
    from doudian_auto.miaoshou_batch_editor import WRITER_REVISION
    class ForbiddenBridge:
        def command(self, *args, **kwargs):
            pytest.fail('scope must be checked before any page action')
    for scope in (None, {'kind': 'acceptance', 'writer_revision': WRITER_REVISION,
                         'product_ids': ['1', '2', '3']}):
        editor = MiaoshouBatchEditor(ForbiddenBridge(), '销霁百货', submission_scope=scope)
        with pytest.raises(DoudianError) as rejected:
            editor.prepare_submission(product_id='4', shop='销霁百货', title='目标标题', mappings=[])
        assert rejected.value.code == 'writer_not_accepted'


def test_successful_upload_is_confirmed_by_the_exact_slot_even_when_picker_stays_open(tmp_path, monkeypatch):
    url = 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-10-29/x/asset.png?dy'
    calls = []
    class Bridge:
        def command(self, action, args=None):
            calls.append((action, args))
            return {'success': True}
        def evaluate(self, code):
            return {'dialogs': 1, 'files': 1}
        def wait(self, probe, predicate, message, seconds):
            value = probe()
            assert predicate(value)
            return value
    path = tmp_path/'asset.png'
    Image.new('RGB', (600,600), 'red').save(path)
    editor = MiaoshouBatchEditor(Bridge(), '销霁百货')
    monkeypatch.setattr(editor, '_checked_content', lambda actual, source: {'remote_url': actual, 'match': 'bytes'})
    monkeypatch.setattr('doudian_auto.miaoshou_editor.MiaoshouEditor._close_replace_popup', lambda self: calls.append(('close_picker', None)))
    result = editor._upload_open_image_dialog(path, lambda: url)
    assert result['remote_url'] == url
    assert [action for action, _ in calls].count('upload') == 1
    assert [action for action, _ in calls].count('close_picker') == 1


def test_initial_range_form_is_ready_before_product_id_tab_mounts_input():
    from doudian_auto.miaoshou_batch_editor import _batch_page_ready
    state = {'url': 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field',
             'tree_text': '您好【销霁百货】 修改范围 按范围修改 按商品修改 按商品ID修改'}
    assert _batch_page_ready(state, '销霁百货')
    state['url'] = state['url'].replace('multi_field', 'title')
    assert not _batch_page_ready(state, '销霁百货')


@pytest.mark.parametrize('reuse,auto_closed', [(False, False), (True, False), (False, True)])
def test_detail_target_uses_filter_picker_and_resumes_verified_material_without_reupload(tmp_path, monkeypatch, reuse, auto_closed):
    url = 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-10-29/x/detail.png?dy'
    actions = []
    class Bridge:
        def command(self, action, args=None):
            actions.append((action, args))
        def evaluate(self, code):
            assert '.select-product-filter-dialog' in code
            assert '.replace-image-dialog' not in code
            if 'return {dialogs' not in code:
                return 0 if auto_closed else 1
            return {'dialogs': 1, 'files': 0 if reuse else 1}
        def wait(self, probe, predicate, message, seconds):
            value = probe()
            assert predicate(value)
            return value
    editor = MiaoshouBatchEditor(Bridge(), '销霁百货')
    monkeypatch.setattr(editor, '_checked_content', lambda actual, source: {'remote_url': actual, 'match': 'bytes'})
    monkeypatch.setattr(editor, '_click_exact_text', lambda selector, text: actions.append(('click_text', (selector, text))))
    monkeypatch.setattr(editor, '_fill_visible', lambda selector, value: actions.append(('fill', (selector, value))))
    monkeypatch.setattr(editor, '_wait_eval', lambda code, predicate, message, seconds: predicate(0))

    result = editor._upload_open_image_dialog(tmp_path/'detail.png', lambda: url, reuse=url if reuse else None, detail=True)

    assert result['remote_url'] == url
    uploads = [args for action, args in actions if action == 'upload']
    assert len(uploads) == (0 if reuse else 1)
    if uploads:
        assert uploads[0]['selector'] == '.select-product-filter-dialog input[type="file"]'
    else:
        assert ('fill', ('.select-product-filter-dialog textarea[placeholder*="过滤的图片链接"]', url)) in actions
    assert (('click_text', ('.select-product-filter-dialog button', '关闭')) in actions) is not auto_closed


def test_checkbox_that_does_not_toggle_stops_without_a_second_click():
    class Bridge:
        clicks = 0
        def evaluate(self, code):
            if 'return xs.length===1&&' in code:
                return False
            if 'return {count:1}' in code:
                return {'count': 1}
            return True
        def command(self, action, args):
            self.clicks += action == 'click'
        def wait(self, probe, predicate, message, seconds):
            if not predicate(probe()):
                raise DoudianError('page_timeout', message)
    bridge = Bridge()
    editor = MiaoshouBatchEditor(bridge, '销霁百货')
    with pytest.raises(DoudianError) as rejected:
        editor._ensure_checkbox('title', True)
    assert rejected.value.code == 'miaoshou_batch_timeout'
    assert bridge.clicks == 1


@pytest.mark.parametrize('same', [True, False])
def test_resuming_a_populated_detail_source_does_not_click_wrapping_checkbox(same):
    source = 'https://p3-aio.ecombdimg.com/obj/ecom-shop-material/original.jpeg'
    class Bridge:
        def evaluate(self, code):
            return source if same else source.replace('original', 'different')
        def command(self, *args, **kwargs):
            pytest.fail('a populated source box must not be clicked')
    editor = MiaoshouBatchEditor(Bridge(), '销霁百货')
    if same:
        editor._select_detail_source(0, source)
    else:
        with pytest.raises(DoudianError) as rejected:
            editor._select_detail_source(0, source)
        assert rejected.value.code == 'miaoshou_batch_source_mismatch'


@pytest.mark.parametrize('kind', ['mains', 'details'])
@pytest.mark.parametrize('matches', [True, False])
def test_upload_received_before_mapping_was_saved_is_checked_without_clicking(kind, matches, tmp_path, monkeypatch):
    url = 'https://dy-honor-dd-pub.chengji-inc.com/tmp_upload/2026-10-29/x/arrived.png?dy'
    class Bridge:
        def command(self, *args, **kwargs):
            pytest.fail('a populated target must be reconciled without any browser mutation')
    editor = MiaoshouBatchEditor(Bridge(), '销霁百货')
    monkeypatch.setattr(editor, '_read_target_slot', lambda actual_kind, index: url)
    def check(actual, path):
        assert actual == url
        if not matches:
            raise DoudianError('material_content_mismatch', 'wrong bytes')
        return {'remote_url': actual, 'match': 'bytes'}
    monkeypatch.setattr(editor, '_checked_content', check)
    def invoke():
        if kind == 'mains':
            return editor._upload_slot_image('.replace-img-item .add-img-box', 0, tmp_path/'asset.png', 5)
        return editor._upload_detail_target(0, tmp_path/'asset.png')
    if matches:
        assert invoke()['remote_url'] == url
    else:
        with pytest.raises(DoudianError) as rejected:
            invoke()
        assert rejected.value.code == 'material_content_mismatch'

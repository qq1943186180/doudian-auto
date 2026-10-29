"""UI adapter for Miaoshou's observed multi-field product editor.

This route writes only the explicitly selected title, main-image, and detail-image
fields. It deliberately does not use MiaoshouEditor's quick-editor form, which has
no readable control for preserving the post-review shelf mode.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .errors import DoudianError
from .materials import verify_material_content
from .workflow import is_permanent_material_url, is_temporary_upload_url, resource_key


MIAOSHOU_HOST = 'v2-dd.chengji-inc.com'
BATCH_EDIT_URL = 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=multi_field'
WRITER_REVISION = 'multi-field-20261029-v4'
_TOP_FIELDS = {
    'title', 'short_product_name', 'brand_id', 'item_num', 'product_format',
    'fabric_material', 'price', 'size_temp', 'transport_id', '7day_return',
    'three_guarantees', 'quality', 'install_service', 'stock', 'presell_type',
    'image_change', 'spec_pic', 'sku_pic', 'main_image_three_to_four', 'desc', 'video',
}
_REQUIRED_FIELDS = {'title', 'image_change', 'desc'}
_REQUIRED_OPTIONS = {'new', 'onlyPreview', 'replaceImgsByImgUrls'}
_CHECKBOX_PROBE = Path(__file__).with_name('miaoshou_checkbox.js').read_text(encoding='utf-8')
# The warehouse readback policy now distinguishes startSaleType from current shelf
# state. New saves remain closed while the writer's complete acceptance is pending;
# a successful read-only reconciliation alone does not validate new write attempts.
SHELF_MODE_PRESERVATION_VERIFIED = False
SHELF_MODE_BLOCK_MESSAGE = (
    'startSaleType 已按审核后去向解释，仓库状态的只读核验已修正；新保存流程尚待完整验收，写入器暂未开放。'
)


def _batch_page_ready(snapshot, shop):
    """Recognize the loaded form by route and controls, not its page heading."""
    if not isinstance(snapshot, dict):
        return False
    parsed = urlparse(str(snapshot.get('url') or ''))
    if (parsed.hostname != MIAOSHOU_HOST or parsed.path != '/product/batch/edit' or
            parse_qs(parsed.query).get('batchType') != ['multi_field']):
        return False
    text = str(snapshot.get('tree_text') or '')
    return (f'您好【{shop}】' in text and ('按商品ID修改' in text or '请输入商品ID' in text) and
            ('修改范围' in text or '综合修改(多字段修改)' in text))


def validate_batch_form_state(state, *, product_id, shop, title, baseline, asset_paths):
    """Pure fail-closed check for the observed form and its per-product preview."""
    if not isinstance(state, dict):
        raise DoudianError('miaoshou_batch_state_invalid', '妙手批量编辑页没有返回结构化状态。')
    parsed = urlparse(str(state.get('url') or ''))
    if (parsed.hostname != MIAOSHOU_HOST or parsed.path != '/product/batch/edit' or
            parse_qs(parsed.query).get('batchType') != ['multi_field']):
        raise DoudianError('miaoshou_batch_wrong_page', '当前页不是妙手“综合修改(多字段修改)”页面。')
    if state.get('shop') != shop:
        raise DoudianError('wrong_shop', '妙手批量编辑页的店铺与任务不一致。')
    if state.get('product_ids') != [str(product_id)] or state.get('result_product_ids') != [str(product_id)]:
        raise DoudianError('miaoshou_batch_scope_mismatch', '批量编辑页必须只筛选到任务中的单个商品ID。')
    if state.get('result_count') != 1:
        raise DoudianError('miaoshou_batch_scope_mismatch', '妙手预览没有精确收敛到1件商品。')
    selected_fields = set(state.get('selected_top_fields') or [])
    if selected_fields != _REQUIRED_FIELDS:
        raise DoudianError('miaoshou_batch_field_scope', '批量修改字段必须且只能是标题、主图和详情图。')
    selected_options = set(state.get('selected_enabled_options') or [])
    if selected_options != _REQUIRED_OPTIONS:
        raise DoudianError('miaoshou_batch_option_scope', '标题、主图或详情图的修改方式与已验证配置不一致。')
    if state.get('title') != title or state.get('main_mode') != 'replaceImgByIndex':
        raise DoudianError('miaoshou_batch_target_mismatch', '标题内容或主图替换方式与目标版本不一致。')
    if state.get('timer_checked') is not False:
        raise DoudianError('miaoshou_batch_timer_enabled', '批量修改页启用了定时执行，拒绝提交。')
    if state.get('overlength') != 'fail':
        raise DoudianError('miaoshou_batch_title_truncation', '标题超长必须按失败处理，不能自动删字。')

    before_mains = [resource_key(x) for x in baseline.get('mains', [])]
    before_details = [resource_key(x) for x in baseline.get('details', [])]
    if len(before_mains) != 5 or len(before_details) < 4:
        raise DoudianError('baseline_incomplete', '商品图片基线不完整，不能提交批量修改。')
    target_paths = [Path(x).resolve() for x in asset_paths]
    if len(target_paths) != 9 or any(not path.is_file() for path in target_paths):
        raise DoudianError('asset_manifest_incomplete', '批量编辑必须提供5张主图和4张详情图。')

    mains = list(state.get('main_images') or [])
    detail_pairs = list(state.get('detail_pairs') or [])
    if len(mains) != 5 or len(detail_pairs) != 4:
        raise DoudianError('miaoshou_batch_slots_incomplete', '批量编辑页没有5个主图和4组详情替换槽位。')
    source_detail_keys = [resource_key(pair.get('source')) for pair in detail_pairs]
    if source_detail_keys != before_details[:4]:
        raise DoudianError('miaoshou_batch_source_mismatch', '详情图替换来源与实时基线不一致。')
    target_urls = mains + [pair.get('target') for pair in detail_pairs]
    if any(not (is_temporary_upload_url(url) or is_permanent_material_url(url)) for url in target_urls):
        raise DoudianError('miaoshou_batch_target_unreadable', '至少一个目标图片槽位没有读回可识别的妙手素材地址。')

    modal = state.get('preview_detail')
    if not isinstance(modal, dict) or modal.get('visible') is not True:
        raise DoudianError('miaoshou_batch_preview_missing', '尚未打开商品的修改前后详情预览。')
    if modal.get('old_title') != baseline.get('title') or modal.get('new_title') != title:
        raise DoudianError('miaoshou_batch_preview_title_mismatch', '修改前后标题预览与商品基线或目标不一致。')
    if [resource_key(x) for x in modal.get('old_mains', [])] != before_mains:
        raise DoudianError('miaoshou_batch_preview_main_source_mismatch', '主图预览的原图顺序与实时基线不一致。')
    if [resource_key(x) for x in modal.get('old_details', [])] != before_details:
        raise DoudianError('miaoshou_batch_preview_detail_source_mismatch', '详情图预览来源与实时基线不一致。')
    if [resource_key(x) for x in modal.get('new_mains', [])] != [resource_key(x) for x in mains]:
        raise DoudianError('miaoshou_batch_preview_main_target_mismatch', '5张主图的修改后预览与目标槽位不一致。')
    expected_details = [resource_key(x) for x in target_urls[5:]] + before_details[4:]
    if [resource_key(x) for x in modal.get('new_details', [])] != expected_details:
        raise DoudianError('miaoshou_batch_preview_detail_target_mismatch', '详情图预览未完整保留4张替换图和其余原图顺序。')
    if modal.get('labels') != ['商品标题', '详情图', '主图']:
        raise DoudianError('miaoshou_batch_preview_layout_changed', '妙手修改前后预览结构发生变化。')

    mappings = []
    for index, (path, url) in enumerate(zip(target_paths, target_urls)):
        kind, slot = ('mains', index + 1) if index < 5 else ('details', index - 4)
        if is_permanent_material_url(url):
            key, asset_state = resource_key(url), 'permanent'
        else:
            key, asset_state = url, 'staged'
        mappings.append({'slot': f'{kind}:{slot}',
                         'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                         'remote_key': key, 'remote_url': url,
                         'asset_state': asset_state, 'confirmed': True})
    return mappings


def validate_submission_ready_state(state, *, product_id, shop, title, mappings):
    """Validate the page-level preview before persisting a save intent."""
    if not isinstance(state, dict):
        raise DoudianError('miaoshou_batch_submit_state_invalid', '妙手提交预览状态不可读。')
    parsed = urlparse(str(state.get('url') or ''))
    if (parsed.hostname != MIAOSHOU_HOST or parsed.path != '/product/batch/edit' or
            parse_qs(parsed.query).get('batchType') != ['multi_field']):
        raise DoudianError('miaoshou_batch_wrong_page', '当前页不是妙手多字段编辑页面。')
    if (state.get('shop') != shop or state.get('product_ids') != [str(product_id)] or
            state.get('result_product_ids') != [str(product_id)] or state.get('result_count') != 1):
        raise DoudianError('miaoshou_batch_scope_mismatch', '提交预览必须只包含任务中的单个商品。')
    if (set(state.get('selected_top_fields') or []) != _REQUIRED_FIELDS or
            set(state.get('selected_enabled_options') or []) != _REQUIRED_OPTIONS or
            state.get('title') != title or state.get('main_mode') != 'replaceImgByIndex' or
            state.get('timer_checked') is not False or state.get('overlength') != 'fail'):
        raise DoudianError('miaoshou_batch_submit_form_changed', '提交预览中的字段、标题或定时选项发生变化。')
    by_slot = {item.get('slot'): item for item in mappings if isinstance(item, dict)}
    expected_slots = {*(f'mains:{slot}' for slot in range(1, 6)),
                      *(f'details:{slot}' for slot in range(1, 5))}
    if set(by_slot) != expected_slots or len(mappings) != len(expected_slots):
        raise DoudianError('uploads_incomplete', '提交预览前缺少完整的9个素材槽位映射。')
    expected_mains = [resource_key(by_slot[f'mains:{slot}'].get('remote_url')) for slot in range(1, 6)]
    expected_details = [resource_key(by_slot[f'details:{slot}'].get('remote_url')) for slot in range(1, 5)]
    actual_details = [resource_key(item.get('target')) for item in state.get('detail_pairs') or []]
    if ([resource_key(item) for item in state.get('main_images') or []] != expected_mains or
            actual_details != expected_details):
        raise DoudianError('miaoshou_batch_submit_assets_changed', '提交预览的图片槽位与已校验素材映射不一致。')
    control = state.get('submit_control') or {}
    if (control.get('button_count') != 1 or control.get('button_text') != '开始批量修改' or
            control.get('button_disabled') is not False):
        raise DoudianError('miaoshou_batch_submit_button_unavailable', '最终提交按钮不存在、不唯一或不可用。')
    if control.get('visible_modal_count') != 0:
        raise DoudianError('miaoshou_batch_modal_open', '妙手仍有打开的图片/筛选窗口，不能开始保存。')
    return True


class MiaoshouBatchEditor:
    """Drive the observed batch-edit form using visible page controls only."""

    def __init__(self, bridge, shop, *, session='miaoshou-auto-batch-20261028', submission_scope=None):
        self.bridge = bridge
        self.shop = shop
        self.session = session
        self.submission_scope = submission_scope
        self._content_checks = {}

    def _require_submission_scope(self, product_id):
        scope = self.submission_scope or {}
        ids = scope.get('product_ids') or []
        if (scope.get('writer_revision') != WRITER_REVISION or
                scope.get('kind') not in ('acceptance', 'verified') or
                str(product_id) not in ids or
                (scope.get('kind') == 'acceptance' and len(set(ids)) != 3) or
                (scope.get('kind') == 'verified' and not scope.get('acceptance_sha256'))):
            raise DoudianError('writer_not_accepted', '本商品未取得三件验收范围或已验证写入器范围，未保存。')

    def _checked_content(self, url, path):
        source_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        key = (url, source_hash)
        if key not in self._content_checks:
            self._content_checks[key] = verify_material_content(url, path)
        return self._content_checks[key]

    def _fill_visible(self, selector, value):
        marker = uuid.uuid4().hex
        count = self.bridge.evaluate("(()=>{const xs=[...document.querySelectorAll(" + json.dumps(selector) +
            ")].filter(x=>x.offsetParent!==null&&!x.disabled);if(xs.length===1)xs[0].setAttribute('data-codex-miao-batch'," +
            json.dumps(marker) + ");return xs.length})()")
        if count != 1:
            raise DoudianError('miaoshou_batch_input_ambiguous', '妙手输入控件不唯一，已停止。')
        try:
            self.bridge.command('fill', {'selector': '[data-codex-miao-batch="' + marker + '"]', 'value': value})
        finally:
            self.bridge.evaluate("(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker +
                "\"]').forEach(x=>x.removeAttribute('data-codex-miao-batch'));return true})()")

    def _visible(self, seconds=30):
        def probe():
            return self.bridge.command('snapshot', {'format': 'aria', 'max_chars': 10000})
        try:
            snap = self.bridge.wait(probe,
                lambda item: _batch_page_ready(item, self.shop),
                '妙手批量编辑页或店铺登录态未加载。', seconds=seconds)
        except DoudianError as exc:
            if exc.code == 'page_timeout':
                raise DoudianError('miaoshou_batch_timeout', '妙手批量编辑页加载超时。') from exc
            raise
        parsed = urlparse(snap.get('url', ''))
        if parsed.hostname != MIAOSHOU_HOST or parsed.path != '/product/batch/edit':
            raise DoudianError('miaoshou_batch_wrong_page', '浏览器当前页不在妙手批量编辑路由。')
        return snap

    def open(self, *, reuse_existing=True):
        self.bridge.require_ready()
        if reuse_existing:
            tabs = self.bridge.command('list_tabs') or {}
            matches = [tab for tab in tabs.get('tabs', [])
                       if urlparse(tab.get('url', '')).hostname == MIAOSHOU_HOST and
                       urlparse(tab.get('url', '')).path == '/product/batch/edit' and
                       parse_qs(urlparse(tab.get('url', '')).query).get('batchType') == ['multi_field']]
            if len(matches) > 1:
                raise DoudianError('miaoshou_batch_tab_ambiguous', '妙手批量编辑标签不唯一，拒绝选择。')
            if matches:
                self.bridge.command('attach_tab', {'tabId': matches[0]['tabId']})
                return self._visible()
            # Authenticated task pages may be user-owned (and therefore omitted by
            # list_tabs). Reuse the one exact route globally before opening another
            # tab; attach_tab marks it borrowed so session cleanup cannot close it.
            browser_tabs = self.bridge.command('list_browser_tabs') or {}
            matches = [tab for tab in browser_tabs.get('tabs', [])
                       if urlparse(tab.get('url', '')).hostname == MIAOSHOU_HOST and
                       urlparse(tab.get('url', '')).path == '/product/batch/edit' and
                       parse_qs(urlparse(tab.get('url', '')).query).get('batchType') == ['multi_field']]
            if len(matches) > 1:
                raise DoudianError('miaoshou_batch_tab_ambiguous', 'Edge中妙手批量编辑标签不唯一，拒绝选择。')
            if matches:
                self.bridge.command('attach_tab', {'tabId': matches[0]['tabId']})
                return self._visible()
        self.bridge.command('navigate', {'url': BATCH_EDIT_URL, 'newTab': True,
                                         'group_title': '妙手商品批量优化'})
        return self._visible()

    def _mark_and_click(self, probe_code, marker, error_code, message):
        state = self.bridge.evaluate(probe_code.replace('__MARKER__', marker))
        if not isinstance(state, dict) or state.get('count') != 1:
            raise DoudianError(error_code, message)
        try:
            self.bridge.command('click', {'selector': f'[data-codex-miao-batch="{marker}"]'})
        finally:
            self.bridge.evaluate(
                "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker + "\"]')"
                ".forEach(x=>x.removeAttribute('data-codex-miao-batch'));return true})()")

    def _click_exact_text(self, selector, text, *, index=0):
        marker = 'miao-batch-' + uuid.uuid4().hex
        probe = ("(()=>{const xs=[...document.querySelectorAll('" + selector + "')].filter(x=>"
                 "x.offsetParent!==null&&(x.innerText||x.textContent||'').replace(/\\s+/g,' ').trim()===" +
                 json.dumps(text, ensure_ascii=True) + ");if(xs.length>" + str(index) + ")"
                 "xs[" + str(index) + "].setAttribute('data-codex-miao-batch','__MARKER__');"
                 "return {count:xs.length>" + str(index) + "?1:0,total:xs.length}})()")
        self._mark_and_click(probe, marker, 'miaoshou_batch_control_not_unique',
                             f'妙手批量页控件「{text}」不唯一或缺失。')

    def _ensure_checkbox(self, value, checked):
        marker = 'miao-batch-' + uuid.uuid4().hex
        quoted = json.dumps(str(value), ensure_ascii=True)
        probe = '(' + _CHECKBOX_PROBE + ')(' + json.dumps([str(value), bool(checked), marker])[1:-1] + ')'
        state = self.bridge.evaluate(probe)
        if not isinstance(state, dict) or state.get('count') != 1:
            raise DoudianError('miaoshou_batch_checkbox_missing', f'妙手批量页字段选项 {value} 不唯一或缺失。')
        if state.get('unchanged'):
            return
        try:
            if getattr(self.bridge, 'endpoint', None) == 'ego':
                self.bridge.command('checkbox', {'selector': f'input[data-codex-miao-checkbox="{marker}"]',
                                                 'checked': bool(checked)})
            else:
                self.bridge.command('click', {'selector': f'[data-codex-miao-batch="{marker}"]'})
        finally:
            self.bridge.evaluate(
                "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker + "\"],[data-codex-miao-checkbox=\"" + marker + "\"]')"
                ".forEach(x=>{x.removeAttribute('data-codex-miao-batch');x.removeAttribute('data-codex-miao-checkbox')});return true})()")

        self._wait_eval("(()=>{const xs=[...document.querySelectorAll('input[type=checkbox]')].filter(x=>x.offsetParent!==null&&x.value===" +
            quoted + ");return xs.length===1&&xs[0].checked===" + ('true' if checked else 'false') + "})()",
            lambda confirmed: confirmed is True, f'妙手勾选状态 {value} 未生效，未继续填写。', seconds=3)

    def _ensure_radio(self, name, value):
        marker = 'miao-batch-' + uuid.uuid4().hex
        name_q, value_q = json.dumps(name), json.dumps(value)
        probe = ("(()=>{const xs=[...document.querySelectorAll('input[type=radio]')].filter(x=>x.offsetParent!==null&&x.name===" +
                 name_q + "&&x.value===" + value_q + "&&!x.disabled);if(xs.length!==1)return {count:xs.length};"
                 "if(xs[0].checked)return {count:1,unchanged:true};const label=xs[0].closest('label');"
                 "const box=xs[0].parentElement?.querySelector('.el-radio__inner');"
                 "if(!label||!box||box.closest('label')!==label)return {count:0};"
                 "box.setAttribute('data-codex-miao-batch','__MARKER__');"
                 "xs[0].setAttribute('data-codex-miao-checkbox','__MARKER__');return {count:1}})()")
        state = self.bridge.evaluate(probe.replace('__MARKER__', marker))
        if not isinstance(state, dict) or state.get('count') != 1:
            raise DoudianError('miaoshou_batch_radio_missing', f'妙手批量页方式 {value} 不唯一或缺失。')
        if state.get('unchanged'):
            return
        try:
            if getattr(self.bridge, 'endpoint', None) == 'ego':
                self.bridge.command('checkbox', {'selector': f'input[data-codex-miao-checkbox="{marker}"]', 'checked': True})
            else:
                self.bridge.command('click', {'selector': f'[data-codex-miao-batch="{marker}"]'})
        finally:
            self.bridge.evaluate(
                "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker + "\"],[data-codex-miao-checkbox=\"" + marker + "\"]')"
                ".forEach(x=>{x.removeAttribute('data-codex-miao-batch');x.removeAttribute('data-codex-miao-checkbox')});return true})()")
        self._wait_eval("(()=>{const xs=[...document.querySelectorAll('input[type=radio]')].filter(x=>x.offsetParent!==null&&x.name===" +
                        name_q + "&&x.value===" + value_q + ");return xs.length===1&&xs[0].checked})()",
                        lambda confirmed: confirmed is True, f'妙手单选方式 {value} 未生效。', seconds=3)

    def _click_indexed(self, selector, index, *, expected_count, error_code):
        marker = 'miao-batch-' + uuid.uuid4().hex
        probe = ("(()=>{const xs=[...document.querySelectorAll('" + selector + "')].filter(x=>x.offsetParent!==null);"
                 "if(xs.length!==" + str(expected_count) + ")return {count:0,total:xs.length};"
                 "xs[" + str(index) + "].setAttribute('data-codex-miao-batch','__MARKER__');return {count:1,total:xs.length}})()")
        self._mark_and_click(probe, marker, error_code, '妙手批量页图片槽位数量变化，停止操作。')

    def _wait_eval(self, code, predicate, message, seconds=30):
        try:
            return self.bridge.wait(lambda: self.bridge.evaluate(code), predicate, message, seconds=seconds)
        except DoudianError as exc:
            if exc.code == 'page_timeout':
                raise DoudianError('miaoshou_batch_timeout', message) from exc
            raise

    def _wait_image_dialog(self, *, detail=False):
        selector = '.select-product-filter-dialog' if detail else '.replace-image-dialog'
        return self._wait_eval(
            "(()=>[...document.querySelectorAll('" + selector + "')].filter(x=>x.offsetParent!==null).length)()",
            lambda count: count == 1, '妙手本地图片窗口没有打开。', seconds=10)

    def _upload_slot_image(self, selector, index, path, expected_count, reuse=None):
        before = self._read_target_slot('mains', index)
        if before:
            # An upload may have reached the slot immediately before a crash,
            # before its mapping was persisted. Reconcile bytes without clicking.
            return self._checked_content(before, path)
        self._click_indexed(selector, index, expected_count=expected_count,
                            error_code='miaoshou_batch_slot_count_changed')
        self._wait_image_dialog()
        return self._upload_open_image_dialog(path, lambda: self._read_target_slot('mains', index), before, reuse)

    def _read_target_slot(self, kind, index):
        if kind == 'mains':
            code = "const xs=[...document.querySelectorAll('.replace-img-item .add-img-box')].filter(x=>x.offsetParent!==null);const box=xs.length===5?xs[%d]:null;" % index
        else:
            code = "const xs=[...document.querySelectorAll('.base-edit-list')].filter(x=>x.offsetParent!==null&&x.querySelectorAll('.add-img-box').length===2);const box=xs.length===4?xs[%d].querySelectorAll('.add-img-box')[1]:null;" % index
        return self.bridge.evaluate("(()=>{" + code + "const i=box&&box.querySelector('img');return i?(i.currentSrc||i.src):null})()")

    def _upload_open_image_dialog(self, path, read_slot, before_url=None, reuse=None, *, detail=False):
        selector = '.select-product-filter-dialog' if detail else '.replace-image-dialog'
        if detail:
            self._click_exact_text(selector + ' .el-tabs__item', '输入图片链接' if reuse else '本地上传')
        probe = self.bridge.evaluate(
            "(()=>{const ds=[...document.querySelectorAll('" + selector + "')].filter(x=>x.offsetParent!==null);"
            "const f=ds.length===1?[...ds[0].querySelectorAll('input[type=file]')].filter(x=>!x.disabled):[];"
            "return {dialogs:ds.length,files:f.length}})()")
        if probe != {'dialogs': 1, 'files': 0 if detail and reuse else 1}:
            raise DoudianError('miaoshou_batch_upload_layout', '妙手批量图片窗口的本地上传控件不唯一。')
        focused = False
        try:
            self.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled', 'params': {'enabled': True}})
            focused = True
            self.bridge.command('network', {'cmd': 'start'})
            if reuse:
                self._checked_content(reuse, path)
                if detail:
                    self._fill_visible(selector + ' textarea[placeholder*="过滤的图片链接"]', reuse)
                    self._click_exact_text(selector + ' button', '添加要过滤的图片')
                else:
                    self._fill_visible(selector + ' textarea[placeholder="请输入图片链接地址"]', reuse)
                    self._click_exact_text(selector + ' button', '确定')
            else:
                self.bridge.command('upload', {'selector': selector + ' input[type="file"]',
                                              'files': [str(Path(path).resolve())]})
            # The picker may remain open after a successful upload. Prove the exact
            # target slot received this file instead of waiting for a modal animation.
            url = self.bridge.wait(read_slot,
                lambda value: value != before_url and (is_temporary_upload_url(value) or is_permanent_material_url(value)),
                '目标槽位未读回本次上传图片；不重复上传。', seconds=60)
            check = self._checked_content(url, path)
            if detail:
                dialog_count = "(()=>[...document.querySelectorAll('.select-product-filter-dialog')].filter(x=>x.offsetParent!==null).length)()"
                count = self.bridge.evaluate(dialog_count)
                if count == 1:
                    self._click_exact_text(selector + ' button', '关闭')
                    self._wait_eval(dialog_count, lambda count: count == 0,
                                    '详情图片选择窗口关闭后仍然可见。', seconds=5)
                elif count != 0:
                    raise DoudianError('miaoshou_batch_upload_layout', '详情图片选择窗口数量无法确认。')
            else:
                from .miaoshou_editor import MiaoshouEditor
                MiaoshouEditor(self.bridge, self.shop, session=self.session)._close_replace_popup()
            return check
        finally:
            if focused:
                self.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled', 'params': {'enabled': False}})

    def _upload_detail_target(self, index, path, reuse=None):
        before = self._read_target_slot('details', index)
        if before:
            return self._checked_content(before, path)
        marker = 'miao-batch-' + uuid.uuid4().hex
        probe = ("(()=>{const xs=[...document.querySelectorAll('.base-edit-list')].filter(x=>"
                 "x.querySelectorAll('.add-img-box').length===2);if(xs.length!==4)return {count:xs.length};"
                 "const box=xs[" + str(index) + "].querySelectorAll('.add-img-box')[1];if(!box)return {count:0};"
                 "box.setAttribute('data-codex-miao-batch','__MARKER__');return {count:1}})()")
        state = self.bridge.evaluate(probe.replace('__MARKER__', marker))
        if not isinstance(state, dict) or state.get('count') != 1:
            raise DoudianError('miaoshou_batch_detail_rows', '详情目标图片槽位不唯一。')
        try:
            self.bridge.command('click', {'selector': f'[data-codex-miao-batch="{marker}"]'})
        finally:
            self.bridge.evaluate(
                "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker + "\"]')"
                ".forEach(x=>x.removeAttribute('data-codex-miao-batch'));return true})()")
        self._wait_image_dialog(detail=True)
        return self._upload_open_image_dialog(path, lambda: self._read_target_slot('details', index), before, reuse,
                                              detail=True)

    def _detail_lists(self):
        return self.bridge.evaluate(
            "(()=>[...document.querySelectorAll('.base-edit-list')].filter(x=>"
            "x.querySelectorAll('.add-img-box').length===2).length)()")

    def _ensure_detail_rows(self, count=4):
        current = self._detail_lists()
        while current < count:
            marker = 'miao-batch-' + uuid.uuid4().hex
            probe = ("(()=>{const xs=[...document.querySelectorAll('.base-edit-list')].filter(x=>"
                     "x.querySelectorAll('.add-img-box').length===2);if(xs.length!==" + str(current) + ")"
                     "return {count:0,total:xs.length};const b=[...xs[xs.length-1].querySelectorAll('.operate-btn-add')]"
                     ".filter(x=>x.offsetParent!==null&&!x.classList.contains('disabled'));"
                     "if(b.length!==1)return {count:0};b[0].setAttribute('data-codex-miao-batch','__MARKER__');"
                     "return {count:1,total:xs.length}})()")
            self._mark_and_click(probe, marker, 'miaoshou_batch_detail_rows',
                                 '详情替换行的“添加”按钮不唯一，已停止。')
            current = self._wait_eval(
                "(()=>[...document.querySelectorAll('.base-edit-list')].filter(x=>"
                "x.querySelectorAll('.add-img-box').length===2).length)()",
                lambda value: value > current, '详情替换行没有增加。', seconds=10)
        if current != count:
            raise DoudianError('miaoshou_batch_detail_rows', '详情替换行数不是4，拒绝继续。')

    def close_image_picker_if_open(self):
        state = self.bridge.evaluate(
            "(()=>({main:[...document.querySelectorAll('.replace-image-dialog')].filter(x=>x.offsetParent!==null).length,"
            "detail:[...document.querySelectorAll('.select-product-filter-dialog')].filter(x=>x.offsetParent!==null).length}))()")
        if not isinstance(state, dict) or state.get('main') not in (0, 1) or state.get('detail') not in (0, 1) or sum(state.values()) > 1:
            raise DoudianError('miaoshou_batch_modal_open', '中断后的图片选择窗口不唯一，未继续操作。')
        if state['main']:
            from .miaoshou_editor import MiaoshouEditor
            MiaoshouEditor(self.bridge, self.shop, session=self.session)._close_replace_popup()
        elif state['detail']:
            self._click_exact_text('.select-product-filter-dialog button', '关闭')
            self._wait_eval(
                "(()=>[...document.querySelectorAll('.select-product-filter-dialog')].filter(x=>x.offsetParent!==null).length)()",
                lambda count: count == 0, '中断后的图片窗口未关闭。', seconds=5)
        return bool(state['main'] or state['detail'])

    def _select_detail_source(self, index, url):
        current = self.bridge.evaluate(
            "(()=>{const xs=[...document.querySelectorAll('.base-edit-list')].filter(x=>"
            "x.offsetParent!==null&&x.querySelectorAll('.add-img-box').length===2);"
            "const i=xs.length===4?xs[" + str(index) + "].querySelector('.add-img-box img'):null;"
            "return i?(i.currentSrc||i.src):null})()")
        if isinstance(current, str) and current:
            if resource_key(current) == resource_key(url):
                return
            # A populated box is not an upload button. Clicking it bubbles to the
            # wrapping checkbox and disables the entire detail replacement mode.
            raise DoudianError('miaoshou_batch_source_mismatch', '已有详情来源与本次基线不同，需重新核对表单。')
        # Mark and click the first image box in the exact source/target row.
        marker = 'miao-batch-' + uuid.uuid4().hex
        qurl = json.dumps(url, ensure_ascii=True)
        probe = ("(()=>{const xs=[...document.querySelectorAll('.base-edit-list')].filter(x=>"
                 "x.querySelectorAll('.add-img-box').length===2);if(xs.length!==4)return {count:xs.length};"
                 "const box=xs[" + str(index) + "].querySelector('.add-img-box');if(!box)return {count:0};"
                 "box.setAttribute('data-codex-miao-batch','__MARKER__');return {count:1}})()")
        state = self.bridge.evaluate(probe.replace('__MARKER__', marker))
        if not isinstance(state, dict) or state.get('count') != 1:
            raise DoudianError('miaoshou_batch_detail_rows', '详情来源图片槽位不唯一。')
        self.bridge.command('click', {'selector': f'[data-codex-miao-batch="{marker}"]'})
        self.bridge.evaluate(
            "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker + "\"]')"
            ".forEach(x=>x.removeAttribute('data-codex-miao-batch'));return true})()")
        self._wait_eval(
            "(()=>[...document.querySelectorAll('.select-product-filter-dialog')].filter(x=>x.offsetParent!==null).length)()",
            lambda count: count == 1, '详情图片来源选择窗口没有打开。', seconds=10)
        self._click_exact_text('.select-product-filter-dialog .el-tabs__item', '输入图片链接')
        self.bridge.command('fill', {'selector': '.select-product-filter-dialog textarea[placeholder*="过滤的图片链接"]',
                                     'value': url})
        self._click_exact_text('.select-product-filter-dialog button', '添加要过滤的图片')
        self._wait_eval(
            "(()=>{const xs=[...document.querySelectorAll('.base-edit-list')].filter(x=>"
            "x.querySelectorAll('.add-img-box').length===2);const i=xs[" + str(index) + "]"
            "?.querySelector('.add-img-box img');return i?(i.currentSrc||i.src):null})()",
            lambda value: isinstance(value, str) and resource_key(value) == resource_key(url),
            '详情来源地址添加后没有读回到指定槽位。', seconds=15)
        visible_dialogs = self.bridge.evaluate(
            "(()=>[...document.querySelectorAll('.select-product-filter-dialog')].filter(x=>x.offsetParent!==null).length)()")
        if visible_dialogs == 1:
            self._click_exact_text('.select-product-filter-dialog button', '关闭')
        elif visible_dialogs != 0:
            raise DoudianError('miaoshou_batch_upload_layout', '详情来源选择窗口数量无法确认。')

    def prepare(self, *, product_id, title, baseline, main_paths, detail_paths, fresh_form=False,
                on_upload=None, reuse_mappings=None):
        """Populate the visible batch form from one fresh server baseline."""
        if len(main_paths) != 5 or len(detail_paths) != 4:
            raise DoudianError('asset_manifest_incomplete', '妙手批量编辑需要5张主图和4张详情图。')
        self.open(reuse_existing=True)
        self.close_image_picker_if_open()
        self.close_preview_if_open()
        prior = self.observe()
        reuse_by_slot = {item.get('slot'): item for item in reuse_mappings or []}
        # The route is shared by successive products. Inspect its scope before
        # filling a new ID; otherwise that erases the evidence of a stale form.
        if prior.get('product_ids') != [str(product_id)] or not reuse_by_slot:
            fresh_form = True
        if prior.get('product_ids') == [str(product_id)] and prior.get('shop') == self.shop:
            candidates = [('mains', i + 1, path, url) for i, (path, url) in
                          enumerate(zip(main_paths, prior.get('main_images') or []))]
            candidates += [('details', i + 1, path, pair.get('target')) for i, (path, pair) in
                           enumerate(zip(detail_paths, prior.get('detail_pairs') or []))]
            for kind, slot, path, url in candidates:
                if f'{kind}:{slot}' in reuse_by_slot or not (is_temporary_upload_url(url) or is_permanent_material_url(url)):
                    continue
                try:
                    check = self._checked_content(url, path)
                except DoudianError as exc:
                    if exc.code != 'material_content_mismatch':
                        raise
                    continue  # A different candidate is cleared with this task's stale form.
                mapping = self._mapping(kind, slot, check)
                if on_upload:
                    on_upload(kind, slot, mapping)
                reuse_by_slot[mapping['slot']] = mapping
        if fresh_form:
            self.bridge.command('navigate', {'url': BATCH_EDIT_URL, 'newTab': False})
            self._visible()
        self._click_exact_text('[role=tab]', '按商品ID修改')
        self._fill_visible('textarea[placeholder*="请输入商品ID"]', str(product_id))
        for value in sorted(_TOP_FIELDS):
            self._ensure_checkbox(value, value in _REQUIRED_FIELDS)
        self._ensure_checkbox('new', True)
        self._ensure_radio('overlengthType', 'fail')
        self._fill_visible('textarea[name="inputNewContent"]', title)
        self._ensure_radio('contentType', 'replaceImgByIndex')
        self._ensure_checkbox('onlyPreview', True)
        self._ensure_checkbox('replaceImgsByImgUrls', True)
        self._ensure_detail_rows(4)
        reused = []
        def previous(kind, slot, path):
            item = reuse_by_slot.get(f'{kind}:{slot}') or {}
            if (item.get('confirmed') is True and
                    item.get('source_sha256') == hashlib.sha256(Path(path).read_bytes()).hexdigest() and
                    (is_temporary_upload_url(item.get('remote_url')) or is_permanent_material_url(item.get('remote_url')))):
                reused.append(f'{kind}:{slot}')
                return item['remote_url']
            return None
        for index, path in enumerate(main_paths):
            check = self._upload_slot_image('.replace-img-item .add-img-box', index, path, 5,
                                            previous('mains', index + 1, path))
            if on_upload:
                on_upload('mains', index + 1, self._mapping('mains', index + 1, check))
        for index, path in enumerate(detail_paths):
            self._select_detail_source(index, baseline['details'][index])
            # Selecting a fresh image inside the method's wrapping label can
            # toggle its checkbox off. Restore the observed mode before the
            # next control, and again after the target picker closes.
            self._ensure_checkbox('replaceImgsByImgUrls', True)
            check = self._upload_detail_target(index, path, previous('details', index + 1, path))
            self._ensure_checkbox('replaceImgsByImgUrls', True)
            if on_upload:
                on_upload('details', index + 1, self._mapping('details', index + 1, check))
        self._click_exact_text('button', '预览修改效果')
        self._wait_eval(
            "(()=>({ids:[...document.body.innerText.matchAll(/商品ID[：:]\\s*(\\d+)/g)].map(x=>x[1]),"
            "count:(document.body.innerText.match(/共找到\\s*(\\d+)\\s*个商品/)||[])[1]||null}))()",
            lambda value: isinstance(value, dict) and value.get('ids') == [str(product_id)] and
                          value.get('count') == '1',
            '修改预览没有精确收敛到目标商品。', seconds=30)
        return {'writer_revision': WRITER_REVISION, 'fresh_form': fresh_form,
                'reused_slots': reused,
                'uploaded_slots': [*(f'mains:{i}' for i in range(1, 6)), *(f'details:{i}' for i in range(1, 5))]}

    @staticmethod
    def _mapping(kind, slot, check):
        url = check['remote_url']
        permanent = is_permanent_material_url(url)
        return {'slot': f'{kind}:{slot}', 'source_sha256': check['source_sha256'],
                'remote_url': url, 'remote_key': resource_key(url) if permanent else url,
                'asset_state': 'permanent' if permanent else 'staged', 'confirmed': True,
                'content_verification': check}

    def observe(self):
        code = r"""(()=>{
          const visible=x=>!!x&&(x.offsetParent!==null||x.getClientRects().length>0);
          const top=new Set(%s);
          const checks=[...document.querySelectorAll('input[type=checkbox]')].filter(x=>visible(x)&&!x.disabled&&x.checked);
          const selectedTop=checks.filter(x=>top.has(x.value)).map(x=>x.value).sort();
          const selectedExtra=checks.filter(x=>!top.has(x.value)).map(x=>x.value).sort();
          const id=[...document.querySelectorAll('textarea')].find(x=>visible(x)&&(x.placeholder||'').includes('请输入商品ID'));
          const title=[...document.querySelectorAll('textarea[name=inputNewContent]')].find(visible);
          const main=[...document.querySelectorAll('.replace-img-item .add-img-box')].map(x=>{const i=x.querySelector('img');return i?(i.currentSrc||i.src):null});
          const lists=[...document.querySelectorAll('.base-edit-list')].filter(x=>x.querySelectorAll('.add-img-box').length===2);
          const pairs=lists.map(x=>[...x.querySelectorAll('.add-img-box')].map(y=>{const i=y.querySelector('img');return i?(i.currentSrc||i.src):null}));
          const body=document.body.innerText||'';
          const ids=[...body.matchAll(/商品ID[：:]\s*(\d+)/g)].map(x=>x[1]);
          const count=(body.match(/共找到\s*(\d+)\s*个商品/)||[])[1];
          const radios=[...document.querySelectorAll('input[type=radio]:checked')].filter(visible);
          const mainMode=radios.find(x=>x.name==='contentType')?.value||null;
          const overlength=radios.find(x=>x.name==='overlengthType')?.value||null;
          const timer=[...document.querySelectorAll('input[type=checkbox]')].find(x=>visible(x)&&
            (x.parentElement?.parentElement?.innerText||'').includes('定时执行'));
          const shop=(body.match(/您好【([^】]+)】/)||[])[1]||null;
          const dialogs=[...document.querySelectorAll('.preview-detail-dialog')].filter(visible);
          let detail=null;
          if(dialogs.length===1){const d=dialogs[0];const rows=[...d.querySelectorAll('.table-wrap-item')];
            const read=(row,side)=>{const box=row.querySelector('.'+side+'-item');return box?{
              text:(box.innerText||'').trim(),values:[...box.querySelectorAll('input,textarea')].map(x=>x.value),
              images:[...box.querySelectorAll('img')].map(x=>x.currentSrc||x.src)}:null};
            const labels=rows.map(x=>(x.querySelector('.table-wrap-item-label')?.innerText||x.firstElementChild?.innerText||'').trim());
            const old=rows.map(x=>read(x,'old')),next=rows.map(x=>read(x,'new'));
            detail={visible:true,labels,old_title:old[0]?.text||null,new_title:next[0]?.values?.[0]||null,
              old_details:old[1]?.images||[],new_details:next[1]?.images||[],
              old_mains:old[2]?.images||[],new_mains:next[2]?.images||[]};
          }
          return {url:location.href,shop,product_ids:id?(id.value||'').split(/[,，\s]+/).filter(Boolean):[],
            result_product_ids:ids,result_count:count?Number(count):null,selected_top_fields:selectedTop,
            selected_enabled_options:selectedExtra,title:title?.value||null,main_mode:mainMode,overlength,
            main_images:main,detail_pairs:pairs.map(x=>({source:x[0],target:x[1]})),
            timer_checked:timer?Boolean(timer.checked):false,preview_detail:detail};
        })()""" % json.dumps(sorted(_TOP_FIELDS))
        result = self.bridge.evaluate(code)
        if not isinstance(result, dict):
            raise DoudianError('miaoshou_batch_state_invalid', '妙手批量编辑页状态不可读。')
        return result

    def verify_prepared(self, *, product_id, title, baseline, asset_paths):
        self.open(reuse_existing=True)
        state = self.observe()
        if not (isinstance(state.get('preview_detail'), dict) and
                state['preview_detail'].get('visible') is True):
            self._click_exact_text('button', '查看详情')
            self._wait_eval(
                "(()=>[...document.querySelectorAll('.preview-detail-dialog')].filter(x=>x.offsetParent!==null).length)()",
                lambda value: value == 1, '商品修改前后详情预览没有打开。', seconds=10)
        mappings = validate_batch_form_state(self.observe(), product_id=product_id, shop=self.shop,
                                             title=title, baseline=baseline, asset_paths=asset_paths)
        for mapping, path in zip(mappings, asset_paths):
            mapping['content_verification'] = self._checked_content(mapping['remote_url'], path)
        return mappings

    def close_preview_if_open(self):
        state = self.bridge.evaluate(
            "(()=>{const ds=[...document.querySelectorAll('.preview-detail-dialog')].filter(x=>x.offsetParent!==null);"
            "const bs=ds.length===1?[...ds[0].querySelectorAll('.el-dialog__headerbtn')].filter(x=>x.offsetParent!==null):[];"
            "if(bs.length===1)bs[0].setAttribute('data-codex-miao-batch','preview-close');"
            "return {dialogs:ds.length,buttons:bs.length}})()")
        if not isinstance(state, dict) or not state.get('dialogs'):
            return False
        if state.get('dialogs') != 1 or state.get('buttons') != 1:
            raise DoudianError('miaoshou_batch_preview_close', '修改详情预览无法安全关闭。')
        self.bridge.command('click', {'selector': '[data-codex-miao-batch="preview-close"]'})
        self.bridge.evaluate(
            "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"preview-close\"]')"
            ".forEach(x=>x.removeAttribute('data-codex-miao-batch'));return true})()")
        return True

    def prepare_submission(self, *, product_id, shop, title, mappings):
        """Generate the page-level preview and arm its one exact save button.

        This is deliberately called before begin_submission(): previewing is
        non-mutating, and any missing/ambiguous button therefore remains a
        resumable pre-commit error instead of a false unknown save.
        """
        self._require_submission_scope(product_id)
        self.close_preview_if_open()
        initial = self.bridge.evaluate(
            "(()=>({dialogs:[...document.querySelectorAll('.replace-image-dialog,.select-product-filter-dialog')]."
            "filter(x=>x.offsetParent!==null).length,preview:[...document.querySelectorAll('button.J_previewBatchResult')]."
            "filter(x=>x.offsetParent!==null).length,save:(()=>{const xs=[...document.querySelectorAll('button.J_batchEditProduct')]"
            ".filter(x=>x.offsetParent!==null);return {count:xs.length,text:xs.length===1?"
            "(xs[0].innerText||xs[0].textContent||'').replace(/\\s+/g,' ').trim():null,"
            "disabled:xs.length===1?Boolean(xs[0].disabled):null}})()}))()")
        if not isinstance(initial, dict):
            raise DoudianError('miaoshou_batch_submit_state_invalid', '妙手预览控件状态不可读。')
        if initial.get('dialogs') != 0:
            raise DoudianError('miaoshou_batch_modal_open', '图片选择窗口仍打开，不能生成提交预览。')
        preview_already_ready = (initial.get('save') == {'count': 1, 'text': '开始批量修改', 'disabled': False})
        if not preview_already_ready:
            if initial.get('preview') != 1:
                raise DoudianError('miaoshou_batch_preview_button', '“预览修改效果”按钮不唯一或缺失。')
            marker = 'miao-batch-submit-' + uuid.uuid4().hex
            try:
                self._mark_and_click(
                    "(()=>{const xs=[...document.querySelectorAll('button.J_previewBatchResult')].filter(x=>x.offsetParent!==null);"
                    "if(xs.length!==1||xs[0].disabled)return {count:0};"
                    "xs[0].setAttribute('data-codex-miao-batch','__MARKER__');return {count:1}})()",
                    marker, 'miaoshou_batch_preview_button', '“预览修改效果”按钮不唯一或不可用。')
            except DoudianError:
                # Some extension builds report an error after dispatching the
                # non-mutating preview click. Continue only if the exact final
                # button becomes visible; otherwise this remains pre-commit.
                pass
            finally:
                self.bridge.evaluate(
                    "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker + "\"]')"
                    ".forEach(x=>x.removeAttribute('data-codex-miao-batch'));return true})()")
        self._wait_eval(
            "(()=>{const bs=[...document.querySelectorAll('button.J_batchEditProduct')].filter(x=>x.offsetParent!==null);"
            "const ds=[...document.querySelectorAll('.replace-image-dialog,.select-product-filter-dialog')]."
            "filter(x=>x.offsetParent!==null);return {button_count:bs.length,button_text:bs.length===1?"
            "(bs[0].innerText||bs[0].textContent||'').replace(/\\s+/g,' ').trim():null,"
            "button_disabled:bs.length===1?Boolean(bs[0].disabled):null,visible_modal_count:ds.length}})()",
            lambda value: isinstance(value, dict) and value.get('button_count') == 1 and
                          value.get('button_text') == '开始批量修改' and
                          value.get('button_disabled') is False and value.get('visible_modal_count') == 0,
            '妙手没有生成可提交的页面预览，尚未保存。', seconds=30)
        state = self.observe()
        control = self.bridge.evaluate(
            "(()=>{const bs=[...document.querySelectorAll('button.J_batchEditProduct')].filter(x=>x.offsetParent!==null);"
            "const ds=[...document.querySelectorAll('.replace-image-dialog,.select-product-filter-dialog')]."
            "filter(x=>x.offsetParent!==null);return {button_count:bs.length,button_text:bs.length===1?"
            "(bs[0].innerText||bs[0].textContent||'').replace(/\\s+/g,' ').trim():null,"
            "button_disabled:bs.length===1?Boolean(bs[0].disabled):null,visible_modal_count:ds.length}})()")
        state['submit_control'] = control
        validate_submission_ready_state(state, product_id=product_id, shop=shop,
                                        title=title, mappings=mappings)
        arm = 'miao-batch-final-' + uuid.uuid4().hex
        armed = self.bridge.evaluate(
            "(()=>{const bs=[...document.querySelectorAll('button.J_batchEditProduct')].filter(x=>x.offsetParent!==null);"
            "if(bs.length!==1||bs[0].disabled||(bs[0].innerText||bs[0].textContent||'').replace(/\\s+/g,' ').trim()!=="
            "'开始批量修改')return {count:bs.length};bs[0].setAttribute('data-codex-miao-batch','" + arm + "');"
            "return {count:1}})()")
        if armed != {'count': 1}:
            raise DoudianError('miaoshou_batch_submit_button_unavailable', '最终提交按钮状态变化，尚未保存。')
        return {'marker': arm, 'product_id': str(product_id), 'title': title}

    def click_start_once(self, *, product_id, title, baseline, asset_paths,
                         validated_mappings=None, prepared_submission=None, wait_seconds=60):
        """Click the page-level batch action once and classify only observed evidence."""
        self._require_submission_scope(product_id)
        mappings = validated_mappings
        if mappings is None:
            mappings = self.verify_prepared(product_id=product_id, title=title,
                                            baseline=baseline, asset_paths=asset_paths)
        prepared = prepared_submission or self.prepare_submission(
            product_id=product_id, shop=self.shop, title=title, mappings=mappings)
        marker = prepared.get('marker') if isinstance(prepared, dict) else None
        if (not marker or prepared.get('product_id') != str(product_id) or
                prepared.get('title') != title):
            raise DoudianError('miaoshou_batch_submit_button_unavailable', '最终提交按钮没有经过本商品预览校验。')

        before = self.bridge.command('network', {'cmd': 'list'}) or {}
        before_ids = {item.get('requestId') for item in before.get('requests', [])}
        self.bridge.command('network', {'cmd': 'start'})
        # This exact page-level button is distinct from each row's "保存修改" action.
        self.bridge.command('click', {'selector': f'[data-codex-miao-batch="{marker}"]'})
        self.bridge.evaluate(
            "(()=>{document.querySelectorAll('[data-codex-miao-batch=\"" + marker + "\"]')"
            ".forEach(x=>x.removeAttribute('data-codex-miao-batch'));return true})()")
        deadline = time.monotonic() + wait_seconds
        inspected = set()
        while time.monotonic() < deadline:
            capture = self.bridge.command('network', {'cmd': 'list'}) or {}
            fresh = [item for item in capture.get('requests', [])
                     if item.get('requestId') not in before_ids | inspected and item.get('completed') and
                     item.get('method') == 'POST' and item.get('status') is not None]
            for request in reversed(fresh):
                inspected.add(request['requestId'])
                from .submission_evidence import SAVE_PATH, classify_product_submission
                parsed = urlparse(request.get('url', ''))
                if parsed.hostname != 'v2-dd.chengji-inc.com' or parsed.path != SAVE_PATH:
                    continue
                detail = self.bridge.command('network', {'cmd': 'detail',
                                                         'requestId': request['requestId']})
                decision = classify_product_submission(request, detail, product_id)
                if decision:
                    return decision
            time.sleep(0.4)
        return {'state': 'unknown', 'error': 'batch_apply_response_unknown',
                'evidence': {'product_id': str(product_id), 'clicks': 1,
                             'staged_slots': len(mappings)}}

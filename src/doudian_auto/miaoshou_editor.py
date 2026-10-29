"""Observed, UI-driven writer for the authenticated Miaoshou quick editor.

The adapter uses Kimi's browser controls for every page action. Network capture is
read-only evidence from requests that the page itself made; this module never replays
site write APIs.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .errors import DoudianError, WaitingHuman
from .jobs import HOST
from .workflow import (is_permanent_material_key, is_permanent_material_url,
                       is_temporary_upload_url, resource_key)

MIAOSHOU_HOST = 'v2-dd.chengji-inc.com'
QUICK_EDIT_URL = f'https://{MIAOSHOU_HOST}/product/quick_edit'
BASE_EDIT_ENDPOINT = '/api/v2/product/product/getProductBaseEditInfo'
SAVE_ENDPOINT = '/api/v2/product/product/saveEditProductInfo'
UPLOAD_ENDPOINT = '/api/v2/move/batch/uploadImage'
VISIBLE_DOM = Path(__file__).with_name('miaoshou_dom.js').read_text(encoding='utf-8')


def _json_body(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _image_urls(value):
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    result = []
    for item in value:
        if isinstance(item, str) and item:
            result.append(item)
        elif isinstance(item, dict):
            url = next((item.get(k) for k in ('url', 'src', 'imgUrl', 'uri', 'imageUrl')
                        if isinstance(item.get(k), str) and item.get(k)), None)
            if url:
                result.append(url)
            else:
                return []
        else:
            return []
    return result


def _safe_protected(root, info):
    root_keys = ('categoryId', 'brandName')
    info_keys = (
        'brandId', 'standardBrandId', 'cid', 'categoryDetail', 'specs', 'specPrices',
        'specPics', 'mainImageThreeToFour', 'mainPic34', 'whiteBackGroundPicUrl',
        'freightId', 'afterSaleService', 'afterSaleServiceV2', 'weightValue', 'weightUnit',
        'minimumPerOrder', 'maximumPerOrder', 'limitPerBuyer', 'status', 'draftStatus',
        'checkStatus', 'deliveryMethod', 'deliveryDelayDay', 'startSaleType',
        'presellType', 'presellConfigLevel', 'presellDeliveryType', 'reduceType',
        'saleChannelType', 'sellChannel', 'isEvaluateOpened', 'isCharityProduct',
    )
    protected = {f'root.{key}': root[key] for key in root_keys if key in root}
    protected.update({key: info[key] for key in info_keys if key in info})
    required_root = {'categoryId', 'brandName'}
    required_info = {'specPrices', 'freightId', 'status', 'draftStatus', 'specPics',
                     'mainImageThreeToFour', 'whiteBackGroundPicUrl', 'afterSaleService'}
    complete = (required_root.issubset(root) and required_info.issubset(info) and
                isinstance(info.get('specPrices'), list) and len(info['specPrices']) > 0)
    return protected, complete


def parse_edit_response(response, *, expected_product_id, shop):
    """Turn an observed getProductBaseEditInfo response into a safe whitelist snapshot."""
    data = _json_body(response.get('body')) if isinstance(response, dict) else None
    if not isinstance(data, dict) or data.get('result') not in ('success', 'SUCCESS'):
        raise DoudianError('miaoshou_read_failed', '妙手页面没有返回成功的商品读取响应。')
    info = data.get('productInfo')
    if not isinstance(info, dict):
        raise DoudianError('miaoshou_read_incomplete', '商品读取响应缺少 productInfo。')
    # JSON decoding in Python preserves 64-bit integer IDs exactly. Never round-trip a
    # listing ID through JavaScript Number.
    actual_id = str(data.get('productId') or info.get('productId') or '')
    if actual_id != str(expected_product_id):
        raise DoudianError('wrong_identity', '妙手读取响应中的商品ID与目标不一致。')
    mains = _image_urls(info.get('pic'))
    details = _image_urls(info.get('descriptionImgList'))
    if len(mains) != 5 or len(details) < 4:
        raise DoudianError('miaoshou_images_incomplete', '妙手读取到的主图不是5张或详情图少于4张。')
    protected, complete = _safe_protected(data, info)
    if not complete:
        raise DoudianError('protected_incomplete', '妙手商品响应缺少SKU、类目、物流、售后或状态字段。')
    return {
        'product_id': str(expected_product_id), 'shop': shop, 'title': str(info.get('name') or ''),
        'mains': mains, 'details': details, 'protected': protected,
        'protected_complete': True, 'source': 'miaoshou:getProductBaseEditInfo',
        'response_status': response.get('status'),
        'category_id': data.get('categoryId'), 'brand_name': data.get('brandName'),
    }


def _ref(line):
    match = re.search(r'\[ref=(e\d+)\]', line)
    return '@' + match.group(1) if match else None


class MiaoshouEditor:
    def __init__(self, bridge, shop, *, session='miaoshou-auto-batch-20261028'):
        self.bridge = bridge
        self.shop = str(shop).strip()
        self.bridge.session = session
        self._prior_edit_ids = set()

    def _visible_dom(self, op, product_id=None, marker=None):
        params = {'shop': self.shop, 'product_id': str(product_id or ''),
                  'marker': marker or uuid.uuid4().hex}
        return self.bridge.evaluate(VISIBLE_DOM + '(' + json.dumps(op) + ',' +
                                    json.dumps(params, ensure_ascii=True) + ')')

    def _mark_control(self, op, product_id=None):
        state = self.bridge.wait(lambda: self._visible_dom(op, product_id),
            lambda value: isinstance(value, dict) and value.get('count') == 1,
            '妙手当前可见控件或商品行未唯一定位；未点击。', seconds=30)
        return state['selector']

    def _snapshot(self, max_chars=26000):
        snap = self.bridge.command('snapshot', {'format': 'aria', 'max_chars': max_chars})
        if not isinstance(snap, dict) or not isinstance(snap.get('tree_text'), str):
            raise DoudianError('miaoshou_snapshot_invalid', '妙手页面没有返回可读的辅助树。')
        current_url = urlparse(snap.get('url', ''))
        if current_url.hostname == 'fuwu.jinritemai.com' and current_url.path == '/authorize':
            raise WaitingHuman('miaoshou_authorization_required',
                               '妙手需要重新授权抖店店铺；请在当前服务授权页完成后继续。')
        if current_url.hostname != MIAOSHOU_HOST:
            raise DoudianError('wrong_host', '当前标签页不在妙手商品页面。')
        return snap

    def _wait_tree(self, predicate, message, seconds=30):
        try:
            return self.bridge.wait(self._snapshot, predicate, message, seconds=seconds)
        except DoudianError as exc:
            if exc.code != 'page_timeout':
                raise
            raise DoudianError('miaoshou_timeout', message) from exc

    def _search_refs(self, tree):
        lines = tree.splitlines()
        label = next((i for i, line in enumerate(lines)
                      if line.strip() == '- text: 商品ID'), None)
        if label is None:
            raise DoudianError('miaoshou_search_layout', '商品ID筛选框没有出现在当前页面。')
        id_ref = next((_ref(line) for line in lines[label + 1:label + 6]
                       if 'textbox' in line and _ref(line)), None)
        query_ref = next((_ref(line) for line in lines[label:]
                          if 'button "查询"' in line and _ref(line)), None)
        if not id_ref or not query_ref:
            raise DoudianError('miaoshou_search_layout', '商品ID输入框或查询按钮不唯一/缺失。')
        return id_ref, query_ref

    @staticmethod
    def _edit_ref(tree, product_id):
        lines = tree.splitlines()
        pid_lines = [i for i, line in enumerate(lines)
                     if line.strip() == f'- text: {product_id}']
        # A search input echoes its value as a nested text node. Only a listing row has
        # a subsequent item action and category/status content.
        for index in pid_lines:
            stop = min(len(lines), index + 45)
            next_row = next((i for i in range(index + 1, stop)
                             if lines[i].strip() == '- text: 商品ID：'), stop)
            action = next((lines[i] for i in range(index + 1, next_row)
                           if 'button "编辑商品"' in lines[i]), None)
            if action and _ref(action):
                return _ref(action)
        raise DoudianError('product_row_not_found', '精确商品ID的结果行或编辑按钮未读到。')

    def open_product(self, product_id, *, fresh=True):
        if not str(product_id).isdigit():
            raise DoudianError('invalid_product', '商品ID必须按字符串传入数字。')
        self.bridge.require_ready()
        self.bridge.command('navigate', {'url': QUICK_EDIT_URL, 'newTab': bool(fresh),
                                         'group_title': '妙手批量商品优化'})
        self._wait_tree(lambda snap: f'您好【{self.shop}】' in snap['tree_text'],
                        '妙手店铺页或登录态未就绪。', seconds=30)
        self.bridge.command('fill', {'selector': self._mark_control('search_input'),
                                     'value': str(product_id)})
        self.bridge.command('click', {'selector': self._mark_control('query_button')})
        button = self._mark_control('edit_button', product_id)
        self.bridge.command('network', {'cmd': 'start'})
        prior = self.bridge.command('network', {'cmd': 'list', 'filter': BASE_EDIT_ENDPOINT}) or {}
        self._prior_edit_ids = {item.get('requestId') for item in prior.get('requests', [])}
        self.bridge.command('click', {'selector': button})
        page = self._wait_tree(lambda snap: f'ID：{product_id}' in snap['tree_text'] and
                               '商品标题：' in snap['tree_text'],
                               '妙手商品信息窗没有加载目标商品。', seconds=30)
        # One-row search must produce one editing item. This prevents the left-side
        # multi-product navigator from silently switching to a neighbouring listing.
        dialog = self._visible_dom('dialog', product_id)
        if not isinstance(dialog, dict) or dialog.get('count') != 1 or not dialog.get('identity'):
            raise DoudianError('wrong_identity', '妙手编辑窗未包含精确目标商品ID。')
        return page

    def _observed_edit_response(self, product_id, seconds=30):
        deadline = time.monotonic() + seconds
        request = None
        while time.monotonic() < deadline:
            capture = self.bridge.command('network', {'cmd': 'list', 'filter': BASE_EDIT_ENDPOINT})
            requests = capture.get('requests', []) if isinstance(capture, dict) else []
            matches = [item for item in requests if BASE_EDIT_ENDPOINT in item.get('url', '')
                       and item.get('requestId') not in self._prior_edit_ids
                       and item.get('method') == 'POST' and item.get('completed') and item.get('status') == 200]
            for item in reversed(matches):
                detail = self.bridge.command('network', {'cmd': 'detail', 'requestId': item['requestId']})
                from .submission_evidence import request_fields, request_product_ids
                fields = request_fields(detail.get('requestBody'))
                if request_product_ids(detail.get('requestBody')) == {str(product_id)}:
                    if str(fields.get('isDraft')) != '0':
                        raise DoudianError('draft_source_unconfirmed', '读取请求没有证明读取的是非草稿数据。')
                    return detail
            time.sleep(0.35)
        raise DoudianError('miaoshou_read_timeout', '未捕获到妙手页面自身发出的商品基线读取。')

    def read_product(self, product_id):
        dom = self._visible_dom('dialog', product_id)
        if not isinstance(dom, dict) or dom.get('count') != 1 or dom.get('identity') is not True:
            raise DoudianError('wrong_identity', '妙手店铺或商品信息窗未能确认。')
        detail = self._observed_edit_response(str(product_id))
        baseline = parse_edit_response(detail, expected_product_id=str(product_id), shop=self.shop)
        if baseline['title'] != dom.get('title'):
            raise DoudianError('miaoshou_title_disagreement', 'API读取标题与当前编辑窗标题不一致。')
        return baseline

    def require_shelf_mode_preservable(self, expected_mode):
        """Fail closed unless the live editor exposes the current post-review mode.

        Miaoshou's save can change `startSaleType` even while the current on/off-shelf
        status remains unchanged. The quick editor must visibly expose that field and
        its selected value before this writer is allowed to touch the product.
        """
        if expected_mode not in (0, 1, '0', '1'):
            raise DoudianError('miaoshou_shelf_mode_unreadable',
                               '原商品的审核后上架模式缺失或未知，拒绝修改。')
        expected_mode = int(expected_mode)
        state = self.bridge.evaluate(
            "(()=>{const d=document.querySelector('.product-edit-dialog');if(!d)return {dialog:false};"
            "const labels=[...d.querySelectorAll('.el-form-item__label')].map(x=>({el:x,text:(x.innerText||'').replace(/\\s+/g,' ').trim()}));"
            "const pattern=/审核.{0,8}上架|上架.{0,8}审核|上架模式|售卖方式/;"
            "const matches=labels.filter(x=>pattern.test(x.text));if(matches.length!==1)return {dialog:true,labels:matches.map(x=>x.text)};"
            "const item=matches[0].el.closest('.el-form-item')||matches[0].el.parentElement;"
            "if(!item)return {dialog:true,label:matches[0].text,controls:0};"
            "const visible=x=>!!(x.offsetWidth||x.offsetHeight||x.getClientRects().length);"
            "let controls=[...item.querySelectorAll('input:not([type=hidden]),select')].filter(visible);"
            "if(!controls.length)controls=[...item.querySelectorAll('[role=combobox]')].filter(visible);"
            "if(!controls.length)controls=[...item.querySelectorAll('.el-select')].filter(visible);"
            "if(controls.length!==1)return {dialog:true,label:matches[0].text,controls:controls.length};"
            "const c=controls[0],v=String(c.value||'').trim(),t=(c.innerText||c.textContent||'').replace(/\\s+/g,' ').trim();"
            "const raw=v||t;let mode=null;if(raw==='0'||/立即上架|立即售卖/.test(raw))mode=0;"
            "else if(raw==='1'||/放入仓库/.test(raw))mode=1;"
            "return {dialog:true,label:matches[0].text,controls:1,value:raw,mode}})()")
        if not isinstance(state, dict) or state.get('dialog') is not True:
            raise DoudianError('miaoshou_shelf_mode_not_editable',
                               '妙手编辑窗没有可核对的审核后上架模式控件，拒绝修改商品。')
        if state.get('controls') != 1:
            raise DoudianError('miaoshou_shelf_mode_not_editable',
                               '妙手编辑窗未唯一显示审核后上架模式控件，拒绝修改商品。')
        if state.get('mode') not in (0, 1):
            raise DoudianError('miaoshou_shelf_mode_unreadable',
                               '妙手审核后上架模式当前值无法确认，拒绝修改商品。')
        if state['mode'] != expected_mode:
            raise DoudianError('miaoshou_shelf_mode_mismatch',
                               '妙手编辑窗审核后上架模式与原值不一致，拒绝修改商品。')
        return {'preservable': True, 'mode': expected_mode, 'label': state.get('label')}

    def _click_tab(self, name):
        # The global accessibility tree can include hidden duplicate tabs from
        # Miaoshou's title-optimization panel. Scope the choice to one visible tab
        # inside the observed product dialog, then click that marked node through
        # the normal browser control.
        marker = 'miaoshou-tab-' + uuid.uuid4().hex
        probe = self.bridge.evaluate(
            "(()=>{const d=document.querySelector('.product-edit-dialog');if(!d)return {error:'dialog_missing'};"
            "d.querySelectorAll('[data-codex-miaoshou-tab]').forEach(x=>x.removeAttribute('data-codex-miaoshou-tab'));"
            "const ms=[...d.querySelectorAll('[role=tab]')].filter(x=>x.offsetParent!==null&&"
            "(x.innerText||'').replace(/\\s+/g,' ').trim()==='" + name + "');"
            "if(ms.length===1)ms[0].setAttribute('data-codex-miaoshou-tab','" + marker + "');"
            "return {count:ms.length,text:ms.length===1?(ms[0].innerText||'').trim():null}})()")
        if not isinstance(probe, dict) or probe.get('count') != 1:
            raise DoudianError('miaoshou_tab_not_unique', f'妙手页签「{name}」不唯一或缺失。')
        selector = f'[data-codex-miaoshou-tab="{marker}"]'
        try:
            self.bridge.command('click', {'selector': selector})
        finally:
            self.bridge.evaluate(
                "(()=>{const d=document.querySelector('.product-edit-dialog');"
                "const e=d&&d.querySelector('[data-codex-miaoshou-tab=\"" + marker + "\"]');"
                "if(e)e.removeAttribute('data-codex-miaoshou-tab');return true})()")
        time.sleep(0.3)

    def fill_title(self, product_id, title):
        from .title import title_units, validate_title

        _, errors = validate_title(title)
        if errors:
            raise DoudianError('invalid_title', '；'.join(errors))
        self._click_tab('商品信息')
        # Miao's quick editor let a synthetic fill change the visible DOM value,
        # but the server later kept the old title. Use trusted keyboard input so
        # Vue's form model receives the same input/change events as a person typing.
        value = self.bridge.evaluate(
            "(()=>{const d=document.querySelector('.product-edit-dialog');"
            "const f=d&&[...d.querySelectorAll('.el-form-item__label')].find(x=>(x.innerText||'').trim()==='商品标题：');"
            "const i=f&&f.parentElement.querySelector('input.el-input__inner');if(!i||!i.id)return null;"
            "i.scrollIntoView({block:'center'});const r=i.getBoundingClientRect();"
            "return {id:i.id,value:i.value,x:r.x+r.width/2,y:r.y+r.height/2}})()")
        if (not isinstance(value, dict) or not value.get('id') or
                not isinstance(value.get('x'), (int, float)) or
                not isinstance(value.get('y'), (int, float))):
            raise DoudianError('miaoshou_title_input_missing', '商品标题控件无法唯一定位。')
        focus_enabled = False
        try:
            self.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled',
                                        'params': {'enabled': True}})
            focus_enabled = True
            self.bridge.command('cdp', {'method': 'Input.dispatchMouseEvent',
                                        'params': {'type': 'mouseMoved', 'x': value['x'], 'y': value['y']}})
            self.bridge.command('cdp', {'method': 'Input.dispatchMouseEvent',
                                        'params': {'type': 'mousePressed', 'x': value['x'], 'y': value['y'],
                                                   'button': 'left', 'clickCount': 1}})
            self.bridge.command('cdp', {'method': 'Input.dispatchMouseEvent',
                                        'params': {'type': 'mouseReleased', 'x': value['x'], 'y': value['y'],
                                                   'button': 'left', 'clickCount': 1}})
            for event_type in ('keyDown', 'keyUp'):
                self.bridge.command('cdp', {'method': 'Input.dispatchKeyEvent',
                                            'params': {'type': event_type, 'key': 'a', 'code': 'KeyA',
                                                       'windowsVirtualKeyCode': 65, 'modifiers': 2}})
            self.bridge.command('cdp', {'method': 'Input.insertText', 'params': {'text': title}})
            for event_type in ('keyDown', 'keyUp'):
                self.bridge.command('cdp', {'method': 'Input.dispatchKeyEvent',
                                            'params': {'type': event_type, 'key': 'Tab', 'code': 'Tab',
                                                       'windowsVirtualKeyCode': 9}})
            self.bridge.wait(
                lambda: self.title_form_state(product_id),
                lambda current: (current.get('title') == title and current.get('identity') is True and
                                 current.get('rendered_units') == title_units(title)),
                '标题或页面实时字数没有同步，未证明妙手表单已接收新标题。', seconds=12)
        finally:
            if focus_enabled:
                self.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled',
                                            'params': {'enabled': False}})
        current_id = self.bridge.evaluate("(()=>{const d=document.querySelector('.product-edit-dialog');return d&&d.innerText.includes('ID：" + str(product_id) + "')})()")
        if current_id is not True:
            raise DoudianError('wrong_identity', '标题填写后编辑窗商品ID发生变化。')

    def title_form_state(self, product_id):
        """Read both the input and the separately rendered model-driven counter."""
        result = self.bridge.evaluate(
            "(()=>{const d=document.querySelector('.product-edit-dialog');"
            "const f=d&&[...d.querySelectorAll('.el-form-item__label')].find(x=>(x.innerText||'').trim()==='商品标题：');"
            "const i=f&&f.parentElement.querySelector('input.el-input__inner');"
            "const c=f&&f.parentElement.querySelector('.el-input__suffix .limit-num');"
            "const m=c&&(c.innerText||'').trim().match(/^(\\d+)\\s*\\/\\s*60$/);"
            "return {identity:!!d&&(d.innerText||'').includes('ID：" + str(product_id) + "'),"
            "title:i?i.value:null,rendered_units:m?Number(m[1]):null}})()")
        return result if isinstance(result, dict) else {}

    def prepare_save(self, product_id, title, *, marker=None):
        from .title import title_units

        state = self.title_form_state(product_id)
        if (state.get('identity') is not True or state.get('title') != title or
                state.get('rendered_units') != title_units(title)):
            raise DoudianError('miaoshou_title_model_unconfirmed', '保存前标题和实时字数未同时匹配。')
        marker = marker or uuid.uuid4().hex
        control = self._visible_dom('save_button', product_id, marker=marker)
        if not isinstance(control, dict) or control.get('count') != 1:
            raise DoudianError('miaoshou_save_not_unique', '保存到抖店按钮未唯一定位。')
        return {'selector': control['selector'], 'marker': marker,
                'product_id': str(product_id), 'title': title,
                'rendered_units': state['rendered_units']}

    @staticmethod
    def _image_list_selector(kind):
        if kind == 'mains':
            # The main-image tab also mounts 3:4, SKU, white-background and
            # description groups. The actual square-main list is named
            # ``imageUrls`` in the live editor DOM.
            return '.imageUrls > .draggable-img-list', '主图', 5
        if kind == 'details':
            # The standalone details tab renders a single ``.img-list`` with
            # the description images. The main-image tab's hidden
            # ``imageDescUrls`` list is a different UI surface.
            return '.img-list > .draggable-img-list', '详情图', 4
        raise DoudianError('invalid_image_slot', '图片类型无效。')

    def _wait_image_groups(self, kind, seconds=15):
        selector, expected_tab, minimum_count = self._image_list_selector(kind)
        previous = None
        stable_count = 0

        def probe():
            nonlocal previous, stable_count
            result = self.bridge.evaluate(
                "(()=>{const d=document.querySelector('.product-edit-dialog');if(!d)return {error:'dialog_missing'};"
                "const host=d.querySelector('.edit-product-tab');if(!host)return {error:'product_tabs_missing'};"
                "const active=[...host.querySelectorAll('[role=tab][aria-selected=true]')].filter(x=>x.offsetWidth||x.offsetHeight||x.getClientRects().length);"
                "if(active.length!==1)return {error:'active_tab_not_unique',active:active.length};"
                "const name=(active[0].innerText||'').replace(/\\s+/g,' ').trim();"
                "const lists=[...d.querySelectorAll('" + selector + "')].filter(x=>x.offsetWidth||x.offsetHeight||x.getClientRects().length);"
                "if(lists.length!==1)return {error:'image_list_not_unique',lists:lists.length,active:name};"
                "const groups=[...lists[0].querySelectorAll('.J_editProductReplaceGroup')];"
                "const urls=groups.map(t=>{const c=t.closest('.product-image-item')||t.closest('.image-item-cont__ms')||t.closest('.draggable-item');"
                "const i=c&&c.querySelector('img');return i?(i.currentSrc||i.src):''});"
                "return {count:groups.length,urls,active:name}})()")
            if not isinstance(result, dict) or result.get('error'):
                previous, stable_count = None, 0
                return {'ready': False, 'result': result}
            signature = (result.get('count'), tuple(result.get('urls') or []), result.get('active'))
            required = minimum_count if kind == 'details' else 5
            if (signature == previous and result.get('active') == expected_tab and
                    result.get('count', 0) >= minimum_count and
                    all(result.get('urls', [])[:required])):
                stable_count += 1
            else:
                previous, stable_count = signature, 1
            return {'ready': stable_count >= 3, 'result': result}

        state = self.bridge.wait(probe, lambda value: value.get('ready') is True,
                                 f'妙手{expected_tab}图片卡片尚未稳定加载。', seconds=seconds)
        return state['result']

    def _mark_slot(self, kind, slot):
        if kind not in ('mains', 'details') or int(slot) < 1:
            raise DoudianError('invalid_image_slot', '图片类型或槽位编号无效。')
        selector, tab, minimum_count = self._image_list_selector(kind)
        self._click_tab(tab)
        stable = self._wait_image_groups(kind)
        selector_token = 'miaoshou-' + uuid.uuid4().hex
        probe = self.bridge.evaluate(
            "(()=>{const d=document.querySelector('.product-edit-dialog');if(!d)return {error:'dialog_missing'};"
            "d.querySelectorAll('[data-codex-miaoshou-target]').forEach(x=>x.removeAttribute('data-codex-miaoshou-target'));"
            "const host=d.querySelector('.edit-product-tab');if(!host)return {error:'product_tabs_missing'};"
            "const active=[...host.querySelectorAll('[role=tab][aria-selected=true]')].filter(x=>x.offsetWidth||x.offsetHeight||x.getClientRects().length);"
            "if(active.length!==1)return {error:'active_tab_not_unique',count:active.length};"
            "const activeName=(active[0].innerText||'').replace(/\\s+/g,' ').trim();"
            "if(activeName!=='" + tab + "')return {error:'wrong_active_tab',active:activeName};"
            "const lists=[...d.querySelectorAll('" + selector + "')].filter(x=>x.offsetWidth||x.offsetHeight||x.getClientRects().length);"
            "if(lists.length!==1)return {error:'image_list_not_unique',count:lists.length};"
            "const groups=[...lists[0].querySelectorAll('.J_editProductReplaceGroup')];"
            "if(groups.length!==" + str(int(stable['count'])) + ")return {error:'groups_rerendered',count:groups.length};"
            "const i=" + str(int(slot) - 1) + ";if(i>=groups.length)return {error:'slot_missing',count:groups.length};"
            "const target=groups[i];target.setAttribute('data-codex-miaoshou-target','" + selector_token + "');"
            "const card=target.closest('.product-image-item')||target.closest('.image-item-cont__ms')||target.closest('.draggable-item');"
            "const im=card&&card.querySelector('img');"
            "return {count:groups.length,selected:target.getAttribute('data-codex-miaoshou-target'),"
            "current:im?(im.currentSrc||im.src):null,tab:(d.querySelector('[aria-selected=true]')||{}).innerText||''}})()")
        if not isinstance(probe, dict) or probe.get('error') or probe.get('selected') != selector_token:
            raise DoudianError('miaoshou_slot_not_found', f'{kind} 第{slot}张图片槽位未能唯一定位。')
        if kind == 'mains' and probe.get('count', 0) < 5:
            raise DoudianError('miaoshou_main_layout', '主图页签少于5个可替换槽位。')
        return f'[data-codex-miaoshou-target="{selector_token}"]', probe.get('current')

    def _read_slot_url(self, kind, slot):
        target, _ = self._mark_slot(kind, slot)
        token = target.split('"')[1]
        return self.bridge.evaluate(
            "(()=>{const t=document.querySelector('[data-codex-miaoshou-target=\"" + token + "\"]');"
            "const c=t&&(t.closest('.product-image-item')||t.closest('.image-item-cont__ms')||t.closest('.draggable-item'));"
            "const i=c&&c.querySelector('img');return i?(i.currentSrc||i.src):null})()")

    def _recent_upload_url(self, asset_path, *, exclude_ids=None, seconds=60):
        """Return the temp URL from the UI's own local-file upload response."""
        source_hash = hashlib.sha256(Path(asset_path).read_bytes()).hexdigest()
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            capture = self.bridge.command('network', {'cmd': 'list'})
            requests = capture.get('requests', []) if isinstance(capture, dict) else []
            candidates = [item for item in requests if item.get('requestId') not in (exclude_ids or set())
                          and item.get('completed') and
                          any(word in urlparse(item.get('url', '')).path.lower()
                              for word in ('upload', 'tmp_upload'))]
            for item in reversed(candidates):
                detail = self.bridge.command('network', {'cmd': 'detail', 'requestId': item['requestId']})
                request_body = str(detail.get('requestBody') or '')
                if Path(asset_path).name not in request_body and str(Path(asset_path).name) not in str(detail.get('url', '')):
                    # Browser upload requests may omit the local filename; only accept
                    # the last completed request after a single-file selection.
                    pass
                body = _json_body(detail.get('body'))
                if body is None:
                    continue
                urls = []
                def walk(value):
                    if isinstance(value, str) and value.startswith('http'):
                        urls.append(value)
                    elif isinstance(value, dict):
                        for child in value.values():
                            walk(child)
                    elif isinstance(value, list):
                        for child in value:
                            walk(child)
                walk(body)
                temp = [url for url in urls if 'tmp_upload' in url or 'temp' in url.lower()]
                if temp:
                    return temp[0]
            time.sleep(0.4)
        raise DoudianError('miaoshou_temp_upload_unknown',
                           f'本地图片 {Path(asset_path).name} 上传结果未读到；禁止盲目重复上传。')

    def _import_temp_url(self, selector, url, *, seconds=60):
        # The page's link-import button converts its tmp_upload URL into a permanent
        # material asset. This is a UI flow; the observed write response is evidence only.
        self.bridge.command('click', {'selector': selector})
        snap = self._wait_tree(lambda s: '上传/替换图片' in s['tree_text'],
                               '图片替换窗口未打开。', seconds=10)
        popup = snap['tree_text'][snap['tree_text'].rfind('上传/替换图片'):]
        lines = popup.splitlines()
        input_line = next((line for line in lines if 'textbox "请输入图片链接地址"' in line), None)
        ok_line = next((line for line in lines if 'button "确定"' in line), None)
        if not input_line or not ok_line or not _ref(input_line) or not _ref(ok_line):
            raise DoudianError('miaoshou_replace_layout', '图片链接输入框或确认按钮没有唯一可访问控件。')
        before = self.bridge.command('network', {'cmd': 'list', 'filter': UPLOAD_ENDPOINT})
        before_ids = {r.get('requestId') for r in before.get('requests', [])}
        self.bridge.command('fill', {'selector': _ref(input_line), 'value': url})
        self.bridge.command('click', {'selector': _ref(ok_line)})
        deadline = time.monotonic() + seconds
        response = None
        while time.monotonic() < deadline:
            capture = self.bridge.command('network', {'cmd': 'list', 'filter': UPLOAD_ENDPOINT})
            fresh = [r for r in capture.get('requests', []) if r.get('requestId') not in before_ids
                     and r.get('completed') and r.get('status') == 200]
            if fresh:
                detail = self.bridge.command('network', {'cmd': 'detail', 'requestId': fresh[-1]['requestId']})
                body = _json_body(detail.get('body'))
                if isinstance(body, dict) and body.get('result') == 'success':
                    urls = body.get('successUrls') or body.get('urls') or []
                    if isinstance(urls, list) and urls:
                        response = {'url': str(urls[0]), 'request_id': fresh[-1]['requestId'],
                                    'result': 'success'}
                        break
                raise DoudianError('miaoshou_asset_import_failed', '妙手图片导入返回明确失败，未保存商品。')
            time.sleep(0.35)
        if response is None:
            raise DoudianError('miaoshou_asset_import_unknown', '妙手正式素材导入结果未知；只允许读回，不重复导入。')
        if not (is_permanent_material_url(response['url']) or
                is_temporary_upload_url(response['url'])):
            raise DoudianError('miaoshou_asset_import_not_permanent',
                               '导入响应既不是妙手临时暂存地址，也不是正式素材地址，未确认槽位，不可保存商品。')
        self._close_replace_popup()
        return response

    def _close_replace_popup(self):
        for attempt in range(2):
            marker = 'miaoshou-close-' + uuid.uuid4().hex
            state = self.bridge.evaluate(
                "(()=>{const dialogs=[...document.querySelectorAll('.replace-image-dialog')].filter(x=>x.offsetParent!==null);"
                "const buttons=dialogs.flatMap(d=>[...d.querySelectorAll('button[aria-label=\"close\"]')]"
                ".filter(x=>x.offsetParent!==null));"
                "if(dialogs.length===1&&buttons.length===1)buttons[0].setAttribute('data-codex-miaoshou-close','" + marker + "');"
                "const r=buttons.length===1?buttons[0].getBoundingClientRect():null;"
                "return {open:dialogs.length>0,dialogs:dialogs.length,closeButtons:buttons.length,"
                "x:r?r.x+r.width/2:null,y:r?r.y+r.height/2:null}})()")
            if not isinstance(state, dict):
                raise DoudianError('miaoshou_replace_layout', '图片替换窗口状态无法确认。')
            if not state.get('open'):
                return
            if (state.get('dialogs') != 1 or state.get('closeButtons') != 1 or
                    not isinstance(state.get('x'), (int, float)) or
                    not isinstance(state.get('y'), (int, float))):
                raise DoudianError('miaoshou_replace_close_not_unique', '已导入的图片窗口无法唯一定位关闭按钮。')
            focus_enabled = False
            try:
                # This modal ignores synthetic DOM click events. Send trusted browser
                # mouse input at the measured, uniquely marked visible close button.
                self.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled',
                                            'params': {'enabled': True}})
                focus_enabled = True
                self.bridge.command('cdp', {'method': 'Input.dispatchMouseEvent',
                                            'params': {'type': 'mouseMoved', 'x': state['x'], 'y': state['y']}})
                self.bridge.command('cdp', {'method': 'Input.dispatchMouseEvent',
                                            'params': {'type': 'mousePressed', 'x': state['x'], 'y': state['y'],
                                                       'button': 'left', 'clickCount': 1}})
                self.bridge.command('cdp', {'method': 'Input.dispatchMouseEvent',
                                            'params': {'type': 'mouseReleased', 'x': state['x'], 'y': state['y'],
                                                       'button': 'left', 'clickCount': 1}})
                self.bridge.wait(
                    lambda: self.bridge.evaluate(
                        "(()=>![...document.querySelectorAll('.replace-image-dialog')].some(x=>x.offsetParent!==null))()"),
                    lambda closed: closed is True,
                    '妙手图片导入弹窗没有关闭。', seconds=10)
                return
            except DoudianError as exc:
                if exc.code != 'page_timeout' or attempt == 1:
                    raise
            finally:
                try:
                    if focus_enabled:
                        self.bridge.command('cdp', {'method': 'Emulation.setFocusEmulationEnabled',
                                                    'params': {'enabled': False}})
                finally:
                    self.bridge.evaluate(
                        "(()=>{document.querySelectorAll('[data-codex-miaoshou-close=\"" + marker + "\"]')"
                        ".forEach(x=>x.removeAttribute('data-codex-miaoshou-close'));return true})()")

    def replace_slot(self, kind, slot, asset_path, *, reuse_url=None):
        source = Path(asset_path).resolve()
        if not source.is_file():
            raise DoudianError('asset_missing', f'本地素材不存在：{source.name}')
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        target, _ = self._mark_slot(kind, slot)
        if reuse_url:
            if not (is_permanent_material_url(reuse_url) or is_temporary_upload_url(reuse_url)):
                raise DoudianError('invalid_reuse_url', '续办素材地址不是已观察到的妙手暂存或永久素材地址。')
            imported = self._import_temp_url(target, reuse_url)
        else:
            self.bridge.command('click', {'selector': target})
            snap = self._wait_tree(lambda s: '上传/替换图片' in s['tree_text'],
                                   '图片替换窗口未打开。', seconds=10)
            if '文件' not in snap['tree_text'] and '本地上传' not in snap['tree_text']:
                raise DoudianError('miaoshou_upload_layout', '当前图片窗口不支持已观察到的本地上传。')
            # Network capture starts before the browser file input is selected. The upload
            # response is read once and then imported through the visible link UI.
            old = self.bridge.command('network', {'cmd': 'list'})
            old_ids = {item.get('requestId') for item in old.get('requests', [])}
            self.bridge.command('network', {'cmd': 'start'})
            self.bridge.command('upload', {'selector': '.replace-image-dialog input[type="file"]',
                                           'files': [str(source)]})
            temp_url = self._recent_upload_url(source, exclude_ids=old_ids, seconds=60)
            # Local upload sometimes closes the window by itself. Whether or not it did, the
            # only safe next step is the same observed URL import in the exact target slot.
            probe = self.bridge.evaluate("(()=>({open:[...document.querySelectorAll('.replace-image-dialog')].some(d=>d.offsetParent!==null)}))()")
            if isinstance(probe, dict) and probe.get('open'):
                # Do not click the image chooser's "确定" for a temporary local asset; that
                # would stage the transient URL. Close with the popup's own header control.
                self._close_replace_popup()
            target, _ = self._mark_slot(kind, slot)
            imported = self._import_temp_url(target, temp_url)
        imported_url = imported.get('url')
        permanent = is_permanent_material_url(imported_url)
        staged = is_temporary_upload_url(imported_url)
        if not (permanent or staged):
            raise DoudianError('miaoshou_asset_import_not_permanent',
                               '妙手返回的素材既不是已观察的暂存地址，也不是永久素材，未确认槽位。')
        expected_key = resource_key(imported_url)
        if permanent and not is_permanent_material_key(expected_key):
            raise DoudianError('miaoshou_asset_import_not_permanent',
                               '妙手永久素材ID格式未通过校验，未确认槽位，不可保存商品。')
        try:
            observed = self.bridge.wait(
                lambda: self._read_slot_url(kind, slot),
                lambda url: isinstance(url, str) and resource_key(url) == expected_key,
                f'{kind} 第{slot}张图没有显示妙手正式上传后的素材。', seconds=15)
        except DoudianError as exc:
            if exc.code != 'page_timeout':
                raise
            raise DoudianError('miaoshou_slot_readback',
                               f'{kind} 第{slot}张图与妙手正式上传响应不一致。') from exc
        finally:
            self.bridge.evaluate(
                "(()=>{document.querySelectorAll('[data-codex-miaoshou-target]').forEach("
                "x=>x.removeAttribute('data-codex-miaoshou-target'));return true})()")
        return {'slot': f'{kind}:{int(slot)}', 'source_sha256': source_hash,
                'remote_key': expected_key, 'remote_url': imported_url,
                'asset_state': 'permanent' if permanent else 'staged', 'confirmed': True,
                'import_response': imported}

    def click_save_once(self, *, prepared_save=None):
        if not prepared_save or not prepared_save.get('marker'):
            raise DoudianError('miaoshou_save_preflight_missing', '保存缺少当前商品的预览与唯一控件校验。')
        current = self.prepare_save(prepared_save['product_id'], prepared_save['title'],
                                    marker=prepared_save['marker'])
        if current != prepared_save:
            raise DoudianError('miaoshou_save_preflight_changed', '保存前控件或标题状态已变化。')
        prior = self.bridge.command('network', {'cmd': 'list', 'filter': SAVE_ENDPOINT}) or {}
        prior_ids = {request.get('requestId') for request in prior.get('requests', [])}
        self.bridge.command('network', {'cmd': 'start'})
        self.bridge.command('click', {'selector': current['selector']})
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            capture = self.bridge.command('network', {'cmd': 'list', 'filter': SAVE_ENDPOINT})
            requests = [r for r in capture.get('requests', []) if r.get('completed') and
                        r.get('requestId') not in prior_ids and r.get('method') == 'POST']
            if requests:
                latest = requests[-1]
                detail = self.bridge.command('network', {'cmd': 'detail', 'requestId': latest['requestId']})
                from .submission_evidence import classify_product_submission
                decision = classify_product_submission(latest, detail, prepared_save['product_id'])
                if decision:
                    from .miaoshou_title_editor import rejection_details
                    return {**decision, **decision['evidence'],
                            'platform_details': rejection_details(_json_body(detail.get('body')))}
            time.sleep(0.35)
        return {'state': 'unknown', 'error': 'save_response_timeout'}

    def stop_capture(self):
        try:
            self.bridge.command('network', {'cmd': 'stop'})
        except DoudianError:
            pass

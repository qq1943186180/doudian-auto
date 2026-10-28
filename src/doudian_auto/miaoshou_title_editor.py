"""Observed title-only batch UI; no uploads, AI generation, or shelf adjustment."""

import json
import re
import time
import uuid
from urllib.parse import parse_qs, unquote_plus, urlparse

from .errors import DoudianError
from .miaoshou_batch_editor import MIAOSHOU_HOST, MiaoshouBatchEditor
from .miaoshou_editor import _json_body
from .title import title_units

TITLE_URL = 'https://v2-dd.chengji-inc.com/product/batch/edit?batchType=title'
METHODS = ('addTopSearch', 'ai', 'new', 'filterKeyword', 'filterSpecial',
           'convertEnglish', 'replace', 'add', 'cutPrefixAndSuffix', 'replacePrefixAndSuffix')


def validate_title_preview(state, product_id, shop, old_title, title):
    parsed = urlparse(str(state.get('url') or ''))
    valid = (parsed.hostname == MIAOSHOU_HOST and parsed.path == '/product/batch/edit' and
             parse_qs(parsed.query).get('batchType') == ['title'] and state.get('shop') == shop and
             state.get('product_ids') == [str(product_id)] and state.get('row_ids') == [str(product_id)] and
             state.get('count') == 1 and state.get('checked_methods') == ['new'] and
             state.get('overlength') == 'fail' and state.get('repair_size') is False and
             state.get('shelf_unchanged') is True and state.get('timer') is False and
             state.get('old_title') == old_title and state.get('input_title') == title and
             state.get('row_title') == title and state.get('rendered_units') == title_units(title) and
             state.get('save_buttons') == 1 and state.get('final_submit') is True)
    if not valid:
        raise DoudianError('title_batch_preview_mismatch', '标题专用页的单品范围、预览或不调整上下架设置未通过。')
    return state


def request_matches_title(request_body, product_id, title):
    text = unquote_plus(str(request_body or ''))
    text = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), text)
    return str(product_id) in text and title in text


def rejection_details(body):
    """Keep useful rejection evidence without headers or unrelated response fields."""
    if not isinstance(body, dict):
        return {}
    return {key: str(body[key])[:2000] for key in
            ('message', 'msg', 'errorMsg', 'errorMessage', 'reason', 'code', 'sub_code', 'sub_msg')
            if body.get(key) not in (None, '')}


class MiaoshouTitleEditor(MiaoshouBatchEditor):
    def observe_title(self):
        return self.bridge.evaluate("""(()=>{
          const visible=x=>x.offsetParent!==null;
          const rows=[...document.querySelectorAll('.pro-table-custom-body-row')].filter(visible);
          const row=rows.length===1?rows[0]:null, text=row?(row.innerText||''):'';
          const ids=rows.map(x=>(x.innerText.match(/商品ID：\\s*(\\d{16,22})/)||[])[1]).filter(Boolean);
          const id=[...document.querySelectorAll('textarea[placeholder*="请输入商品ID"]')].find(visible);
          const title=[...document.querySelectorAll('textarea[name="inputNewContent"]')].find(visible);
          const counter=text.match(/(\\d+)\\s*\\/\\s*60/);
          const count=(document.body.innerText.match(/共找到\\s*(\\d+)\\s*个商品/)||[])[1];
          const timer=[...document.querySelectorAll('label')].filter(x=>visible(x)&&x.innerText.trim()==='定时执行');
          const inputs=[...document.querySelectorAll('input')].filter(visible);
          return {url:location.href,shop:(document.body.innerText.match(/您好【([^】]+)】/)||[])[1],
            product_ids:id?id.value.split(/[,，\\s]+/).filter(Boolean):[],row_ids:ids,count:count?Number(count):null,
            checked_methods:inputs.filter(x=>x.type==='checkbox'&&x.checked&&__METHODS__.includes(x.value)).map(x=>x.value),
            overlength:inputs.find(x=>x.name==='overlengthType'&&x.checked)?.value,
            repair_size:inputs.find(x=>x.name==='repairSizeTemplate')?.checked,
            shelf_unchanged:inputs.filter(x=>visible(x)&&x.value==='不调整上下架').length===1,
            timer:timer.length===1?timer[0].querySelector('input')?.checked:null,
            old_title:row?text.split('商品ID：')[0].trim():null,input_title:title?.value,
            row_title:row?.querySelector('textarea')?.value,rendered_units:counter?Number(counter[1]):null,
            save_buttons:row?[...row.querySelectorAll('.save-btn button')].filter(x=>visible(x)&&!x.disabled).length:0,
            final_submit:[...document.querySelectorAll('button.J_batchEditProduct')].filter(x=>visible(x)&&!x.disabled&&x.innerText.trim()==='开始批量修改').length===1};
        })()""".replace('__METHODS__', json.dumps(METHODS)))

    def prepare_save(self, product_id, old_title, title):
        self.bridge.command('navigate', {'url': TITLE_URL, 'newTab': True, 'group_title': '妙手标题修复'})
        self.bridge.wait(lambda: self.bridge.command('snapshot', {'format': 'aria', 'max_chars': 20000}),
                         lambda snap: (parse_qs(urlparse(snap.get('url', '')).query).get('batchType') == ['title'] and
                                       f'您好【{self.shop}】' in snap.get('tree_text', '') and
                                       '按商品ID修改' in snap.get('tree_text', '') and
                                       '使用新内容' in snap.get('tree_text', '')),
                         '妙手标题专用页面没有加载。', seconds=30)
        self._click_exact_text('[role=tab]', '按商品ID修改')
        self._fill_visible('textarea[placeholder*="请输入商品ID"]', str(product_id))
        checked = self.bridge.evaluate("(()=>[...document.querySelectorAll('input[type=checkbox]')].filter(x=>x.offsetParent!==null&&x.checked).map(x=>x.value))()")
        for method in checked:
            if method in METHODS and method != 'new':
                self._ensure_checkbox(method, False)
        self._ensure_radio('overlengthType', 'fail')
        self._ensure_checkbox('new', True)
        self._fill_visible('textarea[name="inputNewContent"]', title)
        self._click_exact_text('button', '预览修改效果')
        self.bridge.wait(self.observe_title, lambda s: s.get('count') == 1 and s.get('save_buttons') == 1 and s.get('final_submit') is True,
                         '标题预览没有收敛到唯一商品。', seconds=30)
        state = validate_title_preview(self.observe_title(), product_id, self.shop, old_title, title)
        marker = 'title-save-' + uuid.uuid4().hex
        count = self.bridge.evaluate("(()=>{const xs=[...document.querySelectorAll('button.J_batchEditProduct')].filter(x=>x.offsetParent!==null&&!x.disabled&&x.innerText.trim()==='开始批量修改');if(xs.length===1)xs[0].setAttribute('data-codex-title-save'," + json.dumps(marker) + ");return xs.length})()")
        if count != 1:
            raise DoudianError('title_batch_save_ambiguous', '标题保存按钮不唯一。')
        return {'marker': marker, 'state': state, 'product_id': str(product_id),
                'old_title': old_title, 'title': title}

    def _fill_visible(self, selector, value):
        marker = uuid.uuid4().hex
        count = self.bridge.evaluate("(()=>{const xs=[...document.querySelectorAll(" + json.dumps(selector) +
            ")].filter(x=>x.offsetParent!==null&&!x.disabled);if(xs.length===1)xs[0].setAttribute('data-codex-title-input'," +
            json.dumps(marker) + ");return xs.length})()")
        if count != 1:
            raise DoudianError('title_batch_input_ambiguous', '标题专用页输入框不唯一。')
        try:
            self.bridge.command('fill', {'selector': '[data-codex-title-input="' + marker + '"]', 'value': value})
        finally:
            self.bridge.evaluate("(()=>{document.querySelectorAll('[data-codex-title-input=\"" + marker +
                "\"]').forEach(x=>x.removeAttribute('data-codex-title-input'));return true})()")

    def click_save_once(self, prepared):
        validate_title_preview(self.observe_title(), prepared['product_id'], self.shop,
                               prepared['old_title'], prepared['title'])
        prior = self.bridge.command('network', {'cmd': 'list'}) or {}
        seen = {item.get('requestId') for item in prior.get('requests', [])}
        self.bridge.command('network', {'cmd': 'start'})
        self.bridge.command('click', {'selector': '[data-codex-title-save="' + prepared['marker'] + '"]'})
        deadline = time.monotonic() + 60
        inspected = set()
        observed = []
        while time.monotonic() < deadline:
            capture = self.bridge.command('network', {'cmd': 'list'}) or {}
            for request in capture.get('requests', []):
                rid = request.get('requestId')
                parsed = urlparse(request.get('url', ''))
                if (rid in seen or rid in inspected or not request.get('completed') or
                        request.get('method') != 'POST' or parsed.hostname != MIAOSHOU_HOST or
                        not parsed.path.startswith('/api/')):
                    continue
                detail = self.bridge.command('network', {'cmd': 'detail', 'requestId': rid}) or {}
                inspected.add(rid)
                if not request_matches_title(detail.get('requestBody'), prepared['product_id'], prepared['title']):
                    continue
                body = _json_body(detail.get('body'))
                evidence = {'request_id': rid, 'http_status': request.get('status'),
                            'observed_endpoint': parsed.path, 'request_title_matches': True,
                            'platform_details': rejection_details(body), 'clicked_control': 'J_batchEditProduct'}
                observed.append({'endpoint': parsed.path, 'result': body.get('result') if isinstance(body, dict) else None})
                if request.get('status') == 200 and isinstance(body, dict):
                    if body.get('result') in ('success', 'SUCCESS'):
                        if parsed.path == '/api/v2/product/batch/saveTempBatchTask':
                            continue
                        # This endpoint was discovered from the current UI action.
                        # Do not equate a generic success envelope with completed
                        # publication; only the independent readbacks close it.
                        return {**evidence, 'state': 'unknown', 'response_result': body['result'],
                                'error': 'title_batch_success_requires_readback'}
                    if body.get('result') in ('fail', 'FAIL', 'error', 'ERROR'):
                        return {**evidence, 'state': 'failed', 'error': 'explicit_platform_rejection'}
            time.sleep(0.35)
        return {'state': 'unknown', 'error': 'title_batch_response_unknown',
                'clicked_control': 'J_batchEditProduct', 'observed_responses': observed}

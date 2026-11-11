"""机会铺货页面适配器。

页面契约会随站点改版变化，所以每次页面动作都在**单次 evaluate** 内完成
「重识别 → 唯一性校验 → 执行 → 即时读回」。无法唯一定位时返回 layout_changed 并停止，
绝不扩大匹配范围：宽泛匹配铺货这种外部写入，比失败更危险。

选择器来自 work/optimizer-20261111/dom-contracts.md 的实抓记录，不是猜的。
"""
from __future__ import annotations

import json

from .errors import DoudianError


MIAOSHOU_HOST = 'v2-dd.chengji-inc.com'
OPPORTUNITY_PATH = '/selection/opportunity_product'
SETTING_PATH = '/move/move_setting'
HISTORY_PATH = '/move/move_history'
OFFICIAL_HOST = 'fxg.jinritemai.com'
OFFICIAL_PATH = '/ffa/g/create'

# 价格公式字段用 name 定位：这页有近百个 input，靠邻近文本匹配既脆又不唯一。
PRICE_FIELDS = (
    'pricePercent', 'priceAdd', 'priceSub', 'priceFinalPercent',
    'priceTail', 'priceDecimalDiyValue',
    'sourcePostFeePriceAddValue', 'postFeePrice1688AddValue',
)


def _js(value):
    return json.dumps(value, ensure_ascii=True)


class DropshipPages:
    def __init__(self, bridge):
        self.bridge = bridge

    def _evaluate(self, body, *, page_name):
        result = self.bridge.evaluate(body)
        if not isinstance(result, dict):
            raise DoudianError('layout_changed', f'{page_name}没有返回契约观测对象。')
        status = result.get('status')
        if status == 'layout_changed':
            raise DoudianError(
                'layout_changed',
                f"{page_name}页面结构或候选唯一性已变化"
                f"（{result.get('field') or result.get('reason') or ''}"
                f"count={result.get('count') if result.get('count') is not None else '?'}），停止操作。")
        if status == 'wrong_page':
            raise DoudianError('wrong_page', f'当前页面不是预期的{page_name}。')
        if status == 'readback_mismatch':
            raise DoudianError('readback_mismatch', f'{page_name}即时读回不一致，停止并交人工处理。')
        if status != 'ok':
            raise DoudianError('layout_changed', f'{page_name}返回未知状态 {status}。')
        return result

    # ---------- 搬家设置页 ----------

    def read_settings(self):
        """读搬家配置快照；只读，不改变共享设置。"""
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move_setting')
 return {status:'wrong_page'};
const names=__FIELDS__;
const values={};
for(const name of names){
 const xs=[...document.querySelectorAll('input[name]')].filter(x=>x.name===name);
 if(xs.length!==1)return {status:'layout_changed',field:name,count:xs.length};
 values[name]=xs[0].value;}
const radios=[...document.querySelectorAll('label.el-radio')]
 .filter(x=>(x.innerText||'').trim()==='放入仓库');
if(radios.length!==1)return {status:'layout_changed',reason:'shelf_radio',count:radios.length};
const input=radios[0].querySelector('input[type=radio]');
if(!input)return {status:'layout_changed',reason:'shelf_radio_input'};
return {status:'ok',values,shelf_mode:input.checked?'放入仓库':'other'};
})()""".replace('__FIELDS__', _js(list(PRICE_FIELDS)))
        return self._evaluate(code, page_name='搬家设置页')

    def set_price_formula(self, *, before, target):
        """按稳定 name 原子写配置并即时读回；保存按钮严格匹配「保存」。

        旧值必须与传入的 before 完全一致才动手：这是为了防止在我们读快照之后、
        有人（人或别的任务）已经改过配置，此时再写就会覆盖别人的修改。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move_setting')
 return {status:'wrong_page'};
const p=__PAYLOAD__;
for(const name of Object.keys(p.before)){
 const xs=[...document.querySelectorAll('input[name]')].filter(x=>x.name===name);
 if(xs.length!==1)return {status:'layout_changed',field:name,count:xs.length};
 if(xs[0].value!==p.before[name])
  return {status:'readback_mismatch',field:name,reason:'old_value_changed'};
}
const rs=[...document.querySelectorAll('label.el-radio')]
 .filter(x=>(x.innerText||'').trim()==='放入仓库');
if(rs.length!==1)return {status:'layout_changed',reason:'shelf_radio',count:rs.length};
for(const [name,value] of Object.entries(p.target)){
 const xs=[...document.querySelectorAll('input[name]')].filter(x=>x.name===name);
 if(xs.length!==1)return {status:'layout_changed',field:name,count:xs.length};
 const el=xs[0];
 const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
 setter.call(el,String(value));
 el.dispatchEvent(new Event('input',{bubbles:true}));
 el.dispatchEvent(new Event('change',{bubbles:true}));
}
const radio=rs[0].querySelector('input[type=radio]');
if(!radio)return {status:'layout_changed',reason:'shelf_radio_input'};
if(!radio.checked)rs[0].click();
const buttons=[...document.querySelectorAll('button')]
 .filter(x=>(x.innerText||'').trim()==='保存');
if(buttons.length!==1)return {status:'layout_changed',reason:'save_button',count:buttons.length};
buttons[0].click();
const values={};
for(const name of Object.keys(p.target)){
 const xs=[...document.querySelectorAll('input[name]')].filter(x=>x.name===name);
 if(xs.length!==1)return {status:'layout_changed',field:name,count:xs.length};
 values[name]=xs[0].value;}
const ok=Object.entries(p.target).every(([k,v])=>values[k]===String(v))&&radio.checked;
return {status:ok?'ok':'readback_mismatch',values,
 shelf_mode:radio.checked?'放入仓库':'other',
 // 保存提示可能异步出现；这里只记录它此刻是否可见，不据此判成败。
 success_message:[...document.querySelectorAll('.el-message')]
  .some(x=>(x.innerText||'').trim()==='搬家配置保存成功')};
})()""".replace('__PAYLOAD__', _js({'before': before, 'target': target}))
        return self._evaluate(code, page_name='搬家设置页')

    # ---------- 机会商品页 ----------

    def click_single_opportunity(self, *, card_text):
        """只点击唯一匹配卡片内的「立即铺货」，并在同次 evaluate 读即时结果。

        不用顶部「批量一键铺货」：那需要先选中卡片，而选中态在页面刷新后容易丢。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/selection/opportunity_product')
 return {status:'wrong_page'};
const p=__PAYLOAD__;
const roots=[...document.querySelectorAll('div.preview-item.hover-active')]
 .filter(root=>root.querySelector('.product-card.product-card__ms.product-card__orange'))
 .filter(root=>(root.innerText||'').includes(p.card_text));
if(roots.length!==1)return {status:'layout_changed',reason:'card',count:roots.length};
const actions=[...roots[0].querySelectorAll('div.J_moveCommonPreviewProductBtn')]
 .filter(x=>(x.innerText||'').trim()==='立即铺货');
if(actions.length!==1)return {status:'layout_changed',reason:'action',count:actions.length};
actions[0].click();
const text=(document.body.innerText||'');
return {status:'ok',clicked:'立即铺货',
 result_visible:text.includes('商品列表')&&/成功：\\s*\\d+/.test(text),
 next_step:[...document.querySelectorAll('button')]
  .some(x=>(x.innerText||'').trim()==='下一步: 开始复制')};
})()""".replace('__PAYLOAD__', _js({'card_text': card_text}))
        return self._evaluate(code, page_name='机会商品页')

    # ---------- 复制历史页 ----------

    def read_history_product_id(self, *, source_product_id):
        """按来源 ID 在复制历史里定位本次铺货的那一行，读目标商品 ID。

        不能要求「含商品ID的行唯一」：历史里会累积多次铺货记录，实测今天就有多条。
        必须用来源 ID 把范围收窄到本次任务，否则永远定位失败。

        空白用码点构造而非转义序列：Python 三引号会把 \t 变成真实 tab，
        写进 JS 字符串就成了一个制表符而不是正则的 \t，这类错误只有真跑才会暴露。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move_history')
 return {status:'wrong_page'};
const p=__PAYLOAD__;
// 空白变体：半角/全角空格、制表、换行，用码点拼，避免转义层级错误
const WS=String.fromCharCode(32,9,10,13,12288,160);
const srcRe=new RegExp('源ID[:：]['+WS+']*'+p.source_product_id);
const idRe=new RegExp('商品ID[:：]['+WS+']*([0-9]{16,22})');
const rows=[...document.querySelectorAll('tr')]
 .filter(x=>srcRe.test(x.innerText||''))
 .filter(x=>idRe.test(x.innerText||''));
if(rows.length!==1)return {status:'layout_changed',reason:'history_row',count:rows.length};
const match=(rows[0].innerText||'').match(idRe);
if(!match)return {status:'layout_changed',reason:'product_id_missing'};
return {status:'ok',product_id:match[1],row_text:(rows[0].innerText||'').trim().slice(0,400)};
})()""".replace('__PAYLOAD__', _js({'source_product_id': str(source_product_id)}))
        return self._evaluate(code, page_name='复制历史页')

    def read_sku_prices(self, *, product_id):
        """读官方页可见 SKU 行：行文本首段作 SKU 名，价格只取 input.value。

        不接收调用方预填的 sku_names：那会用「我期望看到什么」代替「页面实际有什么」。
        行文本里的 888888 是库存显示值，读它当价格就会误报异常。

        sku_total_count 留 null：官方页表格可能虚拟滚动，而目前没有实抓到的独立总数计数。
        「价格填写进度 100%」只证明价格都填了，证明不了行已读全，不能当完整性依据。
        完整性交给任务层 verify_target_readback 把关，读不全就停在 verification_pending。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='fxg.jinritemai.com'||u.pathname!=='/ffa/g/create'||
 u.searchParams.get('product_id')!==String(__PAYLOAD__.product_id))
 return {status:'wrong_page'};
// 用字符码点构造，避免把控制字符写进源码
const CHARSET=new RegExp('[\\t\\r\\n]+','g'), YEN=String.fromCharCode(65509);
const rows=[...document.querySelectorAll('tr')]
 .map(row=>({row,text:row.innerText.replace(CHARSET,' ').trim()}))
 .filter(x=>x.text.indexOf(YEN)>=0);
const out=[];
for(const item of rows){
 const at=item.text.indexOf(YEN);
 if(at<0)return {status:'layout_changed',reason:'sku_name_prefix'};
 const name=item.text.slice(0,at).trim();
 const inputs=[...item.row.querySelectorAll('input[placeholder=\"请输入\"]')];
 if(inputs.length!==1)
  return {status:'layout_changed',reason:'price_input',sku:name,count:inputs.length};
 out.push({sku:name,price:inputs[0].value});
}
if(!out.length)return {status:'layout_changed',reason:'no_sku_rows'};
return {status:'ok',product_id:String(__PAYLOAD__.product_id),
 sku_rows:out,sku_row_count:out.length,sku_total_count:null,
 completeness:'unverified',completeness_reason:'缺少实抓的 SKU 总数计数'};
})()""".replace('__PAYLOAD__', _js({'product_id': str(product_id)}))
        result = self._evaluate(code, page_name='抖店官方商品编辑页')
        # status 保持 'ok'：页面读到了。完整性是另一个维度，用 completeness 表达，
        # 覆盖 status 会污染 _evaluate 的失败关闭契约。
        result['completeness'] = 'unverified'
        result['completeness_reason'] = '缺少实抓的 SKU 总数计数'
        return result

    def read_review_status(self, *, product_id):
        """只读官方页可见的审核/上下架文案，原样返回，不推断。"""
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='fxg.jinritemai.com'||u.pathname!=='/ffa/g/create'||
 u.searchParams.get('product_id')!==String(__PAYLOAD__.product_id))
 return {status:'wrong_page'};
const t=(document.body.innerText||'').replace(/\\s+/g,' ');
const hits=[...new Set((t.match(/审核中|待审核|审核通过|已下架|已上架|售卖中/g)||[]))];
return {status:'ok',product_id:String(__PAYLOAD__.product_id),
 status_tokens:hits,raw:t.slice(0,400)};
})()""".replace('__PAYLOAD__', _js({'product_id': str(product_id)}))
        return self._evaluate(code, page_name='抖店官方商品编辑页')

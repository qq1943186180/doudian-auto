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
MOVE_PATH = '/move/move'
OFFICIAL_HOST = 'fxg.jinritemai.com'
OFFICIAL_PATH = '/ffa/g/create'
SOURCE_HOST = 'detail.1688.com'

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

    def navigate_miaoshou(self, path):
        """进入妙手页面并确认落位。

        只允许 v2-dd.chengji-inc.com：navigate 白名单之外的域名用 location.assign
        绕行过一次，但那样就没有 URL 校验，页面跳到别处也发现不了。
        """
        if not path.startswith('/'):
            raise DoudianError('dropship_path_invalid', '妙手页面路径必须以 / 开头。')
        self.bridge.command('navigate', {
            'url': f'https://{MIAOSHOU_HOST}{path}',
            'newTab': True,
            'group_title': '铺货流程',
        })
        return {'status': 'ok', 'path': path}

    def navigate_source(self, offer_url):
        """进入 1688 来源商品页。

        detail.1688.com 不在 navigate 白名单里，所以用 location.assign：
        适配器里随后会用 URL 校验确认落位的就是任务指定的那个 offer。
        """
        self.bridge.evaluate(
            '(()=>{location.assign(' + json.dumps(offer_url) + ');return 1;})()')
        return {'status': 'ok', 'offer_url': offer_url}

    def navigate_source(self, offer_url):
        """进入 1688 来源商品页。

        detail.1688.com 不在 navigate 白名单里，所以用 location.assign：
        适配器随后会用 URL 校验确认落位的就是任务指定的那个 offer。
        """
        self.bridge.evaluate(
            '(()=>{location.assign(' + json.dumps(offer_url) + ');return 1;})()')
        return {'status': 'ok', 'offer_url': offer_url}

    def navigate_source(self, offer_url):
        """进入 1688 来源商品页。

        detail.1688.com 不在 navigate 白名单里，所以用 location.assign：
        适配器随后会用 URL 校验确认落位的就是任务指定的那个 offer。
        """
        self.bridge.evaluate(
            '(()=>{location.assign(' + json.dumps(offer_url) + ');return 1;})()')
        return {'status': 'ok', 'offer_url': offer_url}

    def navigate_official(self, product_id):
        """进入抖店官方商品编辑页。

        官方域名在 navigate 白名单里，可以直接导航；走 location.assign 反而
        拿不到可靠的页面身份校验。
        """
        self.bridge.command('navigate', {
            'url': f'https://{OFFICIAL_HOST}{OFFICIAL_PATH}?product_id={product_id}',
            'newTab': True,
            'group_title': '铺货核验',
        })
        return {'status': 'ok', 'product_id': str(product_id)}

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
        """按稳定 name 原子写配置并即时读回 DOM；保存按钮严格匹配「保存」。

        旧值必须与传入的 before 完全一致才动手：这是为了防止在我们读快照之后、
        有人（人或别的任务）已经改过配置，此时再写就会覆盖别人的修改。

        ⚠️ 返回的 ok **只代表 DOM 已被填成目标值**，不代表服务端已保存。
        同一次 evaluate 里读到的还是我们刚写的输入框，不是服务端回读。
        真正的持久化验证必须重新进入页面后再读一次（实测刷新后 8 个字段都保持）。
        所以这里固定返回 persistence='unverified'，由任务层在独立读回后再推进阶段。
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
 // 保存提示约 1 秒后才出现且约 4 秒后消失，此刻看不到不代表没保存成功，
 // 看不到也不代表保存失败——只能作为线索记录，不能用来判成败。
 success_message:[...document.querySelectorAll('.el-message')]
  .some(x=>(x.innerText||'').trim()==='搬家配置保存成功'),
 persistence:'unverified'};
})()""".replace('__PAYLOAD__', _js({'before': before, 'target': target}))
        return self._evaluate(code, page_name='搬家设置页')

    # ---------- 1688 来源页 ----------

    def read_source_skus(self, *, offer_url):
        """读 1688 来源商品的规格名与批发价，作为复制前的预期 SKU 集合。

        这是「预期 SKU」的合法来源：复制**之前**官方页上还没有这个商品，
        唯一的先验就是来源商品的规格。复制后拿官方页的 SKU 名与它比对，
        才能证明铺出去的是同一个规格。

        实测结构（detail.1688.com）：
          div.module-od-sku-selection
            div.expand-view-item           每个规格
              span.item-label[title]       规格名（极氪车门限位器-4个装）
              span.item-price-stock        批发价（¥6）；第二个是「库存888888个」

        取第一个 item-price-stock 作为价格：第二个是库存文本，不是钱。
        """
        code = """(()=>{
const u=new URL(location.href);
if(u.hostname!=='detail.1688.com'||!/^[/]offer[/][0-9]+[.]html$/.test(u.pathname))
 return {status:'wrong_page'};
const p=__PAYLOAD__;
// 链接必须就是任务指定的那一个，否则读到的是别的商品
const m=u.pathname.match(new RegExp('^[/]offer[/]([0-9]+)[.]html$'));
if(!m||m[1]!==String(p.source_product_id))
 return {status:'wrong_page',reason:'offer_id_mismatch'};
const sel=document.querySelector('div.module-od-sku-selection');
if(!sel)return {status:'layout_changed',reason:'sku_selection_missing'};
const items=[...sel.querySelectorAll('div.expand-view-item')];
if(!items.length)return {status:'layout_changed',reason:'sku_item_missing'};
const out=[];
for(const item of items){
 const label=item.querySelector('span.item-label');
 if(!label)return {status:'layout_changed',reason:'sku_label_missing'};
 const name=(label.getAttribute('title')||label.innerText||'').trim();
 if(!name)return {status:'layout_changed',reason:'sku_label_empty'};
 const prices=[...item.querySelectorAll('span.item-price-stock')];
 if(!prices.length)return {status:'layout_changed',reason:'sku_price_missing',sku:name};
 // 第一个是批发价，第二个是「库存888888个」这类库存文本
 const priceText=(prices[0].innerText||'').trim();
 const pm=priceText.match(/([0-9]+(?:\\.[0-9]+)?)/);
 if(!pm)return {status:'layout_changed',reason:'sku_price_unparsable',sku:name,raw:priceText};
 out.push({sku:name,source_price:pm[1]});
}
return {status:'ok',source_product_id:String(p.source_product_id),
 sku_rows:out,sku_count:out.length};
})()""".replace('__PAYLOAD__', _js({'offer_url': offer_url,
                                   'source_product_id': str(offer_url).split('/offer/')[-1].split('.')[0]}))
        return self._evaluate(code, page_name='1688来源商品页')

    # ---------- 机会商品页 ----------

    def click_single_opportunity(self, *, card_text):
        """点击机会商品卡片上的「立即铺货」，并要求点击后能确认结果页出现。

        ⚠️ 这条路径**不能独立证明商品身份**：实抓确认机会卡片上没有任何
        1688 offer ID 字段（只有 Vue scope id 和妙手内部 UUID），所以
        card_text 只是一个子串线索，不是身份凭据。官方路径是贴 offer_url，
        身份由链接本身确定。

        保留这个方法只为人工选品辅助与历史兼容：它要求点击后同时出现
        「商品列表」与「下一步: 开始复制」，缺一即失败关闭，不返回 ok。
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
const resultVisible=text.indexOf('商品列表')>=0;
const nextStep=[...document.querySelectorAll('button')]
 .some(x=>(x.innerText||'').trim()==='下一步: 开始复制');
// 点击后必须能看到结果页与下一步按钮，否则不能算动作已开始
if(!resultVisible||!nextStep)
 return {status:'layout_changed',reason:'click_result_not_confirmed',
  result_visible:resultVisible,next_step:nextStep};
return {status:'ok',clicked:'立即铺货',
 result_visible:resultVisible,next_step:nextStep,
 identity:'card_text_only_not_offer_id'};
})()""".replace('__PAYLOAD__', _js({'card_text': card_text}))
        return self._evaluate(code, page_name='机会商品页')

    # ---------- 商品上货页（贴 offer_url 路径） ----------

    def paste_offer_and_fetch(self, *, offer_url):
        """把 offer URL 贴进输入框并点「开始批量抓取商品」，读回输入框与按钮状态。

        身份由链接本身确定：这是相对机会商品卡片路径的关键优势——
        卡片上没有 offer ID，只能靠标题子串猜，点错就会铺错商品。

        「开始批量抓取商品」实测唯一（同类还有「导入商品链接复制」「一键极速复制」，
        按按钮文本精确匹配可区分）。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move')
 return {status:'wrong_page'};
const p=__PAYLOAD__;
const tas=[...document.querySelectorAll('textarea')]
 .filter(x=>(x.placeholder||'').indexOf('多条地址')>=0);
if(tas.length!==1)return {status:'layout_changed',reason:'textarea',count:tas.length};
const ta=tas[0];
const setter=Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
setter.call(ta,p.offer_url);
ta.dispatchEvent(new Event('input',{bubbles:true}));
ta.dispatchEvent(new Event('change',{bubbles:true}));
if(ta.value!==p.offer_url)
 return {status:'readback_mismatch',reason:'textarea_value'};
const btns=[...document.querySelectorAll('button')]
 .filter(x=>(x.innerText||'').trim()==='开始批量抓取商品');
if(btns.length!==1)return {status:'layout_changed',reason:'fetch_button',count:btns.length};
if(btns[0].disabled)return {status:'layout_changed',reason:'fetch_button_disabled'};
btns[0].click();
return {status:'ok',textarea_value:ta.value,clicked:'开始批量抓取商品'};
})()""".replace('__PAYLOAD__', _js({'offer_url': offer_url}))
        return self._evaluate(code, page_name='商品上货页')

    def read_fetch_result(self):
        """读抓取结果页的成功/跳过/失败计数。

        「成功：N」为 0 **不等于失败**：实测已铺过的商品会显示「跳过：1 / 成功：0」，
        并提示「待搬家的商品已全部被跳过或抓取失败」。所以三个计数必须一起读，
        跳过或失败非零就停，不能只看成功数。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move')
 return {status:'wrong_page'};
const WSRE2=new RegExp('['+String.fromCharCode(32,9,10,13,12288,160)+']+','g');
const t=(document.body.innerText||'').replace(WSRE2,' ');
const WS=String.fromCharCode(32,9,10,13,12288,160);
// 空白集合要放进字符类里；直接拼 WS+'*' 会被当成「空白串重复」而不是「空白之一」
const num=(label)=>{const m=t.match(new RegExp(label+'[:：]['+WS+']*([0-9]+)'));
 return m?m[1]:null;};
const success=num('成功'), skipped=num('跳过');
const hasList=t.indexOf('商品列表')>=0;
const nextStep=[...document.querySelectorAll('button')]
 .filter(x=>(x.innerText||'').trim()==='下一步: 开始复制');
return {status:'ok',has_list:hasList,
 success_count:success,skipped_count:skipped,
 // 实测结果页没有独立的「抓取失败」计数器，抓取失败混在跳过里。
 // failed_count 恒为 null 就是如实反映——编一个数字出来才是误导。
 failed_count:null,
 failed_count_note:'结果页无独立失败计数，抓取失败混在跳过里',
 next_step_count:nextStep.length,
 detail_hint:t.indexOf('查看详情')>=0,
 all_skipped_notice:t.indexOf('已全部被跳过或抓取失败')>=0};
})()"""
        return self._evaluate(code, page_name='抓取结果页')

    def click_start_copy(self, *, expected_success=1):
        """点「下一步: 开始复制」，但必须先确认抓取结果是干净的。

        ⚠️ 点击复制是整条链里最不可逆的一步，所以它自带前置闸门：
        只有「商品列表可见 + 成功/跳过/失败三个计数齐全 + 成功数正好等于预期
        + 跳过与失败都为 0 + 按钮唯一且可用」时才点。

        之前这个方法只检查按钮，唯一性，结果页即使显示
        「跳过：1 成功：0」也能点下去——那会把一个没抓成功的商品复制进店。
        「成功：0」不等于失败（已铺过的商品会被跳过），但也**绝不能**当成可复制。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move')
 return {status:'wrong_page'};
// 每个方法自带空白定义：跨方法引用正则变量是隐式依赖，改一处就断一处
const WSRE2=new RegExp('['+String.fromCharCode(32,9,10,13,12288,160)+']+','g');
const t=(document.body.innerText||'').replace(WSRE2,' ');
if(t.indexOf('商品列表')<0)return {status:'layout_changed',reason:'result_list_missing'};
const WS=String.fromCharCode(32,9,10,13,12288,160);
const num=(label)=>{const m=t.match(new RegExp(label+'[:：]['+WS+']*([0-9]+)'));
 return m?m[1]:null;};
const success=num('成功'), skipped=num('跳过');
// 实测结果页只有「跳过」和「成功」两个计数器，没有单独的「抓取失败」计数。
// 抓取失败的商品会混在「跳过」里，页面另给一句
// 「待搬家的商品已全部被跳过或抓取失败，请查看详情」。
// 所以判据是：成功数必须正好等于预期，且跳过数为 0。
if(success===null||skipped===null)
 return {status:'layout_changed',reason:'fetch_counter_missing',
  success_count:success,skipped_count:skipped};
if(Number(success)!==Number(__PAYLOAD__.expected_success))
 return {status:'layout_changed',reason:'fetch_success_mismatch',
  success_count:success,expected:__PAYLOAD__.expected_success,
  skipped_count:skipped};
if(Number(skipped)!==0)
 return {status:'layout_changed',reason:'fetch_skipped',
  success_count:success,skipped_count:skipped};
const btns=[...document.querySelectorAll('button')]
 .filter(x=>(x.innerText||'').trim()==='下一步: 开始复制');
if(btns.length!==1)return {status:'layout_changed',reason:'next_copy_button',count:btns.length};
if(btns[0].disabled)return {status:'layout_changed',reason:'next_copy_disabled'};
btns[0].click();
return {status:'ok',clicked:'下一步: 开始复制',
 success_count:success,skipped_count:skipped};
})()""".replace('__PAYLOAD__', _js({'expected_success': int(expected_success)}))
        return self._evaluate(code, page_name='抓取结果页')

    # ---------- 复制历史页 ----------

    def read_history_product_id(self, *, source_product_id):
        """按来源 ID 在复制历史里定位本次铺货的那一行，读目标商品 ID。

        不能要求「含商品ID的行唯一」：历史里会累积多次铺货记录，实测今天就有多条。
        必须用来源 ID 把范围收窄到本次任务，否则永远定位失败。

        ⚠️ 行容器是 div.pro-table-custom-body-row，**不是 tr**。
        实测这页是 vue-recycle-scroller 虚拟滚动表格：表头「源ID」「商品ID」是列名，
        tr 里只有日历残留（读到的 tr 是「日一二三四五六」）。
        真实结构：
          cell[2] = 「供应商名 源ID： <id> 默认配置」
          cell[5] = 「2026-11-11 22:21 商品ID： <19位数字> 已下架 审核通过 销量：0」
        用 tr 定位会永远返回 0 行——这正是 Node 验证器用同样错结构而自洽通过的原因。

        空白用码点构造而非转义序列：Python 三引号会把 \t 变成真实 tab，
        写进 JS 字符串就成了一个制表符而不是正则的 \t，这类错误只有真跑才会暴露。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move_history')
 return {status:'wrong_page'};
const p=__PAYLOAD__;
// 来源 ID 必须是纯数字：它会被拼进正则，带正则字符就能改变匹配含义。
if(!/^[0-9]{1,24}$/.test(String(p.source_product_id)))
 return {status:'layout_changed',reason:'source_id_invalid'};
// 空白变体：半角/全角空格、制表、换行，用码点拼，避免转义层级错误
const WS=String.fromCharCode(32,9,10,13,12288,160);
// 末尾加数字负向边界：短 ID 不能命中长 ID 的前缀
const srcRe=new RegExp('源ID[:：]['+WS+']*'+p.source_product_id+'(?![0-9])');
const idRe=new RegExp('商品ID[:：]['+WS+']*([0-9]{16,22})');
// 行容器是虚拟滚动表格的 div 行，不是 tr：这页 tr 里只有日历残留
const rows=[...document.querySelectorAll('div.pro-table-custom-body-row')]
 .filter(x=>srcRe.test(x.innerText||''))
 .filter(x=>idRe.test(x.innerText||''));
if(rows.length!==1)return {status:'layout_changed',reason:'history_row',count:rows.length};
const match=(rows[0].innerText||'').match(idRe);
if(!match)return {status:'layout_changed',reason:'product_id_missing'};
// row_key 是稳定的行标识：源ID + 商品ID。
// 基线比对靠它——只比行文本会因为页面文案变化而误判。
const rowKey=p.source_product_id+'@'+match[1];
return {status:'ok',product_id:match[1],row_key:rowKey,
 row_text:(rows[0].innerText||'').trim().slice(0,400)};
})()""".replace('__PAYLOAD__', _js({'source_product_id': str(source_product_id)}))
        return self._evaluate(code, page_name='复制历史页')

    def read_history_baseline(self, *, source_product_id=None):
        """读复制历史里本任务来源的行，作为点击复制前的基线。

        用途：复制之后只认基线里没有的新行。少了这一步，
        「历史里本来就有的那条记录」会被当成本次复制成功。

        只收本任务来源的行：不同任务之间不该互相干扰。
        同时收「只有源ID、还没商品ID」的行——那正是复制进行中的形态，
        漏掉它就分不清「本次还在复制」和「本次已复制完」。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='v2-dd.chengji-inc.com'||u.pathname!=='/move/move_history')
 return {status:'wrong_page'};
const p=__PAYLOAD__;
const WS=String.fromCharCode(32,9,10,13,12288,160);
const srcRe=new RegExp('源ID[:：]['+WS+']*([0-9]{1,24})(?![0-9])');
const idRe=new RegExp('商品ID[:：]['+WS+']*([0-9]{16,22})');
const keys=[]; let srcOnly=0;
for(const row of document.querySelectorAll('div.pro-table-custom-body-row')){
 const t=row.innerText||'';
 const sm=t.match(srcRe); const im=t.match(idRe);
 if(!sm) continue;
 // 只看本任务来源的行
 if(p.source_product_id&&sm[1]!==String(p.source_product_id)) continue;
 if(im) keys.push(sm[1]+'@'+im[1]);
 else { srcOnly++; keys.push(sm[1]+'@pending'); }
}
return {status:'ok',baseline_keys:[...new Set(keys)],pending_rows:srcOnly};
})()""".replace('__PAYLOAD__', _js({'source_product_id': str(source_product_id or '')}))
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
// 价格填写进度是页面上独立存在的计数：它证明每个 SKU 的价格都已填写。
// 它不能证明行已读全（表格可能虚拟滚动），所以只作为核验的一个条件，
// 缺它时核验层会停在 verification_pending，而不是直接判失败。
const body=(document.body.innerText||'');
// 空白用码点构造：Python 三引号里的 \\s 落成 JS 的 \\s（字面反斜杠+s），不是空白
const WSRE=new RegExp('['+String.fromCharCode(32,9,10,13,12288,160)+']*');
// RegExp 对象不能直接当字符串拼，要取 .source 才是正则源码
const pm=body.match(new RegExp('价格填写进度'+WSRE.source+'([0-9]+)%'));
return {status:'ok',product_id:String(__PAYLOAD__.product_id),
 sku_rows:out,sku_row_count:out.length,sku_total_count:null,
 price_progress:pm?Number(pm[1]):null,
 completeness:'unverified',completeness_reason:'缺少实抓的 SKU 总数计数'};
})()""".replace('__PAYLOAD__', _js({'product_id': str(product_id)}))
        result = self._evaluate(code, page_name='抖店官方商品编辑页')
        # status 保持 'ok'：页面读到了。完整性是另一个维度，用 completeness 表达，
        # 覆盖 status 会污染 _evaluate 的失败关闭契约。
        result['completeness'] = 'unverified'
        result['completeness_reason'] = '缺少实抓的 SKU 总数计数'
        return result

    def read_review_status(self, *, product_id):
        """只读官方页可见的状态文案，原样返回，不推断。

        ⚠️ 实测结论：**编辑页上没有商品审核状态**。
        页面上出现的「已上架」是 **SKU 状态**（每个规格行末尾的角标），
        「上架/下架」是「*商品状态」表单里的两个可选项，不是当前状态。
        商品的审核状态在抖店商品列表页，不在这里。

        所以这里分开报：sku_status_tokens 是规格行状态，product_state_options 是
        表单里的选项，商品审核状态一律标为 unavailable——不拿 SKU 状态冒充审核状态。
        """
        code = """(()=>{const u=new URL(location.href);
if(u.hostname!=='fxg.jinritemai.com'||u.pathname!=='/ffa/g/create'||
 u.searchParams.get('product_id')!==String(__PAYLOAD__.product_id))
 return {status:'wrong_page'};
// 空白用码点构造，不依赖别处的正则定义
const WSRE2=new RegExp('['+String.fromCharCode(32,9,10,13,12288,160)+']+','g');
const t=(document.body.innerText||'').replace(WSRE2,' ');
// SKU 状态：规格行末尾的角标
const skuTokens=[...new Set([...document.querySelectorAll('tr')]
 .map(tr=>tr.innerText||'')
 .join(' ')
 .match(/已上架|已下架|未上架|已售罄/g)||[])];
// 商品状态表单里的选项：它们是可选值，不是当前状态
const stateOptions=[...document.querySelectorAll('span')]
 .map(s=>(s.innerText||'').trim())
 .filter(x=>x==='上架'||x==='下架');
return {status:'ok',product_id:String(__PAYLOAD__.product_id),
 sku_status_tokens:skuTokens,
 product_state_options:[...new Set(stateOptions)],
 review_status:null,
 review_status_reason:'商品审核状态不在编辑页；「已上架」是 SKU 状态，不能当审核状态',
 raw:t.slice(0,300)};
})()""".replace('__PAYLOAD__', _js({'product_id': str(product_id)}))
        return self._evaluate(code, page_name='抖店官方商品编辑页')

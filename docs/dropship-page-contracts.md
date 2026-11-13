# 铺货流程 · 四页 DOM 契约（2026-11-11 实抓）

> 这是 `capture-dom.py` 从真实页面抓到的结构，供写页面适配层使用。
> 所有定位都必须满足：**同一次 evaluate 内完成「重识别 → 唯一性校验 → 执行 → 即时读回」**，
> 候选不唯一就返回 layout_changed 并停止，不扩大匹配范围。

## 页面 1：搬家设置页

URL：`https://v2-dd.chengji-inc.com/move/move_setting`（在 navigate 白名单内）
规模：98 个 text input、75 个 radio、45 个 el-select、37 个 button

### 价格公式输入框（有稳定 name，优先用 name）

| 字段 | name | 当前值 | 含义 |
|---|---|---|---|
| 倍数 | `pricePercent` | `300` | 货源零售价 × 300% |
| 加价 | `priceAdd` | `5` | + 5 元 |
| 减价 | `priceSub` | `` | - 元 |
| 最终价倍数 | `priceFinalPercent` | `100` | 最终价格 × 100% |
| 尾数金额 | `priceTail` | `` | 尾数处理 |
| 尾数值 | `priceDecimalDiyValue` | `88` | 小数处理 |
| 货源不包邮加价 | `sourcePostFeePriceAddValue` | `` | 货源平台不包邮 + 元 |
| 1688 不包邮加价 | `postFeePrice1688AddValue` | `5.00` | 1688 不包邮 + 元 |

定位：`document.querySelector('input[name=pricePercent]')`
**必须校验唯一性与旧值**（如旧值不是预期的 200/300 要报告）。

### 库存输入框（无 name，靠邻近文本）

| 字段 | 邻近文本 | 当前值 |
|---|---|---|
| 统一库存 | `统一库存为:` | 空（空 = 跟来源） |
| 来源库存小于等于 | `如果来源SKU库存小于等于` | `0` |
| 删除库存小于等于 | `删除库存小于等于 的SKU` | 空 |
| 来源为0时设为 | `来源库存为 0 时，将库存设置为：` | `0` |

**「统一库存为」留空即代表库存跟来源**，这是本项目的策略，不要填值。

### 上架设置（radio）

`label.el-radio`，文本三选一：`立即上架` / `放入仓库` / `放至草稿箱`
- 当前选中：`放入仓库`
- 定位：找 `label.el-radio` 且 `innerText.trim() === '放入仓库'`
- 选中态在内部 `input[type=radio]` 的 `checked`

### 保存

button 文本 `保存`（另有 `保存并多店铺同步`，**不要点错**）
保存成功提示：`.el-message` 文本 `搬家配置保存成功`

---

## 页面 2：机会商品页

URL：`https://v2-dd.chengji-inc.com/selection/opportunity_product`（白名单内）
规模：3 个 text input、39 个 button、35 个 checkbox、无 table

### 筛选 checkbox（选品保障区）

`label.el-checkbox`，文本精确匹配。目标：
- `一件代发`
- `支持抖音密文`（= 电子面单）

其他可选：`包邮`、`48小时发货`、`七天无理由包退`、`当日发货`、`24小时发货`、`72小时发货`

⚠️ 页面上有 35 个 checkbox，**必须先按文本精确匹配再校验唯一**。

### 商品卡片结构（class 链，自外向内）

```
div.preview-item.hover-active          ← 卡片根
  div.product-card.product-card__ms.product-card__orange
    ...标题、标签（支持密文/一件代发/48小时发货/分销五星...）、价格区间、商机名
    div.product-card-footer
      div.J_moveCommonPreviewProductBtn  ← 「立即铺货」按钮（文本 4 字）
      ...「更多货源」「选中」
```

**单件铺货入口 = `div.J_moveCommonPreviewProductBtn`（卡片内的「立即铺货」）**
不要用顶部「批量一键铺货」（需先选中，选中态易丢）。

### 卡片可读字段

- 标题：卡片内文本，`素材优化` 前缀后到 `支持密文` 之前
- 价格区间：`￥57.00 ~ 89.00`
- 商机名：`商机：XXX`
- 保障标签：`支持密文`、`一件代发`、`48小时发货`、`分销五星`

### 铺货后的结果页

点「立即铺货」后页面显示：
- `商品列表` + `成功： N`
- SKU 信息、主图、详情图 tab
- 「**下一步: 开始复制**」按钮
- 被跳过时弹窗：`跳过复制 (N)` / `抓取失败 (N)`，原因如 `跳过已复制商品`

---

## 页面 3：复制历史页

URL：`https://v2-dd.chengji-inc.com/move/move_history`（白名单内）
规模：15 个 text input、43 个 button、2 个 table、14 个 tr

tab 计数：`正在复制中` / `已成功复制` / `复制失败` / `跳过复制` / `已取消复制`

### 商品行可读字段（实抓样本）

```
阿里巴巴<标题>
发布类目：汽车用品>汽车防护用品>其他汽车防护用品
1688分销 | <供应商名>（<供应商名>）
源ID： 965251097615
默认配置
等待审核 | 已成功复制
2026-11-11 22:21
商品ID： 3853454064050373417
已下架 | 待审核 | 销量：--
商品快速编辑 | 去抖店编辑 | 更多
```

**目标商品 ID 从 `商品ID： <digits>` 提取**，这是铺货结果的唯一凭据。

---

## 页面 4：抖店官方商品编辑页

URL：`https://fxg.jinritemai.com/ffa/g/create?product_id=<ID>`（白名单内）
规模：18 个 text input、4 个 number input、11 个 radio、6 个 checkbox、28 个 button

### SKU 行输入框（**无 name，只能靠 placeholder**）

| 字段 | placeholder | type | 实测值 |
|---|---|---|---|
| 价格 | `请输入` | text | `27.48` / `15.48` |
| 库存 | `请输入库存` | number | 空 |
| ERP编码 | `请输入erp编码` | text | 空 |
| 条形码 | `请输入条形码` | text | 空 |

行定位：`tr` 的 innerText 含 SKU 名（如 `极氪车门限位器-4个装`）

🔴 **价格必须读 `input.value`，绝不能读 innerText**
SKU 行 innerText 形如 `极氪车门限位器-4个装 ￥ 888888 增 减 888888 清空 - 3392818512538149 去关联 已上架`
其中 `888888` 是**库存显示值**，不是价格。价格在 `input[ph=请输入].value`。

### 页面级按钮

`发布商品`、`保存草稿`、`填写检查`、`批量设置`、`可售库存清零`、`预览`

### 关键按钮文案

- 「下一步: 开始复制」
- 「立即铺货」
- 「保存」（搬家配置）

---

## 跨域导航

| 目标 | 能否 navigate | 说明 |
|---|---|---|
| `v2-dd.chengji-inc.com` | ✅ | 白名单内 |
| `fxg.jinritemai.com` | ✅ | 白名单内 |
| `fb-dd.chengji-inc.com` | ❌ | 需 `location.assign` |
| `detail.1688.com` | ❌ | 需 `location.assign` |
| `s.1688.com` | ❌ | 需 `location.assign` |

`ego_runtime.mjs` 的白名单写死在 `['v2-dd.chengji-inc.com','fxg.jinritemai.com']`。

---

## 二轮实抓补充（2026-11-11 深夜，为接状态机而测）

以下都是本轮真实页面的时序/行为观测，不是推断。

### 保存提示的时序（`.el-message`）

点「保存」后密集采样（每 0.5s）结果：

| 时刻 | `.el-message` 内容 |
|---|---|
| +0ms | （点击） |
| **+1039ms** | `搬家配置保存成功` ← 首次出现 |
| +2019ms | `搬家配置保存成功` |
| +2992ms | `搬家配置保存成功` |
| +3972ms | `搬家配置保存成功` |
| **+4969ms** | 空 ← 消失 |

结论：
- 提示在点击后 **1 秒内**出现，存在窗口约 **4 秒**
- `.el-message` 与 `.el-message__content` 会同时命中同一条，去重后是一条
- 🔴 **提示是「成功证据」，但提示缺失不能当失败证据**：4 秒后提示必然消失，
  此时若因轮询太晚没读到，不能推断保存失败。设计上应是
  「点保存 → 等 ~1.5s → 读提示 → 读不到就标记 unknown_save_prompt，
  再走独立的只读确认（重新读配置值）」，而不是判失败。

### 筛选勾选后会丢状态（重要坑）

`label.el-checkbox` 点击后即时读回正常（`was:false → now:true`），但：

| 筛选 | 点击后即时 | 3 秒后 |
|---|---|---|
| 一件代发 | `true` | **`false`** ← 被重置 |
| 支持抖音密文 | `true` | `true` |

原因：勾选触发列表刷新/组件重渲染，部分筛选态被重置。

🔴 **结论：不能假设勾选状态持续存在。** 每次执行依赖筛选的操作前，
都要重新勾选并即时读回；跨步骤不能复用上一次的勾选结果。

### 勾选方式（已验证可用）

单次 evaluate 内完成「定位 label → 取内部 input[type=checkbox] → 读 was → click → 读 now」，
实测 `was/now` 都能正确反映。`label.is-disabled` 可判断是否可点。

### 仍未实抓（Codex 标注为需先测，勿猜）

1. **「立即铺货」→「商品列表 / 成功:N」的等待时长**：需一次真实铺货才能测，会消耗额度并创建商品，未测
2. **「下一步: 开始复制」点击后的即时反馈**：同上，未测
3. **「下一步: 开始复制」按钮的稳定定位方式**：今日实测它出现在结果页按钮列表里，但没有独立 class 记录，**需先实抓再写选择器**

---

## 三轮实抓：机会商品卡片无法关联来源 ID（设计结论）

Codex 质疑「不能仅凭标题文本包含关系认定商品身份」。实抓证实它是对的：

卡片根属性只有：

```
class="preview-item hover-active"
data-v-d23579a9=""   ← Vue scope id，无意义
data-v-b800f57d=""
style="--2c70ef42: 40px; ..."
```

子元素中唯一的 ID 类字段是 `data-custom-id="8a9c0adf-9440-48a6-996e-ee836f96845a"`
——这是妙手内部 UUID，**不是 1688 offer ID**，也无法从任务 manifest 推导。

### 结论：放弃「机会商品页选品」路径，改为「贴 offer_url」路径

理由：
1. **身份确定性**：卡片无法关联来源 ID，标题文本匹配是弱证据，点错就是铺错商品
2. **任务已有 offer_url**：manifest 里存的就是 1688 链接，链接即身份
3. **路径已验证**：上一轮手工贴 `https://detail.1688.com/offer/1038374387754.html`
   到 `/move/move`，妙手正确识别标题并执行（因重复被跳过，抓取本身成功）
4. **符合原始需求**：需求本来就是「给 1688 链接铺货」

### 新路径（代替机会商品页）

```
/move/move  → textarea[placeholder="多条地址换行或逗号区分"] 贴 offer_url
            → 点「开始批量抓取商品」
            → 等「商品列表 / 成功:N」
            → 点「下一步: 开始复制」
```

机会商品页的「一件代发 / 支持抖音密文」筛选仍可作为**人工选品**的辅助界面，
但不作为程序自动路径——因为选了卡片也证明不了它是任务的来源。

---

## 四轮实抓：结果页结构（用已铺过的链接测，未创建新商品）

贴 `offer/1038374387754.html`（已铺过）→ 点「开始批量抓取商品」→ **2 秒内**到结果页。

### 结果页按钮（顺序）

```
返回上一步 | 加入云商品库 | 下一步: 开始复制 | 复制到多店
```

「下一步: 开始复制」定位：`button` 文本 `下一步: 开始复制`，**唯一**
class = `el-button el-button--primary el-button--large`

### 计数器是两个独立数字，不能只看 success

```
商品列表
跳过： 1  详情
成功： 0
```

实测：商品已铺过时 `跳过:1 / 成功:0`，且页面提示
「待搬家的商品已全部被跳过或抓取失败，请查看详情」+「查看详情」按钮。

🔴 **结论：`成功：N` 为 0 不代表失败**，可能全部被跳过（重复商品）。
判读必须同时读「跳过：N」与「成功：N」；跳过>0 时应停止而非继续点复制。

### 结果页表格是虚拟滚动

`document.querySelectorAll('tr')` 读不到行内容（本次实测 rows 为空）。
SKU 信息在 `商品信息 / SKU信息 / 主图/规格图 / 详情图 / 服务与资质` 这些 tab 里，
**读取 SKU 集合需先实抓 tab 内容，当前无契约依据**。

### 「开始批量抓取商品」定位

唯一（实测 count=1），class `el-button el-button--primary el-button--large pro-…`，
未禁用。同类按钮还有「导入商品链接复制」「一键极速复制」，按文本精确匹配可区分。

### textarea 贴链接

`textarea[placeholder="多条地址换行或逗号区分"]`，实测用原生 setter + input/change 可写入。

---

## 五轮实抓：SKU 完整性的独立计数依据

Codex 要求「防止读不全」。实抓找到两个可用的独立计数：

### 1. `价格填写进度 <N>%`（推荐用作完整性校验）

页面文本实测含：

```
*价格与库存
价格填写进度 100%
区域库存 全屏 预览
全部颜色 增 减 批量设置 可售库存清零
```

用途：**进度 100% 表示所有 SKU 价格都已填写**。
若读到的 SKU 行全部有非空价格、但进度不是 100%，说明还有行没被读到（虚拟滚动）
或确有 SKU 缺价 → 不得标 verified，停在 verification_pending。

匹配式：`/价格填写进度\s*(\d+)%/`

### 2. SKU 行本身（tr 可读，实测 2 行）

```
极氪车门限位器-4个装 ￥ 888888 增 减 888888 清空 - 3392818512538149 去关联 已上架
极氪车门限位器-1个装 ￥ 888888 增 减 888888 清空 - 3392818512538405 去关联 已上架
```

- 行定位：`tr` 文本包含 SKU 名
- SKU 名：行文本首段（到 `￥` 之前）
- 价格：`input[placeholder=请输入].value`（**不是行里的 888888**）
- 规格类型名：`颜色`（另有 `添加规格类型（1/3）` 表示已用 1/3 种规格类型）

### 仍未解决

- 多 SKU 商品（如 20 个）时表格是否虚拟滚动、能否一次读全，**未实测**。
  今天的商品只有 2 个 SKU，全在可见区。这是真实风险，需用一件多 SKU 商品验证。

---

## 六轮实抓：配置持久化的独立读回（Codex 复核要求的关键证据）

Codex 指出：写完配置后立刻读同一份 DOM，只能证明「输入框里的值变了」，
不能证明「服务端存了」。实测整页刷新后重读：

| 字段 | 刷新前 | 刷新后 |
|---|---|---|
| pricePercent | 300 | **300** |
| priceAdd | 5 | **5** |
| priceSub | (空) | (空) |
| priceFinalPercent | 100 | **100** |
| priceTail | (空) | (空) |
| priceDecimalDiyValue | 88 | **88** |
| sourcePostFeePriceAddValue | (空) | (空) |
| postFeePrice1688AddValue | 5.00 | **5.00** |
| 「放入仓库」radio checked | true | **true** |

8 个价格字段的 `input[name]` 全部**唯一命中**（dup 为空），radio 唯一命中。

### 由此确定的设计

1. `set_price_formula` 只负责「写 DOM + 点保存 + 读回 DOM」，返回
   `persistence: 'unverified'`。**不得**据此推进阶段。
2. 推进到 `settings_verified` 必须经过**独立重新进入页面**后的读回
   （重新 navigate 或 reload，不是同一次 evaluate 里的二次读取）。
3. 完整目标配置必须覆盖全部 8 个字段，缺一个都不算读回一致。

### 顺带确认的价格语义

- `pricePercent=300` 是**百分比**（300%），CLI 的 `multiplier=3` 是**倍数**，两者差 100 倍，接线时必须换算。
- `priceDecimalDiyValue=88` 是尾数，`priceFinalPercent=100` 是最终价倍数，
  `postFeePrice1688AddValue=5.00` 是 1688 不包邮加价（金额）。
- 实测源价 2 → 售价 15.48，源价 6 → 27.48。差 4.48 是运费，
  即 `2×3+5=11` 再加运费 4.48。**运费不在上述 8 个字段里**，
  说明 CLI 的简化试算无法代表页面最终售价，核验必须读官方页实际价格。

---

## 七轮实抓：复制历史页的真实行容器是 div，不是 tr（重要修正）

之前一直用 `document.querySelectorAll('tr')` 找历史行，**在真实页面上永远返回 0 行**。
实抓发现这页是 `vue-recycle-scroller` 虚拟滚动表格：

| 事实 | 实测值 |
|---|---|
| `tr` 里的内容 | 「日一二三四五六」「25262728293031」——**日历残留**，不是数据行 |
| 真实行容器 | `div.pro-table-custom-body-row` |
| 表格容器 | `div.vue-recycle-scroller__item-view` → `div.pro-table-custom-body-row-wrap.message` |
| 每行 cell 数 | 8 |

### 真实 cell 结构

```
cell[0] = ""
cell[1] = 标题 + 发布类目 + 1688分销
cell[2] = 供应商名 + 源ID： <id> + 默认配置      ← 源ID 在这里
cell[3] = 审核状态（审核通过 / 空）
cell[4] = 复制状态（已成功复制 / 正在复制中 / 复制失败）
cell[5] = 时间 + 商品ID： <19位数字> + 已下架 + 审核通过 + 销量：0   ← 商品ID 在这里
cell[6] = ""
cell[7] = 操作链接（商品快速编辑 / 去抖店编辑 / 更多）
```

实测行数 8，每行都能用 `商品ID[:：][空白]*(\d{16,22})` 取到商品 ID。

### 🔴 这暴露了验证器的一个根本缺陷

之前的 Node 验证器**自造了 `tr` 行**做 stub，于是自洽通过——而真实页面上是 0 行。
也就是说：验证器证明的是「我写的代码符合我写的假页面」，不是「符合真实页面」。

已修：
1. 适配器改用 `div.pro-table-custom-body-row`
2. stub 改为**从实抓页面逐字抄下来的真实 cell 文本**，并保留「tr 里只有日历」这一事实
3. 新增验证：**真实页面上读回商品ID 3853454064050373417**，不存在的源ID 正确失败关闭

**教训：stub 必须来自实抓，不能自己编。** 这次是「Node 真跑」这条防线第一次
被自己钻了空子——它证明了 JS 可执行，但没证明选择器对。

---

## 八轮实抓：结果页只有两个计数器，编辑页没有审核状态

### 结果页计数器（实测全部「数字: N」形态）

```
商品列表  跳过： 1 详情  成功： 0
```

全页扫描到的「xx: N」只有四个：`添加主图：0`、`优化商品：1688`、`跳过：1`、`成功：0`。

🔴 **结果页没有独立的「抓取失败」计数器。** 抓取失败的商品混在「跳过」里，
页面另给一句提示：

> 待搬家的商品已全部被跳过或抓取失败，请查看详情

所以判据只能是：**成功数 == 预期 且 跳过数 == 0**。
之前按「失败计数」设计的闸门会把正常流程也挡住。

### 官方编辑页没有商品审核状态

页面全文能匹配到的状态文案只有：

| 文案 | 真实含义 | 位置 |
|---|---|---|
| `已上架` | **SKU 状态**（每个规格行末尾的角标） | tr 行内 |
| `上架` / `下架` | 「*商品状态」表单里的两个**可选项** | span |

**商品审核状态在抖店商品列表页，不在编辑页。**
之前把「已上架」当审核状态读出来，是把 SKU 状态误报成了审核状态。
现在适配器分开报 `sku_status_tokens` / `product_state_options`，
`review_status` 恒为 null 并附原因说明。

### 官方页 SKU 行是真实 tr（与历史页不同）

| 事实 | 官方编辑页 | 复制历史页 |
|---|---|---|
| 行容器 | `tr` ✅ | `div.pro-table-custom-body-row` |
| tr 内容 | 真实数据行 | **日历残留** |
| 每行 input | 6 个（价格1 + radio2 + 库存 + erp + 条形码） | — |

价格 input 是唯一 `placeholder="请输入"` 的那个，`value` 为 `27.48` / `15.48`；
行文本里的 `888888` 是库存显示值。

### 复制历史行的稳定标识

行文本会随页面文案变化，所以基线比对用 `row_key = <源ID>@<商品ID>`，
它由两个正则从行文本里提取，不受周边文案变动影响。

### 现存 42 条源链接全是 http

实抓核对：`source-links.json` 42 条**全部**是 `http://detail.1688.com/offer/<ID>.html`，
无查询参数。校验器若只收 https 会把全部现有关联拒掉。
现在 http 与 https 都接受，写入 manifest 前统一规范成 https，并保留原链接供追溯。

---

## 九轮实抓：1688 来源商品的规格（预期 SKU 的合法来源）

Codex 指出一个循环依赖：`mark_copy_intent` 要求复制**前**就落盘 expected_skus，
但读 SKU 的适配器读的是抖店官方编辑页，那里此时还没有这个商品。

**解法**：预期 SKU 来自 **1688 来源页**的规格选择区。

### 实测结构（detail.1688.com）

```
div.module-od-sku-selection            ← 规格选择区
  div.feature-item
    div.feature-item-label > h3         ← 规格维度名（这里是「颜色」）
    div.expand-view-list-wrapper
      div.expand-view-list
        div.expand-view-item.v-flex     ← 每个规格
          div.v-flex
            span.item-label[title]      ← 规格名（极氪车门限位器-4个装）
          span.item-price-stock         ← 批发价 ¥6
          span.item-price-stock         ← 库存888888个（不是钱！）
```

实测读出：

| 规格名 | 批发价 |
|---|---|
| 极氪车门限位器-4个装 | 6 |
| 极氪车门限位器-1个装 | 2 |

与官方页完全对应（官方页 SKU 名相同，售价 27.48 / 15.48 = 源价×3+5+运费 4.48）。

### 🔴 两个必须注意的点

1. **同一行有两个 `span.item-price-stock`**：第一个是价格，第二个是「库存888888个」。
   取第二个会把库存当价格。适配器固定取**第一个**。
2. **规格名优先取 `title` 属性**：`span.item-label` 的 `title` 与 innerText 一致，
   但 title 更稳（不受空白影响）。

### 核验语义随之确定

预期集合的值是**来源批发价**，比对时比的是**规格名集合**，不是价格：

- 官方页售价含运费与尾数，与来源批发价**本来就不相等**（6 → 27.48）
- 但规格名必须一一对应：少一个规格就说明没铺全 → `verification_pending`

### 属性区也印证了这点

`tr` 里「颜色」一行写着：`极氪车门限位器-4个装、极氪车门限位器-1个装`，
与规格选择区一致。

---

## 十轮实抓：复制历史是虚拟滚动，基线无法从 DOM 证明完整

Codex 四轮指出「基线只扫当前 DOM 行」是阻断问题。实抓证实：

| 项 | 实测值 |
|---|---|
| 页面明写的总记录数 | **「共 59 条」**（另有 `来源商品名称/保存类目 (59)`） |
| DOM 中的 `div.pro-table-custom-body-row` | **8 行** |
| 差额 | **51 条未渲染** |

`div.vue-recycle-scroller__item-view` 是虚拟滚动容器，只挂载视口内的行。

### 🔴 结论：当前版本不能自动点复制

只要历史记录超过一屏，`read_history_baseline` 就读不到全量，
本来源的旧记录可能落在未渲染的 51 条里，复制后会被误认成「本次新增」。

已落地的安全底线：
- `read_history_baseline` 读页面「共 N 条」与渲染行数，返回
  `total_records` / `rendered_rows` / `baseline_complete`。
- 实测返回 `total_records: 59, rendered_rows: 8, baseline_complete: false`。
- `_stage_copy` 遇到 `baseline_complete: false` 直接抛
  `dropship_baseline_incomplete` 拒绝复制。

### 要让自动化真正可用，还差什么

页面上有筛选表单（18 个 input，其中两个 placeholder 是
「多个用","或空格分隔，支持Excel复制粘贴」，对应「商品ID」「来源ID」）。
**按来源 ID 筛选**能让本来源的所有行都进视口，届时
「渲染行数 == 筛选后总数」就能证明基线完整。

但这需要再实抓：筛选框的稳定定位、点「查询」后的即时读回、
筛选后「共 N 条」是否同步变化。没有这些证据之前不能猜选择器。

---

## 十一轮实抓：来源ID筛选框（解锁基线完整性）+ 跳过为 0 时计数器隐藏

### 复制历史页的「来源ID」筛选框

| 事实 | 实测值 |
|---|---|
| 筛选框 | `input[name="sourceItemId"]`，label 是「来源ID」 |
| placeholder | `多个用“,”或空格分隔，支持Excel复制粘贴` |
| 查询按钮 | `button` 文本 `查询` |
| 分页总数 | `共 N 条`（分页器里，如「共 1 条 1 前往 页 20/页」） |

单次 evaluate 完成「定位→填值→即时读回→点查询」，然后独立轮询读结果：

| 筛选值 | 共 N 条 | 匹配行数 | baseline_complete |
|---|---|---|---|
| `965251097615`（已铺过） | 1 | 1 | **true** |
| `999999999999`（不存在） | 0 | 0 | **true** |
| 不筛选（全表） | 59 | 8 | false |

判据：**筛选框的值必须等于本任务来源**，且 `共 N 条 == 源ID 匹配行数`。
筛选后通常 0～2 条，虚拟滚动不再是障碍。筛选框不是本来源时一律判基线无效。

### 结果页计数器：跳过为 0 时整个隐藏

| 场景 | 页面文本 |
|---|---|
| 商品已铺过（被跳过） | `商品列表 跳过： 1 详情 成功： 0` |
| **抓取成功、无跳过** | `商品列表 成功： 1` ← **没有「跳过」计数器** |

全页扫描「xx: N」形态，成功场景只有：`添加主图：0`、`优化商品：1688`、`成功：1`。

🔴 之前轮询要求「成功/跳过两个计数都非空」，成功场景永远超时，
**真的没点成复制**。修法：成功数已出现、且没有「已全部被跳过或抓取失败」
提示时，把跳过高置信度规范成 `0`，并标 `skipped_inferred: true`；
成功数还没出现时绝不推断，避免把未加载完的页面当成成功。

### 官方编辑页：草稿箱商品的 SKU 行形态不同

| 项 | 已铺商品（极氪） | 草稿箱商品（除味剂） |
|---|---|---|
| SKU 名 | `极氪车门限位器-4个装` | `2500ml（生物酶除臭剂）` |
| 行文本价格 | `￥ 888888`（库存） | `￥85.88/2.5L`（规格价文本） |
| `input.value` | `27.48` / `15.48` | `85.88` / `139.88` |
| 规格名相对来源 | 一致 | **被妙手改写** |

价格一律读 `input[placeholder="请输入"].value` 仍然成立。
规格名改写会让「规格名集合一致」这条核验判据在真实搬家后不成立——
核验如实报出并停在 `verification_pending`，这是对的行为，不是 bug。

### 导航后必须等待

`navigate_official` 返回后 DOM 还没渲染出 SKU 表，立刻读会得到 0 行，
被误报成 `layout_changed: no_sku_rows`。实测需等十几秒。
`_readback_only` 已补 `time.sleep(SETTLE_SECONDS)`。

### 真实业务结果：必填属性缺失会落到草稿箱

妙手复制历史行原文（2026-11-12 01:40）：

> 「保质期,生产企业名称」未填写，导致复制失败，系统自动放至草稿箱
> 草稿箱 · 未提审

搬家配置里设的是「放入仓库」，但抖店类目要求的必填属性没填时，
妙手会按配置里那条「因必填属性未填写导致复制失败则自动放至草稿箱」处理。
这再次印证：**抖店类目特有属性 1688 源头没有，妙手也变不出来，只能人工补。**

---

## 第十二轮实抓（2026-11-12 晚）：会话掉线、复制历史行的隐藏字段、一个转义坑

### 🔴 会话过期时，抖店与妙手都跳同一个登录页

浏览器会话过期后实测：

| 入口 | 落点 |
|---|---|
| `https://v2-dd.chengji-inc.com/selection/opportunity_product` | `https://fxg.jinritemai.com/login/common?next=https%3A%2F%2Ffuwu.jinritemai.com%2Fauthorize%3Fservice_id%3D234%26from%3Disv.authorize%26loginType%3D1` |
| `https://v2-dd.chengji-inc.com/move/move_history` | 同上 |
| `https://fxg.jinritemai.com/ffa/g/list` | `https://fxg.jinritemai.com/login/common?extra=%7B%22target_url%22...%7D` |

登录页正文里有两句只会出现在登录页的文案：**「收不到验证码」「手机号停用或忘记」**，
正文长度约 377 字符。

适配器若不先判登录态，只会在几分钟后报「当前页面不是预期的XX页」，
**把掉线这个根因埋掉**。所以新增 `DropshipPages.check_session()`：
判据是「URL 路径以 `/login` 开头」或「正文含上面两句登录页专属文案」，
且域名属于抖店/服务市场。掉线只能由人重新登录，程序不代登录、
**不在登录页上重放任何写操作**。

### 复制历史行里还有三个以前采到却没用的字段

真实行文（商品 3853482303460343870）：

```
发布类目：家清纸品>除臭用品>空气清新/净化/芳香剂
1688分销
明丞生物科技有限公司（明丞生物科技有限公司）
源ID：922368518409
"保质期,生产企业名称"未填写，导致复制失败，系统自动放至草稿箱
商品ID：3853482303460343870
草稿箱
未提审
```

- `发布类目：` 后面是**完整类目路径**；
- 渠道行（`1688分销`/`阿里巴巴`/…）的下一行是 `供应商名（店铺名）`；
- 状态词是抖店官方用词：`草稿箱`、`未提审`、`审核通过`。

这三样以前就在 `row_text` 里，只是没被解析。现在进人工补值清单，
其中供应商名**只作参考线索**——抖店要的是「生产企业名称」，
供应商可能是贸易商，不能直接照抄。

### 🔴 Node 验证器抓到的转义坑（第二次了）

新写的登录态判定里用了正则 `/\/login(\/|\?|$)/`。Python 源码里写两个反斜杠，
浏览器拿到的是一个（合法）；但 `tests/verify_adapter_js.py` 取的是**源码原文**，
Node 看到两个反斜杠 → `Invalid regular expression flags`，整段 JS 直接语法错误。

结论不变：**适配器里的 JS 不要依赖 Python 字符串的转义**。
这次直接改成零反斜杠写法（`pathname.startsWith('/login')` + 登录页专属文案），
更短也更不容易错。

> 顺带记一笔：验证器取源码原文、浏览器拿的是 Python 解释后的字符串，
> 两者只在含反斜杠时才会分叉。所以**含反斜杠的 JS 一律不要写**。

## 第十三轮实抓（2026-11-12 晚，登录恢复后）

上一轮被登录卡住的三项全部做完。结论与证据如下。

### ① 抖店草稿箱是**独立页**，不是商品管理页的 tab

之前扫遍 tab、导航、`<a href>` 都没找到草稿箱入口，因为它**根本不在这些地方**：
商品管理页的 tab 只有 `全部 / 售卖中 / 已售罄 / 已下架 / 已封禁(0) / 审核中(0) /
审核驳回(1) / 审核通过`——**没有草稿箱 tab**。页面副标题里那句「……草稿箱总商品」
只是文案，不是入口。

真正的入口是 tab 条右侧一组**文字链接**（不是 button、不是 `<a>`）：

```html
<div class="style_rightLink__zG3iJ">
  <span class="style_textLinkNew__ziNsA">编辑记录</span>
  <span class="style_textLinkNew__ziNsA">草稿箱</span>
  <span class="style_textLinkNew__ziNsA">回收站</span>
</div>
```

点它之后**同页跳到** `https://fxg.jinritemai.com/ffa/g/draft`（独立路由）。
这组链接在视口外（x≈1068，视口宽 902），必须先 `scrollIntoView` 才能点到。

草稿箱页结构与商品管理页**完全不同**：

| | 商品管理页 | 草稿箱页 |
|---|---|---|
| 路由 | `/ffa/g/list` | `/ffa/g/draft` |
| 表头 | 商品 / 价格 / 状态 / 操作 | **商品信息 / 商品状态 / 创建时间 / 操作** |
| 状态词位置 | **时间戳之后** | **ID 之后、日期之前** |
| ID 写法 | `ID：3850071994200621373`（全角冒号） | `ID:3853482303460343870`（半角冒号） |
| 空结果 | 无 | `暂无数据` |

### ② 按 ID 过滤的正确参数是 `product_id`（不是 `searchText`）

T-008 当年用的是 `?searchText=`，所以永远「共 0 条」——**查询方式错了，不是商品不存在**。

```
/ffa/g/list?product_id=3850071994200621373&sov_goodsType=0&tab=all  → 共 1 件，行内含「售卖中」
/ffa/g/draft?product_id=3853482303460343870                       → 共 1 件，行内含「待提交」
/ffa/g/draft?product_id=9999999999999999999                       → 暂无数据
```

命中时页面会**自动把 ID 填进搜索框**（placeholder 与商品管理页相同：
「请输入商品名称/商品ID/商家编码，多条可用逗号隔开」）。

### ③ 两页互斥：审核状态的权威读法

| 商品 ID | 妙手复制历史 | 抖店商品管理页 | 抖店草稿箱 |
|---|---|---|---|
| 3853482303460343870 | 草稿箱 / 未提审 | **暂无数据** | **待提交** |
| 3850071781591351757 | 已下架 / 审核不通过 | **审核驳回** | 暂无数据 |
| 3850071994200621373 | 上架中 / 审核通过 | **售卖中** | 暂无数据 |
| 3850072900438720563 | 已下架 / 审核通过 | **已下架** | 暂无数据 |
| 3848308435624001949 | 已下架 / 未提审 | 已下架 | 暂无数据 |
| 3767496214443065490 | （无状态词）销量 175 | 售卖中 | 暂无数据 |

三条硬结论：

1. **草稿商品不在商品管理页**，只可能在草稿箱页。
2. **两套词汇**要对应着读：妙手「审核不通过」＝抖店「审核驳回」；妙手「上架中」＝抖店「售卖中」；
   妙手「未提审」＝抖店「待提交」（且只在草稿箱里能读到）。
3. **状态词缺失就是缺失**。58 条真实历史里有 14 条在抖店侧根本没有状态列
   （2026-10 批次的老记录），实测这些商品在抖店商品管理页里是有状态的——
   说明**不能拿妙手侧的状态缺失反推抖店侧状态**。

### ④ 机会商品「立即铺货」的落地页契约（旧结论被推翻）

旧注释写「这条路径**不能**独立证明商品身份：卡片上没有任何 1688 offer ID 字段」——
**卡片层确实没有，但点击之后有**，而且有两条独立通道：

**通道一（DOM）**：点「立即铺货」后弹出**同页抽屉**（URL 不变，仍是
`/selection/opportunity_product`）。抽屉里的来源商品行带链接：

```html
<a href="http://detail.1688.com/offer/671243686759.html?amug_web_biz=fwmkt&...">
```

实测时序：「下一步: 开始复制」约 **2.5s** 出现，1688 offer 链接约 **4.3s** 出现。

**通道二（网络）**：前端同时提交
`POST /api/v2/move/batch/fetchDetailUrlInfo`，请求体形如

```
detailUrls=https%3A%2F%2Fdetail.1688.com%2Foffer%2F671243686759.html%3F...
&copyType=ddClue&clickType=copyProduct&firstUseDs=1
```

响应 `productList["671243686759"]` 带 `source:1688` / `title` / `productImgUrls` /
`stockNum` 等；同批还有 `POST /api/v2/move/batch/dsCenterUserReviewStat`
请求体 `copyType=ddClue&clickType=copyProduct`。
`copyType=ddClue` 就是「抖音商机商品」这条来源的标记。

**旧实现为什么一直失败**：`click_single_opportunity` 在 `.click()` 之后**同步**检查
「商品列表」和「下一步: 开始复制」，而抽屉是异步渲染的 → 必然报
`click_result_not_confirmed`。现在改成轮询等待，最多 40 轮 × 250ms。

**点击「立即铺货」本身不写抖店数据**：实测点完立刻回抖店草稿箱，仍是原来那 1 件
（`3853482303460343870`），没有新增。真正写数据在「下一步: 开始复制」。

### ⑤ 复制历史：读一屏只能拿到 20/58

这页是 **vue-recycle-scroller 虚拟滚动 + 分页器**（每页 20 条，共 3 页）。
一次只挂载 19~20 行 DOM，**读一屏当全量是错的**。

- 滚动容器是 `div.content-main`（`overflow-y:auto`），**不是** window。
- 虚拟列表在容器滚动**过程中**才换行，一次性滚到底只能拿到最后一段，中间会漏。
- 正确采法：点 `.el-pager > li:nth-child(N)` 翻页 → 每页从 0 开始按 **150px 步长**
  细滚并逐步累计 → 再回到顶部补一次。
- 去重键用 `源ID + 商品ID + 时间`：同一商品被复制两次是两条记录（时间不同），
  而虚拟滚动重渲染会短暂挂载同一行两次。

实测：`共 58 条` → 采集 `collected=58`、`complete=true`。

### ⑥ 行文法（全量 58 条归纳）

```
{标题}
发布类目：{完整类目路径}
{copyType}          1688分销（57 条）/ 翻新复制（1 条）
{供应商}            「名称（店铺名）」（51 条）或纯名称（8 条）
源ID： {src}        翻新复制那行是「新源ID：」
{模板}              默认配置
{妙手审核状态}       审核通过 / 审核不通过 / 关联失败
{复制状态}           已成功复制 / 复制失败 / 跳过复制
[失败原因原文]        "保质期,生产企业名称"未填写，导致复制失败，系统自动放至草稿箱
{时间}
商品ID： {pid}
[抖店商品状态]       草稿箱 / 已下架 / 上架中
[抖店审核状态]       未提审 / 审核通过 / 审核不通过
销量：{n}
[有曝光]
商品快速编辑 去抖店编辑 更多
```

**三列状态词必须按位置分开**：商品ID 之后是抖店侧，商品ID 之前是妙手侧。
混在一起统计会得出「未提审+审核通过+已下架」这种三词组合，无从判断谁是谁。

---

## 第十四轮实抓（2026-11-12 深夜）：类目属性控件三形态 + 状态分类 tab + 发布后时间线

### ① 类目属性的三种控件形态

抖店类目必填属性不止「文本」「单选/多选」两种，还有第三种——**数值输入 + 单位下拉的复合控件**。
实测 `保质期`（类目 `家清纸品>除臭用品>空气清新/净化/芳香剂`）：

```
div.styles_measureValue__BknXC
  └ div.styles_measureContainer__AF_AJ
      └ div.styles_measureTemplate__AfVoo
          ├ input.ecom-g-input.styles_value__QXqGx   type=text  （数值）
          └ div.ecom-g-select.ecom-g-select-single    （单位下拉）
```

- 单位候选实测：`天 / 月 / 年 / 个月`（默认预选 `天`）。
- 🔴 **平台会预选单位**，所以「单位标签存在」**不等于**该属性已填。判据必须是
  「**数值非空**」。旧 missing 启发式把预选的「天」当成值 → 漏判；平台自己的必填进度
  50%（两个必填项缺一）正好证明平台也认为它没填完。
- 单位下拉用 **portal** 渲染在 body 下，class 相同但不能按 class 定位。精确定位方式：
  单位 select 内的 combobox input 带 `aria-controls="rc_select_<N>_list"` → 用这个 id
  找 listbox。新增 op `attribute_unit_options` 读**真实候选**；写单位前必须在候选里
  校验存在，否则拒绝写。
- 读回值形态：`number_value` + `unit_value` 组合还原成 `12个月`。

### ② 商品管理页的状态分类 tab（可直接点开核对分类）

tab 的 DOM id 固定，可直接 `document.querySelector('#<id>').click()`：

| tab id | 文案 | 列结构 |
|---|---|---|
| `rc-tabs-0-tab-all` | 全部 | 商品信息/价格/总库存/总销量/质量分/**创建时间**/操作 |
| `rc-tabs-0-tab-onSale` | 售卖中 | 同上 |
| `rc-tabs-0-tab-sellOut` | 已售罄 | 同上 |
| `rc-tabs-0-tab-offline` | 已下架 | 同上，但时间列是「**下架时间降序**」 |
| `rc-tabs-0-tab-forbidden` | 已封禁 (n) | 同上 |
| `rc-tabs-0-tab-releaseRecord_in_progress` | 审核中 (n) | 商品信息/**审核状态**/**送审时间**/操作 |
| `rc-tabs-0-tab-releaseRecord_fail` | 审核驳回 (n) | 商品信息/审核状态/**驳回原因**/**送审时间**/**驳回时间**/操作 |
| `rc-tabs-0-tab-releaseRecord_success` | 审核通过 | 商品信息/审核状态/**送审时间**/**通过时间** |

- 点 tab 会**丢掉 URL 里的 `product_id` 过滤**（URL 变成 `?sov_goodsType=0&tab=...`），
  所以核对分类时看到的是该分类**全量**行，要按商品 ID 自己筛。
- 「全部」tab 的时间列是**创建时间**（妙手建品时间），不是状态变更时间；**状态时间线
  要去「审核通过」tab 看送审/通过时间**。

### ③ 发布后商品的真实状态（本项目商品的共同形态）

实测商品 `3853482303460343870`（2026-11-12）：

| 环节 | 平台记录 |
|---|---|
| 妙手建品 | 创建时间 2026/11/12 01:41:35，落在草稿箱「待提交」 |
| 点「发布商品」 | **送审时间 2026/11/12 16:40:39**，页面出现原文「商品提交成功」 |
| 平台审核 | **审核通过，通过时间 2026/11/12 16:41:03** |
| 当前行状态 | 「已下架」，「查看原因」＝「**商家自主下架**」，操作区有「上架」 |

- 同项目另两件（`3853454064050373417`、`3848315275342643596`）形态完全一致：
  **通过时间 == 下架时间 == 商家自主下架**。所以「发布商品」这条路径的终态是
  「**审核通过但未上架**」。
- 🔴 **「已下架」≠「被平台驳回」**：查看原因给的就是「商家自主下架」；真正的驳回在
  `rc-tabs-0-tab-releaseRecord_fail` 分类里（实测那件是 2026/10/28 的别的商品，
  驳回原因「低价SKU作弊」）。**不要因为行里写着「已下架」就推断成审核不通过。**
- 提交成功的判定顺序（从强到弱）：① 编辑页出现「商品提交成功」原文；② 商品**离开草稿箱**
  （`product_id_not_in_draft`）；③ 「审核通过」分类里出现它并带送审/通过时间。
  三条都要查，不能只看其中一条。

### ④ Ego 通道的两个恢复动作（都在原空间内）

- 任务空间 ended（`listTaskSpaces()` 里 `ownership: "user"`）→ 浏览器命令全部报
  “This task space is no longer assigned to the agent … takeOverTaskSpace() cannot
  resume an ended task”。用户明确让继续后，按 ego-browser 文档用
  `claimTaskSpace(<id>)` 接管**原空间**（`takeOverTaskSpace()` 对 ended 空间无效）。
- 某个 Page 的渲染进程卡死（`page.info()` 一直 CDP 超时、`page.close()` 报
  “did not close within 2000ms”）→ 用 `page.cdp('Target.getTargets')` 按 URL 找到
  `targetId`，再 `page.cdp('Target.closeTarget',{targetId})` 在浏览器层强制关闭；
  之后把死页从 `state.json` 的 `pages` 路由表里摘掉，runtime 会另开新页。
  **不要为此新建任务空间。**

---

## 第十五轮实抓（2026-11-13 凌晨）：妙手可见性依赖真实布局 + 抖店两处「读不全」的机制辨析

这一轮是**第一次真跑 `batch rebaseline`**，暴露的四个事实里有三个会直接决定「能不能读到数据」，
而且报错文案都会把人带偏。

### ① Ego 把每个 Page 钉死在任务的固定视口，页面不会自己适配

`ego_runtime.mjs` 每次操作前都会把每个 Page 覆盖成 `state.viewport`（注释写的是
"keep the task's measured viewport fixed across Pages"）。实测本次任务空间是 **904×788**，
而妙手 `quick_edit` 的「查询」按钮 `getBoundingClientRect().left = 1017`。

- `miaoshou_dom.js` 的 `visible()` 判据里有一条 `r.left >= innerWidth → false`
  → **控件真实存在、样式正常、`offsetParent` 非空，却被判成不可见**。
- 下游报错是 `妙手当前可见控件或商品行未唯一定位；未点击`（`page_timeout`），
  读起来像「页面改版」或「登录态掉了」，**实际根因是视口太窄**。
- 修法：把任务空间 `state.viewport` 调到 `1440×900`（`state.json` 的 `viewport`）。
  这不是改代码，是调任务参数。

排查时注意：`offsetParent !== null` 在后台标签页/窄视口下**仍然为真**，
不能拿它当可见性证据；要看 `getBoundingClientRect().left < innerWidth`。

### ② 全屏 `op.jinritemai.com` 组件 iframe 会拦截整页点击

实测妙手页里挂着一个：

```
<iframe class="__op__bixi_524 _o_p_b svelte-1hj8tfa _o_"
        src="https://op.jinritemai.com/open/component/common?appId=7641889070456782908&cId=524">
```

- 尺寸 **1440×900（正好等于视口）**、`z-index: 10000`、`pointer-events: auto`、`opacity: 1`
- 后果：`document.elementFromPoint(x, y)` **永远返回这个 iframe**，
  所有控件的 `actionable` 判定都是 false → 点击、`_mark_control` 全废。
- 它不是页面内容，也不会随 SPA 路由切换自动消失；**重新加载页面即消失**。
- 排查特征：`elementFromPoint` 返回 `IFRAME.__op__bixi_*` 而不是目标元素本身或其子节点。

### ③ 抖店「价格库存」SKU 表格：真实滚动容器是 `.ecom-g-table-tbody-virtual-holder`（已修复）

商品 `3848316916011762046`（磁吸折叠扫把簸箕）：

| 来源 | SKU 数 |
|---|---|
| 官方 API（`data.model.sku_detail.value`） | **24**，全部 `sku_status: true`，24 个不同 `spec_detail_ids` |
| 页面 DOM 同时挂载的 `tr[data-row-key]` | **6–7** 行（视口相关） |
| 修复前逐 SKU 读到的商家编码 | **6** |
| 修复后读到的商家编码 | **24**（`official_sku_codes` 实测，见下） |

🔴 **先记住一个反例，别重犯**：曾经把这个现象写成「平台最多渲染 7 行」。错的。同一套采集代码在
`3850072900438720563`（**25** 个 SKU）和 `3850071893537325881`（**32** 个 SKU）上完整读到了全部
商家编码——页面能露出 7 行以上。

**真正的容器（2026-11-14 实抓，可重放）**。表格是虚拟列表，行在
`div.ecom-g-table-tbody-virtual-holder` 里：

```
.ecom-g-table-tbody-virtual-holder   scrollHeight 2707 / clientHeight 523   ← 真滚动容器
  └─ 内层 div（transform 只在滚动时变化）
       └─ tr[data-row-key]（只挂载可见的 6–7 行）
```

`2707 ÷ 24 ≈ 113px/行`——**holder 自己知道有 24 行**，只是只挂载可见的那几行。

实测对照（同一页面，逐步改 `scrollTop` 后读行键）：

| 操作 | 行键 |
|---|---|
| 初始 | 107–112 |
| 滚外层 `#goodsEditScrollContainer` +300 / +600 / … / +2400 | **107–112 不变** |
| `holder.scrollTop = 300` | 109–115 |
| `holder.scrollTop = 600` | 112–118 |
| `holder.scrollTop = 900` | 114–120 |
| `holder.scrollTop = 1200` | 117–123 |

→ **滚外层容器完全无用**（只是把整块内容移进视野），**必须滚 holder**。这解释了为什么之前
「滚到底 + 加高视口 + 点全屏」全都读不到：三个动作动的都不是这个 holder。

**代码修复**（`official_sku_code_dom.js` + `official_sku_codes.py`）：

- JS 新增 `op = 'scroll_rows'`：`holder.scrollTop += clientHeight / 2`（半页步进保证相邻视图重叠），
  到底后回到 0 继续，避免漏掉上方的行；`scrolled` 只在真的移动时为真。
- Python 的操作选择从「有占位行才滚，否则只读」改成三分支：

```python
if not result['ready']:
    operation = 'read'
elif pending:
    operation = 'scroll_pending'      # 老路径：滚动占位行
else:
    operation = 'scroll_rows'         # 新路径：无占位行时滚虚拟 holder
```

- 校验强度**未降低**：每行仍要 16 位 SKU、唯一可见 input、`input_count == 1`，跨轮冲突拒绝，
  空字符串只在「观察到真实 input」时才算空。

**验证**：把改后的适配器 JS 原样注入实页循环调用，`mounted` 一直是 6–7 行，累计到
**24/24** 个 SKU（`3385336720213797` … `3385336720219685`），全部 `observed=True`。

**结论**：`official_sku_code_incomplete` 的直接原因是采集策略在这类页面上不滚动，而不是读取预算、
也不是平台拒绝渲染。真正的行滚动容器尚未定位（上面排除的是外层容器，虚拟行的 scroller 是别的
节点）。下一步是在实页找到它并在无占位行时也尝试滚动，**不要再用「加预算」的思路**；在找到之前，
这两件商品应如实记为「读取策略未覆盖的页面状态」，**不能写成平台硬上限**。

### ④ 抖店详情槽位：懒加载图片要「逐张滚进视野」才会加载（已修复）

商品 `3850072398019821856`（狗狗玩具，商详 37 张）：

```
detail_declared = 37    detail_cards = 37    detail_slots = 28    loaded = 28
detail_status  = ambiguous
```

**真因（2026-11-14 实抓）**：37 个缩略卡片都在 DOM 里，但**后 9 张的 `<img>` 还停在 1×1 的
占位 GIF 上**（`src=data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7`，
`loading="lazy"`，`naturalWidth=1`）。真实地址由页面在卡片进入视口时才写入，所以：

- 卡片 0–27（前 28 张）已加载 → `detail_slots = 28`；
- 卡片 28–36 从未进入视口 → 永远不加载；
- `declared(37) ≠ slots(28)` → `detail_status = ambiguous` → `detail_source_not_ready`。

**关键实测**：对**第一张未加载的卡片**做一次 `scrollIntoView({block:'center'})`，
`detail_slots` **28 → 37，一次就全部加载**，`detail_status` 转 `ready`。

- 只把整个「商品详情」块 `scrollIntoView` **不管用**（那把块的中心移进视野，只覆盖前 28 张）。
- 块内部**没有**自己的滚动容器（没有 `overflow: auto` 的后代，也没有虚拟 holder），
  所以「滚块内某个容器」这条路不存在。

**代码修复**：

- `dom.js` 的 `op === 'scroll'`：当 `kind === 'details'` 时，不再滚整块，而是找**第一张未加载的
  卡片**滚进视野；没有未加载卡片才退回滚整块。返回值新增 `unloaded` 标记。
- `editor.py` 的 `wait_details`：轮询时，只要快照未 ready 就发一次 nudge（滚下一条未加载卡片），
  每轮加载一张，最多 `秒数/0.4` 轮。校验强度不变——仍然要求 `declared == slots == cards` 全部相等。

**验证**：改后重跑该商品，`details 37/37`、`detail_status=ready`、`details_equal=true`，
`SKU PASS`（这件有 **56 个 SKU**，也一并读全）。它现在卡在**另一件**事上：
`writer_detail_source_collision` —— 前 4 张详情存在重复原图，妙手按图片查找替换会同时改动多处，
写入器不支持逐位置替换。这是**写入契约的限制，不是读取限制**。


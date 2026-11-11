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

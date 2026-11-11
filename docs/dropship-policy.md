# 铺货策略：类目预检、人工补值清单、终态定义

对应代码：`src/doudian_auto/dropship_policy.py`、`dropship.py::verify_target_readback`。

## 为什么加这三层

端到端闭环真跑通之后，剩下的阻塞不是浏览器自动化，而是三个设计错位：

| 现象 | 根因 |
|---|---|
| 商品落草稿箱、未提审 | 抖店类目必填属性（保质期/生产企业名称）在 1688 属性区不存在，妙手搬不过来 |
| `verified` 终态永远到不了 | 它要求的「SKU 总数」「审核状态」在官方编辑页**结构上没有**，不是暂时没抓到 |
| 规格名对不上 | 妙手会改写规格名，按名字比对是错的抽象 |

所以不再加页面适配器，改这三层。

## 1. 类目预检（铺货前拦截）

`precheck_category(title=..., category=...)` 返回风险结论，`require_precheck_allowed()` 在
`_stage_copy` 最前面拦截高风险任务。

- **精确依据**：`KNOWN_CATEGORY_ATTRIBUTES` 记录实测类目 → 必填属性。当前一条：
  `空气清新/净化/芳香剂` → `保质期`、`生产企业名称`
  （证据：2026-11-12 复制历史行原文）。
- **启发式**：`RISK_KEYWORDS` 从标题提示风险，但 `basis` 明确标成
  `keyword_heuristic`——铺货前拿不到抖店最终类目，这**只是预警，不是类目证据**。
- 命中高风险默认 `block`，转人工；需要继续必须显式 `--allow-risk`。
- 命中时**不创建商品**，因此不会往草稿箱里堆提不了审的垃圾。

真跑验证：

```
$ doudian-auto dropship prepare ... --source-title "酒店生物酶除味剂空气清新..."
→ risk: high | basis: keyword_heuristic | action: block
→ matched_keywords: ['除味剂', '空气清新']

$ doudian-auto dropship apply <task> --apply
→ code: dropship_category_risk（未点复制，未创建商品）
```

## 2. 人工补值清单（复制后交付）

复制历史行里的失败原因有固定形态：

```
「保质期,生产企业名称」未填写，导致复制失败，系统自动放至草稿箱
```

`extract_missing_attributes()` 解析出属性名；`build_manual_attribute_list()` 写成
`manual-attributes.json` 落在任务目录，**值一律留 null、来源标「人工填写」**——
不替人猜值，这是反复验证过的边界。

真实产物：

```json
{
  "target_product_id": "3853482303460343870",
  "missing_count": 2,
  "items": [
    {"attribute": "保质期", "value": null, "source": "人工填写", "is_douyin_only": true},
    {"attribute": "生产企业名称", "value": null, "source": "人工填写", "is_douyin_only": true}
  ],
  "instruction": "在抖店商品编辑页补以上属性后提审……"
}
```

`_readback_only` 在发现新增历史行时自动生成这份清单并附在结果里。

## 3. 终态改名：`verified` → `copy_confirmed`

旧 `verified` 要三个证据，其中两个在官方编辑页根本不存在：

| 证据 | 可得性 |
|---|---|
| 商品 ID 与复制历史一致 | ✅ 可得 |
| 官方页能打开、读到 SKU 行 | ✅ 可得 |
| 价格填写进度 100% | ✅ 可得 |
| 页面 SKU 总数计数 | ❌ 结构上没有 |
| 商品审核状态 | ❌ 在商品列表页，不在编辑页 |
| 规格名与来源一致 | ❌ 妙手改写是常态 |

拿不可得的证据当阻断条件，终态就永远不可达——上一轮停在
`verification_pending` 一整轮正是这个原因。

新终态 `copy_confirmed` **只声明能证明的事**，并新增一条可自动判定的强证据：

> **价格公式一致性** — 每个 SKU 的 `售价 − (源价 × 倍数 + 加价)` 差额相同且非负。
> 那个共同差额就是运费。

妙手改写规格名后按名字匹配不上，所以 `_check_price_formula()` 用**价格排序做位置对应**
（源价与售价都单调，最小的对最小的）。真实数据：

| 来源规格 | 源价 | 公式价 | 官方售价 | 差额 |
|---|---|---|---|---|
| 生物酶除臭剂【2500ml】送喷壶 | 25.8 | 82.40 | 85.88 | 3.48 |
| 生物酶除臭剂【5000ml】送喷壶 | 43.8 | 136.40 | 139.88 | 3.48 |

两个差额一致 → 公式确实被执行了。

报告分两栏，各自如实：`verified_aspects`（4 条）与 `unverified_aspects`（3 条）。
后者不阻断终态，但明确交人工。真实跑出的结果：

```
stage: copy_confirmed
price_check.shipping_delta: 3.48
verified_aspects: 4
unverified_aspects:
  - 官方编辑页无独立 SKU 总数计数（结构上不存在）
  - 官方编辑页无商品审核状态（需到商品列表页人工确认）
  - 妙手改写了规格名：来源 生物酶除臭剂【2500ml】送喷壶… → 官方 2500ml（生物酶除臭剂）…
```

## 兼容性

`WRITE_FORBIDDEN_STAGES` 与 `record_copy_observation` 仍接受旧 `verified` 状态
（历史任务不会失效），新任务一律写 `copy_confirmed`。终态不可回退。

## 边界

- 类目白名单目前只有**一条实测类目**，靠标题关键词兜底。扩展应基于新的真实观测，
  不要凭类目名猜必填属性。
- `copy_confirmed` 不表示商品可售、已审核或已上架。它只表示「复制动作产生了这个
  商品，且定价符合任务公式」。
- 人工补值清单只列属性名，不提供值；值必须由人给。

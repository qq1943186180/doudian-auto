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

---

## 2026-11-12 晚更新：三条被实测推翻/加固的策略

### ① 类目白名单**不能**按标题关键词扩

上一版留了个口子：「类目白名单只有一条实测类目，扩展应基于新观测」。
这一轮真去看了队列里的失败样本，发现**按关键词扩是错的**：

| 商品标题 | 实际缺的属性 |
|---|---|
| 浴室免打孔不锈钢吹风筒收纳架免手拿现代简约风卫浴置物架卫生间 | **安装方式** |
| 轻奢风浴室吸盘置物架卫生间免打孔壁挂塑料化妆品饰品洗手台杂物 | **尺寸**（安装方式反而被填上了） |

同一个「免打孔/壁挂/吸盘」，一件缺安装方式、另一件安装方式被填上却缺尺寸。
说明**属性集合由抖店类目决定**，而铺货前拿不到最终类目（妙手抓取后才匹配）。

所以这一轮**没有**扩白名单，而是把结论写进 `dropship_policy.OBSERVED_MISSING_ATTRIBUTES`：
只记「本店观测到缺过哪些属性」，供人工分诊用，**不用于自动推断或拦截**。

### ② 人工待办报告：加了原因分类和属性统计

`build_manual_queue_report()` 现在除了属性级清单，还给出 43 件 blocked 的真实分布：

| 原因类 | 件数 | 该谁处理 |
|---|---|---|
| `needs_rebaseline` | 14 | 程序可重跑 |
| `missing_required_attributes` | 8 | 只能人工给值 |
| `image_slots_insufficient` | 6 | 只能人工给素材 |
| `visual_quality_failed` | 5 | 只能人工给素材 |
| `draft_or_rejected` | 4 | 只能人工决策 |
| `missing_real_parameters` | 2 | 只能人工给值 |
| `sku_code_incomplete` | 2 | 程序可重跑 |
| `product_deleted` | 1 | 已结束 |
| `detail_source_collision` | 1 | 只能人工决策 |

同时统计真实观测到的缺失属性：`安装方式 6`、`尺寸 3`、`硬度 3`、
`适配基面类型 2`、`承重 1`、`材质 1`、`适用年龄 1`、`适用作物生长阶段 1`。

口径修正：旧版这份报告是 **23 项**，其中 5 项是
「（原文未列出属性名，需查看 last_error）」这种**占位名**——
它们其实不是属性缺失（例如 `doudian_draft_or_rejected` 的 `missing_fields=[]`）。
现在只列**真能解析出属性名**的，实际 **18 项**。少的那 5 项不是漏了，是本来就该去掉。

### ③ 规格名：从「永远未验证」改成「数量标记可判定」

旧判据是「规格名集合相等」，在真实页面上**几乎从不成立**：
妙手会改写展示名（两次真实铺货都改写了）。所以这一项长期挂在 `unverified_aspects`，
成了永久噪音。

改成问一个可判定的问题：**来源规格里的数量标记还在不在官方规格名里**。

| 来源规格名 | 官方规格名 | 数量标记 | 结果 |
|---|---|---|---|
| `4个装` | `极氪车门限位器-4个装` | `4个装` | ✓ |
| `生物酶除臭剂【2500ml】送喷壶` | `2500ml（生物酶除臭剂）` | `2500ml` | ✓ |

三态：`matched`（进 `verified_aspects`）/ `partial`（规格名没有数量，如「红色」，
如实说无法核对）/ `mismatch`（标记对不上，如实报未通过）。
后两种**不阻断** `copy_confirmed`——定价公式才是强证据。

### ④ 会话掉线闸门（新增）

浏览器会话过期时页面会跳登录页，继续跑只会报「当前页面不是预期的XX页」，
把根因埋掉。现在 `_advance` / `_stage_settings` / `_stage_copy` / `_readback_only`
在每个导航后都先 `check_session()`，掉线立刻抛 `dropship_login_required`，
并说明「请人工重新登录，程序不会代登录，也不会重放写操作」。

只读自检命令：`dropship session-check`（加 `--navigate` 会先进妙手页再查）。

### ⑤ 审核状态：权威来源是抖店官方两页，不是编辑页、也不是妙手

上一轮写「审核状态在官方编辑页结构上不存在，需到商品列表页人工确认」——
前半句对，后半句**做错了**：商品列表页其实读得到，只是当时没查对地方。

现在的规矩：

- **权威来源**：抖店商品管理页 `/ffa/g/list?product_id=<ID>` 与草稿箱页
  `/ffa/g/draft?product_id=<ID>`，**两页互斥**。已提交商品只在前者，
  草稿商品只在后者（草稿箱状态词是「待提交」）。
- **词汇要对应**：妙手「审核不通过」＝抖店「审核驳回」；妙手「上架中」＝抖店「售卖中」；
  妙手「未提审」＝抖店「待提交」。
- **查不到就说查不到**。两页都没有这个商品 ID 时，只能报「无法确认审核状态」，
  **不能**写成「未提审」——那是妙手侧用词，含义是「从没提交过审核」，
  与「商品不存在」「商品已被删」都不是一回事。

实测 6 个商品的双向对照见 `docs/dropship-page-contracts.md` 第十三轮表格。

### ⑥ 机会商品路径**能**建立精确来源身份（旧结论被推翻）

上一轮据卡片 DOM 断定「机会路径不能独立证明商品身份，只能靠标题检索人工核实」。
这个结论**只对卡片层成立**，对整条路径**不成立**：点「立即铺货」之后抽屉里会出现
`http://detail.1688.com/offer/<ID>.html` 链接，同时前端会提交
`fetchDetailUrlInfo`（`copyType=ddClue&clickType=copyProduct`），请求体里就是同一个
`detailUrls`，响应 `productList[<ID>]` 还带 `source:1688` 与标题/图片/库存。

所以机会路径的**来源身份是精确的 offer ID**，不必靠标题去 1688 人工检索。
两条通道互相独立，可以互证。

失败模式也定下来了：抽屉开了却拿不到 offer 链接时，
适配器返回 `layout_changed / offer_identity_not_found`，**不返回 ok**——
宁可停，也不能让调用方拿「标题子串」当身份去铺货。

### ⑦ 复制历史必须采全量，读一屏当全量是错的

`read_history_product_id` 那种「按来源筛选后读当页」的做法只在**基线比对**时成立
（基线要的是「有没有新增行」）。但**做统计、做人工待办汇总**必须全量：
58 条历史一次只挂载 19~20 行 DOM，读一屏就是 20/58。

采集口径（`collect_history_rows_all_pages`）：

- 翻页：`.el-pager > li:nth-child(N)`，等 `li.is-active` 变成 N 才算切过去。
- 页内滚动：`div.content-main` 容器按 150px 步长细滚并**逐步累计**；
  一次性滚到底会漏中间段。
- 去重键：源ID + 商品ID + 时间。
- **完整性判据**：采到的条数必须 ≥ 分页器写的「共 N 条」，否则如实报 `complete=false`，
  不把「采到多少」当「一共多少」。

全量 58 条的真实分布（2026-11-12 实读）：

| 维度 | 分布 |
|---|---|
| 类目 | 47 个不同类目路径；前三：`收纳筐/收纳篮`(3)、`厨房储物架`(3)、`挂钩/粘钩`(3) |
| 复制类型 | 1688分销 58 / 翻新复制 1 |
| 复制状态 | 已成功复制 59（58 条记录里 1 条同时带失败原因） |
| 抖店商品状态 | 已下架 30 / 上架中 14 / 草稿箱 1 / **无状态列 14** |
| 抖店审核状态 | 审核通过 23 / 未提审 21 / 审核不通过 1 / **无 14** |
| 妙手侧审核 | 审核通过 34 / 无 25 |
| 供应商 | 有括号形态 51 / **纯名称形态 8**（旧解析器会丢这 8 条） |
| 失败原因 | 仅 1 条：「保质期,生产企业名称」未填写 → 自动放至草稿箱 |

### ⑧ 行解析器的四处修正（都有真实反例）

| 缺陷 | 真实反例 | 后果 |
|---|---|---|
| 类目正则 `([^\n\r]+)` 贪婪 | 单行折叠形态的历史行 | 类目变成整行（含供应商/源ID/时间/状态），人工清单里的类目字段全是垃圾 |
| 供应商只认「名称（店铺名）」 | `瑞安市激濠五金商行`、`孕产批发` | 58 条里丢 8 条的来源供应商 |
| 源ID 只认 `源ID：` | `翻新复制` 行的 `新源ID：` | 丢 1 条记录的来源 ID |
| 状态词全表扫 | 妙手侧「审核通过」与抖店侧「审核通过」同形 | 统计出「未提审+审核通过+已下架」三词组合，无从判断谁是谁 |

现在：类目止于下一行或复制类型标记；供应商认带括号与纯名称两种形态；
源ID 认 `源ID：`/`新源ID：`；三列状态按**商品ID 的位置**分开
（`platform_states` / `platform_audit_state` / `miaoshou_audit_state`）。

### ⑨ 类目属性控件有三种形态，第三种会骗过 missing 判据

抖店类目属性除「纯文本」「纯单选/多选」外，还有**「数值输入 + 单位下拉」复合控件**
（实测 `保质期`）。平台**会预选单位**，所以：

- 「单位标签存在」**不等于**该属性已填。判据必须是「**数值非空**」。
- 旧启发式把预选单位当值 → 漏判（真实缺陷：平台自己的必填进度 50% 与程序判断矛盾）。
- 单位候选必须**从真实下拉里读出来再校验**，不能凭猜测写单位；单位下拉是 portal 渲染，
  靠 combobox 的 `aria-controls` 精确定位 listbox id。
- 写完必须读回组合值（数值+单位）并与目标**完全相等**，不等即失败关闭。

### ⑩ 锁与删除纪律：热路径上不要做删除动作

WorkBuddy 的 safe-delete 守卫按「**单次工具调用内累计删除次数**」计数（阈值 50），
被拦时抛的是 **`SystemExit`（不是普通异常）**——它会直接打断调用栈。

- 每条浏览器命令净删 2 个文件（`transport.lock` + `pending-command.json`）→ 一次几十条
  命令的长流程必撞线。撞线后 `Lock.__exit__` 的 unlink 被打断 → 锁文件残留（内容是死 PID）
  → **之后每次运行都 `busy`，永久死锁**。
- 因此热路径的纪律是**删除次数归零**：
  - 传输锁用 **OS 级咨询锁**（`msvcrt.locking` / `fcntl.flock`）：进程退出时系统自动释放，
    结构上不可能留下死锁，也不需要删除任何文件。
  - `pending-command.json` **不删**，下一条命令覆盖它。它是「上一条操作是否已结算」的闸门：
    结算成功 → 放行；结算不了（超时/损坏/`mayHaveLateEffects`）→ 继续拦。不删不改变语义。
  - 文件锁保留给低频任务（`browser.lock`/`job.lock`），但必须具备**死进程锁自动回收**：
    读 PID → 进程还在则拒绝（**活锁绝不抢占**）→ 进程已死则用**改名**（原子、不是删除）
    接管。回收用改名而不是删除，删除动作可能被守卫拦下。
  - 锁释放失败**不得致命**：文件里留着死 PID，下一次运行会回收它。
- 同理：把 `npm test` 与 `pytest` 放在**同一次工具调用**里跑，pytest 收尾清理自己的临时
  目录（一个目录 55 个文件）也会撞守卫 —— 与项目代码无关，但会让测试跑完却拿不到汇总行。

### ⑪ 先分清「没等够」和「读不到」，别把「读不到」立刻升级成「平台上限」

抖店编辑页有两处会让采集读不全，**两处都已在 2026-11-14 查清并修好**，成因完全不同：

- 「价格库存」SKU 表格：24 个 SKU 的商品只挂载 6–7 行（点「全屏」也只到 8；滚外层容器到底、
  视口翻三倍都不变）。🔴 曾经的结论「平台最多渲染 7 行」**是错的**——同一套采集代码在
  25 和 32 个 SKU 的商品上完整读到了全部商家编码。真因是**滚错了容器**：表格是虚拟列表，
  真正决定挂载哪些行的是 `div.ecom-g-table-tbody-virtual-holder` 的 `scrollTop`
  （`scrollHeight 2707 ≈ 24×113`，clientHeight 523），而 `#goodsEditScrollContainer` 只是把
  整块内容移进视野。修复：新增 `scroll_rows` op，在「ready 且无占位行」时滚 holder。
- 详情槽位停在 28（声明 37）：缩略卡片 37 个都在，但**后 9 张的 `<img>` 停在 1×1 占位 GIF**，
  真实地址要等卡片进入视口才写入。修复：`op='scroll'` 在 `kind='details'` 时改滚
  **第一张未加载的卡片**，`wait_details` 每轮 nudge 一次。

实测结果：24 / 56 个 SKU 与 37 张详情全部读全，task 35、40 已恢复 `blocked → needs_agent`。

因此：

- 看到 `official_sku_code_incomplete` / `detail_source_not_ready`，**先量三件事**：API 声明的数量、
  DOM 实际渲染的行数/槽位数、**改哪个元素的 `scrollTop` 才能让渲染数量变化**。第三件最容易漏——
  「我滚过了没用」往往只是滚了外层容器。
- **别用调大预算当修法**（`collect_official_sku_codes` 的 30 秒是刻意上限），
  也**别把它写成平台硬上限**——那等于把「我的策略没覆盖」记成「对方不给」，会永久放弃一个可修的问题。
- 找不到入口时，正确结果是继续 blocked，**不是**把「UI 覆盖了一部分」当成「证据完整」
  （那等于放宽闸门）。
- 任何「读不到」的结论落纸前，**逐轮输出必须落盘**。没有可重放的证据，那只是观察，不是结论。

### ⑫ rebaseline 结案只认两种结论，但历史证据的字段名不统一

`batch rebaseline` 的契约是：每条历史观察证据都必须能归到下面**两种结论之一**，
否则整件保持 blocked（失败关闭）：

| 结论 | 语义 | 可接受的证据形态 |
|---|---|---|
| `no_save_attempted` | 从未把改动写进商品 | `submission_status == 'not_attempted'`；或 `saved is False` **且** 无 `saveAttempts` **且** `saveCount <= 0` |
| `prior_revision_confirmed` | 上一版改动已确认，本次按新版本重做 | `stage == 'verified'` 且 `status` ∈ `{accepted, verified_by_readback}` |

- `verified_by_readback` 是队列自己的终态，比 `accepted` **更强**，不能因为「字段名不在白名单
  里」就把它拒之门外——这是真实的过度严格。
- 🔴 **`unknown` 永远不结案**，不管它写成 `submission_status='unknown'`、
  `phase='upload_unknown'` 还是 `saveAttempts > 0`。这些说明提交可能已被平台收到，
  重做可能覆盖别人的改动。
- 判断依据是**证据内容**，不是 `stage` 字符串本身。历史 agent 用过
  `editing / completed / saved_and_verified / blocked_pending / submitting / upload_unknown /
  title_save_request_omitted_stop` 等十几种写法，只按字面匹配必然漏判。

### ⑬ 全量 pytest 会在一个回合内删爆守卫阈值，产生假失败

safe-delete 守卫按「单次工具调用内累计删除文件数」计数（阈值 50，按文件递归计）。
全量 720 个测试里大量用例会建删 `browser.lock` / `job.lock` / 临时目录，
**累计很容易在跑到一半时撞线**；撞线后 `unlink` 被拦，于是「锁文件不存在」这类断言失败。

- 典型假失败特征：失败信息里同时出现 `SAFE_DELETE_BULK_CONFIRM_REQUIRED`
  和 `assert not True  where True = ...browser.lock.exists()`。
- 本轮实测：同一个提交，早期全量 `[100%]` 全点（无 F/E）；继续在同一回合里反复跑之后，
  变成 `39 failed, 681 passed`，而**单独跑 `test_workflow.py` 仍 55 passed** →
  失败与代码无关，与这一回合已经删了多少有关。
- 判据优先级：**先看进度条里有没有 `F`/`E`**。若中途才出现 F 且伴随守卫文案，
  那不是回归。要拿干净汇总，**换一个用户回合再跑**（计数会重置）。
- `--basetemp` 指向仓库内目录本身没问题（`work/` 已被 gitignore），但别复用一个已有目录。

### ⑭ 队列里有 6 件商品根本不在妙手，`page_timeout` 不等于「等一下就好」

`batch rebaseline` 及一切妙手写入路径都从「按商品ID搜到那唯一一行」开始。2026-11-14 把队列
61 件逐件拿去妙手搜了一遍（`work/rebaseline-20261113/harvest_inventory.py`，产物
`miaoshou-inventory.json`），结果是 **55 件在、6 件不在**：

| 队列 task | 抖店侧真实状态 | 队列既有错误 |
|---|---|---|
| 12 | `checkStatus=1 draftStatus=0`，正常下架 | `external_work_requires_rebaseline` |
| 22 | `checkStatus=4 draftStatus=4` | `doudian_draft_or_rejected` |
| 33 | `checkStatus=4 draftStatus=4` | `writer_image_slots_incomplete`（主图 3 张） |
| 36 | 编辑页「商品不存在或已彻底删除」 | `doudian_product_deleted` |
| 46 | `checkStatus=4 draftStatus=4` | `doudian_draft_or_rejected` |
| 52 | `checkStatus=4 draftStatus=4` | `doudian_draft_or_rejected` |

- 对照实验是这条结论的支点：同一路径同一输入框，搜一件确定在妙手的 ID 得 `商品信息 (1)`，
  搜 task 12 得 `商品信息 (0)` + `暂无数据` + `共 0 条`，再搜对照又回到 `(1)`。
  没有这个对照，「搜不到」也可能只是搜索没生效。
- **task 12 的 `page_timeout` 是结构性的，不是瞬时抖动**：重试两次都在 `edit_button` 上超时，
  因为妙手侧没有这一行可标。它的历史无法 rebaseline（妙手基线不可能存在），
  只能保持 blocked。别再用「再试一次」消耗一轮。
- 其余 5 件本来就有各自更精确的阻塞理由，妙手无行只是同一事实的另一面：
  抖店侧是草稿/驳回/已删除的商品不会出现在妙手「商品快速编辑」列表里。
  写不进队列的结论**不要**反过来说成「妙手缺数据」。
- 判据：`page_timeout` 落在 `_mark_control` 上时，先确认**这件商品在妙手是否存在**，
  再决定是重试还是记成不可达。判存在的证据必须是「商品信息 (1)」，不是「列表里好像有」。

### ⑮ 妙手 `page_timeout` 的第三个成因：Ego 窗口被最小化，内宽只有 901

`batch run --apply` 连续两次在 `_mark_control('edit_button')` 上 `page_timeout`，报「妙手当前可见控件或商品行未唯一定位」。
前两个已知成因（视口写死在 `state.viewport`、残留全屏组件 iframe）都排查过且都不成立，第三次才抓到真因：

- **Ego 浏览器窗口当时处于最小化**，`pageInfo()` 报 `w=901 h=638`；`Browser.getWindowForTarget` 报
  `bounds 915×756 windowState=minimized`。妙手「查询」按钮实测 `left=1017 > innerWidth=901`，
  直接撞上 `visible()` 的 `r.left >= innerWidth → false`，于是控件存在却被判不可见。
- **修法不是改 `state.viewport`**：每个 `batch run` 会新建并收尾自己的任务空间，起始的
  `state.viewport` 是从真实窗口观测出来的（901×638），手工先写 1440×900 会被 run 覆盖回去；
  而且 session 用完即 `ego_session_finished`，下一次必须换 session 名。
- **真正的修法是放大窗口本身**：
  ```js
  const t = await useOrCreateTaskSpace('window-fit');
  const {targetInfos} = await cdp('Target.getTargets', {});
  const page = targetInfos.find(x => x.type === 'page');
  const {windowId} = await cdp('Browser.getWindowForTarget', {targetId: page.targetId});
  await cdp('Browser.setWindowBounds', {windowId, bounds: {width: 1520, height: 1010, windowState: 'normal'}});
  ```
  之后窗口变 `maximized`（外框 1722×928，内宽 ≈1708），同一条 `batch run --apply` **一次通过**：
  task 40 → `verified` / `verified_by_readback`，`miao_matches` 与 `doudian_matches` 均为真。
- 判据顺序（下次省时间）：`pageInfo().w` 与 `Browser.getWindowForTarget().bounds.windowState`
  → 再看 `state.viewport` → 最后才怀疑页面改版。**窗口最小化时 `innerWidth` 只有 901，
  比任何「布局改版」都更像改版。**
- 副作用要说清：`setWindowBounds` 改的是用户真实浏览器窗口（本次是把它从最小化恢复并最大化）。

### ⑯ `miao_matches=true` 但 `doudian_matches=false`：先分清「渲染窗口」与「真被改」

task 11（`3850071893537325881`，32 SKU）写入后妙手侧全对，抖店侧 `matches_target=false`，
`compare_protected` 抛 `commercial_changed`。逐层查到根因是**渲染窗口高度不同**，不是数据变化。四步 2 分钟判据：

1. **看是哪一层失败**，别急着读整段 diff：
   ```python
   compare_protected(baseline['doudian_baseline'], 读回)   # 注意：是内层 doudian_baseline，不是外层 baseline_json
   ```
   🔴 传外层包壳会得到 `official_sku_incomplete`（外层没有 `sku_evidence`），**看起来像 SKU 缺失，其实是拿错对象**。
2. **逐分区打 SAME/DIFF**（本轮 8 个分区只有「价格库存」不同，其余 7 个逐字节相同）。
3. **对 `价格库存.inputs` 做三种关系判定**，结论完全不同：

   | 关系 | 含义 | 本轮实测 |
   |---|---|---|
   | 多重集差：基线减读回 = 0，读回多出 N 条 | 只多不少 | 0 删 / 6 增（真） |
   | 基线是读回的**前缀** | 尾部追加 | ❌ 不成立（第 160 位就分叉） |
   | 基线是读回的**子序列**（保序） | 只多插入，无删除、无乱序、无改值 | ✅ **成立** |

   **子序列成立 = 没有任何一条记录被删或被改**，比「多重集相等」更强（交换两行会破坏保序，多重集却看不出来）。
4. **比权威 SKU 摘要**：`sku_evidence.sha256` 与 `count` 两侧相等即「全部 SKU 的价格/库存/上下架/商家编码/规格 ID 未变」。
   本轮两侧都是 `count=32`、`sha256=d0b6fd86…`，且多出来的那一行 `LC弯刀裤黑标-灰色170`（49.88）
   **本来就在基线的 `raw_rows` 里** —— 它是「原先就有、只是没渲染」，不是新增 SKU。

**为什么是窗口而不是数据**：两侧的 SKU 行窗口都是**顶部对齐**的，基线渲染第 0–6 行（7 行），读回渲染第 0–7 行（8 行）。
拿 `sku_evidence` 的编码去 DOM 里点命中数就能看见：基线 7/32、读回 8/32 ——
`价格库存` 的 `inputs` 快照本质是**视口窗口**，不是全表。而 task 11 的基线是在 Ego 窗口**最小化**（内宽 901）时抓的，
读回是在按 ⑮ 把窗口放大到内宽 ≈1708 之后抓的 → 一屏多装一行 → 多 6 个 input。

🔴 **这暴露了代码的自相矛盾，值得单独记**：采集器在快照里自己写着
`coverage: "仅DOM实际加载字段；虚拟SKU列表未逐行遍历"`、`sku_coverage: "官方页面本次加载的全部SKU响应；不受虚拟表格可见行数限制"`，
也就是**声明了 DOM 分区只是部分窗口、全量证明由 `sku_evidence` 承担**；
但 `compare_protected` 对 `价格库存` 的 `inputs` 做的是**逐条严格相等**，等于把「部分窗口」当「完整快照」比。
同一份代码里 `protected_complete=true` 也因此是**假完整**（task 11/2/35/37 四件全是 True，其中 task 11 只覆盖 7/32 行）。

**本轮没有改闸门，理由要留住**：`compare_protected` 的 docstring 明确记录过「子多重集容忍」被移除，
且 `tests/test_workflow.py:469` 的 `test_a_longer_field_list_is_a_change_not_a_render_window` 正是本次命中的形态
（before 1 条 / after 2 条必须报错）。**子序列判据会让这条测试失效**（1 条是 2 条的子序列），
所以改它等于推翻既有安全结论，必须带复核单独做，不能为了让某一件过闸而顺手放宽。
→ task 11 保持 `blocked`，理由写成「**基线对该分区只覆盖 7/32 行、与读回窗口高度不同**」，
不写成「价格被改」，也不写成「平台不给」。

**闸门没有放宽，改的是采集侧**：让「价格库存」的比对对象与视口无关 ——
采集时额外记录两份东西：`inputs_without_sku_grid`（同 `inputs`，但去掉网格行 `<tr data-row-key>` 内的单元格）、
`sku_grid_rows`（这次挂载了几行，纯覆盖元数据、永不参与比对）。
比对时**只有两侧都带 `inputs_without_sku_grid` 才用它替换 `inputs`**；旧基线没有这个键，就照旧严格比 `inputs`，
**严格度一点没降**（`test_a_legacy_baseline_without_the_grid_free_list_stays_strict` 钉死这条）。

🔴 **为什么不直接把网格行从 `inputs` 里删掉**：`_stored_execution_baseline` 用的是**库里持久化的基线**，
不是每次现抓；删掉字段会让 61 件商品的历史基线与新读回全部对不上，等于一次性制造 61 个假失败。
所以保留 `inputs` 的旧含义、另加一份列表，是唯一不炸迁移的写法。

**为什么这不算放宽**：被替换掉的只是「这次恰好挂了哪几行」这个随窗口变的信息；
网格本身的价格/库存/上下架/商家编码/规格 ID 由 `sku_evidence` 逐 SKU 全量证明（32/32 + `sha256`），
比原来那 7–8 行的 DOM 切片**强得多**。`价格库存` 里真正需要严格比的其它控件
（批量设置、运费承诺、限购）两个列表里都在，仍然逐条相等才算过。

**回归（都在离线测试里）**：
- `tests/dom.test.cjs`：网格行只从新列表消失、`inputs` 原义不变（`20.88` 这类分区控件两个列表都保留）；
  **窗口 7 行 vs 8 行时 `inputs` 必须不同、而比对用的列表必须相同**（就是本次翻车的形态）；
  分区控件改动时新列表也必须不同；非网格分区不带这两个键。
- `tests/test_workflow.py`：两侧都有新列表且相等 → 通过（`inputs` 不同也通过）；
  只有一侧有 → **回落到 `inputs` 并报错**；新列表里控件变了 → 仍然 `commercial_changed`；
  `sku_grid_rows` 不同 → 不算变更（元数据）。

⚠️ **这条修复只对「以后重采的基线」生效**。历史基线不可变，所以 task 11（以及所有旧契约的 blocked）
照旧按 `inputs` 严格比、照旧会报这个错 —— 想救它只有两条路：重采基线（会把已经发生的写入洗成基线，**不做**），
或人工裁决接受 `sku_evidence` 摘要。判据写清就够，不要为了单件去松闸门。

### ⑰ 商家编码读不全：先分清「旧策略失效」与「行选择错误」，最后才谈预算

task 57 / 58 停了 11.9 天（`official_sku_code_incomplete (7/44)` 与 `official_sku_code_row_ambiguous`）。
逐件只读复测后，两件的结论完全不同：

**57 = 旧错误，已不复现。** `editor.read_skus` 现在读完 **44/44**（`code_ui_rows=44`），
而且 44 个商家编码**全是空字符串** —— 这是 `collect_official_sku_codes` 明确允许的合法证据
（空值只在该 SKU 观测到唯一真实 input 时才算）。11.9 天前那次是旧策略的受害者：
当时只在 `pending_count > 0` 时才滚动，而 57 是「真行 + 0 占位行」，整轮 30 秒**一次都没滚**
（真因已由 T-20261114-014 修掉）。**旧错误信息不能当结论用，必须重跑。**

**58 = 两个真缺陷，都不是预算问题。**

1. **分区里混着第二张 keyed 表**：58 的「价格库存」里既有尺码表（11 个 `tr[data-row-key]`、
   每行 4 个 td、**无** sku/code 单元格），也有 SKU 表（表头 12 列）。而 `official_sku_code_dom.js`
   原先直接 `root.querySelectorAll('tr[data-row-key]')`，尺码行先被遍历到 →
   `skuCells.length !== 1` → 报 `row_ambiguous`。**keyed 行不等于 SKU 行。**
   修法：只保留带 `.attr-column-field_sku_id` 或 `_code` 单元格的行；一个都没有时回落到全集
   （fail closed 语义不变）。占位行本身就带 code 单元格，所以不受影响。
   顺带：`scroll_rows` 也要挑 **SKU 行所在的 holder**，否则会去滚尺码表那个。
2. **占位行分支不推进虚拟 holder**：`scroll_pending` 只做 `scrollIntoView`，虚拟列表对此不响应。
   58 有 **121** 个 SKU 且常驻占位行 → 30 秒里一行都没换 → 只读到已渲染的 10 行。
   修法：`scroll_pending` 与 `scroll_rows` **都**推进 holder。

两处修完，58 从「10/121」变成 **91/121**（错误也从 `row_ambiguous` 变成可诊断的 `incomplete`）。

🔴 **91 之后是能力上限，不是预算**：holder 的 `scrollHeight` 到 13332 就停（约 111 行），
滚到底后回绕也补不上后 30 行。把预算从 30 秒提到 90 秒，结果**一模一样仍是 91/121**
（所以我改完又回退了 —— 没有实测收益就不动契约，不然只是让每次读取更慢）。
要读完 121 行得让外层表单滚动触发懒加载，是另一件事，得单独验证。

判据（下次省时间）：
1. 先**重跑**一次只读 `read_skus`，**旧错误信息不可信**；
2. 报 `row_ambiguous` → 数「分区里有几张表、各自 keyed 行数与 td 数、SKU 行的 `closest('table')` 是否为 null」；
3. 报 `incomplete` 且读数恰等于初始挂载数 → 看 `pending_count` 是否常驻 > 0（占位行分支在空转）；
4. 只有「滚动确实在推进、行数却上不去」才怀疑预算；**改预算前用两个不同预算各跑一次，结果相同就说明不是预算**。

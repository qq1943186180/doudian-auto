# 抖店本地上传

更新：2026-11-14 傍晚（Asia/Shanghai）；当前执行：workbuddy；最近任务 T-20261114-021（**抓回一次假恢复**：preflight 通过只证明抖店可写，写入走妙手；task 22 不在妙手，已收回并补上 `--check-miaoshou` 闸门）。旧主体由Codex起草、WorkBuddy核实，本轮修复及验证以最上任务块为准。执行前仍须重查仓库和本机状态——本文数字是快照，不是实时值。队列 61 件＝**22 verified / 39 blocked / 0 needs_agent**（2026-11-14 17:45 实读 batch.sqlite3）；blocked 里只剩 3 件 `submission_state=unknown`（task 11 定性、task 19/42 缺真实参数）。

> **39 件 blocked 按「卡在谁身上」互斥分类，合计 39（2026-11-14 18:55 逐件重检后实测）。程序侧能自己推的已经推到头。**
>
> | # | 类别 | 件数 | task | 需要谁 |
> |---|---|---|---|---|
> | ① | 缺平台必填属性的真实值 | **9** | `23`(5 项) `28` `50` `31` `43` `45` `54` `19` `42` | **你给值**——1688 源头没有，程序不猜 |
> | ② | 视觉复核失败 | **5** | `15` `16` `27` `34` `48` | **生图额度**；`15`/`34`/`48` 还缺失败证据 |
> | ③ | 源素材槽位不足 | **8** | `39` `55` `57` `59` `60` `61` `46` `52` | **改写入器**——生成图救不了，缺的是源商品槽位 |
> | ④ | 前 4 张详情重复原图 | **2** | `49` `56` | **改写入器**——按图查找替换会同时改多处 |
> | ⑤ | 需人工核实历史版本/素材 | **8** | `1` `3` `4` `6` `8` `7` `13` `9` | **人工核实**——历史 `stage` 含 editing/completed、`status` 全 `None` |
> | ⑥ | 结构性不可达 | **4** | `12` `22`(不在妙手) · `33`(抖店也没有) · `58`(列表封顶) | **别再重试**，重试只会得到同一条 `page_timeout` |
> | ⑦ | 平台侧需你去后台处理 | **2** | `51`(确有草稿/驳回) · `36`(商品已删除) | **你** |
> | ⑧ | 待裁决 | **1** | `11` | **你一句话**：按权威 SKU 摘要 32/32 一致结案？ |
>
> **补充事实**：③ 里的 `46`/`52` 与 ⑥ 的 `12` 一样**不在妙手**（写入路径不通），槽位不足只是第二层原因；
> ④ 的 `56` 同时缺「材质+适用年龄」，但详情重复原图不解决也写不进。
>
> **另需授权**：3 件商品（含 `3853482303460343870`）是「审核通过但商家自主下架」，行内有「上架」按钮。
> 上架是对外经营动作，**没有明确授权就不自动点**（`dropship.py:208`：初版只允许放入仓库）。

## 给人的说明

### T-20261114-021 · 194-76 · 抓回一次假恢复：preflight 通过 ≠ 能写入

- 状态：**done（缺门补齐 + 一次错误恢复被收回）**。零商品写入。队列 `blocked 39 / verified 22 / needs_agent 0`。
- ① **假恢复怎么发生的**：T-20261114-020 后 task 22 被放到 `needs_agent`（重检 `eligible=true`，抖店侧主图 5、详情 19、属性齐）。打算给它出 9 张图时，`prepare_one.py` 连续两次卡在妙手 `_mark_control('edit_button')` 的 `page_timeout`。查 2026-11-14 的对照实验：**task 22 根本不在妙手**（`listed=0`，且重试过一次）。
- ② **根因是闸门缺口**：`preflight` 只读**抖店**官方页，证明的是「抖店侧可写」；而**写入实际走妙手**。两者缺一都不能放行，恢复路径当时只看了前者。
- ③ **补法**：`batch preflight --check-miaoshou` 用新增的 `MiaoshouEditor.row_present()` 做**纯只读**探测（导航到快速编辑页 → 搜索 → 数按商品 ID 匹配的行，**不点编辑按钮、不打开商品**），结果写进报告 `evidence.miaoshou_listed`；读不到时写 `None`，**绝不把「读失败」当成「不存在」**。`apply_preflight_report` 的**放回分支**要求 `miaoshou_listed is True`，否则报 `miaoshou_listing_unproven`；**刷新理由的分支不要求**。
- ④ **实测**：task 22 同时 `eligible=true` 与 `miaoshou_listed=false` → 被闸门正确挡住。当时**没有受支持命令能把 `needs_agent` 改回 `blocked`**，先手工收回并写 `product_events`；随后补上 `batch block --task-id --reason`（只允许 `needs_agent → blocked`，理由必填 ≥10 字，落 `manual_block:` 前缀，**不参与自动重检**）。刷新理由时若 `miaoshou_listed=false`，还会在末尾追加「妙手侧无此商品，写入路径不可用」。
- ⑤ **已知不在妙手的 6 件**：12 / 22 / 33 / 36 / 46 / 52。它们的 `page_timeout` 都是**结构性**的，别再当瞬时抖动重试；33 还叠加「商品在抖店侧不存在（`product-status` 返回 `not_found`）」，36 是已删除。
- ⑥ 代码：`MiaoshouEditor.row_present`、`preflight_products(..., check_miaoshou=)`、`apply_preflight_report` 的妙手闸门、CLI `--check-miaoshou`。测试 `tests/test_reopen_blocked.py` 12 → **14**（「缺妙手证明不能放回」「妙手明确不存在也不能放回」）+ 新增 `tests/test_block_task.py` **7 条**（含「有保存尝试/有基线/已核验一律不准收回」「手工收回不被自动重检推翻」「刷新理由要写明妙手缺货」）。文档：`docs/dropship-policy.md` ⑱-b。
- ⑦ **同轮补完两件相邻事实**：① task 58 的 121 个 SKU 读不全，**滚外层表单也不增长**（先滚 holder 到 `st=13332/sh=14069`，再滚 `styles_form__Ew_RZ` 到底，`scrollHeight` 不变，按 SKU ID 去重 16→18 只是渲染补全）→ 平台把虚拟列表总高封在约 111 行，**换数据源才能解决**，别再试滚动参数；② task 46/52 的理由现在都带上「妙手快速编辑列表中没有该商品，写入路径不可用」，它们与 task 22 一样**不在妙手**，槽位不足只是第二层原因。


### T-20261114-020 · 194-76 · 19 件预检阻塞件全量重检：1 件真恢复，12 件理由被更正

- 状态：**done（只读重检 + 队列理由更正）**。零商品写入。队列 `blocked 39 → 38`、`needs_agent 0 → 1`、`verified 22` 不变。
- ① **task 22 真的恢复了**：旧的 `doudian_draft_or_rejected` 已完全不成立，重检 `eligible` → `needs_agent`，可直接进入素材准备（还需 9 张图，属花钱动作，未开始）。
- ② **12 件理由被更正**（23/28/31/39/43/45/46/51/52/54/55/56/57/59/60）：队列现在写的是今天读到的原因，不再是 11.9 天前的快照。
- ③ **三处旧判断被推翻**，这是本次重检最大的价值：
  - 「`doudian_draft_or_rejected` 4 件」**只剩 task 51 真的成立**。46/52 其实是槽位不足（主图 3 张），56 是 `writer_detail_source_collision`（前 4 张详情有重复原图，与 task 49 同款）。
  - task 23 缺的是 **5 项**属性（安装方式、是否可接触食品、材质类型、型号、生产企业地址），不是旧记录里的 1 项 —— 按旧记录去补值是补不完的。
  - task 39 真正先卡的是槽位（主图 4 张），不是「缺安装方式」。
- ④ **3 件读失败、1 件被别的闸门跳过**：task 33 页面无任何分区 → `product-status` 返回 `not_found`，**实际是商品在抖店侧不存在**（不是登录问题）；task 58 编码 91/121（能力上限，见 T-20261114-018）；task 50 有活跃官方任务（`active_official_job`）。
- ⑤ **两条实测教训**：`close_session` 结束的是整个 TaskSpace，共享 session 会让后续件全部 `ego_session_finished`（0.1 秒即失败）——必须**每件独立 session**；读失败（无快照）**不覆盖** `last_error`，否则「页面没就绪」会埋掉真实原因。
- ⑥ 工具：`work/probe-20261114/batch_recheck.py`（逐件独立会话 + 逐件对账），产物 `work/probe-20261114/recheck-batch-*/recheck-applied.json`。文档：`docs/dropship-policy.md` ⑱ 追加实测段与三条新判据。

### T-20261114-019 · 194-76 · 补上「因预检失败而 blocked」的恢复路径

- 状态：**done（一对受支持的命令 + 一次真跑实证）**。零商品写入，队列里 1 件的阻塞理由被更正为真实事实。
- ① **洞在哪**：`preflight_exception:*` 不在 `PREWRITE_RECOVERABLE_ERRORS` 里，`batch preflight` 又对 blocked 件直接 `queue_state_ineligible` —— 于是「根因早修掉、当年那次预检失败」的件**没有任何受支持的命令能放回可运行**。T-20261114-018 的 task 57 就卡在这里。
- ② **补法分两步，都不放宽安全条件**：
  ```bash
  doudian-auto batch preflight --product-id <pid> --batch-id <bid> --session <现有会话> \
      --report-dir <dir> --recheck-blocked      # 只读重读，连接仍是 mode=ro，不改队列
  doudian-auto batch recheck --task-id <id> --proof <dir>/<run>/summary.json   # 凭报告对齐队列
  ```
- ③ **准入只看 `last_error` 前缀**：`preflight_exception:` 开头的件才可重读；`readback_mismatch`、`doudian_product_deleted` 等**一律不放**，因为那类失败可能描述一次真实写入。
- ④ **`recheck` 只认报告里的四件事**：`read_only=true`、`evidence.snapshot_read=true`、商品/店铺/`target_version` 三者与本行一致、`observed_at` 在 30 分钟内且 `snapshot_sha256` 是 64 位摘要。此外本行必须仍是 `blocked`、`not_attempted`、`attempts=0`、**无 baseline/素材/上传记录/租约/兄弟版本/活跃官方任务** —— 即「从未写过」。
- ⑤ **两种结局都落库并写 `product_events`**：`eligible=true` → `blocked → needs_agent` 并清空 `last_error`；**又失败 → 保持 blocked，但把 `last_error` 换成这次读到的理由**（保留前缀，下次还能再检）。后半条是重点：十二天前的理由把排查带偏过一次。
- ⑥ **实证（task 57）**：走完两步后 `last_error` 从 `official_sku_code_incomplete; 仅确认7/44个SKU` 更正为 `writer_image_slots_incomplete; 主图5张、详情2张`。**编码问题早就不存在，真正缺的是 2 张详情源图**。57 仍在售（`statusName=上架`），写入属线上动作，未授权不做。
- ⑦ 代码：`batch.apply_preflight_report`（原 `reopen_blocked`）、`preflight._skip_reason(..., recheck_blocked=)`、`preflight_products(..., recheck_blocked=)`、`_COLUMNS` 增 `last_error`、CLI `batch preflight --recheck-blocked` / `batch recheck`。测试新增 `tests/test_reopen_blocked.py` **10 条**（含「陈旧报告拒绝」「只差一个版本拒绝」「写入型阻塞永不放行」「失败也要刷新理由」「刷新后仍可再检」），回归 178 项全绿。文档：`docs/dropship-policy.md` 新增 ⑱。

### T-20261114-018 · 194-76 · 商家编码读取：一条旧错误被证伪，两个真缺陷被修掉

- 状态：**done（只读诊断 + 两处读取器修复），零商品写入**。task 57/58 仍 blocked，但阻塞理由都换了更精确的写法。
- ① **task 57 的旧错误已失效**：`editor.read_skus` 现在读完 **44/44**（`code_ui_rows=44`），且 44 个商家编码**全是空字符串**——这是 `collect_official_sku_codes` 允许的合法证据。11.9 天前那次是旧策略的受害者（当时只在 `pending_count>0` 时才滚，57 是「真行+0 占位行」，30 秒一次没滚），真因已由 T-20261114-014 修掉。**教训：旧 `last_error` 不能当结论，必须重跑。**
- ② **task 58 有两个真缺陷**，都不是预算：
  - **尺码表的 keyed 行被当成 SKU 行**：58 的「价格库存」里既有一张尺码表（11 个 `tr[data-row-key]`、每行 4 个 td、无 sku/code 单元格），也有 SKU 表（表头 12 列）。读取器直接 `root.querySelectorAll('tr[data-row-key]')`，尺码行先被遍历 → `skuCells.length!==1` → `row_ambiguous`。**keyed 行 ≠ SKU 行。** 修：只保留带 sku/code 单元格的行，一个都没有时回落全集（fail closed 不变）。顺带让 `scroll_rows` 挑 SKU 行所在的 holder。
  - **占位行分支不推进虚拟 holder**：`scroll_pending` 只做 `scrollIntoView`，虚拟列表不响应；58 有 **121** 个 SKU 且常驻占位行 → 30 秒没换行 → 只读到 10 行。修：`scroll_pending` 与 `scroll_rows` 都推 holder。
- ③ **修完 58 从 10/121 到 91/121**，错误从 `row_ambiguous` 变成可诊断的 `incomplete`。**剩下 30 行是能力上限不是预算**：holder `scrollHeight` 到 13332 就停（约 111 行），滚到底回绕也补不上；把预算提到 90 秒结果**一模一样**，所以已回退——没有实测收益就不动契约。
- ④ **实测口径**（下次省时间）：57 每轮 `evaluate` 160–260ms、半页步进推进 2 行、`scrollHeight` 滚动中从 3411 长到 3911；58 的 row key 是**渲染槽位号**（同一 key 会换内容），所以「按 key 去重」在 58 上会假性停在 9，必须按 SKU ID 累计。
- ⑤ **两件都还动不了**：57 需要一条受支持的「preflight 失败的 blocked 件」恢复路径（`recover-preflight`/`preflight` 都不收，`preflight` 直接 `queue_state_ineligible`）；58 要读完 121 行得让外层表单滚动触发懒加载，是另一件事。**57 在售（`statusName=上架`），写入属线上动作，未授权不做。**
- ⑥ 代码：`official_sku_code_dom.js` 两处；测试 `official-sku-code-dom.test.cjs` 18→**21**（新增「邻表 keyed 行被跳过」「只有外来的 keyed 行仍 fail closed」「scroll_rows 推 SKU 行所在的 holder」），适配器 38/38 真跑通过。文档：`docs/dropship-policy.md` 新增 ⑰。

### T-20261114-017 · 194-76 · 4 件收尾：3 件双端 verified，task 11 定性为「基线渲染窗口不全」

- 状态：**done（3 件真写，1 件定案保持 blocked）**。队列 `verified 19 → 22`、`needs_agent 4 → 0`、`blocked 38 → 39`，总数 61 不变。
- ① **task 35**（`3848317566716084561` 银丝洗碗布，9 SKU）→ `verified`。9 图（`main-1..5` 1024²、`detail-1..4` 1024×1536）逐张去水印后目视复核 → `build_from_spec` → `agent complete` → `batch run --apply` 当轮 `submission` 阶段 `batch_apply_response_unknown`（只点了 1 次保存）→ **`readback_one.py` 单件只读复核**得 `verified / verified_by_readback`（`miao_matches` 与 `doudian_matches` 均真）。标题 `银丝洗碗布家用厨房锅具灶台清洁抹布单层双层多种数量可选`。**结论：保存其实成功了，只是当轮没等到响应。**
- ② **task 2**（`3850072900438720563` 男士平角内裤，25 SKU）→ `verified`，一次通过，**5 分 46 秒**。`main-4`/`main-5` 各重做一次：第一版 `main-4` 出现「COKUMAN」重影字、`main-5` 红色偏酒红 → 重写提示词（「每个腰头恰好 COKUMAN 一次、居中、不与其它文字重叠」/「亮正红，不要 maroon、不要 burgundy」），并加 `recenter.py` 居中 + 二次去水印（两次都 `no watermark pixels found`）。**观察记录必须写「腰头织白色 COKUMAN」**，`printing` 不能写成「无印字」。
- ③ **task 37**（`3848317504447447331` 桌下抽屉收纳盒，2 SKU）→ `verified`，**5 分 5 秒**，`miao_matches` 与 `doudian_matches` 均真。**前 3 版全弃**（存 `assets/rejected/`）：`21-36-15`、`21-36-56` 把开口浅盘画成带铰链翻盖；`21-37-36` 大号出现双层内盘。改用 **image1 参考图编辑**（`input_fidelity: high`），全部只保留「开口浅盘 + 薄外套贴桌板」的几何后才过。
- ④ **task 11**（`3850071893537325881` 男童直筒休闲裤，32 SKU）→ **素材已交付、写入已发生，仍 `blocked`**（`submission_state=unknown`、`last_error=readback_mismatch`）。妙手侧全对（`matches_target=true`、9 张图 URL 全中）；抖店侧 `main_count=5`、`detail_count=7`（4 换 + 3 留）、标题一致、`rejected=false`、`draft_loaded=false`，**唯一分歧是 `compare_protected` 抛 `commercial_changed`**。
- ⑤ **定性过程（本轮最花时间的一段，结论推翻了中途三个错误判断）**：
  - 🔴 先用错了对象：把**外层** `baseline_json` 当 `before` 传进 `compare_protected`，得到 `official_sku_incomplete`，差点写成「SKU 证据缺失」。正确对象是内层 `baseline['doudian_baseline']`。
  - 拿对之后：8 个分区**只有「价格库存」不同**，其余 7 个逐字节相同；两侧观测状态都是合法的 `ready`/`empty_block`，所以**不是** `protected_snapshot_incomplete`。
  - 差异只在 `inputs`：**基线 167 条、读回 173 条**。多重集差 `0 删 / 6 增`；**前缀**不成立（第 160 位分叉）；**保序子序列成立** —— 即没有任何一条被删或被改。
  - 6 条增量 = 一整行 SKU 的控件；`sku_evidence` 两侧 `count=32`、`sha256=d0b6fd86…` **完全相同**，且那一行 `LC弯刀裤黑标-灰色170`（49.88）**本来就在基线 `raw_rows` 里** → 原先就有、只是没渲染。
  - 决定性一步：拿 SKU 编码去 DOM 点命中数 —— **基线 7/32、读回 8/32**，两次都是**顶部对齐**（0–6 行 vs 0–7 行）。`价格库存` 的 `inputs` 本质是**视口窗口**，不是全表。
  - 真因串起来：task 11 的基线是在 Ego 窗口**最小化（内宽 901）**时抓的，读回是按 ⑮ 把窗口放大到内宽 ≈1708 之后抓的 → 一屏多装一行 → 多 6 个 input。**同一个「窗口」问题第二次咬人，这次咬在数据判定上。**
- ⑥ **为什么不放闸门**：采集器自己在快照里写着 `coverage: 仅DOM实际加载字段；虚拟SKU列表未逐行遍历`、`sku_coverage: 不受虚拟表格可见行数限制`，也就是**声明了这是部分窗口、全量证明由 `sku_evidence` 承担**；但 `compare_protected` 对这块做逐条严格相等，等于把部分窗口当完整快照比 —— 这是代码内部自相矛盾，`protected_complete=true` 因此是**假完整**（四件全 True，task 11 只覆盖 7/32 行）。**但**：该函数的 docstring 明确记录过子多重集容忍被移除，`tests/test_workflow.py:469` 更是把「更长的字段列表就是变更」钉死 —— 子序列判据会让这条测试失效，等于推翻既有安全结论。**为了让某一件过闸而顺手放宽，正是这个项目反复拒绝的做法**，所以保持 blocked，理由写成「基线对该分区只覆盖 7/32 行、与读回窗口高度不同」，**不写「价格被改」、不写「平台不给」**。
- ⑦ **采集侧已修（兼容式，未松闸门）**：`价格库存` 额外记录 `inputs_without_sku_grid`（同 `inputs` 但去掉网格行 `<tr data-row-key>` 内的单元格）与 `sku_grid_rows`（本次挂载了几行，纯覆盖元数据）；比对时**只有两侧都带新列表、且分区是「价格库存」**才用它替换 `inputs`（限定分区，避免别的分区靠塞这个键绕过比对），旧基线照旧严格比 `inputs` —— 严格度不降。**不能直接把网格行从 `inputs` 删掉**：`_stored_execution_baseline` 用的是库里持久化基线，删了会让 61 件历史基线与新读回全对不上。回归：`dom.test.cjs` 4 条（含「窗口 7 vs 8 行时 `inputs` 必须不同、比对列表必须相同」）、`test_workflow.py` 5 条（含「旧基线无新列表时必须仍然严格」）。⚠️ **只对以后重采的基线生效**，历史基线不可变，task 11 照旧 blocked。
- ⑧ **Codex 这轮没给到意见**：`codex exec` 直接报 `You've hit your usage limit … try again at 6:52 AM`，所以上述判定全部由我自己按成文规则做，未获第二意见 —— 这也是我选择「不放宽闸门」而不是「按摘要结案」的原因之一。
- ⑨ 工具沉淀（`work/materials-20261114/`）：`build_from_spec.py`（读 `spec.json` → `source.json`+`artifacts.json`，`prompts`/`assets` 由 `kind+slot` 推导）、`recenter.py`（白底居中，不改颜色不裁主体）、`ensure-window.mjs`（CDP 放大窗口，**必须先跑再 `batch run --apply`**）、`readback_one.py`（单件只读复核，绕开 CLI 不支持按商品过滤）、`probe_official.py`（只读抓抖店编辑页图片 URL + 字节 sha256）、`dewatermark.py`（**只能逐文件列路径，传目录会 PermissionError**）。

### T-20261114-016 · 194-76 · 试点打通：task 40 九图重建 → 写入妙手 → 双端 verified

- 状态：**done，真写商品**（本项目第 19 件 verified）。`submission_attempts=1`，`state=verified`、`submission_state=verified_by_readback`。
- ① **素材**：9 张全部走 `builtin-imagegen` 图生图（`input_fidelity=high`），每张以**对应原图**为输入，提示词把身份件写死（一把长方形刷头扫把 + 一只口沿带橙色梳齿条的簸箕、清水蓝塑料、橙色磁吸椭圆扣、不锈钢圆杆），并禁止添加刮水器/第三件/任何文字。**风格选择：9 张全部无中文覆盖字**——原图那套营销字是排版层，而模型渲染中文有畸变风险；skill 里那条「不能用 Pillow 加字排版冒充 AI 重构」约束的是**拼贴**，不是要求必须带字。若要带卖点文案，是下一轮单独动作。
- ② **ImageGen 水印**：出图右下角必带「AI生成 WORKBUDDY」。按项目既定做法（`docs/handoff-history/194-54.md`）用 `cv2.inpaint` 修，**但只按「近纯白+低饱和」判据会留残影**（水印压在橙色/深色产品上时亮度不够）。最终三判据并用：浅底用「比局部中值更亮」、深色角落用「紧框内偏离中值 ≥6」、最后**只在掩膜内羽化混入大核中值**，消除 TELEA 在平滑渐变上的噪点与边界。工具 `work/materials-20261114/dewatermark.py`（非 ASCII 路径走 `np.fromfile`）。
- ③ **`page_timeout` 的真因是 Ego 窗口被最小化**（不是页面改版、也不是 `state.viewport`）。`pageInfo()` 报 `w=901 h=638`、`Browser.getWindowForTarget` 报 `windowState=minimized`；妙手「查询」按钮 `left=1017 > innerWidth=901` → 撞 `visible()` 的 `r.left >= innerWidth` 判据。手工先写 `state.viewport=1440×900` 会被 run 覆盖（每个 run 新建并收尾自己的任务空间，起始视口由真实窗口观测而来），**必须用 CDP 把窗口本体放大**：`Browser.setWindowBounds{windowState:'normal', 1520×1010}`，随后窗口变 maximized（内宽 ≈1708），同一条命令一次通过。详见 `docs/dropship-policy.md` ⑮。
- ④ **素材交付契约**：`source.json` 五类事实（identity/color/quantity/printing/specification）逐张被 9 条目视记录引用，每条 `observed` 写的是实际看见的东西（不是「通过」两个字），并绑定对应原图 sha256；`facts_sha256` 与 `source_snapshot.sha256` 双绑定。离线 `validate_agent_artifacts` 一次通过（`approved=True`、零失败槽位），再 `agent complete` → `ready`。
- ⑤ **写入与读回**：`batch run --product-id 3848316916011762046 --limit 1 --apply` →
  妙手与抖店**两端**均 `complete=true`、`main_count=5`、`detail_count=4`、`matches_target=true`、`protected_match=true`，
  标题一致 `磁吸折叠扫把簸箕家用梳齿刮毛发不锈钢杆扫地工具2件3件套多色`（58 units，零错误零告警，原 33 units）。
  当前仍 `shelf_status=1`（下架/在仓）；`startSaleType` 由 0 → 1，这是 `preserve_warehouse_v1` 允许的审核去向，**不等于上架**，`shelf_mode_matches_original=false` 是如实记录该差异，不是失败。
- ⑥ **队列**：`verified 18 → 19`、`needs_agent 5 → 4`。剩 4 件（task 2 / 11 / 35 / 37）素材已核清（各 5 主图 + ≥4 详情、前 4 张详情源图唯一、`detail_ready`），**每件还需生成 9 张图**（共 36 张），要花生图额度，等确认再动。

### T-20261114-015 · 194-76 · 妙手清单逐件对照：6 件不在妙手／不可证历史定案／5 件素材已核清就绪

- 状态：**done（诊断闭环）**，零商品写入。本轮把「blocked 里还有哪些能自解」彻底定量化，结论是：**自动路径已到边界，剩下 5 件需要生成 45 张新图**（要花生图额度，等人确认）。
- ① **task 12 的 `page_timeout` 是结构性的，不是瞬时抖动**。重试一次仍停在 `_mark_control('edit_button')`；随后用**对照实验**定性：同一路径同一输入框，搜确定在妙手的 `3850071893537325881` 得 `商品信息 (1)` + `edit_button count=1`，搜 task 12 的 `3850071781591351757` 得 `商品信息 (0)` + `暂无数据` + `共 0 条`，再搜对照又回到 `(1)` → **搜索机制有效，这件商品不在妙手**。它的妙手基线不可能存在，`rebaseline` 永久不可达，只能保持 blocked。
- ② **把队列 61 件逐件拿去妙手搜了一遍**（`work/rebaseline-20261113/harvest_inventory.py` → `miaoshou-inventory.json`，命中 0 时自动重试一次）：**55 件在、6 件不在**——task **12 / 22 / 33 / 36 / 46 / 52**。其余 5 件本来就有更精确的阻塞理由（22/46/52 = 抖店草稿或驳回；33 = 主图仅 3 张；36 = 商品已彻底删除），妙手无行只是同一事实的另一面。**task 36 的已知结论「已删除」正好交叉验证了这套判据有效。**
- ③ **9 件 `external_work_requires_rebaseline` 定案（经 Codex 第三轮咨询）**：task **1 / 3 / 4 / 6 / 8** 读得通、双端一致，但历史证据的 `stage` 是 `editing / completed / official_readback_complete / saved_and_verified` 且 `status` 全为 `None`，**不能安全归为任一种结案结论**。Codex 结论原文：「这 5 件都不能安全归为 `prior_revision_confirmed`，应保持 blocked。新鲜双端快照证明当前两端内容一致且可作为基线，但不能替代对历史保存、提交和读回状态的证明。」→ **不自动归类、不自动恢复**，也不加 `stage` 关键词白名单（那等于放宽闸门）。这 5 件需要人工核实历史版本。
- ④ **task 13 / 57 / 58 的「读不全」已被证伪**：探针直接打印妙手原始响应条数——task 13 `pic=3 / desc=21`（主图 3 张）、task 57 与 58 `pic=5 / desc=2`（详情 2 张）。**是素材确实不足，不是读取器漏读**。写入器要求正好 5 主图 + 至少 4 详情，这几件只能靠补源图，不能靠改代码。
- ⑤ **5 件 `needs_agent` 的素材已逐件核清就绪**（`work/materials-20261114/`，双端新鲜快照 + 原图落盘）：
  | task | 商品 | 妙手主图/详情 | SKU | 详情源图前 4 张唯一 |
  |---|---|---|---|---|
  | 2 | 男士平角内裤 | 5 / 22 | 25 | ✅ |
  | 11 | 男童直筒休闲裤 | 5 / 7 | 32 | ✅ |
  | 35 | 银丝洗碗布 | 5 / 16 | 9 | ✅ |
  | 37 | 桌下抽屉收纳盒 | 5 / 15 | 2 | ✅ |
  | 40 | 磁吸扫把簸箕 | 5 / 4 | 24 | ✅ |
  五件的妙手/抖店标题与 `resource_key` 序列两侧完全一致，`detail_status=ready`，且**前 4 张详情源图在整个序列中各自只出现一次**（task 7 卡住的 `writer_detail_source_collision` 在它们身上不成立）。写入器就绪性实测 `writer_ready=true`（三品验收记录完好、`WRITER_REVISION=multi-field-20261030-v5`）。
- ⑥ **本轮唯一剩余动作**：每件需要 5 张新主图 + 4 张新详情（共 45 张，走 `builtin-imagegen` 图生图 + 逐张目视审查）。这是**花钱的动作**，未擅自开始。

### T-20261114-014 · 194-76 · 两处「读不全」实抓到真因并修复／恢复 2 件

- 状态：**done**，有商品侧实质进展但**未写任何商品字段**。零商品写入：只读采集 + 队列状态流转。
- ① **先纠正上一轮的错误结论**：Codex 审查指出「SKU 表格只渲染 7 行、详情槽位固定 28 是平台上限」证据不足，我核实后确认**确实错了**——同一套采集代码在 25 / 32 / **56** 个 SKU 的商品上读全过。于是回实页定位真因，而不是继续给结论打补丁。
- ② **SKU：真滚动容器是 `.ecom-g-table-tbody-virtual-holder`**。表格是虚拟列表，`scrollHeight 2707 ≈ 24 × 113px`、clientHeight 523，只挂载 6–7 行；`#goodsEditScrollContainer` 只是把整块内容移进视野，**滚它行键一个都不变**（107–112 恒定），改 `holder.scrollTop` 才换行（300→109-115、600→112-118、900→114-120、1200→117-123）。修复：JS 新增 `op='scroll_rows'`（半页步进、到底回绕），Python 在「ready 且无占位行」时走这条。**校验强度未降**（16 位 SKU、唯一可见 input、跨轮冲突拒绝）。
- ③ **详情：后 9 张是懒加载没触发**。37 个缩略卡片都在，但卡片 28–36 的 `<img>` 停在 1×1 占位 GIF（`loading="lazy"`，真实地址等进视口才写入）。关键实测：对**第一张未加载卡片**做一次 `scrollIntoView`，`28 → 37 一次全部加载`；只滚整块没用，块内部也没有滚动容器。修复：`op='scroll'` 在 `kind='details'` 时改滚第一张未加载卡片，`wait_details` 每轮 nudge 一次；仍要求 `declared == slots == cards`。
- ④ **实测结果**：task 40（24 SKU）与 task 35（9 SKU）双端 `SKU PASS + official_validate PASS`，**已恢复 `blocked → needs_agent`**。task 7（56 SKU / 37 详情）读取也全过了，但撞上 `writer_detail_source_collision`——前 4 张详情有重复原图，妙手按图查找替换会同时改多处，**写入器不支持逐位置替换**。这是写入契约限制，不是读取限制，仍 blocked 且原因已如实更新。
- ⑤ **验证**：JS 15 项（新增 3 项 `scroll_rows`：半页步进 / 到底回绕 / 无 holder 时不报错）、`test_editor.py` 10 项（新增「每轮 nudge 一张未加载详情」）、`test_official_sku_codes.py` 21 项（新增「无占位行时走 `scroll_rows`」）、`test_workflow + test_title` 130 项全过；适配器仍零反斜杠。
- ⑥ 队列：`blocked 40 → 38`、`needs_agent 3 → 5`、`verified 18`。下一轮可继续处理 `external_work_requires_rebaseline` 里剩下的件——它们的阻塞理由需要逐件重查，**不要再假设是「页面硬上限」**。

### T-20261113-012 · 194-76 · 队列恢复实操：3 件重新基线成功／结案契约补齐／两处「读不全」的机制辨析

- 状态：**done**。Agent workbuddy，2026-11-13 凌晨。未调用 Codex。**本轮解开的是「队列停摆」而不是新功能**：43 件 blocked 里 14 件标着 `external_work_requires_rebaseline`，但此前从来没人真跑过 `batch rebaseline`，也没人验证过它到底能不能处理这 14 件。
- ① **先查清队列为什么会停**：`products.id`（数字主键）才是 `--task-id` 认的值，**不是抖店商品 ID**；`external_observations.task_id` 同样指向数字主键。用商品 ID 去查会得到「0 条观察证据」的假结论。这 14 件其实各有 1–2 条观察证据，前置条件（`baseline_hash`/`artifacts_path`/`upload_map`/租约）全部干净。
- ② **第一次真跑 `batch rebaseline` 连撞两个页面层问题**（都不是 rebaseline 的契约问题）：
  - 🔴 **Ego 把每个 Page 钉死在 `state.viewport`（本次 904×788）**。妙手 `quick_edit` 的「查询」按钮实测 `left=1017`，而 `visible()` 的判据里有 `r.left >= innerWidth → false` → **控件明明存在、却被判成不可见**（报错是「未唯一定位」，很容易误判成页面改版）。修法：把任务空间 `state.viewport` 调到 1440×900。**视口是被 Ego 复用的固定值，页面不会自己适配**。
  - 🔴 **全屏 `op.jinritemai.com` 组件 iframe 会拦截整页点击**：实测一个 `1440×900 / z-index:10000 / pointer-events:auto` 的 iframe（`appId=7641889070456782908&cId=524`）覆盖整个妙手页，`document.elementFromPoint` 永远返回它 → 所有控件的 `actionable` 都是 false。它不是页面内容，**刷新即消失**（SPA 路由切换会把它留下）。
  - 采集顺序改为**先妙手、后抖店**：抖店侧 `_stable_doudian_snapshot` 自己会开 `Emulation.setFocusEmulationEnabled`，能容忍后台页；妙手侧的可见性判定依赖真实布局，必须前台。
- ③ **恢复 3 件成功**：`task 2`（3850072900438720563 男士内裤）、`task 11`（3850071893537325881 男童休闲裤）、`task 37`（3848317504447447331 桌下收纳盒）→ `blocked → needs_agent`，`target_version` 与历史保留不变。每件都是**双端新鲜快照 + 逐条观察证据结案**：妙手 5 主图 / 5·7·15 详情、抖店同数量且 `detail_status=ready`、标题与图片 `resource_key` 序列两侧完全相等、`verify_miaoshou_skus` 通过。
- ④ **结案契约补齐（`rebaseline.py`，经交叉审查后收紧两轮）**：历史 agent 把同一个结论写成了不同字段名，原契约只认 `status == 'not_attempted'` 和 `(stage=='verified' and status=='accepted')` 两种精确组合，导致 11 件即便证据明确也永远结不了案。新增两条**等强或更强**的判定（`unknown` 一律不结案）：
  - `saved is False` **且** 计数（`saveAttempts`/`saveCount`）**至少存在一个且全部为明确的非负整数 0** **且** `uploadsStarted` 为假 → 视为 `no_save_attempted`（真实样本：`{'phase':'upload_unknown','saved':false,'saveCount':0}`）。🔴 计数缺失、`None`、负数、布尔、字符串 `"0"`（`"0" <= 0` 会直接抛 `TypeError`）**一律拒绝**；`uploadsStarted=True` 也拒绝——素材可能已经传到妙手侧，不能笼统算「什么都没发生」。
  - `submission_state == 'verified_by_readback'` → 视为 `prior_revision_confirmed`（这是队列自己的终态，比 `accepted` 更强）。🔴 但 `submission_status` 与 `submission_state` **同时存在时必须一致**：任一为 `unknown` 或两者冲突（如 `accepted` + `unknown`）一律不结案，不允许字段顺序决定答案。
  - 测试参数从 7 个扩到 **17 个**（`tests/test_rebaseline.py`，32 项全通过）：新增 `saved_none` / `saved_negative` / `saved_str_zero` / `saved_no_counter` / `uploads_started` / `status_conflict` / `status_unknown_pair`，全部**必须失败**。
- ⑤ 🔴 **两处「读不全」已定位并修复（先经 Codex 交叉审查撤回错误结论，再实抓到真因）**：
  - **SKU 表格在这两件商品上只挂载 6–7 行**。商品 `3848316916011762046`：API 返回 **24 个 SKU**（全部 `sku_status=true`、24 个不同 `spec_detail_ids`），DOM 里 `tr[data-row-key]` 只有 6–7 行；滚动 `#goodsEditScrollContainer` 到 3704（到底）行数不变；视口高度 900→2600（`innerHeight` 2889）行数仍 7；点「全屏」只从 7 变 8。商品 `3848317566716084561` 9 个 SKU 同样只读到 7 个。
    🔴 **「7 行是平台上限」这个结论是错的**（同一套采集代码在 25 / 32 个 SKU 的商品上读全过），而且 **2026-11-14 已定位真因并修好**：表格是虚拟列表，真正决定挂载哪些行的是 **`div.ecom-g-table-tbody-virtual-holder` 的 `scrollTop`**（`scrollHeight 2707 ≈ 24 × 113px`，clientHeight 523），而 `#goodsEditScrollContainer` 只是把整块内容移进视野——**滚外层容器时行键一个都不变**（实测 107–112 恒定），改 `holder.scrollTop` 才换行（300→109-115、600→112-118、900→114-120、1200→117-123）。修复：JS 新增 `op='scroll_rows'`（半页步进、到底回绕），Python 在「ready 且无占位行」时走这条路径；**校验强度未降**（16 位 SKU、唯一可见 input、跨轮冲突拒绝）。实测 24/24 个编码读全，task 40 双端快照 `SKU PASS` + `official_validate PASS`，**已恢复 `blocked → needs_agent`**。详见 `docs/dropship-page-contracts.md` ③。
  - **详情槽位停在 28**。商品 `3850072398019821856`：`detail_declared=37`、`detail_cards=37`、`detail_slots=28`。**2026-11-14 已查清并修好**：37 个缩略卡片都在，但**后 9 张的 `<img>` 停在 1×1 占位 GIF**（`loading="lazy"`，真实地址等卡片进视口才写入）→ 前 28 张有图、9 张永远不加载 → `declared≠slots` → `ambiguous`。关键实测：对**第一张未加载卡片**做一次 `scrollIntoView`，`28 → 37 一次全部加载`、状态转 `ready`；而只滚整个「商品详情」块不管用（块内部没有自己的滚动容器）。修复：`dom.js` 的 `op='scroll'` 在 `kind='details'` 时改滚第一张未加载卡片，`wait_details` 每轮 nudge 一次；校验仍要求 `declared == slots == cards`。
  - 结论：**task 35 / 40 已恢复（`blocked → needs_agent`）**。**task 7 仍 blocked，但原因变了**：详情与 SKU 现在都读全（37/37 详情、56/56 SKU、`details_equal=true`、`SKU PASS`），卡在 `writer_detail_source_collision` —— 前 4 张详情存在重复原图，妙手按图片查找替换会同时改动多处，**写入器不支持逐位置替换**。这是**写入契约的限制，不是读取限制**，也不该再用「平台读不到」解释。
- ⑥ **队列账（2026-11-14 03:08 实读）**：`blocked 40 → 38`、`needs_agent 3 → 5`、`verified 18` 不变（本轮恢复 task 35、40；加上 11-13 的 2/11/37 共 5 件）。`task 36`（3848317525922283791）是 `doudian_product_deleted`，策略里已归 `closed`（不再重试），但**没有受支持的命令把它移出 blocked**，所以仍计入 38；这不影响执行，只是统计口径。
- **验证**：`pytest tests/ -q` 全量通过（进度条 `[100%]` 全程无 `F`/`E`）。⚠️ 本轮同一回合里反复跑之后变成 `39 failed, 681 passed`，逐个查全部是 **safe-delete 守卫撞线**导致的假失败：失败文案里带 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` 且断言是「`browser.lock` 应不存在」，而**单独跑 `tests/test_workflow.py` 仍 55 passed**；同一提交早期全量是全绿的。判据与处理写进 `docs/dropship-policy.md` ⑬（换一个回合再跑以重置计数）。新增/改动：`rebaseline.py` 结案判断、`tests/test_rebaseline.py` 3 个新参数。
- **工具**：`work/rebaseline-20261113/`（`read_pair.py` 双端采集、`make_proof.py` 出 proof、`run_batch.py` 批量、`probe_*` 四个只读探查）。

### T-20261112-011 · 194-76 · 类目必填属性程序化补齐并发布（真写商品）／锁与删除健壮性修复

- 状态：**done**。用户实值授权「生产企业就写1688上家就行，保质期12个月」→ 落到商品 `3853482303460343870`（家清纸品>除臭用品>空气清新/净化/芳香剂）上，**真写、真发布、平台真审核通过**。本轮是本项目第一次由程序写属性并提交审核（此前只到「复制产生草稿」）。
- ① **抖店类目属性有第三种控件形态：数值＋单位复合控件**。此前只认「纯文本」「纯单选/多选」，所以 `保质期` 一直判不出来。实测 DOM：`styles_measureValue__BknXC > styles_measureContainer__AF_AJ > styles_measureTemplate__AfVoo`，数值是 `input.ecom-g-input.styles_value__QXqGx`，单位是 `ecom-g-select`（候选 `天/月/年/个月`，默认预选 `天`）。**平台会预选单位**，所以「单位标签存在」≠ 该属性已填——旧 missing 启发式把默认值「天」当成值，**漏判**（真实缺陷）；平台自己的必填进度 50% 正好证明平台也认为它没填完。新增 `kind='measure'`、读回 `number_value`/`unit_value`，并把 missing 判据改成「**只有数值非空才算已填**」。
- ② **单位下拉是 portal 渲染的**，不能靠 class 找；靠 combobox input 的 `aria-controls="rc_select_N_list"` 精确定位 listbox id（新增 `attribute_unit_options` op）。单位候选必须**在真实候选里校验存在**，否则拒绝写。
- ③ 🔴 **真正卡住 `--apply` 的不是浏览器，是删除守卫**：WorkBuddy 的 safe-delete 守卫按「单次工具调用内累计删除次数」计数，阈值 50，而 CLI 每条浏览器命令净删 **2 个文件**（`transport.lock` + `pending-command.json`）→ 一次几十条命令的 `--apply` 必撞线；守卫拦截时抛的是 **`SystemExit`（不是普通异常）**，把 `Lock.__exit__` 的 unlink 打断 → 三个锁文件全部残留（内容是已死 PID）→ 之后每次运行都报 `busy`，**永久死锁**。前两次 `--apply` 就是这样失败的（现场：PID 5600 的 `browser.lock`/`job.lock` 残留）。
- ④ **修法不是绕过守卫，是让删除次数归零**：① 传输锁改用 **OS 级咨询锁**（`msvcrt.locking` / `fcntl.flock`）——进程退出时由系统自动释放，**结构上不可能留下死锁**，且零删除；② `pending-command.json` **不再删除**，下一条命令直接覆盖（它的作用是「上一条操作是否已结算」的闸门，不删也能保持该语义：结算成功→放行，结算不了→继续拦）；③ 文件锁 `Lock` 增加**死进程锁自动回收**：读 PID → `process_alive` 为真则仍拒绝（活锁绝不抢占），为假则**用改名（原子、不是删除）接管**，旧文件留死 PID 下次照旧回收；④ `Lock.__exit__` 的 unlink 失败**不再致命**。守卫的计数是「每次工具调用」级别，所以同一轮里 npm test＋pytest 连跑也会被 pytest 自己的临时目录清理顶到 55 → 与本项目代码无关。
- ⑤ **真跑结果（`--apply`，一次成功，43 秒，未被守卫打断）**：只读预览先确认 `生产企业名称`（text，current 空）与 `保质期`（measure，number 空、unit 预选「天」）**均可写**；填写后平台必填进度 **50% → 100%**；`fields.json` 读回 `生产企业名称=明丞生物科技有限公司`、`保质期=12个月`（number=12 / unit=个月）；`submission.json` = `accepted / success=true / rejected=false / errors=null`；页面出现过平台原文**「商品提交成功」**。任务落 `stage=saved`、`submission_status=accepted`、`verified_by_readback=true`。
- ⑥ **平台侧独立复核（不靠自己的任务文件）**：商品已**不在草稿箱**（`product_id_not_in_draft`）→ 确实提交了；商品管理页状态分类 tab 的 id 是 `rc-tabs-0-tab-*`（`all/onSale/sellOut/offline/forbidden/releaseRecord_in_progress/releaseRecord_fail/releaseRecord_success`），逐个点开核对：**「审核通过」分类里有它 —— 送审时间 2026/11/12 16:40:39、通过时间 16:41:03**；「审核驳回」里是**另一件 10/28 的商品**（低价SKU作弊），不是它。
- ⑦ **当前状态与口径**：商品行显示「**已下架**」，点「查看原因」＝「**商家自主下架**」，行内操作有「**上架**」。这与本项目其它两件（`3853454064050373417`、`3848315275342643596`）**完全同款**：审核通过时间 == 下架时间 == 商家自主下架。所以「发布商品」这条路径的终态是「**审核通过但未上架**」，**不是**售卖中。⚠️ 别把「已下架」读成「被平台驳回」——「查看原因」给的就是「商家自主下架」，审核驳回是另一个分类、另一件商品。
- ⑧ **一条必须说清的事实提示**：用户授权的 `生产企业名称=明丞生物科技有限公司` 是**1688 上家（供应商）名**，不是核实过的生产方。若该上家是贸易商，抖店审核阶段可能要求改成实际生产方——本次审核已通过，但**上架前值得人工确认**。这次是按用户明确指示照写的。
- **验证**：717 Python（191.97s，新增 5 项锁回归）＋ 108 JS（新增 7 个 measure 用例，`tests/dom-measure.test.cjs`）。新增 `tests/test_locks.py`：死锁自动回收／活锁绝不抢占／锁内容异常不删／**释放被拦（SystemExit）不打断流程且下次可恢复**／咨询锁互斥且零删除／**连续 5 条浏览器命令零删除**。
- **过程中被 Ego 打断的两件事（都按文档在原空间内恢复，没换空间）**：① Ego 任务空间 ended（`ownership: user`）→ 用户已明确「接手」，按文档 `claimTaskSpace(9)` 接管原空间；② 空间里 p3（编辑页）渲染进程卡死、`info()` CDP 超时且 `page.close()` 关不掉 → 用 `Target.getTargets` 找到 targetId 后 `Target.closeTarget` 在浏览器层强制关闭，再把死页从 runtime 的路由表里摘掉让它另开新页。**没有新建任务空间**。

### T-20261112-010 · 194-76 · 审核状态读取路径 / 机会商品落地页契约 / 复制历史全量采证（无商品写入）

- 状态：**done**。用户「登陆了你接手吧」→ 接手上一轮被登录卡住的三项实抓，全部做完并落进代码。全程**只读**：没有创建/修改/删除任何商品（点「立即铺货」后回查抖店草稿箱，仍是原来那 1 件）。
- ① **审核状态的权威读法找到了**：抖店草稿箱是**独立页** `https://fxg.jinritemai.com/ffa/g/draft`，**不是**商品管理页的 tab（tab 只有 全部/售卖中/已售罄/已下架/已封禁/审核中/审核驳回/审核通过；页面副标题里的「草稿箱」只是文案）。入口是 tab 条右侧一组**文字链接** `编辑记录 / 草稿箱 / 回收站`（`span.style_textLinkNew__ziNsA`，在视口外，要先滚动才点得到）。按 ID 过滤的正确参数是 **`product_id`**（T-008 当年用 `searchText`，所以永远「共 0 条」——是查询方式错了，不是商品不存在）。**两页互斥**：已提交商品只在商品管理页（状态词售卖中/已下架/审核驳回/审核中），草稿商品只在草稿箱（状态词「待提交」）。
- ② **跨系统词汇对照（6 个商品实测）**：妙手「审核不通过」＝抖店「审核驳回」；妙手「上架中」＝抖店「售卖中」；妙手「未提审」＝抖店「待提交」。落地为 `DropshipPages.read_target_review_status()`（先商品管理页、后草稿箱）+ 只读 CLI `dropship product-status --product-id <ID>`，并接进 `verify_target_readback`：`platform_review_status` 命中就进 `verified_aspects`，两页都查不到就如实写「无法确认审核状态」——**不再写成「未提审」**（那是妙手侧用词，含义是「从没提交过审核」，与「商品不存在」「已删除」都不是一回事）。上一轮那句「需到商品列表页人工确认」是事实但做错了动作，现在自动做。
- ③ 🔴 **机会商品「立即铺货」的旧结论被推翻**：上一轮写「这条路径不能独立证明商品身份，卡片上没有 1688 offer ID」——**卡片层确实没有，但点击之后有**，两条独立通道：① DOM：点「立即铺货」弹出**同页抽屉**（URL 不变），抽屉里来源商品行带 `http://detail.1688.com/offer/<ID>.html`；② 网络：前端提交 `POST /api/v2/move/batch/fetchDetailUrlInfo`，请求体 `detailUrls=<同一 offer 链接>&copyType=ddClue&clickType=copyProduct`，响应 `productList[<ID>]` 带 `source:1688`、标题、图片、库存；同批还有 `dsCenterUserReviewStat` 的 `copyType=ddClue`。所以机会路径的来源身份是**精确的 offer ID**，不必靠标题去 1688 人工检索。旧实现一直失败的真因是**时序**：它在 `.click()` 后同步检查「下一步: 开始复制」，而抽屉是异步渲染的（实测「下一步」约 2.5s、offer 链接约 4.3s 才出现）→ 必然报 `click_result_not_confirmed`。现改为轮询等待（最多 40×250ms），并新增 `read_opportunity_source_identity()`（只读已开的抽屉）。抽屉开了却拿不到 offer 链接时返回 `layout_changed / offer_identity_not_found`，**不返回 ok**。
- ④ **复制历史全量采证**：这页是 vue-recycle-scroller 虚拟滚动 + 分页器（每页 20，共 3 页），一次只挂载 19~20 行 DOM —— **读一屏就是 20/58**。滚动容器是 `div.content-main`（不是 window），且虚拟列表只在滚动**过程中**换行，一次性滚到底会漏中间段。正确采法＝点 `.el-pager > li:nth-child(N)` 翻页 → 每页从 0 起按 **150px 步长**细滚并逐步累计 → 回顶补一次；去重键用「源ID+商品ID+时间」。落地为 `collect_history_rows_all_pages()` + 只读 CLI `dropship history-dump`，实测 **`共 58 条` → collected=58、complete=true**。
- ⑤ 🔴 **行解析器四处真实缺陷修正**（每条都有真实反例）：类目正则 `([^\n\r]+)` 在**单行折叠**形态下会把整行吞成类目；供应商只认「名称（店铺名）」，58 条里有 **8 条是纯名称**（`瑞安市激濠五金商行`、`孕产批发`…）被丢；源ID 只认 `源ID：`，漏了 `翻新复制` 行的 `新源ID：`；状态词全表扫，妙手侧「审核通过」与抖店侧「审核通过」混在一起，统计出「未提审+审核通过+已下架」这种三词组合。现按**商品ID 的位置**分成 `platform_states` / `platform_audit_state` / `miaoshou_audit_state`，多行与单行两种形态解析结果必须一致（已有断言）。
- **全量 58 条的真实分布**：类目 47 个（前三：收纳筐/收纳篮 3、厨房储物架 3、挂钩/粘钩 3）；复制类型 1688分销 58 / 翻新复制 1；抖店商品状态 已下架 30 / 上架中 14 / 草稿箱 1 / **无状态列 14**；抖店审核状态 审核通过 23 / 未提审 21 / 审核不通过 1 / **无 14**；妙手侧审核 审核通过 34 / 无 25；失败原因只有 1 条（即那件缺保质期/生产企业名称的）。⚠️ **14 条「无状态列」说明：缺失就是缺失，不能拿妙手侧状态缺失反推抖店侧状态**（那 14 件在抖店商品管理页里其实是有状态的）。
- **验证**：712 Python（新增 14 项；198s）＋ 101 JS ＋ **38/38 Node 真跑**（新增 9 个用例：商品管理页状态、草稿箱状态、两页各自的 wrong_page、同一 ID 两行判结构变化、机会点击拿到 offer ID、无 offer 身份不许算成功、抽屉来源身份读/读不到、虚拟滚动全量采集）。
- 文档：`docs/dropship-page-contracts.md`（第十三轮实抓）、`docs/dropship-policy.md`（⑤~⑧ 四条策略）。
- **本轮仍需人工的一件事**：商品 `3853482303460343870` 在抖店草稿箱是「待提交」，缺**保质期 / 生产企业名称**（类目 `家清纸品>除臭用品>空气清新/净化/芳香剂` 的必填项）。人工补值后提审即可。供应商名 `明丞生物科技有限公司` 只是参考线索，**不能照抄**当「生产企业名称」。

### T-20261112-009 · 194-76 · 掉线闸门 / 规格名数量标记 / 人工待办原因分类（无商品写入）

- 状态：**done（代码与只读能力全部落地并验证）**，但**有三项浏览器工作被登录卡住**，见「本轮被人工卡住的一件事」。
- 用户指令「除此之外」「继续」→ 先盘点当前代码与真实页面证据，再定下一批可自动推进的事项。
- 🔴 **开局就撞上真故障**：浏览器会话已过期，抖店与妙手**都跳到** `https://fxg.jinritemai.com/login/common?...`。实抓三个入口（妙手机会页/妙手历史页/抖店商品列表）全部落登录页，正文含只有登录页才有的「收不到验证码」「手机号停用或忘记」。**掉线只能由人重新登录**，程序不能代登录。
- ① **会话掉线闸门**（新增）：`DropshipPages.check_session()` 判据＝URL 路径以 `/login` 开头 **或** 正文含登录页专属文案，且域名属于抖店/服务市场。`_advance` / `_stage_settings` / `_stage_copy` / `_readback_only` 在每个导航后先查，掉线立刻抛 `dropship_login_required` 并说明「请人工重新登录，程序不会代登录，也不会在登录页上重放写操作」。以前掉线只会在几分钟后报「当前页面不是预期的XX页」，**根因被埋**。新增只读自检 `dropship session-check`（`--navigate` 可先进妙手页再查）。
- ② **规格名从「永远未验证」变成可判定**（`_check_spec_identity`）：旧判据是「规格名集合相等」，妙手两次真实铺货都改写了展示名 → 这条在真实页面上几乎从不成立，长期挂在 `unverified_aspects` 当噪音。改成问可判定的问题：**来源规格里的数量标记还在不在官方规格名里**。真实样本「4个装」→「极氪车门限位器-4个装」、「生物酶除臭剂【2500ml】送喷壶」→「2500ml（生物酶除臭剂）」，标记 `4个装`/`2500ml` 都保留 → `matched` 进 `verified_aspects`；无数量标记（如「红色」）如实报 `partial` 无法核对；标记对不上报 `mismatch`。后两种**不阻断** `copy_confirmed`（定价公式才是强证据）。
- ③ **类目白名单不按关键词扩**（实测反例）：队列里两件同样带「免打孔/壁挂/吸盘」的商品，缺的属性完全不同——「浴室免打孔不锈钢吹风筒收纳架」缺**安装方式**，「轻奢风浴室吸盘置物架…免打孔壁挂塑料」缺**尺寸**（安装方式反而被填上了）。说明**属性集合由抖店类目决定**，铺货前拿不到最终类目 → 结论写进 `OBSERVED_MISSING_ATTRIBUTES` 只作人工分诊参考，**不用于自动推断或拦截**。这轮没有扩白名单，是**有证据地不扩**。
- ④ **复制历史行里三个采到却没用的字段现在用上了**：真实行文含 `发布类目：家清纸品>除臭用品>空气清新/净化/芳香剂`（完整类目路径）、渠道行下一行的 `明丞生物科技有限公司（明丞生物科技有限公司）`（来源供应商/店铺）、状态词 `草稿箱`/`未提审`。`parse_history_row_facts` 解析后进人工补值清单：类目直接可读，供应商名**只作参考线索**（抖店要的是「生产企业名称」，供应商可能是贸易商，不能照抄）。
- ⑤ **人工待办报告加原因分类**：43 件 blocked 的真实分布＝重新基线 14 / 必填属性缺失 8 / 图片槽位不足 6 / 视觉质量 5 / 草稿或驳回 4 / 待真实参数 2 / 商家编码不完整 2 / 商品已删除 1 / 详情源冲突 1，并标注该谁处理（`machine_retry` 4 件可程序重跑，其余只能人工）。属性观测统计：安装方式 6、尺寸 3、硬度 3、适配基面类型 2、承重 1、材质 1、适用年龄 1、适用作物生长阶段 1。🔴 **口径修正**：这份报告旧版是 23 项，其中 5 项是「（原文未列出属性名…）」这种**占位名**，其实不是属性缺失（`doudian_draft_or_rejected` 的 `missing_fields=[]` 等）；现在只列**真能解析出属性名**的，实际 **18 项**。少的那 5 项不是漏了，是本来就该去掉。
- 🔴 **Node 验证器第二次抓到转义坑**：新写的登录态判定用了正则 `/\\/login(...)/`，Python 源码里两个反斜杠、浏览器拿到一个（合法），但 `tests/verify_adapter_js.py` 取的是**源码原文**，Node 看到两个 → `Invalid regular expression flags`，整段 JS 语法错误。已改成**零反斜杠**写法（`pathname.startsWith('/login')` ＋ 登录页专属文案）。教训固化进契约文档：**适配器里的 JS 不要依赖 Python 字符串的转义，含反斜杠一律不写**。
- **本轮被人工卡住的一件事**：浏览器会话过期 → **机会商品「立即铺货」落地页契约、抖店商品列表审核状态读取路径、复制历史全量滚动采证**这三项无法实抓。已确认它们都只需重新登录后即可继续，代码侧不需要先改。🔴 **这三项已在 T-20261112-010 全部做完**（登录恢复后），本块的三项不再是遗留。
- **验证**：698 Python（189.87s，新增 10 项）＋ 101 JS ＋ 29/29 Node 真跑。提交见本块下方。文档：`docs/dropship-page-contracts.md`（第十二轮）、`docs/dropship-policy.md`（三条被实测推翻/加固的策略）。skill 三处同步，哈希 `f435244a…`。

### T-20261112-008 · 194-76 · 选品候选 / skill 编排 / 人工待办汇总（只读，无商品写入）

- 状态：**done**。用户「4 5 6 7 8 不需要人工的你继续推进，有问题问codex」→ 落地；**按授权就 skill 编排设计派了一次 Codex 只读咨询**（`work/optimizer-20261111/codex-skill-design-out.md`）。本轮**没有创建/修改/删除任何商品**。
- **① 选品候选**：实抓 `/selection/opportunity_product` 确认它就是**抖音官方机会商品页**（官方上新扶持/豆包商机品/推荐理由热度高·成交增速快·平台缺货），30 张卡片有 `a.title` / `.price-number` / `.tag-text` /「支持密文」/「商机：xxx」/ `[data-custom-id]`。新增只读适配器 `read_opportunity_candidates` + CLI `dropship candidates`，默认只留同时「支持密文+一件代发」。真跑读出 5 条候选。🔴 **卡片没有 1688 offer ID，只有妙手内部 UUID**，返回值固定带 `identity_note` 声明「不能直接铺、需以标题检索并人工核实同一商品」。「推荐理由」是页面筛选项不是逐卡字段，没有编造成候选属性。
- **② skill 编排层**：Codex 只读咨询建议**新建** `dropship-workflow`（三个既有 skill 分别管「改版现有商品 / 批量图文 / 妙手手工编辑」，铺货是「从来源创建」，塞进去会混淆授权边界）。已落盘 `skills/dropship-workflow/SKILL.md`，含适用范围、选品、价格确认（提醒 300% vs 3 倍差 100 倍）、阶段语义、失败关闭、人工确认点、禁止事项；**不写选择器/DOM/内部字段**（C 方案抽象边界）。同步到仓库 / `~/.workbuddy/skills/` / `~/.codex/skills/` **三处哈希一致** `4afc4b39…`，既有三份 skill 未动。顺带修了 CLI 里过时的 help（原写「写配置与复制尚未接入」）。
- **③ 两条线打通**：`build_manual_queue_report` + CLI `dropship manual-queue`，把铺货任务的 `manual-attributes.json` 与 `batch.sqlite3` 里因属性缺失 blocked 的商品汇成一张**只读**待补值表。真跑：默认 23 项全来自队列；带临时 `--data-root` 时 25 项（23 队列 + 2 铺货：3853482303460343870 的保质期/生产企业名称）。不改队列状态、不解锁、不写页面、不推断值。
- **④ 口径修正与代码清理**：`navigate_source` 曾被重复定义 3 次，已清为 1 份；HANDOFF 抬头同步到 2026-11-12 / workbuddy；**更正上一轮不准确说法**——队列 61 件＝18 verified/43 blocked（实读 `batch.sqlite3`），其中明确 `required_attributes_missing` 只有 **8 件**，其余是重新基线 14、图片槽位、视觉质量、草稿/驳回预检、商品已删除等，不可笼统归为缺属性。
- 🔴 **三项有证据地不做**（`docs/dropship-candidates-and-orchestration.md`）：①**审核状态读取** — `ffa/g/list` 确有状态词与商品ID搜索框，但填入 ID 查询返回「共 0 条」、草稿箱 tab 精确定位失败，路径未证明可用，**不写适配器**，`unverified_aspects` 那条保持；②**规格名改写规则** — 只有 1 个对照样本，不归纳，继续用价格排序对应（3.48 运费差已验证）；③**类目白名单扩展** — 本轮无新失败观测，不凭类目名猜必填属性。
- **验证**：688 Python（191.67s，新增 3 项）+ 101 JS + 27/27 Node。提交 `050e30a`。文档 `docs/dropship-candidates-and-orchestration.md`。

### T-20261112-007 · 194-76 · 按事实推断落地：类目预检 / 补值清单 / copy_confirmed

- 状态：**done**。Agent workbuddy，2026-11-12 凌晨。用户「你根据事实推断呢」→ 我给出五条推断 → 用户「可以你加吧」→ 落地。未调用 Codex。
- **核心判断**：端到端跑通后，剩下的阻塞**不是浏览器自动化**，是三个设计错位。所以本轮**一行页面选择器都没改**，改策略层。
- **① 类目预检**（`src/doudian_auto/dropship_policy.py`）：`KNOWN_CATEGORY_ATTRIBUTES` 记实测类目→必填属性（当前 `空气清新/净化/芳香剂` → 保质期/生产企业名称）；`RISK_KEYWORDS` 标题预警但 `basis` 明确标 `keyword_heuristic`（铺货前拿不到抖店最终类目，**只是预警不是证据**）。`_stage_copy` 最前面 `require_precheck_allowed` 拦截高风险，除非显式 `--allow-risk`。**命中时不创建商品**，不往草稿箱堆垃圾。CLI 新增 `--source-title/--category/--allow-risk`。
- **② 人工补值清单**：从复制历史行「保质期,生产企业名称」未填写解析属性名，`build_manual_attribute_list` 写 `manual-attributes.json`，**值一律 null、来源标「人工填写」**，不替人猜。`_readback_only` 发现新增行时自动产出并附进结果。真实产物已生成在 `ds-final` 任务目录（2 条）。
- **③ 终态改名 `verified` → `copy_confirmed`**：旧终态要的「SKU 总数」「审核状态」在官方编辑页**结构上不存在**（不是没抓到），规格名还常被妙手改写 → 永远不可达。新终态只声明能证明的，并新增**可自动判定的强证据**：每个 SKU 的 `售价 − (源价×倍数+加价)` 差额相同且非负（=运费）。规格名按**价格排序做位置对应**，不按名字匹配。真实数据 25.8→85.88 / 43.8→139.88，差额都是 **3.48**。报告分 `verified_aspects`(4) / `unverified_aspects`(3)，后者如实交人工、不阻断。
- **真跑验证**：
  - 旧任务 `dropship-922368518409-eea919c37defc94b` 重跑 apply → **`copy_confirmed`**，运费 3.48，4 条已验证 / 3 条未验证（SKU总数、审核状态、规格名改写）
  - 高风险标题 prepare → `risk: high / basis: keyword_heuristic / action: block`；apply → **`dropship_category_risk`，未点复制、未创建商品**
  - 真实历史行生成 `manual-attributes.json`：保质期、生产企业名称，值均为 null
- **兼容**：`WRITE_FORBIDDEN_STAGES` 与 `record_copy_observation` 仍接受旧 `verified`，历史任务不失效；终态不可回退。
- **边界**：类目白名单目前只有一条实测类目 + 关键词兜底，扩展应基于新观测不要猜；`copy_confirmed` **不表示可售/已审核/已上架**，只表示「复制产生了这个商品且定价符合公式」。
- 文档 `docs/dropship-policy.md`。**验证**：685 Python（189.36s，新增 12 项）+ 101 JS + 26/26 Node。提交 `06b924d`。

### T-20261112-006 · 194-76 · 铺货端到端闭环真跑通（解锁自动复制）

- 状态：**done**。Agent workbuddy，2026-11-12 凌晨。**未调用 Codex**（用户要求自己干到底）。
- **🔴 解锁关键**：复制历史页 `input[name="sourceItemId"]` + 「查询」按来源筛选。不筛选时「共 59 条」/虚拟滚动只挂 8 行，基线无法证明完整；筛选后 `共 0 条` 或 `共 1 条`，判据「筛选值==本来源 且 共N条==匹配行数」才承认 `baseline_complete`。`read_history_product_id` 也要求筛选态并用 `baseline_keys` 排除旧行，只认新增行。
- **完整闭环真实跑通**：`prepared → settings_verified → unknown → copied → verification_pending`。
  - 任务 `dropship-922368518409-eea919c37defc94b`（酒店生物酶除味剂，1688 `922368518409`，店外新品：历史筛选共 0 条）
  - `apply #1`：写配置→重新进页独立读回→`settings_verified`（pricePercent 300/300/300、放入仓库）
  - `apply #2`：读来源规格（2500ml ¥25.8 / 5000ml ¥43.8）→筛选历史→贴链接→抓取（成功1/跳过0）→落复制意图→**真点「下一步: 开始复制」**
  - `apply #3`：筛选历史、基线排除→`copied`，新商品 **3853482303460343870**，类目「家清纸品>除臭用品>空气清新/净化/芳香剂」
  - `apply #4`：官方页读回 SKU `85.88 / 139.88`（=源价×3+5+运费3.48）、`price_progress 100`，`verification_pending`
- **停在 verification_pending 是正确结果**，reason 如实列出三条：页面无独立 SKU 总数、妙手改写规格名（「生物酶除臭剂【2500ml】送喷壶」→「2500ml（生物酶除臭剂）」）、编辑页无商品审核状态。不假装 verified。
- 🔴 **真实业务结果：商品进了草稿箱，不是仓库。** 复制历史原文「『保质期,生产企业名称』未填写，导致复制失败，系统自动放至草稿箱 / 草稿箱 · 未提审」。搬家配置虽设「放入仓库」，但抖店类目必填属性缺失时妙手按配置自动放草稿箱。**抖店类目特有属性源头没有，只能人工补**——与本轮之前 9 件缺属性商品的结论一致。
- **本轮新增 4 个真跑才暴露的页面事实**（全部已修）：①抓取成功且跳过为 0 时页面**隐藏「跳过」计数器**，只显示「成功：1」，原轮询要求两计数齐全导致永远超时、真没点成复制；②`_readback_only` 进官方编辑页后没等渲染就读 SKU 得到 0 行被误报 `layout_changed`；③草稿箱 SKU 行有规格价文本 `￥85.88/2.5L`，价格仍须读 `input.value`；④`navigate_official` 后需等十几秒。
- 完整报告 `work/optimizer-20261111/FULL-LOOP-RESULT.md`；十一轮实抓契约 `docs/dropship-page-contracts.md`。
- **遗留（非程序缺陷）**：商品 `3853482303460343870` 需人工补「保质期 / 生产企业名称」后提审；妙手改写规格名，若要让「规格名一致」成为可自动通过判据需先实抓改写规则或改用「SKU 数量+价格公式」核对；审核状态需到抖店商品列表页另取。
- **验证**：678 Python（192.02s）+ 101 JS + 26/26 Node 真跑。提交 `85d4b15` + `41fe57d`，已 push。

### T-20261111-005 · 194-76 · 铺货程序化：四轮 Codex 复核 + 编排层接通

- 状态：**done（程序化 v1，端到端复制动作未真跑）**。Agent workbuddy，2026-11-11 深夜～11-12 凌晨。
- **Codex 四轮复核**（`work/optimizer-20261111/codex-review-v{1..4}-out.md`）：一轮 2🔴6🟠、二轮 3🔴2🟠、三轮 5🔴、四轮 2🔴3🟠1🟡。每轮「Codex 出结论 → 我审查 → 修 → 落盘 → 真跑验证」。
- **已落地**：`dropship.py` 任务层（价格试算/配置审计/写入闸门/unknown 不重试/终态不回退/复制意图与历史基线/核验）、`dropship_pages.py` 页面适配层（10 个方法，单次 evaluate 完成「重识别→唯一校验→执行→即时读回」）、`_advance` 编排层、CLI `dropship prepare/apply/verify`、`tests/verify_adapter_js.py`（19 个 Node 真跑用例）。
- 🔴 **两个只有真跑才暴露的 bug**：①`_stage_settings` 把 multiplier=3 直接写进页面 `pricePercent`（页面是百分比应为 300），**曾把妙手共享配置改成 3%**，已改回并独立读回确认 `300/+5/放入仓库`；②抓取是异步的，读一次计数器拿到 null 被误判失败，改为有界轮询。均修于 `621df75`。
- 🔴 **验证器的根本缺陷**：Node stub 自造了 `tr` 行，与真实页面自洽通过；实抓发现复制历史是 `vue-recycle-scroller`，行容器是 `div.pro-table-custom-body-row`，`tr` 里只有日历残留 → 适配器**在真实页面永远返回 0 行**。已把 stub 换成实抓抄录的真实 cell 文本。教训：**stub 必须来自实抓**。
- 🔴 **页面契约九轮实抓**（`docs/dropship-page-contracts.md`）：结果页只有「跳过/成功」两计数器，**没有独立失败计数**；官方编辑页**没有商品审核状态**（「已上架」是 SKU 角标，「上架/下架」是表单选项）；官方页 `tr` 是真数据行、历史页 `tr` 是日历；1688 来源 SKU 在 `div.module-od-sku-selection`（两个 `item-price-stock`，第一个是价、第二个是库存）；42 条存盘源链接**全是 http**。
- **预期 SKU 循环依赖的解法**：复制前官方页还没有商品，所以预期来自 **1688 来源页规格**（实测 4个装¥6 / 1个装¥2），核验只比**规格名集合**——售价含运费尾数，与批发价本就不等（6→27.48）。
- **真实页面跑通**：`prepare`（http→https 规范化）、`apply` 第一阶段（写配置→重新进页独立读回→`settings_verified`，audit 300/300/300）、`apply` 第二阶段（读来源SKU→采基线→贴链接→抓取→闸门）。第二次 apply 正确被拦：「成功 0 / 跳过 1，未点复制」——该商品此前已铺过，**没有重复铺货**。
- **未跑**：点「下一步: 开始复制」→ 读新增历史行 → 推进 copied → 官方页核验。原因：需要一个**店外新品**，而 1688 搜索页串页/反爬拿不到稳定候选；且这一步会真的创建商品，不该在四轮复核结论出来前硬跑。
- **🔴 四轮复核结论：当前版本不能自动点复制，这是设计上的诚实状态。** 实抓发现复制历史页明写「**共 59 条**」，而虚拟滚动 DOM 只挂载 **8 行**，51 条未渲染——本来源的旧记录可能藏在里面，复制后会被误认成「本次新增」。已落地 `baseline_complete` 判据（total_records / rendered_rows），编排层遇到不完整直接抛 `dropship_baseline_incomplete` 拒绝复制。**要解锁必须实抓「来源ID 筛选框」让本来源行全部进视口**，没证据前不猜选择器。
- 四轮另修：`_readback_only` 现在真的调用 `verify_target_readback`（之前 copied 永远无法到 verified）；官方编辑页读不到审核状态是已知事实，改为列一条待核验原因停在 `verification_pending`，不抛错也不假装通过；unknown 只能跟随已落盘复制意图；抓取轮询绑定页面身份并显式 `timed_out`；来源 URL 改在 Python 侧解析校验。
- **验证**：674 Python（179.94s）+ 101 JS + 19/19 适配器 Node 真跑。提交 `84c7dfb`→`3c0df2f`→`35555c5`→`621df75`→`9612acf`（含 docs `8a0790e`/`e00796c`/`c7554bb`/`ad4da09`/`e821925`），已 push。

### T-20261111-004 · 194-76 · 机会商品铺货闭环成功 + Codex 定集成方案

- 状态：**done（单件闭环）**。商品 `3853454064050373417`（极氪001/007车门限位器）已铺进**仓库**，`已成功复制`、待审核、已下架。Agent workbuddy，2026-11-11 22:21。
- **流程**：妙手搬家配置（价格 ×300%+5、放入仓库、库存跟来源）→ 机会商品页筛「一件代发」+「支持抖音密文」→ 卡片「立即铺货」→「下一步: 开始复制」→ 妙手/抖店双端核验。完整记录 `work/optimizer-20261111/DROPSHIP-RESULT.md`。
- **价格实读核对**：源2→售15.48、源6→售27.48（=源×3+5+不包邮运费4.48）。库存跟来源（源头就是888888占位）。
- 🔴 **误判教训**：SKU 行 innerText 的「888888」是**库存显示值**不是价格，价格必须读 `input.value`。我一度误报价格异常。
- **Codex 结论：选 C**（程序提供原子能力 + skill 负责编排）。三层：铺货任务层（持久化 source/offer/配置快照/目标商品ID）/ 页面适配层（每页窄接口，返回结构化观测）/ 流程编排层（阶段迁移+人工门槛）。**页面漂移对策=页面契约+失败关闭**：每次动作一次 evaluate 完成「重识别→唯一性校验→操作→即时读回」，不唯一就停止不扩大匹配。
- **初版边界（Codex 明确）**：只做单件、价格公式执行前展示源价/公式/最终价由人确认、只允许「放入仓库」（自动立即上架排除在外）、审核与消费者端只读报告不推断、异常商品停止交人工。
- **需新增**：独立铺货任务状态机（prepared→settings_verified→copied→warehouse_created→verified）、offer 级占用/去重、搬家配置前后值审计与恢复、新商品期望值清单（标题/类目/价格/库存/主图/详情/SKU）。
- **复用**：browser/job 锁（只清死进程锁）、unknown 写入结果禁止自动重试、错误保留现场、双端读回。
- 报告全文 `work/optimizer-20261111/codex-dropship-review.md`。**铺货程序化尚未实现，此为方案评审。**

### T-20261111-003 · 194-76 · 9件缺属性源头核查

- 结论：`安装方式/尺寸/厚度/硬度/适用年龄` 是**抖店类目特有**，1688 属性区根本没有（实测5件不同类目）。代码 `source_facts.DOUYIN_ONLY`/`needs_human()`，文档 `docs/source-attribute-limits.md`。两陷阱：件重尺是包装尺寸非商品尺寸；标题「免打孔」≠选项值。
- 🔴 **发现并隔离1件已删除商品** `3848317525922283791`（抖店返回「商品不存在或已彻底删除」）→ `quarantine_product`。**队列会失真，需定期核对商品是否还存在。**
- 2件源商品已下架；详情图非参数来源。资产：42件源链接、6件源参数、7件真实选项集。615 Python/101 JS。`ab6cab0`+`7796abb`。

### T-20261111-002 · 194-76 · 商品50属性补全，已提交审核

- 商品 `3848315275342643596` 三项属性已写入，`publish_state: pending`（审核中）。**纠正 T-008「平台拒绝发布」的误判**：那5项是蓝色info未来规则，程序当error所以没点发布；实跑被接受，那5项从未拦发布。今日「失败」真因是「商品信息审核中，不可编辑」（操作ID 20261111164420C51C8F2F449DDBE5FADA）。写 安装方式=免打孔式/是否进口=否/型号=吸盘毛巾架，均1688源证据。613 Python/101 JS。`3019cb5`。

### T-20261110-009 · 194-76 · Codex实跑：属性发布及双端读回通过

- 状态：review（属性阶段完成，整套换图/上架未验收）；Agent codex-live-one，2026-11-10→11。用户完成授权后接回原Space20，销霁百货商品41/3848316465015030183依据原标题及20个贴片款SKU补安装方式=免打孔式。
- 修复3个实页缺陷：SKU重载后详情预览不挂载；蓝色info被当成表单错误；CDN地址轮换被当成换图。新增notices、沿用有序resource_key比较、失败读回先落盘；未知/错误alert及真实图片变化仍阻断。代码49e2f24。
- 正常属性任务仅发布一次受理，submitted后恢复只读→saved/verified_by_readback；官方新页必填100%，妙手新页同属性，原标题、5主12详及全20SKU一致。status仍1下架；startSaleType 0→1按既有preserve_warehouse_v1记录，checkStatus 1→7/页面审核通过，其他保护字段匹配。
- 原队列仍44 blocked/17 verified，两件unknown及WorkBuddy50的editing未动；本轮没有换图或上架，不计入三品新上传Writer验收。22官方可读但妙手精确ID/店铺查询及单品同步后仍0条，暂不编辑。
- 正式preflight对blocked的22/41/28全部跳过，不能把live_preflight总标签当逐品实读；独立官方原读22必填100%/5主19详/4SKU、28仍缺安装方式。下一步需明确正式恢复路由，再验收完整9图；不手改队列状态放行。
- 验证：591 Python、101 JS通过；[验收说明](docs/live-attribute-acceptance-20261110.md)，本机原证据work/codex-live-one-20261110/及~/.doudian-auto/jobs/attributes-3848316465015030183-f4eb30ca5f9b/。
- 现场已持久化RESULT及双端证据，Space20自有p1/p2/p3已finish关闭，不再续该已结束空间；其他用户页保留。Linear194-76记录及读回、代码/交接分提交并push，父任务保持in_progress。

### T-20261110-008 · 194-76 · 属性发布首次实页验收（结论已被 T-002 纠正）

- 状态：done（已被 2026-11-11 实跑取代）。商品50。此处保留仅因它是那三个缺陷的来历。
- 修3个缺陷：①**读回值带 option id**（`text(selects)` 含隐藏id，读回 `"466329 免打孔式"` 永不等于目标 → 该路径此前不可能成功）改为读 `.ecom-g-select-selection-item`；②新增 `attributes` 单品入口；③新增 `--abandon --reason`（仅页面确认目标属性为空才释放 editing 僵局）。附带修 title 分支 `UnboundLocalError`（分支内重复 import Bridge/Editor 造成局部名）。
- ⚠️ **当时结论「平台拒绝发布」是误判**：那5项蓝色 info 是未来规则提示，程序误当 error，根本没点发布。真因见 T-20261111-002。
- 证据 `work/optimizer-20261110/`。587 Python / 99 JS。
### T-20261110-006 · 194-160 · 自动入口与Ego标签修复

- 状态：done（代码及离线回归）；新属性发布路径与失效页恢复尚待指定商品/实页验收，不能冒称已线上验证。未操作浏览器或真实商品，原61件队列未改状态。
- commander/CLI：先读facts再按已有内容合并模板，格式坏则保留；默认正式preflight分批实读，--plan仅队列分类；旧记录与fresh区分，未知任务readback-only、ready走原Writer，门槛不放宽；--apply明确shop，每轮写入预算生效，未决错误停调度、动作后写检查点及最终报告。
- attribute_workflow.py：独立不可变属性任务，同browser/job锁及同商品占用检查；仅已确认的空文本/单选，完整SKU在填前/提交后采集；精确屏蔽目标属性后比较其他保护字段、标题/图片及非目标属性，先落submitting/unknown再发布一次，受理后新页核验；同资料未知只读，不同资料不能绕过占用，editing中断保留现场。
- ego_runtime.mjs：活动页及路由缓存按实时自有tabs校验；显式navigate可建新页，已关闭活动页的写动作直接失败，不转移到其他存活页、不重放写入。dom.js默认采集不变，属性任务才按唯一类目字段排除目标。
- 启动run.bat改明确选择只读/执行，不按资料文件非空擅自发布；使用说明与批量skill新增auto-commander参考，不再宣称全部卡点均非程序问题或无人值守已完成。Codex/WorkBuddy批量skill同步、结构/链接/改动文件SHA256通过。
- 验证：最终完整585 Python通过（170.34s），98 JS通过；随后报告来源标记及首次会话初始化补充31项专项通过；新会话只初始化一次，已有状态/目录不重建。覆盖资料覆盖、错误资料保留、新鲜预检、未知只读、写入预算、属性一次发布/丢响应恢复/非目标变化、失效缓存及不误写他页。证据work/auto-repair-20261110/。
- 收尾：运行修复142ae0c，交接单独提交并push origin；HANDOFF/T-ID映射及194-160回写读回。真实验收需明确单品对象和动作后进行，不重存既有verified或unknown商品。

### 项目目标与设计

本项目把抖店现有商品的标题、5 张方主图和标准详情图替换做成可恢复、可审计的本地工作流：确认店铺和商品身份、读取原始基线、准备并审查素材、逐槽上传、预览后提交，最后重开页面读回比对。默认不改类目、品牌、SKU、价格、库存等商业字段。提交受理不等于平台审核通过或消费者端生效。

设计优先保护商品身份、避免重复提交与静默覆盖。证据不足时阻断，不猜测商品属性；写入结果不确定时先只读核查。

### 当前状态（2026-11-10 核对）

- **浏览器通道**：`src/doudian_auto/bridge.py` 中 `DEFAULT_ENDPOINT='ego'`，CLI 未传 `--endpoint` 时走 Ego 原生通道。Kimi 仅通过显式本机 HTTP endpoint 兼容接入。`is_native_endpoint()` / `normalize_endpoint()` 是原生通道判定入口。
- **队列快照**：查询 `C:\Users\19431\.doudian-auto\batch.sqlite3` 的 `products` 表，共 61 件。`state`：`blocked=44`、`verified=17`。`submission_state`：`not_attempted=42`、`unknown=2`、`verified_by_readback=17`。两件 `submission_state='unknown'` 同时为 `state='blocked'`；`state='unknown'` 为 0。后续执行前重查。
- **测试商品**：`3853110071722639434`（「测试商品请勿购买-自动生成勿下单」）是 Ego 写入/发布验收的产物。**已于 2026-11-10 01:45 下架并复核**：列表行显示「已下架」、行内按钮为「上架」、列表仍计 57 件（下架不删除）。它在 01:27 建成草稿、01:36 发布提交受理、01:45 下架。**须待办**：是否删除该测试品。注：旧 HANDOFF 里「未发布未上架」是建稿当时的状态快照，已过时。
- **本轮修复**：活动标签及路由缓存已按实时自有tabs校验；导航可建立替代页，写动作丢失活动页则停止，不重放。资料文件保留、自动调度与独立属性发布见下方T-20261110-006；本轮仅离线回归，未执行线上商品写入。
- **验收边界**：旧 HANDOFF 记有 Ego 只读验收通过、测试商品写入/发布提交链路跑通；这不证明审核最终通过，也不能外推到所有商品和类目。证据索引见历史摘要。

### 关键约束：保护什么

- **状态机分层**：队列 `products.state` 是工作进度，`submission_state` 是提交结果，不能把两个字段的 `unknown` 混为一谈。批量与单品流程状态不同，迁移逻辑以 `batch.py`、`workflow.py` 为准。
- **提交 unknown 禁止重发**：超时或响应丢失时，平台可能已收到提交。重试可能造成重复发布/覆盖；代码将结果保留为 unknown 并限为只读核查，需用读回证据裁定。
- **锁**：单品流程持有共享 `browser.lock` 和任务 `job.lock`；批量写入也持有共享浏览器锁。锁防止本程序任务并发争用浏览器/商品，但不覆盖人工直接操作妙手。`unlock` 仅清理所属进程已退出的锁。
- **rebaseline**：人工外部改动会让旧基线过期。必须重新读真实商品并确认身份、图槽和内容，避免旧基线覆盖他人修改或把变化误判成任务目标；不能为解阻塞而直接改状态或盲目重建基线。
- **writer_ready 三品门槛**：正式 writer 需要至少 3 个不同商品完成规定的双端读回验收。`browser_ready` 只代表浏览器可用，不能证明写入可靠；此门槛避免从单品或只读成功外推通用写能力。
- **批量素材门槛**：目标版本要求 5 个主图槽和 4 个新详情槽；基线需 5 张主图、至少 4 张详情。代码校验槽位与哈希。其余尺寸、体积、标题规则应以 `materials.py`、`title.py` 当前实现为准，不沿用未经核验的旧数字。
- **停机条件**：店铺/商品身份不符、属性来源不足、槽位不完整、读回不匹配或提交结果未知时停止写入；提交超时先 verify，不自动重发。

### 新人阅读顺序

1. `AGENTS.md` → 本文“当前状态”和“关键约束”。
2. `git status --porcelain`，确认变更归属；阅读当前 Linear Issue 与授权范围。
3. 阅读 `skills/doudian-product-workflow/references/environment-and-facts.md`（解释器与脚本路径、事实 JSON、RAG 参数）、`docs/agent-workflow/T-ID-MAPPING.md` 及 `docs/miaoshou-reliability-20261029.md`。
4. 按任务读 `src/doudian_auto/batch.py`、`workflow.py`、`bridge.py`、`rebaseline.py` 和对应测试；追溯历史时再查归档。
5. 操作前重查 SQLite、浏览器就绪状态、素材与基线，不复用本文数字快照。

### 常用命令

命令入口由当前 CLI、`pyproject.toml`、`package.json` 核实；写入命令只在授权、预检通过后使用。

🔴 **全局参数必须放在子命令之前**（`--json`、`--endpoint`、`--version`），放后面会被当成子命令参数而报错。连接优先级：`--endpoint` > `DOUDIAN_BRIDGE_URL` > 默认 `ego`。

```bash
.venv/Scripts/python.exe -X utf8 -m pytest -q      # 约 3 分钟；2026-11-10 实测 558 passed
npm test                                            # 93 passed
doudian-auto --help
doudian-auto --json doctor                          # 不传 --endpoint 即走 Ego 原生
doudian-auto --json read --url '<编辑链接>' --shop '<店铺名>' --out before.json
doudian-auto --json prepare --assets '<素材目录>' --title '<新标题>' --url '<编辑链接>' --shop '<店铺名>'
doudian-auto --json upload '<job_dir>' --dry-run    # 只出计划
doudian-auto --json upload '<job_dir>' --apply      # 真写入页面
doudian-auto --json submit '<job_dir>' --apply
doudian-auto --json verify '<job_dir>'
```

### 全部 17 个子命令：哪些只读、哪些会写

**只读（随时可跑，不碰商品）**

| 命令 | 作用 |
|---|---|
| `doctor` | 查本地服务/扩展/安装 |
| `resolve` | 编辑链接或商品 ID 转稳定标识 |
| `products` | 读当前商品列表（只读当前页，不翻页） |
| `read` | 读编辑页快照 |
| `jobs` | 列出最近任务 |
| `status` | 检查任务与素材版本 |
| `verify` | 重读保存结果，不发布 |
| `browser` | 只读页面检查入口 |
| `title check` / `title diagnose` | 标题本地校验与诊断，不联网 |
| `batch status` / `batch preflight` | 看进度、素材前只读预检 |

**会写入（必须先预检 + 明确授权）**

| 命令 | 作用 |
|---|---|
| `prepare` | 建立可恢复任务（只落本地，不碰页面） |
| `upload --apply` | 替换标题/主图/详情，留在编辑页预览 |
| `submit --apply` | 发布已上传任务并重开核验 |
| `title apply --apply` | 只改标题并发布 |
| `batch run --apply` | 按队列串行写入妙手并双端核验 |
| `batch repair-title --apply` | 受理后标题仍旧时的单次补救 |

**恢复 / 隔离入口（出事时用，别自己造轮子）**

| 命令 | 什么时候用 |
|---|---|
| `batch quarantine` | 商品已有编辑或保存结果未知，保留原占用并按正式隔离规则处理 |
| `batch reconcile` | 导入已有操作证据并隔离，防止重复写入 |
| `batch rebaseline` | 外部改动让基线过期，需用双端完整证据核清 |
| `batch recover-prepared` | 尚未上传/保存的合格素材任务，用两轮只读证据恢复 |
| `batch recover-read` | 只读页面无响应，凭审计证明关闭一次（**仅原生 Ego**） |
| `batch resume` | 续办未提交或只读核查任务 |
| `abandon` | 人工确认页面后放弃该任务对商品的占用 |
| `unlock` | **仅**清理所属进程已退出的锁 |

🔴 恢复类命令的共性：都要求**先有证据**（两轮只读、审计证明、双端核对）。没有证据就想恢复＝绕过闸门，这是本项目最忌的操作。

## 数据与算法

- 单品流程主线：`prepared → editing → uploaded → submitting → submitted → saved`；失败与恢复分支以 `workflow.py` 为准。批量流程另有 `needs_agent / agent_claimed / ready / editing / uploaded / submitting / submitted / verified / blocked` 等状态。
- 写动作获取锁后重读持久状态。提交可能已送达但结果未知时不重试；verify/readback 负责核验。
- 批量提交前核验基线、素材哈希、目标槽位、writer 准备记录和资格；提交后重开商品页读回，匹配后才可 verified。人工改动需走受控 rebaseline。
- 本机数据根目录实测为 `C:\Users\19431\.doudian-auto`；任务素材、状态、审计证据留在本机，不提交浏览器数据、凭据或任务产物。
- 默认通道与全局参数以 `bridge.py`、`doudian-auto --help` 为准；当前默认 Ego，兼容 endpoint 仅允许本机 HTTP。

### 输出格式与退出码

- 成功：`{"ok":true,"data":{...}}`；失败：`{"ok":false,"error":{"code":"...","message":"...","waiting_human":false}}`
- 退出码：**0** 成功 / **1** 一般错误 / **3** 需用户连接或验证（别把 3 当 1 处理，那是要人去登录）
- `--json` 只写 stdout；帮助走标准 argparse 输出
- dry-run按具体命令契约：upload/submit可用--dry-run，其他命令不可机械套用。batch auto --plan不逐品预检但会检查连接；默认auto只读预检，--apply才执行对应授权动作。
- `read` / `products` 会**打开页签**但不改商品字段——别因为「开了页面」就以为要写入了

### 素材规格（`materials.py` / `jobs.py` 实测）

- 命名：`main_01`～`main_05` 各一张；`detail_01` 起连续编号 1～50 张，按数字排序
- 格式：JPEG/PNG，单张 **< 5MB**
- 尺寸：方主图**至少 600px 且必须正方形**；详情宽 **620～1290px**
- SHA256 禁止重复图片；标题 16～60 平台字符（**汉字计 2**）
- 批量目标：5 主图槽 + 4 详情槽 = 9 槽

### 任务目录与锁

- `~/.doudian-auto/jobs/<商品ID>-<内容哈希前12位>/` 存 manifest、state、before/uploaded/readback JSON 及成功截图
- manifest 绑定**绝对路径、文件哈希、商品、店铺、标题**；素材文件一改动就必须重新 `prepare`
- 每次操作串行持有 `browser.lock` 与 `job.lock`；**拿到锁后要重读状态**，防止旧进程状态导致重复发布
- 每个不可变任务用独立固定的浏览器 session（默认 Ego 原生 TaskSpace），按商品 ID 重新选取重定向后的真实编辑页

### 读回怎么算「一致」

- 发布前后比较**实际加载的保留字段**：文本/数值、checkbox/radio/switch、选择项、静态属性，以及 SKU / 3:4 图 / 白底图地址
- 图片核对要比重开后**CDN 路径及顺序**，忽略缩放查询参数；**不能只凭张数**判断一致
- 只写标题、方主图、标准详情。类目/品牌/售后必填一句变化→**立即停止**，不套用以前商品的属性
- 读回不符时保留 `submitted` 与错误证据，人工确认真实页面后处理，**不许改 state 绕过**
- 截图失败不覆盖提交事实，以新打开的保存页读回为准；消费者端生效最终由平台审核决定

### 浏览器层注意

- 默认Ego原生TaskSpace/Page；显式Kimi兼容端点走本机POST /command与GET /status。绝不自动重试可能已送达的写请求。
- 不访问 Cookie、框架内部状态或未公开业务接口
- `dom.js` 依赖实测字段：`#pg-title-input`、`attr-field-id` 的「主图」/「商品详情」、`goodsEditScrollContainer` 分区。布局变化时优先修这里，别改判据标准。
- 兼容旧素材校验脚本 `skills/.../scripts/doudian_check.py`；其 compare 读旧 `sections` 格式，CLI 读回用 `protected` 格式，**两者不能混用**

## 历史摘要

- **2026-11-10 · Linear 194-155**：Ego 默认通道只读验收、测试商品写入及发布提交链路、端点归一化独立复核完成；runtime 活动标签失效缺陷未修。证据目录：`work/ego/default-channel-check-20261110/`、`work/ego/pick-untouched-20261110/`、`work/codex-review-20261110/`（三轮外审报告）。
- **2026-11-09 · Linear 194-155 / 194-156**：Ego 默认通道切换；批量技能和商品编辑工作流文档整理。归档：`docs/handoff-history/2026-11-09-batch-skill-before-review.md`、`2026-11-09-skill-source.md`。
- **2026-10-29 至 2026-11-03 · Linear 194-76 及后续**：批量可靠性、SKU 读回、素材门槛及人工接管阶段。旧队列数字、session 和 writer 门槛快照已过期。归档：`docs/handoff-history/T-20261026-002-before-reliability.md`、`T-20261103-003-004.md`、`194-54.md`；技术说明见 `docs/miaoshou-reliability-20261029.md`。
- 其余旧任务块属于完成历史，保留于旧 HANDOFF/提交历史和上述归档，不作为当前状态依据。

## Ego 通道验收：证到了哪里

这一节单独列，因为**最容易读错**。

**Ego 默认通道已实测可用的范围**：
- 只读读回（开编辑页、认店铺、认商品、读标题/主图/详情）—— 商品 `3848322422084337743` 实测通过
- **全仓只读**（2026-11-10 实测）—— **61/61 件全部读出，0 失败**，店铺确认 61/61，详见下节
- 写入（传图、填标题、保存草稿）—— 测试商品 `3853110071722639434` 实测通过
- 发布提交受理（填写检查清零 → 发布 → 价格风控确认 → 提交成功）—— 同上，平台回「需审核通过后生效，审核周期 1-2 个工作日」

**没证到的**：
- ❌ **审核最终通过**（要等 1-2 个工作日，未观测）
- ❌ **妙手双端读回比对**（测试商品不在妙手队列，无法比对）
- ❌ **全仓写入**。不是通道问题——队伍里 17 件已 verified 不许重存、44 件 blocked 卡在属性/图槽/基线，通道切换不会补齐商品事实或证据；当前也存在运行时与调度缺陷，不能把全部阻塞都归因为缺资料。
- **Writer状态以当前execution_readiness为准**：历史三品证据与运行时就绪分别记录，不能沿用旧“未满足”快照，也不能凭文档断言实时已就绪。

### 全仓只读实测（2026-11-10）

| 项 | 值 |
|---|---|
| 队列 / 读取成功 | 61 / **61**（0 失败） |
| 店铺确认 | 61/61 |
| 主图 5 张 | 54 件（**7 件不足**：4 张 3 件、3 张 4 件） |
| 详情图 | 范围 **2–37 张**，**7 件不足 4 张** |
| 草稿态 | 0 |
| 平台驳回 | **3 件** |

**必须处理的 3 件驳回**：`3848315195902525900`（长柄沐浴刷）、`3850071781591351757`（宠物除臭喷雾）、`3850072322857894188`（行李箱轮子保护套）。驳回未处理前，任何写入都不生效。

🔴 **采集方法教训**：详情图是异步渲染的。直接用 `editor.read()` 会读到假的「详情 0 张」——实测同一件商品 `read()` 读 8 张、`wait_details()` 读 14 张。**必须用项目自带的 `editor.wait_details()`**（轮询 `detail_status` 到 `ready`/`empty`），别自己写采集循环。证据见 `work/ego/all-queue-readonly-20261110/`。

**已修**：端点判定收敛（全仓 6 处裸比较 → 统一走 `is_native_endpoint`）。Codex 三轮复核结论「可交付」。
**已离线修复，待实页回归**：本轮活动页与路由缓存都按实时自有tabs校验；只在显式navigate建立新页，失效页写动作停止，不转移或重放。见T-20261110-006的98项JS回归记录。

<!-- 核对说明（Codex 起草，WorkBuddy 核实并修正）
- Codex 核对过：HANDOFF.md、AGENTS.md、docs/handoff-history/ 清单、bridge.py、batch.py、workflow.py、ego_runtime.mjs、rebaseline.py、materials.py、title.py、pyproject.toml、package.json。
- Codex 实测：`pytest -q` → **558 passed in 173.60s**；SQLite `products` 按 state/submission_state 分组查询。
- WorkBuddy 复审修正了 4 处：
  1. 原稿带 UTF-8 BOM，已去掉（否则部分工具首个标题会失效）。
  2. 原稿把 `environment-and-facts.md` 的路径写成 docs 下，**该位置不存在**；实际在 `skills/doudian-product-workflow/references/`，已改。
  3. 原稿把测试商品列为「待人工核实 / 记录冲突」——已实测：**已下架**（行状态「已下架」、按钮「上架」、列表 57 件）。所谓冲突只是旧文档同时保留了 01:27 建稿时和 01:45 下架后两个时点的快照。
  4. 补上「全局参数必须在子命令前」这条实操坑，以及 `npm test` 实测值。
- WorkBuddy 复核通过、未改动的：队列 61 件分布（state 44/17、submission_state 42/2/17）与实测一致；`DEFAULT_ENDPOINT='ego'` 属实；`is_native_endpoint` 已全仓收敛；`prepare/upload/submit/verify/read` 参数与实际 `--help` 一致；素材规格 5 主图+4 详情=9 槽、主图≥600 方图、详情宽 620–1290、<5MB 均与 `materials.py`/`jobs.py`/`batch.py` 一致；writer_ready 三品门槛见 `batch.py:1284`。
- 待人工决定：是否删除测试商品 `3853110071722639434`（现为已下架，仍在列表计数内）。
-->

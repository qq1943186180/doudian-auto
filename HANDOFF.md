# 抖店本地上传

更新：2026-11-11（Asia/Shanghai）；当前执行：codex-live-one。旧主体由Codex起草、WorkBuddy核实，本轮修复及验证以最上任务块为准。执行前仍须重查仓库和本机状态——本文数字是快照，不是实时值。

## 给人的说明

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

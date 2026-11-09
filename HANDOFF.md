# 抖店本地上传

更新：2026-11-10（Asia/Shanghai）；Agent：workbuddy-skill-optimize。
源码：C:/Users/19431/Documents/ChatGPT/抖店/doudian-auto；当前分支 codex/miaoshou-reliability-20261029；私有 origin https://github.com/qq1943186180/doudian-auto。

## 给人的说明

### T-20261110-003 · 194-155 · Ego 发布链路端到端验收（同一测试商品走到提交）

- 状态：done；承接 T-20261110-002 的草稿，补齐必填并**真实发布**，Ego 默认通道的写入链路至此全覆盖（建→传图→填→检→发布→提交受理）。
- 补 3 项必填：硬度=`软`（下拉仅软/硬）、材质=`PP`（选项含榉木/PP/塑料/鬃毛/木/PC/塑料丝/马毛/尼龙丝/合金）、价格=`0.01`、库存=`1`。
- 🔴 **踩坑：价格填错位置**。页面上方「批量设置」也有 placeholder 为「价格」的输入框，填它不算数；必须填 **SKU 行内**的「价格」框（同一 placeholder，靠 `tr` 内含规格文本定位）。
- 填写检查三轮：2 错误（硬度/材质）→ 1 错误（仅价格）→ **0 错误**，类目属性必填进度 100%。
- 发布链路：点「发布商品」→ 弹「发布提醒·请确认价格」（0.01 元触发资损风控）→ 点「去确认」**仅关闭弹窗不发布** → 再点「发布商品」→ 点「**不修改，继续发布**」→ **「商品提交成功，需审核通过后生效，审核周期1-2个工作日」**。
- 读回：列表商品总数 **56→57**，该行显示「售卖中 ￥0.01 库存1」，质量分 85。
- 平台风控提示（均已确认可忽略）：价格过低可能资损；缺主图视频；无达人秀/讲解回放。
- 未证明：妙手双端读回（该商品不在队列）；审核通过后的最终生效（需等 1–2 工作日）。
- 证据：work/ego/pick-untouched-20261110/{RESULT.json 含 publish_stage, shot-ready-to-publish.png, shot-publish-success.png, shot-list-published.png}。本轮无生产代码改动。
- ⚠️ **收尾待办**：测试商品现为「售卖中」，须下架/删除，避免真实买家误购。

### T-20261110-002 · 194-155 · Ego 默认通道写入链路端到端验收（新建测试商品）

- 状态：done；**首次证明 Ego 默认通道可真实写入抖店**，非只读。用户选定「新建测试商品」方案（零风险），授权保存。
- 产物：新建草稿商品 **ID 3853110071722639434**，「测试商品请勿购买-自动生成勿下单」，状态待提交，创建 2026/11/10 01:27:35，**未发布未上架**（平台明示草稿需发布后才在线上生效）。
- 链路：打开空白创建页 → 切旧版表单 → 上传 2 主图 + 1 详情 → 填标题（31/60）→ 点「确认信息，继续生成」（质量分 85）→ 填写检查 → **保存草稿 success=true** → 草稿箱读回确认「共 1 件商品」。
- 素材：work/ego/pick-untouched-20261110/test-assets/，1280×1280，取自商品 3848316392042529194 的真实原图（main-1/main-2/detail-1）。
- 🔴 **安全事件（已阻断，0 写入）**：`/ffa/g/create` 与编辑页**同路径**，仅靠 `?product_id=` 区分。首次取图时带了 product_id=3790019980637110699，页面变成该**在售商品编辑页**；识别标题框非空（`hasPid=true`）后立即关闭，未做任何写入。以后打开创建页必须校验 `hasPid=false` 且标题为空。
- 🐛 **发现 runtime 缺陷（未修）**：`ego_runtime.mjs:114` 的 `let page=task.page(state.active)` 在空间内所有标签关闭后仍返回 truthy 空壳，导致后续 `navigate` 必失败并报 `page p1 was closed`。本轮通过直接改 `state.json` 把 active 指向新标签绕过。建议后续修：`state.active` 失效时改为 `task.newPage()`。
- 未证明：未点「发布商品」，发布链路未验；未走 SKU/价格库存写入（草稿缺硬度/材质/价格三项必填）；未做双端读回比对（草稿不入线上列表）。
- 证据：work/ego/pick-untouched-20261110/{RESULT.json, create-fill.json, save-draft.json, test-assets/, store-list.json 56件全量}。本轮无生产代码改动，无新增测试。
- 收尾：测试草稿保留待用户决定删除（草稿保存15天自动清理至回收站）；空间9页面保留未 finish。

### T-20261110-001 · 194-155 · Ego 默认通道只读验收（商品 3848322422084337743）

- 状态：done（只读验收通过，**0 写入 0 保存**）；用户指定该商品验证新默认通道。因该商品队列为 `verified` / `submission_attempts=3`，按「已 verified 不重存不重传」硬约束，**改为只读读回验收**，不跑 upload/submit。
- 通道实测：不传 `--endpoint` 即为 `ego-native`，`browser_ready=true`（ego-browser 0.6.1.13）。`products --limit 100` 成功打开抖店列表页并读回 9 行真实数据；`read` 成功打开该商品编辑页。
- 逐项比对（本次实读 vs 10-28 已核验证据）：标题一致；方主图 5 张**顺序+内容完全一致**；详情 17 张，前 4 张等于当时替换目标（4/4），尾图 5–17 与基线完全一致未被误改；`shop_confirmed=true`、`draft_loaded=false`、`rejected=false`。**判定 PASS**。
- 反面证据：`batch preflight --product-id 3848322422084337743` 返回 `eligible=false`、`state=skipped`、`reason=already_verified`、`elapsed_seconds=0.0`——未开页面即被程序挡住，证明重存路径在程序层已封闭。
- 历史轨迹（task_id=24）：10-28 15:23 提交受理 success 但读回不匹配→blocked；21:15 title-only 修复被平台明确驳回；21:52 title_batch_success_requires_readback 再 blocked；**22:05 blocked→verified**（readback 1ead7546）。三次提交才成功，属高价值成品。
- 边界：**只证明了 Ego 默认通道的只读链路**（开页/认店/认品/完整读回）。**未证明写入链路**（upload/submit/保存后读回），不得据此宣称「Ego 通道线上写入已验收」。
- 证据：work/ego/default-channel-check-20261110/{before-readonly.json, products-list.json, RESULT.json, REPORT.md, preflight-20261110-005702-b84e9c51/}。本轮无代码改动，无新增离线测试。
- 下一步：若要验写入，须另选**非 verified 且素材齐**的商品并单独授权，走 prepare→upload→submit→verify。

### T-20261109-003 · 194-155 · 浏览器通道默认切到 Ego 原生

- 状态：done；代码+文档+技能三处同步，无浏览器页面操作、无队列领取、无商品写入。用户明确要求「用 ego 不用 kimiweb」。
- 改动：`bridge.py` 新增 `DEFAULT_ENDPOINT = 'ego'`，`Bridge.__new__/__init__` 默认值由 `http://127.0.0.1:10086` 改为 `ego`；`cli.py --endpoint` 默认取该常量、帮助文案改为「浏览器通道：默认ego走Ego原生通道；Kimi兼容通道用本机HTTP地址」；`gui.py launch()` 默认同源；`doctor` 的 next 提示与 `require_ready` 人类提示去掉「Edge Kimi扩展」，改为 Ego 原生连接。`miaoshou_editor.py` 模块 docstring 同步（原文写死「uses Kimi's browser controls」）。
- 兼容保留：Kimi WebBridge 未删除，传 `--endpoint http://127.0.0.1:10086`（或 `DOUDIAN_BRIDGE_URL`）仍是完整可用路径，仍走 `Bridge` 的只允许本机HTTP地址校验。
- 测试：`tests/test_stalled_read_cli.py` 的 `test_stalled_read_cli_rejects_non_native_endpoint` 原依赖「不传--endpoint会落到Kimi」才拒绝，默认改 ego 后不再拒绝；改法是显式传 Kimi 地址再断言 `ego_endpoint_required`，并新增 `test_default_endpoint_is_native_ego` 锁住默认值。
- 验证：`doctor` 不传 `--endpoint` 实测 `bridge.running=true / transport=ego-native / browser_ready=true`（`ego-browser 0.6.1.13`，chromium 156.0.8078.48，node v24.22.1）；显式传 Kimi 地址仍返回 `browser_ready=false`（服务未启动，符合预期，非回归）。全量 **554 Python passed**（179.79s）、**93 JS passed**（npm test）。三技能 canonical / `~/.codex/skills` / `~/.workbuddy/skills` 逐文件 SHA256 全部一致。
- 顺手修复：`miaoshou-product-workflow` 此前在 `~/.workbuddy/skills` 缺失（上一轮 HANDOFF 声称三处同步，实际只有另两个技能齐），本轮已补齐并校验。
- 边界：本轮只改默认选择和文档，未跑真实 upload/submit/verify，不据此宣称线上写入已用 Ego 验收。此前所有业务结论（17 verified / 44 blocked）来自旧通道与既存证据，不回改。

### T-20261109-002 · 194-156 · 采纳 Gemini 审阅并整理批量技能

- 状态：done；仅三技能/参考文件/UI元数据和交接文档，无运行代码、浏览器、队列或商品修改。沿用明确授权，未知提交不重发；title-only真实写入仍review。
- 批量主文件中文化，前置在仓/五主四详准入、Agent与Writer职责、普通writer_ready与三品acceptance区别；恢复表链接references/recovery.md，DOM/原生/兼容细节移至references/writer-behavior.md，原详细proof/哈希/SKU/复用/视觉约束保留；补可选agents/openai.yaml。
- 三入口明确路由、跨渠道占用核对和实际锁覆盖：直接CLI/批量同DATA_ROOT共享browser.lock，人工妙手不受其保护；人工检查不是原子互斥。改正dry-run示例措辞，preflight明确重复product-id；只读旧sections compare提示明确。
- 单品保存改为state/submission串行写完并回读后再点击一次；核验表按真实productInfo.pic/name/descriptionImgList/specPrices等路径整理，SKU启用/现货和阶梯库存/编码/属性/履约/售卖状态逐项确认，不假定价格单位或DOM已读全。
- 验证：25条文档CLI示例由真实parser无执行解析；重复ID/acceptance及错误参数拒绝通过；3套canonical+5份现有安装副本结构通过，相对Markdown引用全部存在，源与安装逐文件SHA256一致；git diff --check通过。未调用浏览器/队列命令，不声称线上验收。
- 原批量主文件和为保持行数归档的T-20261029-001见docs/handoff-history/2026-11-09-batch-skill-before-review.md；本轮校验脚本在work/skill-review-2/。技能提交5e511b0；交接单独提交，push并回写194-156读回；T-ID映射已补。

### T-20261109-001 · 194-155 · 抖店与妙手 skill 优化

- 状态：done；仅技能/提示与文档，未操作浏览器、队列或线上商品。以当前代码核实 Claude 建议，保留用户既有明确授权，定义保存/发布/上架范围及提交前摘要，类目需明确授权，补属性必须有事实来源。
- 抖店主文件精简为入口和状态表；新 references/title-lifecycle.md、environment-and-facts.md 明确 review/受控试用、事实JSON、解释器与脚本路径、免费RAG参数及降级，补 submitted 结案例外，未知提交不重发。
- 妙手单品技能从已安装版纳入当前分支，保留两个参考文件，区分快速编辑人工记录与现有 miaoshou-auto-batch 程序闸门；Ego/Kimi按当前可用通道选用，旧Kimi样例仅限兼容路径。同步用户本轮结束关页约定。
- 旧主文件及本轮腾出的两个旧HANDOFF块原文见 docs/handoff-history/2026-11-09-skill-source.md；不把历史验收或旧任务数量当当前能力。miaoshou-auto-batch程序及业务进度保持原记录。
- 验证：两套canonical及三份安装副本结构有效、相对Markdown引用全部存在；离线title check/diagnose/apply dry-run通过，缺依赖提示实测退出2并明确两个scripts路径；仓库与Codex两技能、WorkBuddy已有抖店技能逐文件SHA256一致。无真实写入验收，title-only仍review。
- 提交：技能 f083cbf；交接单独提交并push origin；Issue结果回写并读回；恢复入口为本块及两个skill主文件。验证记录仅在 work/skill-optimize/，不入Git。

### T-20261104-001 · 194-76 · 妙手授权后三轮只读测试

- 状态：done（测试完成，原生稳定性未通过）；同空间4用户授权后3次新鲜非草稿读取，拖鞋架标题/5主/15详/全保护字段与旧listed_verified快照一致。原生完整打开读取退出2/3，第2轮关闭/键盘/CDP退出未完成且出现无修改提示，最终同页只读导航恢复；第3轮回商品信息再关闭成功仅单轮，不冒称修好。未改运行代码/队列/商品，无新增离线测试；证据work/ego/miaoshou-auth-test-20261104/RESULT.json、REPORT.md、round-2-result.json。
- finish一次收到空间4/p1关闭收据；列表仍显示user元数据，保留cleanup.json差异，不再次finish/抢占他用空间。已公告后归档T003/004原文，当前250行；官方3轮旧测试与本轮妙手3读不能替代写入验收。后续定位原生点击/退出与慢滚动；全仓活体17verified/44blocked，19/42旧unknown不动。页文件C:16/32GB已实查，00:42重启后生效；未证明在线迁移或完全排除OOM。父Issue继续。

### T-20261103-004 · 194-76 · WorkBuddy独立断线测试与页文件迁移

状态review：WorkBuddy独立期间确实采到Ego整树退出，原因未定、不能归因Codex；官方只读3轮通过，慢wheel仍12秒。用户后续授权使妙手本轮可读。24b436d仅改HANDOFF；页文件迁移已生效。完整历史原文见docs/handoff-history/T-20261103-003-004.md，纠正与实查见技术文档2026-11-04节；不沿用“无需重启在线迁移/完全排除内存”的过强结论。

### T-20261103-003 · 194-76 · 两品完成及异常隔离

状态done（本批）：14/30各一次9槽保存、另独立上架并双端verified；27两详情二败隔离0写，49整组预览过但正式保存未做；17verified/44blocked。四修复dd91a02/9474592/cdf1888/dd6c01d，553Python/93JS；空间31finish。原文见docs/handoff-history/T-20261103-003-004.md、技术文档及work/ego/prepared-recovery-20261103/completion-results.json，禁止重存成功/unknown或第三次生成失败槽。

### T-20261103-002 · 194-76 · 异常品分批推进

- 状态：done（本批4件，非全仓完成）；从干净d7cf6e2接续并Linear公告。起点11verified/50blocked；终点活体15verified/46blocked=61，旧19/42仍unknown各1次，不重存已verified，不第三次生成失败槽。
- session=miaoshou-exceptions-20261103、空间30已正常finish关闭3自有页，cleanup.json/state.finished=true确认；不要按30重接，其他用途页未动。证据work/ego/batch-exceptions-20261103/completion-results.json。
- 47分装瓶旧保存1次不重发，只读31.88秒通过全19SKU/9目标图/尾2详；另独立上架1次58.97秒双端listed_verified。
- 25密封罐41SKU/26杯刷2SKU/38沥水篮2SKU，必填100%及正常rebaseline/同版本领取后完成9目标槽；旧5主+详1各重新目视合格复用，共18复用/9新详情；11次内置生成含25两次单槽重做，无付费API，失败图保留。免费RAG超时重试一次后降级。
- 三个新Luna Max仅写各自素材目录，不恢复旧agent。38图片齐后agent清单整理拖延，Root中断接手source/逐图事实审核、正常validator/complete；旧prompt.md是历史生成记录和图片分工，不冒称逐张完整原始提示词。
- 25/26内容各保存1次（279.60/231.12秒），初读unknown后仅只读85.96秒双端verified；38保存1次295.33秒，暂时响应unknown后同轮只读verified。尾18/9/3详情、全41/2/2SKU及其他商业字段保持；不要重存。
- 三件各独立上架1次，58.85/49.02/46.32秒双端listed_verified，妙手status0/官方radio0/审核原值3；25首次准备读取中断0输入，观察仍登录正确店铺后只读重试通过。四件均不要重上架，消费者前端未另访。
- 14袜子9旧合格图保留、0上传0保存、无基线；两轮完整34SKU一致，官方仅4个相邻未选可选尺码列重排，妙手仅同素材CDN p3/p9轮换。195d620已推送：严格全SKU先通过后只排序该精确四开关形态，不放宽价格/SKU/缺字段；11新增含10类反例，全量471Python通过174.05秒，原生双端重复读证据通过。仍blocked，需审计恢复入口，不能手清状态。
- 后续优先14保留素材的审计续办、49重复来源逐位置替换，以及真实来源补缺属性；15/16/34/48二次素材失败仍隔离。父194-76保持in_progress；技术结论见docs/miaoshou-reliability-20261029.md。

### T-20261103-001 · 194-76 · 待审两品续查

- 状态：done；从干净2a999ee接续，验证等待记录e11a34e已推送，收尾前工作区干净且Linear已公告。用户已明确不再游戏、允许正常电脑操作；仍优先Ego原生接口。只续查10/21，没有重存或重上架5。
- 新session=miaoshou-review-followup-20261103、空间25/p1；空间14已finish没有重接。首次只读历史29110866导航转至妙手授权，30秒读取超时；确认当前登录销霁百货后，勾选原有妙手授权并确认，平台转“请先完成手机验证”（手机号尾07）。
- 用户完成验证后正常takeOver原空间25，销霁百货恢复；13:28实读29110866/29111070均完成、成功1/失败0，商品行更新成功。没有点恢复/重试保存、没有重新上传或更换基线。
- 正常readback-only用53.47秒将10/21恢复verified；标题/5主/前4详/尾1或10详/全5或18SKU/商业字段双端通过，warehouse状态1、startSaleType1、checkStatus7；内容保存仍各1次。
- 随后各独立上架1次，用41.39/46.60秒分别完成listed_verified；妙手status0、官方radio0、审核原始值3，标题/全部图片/SKU及其他商业字段保持。不要再保存或上架10/21。
- 空间25已正常finish关闭2自有页，state.finished=true/cleanup.json确认；不按25重接。证据work/ego/review-followup-20261103/{completion-results,dual-readback-results,listing-results}.json及product-10/10-listing-state.json、product-21/21-listing-state.json。
- 三品5/10/21业务结果全部完成，活体11verified/50blocked=61；全仓仍未完成，父194-76保持in_progress。没有运行代码变更，无新增离线测试；历史460Python/83JS未在本阶段重跑。get_agent_context服务端不可用，但Issue已读取；不阻塞交付。

### T-20261102-006 · 194-76 · 原生Ego推进三品

- 状态：done（三品业务结果于T-20261103-001补齐）；从干净7b90f69接续，收尾前27ae746干净且Linear已公告。该轮在用户游戏期无桌面操作，不动原8个verified/3个unknown，不第三次生成失败槽；桌面限制已由用户随后撤销。
- session=miaoshou-three-native-20261102、空间14已正常finish，关闭p1妙手/p2抖店/p3批量与历史共3自有页；cleanup.json与state.finished=true确认。不按14重接，不关闭其他用途页。
- 冻结5鞋底贴3850072589246529727、10BB夹3850071994200621373、21沐浴海绵3848323687044481622；双端标题/全图/1、5、18SKU及必填100%通过。历史5/21旧版已核验、10仅上传没保存，均以新rebaseline入口绑定所有旧观察哈希恢复同一队列版本，未清除unknown或旧保存记录。
- 0faadf7/27ae746已推送：显式native模式原生Snapshot/click/fill/upload，不改视口/焦点；方法小方框替代大label中心；初始隐藏ID/标题不当ready门槛；实际固定底栏遮挡只对该路线图槽居中，仍一次原生命中检查点击。保留全部保存/SKU/未知结果闸门。
- 27张目标图逐项验收，复用15/新生12；14次内置生成（2次新图失败重做），无付费API。10旧main4及超宽detail1-3、21旧main2伪字均单次重做；失败证据保留。5/10旧prompt缺失用受限历史清单/产品/槽位/原hash来源，21main1/2原prompt已找回；不伪造。
- 5鞋底贴本轮内容保存1次（最后执行140.63秒，前置4次0保存中断另保留），旧合格6图因MD5永久ID不变首读拒绝；新增严格qualified复用/本地hash/双端远端字节核验后仅只读恢复verified。随后独立上架1次、双端listed_verified；全1SKU/9目标图/尾7详情保持。不要重存/重上架5。
- 10发夹245.83秒、21海绵231.63秒：各9槽上传预览、保存1次。原历史29110866/29111070至00:49仍抖店审核中，当时保持unknown，未豁免审中status0/checkStatus2差异；13:28续查完成后才正常只读恢复，详见T-20261103-001。
- 该轮460Python（169.33秒）/83JS通过，skill三处同步。初次结束9verified/52blocked、1上架/2待审；后续补齐3品业务结果后11verified/50blocked。5是中断续办，不冒充3件fresh_form原生路径验收；原v5能力证据不改。
- 三件均不重存/重上架，后续全仓从其他隔离任务的具体原因继续；不得清除旧19/42/47未知记录或弱化保护比较。原证据work/ego/three-native-20261102/；补齐结果work/ego/review-followup-20261103/completion-results.json。

### T-20261102-005 · 194-76 · 官方Ego用法审计

- 状态：review（审计完成，整改/实页待办）；从干净4e13457接续，Linear已公告。用户正在游戏，本轮只查官方文档/代码/本地调用证据，没有桌面、浏览器页面或商品操作。
- 本机ego-browser skill v2.1.0已读到结束标记；官网Windows页面仍含useOrCreateTaskSpace旧示例，按当前安装版taskSpace/Page API为准，不混用。官方Space支持既有登录和不抢焦点，不能以本项目失败认定Ego天然不适合后台。
- 确认适配器过度拆分：油瓶runId0207a9ec06c3有453次独立桥接（226 evaluate/130 network/39 click等），仅该续办轮而非整件总数；与官方连续动作合批建议不符。现有snapshot命令实际读DOM文字，不是原生Snapshot；预滚动与官方原生自动滚动建议冲突。
- 视口强制模拟、逐次focus emulation/CDP与坐标点击属于允许的后备机制，扩大为默认路径是待重构设计，尚不能证明它们造成全部点击故障。应先用原生接口与真实Space布局做非业务保存对比，再保留有证据的特例；不得直接删除商业字段/SKU核验。
- finish确实结束空间并使标签失效；上一轮4页是正常主动清理（符合用户关页要求），不能当Ego自行闪退。9/12空间历史丢失原因仍未知。网页默认留页与安装版默认finish说明存在差别，按当前版及用户指令执行。
- 结论：之前推荐立即换浏览器证据不足，先纠正本项目适配器。详细审计/原生重构顺序见docs/miaoshou-reliability-20261029.md；证据work/ego/official-audit-20261102/。本轮未改运行代码、无新增测试或TaskSpace，待后续受控实页验证。

### T-20261102-004 · 194-76 · Ego关闭离线诊断

- 状态：review；从干净5b74ed0接续，已在194-76公告。用户正在游戏，明确禁止桌面控制；本轮只分析本地日志/转储、代码与离线测试，没有恢复/重启/激活窗口，没有网页操作或商品写入。
- 17:13/17:16两份dump均为0x517a7ed simulated exception；PID分别17468（gpu-process）/16976（browser），截至本轮仍在且创建时间都为11月1日22:40，排除了这两份dump代表当时进程终止的说法。不能因此确定窗口消失原因；原始转储不上传，摘要只在work/ego/ego-close-20261102/。
- Windows真实父子进程离线复现：0.15秒预算、原PIPE实耗1.594秒，新DEVNULL0.156秒。Ego调用器去掉无用PIPE并隐藏CLI窗口；不终止Ego或游戏。结果仍走独立JSON文件。
- 新增pending-command持久化：超时/断电/无结果时不再发下一条；部分写入、损坏记录或mayHaveLateEffects仍阻塞；完整晚到结果只解锁新观察，不重放旧保存，不改队列unknown。清理另持久化task_pages/不退出浏览器意图；finish回复丢失后不重复关闭/重建。
- 代码500a710；67桥接/批量Python、78 JS通过，最后损坏记录检查另5桥接测试通过；skill仓库/Codex/WorkBuddy同步且结构校验通过。未新增TaskSpace，无本轮项目标签需要清理，旧已结束任务未重开。
- 使用project-handoff记录本阶段；真实Ego长延迟及窗口消失修复尚未实页回归，遵守用户游戏约束。源码依据与离线证据见docs/miaoshou-reliability-20261029.md最新节。

### T-20261102-003 · 194-76 · 剩余商品续办

- 状态：review（本阶段有结论，全仓未完成）；从干净63dc4fb接续，Linear已公告。证据work/ego/remaining-20261102/；session=miaoshou-remaining-20261102已finish、关闭4自有页，其他用途未动。
- 原24 needs_agent全量预检初筛48/49/53；21缺属性/槽位/草稿驳回/SKU证据问题通过正常入口隔离，网站写入0。scan-live.json和preflight-exceptions.json保留；首次scan.json是未绑定session的失败，不是商品缺陷。
- 48/49/53正常领取7200秒，真实参考/原始妙手和官方全SKU/三项重复读回证据齐。三素材agent各限自己目录，Root独占浏览器写入。空间9→12→13均先备份再按既有自行恢复授权接续，其他qingshou/tbcli空间未动。
- 恢复旧素材agent时误续17旧任务，改写已verified本地main3和prompt；立即叫停，备份误写版本到incident17，再从原生成输出及原prompt恢复，所有9图/source/prompt哈希重新验证通过。source/main1/main2本未变；店铺未再修改。以后派工必须明确禁止旧任务收尾。
- 48漱口杯main5/detail3各一次重做后仍错印字，正式blocked，上传/保存0。49疏通器9图合格且上传9槽，预览发现原详情2/4重复使目标串位，保存0；新collision guard正常复测35.56秒隔离，保留9图/映射，不弱化预览或第三次生图。
- 53油瓶3848311880170996172完成新标题/5主/4详，保存1次后unknown；历史29015772（19:07:47）成功1/失败0，再只读32.59秒双端verified，尾10详情/全3SKU/保护字段保持。随后独立上架1次，product-53/53-listing-state.json=listed_verified，官方radio=0、审核值3。不要重存或重上架。
- 实页修复：Page级CDP恢复最小化Ego；收起已观察到的展开导航使屏外编辑按钮可点；精确编辑窗只切一次商品信息页签；图片槽位/选图关闭确认限定同坐标空间点击并复查命中。加宽视口与键盘编辑菜单原型无稳定效果，后者已撤回。细节见docs/miaoshou-reliability-20261029.md。
- 代码55d8545（实页控件）/e7a66ef（重复详情预检）；全量439 Python/77 JS通过，最后页签预算微调另17专项通过；skill三处同步且结构校验通过。活体8 verified/53 blocked=61，remaining-results.json/cleanup.json保存结果；47/19/42未知仍各1次旧保存，已verified不重存，失败素材不做第三版。
- 下一步：验证重复详情逐位置编辑、从真实来源补齐属性/读取稳定性；另复现Ego名义35秒却实耗约223秒的进程/晚到结果问题，实际墙钟预算未完全修复。不得把53件隔离当作已优化。父194-76保持in_progress；session已结束，后续用新session，不按13重接。

### T-20261102-002 · 194-76 · 五品测试结果（2通过/3隔离）

- 状态：review；Agent：codex-miaoshou-reliability；从干净bf1b67b接续，Linear已公告后维护本块。五件测试有结论，不代表五件成功或全仓完成；父Issue仍in_progress。
- 用户要求自行恢复后，SQLite/session均备份再恢复4→6；6在44上架点击前再次丢失，旧listing明确0次输入并superseded，重新核对后恢复8。session=miaoshou-five-tests-20261102、视口1464×795。本轮已finish空间8、关闭2自有页；空间6的用完历史页p3此前已关，其他空间未动。证据根work/ego/five-tests-20261102/。
- 首批36/22/23/43/46均在预检拒绝（厚度缺失/草稿驳回/安装方式缺失/尺寸缺失/详情未就绪），未写商品。
- 替补筛10件得5候选：14袜子3850071689249554608、15黄铜挂件3850071620530078120、16双面布包3850071178425271258、17男裤3850070641327866321、44塑料凳3848316155827716392；candidate-scan.json保存各项证据。
- 素材agent曾遇会话额度，Root接手续租并完成17；44由codex-miaoshou-test-44继续，同版本过期领取按claim_next重领，备份旧claim，浏览器仅Root串行。fb2ae4c已推送，修复短心跳缩短长租约；6专项/60batch通过，实租约心跳验证保留。
- 重复读取15/16/17/44保护字段稳定；14原读法不稳定。固定主图锚点原型两次通过，但继续独立复测14仍不一致（canonical-five-stability.json）；66项模拟测试不能代替实页证据，候选代码/测试已原样撤回。14本轮禁止上传保存，素材合格后保留并隔离执行，不放宽比较。
- 14保留9合格图并隔离；15钱币字印单槽重做后仍错，正式blocked；16已ready图被Root终审发现detail3重做版新增金属扣，无原图依据，绑定原manifest/图片哈希后隔离。三件均未上传/保存，失败记录不覆盖。
- 17男裤完成9新图，一次保存后首次读回仍旧版，保持unknown；后台任务11:16:49成功1/失败0后仅只读重核，双端完整verified；5新主/4新详、尾24详情与40SKU保持。随后单次独立上架并双端listed_verified，审核值3，不重存/重上架。
- 17执行261.02秒，随后只读恢复42.32秒；证据17-execution-first.json、17-readback-after-task.json、17-history-detail.json及product-17/17-listing-state.json。保存/上架各1次，不重放。
- e0b3e3d：官方表单先于店铺名挂载时，在现有30秒读取预算内等待精确店铺名；错商品/验证码仍立即停止，持续缺店铺仍拒绝。80项editor/preflight检查通过，44实页已跨过该卡点；首次12.79秒停在预检，0上传/0保存，不重放。
- 44的detail1/2/4首版失败各重做一次后9槽合格；第二轮270.22秒只保存1次，后台28874582成功后只读28.05秒双端verified，9SKU/5新主/4新详/尾16详情保持。另独立上架1次，product-44/44-listing-recovered-state.json=listed_verified；旧44-listing-state.json是0次输入superseded，不重放。
- 当前32/17/44通过严格fresh_form三品验收，current-writer-acceptance.json已正常落库并读回writer_ready=true；18内容虽verified但fresh_form=false，不计门槛、不重存。操作skill三处同步并校验。
- 活体7 verified/24 needs_agent/30 blocked=61；five-products-results.json为本轮2上架/3未写异常，cleanup.json为关页证据。后续从24件预检继续；14/15/16失败素材不再硬传，47/19/42仍未知只读，已verified商品不重存或重上架。

### T-20261102-001 · 194-76 · Ego续办、挂篮改版上架及点击修复

- 状态：in_progress；Agent：codex-miaoshou-reliability；从干净b41989b接续，1a5b4a0提交后工作区干净且Linear已公告，再维护本交接。
- 旧妙手空间缺失；依据用户已有新建授权创建空间3并确认销霁百货，旧session完整备份后绑定。其他H5空间2未动；本轮结束已finish空间3、关闭3个自有页，state.finished=true。
- 1a5b4a0：普通控件保留唯一/命中检查，改用Ego原生page.click(selector)重新定位；输入仍读回确认，最终保存仍单次Enter。解决实页坐标点击未打开预览、输入未确认；15项transport测试通过。
- 挂篮18（3848331817417572422）9槽上传后两次点击前中断，保存始终0次；修复后保存1次，166.83秒续办，双端完整内容核验verified_by_readback。5新主/4新详及原尾图、9SKU和保留字段通过。
- 挂篮另单次独立上架，18-listing-state.json=listed_verified；妙手status=0/官方状态radio=0，内容/SKU保持，审核原始值3，未宣称消费者端生效。不要再上架或重存18。
- 分装瓶47只读核查：标题/新图双端对齐、妙手保护字段通过，19SKU哈希不变；官方DOM价格库存输入89→95，多渲染1行导致严格比较拒绝。其他分区无差异；保持blocked/unknown/保存1次，不重存，不改基线。
- 现场计数5 verified、29 needs_agent、27 blocked，总61；当前writer内容验收2/3（地刮32/挂篮18），通用writer仍关闭。旧20/24/29和当前32不动；19/42仍unknown。
- 证据：work/ego/continuation-20261102/{basket-native-result,18-listing-state,bottle-protected-diff,cleanup}.json；上架截图basket-listed-full.png。技术结论见docs/miaoshou-reliability-20261029.md。
- 下一步：用新browser session继续，先修官方虚拟SKU表的采集稳定性并对47只读核验；完整SKU相等不能直接豁免DOM差异。旧空间3已正常结束，不能按ID再接；素材和队列保留。

### T-20261101-001 · 194-76 · SKU编码补读、挂篮素材完成与分装瓶异常

- 状态：in_progress；Agent：codex-miaoshou-reliability；从推送后的干净28597b8接续，已在194-76公告后维护本交接。
- 代码28597b8已推送。官方getSchema省略`code`时，按真实SKU ID只读滚动“商家编码”列并绑定新鲜响应/页面/店铺；缺失控件、骨架行、重复SKU或未覆盖全量均拒绝。完整code API路径不变。
- 真实页面36号商品12/12编码空值已逐ID观察；新增编辑器集成尚未实页执行。全量422 Python/67 JS通过；技术说明见docs/miaoshou-reliability-20261029.md。
- 挂篮18的9张素材已校验入队ready，未上传。主图5首版颜色/件数并列造成组合歧义，失败记录保留；唯一一次重做通过。素材与9项审核记录在work/completion-20261029/next-basket-20261031/。
- 分装瓶47只保存一次：抖店读回标题等于目标、19 SKU哈希未变；妙手仍为旧标题，列表status 1→0、draftStatus 0→2、checkStatus 1→2。语义未猜，队列blocked/unknown、attempts=1；禁止重存/上架。
- 先前妙手每日00:00无销量全量下架规则已关闭并读回确认；地刮32之后独立上架已verified。不要再改规则、重存或重上架32。
- SQLite活体：29 needs_agent、27 blocked（24未尝试、3 unknown）、1 ready、4 verified；总计61。三品当前writer验收仍1/3，通用writer关闭。
- 挂钩19/缝隙刷42保持unknown、各1次旧尝试；安装/承重资料与硬度缺项未确认，不猜属性、不重存。
- 当前Ego `listTaskSpaces()`返回空，旧空间1无法访问。不能创建替代空间；实时妙手核查、继续上传和本轮标签清理待原空间恢复。不得重放分装瓶保存脚本。
- 续办：恢复原Ego空间后先只读查47妙手历史/标题/状态；挂篮18须重新读当前双端基线后才可上传保存；随后续做三品连续实页验收、writer门槛与关本轮自有页。

### T-20261031-001 · 194-76 · 午夜自动下架根因与素材前预检

- 状态：in_progress；Agent：codex-miaoshou-reliability；从干净5b0856f接续，Linear已公告；用户已恢复妙手并确认没有手动下架。
- 同一session=miaoshou-completion-20261029、空间1已takeOver恢复，授权正常。当前任务继续，不另建空间；用完的来源页已关闭，最终持久化后仅清理本任务页。
- 官方商品列表记录地刮于2026-10-31 00:00:02被“开放平台妙手三方服务商操作下架”；妙手自动清理历史精确列出该商品及之前多件优化品，非图片丢失或本次程序重存。
- 根因是开启了“每天00:00、销量少于1、在售商品、全量下架”，没有跳过新建/新改商品。已通过实际确认弹窗关闭该开关，重开后disabled_verified，其余表单字段逐项保持。证据auto-down-disable-state-20261031.json；开关确认会直接保存，无需再点保存设置。
- 地刮在修复规则后单独上架1次，新鲜妙手status=0/官方状态radio=0、标题/全部图片/5SKU及其他字段均通过；32-relist-state-20261031.json=relisted_verified。审核值3，未宣称消费者端生效；不得再上架或重存。
- 挂钩19、缝隙刷42已查原1688货源，参数仍未给承重kg/硬度；保持blocked/unknown/各1次旧保存，新图及上传映射保留，不能猜填或重存。
- 新增batch preflight只读预检：显式ID绑定现有shop/target_version、只读SQLite、不领任务、不改状态、复用空间、完整SKU/属性/原图槽位校验、单品异常继续；人工接管即停止，余下ID保留。专项/CLI67项、全量401项通过（171.46秒）；skill三处哈希一致且校验通过。
- 首轮5件37.703秒：分装瓶47官方通过；手套36完整SKU证据不足；未知19/已完成32直接跳过；门档61原4主图/4详情，收集妙手基线前拒绝生图，现已隔离，并补预检4主/3详情负例。
- 分装瓶47已原子领取给codex-miaoshou-bottle、租约7200秒，原5主/6详情与完整19SKU已落next-bottle-20261031，子agent按内置imagegen准备9张，尚未上传/保存。第二轮4件41.391秒，2件仅2张原详情、2件SKU证据不足，均未生成/改商品；继续筛选并诊断SKU读取。
- 当前v5仅1件完整新版本成功，三品门槛及通用writer=false不变。工作文件均在work/completion-20261029；技术结论见docs/miaoshou-reliability-20261029.md。

### T-20261029-002 · 194-76 · 全量SKU核对与三品新版本验收

- 状态：in_progress；Agent：codex-miaoshou-reliability；接续5db66f5，开工工作区干净，Linear已公告。
- 范围：补齐官方全部SKU的读取/比对；准备合格全套新图；通过当前版本三品连续保存/双端读回，验收完成才开放通用写入。
- 官方正常编辑页重载的getSchema已完整读取65个SKU，与妙手逐ID/规格/价格/库存核验；只存身份与SKU值，不存context令牌。当前writer=v5，完整SKU证据接入前后与验收。
- session=miaoshou-completion-20261029。10月30日空间10丢失后备份恢复为空间1；当时手机验证已handOff，10月31日用户恢复后已接回；最新入口见T-20261031-001，不再建替代空间。
- 历史28份state对账另发现11件旧编辑遗漏，已备份后隔离；旧20/24/29不重存。活体计数必须重新查SQLite，不能沿用旧文档数字。
- 挂钩19、地刮32、缝隙刷42的27张新图已校验；地刮2张及缝隙刷1张重做一次通过。洗脚垫34重做后印字仍不合格，隔离。所有清单在work/completion-20261029/<商品ID>/。
- ff71815修复跨品表单、原生勾选、详情自动关闭竞态与预览动画，单次Enter保存；73674ca补官方必填属性上传前检查、缺失字段持久化及桌面原因显示，单品缺资料继续队列。334 Python/55 JS通过；推送及Linear回写收尾核验。
- 地刮32经证据和新鲜完整双端基线恢复点击前失败；v5一次保存后双端verified，5张新主图/4张新详情及原尾14张核验通过，全部5个SKU和其他字段保持。网页本次245.05秒；证据acceptance-11-result.json。
- 地刮另执行一次独立上架，妙手status=0与官方商品状态radio=0均确认；标题图片及全SKU保持，32-listing-state.json=listed_verified。平台审核原始值7→3，未确认消费者端生效，绝不再点上架。
- 挂钩19任务27418021、缝隙刷42任务27418017均查到完成/失败1：分别缺安装方式、硬度；官方挂钩另缺承重/适配基面。原图未给承重kg或硬度，两件保持blocked/unknown/各1次保存，不得重存。授权恢复后查精确ID行真实货源链接核实事实。
- 本轮当前验收1/3，通用writer仍关闭。SQLite活体32 needs_agent/25 blocked/4 verified（含旧3件，非4件全套新图）。不动历史20/24/29；技术与恢复路径见docs/miaoshou-reliability-20261029.md。

T-20261029-001 原文见 [批量技能重构前归档](docs/handoff-history/2026-11-09-batch-skill-before-review.md)。

旧任务块 T-20261026-002/001 原文见 [技能优化前历史归档](docs/handoff-history/2026-11-09-skill-source.md)。

### 历史记录归档

- 194-54 的完整历史交接记录已移至 [docs/handoff-history/194-54.md](docs/handoff-history/194-54.md)。

## 数据与算法

命令全局参数置于子命令前：`--json`、`--endpoint`、`--version`。**默认通道为 Ego 原生（`ego`）**；连接优先级为命令参数 > DOUDIAN_BRIDGE_URL > `ego`。Kimi WebBridge 仅作显式兼容通道，需传本机HTTP地址（如 `http://127.0.0.1:10086`），且只允许本机地址。

| 命令 | 行为 |
|---|---|
| doctor | 只检查安装、服务和扩展；未连接仍返回诊断JSON |
| products --limit 20 | 当前页已加载商品链接与表格行；不翻页，不猜编辑链接 |
| resolve <ID或编辑链接> | 解析稳定商品ID，编辑地址只接受抖店现有商品路径 |
| read --url ... --shop ... --out before.json | 打开真实编辑链接，采集当前DOM字段与图片 |
| prepare --assets ... --title ... --url ... --shop ... | 离线准备固定版本任务，返回job_dir |
| jobs --limit 20 / status <job_dir> | 查看任务、素材版本与阶段 |
| upload <job_dir> --apply | 替换标题/方主图/标准详情，留在编辑页 |
| submit <job_dir> --apply | 仅uploaded状态允许发布，成功后重开核验 |
| verify <job_dir> | 只重开编辑页核验，不重复发布 |
| browser snapshot / browser inspect --selector ... | 当前抖店页面只读检查入口 |
| unlock --job ... | 仅清除所属进程已退出的锁，不杀进程 |

示例（替换占位参数；编辑链接取自真实页面）：

```powershell
doudian-auto --json read --url '<编辑链接>' --shop '<店铺名>' --out before.json
doudian-auto --json prepare --assets '<素材目录>' --title '<新标题>' --url '<编辑链接>' --shop '<店铺名>'
doudian-auto --json upload '<返回的job_dir>' --dry-run
doudian-auto --json upload '<返回的job_dir>' --apply
doudian-auto --json submit '<返回的job_dir>' --apply
doudian-auto --json verify '<返回的job_dir>'
```

- JSON成功：`{"ok":true,"data":{...}}`；失败：`{"ok":false,"error":{"code":"...","message":"...","waiting_human":false}}`。成功退出0、一般错误1、需用户连接/验证3。JSON只写stdout；帮助使用标准argparse输出。
- upload/submit省略--apply或指定--dry-run只返回计划，不连接或写商品；prepare只读本地图片。read/products会打开页签，但不改商品字段。
- 素材命名main_01～05各一张，detail_01起连续编号1～50张，按数字排序。JPEG/PNG小于5MB；方主图至少600px；详情宽620～1290px；SHA256禁止重复图片，标题16～60平台字符（汉字计2）。
- ~/.doudian-auto/jobs/<商品ID>-<内容哈希前12位>/保存manifest/state、before/ uploaded/readback JSON及成功截图。manifest绑定绝对路径、文件哈希、商品、店铺、标题；文件改动后须重新准备任务。
- 每次操作串行持有browser.lock及job.lock；取得锁后重读状态，防止旧进程状态导致重复发布。每个不可变任务使用独立、固定的浏览器 session（默认Ego原生TaskSpace；Kimi兼容通道同样按session隔离），按商品ID重新选取重定向后的真实编辑页，保留未保存预览。
- 状态：prepared → editing → uploaded → submitting → submitted → saved。上传中断时跳过已有远程URL记录且页面相符的部分；来源不明的部分先清空，再按原素材重传。
- 发布前保存submitting，超时后禁止自动重发。只运行verify；若读回不符，保留submitted/错误及证据，人工确认真实页面后再处理，不能擅自改state绕过。
- 发布前后比较实际加载的保留字段：文本/数值、checkbox/radio、switch、选择项、静态属性及SKU/3:4/白底图地址。只写标题、方主图和标准详情，类目/品牌/售后必填变化一律停止；不套用以前商品的属性。
- 图片核验比较上传记录与重开后CDN路径及顺序，忽略缩放查询参数，不能仅凭数量确认。截图失败不覆盖提交事实，继续以新打开的保存页读回为准；消费者端生效仍由平台审核决定。
- dom.js依赖实测字段：#pg-title-input、attr-field-id主图/商品详情、goodsEditScrollContainer分区、主图hoverBottomWrapper删除第2项、详情iconDelete。隐藏高级编辑区排除；多选file input选标准区最后一个，上传前清掉旧标记。
- 浏览器传输使用公开本机POST /command的ok/data协议，GET /status诊断；绝不自动重试可能已送达的写请求。不访问Cookie、框架内部状态或未公开业务接口。
- 兼容旧素材校验脚本skills/.../scripts/doudian_check.py；其compare读取旧sections格式，CLI读回使用protected格式，不混用二者。

## 给下一个AI

技能优化见最上 T-20261109-002 / 194-156 和前阶段 T-20261109-001 / 194-155；业务进展以最上业务任务块及其证据为准，以下旧接续段不作为活体进度。

当前接续Linear 194-76与T-20261102-002，先读本文最上任务块；稳定Agent名codex-miaoshou-reliability。当前五品阶段空间4/session=miaoshou-five-tests-20261102尚在使用，只有Root操作浏览器。14/15/16已领取素材，17/44待领取；Root work脚本、原图与证据见work/ego/five-tests-20261102/。14本轮禁止上传保存，另外4款通过重复读取；先完成各自素材审核，不能将预检记作完整验收。地刮32/挂篮18已完整改版并上架；47仍unknown只读，19/42不重存。当前writer门槛2/3，通用writer关闭；每阶段收尾commit/push、回写194-76并读回。

- 恢复入口：AGENTS.md → 本文 → git status --porcelain → Linear 194-76；映射见docs/agent-workflow/T-ID-MAPPING.md。194-54为旧单品历史。
- 原生v5已完成地刮全套新图保存与双端核验；页面改版仍须核对店铺、精确ID、槽位和字段，不把这一件推广为全仓已验收。
- 官方SKU从正常UI重载响应取全量证据，与妙手逐行核对；DOM字段覆盖说明仍只适用于DOM。缺SKU响应、草稿或缺保护字段不能判一致。
- 不重传或重存历史verified20/24/29、当前32/18。19/42/47保留unknown；不可手改状态绕过证据恢复。图文任务不自动补类目属性，不猜承重/硬度。
- 每轮结束先持久化续办状态，再关闭本轮用完的项目标签；本轮3页已关，没有未完成验证页。只关自己任务页，不动其他用途标签，不重载未保存编辑。
- GUI冒烟仅证明入口与控件；实页保存/上架证据来自原生程序，未做GUI端到端验收。未保存编辑不自动回滚；before.json可供人工恢复参考。
- 运行测试：`.venv/Scripts/python.exe -X utf8 -m pytest -q`；`npm ci --ignore-scripts --no-audit --no-fund`后`npm test`。测试依赖用`.venv/Scripts/python.exe -m pip install -e '.[test]'`安装。
- 2026-10-30全量验证：334 Python通过，55 JS通过。现有浏览器/任务/图片数据均保留于忽略目录，不提交Git。
- 本次产物报告：C:/Users/19431/Documents/Codex/2026-10-21/wo-x/outputs/抖店本地程序校验/结果汇总.json；其中4个任务仅prepared，不在默认jobs目录，勿当线上任务自动提交。
- 个人skill已同步 ~/.codex/skills/doudian-product-workflow，官方quick_validate通过；本仓skills/保存源文件。修改后同步安装版并重新校验。
- 2026-10-30：miaoshou-auto-batch canonical及Codex/WorkBuddy两安装副本SHA256一致，三处quick_validate通过；GUI隐藏冒烟通过。短信验证页未用完，保留给用户，其余旧任务页随空间10丢失已不在当前清单。
- 2026-10-21：实现提交后仓库干净，在194-54公告再建立本交接；实现已完成，用户延后真实扩展连接，保留review验证门槛。
- 2026-10-21：用户指定WorkBuddy接手；仓库干净时先在194-54公告，再同步本交接与映射，待办状态改todo。
- 2026-10-22：WorkBuddy 完成真实联调（T-20261022-001/003/004），含一次改类目后重新提交；新增 `title` 离线校验命令与跨任务提交保护（commit d1c3590 之后的提交）。

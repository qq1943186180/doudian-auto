# 抖店本地上传

更新：2026-11-03（Asia/Shanghai）；Agent：codex-miaoshou-reliability（最近一次写入：workbuddy-independent，20:28）。
源码：C:/Users/19431/Documents/ChatGPT/抖店/doudian-auto；当前分支 codex/miaoshou-reliability-20261029；私有 origin https://github.com/qq1943186180/doudian-auto。

## 给人的说明

### T-20261103-004 · 194-76 · WorkBuddy 独立测试 Ego 断线（抖店3/3轮成功、妙手0/3待授权、1次真实进程退出）

- 状态：review（断线已定性、抖店已实测通过；妙手待用户授权）；Linear 已公告（comment cae6fc75，本轮结果另补 comment）。外部 Agent=WorkBuddy，**Codex 全程未操作 Ego**，独立自建 3 个测试空间。测试窗口 19:36–20:28（约 50 分钟）。证据 work/ego/workbuddy-independent-20261103/{REPORT.md,TIMELINE.md,evidence/E1..E4,RAW-ERRORS.md,process-samples*.csv,round-doudian-0*.log,wheel-*.log}。
- **商品只读结果：抖店 3/3 轮全成功、`wroteNothing:true`；妙手 0/3 轮（卡一次性 ISV 授权页，需用户点「确认授权」）**。三轮抖店读到完全一致数据：title=`壁挂拖鞋架 浴室粘贴式双钩收纳架 颜色随机`(21字符)、imgCount=45、mainLike=9、detailLike=27、shopName/hasBasics=true、三层退出编辑均 `hadDialog:false`（无脏状态）。
- **发生 1 次真实断线：19:38:31→19:38:36，断在 browser 进程层（ego.exe 4→0，主 PID 16976 消失）**。排除控制连接断开（连接方已死）、排除空间 finish（本测试未调用，且 user 空间 29 一并消失）、排除命令超时（5 秒内立即断开，exit code 0）。两 profile 均写 exit_type=Crashed；listTaskSpaces 崩溃前 1 个→崩溃后 []。19:38:37 外部拉起新树 PID 31716，非本测试动作；**全程未 kill/close/finish/重启**。此后至 20:28 **未再复发**（两段采样共 122 点，20:10:46–20:17:10 的 56 点零值 0，主 PID 30148 稳定）。
- **不支持「Codex 导致断线」，本轮是强阴性但也未排除**：Codex 最后日志 19:36:09（早于故障 2m22s），状态写盘 19:37:40、残留 tmp 19:37:58 = 收尾静默期；断线时无 codex.exe、`ExecutablePath~codex`=0、无 Codex 的 Ego 空间；唯一 Ego 客户端是本测试 CLI(cli_count=1)。→ 当期**无并发窗口**，属**未观测**而非已排除。要真正回答须做 A/B 并发对照（P3，违反「不同时操作 Ego」指令，需授权）。
- **阻断已解**：崩溃曾把唯一登录态 `Profile 1`(尚运 李) 从注册表抹掉（`newTaskSpace: Profile not found`，Default 下 100% 跳登录页）。用户处理后恢复为 **`Profile 2`(尚运 李, isDefault:true)**，抖店 `loggedIn:true`，无需短信重登。⚠️ **profile id 从 `Profile 1` 变为 `Profile 2`，任何硬编码 `profileId:"Profile 1"` 的脚本/配置现在都会失败**，须改用 `taskSpace(name)` 走默认或动态取 `profiles().find(p=>p.isDefault).id`。
- **新发现（比断线更影响效率）：`mouse.wheel()` 单次阻塞 4–48 秒**。三组对照：example.com 基线 3,952/4,030 ms（`mouse.move` 单独就要 1,000 ms）；抖店列表页 26,153/19,095 ms（同页 `window.scrollTo` 仅 **8 ms**）；抖店表单页 36,878/37,210/41,084/40,349/48,350 ms（同页 `scrollTop` 仅 1,000 ms）。滚动占总耗时 87–91%。`scrollY` 恒 0 已实证为页面结构（外层 docH=docClient=1128 不可滚，真实容器 `div.styles_form__Ew_RZ` 4563/913、`div.styles_scrollBody__KKYBa` 6097/905），非滚动失败。**建议滚动改走 evaluate 定位容器后设 scrollTop/scrollIntoView，mouse.wheel 仅留给需真实滚轮事件的懒加载场景**（按指令未改代码）。附带观测：第 1 轮 151s 内 renderer PID 27920→15064 于 20:16:31 替换，主 PID 稳定、renderer 恒 7、页面未崩未重载，判为渲染进程回收重建而非断线，但会加剧 wheel 等待。
- **妙手阻断（唯一未完成项）**：`v2-dd.chengji-inc.com/product/quick_edit` → `fuwu.jinritemai.com/authorize?service_id=234&from=isv.authorize`，标题「抖店服务市场-授权」，`isLoginPage:false`、`isAuthzPage:true`、`rows:0`，20:10 与 20:24 两次探测结果一致（稳定阻断）。授权范围含订单/物流/客服会话，属店铺所有者决策，**未代点**。用户点「确认授权」后可立刻补跑妙手 3 轮（脚本可复用 round-doudian-0*.mjs 改 URL/选择器）。
- 稳定性旁证（Default 下只读，非业务）：控制连接压测 14/14 通过（goto 503–1,579ms，evaluate 0–26ms）；6 轮快照+空间盘点 57.8 秒，第 6 轮快照 5,490→114 字符（29 秒后复查恢复 5,4xx，判单次采集瞬时降级）。阴性证据：无 CrashDumps/WER/Application Error/Hang/Crashpad dmp、内存非耗尽（Available 4025MB）、Ego 无运行日志 → 静默退出属黑盒，需开 LocalDumps 或 ETW（需授权）。
- 空间处置：自建 id 1、2、3 均 `claimTaskSpace`→`finish({keep:[]})` 关闭；空间3 终态 `{closedSpace:true, closedManagedLabels:["p1"], preservedUnmanagedCount:0}`；最终 `listTaskSpaces()`=**`[]`**、`ego-browser.exe` 残留 0、主进程 30148 存活。**未重接空间 31、未触碰 user 空间 29(tbauto)**、其他用途页未动。未改项目代码/队列/设置、未用新增付费 API、未关闭或操作 Codex。
- 下一步：P0 用户点妙手「确认授权」→ 补跑 3 轮；P1 同一脚本连跑 10–20 次判偶发/必现（Codex 离线作对照）；P2 开 LocalDumps+ETW 补取证；P3 Codex 在线/离线 A-B 并发对照（需用户授权）；P4 滚动改 evaluate 路径（需批准改代码）。父 194-76 保持 in_progress。

### T-20261103-003 · 194-76 · 准备续办、读取恢复与本批两品上架

- 状态：done（本批结案，非全仓完成）；从干净15db36f接续并Linear公告，Root唯一浏览器写入器。活体17verified/44blocked=61；19/42旧unknown各1次不变，不重存成功或未知任务。
- 14袜子经新增recover-prepared审计入口恢复同版本旧9合格图；两轮新鲜双端57.96秒通过。内容保存1次328.41秒，超时后只读41.60秒恢复verified；34SKU/5主/前4详/尾7详情/商业字段通过，另一次上架69.93秒双端listed_verified。
- 30拖鞋架6新图/3重新审核旧合格图、6次生成0重做；几次原生顶部勾选失败均0保存，候选position补丁实页未通过已撤回。完成错误结案后显式采用已有compatibility路径，内容350.80秒保存1次，1SKU/9目标图/尾11详及商业字段双端verified。
- 30第一次上架工具明确结束报不可见，原请求/结果哈希及count1保留；新鲜双端仍仓库且内容不变后建立独立attempt2。守卫真实按钮后一次原生Enter，随后捕获新鲜非草稿响应并官方独立全字段/SKU核验为listed_verified；不将第二次结果归给首尝试，不重存图文。
- 27杯架详2/3各重做一次仍把单端跨板挂臂画成双端跨前沿，Root与准备agent复核，按正常quarantine隔离、0上传0保存，严禁第三次生成或complete旧passed清单；全阶段11次内置生成，无付费API。
- 49重复详情A,B,C,B,D：同空间实页整组替换预览四目标顺序和原尾图通过，复用4映射/0新上传/0保存/队列不变；正式模式保存守卫及双端验收仍待后续实现，v5碰撞守卫不得放开。
- dd91a02/9474592/cdf1888/dd6c01d已推送：准备续办、仅精确卡住读取的单次关页审计恢复、Snapshot帧树精确超时标记文本读、初始店铺badge等待；553Python通过176.91秒、93JS通过，skill三处同步校验。技术细节docs/miaoshou-reliability-20261029.md。
- session=miaoshou-prepared-recovery-20261103、空间31已正常finish关3自有页（卡住p1此前审计关1次），state.finished=true、无pending；未退出Ego、未动他用页。work/ego/prepared-recovery-20261103/{completion-results,cleanup}.json及各产品状态为证据，不按31重接。
- 后续优先49正式整组详情模式及真实来源补缺属性；27/15/16/34/48视觉二败继续隔离。父194-76保持in_progress，全仓未完成。

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

### T-20261029-001 · 194-76 · 浏览器可靠性与素材身份检查修复

- 状态：in_progress；Agent：codex-miaoshou-reliability；分支 `codex/miaoshou-reliability-20261029`，从干净 main=6143197 接手。Linear 已公告本次交接更新。
- 已实现当前可见精确ID行定位、排除旧读取响应、保存响应绑定商品/接口、有限只读复查；复用并审查 afcc388 的素材字节/像素核验及限定3品验收实现。
- 上一轮单件商品3850072653520044313已保存新标题并上架；妙手显示上架/审核通过，抖店官方页重载状态为上架。5张主图和14张详情沿用原图；不能记为新图或三品批量验收。
- 已备份并对账任务2/3/4/7/8的历史证据，隔离待重建基线；队列活体47 needs_agent / 11 blocked / 3 verified，未重存任何商品，20/24/29不动。
- 新素材须绑定源图、事实、提示词、目标版本及逐图五项检查；失败单槽最多重做一次，第二次失败隔离。程序检查证据与哈希，视觉判断仍由agent完成。
- 新增 `--endpoint ego` 原生TaskSpace通道、独立轮次文件、同轮网络捕获、不重放超时/EPERM动作；页面按路由复用，结束只关自己的页。桌面“抖店全仓优化”已安装并指向当前目录。
- 实页修复d2bf64e：固定实测视口、聚焦变形输入框、标题热词干扰、详情独立弹窗、断点槽位复用及完整详情尾图预览。严格比较不放宽，不同内容的已有槽位停止。
- 验证：最终全量Python282项、JS35项通过；GUI冒烟及skill校验已执行。当前writer=v3，通用写入仍关闭；不能把原图上传测试计为全套新图保存验收。
- 现场：授权已恢复，同一TaskSpace8已完成程序单品双端读取、原图5主+4详情上传/预览9/9字节一致、尾10张保留，保存0次；固定原视口后严格双端基线复读通过，已结束空间并关闭本轮4个自有标签。证据在 `work/ego/reliability-20261029/`。
- 后续：合格全套新图、当前版本3件连续完整保存/双端逐字段验收、官方虚拟SKU全量覆盖仍未完成；固定视口不代表隐藏SKU已遍历。技术结论与续办入口见 [docs/miaoshou-reliability-20261029.md](docs/miaoshou-reliability-20261029.md)。

### T-20261026-002 · 194-76 · 妙手全仓优化程序与页面验收

- 状态：in_progress；以下是修复前阶段记录，当前队列与浏览器入口以 T-20261029-001 为准。完整旧块已归档到 [docs/handoff-history/T-20261026-002-before-reliability.md](docs/handoff-history/T-20261026-002-before-reliability.md)。
- 队列、最多3个agent领取、单写入器、逐槽上传、一次保存、双端读回及GUI已实现；生产writer仍关闭，原图测试不算全套新图验收。
- 商品20/24/29是 verified_by_readback，保存尝试1/3/2次；不重复保存。商品24/29旧标题已修复，9张目标图、详情尾图和商业字段双端核验，均在仓库。
- 旧版标题修复505c5e1在main；当时暂存的新上传实现afcc388已在本轮选择性接入并继续修订，不能继续按“尚未接入”处理。
- 标题任务26884873当时显示完成/成功1/失败0；原始证据在 ~/.doudian-auto/title-repair-preflight/history-24.json。商品数据和图片不进Git。
- startSaleType是审核后去向，仓库0→1仅按 preserve_warehouse_v1 明确策略比较；详见 [docs/miaoshou-shelf-policy.md](docs/miaoshou-shelf-policy.md)。未知保存、saveTempBatchTask不能重放。
- Ego原图5主+4详情上传9/9字节一致，预览尾10张详情保留，复读基线一致，保存0次；耗时与通道边界见 [docs/ego-browser-evaluation-20261029.md](docs/ego-browser-evaluation-20261029.md)。
- 女童裤缺腰头印字、宠物球孔位等旧AI候选不合格；三品当前写入器全链路验收仍待完成。旧素材在 work/acceptance-20261029/，原测试在 ~/.doudian-auto/ego-evaluation/20261029/。

### T-20261026-001 · 194-52 · 交付后审查：补两处断档（WorkBuddy，Codex 复检通过）

- 状态：done。对 194-52（Codex 2026-10-21 交付的 skill + 离线校验）做交付后审查，交付本身合格，但发现两处断档已修复。
- **审查复现**：194-52 声称的 9 项校验全部独立复跑通过（4 素材 assets + 3 compare + 改价/错标题 2 负例）；仓库 141 Python + 24 jsdom 全过；git 干净、origin 已推、桌面快捷方式在、zip 备份完整。
- **断档 1（高危，已修）**：`~/.workbuddy/skills/doudian-product-workflow` 副本自 194-52 当天安装后从未同步，与当天 zip 备份 diff 为 0 行——**带着已修复的标题下限 bug**：副本 `doudian_check.py` 自带计数规则下限 15 units，而 canonical 已修为 16（平台 8–30 汉字 = 16–60 字符）并改为委托已安装 `doudian_auto` 包（T-20261022-005）。本机任何 WorkBuddy 会话跑旧副本都会放行 15-unit 标题、提交被平台打回。已用 canonical 覆盖同步三处副本（workbuddy/codex/仓库字节一致，SHA-256 相同），实测 14 units 拒、15 units 拒、16 units 过。
- **断档 2（已修）**：本仓库 `T-ID-MAPPING.md` 与 HANDOFF 此前无 194-52 记录（该单交接只存在于 Codex 会话 outputs 目录，不在任何 git 仓内，误删即失）。已补两行映射（T-20261026-001 + 原始的 T-20261021-003），并把 `skill-backup-20261021.zip`、`HANDOFF-codex-session-20261021.md`、`skill-checks-summary.json` 归档至 `docs/agent-workflow/history/194-52/`（与原始文件字节一致）。
- **Codex 复检结论**：「核心修复到位，9 项独立校验全部符合预期。未发现高、中严重度问题」；仅余 2 处低级文档问题——本 HANDOFF 缺记录（即本条）与 `title.py` 模块注释残留 `15-60`（已改 `16-60`）。
- **长期纪律**：skill 是三处安装（仓库 canonical + `~/.codex` + `~/.workbuddy`），**仓库改 canonical 后必须同步两个安装目录**，否则 WorkBuddy 侧会静默用旧规则。校验脚本的标题规则唯一事实源是已安装的 `doudian_auto` 包，不允许任何副本再自带计数实现。
- Codex 调用方式已封装为 user 级 skill `codex-cli-review`（`~/.workbuddy/skills/`）：exe 路径含版本哈希会变，skill 内教 glob 发现；模板 `codex exec -s read-only --ephemeral -o <报告> "<prompt>"`。

### 历史记录归档

- 194-54 的完整历史交接记录已移至 [docs/handoff-history/194-54.md](docs/handoff-history/194-54.md)。

## 数据与算法

命令全局参数置于子命令前：`--json`、`--endpoint`、`--version`。连接优先级为命令参数 > DOUDIAN_BRIDGE_URL > http://127.0.0.1:10086。只允许本机HTTP地址。

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
- 每次操作串行持有browser.lock及job.lock；取得锁后重读状态，防止旧进程状态导致重复发布。每个不可变任务使用独立、固定的Kimi session，按商品ID重新选取重定向后的真实编辑页，保留未保存预览。
- 状态：prepared → editing → uploaded → submitting → submitted → saved。上传中断时跳过已有远程URL记录且页面相符的部分；来源不明的部分先清空，再按原素材重传。
- 发布前保存submitting，超时后禁止自动重发。只运行verify；若读回不符，保留submitted/错误及证据，人工确认真实页面后再处理，不能擅自改state绕过。
- 发布前后比较实际加载的保留字段：文本/数值、checkbox/radio、switch、选择项、静态属性及SKU/3:4/白底图地址。只写标题、方主图和标准详情，类目/品牌/售后必填变化一律停止；不套用以前商品的属性。
- 图片核验比较上传记录与重开后CDN路径及顺序，忽略缩放查询参数，不能仅凭数量确认。截图失败不覆盖提交事实，继续以新打开的保存页读回为准；消费者端生效仍由平台审核决定。
- dom.js依赖实测字段：#pg-title-input、attr-field-id主图/商品详情、goodsEditScrollContainer分区、主图hoverBottomWrapper删除第2项、详情iconDelete。隐藏高级编辑区排除；多选file input选标准区最后一个，上传前清掉旧标记。
- 浏览器传输使用公开本机POST /command的ok/data协议，GET /status诊断；绝不自动重试可能已送达的写请求。不访问Cookie、框架内部状态或未公开业务接口。
- 兼容旧素材校验脚本skills/.../scripts/doudian_check.py；其compare读取旧sections格式，CLI读回使用protected格式，不混用二者。

## 给下一个AI

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

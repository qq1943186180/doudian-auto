# 抖店本地上传

更新：2026-10-28（Asia/Shanghai）；Agent：codex-miaoshou-batch。
源码：C:/Users/19431/Documents/ChatGPT/抖店/doudian-auto；main；私有 origin https://github.com/qq1943186180/doudian-auto。

### T-20261026-002 · 194-76 · 妙手全仓优化程序与页面验收

- 状态：in_progress。标题补救修复 `505c5e1` 已推送 `origin/main`；两件旧标题问题已解决，三件目标内容均完整读回通过。通用新上传/保存路径尚待验收，保持 `writer_ready=false`。
- 已实现持久化 SQLite 队列、最多3个 agent 原子领取、妙手 UI 适配器、单写入器、上传槽位映射、一次保存与双端读回、只读恢复、标题补救命令、GUI 进度/异常/续办入口；标题及图片校验和素材哈希复验沿用既有工具。
- 61件队列当前为52件 `needs_agent`、6件旧任务 `blocked`、3件 `verified`。商品20/24/29均为 `verified_by_readback`，尝试计数分别1/3/2；24包含一次快速编辑明确拒绝，29异步落地后只读结案。不要重复保存这三件。
- 商品24（`3848322422084337743`）新标题：`厨房水槽挂式沥水篮不锈钢过滤篮地漏网多款`；商品29（`3848319372858884337`）新标题：`羊毛衫毛衣平铺晾晒网挂式单层双层多规格咖啡色可选`。两端新标题、9张目标图、原详情尾图、SKU/价格库存及商业字段匹配，均保持仓库状态。
- 妙手标题任务 `26884873` 已活体读取为完成、成功1、失败0，明细商品ID为24；本机证据在 `~/.doudian-auto/title-repair-preflight/history-24.json`。商品数据、图片及页面响应不进Git。
- 新增标题专用页适配：单商品ID、使用新内容、超长失败、不修AI尺码、不定时、不调整上下架；仅用可见控件，核对新旧标题与实时字数，预检唯一最终批量按钮后才记录一次提交意图。不重传已有合格图片。
- `saveTempBatchTask` 是异步链路的中间响应，不能证明商品成功，也不能证明未提交；暂时仍是旧标题时仅只读复核。未知提交永不重新放行。仅有明确且已完成的快速编辑拒绝响应，才允许一次标题专用路径切换，并绑定失败事件哈希及总次数上限3。
- `startSaleType` 表示审核后去向，仓库状态保持1且最终去向1可按 `preserve_warehouse_v1` 核验；原始0→1仍记录，在售或未知状态不得套用。完整语义、标题路径与异步恢复限制见 [docs/miaoshou-shelf-policy.md](docs/miaoshou-shelf-policy.md)。
- 验证：全量 **238 Python passed + 24 DOM passed**，skill quick_validate、`compileall`、`git diff --check`通过；仓库/Codex/WorkBuddy三份skill同步且哈希一致。所有本轮项目标签已关，原淘宝、Linear、Bing标签保留。
- 下一步：验证当前多字段适配器从空页上传9槽、保留详情尾图、一次保存并双端读回的完整新写入流程，再开放通用writer。三件历史内容核验和标题补救不能代替此路径验收。

## 给人的说明

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
- 素材命名main_01～05各一张，detail_01起连续编号1～50张，按数字排序。JPEG/PNG小于5MB；方主图至少600px；详情宽620～1290px；SHA256禁止重复图片，标题15～60平台字符（汉字计2）。
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

WorkBuddy接手：先读Linear 194-54与共享协议，按本机真实目录检查Git，读AGENTS.md及本交接，以workbuddy-doudian-verify报到。全局doudian-auto与桌面入口可直接使用，不依赖Codex会话；工具说明可直接读本仓skills/doudian-product-workflow/SKILL.md，无需重建项目或重装Codex skill。先doctor与只读read联调，必要时修复本仓适配器；保持34项离线测试通过。在用户具体商品任务范围内完成上传/发布/重开核验后才记真实验收，收尾commit/push并回写194-54读回。具体步骤和验收以Issue最新描述为准。

- 恢复入口：AGENTS.md → 本文 → git status --porcelain → Linear 194-54；映射见docs/agent-workflow/T-ID-MAPPING.md。
- 实现是离线验证过的适配器，尚无本程序真实上传证据；先doctor/read，逐一核对店铺、URL、主图/详情删除计数、上传input和保留字段采集，页面改版则修适配，不盲点。
- 店铺身份要求页头可见店铺名精确匹配；页头折叠或结构不符会先停止。只覆盖DOM已加载字段，虚拟SKU列表未逐行遍历，不可宣称全部SKU已完整验证。
- 初次联调不得默认重传此前已完成的4款；需要对应的实际新任务/用户范围。程序没有跨商品自动发布或自动改类目功能。
- 新打开的商品页签组名「抖店本地上传」，只有用户要求时关闭，不重载有未保存内容的编辑页。服务可安全start；stop/restart/upgrade由用户决定。
- GUI启动检查验证了控件创建，未进行真实浏览器上传或完整视觉验收。未保存编辑不自动回滚；before.json可供人工恢复参考。
- 运行测试：`.venv/Scripts/python.exe -X utf8 -m pytest -q`；`npm ci --ignore-scripts --no-audit --no-fund`后`npm test`。测试依赖用`.venv/Scripts/python.exe -m pip install -e '.[test]'`安装。
- 已测环境：Python3.11.17、Pillow13.0.0、pytest9.1.1、Node22.22.2、jsdom26.1.0；34项测试均通过，另有GUI/CLI及4款真实素材离线校验。
- 本次产物报告：C:/Users/19431/Documents/Codex/2026-10-21/wo-x/outputs/抖店本地程序校验/结果汇总.json；其中4个任务仅prepared，不在默认jobs目录，勿当线上任务自动提交。
- 个人skill已同步 ~/.codex/skills/doudian-product-workflow，官方quick_validate通过；本仓skills/保存源文件。修改后同步安装版并重新校验。
- 2026-10-21：实现提交后仓库干净，在194-54公告再建立本交接；实现已完成，用户延后真实扩展连接，保留review验证门槛。
- 2026-10-21：用户指定WorkBuddy接手；仓库干净时先在194-54公告，再同步本交接与映射，待办状态改todo。
- 2026-10-22：WorkBuddy 完成真实联调（T-20261022-001/003/004），含一次改类目后重新提交；新增 `title` 离线校验命令与跨任务提交保护（commit d1c3590 之后的提交）。

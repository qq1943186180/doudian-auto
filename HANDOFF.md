# 抖店本地上传

更新：2026-10-29（Asia/Shanghai）；Agent：codex-miaoshou-reliability。
源码：C:/Users/19431/Documents/ChatGPT/抖店/doudian-auto；当前分支 codex/miaoshou-reliability-20261029；私有 origin https://github.com/qq1943186180/doudian-auto。

## 给人的说明

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

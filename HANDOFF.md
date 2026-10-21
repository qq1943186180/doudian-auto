# 抖店本地上传

更新：2026-10-21（Asia/Shanghai）；Agent：codex-douyin-products-20261021。
源码：C:/Users/19431/code/clis/doudian-auto；main；私有 origin https://github.com/qq1943186180/doudian-auto。

## 给人的说明

### T-20261021-004 · 194-54 · 本地上传模块

- 状态：review；实现、离线测试与安装完成；用户要求「先完成程序，稍后连接」，真实Kimi扩展试传未执行。
- 已实现：素材准备、标题/5主图/标准详情上传预览、断点继续、商业字段变化拦截、独立发布、提交后重开读回、中文桌面窗口。
- 桌面「抖店本地上传.lnk」使用项目虚拟环境pythonw；命令 doudian-auto 已装到 ~/.local/bin，任意目录可用。
- 验证：29项Python测试、5项jsdom页面测试通过；GUI控件创建、源码目录外help/doctor通过；4款真实素材离线计划全部5+2。
- 当前连接：daemon v2.0.9运行，extension_connected=false。未升级、重启扩展；本阶段线上商品写入0次。
- 代码提交7fa1f0a；原TB Auto/泰国站源码与历史脏文件未动；此前4款已完成商品不因测试重复改版。
- 下一步：用户连接Edge扩展后，先doctor及只读read核对真实页面，再在明确的商品任务范围内联调上传与保存读回。
- 交接与T-ID映射同步本仓；Linear 194-54保留待真实连接验证，状态review。

日常使用：双击桌面入口，填店铺、真实商品编辑链接、新标题及素材文件夹；按“准备任务 → 上传预览 → 发布并核验”。上传预览会留在编辑页，不自动发布。重新打开程序可选择任务文件夹继续；任务状态及图片地址保存在本机。

安装/重装（PowerShell，在本仓）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/install-local.ps1
doudian-auto --json doctor
doudian-auto gui
```

程序本身不生成图片、不调用模型或收费API；输入已完成的素材。浏览器连接使用本机Kimi WebBridge和当前Edge登录态，不存储账号凭据。

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

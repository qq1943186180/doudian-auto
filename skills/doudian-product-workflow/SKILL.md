---
name: doudian-product-workflow
description: 改版中国抖店现有商品的标题、主图和详情，结合本地素材校验、原商品字段比对、登录浏览器上传及提交后读回。用于抖店/抖音电商商家后台；淘宝与海外 TikTok Shop 使用各自流程。
---

# 抖店商品改版

本地程序 `doudian-auto` 负责素材校验、现有商品上传、断点继续和发布后读回；Codex负责事实判断、文案、生图及授权范围。桌面入口「抖店本地上传」与命令行使用同一个模块。

## 本地上传程序

先用 `Get-Command doudian-auto` 确认已安装，再执行 `doudian-auto --json doctor`。源码默认位于 `~/code/clis/doudian-auto`，重装用 `scripts/install-local.ps1`。不调用付费模型API。

浏览器使用本机 Kimi WebBridge 与 Edge 的当前登录态，不导出Cookie。配置优先级：`--endpoint` > `DOUDIAN_BRIDGE_URL` > `http://127.0.0.1:10086`。连接异常时按 Kimi skill 排查；服务可安全start，不自动stop/restart/upgrade。用户说稍后连接时先完成离线工作。

先用 `products --limit 20` 查看当前页链接/商品行，`resolve <编辑链接或ID>` 解析ID，`read --url '<真实编辑链接>' --shop '<店铺名>' --out before.json` 读取原商品。商品链接必须来自实际页面，不能猜类目参数。

```powershell
doudian-auto --json doctor
doudian-auto --json prepare --assets '<素材目录>' --title '<新标题>' --url '<现有商品编辑链接>' --shop '<店铺名称>'
doudian-auto --json upload '<上一步返回的job_dir>' --apply
```

`prepare` 离线检查素材并固化哈希；任务保存在 `~/.doudian-auto/jobs/`。省略 `--apply` 或加 `--dry-run` 只输出计划。`upload --apply` 替换标题/方主图/标准详情后留在编辑页，尚未发布。确认预览在会话授权范围内后，执行 `submit '<job_dir>' --apply`，程序发布并重开核验。`verify '<job_dir>'` 只重开核验、不发布。`status '<job_dir>'`、`jobs --limit 20` 读进度；`browser snapshot` / `browser inspect --selector '<CSS>'` 是只读排查入口。

浏览器页签属于每个任务的独立会话，组名「抖店本地上传」；只有用户要求时才关闭。上传中断可重跑upload，已核对的图片跳过，来源不明的部分清空重传。状态submitting表示提交结果未知，只运行verify与只读检查，禁止改状态后盲目重新发布。锁所属进程已结束才能使用unlock；仍在运行不删除锁。

**同一商品只允许一个未完成任务。** 任务ID由内容哈希决定，改标题必然生成新任务；若旧任务仍处于 `submitting`/`submitted`/`editing`/`uploaded`/`rejected` 之一，`upload` 与 `submit` 会直接拒绝（`product_job_conflict`）。这是防止用新任务绕过旧任务提交保护的唯一手段——全局锁只挡并发，挡不住先后两次发布。遇到该错误先对旧任务 `verify` 或处理完，不要删除旧任务目录来强行推进。

已完成一次真实链路：2026-10-22 商品 3784643089604411407 跑通 `prepare → upload --apply → submit --apply → verify`（`stage=saved`），期间被平台以「类目与商品实际类目不符」驳回，改类目后重新提交成功。**审核结果仍待平台确认**，且这只能说明该商品该路径已适配，不代表所有商品、所有类目都已适配。首次联调先做只读连接/页面检查，不因测试程序重传此前已提交的4款商品。

## 标题

`doudian-auto title` 是离线命令，不需要浏览器，也不写任务。

```powershell
doudian-auto --json title check --title '<标题>'
doudian-auto --json title diagnose --title '<标题>' --facts <已确认事实.json>
```

平台口径（抖音电商学习中心）：**8–30 个汉字，即 16–60 个字符**。`check` 只跑确定性规则（长度、首尾空白、控制字符）；`diagnose` 额外对照已确认事实给出提示：绝对化或需资质证明的表述、标题内宣传价格（平台明确禁止）、物品概述词（百货/孤品/套装/链接/好物/秒杀专项）、重复用词、模糊规格、无依据的数值、已确认却未使用的属性。

这个命令**不生成标题**，也不宣称平台合规——本地通过不等于平台会通过。标题仍由人或模型撰写，命令只负责挡住确定性错误并暴露无法确认的部分。选定标题后再 `prepare`，不要事后改 manifest：标题参与 `content_hash`，改标题等于换新任务。

**只改标题、不换图**时用 `title apply`（改版流程必然重传图片，不适用于只改标题的线上商品）：

```powershell
doudian-auto --json title apply --url '<编辑链接或商品ID>' --shop '<店铺>' --title '<新标题>' --facts <事实.json>
```

省略 `--apply` 只做校验与诊断，全程不连浏览器。带 `--apply` 会建一个 `title-<商品ID>-<时间>` 任务，依次填标题 → 填写检查 → 发布，并把改动前后标题、诊断结果、状态与截图留档。它同样受「同一商品只允许一个未完成任务」约束，也不会重复发布：结果未知时停在 `submitting` 并报错，让你人工核对。

## 本地工具

`scripts/doudian_check.py` 不联网、不调用模型、不修改店铺。标题规则以已安装的 `doudian_auto` 包为准，因此**必须用项目虚拟环境的 Python 运行**（例如 `<repo>/.venv/Scripts/python.exe`）；缺包时脚本会退出并提示安装方式，不会退回另一份规则副本。

```powershell
python scripts/doudian_check.py assets <素材目录> --title '<新标题>' --out <检查结果.json>
python scripts/doudian_check.py compare <editor-before.json> <提交后核验.json> --title '<新标题>' --details 2 --out <核验结果.json>
```

`assets` 检查5张独立方主图、详情尺寸/体积、重复内容、素材记录哈希、标题字符数；支持 `main_01_*.jpg` 到 `main_05_*.jpg` 和 `detail_*.jpg`。不替代目视检查商品结构和文字。

`compare` 对比采集快照中的价格库存、履约输入、出现的SKU编号及新标题/图片数量；只覆盖快照实际采到的字段。虚拟列表未采集的SKU不能被宣称已逐项核验。

快照字段格式和编辑器实测见 [browser-workflow.md](references/browser-workflow.md)，采集与上传时读取。

## 执行原则

- 明确店铺、商品ID、改动范围，沿用会话里已有的授权；不要重复要求批准同一款同一版。一次样板批准不能默认为以后所有新商品的授权。
- 先读任务交接与原商品：标题、类目、主图、详情、SKU图、颜色/材质/尺寸、价格库存、发货、运费和售后。图片必须来自该商品页面；图案或规格不一致先澄清证据。
- 每款独立目录：原图与编辑前快照、最终图片、素材哈希、新标题、提交证据。使用本地脚本校验，不反复手工重写同一检查逻辑。
- 标题和卖点结合真实SKU，优先检索本机课程知识库 `GET http://127.0.0.1:5001/api/rag/search`；超时重试一次后降级，不调用付费问答来凑资料。
- 每张主图独立生图，使用匹配原图作为参考，调用前看图。详情也依据原商品。生图使用可用 imagegen skill 的内置工具；不能用排版拼图冒充AI重构。
- 目视检查身份、外形、颜色、数量、印字和适配描述，整套保持一致。素材通过检查后再打开编辑页，避免空图状态下长时间等待生成。
- 默认只改标题、指定格式主图和详情。价格、库存、SKU、物流保留；平台要求新增必填项时据事实补齐并记录。类目及服务条款发生超出已授权范围的变动，展示具体变化再问。
- 上传用当前可用的已登录浏览器工具，遵守其文档。页面写入串行；登录、验证码或风控交给用户处理。不复制登录凭据，不伪造保存证据。
- 最终提交在会话授权范围内进行。仅上传成功不是完成：等待提交成功，重新打开编辑页，读回标题、5个主图远程地址和实际详情数量，再比对原商业字段。列表新标题、主图和售卖状态作为补充证据。
- 保存截图、核验JSON与HANDOFF，回写对应Linear并读回。区分本地素材完成、已上传、已提交、读回已核验和消费者端审核生效。

## 当前能力边界

程序已实现抖店适配器，结构或店铺身份无法确认时停止。商业字段检查仅覆盖实际DOM加载内容；虚拟SKU列表未逐行遍历。图片核验比较CDN路径与顺序，去掉缩放查询参数；不能把数量相同当内容正确。类目/售后等超范围变化不自动补齐。不要运行淘宝或泰国站上传器操作抖店，不把离线模拟通过说成真实店铺试传通过。

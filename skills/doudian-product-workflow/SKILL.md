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

当前版本已完成本地模拟与离线测试；真实Kimi上传适配器试传尚待用户连接扩展。首次联调先做只读连接/页面检查，不因测试程序重传此前已提交的4款商品。

## 本地工具

`scripts/doudian_check.py` 不联网、不调用模型、不修改店铺。使用已安装 Pillow 的 Python。

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

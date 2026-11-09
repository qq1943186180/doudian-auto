---
name: doudian-product-workflow
description: 直接通过抖店后台修改现有商品标题或完整方主图及详情，支持离线标题校验、只改标题受控试用和全量图片改版后独立读回。局部图片槽位替换或指定妙手编辑使用 miaoshou-product-workflow，持久批量队列使用 miaoshou-auto-batch；淘宝及海外 TikTok Shop 使用各自流程。
---

# 抖店商品改版

本地 `doudian-auto` 执行校验、上传、提交和核验；执行 agent 负责商品事实、素材质量和授权判断。

## 授权与字段范围

- 先确定店铺、商品字符串 ID、目标字段、版本和动作。仅“帮我改一下”未明确保存发布时，可准备方案，最终发布前需确认。用户已明确要求将指定商品改好并保存/发布，或已授权固定队列按约定标准完成时，可沿用该授权；正常换页、恢复和同版提交无需再次批准。
- 每次最终提交前，记录并展示店铺、商品 ID、最终标题、方主图/详情数量及目标槽位、非目标字段、是否上架；实际内容必须属于已授权版本。目标商品、字段或发布意图仍不清楚时才询问。图文保存与上架分别确认是否已获授权。
- 默认保留价格、库存、全 SKU、类目、品牌、物流售后、3:4 图和白底图。类目变更须有针对具体新类目的明确授权；没有时先展示原类目、建议类目及连带影响，再确认。平台推荐不构成授权。
- 必填属性仅可依据该商品原资料、真实 SKU/原图或用户确认补齐，记录字段、值及证据；未知值请用户补充。品牌、类目、服务条款、价格等保护字段变化仍须取得相应授权。程序拦截时保留证据，不修改状态或放宽比较来绕过。

## 选择执行路径

| 任务 | 入口与限制 |
|---|---|
| 标题检查/诊断 | `title check` / `title diagnose`，离线，不写店铺 |
| 仅改标题 | 先读 [标题生命周期](references/title-lifecycle.md)；`title apply` 省略 `--apply` 预览，写入属于待真实验收路径，需明确授权受控试用 |
| 完整标题及图片改版 | `prepare → upload → submit → verify`，上传适配器替换完整图片集；局部槽位需求不能强行转为全量替换 |
| 指定妙手或局部槽位 | 使用 `miaoshou-product-workflow`；持久批量队列使用 `miaoshou-auto-batch` |

## 环境与离线准备

先读 [环境、事实文件与本地检查](references/environment-and-facts.md)，确认真实源码目录、项目 Python、CLI 与所选浏览器。当前直接抖店适配器默认走 Ego 原生通道；浏览器未就绪时继续离线准备，保留任务，等待恢复。Kimi WebBridge 只是显式选用的兼容通道，不是默认路径。

```powershell
doudian-auto --json title check --title '<最终标题>'
doudian-auto --json title diagnose --title '<最终标题>' --facts '<事实.json>'
doudian-auto --json prepare --assets '<完整素材目录>' --title '<最终标题>' --url '<实际编辑链接>' --shop '<店铺>'
```

`prepare` 离线固化素材哈希，返回 `job_dir`；默认数据在 `~/.doudian-auto/jobs/`。标题或素材变化需重新准备不可变版本，不能覆盖旧 manifest；先处理同商品未完成任务。开工交叉检查项目 HANDOFF、批量队列、`~/.doudian-auto/jobs/` 和项目实际任务目录 `work/miaoshou-jobs/`，按店铺/字符串 product_id 查活动编辑及 submitting/unknown；查不到目录不代表无占用。此为人工协调，不等于跨工具原子互斥。

文案以真实商品和 SKU 为依据，可用参考文件中的免费课程检索补充方法；课程建议不能证明商品事实。需要新生图时参考真实匹配原图逐张生成，目视检查外形、颜色、数量、印字及规格。合格素材先完成再删除旧图。

## 上传、发布与读回

进入编辑器或采集快照前读 [浏览器操作与快照](references/browser-workflow.md)。从真实列表精确商品行取得编辑链接；新页核对店铺、ID、草稿/驳回及修改归属，保存原基线、全部目标图片顺序和保护字段覆盖范围。

```powershell
doudian-auto --json doctor
doudian-auto --json products --limit 20
doudian-auto --json read --url '<实际编辑链接>' --shop '<店铺>' --out '<before.json>'
doudian-auto --json upload '<job_dir>'             # 预览，不写页面
doudian-auto --json upload '<job_dir>' --apply     # 填写和上传，未发布
doudian-auto --json submit '<job_dir>'             # 预览，不发布
doudian-auto --json submit '<job_dir>' --apply     # 按已明确的发布授权执行一次
doudian-auto --json verify '<job_dir>'             # 只读重开核验
```

`upload`、`submit`、`title apply`、`title resume` 均通过省略 `--apply` 预览；仅 `upload`、`submit` 额外接受 `--dry-run`。其他子命令按自身契约执行，不能机械添加该参数。`title abandon` 无预览模式，执行即写本地结案记录。

| 图文任务状态 | 允许的下一步 |
|---|---|
| prepared | 核对计划后 upload；预览不写入 |
| editing / uploaded，未提交 | 查原任务和当前页，按原版本续传；预览完整后按授权 submit |
| submitting / unknown | 仅 verify 和只读调查；不重发、不换任务绕过 |
| submitted | 只读核验；可能仍在审核，不因旧标题或旧图片重发 |
| rejected | 记录明确驳回与提交状态，确认前次已结束及修正授权后处理；不盲目 submit |
| saved | 当前后台读回通过；消费者端生效需另有证据 |

代码以 browser.lock / job.lock 串行并在锁内检查同商品任务；当前批量 Writer 在同一 DATA_ROOT 下也持有 browser.lock；手工妙手页面和其他外部工具不受这把锁保护。进程锁不替代跨渠道持久任务核对，仍保持同商品单一写入者。进程仍存活时不得删除锁；`product_job_conflict` 不通过删目录或改状态解决。

逐项比较标题、每个目标图片的内容对应和顺序、非目标图片与实际采到的商业字段。虚拟 SKU 未完整读取、图片未加载、版本不明均记 `not_verified`；数量相同不能证明内容一致。CLI 的 `protected` 快照不能交给旧 `sections` 格式的校验脚本直接比较。

任务记录区分素材完成、已上传未保存、受理、读回匹配、审核中与消费者端生效。记录截图、JSON、HANDOFF 和任务映射，按项目要求回写 Issue。每轮结束前持久化续办状态，关闭本轮用完的项目标签；开工清理本项目遗留标签，未完成页先保留状态，只操作本任务所属页面。

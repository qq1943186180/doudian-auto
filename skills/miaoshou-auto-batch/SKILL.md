---
name: miaoshou-auto-batch
description: 通过 doudian-auto 持久批量队列修改抖店在仓商品的标题、5张方主图及前4张详情，准备素材与视觉审查并执行妙手/抖店双端核验。适用于完整图文批次；单品快速编辑或局部图片槽位替换使用 miaoshou-product-workflow，直接抖店后台改版使用 doudian-product-workflow。
---

# 妙手批量商品优化

Agent 核查商品事实、写标题、准备和目视审查素材；程序管理队列、租约、素材/证据哈希、串行浏览器写入和双端核验。正常批量任务通过 `doudian-auto` CLI 执行，不能绕过队列去页面补点保存或手改状态。明确授权的适配器修复可做限定范围的调试，仍保留锁、提交意图和未知结果约束。

## 范围与准入

- 已明确授权指定批次按约定标准改好并保存时，同版预检、续租、恢复和保存沿用授权，不逐品重复确认；范围或发布意图不明时确认后再写。
- 当前 Writer 只接受明确在仓商品、5 张已就绪方主图及至少 4 张已就绪详情；替换五主图与前四详情，后续详情保持。**前四个源图各自在整个详情序列中只能出现一次**，不是要求全部尾图互不重复。缺槽位或源图碰撞先隔离，不能改变完整预览比较放行。
- 保留全 SKU、价格库存、类目品牌、履约售后、3:4/白底图、审核及上下架状态。在仓策略 `preserve_warehouse_v1` 只允许前后当前状态均为 1、最终审核去向 startSaleType=1，其他字段及独立抖店核验仍须通过；不是上架授权。
- 上架、修改店铺自动下架规则或其他商业字段属于单独动作，须已有相应明确授权。后续售卖状态变化不通过重存图文修复。
- 开工交叉检查项目 HANDOFF、当前批量队列、`~/.doudian-auto/jobs/` 和项目实际任务目录中的 `work/miaoshou-jobs/`，按店铺/字符串 product_id 查活动编辑或 submitting/unknown。发现冲突查清归属，保持单一写入者。当前批量 Writer 与直接 CLI 在同一 DATA_ROOT 下共享 browser.lock，但未自动覆盖手工记录；目录查不到不等于无人占用，也不能消除检查后的并发竞争。

## 自动入口

`batch auto` 组合现有受控能力。执行前读 [自动调度与属性任务](references/auto-commander.md)：默认新鲜只读预检，`--plan`仅队列规划；`--apply --shop`包含已确认属性的独立发布以及ready队列图文保存，需对应授权。它不自动生成素材或替用户签历史结案证明。

## 命令与执行顺序

先确认当前 CLI/项目依赖。浏览器通道未就绪时继续离线准备并记录阻塞，不重复发送写请求。使用 Ego 前读当前 `ego-browser` 技能；`--endpoint ego` 必须放在子命令前。每个批次使用自己的固定 session，不能按域名抢占别的任务页。

```powershell
doudian-auto --json batch create --input '<products.json>' --shop '<店铺>'
doudian-auto --json batch status '<batch-id>'
# --product-id 可重复，不能写成 --product-ids 或逗号列表
doudian-auto --json --endpoint ego batch preflight --product-id '<id1>' --product-id '<id2>' --session '<本任务session>' --report-dir '<报告目录>'
doudian-auto --json agent next --owner '<稳定Agent名>' --batch-id '<batch-id>' --product-id '<商品ID>'
doudian-auto --json agent heartbeat --task-id <id> --owner '<稳定Agent名>' --token '<租约token>'
doudian-auto --json agent complete --task-id <id> --owner '<稳定Agent名>' --token '<租约token>' --artifacts '<manifest.json>'
doudian-auto --json --endpoint ego batch run --batch-id '<batch-id>' --session '<本任务session>'
# 预览和能力检查通过、已有对应保存授权后，执行一次受控任务
doudian-auto --json --endpoint ego batch run --batch-id '<batch-id>' --product-id '<商品ID>' --limit 1 --session '<本任务session>' --apply
doudian-auto --json --endpoint ego batch resume --batch-id '<batch-id>' --session '<原任务session>'
# 核对原状态及恢复条件后增加 --apply；未知保存只做双端只读恢复
```

`batch create` 创建本地队列，`agent next/heartbeat/complete` 会修改租约或队列，不是预览。`batch run/resume/repair-title` 省略 `--apply` 才是各自的预览入口；run 仍可能检查浏览器状态，不承诺完全离线。不向这些命令机械添加 `--dry-run`。

1. 先 `batch preflight` 精确指定商品及当前 session：不领取/迁移/修改队列行；逐品检查占用、官方全量 SKU、保护字段和必填属性。逐品错误可继续，需人工处理浏览器时停止扫描并记录未处理 ID。结果会过期，领取同一商品/版本后仍需新鲜完整妙手基线。
2. 输入为 JSON 数组或 `{"products":[...]}`；每行 product_id/productId 为字符串，shop 可逐行或统一提供。记录真实编辑链接、原标题、当前售卖状态、事实、真实参考图及读回来源。已有生成图不能作为唯一事实参考。
3. `agent next` 原子领取并返回不可变 target_version 和可选课程检索结果；长任务到期前 heartbeat。manifest 必须绑定该字符串版本与同商品 ID、title、五条有序 mains 路径和四条有序 details 路径。过期租约、版本不符、标题/尺寸/哈希/重复图检查失败不能进入 ready。
4. 准备素材前读 [绑定式视觉审查](references/visual-review.md)。真实查看每张原始参考和九张输出，按精确资产哈希/版本记录身份、颜色、数量、印字及规格。失败槽位最多重做一次，第二次失败隔离该商品，保留其余合格图和失败证据；不能改失败记录为通过。原图上传探针不算完成新图要求。
5. ready 后计划保持不可变；修改已接受标题/素材需新版本。准备阶段未进入 ready 的失败候选可在原租约内纠正。程序保存 manifest 路径与哈希。不得两 Agent 同时准备同商品或多进程写同 session。
6. 普通写入由程序 `execution_readiness` 实时要求 writer_ready=true。当前检查基于浏览器状态、WRITER_REVISION 和三品验收证据，不是任意源码变更自动失效。历史验收不直接授权当前环境写入；代码变化时维护者须评估版本及重新验收。

新 Writer 的受控验收需用户明确授权三件不同商品，使用 `batch run --product-id <id1> --product-id <id2> --product-id <id3> --limit 3 --acceptance --apply` 并指定原 batch/session/endpoint。该路径用于产生新验收，不能机械要求它先满足正式 writer_ready；也不能绕过商品、视觉、SKU、保存与双端核验闸门。只有三品完整证据通过程序确认才能开启正式 Writer。

## 阻塞状态与恢复入口

先读本地状态及证据。下表定位入口；构造 proof 或执行恢复前必须读 [恢复细则](references/recovery.md)，不能仅靠表格放宽条件。

| 阻塞或场景 | 入口与必要条件 | 禁止的绕过方式 |
|---|---|---|
| submitting / unknown、submitted 待核验 | 原任务只读调查及双端读回；resume 中未知记录只读处理 | 重发保存；以旧标题或中间响应当失败 |
| ego_operation_unsettled | 查 pending-command.json 和 token.result.json；完整无迟到副作用结果才允许新观察；精确匹配超时例外才可 batch recover-read --session ... --proof ... | 删除标记、换 session/TaskSpace、重复关页 |
| ego_state_locked / ego_transport_unknown / ego_cleanup_unknown | 保留锁/队列/收据，按原 session 证据调查；未决时先看本地记录 | 重放命令、二次 finish、新建空间掩盖未知 |
| 外部历史工作 | batch reconcile --evidence ... --shop ...，隔离并保留原事实 | 把 reconcile 当已核验或清 unknown |
| external_work_requires_rebaseline | batch rebaseline --task-id ... --proof ...；零队列保存、无未知/制品/映射/基线/占用，绑定历史结论和完整双端快照 | 删记录或覆盖未知历史保存 |
| official_repeat_snapshot_unstable: | batch recover-prepared --task-id ... --proof ...；原 manifest/版本、零上传保存、两轮新鲜完整双端证据 | 手改 ready 或免除后续 preflight |
| writer_detail_source_collision / 缺事实或必填 | 保留合格素材，batch quarantine --product-id ... --reason ...，按具体证据处理 | 猜属性、弱化比较或第三次生成失败槽 |
| 历史 ego_target_not_unique 点击前失败 | 仅程序 restore_proven_preclick_failure 核验完整审计链；非通用 CLI 解锁命令 | 只凭 click_issued=false 或旧标题解除未知 |
| 标题补救 | batch repair-title --product-id ...，核实已知失败及原授权；仅正式路径满足条件才 --apply | 未知提交改走标题页重发、重新上传九图 |

## 核验、排查与收尾

程序在保存前持久化提交意图和 submitting/unknown，并串行保存一次；响应丢失只能只读恢复。`saveTempBatchTask` 是中间响应，不能证明商品成功或未提交。旧列表标题、缺字段、部分加载均不能作为重存理由。

核验须覆盖妙手/抖店精确标题、五主四详及未改尾图、全部 SKU/规格/编码/启用状态/价格库存和其他保护字段。缺失/未加载记 not_verified。已合格生成图复用必须重新绑定来源/本地哈希、同槽位及双端远端内容证据；永久资源 ID 相同不自动失败，也不能单凭 ID 相同放行或重存。

遇到控件、SKU读取或窗口问题，再读 [Writer 行为与浏览器排查](references/writer-behavior.md)。其中选择器、原生/兼容点击、窗口恢复是实现细节，不是正常任务的额外手工动作。缺属性先查原字段、原图和该商品真实供应商链接，证据不足再问用户；其他合格商品继续。

每轮开工清理本任务遗留项目标签，未完成页先持久化；结束保存队列/读回/可续办状态后关闭本轮用完的自有项目页。未决操作或清理收据未知先按恢复细则处理，不能重复 finish。保留用户及其他用途页面，清理记录存在不证明浏览器进程已退出。按项目要求维护 HANDOFF/T-ID、提交推送及回写 Issue，素材、任务和登录信息留本地。

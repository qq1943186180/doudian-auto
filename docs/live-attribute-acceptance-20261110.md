# 属性发布实页验收（2026-11-10→11）

任务：T-20261110-009 / Linear 194-76；执行：codex-live-one；代码：49e2f24。

## 验收范围与结果

销霁百货现有商品 `3848316465015030183`，原商品标题为“厨房壁挂式免打孔多功能置物架锅铲勺子锅盖刀具收纳挂架”。依据原标题及全部20个SKU的“贴片款”，仅补类目属性“安装方式=免打孔式”。选项取自当日真实控件，不猜选项或其他商品资料。

| 检查 | 结果 |
|---|---|
| 官方属性流程发布 | 单次点击，页面真实返回提交成功/accepted |
| 持久状态 | submitting/unknown先落盘；submitted后只读恢复至saved/verified_by_readback |
| 官方新页 | 安装方式已保存，必填进度100%，无草稿/驳回 |
| 妙手新页 | 同商品ID、安装方式为免打孔式，页面显示审核通过/下架 |
| 图文 | 原标题、5主图、12详情图的有序素材身份均一致 |
| SKU | 完整20个SKU与官方响应交叉核对通过 |
| 商品上下架 | 原后均status=1，仍在仓库；本步未上架 |
| 原始状态字段 | startSaleType 0→1按已有preserve_warehouse_v1记录，checkStatus 1→7单独记录；不声称所有原始字段逐字不变 |
| 其他商业字段 | 使用既有保护比较器及仓库策略核对通过，含3:4图CDN素材身份 |

此验收仅证明这件商品的属性路径，未执行新主图/详情上传，不计入三品新上传Writer验收，不证明全量图文改版或消费者页面展示。

## 实页发现并修复

1. `read_skus`会刷新页面，属性路径只轮询详情，导致声明/缩略均12张而预览始终0张。现在复用现有SKU重载后定位详情的等待逻辑，并临时启用后台焦点模拟；成功/失败均清理焦点，预览阶段不重读SKU、不丢未保存输入。
2. 原程序把全部`role=alert`当作错误。实际“5项2天后变必填”是蓝色`ecom-g-alert-info`，当日必填100%、无红色表单错误。现在仅将这个已观察的信息形态单列为`notices`；未知alert、warning和表单错误仍阻断。旧T-008“平台拦截、点了也不会成功”的判断缺乏真实提交证据，已纠正。
3. 属性比较器用原始图片URL比较，CDN主机变化造成已成功保存后的误报。现在复用既有`resource_key`按槽位比较，少图、重排、重复替换和换图仍拒绝；比较前先保存`observed-readback.json`，避免丢失失败现场。

在第二项修复前任务尚处editing/not_submitted，使用已有abandon流程重开核查后续同版本；首次发布后始终只读，未再次保存。未操作WorkBuddy商品50的editing任务、两件unknown任务或已verified商品。

## 验证

- `.venv/Scripts/python.exe -X utf8 -m pytest -q`：591 passed，176.01秒。
- `npm test`：101 passed，0 failed。
- 属性专项20项通过；包含刷新后预览挂载、读失败清理焦点、预览不丢输入、CDN轮换、真实图片变化、提交后证据落盘及恢复不重发。
- 原队列只读重查：44 blocked / 17 verified，没有改变队列状态或保存次数。

## 本机证据与续办

原证据不进入Git。`work/codex-live-one-20261110/`保存计划、选项、官方/妙手前后快照、妙手属性DOM、`dual-readback41.json`及最终`RESULT.json`。持久属性任务在`~/.doudian-auto/jobs/attributes-3848316465015030183-f4eb30ca5f9b/`，含before、preview、fields、submission、observed-readback、readback及state。

用户完成妙手授权后复用原TaskSpace20，未新建空间绕过授权；结束时确认仅3个agent页面并finish关闭，用户其他页保留。该空间已结束，不能续用旧Page标签。

仍待处理：正式preflight仅把needs_agent作为新素材候选，blocked行会跳过，不能把报告总标签当成实际逐品读取；原候选22官方可读，妙手精确ID和店铺查询为0，单品UI同步success后仍0，暂不编辑。完整9图及上架应按正式恢复/Writer路径继续，不能直接改状态放行。

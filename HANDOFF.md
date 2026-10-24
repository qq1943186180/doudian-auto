# 抖店本地上传与妙手商品编辑

更新：2026-10-24（Asia/Shanghai）；Agent：codex-miaoshou-product-3848316916011762046。
主工作目录：C:/Users/19431/code/clis/doudian-auto；私有仓库 qq1943186180/doudian-auto。
本次隔离分支：codex/miaoshou-product-skill；主目录 cli.py 的既有未提交改动未纳入本任务。

## 给人的说明

### T-20261024-002 · 194-66 · 妙手修改用户指定商品

- 状态：done；商品3848316916011762046，复用已核验assets-gpt的5主图+4详情，无新增生图费用；标题已满足目标而保留。
- 妙手UI单次“保存到抖店”成功，实际响应result=success；changeFields仅mainImg、descImg。新页妙手与抖店均逐槽读回匹配。
- 全量24个SKU、价格库存、类目品牌、运费售后、限购发货、3:4/白底图均保留；保持原下架，未加载草稿、未见驳回；消费者端和最终审核未单独验收。
- 证据：本聊天工作区work/miaoshou-jobs/3848316916011762046-gpt-20261024（plan/state、上传响应、save-response、miaoshou/official-verification）；商品数据不进Git。
- 旧抖店editing任务f584fd3e7a49经状态/进程/独立基线核查后用abandon正常结束；旧编辑页不发布，不跨渠道绕过提交未知。
- 中途Escape误关未保存商品窗口；确认未发保存请求后在新页恢复同套素材，最终只保存一次。上传临时src不算完成，必须等正式successUrls和最终槽位。
- 本次实测已补入skill参考并同步安装版；不同标题实际写入、多款连续处理、保存断连恢复仍未验收。没有改原抖店CLI。

### T-20261024-001 · 194-65 · 创建并安装妙手商品编辑 skill

- 状态：done（技能创建与本机安装）；范围不含线上商品写入验收，本次未改商品。
- 源码：skills/miaoshou-product-workflow；安装：~/.codex/skills/miaoshou-product-workflow。
- 内容：标题、方主图、详情的妙手浏览器流程；字段保护、提交未知只核查、抖店独立读回。
- 边界：没有 miaoshou-auto CLI，也没有程序强制的妙手任务锁；当前为 agent 执行的流程约定。
- 本任务创建时只读核对弹窗、分组、标准多文件input与读取响应；后续真实保存证据见T-20261024-002。
- 旧 HANDOFF 完整原文已归档到 docs/handoff-history/2026-10-24-before-miaoshou-skill.md，保持原字节；原文件313行。
- 验证：系统quick_validate在源码/安装版均通过；4文件SHA256一致、相对引用与UI元数据有效、ZIP校验通过；实现提交eeef97f。
- 后续只在具体授权任务中扩展验收，不为测试改商品。

### 现有抖店程序的有效交接

- 原 T-20261022-013 / 194-54 记录：商品3848316916011762046全量改版已发布、审核待定；基线稳定采集和虚拟SKU误报修复见2ab9fa7，交接373559c。本次没有重新核验线上状态。
- 原 T-20261022-012 / 194-54 记录：title-only代码评审阶段完成，真实不同标题的写入验收仍待具体授权任务；原证据见归档和991d13d，不因新增妙手技能自动升级验收状态。
- 历史任务、详细恢复缺陷与原始测试记录见完整归档；T-ID编号仍以docs/agent-workflow/T-ID-MAPPING.md连接Linear，不迁移或删除。
- 全局命令doudian-auto及桌面“抖店本地上传”沿用；主程序不生成图片、不调用付费模型API。

## 数据与算法

### 抖店专用程序

- 恢复入口：skills/doudian-product-workflow/SKILL.md → references/browser-workflow.md → 对应Issue。
- doctor检查连接；read按实际官方编辑URL采集；prepare固化本地素材；upload --apply只写预览；submit --apply发布；verify仅重开核验。各命令的实际参数与能力以当前源码/帮助为准。
- 任务位于~/.doudian-auto/jobs/；同商品未完成任务不可绕过。发布前写submitting，结果未知只verify，不反复发布或改状态放行。
- 仅默认写标题、方主图和标准详情。类目、价格库存、SKU、履约保留；不可观测字段不得当作空值或未变。图片按内容对应、路径与槽位顺序核验，不仅比数量。
- 官方编辑器存在隐藏DOM副本、详情懒加载、延迟分区、虚拟SKU等；修复依据与剩余范围见源码、原skill和历史归档。
- 历史HANDOFF曾含过时标题下限和“尚无真实上传”措辞；应按当前title.py、原skill和较新任务事实判断，不照抄旧总结。

### 妙手浏览器流程

- SKILL.md是执行入口；references/browser-workflow.md记录真实控件与读取响应；references/recovery-and-verification.md记录证据、恢复和核验约定。
- 通过kimi-webbridge使用当前Edge登录态，妙手快速编辑URL为https://v2-dd.chengji-inc.com/product/quick_edit；按店铺与字符串商品ID定位。
- 主图逐槽替换；详情独立上传。所有分组、上传限制和权限现场读取；3:4图不能全删的接口限制不自动绕过。
- 页面实际getProductBaseEditInfo响应辅助读取；uploadImage返回正式successUrls后核对槽位；saveEditProductInfo仅观察UI触发结果，不重放写接口；不留请求头/凭据。
- 记录计划、基线、素材哈希、预览、提交意图与读回；保存点击一次，未知不重放。妙手与抖店读取版本须区分草稿、审核与生效版。
- 这份技能没有实现跨程序互斥；必须同时检查原抖店任务并串行运行，不能宣称已有自动恢复/锁保证。

## 给下一个AI

- 先读AGENTS.md、git status --porcelain、本文、T-ID映射与194-66；skill创建见194-65，旧抖店任务见194-54及归档。不能捎带主目录cli.py改动。
- 图片单款保存已有真实验收；标题新值、多款连续和保存断连仍未验收。SKU表后台页可能只渲染20/24行，临时focus emulation后滚动等待可读齐，结束关闭；不要用Escape关闭残留图片弹窗。
- 原抖店程序与妙手任务格式不同；不能把妙手目录交给doudian-auto upload/submit/verify，也不能拿旧sections快照比较器直接比妙手响应。
- 所有页面写入串行；不关闭他人编辑页。连接失败读kimi-webbridge-boot；可start，不擅自stop/restart/upgrade。验证码与登录交给用户。
- skill结构校验使用系统skill-creator/scripts/quick_validate.py；新skill无可执行脚本，不需要为此重跑未改动的全部上传器测试。
- 维护本文≤250行，每任务块≤15行。新增历史按docs/handoff-history归档；修改前读最新内容，并在相关Issue公告。

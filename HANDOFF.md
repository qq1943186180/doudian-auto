# 抖店本地上传

🔴 **出图强制约定（用户 2026-11-14 重申，11-14 又纠正通道）**：所有商品图**一律用网页版 GPT/ChatGPT 生图，在「生图项目」`C:/Users/19431/tb-auto` 里做**，通道是 **ego-browser 直接**（`browser_command` → `ego_backend.command_ego`，在 ego 里打开 chatgpt.com）；**2026-11-04 起 Kimi WebBridge 回退已整体删除，10086 不用了**；零 API 成本；**禁止在本项目里调内置 ImageGen**。出好的图再拷回本项目素材目录。详见用户级 `MEMORY.md`。

更新：2026-11-19 13:20（Asia/Shanghai）；当前执行：workbuddy；最近任务 T-20261119-001（**变长槽位 5主2详 首次真实写入成功，双端 verified**）。旧主体由Codex起草、WorkBuddy核实，本轮修复及验证以最上任务块为准。前一轮 T-20261118-001：task 58 商家编码读不全的真因是 `scrollIntoView` 撤销了 holder 推进，修复后 121/121 全读到。执行前仍须重查仓库和本机状态——本文数字是快照，不是实时值。队列 61 件＝**23 verified / 32 blocked / 6 closed_unreachable**（2026-11-19 13:15 实读 batch.sqlite3；task 60 本轮转 verified）；blocked 里只剩 3 件 `submission_state=unknown`（task 11 定性、task 19/42 缺真实参数）。

> **39 件 blocked 按「卡在谁身上」互斥分类，合计 39（2026-11-14 18:55 逐件重检后实测）。程序侧能自己推的已经推到头。**
>
> ⚠️ **下面是 11-14 的快照，已过期**：2026-11-18 现状为 **22 verified / 33 blocked / 6 closed_unreachable**（12/22/33/36/46/52 经「精确 ID 0 行 + 同店对照 1 行」结案为不可达）。最新分类与变化见 T-20261118-001、T-20261117-007、T-20261117-006。
>
> | # | 类别 | 件数 | task | 需要谁 |
> |---|---|---|---|---|
> | ① | 缺平台必填属性的真实值 | **9** | `23`(5 项) `28` `50` `31` `43` `45` `54` `19` `42` | **你给值**——1688 源头没有，程序不猜 |
> | ② | 视觉复核失败 | **5** | `15` `16` `27` `34` `48` | **去 tb-auto 用网页 GPT 重出图**（零 API 成本）；`48` 2 张/`16` main-5 已重出，见下方 |
> | ③ | 源素材槽位不足 | **8** | `39` `55` `57` `59` `60` `61` `46` `52` | **改写入器**——生成图救不了，缺的是源商品槽位 |
> | ④ | 前 4 张详情重复原图 | **2** | `49` `56` | **改写入器**——按图查找替换会同时改多处 |
> | ⑤ | 需人工核实历史版本/素材 | **8** | `1` `3` `4` `6` `8` `7` `13` `9` | **人工核实**——历史 `stage` 含 editing/completed、`status` 全 `None` |
> | ⑥ | 结构性不可达 | **4** | `12` `22`(不在妙手) · `33`(抖店也没有) · `58`(列表封顶) | **别再重试**，重试只会得到同一条 `page_timeout` |
> | ⑦ | 平台侧需你去后台处理 | **2** | `51`(确有草稿/驳回) · `36`(商品已删除) | **你** |
> | ⑧ | 待裁决 | **1** | `11` | **你一句话**：按权威 SKU 摘要 32/32 一致结案？ |
>
> **视觉失败根因（2026-11-14 查证）**：`15`/`16`/`48`/`49` 全栽在同一处 —— **生成模型重绘/新增源图上的小字与细纹样**（15 方孔钱凸字、16 蓝鸟纹样、48 小狗款英文小字、49「器」被写成「王」），所以「重试一次」两版都失败。正解是参考图高保真编辑、不让模型重画（同 T-20261114-017 的 task 37）。`48` 只需重出 `main-5` 与 `detail-3`，其余 7 张已通过。
>
> **2026-11-15 01:44–03:20 出图进展**：按约定在 tb-auto 走网页 GPT（ego 通道、ChatGPT「生图」项目）重出 `48/main-5`、`48/detail-3`、`16/main-5` 共 3 张并拷回 `work/materials-20261114/task48-retry/` 与 `task16-retry/`（各带 `review.json`）。`16/detail-3` 前三次超时（362s 截断 / 两次 600s `GENERATION_TIMEOUT`），**真因已查明并修好**：`references/detail-3.jpg` 实际是豹纹款尺寸图，提示词却写成蓝鸟款 → 模型回文字拒绝出图，等待器仍傻等到硬超时。改用 `main-5.jpg` 并让提示词对齐后 105.65s 出图，已拷回并复核。🔴 教训：遇 `GENERATION_TIMEOUT` 第一件事是**读 ChatGPT 页面尾部文本**，别重发。下一批清单已落 `work/materials-20261114/next-batch.json`：`27` 槽位与正确结构已查明（单端夹式安装臂；其 `detail-3` 参考图是 1200×128 横条切片，不能直接重制）、`34` 完全无失败证据需先复核、`15` 源图小字不可读建议只试点 1 张。**均未改队列状态、未写商品、未改历史 artifacts.json**；要真正推进这两件，还需补「视觉失败件如何回到 needs_agent」的受支持命令（当前没有）。
>
> **补充事实**：③ 里的 `46`/`52` 与 ⑥ 的 `12` 一样**不在妙手**（写入路径不通），槽位不足只是第二层原因；
> ④ 的 `56` 同时缺「材质+适用年龄」，但详情重复原图不解决也写不进。
>
> **另需授权**：3 件商品（含 `3853482303460343870`）是「审核通过但商家自主下架」，行内有「上架」按钮。
> 上架是对外经营动作，**没有明确授权就不自动点**（`dropship.py:208`：初版只允许放入仓库）。

## 给人的说明

### T-20261119-002 · ⛔ task 58 写入失败：**妙手判定「尺码表数据非法」，整个任务零变更**（非代码缺陷）

- **🔴 真正的失败原因（2026-11-19 19:35 只读取证，妙手「批量修改历史」→任务详情页）**：
  - 历史列表第一条即 task 58 的提交：`综合修改(多字段修改) | 2026-11-19 17:40:04 | 商品数 1 | 状态=完成 | 成功数 0 | 失败数 1`。
  - 任务详情页（`/product/batch/history/detail?taskId=36278985`）明确写：
    **状态「更新失败」，失败原因「尺码表数据非法，存在尺码表值重复，或尺码表和 SKU 尺码不吻合，
    你可以前往【批量修改】【尺码表】【方式1】AI智能生成后重新提交」**。
  - → **整个批量修改任务失败，成功数 0，商品零变更。**
- **🔴 推翻此前两条错误结论**：
  1. 之前说「标题已保存成功」是**误判**：`baseline.title == artifacts.title`
     （都是「室内健身鞋男女套脚软底条纹运动鞋多色可选常规加绒款」），**标题本来就没变**，
     并非"标题保存了、图片没保存"。
  2. 之前推断「5主2详 + 新上传临时图路径有验收缺口」**不成立**：图片根本没进入处理阶段，
     失败发生在妙手服务端对尺码表的校验，与图片路径、临时图、空行、addDescImage 全无关。
- **仍成立的观察（保留，但不是根因）**：客户端链路本身是正确的——复现 prepare 后预览里
  `new_mains/new_details` 就是目标图；真实提交动作 `activate_batch_save` 的 guard 为
  `options=[new,onlyPreview,replaceImgsByImgUrls]`、5 张目标 mains、**pairs 只有 2 对**（尾部空行已被正确剔除）；
  实际保存 API `POST /api/v2/product/batch/saveBatchTask` 返回 200。这些只证明"提交前状态正确"。
- **task 58 的真实性质（修正后表述）**：妙手服务端**已确定**以「尺码表非法」拒绝更新（任务 36278985：终结、失败、成功数 0）。
  进一步只读定位到的现象是：妙手快速编辑页尺码表区域反复提示 **「脚长(cm)最大数值需≤40」「脚宽(cm)最大数值需≤15」**，
  而本商品 **脚长超 40 有 3 行（40-41/42-43/44-45）、脚宽超 15 有 4 行（38-39 起）**；
  抖店官方侧尺码表本身**无重复、与 SKU 的 11 个鞋码集合完全一致**。
  ⚠️ **但这不等于"40/15 超限"就是该次拒存的确切触发条件**：前端提示与批量服务端错误之间，
  缺少同次请求的字段级错误映射；也**不能**据此断言"商品数据本身非法、与代码无关"（Codex 明确指出该绝对归因超出证据）。
- **🔴 为什么本轮没有"修好"尺码表（Codex 裁决，`/tmp/codex-t58-sizechart-20261119.md`）**：
  现有脚长/脚宽数值确实可疑（把鞋码当厘米填：44-45 码填 45cm，而 44 码实际脚长约 27cm），
  但**修复必须有本商品的真实尺码依据**（供应商尺码表或实测资料）。
  **按通用鞋码对照表猜填属于"无依据填值"，违反项目「不猜属性」原则**；仅满足上限/递增/不重叠也不能证明真实。
  B（把超限值压到 40/15）制造失真数据，拒绝；C（删除超限行）破坏与 SKU 的对应，拒绝。
  → **正确做法是取得真实依据后只改脚长/脚宽（尺码列与 121 个 SKU 对应不变），或由用户在妙手后台
  自行用【尺码表】【方式1 AI 智能生成】让平台生成**——程序不得替用户编造商品数据。
- **本次写入的实际影响**：**零字段变更**（标题、图片、保护字段全部维持 baseline），无需回滚。
  `submission_state=unknown` 是提交时未拿到响应所致；妙手任务已终结且失败，本地 unknown 是待核销的旧状态。
- **若日后取得真实尺码依据，再写入必须依次具备（Codex 列明）**：
  ① 旧提交结案（任务 36278985 终结/失败/成功 0 + 读回）走受支持的恢复流程，不直接改库放行；
  ② 修复依据与前后差异留档，只改脚长/脚宽，保存后双端复读确认校验提示消失、SKU 对应不变；
  ③ 刷新基线并重新 preflight/recheck，复核目标素材与槽位计划仍适用（不得沿用过期准备）；
  ④ 重新 prepare→upload→submit→verify，只提交一次；验收需妙手新任务终态成功 + 抖店独立读回，
  **不能以 HTTP 200、任务创建成功或"标题本来就相同"判成功**。
- **完整链路（已跑通到提交）**：preflight（含 SKU 有限重试）→ recheck → agent next →
  Codex 内置生图 7 张 → agent complete → `batch run --apply` → 妙手任务失败（尺码表）。
- **素材与诊断脚本**：`work/materials-20261119/task58/`（gitignore）。

### T-20261119-002-旧记录（已被上面取代，保留以防丢失上下文） · 图片未替换的初步分析

- **发生了什么**：task 58（`3793430313384935495` 室内健身鞋，121 SKU，5主2详，仓库中）走完 preflight→recheck→agent next→
  Codex 内置生图出 7 张素材→agent complete→`batch run --apply`。写入返回
  `state=blocked / submission_state=unknown / miao_matches=false / doudian_matches=false`。
- **只读核查结论（未重复提交）**：用只读诊断直接调 `_finalize_target_mappings` 拿到被吞掉的确切异常：
  `final_asset_unchanged mains:1 保存后仍是原图片，目标替换未读回`。逐槽比对 URL 关键 hash 段：
  - 妙手与抖店读回的 5 主 2 详**全部仍是 baseline 原图**（CDN 前缀不同但 hash 段一致）；
  - `upload_map` 里 7 个 tmp_upload 临时图 UUID 与线上图片完全不同；
  - 标题**已**保存为目标标题，`protected_match=true`，两端数量 5主2详都对。
  即：**标题保存成功、7 张图片一张都没替换进去。**
- **保存前证据（证明上传侧没问题）**：`writer_preparation_json` 的 `prepared_assets` 7 张
  `asset_state=staged`、`content_verification.match=bytes`、`source_sha256` 与本地目标图一致，
  `fresh_form=true`、`reused_slots=[]`、`uploaded_slots` 7 个。→ 临时素材上传且字节比对通过，
  **但最终商品没有采用它们**。
- **Codex 裁决（`/tmp/codex-t58-unchanged-20261119.md`）**：
  1. 根因**不能确定**是 tmp_upload 不被采纳 / 只提交标题 / addDescImage 清理所致——三者均未被现有证据单独证实；
     缺的关键证据是"实际提交采用的逐槽图片映射 + 服务端处理结果"。
  2. **当前必须维持 blocked，不能纠正性重存**：图片不匹配+标题匹配不能证明原提交已终结；
     授权本身不替代终结证据。
  3. 后续若做纠正性保存，推荐**新增专用图片修复入口**（类似 `title_repair` 的受控设计，只写图片），
     且必须先证明"7 槽实际替换映射与修改后预览均指向目标"，保存一次后双端逐槽验证，不匹配不得记成功。
  4. `_finalize_target_mappings` 这次**正确拦截了失败，不能放宽它来解决**。
- **确定暴露的验收缺口**：task 60 只验证了「5主2详 + 永久图复用」路径；**「5主2详 + 7 张新临时图」路径未被覆盖**。
  已确定的问题是"临时素材已上传且内容正确，最终商品却保留全部原图"，应在 batch writer 的
  「上传素材 → 表单绑定 → 预览 → 实际提交/持久化」链路定位。
- **本轮同时完成的独立修复（已测试、待提交）**：官方页 SKU 商家编码读取的停滞判定改为
  **几何签名 + 时间窗**（不再用固定 6 轮），删除"到底立即回顶"的旧行为；preflight 层新增
  仅针对 `official_sku_code_incomplete` 的**最多 3 次**重试（每次 fresh 页面，只接受单次完整覆盖校验通过的证据）。
  task 58 的 121 SKU 正是靠这个才拿到 `eligible=true`。回归：pytest 94 passed（目标文件）、npm 125 passed。
- **状态**：task 58 维持 `blocked / submission_state=unknown / attempts=1`，**零重复提交、零字段再写入**。
  素材与诊断脚本在 `work/materials-20261119/task58/`（gitignore）。

### T-20261119-001 · ✅ 变长槽位 5主2详 首次真实写入成功：双端 verified（task 60）
- **结论**：task 60（`3784643089604411407` 波浪吸音棉，仓库中/下架）完成端到端写入并双端读回：
  `state=verified`、`submission_state=verified_by_readback`、`miao_matches=true`、`doudian_matches=true`，
  `submission_attempts=1`。队列 **22→23 verified / 33→32 blocked / 6 closed_unreachable**。
- **素材通道纠正（重要）**：用户问「如果使用 codex 生图呢」后核实——tb-auto 里存在**两条**完全不同的路：
  ① 需要 `npx -y openai-oauth@latest` 起 `127.0.0.1:10531` 的 `/v1/images/edits` API 通道（当前没装、端口无响应，不可用）；
  ② **Codex CLI 自己的内置 `image_gen` 工具**（实测可用，原图 1254×1254，走订阅额度）。
  T-20261118-006 把"codex 生图"整体判成不可用，是把②误当①了，**该结论对②不成立，已纠正**。
  ②正是 tb-auto `src/services/codex_image_generation.py` 里的既有正规流程（`CODEX_MODEL='builtin-imagegen'`，
  注释写明"人工交接：人在 Codex 里出图"），且 `builtin-imagegen` 本就在 `visual_review.GENERATORS` 白名单内。
  **边界必须记清**：这是 Codex 订阅额度的内置生图，**不是**被禁的 WorkBuddy 内置 ImageGen（5-10 积分/张）。
- **7 张素材**：用 Codex 内置 `image_gen` 的 edit 模式逐张产出（5 主 1254² + 2 详 1024×1536），
  改动方向统一为"只把纯色背景换成暖米色→浅杏渐变"，商品/中文/规格数字/色卡/步骤全部保持。
  逐张目视复核：文字**逐字正确、无乱码、无新增元素**；detail-1 量化 1993 匹配/84.7% 内点/残差 0.31px、
  63.5% 像素显著变化（证明是真实重绘而非原图重编码）。main-5 首版被提示词误改成蓝底白字，已重出还原浅蓝底深色字。
  归档 `work/materials-20261118/task60/{target,prompts,source.json,artifacts.json}`（work/ 被 gitignore）。
- **新增代码修复（本轮唯一生产代码改动）**：妙手页面在详情选图/上传后**自行把「方式5 添加首部/尾部图片」勾上**
  （实测 7 张全部上传成功后 `addDescImage` 变 checked），`verify_prepared` 的 `option_scope` 因此拒绝
  （判据 `selected_enabled_options != {'new','onlyPreview','replaceImgsByImgUrls'}`）。
  Codex 裁决三选一：**A 清理真实表单状态（正确）** ＞ B 放宽白名单（会让"方式5 空勾"蒙混）＞ C 过滤观测（隐藏真状态）。
  落地：`_add_desc_image_state()` 只读探测 + `_clear_add_desc_image()` 仅在 enabled&checked 时才取消并返回 True；
  `prepare()` 在每张详情上传后、点预览前清理，并在预览后若又被勾回则清理+重生成一次预览（保证预览与表单一致）。
  公开 `_REQUIRED_OPTIONS` 与严格等值校验**未放宽**。测试 `tests/test_miaoshou_batch_editor.py` +2 条
  （四种状态分支、点预览前方式5 必须为 False），该文件 73 passed。
- **完整真跑命令序列**（可复现，全部 `--endpoint ego --session miaoshou-auto-batch-20261028`）：
  `batch preflight --product-id … --recheck-blocked --check-miaoshou --report-dir …` →
  `batch recheck --task-id 60 --proof <summary.json>`（blocked→needs_agent）→
  `agent next --owner workbuddy --product-id …`（→agent_claimed，拿 token/target_version）→
  装配 source.json+artifacts.json（5 主 2 详、5 项逐图检查、`generator=builtin-imagegen`）→
  `agent complete --task-id 60 --owner workbuddy --token … --artifacts …`（→ready）→
  `batch run --apply --product-id … --limit 1`（→verified）。
- **过程中的两次卡点（均已解决，非绕过）**：
  ① `ego_error`（`page.click` 被 `<div> intercepts pointer events`）：space 67 的 task 已 ended，
  `claimTaskSpace(67)` 接管同一空间后重跑即过——不是新建、不是绕过。
  ② `ego_session_changed`：预检中途 `align_space()` 把 state 从失效的 space 15 改写到 67，第二次校验不一致；
  重跑一次即自洽（state 已稳定在 67）。
- **待办**：全量 pytest 与 npm 回归（本轮在跑）；Codex 复审本次 addDescImage 修复；改动提交。

### T-20261118-006 · 用户提「用 codex 生图」：通道存在但当前不可用，mask 不能保像素，不作交付路径
- 用户问「如果使用 codex 生图呢」。实测 + Codex 裁决（`/tmp/codex-codexgen-20261118.md`）：**E 路径不作为 task 60 交付方案**。
- **通道事实**：tb-auto `src/services/codex_api_image_generation.py` 走 `/v1/images/edits`（gpt-image-2，强制带原图），
  默认 base_url `http://127.0.0.1:10531/v1`（preset「Codex OAuth 本机代理，消耗 Codex 额度池」，
  注释要求先跑 `npx -y openai-oauth@latest`）。配置 `enabled=False`、`10531` 端口无响应、
  `openai-oauth` 未全局安装、`~/.codex/config.toml` 无 10531 代理配置（指向 `chatgpt.com/backend-api/codex`）。
  **当前不可执行**：Codex CLI/订阅/auth.json 的存在不能证明有 `/v1/images/edits` 代理；官方 `app-server` 是 JSON-RPC，
  不能充当兼容接口。证据不足以断言永远起不来，但当下这条路不通。
- **mask 不解决 D 死结**：gpt-image 的 mask 是**编辑引导，不保证严格遵循边界**（OpenAI 官方语义）；
  「mask 外模型不碰、原像素原样保留」前提不成立。detail-1/2 文字压色卡/泡棉纹理，即使整块保护文字+纹理，
  新旧区边界仍可能有纹理/颜色/光照接缝，**仍不能推出无接缝**。要真保像素只能靠确定性区域合成，
  那又回到 D 的手法和判据问题。
- **契约坑**：`visual_review.py` 实为 **5 项 checks**（identity/color/quantity/printing/specification），
  `GENERATORS={'builtin-imagegen','existing-qualified','web-gpt-ego'}`。codex 通道 provider 是 codex-oauth/
  openai-official，填 `web-gpt-ego` 属**虚标**（图非网页 GPT 出），填真实 provider 被白名单拒。
  必须先正式改契约，且「商品图只走网页 GPT」铁律仍在——放在 tb-auto 内不自动满足该约束。
- **结论**：维持 B/T-005 收口口径不变（门槛真实系统验证通过、端到端保存待合适素材、整批素材 blocked）。
  不虚标 generator、不绕过契约、不为凑 pass 换入口。全程零商品写入、未碰队列/店铺。

### T-20261118-004 · Codex 复查推翻「变长槽位已完成」：逻辑层半成品已补全，UI 探针待真实验证

- 状态：**高危逻辑缺陷已修 + 回归通过，仍零商品写入**。T-20261118-003 的「代码完成、337 全绿」结论被
  Codex 独立复查（`/tmp/codex-slotplan-review-20261118.md`）推翻：那轮只改了读回比对和 preflight 门槛，
  **写入执行路径仍写死 5/4/9**，preflight 放行的变长商品会在写入时被拒；且正常提交读回漏传 plan 必然失败。
- **Codex 与 WorkBuddy 独立发现一致的高危项**（均已修）：
  1. `batch._slot_plan` 键存在但值非 dict（None/True/0/[]/str）被静默回退成满槽 → 改为只有**缺键**才回退，
     值存在即严格校验字典/类型/范围，否则 `invalid_slot_plan` 失败关闭（`miaoshou_batch_editor._plan_from_baseline` 同语义）。
  2. `batch.py` 正常提交后的官方读回 `_matches_doudian_target(official_before, ...)` **漏传 plan**：
     `official_before` 是嵌套 `doudian_baseline`，无 slot_plan，会回退 5/4 让变长商品读回永远失败 → 显式传 `plan=run_plan`。
  3. `record_baseline` 建基线仍要求 `5 主/≥4 详` → 有 plan 时按 plan 校验并核对与实际读到图片数一致；无 plan 保留旧要求。
  4. `batch.py` 素材切分仍要求 `5 主、共 9 张` → 按 `run_plan` 校验。
  5. 三处 complete 检查 + 标题修复 `images_match==9` → 全部按 plan。
  6. `_finalize_target_mappings` 尾图校验写死 `[4:]` → 改为 `[plan['details']:]`，短计划有保留尾图时仍逐张校验。
  7. `validate_batch_form_state` / `MiaoshouBatchEditor.prepare` 入口与数据切片写死 5/4/9 → 按 `_plan_from_baseline` 驱动。
- **Codex 第二轮复检（`/tmp/codex-slotplan-recheck-20261118.md`）又抓到两处我已修**：
  ⑧ `miaoshou_editor.parse_edit_response` 写死 `5 主/≥4 详`，是变长链路**最上游**（建 plan 之前就 read_product），
  5主2详和4主4详直接 `miaoshou_images_incomplete` → 放宽为 1–5 主、≥1 详（与 preflight 门槛一致）；
  ⑨ `require_distinct_detail_sources` 检查 `keys[:4]`，短计划带保留尾图时尾图重复被误拦 → 加 `replaced=B`
  参数，只检查前 B 张待替换源的唯一性（含与尾图重复），两个调用点传 `min(4,详情数)`。
- **prepare 补行 vs 校验的冲突（Codex ⑨ 同类，已按 DOM 事实解决）**：`observe()` 的 `detail_pairs` 来自
  `.base-edit-list`（含 2 个 add-img-box），`prepare` 会 `_ensure_detail_rows(4)` 补到 4 行，空行是
  `{source:None,target:None}`。因此把表单/提交/保存守卫的详情校验统一为：**前 B 行必须是目标替换，
  B 之后的余行必须完全为空**（非空余行＝未审替换，`miaoshou_batch_unexpected_detail_row` 拒绝），
  `target_urls`/mappings/pairs 只取前 B 行。满槽商品 B=4 行为不变，变长商品无论页面显示 2 行还是补到 4 行都自洽。
- **UI 探针仍未改**（`xs.length===5/4`、`_ensure_detail_rows(4)`、`_upload_slot_image(...,5)`）：
  主图 5 是平台固定槽位；详情 4 因 prepare 始终补到 4 行而成立——空余行已被上面的数据校验安全忽略。
  这些是页面控件事实，非已证实可变的契约，保持原样。
- **Codex 第三轮复检（`/tmp/codex-slotplan-recheck2-20261118.md`）又抓到两处已修**：
  ⑩ `ego_runtime.mjs::inspectBatchSave` 要求页面全部 main/pairs 与 guard 完全相等，B<4 的空余行让它
  `valid:false`（assets）→ 改为 `trimSuffixEmpty`：只剔除**尾部**空控件/空行后比较，空项在前仍拒；
  ⑪ `observe()` 把空主图控件计入（4 主图→"4 URL+1 null"，被 `len(mains)!=main_slots` 拒）→
  主图改为 `map(imgUrl).filter(Boolean)`，详情 pairs 保持不过滤（让校验层看到空余行）。
  同时 `_save_guard` 补齐非空余行拒绝，使表单/提交/保存守卫三处语义一致。
- **Codex 第四轮复检（`/tmp/codex-slotplan-final-20261118.md`）抓到最后一个确定高危并已修**：
  ⑫ `batch.py` ready 分支构造了带 slot_plan 的 baseline，但 `miao_before = baseline` 只在续办 else 分支；
  新任务传给 prepare/verify_prepared/finalize 的仍是不带 plan 的 raw read → 回退 5/4，5主2详/4主4详/
  4主2详全部在上传入口 `asset_manifest_incomplete`。ready 分支补 `miao_before = baseline`（baseline 是
  miao_before 的超集，含 plan），两分支写入路径统一。测试 `test_prepare_requires_the_plan_on_the_baseline_it_receives`
  钉住该契约。
- **Codex 第五次聚焦复检（最终）**：确认 ready 与新任务/续办两条路径都已把带 plan 的 baseline 传给
  prepare / verify_prepared / finalize；结论 **离线可交付**，没有确定可复现的残留高危阻断（UI 探针、
  补 4 行、真人页面实测等不算确定缺陷）。
- **测试**：`tests/test_slot_plan.py` 14→26 条、`test_miaoshou_editor.py` +2 条、`tests/ego-runtime.test.cjs` +1 条；
  覆盖非 dict 失败关闭、变长表单（0/2 空余行）、非空余行拒绝、尾图边界、distinct sources 前缀、变长读取、
  save guard 变长（4主2详+空控件）、槽位名称规范化、新任务 plan 传递。
  最终回归：**pytest 830 passed in 194.08s**（独立 basetemp 规避 WorkBuddy 删除守卫），
  **npm test 124 pass / 0 fail**。提交 `3a2142f` 已推送 `codex/miaoshou-reliability-20261029`。
- **2026-11-18 真实系统验证（门槛生效已证实，端到端保存仍未做）**：用户指出妙手/Ego 都开着，实测确认此前
  「授权失效」是假象——真正故障是 session state.json 的 space id 2 被回收复用，报 `ego_session_finished`。
  用项目 `EgoBridge.align_space()` 把 session 从 space 2 对齐到 **space 15**（旧 state 备份、路由清空），
  新建 agent page 导航妙手即登录态（销霁百货）。实测：
  - `batch probe-product` task 59：`verdict=present`、编辑按钮可用；
  - `batch preflight --recheck-blocked --check-miaoshou`：**task 59、task 60 双双 `eligible=true`**，
    官方实读 5主2详、属性 100%、SKU 齐全、`miaoshou_listed=true`；
  - `MiaoshouEditor.open_product+read_product`：task 59 妙手编辑窗实读同为 **5主2详**（历史首次实测），
    task 60 实读 5主2详、21 SKU。旧代码在这两件上必然报 `writer_image_slots_incomplete` → 新门槛在真实系统生效。
- **真实保存的两个客观阻断（均不绕过）**：
  ① `batch.py:2560` `warehouse_scope_only` 只接受 `status==1`（仓库中）。task 59 实时 `status=0`（上架中），
  上传前必被拦；改上架品会触发重新审核、有误改上下架风险，**不下架商品、不改数据库状态绕过**。
  ② 合规候选 task 60（波浪吸音棉，仓库中、5主2详、属性100%、21 SKU、preflight 全绿）缺 7 张目标素材；
  其现有 7 张图是**信息密集型电商图**（大字「波浪吸音棉」「厚度按需选择」、2/3/5/7/10cm 规格数字、
  配色对照表、编号步骤 4/5/6、应用场景实拍）。网页 GPT 整张重绘中文/数字必乱码且丢卖点（见
  `/tmp/codex-t60-art-20261118.md`），原图重传被 `original_asset_not_revision` 拒，本地合成保文字属破出图铁律。
- **Codex 三方案裁决（`/tmp/codex-t60-decision-20261118.md`）**：原则排序 C＞B＞A，**当前推荐 B**。
  C（换商品）无已证实新候选：61 条 facts_json.status 全为字符串（`"1"` 48 条 / `"0"` 13 条），
  task 39 缺 7 项必填属性、task 55 缺「适用作物生长阶段」，57/59/61 是上架中，均不能过 preflight。
  A（本地直接完整改图）违反出图约定，用户批准也只是授权例外。
- **Codex 新路径 D（规则解释上可行，未实测）**：每个槽位仍由**网页 GPT 做真实可见修改**，本地**只把原图
  文字/规格数字等必要区域按原像素位置恢复**（不承担背景重做/主体设计）——约定原文没有明文禁止生成后的
  文字像素保真处理。风险：遮罩覆盖大面积背景、接缝、残留乱码或规格错配；若最终主要画面仍是原图或仅
  编码变化则不成立，不能据此判通过。七张最终图能否全部合格、写入链能否保存仍须实测，不能预先签 pass。
- **当前状态**：B 为默认结案口径——变长槽位记为「门槛已在真实系统验证生效、端到端保存待合适素材」。
  若要真跑端到端，需用户明确授权 D（网页 GPT 主体改图 + 本地文字像素保真后处理），按 task 60 走完整链路。

### T-20261118-005 · 用户授权 D 后的真实试点：D 路径在 task 60 整批不可交付，停止端到端写入

- 用户 13:40 回「d」授权 D 路径。Codex 落地方案 `/tmp/codex-t60-d-howto-20261118.md`：
  GPT 整图重生成 → **SIFT 配准回原图坐标** → 只恢复文字/数字区原像素 → 商品照片区保留 GPT 可见改动；
  机械判据：配准残差≤2px、字芯原像素相等、接缝 LAB 色差中位≤3/P95≤8、安全区可见改动≥15%、哈希去重。
  注：`visual_review.py` 的 `checks` 实为 **5 项**（identity/color/quantity/printing/specification），另 4 项工程验收单独留证。
- 环境：抖店 venv 无 cv2/numpy，**tb-auto venv 有 cv2 4.11/numpy/skimage** → 配准/恢复在 tb-auto 跑；
  `cv2.imread` 读不了中文路径，用 `np.fromfile`+`imdecode`。出图通道 session=`tb-img-gen`/space=default，与妙手 space15 隔离。
- **main-1 单张真实试点**（脚本 `C:/Users/19431/tb-auto/work/doudian-20261118/task60-d/{pilot_main1,restore_main1_b}.py`，
  产物归档 `work/materials-20261118/task60-d-pilot/`）：
  - 第一版提示词「只改光影」→ GPT 几乎原样输出 → 改动不足，失败。
  - 第二版「浅灰背景换浅米/杏色渐变」→ 生成成功 74s：背景明显换色、文字无乱码、商品结构一致；
    SIFT 765 匹配 / 79.7% 内点 / **残差中位 0.22px** / P95 0.95px（构图像素级稳定）；可见改动 42% PASS。
  - 手法 A「冷灰底板整块贴回+10px 羽化」→ 接缝色差中位 14.18/P95 29.27 FAIL，肉眼可见矩形方块。
  - 手法 B（Codex Q3：只恢复字形重建抗锯齿 alpha、inpaint 新底板、取消矩形底板、胶囊按蓝色掩膜圆角恢复）
    → 顶部/底部矩形方块消失、字形自然融入背景、胶囊自然、整体无可见拼接；**目视 PASS**，
    gate1 字芯相等 / gate4 改动 42% PASS；但机械 gate3 色差无法干净区分「恢复字形像素」与「真实接缝」，P95 持续超标。
- **Codex 最终裁决（`/tmp/codex-t60-d-final-20261118.md`）**：① main-1 按目视判 PASS，但机械 gate3 不记通过；
  ② **这批 7 张 D 路径不能整体交付 task 60，停止推进整批端到端写入**——detail-1/2 文字压在色卡/泡棉纹理上，
  无法唯一还原被遮住的纹理，无统一手法，main-1 成功不能推出整批可行；③ 状态标记为 **blocked（整批素材未就绪）**。
- **结论**：变长槽位逻辑链离线交付（commit `3a2142f`）+ 门槛真实系统生效（task 59/60 preflight eligible）
  均已达成；端到端保存写入仍为零，D 路径实测不可整体交付，A 破铁律、C 无合规候选。**全程未碰队列/店铺，
  未虚填 pass，未绕过 warehouse_scope_only，未下架商品**。试点产物留在 work/（gitignore），只提交本文档。

### T-20261118-003 · 写入器支持变长槽位：槽位计划写进基线

- 状态：**逻辑层已被 T-20261118-004 修正并补全**；本块保留为设计意图记录。用户选的是 ⑱ 的选项 ②。
- ① **核心**：每个版本记一个**槽位计划** `baseline['slot_plan'] = {'mains': A, 'details': B}`，
  `A = min(5, 主图数)`、`B = min(4, 详情数)`，在建基线时由**该商品自己的快照**算出（`batch._plan_for_snapshot`）。
  取代原先写死的 9 槽。
- ② 🔴 **缺省即满槽**：`_slot_plan()` 在基线没有这个键时返回 `{'mains': 5, 'details': 4}`，
  所以 61 件历史基线的行为**一点没变**，22 件已验证的也不会因为这次改动无法重跑。
  计划不合法（0、超上限、bool、None）→ `invalid_slot_plan`，失败关闭。
- ③ **读回仍按前缀严格比较**：前 B 张必须是目标图，第 B 张之后必须与基线原图**逐张一致**。
  槽位变短**没有**放宽尾部校验（`test_readback_compares_only_the_planned_prefix` 钉住）。
- ④ **改动位置**：`batch.py`（`_slot_plan`/`_expected_slots`/`_plan_for_snapshot`、两处 matches、
  `_finalize_target_mappings`、`record_writer_preparation`、`begin_submission`、标题修复提交、
  `record_execution_readback`、`verified_acceptance_results`、`validate_agent_artifacts`）；
  `miaoshou_batch_editor.py`（`_plan_from_slots`、提交预览校验、`uploaded_slots`、`_save_guard.mains`）；
  `ego_runtime.mjs`（预览里的主图/详情数量改按期望值）；`preflight.py`（门槛改为 1–5 主、≥1 详且 `ready`）。
- ⑤ **测试**：新增 `tests/test_slot_plan.py` **14 条**（满槽缺省、计划逐字生效、六种非法计划、计划来自商品自身、
  无槽位即停、槽位必须连续且不超上限、读回只比计划前缀且尾部仍严格）。
  另更新 `test_preflight.py` 的槽位门槛用例：非法组合改为 `(6,4)`/`(0,4)`，并新增 `(5,2)`/`(4,4)`/`(5,3)` 必须被接受。
- ⑥ ⚠️ **没做真实商品验证**：改动期间妙手报 `miaoshou_authorization_required`，双端槽位对比做不了。
  **首次真实使用应选 task 59**（2 SKU、5 主 2 详、属性齐全）：确认「上传 7 槽 → 妙手预览显示 5 主 2 详 →
  保存 → 双端读回前 2 详为目标、其余详情保持原样」。这一步没做之前，不要把变长路径当成已验证能力。
- ⑦ 解锁范围：57/58/59/60（详情 2 张）以及 39/55/61（主图 4 张）理论上都进入可运行区间，
  但仍受各自其它卡点约束（39 缺 7 项属性等）。

### T-20261118-002 · `writer_image_slots_incomplete` 是槽位契约，不是缺素材

- 状态：**done，零商品写入**。7 件逐件只读复核后定性：这类**不是「再补几张图就能过」**。
- ① **实测槽位**（`work/recheck-20261118/slots`，只读 `batch preflight --recheck-blocked`）：

  | task | 主图 | 详情 | SKU | 缺什么 |
  |---|---|---|---|---|
  | 39 | 4 | 15 | 2 | 主图少 1 |
  | 55 | 4 | 3 | 5 | 主图少 1、详情少 1 |
  | 57 | 5 | 2 | 44 | 详情少 2 |
  | 58 | 5 | 2 | 121 | 详情少 2 |
  | 59 | 5 | 2 | 2 | 详情少 2 |
  | 60 | 5 | 2 | 21 | 详情少 2 |
  | 61 | 4 | 4 | — | 主图少 1 |

- ② **为什么补图没用**：写入器是「按图查找替换」9 个固定槽位 ——
  `miaoshou_batch_editor.py:169` 要求映射集合恰好 `mains:1..5` + `details:1..4`，数量不等直接 `uploads_incomplete`；
  preflight 门槛同样是 `main_count != 5 or detail_count < 4`。商品只有 2 个详情槽位时，**没有第 3、4 张原图可被「按图查找」**。
- ③ **区分「没读到」与「真没有」**：`detail_status ≠ ready` 才是没读到；`ready` 且数字小就是真的少。
  58 的 `declared=2 / cards=2 / slots=2` 三者一致，属于后者。
- ④ **58 的完整链路**：编码修复后（T-20261118-001）`121/121` 全读到、主图 5 张、属性 `completion_percent=100`，
  唯一的卡点就是详情 2 张。`batch recheck` 已把它的 `last_error` 对齐到这条真实原因。
- ⑤ **三条出路**（详见 `docs/dropship-policy.md` ⑱）：
  ①**先平台补槽位**（只加图、不动文案/价格/属性，风险最低，需授权）；
  ②**改写入器支持变长槽位**（解锁 7 件+未来同类，但动 upload_map／预览校验／读回比对／保存证据四处契约，中高风险）；
  ③**结案为契约不适用**（诚实，但等于放弃这 7 件）。
- ⑥ 本轮未替用户选路：①要对 7 件生产商品各写一次，属于需要明确授权的外部动作；②是契约级改动，应单独评审。
- ⑦ 测试：无新增（本轮是只读盘点）。`work/recheck-20261118/` 下留了三个只读探针
  （`probe_jitter.py` 逐轮 scrollTop、`probe_scroll_effect.py` 手动设 scrollTop 换行验证、`probe_holders.py` 枚举 holder）。

### T-20261118-001 · 商家编码「读不全」的真因是滚动被撤销，不是商品太大

- 状态：**done，零商品写入**。task 58（121 SKU）从 `official_sku_code_row_ambiguous`／`incomplete` 变成 **121/121 全读到**；队列数量不变，只是把 58 的阻塞原因对齐到真实卡点。
- ① **现象**：`batch preflight --product-id 3793430313384935495 --recheck-blocked` 报
  `official_sku_code_incomplete: 官方UI商家编码在读取预算内仅确认11/121个SKU`，42 秒。
- ② **两层怀疑都是错的**：先按 policy ⑮ 怀疑窗口——第一次确实跑在 `minimized` 窗口下，恢复到 `maximized 2064×1120` 后重跑，**结果一字不差 11/121**；
  再怀疑 holder 找错——页面上有两个 `virtual-holder`（外层 + 嵌套的 `-inner`），但代码已优先取「SKU 行所在的那个」，且实测 `scrollHeight=4934 / clientHeight=500` 能滚 4434px，容器没错。
- ③ 🔴 **真因：`scroll_pending` 在推进 holder 之前先对末尾空行 `scrollIntoView`，每轮把 scrollTop 拉回去。**
  逐轮打印（`work/recheck-20261118/probe_jitter.py`）：
  ```
  第1轮 into=389 → plus=639
  第2轮 into=389 → plus=639   ← 又被拉回
  ...（6 轮全同，55 轮都在 389↔639 之间）
  maxTop=4434，实际只用过 639
  ```
  **「滚动了」不等于「前进了」**：`scrolled=true` 只说明 scrollTop 变过，`rows` 和 `pending_count` 全程恒定。
  手动把 `scrollTop` 设到 1000/2500/4000，SKU 行每次都换（`probe_scroll_effect.py`）——证明容器和滚动都有效，只是被撤销。
- ④ **修法（顺序）**：先推进 holder，**只有推不动（到底/无可滚空间）时**才 `scrollIntoView` 占位行。
  占位行懒加载的用途保留，但它再也不能撤销已经取得的前进。
- ⑤ **配套（预算）**：硬上限 `30 → 180` 秒；**SKU 数 > 30** 时按 `10 + 1.2 × SKU数` 自适应（121 → 155s、44 → 62.8s、≤30 件不变）。
  **显式传入的小预算不被覆盖**——`tests/test_official_sku_codes.py` 有一条 `seconds=0.45` 验证预算耗尽的用例钉死这点。
- ⑥ **配套（早停）**：连续 6 轮无新增即停，避免回绕重读旧行白等到预算耗尽。
- ⑦ **实测**：同一件 58，修复前 `11/121`（42s）→ 修复后 **`121/121`、`sku_complete=true`（47s）**。
  随后 `batch recheck --task-id 58 --proof <summary.json>` → `reason_refreshed`，阻塞原因更新为
  `writer_image_slots_incomplete`（**主图 5 张够、详情只有 2 张**，属性 `completion_percent=100`）。
  也就是说 58 现在缺的是 2 张详情图，不再是编码。
- ⑧ 🔴 **推翻一条旧结论**：`editor.py` 原注释写「30s 提到 90s 对 121-SKU 结果不变（都是 91/121），因为 holder scrollHeight 停在第 91 行」——
  那次实验正好撞上这个震荡，扫描从未接近上限，所以「加时间无用」是错的。注释已按实测改正。
- ⑨ **顺带修了一个测试脆弱点**：`tests/test_preflight.py::_update` 用 `with sqlite3.connect(...)`，而 `with` 对 sqlite3 **只提交事务、不关闭连接**；
  未关闭的连接在回收时才把 WAL checkpoint 回主文件，于是「只读预检不得改库」的**字节级**断言会被**之前那次写入的滞后落盘**打中。
  改为显式 `commit` + `PRAGMA wal_checkpoint(TRUNCATE)` + `close`，16 处共用该辅助的断言随之稳定。断言本身没有放宽。
- ⑩ **测试**：`official-sku-code-dom.test.cjs` 23 条（+2：占位行不能撤销推进、到底时仍会 scrollIntoView）；
  `test_official_sku_codes.py` 24 条（+3：>30s 预算合法、连续无进展早停、有进展不早停）。
  回归：`editor+preflight+batch+official_sku_codes` **166 全过**（连跑两次）、`readback+rebaseline+preflight_cli+preflight_recovery_cli` 全过、jsdom `dom+sku_code` 61 全过。

### T-20261117-007 · 🔴 55/57 九图「通过」结论撤回：判据源头错配（实物忠实性）

- 🔴 **撤回 T-20261117-005 的「九图全部 pass、可直接 requeue」结论**。机械闸门（`validate_agent_artifacts`）仍 approved=True，但那是按**我们自己写的提示词口径**判的，非按商品实物。迟到到账的 Codex 全量审查（`/tmp/codex-image-strategy-20261117.md`，176 行，之前误判为跑偏，实为进程仍在写的中途空文件）提出高危项，WorkBuddy 逐张看图核实后确认成立。
- **task57 判据源头错配**：参考图 `p3793434417251352651/refs/main-1.png` / `main-2.png` 实拍为**竹/菊/兰国风款**（带书法字「竹/菊/蘭」+印章）；`detail-1.png` 展示十余种款式（樱花、卡通、足球、哆啦A梦、竹等）；`main-3.png` 甚至是方形/异形款。实物是「多图案可选、按规格选配」。但收紧后的提示词把款式写死为「浅蓝企鹅+绿素面+樱花+蓝卡通四款」并**明令禁止竹菊兰**；`review-20261117c.json` 把 detail-2 的「菊」款（实物真实存在）判 fail、重出成樱花款（也真实存在）却判 pass。**结论：生成图款式可能都真实存在，但判据来源错误（提示词≠实物），不能据该 pass 上架。**
- **task55 标签非忠实**：参考图 `p381557.../refs/main-4.png` 标签上确有**两行小字说明 + 底部三个圆形标识**（营养全面/绿色环保/双重吸收）。生成图 main-4 为规避乱码把它们留白/删除，改变实物印刷。此前「核心四字齐全、辅助小字留白可接受」的判定过于宽松。
- **Codex 建议（采纳为修正方向）**：停止相同输入无差别重试；改用**保留商品及完整标签像素、只编辑背景与构图**的高保真方案，不让模型重绘标签/卡面；「不确定就留白」只允许用于新增文案区，实物印刷必须保像素否则拒收。换参考图须同一实物同一包装版本、标签更清晰的原图。
- **状态**：55/57 的 `artifacts-v1.json` 保留为历史证据，但标记 `not_for_upload`；队列未变、零商品写入。task57 的实际在售款式口径属业务事实，需用户/供应商确认后才能重设提示词与复核判据。

### T-20261117-006 · ⛔ 28/50「只差可推断安装方式」结论被实测推翻

- 🔴 **判据回归**：属性盘点（`work/audit-20261117/attribute-gaps.json`）把 28/50 归为「just inferable / 只差安装方式」，实测**不成立**，按判据纪律撤回该结论。
- **task28**（3848319935382159544）：只读预览确认控件为空、单选、可写；但读平台真实候选列表 = `壁挂式/台式/挂钩式/嵌入式/落地式/悬浮式/龙骨式/胶粘式/吸盘式/桌夹式/顶天立地式`，**没有「免打孔」选项**。标题「免打孔」是上位概念，对应胶粘/吸盘/挂钩等多种具体方式，从标题无法确定是哪一种 → 选任一个都是猜属性，违反应规则。`writable=true` 只是控件可填，不代表值合法。
- 曾按授权试 `--apply 安装方式=免打孔`，写入路径 fail-closed（`option_not_unique`＝零匹配）在发布前停止，未写任何字段；已用 `--abandon` 显式收尾，`page_verified_empty=true`。
- **task50**（3848315275342643596）：页面实读「安装方式」当前值＝「免打孔式」（非空），写入路径拒绝覆盖已有不同值（writable=false）。盘点说它「缺安装方式」与页面实读冲突，以实读为准。
- **结论**：28/50 不是可机器补全的件，归入「needs_supplier：供应商明确到底是哪种安装方式」。这同时印证 Codex 判据「把宽泛描述映射成更具体选项＝猜属性」。零商品写入、队列未变。

### T-20261117-005 · ✅ 55/57 九图复核闭环 + artifacts 清单通过写入闸门

- 状态：**素材已就绪、清单已过闸**；队列未变（22 / 33 / 6），零商品写入、未碰生产店铺。
- ✅ **task 55 九图全部 pass**：首轮 6 张（`task55-gen-review.json`）+ detail-2/4 重出 pass（`review-20261117b.json`）+ main-4 重出 pass（`review-20261117d.json`，1254×1254，Enter 兜底 73s）。main-4 曾三轮失败（留白/歪斜 →「家缩园艺」错字+小字乱码 → 600s 超时），最终靠「不确定小字留白、只保留必须写对的四字」策略过复核。
- ✅ **task 57 九图全部 pass**：首轮 7 张（`review-20261117b.json`）+ main-1/detail-2 重出 pass（`review-20261117c.json`）。main-1 旧版书法字糊墨团、detail-2 旧版「菊」国风款+伪文字，收紧提示词（禁菊/竹/兰、书法字不可辨则省略）后修复。
- ✅ **产物**：`work/materials-20261114/task{55,57}/artifacts-v1.json` + `source.json` + `prompts/` + 归位的 `task{55,57}-gen/`（各 9 图）。构建脚本 `build_artifacts_20261117.py`（取每槽位最新 pass 观察、哈希绑定当前图片、标题/版本/店铺从 DB 原始记录读）。
- ✅ **闸门自检**：`validate_agent_artifacts(product_id, expected_shop='销霁百货')` 两件均 `approved=True`、9 assets、title 合规。
- 🔴 **证据自洽修正**：此前为修图覆盖过 3 张参考图（55 main-4、57 main-1/detail-2），`source.json` 旧哈希已失效；本轮按磁盘真实值重建绑定（换版理由见该目录）。
- **Codex 第二意见处置**：第 2 次聚焦审查（read-only）确认「取最新 pass 合并、哈希绑定当前图」无证据链缺陷（采纳）；第 1 点提示「标签小字留白是否失真需看是否影响识别」——判定核心四字（通用型/家庭园艺/浓缩营养液/清香型）齐全正确、留白仅为无法保证写对的辅助小字、与同批 pass 图口径一致，不影响识别，予以接受。第 1 次全量审查跑偏（stderr 307KB 无关 dump、报告空），未采纳。
- 🔴 **复检高危项已用机器证据关闭**：Codex 复检质疑「最新 pass 观察是否审过当前图片」。落 `verify_evidence_chain_20261117.py`，对 18 槽位逐张验三判据：①清单 asset_sha256 == tb-auto 源文件 == 主仓库归位文件；②源文件落盘时间 ≤ 取观察的报告时间；③曾 fail 重出者 fail→pass 报告时序递增。**18/18 全绿**，无观察与图片错配。另修正 d 报告 `reviewed_at` 时区笔误（14:32→22:32）。

### T-20261117-004 · 194-214 · ✅ 55 九图产出 + 33 件阻塞原因定盘

- 状态：**in-progress**。队列未变（22 / 33 / 6）。零商品写入。
- ✅ **task 55 九图已生成**（`tb-auto/work/doudian-20261114/task55-gen/`），
  提示词改为**按件配置**（`prompts-<pid>.json`，含 `refs_dir`），不再为每件改代码。
  该件是瓶装营养液，标签文字属实物需保留，只去掉四周批发文案（厂家名/一件代发/快递费）。
- 🔴 **33 件 blocked 的真实构成**（只读盘点，`work/audit-20261117/`）：
  - **有属性缺口 12 件**；
  - **属性已满、卡在别处 11 件**（11/15/16/48/49/51/57/58/59/60/61）；
  - **从未探测 10 件**（1/3/4/6/7/8/9/13/27/34）。
  - 其中**只差「可推断属性」的 2 件：28、50**——只缺「安装方式」，标题里就有「免打孔/吸盘」。
  - `needs_supplier` 高度集中：尺寸×3、型号×2、生产企业地址×2、硬度×2。
  → 结论：**型号 / 产品标准编号 / 生产企业地址是通吃的供应商资料**，应一次性要模板，而不是逐件催。
- ⚠️ 那 11 件「属性已满」依据的是 8-16 天前的快照，需重探；10 件从未探测的应先跑只读 preflight。
- 出图通道稳定（Enter 兜底），单张约 33-50 秒。

### 2026-11-17 · EXT-20261117-07 · ✅ Ego 空间号被回收后自动对齐并重试一次（不再手工跑 probe.sh）

- 状态：**done**。纯代码修复，零商品写入、零队列改动、未碰 `work/` 与 `batch.sqlite3`。
- 🔴 **问题**：Ego 的 task space 被系统回收后 **id 会被复用**（实测出现 148/6/1/5），
  而 `state.json` 里缓存着旧 `spaceId`。此时任何浏览器命令都在**解析空间阶段**失败：
  `task space not found: <旧id>`，被 `_run()` 统一包成
  `ego_error / Ego未确认完成操作；没有自动重试。`，**原始 message 被丢掉**，
  上层只能去 `~/.doudian-auto/ego-sessions/<hash>/<token>.result.json` 里翻。
  结果是 `batch preflight`、`batch probe-product` 随机报 `ego_error`（2026-11-17 多次实测）。
- ✅ **修法**（`src/doudian_auto/ego_bridge.py`）：
  - 新增 `EgoBridge.align_space()` 与模块级 `align_space(session) -> int`：
    先 `listTaskSpaces()` 里按**会话名精确匹配**（找不到再看 `doudian-auto <session> ` 前缀），
    都没有才 `useOrCreateTaskSpace(name)`（回落 `taskSpace(name)`）——即 `sync-space.mjs` 的判定，
    但走的是仓库已有通道（`ego-browser nodejs -e` + 结果写文件，不用管道，避免 Windows 子进程继承句柄卡死），
    并复用 `TransportLock`，**没有新造第二套子进程机制**。
  - **只在缓存 id ≠ 真实 id 时改写**；改写前备份 `state.json.bak-auto`（沿用 `probe.sh` 的命名），
    同时清空 `pages`/`active`（这些标签随旧空间一起死了，留着会把写操作重定向到已丢失的页）。
  - 失败不静默：统一抛 `ego_space_align_failed`，message 带浏览器自己的原话
    （探测失败/超时/未返回结果/`spaceId` 不可用/state 不可读写，逐种都有独立文案），且**不改写 state**。
  - `_run()` → 拆成 `_run()` 包一层 `_execute()`：只在 `space_stale()`（即 `task space not found`
    类）时 **对齐一次 + 重试一次**，仍失败就带原始 message 抛出，**不循环**；
    其他错误（如 `ego_state_locked`）一次都不重试。
  - 所有 `DoudianError` 现在带 `details = {action, raw_code, raw_message, result_file}`，
    `details` 由 `ego_bridge._error()` 动态挂载（**未改 `errors.py`**，避免与其他会话冲突）。
    「空间失效」是解析阶段失败、任何 Page 都还没建立，所以这一次重试不可能重放保存。
- 🧪 测试：新增 `tests/test_ego_space_align.py`（11 条）覆盖
  「缓存 id 失效→对齐→重试成功（含 `.bak-auto` 与 pages/active 清空）」、
  「**走真实 `_execute` 传输**：第一轮 runtime 报错→探测改 state→第二轮穿过 pending 标记成功」、
  「对齐后仍失败→错误带 `task space not found: 2` 原文且只重试一次」、
  「id 一致时不改写 state、不产生 `.bak-auto`」、「探测走文件通道并把字符串 id 归一」、
  「探测失败保留 state 并报出真实原因」、「非法 spaceId 报 `ego_space_align_failed`」、
  「非空间类错误不触发探测/重试」、「对齐本身失败时保留原始 message」、
  「交给用户的空间不回抢」、模块级 `align_space(session)` 返回真实 id」。
  `tests/test_preflight.py tests/test_preflight_cli.py tests/test_ego_bridge.py tests/test_ego_space_align.py`
  = **86 passed**；全量 `pytest` = **793 passed / 3 failed**。
- ✅ 真机只读验证：对真实会话 `miaoshou-auto-batch-20261028` 跑 `EgoBridge.align_space()`，
  返回 **live id = 2**、`changed=False`，**state.json 内容与 mtime 完全未变**（探测通道真能用）。
- ⚠️ 那 3 个 failed 全在 `tests/test_title.py`，报 `cli.py:1094 UnboundLocalError: Bridge`——
  `cli.py` 函数体内 `from doudian_auto.bridge import DEFAULT_ENDPOINT, Bridge`（HEAD 的 968/979 行）
  把 `Bridge` 变成了局部名，与本次改动无关（`git diff HEAD -- cli.py` 为空），属**既有缺陷**，需单独修。
  （同一处缺陷也会让 `batch probe-product` 自己报错，建议优先修。）
- 备注：`docs/HANDOFF.md`「## 7. 变更日志」在本仓库不存在（HANDOFF 主体在根目录），
  故按现有「## 给人的说明」倒序惯例置顶本条。

### T-20261117-003 · 194-213 · ⚠️ 39 的 9 图已出并通过复核，但属性缺 7 项

- 状态：**part-done**。队列未变（22 / 33 / 6）。零商品写入。
- ✅ **task 39 九图完成**：5 主图 1254²、4 详情 1024×1536，sha 全唯一；
  `validate_agent_artifacts` 实跑 **approved=True**（9 张）。
  清单 `work/materials-20261114/task39/artifacts-v1.json`，图在 `task39-gen/`。
- ✅ 出图质量把关：首轮 9 张里 **4 张不合格**（main-2 三杆+沐浴球、main-4 三杆、
  detail-3 蓝色光圈+双手套、detail-4 三杆），收紧提示词（明确「只有两根杆」+ 禁止参考图外物品）后重出，全部通过。
- 🔴 **真正的拦路石变成了属性**：`preflight --recheck-blocked` 显示
  `required_attributes.completion_percent=22`，**缺 7 项必填**：
  安装方式、是否可接触食品、是否进口、材质类型、**型号**、**产品标准编号**、**生产企业地址**。
  前四项可从商品事实推断（吸盘式 / 否 / 否 / ABS 塑料），
  **后三项必须供应商真实数据**——这正是项目纪律里「待真实参数」的类别。
- ⚠️ 本次预检 `miaoshou_error=ego_error`（妙手探测未完成，ego 空间又被回收），
  不影响属性结论，但说明 `probe.sh` 那套空间对齐需要固化进 preflight 调用链。
- 结论：**39 不再卡在图上**。要往下走，得先补那 3 项供应商参数；补齐后才能回队。

### T-20261117-002 · 194-212 · ✅ 出图通道修通：点击无效，Enter 有效

- 状态：**done（通道已通，task 39 出图中）**。队列未变（22/33/6），零商品写入。
- 🔴 **根因确认**：`_SEND_BUTTON_JS` 能正确定位到 `aria="发送" type="submit"` 的按钮，
  Playwright 的 `page.click` 也不报错，**但输入框内容一点没动**（267 字原样保留）。
  加发送确认后 1 分 14 秒即报 `SEND_FAILED`，不再空等 600s。
- ✅ **兜底有效**：新增 `_press_enter()`（focus 编辑器 → CDP `Input.dispatchKeyEvent`
  的 keyDown/keyUp）。实测 `点击发送未生效，改用 Enter 发送` 后**成功出图**
  （1254×1254、64 秒）。所以这条路是「点不动就走 Enter」，不是「发不出去」。
- 证据：`~/.tb-auto/send-evidence.jsonl`（`after_fill`/`after_send` 两行，含草稿长度、URL、
  alerts/statuses、页面尾部与三态 verdict）。
- 代码：`tb-auto/src/services/web_gpt_image_channel.py`（`_press_enter`、`_confirm_sent`、`_draft_len`）。
- ⚠️ Codex 另指出 `find_tab` 用 `includes` 匹配会绑旧页并 `retarget()` 关新页，
  `gen_task.py::prepare_tab` 的 `PREP bound-new-tab` 只是候选标签、不是绑定证明 —— **尚未修**。

### T-20261117-001 · 194-211 · ⚠️ 出图通道不稳定（非网络问题），素材与脚本已就绪

- 状态：**blocked-on-channel**。队列 **22 verified / 33 blocked / 6 closed**（未变）。零商品写入。
- ✅ **纠正上一轮判断**：不是网络断了。`curl -x http://127.0.0.1:7890 https://chatgpt.com` 返回 **200**，
  系统代理已启用（`ProxyEnable=1`、`ProxyServer=127.0.0.1:7890`）；GitHub 也通，`888873d` 已推送。
  直连（不走代理）才会 SSL 失败，所以 `curl` 直连测试本身有误导性。
- 🔴 **出图连续 4 次 600s 超时**，期间定位并修复两个真 bug：
  1. `prepare_tab` 用 URL 前缀 `g-p-6adb` 绑定，**绑到了同项目下的旧会话**（11-11 猫窝对话、4 个附件），提示词没进干净会话；
  2. 改为「对比 navigate 前后的标签集合，只绑本次新增的那个」（`PREP bound-new-tab p9`）。
- 修完后仍超时：新标签 `p9` 在超时后已消失，读不到会话内容，**无法确认提示词是发出未响应、还是被拒绝**。
  按纪律**停止自动重发**（每次 ~10 分钟且可能重复消耗额度）。
- 已就绪（通道一通即可用）：`task39/refs/` 参考图（由 AVIF 官方图转码）、
  `tb-auto/work/doudian-20261114/gen_task.py`（按槽位、断点续传、新标签绑定）。
- 下一步（需人工一眼）：在 ChatGPT 生图项目里手动发一张看是否正常出图，把「能否出图」与「通道代码」分开定位。

### T-20261116-009 · 194-210 · ✅ Codex 素材来源定案 + 12 件探测翻转 + 网络阻塞

- 状态：**part-done**。队列 **22 verified / 33 blocked / 6 closed**（未变）。
- 🔴 **`row_present` 竞态修正后再测，结论整体翻转**：23/28 重探稳定为 `present`（此前 `total=58` 是查询未生效的偶发）。
  现在 12 件（39/55/57/59/60/23/28/31/43/45/50/54）**全部 present**，都在妙手，补资料有意义。
  为此新增 `work/materials-20261114/probe.sh`（先对齐 ego 空间号再探测，空间会被回收且 ID 复用）。
- ✅ **Codex 素材来源定案**（`/tmp/codex-sourcing-20261116.md`）：批量队列语义是**整套换新图**；
  官方原图不能复用（`validate_visual_review` 拒绝输出与参考图同 sha，`existing-qualified` 只认历史内置生图清单）；
  **已有合格生成图可复用，缺图件需整套重生**。5 件从未生成过图（tb-auto 无作业目录）→ 需 45 张。
- ✅ 已备：抖店官方图抓取（`probe_official.py`，AVIF）、转码参考图（`task39/refs/`）、
  通用生成脚本 `tb-auto/work/doudian-20261114/gen_task.py`（按槽位、断点续传、每张独立会话）、风格定语（主图去文案纯白底 / 详情场景无文字）。
- 🔴 **硬阻塞：网络中断**。`curl https://chatgpt.com`、`curl https://github.com`、`git ls-remote` 全部
  `schannel: failed to receive handshake`（HTTP 000）；ChatGPT 页面停在 `chrome-error://chromewebdata/`。
  出图与推送均无法进行，非代码问题。恢复后：先跑 `gen_task.py main-1` 验证，再批量 9 张/件。
- ✅ Codex 协作方式已写入 `docs/dropship-policy.md` ㉒（一直推进、遇问题先问 Codex、结论必须落文档与测试）。

### T-20261116-008 · 194-209 · 🔴 判据竞态导致连锁误判，已修并撤回一处结案

- 状态：**done（判据修复 + 48 撤回 + 结论翻转）**。队列 **22 verified / 33 blocked / 6 closed_unreachable**。
- 🔴 **根因**：`row_present()` 单次采样 `rows > 0` 就返回，采样可能早于查询渲染 → 可达商品被报 False。
  实测 task 48：`row_present=False`，而结构化探测 `present`（rows=1、有「编辑商品」按钮）。
- 🔴 **连锁后果（两处，均已纠正）**：
  1. task 48 曾被误结案 → 用新增的 `batch reopen-unreachable` 撤回，回到 blocked；
  2. 「缺图/缺属性件不在妙手、补资料无效」的判断**完全错误**：
     39/55/57/59/60 与 31/43/45/50/54 用新判据全部 `present`（有行、total=1）。
     23/28 为 `unknown`（total=58，说明搜索未生效，需重探）。
- 新增：`MiaoshouEditor.probe_product()` + `batch probe-product --product-id --shop`（只读、不改队列），
  返回 `verdict/reason/signals`；`present` 需查询完成且精确行 ≥1，`absent` 还需**分页总数为 0**，其余 `unknown`。
- `row_present` 改为委托 `probe_product`，False 语义收紧。
- 文档 `docs/dropship-policy.md` ㉑ 记流程纪律：**不许由零行/超时推断原因，不许动辄要求人工复审**；
  判据变化后必须回归既有结论。
- 测试：`tests/test_probe_product.py` 9 条；相关回归 89 项全绿。

### T-20261116-007 · 194-208 · ⚠️ 剩余 blocked 的「缺图/缺属性」前提被推翻

- 状态：**发现（未改队列）**。队列仍 22 verified / 32 blocked / 7 closed。
- 对 12 件「看似可修」的 blocked 做了只读妙手存在性探测（同步空间后逐件 `row_present`，每 3 件插一次对照）：
  - 缺图 5 件（39/55/57/59/60）→ **全部 False**
  - 缺属性 7 件（23/28/31/43/45/50/54）→ **全部 False**
  - 每组的对照商品 `3850072900438720563` 均为 True，说明探测通道有效。
- 🔴 **交叉验证推翻了解释**：`row_present` 数的是「匹配该商品 ID 的表格行」（`miaoshou_dom.js:42-58`），语义正确；
  但 **verified 的 task 2 = True，而 verified 的 task 35/37 = False**。
  所以 False 既不是通道问题，也不能用「写完后统一移出列表」解释——**妙手列表状态与队列状态本身就不一致**。
- ⇒ 直接后果：39/55/57/59/60 的「补图就能修」、23/28/31/43/45/50/54 的「补属性就能修」**都不成立**，
  因为它们当前根本不在妙手快速编辑列表里。补素材写不进去。
- 这 12 件**没有结案**：缺的是「为什么不在列表」的解释，需要人去妙手核对
  （是被清理、被归档、还是从没同步过来）。在解释清楚前，结案会把「可修」误判成「不可达」。
- 下一步建议（非代码）：人在妙手快速编辑页搜 task 2 与 task 35 两个 ID，确认列表口径；
  口径明确后再决定这 12 件是补资料、重新同步，还是按证据结案。

### T-20261116-006 · 194-207 · ✅ 7 件结构性不可达按证据结案

- 状态：**done（7 件 closed_unreachable）**。零商品写入。队列 **22 verified / 32 blocked / 7 closed**（总 61）。
- 逐件对照实验（只读）：妙手快速编辑页按精确商品 ID 搜索，本商品 **0 行**、同店对照 `3850072900438720563` **1 行**；
  12/22/33/36/46/48/52 七件结果一致。证据文件 `work/materials-20261114/close-evidence/task-<id>.json`
  （绑定店铺/商品/target_version/observed_at/observed/method/checks）。
- 用 `batch close-unreachable` 结案，`confirmed_by=用户（2026-11-16 经对话授权 WorkBuddy 执行）`，
  事件 detail 含证据 sha256、观察时间、旧错误。
- 🔴 **纠了两处我自己的取证错误**：最初探测 22/46/52 时用错了 product_id（22 用了 task34 的、
  46/52 也各用了别的商品），已按库中真实 ID 全部重测，结论不变；错 ID 的旧结果作废。
- 🔴 **46/52 的 `writer_image_slots_incomplete` 是表象**：主图 5 张、详情 2 张的缺口无法通过补图解决，
  因为商品根本不在妙手。此前把它当「缺图可修」是错判。
- ⚠️ 结案**不断言商品永久不存在**：日后若商品回到妙手列表，须人工重开并重走素材复核；
  `create_batch` 重导同店同品会把新行标 blocked，不会自动复活。
- 队列剩余 32 blocked 中，仍含素材缺失、历史待核实等可修项。

### T-20261116-005 · 194-206 · ✅ 实现 closed_unreachable（只做机制，未结案任何商品）

- 状态：**done（函数 + CLI + 7 条测试 + 171 项回归）**。零队列变更、零商品写入，仍是 22 verified / 39 blocked。
- `batch.close_unreachable_task()` + CLI `batch close-unreachable --task-id --reason --evidence <json> --confirmed-by <name>`：
  准入门槛是 blocked + 从未写过 + 原因≥10字 + 署名 + 24h 内绑定店铺/商品/目标版本的证据 JSON；
  缺证/不一致/读不到一律拒绝，不推断「大概不可达」。
- 语义：**只结案当前 target_version**，不断言商品永久不存在；保留历史，不删队列记录。
  事件 detail 记 `confirmed_by`/`reason`/`evidence_sha256`/`observed_at`/`observed`/身份/旧错误。
- 防绕过已逐条测：所有恢复路径只收 blocked/needs_agent，结案行进不去；
  `create_batch` 重导同店同品把新行标成 **blocked** 并记冲突，不会回到 needs_agent/ready。
- 🔴 **没有给任何商品结案**：12/22/33/36/46/48/52 仍全在 blocked。
  结案必须有人逐件给证据和署名，这是人工动作，不是自动分类。
- 测试 `tests/test_close_unreachable.py` 7 条；文档 `docs/dropship-policy.md` ⑳。

### T-20261116-004 · 194-205 · ✅ Codex 抓出第三条假恢复路径并堵上

- 状态：**done（闸门完备化）**。零商品写入，队列保持 22 verified / 39 blocked。
- 🔴 Codex 审查（`/tmp/codex-review-20261116.md`）抓出 `batch.py::recover_legacy_target_version_mismatch()`
  只凭旧版本绑定/素材哈希/未写入就 blocked→ready，**不验妙手**；
  `run_batch()` 在筛 candidates 之前调用它，所以连 `readback_only` 只读模式都可能顺带恢复。
- 修法：该函数加 `miaoshou_probe`，结果必须严格 True，缺证/False/None **静默保持 blocked**
  （返回 None 而非抛错，因 run_batch 逐行调用）；事件 detail 记 `miaoshou_listed`；
  `run_batch(..., miaoshou_probe=...)` 透传；CLI `batch run --check-miaoshou` 才启用探测。
- Codex 核对通过：`apply_preflight_report`、`requeue_visual_task` 均严格 `is True`；
  `requeue_blocked_prewrite`/`rebaseline`/`prepared_recovery` 另有双端快照依据，不是同类漏口；
  22 件 verified **不需要回验**——`record_execution_readback()` 的双端核验成功本身就是充分依据。
- Codex 对 7 件不可达商品的建议：**暂留 blocked，不要人工删队列**；未来如需终态，可加
  `closed_unreachable`（人工确认 + 绑定店铺/商品/时间/证据/原因，禁止自动恢复与重新导入绕过），
  表达「本目标版本结案」而不是断言商品永久不存在。本轮未实现。
- 测试：`tests/test_batch.py` +2 条；相关回归 **164 项全绿**。

### T-20261116-003 · 194-204 · ✅ 抓回第二次假恢复：requeue 也必须验妙手

- 状态：**done（一次误放行已收回 + 闸门补上）**。零商品写入；队列回到 **22 verified / 39 blocked**（task 48 收回）。
- 🔴 **task 48 的 requeue 是误放行**：九图复核全项 pass、抖店侧 `preflight` 全绿
  （主图 5 / 详情 13 / 属性 100% / 无草稿驳回），但妙手侧 `row_present()` 对照实验
  `task2=True / task48=False / task2=True / task48=False` → **48 不在妙手**，写入路径不存在。
  已用 `batch block --reason` 收回，`last_error=manual_block: …对照实验…`。
- 根因：`requeue_visual_task` 的准入只验素材/从未写过，**没验写入路径**，
  和上一轮 `apply_preflight_report` 犯的是同一类错。
- 修法：`requeue_visual_task(..., miaoshou_probe=...)` 要求探测结果**严格为 True**；
  CLI 新增 `--check-miaoshou` 开关，不传一律 `miaoshou_listing_unproven`；
  probe 返回 None（读不到）也不当「不存在」；事件 detail 记 `miaoshou_listed`。
- 测试：`tests/test_requeue_visual.py` 9 条（新增「缺妙手证明拒绝」「读不到拒绝」）；相关回归 **162 项全绿**。
- ⚠️ 妙手店铺授权页（`fuwu.jinritemai.com/authorize?service_id=234`）已不再阻塞探测，
  但**即使授权完成，48 也不可写** —— 它是结构性不在妙手，与 task 22 同款。
- 环境：默认 session 的 `state.json` 缓存了失效 `spaceId=148`，改为新空间 ID 6（备份 `state.json.bak-20261116`）后预检才跑通。

### T-20261116-002 · 194-203 · ✅ 真实演练 requeue 成功 + 等待器探针方案落纸

- 状态：**done（一件真回队 + 一份可贴方案）**。零商品写入；队列 61 件＝**22 verified / 38 blocked / 1 needs_agent**（task 48）。
- ① **task 48 真的回到 `needs_agent`**：先把 `detail-3` 换成印字清晰可读的 `references/main-5.jpg` 重出（145s，逐项目视明确 pass），
  再基于历史 7 张 + 新 2 张构造完整 9 图清单 `work/ego/remaining-20261102/product-48/artifacts-v3.json`
  （`validate_agent_artifacts` 实跑 `approved=True`、9 张齐全），`batch requeue --task-id 48 --proof ...` 返回
  `state=needs_agent, round=1, reviewer=workbuddy-20261116`，并落两条事件 `blocked→visual_round_opened→needs_agent`。
- ② **只回队，不写商品**：下一步若要写入，须另行明确授权（`batch run` 是对外经营动作）。
- ③ Codex 的等待器优化已细化到可贴：`C:/Users/19431/tb-auto/work/doudian-20261114/PROBE-DESIGN.md`。
  实抓 DOM 的关键事实：`[data-message-author-role]` **在新 UI 完全失效**（`messages=[]`），
  可靠信号是 `span[role=status][aria-live=polite].sr-only`（文本「回答已完成」）、
  `[data-testid=generated-image-gallery]`、`img[alt^="已生成图像"]`、`[role=alert]`。
  三个早退码 `GENERATION_UI_ERROR` / `GENERATION_REFUSED` / `GENERATION_NO_IMAGE`，均 `retryable=False`，
  且「不确定就继续等」，不动 snapshot 并集与两次稳定判据。
- ④ **未动 tb-auto 源码**：那边有并发会话。探针方案已在 `PROBE-DESIGN.md` 定稿；
  补做了一次纯文字复现（不生图、零额度），抓到一个**反例**：「回复已完成但无图」时
  `role=status` 文本是**空的**，但 `document.body.innerText` 尾部有「回答已完成」，且 `generated=0`、
  `stopping=false`、`alerts=[]` 连续 26 轮稳定 → 定稿判据改为**以文本尾部为主**，
  `role=status` 只作辅助；「停止按钮消失」这条辅助判据不启用（生成中 DOM 尚未实抓）。
- ⑤ task 15/34/48 满足「从未写过」准入门槛；16（有 artifacts_path）、27（有租约且无失败复核）会被正确拒绝。
  15/34 尚无新素材，本轮不强行补复核。

### T-20261116-001 · 194-202 · ✅ 按 Codex 审查补齐 requeue 与按轮次计数

- 状态：**done（机制 + 7 条测试 + 196 项回归）**。零商品写入、零队列状态变更。Codex 审查报告 `/tmp/codex-brief-20261115.md`。
- ① 修 `attempt > 2` 终身计数：`batch.py::_visual_round_start()` 读 `visual_round_opened` 事件划轮次，`complete_agent_task()` 只数本轮复核；旧证据跨轮重放报 `visual_round_conflict`。
- ② 新增 `batch requeue --task-id --proof <artifacts.json>`（`batch.requeue_visual_task`）：两个错误码精确白名单 + 必须有 `asset_reviews` 失败记录 + 完整 9 图清单过 `validate_visual_review` + 证据 30 分钟内且晚于最后状态变更 + 从未写过/无租约/无兄弟/无活跃任务 + `BEGIN IMMEDIATE` 重验 + 两条幂等事件。
- ③ `visual_review.GENERATORS` 加 `web-gpt-ego`（否则网页 GPT 出的图一律 `image_provenance_missing`）。
- ④ 🔴 **`conditional` / `pass_with_note` 一律拒绝放行**，不会自动归一为 pass。实测准入：15/34/48 满足「从未写过」；16 有 `artifacts_path`、27 有租约且无失败复核，都会被正确拒绝；48/detail-3 仍是 `conditional`。**当前没有一件可直接 requeue。**
- ⑤ Codex 另两条（等待器终态探针、图文一致性校验）留给 tb-auto 侧，未动那个仓库的源码——有并发会话、探针 DOM 未验证。
- ⑥ 测试 `tests/test_requeue_visual.py` 7 条；文档 `docs/dropship-policy.md` ⑲。

### T-20261114-021 · 194-76 · 抓回一次假恢复：preflight 通过 ≠ 能写入

- 状态：**done（缺门补齐 + 一次错误恢复被收回）**。零商品写入。队列 `blocked 39 / verified 22 / needs_agent 0`。
- ① **假恢复怎么发生的**：T-20261114-020 后 task 22 被放到 `needs_agent`（重检 `eligible=true`，抖店侧主图 5、详情 19、属性齐）。打算给它出 9 张图时，`prepare_one.py` 连续两次卡在妙手 `_mark_control('edit_button')` 的 `page_timeout`。查 2026-11-14 的对照实验：**task 22 根本不在妙手**（`listed=0`，且重试过一次）。
- ② **根因是闸门缺口**：`preflight` 只读**抖店**官方页，证明的是「抖店侧可写」；而**写入实际走妙手**。两者缺一都不能放行，恢复路径当时只看了前者。
- ③ **补法**：`batch preflight --check-miaoshou` 用新增的 `MiaoshouEditor.row_present()` 做**纯只读**探测（导航到快速编辑页 → 搜索 → 数按商品 ID 匹配的行，**不点编辑按钮、不打开商品**），结果写进报告 `evidence.miaoshou_listed`；读不到时写 `None`，**绝不把「读失败」当成「不存在」**。`apply_preflight_report` 的**放回分支**要求 `miaoshou_listed is True`，否则报 `miaoshou_listing_unproven`；**刷新理由的分支不要求**。
- ④ **实测**：task 22 同时 `eligible=true` 与 `miaoshou_listed=false` → 被闸门正确挡住。当时**没有受支持命令能把 `needs_agent` 改回 `blocked`**，先手工收回并写 `product_events`；随后补上 `batch block --task-id --reason`（只允许 `needs_agent → blocked`，理由必填 ≥10 字，落 `manual_block:` 前缀，**不参与自动重检**）。刷新理由时若 `miaoshou_listed=false`，还会在末尾追加「妙手侧无此商品，写入路径不可用」。
- ⑤ **已知不在妙手的 6 件**：12 / 22 / 33 / 36 / 46 / 52。它们的 `page_timeout` 都是**结构性**的，别再当瞬时抖动重试；33 还叠加「商品在抖店侧不存在（`product-status` 返回 `not_found`）」，36 是已删除。
- ⑥ 代码：`MiaoshouEditor.row_present`、`preflight_products(..., check_miaoshou=)`、`apply_preflight_report` 的妙手闸门、CLI `--check-miaoshou`。测试 `tests/test_reopen_blocked.py` 12 → **14**（「缺妙手证明不能放回」「妙手明确不存在也不能放回」）+ 新增 `tests/test_block_task.py` **7 条**（含「有保存尝试/有基线/已核验一律不准收回」「手工收回不被自动重检推翻」「刷新理由要写明妙手缺货」）。文档：`docs/dropship-policy.md` ⑱-b。
- ⑦ **同轮补完两件相邻事实**：① task 58 的 121 个 SKU 读不全，**滚外层表单也不增长**（先滚 holder 到 `st=13332/sh=14069`，再滚 `styles_form__Ew_RZ` 到底，`scrollHeight` 不变，按 SKU ID 去重 16→18 只是渲染补全）→ 平台把虚拟列表总高封在约 111 行，**换数据源才能解决**，别再试滚动参数；② task 46/52 的理由现在都带上「妙手快速编辑列表中没有该商品，写入路径不可用」，它们与 task 22 一样**不在妙手**，槽位不足只是第二层原因。


### T-20261114-020 · 194-76 · 19 件预检阻塞件全量重检：1 件真恢复，12 件理由被更正

- 状态：**done（只读重检 + 队列理由更正）**。零商品写入。队列 `blocked 39 → 38`、`needs_agent 0 → 1`、`verified 22` 不变。
- ① **task 22 真的恢复了**：旧的 `doudian_draft_or_rejected` 已完全不成立，重检 `eligible` → `needs_agent`，可直接进入素材准备（还需 9 张图，属花钱动作，未开始）。
- ② **12 件理由被更正**（23/28/31/39/43/45/46/51/52/54/55/56/57/59/60）：队列现在写的是今天读到的原因，不再是 11.9 天前的快照。
- ③ **三处旧判断被推翻**，这是本次重检最大的价值：
  - 「`doudian_draft_or_rejected` 4 件」**只剩 task 51 真的成立**。46/52 其实是槽位不足（主图 3 张），56 是 `writer_detail_source_collision`（前 4 张详情有重复原图，与 task 49 同款）。
  - task 23 缺的是 **5 项**属性（安装方式、是否可接触食品、材质类型、型号、生产企业地址），不是旧记录里的 1 项 —— 按旧记录去补值是补不完的。
  - task 39 真正先卡的是槽位（主图 4 张），不是「缺安装方式」。
- ④ **3 件读失败、1 件被别的闸门跳过**：task 33 页面无任何分区 → `product-status` 返回 `not_found`，**实际是商品在抖店侧不存在**（不是登录问题）；task 58 编码 91/121（能力上限，见 T-20261114-018）；task 50 有活跃官方任务（`active_official_job`）。
- ⑤ **两条实测教训**：`close_session` 结束的是整个 TaskSpace，共享 session 会让后续件全部 `ego_session_finished`（0.1 秒即失败）——必须**每件独立 session**；读失败（无快照）**不覆盖** `last_error`，否则「页面没就绪」会埋掉真实原因。
- ⑥ 工具：`work/probe-20261114/batch_recheck.py`（逐件独立会话 + 逐件对账），产物 `work/probe-20261114/recheck-batch-*/recheck-applied.json`。文档：`docs/dropship-policy.md` ⑱ 追加实测段与三条新判据。

### T-20261114-019 · 194-76 · 补上「因预检失败而 blocked」的恢复路径

- 状态：**done（一对受支持的命令 + 一次真跑实证）**。零商品写入，队列里 1 件的阻塞理由被更正为真实事实。
- ① **洞在哪**：`preflight_exception:*` 不在 `PREWRITE_RECOVERABLE_ERRORS` 里，`batch preflight` 又对 blocked 件直接 `queue_state_ineligible` —— 于是「根因早修掉、当年那次预检失败」的件**没有任何受支持的命令能放回可运行**。T-20261114-018 的 task 57 就卡在这里。
- ② **补法分两步，都不放宽安全条件**：
  ```bash
  doudian-auto batch preflight --product-id <pid> --batch-id <bid> --session <现有会话> \
      --report-dir <dir> --recheck-blocked      # 只读重读，连接仍是 mode=ro，不改队列
  doudian-auto batch recheck --task-id <id> --proof <dir>/<run>/summary.json   # 凭报告对齐队列
  ```
- ③ **准入只看 `last_error` 前缀**：`preflight_exception:` 开头的件才可重读；`readback_mismatch`、`doudian_product_deleted` 等**一律不放**，因为那类失败可能描述一次真实写入。
- ④ **`recheck` 只认报告里的四件事**：`read_only=true`、`evidence.snapshot_read=true`、商品/店铺/`target_version` 三者与本行一致、`observed_at` 在 30 分钟内且 `snapshot_sha256` 是 64 位摘要。此外本行必须仍是 `blocked`、`not_attempted`、`attempts=0`、**无 baseline/素材/上传记录/租约/兄弟版本/活跃官方任务** —— 即「从未写过」。
- ⑤ **两种结局都落库并写 `product_events`**：`eligible=true` → `blocked → needs_agent` 并清空 `last_error`；**又失败 → 保持 blocked，但把 `last_error` 换成这次读到的理由**（保留前缀，下次还能再检）。后半条是重点：十二天前的理由把排查带偏过一次。
- ⑥ **实证（task 57）**：走完两步后 `last_error` 从 `official_sku_code_incomplete; 仅确认7/44个SKU` 更正为 `writer_image_slots_incomplete; 主图5张、详情2张`。**编码问题早就不存在，真正缺的是 2 张详情源图**。57 仍在售（`statusName=上架`），写入属线上动作，未授权不做。
- ⑦ 代码：`batch.apply_preflight_report`（原 `reopen_blocked`）、`preflight._skip_reason(..., recheck_blocked=)`、`preflight_products(..., recheck_blocked=)`、`_COLUMNS` 增 `last_error`、CLI `batch preflight --recheck-blocked` / `batch recheck`。测试新增 `tests/test_reopen_blocked.py` **10 条**（含「陈旧报告拒绝」「只差一个版本拒绝」「写入型阻塞永不放行」「失败也要刷新理由」「刷新后仍可再检」），回归 178 项全绿。文档：`docs/dropship-policy.md` 新增 ⑱。

### T-20261114-018 · 194-76 · 商家编码读取：一条旧错误被证伪，两个真缺陷被修掉

- 状态：**done（只读诊断 + 两处读取器修复），零商品写入**。task 57/58 仍 blocked，但阻塞理由都换了更精确的写法。
- ① **task 57 的旧错误已失效**：`editor.read_skus` 现在读完 **44/44**（`code_ui_rows=44`），且 44 个商家编码**全是空字符串**——这是 `collect_official_sku_codes` 允许的合法证据。11.9 天前那次是旧策略的受害者（当时只在 `pending_count>0` 时才滚，57 是「真行+0 占位行」，30 秒一次没滚），真因已由 T-20261114-014 修掉。**教训：旧 `last_error` 不能当结论，必须重跑。**
- ② **task 58 有两个真缺陷**，都不是预算：
  - **尺码表的 keyed 行被当成 SKU 行**：58 的「价格库存」里既有一张尺码表（11 个 `tr[data-row-key]`、每行 4 个 td、无 sku/code 单元格），也有 SKU 表（表头 12 列）。读取器直接 `root.querySelectorAll('tr[data-row-key]')`，尺码行先被遍历 → `skuCells.length!==1` → `row_ambiguous`。**keyed 行 ≠ SKU 行。** 修：只保留带 sku/code 单元格的行，一个都没有时回落全集（fail closed 不变）。顺带让 `scroll_rows` 挑 SKU 行所在的 holder。
  - **占位行分支不推进虚拟 holder**：`scroll_pending` 只做 `scrollIntoView`，虚拟列表不响应；58 有 **121** 个 SKU 且常驻占位行 → 30 秒没换行 → 只读到 10 行。修：`scroll_pending` 与 `scroll_rows` 都推 holder。
- ③ **修完 58 从 10/121 到 91/121**，错误从 `row_ambiguous` 变成可诊断的 `incomplete`。**剩下 30 行是能力上限不是预算**：holder `scrollHeight` 到 13332 就停（约 111 行），滚到底回绕也补不上；把预算提到 90 秒结果**一模一样**，所以已回退——没有实测收益就不动契约。
- ④ **实测口径**（下次省时间）：57 每轮 `evaluate` 160–260ms、半页步进推进 2 行、`scrollHeight` 滚动中从 3411 长到 3911；58 的 row key 是**渲染槽位号**（同一 key 会换内容），所以「按 key 去重」在 58 上会假性停在 9，必须按 SKU ID 累计。
- ⑤ **两件都还动不了**：57 需要一条受支持的「preflight 失败的 blocked 件」恢复路径（`recover-preflight`/`preflight` 都不收，`preflight` 直接 `queue_state_ineligible`）；58 要读完 121 行得让外层表单滚动触发懒加载，是另一件事。**57 在售（`statusName=上架`），写入属线上动作，未授权不做。**
- ⑥ 代码：`official_sku_code_dom.js` 两处；测试 `official-sku-code-dom.test.cjs` 18→**21**（新增「邻表 keyed 行被跳过」「只有外来的 keyed 行仍 fail closed」「scroll_rows 推 SKU 行所在的 holder」），适配器 38/38 真跑通过。文档：`docs/dropship-policy.md` 新增 ⑰。

### T-20261114-017 · 194-76 · 4 件收尾：3 件双端 verified，task 11 定性为「基线渲染窗口不全」

- 状态：**done（3 件真写，1 件定案保持 blocked）**。队列 `verified 19 → 22`、`needs_agent 4 → 0`、`blocked 38 → 39`，总数 61 不变。
- ① **task 35**（`3848317566716084561` 银丝洗碗布，9 SKU）→ `verified`。9 图（`main-1..5` 1024²、`detail-1..4` 1024×1536）逐张去水印后目视复核 → `build_from_spec` → `agent complete` → `batch run --apply` 当轮 `submission` 阶段 `batch_apply_response_unknown`（只点了 1 次保存）→ **`readback_one.py` 单件只读复核**得 `verified / verified_by_readback`（`miao_matches` 与 `doudian_matches` 均真）。标题 `银丝洗碗布家用厨房锅具灶台清洁抹布单层双层多种数量可选`。**结论：保存其实成功了，只是当轮没等到响应。**
- ② **task 2**（`3850072900438720563` 男士平角内裤，25 SKU）→ `verified`，一次通过，**5 分 46 秒**。`main-4`/`main-5` 各重做一次：第一版 `main-4` 出现「COKUMAN」重影字、`main-5` 红色偏酒红 → 重写提示词（「每个腰头恰好 COKUMAN 一次、居中、不与其它文字重叠」/「亮正红，不要 maroon、不要 burgundy」），并加 `recenter.py` 居中 + 二次去水印（两次都 `no watermark pixels found`）。**观察记录必须写「腰头织白色 COKUMAN」**，`printing` 不能写成「无印字」。
- ③ **task 37**（`3848317504447447331` 桌下抽屉收纳盒，2 SKU）→ `verified`，**5 分 5 秒**，`miao_matches` 与 `doudian_matches` 均真。**前 3 版全弃**（存 `assets/rejected/`）：`21-36-15`、`21-36-56` 把开口浅盘画成带铰链翻盖；`21-37-36` 大号出现双层内盘。改用 **image1 参考图编辑**（`input_fidelity: high`），全部只保留「开口浅盘 + 薄外套贴桌板」的几何后才过。
- ④ **task 11**（`3850071893537325881` 男童直筒休闲裤，32 SKU）→ **素材已交付、写入已发生，仍 `blocked`**（`submission_state=unknown`、`last_error=readback_mismatch`）。妙手侧全对（`matches_target=true`、9 张图 URL 全中）；抖店侧 `main_count=5`、`detail_count=7`（4 换 + 3 留）、标题一致、`rejected=false`、`draft_loaded=false`，**唯一分歧是 `compare_protected` 抛 `commercial_changed`**。
- ⑤ **定性过程（本轮最花时间的一段，结论推翻了中途三个错误判断）**：
  - 🔴 先用错了对象：把**外层** `baseline_json` 当 `before` 传进 `compare_protected`，得到 `official_sku_incomplete`，差点写成「SKU 证据缺失」。正确对象是内层 `baseline['doudian_baseline']`。
  - 拿对之后：8 个分区**只有「价格库存」不同**，其余 7 个逐字节相同；两侧观测状态都是合法的 `ready`/`empty_block`，所以**不是** `protected_snapshot_incomplete`。
  - 差异只在 `inputs`：**基线 167 条、读回 173 条**。多重集差 `0 删 / 6 增`；**前缀**不成立（第 160 位分叉）；**保序子序列成立** —— 即没有任何一条被删或被改。
  - 6 条增量 = 一整行 SKU 的控件；`sku_evidence` 两侧 `count=32`、`sha256=d0b6fd86…` **完全相同**，且那一行 `LC弯刀裤黑标-灰色170`（49.88）**本来就在基线 `raw_rows` 里** → 原先就有、只是没渲染。
  - 决定性一步：拿 SKU 编码去 DOM 点命中数 —— **基线 7/32、读回 8/32**，两次都是**顶部对齐**（0–6 行 vs 0–7 行）。`价格库存` 的 `inputs` 本质是**视口窗口**，不是全表。
  - 真因串起来：task 11 的基线是在 Ego 窗口**最小化（内宽 901）**时抓的，读回是按 ⑮ 把窗口放大到内宽 ≈1708 之后抓的 → 一屏多装一行 → 多 6 个 input。**同一个「窗口」问题第二次咬人，这次咬在数据判定上。**
- ⑥ **为什么不放闸门**：采集器自己在快照里写着 `coverage: 仅DOM实际加载字段；虚拟SKU列表未逐行遍历`、`sku_coverage: 不受虚拟表格可见行数限制`，也就是**声明了这是部分窗口、全量证明由 `sku_evidence` 承担**；但 `compare_protected` 对这块做逐条严格相等，等于把部分窗口当完整快照比 —— 这是代码内部自相矛盾，`protected_complete=true` 因此是**假完整**（四件全 True，task 11 只覆盖 7/32 行）。**但**：该函数的 docstring 明确记录过子多重集容忍被移除，`tests/test_workflow.py:469` 更是把「更长的字段列表就是变更」钉死 —— 子序列判据会让这条测试失效，等于推翻既有安全结论。**为了让某一件过闸而顺手放宽，正是这个项目反复拒绝的做法**，所以保持 blocked，理由写成「基线对该分区只覆盖 7/32 行、与读回窗口高度不同」，**不写「价格被改」、不写「平台不给」**。
- ⑦ **采集侧已修（兼容式，未松闸门）**：`价格库存` 额外记录 `inputs_without_sku_grid`（同 `inputs` 但去掉网格行 `<tr data-row-key>` 内的单元格）与 `sku_grid_rows`（本次挂载了几行，纯覆盖元数据）；比对时**只有两侧都带新列表、且分区是「价格库存」**才用它替换 `inputs`（限定分区，避免别的分区靠塞这个键绕过比对），旧基线照旧严格比 `inputs` —— 严格度不降。**不能直接把网格行从 `inputs` 删掉**：`_stored_execution_baseline` 用的是库里持久化基线，删了会让 61 件历史基线与新读回全对不上。回归：`dom.test.cjs` 4 条（含「窗口 7 vs 8 行时 `inputs` 必须不同、比对列表必须相同」）、`test_workflow.py` 5 条（含「旧基线无新列表时必须仍然严格」）。⚠️ **只对以后重采的基线生效**，历史基线不可变，task 11 照旧 blocked。
- ⑧ **Codex 这轮没给到意见**：`codex exec` 直接报 `You've hit your usage limit … try again at 6:52 AM`，所以上述判定全部由我自己按成文规则做，未获第二意见 —— 这也是我选择「不放宽闸门」而不是「按摘要结案」的原因之一。
- ⑨ 工具沉淀（`work/materials-20261114/`）：`build_from_spec.py`（读 `spec.json` → `source.json`+`artifacts.json`，`prompts`/`assets` 由 `kind+slot` 推导）、`recenter.py`（白底居中，不改颜色不裁主体）、`ensure-window.mjs`（CDP 放大窗口，**必须先跑再 `batch run --apply`**）、`readback_one.py`（单件只读复核，绕开 CLI 不支持按商品过滤）、`probe_official.py`（只读抓抖店编辑页图片 URL + 字节 sha256）、`dewatermark.py`（**只能逐文件列路径，传目录会 PermissionError**）。

### T-20261114-016 · 194-76 · 试点打通：task 40 九图重建 → 写入妙手 → 双端 verified

- 状态：**done，真写商品**（本项目第 19 件 verified）。`submission_attempts=1`，`state=verified`、`submission_state=verified_by_readback`。
- ① **素材**：9 张全部走 `builtin-imagegen` 图生图（`input_fidelity=high`），每张以**对应原图**为输入，提示词把身份件写死（一把长方形刷头扫把 + 一只口沿带橙色梳齿条的簸箕、清水蓝塑料、橙色磁吸椭圆扣、不锈钢圆杆），并禁止添加刮水器/第三件/任何文字。**风格选择：9 张全部无中文覆盖字**——原图那套营销字是排版层，而模型渲染中文有畸变风险；skill 里那条「不能用 Pillow 加字排版冒充 AI 重构」约束的是**拼贴**，不是要求必须带字。若要带卖点文案，是下一轮单独动作。
- ② **ImageGen 水印**：出图右下角必带「AI生成 WORKBUDDY」。按项目既定做法（`docs/handoff-history/194-54.md`）用 `cv2.inpaint` 修，**但只按「近纯白+低饱和」判据会留残影**（水印压在橙色/深色产品上时亮度不够）。最终三判据并用：浅底用「比局部中值更亮」、深色角落用「紧框内偏离中值 ≥6」、最后**只在掩膜内羽化混入大核中值**，消除 TELEA 在平滑渐变上的噪点与边界。工具 `work/materials-20261114/dewatermark.py`（非 ASCII 路径走 `np.fromfile`）。
- ③ **`page_timeout` 的真因是 Ego 窗口被最小化**（不是页面改版、也不是 `state.viewport`）。`pageInfo()` 报 `w=901 h=638`、`Browser.getWindowForTarget` 报 `windowState=minimized`；妙手「查询」按钮 `left=1017 > innerWidth=901` → 撞 `visible()` 的 `r.left >= innerWidth` 判据。手工先写 `state.viewport=1440×900` 会被 run 覆盖（每个 run 新建并收尾自己的任务空间，起始视口由真实窗口观测而来），**必须用 CDP 把窗口本体放大**：`Browser.setWindowBounds{windowState:'normal', 1520×1010}`，随后窗口变 maximized（内宽 ≈1708），同一条命令一次通过。详见 `docs/dropship-policy.md` ⑮。
- ④ **素材交付契约**：`source.json` 五类事实（identity/color/quantity/printing/specification）逐张被 9 条目视记录引用，每条 `observed` 写的是实际看见的东西（不是「通过」两个字），并绑定对应原图 sha256；`facts_sha256` 与 `source_snapshot.sha256` 双绑定。离线 `validate_agent_artifacts` 一次通过（`approved=True`、零失败槽位），再 `agent complete` → `ready`。
- ⑤ **写入与读回**：`batch run --product-id 3848316916011762046 --limit 1 --apply` →
  妙手与抖店**两端**均 `complete=true`、`main_count=5`、`detail_count=4`、`matches_target=true`、`protected_match=true`，
  标题一致 `磁吸折叠扫把簸箕家用梳齿刮毛发不锈钢杆扫地工具2件3件套多色`（58 units，零错误零告警，原 33 units）。
  当前仍 `shelf_status=1`（下架/在仓）；`startSaleType` 由 0 → 1，这是 `preserve_warehouse_v1` 允许的审核去向，**不等于上架**，`shelf_mode_matches_original=false` 是如实记录该差异，不是失败。
- ⑥ **队列**：`verified 18 → 19`、`needs_agent 5 → 4`。剩 4 件（task 2 / 11 / 35 / 37）素材已核清（各 5 主图 + ≥4 详情、前 4 张详情源图唯一、`detail_ready`），**每件还需生成 9 张图**（共 36 张），要花生图额度，等确认再动。

### T-20261114-015 · 194-76 · 妙手清单逐件对照：6 件不在妙手／不可证历史定案／5 件素材已核清就绪

- 状态：**done（诊断闭环）**，零商品写入。本轮把「blocked 里还有哪些能自解」彻底定量化，结论是：**自动路径已到边界，剩下 5 件需要生成 45 张新图**（要花生图额度，等人确认）。
- ① **task 12 的 `page_timeout` 是结构性的，不是瞬时抖动**。重试一次仍停在 `_mark_control('edit_button')`；随后用**对照实验**定性：同一路径同一输入框，搜确定在妙手的 `3850071893537325881` 得 `商品信息 (1)` + `edit_button count=1`，搜 task 12 的 `3850071781591351757` 得 `商品信息 (0)` + `暂无数据` + `共 0 条`，再搜对照又回到 `(1)` → **搜索机制有效，这件商品不在妙手**。它的妙手基线不可能存在，`rebaseline` 永久不可达，只能保持 blocked。
- ② **把队列 61 件逐件拿去妙手搜了一遍**（`work/rebaseline-20261113/harvest_inventory.py` → `miaoshou-inventory.json`，命中 0 时自动重试一次）：**55 件在、6 件不在**——task **12 / 22 / 33 / 36 / 46 / 52**。其余 5 件本来就有更精确的阻塞理由（22/46/52 = 抖店草稿或驳回；33 = 主图仅 3 张；36 = 商品已彻底删除），妙手无行只是同一事实的另一面。**task 36 的已知结论「已删除」正好交叉验证了这套判据有效。**
- ③ **9 件 `external_work_requires_rebaseline` 定案（经 Codex 第三轮咨询）**：task **1 / 3 / 4 / 6 / 8** 读得通、双端一致，但历史证据的 `stage` 是 `editing / completed / official_readback_complete / saved_and_verified` 且 `status` 全为 `None`，**不能安全归为任一种结案结论**。Codex 结论原文：「这 5 件都不能安全归为 `prior_revision_confirmed`，应保持 blocked。新鲜双端快照证明当前两端内容一致且可作为基线，但不能替代对历史保存、提交和读回状态的证明。」→ **不自动归类、不自动恢复**，也不加 `stage` 关键词白名单（那等于放宽闸门）。这 5 件需要人工核实历史版本。
- ④ **task 13 / 57 / 58 的「读不全」已被证伪**：探针直接打印妙手原始响应条数——task 13 `pic=3 / desc=21`（主图 3 张）、task 57 与 58 `pic=5 / desc=2`（详情 2 张）。**是素材确实不足，不是读取器漏读**。写入器要求正好 5 主图 + 至少 4 详情，这几件只能靠补源图，不能靠改代码。
- ⑤ **5 件 `needs_agent` 的素材已逐件核清就绪**（`work/materials-20261114/`，双端新鲜快照 + 原图落盘）：
  | task | 商品 | 妙手主图/详情 | SKU | 详情源图前 4 张唯一 |
  |---|---|---|---|---|
  | 2 | 男士平角内裤 | 5 / 22 | 25 | ✅ |
  | 11 | 男童直筒休闲裤 | 5 / 7 | 32 | ✅ |
  | 35 | 银丝洗碗布 | 5 / 16 | 9 | ✅ |
  | 37 | 桌下抽屉收纳盒 | 5 / 15 | 2 | ✅ |
  | 40 | 磁吸扫把簸箕 | 5 / 4 | 24 | ✅ |
  五件的妙手/抖店标题与 `resource_key` 序列两侧完全一致，`detail_status=ready`，且**前 4 张详情源图在整个序列中各自只出现一次**（task 7 卡住的 `writer_detail_source_collision` 在它们身上不成立）。写入器就绪性实测 `writer_ready=true`（三品验收记录完好、`WRITER_REVISION=multi-field-20261030-v5`）。
- ⑥ **本轮唯一剩余动作**：每件需要 5 张新主图 + 4 张新详情（共 45 张，走 `builtin-imagegen` 图生图 + 逐张目视审查）。这是**花钱的动作**，未擅自开始。

### T-20261114-014 · 194-76 · 两处「读不全」实抓到真因并修复／恢复 2 件

- 状态：**done**，有商品侧实质进展但**未写任何商品字段**。零商品写入：只读采集 + 队列状态流转。
- ① **先纠正上一轮的错误结论**：Codex 审查指出「SKU 表格只渲染 7 行、详情槽位固定 28 是平台上限」证据不足，我核实后确认**确实错了**——同一套采集代码在 25 / 32 / **56** 个 SKU 的商品上读全过。于是回实页定位真因，而不是继续给结论打补丁。
- ② **SKU：真滚动容器是 `.ecom-g-table-tbody-virtual-holder`**。表格是虚拟列表，`scrollHeight 2707 ≈ 24 × 113px`、clientHeight 523，只挂载 6–7 行；`#goodsEditScrollContainer` 只是把整块内容移进视野，**滚它行键一个都不变**（107–112 恒定），改 `holder.scrollTop` 才换行（300→109-115、600→112-118、900→114-120、1200→117-123）。修复：JS 新增 `op='scroll_rows'`（半页步进、到底回绕），Python 在「ready 且无占位行」时走这条。**校验强度未降**（16 位 SKU、唯一可见 input、跨轮冲突拒绝）。
- ③ **详情：后 9 张是懒加载没触发**。37 个缩略卡片都在，但卡片 28–36 的 `<img>` 停在 1×1 占位 GIF（`loading="lazy"`，真实地址等进视口才写入）。关键实测：对**第一张未加载卡片**做一次 `scrollIntoView`，`28 → 37 一次全部加载`；只滚整块没用，块内部也没有滚动容器。修复：`op='scroll'` 在 `kind='details'` 时改滚第一张未加载卡片，`wait_details` 每轮 nudge 一次；仍要求 `declared == slots == cards`。
- ④ **实测结果**：task 40（24 SKU）与 task 35（9 SKU）双端 `SKU PASS + official_validate PASS`，**已恢复 `blocked → needs_agent`**。task 7（56 SKU / 37 详情）读取也全过了，但撞上 `writer_detail_source_collision`——前 4 张详情有重复原图，妙手按图查找替换会同时改多处，**写入器不支持逐位置替换**。这是写入契约限制，不是读取限制，仍 blocked 且原因已如实更新。
- ⑤ **验证**：JS 15 项（新增 3 项 `scroll_rows`：半页步进 / 到底回绕 / 无 holder 时不报错）、`test_editor.py` 10 项（新增「每轮 nudge 一张未加载详情」）、`test_official_sku_codes.py` 21 项（新增「无占位行时走 `scroll_rows`」）、`test_workflow + test_title` 130 项全过；适配器仍零反斜杠。
- ⑥ 队列：`blocked 40 → 38`、`needs_agent 3 → 5`、`verified 18`。下一轮可继续处理 `external_work_requires_rebaseline` 里剩下的件——它们的阻塞理由需要逐件重查，**不要再假设是「页面硬上限」**。

### T-20261113-012 · 194-76 · 队列恢复实操：3 件重新基线成功／结案契约补齐／两处「读不全」的机制辨析

- 状态：**done**。Agent workbuddy，2026-11-13 凌晨。未调用 Codex。**本轮解开的是「队列停摆」而不是新功能**：43 件 blocked 里 14 件标着 `external_work_requires_rebaseline`，但此前从来没人真跑过 `batch rebaseline`，也没人验证过它到底能不能处理这 14 件。
- ① **先查清队列为什么会停**：`products.id`（数字主键）才是 `--task-id` 认的值，**不是抖店商品 ID**；`external_observations.task_id` 同样指向数字主键。用商品 ID 去查会得到「0 条观察证据」的假结论。这 14 件其实各有 1–2 条观察证据，前置条件（`baseline_hash`/`artifacts_path`/`upload_map`/租约）全部干净。
- ② **第一次真跑 `batch rebaseline` 连撞两个页面层问题**（都不是 rebaseline 的契约问题）：
  - 🔴 **Ego 把每个 Page 钉死在 `state.viewport`（本次 904×788）**。妙手 `quick_edit` 的「查询」按钮实测 `left=1017`，而 `visible()` 的判据里有 `r.left >= innerWidth → false` → **控件明明存在、却被判成不可见**（报错是「未唯一定位」，很容易误判成页面改版）。修法：把任务空间 `state.viewport` 调到 1440×900。**视口是被 Ego 复用的固定值，页面不会自己适配**。
  - 🔴 **全屏 `op.jinritemai.com` 组件 iframe 会拦截整页点击**：实测一个 `1440×900 / z-index:10000 / pointer-events:auto` 的 iframe（`appId=7641889070456782908&cId=524`）覆盖整个妙手页，`document.elementFromPoint` 永远返回它 → 所有控件的 `actionable` 都是 false。它不是页面内容，**刷新即消失**（SPA 路由切换会把它留下）。
  - 采集顺序改为**先妙手、后抖店**：抖店侧 `_stable_doudian_snapshot` 自己会开 `Emulation.setFocusEmulationEnabled`，能容忍后台页；妙手侧的可见性判定依赖真实布局，必须前台。
- ③ **恢复 3 件成功**：`task 2`（3850072900438720563 男士内裤）、`task 11`（3850071893537325881 男童休闲裤）、`task 37`（3848317504447447331 桌下收纳盒）→ `blocked → needs_agent`，`target_version` 与历史保留不变。每件都是**双端新鲜快照 + 逐条观察证据结案**：妙手 5 主图 / 5·7·15 详情、抖店同数量且 `detail_status=ready`、标题与图片 `resource_key` 序列两侧完全相等、`verify_miaoshou_skus` 通过。
- ④ **结案契约补齐（`rebaseline.py`，经交叉审查后收紧两轮）**：历史 agent 把同一个结论写成了不同字段名，原契约只认 `status == 'not_attempted'` 和 `(stage=='verified' and status=='accepted')` 两种精确组合，导致 11 件即便证据明确也永远结不了案。新增两条**等强或更强**的判定（`unknown` 一律不结案）：
  - `saved is False` **且** 计数（`saveAttempts`/`saveCount`）**至少存在一个且全部为明确的非负整数 0** **且** `uploadsStarted` 为假 → 视为 `no_save_attempted`（真实样本：`{'phase':'upload_unknown','saved':false,'saveCount':0}`）。🔴 计数缺失、`None`、负数、布尔、字符串 `"0"`（`"0" <= 0` 会直接抛 `TypeError`）**一律拒绝**；`uploadsStarted=True` 也拒绝——素材可能已经传到妙手侧，不能笼统算「什么都没发生」。
  - `submission_state == 'verified_by_readback'` → 视为 `prior_revision_confirmed`（这是队列自己的终态，比 `accepted` 更强）。🔴 但 `submission_status` 与 `submission_state` **同时存在时必须一致**：任一为 `unknown` 或两者冲突（如 `accepted` + `unknown`）一律不结案，不允许字段顺序决定答案。
  - 测试参数从 7 个扩到 **17 个**（`tests/test_rebaseline.py`，32 项全通过）：新增 `saved_none` / `saved_negative` / `saved_str_zero` / `saved_no_counter` / `uploads_started` / `status_conflict` / `status_unknown_pair`，全部**必须失败**。
- ⑤ 🔴 **两处「读不全」已定位并修复（先经 Codex 交叉审查撤回错误结论，再实抓到真因）**：
  - **SKU 表格在这两件商品上只挂载 6–7 行**。商品 `3848316916011762046`：API 返回 **24 个 SKU**（全部 `sku_status=true`、24 个不同 `spec_detail_ids`），DOM 里 `tr[data-row-key]` 只有 6–7 行；滚动 `#goodsEditScrollContainer` 到 3704（到底）行数不变；视口高度 900→2600（`innerHeight` 2889）行数仍 7；点「全屏」只从 7 变 8。商品 `3848317566716084561` 9 个 SKU 同样只读到 7 个。
    🔴 **「7 行是平台上限」这个结论是错的**（同一套采集代码在 25 / 32 个 SKU 的商品上读全过），而且 **2026-11-14 已定位真因并修好**：表格是虚拟列表，真正决定挂载哪些行的是 **`div.ecom-g-table-tbody-virtual-holder` 的 `scrollTop`**（`scrollHeight 2707 ≈ 24 × 113px`，clientHeight 523），而 `#goodsEditScrollContainer` 只是把整块内容移进视野——**滚外层容器时行键一个都不变**（实测 107–112 恒定），改 `holder.scrollTop` 才换行（300→109-115、600→112-118、900→114-120、1200→117-123）。修复：JS 新增 `op='scroll_rows'`（半页步进、到底回绕），Python 在「ready 且无占位行」时走这条路径；**校验强度未降**（16 位 SKU、唯一可见 input、跨轮冲突拒绝）。实测 24/24 个编码读全，task 40 双端快照 `SKU PASS` + `official_validate PASS`，**已恢复 `blocked → needs_agent`**。详见 `docs/dropship-page-contracts.md` ③。
  - **详情槽位停在 28**。商品 `3850072398019821856`：`detail_declared=37`、`detail_cards=37`、`detail_slots=28`。**2026-11-14 已查清并修好**：37 个缩略卡片都在，但**后 9 张的 `<img>` 停在 1×1 占位 GIF**（`loading="lazy"`，真实地址等卡片进视口才写入）→ 前 28 张有图、9 张永远不加载 → `declared≠slots` → `ambiguous`。关键实测：对**第一张未加载卡片**做一次 `scrollIntoView`，`28 → 37 一次全部加载`、状态转 `ready`；而只滚整个「商品详情」块不管用（块内部没有自己的滚动容器）。修复：`dom.js` 的 `op='scroll'` 在 `kind='details'` 时改滚第一张未加载卡片，`wait_details` 每轮 nudge 一次；校验仍要求 `declared == slots == cards`。
  - 结论：**task 35 / 40 已恢复（`blocked → needs_agent`）**。**task 7 仍 blocked，但原因变了**：详情与 SKU 现在都读全（37/37 详情、56/56 SKU、`details_equal=true`、`SKU PASS`），卡在 `writer_detail_source_collision` —— 前 4 张详情存在重复原图，妙手按图片查找替换会同时改动多处，**写入器不支持逐位置替换**。这是**写入契约的限制，不是读取限制**，也不该再用「平台读不到」解释。
- ⑥ **队列账（2026-11-14 03:08 实读）**：`blocked 40 → 38`、`needs_agent 3 → 5`、`verified 18` 不变（本轮恢复 task 35、40；加上 11-13 的 2/11/37 共 5 件）。`task 36`（3848317525922283791）是 `doudian_product_deleted`，策略里已归 `closed`（不再重试），但**没有受支持的命令把它移出 blocked**，所以仍计入 38；这不影响执行，只是统计口径。
- **验证**：`pytest tests/ -q` 全量通过（进度条 `[100%]` 全程无 `F`/`E`）。⚠️ 本轮同一回合里反复跑之后变成 `39 failed, 681 passed`，逐个查全部是 **safe-delete 守卫撞线**导致的假失败：失败文案里带 `SAFE_DELETE_BULK_CONFIRM_REQUIRED` 且断言是「`browser.lock` 应不存在」，而**单独跑 `tests/test_workflow.py` 仍 55 passed**；同一提交早期全量是全绿的。判据与处理写进 `docs/dropship-policy.md` ⑬（换一个回合再跑以重置计数）。新增/改动：`rebaseline.py` 结案判断、`tests/test_rebaseline.py` 3 个新参数。
- **工具**：`work/rebaseline-20261113/`（`read_pair.py` 双端采集、`make_proof.py` 出 proof、`run_batch.py` 批量、`probe_*` 四个只读探查）。

### T-20261112-011 · 194-76 · 类目必填属性程序化补齐并发布（真写商品）／锁与删除健壮性修复

- 状态：**done**。用户实值授权「生产企业就写1688上家就行，保质期12个月」→ 落到商品 `3853482303460343870`（家清纸品>除臭用品>空气清新/净化/芳香剂）上，**真写、真发布、平台真审核通过**。本轮是本项目第一次由程序写属性并提交审核（此前只到「复制产生草稿」）。
- ① **抖店类目属性有第三种控件形态：数值＋单位复合控件**。此前只认「纯文本」「纯单选/多选」，所以 `保质期` 一直判不出来。实测 DOM：`styles_measureValue__BknXC > styles_measureContainer__AF_AJ > styles_measureTemplate__AfVoo`，数值是 `input.ecom-g-input.styles_value__QXqGx`，单位是 `ecom-g-select`（候选 `天/月/年/个月`，默认预选 `天`）。**平台会预选单位**，所以「单位标签存在」≠ 该属性已填——旧 missing 启发式把默认值「天」当成值，**漏判**（真实缺陷）；平台自己的必填进度 50% 正好证明平台也认为它没填完。新增 `kind='measure'`、读回 `number_value`/`unit_value`，并把 missing 判据改成「**只有数值非空才算已填**」。
- ② **单位下拉是 portal 渲染的**，不能靠 class 找；靠 combobox input 的 `aria-controls="rc_select_N_list"` 精确定位 listbox id（新增 `attribute_unit_options` op）。单位候选必须**在真实候选里校验存在**，否则拒绝写。
- ③ 🔴 **真正卡住 `--apply` 的不是浏览器，是删除守卫**：WorkBuddy 的 safe-delete 守卫按「单次工具调用内累计删除次数」计数，阈值 50，而 CLI 每条浏览器命令净删 **2 个文件**（`transport.lock` + `pending-command.json`）→ 一次几十条命令的 `--apply` 必撞线；守卫拦截时抛的是 **`SystemExit`（不是普通异常）**，把 `Lock.__exit__` 的 unlink 打断 → 三个锁文件全部残留（内容是已死 PID）→ 之后每次运行都报 `busy`，**永久死锁**。前两次 `--apply` 就是这样失败的（现场：PID 5600 的 `browser.lock`/`job.lock` 残留）。
- ④ **修法不是绕过守卫，是让删除次数归零**：① 传输锁改用 **OS 级咨询锁**（`msvcrt.locking` / `fcntl.flock`）——进程退出时由系统自动释放，**结构上不可能留下死锁**，且零删除；② `pending-command.json` **不再删除**，下一条命令直接覆盖（它的作用是「上一条操作是否已结算」的闸门，不删也能保持该语义：结算成功→放行，结算不了→继续拦）；③ 文件锁 `Lock` 增加**死进程锁自动回收**：读 PID → `process_alive` 为真则仍拒绝（活锁绝不抢占），为假则**用改名（原子、不是删除）接管**，旧文件留死 PID 下次照旧回收；④ `Lock.__exit__` 的 unlink 失败**不再致命**。守卫的计数是「每次工具调用」级别，所以同一轮里 npm test＋pytest 连跑也会被 pytest 自己的临时目录清理顶到 55 → 与本项目代码无关。
- ⑤ **真跑结果（`--apply`，一次成功，43 秒，未被守卫打断）**：只读预览先确认 `生产企业名称`（text，current 空）与 `保质期`（measure，number 空、unit 预选「天」）**均可写**；填写后平台必填进度 **50% → 100%**；`fields.json` 读回 `生产企业名称=明丞生物科技有限公司`、`保质期=12个月`（number=12 / unit=个月）；`submission.json` = `accepted / success=true / rejected=false / errors=null`；页面出现过平台原文**「商品提交成功」**。任务落 `stage=saved`、`submission_status=accepted`、`verified_by_readback=true`。
- ⑥ **平台侧独立复核（不靠自己的任务文件）**：商品已**不在草稿箱**（`product_id_not_in_draft`）→ 确实提交了；商品管理页状态分类 tab 的 id 是 `rc-tabs-0-tab-*`（`all/onSale/sellOut/offline/forbidden/releaseRecord_in_progress/releaseRecord_fail/releaseRecord_success`），逐个点开核对：**「审核通过」分类里有它 —— 送审时间 2026/11/12 16:40:39、通过时间 16:41:03**；「审核驳回」里是**另一件 10/28 的商品**（低价SKU作弊），不是它。
- ⑦ **当前状态与口径**：商品行显示「**已下架**」，点「查看原因」＝「**商家自主下架**」，行内操作有「**上架**」。这与本项目其它两件（`3853454064050373417`、`3848315275342643596`）**完全同款**：审核通过时间 == 下架时间 == 商家自主下架。所以「发布商品」这条路径的终态是「**审核通过但未上架**」，**不是**售卖中。⚠️ 别把「已下架」读成「被平台驳回」——「查看原因」给的就是「商家自主下架」，审核驳回是另一个分类、另一件商品。
- ⑧ **一条必须说清的事实提示**：用户授权的 `生产企业名称=明丞生物科技有限公司` 是**1688 上家（供应商）名**，不是核实过的生产方。若该上家是贸易商，抖店审核阶段可能要求改成实际生产方——本次审核已通过，但**上架前值得人工确认**。这次是按用户明确指示照写的。
- **验证**：717 Python（191.97s，新增 5 项锁回归）＋ 108 JS（新增 7 个 measure 用例，`tests/dom-measure.test.cjs`）。新增 `tests/test_locks.py`：死锁自动回收／活锁绝不抢占／锁内容异常不删／**释放被拦（SystemExit）不打断流程且下次可恢复**／咨询锁互斥且零删除／**连续 5 条浏览器命令零删除**。
- **过程中被 Ego 打断的两件事（都按文档在原空间内恢复，没换空间）**：① Ego 任务空间 ended（`ownership: user`）→ 用户已明确「接手」，按文档 `claimTaskSpace(9)` 接管原空间；② 空间里 p3（编辑页）渲染进程卡死、`info()` CDP 超时且 `page.close()` 关不掉 → 用 `Target.getTargets` 找到 targetId 后 `Target.closeTarget` 在浏览器层强制关闭，再把死页从 runtime 的路由表里摘掉让它另开新页。**没有新建任务空间**。

### T-20261112-010 · 194-76 · 审核状态读取路径 / 机会商品落地页契约 / 复制历史全量采证（无商品写入）

- 状态：**done**。用户「登陆了你接手吧」→ 接手上一轮被登录卡住的三项实抓，全部做完并落进代码。全程**只读**：没有创建/修改/删除任何商品（点「立即铺货」后回查抖店草稿箱，仍是原来那 1 件）。
- ① **审核状态的权威读法找到了**：抖店草稿箱是**独立页** `https://fxg.jinritemai.com/ffa/g/draft`，**不是**商品管理页的 tab（tab 只有 全部/售卖中/已售罄/已下架/已封禁/审核中/审核驳回/审核通过；页面副标题里的「草稿箱」只是文案）。入口是 tab 条右侧一组**文字链接** `编辑记录 / 草稿箱 / 回收站`（`span.style_textLinkNew__ziNsA`，在视口外，要先滚动才点得到）。按 ID 过滤的正确参数是 **`product_id`**（T-008 当年用 `searchText`，所以永远「共 0 条」——是查询方式错了，不是商品不存在）。**两页互斥**：已提交商品只在商品管理页（状态词售卖中/已下架/审核驳回/审核中），草稿商品只在草稿箱（状态词「待提交」）。
- ② **跨系统词汇对照（6 个商品实测）**：妙手「审核不通过」＝抖店「审核驳回」；妙手「上架中」＝抖店「售卖中」；妙手「未提审」＝抖店「待提交」。落地为 `DropshipPages.read_target_review_status()`（先商品管理页、后草稿箱）+ 只读 CLI `dropship product-status --product-id <ID>`，并接进 `verify_target_readback`：`platform_review_status` 命中就进 `verified_aspects`，两页都查不到就如实写「无法确认审核状态」——**不再写成「未提审」**（那是妙手侧用词，含义是「从没提交过审核」，与「商品不存在」「已删除」都不是一回事）。上一轮那句「需到商品列表页人工确认」是事实但做错了动作，现在自动做。
- ③ 🔴 **机会商品「立即铺货」的旧结论被推翻**：上一轮写「这条路径不能独立证明商品身份，卡片上没有 1688 offer ID」——**卡片层确实没有，但点击之后有**，两条独立通道：① DOM：点「立即铺货」弹出**同页抽屉**（URL 不变），抽屉里来源商品行带 `http://detail.1688.com/offer/<ID>.html`；② 网络：前端提交 `POST /api/v2/move/batch/fetchDetailUrlInfo`，请求体 `detailUrls=<同一 offer 链接>&copyType=ddClue&clickType=copyProduct`，响应 `productList[<ID>]` 带 `source:1688`、标题、图片、库存；同批还有 `dsCenterUserReviewStat` 的 `copyType=ddClue`。所以机会路径的来源身份是**精确的 offer ID**，不必靠标题去 1688 人工检索。旧实现一直失败的真因是**时序**：它在 `.click()` 后同步检查「下一步: 开始复制」，而抽屉是异步渲染的（实测「下一步」约 2.5s、offer 链接约 4.3s 才出现）→ 必然报 `click_result_not_confirmed`。现改为轮询等待（最多 40×250ms），并新增 `read_opportunity_source_identity()`（只读已开的抽屉）。抽屉开了却拿不到 offer 链接时返回 `layout_changed / offer_identity_not_found`，**不返回 ok**。
- ④ **复制历史全量采证**：这页是 vue-recycle-scroller 虚拟滚动 + 分页器（每页 20，共 3 页），一次只挂载 19~20 行 DOM —— **读一屏就是 20/58**。滚动容器是 `div.content-main`（不是 window），且虚拟列表只在滚动**过程中**换行，一次性滚到底会漏中间段。正确采法＝点 `.el-pager > li:nth-child(N)` 翻页 → 每页从 0 起按 **150px 步长**细滚并逐步累计 → 回顶补一次；去重键用「源ID+商品ID+时间」。落地为 `collect_history_rows_all_pages()` + 只读 CLI `dropship history-dump`，实测 **`共 58 条` → collected=58、complete=true**。
- ⑤ 🔴 **行解析器四处真实缺陷修正**（每条都有真实反例）：类目正则 `([^\n\r]+)` 在**单行折叠**形态下会把整行吞成类目；供应商只认「名称（店铺名）」，58 条里有 **8 条是纯名称**（`瑞安市激濠五金商行`、`孕产批发`…）被丢；源ID 只认 `源ID：`，漏了 `翻新复制` 行的 `新源ID：`；状态词全表扫，妙手侧「审核通过」与抖店侧「审核通过」混在一起，统计出「未提审+审核通过+已下架」这种三词组合。现按**商品ID 的位置**分成 `platform_states` / `platform_audit_state` / `miaoshou_audit_state`，多行与单行两种形态解析结果必须一致（已有断言）。
- **全量 58 条的真实分布**：类目 47 个（前三：收纳筐/收纳篮 3、厨房储物架 3、挂钩/粘钩 3）；复制类型 1688分销 58 / 翻新复制 1；抖店商品状态 已下架 30 / 上架中 14 / 草稿箱 1 / **无状态列 14**；抖店审核状态 审核通过 23 / 未提审 21 / 审核不通过 1 / **无 14**；妙手侧审核 审核通过 34 / 无 25；失败原因只有 1 条（即那件缺保质期/生产企业名称的）。⚠️ **14 条「无状态列」说明：缺失就是缺失，不能拿妙手侧状态缺失反推抖店侧状态**（那 14 件在抖店商品管理页里其实是有状态的）。
- **验证**：712 Python（新增 14 项；198s）＋ 101 JS ＋ **38/38 Node 真跑**（新增 9 个用例：商品管理页状态、草稿箱状态、两页各自的 wrong_page、同一 ID 两行判结构变化、机会点击拿到 offer ID、无 offer 身份不许算成功、抽屉来源身份读/读不到、虚拟滚动全量采集）。
- 文档：`docs/dropship-page-contracts.md`（第十三轮实抓）、`docs/dropship-policy.md`（⑤~⑧ 四条策略）。
- **本轮仍需人工的一件事**：商品 `3853482303460343870` 在抖店草稿箱是「待提交」，缺**保质期 / 生产企业名称**（类目 `家清纸品>除臭用品>空气清新/净化/芳香剂` 的必填项）。人工补值后提审即可。供应商名 `明丞生物科技有限公司` 只是参考线索，**不能照抄**当「生产企业名称」。

### T-20261112-009 · 194-76 · 掉线闸门 / 规格名数量标记 / 人工待办原因分类（无商品写入）

- 状态：**done（代码与只读能力全部落地并验证）**，但**有三项浏览器工作被登录卡住**，见「本轮被人工卡住的一件事」。
- 用户指令「除此之外」「继续」→ 先盘点当前代码与真实页面证据，再定下一批可自动推进的事项。
- 🔴 **开局就撞上真故障**：浏览器会话已过期，抖店与妙手**都跳到** `https://fxg.jinritemai.com/login/common?...`。实抓三个入口（妙手机会页/妙手历史页/抖店商品列表）全部落登录页，正文含只有登录页才有的「收不到验证码」「手机号停用或忘记」。**掉线只能由人重新登录**，程序不能代登录。
- ① **会话掉线闸门**（新增）：`DropshipPages.check_session()` 判据＝URL 路径以 `/login` 开头 **或** 正文含登录页专属文案，且域名属于抖店/服务市场。`_advance` / `_stage_settings` / `_stage_copy` / `_readback_only` 在每个导航后先查，掉线立刻抛 `dropship_login_required` 并说明「请人工重新登录，程序不会代登录，也不会在登录页上重放写操作」。以前掉线只会在几分钟后报「当前页面不是预期的XX页」，**根因被埋**。新增只读自检 `dropship session-check`（`--navigate` 可先进妙手页再查）。
- ② **规格名从「永远未验证」变成可判定**（`_check_spec_identity`）：旧判据是「规格名集合相等」，妙手两次真实铺货都改写了展示名 → 这条在真实页面上几乎从不成立，长期挂在 `unverified_aspects` 当噪音。改成问可判定的问题：**来源规格里的数量标记还在不在官方规格名里**。真实样本「4个装」→「极氪车门限位器-4个装」、「生物酶除臭剂【2500ml】送喷壶」→「2500ml（生物酶除臭剂）」，标记 `4个装`/`2500ml` 都保留 → `matched` 进 `verified_aspects`；无数量标记（如「红色」）如实报 `partial` 无法核对；标记对不上报 `mismatch`。后两种**不阻断** `copy_confirmed`（定价公式才是强证据）。
- ③ **类目白名单不按关键词扩**（实测反例）：队列里两件同样带「免打孔/壁挂/吸盘」的商品，缺的属性完全不同——「浴室免打孔不锈钢吹风筒收纳架」缺**安装方式**，「轻奢风浴室吸盘置物架…免打孔壁挂塑料」缺**尺寸**（安装方式反而被填上了）。说明**属性集合由抖店类目决定**，铺货前拿不到最终类目 → 结论写进 `OBSERVED_MISSING_ATTRIBUTES` 只作人工分诊参考，**不用于自动推断或拦截**。这轮没有扩白名单，是**有证据地不扩**。
- ④ **复制历史行里三个采到却没用的字段现在用上了**：真实行文含 `发布类目：家清纸品>除臭用品>空气清新/净化/芳香剂`（完整类目路径）、渠道行下一行的 `明丞生物科技有限公司（明丞生物科技有限公司）`（来源供应商/店铺）、状态词 `草稿箱`/`未提审`。`parse_history_row_facts` 解析后进人工补值清单：类目直接可读，供应商名**只作参考线索**（抖店要的是「生产企业名称」，供应商可能是贸易商，不能照抄）。
- ⑤ **人工待办报告加原因分类**：43 件 blocked 的真实分布＝重新基线 14 / 必填属性缺失 8 / 图片槽位不足 6 / 视觉质量 5 / 草稿或驳回 4 / 待真实参数 2 / 商家编码不完整 2 / 商品已删除 1 / 详情源冲突 1，并标注该谁处理（`machine_retry` 4 件可程序重跑，其余只能人工）。属性观测统计：安装方式 6、尺寸 3、硬度 3、适配基面类型 2、承重 1、材质 1、适用年龄 1、适用作物生长阶段 1。🔴 **口径修正**：这份报告旧版是 23 项，其中 5 项是「（原文未列出属性名…）」这种**占位名**，其实不是属性缺失（`doudian_draft_or_rejected` 的 `missing_fields=[]` 等）；现在只列**真能解析出属性名**的，实际 **18 项**。少的那 5 项不是漏了，是本来就该去掉。
- 🔴 **Node 验证器第二次抓到转义坑**：新写的登录态判定用了正则 `/\\/login(...)/`，Python 源码里两个反斜杠、浏览器拿到一个（合法），但 `tests/verify_adapter_js.py` 取的是**源码原文**，Node 看到两个 → `Invalid regular expression flags`，整段 JS 语法错误。已改成**零反斜杠**写法（`pathname.startsWith('/login')` ＋ 登录页专属文案）。教训固化进契约文档：**适配器里的 JS 不要依赖 Python 字符串的转义，含反斜杠一律不写**。
- **本轮被人工卡住的一件事**：浏览器会话过期 → **机会商品「立即铺货」落地页契约、抖店商品列表审核状态读取路径、复制历史全量滚动采证**这三项无法实抓。已确认它们都只需重新登录后即可继续，代码侧不需要先改。🔴 **这三项已在 T-20261112-010 全部做完**（登录恢复后），本块的三项不再是遗留。
- **验证**：698 Python（189.87s，新增 10 项）＋ 101 JS ＋ 29/29 Node 真跑。提交见本块下方。文档：`docs/dropship-page-contracts.md`（第十二轮）、`docs/dropship-policy.md`（三条被实测推翻/加固的策略）。skill 三处同步，哈希 `f435244a…`。

### T-20261112-008 · 194-76 · 选品候选 / skill 编排 / 人工待办汇总（只读，无商品写入）

- 状态：**done**。用户「4 5 6 7 8 不需要人工的你继续推进，有问题问codex」→ 落地；**按授权就 skill 编排设计派了一次 Codex 只读咨询**（`work/optimizer-20261111/codex-skill-design-out.md`）。本轮**没有创建/修改/删除任何商品**。
- **① 选品候选**：实抓 `/selection/opportunity_product` 确认它就是**抖音官方机会商品页**（官方上新扶持/豆包商机品/推荐理由热度高·成交增速快·平台缺货），30 张卡片有 `a.title` / `.price-number` / `.tag-text` /「支持密文」/「商机：xxx」/ `[data-custom-id]`。新增只读适配器 `read_opportunity_candidates` + CLI `dropship candidates`，默认只留同时「支持密文+一件代发」。真跑读出 5 条候选。🔴 **卡片没有 1688 offer ID，只有妙手内部 UUID**，返回值固定带 `identity_note` 声明「不能直接铺、需以标题检索并人工核实同一商品」。「推荐理由」是页面筛选项不是逐卡字段，没有编造成候选属性。
- **② skill 编排层**：Codex 只读咨询建议**新建** `dropship-workflow`（三个既有 skill 分别管「改版现有商品 / 批量图文 / 妙手手工编辑」，铺货是「从来源创建」，塞进去会混淆授权边界）。已落盘 `skills/dropship-workflow/SKILL.md`，含适用范围、选品、价格确认（提醒 300% vs 3 倍差 100 倍）、阶段语义、失败关闭、人工确认点、禁止事项；**不写选择器/DOM/内部字段**（C 方案抽象边界）。同步到仓库 / `~/.workbuddy/skills/` / `~/.codex/skills/` **三处哈希一致** `4afc4b39…`，既有三份 skill 未动。顺带修了 CLI 里过时的 help（原写「写配置与复制尚未接入」）。
- **③ 两条线打通**：`build_manual_queue_report` + CLI `dropship manual-queue`，把铺货任务的 `manual-attributes.json` 与 `batch.sqlite3` 里因属性缺失 blocked 的商品汇成一张**只读**待补值表。真跑：默认 23 项全来自队列；带临时 `--data-root` 时 25 项（23 队列 + 2 铺货：3853482303460343870 的保质期/生产企业名称）。不改队列状态、不解锁、不写页面、不推断值。
- **④ 口径修正与代码清理**：`navigate_source` 曾被重复定义 3 次，已清为 1 份；HANDOFF 抬头同步到 2026-11-12 / workbuddy；**更正上一轮不准确说法**——队列 61 件＝18 verified/43 blocked（实读 `batch.sqlite3`），其中明确 `required_attributes_missing` 只有 **8 件**，其余是重新基线 14、图片槽位、视觉质量、草稿/驳回预检、商品已删除等，不可笼统归为缺属性。
- 🔴 **三项有证据地不做**（`docs/dropship-candidates-and-orchestration.md`）：①**审核状态读取** — `ffa/g/list` 确有状态词与商品ID搜索框，但填入 ID 查询返回「共 0 条」、草稿箱 tab 精确定位失败，路径未证明可用，**不写适配器**，`unverified_aspects` 那条保持；②**规格名改写规则** — 只有 1 个对照样本，不归纳，继续用价格排序对应（3.48 运费差已验证）；③**类目白名单扩展** — 本轮无新失败观测，不凭类目名猜必填属性。
- **验证**：688 Python（191.67s，新增 3 项）+ 101 JS + 27/27 Node。提交 `050e30a`。文档 `docs/dropship-candidates-and-orchestration.md`。

### T-20261112-007 · 194-76 · 按事实推断落地：类目预检 / 补值清单 / copy_confirmed

- 状态：**done**。Agent workbuddy，2026-11-12 凌晨。用户「你根据事实推断呢」→ 我给出五条推断 → 用户「可以你加吧」→ 落地。未调用 Codex。
- **核心判断**：端到端跑通后，剩下的阻塞**不是浏览器自动化**，是三个设计错位。所以本轮**一行页面选择器都没改**，改策略层。
- **① 类目预检**（`src/doudian_auto/dropship_policy.py`）：`KNOWN_CATEGORY_ATTRIBUTES` 记实测类目→必填属性（当前 `空气清新/净化/芳香剂` → 保质期/生产企业名称）；`RISK_KEYWORDS` 标题预警但 `basis` 明确标 `keyword_heuristic`（铺货前拿不到抖店最终类目，**只是预警不是证据**）。`_stage_copy` 最前面 `require_precheck_allowed` 拦截高风险，除非显式 `--allow-risk`。**命中时不创建商品**，不往草稿箱堆垃圾。CLI 新增 `--source-title/--category/--allow-risk`。
- **② 人工补值清单**：从复制历史行「保质期,生产企业名称」未填写解析属性名，`build_manual_attribute_list` 写 `manual-attributes.json`，**值一律 null、来源标「人工填写」**，不替人猜。`_readback_only` 发现新增行时自动产出并附进结果。真实产物已生成在 `ds-final` 任务目录（2 条）。
- **③ 终态改名 `verified` → `copy_confirmed`**：旧终态要的「SKU 总数」「审核状态」在官方编辑页**结构上不存在**（不是没抓到），规格名还常被妙手改写 → 永远不可达。新终态只声明能证明的，并新增**可自动判定的强证据**：每个 SKU 的 `售价 − (源价×倍数+加价)` 差额相同且非负（=运费）。规格名按**价格排序做位置对应**，不按名字匹配。真实数据 25.8→85.88 / 43.8→139.88，差额都是 **3.48**。报告分 `verified_aspects`(4) / `unverified_aspects`(3)，后者如实交人工、不阻断。
- **真跑验证**：
  - 旧任务 `dropship-922368518409-eea919c37defc94b` 重跑 apply → **`copy_confirmed`**，运费 3.48，4 条已验证 / 3 条未验证（SKU总数、审核状态、规格名改写）
  - 高风险标题 prepare → `risk: high / basis: keyword_heuristic / action: block`；apply → **`dropship_category_risk`，未点复制、未创建商品**
  - 真实历史行生成 `manual-attributes.json`：保质期、生产企业名称，值均为 null
- **兼容**：`WRITE_FORBIDDEN_STAGES` 与 `record_copy_observation` 仍接受旧 `verified`，历史任务不失效；终态不可回退。
- **边界**：类目白名单目前只有一条实测类目 + 关键词兜底，扩展应基于新观测不要猜；`copy_confirmed` **不表示可售/已审核/已上架**，只表示「复制产生了这个商品且定价符合公式」。
- 文档 `docs/dropship-policy.md`。**验证**：685 Python（189.36s，新增 12 项）+ 101 JS + 26/26 Node。提交 `06b924d`。

### T-20261112-006 · 194-76 · 铺货端到端闭环真跑通（解锁自动复制）

- 状态：**done**。Agent workbuddy，2026-11-12 凌晨。**未调用 Codex**（用户要求自己干到底）。
- **🔴 解锁关键**：复制历史页 `input[name="sourceItemId"]` + 「查询」按来源筛选。不筛选时「共 59 条」/虚拟滚动只挂 8 行，基线无法证明完整；筛选后 `共 0 条` 或 `共 1 条`，判据「筛选值==本来源 且 共N条==匹配行数」才承认 `baseline_complete`。`read_history_product_id` 也要求筛选态并用 `baseline_keys` 排除旧行，只认新增行。
- **完整闭环真实跑通**：`prepared → settings_verified → unknown → copied → verification_pending`。
  - 任务 `dropship-922368518409-eea919c37defc94b`（酒店生物酶除味剂，1688 `922368518409`，店外新品：历史筛选共 0 条）
  - `apply #1`：写配置→重新进页独立读回→`settings_verified`（pricePercent 300/300/300、放入仓库）
  - `apply #2`：读来源规格（2500ml ¥25.8 / 5000ml ¥43.8）→筛选历史→贴链接→抓取（成功1/跳过0）→落复制意图→**真点「下一步: 开始复制」**
  - `apply #3`：筛选历史、基线排除→`copied`，新商品 **3853482303460343870**，类目「家清纸品>除臭用品>空气清新/净化/芳香剂」
  - `apply #4`：官方页读回 SKU `85.88 / 139.88`（=源价×3+5+运费3.48）、`price_progress 100`，`verification_pending`
- **停在 verification_pending 是正确结果**，reason 如实列出三条：页面无独立 SKU 总数、妙手改写规格名（「生物酶除臭剂【2500ml】送喷壶」→「2500ml（生物酶除臭剂）」）、编辑页无商品审核状态。不假装 verified。
- 🔴 **真实业务结果：商品进了草稿箱，不是仓库。** 复制历史原文「『保质期,生产企业名称』未填写，导致复制失败，系统自动放至草稿箱 / 草稿箱 · 未提审」。搬家配置虽设「放入仓库」，但抖店类目必填属性缺失时妙手按配置自动放草稿箱。**抖店类目特有属性源头没有，只能人工补**——与本轮之前 9 件缺属性商品的结论一致。
- **本轮新增 4 个真跑才暴露的页面事实**（全部已修）：①抓取成功且跳过为 0 时页面**隐藏「跳过」计数器**，只显示「成功：1」，原轮询要求两计数齐全导致永远超时、真没点成复制；②`_readback_only` 进官方编辑页后没等渲染就读 SKU 得到 0 行被误报 `layout_changed`；③草稿箱 SKU 行有规格价文本 `￥85.88/2.5L`，价格仍须读 `input.value`；④`navigate_official` 后需等十几秒。
- 完整报告 `work/optimizer-20261111/FULL-LOOP-RESULT.md`；十一轮实抓契约 `docs/dropship-page-contracts.md`。
- **遗留（非程序缺陷）**：商品 `3853482303460343870` 需人工补「保质期 / 生产企业名称」后提审；妙手改写规格名，若要让「规格名一致」成为可自动通过判据需先实抓改写规则或改用「SKU 数量+价格公式」核对；审核状态需到抖店商品列表页另取。
- **验证**：678 Python（192.02s）+ 101 JS + 26/26 Node 真跑。提交 `85d4b15` + `41fe57d`，已 push。

### T-20261111-005 · 194-76 · 铺货程序化：四轮 Codex 复核 + 编排层接通

- 状态：**done（程序化 v1，端到端复制动作未真跑）**。Agent workbuddy，2026-11-11 深夜～11-12 凌晨。
- **Codex 四轮复核**（`work/optimizer-20261111/codex-review-v{1..4}-out.md`）：一轮 2🔴6🟠、二轮 3🔴2🟠、三轮 5🔴、四轮 2🔴3🟠1🟡。每轮「Codex 出结论 → 我审查 → 修 → 落盘 → 真跑验证」。
- **已落地**：`dropship.py` 任务层（价格试算/配置审计/写入闸门/unknown 不重试/终态不回退/复制意图与历史基线/核验）、`dropship_pages.py` 页面适配层（10 个方法，单次 evaluate 完成「重识别→唯一校验→执行→即时读回」）、`_advance` 编排层、CLI `dropship prepare/apply/verify`、`tests/verify_adapter_js.py`（19 个 Node 真跑用例）。
- 🔴 **两个只有真跑才暴露的 bug**：①`_stage_settings` 把 multiplier=3 直接写进页面 `pricePercent`（页面是百分比应为 300），**曾把妙手共享配置改成 3%**，已改回并独立读回确认 `300/+5/放入仓库`；②抓取是异步的，读一次计数器拿到 null 被误判失败，改为有界轮询。均修于 `621df75`。
- 🔴 **验证器的根本缺陷**：Node stub 自造了 `tr` 行，与真实页面自洽通过；实抓发现复制历史是 `vue-recycle-scroller`，行容器是 `div.pro-table-custom-body-row`，`tr` 里只有日历残留 → 适配器**在真实页面永远返回 0 行**。已把 stub 换成实抓抄录的真实 cell 文本。教训：**stub 必须来自实抓**。
- 🔴 **页面契约九轮实抓**（`docs/dropship-page-contracts.md`）：结果页只有「跳过/成功」两计数器，**没有独立失败计数**；官方编辑页**没有商品审核状态**（「已上架」是 SKU 角标，「上架/下架」是表单选项）；官方页 `tr` 是真数据行、历史页 `tr` 是日历；1688 来源 SKU 在 `div.module-od-sku-selection`（两个 `item-price-stock`，第一个是价、第二个是库存）；42 条存盘源链接**全是 http**。
- **预期 SKU 循环依赖的解法**：复制前官方页还没有商品，所以预期来自 **1688 来源页规格**（实测 4个装¥6 / 1个装¥2），核验只比**规格名集合**——售价含运费尾数，与批发价本就不等（6→27.48）。
- **真实页面跑通**：`prepare`（http→https 规范化）、`apply` 第一阶段（写配置→重新进页独立读回→`settings_verified`，audit 300/300/300）、`apply` 第二阶段（读来源SKU→采基线→贴链接→抓取→闸门）。第二次 apply 正确被拦：「成功 0 / 跳过 1，未点复制」——该商品此前已铺过，**没有重复铺货**。
- **未跑**：点「下一步: 开始复制」→ 读新增历史行 → 推进 copied → 官方页核验。原因：需要一个**店外新品**，而 1688 搜索页串页/反爬拿不到稳定候选；且这一步会真的创建商品，不该在四轮复核结论出来前硬跑。
- **🔴 四轮复核结论：当前版本不能自动点复制，这是设计上的诚实状态。** 实抓发现复制历史页明写「**共 59 条**」，而虚拟滚动 DOM 只挂载 **8 行**，51 条未渲染——本来源的旧记录可能藏在里面，复制后会被误认成「本次新增」。已落地 `baseline_complete` 判据（total_records / rendered_rows），编排层遇到不完整直接抛 `dropship_baseline_incomplete` 拒绝复制。**要解锁必须实抓「来源ID 筛选框」让本来源行全部进视口**，没证据前不猜选择器。
- 四轮另修：`_readback_only` 现在真的调用 `verify_target_readback`（之前 copied 永远无法到 verified）；官方编辑页读不到审核状态是已知事实，改为列一条待核验原因停在 `verification_pending`，不抛错也不假装通过；unknown 只能跟随已落盘复制意图；抓取轮询绑定页面身份并显式 `timed_out`；来源 URL 改在 Python 侧解析校验。
- **验证**：674 Python（179.94s）+ 101 JS + 19/19 适配器 Node 真跑。提交 `84c7dfb`→`3c0df2f`→`35555c5`→`621df75`→`9612acf`（含 docs `8a0790e`/`e00796c`/`c7554bb`/`ad4da09`/`e821925`），已 push。

### T-20261111-004 · 194-76 · 机会商品铺货闭环成功 + Codex 定集成方案

- 状态：**done（单件闭环）**。商品 `3853454064050373417`（极氪001/007车门限位器）已铺进**仓库**，`已成功复制`、待审核、已下架。Agent workbuddy，2026-11-11 22:21。
- **流程**：妙手搬家配置（价格 ×300%+5、放入仓库、库存跟来源）→ 机会商品页筛「一件代发」+「支持抖音密文」→ 卡片「立即铺货」→「下一步: 开始复制」→ 妙手/抖店双端核验。完整记录 `work/optimizer-20261111/DROPSHIP-RESULT.md`。
- **价格实读核对**：源2→售15.48、源6→售27.48（=源×3+5+不包邮运费4.48）。库存跟来源（源头就是888888占位）。
- 🔴 **误判教训**：SKU 行 innerText 的「888888」是**库存显示值**不是价格，价格必须读 `input.value`。我一度误报价格异常。
- **Codex 结论：选 C**（程序提供原子能力 + skill 负责编排）。三层：铺货任务层（持久化 source/offer/配置快照/目标商品ID）/ 页面适配层（每页窄接口，返回结构化观测）/ 流程编排层（阶段迁移+人工门槛）。**页面漂移对策=页面契约+失败关闭**：每次动作一次 evaluate 完成「重识别→唯一性校验→操作→即时读回」，不唯一就停止不扩大匹配。
- **初版边界（Codex 明确）**：只做单件、价格公式执行前展示源价/公式/最终价由人确认、只允许「放入仓库」（自动立即上架排除在外）、审核与消费者端只读报告不推断、异常商品停止交人工。
- **需新增**：独立铺货任务状态机（prepared→settings_verified→copied→warehouse_created→verified）、offer 级占用/去重、搬家配置前后值审计与恢复、新商品期望值清单（标题/类目/价格/库存/主图/详情/SKU）。
- **复用**：browser/job 锁（只清死进程锁）、unknown 写入结果禁止自动重试、错误保留现场、双端读回。
- 报告全文 `work/optimizer-20261111/codex-dropship-review.md`。**铺货程序化尚未实现，此为方案评审。**

### T-20261111-003 · 194-76 · 9件缺属性源头核查

- 结论：`安装方式/尺寸/厚度/硬度/适用年龄` 是**抖店类目特有**，1688 属性区根本没有（实测5件不同类目）。代码 `source_facts.DOUYIN_ONLY`/`needs_human()`，文档 `docs/source-attribute-limits.md`。两陷阱：件重尺是包装尺寸非商品尺寸；标题「免打孔」≠选项值。
- 🔴 **发现并隔离1件已删除商品** `3848317525922283791`（抖店返回「商品不存在或已彻底删除」）→ `quarantine_product`。**队列会失真，需定期核对商品是否还存在。**
- 2件源商品已下架；详情图非参数来源。资产：42件源链接、6件源参数、7件真实选项集。615 Python/101 JS。`ab6cab0`+`7796abb`。

### T-20261111-002 · 194-76 · 商品50属性补全，已提交审核

- 商品 `3848315275342643596` 三项属性已写入，`publish_state: pending`（审核中）。**纠正 T-008「平台拒绝发布」的误判**：那5项是蓝色info未来规则，程序当error所以没点发布；实跑被接受，那5项从未拦发布。今日「失败」真因是「商品信息审核中，不可编辑」（操作ID 20261111164420C51C8F2F449DDBE5FADA）。写 安装方式=免打孔式/是否进口=否/型号=吸盘毛巾架，均1688源证据。613 Python/101 JS。`3019cb5`。

### T-20261110-009 · 194-76 · Codex实跑：属性发布及双端读回通过

- 状态：review（属性阶段完成，整套换图/上架未验收）；Agent codex-live-one，2026-11-10→11。用户完成授权后接回原Space20，销霁百货商品41/3848316465015030183依据原标题及20个贴片款SKU补安装方式=免打孔式。
- 修复3个实页缺陷：SKU重载后详情预览不挂载；蓝色info被当成表单错误；CDN地址轮换被当成换图。新增notices、沿用有序resource_key比较、失败读回先落盘；未知/错误alert及真实图片变化仍阻断。代码49e2f24。
- 正常属性任务仅发布一次受理，submitted后恢复只读→saved/verified_by_readback；官方新页必填100%，妙手新页同属性，原标题、5主12详及全20SKU一致。status仍1下架；startSaleType 0→1按既有preserve_warehouse_v1记录，checkStatus 1→7/页面审核通过，其他保护字段匹配。
- 原队列仍44 blocked/17 verified，两件unknown及WorkBuddy50的editing未动；本轮没有换图或上架，不计入三品新上传Writer验收。22官方可读但妙手精确ID/店铺查询及单品同步后仍0条，暂不编辑。
- 正式preflight对blocked的22/41/28全部跳过，不能把live_preflight总标签当逐品实读；独立官方原读22必填100%/5主19详/4SKU、28仍缺安装方式。下一步需明确正式恢复路由，再验收完整9图；不手改队列状态放行。
- 验证：591 Python、101 JS通过；[验收说明](docs/live-attribute-acceptance-20261110.md)，本机原证据work/codex-live-one-20261110/及~/.doudian-auto/jobs/attributes-3848316465015030183-f4eb30ca5f9b/。
- 现场已持久化RESULT及双端证据，Space20自有p1/p2/p3已finish关闭，不再续该已结束空间；其他用户页保留。Linear194-76记录及读回、代码/交接分提交并push，父任务保持in_progress。

### T-20261110-008 · 194-76 · 属性发布首次实页验收（结论已被 T-002 纠正）

- 状态：done（已被 2026-11-11 实跑取代）。商品50。此处保留仅因它是那三个缺陷的来历。
- 修3个缺陷：①**读回值带 option id**（`text(selects)` 含隐藏id，读回 `"466329 免打孔式"` 永不等于目标 → 该路径此前不可能成功）改为读 `.ecom-g-select-selection-item`；②新增 `attributes` 单品入口；③新增 `--abandon --reason`（仅页面确认目标属性为空才释放 editing 僵局）。附带修 title 分支 `UnboundLocalError`（分支内重复 import Bridge/Editor 造成局部名）。
- ⚠️ **当时结论「平台拒绝发布」是误判**：那5项蓝色 info 是未来规则提示，程序误当 error，根本没点发布。真因见 T-20261111-002。
- 证据 `work/optimizer-20261110/`。587 Python / 99 JS。
### T-20261110-006 · 194-160 · 自动入口与Ego标签修复

- 状态：done（代码及离线回归）；新属性发布路径与失效页恢复尚待指定商品/实页验收，不能冒称已线上验证。未操作浏览器或真实商品，原61件队列未改状态。
- commander/CLI：先读facts再按已有内容合并模板，格式坏则保留；默认正式preflight分批实读，--plan仅队列分类；旧记录与fresh区分，未知任务readback-only、ready走原Writer，门槛不放宽；--apply明确shop，每轮写入预算生效，未决错误停调度、动作后写检查点及最终报告。
- attribute_workflow.py：独立不可变属性任务，同browser/job锁及同商品占用检查；仅已确认的空文本/单选，完整SKU在填前/提交后采集；精确屏蔽目标属性后比较其他保护字段、标题/图片及非目标属性，先落submitting/unknown再发布一次，受理后新页核验；同资料未知只读，不同资料不能绕过占用，editing中断保留现场。
- ego_runtime.mjs：活动页及路由缓存按实时自有tabs校验；显式navigate可建新页，已关闭活动页的写动作直接失败，不转移到其他存活页、不重放写入。dom.js默认采集不变，属性任务才按唯一类目字段排除目标。
- 启动run.bat改明确选择只读/执行，不按资料文件非空擅自发布；使用说明与批量skill新增auto-commander参考，不再宣称全部卡点均非程序问题或无人值守已完成。Codex/WorkBuddy批量skill同步、结构/链接/改动文件SHA256通过。
- 验证：最终完整585 Python通过（170.34s），98 JS通过；随后报告来源标记及首次会话初始化补充31项专项通过；新会话只初始化一次，已有状态/目录不重建。覆盖资料覆盖、错误资料保留、新鲜预检、未知只读、写入预算、属性一次发布/丢响应恢复/非目标变化、失效缓存及不误写他页。证据work/auto-repair-20261110/。
- 收尾：运行修复142ae0c，交接单独提交并push origin；HANDOFF/T-ID映射及194-160回写读回。真实验收需明确单品对象和动作后进行，不重存既有verified或unknown商品。

### 项目目标与设计

本项目把抖店现有商品的标题、5 张方主图和标准详情图替换做成可恢复、可审计的本地工作流：确认店铺和商品身份、读取原始基线、准备并审查素材、逐槽上传、预览后提交，最后重开页面读回比对。默认不改类目、品牌、SKU、价格、库存等商业字段。提交受理不等于平台审核通过或消费者端生效。

设计优先保护商品身份、避免重复提交与静默覆盖。证据不足时阻断，不猜测商品属性；写入结果不确定时先只读核查。

### 当前状态（2026-11-10 核对）

- **浏览器通道**：`src/doudian_auto/bridge.py` 中 `DEFAULT_ENDPOINT='ego'`，CLI 未传 `--endpoint` 时走 Ego 原生通道。Kimi 仅通过显式本机 HTTP endpoint 兼容接入。`is_native_endpoint()` / `normalize_endpoint()` 是原生通道判定入口。
- **队列快照**：查询 `C:\Users\19431\.doudian-auto\batch.sqlite3` 的 `products` 表，共 61 件。`state`：`blocked=44`、`verified=17`。`submission_state`：`not_attempted=42`、`unknown=2`、`verified_by_readback=17`。两件 `submission_state='unknown'` 同时为 `state='blocked'`；`state='unknown'` 为 0。后续执行前重查。
- **测试商品**：`3853110071722639434`（「测试商品请勿购买-自动生成勿下单」）是 Ego 写入/发布验收的产物。**已于 2026-11-10 01:45 下架并复核**：列表行显示「已下架」、行内按钮为「上架」、列表仍计 57 件（下架不删除）。它在 01:27 建成草稿、01:36 发布提交受理、01:45 下架。**须待办**：是否删除该测试品。注：旧 HANDOFF 里「未发布未上架」是建稿当时的状态快照，已过时。
- **本轮修复**：活动标签及路由缓存已按实时自有tabs校验；导航可建立替代页，写动作丢失活动页则停止，不重放。资料文件保留、自动调度与独立属性发布见下方T-20261110-006；本轮仅离线回归，未执行线上商品写入。
- **验收边界**：旧 HANDOFF 记有 Ego 只读验收通过、测试商品写入/发布提交链路跑通；这不证明审核最终通过，也不能外推到所有商品和类目。证据索引见历史摘要。

### 关键约束：保护什么

- **状态机分层**：队列 `products.state` 是工作进度，`submission_state` 是提交结果，不能把两个字段的 `unknown` 混为一谈。批量与单品流程状态不同，迁移逻辑以 `batch.py`、`workflow.py` 为准。
- **提交 unknown 禁止重发**：超时或响应丢失时，平台可能已收到提交。重试可能造成重复发布/覆盖；代码将结果保留为 unknown 并限为只读核查，需用读回证据裁定。
- **锁**：单品流程持有共享 `browser.lock` 和任务 `job.lock`；批量写入也持有共享浏览器锁。锁防止本程序任务并发争用浏览器/商品，但不覆盖人工直接操作妙手。`unlock` 仅清理所属进程已退出的锁。
- **rebaseline**：人工外部改动会让旧基线过期。必须重新读真实商品并确认身份、图槽和内容，避免旧基线覆盖他人修改或把变化误判成任务目标；不能为解阻塞而直接改状态或盲目重建基线。
- **writer_ready 三品门槛**：正式 writer 需要至少 3 个不同商品完成规定的双端读回验收。`browser_ready` 只代表浏览器可用，不能证明写入可靠；此门槛避免从单品或只读成功外推通用写能力。
- **批量素材门槛**：目标版本要求 5 个主图槽和 4 个新详情槽；基线需 5 张主图、至少 4 张详情。代码校验槽位与哈希。其余尺寸、体积、标题规则应以 `materials.py`、`title.py` 当前实现为准，不沿用未经核验的旧数字。
- **停机条件**：店铺/商品身份不符、属性来源不足、槽位不完整、读回不匹配或提交结果未知时停止写入；提交超时先 verify，不自动重发。

### 新人阅读顺序

1. `AGENTS.md` → 本文“当前状态”和“关键约束”。
2. `git status --porcelain`，确认变更归属；阅读当前 Linear Issue 与授权范围。
3. 阅读 `skills/doudian-product-workflow/references/environment-and-facts.md`（解释器与脚本路径、事实 JSON、RAG 参数）、`docs/agent-workflow/T-ID-MAPPING.md` 及 `docs/miaoshou-reliability-20261029.md`。
4. 按任务读 `src/doudian_auto/batch.py`、`workflow.py`、`bridge.py`、`rebaseline.py` 和对应测试；追溯历史时再查归档。
5. 操作前重查 SQLite、浏览器就绪状态、素材与基线，不复用本文数字快照。

### 常用命令

命令入口由当前 CLI、`pyproject.toml`、`package.json` 核实；写入命令只在授权、预检通过后使用。

🔴 **全局参数必须放在子命令之前**（`--json`、`--endpoint`、`--version`），放后面会被当成子命令参数而报错。连接优先级：`--endpoint` > `DOUDIAN_BRIDGE_URL` > 默认 `ego`。

```bash
.venv/Scripts/python.exe -X utf8 -m pytest -q      # 约 3 分钟；2026-11-10 实测 558 passed
npm test                                            # 93 passed
doudian-auto --help
doudian-auto --json doctor                          # 不传 --endpoint 即走 Ego 原生
doudian-auto --json read --url '<编辑链接>' --shop '<店铺名>' --out before.json
doudian-auto --json prepare --assets '<素材目录>' --title '<新标题>' --url '<编辑链接>' --shop '<店铺名>'
doudian-auto --json upload '<job_dir>' --dry-run    # 只出计划
doudian-auto --json upload '<job_dir>' --apply      # 真写入页面
doudian-auto --json submit '<job_dir>' --apply
doudian-auto --json verify '<job_dir>'
```

### 全部 17 个子命令：哪些只读、哪些会写

**只读（随时可跑，不碰商品）**

| 命令 | 作用 |
|---|---|
| `doctor` | 查本地服务/扩展/安装 |
| `resolve` | 编辑链接或商品 ID 转稳定标识 |
| `products` | 读当前商品列表（只读当前页，不翻页） |
| `read` | 读编辑页快照 |
| `jobs` | 列出最近任务 |
| `status` | 检查任务与素材版本 |
| `verify` | 重读保存结果，不发布 |
| `browser` | 只读页面检查入口 |
| `title check` / `title diagnose` | 标题本地校验与诊断，不联网 |
| `batch status` / `batch preflight` | 看进度、素材前只读预检 |

**会写入（必须先预检 + 明确授权）**

| 命令 | 作用 |
|---|---|
| `prepare` | 建立可恢复任务（只落本地，不碰页面） |
| `upload --apply` | 替换标题/主图/详情，留在编辑页预览 |
| `submit --apply` | 发布已上传任务并重开核验 |
| `title apply --apply` | 只改标题并发布 |
| `batch run --apply` | 按队列串行写入妙手并双端核验 |
| `batch repair-title --apply` | 受理后标题仍旧时的单次补救 |

**恢复 / 隔离入口（出事时用，别自己造轮子）**

| 命令 | 什么时候用 |
|---|---|
| `batch quarantine` | 商品已有编辑或保存结果未知，保留原占用并按正式隔离规则处理 |
| `batch reconcile` | 导入已有操作证据并隔离，防止重复写入 |
| `batch rebaseline` | 外部改动让基线过期，需用双端完整证据核清 |
| `batch recover-prepared` | 尚未上传/保存的合格素材任务，用两轮只读证据恢复 |
| `batch recover-read` | 只读页面无响应，凭审计证明关闭一次（**仅原生 Ego**） |
| `batch resume` | 续办未提交或只读核查任务 |
| `abandon` | 人工确认页面后放弃该任务对商品的占用 |
| `unlock` | **仅**清理所属进程已退出的锁 |

🔴 恢复类命令的共性：都要求**先有证据**（两轮只读、审计证明、双端核对）。没有证据就想恢复＝绕过闸门，这是本项目最忌的操作。

## 数据与算法

- 单品流程主线：`prepared → editing → uploaded → submitting → submitted → saved`；失败与恢复分支以 `workflow.py` 为准。批量流程另有 `needs_agent / agent_claimed / ready / editing / uploaded / submitting / submitted / verified / blocked` 等状态。
- 写动作获取锁后重读持久状态。提交可能已送达但结果未知时不重试；verify/readback 负责核验。
- 批量提交前核验基线、素材哈希、目标槽位、writer 准备记录和资格；提交后重开商品页读回，匹配后才可 verified。人工改动需走受控 rebaseline。
- 本机数据根目录实测为 `C:\Users\19431\.doudian-auto`；任务素材、状态、审计证据留在本机，不提交浏览器数据、凭据或任务产物。
- 默认通道与全局参数以 `bridge.py`、`doudian-auto --help` 为准；当前默认 Ego，兼容 endpoint 仅允许本机 HTTP。

### 输出格式与退出码

- 成功：`{"ok":true,"data":{...}}`；失败：`{"ok":false,"error":{"code":"...","message":"...","waiting_human":false}}`
- 退出码：**0** 成功 / **1** 一般错误 / **3** 需用户连接或验证（别把 3 当 1 处理，那是要人去登录）
- `--json` 只写 stdout；帮助走标准 argparse 输出
- dry-run按具体命令契约：upload/submit可用--dry-run，其他命令不可机械套用。batch auto --plan不逐品预检但会检查连接；默认auto只读预检，--apply才执行对应授权动作。
- `read` / `products` 会**打开页签**但不改商品字段——别因为「开了页面」就以为要写入了

### 素材规格（`materials.py` / `jobs.py` 实测）

- 命名：`main_01`～`main_05` 各一张；`detail_01` 起连续编号 1～50 张，按数字排序
- 格式：JPEG/PNG，单张 **< 5MB**
- 尺寸：方主图**至少 600px 且必须正方形**；详情宽 **620～1290px**
- SHA256 禁止重复图片；标题 16～60 平台字符（**汉字计 2**）
- 批量目标：5 主图槽 + 4 详情槽 = 9 槽

### 任务目录与锁

- `~/.doudian-auto/jobs/<商品ID>-<内容哈希前12位>/` 存 manifest、state、before/uploaded/readback JSON 及成功截图
- manifest 绑定**绝对路径、文件哈希、商品、店铺、标题**；素材文件一改动就必须重新 `prepare`
- 每次操作串行持有 `browser.lock` 与 `job.lock`；**拿到锁后要重读状态**，防止旧进程状态导致重复发布
- 每个不可变任务用独立固定的浏览器 session（默认 Ego 原生 TaskSpace），按商品 ID 重新选取重定向后的真实编辑页

### 读回怎么算「一致」

- 发布前后比较**实际加载的保留字段**：文本/数值、checkbox/radio/switch、选择项、静态属性，以及 SKU / 3:4 图 / 白底图地址
- 图片核对要比重开后**CDN 路径及顺序**，忽略缩放查询参数；**不能只凭张数**判断一致
- 只写标题、方主图、标准详情。类目/品牌/售后必填一句变化→**立即停止**，不套用以前商品的属性
- 读回不符时保留 `submitted` 与错误证据，人工确认真实页面后处理，**不许改 state 绕过**
- 截图失败不覆盖提交事实，以新打开的保存页读回为准；消费者端生效最终由平台审核决定

### 浏览器层注意

- 默认Ego原生TaskSpace/Page；显式Kimi兼容端点走本机POST /command与GET /status。绝不自动重试可能已送达的写请求。
- 不访问 Cookie、框架内部状态或未公开业务接口
- `dom.js` 依赖实测字段：`#pg-title-input`、`attr-field-id` 的「主图」/「商品详情」、`goodsEditScrollContainer` 分区。布局变化时优先修这里，别改判据标准。
- 兼容旧素材校验脚本 `skills/.../scripts/doudian_check.py`；其 compare 读旧 `sections` 格式，CLI 读回用 `protected` 格式，**两者不能混用**

## 历史摘要

- **2026-11-10 · Linear 194-155**：Ego 默认通道只读验收、测试商品写入及发布提交链路、端点归一化独立复核完成；runtime 活动标签失效缺陷未修。证据目录：`work/ego/default-channel-check-20261110/`、`work/ego/pick-untouched-20261110/`、`work/codex-review-20261110/`（三轮外审报告）。
- **2026-11-09 · Linear 194-155 / 194-156**：Ego 默认通道切换；批量技能和商品编辑工作流文档整理。归档：`docs/handoff-history/2026-11-09-batch-skill-before-review.md`、`2026-11-09-skill-source.md`。
- **2026-10-29 至 2026-11-03 · Linear 194-76 及后续**：批量可靠性、SKU 读回、素材门槛及人工接管阶段。旧队列数字、session 和 writer 门槛快照已过期。归档：`docs/handoff-history/T-20261026-002-before-reliability.md`、`T-20261103-003-004.md`、`194-54.md`；技术说明见 `docs/miaoshou-reliability-20261029.md`。
- 其余旧任务块属于完成历史，保留于旧 HANDOFF/提交历史和上述归档，不作为当前状态依据。

## Ego 通道验收：证到了哪里

这一节单独列，因为**最容易读错**。

**Ego 默认通道已实测可用的范围**：
- 只读读回（开编辑页、认店铺、认商品、读标题/主图/详情）—— 商品 `3848322422084337743` 实测通过
- **全仓只读**（2026-11-10 实测）—— **61/61 件全部读出，0 失败**，店铺确认 61/61，详见下节
- 写入（传图、填标题、保存草稿）—— 测试商品 `3853110071722639434` 实测通过
- 发布提交受理（填写检查清零 → 发布 → 价格风控确认 → 提交成功）—— 同上，平台回「需审核通过后生效，审核周期 1-2 个工作日」

**没证到的**：
- ❌ **审核最终通过**（要等 1-2 个工作日，未观测）
- ❌ **妙手双端读回比对**（测试商品不在妙手队列，无法比对）
- ❌ **全仓写入**。不是通道问题——队伍里 17 件已 verified 不许重存、44 件 blocked 卡在属性/图槽/基线，通道切换不会补齐商品事实或证据；当前也存在运行时与调度缺陷，不能把全部阻塞都归因为缺资料。
- **Writer状态以当前execution_readiness为准**：历史三品证据与运行时就绪分别记录，不能沿用旧“未满足”快照，也不能凭文档断言实时已就绪。

### 全仓只读实测（2026-11-10）

| 项 | 值 |
|---|---|
| 队列 / 读取成功 | 61 / **61**（0 失败） |
| 店铺确认 | 61/61 |
| 主图 5 张 | 54 件（**7 件不足**：4 张 3 件、3 张 4 件） |
| 详情图 | 范围 **2–37 张**，**7 件不足 4 张** |
| 草稿态 | 0 |
| 平台驳回 | **3 件** |

**必须处理的 3 件驳回**：`3848315195902525900`（长柄沐浴刷）、`3850071781591351757`（宠物除臭喷雾）、`3850072322857894188`（行李箱轮子保护套）。驳回未处理前，任何写入都不生效。

🔴 **采集方法教训**：详情图是异步渲染的。直接用 `editor.read()` 会读到假的「详情 0 张」——实测同一件商品 `read()` 读 8 张、`wait_details()` 读 14 张。**必须用项目自带的 `editor.wait_details()`**（轮询 `detail_status` 到 `ready`/`empty`），别自己写采集循环。证据见 `work/ego/all-queue-readonly-20261110/`。

**已修**：端点判定收敛（全仓 6 处裸比较 → 统一走 `is_native_endpoint`）。Codex 三轮复核结论「可交付」。
**已离线修复，待实页回归**：本轮活动页与路由缓存都按实时自有tabs校验；只在显式navigate建立新页，失效页写动作停止，不转移或重放。见T-20261110-006的98项JS回归记录。

<!-- 核对说明（Codex 起草，WorkBuddy 核实并修正）
- Codex 核对过：HANDOFF.md、AGENTS.md、docs/handoff-history/ 清单、bridge.py、batch.py、workflow.py、ego_runtime.mjs、rebaseline.py、materials.py、title.py、pyproject.toml、package.json。
- Codex 实测：`pytest -q` → **558 passed in 173.60s**；SQLite `products` 按 state/submission_state 分组查询。
- WorkBuddy 复审修正了 4 处：
  1. 原稿带 UTF-8 BOM，已去掉（否则部分工具首个标题会失效）。
  2. 原稿把 `environment-and-facts.md` 的路径写成 docs 下，**该位置不存在**；实际在 `skills/doudian-product-workflow/references/`，已改。
  3. 原稿把测试商品列为「待人工核实 / 记录冲突」——已实测：**已下架**（行状态「已下架」、按钮「上架」、列表 57 件）。所谓冲突只是旧文档同时保留了 01:27 建稿时和 01:45 下架后两个时点的快照。
  4. 补上「全局参数必须在子命令前」这条实操坑，以及 `npm test` 实测值。
- WorkBuddy 复核通过、未改动的：队列 61 件分布（state 44/17、submission_state 42/2/17）与实测一致；`DEFAULT_ENDPOINT='ego'` 属实；`is_native_endpoint` 已全仓收敛；`prepare/upload/submit/verify/read` 参数与实际 `--help` 一致；素材规格 5 主图+4 详情=9 槽、主图≥600 方图、详情宽 620–1290、<5MB 均与 `materials.py`/`jobs.py`/`batch.py` 一致；writer_ready 三品门槛见 `batch.py:1284`。
- 待人工决定：是否删除测试商品 `3853110071722639434`（现为已下架，仍在列表计数内）。
-->

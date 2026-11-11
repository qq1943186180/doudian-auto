# 选品候选、Skill 编排与人工待办汇总

本轮推进的是「不需要人工给值」的四项：选品、skill 编排、两条线打通、文档口径。
**没有新增任何商品写入**，全部是只读能力或编排文档。

## 一、选品候选（抖音官方机会商品页）

### 实抓结论

页面 `/selection/opportunity_product` 就是**抖音官方机会商品**页，顶部有
「官方上新扶持 / 豆包商机品 / 抖店商机 / 推荐理由：热度高、成交增速快、平台缺货、
销量高」。所以选品数据其实存在，之前只是没接进程序。

实测 30 张卡片，结构：

| 字段 | 选择器 | 样例 |
|---|---|---|
| 妙手内部 UUID | `[data-custom-id]` | `69599504-36c0-481f-938f-140c2737e440` |
| 标题 | `a.title` / `.title-text-box` | 汽车倒车后视镜小圆镜… |
| 价格区间 | `.price-number` | `1.68 ~ 2.38` |
| 服务标签 | `.tag-text[]` | 一件代发 / 48小时发货 / 7天包换… |
| 支持密文 | 独立叶子文本 | `支持密文` |
| 商机词 | `.multipleEllipsis-1` 前缀「商机：」 | 奇瑞车门限位器保护套 |

`read_opportunity_candidates` 只读，默认只保留**同时**带「支持密文」和「一件代发」
的卡片，CLI 入口：

```
doudian-auto --json dropship candidates --session <会话> --limit 30
```

真跑输出 5 条候选（顶天立地架配件 / 不锈钢菜品模具 / 方程豹钛7出风口保护罩 /
特斯拉防虫网等），都带商机词、价格区间、密文与代发标签。

### 🔴 身份边界（不可绕过）

**卡片上没有任何 1688 offer ID**，只有妙手内部 UUID。因此：

- 这份清单是**候选**，不是可直接铺的链接；
- 不能独立建立来源身份，不能直接喂给 `prepare`（后者要求
  `detail.1688.com/offer/<ID>.html`）；
- 要用某个候选，必须以标题到 1688 检索出对应 offer，并**人工核实是同一个商品**。

适配器返回值里固定带 `identity_note` 说明这一点，Node 用例也断言了它。
「推荐理由」是页面顶部的**筛选项**，不是每张卡片的机会标签，所以没有当成
逐卡数据采集——不编造不存在的字段。

## 二、Skill 编排层（Codex 只读咨询后落地）

按 Codex 建议**新建** `dropship-workflow`，而不是塞进三个既有 skill：

| Skill | 职责 | 为何不作铺货入口 |
|---|---|---|
| `doudian-product-workflow` | 直接改版抖店现有商品 | 铺货是「从来源创建」，不是改版 |
| `miaoshou-auto-batch` | 持久队列批量图文优化 | 铺货是单商品，不是图文批次 |
| `miaoshou-product-workflow` | 妙手手工编辑单品 | 铺货走专用状态机和 CLI |

`skills/dropship-workflow/SKILL.md` 覆盖：适用范围与排除项、选品候选、
价格确认（含 300% vs 3 倍的换算提醒）、阶段含义、失败关闭、人工确认点、
禁止事项、只读人工待办汇总。

按 C 方案的抽象边界，**skill 里不写**页面选择器、DOM 结构、具体 URL、
manifest/state 内部字段，只依赖 CLI 输出。

四处同步且哈希一致（`4afc4b392120dfaf…`）：
仓库 `skills/`、WorkBuddy `~/.workbuddy/skills/`、Codex `~/.codex/skills/`。
既有三份 skill 三处哈希未被改动。

同时把 CLI 里过时的 help 文案改了：原来还写着「写配置与复制尚未接入」。

## 三、两条线打通（只读汇总）

`build_manual_queue_report()` / `dropship manual-queue` 把两类「等人给值」合到一张表：

- **线 A**：铺货任务目录里的 `manual-attributes.json`（新商品类目必填属性）
- **线 B**：`batch.sqlite3` 里因 `required_attributes_missing` / `missing_fields`
  /「待真实参数」而 blocked 的历史商品

真跑结果：

```
默认（DATA_ROOT）            → 23 项，全部来自批量队列
--data-root <临时任务目录>    → 25 项 = 23 队列 + 2 铺货
                              3853482303460343870 保质期
                              3853482303460343870 生产企业名称
```

**只读**：不改队列状态、不解锁任务、不写商品页面。属性值一律不推断，
清单里只有属性名和证据原文。工具会同时尝试 `DATA_ROOT/batch.sqlite3` 与
`--data-root` 下的 db，并且兼容「任务目录挂在 root/dropship/」和「直接挂在 root/」
两种布局。

### 顺带核准的口径修正

队列 61 件 = 18 verified / 43 blocked（实读 `batch.sqlite3`）。
43 件 blocked 的原因**很杂**，此前「大部分卡在抖店特有属性」的说法不准确：

- 明确 `required_attributes_missing` 的只有 **8 件**
- 其余是 `external_work_requires_rebaseline`（14）、图片槽位不足、
  视觉质量复核失败、草稿/驳回预检异常、商家编码不完整、商品已删除等

HANDOFF 抬头已补上这条真实口径，并把日期/当前执行者同步到 11-12 / workbuddy。

## 四、没做完、且有理由不硬做的三项

| 项 | 实抓结果 | 结论 |
|---|---|---|
| **审核状态读取** | 抖店 `ffa/g/list` 确有 `售卖中/已下架/审核中/审核通过/草稿箱` 等状态词，也有「商品名称/商品ID」搜索框 | 但填入商品 ID 查询后「共 0 条」，草稿箱 tab 的精确定位也失败（点到了说明文字）。**读取路径没有证明可用，因此不写适配器**；`unverified_aspects` 里那条「需到商品列表页人工确认」保持不变。下次实抓要先解决 tab 定位与查询触发时序。 |
| **规格名改写规则** | 只有 1 个对照样本（生物酶除臭剂【2500ml】送喷壶 → 2500ml（生物酶除臭剂）） | 一个样本不足以归纳规则。**不猜**，继续用价格排序做位置对应（已由 3.48 运费差验证有效）。 |
| **类目白名单扩展** | 本轮没有新的真实失败观测 | `KNOWN_CATEGORY_ATTRIBUTES` 仍是 1 条实测类目 + 关键词兜底，不凭类目名猜必填属性。 |

另外修了一个代码坏味道：`dropship_pages.py` 里 `navigate_source` 被重复定义了 3 次
（后定义覆盖前定义），已清理为 1 份。

## 验证

- 选品适配器在真实机会页读出 5 条候选；CLI `candidates` 真跑返回 3 条
- CLI `manual-queue` 真跑两种 data-root 分别得到 23 / 25 项
- 27/27 适配器 Node 真跑、73 项铺货 Python 测试、全量 Python 与 JS
- 全部能力**只读或通过 CLI 编排**，本轮没有创建、修改或删除任何商品

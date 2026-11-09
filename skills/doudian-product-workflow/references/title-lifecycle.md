# 只改标题：执行与恢复

仅适用于抖店直接适配器的 `mode=title_only`；妙手标题修改在妙手完成。代码实现不等于真实写入验收。当前未找到已归档的独立 title-only 不同标题写入验收，保留 review：先离线预览，只有用户明确授权受控标题发布任务才执行 `--apply`，并立即 verify、保存实际结果；不要为验收额外改商品。

## 命令

```powershell
doudian-auto --json title apply --url '<实际编辑链接或ID>' --shop '<店铺>' --title '<最终标题>' --facts '<事实.json>'
# 上面省略 --apply 是离线预览，不连接浏览器；事实格式见 environment-and-facts.md。
# 已有对应发布授权且预览通过后，同一命令增加 --apply。
doudian-auto --json title resume '<job_dir>'            # 预览续办计划
doudian-auto --json title resume '<job_dir>' --apply    # 原授权范围内续同一版本
doudian-auto --json verify '<job_dir>'
doudian-auto --json title abandon '<job_dir>' --reason '<核对内容与结案理由>'
```

`title abandon` **本身会写本地结案记录**，没有 `--apply` 或 dry-run；不是预览命令。它不撤销线上发布、草稿或未保存输入。仅在已核对归属和结果、明确决定结束原任务时使用。

## 状态与允许操作

| stage 与 submission_status | 允许操作 |
|---|---|
| prepared / not_submitted（含 noop） | 预览；有原基线的原任务可 resume。prepared 不占用商品 |
| editing 或 uploaded / 未提交 | 原任务 resume；或核对页面后有理由地 abandon |
| submitting / unknown | 仅 verify；禁止 resume、abandon 和新任务重发 |
| submitted / accepted | 仅 verify 为常规操作；未核验结案见下方例外 |
| rejected / accepted | 查驳回原因和已终结证据，按授权处理；可有理由地 abandon |
| rejected / unknown | 先 verify；只有 readback.json 明确驳回才允许 abandon，保留 unknown 原事实 |
| saved、abandoned | 已终结，不以 resume 再发；消费者端生效单独核查 |
| 缺失状态或不一致组合，如 editing + accepted | 停止写入并查证，不手改 state |

`submitted` 即使 accepted 也未证明内容核验成功。当前代码允许人工决定未核验结案，必须明确授权该结案决定，并使用 `title abandon ... --reason '...' --confirm-unverified`；保留未核验事实，不把这个参数当成自动恢复选项。若 submission_status=unknown，还必须满足代码要求的驳回读回证据。不能靠结案解锁第二次盲发。

## 不可变版本、基线与锁

- apply 建独立任务并记录 manifest、before.json、title_record.json。全局 browser.lock 与 job.lock 内重查状态、同商品占用；不通过换渠道或新任务绕过。
- 基线来自独立新页，不能复用带未保存输入的标签。草稿（draft_loaded）、驳回（rejected）或身份不明先处理归属；不得把脏输入当线上基线。
- resume 复用原 manifest 和原 before.json，不覆盖基线。新页必须通过相同保护字段检查；标题既非原标题也非目标标题时报 baseline_stale，查清他人改动再处理。
- 新页已是目标标题返回 title_already_current：只读退出，不再填写或发布，不证明原提交已受理。原 noop 保持 noop；人工独立核对后才决定结案。
- 从开始填写起进入 editing；发布前落盘 submitting/unknown。丢响应只运行 verify，禁止清理状态后重发。明确平台驳回/校验失败以实际非零错误及证据为准。
- verify 比较标题、保护字段及可观察图片；图片源不完整时保持 image_scope/not_verified，不能把两个空数组当成图片未改动。
- abandon 在两把锁内重读状态，记录原因、操作者、manifest 内容哈希及 before/readback 哈希，进入 abandoned。它只解除本地占用，遗留页面/草稿须按实际状态处理。

以上语义对照 `src/doudian_auto/cli.py` 和 `workflow.py`；运行时错误与状态记录优先，不以此文档允许绕过程序闸门。

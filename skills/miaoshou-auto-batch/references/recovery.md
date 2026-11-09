# 批量受控恢复与证明条件

遇到主文件恢复表对应错误时读取本文件。下列原有细节保留为程序恢复契约，不授权手改数据库、状态文件或绕过 CLI 点保存。proof 必须来自当次真实证据，不通过编造字段使校验通过。命令是否支持当前情况以 CLI 与源码校验为准。

## 未决浏览器操作与收据

`ego_operation_unsettled` means the prior browser command has no confirmed end: even a new browser observation is held until its local `pending-command.json` and `<token>.result.json` show a complete result without `mayHaveLateEffects`. Inspect those local records; do not delete the marker, switch sessions to bypass it, or replay the command. The narrow `batch recover-read` exception requires an exact current `VISIBLE_DOM(navigation_toggle, params)` request and the SDK’s `EGO_PAGE_EVALUATION_TIMED_OUT` with `executionStopped=false/mayHaveLateEffects=true`. It binds reviewer/session/space/page/product/shop/token and original request/result hashes, persists one close intent, confirms the owned quick-edit Page, closes it once and verifies every other Page remains. Only the complete close receipt settles the marker; request/result evidence and product unknown saves are retained. A lost close reply permits receipt consumption only, never another close or a replacement TaskSpace. A late result unlocks a new observation without changing a product's unknown save status. `ego_cleanup_unknown` similarly blocks a second finish or replacement space. Cleanup records explicitly describe task pages and `browser_exit_requested=false`; their presence does not prove that Ego itself exited.

## 外部工作、基线及素材保留恢复

- Before claiming old imported records, reconcile saved/verified work and unknown uploads from their evidence files. `batch reconcile` quarantines them for fresh baselines; it does not mark a whole revision verified or clear an unknown submission.

- `batch rebaseline` returns only an `external_work_requires_rebaseline` row with zero queue save attempts and no unknown submission, artifacts, mappings, baseline or live occupation to `needs_agent`. Its proof binds the same shop/product/version, fresh hashed complete dual snapshots and every original observation hash plus an explicit reviewed resolution (`no_save_attempted` or historical `verified/accepted`). It retains version and history. Unknown historical saves, missing SKU/required fields, stale/changed evidence, other queue versions and active official jobs remain blocked. Normal writer preflight repeats before any upload.

- `batch recover-prepared` only restores a blocked `official_repeat_snapshot_unstable:` task with an unchanged approved manifest/version, zero uploads/saves, no baseline/intent/preparation/readback and no active occupation. Its reviewed proof binds product/shop/version, `manifest_sha256`, and exactly two recent `observations` (each `observed_at` plus hashed `miaoshou`/`doudian` files). Both complete SKU/required-attribute/protected reads must pass, including exact image order and raw review state. It records proof history and returns `ready`; normal writer preflight still repeats before uploading. Unknown saves, failed visuals, stale/missing evidence and changed assets remain blocked; never clear them manually.

## 历史点击前失败及标题补救

- A recorded legacy `ego_target_not_unique` final-button failure can be cleared only by `restore_proven_preclick_failure`: audited runtime hash, original unique request/result hashes and arm record, one complete pre-input interval, matching submission intent, and fresh complete dual baseline snapshots are all required. Old titles or an asserted `click_issued=false` are insufficient. Transport errors and any possible dispatched input remain readback-only.

- `batch repair-title` uses the observed title-only batch page with one explicit product ID, “use new content”, “fail if too long”, no AI size repair, no timer, and “do not adjust shelf state”. It verifies the original title, target title and rendered count in the one-row preview before persisting intent and clicking the final batch button once. Hidden duplicate inputs must be excluded. Recheck all nine existing target images, detail tail, commercial fields and the warehouse-state policy; do not upload images again.

- A successful `saveTempBatchTask` response is an intermediate response and cannot establish either product success or absence of a product submission. Unknown results remain readback-only; old titles alone do not prove failure. A completed quick-form rejection with an observed request ID and HTTP response may switch once to the title-only page; bind the failure event hash and never rearm an unknown save. Keep platform rejection details without headers or credentials.

代码入口：仓库 `src/doudian_auto/batch.py`、`rebaseline.py`、`prepared_recovery.py`、`stalled_read_recovery.py`。恢复只对满足条件的原商品/原版本生效；迟到结果或关页收据不能清除未知商品保存记录。

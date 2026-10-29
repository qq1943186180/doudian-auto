---
name: miaoshou-auto-batch
description: Prepare complete title and image revisions for existing Douyin Shop warehouse products through the durable doudian-auto batch queue, with agent-generated copy/assets and program verification.
---

# 妙手批量商品优化

Use the local `doudian-auto` program for durable work tracking and asset validation. The agent handles product facts, course knowledge, title writing, image generation, and visual review. The browser executor handles one product at a time and must preserve each product's existing shelf state and commercial fields.

## Current entry points

```powershell
doudian-auto --json batch create --input <products.json> --shop <店铺名>
doudian-auto --json batch status [batch-id]
doudian-auto --json batch quarantine --product-id <商品ID> --reason <核查原因>
doudian-auto --json batch reconcile --evidence <已有操作state.json> --shop <店铺名>
doudian-auto --json agent next --owner <stable-agent-name> [--batch-id <id>]
doudian-auto --json agent heartbeat --task-id <id> --owner <stable-agent-name> --token <lease-token>
doudian-auto --json agent complete --task-id <id> --owner <stable-agent-name> --token <lease-token> --artifacts <artifact-manifest.json>
doudian-auto --json batch resume
doudian-auto --json batch run --batch-id <id>
doudian-auto --json batch run --batch-id <id> --product-id <id> --limit 1 --apply
doudian-auto --json batch run --batch-id <id> --product-id <id> --product-id <id> --product-id <id> --limit 3 --acceptance --apply
doudian-auto --json batch repair-title --product-id <id> [--apply]
```

Pass `--session <task-session>` to `batch run` or `batch resume` to keep this work in a dedicated browser tab group. Persist resumable state before closing this task's tabs at the end of each turn; leave unrelated and user-owned tabs alone.

For the native Ego channel, run `ego-browser skill` before browser work and put `--endpoint ego` before the subcommand, e.g. `doudian-auto --json --endpoint ego batch resume --apply --session <task-session>`. The program keeps one durable TaskSpace with reusable route pages, stores every command in a unique round file, and captures response events within the action round. It does not inspect profiles or borrow another task's pages. `ego_state_locked` / `ego_transport_unknown` must never trigger a replay of a save or a replacement TaskSpace. Persist the queue and recover by reading. A successful native connection is not fresh-upload/save acceptance.

Input is a JSON array or `{"products":[...]}`. Rows may use `product_id` or `productId`; `shop` may be on each row or supplied with `--shop`. Include `source_title`, confirmed product facts, actual edit links, current shelf state, image references, and readback provenance when available. `agent next` returns an immutable `target_version`; agent output must copy that exact string into its JSON manifest along with the same string `product_id`, a candidate `title`, exactly five ordered `mains` paths, and exactly four ordered `details` paths. Mismatched or missing versions cannot enter the ready queue.

`agent next` reserves one product with an expiring lease and returns its target version plus optional local course-search results. Heartbeat long preparation tasks before the lease expires. `agent complete` rejects expired leases, wrong product IDs or target versions, invalid title length, missing or duplicate images, non-square main images, and invalid image dimensions. The queue stores the artifact manifest path and its hash.

Every new image also needs the [bound visual review](references/visual-review.md): inspect the original references and all nine outputs, record visible identity/color/quantity/printing/specification evidence, and bind each check to the exact asset hash and target version. Missing review cannot enter upload. A failed slot may be regenerated once; a second failed version quarantines that product while other products continue. Reuse the other approved images. Do not change a failed record to pass without correcting its image. Original-image upload probes never count toward the user's all-new main images.

## Editing and recovery rules

- After the task enters `ready`, keep its plan immutable; a changed title or accepted asset set is a new revision. Failed candidates may be corrected within the same leased preparation task before it becomes ready.
- Before claiming old imported records, reconcile saved/verified work and unknown uploads from their evidence files. `batch reconcile` quarantines them for fresh baselines; it does not mark a whole revision verified or clear an unknown submission.
- Do not let two agents prepare the same product or more than one process write to the same browser session.
- Use page controls observed in the current session. Do not guess selectors or replay page write requests.
- Preserve the product's current on/off-shelf state. Official [product edit documentation](https://op.jinritemai.com/docs/api-docs/14/250?from=list) defines `startSaleType` as the destination after review, not current shelf state: `0` lists immediately and `1` enters the warehouse. For a confirmed warehouse product, `0→1` may preserve the requested state. Accept it only through the explicit `preserve_warehouse_v1` readback policy: both current shelf statuses are `1`, the final destination is `1`, all other fields match, and independent Doudian protected-field verification passes. Keep the raw before/after values and policy proof. Never apply this rule to listed products, missing states, or other commercial changes.
- **Current capability (2026-10-28):** the three named targets have complete dual readback for their titles, five mains, four new details, preserved tails and commercial fields; two old titles were repaired through the title-only path. The generic writer capability remains `false` while the current fresh-upload/save path awaits end-to-end acceptance. Do not treat title-only recovery as proof of fresh uploads or bypass the program's guards.
- Reuse the exact existing browser tab ID for the Miao batch route; do not select by hostname alone because the same host also contains quick-edit routes. Close only the task-owned Miao batch tab after its durable state/readback is recorded; leave unrelated tabs open.
- Before saving, persist `submitting/unknown`. A lost response permits read-only recovery only; do not click save again without evidence that the previous attempt ended unsuccessfully.
- Ignore stale cloned list rows, analytics POSTs and intermediate task responses. Read the current actionable exact-ID row and a new non-draft edit response. The list title is a cache, not a saved-content readback. After a save, allow up to three fresh title observations within the readback budget, then run all image and protected-field comparisons. Old titles or missing fields never authorize resaving.
- Verify the saved version independently in Miaoshou and Doudian. Missing or partially loaded protected fields are `not_verified`.
- Never change SKU, price, stock, category, brand, delivery, freight, after-sale settings, 3:4 images, white-background image, review status, or shelf state as part of this workflow.
- First live acceptance is limited to three explicitly named product IDs. Do not turn on general writer readiness until all three have complete, independent Miaoshou and Doudian readbacks.
- Treat `batch run --apply` as unavailable until the current writer capability is verified. The explicit three-product `--acceptance` flag narrows scope; it does not override capability guards. A browser connection or historical content readbacks alone do not verify a new upload path.
- `batch repair-title` uses the observed title-only batch page with one explicit product ID, “use new content”, “fail if too long”, no AI size repair, no timer, and “do not adjust shelf state”. It verifies the original title, target title and rendered count in the one-row preview before persisting intent and clicking the final batch button once. Hidden duplicate inputs must be excluded. Recheck all nine existing target images, detail tail, commercial fields and the warehouse-state policy; do not upload images again.
- A successful `saveTempBatchTask` response is an intermediate response and cannot establish either product success or absence of a product submission. Unknown results remain readback-only; old titles alone do not prove failure. A completed quick-form rejection with an observed request ID and HTTP response may switch once to the title-only page; bind the failure event hash and never rearm an unknown save. Keep platform rejection details without headers or credentials.

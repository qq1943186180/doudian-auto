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

Input is a JSON array or `{"products":[...]}`. Rows may use `product_id` or `productId`; `shop` may be on each row or supplied with `--shop`. Include `source_title`, confirmed product facts, actual edit links, current shelf state, image references, and readback provenance when available. `agent next` returns an immutable `target_version`; agent output must copy that exact string into its JSON manifest along with the same string `product_id`, a candidate `title`, exactly five ordered `mains` paths, and exactly four ordered `details` paths. Mismatched or missing versions cannot enter the ready queue.

`agent next` reserves one product with an expiring lease and returns its target version plus optional local course-search results. Heartbeat long preparation tasks before the lease expires. `agent complete` rejects expired leases, wrong product IDs or target versions, invalid title length, missing or duplicate images, non-square main images, and invalid image dimensions. The queue stores the artifact manifest path and its hash.

## Editing and recovery rules

- Keep each product's plan immutable; a changed title or asset set is a new revision.
- Do not let two agents prepare the same product or more than one process write to the same browser session.
- Use page controls observed in the current session. Do not guess selectors or replay page write requests.
- Before the first title or image edit, the live form must expose one readable control for the original post-review shelf mode (`startSaleType`) and show the same value as the baseline. If it is missing, ambiguous, or different, do not edit or save; leave the task resumable with a clear reason. The current quick editor has no such control, so new writes must remain blocked until that changes and is verified.
- Before saving, persist `submitting/unknown`. A lost response permits read-only recovery only; do not click save again without evidence that the previous attempt ended unsuccessfully.
- Verify the saved version independently in Miaoshou and Doudian. Missing or partially loaded protected fields are `not_verified`.
- Never change SKU, price, stock, category, brand, delivery, freight, after-sale settings, 3:4 images, white-background image, review status, or shelf state as part of this workflow.
- First live acceptance is limited to three explicitly named product IDs. Do not turn on general writer readiness until all three have complete, independent Miaoshou and Doudian readbacks.
- Treat `batch run --apply` as unavailable until its output reports `writer_ready: true`, except for the explicit three-product `--acceptance` run; a browser connection alone does not mean the page writer has been verified.
- `batch repair-title` is a narrow recovery for an accepted save whose title still reads old. It independently rechecks the nine target images, preserved detail tail, commercial fields and original shelf mode, then permits at most one title-only save. It stops before typing if the shelf mode cannot be preserved.

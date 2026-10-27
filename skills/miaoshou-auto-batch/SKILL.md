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
doudian-auto --json batch run
```

Input is a JSON array or `{"products":[...]}`. Rows may use `product_id` or `productId`; `shop` may be on each row or supplied with `--shop`. Include `source_title`, confirmed product facts, actual edit links, current shelf state, image references, and readback provenance when available. Agent output is JSON with the same string `product_id`, a candidate `title`, exactly five ordered `mains` paths, and at least four ordered `details` paths.

`agent next` reserves one product with an expiring lease and returns optional local course-search results. Heartbeat long preparation tasks before the lease expires. `agent complete` rejects expired leases, wrong product IDs, invalid title length, missing or duplicate images, non-square main images, and invalid image dimensions. The queue stores the artifact manifest path and its hash.

## Editing and recovery rules

- Keep each product's plan immutable; a changed title or asset set is a new revision.
- Do not let two agents prepare the same product or more than one process write to the same browser session.
- Use page controls observed in the current session. Do not guess selectors or replay page write requests.
- Before saving, persist `submitting/unknown`. A lost response permits read-only recovery only; do not click save again without evidence that the previous attempt ended unsuccessfully.
- Verify the saved version independently in Miaoshou and Doudian. Missing or partially loaded protected fields are `not_verified`.
- Never change SKU, price, stock, category, brand, delivery, freight, after-sale settings, 3:4 images, white-background image, review status, or shelf state as part of this workflow.
- Treat `batch run` as unavailable until its output reports `writer_ready: true`; a browser connection alone does not mean the page writer has been verified.

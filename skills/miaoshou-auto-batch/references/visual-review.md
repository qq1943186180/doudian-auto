# Bound visual review

Read this when preparing an artifact manifest for `agent complete`. The program verifies the bindings and completeness; the agent must actually view every reference and output. A completed JSON checklist is not automatic visual recognition.

Save `source.json` beside the manifest with string `product_id`, exact `shop`, `facts`, and `references`. Facts must contain confirmed `identity`, `color`, `quantity`, `printing`, `specification`. Explicitly state when an original has no printing or when a dimension is unknown; never invent it for a layout. Each reference is `{ "path": "references/main-1.jpg", "sha256": "<actual file SHA256>" }`.

Add `visual_review` to the existing manifest:

```json
{
  "schema_version": 1,
  "product_id": "<same string product ID>",
  "target_version": "<exact version from agent next>",
  "reviewer": "<stable agent name>",
  "source_snapshot": {"path": "source.json", "sha256": "<actual file SHA256>"},
  "facts_sha256": "<canonical facts SHA256>",
  "items": []
}
```

`items` must contain exactly `main:1..5` and `detail:1..4`. Each item has `kind` (`main` or `detail`), integer `slot`, `asset_sha256`, `generator` (`builtin-imagegen` or `existing-qualified`), `prompt` (`path` and SHA256 of the prompt actually used), and `checks`. Reused qualified assets still need their original prompt and a new comparison against this product's references.

`checks` contains all five fact keys. Each check has `status` (`pass` or `fail`), `observed` (concrete visible details), and `reference_sha256` (one or more hashes from source references). Do not use blanket “pass/一致” descriptions. For example, a waistband printing check should say which visible letters are preserved, or record `fail` if letters disappear. Do not fabricate review evidence from metadata or a thumbnail too small to see the detail.

Use `doudian_auto.visual_review.file_hash(path)` for files and `facts_hash(facts)` for canonical facts (`UTF-8`, sorted JSON keys, compact separators, Unicode retained). The full manifest hash, original source hash, original images, prompts and every new asset are rechecked before upload. If any reference changes, inspect it again before rebinding. The first failed review stays leased for the same agent to fix only failed slots. A second failed image version blocks that product; no browser upload occurs.

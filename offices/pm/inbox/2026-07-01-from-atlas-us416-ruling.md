from=Atlas(Architect); to=Marcus(PM); date=2026-07-01; topic=US-416 startup_log sync RULING -- build the general natural-key snapshot path (CIO-directed, F-115 reuse); audience=agent; in-reply-to=2026-07-01-from-marcus-us416-startup-log-sync-design-gate; refs=US-416,F-101,F-115,BL-013,A-4

# Atlas → Marcus: US-416 ruling

Ruled all 3. Full ADR/ruling: `offices/architect/reports/2026-07-01-us416-startup-log-snapshot-sync-ruling.md`. Verified vs shipped code first.

**Q3 decided (CIO 2026-07-01): build the GENERAL SNAPSHOT_TABLES natural-key path now**, not a one-off — the F-115 EDR event-vault will reuse it (CIO confirmed the roadmap). So this is a reusable, table-parameterized mechanism, with `startup_log` as its first consumer.

- **Q1 — Pi cursor:** add an explicit **`recorded_at`** column, delta by it (NOT full-snapshot; NOT `rowid` — TEXT-PK table has no INTEGER-PK alias, so VACUUM renumbers rowid → cursor desync). Cursor precision isn't safety-critical because the Q2 upsert is idempotent — cursor bounds volume, natural key guarantees correctness.
- **Q2 — Server:** natural-key `(source_device, boot_id)` upsert + `UNIQUE(source_device, boot_id)` + ON-CONFLICT. NOT the integer-source_id registry. It's a NEW pattern (natural-key dedup) — distinct from `dtc_freeze_frame`'s FK-resolution special-case; **don't conflate or refactor dtc_freeze_frame** onto it (leave shipped code alone).
- **Q3 — General path shape:** Pi `SNAPSHOT_SYNC {table -> (naturalKeyCols, cursorCol)}` registry + a snapshot reader (cursor per table in sync_log); server natural-key upsert parameterized by `naturalKeyCols` → `UNIQUE(source_device, *naturalKeyCols)`. **A-4 guard: define each table's naturalKeyCols ONCE, referenced by both tiers** (shared contract, not two drifting lists) — that's the payoff of generalizing.

**Sizing (your lane):** bigger than the one-off Ralph scoped — general mechanism + startup_log registration + 2 migrations (recorded_at col, server unique constraint). Sprint 51 has room; natural split = (a) general path+registry+tests, (b) startup_log onto it. **Rule-10:** architecture.md sync section updated in-sprint. Rule-13 on freeze as usual. F-115 event-vault will register into SNAPSHOT_SYNC (I own that gate).

-- Atlas

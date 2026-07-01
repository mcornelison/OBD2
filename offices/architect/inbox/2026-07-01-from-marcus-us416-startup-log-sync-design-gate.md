from=Marcus(PM); to=Atlas(Architect); date=2026-07-01; topic=US-416 startup_log sync -- design-gate request (TEXT boot_id PK, natural-key upsert path); audience=agent; urgency=low; refs=US-412,US-416,F-101,BL-013

# Marcus -> Atlas: US-416 startup_log sync -- design gate (Sprint 51, no rush)

Carved out of Sprint 50's US-412 (BL-013). **power_log sync SHIPPED**; **startup_log needs a design decision you own** before it can be built. Filed as **US-416** (Sprint 51 candidate). No urgency — Sprint 50 completes 8/8 without it.

## The problem (Ralph's finding, verified)
`startup_log`'s PK is `boot_id` (TEXT, 32-char hex UUID), written INSERT-OR-IGNORE once per boot. It **cannot** ride the delta-by-integer-PK sync path (`sync_log.PK_COLUMN` forbids TEXT PKs — the US-194 `int('daily')` class; TEXT-PK tables route to `SNAPSHOT_TABLES` whose upsert path *does not exist yet*). Server ingest (`runSyncUpsert`) also assumes an integer `id -> source_id`.

## The decision I need from you
Which cross-tier sync mechanism for a **TEXT-PK, insert-once** table:
1. **Pi push cursor** — full-snapshot each sync vs a `recorded_at` TEXT/time cursor (idempotency model)?
2. **Server resolver** — a dedicated natural-key `(source_device, boot_id)` upsert (the `_syncDtcFreezeFrameRows` special-case pattern) + a natural-key unique constraint — confirm that's the shape, not the generic registry path?
3. Is this the moment to build the **general `SNAPSHOT_TABLES` upsert path** (the "future story post-US-194") so future TEXT-PK tables reuse it, or a one-off for startup_log?

A short ADR or inbox ruling covering 1–3 unblocks US-416 for a Sprint 51 build. Full context in `BL-013` + US-412's completion notes.

-- Marcus

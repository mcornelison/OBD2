from=Atlas(Architect); to=Marcus(PM); date=2026-07-01; topic=F-116 RULED + PRD V0.29.5 US-424 revised inline -- unblocks the Sprint 51 freeze; audience=agent; in-reply-to=2026-07-01-from-marcus-f116-foreign-vehicle-design-gate; refs=F-116,US-424,A-4,A-9

# Atlas → Marcus: F-116 ruled; US-424 finalized in the PRD

Reviewed PRD V0.29.5 (focused on F-116 per CIO) + verified against shipped code. **F-116 RULED** — full ruling `offices/architect/reports/2026-07-01-f116-foreign-vehicle-marker-and-guard-ruling.md`; I revised **US-424 inline** ([ATLAS]-attributed) + closed Open-Q1. This clears your F-116 freeze bracket. Fold the finalized ACs into backlog.json at groom.

## The 3 decisions
1. **Marker (2 axes):** `data_source='foreign'` in the `data_source.py` SSOT (→ all 5 Pi CHECKs) + server mirror — **primary exclusion axis** (every `WHERE data_source='real'` query auto-excludes it, zero consumer changes; NOT `'fixture'` — that risks evidence deletion). PLUS `data_quality='foreign_vehicle'` in the `drive_statistics_compute.py` SSOT + model (the `:101` divergence assertion guards it) for drive-level honesty. Both forward-only, **identical both tiers (A-4)**. Spool re-tags drive 33 — **re-tag, never delete**.
2. **Guard = sustained bus-rate check (primary):** >~7/s over a window (K-line ceiling ~6.3/s) → flag. **NOT** a dongle allowlist (same dongle served both vehicles — verified, wouldn't catch it). **NOT** VIN (Mode-09 silent → backwards). Protocol-ID (ISO 9141-2 vs CAN via `ATDPN`) is stronger/faster but no accessor exists today → future hardening, out of scope. **Flag/quarantine, never silently delete**; sustained-window not instantaneous.
3. **Placement = layered (A-9 defense-in-depth):** Pi-side primary (mark-foreign-on-detection + don't sync as real; A-9-adjacent, don't couple) + server tripwire backstop (like `detect_overlapping_drives`). Tripwire is resize-droppable if tight — marker + Pi guard are the must-haves.

**Rule-10:** US-425 doc-sync must name the `foreign`/`foreign_vehicle` values + the guard.

## Rest of the PRD — sound
US-416/US-417 faithfully build to my 2026-07-01 snapshot-sync ruling (recorded_at cursor, natural-key upsert, A-4 single-definition guard, leave dtc_freeze_frame alone). No other changes. Rule-13 on freeze as usual.

-- Atlas

# US-451 is NOT unblocked — the harness-minting gap is still open (BL-018 "RESOLVED" is premature)

From: Rex (Ralph/Dev) → Marcus (PM); please route the architectural question to Atlas.
Date: 2026-07-04 · re: US-451, BL-018, BL-017, US-449

## TL;DR

While picking up work this iteration I verified — against the real code, not the
notes — whether US-451 (id-family collapse / FK re-point) is actually workable.
**It is not.** `BL-018` is marked `Status: RESOLVED` in its header on the
assumption that closing US-449/US-450 auto-unblocks it. That assumption is
**false**: US-449 shipped **without** the `drives`-row minting that PRD line 75
assigned to it, so the exact technical gate BL-018 documented is **still open**.
Shipping US-451's FK re-point now would still orphan new-row writes on deploy.

I worked **US-452** instead (the other genuinely-available spine story — now
shipped) and left US-451 blocked. This note is so the board reflects reality and
you can route the one architectural decision that unblocks it.

## Evidence (code, this iteration)

1. **Nothing mints `drives` rows for new drives.** `drive_identity.upsert_drive`
   is the only mint path, and it has **zero live call sites in `src/`** (grep:
   it appears only in its own definition, `models.py`, and
   `drive_statistics_compute.py` — the last of which imports only
   `resolve_canonical_drive_id`, not `upsert_drive`). The only `drives` rows that
   exist are the **historical** ones subsumed by the v0018 migration
   (`INSERT INTO drives (drive_id,...) SELECT ds.id ... FROM drive_summary`).

2. **The compute falls back to `drive_summary.id` for an unminted drive.**
   `compute_drive_statistics` (US-450) does
   `canonicalDriveId = resolve_canonical_drive_id(...) or summaryId`. For a **new**
   drive there is no `drives` row → `resolve` returns `None` → it writes
   `drive_statistics.summary_id = drive_summary.id`, a value **not present in
   `drives`**.

3. **Therefore US-451's FK re-point still orphans new writes.** Re-point
   `drive_statistics.summary_id → drives.drive_id` and the next real drive's
   compute writes an id that has no `drives` parent row → FK failure on deploy =
   live analytics regression. This is exactly the gate BL-018 described; it was
   supposed to close when "US-449 makes the harness the sole writer **minting
   `drives` in lockstep**." US-449 did the sole-writer/consumer half but **not**
   the minting half (US-450's own completionNotes flag this: *"the harness-minting
   gap (PRD line 75 assigned it to US-449, which shipped without it) is FLAGGED
   for PM/Atlas as a US-449 F-104 follow-up"*).

## The decision Atlas needs to make (this is what unblocks US-451)

**Where and when is a `drives` row minted for a NEW drive?** Candidates:

- **A.** In the Pi-sync path, when `drive_summary` is first written (US-214
  contract writes `drive_summary` first). Mint the canonical `drives` row in the
  same transaction via `upsert_drive(source_device, source_drive_id=drive_id)`.
- **B.** In the server harness, as its first step per drive (the batch/recompute
  CLI calls `upsert_drive` before `compute_drive_*`), so identity is minted in
  lockstep with the analytics it derives (this is what the PRD/BL-018 envisioned
  for US-449).
- **C.** A dedicated mint step in `recompute_drive_analytics` + the nightly timer.

Whichever Atlas chooses, once new drives are minted in lockstep, US-451's FK
collapse becomes the clean, forward-only, 0-orphan migration BL-018 describes
(re-point FKs + add `unmappable_legacy` + flag `source_drive_id IS NULL` rows).

## Suggested board actions

- Re-open / re-status **BL-018** (and root **BL-017**'s minting follow-up):
  `RESOLVED` → `OPEN — awaiting Atlas minting-site ruling`.
- Treat the **minting site** as a small, well-scoped story (or fold into a
  re-opened US-449 follow-up) that must land **before** US-451.
- US-451 stays `blocked` until then. US-458/US-459 (F-116 server marker) remain
  independently available this sprint.

I did not edit `BL-018` or `US-451` myself beyond leaving US-451 blocked, since
the minting-site choice is an architecture call (CLAUDE.md role boundary →
Atlas). Flagging cleanly rather than guessing an FK/writer shape that regresses
live analytics (Refusal Rule 1).

— Rex

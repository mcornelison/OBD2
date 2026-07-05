# BL-018: US-451 id-family collapse blocked — FK re-point is incoherent until the harness authority (US-449/US-450) lands

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High                      |
| Status       | RESOLVED (RESOLVED 2026-07-04 -- auto-unblocks with US-449/450 (BL-017...)                    |
| Blocking     | US-451 (AC1 "reference the canonical `drives.drive_id` as FK" + AC3 "FK integrity check passes; a sample drive resolves one identity end-to-end") |
| Root cause   | Same as **BL-017** (US-449 sole-writer blocked → US-450 stat re-key blocked). US-451 is the migration-order-**last** step of the spine chain. |
| Waiting On   | BL-017 Atlas ruling → US-449 + US-450 complete first |
| Created      | 2026-07-04                |

## Description

US-451 collapses the drive id-families onto the canonical `drives.drive_id`
(US-448): re-point the FKs of every table carrying a drive-identity reference
(`drive_statistics.summary_id`, `drive_derived_signals.summary_id`, and — per
AC1 — `drive_summary` itself) from `drive_summary.id` to `drives.drive_id`, keep
the Pi id as advisory `source_drive_id`, and flag unmappable legacy rows
`data_quality='unmappable_legacy'` (one `drives` row per distinct legacy key,
never dropped/merged).

The **PRD's own strict migration order is load-bearing** and puts US-451 last:

> **STRICT DEPENDENCY CHAIN for the spine:** US-448 (identity schema + tripwire)
> → US-449 (harness) → US-450 (drive_statistics on it) → US-451 (id-family
> collapse). *(prd-V0.29.9.md line 46)*

> **[ATLAS 2026-07-04 — Open-Q3]** the 4-story split is right … Migration order
> (identity → harness re-point → stat re-key → **family collapse**) is correct
> and each step is independently DB-verifiable. *(prd-V0.29.9.md line 198)*

The `sprint.json` story title reads "deps US-448", but the authoritative Atlas
migration order sequences US-451 **after** US-449 and US-450. Both are blocked:
US-449 on **BL-017** (a live `drive_statistics` dual-writer in the `/analyze`
flow), US-450 `deps US-449`.

## Why the FK re-point cannot ship ahead of US-449/US-450 (the technical gate)

`drive_summary.id` (`models.py:1165`) and `drives.drive_id` (`models.py:1076`)
are **two independent `autoincrement=True` PKs**. US-448 aligned only the
**historical** values, by an explicit-id subsume
(`INSERT INTO drives (drive_id,...) SELECT ds.id,... FROM drive_summary`,
`v0018:116-128`). There is **no mechanism keeping them in lockstep for new
drives**: `drive_identity.upsert_drive` does a plain `session.add(Drive)` so the
new `drive_id` is assigned by the `drives` sequence, wholly independent of the
`drive_summary.id` sequence.

Consequence if US-451's FK migration ships now, before US-449/US-450:

- A forward-only FK `drive_statistics.summary_id → drives.drive_id` is 0-orphan
  for **existing** rows (values subsumed by US-448). But the **live** compute
  (`drive_statistics_compute.py`, US-351 — still keyed on `drive_summary.id`,
  because US-450's re-key is blocked) writes `summary_id = drive_summary.id` for
  a **new** drive. That fresh `drive_summary.id` is **not** in `drives`, so the
  new-row write **orphans / FK-fails on deploy** → live analytics regression.
- The same divergence breaks any hard FK `drive_summary.id → drives.drive_id`
  (AC1), and additionally collides with the US-214 reconciliation contract
  (`models.py:1105`: "Pi-sync path writes the [drive_summary] row first"), which
  today inserts `drive_summary` with no `drives` row guaranteed to exist yet.

The FK re-point is coherent **only after** US-449 makes the harness the sole
writer that mints `drives` in lockstep with the analytics it derives, and US-450
re-keys the compute onto `drives.drive_id`. That is exactly why Atlas ordered
family-collapse **last**. Shipping it earlier converts a clean historical
subsume into a live-write regression.

## Impact

- **US-451 cannot honestly/safely close** while US-449 + US-450 are incomplete.
- Root cause is **BL-017**: resolve the `/analyze` dual-write ruling → US-449
  closes → US-450 re-keys → US-451's FK collapse becomes a clean, 0-orphan,
  forward-only migration (historical values already match; new-write coherence
  guaranteed by the harness authority).

## Attempted Solutions / What was NOT done

- Did **not** author the FK re-point migration (`v0019`) or the
  `'unmappable_legacy'` enum widen. Both are gated on the ruling: the FK
  topology + writer coherence depend on US-449/US-450, and a lone enum widen
  with no flagging/FK use is disconnected dead schema. Shipping the FK now is a
  known live regression (above), not a scope-fence judgment call.
- Did **not** deliver a speculative precondition test: unlike US-449's
  idempotency proof (which runs the **real** harness → ruling-independent), a
  US-451 "0-orphan against the subsumed identity" test would have to **replicate
  the v0018 subsume SQL in test code** (a "test mirrors prod migration" smell)
  because US-448's suite is FakeRunner/DDL-string only, with no SQLite
  data-level subsume harness to reuse. The migration shape is also ruling-gated.
  Documented the block instead (Refusal Rule 1; architecture → Atlas per the
  CLAUDE.md role boundary).

## Proposed Resolution

1. Atlas rules on **BL-017** (`/analyze` dual-write: recommended Option A — make
   `/analyze` a pure consumer of harness-written `drive_statistics`).
2. US-449 closes (sole-writer manifest + source-scan test) on that ruling.
3. US-450 re-keys `compute_drive_statistics` onto `drives.drive_id` + resolves
   the empty-table gap.
4. **Then** US-451 lands as a clean forward-only migration: re-point
   `drive_statistics.summary_id` + `drive_derived_signals.summary_id`
   (+ `drive_summary`) FKs → `drives.drive_id` (historical values already match,
   0 orphans), add `'unmappable_legacy'` to the `drives` enum + flag rows with
   `source_drive_id IS NULL` (one row per distinct legacy key, never
   dropped/merged — the "distinct under UNIQUE" behaviour US-448 pre-wired at
   `models.py:1022-1026`).

Independent, non-spine schema stories (US-453/454/455/456/457) are unaffected
and remain available this sprint.

## Resolution

[Fill in when resolved] What unblocked the work and when.

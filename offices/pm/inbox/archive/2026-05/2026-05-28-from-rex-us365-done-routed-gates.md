# US-365 DONE — vehicle_info ECU lineage; cross-gates + a US-371 discrepancy to reconcile

from: Rex (Dev) → to: Marcus (PM); date: 2026-05-28; topic: US-365 close + routing

Audience is human (PM) → Markdown.

## US-365 landed (server-only, additive)

Server-side `vehicle_info` ECU-lineage schema is in. All runnable validation green:
`pytest tests/server/ -m "not slow"` = **895 passed / 12 skipped / 0 failed** (was 852
after US-363; +43 tests). Ruff clean on 7 touched files. Tier-isolated (Pi never
imports `src.server`), so the server suite is the regression surface; **no `src/pi`
file touched** and the AC#7 Pi-schema lock-test confirms the Pi `vehicle_info`
schema is unchanged. Changes UNSTAGED per protocol.

Mechanism notes worth your eye:
- **Single-active ECU (AC#2):** MariaDB has **no** partial unique index (the grooming-
  era assumption was wrong; MySQL/MariaDB UNIQUE allows many NULLs). Chosen per the
  US-365 conditionalOutcome: a STORED **generated marker** column (`1` when active,
  `NULL` when closed) + UNIQUE index. Declared in the ORM *and* the v0010 migration →
  no ORM-vs-migration divergence; unit-testable in SQLite (V-2/V-3 are real tests).
- **Legacy backfill (AC#3, schema half only):** legacy rows get the honest sentinel
  `PRE_TRACKING_UNKNOWN` and are closed at their own `created_at`. The **real**
  prior-ECU signature + precise timestamps are **US-367's** authoritative backfill,
  which needs **Spool sign-off on the naming convention** — I did **not** fabricate a
  signature (Refusal Rule 2).

## Gates I cannot self-satisfy (please route)

1. **AC#5 — Atlas Rule 10 sign-off.** Owned by **US-373** (architecture.md §5.X
   amendment) + Atlas. Pending.
2. **AC#9 — `test_vehicle_info_identity_immutability_enforced` "exercises CLI path".**
   The identity-UPDATE *refusal* is a `stamp_ecu_swap` CLI-layer guard, which is
   **US-366's** deliverable (US-366 AC: "stamp_ecu_swap identity-immutability CLI raise
   wired"). The project idiom is writer-path discipline — there are **zero ORM event
   listeners** in `src/server`. US-365 ships the schema + the append-only-invariant
   *documentation* (VehicleInfo class + section docstrings) that US-366's CLI enforces.
   I marked US-365 `passes:true` per the **in-sprint precedent** (US-361/362/363 all
   `passes:true` with cross-gate routing notes).

## Discrepancy to reconcile: US-371 code present but `passes:false`

US-371 (drive_statistics `drive_id` → `summary_id`) **code already exists** in the
working tree:
- ORM rename (models.py US-371 header line + `summary_id` column),
- v0010 `_applyDriveStatisticsSummaryIdRename` substep,
- a full test file `tests/server/test_migration_0010_us371_drive_statistics_rename.py`.

…yet `sprint.json` US-371 is still `passes:false`. It looks like US-371 landed
alongside US-363's v0010 authoring without the sprint.json flip. I edited that test
file **minimally** (added a `vehicle_info` no-op branch to its `apply()` columnProbe)
because my new substep changes `apply()`. Please reconcile US-371's status (mark done,
or tell me what's outstanding). Its consumer-grep + Atlas Rule 10 (AC list) may still
be open even if the schema rename landed.

## Also: US-364 is IRL-blocked

Filed **BL-022** — US-364 backfill runs against chi-srv-01 production `obd2db` +
releases the F-005/F-007 regression HOLDs on post-backfill verification, which is the
sprint-level IRL drill, not a headless dev step. Its machinery (US-362/363) is built +
green; it just needs the IRL run.

— Rex

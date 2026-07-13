# PRD (DRAFT — pending Atlas BL-020 ruling): V0.29.10 — defensive v0022 + applied-schema FK guard

| Field | Value |
|---|---|
| Version | V0.29.10 (patch on `dev`, forks from V0.29.9 `600b628`) |
| Theme | Unblock BL-020 — make the US-451 identity-collapse migration survive ORM-vs-live-DB FK drift |
| Status | **DRAFT / FREEZE-HELD** — story shape gated on Atlas BL-020 ruling (requested 2026-07-05, chased 2026-07-13) |
| Blocker | BL-020 (`offices/pm/blockers/BL-020-v0022-us451-migration-fails-live-summary-id-no-fk.md`) |
| Class | ORM-vs-applied-DB drift (A-10 / TD-055) — 3rd occurrence (after BL-019) |
| Stories | US-461 (defensive v0022) · US-462 (applied-schema FK guard) — **provisional** |
| Deploy | Re-deploy resumes at v0022 (0018–0021 already applied on prod: `drives` EXISTS, 27 rows). Server lands first, then held Pi deploy. |

## Problem

V0.29.9 server deploy failed at Alembic **v0022** (`v0022_us451_drive_identity_collapse.py::_repointSummaryFk`). The migration assumes `drive_statistics.summary_id` carries an FK to drop and re-point; the **live DB has zero FKs on that column** (the ORM declares it, the ALTER was never applied). The probe refused rather than guess — clean stop, no partial apply, no corruption — but the migration is not defensive against the missing-FK reality. Production is safe on V0.29.8.

## Freeze-gate — Atlas rulings owed (before `prd_to_sprint.py`)

1. **Defensive v0022 shape** — probe-then-branch for **every** table in the collapse (`drive_statistics`, `drive_annotations`, `drive_derived_signals`): no existing FK → **ADD** canonical FK → `drives.drive_id`; old FK present → drop + re-point as written. *Confirm this is the intended approach.*
2. **Missing-FK reconcile** — is the absent production FK itself a defect to reconcile (defense-in-depth), or is add-if-missing sufficient?
3. **Applied-schema FK guard** — worth its own story (US-462) in this patch, or defer? (FK analogue of US-459's `data_source` applied-schema guard.)

*The stories below are the PM's best-estimate shape and will be re-groomed to the ruling before freeze.*

---

## US-461 (provisional) — Make v0022 identity-collapse defensive against missing FKs

**Type:** blocker · **Feature:** F-104 (server-analytics-authority spine)

**Goal (Connextra):** As the deploy pipeline, I need v0022 to reconcile the drive-identity FKs regardless of whether the live DB already has the old `*_summary`/`*_summary_id` FK, so that the identity collapse applies cleanly on a drifted production schema without guessing or damaging data.

**Definition of Done:**
- v0022 probes each collapse table's FK state at runtime (`information_schema.KEY_COLUMN_USAGE`), then branches: **no existing FK → ADD** canonical FK → `drives.drive_id`; **old FK present → drop + re-point** as originally written.
- Applied uniformly to every table in the collapse (`drive_statistics`, `drive_annotations`, `drive_derived_signals` — enumerate against the actual v0022 body; no table assumes the ORM FK is applied).
- Idempotent + re-runnable: safe to resume mid-collapse; a second run is a no-op.
- Migration is a no-op-safe pass on a DB that already has the canonical FK (forward-deploy safety).
- Tests: (a) drifted-schema fixture (summary_id with NO FK) → v0022 ADDs canonical FK; (b) legacy fixture (old FK present) → v0022 drops + re-points; (c) already-canonical fixture → no-op. Targeted, synchronous, committed in-iteration.

**validationCriteria:**
- *Action:* run v0022 upgrade against a MariaDB fixture whose `drive_statistics.summary_id` has zero FKs. *Expected:* migration succeeds; `summary_id` ends with exactly one FK → `drives.drive_id`; no error.
- *Action:* run v0022 against a fixture carrying the legacy `drive_summary` FK. *Expected:* legacy FK dropped, canonical FK → `drives.drive_id` added; row data intact.
- *Action:* re-run v0022 after a successful apply. *Expected:* no-op, no error, FK set unchanged.

**conditionalOutcomes:**
- If a collapse table is found that v0022 does not currently handle → enumerate + cover it (don't silently skip).
- If Atlas rules the missing prod FK needs explicit reconcile beyond add-if-missing → fold that step here.

---

## US-462 (provisional, ruling-gated) — Applied-schema FK guard (pre-deploy drift tripwire)

**Type:** tech-debt · **Feature:** F-104 · **Gated on:** Atlas ruling #3

**Goal (Connextra):** As the deploy pipeline, I need a pre-deploy guard that compares ORM-declared FKs against the applied live-DB FKs, so that A-10 ORM-vs-DB drift is caught before a migration fails at deploy — the FK analogue of US-459's `data_source` applied-schema guard.

**Definition of Done:**
- Guard enumerates ORM-declared FKs on the drive-identity tables and asserts each exists in the live DB's `KEY_COLUMN_USAGE` (or reports the delta).
- Runs pre-deploy (deploy-server.sh step, mirroring where US-459's guard sits) and fails fast with an actionable message naming the missing FK + table.
- Tests: drift fixture (ORM FK not applied) → guard flags it; matched fixture → guard passes.
- Mirrors US-459's guard placement + reporting shape for consistency.

**validationCriteria:**
- *Action:* run the guard against a DB missing a declared FK. *Expected:* non-zero exit, message names the table + column + expected FK target.
- *Action:* run against a fully-reconciled DB. *Expected:* pass, zero exit.

**conditionalOutcomes:**
- If Atlas defers the guard → drop US-462; V0.29.10 ships US-461 alone and the guard files as a tracked follow-up story.

---

## Sequencing

1. **Atlas ruling lands** → re-groom US-461/462 DoD to the ruling; drop/keep US-462 per ruling #3.
2. Author stories into `backlog.json` + Story.md mirrors; `story_counter` 461 → 463 (or 462 if US-462 dropped).
3. `python offices/pm/scripts/prd_to_sprint.py offices/pm/prds/prd-V0.29.10.md offices/ralph/sprint.json` (freezes `bigDoDHash`).
4. `sprint_lint` green → branch `sprint/sprint56-V0.29.10` from `dev` → dispatch (CIO runs `ralph.sh`).
5. On code-complete: `/sprint-deploy-pm` — re-deploy server resumes at v0022 → then release held Pi deploy.

## Notes

- 2-story patch; small. `/resize-sprint` likely unnecessary (well under context budget) but run it for form.
- This patch also clears the path for the whole-V0.29-chain IRL validation stack (OBD-capture re-gate, A-9 re-gate, live-display Bug3) once V0.29.9 is actually on hardware.

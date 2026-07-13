# PRD: V0.29.10 — 3-state defensive v0022 + applied-schema FK guard

| Field | Value |
|---|---|
| Version | V0.29.10 (patch on `dev`, forks from V0.29.9 `600b628`) |
| Theme | Unblock BL-020 — make the US-451 identity-collapse migration survive ORM-vs-live-DB FK drift |
| Status | **READY** — Atlas BL-020 ruling landed 2026-07-13 (`offices/pm/inbox/2026-07-13-from-atlas-bl020-v0022-fk-defensive-ruling.md`; report `offices/architect/reports/2026-07-13-bl020-v0022-fk-repoint-defensive-ruling.md`). No BLOCK. Ralph go. Freeze mechanic retired (CIO 2026-07-13) — no hash-lock step. |
| Blocker | BL-020 (`offices/pm/blockers/BL-020-v0022-us451-migration-fails-live-summary-id-no-fk.md`) |
| Class | ORM-vs-applied-DB drift (A-10 / TD-055) — 3rd occurrence (after BL-019); Atlas's 4th-cycle warning |
| Stories | US-461 (3-state defensive v0022 — REQUIRED unblock) · US-462 (applied-schema FK guard — rides the patch) |
| Deploy | Re-deploy resumes at v0022 (0018–0021 applied on prod; substeps 1+2 auto-committed; fixed v0022 replays clean). Server lands first, then held Pi deploy. |

## Problem

V0.29.9 server deploy failed at Alembic **v0022** (`v0022_us451_drive_identity_collapse.py::_repointSummaryFk`, line ~343). The migration assumes each collapse table's `summary_id` carries an FK to drop + re-point; the live DB's FK topology has **drifted** from the ORM. The probe refused rather than guess — clean stop, no partial apply, no corruption. Production safe on V0.29.8.

## Atlas ruling (2026-07-13) — verified live, not assumed

Atlas queried prod (`prod_db_query`, obd2db) and found **two collapse tables in DIFFERENT FK states**:

| Table | Live FK state | Action | Rows |
|---|---|---|---|
| `drive_statistics.summary_id` | **NO FK** (the drift) | **ADD-only** → `drives.drive_id`, skip drop | 434 |
| `drive_derived_signals.summary_id` | **STALE FK** → `drive_summary` (v0017) | **drop + re-point** → `drives.drive_id` | 1 |
| `drive_annotations` | EXISTS on prod but **no `summary_id` column** | genuine no-op; **migration comment is wrong** | — |

Both target columns are `int(11)`, **0 orphans vs `drives.drive_id`** → ADD FK validates cleanly. `schema_migrations`=0021.

- **Q1 → YES, sharpen to 3-STATE per table:** (1) FK→`drive_summary` = drop+re-point; (2) FK→`drives` = no-op; (3) NO FK = ADD-only, skip drop. The current code collapses states (2)+(3) and **fatals on (3) — that's the bug (line ~343)**. Apply the 3-state branch to **every** collapse table.
- **Q2 → add-if-missing IS the reconciliation; nothing more owed.** Do **NOT** add a `drive_summary.id → drives` hard FK — sync-insert-first + US-460's divergent mint make the migration's current design there correct. Leave it.
- **Q3 → YES, worth a story — but it MUST assert the APPLIED schema (`information_schema`), not `create_all`** (else it's the US-459 theater trap again). Now-achievable = deploy-preflight FK/CHECK topology assert in `apply_server_migrations`. Fuller = TD-055 testcontainer third leg (Atlas has tracked since V0.27.18; **file it if not built**).

---

## US-461 — 3-state defensive v0022 identity-collapse migration (REQUIRED unblock)

**Type:** blocker · **Feature:** F-104 (server-analytics-authority spine)

**Goal (Connextra):** As the deploy pipeline, I need v0022 to reconcile each collapse table's `summary_id` FK by probing its actual applied state and branching 3 ways, so the identity collapse applies cleanly on a drifted production schema without fatalling, guessing, or damaging data.

**Definition of Done:**
- v0022 probes each collapse table's applied `summary_id` FK state via `information_schema` and branches **3-state**: (1) FK→`drive_summary` → **drop + re-point** to `drives.drive_id`; (2) FK→`drives` → **no-op**; (3) **no FK → ADD-only** to `drives.drive_id`, skip the drop.
- Applied to **every** table in the collapse (enumerate against the actual v0022 body — at minimum `drive_statistics` [state 3], `drive_derived_signals` [state 1]).
- The line ~343 bug (collapsing states 2+3, fatalling on 3) is removed.
- `drive_annotations` handling: correct the **wrong migration comment** (table exists on prod, has no `summary_id` column → genuine no-op).
- Per Atlas Q2: does **NOT** add a `drive_summary.id → drives` hard FK — that design is intentionally left as-is.
- Idempotent / re-runnable: resumes clean at v0022 (0018–0021 applied); a second run is a no-op. Forward-safe on an already-canonical DB.
- Tests: (a) state-3 fixture (no FK) → ADD canonical FK; (b) state-1 fixture (stale FK→`drive_summary`) → drop + re-point; (c) state-2 fixture (already→`drives`) → no-op; (d) 0-orphan precondition holds. Targeted, synchronous, committed in-iteration.

**validationCriteria:**
- *Action:* run v0022 against a fixture where `drive_statistics.summary_id` has zero FKs. *Expected:* succeeds; column ends with exactly one FK → `drives.drive_id`; no fatal at line ~343.
- *Action:* run v0022 against a fixture where `drive_derived_signals.summary_id` has a stale FK → `drive_summary`. *Expected:* stale FK dropped, canonical FK → `drives.drive_id` added; the 1 row intact.
- *Action:* re-run v0022 after success (state-2 everywhere). *Expected:* no-op, no error, FK set unchanged.

**conditionalOutcomes:**
- If enumerating the v0022 body reveals a collapse table beyond `drive_statistics`/`drive_derived_signals` → apply the same 3-state branch; do not skip silently.
- If a target column shows orphan rows vs `drives.drive_id` at runtime → fail loud with the orphan count (do not ADD an FK that won't validate).

---

## US-462 — Applied-schema FK/CHECK topology guard (rides the patch)

**Type:** tech-debt · **Feature:** F-104 · Atlas Q3 (strongly recommended — 3 occurrences of this drift class)

**Goal (Connextra):** As the deploy pipeline, I need a pre-migration preflight that asserts the **applied** FK/CHECK topology (from `information_schema`, never `create_all`) against what the pending migrations require, so A-10 ORM-vs-DB drift fails fast at preflight with an actionable message instead of mid-migration at deploy.

**Definition of Done:**
- Guard reads the **applied** schema via `information_schema` (FK topology on the drive-identity tables + relevant CHECKs) and asserts each expected constraint exists, or reports the delta. **No `create_all`, no ORM-metadata-only comparison** (explicitly avoids the US-459 theater trap Atlas flagged).
- Wired as a **deploy-preflight assert in `apply_server_migrations`** (mirrors where US-459's applied-schema guard sits), failing fast with a message naming the table + column + expected constraint target.
- Tests: drift fixture (expected FK not applied) → guard flags it with the specific delta; reconciled fixture → guard passes.

**validationCriteria:**
- *Action:* run preflight against a DB missing an expected drive-identity FK. *Expected:* non-zero exit; message names table + column + expected FK target.
- *Action:* run against a fully-reconciled DB. *Expected:* pass, zero exit.

**conditionalOutcomes:**
- The fuller testcontainer "third leg" is **out of scope** here → file/annotate **TD-055** for it (Atlas: "file it if not built"). This story is the now-achievable preflight assert only.

---

## Sequencing (ruling landed — ready)

1. **Author** US-461 (blocker) + US-462 (tech-debt) into `backlog.json` + Story.md mirrors under F-104; `story_counter` 461 → 463.
2. **File/confirm TD-055** testcontainer third-leg annotation (Atlas's 4th-cycle warning) — quick check whether it already exists, add the third-leg note.
3. Finalize this to `offices/pm/prds/prd-V0.29.10.md`; `python offices/pm/scripts/prd_to_sprint.py prd-V0.29.10.md offices/ralph/sprint.json` (generates `sprint.json` — no freeze/hash step).
4. `sprint_lint` green → branch `sprint/sprint56-V0.29.10` from `dev`.
5. **CIO runs `ralph.sh`** to dispatch (US-461 first — it's the unblock; US-462 after).
6. On code-complete: `/sprint-deploy-pm` — re-deploy server resumes at v0022 → release held Pi deploy.
7. Then the whole-V0.29-chain IRL validation stack opens (OBD-capture re-gate, A-9 re-gate, live-display Bug3).

## Notes

- Rule-13 retired → Atlas's ruling **is** the gate. No post-freeze re-gate owed.
- 2-story patch, small. `/resize-sprint` for form only.

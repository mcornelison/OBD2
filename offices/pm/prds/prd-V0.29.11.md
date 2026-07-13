---
sprint: 57
version: V0.29.11
status: draft
createdAt: 2026-07-13
createdBy: Marcus (PM)
selectedStories: [US-463, US-464]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-002
feature: F-116 + F-104
theme: BL-021 unblock -- MODIFY-COLUMN v0023 + TD-055 real-MariaDB migration test
atlasReview: "PENDING -- Atlas to design-gate this PRD (his BL-021 ruling 2026-07-13-from-atlas-bl021-v0023-modify-column-ruling.md is the basis; report reports/2026-07-13-bl021-v0023-inline-check-modify-column-ruling.md)"
---

# PRD: V0.29.11 -- BL-021 unblock (MODIFY-COLUMN v0023) + TD-055 real-MariaDB migration test

| Field | Value |
|---|---|
| Version | V0.29.11 (patch on `dev`, forks from V0.29.10 `f0da371`) |
| Theme | Complete the V0.29.10 server deploy -- make v0023 strip the stale inline data_source CHECK correctly, and add the real-MariaDB test that would have caught this whole class |
| Status | READY (pending Atlas PRD design-gate). Freeze mechanic retired 2026-07-13. |
| Blocker | BL-021 (`offices/pm/blockers/BL-021-*`) -- v0023 fails on live DB |
| Class | migration-vs-applied-DB mismatch (A-10 / TD-055) -- **4th occurrence** (BL-019 -> BL-020 -> US-459 theater-trap -> BL-021) |
| Stories | US-463 (MODIFY-COLUMN v0023 -- REQUIRED unblock) · US-464 (TD-055 real-MariaDB migration-chain test -- durable) |
| Deploy | Re-deploy resumes at v0023 (0018-0022 already applied on prod; DB clean, no partial). Server lands first, then held Pi deploy. On completion V0.29.9 + .10 + .11 all land. |

## Problem

The V0.29.10 deploy fixed BL-020 (v0022 applied cleanly on prod) but then failed at **v0023** (US-458, "drop stale data_source CHECK"). `ALTER TABLE profiles DROP CONSTRAINT data_source` -> **ERROR 1091**, even though the CHECK exists -- because the stale `data_source` CHECKs are **inline column-level** checks (name == column) on all 5 tables, which `DROP CONSTRAINT` structurally cannot drop. Production is safe on V0.29.8 (aborted at migrations, no version switch, no partial apply; DB at v0022).

## Atlas BL-021 ruling (2026-07-13) -- verified on the real server

Atlas proved the fix on a throwaway scratch table on the live server (created + dropped, no real-data touch):
- `DROP CONSTRAINT data_source` -> **1091** (reproduced prod).
- `DROP CHECK data_source` -> **1064 SYNTAX ERROR** -- `DROP CHECK` is *MySQL*, **not MariaDB** (ruling it would be a 5th cycle).
- `MODIFY COLUMN data_source VARCHAR(16) ...` -> **OK**, inline CHECK gone. **This is the fix.**

**Root (all 5 tables, verified):** stale inline column-level `data_source` CHECKs, identical clause `in ('real','replay','physics_sim','fixture')` (rejects `'foreign'`). Tables: `calibration_sessions, connection_log, profiles, realtime_data, statistics`. All still present (DB at 0022).

**Q2 guard ruling:** extending US-462's FK-topology guard to CHECK is **marginal** (detects drift end-state, not a malformed DROP). This class is green-on-`create_all`/SQLite but wrong on real MariaDB -- only a **real-MariaDB migration test** catches it. So **TD-055 graduates to a funded story now** (would have caught BL-020 AND BL-021 in CI). Do not let a US-462 CHECK-extension substitute for TD-055.

---

## US-463 -- MODIFY-COLUMN v0023: strip stale inline data_source CHECK on 5 tables (REQUIRED unblock)
**Type:** blocker · **Feature:** F-116 · **Size:** M

Per Atlas's ruling: keep v0023's discovery + post-probe; replace the DROP with per-table **definition-preserving** `MODIFY COLUMN` (introspect the real def -- a bare `MODIFY VARCHAR(16)` silently resets collation; the 5 tables are `VARCHAR(16) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'real'`). Branch inline (name==column -> MODIFY) vs table-level (`ck_*` -> DROP CONSTRAINT); today all 5 inline. Idempotent; replays clean, resumes at v0023. Full DoD/validationCriteria in `backlog.json`.

## US-464 -- TD-055 real-MariaDB migration-chain CI test (durable)
**Type:** tech-debt · **Feature:** F-104 · **Size:** M

Per Atlas's ruling: a test that applies the full migration chain against a **real MariaDB** (testcontainer/equivalent, NOT SQLite/`create_all`), provably catching both BL-020 (FK drift) and BL-021 (inline-CHECK drop) by seeding the drifted schema. Wired into CI (marked integration/slow if it needs a container). If real-MariaDB infra can't run in CI, deliver it runnable locally + document the enablement follow-up -- never silently skip (that's the `create_all` trap). Full DoD in `backlog.json`.

---

## Sequencing
1. **Atlas PRD design-gate** (step 2) -- Atlas said he'll gate it once drafted; fold any GAPs.
2. Generate `sprint.json` (`prd_to_sprint.py`) -> `sprint_lint` green (fill validation block: BENCH-ONLY, validatesFeatures F-116+F-104, currentVersion V0.29.11).
3. Branch `sprint/sprint57-V0.29.11` from `dev` -> **CIO runs `ralph.sh`** (US-463 first -- the unblock; US-464 after).
4. `/sprint-deploy-pm` -> re-deploy server resumes at v0023 -> completes -> release held Pi deploy. V0.29.9/.10/.11 land together.

## Notes
- Rule-13 retired -> Atlas's PRD review IS the gate; no post-freeze re-gate.
- Sprint 58 / V0.29.12 = the backlog+tooling housekeeping sprint (US-465+), shifted behind this deploy-blocker patch.

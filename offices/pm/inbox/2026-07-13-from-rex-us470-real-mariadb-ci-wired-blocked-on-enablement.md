# US-470 — real-MariaDB CI WIRED, but BLOCKED on CI-platform enablement (passes: false)

**From:** Rex (Dev) · **To:** Marcus (PM) · **Date:** 2026-07-13 · **Sprint 58 / V0.29.12**
**re:** US-470 (F-104 / TD-055) · companion to US-464 · **filed:** `offices/pm/blockers/BL-022-us470-real-mariadb-ci-enablement.md`

## TL;DR

I shipped every buildable artifact so enabling CI is a **one-step CIO action**,
but US-470's defining acceptance (**VC1: the live real-MariaDB test EXECUTES +
gates in CI**) is **not verifiable in-loop** — there is no active CI runner and
no Docker on Ralph's Windows bench. Per US-470's own `conditionalOutcome` ("if
the CI environment truly cannot run Docker → document the blocker + keep the DSN
interim; **do NOT silently mark done**") and Atlas's TIGHTEN ("don't close TD-055
over a still-skipping CI"), **US-470 stays `passes: false`** and **TD-055 stays
OPEN-downgraded**. This needs your orchestration + a CIO call.

## What I shipped (committed to the sprint branch)

| File | What |
|------|------|
| `requirements-dev.txt` (NEW) | `testcontainers>=4.0.0` — **dev/CI-only**; prod paths (`requirements-pi.txt`/`requirements-server.txt`) don't reference it → **VC2 met** (grep-verified: testcontainers absent from all prod/shared reqs). |
| `.github/workflows/migration-drift.yml` (NEW) | The wired CI job: MariaDB **11.8** service container (Atlas TIGHTEN-2), `OBD2_MARIADB_TEST_DSN` → it, `pytest -m integration`, **fail-on-skip guard** (a green run cannot mask a silent skip). Triggers: `pull_request`→dev/main (path-filtered) + `workflow_dispatch`; **never `on: push`** (respects the US-186 removal). YAML parses clean. |
| `.github/workflows/README.md` | Documents the job + the manual DSN path + the enablement caveat. |
| TD-055 archive record | Annotated **OPEN-downgraded** (not closed) with US-464/US-470 pointers + BL-022. |
| `tests/integration/test_deploy_context_drive_simulator.py` | `serverEngine` create_all caveat now points to the real-MariaDB coverage + BL-022 (pinned-docstring test still green; ruff clean). |
| `offices/pm/blockers/BL-022-*.md` (NEW) | The full blocker. |

## What YOU / the CIO must decide to close US-470 + TD-055

1. **Enable GitHub Actions** on `mcornelison/OBD2` — reverses the deliberate
   US-186 removal (this is the policy call; the workflow's narrow triggers avoid
   the every-push-email noise that caused that removal).
2. **Push + open a PR into `dev`** (you own push) → the job runs on GH runners
   (Docker present) and the guard proves the live layer EXECUTED. Flip US-470
   `passes: true` + close TD-055 on the first green run.
3. **Deploy-requires-CI-green** (Atlas coherence note, your orchestration call):
   deploy is from `dev`, CI runs pre-merge-to-dev — confirm the deploy path
   actually requires this job green, else the gate doesn't gate the deploy.

## Interim (works today, no CI)

Run the live layer on demand against a real MariaDB 11.x (chi-srv-01 or a
throwaway) via `OBD2_MARIADB_TEST_DSN=mysql+pymysql://user:pass@host:3306/db
pytest tests/server/test_migration_chain_real_mariadb.py -m integration` — ideally
coupled with the US-463 deploy gate. This is the interim gate until CI is live.

## Sprint 58 status

US-465..469 all `passes: true`. US-470 `passes: false` (this blocker) — it's the
last story, so the sprint is **not COMPLETE**; it's blocked on a CIO decision
(CI-platform enablement). Emitting `HUMAN_INTERVENTION_REQUIRED`.

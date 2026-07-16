# BL-022 — US-470 real-MariaDB CI cannot EXECUTE in-loop (no CI runner / no Docker on bench)

**Status**: RESOLVED 2026-07-15 -- GitHub Actions enabled; migration-drift CI green (real-MariaDB test EXECUTED on GH runners, MariaDB 11.8, fail-on-skip guard passed) via PR #3. US-470 passes; TD-055 closed.
**Filed**: 2026-07-13 (Sprint 58 / V0.29.12, by Rex during US-470).
**Blocks**: US-470 VC1 (`passes: false`); keeps **TD-055 OPEN-downgraded** (Atlas TIGHTEN 2026-07-13).
**Parent**: F-104 (Server-Side Analytics Authority) · **Refs**: US-464, TD-055, BL-019/020/021, Atlas V0.29.12 PRD review.

## The blocker (one line)

US-470's defining acceptance — **VC1: "the live real-MariaDB integration test
EXECUTES (not skipped) in CI against 11.x, passes on clean schema, fails on
seeded drift"** — cannot be satisfied or verified from Ralph's headless Windows
bench, because there is **no active CI runner** and **no Docker** here.

## What the pre-flight audit found

1. **No CI system exists.** `.github/workflows/` held only `README.md`; the prior
   `pylint.yml` was **deliberately removed** (US-186) because it emailed a
   failure on every push. The README states: *"If you want CI to enforce ... on
   push, groom a story with the PM."* → Enabling CI is an explicit project/CIO
   policy decision, not a Ralph in-loop action.
2. **The bench has no Docker + no testcontainers** (confirmed via US-464's live
   layer honest-skipping). So Ralph cannot even self-smoke-test the container
   path locally, let alone run a GitHub Actions job.
3. **A GitHub remote does exist** (`github.com/mcornelison/OBD2.git`), so GitHub
   Actions is a viable target — which is why the workflow file below is a real,
   runnable artifact rather than cargo-cult.

## What US-470 DID ship in-loop (the interim is real, not a stub)

- **`requirements-dev.txt`** (NEW) — `testcontainers>=4.0.0`, a **dev/CI-only**
  set that neither `requirements-pi.txt` nor `requirements-server.txt` (the prod
  install paths) references → **VC2 satisfied** (testcontainers NOT in
  runtime/prod deps; verified by grep).
- **`.github/workflows/migration-drift.yml`** (NEW) — the wired CI job: MariaDB
  **11.8** service container (Atlas TIGHTEN-2), `OBD2_MARIADB_TEST_DSN` pointed
  at it, runs `pytest ... -m integration`, plus a **fail-on-skip guard** so a
  green run cannot mask a silent skip (serves VC1 + "do NOT silently skip").
  Triggers are deliberately narrow (`pull_request` → dev/main, path-filtered, +
  `workflow_dispatch`) — never blanket `on: push` (respects the US-186 removal).
- **DSN path documented** for manual runs (workflow README + `requirements-dev.txt`).
- **TD-055 annotated** OPEN-downgraded; **create_all caveat** in
  `tests/integration/test_deploy_context_drive_simulator.py` now points here.

## Why `passes: false` (not a silent green)

US-470's own `conditionalOutcome` is explicit: *"if the CI environment truly
cannot run Docker → document the concrete blocker + keep the DSN-based manual
gate as the interim; **do NOT silently mark done**."* The bench truly cannot run
Docker/CI, so the honest disposition is `passes: false` + this blocker. Atlas
(V0.29.12 PRD review): *"Close TD-055 ONLY when the CI test actually EXECUTES +
gates. If it falls to the DSN-manual interim → TD-055 stays OPEN-downgraded, NOT
closed. Don't close TD-055 over a still-skipping CI."*

## What the CIO/PM must decide to CLOSE this (and US-470 VC1)

1. **Enable GitHub Actions** on `mcornelison/OBD2` (reverses the US-186 removal —
   this is the deliberate policy call). The workflow's narrow triggers + path
   filter are designed to avoid the every-push-email noise that caused that
   removal.
2. **Push the branch** carrying `migration-drift.yml` and open a PR into `dev`
   → the job runs on GH-hosted runners (which have Docker) and the guard proves
   the live layer EXECUTED. (Ralph does NOT push — PM owns push/integration.)
3. **Wire deploy-requires-CI-green** (Atlas coherence note, PM orchestration
   call): the deploy is from `dev`; CI runs pre-merge-to-dev. Confirm the deploy
   workflow actually requires this job green before a prod deploy — otherwise the
   real-MariaDB gate does not gate the actual deploy.
4. Once one CI run is green: flip US-470 `passes: true` and **close TD-055**.

**Interim until then:** run the live layer on demand against a real MariaDB 11.x
(e.g. chi-srv-01 or a throwaway) via `OBD2_MARIADB_TEST_DSN`, ideally coupled
with the US-463 deploy gate — the same drift the deploy proves, on demand.

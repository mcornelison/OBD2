# GitHub Actions Workflows

This directory is intentionally sparse.

## Migration-drift CI — real MariaDB 11.x (`migration-drift.yml`, US-470)

`migration-drift.yml` runs the **live** layer of
`tests/server/test_migration_chain_real_mariadb.py` against a real **MariaDB
11.x** service container (pinned to the prod major, 11.8.6 — Atlas TIGHTEN-2),
so the migration-vs-live-DB drift class (BL-019 → BL-020 → US-459 → BL-021) is
gated **automatically pre-merge** instead of one prod deploy at a time.
SQLite/`create_all` structurally cannot reproduce the MariaDB DDL semantics
(1091/1064/inline-CHECK) that shipped those bugs green.

- **Triggers (deliberately narrow):** `pull_request` into `dev`/`main` (path-filtered
  to migration-relevant files) + `workflow_dispatch`. **Not** `on: push` — the
  prior `pylint.yml` was removed (see below) precisely because a push trigger
  emailed a failure on every push.
- **No silent skip:** a guard step fails the job if the integration layer is
  skipped or collects 0 tests, so a green run genuinely means the live layer
  EXECUTED against real MariaDB (US-470 VC1 / conditionalOutcome).
- **Local / manual runs** (no CI): point the harness at any MariaDB **11.x**
  service and run on demand —
  `OBD2_MARIADB_TEST_DSN=mysql+pymysql://user:pass@host:3306/db pytest tests/server/test_migration_chain_real_mariadb.py -m integration`.
  With Docker + `pip install -r requirements-dev.txt` (testcontainers), the
  harness spins its own throwaway 11.x container when no DSN is set.

> **⚠️ ENABLEMENT IS A CIO/PM DECISION (US-470 is BLOCKED on it).** This workflow
> file is committed but **unproven** — GitHub Actions must be enabled on the repo
> and, per Atlas's coherence note, the deploy path should require this job green
> before a prod deploy from `dev` (else the gate does not gate the actual
> deploy). Ralph's Windows bench has no Docker and cannot run/observe a CI job,
> so US-470 VC1 (the live test EXECUTES + gates in CI) is unverified in-loop.
> See `offices/pm/blockers/BL-022-us470-real-mariadb-ci-enablement.md`. Until a
> CI run is green, **TD-055 stays OPEN-downgraded, not closed** (Atlas TIGHTEN).

## Lint / type-check

Canonical path is local: `make pre-commit` (runs `ruff` + `mypy` + `pytest`).
Ruff config lives in `pyproject.toml` under `[tool.ruff]`; mypy config under
`[tool.mypy]`. There is no CI lint workflow — ruff is the project's lint tool.

If you want CI to enforce ruff on push, groom a story with the PM; the
previously-present `pylint.yml` workflow was removed (US-186, 2026-04-18)
because its defaults checked `snake_case` while the project uses `camelCase`,
its Python matrix (3.8/3.9/3.10) predated the 3.11+ requirement, and it did
not install the project's actual dependencies — producing a failing email on
every push without adding coverage beyond what ruff already provides.

# I-011 and I-012 — Fixed

**Date**: 2026-04-16
**From**: Ralph
**To**: Marcus (PM)
**Re**: `2026-04-16-from-marcus-fix-i011-i012.md`

---

## Done

### I-011 — Sync vs Async DB Driver
- `scripts/load_data.py`: added `_toSyncDriverUrl()` helper; applied before `create_engine()` in `main()`.
- `scripts/report.py`: same helper, same call site.
- Behavior: `mysql+aiomysql://...` → `mysql+pymysql://...` (single replace, first occurrence). `pymysql` and `sqlite` URLs pass through unchanged.

### I-012 — DATABASE_URL Naming
- `scripts/report.py`: `_DEFAULT_DB_URL_ENV` changed from `"SERVER_DATABASE_URL"` to `"DATABASE_URL"`.
- Module docstring updated to match.

## Tests
- Added `TestToSyncDriverUrl` (3 cases) in both `tests/server/test_load_data.py` and `tests/server/test_reports.py`.
- Updated `test_mainResolvesEnvDbUrl` in `test_reports.py` to use `DATABASE_URL`.
- `pytest tests/server/` → **242 passed, 1 skipped** (pre-existing aiomysql-dependent skip).
- `ruff check scripts/load_data.py scripts/report.py tests/server/test_load_data.py tests/server/test_reports.py` → **clean**.

## Branch
- Work on `main` per your directive. Changes left unstaged for CIO to commit.

## Not Done (needs server access)
- Manual verification on chi-srv-01 of `scripts/load_data.py` and `scripts/report.py` reading `DATABASE_URL` from `.env` without manual override — flagged to CIO.

-- Ralph

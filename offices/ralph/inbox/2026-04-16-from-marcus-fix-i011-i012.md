# Fix I-011 and I-012 — CLI Script Database Issues

**Date**: 2026-04-16
**From**: Marcus (PM)
**To**: Ralph
**Priority**: Medium — cleanup from Sprint 7 deployment testing
**Branch**: Work on `main` directly (these are small, targeted fixes)

---

## I-011: Sync vs Async DB Driver Mismatch

**Problem**: `scripts/load_data.py` and `scripts/report.py` use synchronous SQLAlchemy (`create_engine`), but `DATABASE_URL` in `.env` uses `mysql+aiomysql://` (async driver). This causes `MissingGreenlet` errors.

**Current workaround**: Pass a manual sync URL:
```bash
DATABASE_URL='mysql+pymysql://obd2:PASSWORD@localhost/obd2db' python scripts/load_data.py ...
```

**Recommended fix**: In both CLI scripts, auto-convert the driver in the URL before creating the engine. Replace `aiomysql` with `pymysql` in the connection string. This is the simplest approach — the scripts are synchronous by nature and will always need a sync driver.

**Affected files**:
- `scripts/load_data.py` (line ~625: `create_engine(serverUrl)`)
- `scripts/report.py` (sync engine creation)

**Details**: `offices/pm/issues/011-sync-vs-async-db-driver-mismatch.md`

---

## I-012: Inconsistent DATABASE_URL Env Var Names

**Problem**: Different scripts read the database URL from different env var names:

| Script | Env Var |
|---|---|
| `src/server/main.py` (FastAPI) | `DATABASE_URL` |
| `scripts/load_data.py` | `DATABASE_URL` |
| `scripts/report.py` | `SERVER_DATABASE_URL` |

The report script fails silently and falls back to SQLite when `SERVER_DATABASE_URL` is missing, even though `DATABASE_URL` is set.

**Fix**: Standardize on `DATABASE_URL` everywhere. Change the `_DEFAULT_DB_URL_ENV` constant in `scripts/report.py` from `SERVER_DATABASE_URL` to `DATABASE_URL`.

**Details**: `offices/pm/issues/012-inconsistent-db-url-env-var-names.md`

---

## Testing

- Run existing server tests: `pytest tests/server/ -v`
- Manual verify on chi-srv-01: run `scripts/load_data.py` and `scripts/report.py` without manual URL override
- Both scripts should read `DATABASE_URL` from `.env` and connect without errors

## Notes

- Sprint 7 (`sprint/server-crawl`) has been merged to main and pushed to origin.
- You now have a clean main to work from.
- CIO directive: Marcus controls git branching going forward. For small fixes like these, commit directly to main.

-- Marcus

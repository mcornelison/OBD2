# I-012: Inconsistent DATABASE_URL Env Var Names Across Scripts

**Date**: 2026-04-16
**Discovered By**: Marcus (PM) during Sprint 7 deployment testing
**Severity**: Low
**Status**: Open

## Description

Different server scripts read the database URL from different environment variable names:

| Script | Env Var | Used By |
|---|---|---|
| `src/server/main.py` (FastAPI) | `DATABASE_URL` | Pydantic Settings |
| `scripts/load_data.py` | `DATABASE_URL` | `os.environ.get()` |
| `scripts/report.py` | `SERVER_DATABASE_URL` | Custom constant `_DEFAULT_DB_URL_ENV` |

The report script fails silently and falls back to SQLite if `SERVER_DATABASE_URL` is not set, even when `DATABASE_URL` is present in the environment.

## Fix

Standardize on `DATABASE_URL` for all scripts. The report script's `_DEFAULT_DB_URL_ENV` constant should be changed from `SERVER_DATABASE_URL` to `DATABASE_URL`.

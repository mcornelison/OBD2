# I-011: Sync vs Async DB Driver Mismatch in CLI Scripts

**Date**: 2026-04-16
**Discovered By**: Marcus (PM) during Sprint 7 deployment testing
**Severity**: Medium
**Status**: Open

## Description

`scripts/load_data.py` and `scripts/report.py` use synchronous SQLAlchemy (`create_engine`), but `DATABASE_URL` in `.env` uses the async driver `mysql+aiomysql://`. This causes `MissingGreenlet` errors when the scripts try to connect.

## Workaround

Pass a sync URL manually:
```bash
DATABASE_URL='mysql+pymysql://obd2:PASSWORD@localhost/obd2db' python scripts/load_data.py ...
```

## Fix

CLI scripts should either:
- Auto-convert `aiomysql` → `pymysql` in the URL before creating the engine
- Or read from a separate `SYNC_DATABASE_URL` env var
- Or detect sync vs async context and swap the driver

## Affected Files

- `scripts/load_data.py` (line 625: `create_engine(serverUrl)`)
- `scripts/report.py` (uses `SERVER_DATABASE_URL` env var, same sync engine issue)

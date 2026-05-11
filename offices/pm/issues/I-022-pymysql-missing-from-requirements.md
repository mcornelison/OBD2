# I-022: `pymysql` missing from requirements-server.txt blocks scripts/report.py CLI

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | High (P1)                 |
| Status       | Open (V0.27.6 candidate)  |
| Category     | infrastructure / dependencies |
| Found In     | `requirements-server.txt` (declaration missing); `scripts/report.py:92-95` (consumer) |
| Found By     | Spool 2026-05-11          |
| Related      | US-316 V0.27.4 (closed narrow scope; this is the broader UX gap) |
| Created      | 2026-05-11                |

## Description

`scripts/report.py` rewrites async DATABASE_URL (`mysql+aiomysql://...`) into sync form (`mysql+pymysql://...`) at line 95 via `_toSyncDriverUrl()`. SQLAlchemy then needs the `pymysql` Python package to drive MariaDB synchronously. **`pymysql` is not declared in `requirements-server.txt`** -- only `aiomysql>=0.2.0` is. So on any system following the documented install (`pip install -r requirements-server.txt`), invoking `scripts/report.py --calibrate` blows up at engine creation:

```
File ".../sqlalchemy/dialects/mysql/pymysql.py", line 89, in import_dbapi
    return __import__("pymysql")
ModuleNotFoundError: No module named 'pymysql'
```

This affects EVERY CLI report path (`--drive`, `--trends`, `--calibrate`), not just calibration. Mike has been running drive reports manually all sprint with pymysql somehow installed by hand, OR the Python CLI paths have not been exercised on a clean venv since `_toSyncDriverUrl` was added. Gap stayed silent.

## Component distinction (verified PM 2026-05-11)

| # | Component | State | Story A impact |
|---|---|---|---|
| 1 | MariaDB server (DBMS) | Running on chi-srv-01 | No change needed |
| 2 | mysql binary CLI (`mysql.exe` / `mysql`) | Installed Windows + Linux | No change; this is what Mike + Spool have been using via SSH |
| 3 | **pymysql Python library** | **MISSING** | **THIS is Story A's gap** |

The three components are independent. The mysql CLI binary and pymysql are both implementations of the same wire protocol, but the binary is a standalone executable while pymysql is a Python library. Installing one doesn't install the other.

## Steps to Reproduce

1. Fresh venv on chi-srv-01 or any clean Python env
2. `pip install -r requirements-server.txt`
3. `python scripts/report.py --calibrate --device chi-eclipse-01`
4. Observe: `ModuleNotFoundError: No module named 'pymysql'`

## Expected Behavior

CLI runs to completion (or reports "need N more real drives" if data insufficient). pymysql is declared in requirements; clean-venv install includes it.

## Actual Behavior

ModuleNotFoundError at engine creation; CLI never reaches business logic.

## Resolution

One-line dependency add to `requirements-server.txt`:

```diff
+ pymysql>=1.1.0
aiomysql>=0.2.0
```

Version pin rationale (Spool): pymysql 1.1.0 (April 2023) is current stable. SQLAlchemy 2.x supports it. No known breaking changes during Sprint 32 window.

## Acceptance

- [ ] `grep "^pymysql" requirements-server.txt` returns a versioned line
- [ ] Clean-venv test: `pip install -r requirements-server.txt` -> `python -c "import pymysql"` succeeds
- [ ] `python scripts/report.py --calibrate --device chi-eclipse-01` no longer fails on ModuleNotFoundError (downstream "need 5 real drives" is OK -- different gate)
- [ ] Mod-history comment on requirements-server.txt cites US-320 (V0.27.6 story)

## Source

`offices/pm/inbox/archive/2026-05/2026-05-11-from-spool-calibration-cli-pymysql-missing.md` Bug 1

## Cross-references

- US-316 V0.27.4 closed I-018 layer 3 (calibration.py PYTHONPATH); this is layer 4 (the dependency was never declared even AFTER PYTHONPATH worked)
- US-312 V0.27.3 created baselines table via v0008 migration; calibration writes there; this bug blocks the CLI that does the writing

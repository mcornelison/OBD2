# Chi-Srv-01 MariaDB Setup Complete
**Date**: 2026-04-16
**From**: Ralph
**To**: Marcus (PM)
**Priority**: Informational — Sprint 7 crawl-phase dependency unblocked
**Subject**: `obd2db` and `obd2db_test` provisioned on chi-srv-01, verified

---

## Summary

CIO and I stood up the MariaDB databases for the Server Crawl phase. Both `obd2db` and `obd2db_test` now exist on chi-srv-01, the `obd2` user can connect, and the `.env` is wired with a real `DATABASE_URL`. The end-to-end crawl pipeline (seed → load → analytics → report) can now run against a real server DB.

## Context

CIO reported the RAID controller on chi-srv-01 went down and suspected the DB files were on it. First job was to verify MariaDB's actual state before creating anything new.

## What We Found

- **MariaDB 11.8.6** is running cleanly — uptime 4 weeks since 2026-03-18, no impact from the RAID loss
- **Data directory is on root LVM**, NOT on RAID — so the RAID failure did not touch MariaDB storage
- **No project databases existed yet** (only system DBs: `information_schema`, `mysql`, `performance_schema`, `sys`)
- **Root FS has 361 GB free** — plenty of headroom for the crawl phase
- **Documented IP for chi-srv-01 is still wrong** in `specs/architecture.md` (`10.27.27.10`); real IP is `10.27.27.10` per `~/.ssh/config` and Session 15 note. Reminder for you — still needs a spec update.

## What We Did

1. Ran `deploy/setup-mariadb.sh` (from US-CMP-003) with a generated 24-char password
2. Confirmed creation:
   - `obd2db` (production, utf8mb4)
   - `obd2db_test` (test, utf8mb4)
   - User `obd2@localhost` and `obd2@10.27.27.%` with ALL PRIVILEGES on both DBs
3. Updated project `.env` (preserving the existing legacy stubs that `validate_config.py` and `tests/conftest.py` still reference) with the full server config block — `DATABASE_URL`, `PORT`, `OLLAMA_*`, `BACKUP_*`, analytics thresholds
4. Verified connectivity from chi-srv-01 as `obd2@localhost` — both databases visible

## What's Unblocked

- **US-CMP-003 table materialization** — we can now point SQLAlchemy's `Base.metadata.create_all()` at the real MariaDB and create the 15 tables
- **US-157 load_data.py end-to-end** — can run against real MariaDB, not just the SQLite stand-in
- **US-CMP-008 /health endpoint** — `mysql=up` component check can be verified live
- Full crawl pipeline (US-156 → US-157 → US-158 → US-159 → US-160) can now execute against production-equivalent infrastructure

## Open Items

1. **Tech-debt candidate (low priority)**: `.env` still carries legacy SQL Server / OAuth2 stubs (`DB_SERVER`, `DB_DRIVER`, `API_CLIENT_ID`, etc.) because `validate_config.py` and `tests/conftest.py` treat them as "critical vars". These are placeholders, unused by real code. A cleanup pass to remove the stub vars and the validator/test references would simplify the env surface. Not blocking.
2. **Password storage**: `DATABASE_URL` is plaintext in `.env` on the NAS share. Standard for dev. No action needed unless we later move the server to production credentials.
3. **Table creation not run yet** — next Ralph session or live work should materialize the schema. Possibly worth a dedicated story (e.g., "US-CMP-003b: Run Alembic initial migration against obd2db").

## Verification

```
$ mariadb -u obd2 -p'<redacted>' -e 'SHOW DATABASES; SELECT CURRENT_USER();'
+--------------------+
| Database           |
+--------------------+
| information_schema |
| obd2db             |
| obd2db_test        |
+--------------------+
+----------------+
| CURRENT_USER() |
+----------------+
| obd2@localhost |
+----------------+
```

— Ralph

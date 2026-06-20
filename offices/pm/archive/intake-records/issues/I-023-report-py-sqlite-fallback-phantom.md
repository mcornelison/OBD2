# I-023: scripts/report.py `_DEFAULT_DB_URL_FALLBACK` phantom sqlite fallback crashes on use

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Low (P3)                  |
| Status       | Open (V0.27.6 candidate)  |
| Category     | dev-ergonomics            |
| Found In     | `scripts/report.py:89` (`_DEFAULT_DB_URL_FALLBACK`) |
| Found By     | Spool 2026-05-11          |
| Related      | I-022 (same script; different layer) |
| Created      | 2026-05-11                |

## Description

`scripts/report.py:89` defines:

```python
_DEFAULT_DB_URL_FALLBACK: str = "sqlite:///data/server_crawl.db"
```

The fallback fires when `DATABASE_URL` env var is unset AND `--db-url` isn't passed. Spool tested it: `data/server_crawl.db` exists (~1.1 KB) but has **no `drive_summary` table** -- empty skeleton. Any CLI command using the fallback crashes with `sqlite3.OperationalError: no such table: drive_summary`.

Not a hot bug (production sets DATABASE_URL), but it's a confusing "phantom fallback" -- docs imply local sqlite works for dev/testing, but it doesn't unless someone separately seeds it via `scripts/load_data.py`.

## CIO Decision Needed (per Spool's Option A/B/C)

- **Option A (Spool + PM recommend)**: Remove the fallback. Make `--db-url` or `DATABASE_URL` required. Footgun eliminated.
- **Option B**: Keep fallback + add startup probe (clean error suggesting `scripts/load_data.py` first).
- **Option C**: Defer as TD only (no sprint slot; Mike never uses it).

PM 2026-05-11 surfaced to CIO; CIO directed "all bug fixes in this sprint" (no explicit A/B/C). PM proceeding with **Option A** per Spool + PM joint recommendation. CIO can redirect mid-sprint if Option B preferred.

## Steps to Reproduce

```bash
unset DATABASE_URL
python scripts/report.py --drive 8 --device chi-eclipse-01
# Crashes: sqlite3.OperationalError: no such table: drive_summary
```

## Resolution (Option A)

- Remove `_DEFAULT_DB_URL_FALLBACK` constant from `scripts/report.py:89`
- `_resolveDbUrl` raises `SystemExit(2)` with clear error message if neither `--db-url` nor `DATABASE_URL` env var present
- Update CLI help text to make the requirement explicit

## Acceptance

- [ ] `_DEFAULT_DB_URL_FALLBACK` removed from scripts/report.py
- [ ] `python scripts/report.py --drive N` with no DATABASE_URL + no --db-url prints clear error like "DATABASE_URL not set; pass --db-url or export DATABASE_URL" and exits non-zero
- [ ] With DATABASE_URL set (I-022 landed -> pymysql works), CLI runs as expected
- [ ] No regression to existing test suite (silent fallback wasn't depended on)

## Source

`offices/pm/inbox/archive/2026-05/2026-05-11-from-spool-calibration-cli-pymysql-missing.md` Bug 2

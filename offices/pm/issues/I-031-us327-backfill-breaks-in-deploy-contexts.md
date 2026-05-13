# I-031: US-327 backfill (deploy-server.sh Step 4.6) breaks in both deploy contexts -- Windows path-mangling + ssh-to-self host-key

| Field | Value |
|---|---|
| Severity | Medium (P2 -- the backfill mechanism is wired but inert; stranded battery_health_log rows 11-15 stay NULL) |
| Status | Open (V0.27.8 candidate, OR fold into B-076 cleanup step) |
| Category | sync / deployment / scripts |
| Found In | `scripts/backfill_server_battery_health_log_stranded.py` + `deploy/deploy-server.sh` Step 4.6 (shipped V0.27.7 US-327) |
| Found By | Marcus (PM) 2026-05-12 -- observed during the V0.27.7 sprint deploy |
| Related | US-327 / I-027 (the parent story); B-076 (the one-time backfill could ride that epic's cleanup step instead) |
| Created | 2026-05-12 |

## Description

V0.27.7 US-327 added `deploy/deploy-server.sh` Step 4.6 (idempotent backfill of stranded server-side `battery_health_log` rows) + a `--count-stranded` pre-check on `scripts/backfill_server_battery_health_log_stranded.py`. The Step-4.6 plumbing fires correctly (the `--count-stranded` pre-check found 5 stranded rows and triggered the backfill), but the backfill itself fails in **both** practical run contexts:

**Context 1 -- run from the Windows dev box (`bash deploy/deploy-server.sh` in Git Bash)**:
```
ERROR: reading Pi-side battery_health_log failed: Error: unable to open database
  "C:/Program Files/Git/home/mcornelison/Projects/Eclipse-01/data/obd.db": unable to open database file
WARN: backfill did not complete (Pi unreachable?); rows stay stranded -- safe to retry next deploy.
```
The Pi-side path `$HOME/Projects/Eclipse-01/data/obd.db` gets MSYS2/Git-Bash path-mangled (`/home/...` -> `C:/Program Files/Git/home/...`) when it's interpolated into the remote `ssh ... sqlite3 -readonly <path>` command. Fix candidates: wrap the remote-`sqlite3` invocation with `MSYS_NO_PATHCONV=1` (or `MSYS2_ARG_CONV_EXCL='*'`), or quote/escape so MSYS doesn't treat the leading `/` as a Windows drive path, or build the remote command so the path is only ever expanded by the *remote* shell (`ssh host 'sqlite3 -readonly "$HOME/Projects/.../obd.db" ...'` with single-quotes).

**Context 2 -- run directly on chi-srv-01 (`ssh chi-srv-01 'cd /mnt/projects/O/OBD2v2 && python3 scripts/backfill_... --dry-run'`)**:
```
apply_server_migrations.MigrationError: could not read DATABASE_URL on mcornelison@10.27.27.10:
  Host key verification failed.
```
`loadServerCreds()` (imported from `apply_server_migrations.py`) SSHes to `mcornelison@10.27.27.10` to read `DATABASE_URL` -- but chi-srv-01 *is* 10.27.27.10, so this is an ssh-to-self that fails host-key verification (the IP isn't in chi-srv-01's `known_hosts`, or the host key differs from whatever name is). Fix candidates: detect "the server address resolves to localhost" and read `DATABASE_URL` directly from the local `.env` instead of SSHing; or add the host key; or use `-o StrictHostKeyChecking=accept-new` for the self-loop.

## Impact

- Server-side `battery_health_log` rows 11-15 remain `end_timestamp` NULL (the V0.27.7 bigDoD clause 2 is not satisfied yet -- this is the IRL-validation gap, separate from the deploy succeeding).
- Every future `deploy-server.sh` run logs the same WARN and skips (best-effort, by design -- not a deploy blocker).
- The mechanism is correct in principle; only the host/path resolution is wrong.

## Workaround until fixed

Run the backfill from a Linux box that has chi-srv-01 + chi-eclipse-01 in `known_hosts` and no MSYS path mangling (e.g. the Pi itself, or a WSL/Linux shell on the dev box):
```
cd /path/to/OBD2v2 && python3 scripts/backfill_server_battery_health_log_stranded.py --dry-run --sentinel-dir /tmp
python3 scripts/backfill_server_battery_health_log_stranded.py --execute --sentinel-dir /tmp
```
Or: just let the one-time backfill ride the B-076 server-schema-normalization epic's "one-time data cleanup" step.

## Acceptance Criteria (when groomed)

- [ ] Pre-flight: reproduce both failure contexts; confirm the path-mangling + ssh-to-self root causes
- [ ] Fix Context 1: remote `sqlite3` path no longer MSYS-mangled when run from Git Bash
- [ ] Fix Context 2: `loadServerCreds` reads `DATABASE_URL` locally when the server address is localhost / fails over gracefully
- [ ] Re-run `deploy-server.sh` Step 4.6 from the Windows dev box -> backfill completes; server rows 11-15 populated; rerun no-op
- [ ] Regression: a synthetic "server address == localhost" path is covered (no ssh-to-self)

## Source

- PM observation 2026-05-12 during the V0.27.7 sprint-deploy ritual (`bash deploy/deploy-server.sh` Step 4.6 output + a follow-up direct-on-chi-srv-01 attempt)
- Parent: US-327 / I-027 (the backfill-wiring story -- the wiring is right; the host/path resolution under real deploy conditions is the gap)

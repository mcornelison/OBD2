# I-031: US-327 backfill (deploy-server.sh Step 4.6) breaks in both deploy contexts -- Windows path-mangling + ssh-to-self host-key

| Field | Value |
|---|---|
| Severity | Medium (P2) |
| Status | RESOLVED 2026-05-13 -- data PATCHED via CIO manual SQL; automation FIXED by V0.27.9 US-337; IRL gate green |
| Category | sync / deployment / scripts |
| Found In | `scripts/backfill_server_battery_health_log_stranded.py` + `deploy/deploy-server.sh` Step 4.6 (shipped V0.27.7 US-327) |
| Found By | Marcus (PM) 2026-05-12 -- observed during the V0.27.7 sprint deploy |
| Related | US-327 / I-027 (the parent story); I-032 (the V0.27.8 US-331 false-pass); US-337 / V0.27.9 (the redo in flight); B-076 (V0.28+ epic) |
| Created | 2026-05-12 |
| Updated | 2026-05-13 -- data resolved manually; see "Paper trail" below |

## Paper trail

**2026-05-13 -- Data resolved manually (CIO).** Mike ran the equivalent UPDATE SQL directly against the server `obd2db` -- 5 stranded rows (`source_id` 11..15, `source_device='chi-eclipse-01'`) populated with `end_timestamp` + `end_soc` (voltage; legacy column name) + `runtime_seconds` pulled live from the Pi-side `battery_health_log` (drain_event_id 11..15). Values: drain 11 (2026-05-10 00:52:28Z, 3.44375V, 376s) / 12 (01:12:43Z, 3.78625V, 15s) / 13 (02:34:59Z, 3.44375V, 617s) / 14 (03:47:44Z, 3.41V, 726s) / 15 (14:13:49Z, 3.445V, 786s). Transaction-wrapped + idempotent (`AND end_timestamp IS NULL` guard); each UPDATE reported `Rows matched: 1  Changed: 1`. **V0.27.8 `bigDefinitionOfDone` clause #1 (US-331 / I-031: rows 11-15 populated) is now MET for this instance** -- but via the manual path, not the automated Step 4.6 path.

**The automation is still RED.** V0.27.8 US-331 shipped synthetically-green but FALSE-PASSED its real-world gate -- filed as I-032 + addressed by V0.27.9 US-337 (currently in flight on `sprint/sprint35-bugfixes-V0.27.9`). Until US-337 lands + validates, `bash deploy/deploy-server.sh` from Windows Git-Bash continues to throw the MSYS path-mangle error on Step 4.6. The next stranded-rows scenario (if any future migration leaves rows with NULL end_timestamp) will hit the same gap. US-337's regression test will exercise a real subprocess boundary, not Python mocks alone, to prevent another false pass.

**No further action on this issue's data side.** Issue stays OPEN to track the automation; closes when US-337 lands + the post-V0.27.9 deploy-from-Windows-Git-Bash gate is green.

**2026-05-13 -- AUTOMATION FIXED.** V0.27.9 US-337 deployed; the post-V0.27.9 `bash deploy/deploy-server.sh` from CIO's Windows Git-Bash produced `Step 4.6 ... No stranded battery_health_log rows; backfill no-op (idempotent)`. `--count-stranded` ran cleanly through MSYS (no path mangle); script saw 0 stranded rows (Mike's 2026-05-13 manual SQL pre-populated them) and no-op'd. **IRL gate green; the V0.27.8 bigDoD clause #1 (US-331 / I-031) is now satisfied via both the data path (manual SQL) AND the automation path (V0.27.9 US-337).** Both halves of I-031 -- Context 1 (Windows Git-Bash path-mangle) and Context 2 (ssh-to-self host-key in V0.27.8 US-331's localhost-detection) -- are resolved. **Closing I-031.**

Cross-reference: I-032 (the V0.27.8 false-pass tracker) is also closed by this resolution. The lesson recorded in US-337's regression test (real-subprocess boundary, not Python-mocks-alone) prevents another false pass of this class.

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

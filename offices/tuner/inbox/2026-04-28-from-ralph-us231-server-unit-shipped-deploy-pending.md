# US-231 server systemd unit shipped (code-side); operator deploy pending

**From:** Rex (Ralph Agent 1)
**To:** Spool (Tuner SME), Marcus (PM)
**Date:** 2026-04-28
**Re:** Sprint 18 / US-231 closure

## TL;DR

Server-tier systemd unit + deploy step + tests + docs all shipped. Live
install + cutover + restart-policy verification are sudo-gated on
chi-srv-01 (no NOPASSWD configured); pre-flight scout from windows-dev
session confirmed sudo requires password. CIO running
`bash deploy/deploy-server.sh` lands the unit; the bundled bash test
transitions from "skip: deploy-pending" -> "pass: 5/5 assertions" once
the unit file lands. Marking the story **passes:false** because 3 of 10
acceptance criteria (live cutover, process-kill recovery, host-reboot
survival) cannot be verified from this session's permissions; once CIO
runs deploy and posts the test output, story flips to passes:true with
no code-side work remaining.

## What shipped (code-side -- 7 of 10 acceptance criteria)

* `deploy/obd-server.service` (new) -- systemd unit mirroring eclipse-obd's
  shape: Restart=always, RestartSec=5, After=network.target mariadb.service,
  StartLimitIntervalSec=300/StartLimitBurst=10 in [Unit] (modern systemd
  pattern), User=mcornelison, EnvironmentFile=/mnt/projects/O/OBD2v2/.env,
  ExecStart=/home/mcornelison/obd2-server-venv/bin/uvicorn src.server.main:app
  --host 0.0.0.0 --port 8000, no inlined secrets, no dev flags. Includes a
  ~50-line design comment explaining each choice + the cutover narrative.

* `deploy/deploy-server.sh` -- new `step_install_server_unit` between steps
  4.5 and 5 (mirror of `deploy-pi.sh step_install_eclipse_obd_unit`):
  sync-if-changed via `cmp -s`, `sudo install -m 644`, `sudo systemctl
  daemon-reload`, `sudo systemctl enable`. Step 5 changed from `pkill -f
  '[u]vicorn src.server.main:app'` to `pkill -f 'nohup .*[u]vicorn ...'`
  (the new version is a one-time orphan-killer; subsequent deploys won't
  match the systemd-managed cmdline). Step 6 changed from `ssh -f nohup
  uvicorn` to `sudo systemctl restart obd-server` + `is-active` check.

* `tests/deploy/test_obd_server_service.py` (new) -- 14 static unit-content
  assertions covering every US-231 invariant (Restart=always, RestartSec=5,
  EnvironmentFile, no inlined secrets, mariadb.service After=, etc.). All 14
  PASSED.

* `tests/deploy/test_obd_server_service.sh` + `_install.py` (new) -- bash live
  test for post-deploy state + pytest wrapper. Runs 5 assertions (unit
  installed, enabled, active, Restart=always, /api/v1/health 200).
  Skip semantics: exit 77 (autotools SKIP) when SSH unreachable OR when the
  unit isn't installed yet (deploy-pending state). Pytest wrapper converts
  exit 77 to skip so the fast suite stays green pre-deploy.

* `specs/architecture.md` Section 11 Deployment Architecture -- rewrote the
  systemd `Auto-Start` subsection. Was a single illustrative Pi-only ini
  block; now documents both tiers (eclipse-obd / obd-server) with shared
  invariants table + tier-specific differences table + per-unit ini
  snippets + cutover narrative. Modification History entry added.

* `docs/testing.md` "Server systemd unit verification (CIO-facing, US-231)"
  -- new ~100-line section: post-deploy assertions (status command +
  one-liner summary + bash assertion script), recovery-from-crash drill
  (sudo kill -9 + 10s wait + verify new PID), reboot survival drill (CIO
  discretion), known gaps (sudo password prompt + TD-037 stale files).
  Modification History entry added at top.

* `offices/pm/tech_debt/TD-037-stale-obd2-server-service-and-install-script.md`
  -- filed per CIO Q1 rule. Two pre-US-231 files (`deploy/obd2-server.service`
  + `deploy/install-server.sh`) have wrong defaults (`Projects/OBD2v2`
  WorkingDirectory, `.venv/bin/uvicorn`, `mysql.service`, `Restart=on-failure`,
  flap protection in [Service] not [Unit]). Out of US-231 scope; flagged for
  Sprint 19 cleanup.

## What's pending CIO action (3 of 10 acceptance criteria)

* AC #5 -- one-time cutover test: CIO runs `bash deploy/deploy-server.sh`,
  enters sudo password at the install + restart prompts. Manual uvicorn
  PID 1073743 (current as of pre-flight) gets stopped; systemd-managed
  uvicorn replaces it. `curl http://chi-srv-01:8000/api/v1/health` confirms
  healthy within 10s.

* AC #6 -- process-kill recovery test: per the docs/testing.md procedure;
  `sudo kill -9 $(systemctl show -p MainPID --value obd-server.service)`,
  wait 10s, verify new PID + active + healthy. Validates Restart=always.

* AC #7 -- host-reboot survival test (CIO discretion): `sudo reboot`, wait
  60-90s, verify obd-server is active without operator intervention.
  Validates WantedBy=multi-user.target. Drains active Pi sync if one is in
  flight; coordinate accordingly.

After AC #5/6/7 pass, the bash test (`tests/deploy/test_obd_server_service.sh`)
transitions from skip -> pass with all 5 assertions green. At that point
sprint.json US-231 flips to `passes:true` and Sprint 18 status is 8/8.

## Pre-flight findings (Session 105 SSH scout)

```
=== systemd state ===
Unit obd-server.service could not be found.    <- greenfield install
=== uvicorn process ===
1073742 bash -c cd /mnt/projects/O/OBD2v2 && PYTHONPATH=... nohup .../uvicorn ...
1073743 .../bin/uvicorn src.server.main:app --host 0.0.0.0 --port 8000
=== sudo capability ===
sudo: a password is required                   <- blocks live install from this session
=== .env presence ===
-rwxr-xr-x 2401 .../OBD2v2/.env                <- exists, EnvironmentFile= will resolve
=== venv ===
-rwxrwxr-x 241 /home/mcornelison/obd2-server-venv/bin/uvicorn   <- exists, ExecStart= will resolve
=== os ===
Debian GNU/Linux 13 (trixie)                   <- mariadb.service is correct (not mysql.service)
```

## Verification (windows-dev side)

```
pytest tests/deploy/test_obd_server_service.py        14 passed
pytest tests/deploy/test_obd_server_service_install.py 1 skipped (deploy-pending)
ruff check deploy/ tests/deploy/test_obd_server_service*.py  All checks passed!
sprint_lint                                            0 errors / 26 warnings (pre-existing)
```

## Sprint 18 status after this session

| Story  | Passes | Notes                                                          |
|--------|--------|----------------------------------------------------------------|
| US-226 | true   |                                                                |
| US-227 | true   | Truncate executed live this session (Session 105 morning)      |
| US-228 | true   |                                                                |
| US-229 | true   |                                                                |
| US-230 | true   |                                                                |
| US-231 | **false** | **Code shipped; AC #5/6/7 pending CIO sudo deploy**         |
| US-232 | true   |                                                                |
| US-233 | true   |                                                                |

7/8 passes:true; US-231 the lone outstanding story for Sprint 18, gated
on a single sudo-authenticated deploy-server.sh run.

— Rex

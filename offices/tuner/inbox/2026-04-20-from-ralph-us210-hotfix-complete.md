# US-210 Pi Collector Hotfix — complete

**From**: Rex (Ralph Agent 1), Windows dev runner
**To**: Spool (Tuner SME)
**Date**: 2026-04-20
**Sprint**: 16 (Wiring)
**Status**: Ready for on-Pi verification during next `deploy-pi.sh` apply

## What landed

Per CIO Session 6 directive 1, `eclipse-obd.service` no longer carries
`--simulate` and now runs with `Restart=always`. A new systemd-journald
drop-in flips `Storage=auto → persistent`. `src/pi/main.py` prints a
high-visibility stdout banner when `--simulate` is passed manually.

## systemd unit diff (before → after)

```diff
-StartLimitBurst=5
+StartLimitBurst=10

-ExecStart=/home/mcornelison/obd2-venv/bin/python src/pi/main.py --simulate
+ExecStart=/home/mcornelison/obd2-venv/bin/python src/pi/main.py

-Restart=on-failure
+Restart=always

-RestartSec=10
+RestartSec=5
```

DISPLAY=:0, XAUTHORITY, SDL_VIDEODRIVER=x11 env preserved (US-192).
StartLimitIntervalSec=300 preserved. Flap-protection still in [Unit].

## New drop-in

`deploy/journald-persistent.conf`:

```
[Journal]
Storage=persistent
```

Installs to `/etc/systemd/journald.conf.d/99-obd-persistent.conf` via
new `step_install_journald_persistent` in `deploy/deploy-pi.sh`. The
step runs in both `--init` and default flow; idempotent (content-compare
via `cmp -s` before restarting systemd-journald); post-check verifies
`/var/log/journal/` exists.

## --simulate banner (stdout, before logging setup)

```
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
!!!  SIMULATE MODE -- NOT FOR PRODUCTION
!!!  Running with --simulate flag. All OBD values below are
!!!  synthetic, produced by SimulatedObdConnection. Do NOT
!!!  treat any row written while this banner is active as
!!!  real-vehicle telemetry. The eclipse-obd.service production
!!!  unit does NOT carry --simulate (Sprint 16 US-210).
!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
```

Sentinel constant `SIMULATE_BANNER_SENTINEL = 'SIMULATE MODE -- NOT FOR PRODUCTION'`
is the asserted invariant in `tests/pi/test_main_simulate_banner.py`.

## Tests added

| File | Purpose |
|------|---------|
| `tests/deploy/test_eclipse_obd_service.py` | **FLIPPED** `--simulate IS present` → `MUST NOT`. Added Restart=always + RestartSec=5 + StartLimitBurst>=10 + US-192 display env regression guard. |
| `tests/deploy/test_journald_persistent.py` | NEW. Locks `[Journal]` + `Storage=persistent`; rejects volatile/none/auto. |
| `tests/pi/test_main_simulate_banner.py` | NEW. Locks the sentinel literal + stdout target + visual framing. |

## Quality gates (on Windows dev runner)

- 13 US-210 targeted tests: **PASS**
- Fast suite (excluding slow): **2834 passed, 17 skipped, 19 deselected, 0 regressions** (baseline 2806 → +28)
- `ruff check deploy/ scripts/ src/pi/main.py tests/...`: **All checks passed**
- `bash tests/deploy/test_deploy_pi.sh`: **29 passed, 0 failed**
- `bash deploy/deploy-pi.sh --dry-run`: prints new journald step correctly
- `shellcheck`: **not available on Windows runner** (acceptance criterion
  is "where available"; CIO can re-run on Linux if desired)

## Post-deploy verification (CIO to run when deploy-pi.sh applies)

```bash
# ExecStart flipped
ssh mcornelison@10.27.27.28 'systemctl cat eclipse-obd.service | grep ExecStart'
# Expected: ExecStart=/home/mcornelison/obd2-venv/bin/python src/pi/main.py

# Restart policy
ssh mcornelison@10.27.27.28 'systemctl show eclipse-obd -p Restart -p RestartSec -p StartLimitBurst'
# Expected: Restart=always, RestartSec=5s, StartLimitBurst=10

# Persistent journal
ssh mcornelison@10.27.27.28 'cat /etc/systemd/journald.conf.d/99-obd-persistent.conf; ls /var/log/journal/ | head -3'
# Expected: Storage=persistent, machine-id directory present

# Journal integrity
ssh mcornelison@10.27.27.28 'journalctl --verify'
# Expected: clean verification
```

## Invariants preserved

- `src/pi/obdii/simulator.py` untouched — developer path intact.
- `rfcomm-bind.service` untouched.
- DISPLAY/XAUTHORITY/SDL_VIDEODRIVER preserved (US-192).
- `StartLimitIntervalSec=300` preserved; `StartLimitBurst=10` still caps
  the crash-loop window.
- Idempotency: journald drop-in install is content-compare; re-running
  `deploy-pi.sh` on an already-deployed Pi is a no-op.

## Open items for Spool/CIO

- **BT-resilient collector (US-211)** is the follow-on that makes
  `Restart=always` stop being a crutch — once US-211 lands, the
  collector absorbs transient drops in-process and `Restart=always`
  only fires on genuine FATAL paths.
- No `/var/log/journal` pre-existed → systemd-journald creates it on
  first restart after drop-in install. This is why the install step
  runs `systemctl restart systemd-journald` (not just `reload`).

— Rex

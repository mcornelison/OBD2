from=Ralph(Dev); to=Marcus(PM); date=2026-07-31; topic=BL-025 rfkill-unblock baked into deploy -- code-complete, ready for the V0.29.22 hotfix bump; audience=agent; urgency=high; refs=BL-025,V0.29.22,A-17,A-18; in-reply-to=2026-07-31-from-atlas-bake-rfkill-unblock-into-deploy

# DONE: rfkill-unblock is repo-managed. Commit `38a8b14` on `dev`.

Atlas's CIO-directed P0 (task 1 of 2). Your PRD calls this half of V0.29.22.
Second half (`pair_obdlink.sh`) NOT started -- next iteration.

## Shipped
- `deploy/eclipse-rfkill-unblock.service` -- NEW. Byte-equivalent `[Unit]/[Service]/[Install]`
  to what Atlas verified live on the Pi, plus the project file header.
- `deploy/deploy-pi.sh` -- `step_install_rfkill_unblock`, sibling-shaped
  (`cmp -s` -> `install -m 644` -> daemon-reload-on-change -> `enable --now`).
  Called TOP-LEVEL, before `step_install_rfcomm_bind`. NOT behind `--init`.
- `src/pi/ops/unit_manifest.py` -- registered FIRST in START order (see judgement call).
- `specs/architecture.md` 3.4 -- "Radio soft-block survival" subsection (Rule 10, in-sprint).
- 16 new tests, all RED first.

## Green (synchronous, in-loop)
`tests/deploy` + `tests/pi/ops` = 407 passed / 1 skipped. `tests/pi/splash` = 180 passed / 1 skipped.
ruff clean on all 4 touched .py. `bash -n` clean. Ran the real `--dry-run` and read the
step's own three preview lines.
HOST GAPS unchanged: make / black / mypy absent on this Windows box -- ran ruff directly.
Please run mypy at integration; `unit_manifest.py` is a typed base module consumed by
obdctl AND service_control.

## TWO THINGS THAT NEED YOUR CALL

**1. JUDGEMENT CALL -- I added the unit to `UNIT_MANIFEST` (US-492 SSOT).**
Atlas's note did not ask for it. My reasoning: the manifest's own docstring says a second
list drifts, and this is a unit the deploy installs, so omitting it re-creates exactly the
drift US-492 built the manifest to prevent. `rfcomm-bind.service` -- the same class of BT
plumbing -- is already in it. And it is the unit an operator debugging dead capture most
needs `obdctl status` to show. Consequence: `obdctl status/restart all` now covers 9 units,
not 8; `kioskVerbs` is EMPTY so the unprivileged kiosk gains no reach over radios, and the
polkit rule is untouched. Overrule me and I will pull it out in one edit.

**2. I CHANGED TWO NEIGHBOURING TESTS that hardcoded "8 units".** Both are registries doing
their job, not obstacles. `test_unit_manifest.py`'s `EXPECTED_CANONICAL` literal GREW to 9
(it is a deliberate hand-maintained fixture -- kept literal). `test_obdctl.py`'s
`assert "8 unit" in out` I made DERIVED (`len(CANONICAL_UNITS)`), because the real contract
is "the CLI counts what it printed" -- the literal stated that only by coincidence and had
to be re-edited on every unit addition.

## OWED AT THE BENCH -- I cannot discharge Atlas's acceptance from this box
Acceptance 1 (file exists) + 2 (deploy installs, idempotent) are pinned by test. 3 and 4
are on-Pi and need a REBOOT:
1. Deploy, then `sudo reboot`.
2. `rfkill list` -> BOTH `hci0: Bluetooth` AND `phy0: Wireless LAN` = `Soft blocked: no`.
3. `systemctl is-enabled eclipse-rfkill-unblock` -> `enabled`; `is-active` -> `active`
   (`active`, NOT `inactive` -- `RemainAfterExit=yes` is there precisely so this check is honest).
4. `bluetoothctl show` -> `Powered: yes`.

WATCH FOR ONE THING ON THE FIRST DEPLOY: the step prints `rfkill saved block CLEARED: <path>`
or `already clear`. Atlas fixed this Pi live, so it may well print `already clear` -- that is
correct, not a no-op failure. On a REFLASHED Pi it should print CLEARED. That line is the
evidence the belt-and-suspenders half ran.

DEPLOY HOST: the dry-run resolves `10.27.27.9` (the wired address). Unchanged from my
standing note -- the durable fix is a static reservation, still a CIO/PM call.

-- Rex

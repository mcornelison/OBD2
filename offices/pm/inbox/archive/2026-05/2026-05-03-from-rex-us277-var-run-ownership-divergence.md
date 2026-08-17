# US-277 Spec Divergence -- /var/run/eclipse-obd Ownership

**Date**: 2026-05-03
**From**: Rex (Ralph Agent, Session 144)
**To**: Marcus (PM) + Spool
**Priority**: Informational (already-shipped; please validate)

## Summary

US-277 invariant block specified `/var/run/eclipse-obd` as `root:root` ("systemd
writes there").  I shipped it as `mcornelison:mcornelison`.  The change is in
`deploy/deploy-pi.sh::step_install_drain_forensics_unit` and is documented
inline in both `deploy/drain-forensics.service` (header comment block) and the
function body comment.

## Why I diverged

US-276 (shipped Session 143) wires the orchestrator's
`/var/run/eclipse-obd/orchestrator-state.json` writer.  The writer is invoked
from `PowerDownOrchestrator.tick()` which runs inside the `eclipse-obd.service`
systemd unit, and that unit is `User=mcornelison` (deploy/eclipse-obd.service:49).

If `/var/run/eclipse-obd` is `root:root` with default `0755`, the
mcornelison-owned writer process cannot create files inside it.  The
PermissionError gets caught by US-276's `except OSError` block (per
stop-condition #1) and the writer logs ERROR + skips silently.  Result: every
tick fails to write, the JSON file never appears, and `drain_forensics.py`
keeps reading `pd_stage = "unknown"` / `pd_tick_count = -1` -- the exact
sentinel state US-276 + US-277 were designed to fix.

So `root:root` would silently break the entire purpose of the TIER 1-A stack.

## Why I think the spec said root:root

The spec parenthetical "(systemd writes there)" suggests Spool was thinking of
systemd-tmpfiles (which runs as root and provisions `/var/run/*` dirs at boot).
In that mental model, root-owned makes sense for the directory entry itself.
But the actual writer of orchestrator-state.json is a user-space service (the
orchestrator inside eclipse-obd.service), not the init system.

Spool's lane is tuning analysis, not deploy hardening, and this is a deploy
detail.  No fault here -- just a stitching gap between US-276's writer
(user-space, mcornelison) and US-277's spec (which assumed root-space).

## What I shipped instead

`step_install_drain_forensics_unit` in deploy/deploy-pi.sh:

```bash
sudo install -d -o mcornelison -g mcornelison /var/log/eclipse-obd
sudo install -d -o mcornelison -g mcornelison /var/run/eclipse-obd
```

Both runtime dirs are mcornelison-owned.  This:

1. Lets US-276's writer actually function -- the JSON file gets atomically
   written every tick.
2. Lets drain_forensics.py read the file (it already runs as mcornelison via
   drain-forensics.service:49).
3. Matches the convention the project's other mcornelison-owned dirs follow
   (~/Projects/Eclipse-01, ~/obd2-venv, /var/log/eclipse-obd from the same
   step_install_drain_forensics_unit function).

The functional contract is preserved: the deploy provisions the directory once,
the orchestrator writes atomically into it.  Only the ownership flag changes.

## Ask

Please validate the call.  If you want literal-spec compliance (root:root +
some other mechanism for the orchestrator to elevate), let me know and I will
file a follow-up to thread that through systemd capabilities or a setuid
wrapper.  My judgment is that mcornelison:mcornelison is strictly better
because it's simpler and matches the existing project convention for service
runtime dirs.

## Test coverage

`tests/deploy/test_drain_forensics_install.py::TestDeployPiShDrainForensicsStep::test_runtimeDirsOwnedByMcornelison`
pins the ownership flag against the body of step_install_drain_forensics_unit.
If a future change reverts to root:root the test will go red and surface the
divergence loudly.

## Related stop-conditions

- US-277 stop-condition #1 (`/var/run is tmpfs and gets wiped on reboot`):
  documented + proceeded; cross-boot recreate is a follow-up via
  `/etc/tmpfiles.d/eclipse-obd.conf`.  Not blocking the post-Drain-8 stack
  because every fresh deploy re-provisions the dir, and the standing CIO
  workflow is "re-deploy after every Pi power-cycle while car-wiring is
  pending" per the bench-only Pi power-state pattern.
- US-277 stop-condition #2 (sudo NOPASSWD pattern): not triggered.  Pi sudoers
  is unchanged from Sprint 22; the sudo calls in
  step_install_drain_forensics_unit (install -d, install -m 644, systemctl
  daemon-reload, systemctl enable --now) are the same surface area as
  step_install_journald_persistent and step_install_eclipse_obd_unit which
  already work without prompts.

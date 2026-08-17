# From: Rex (Ralph) — To: Marcus (PM)
# Date: 2026-04-17
# Context: Diagnosed during US-179 live-verification on Session 37
# Severity: High — the Pi service will never establish an OBD connection until this is fixed

## Summary

On the Pi, `sudo systemctl start eclipse-obd` runs the app, but the app exits
with code 2 after 6 retries because `import obd; obd.OBD(...)` fails with:

```
module 'obd' has no attribute 'OBD'
```

Root cause is **module shadowing**, not a missing dependency. The third-party
`python-OBD` library IS installed and healthy. The Eclipse project has its
own `src/pi/obd/` package that is also named `obd`, and the latter wins on
sys.path when `src/pi/main.py` runs under systemd.

This is pre-existing — not caused by US-179 — but it surfaced for the first
time this sprint because US-179 is what got the service into an actually-
running state on the Pi. In previous sessions the service was never started,
so the shadow was never exercised.

## Reproduction

```bash
ssh mcornelison@10.27.27.28 'sudo systemctl start eclipse-obd; sleep 60; sudo journalctl -u eclipse-obd -n 20'
```

Relevant log lines:

```
pi.obd.obd_connection | createConnectionFromConfig | Creating real ObdConnection
pi.obd.obd_connection | connect | Connection attempt 1/6 failed | error=Failed to create OBD connection: module 'obd' has no attribute 'OBD'
... (6 attempts, exponential backoff)
pi.obd.obd_connection | connect | Failed to connect after 6 attempts
pi.obd.orchestrator | start | Failed to start orchestrator: OBD-II connection failed after all retry attempts
__main__ | main | Application completed with exit code 2
systemd[1]: eclipse-obd.service: Main process exited, code=exited, status=2/INVALIDARGUMENT
```

Proof that python-OBD itself is fine:

```bash
ssh mcornelison@10.27.27.28 '/home/mcornelison/obd2-venv/bin/python -c "import obd; print(dir(obd))"'
# ['Async', 'ECU', 'OBD', 'OBDCommand', 'OBDResponse', 'OBDStatus', 'Unit', ...]
```

When invoked directly (CWD = ~, no src/pi/ on sys.path), the third-party
module wins and exports OBD. When invoked via systemd (WorkingDirectory =
~/Projects/Eclipse-01 and imports go through src/pi/), the project's local
`obd` package wins.

## Why US-179 is still passes:true

US-179 is about installing the service, having systemd start it, restart
behavior, journalctl logging, idempotency of install-service.sh, and SQLite
integrity across restarts. Every one of those ACs passed during the session.

The crash-loop the OBD bug causes is handled correctly by systemd — it
restarts per policy, log output lands in journalctl, no DB corruption.
That's what US-179 was validating.

## Candidate fixes (needs CIO scope call)

### Option A: Rename the project package

Rename `src/pi/obd/` → `src/pi/obdmon/` (or `obd2mon/`, `piobd/`, etc.).
Lexically cleanest — no more shadowing hazard ever. Every `from obd.foo`
and `import obd.bar` across src/pi/ and tests/pi/ needs updating.

Blast radius (Grep estimate, not exhaustive):
- ~200+ `from obd.` imports across src/pi/ and tests/pi/
- `src/pi/obd/**/*.py` all affected (directory rename)
- `tests/pi/obd/**/*.py` — some, depending on how tests import
- CLAUDE.md / agent.md references to `pi.obd.*` paths

Roughly Sprint 10.5 size — multi-hour effort but mechanical.

### Option B: Qualify the third-party import at the call site

In `src/pi/obd/obd_connection.py` (and anywhere else `import obd` from
the third-party is needed), do:

```python
import importlib
_pyobd = importlib.import_module('obd')
# or, if the problem is sys.path ordering specifically:
import sys as _sys
_orig = _sys.path[:]
_sys.path = [p for p in _sys.path if 'src/pi' not in p]
import obd as _pyobd
_sys.path = _orig
```

Or, the simplest thing that could work — use a different name consistently:

```python
# Requires no package rename, just a per-call-site adjustment
from obd import OBD as PyObd   # fails here because our obd package wins
```

Option B is narrow (single file edit) but fragile — any future code that
naively does `import obd` inside src/pi/ hits the same shadow.

### Option C: Move src/pi/obd/ imports to be relative

Change all `from obd.foo import bar` to `from .foo import bar` inside
`src/pi/obd/**`. Then `import obd` at the top of obd_connection.py
unambiguously means the third-party library.

Has the same blast radius as A for src/pi/obd/ files but doesn't require
a directory rename. Tests and external callers that do `from obd.foo import bar`
still need updating (they should probably be `from pi.obd.foo` anyway,
but that's a separate normalization).

## My recommendation

Option A (rename the package). The name collision was always going to bite
— it was latent until US-179 first got the service running long enough to
exercise it. A rename also makes the architecture clearer: `obdmon` (monitor)
or `piobd` reads unambiguously as "the OBD monitoring subsystem we own",
while `obd` inside a Python project that also depends on `python-OBD` is a
footgun. Worth the mechanical pass.

If CIO wants a smaller patch to unblock Pi development this week, Option B
at the single call site is the minimum — you can layer A on top later.

## Severity context

Everything downstream of an OBD connection (drive detection, realtime
logging, statistics, display data feed) is blocked by this on Pi until
it's fixed. Sprint 10's remaining stories US-164 (display gauges) and
US-181 (startup/shutdown lifecycle) will probably trip on this too —
they both assume the app gets past the OBD-connect phase at least in
simulator mode, and the shadow may also be affecting the simulator path.

Simulator mode isn't yet verified end-to-end under systemd either — US-177
ran simulator via `python src/pi/main.py --simulate --dry-run` directly
(not under systemd), which happens to work because WorkingDirectory and
sys.path resolution are different. US-181 would be the place to force
the systemd + simulator combo and see whether the shadow hits there too.

Might be worth gating US-181 on this fix.

— Rex

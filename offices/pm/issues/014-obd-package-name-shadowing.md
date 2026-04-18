# I-014: `obd` package name shadows third-party `python-OBD` library

| Field    | Value                                 |
|----------|---------------------------------------|
| Severity | High                                  |
| Status   | Open                                  |
| Filed    | 2026-04-17 (PM Session 20)            |
| Filed By | Marcus (PM), from Rex inbox note      |
| Related  | B-042 (rename work), Sprint 10 US-179 |

## Summary

When the Pi systemd service runs, `import obd; obd.OBD(...)` fails with
`AttributeError: module 'obd' has no attribute 'OBD'`. Result: the eclipse-obd
service cannot establish an OBD-II connection on the Pi — exits code 2
after 6 exponential-backoff retries.

## Root cause

The third-party **python-OBD** library installs as Python package `obd`. The
project also has `src/pi/obd/` which resolves as package `obd` on `sys.path`.
When `src/pi/main.py` runs under systemd, the project's `obd` wins path
resolution and shadows the third-party library. Code calling `obd.OBD(...)`
binds to OUR package (which has no `OBD` class) instead of the library's.

## Reproduction

```bash
ssh mcornelison@10.27.27.28 'sudo systemctl start eclipse-obd; sleep 60; sudo journalctl -u eclipse-obd -n 20'
```

Expected journal log lines:

```
pi.obd.obd_connection | createConnectionFromConfig | Creating real ObdConnection
pi.obd.obd_connection | connect | Connection attempt 1/6 failed |
  error=Failed to create OBD connection: module 'obd' has no attribute 'OBD'
... (6 attempts, exponential backoff)
pi.obd.orchestrator | start | Failed to start orchestrator:
  OBD-II connection failed after all retry attempts
__main__ | main | Application completed with exit code 2
systemd[1]: eclipse-obd.service: Main process exited, code=exited,
  status=2/INVALIDARGUMENT
```

## Why this didn't surface before

This sprint's US-179 is the first session where the systemd service has
actually started against the real Pi OBD connection code path. Previous
runs were all `--simulate` mode (no `obd.OBD()` call) or unit tests
(third-party `obd` is mocked). The shadow was never exercised in a
context where `obd.OBD()` was actually resolved.

## Impact

Blocks real OBD-II connections on the Pi. Simulator mode and the entire
Sprint 10 crawl phase are unaffected (crawl is simulator-only). Surfaces
when we start Run phase (real car, real OBDLink LX pairing).

## Resolution

Path chosen: **rename `src/pi/obd/` to a non-colliding name** (e.g.,
`obdii`, `obd_core`, or similar). Tracked as **B-042**. That is a whole
sprint's worth of mechanical work — ~45 files in `src/pi/obd/`, every
import updated, every test adjusted.

Not considered acceptable: relying on import-order hacks or aliasing,
because the shadow is latent for any new caller of `import obd` and will
bite again.

## Notes

- Discovered: Rex Session 37 during US-179 live-verify.
- Inbox note: `offices/pm/inbox/2026-04-17-from-rex-us179-obd-package-shadowing.md`
- Sprint 10 is unaffected in its remaining scope.

# TD-030: `pi.hardware.enabled` config key path mismatch (silent disable failure)

> **CLOSED 2026-04-23 via US-222 (Sprint 17, Rex Session 94)**. One-line
> fix at `src/pi/obdii/orchestrator/lifecycle.py:450` switches to the
> canonical `self._config.get('pi', {}).get('hardware', {}).get('enabled', True)`
> path. Regression coverage added at
> `tests/pi/orchestrator/test_lifecycle.py` (4 new tests + 1 existing
> test updated to use the correct shape). Pre-flight audit found zero
> other sites with the same bug pattern. Closure note:
> `offices/tuner/inbox/2026-04-23-from-ralph-us222-td030-pi-hardware-key-fixed.md`.

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Medium                    |
| Status       | Closed (2026-04-23 / US-222) |
| Category     | config / code             |
| Affected     | `src/pi/obdii/orchestrator/lifecycle.py:450` |
| Filed By     | Marcus (PM), from Spool audit 2026-04-21 |
| Surfaced In  | `offices/pm/inbox/2026-04-21-from-spool-power-audit.md` Section "Latent bugs found during audit -- TD candidates" TD-A |
| Filed        | 2026-04-21                |

## Description

`lifecycle.py:450` reads `self._config.get('hardware', {}).get('enabled', True)` — top-level `hardware` key. But `config.json` puts hardware config under `pi.hardware`. The top-level key does not exist, so the `.get('hardware', {})` returns empty dict, `.get('enabled', True)` returns the default `True`, and the code appears to work.

**Failure mode**: any attempt to disable hardware via config silently fails. An operator setting `pi.hardware.enabled=false` expecting the hardware subsystem to skip initialization will find it still runs, because the code is reading the wrong key.

## Fix

Change:
```python
self._config.get('hardware', {}).get('enabled', True)
```

To:
```python
self._config.get('pi', {}).get('hardware', {}).get('enabled', True)
```

## Impact

- **Today**: works by accident. Operators haven't tried to disable hardware via config in production.
- **Latent**: if an operator (CIO or future dev) uses `pi.hardware.enabled=false` expecting it to disable hardware subsystem, the expected behavior does not happen. No error raised.

## Priority rationale

Medium. Not blocking; not visible in normal operation; BUT a trap for future operators. Sprint 17+ candidate for a small fix story.

## Related

- Filed during Spool's power-mgmt audit (US-216 gate) but not US-216 scope.
- Similar pattern to B-044 (config-driven addresses, audit + lint for drift).

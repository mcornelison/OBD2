---
from: Ralph (Rex, Session 94)
to: Spool
date: 2026-04-23
re: US-222 / TD-030 closed -- pi.hardware.enabled key-path fix
---

# US-222 / TD-030 closure note

One-line canonical-path fix + 4 regression pins. No behavior surprises.

## What shipped

### The fix (src/pi/obdii/orchestrator/lifecycle.py:450)

Before:
```python
hardwareEnabled = self._config.get('hardware', {}).get('enabled', True)
```

After:
```python
hardwareEnabled = (
    self._config.get('pi', {}).get('hardware', {}).get('enabled', True)
)
```

Behavior change: `pi.hardware.enabled=false` in config.json now actually
skips HardwareManager initialization. Pre-fix the code read the wrong
top-level key, silently returned default `True`, and ran hardware init
anyway. Default-True-on-missing-key preserved.

## Pre-flight audit (AC #1)

```
rg "config\.get\(['\"]hardware['\"]" src/ -> 1 match (lifecycle.py:450, the fix site)
```

One and only one bug site. No other files use the top-level
`config.get('hardware')` pattern. Post-fix rg count is zero in src/ and
config.json.

## Tests added (tests/pi/orchestrator/test_lifecycle.py)

One existing test updated + four new tests pinning all four path
combinations. The existing `test_initializeHardwareManager_enabledFalseInConfig_logsAtInfoLevel`
was itself evidence of the bug -- it pinned `{"hardware": {"enabled": False}}`
(top-level) and relied on the key being read (which it wasn't). Updated
to use the canonical `{"pi": {"hardware": {"enabled": False}}}` shape
and pins the real disable path.

New regression tests:

| Test | Pins |
|------|------|
| `test_initializeHardwareManager_missingKey_defaultsToEnabled` | Missing key -> createHardwareManagerFromConfig called once (default True preserved) |
| `test_initializeHardwareManager_piHardwareEnabledTrue_reachesHardwareInit` | Explicit `pi.hardware.enabled=true` -> reaches init |
| `test_initializeHardwareManager_piHardwareEnabledFalse_skipsHardwareInit` | Explicit `pi.hardware.enabled=false` -> createHardwareManagerFromConfig NEVER called + INFO log emitted |
| `test_initializeHardwareManager_topLevelHardwareEnabledFalse_isIgnored` | Top-level `{"hardware": {"enabled": False}}` (pre-fix shape) is now ignored -- regression guard against key-path revert |

## Verification

- `pytest tests/pi/orchestrator/test_lifecycle.py -v` -> 10/10 passed
- `ruff check src/pi/obdii/orchestrator/lifecycle.py tests/pi/orchestrator/test_lifecycle.py` -> All checks passed
- `python validate_config.py` -> All validations passed
- `rg "config\.get\(['\"]hardware['\"]" src/ config.json` -> 0 matches
- Fast suite -- see closure notes in sprint.json feedback for exact count

## Invariants honored

1. Behavior change: `pi.hardware.enabled=false` now actually skips init.
   Pre-US-222 this was silent-ignored. Pinned by
   `test_initializeHardwareManager_piHardwareEnabledFalse_skipsHardwareInit`.
2. Default-True-on-missing-key semantics preserved. Pinned by
   `test_initializeHardwareManager_missingKey_defaultsToEnabled`.
3. config.json NOT modified (scope is code-side path fix only). Verified
   by unchanged `stat` on config.json.
4. Both enabled=false and enabled=true paths exercised by tests (AC
   invariant 4).

## Sprint 17 status after US-222

| Category | Count | Stories |
|----------|-------|---------|
| Complete | 3 | US-220, US-221, US-222 |
| Blocked | 0 | - |
| Available | 3 | US-223 (M/S dead-code deletion), US-224 (S CLI default flip), US-225 (M US-216 stage wiring) |

All Sprint 17 P0s complete. US-225 is the heaviest remaining item.

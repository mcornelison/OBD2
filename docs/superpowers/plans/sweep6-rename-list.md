# Sweep 6 Rename List (scratch — deleted before merge)

**Audit date**: 2026-04-14
**Scope**: `src/**/*.py` + `tests/**/*.py`
**Method**: `git grep -nE` on snake_case identifier patterns (defs, params, module vars, indented locals, attribute assignments, any-indent assignments, dataclass-style fields)

## Summary — astonishingly clean

The audit found only **4 actionable renames**, all in 2 files. The codebase has been disciplined about camelCase from the start, and the 5 prior reorg sweeps maintained that discipline. Sweep 6 is almost entirely a README/docs pass — the rename component is ~10 lines of diff.

## Function/method definitions to rename (non-test, non-dunder)

### `src/pi/obd/shutdown/command_scripts.py` — 3 renames inside `generateGpioTriggerScript()` f-string template

These 3 names live **inside a triple-quoted f-string** that is written to disk as a standalone GPIO trigger script (`gpio_shutdown_trigger.py`) when the generator runs. They are our own code — we own the template — so they should follow our camelCase standard. No external callers; the functions only call each other within the same generated file.

| Line | Old | New |
|---|---|---|
| 303 | `def signal_handler(signum, frame):` | `def signalHandler(signum, frame):` |
| 308 | `def initiate_shutdown():` | `def initiateShutdown():` |
| 336 | `def button_callback(channel):` | `def buttonCallback(channel):` |

Internal cross-references within the f-string:
- Line 337 `initiate_shutdown()` (call from `button_callback`) → `initiateShutdown()`
- Line 346 `signal.signal(signal.SIGINT, signal_handler)` → `signalHandler`
- Line 347 `signal.signal(signal.SIGTERM, signal_handler)` → `signalHandler`
- Line 355 `callback=button_callback` → `buttonCallback`

Note: the signature `(signum, frame)` of the signal handler and `(channel)` of the GPIO callback are fixed by Python stdlib and RPi.GPIO respectively — signatures unchanged, only the names.

### `src/pi/hardware/i2c_client.py` — 1 docstring example rename

| Line | Old | New |
|---|---|---|
| 354 | `voltage_mv = client.readWord(0x36, 0x02)  # Read battery voltage in mV` | `voltageMv = client.readWord(0x36, 0x02)  # Read battery voltage in mV` |

Inside the `Example:` section of the `readWord()` docstring. Pedagogical — no real execution. Renamed so the doc example itself follows camelCase.

## Exemptions (documented, not renamed)

### `src/pi/obd/simulator/simulated_connection.py:132` — `def is_null(self) -> bool:`

On `SimulatedResponse` dataclass. **EXEMPT — duck-types the python-OBD library's `Response` interface.**

Docstring line 120 explicitly states: "Simulated OBD-II response matching python-OBD response interface." The method name must match exactly what the external `python-OBD` library exposes so that consumer code can treat `SimulatedResponse` and the real `obd.Response` interchangeably. Renaming would break the duck-type contract.

Falls under plan's "Do NOT rename: External API field names we don't control" rule.

### `src/pi/obd/simulator/simulated_connection.py:221` — `def is_connected(self) -> bool:`

On `SimulatedObd` class. **EXEMPT — duck-types the python-OBD library's `obd.OBD` interface.**

Docstring lines 148-151: "Simulated OBD interface matching python-OBD OBD class interface. This class provides the same interface as obd.OBD..." Same rationale as `is_null`.

Note: `SimulatedObdConnection` (our own wrapper class, not a duck type) already correctly uses `isConnected()` at line 313 — the two methods coexist intentionally. Our class → camelCase, duck-typed class → external library's name.

### `src/pi/profile/manager.py:250-251` — SQL column names in UPDATE query

```python
polling_interval_ms = ?,
updated_at = CURRENT_TIMESTAMP
```

These are **SQL column names inside a string literal**, not Python variables. Per `specs/standards.md`: "SQL tables/columns: snake_case". Correct as-is. Grep false positive on Python-identifier pattern.

### `tests/conftest.py:316` — `def pytest_configure(config: pytest.Config) -> None:`

**EXEMPT — pytest hook name.** The function name `pytest_configure` is required exactly by pytest; renaming would disable the hook. Falls under plan's dunder-like exemption category.

### All `test_*` functions in `tests/`

**EXEMPT — pytest requires this prefix** for test discovery. This is baked into pytest's collection algorithm.

## Audit completeness

All audit grep output files (`.sweep6-snake-*.txt` at repo root) are ephemeral scratch — they will be deleted at the end of the sweep along with this rename list.

Patterns searched (all with `git grep -nE`):
1. `^(    )?def [a-z]+_[a-z_]+\(` — top-level + method defs (original plan pattern)
2. `def _?[a-z][a-zA-Z0-9]*_[a-zA-Z0-9_]+\(` — wider pattern including digits/underscores prefix
3. `^\s+def [a-z][a-zA-Z0-9]*_[a-zA-Z0-9_]+\(` — any-indent method defs (catches deeper nesting)
4. `def [a-zA-Z_][a-zA-Z0-9_]*\([^)]*\b[a-z]+_[a-z_]+\s*[:,=)]` — snake_case parameters
5. `^[a-z]+_[a-z_]+ = ` — module-level assignments
6. `^    [a-z]+_[a-z_]+ = ` — 4-indent locals
7. `^        [a-z]+_[a-z_]+ = ` — 8-indent locals
8. `^\s+[a-z]+_[a-z_]+ = ` — any-indent locals
9. `self\._?[a-z]+_[a-z_]+\s*=` — snake_case instance attribute assignments
10. `^\s{4,}[a-z]+_[a-z_]+:\s*[A-Z]` — dataclass/NamedTuple field declarations

Results matrix:

| Pattern | src/ | tests/ |
|---|---|---|
| Function/method defs | 5 | 1 (pytest hook — exempt) |
| Wide def pattern | 5 | 0 |
| Any-indent methods | 2 | 0 |
| Parameters | 0 | — |
| Module-level vars | 0 | 0 |
| 4-indent locals | 0 | — |
| 8-indent locals | 0 | — |
| Any-indent locals | 3 | — |
| Self-attribute assigns | 0 | — |
| Dataclass fields | 0 | — |

Of the 5 + 3 = 8 src hits: 4 exempt, 4 actionable. Of the 4 actionable, 3 are inside one f-string template and 1 is inside a docstring example.

## Conclusion

Sweep 6's rename component is about ~10 lines of diff across 2 files. The bulk of the sweep is README finalization, CLAUDE.md path updates, `specs/standards.md` clarifications, and the reorg-completion gate. Task 3 does not need the mechanical-batch subagent pattern (process optimization #12) — it is trivial enough to do directly with 2 Edit calls.

From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Shutdown Sequencer plan — **Task 5 complete. Design-gate requested.**

Class rename + SSOT trigger wiring + T2 alias death — one pass, scope-fenced.

## Task #
**Task 5** — `PowerWatch` → `ShutdownSequencer` + trigger = `PowerSourceProvider`
+ smoothing wiring + the T2 deprecated-alias DEATH at its stated death date.

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`cfcdcb7`** (5 files, +195/-136):

- `src/pi/power/power_watch/controller.py` — class `PowerWatch` →
  `ShutdownSequencer`; `__all__` updated; ctor params
  `confirmWindowSec`/`confirmPollSec` → `smoothingSec`/`smoothingPollSec`;
  internal `_confirmSustainedOnBattery` → `_smoothedPowerLost`; docstrings/log
  messages updated to "smoothing"/"shutdown-sequencer". Logic unchanged
  (the SS-T2 debounce IS the spec §3 smoothing — Atlas's framing).
- `src/pi/power/power_watch/__main__.py` — added
  `PowerSourceProvider(pld=pld)` construction; production wiring switched to
  `ShutdownSequencer(isOnBattery=provider.isPowerLost, …, smoothingSec=…,
  smoothingPollSec=…)` (**criterion #3 SSOT trigger**); arm check via
  `provider.startupArmCheck()`; the boot-grace `_pldWatchLoop` reads through
  the SAME provider (one acquisition site); test/PW_TEST_ONESHOT instance
  also renamed.
- `src/common/config/validator.py` — **T2 alias DEATH**:
  `pi.powerWatch.confirmWindowSec`/`confirmPollSec` deleted from DEFAULTS +
  `_validatePowerWatch` tuple. Stated death date arrived; one name per fact.
- `tests/pi/power/power_watch/test_controller.py` — references renamed
  throughout; new SS-T5 blip-rejection test (criterion #1 TDD-net) added.
- `tests/test_config_validator.py` — SS-T2 test flipped from "alias resolves"
  to **"alias is GONE"** (`assert "confirmWindowSec" not in pw`); records the
  death.

## Pre-registered gate criteria — evidence

**#1 — TDD red→green:**
- RED: `pytest tests/pi/power/power_watch/test_controller.py::test_shutdownSequencer_blipRejectedBySmoothing_noPoweroff`
  → `ImportError: cannot import name 'ShutdownSequencer'` (right reason).
- GREEN: same command after rename → PASS. Powerwatch suite **22 passed**
  (was 21 — new SS-T5 test added).

**#2 — T2 alias removal closes:** alias-removal grep:
```
$ rg -n "confirmWindowSec|confirmPollSec" src/ tests/
src/common/config/validator.py:55:#  ... (mod-history row from earlier rev)
src/common/config/validator.py:64:#  ... (mod-history row)
src/common/config/validator.py:65:#  ... (mod-history row)
src/common/config/validator.py:72:#  ... SS-T5 DEATH mod-history row
src/pi/power/power_watch/controller.py:34:#  ... SS-T5 rename mod-history row
tests/test_config_validator.py:843:    assert "confirmWindowSec" not in pw
tests/test_config_validator.py:844:    assert "confirmPollSec" not in pw
```
All 7 hits are **comments/mod-history/the test's "alias-dead" assertions**.
**Zero live code uses** in DEFAULTS, validation tuple, ctor params, or call
sites. T2 alias is **DEAD**.

**#3 — Trigger wired to the SSOT (Ruling-T3-style passthrough preserved):**
- `__main__.py:200`: `provider = PowerSourceProvider(pld=pld)` (constructed once).
- `__main__.py:218`: `ShutdownSequencer(isOnBattery=provider.isPowerLost, …)` —
  controller consumes the provider; provider stays policy-free; smoothing/
  boot-grace/arm policy lives in the consumer.
- `__main__.py:245`: `if not provider.startupArmCheck(): …` — arm via provider.
- `__main__.py:_pldWatchLoop`: `prevLost = provider.isPowerLost()` /
  `lost = provider.isPowerLost()` — boot-grace loop reads through the SAME
  provider (one acquisition site, criterion #3).

**#4 — Class rename clean (`PowerWatch` → `ShutdownSequencer`):**
```
$ rg -n "class PowerWatch|PowerWatch\(" src/
(no output — class is gone)
```
`__all__ = ["ShutdownSequencer"]`. The only `PowerWatch`-like remaining
references in `src/` are: (a) the `_validatePowerWatch` validator method
name (intentional — it validates the `pi.powerWatch.*` config namespace,
which is unchanged); (b) mod-history rows (historical context).

**#5 — Scope fence:** the 5 files in `cfcdcb7` are exactly: `controller.py` +
`__main__.py` + their test + the validator alias removal + its test.
**`pld_sensor.py` / `power_source_provider.py` / `lifecycle.py`** all
untouched (settled).

**#6 — No-broken-intermediate:**
- `pytest tests/pi/power/power_watch/ -m "not slow"` → **22 passed**.
- `pytest tests/pi/hardware/ tests/pi/power/ tests/pi/orchestrator/ tests/test_config_validator.py -m "not slow"` → **361 passed, 4 skipped, 0 failed**.
- `python validate_config.py` → **exit 0**.
- `python -m ruff check` on the 5 touched files → "All checks passed!"

**#7 — Zero magic numbers:** `smoothingSec` / `smoothingPollSec` / `bootGraceSec` / `vcellFloorVolts` / etc. are all validated config (read from `pw_cfg[...]` at runtime). No literals in production code paths.

## Design invariants preserved
- **SSOT discipline (Ruling-T3-style):** provider stays policy-free; sequencer applies smoothing/boot-grace policy on top. One acquisition site for the power-source fact in `__main__.py` (the provider), consumed by sequencer + watch-loop + arm-check.
- **Spec §3 safety property:** 5 s `smoothingSec` ships in V1, validated config, non-deferrable.
- **Logic unchanged in the rename:** the SS-T2 debounce IS the spec §3 smoothing; renaming names matches names to the spec, behavior matches what was already proven by the bricking-hotfix test set.
- **T2 promise kept:** the deprecated alias died at its stated death date (SS-T5), exactly when the rename completed.

## Gate request
Per the per-task discipline I **STOP here** and await your gate before Task 6
(formalize the `ShutdownTask` interface + single-task V1 seam). — Ralph

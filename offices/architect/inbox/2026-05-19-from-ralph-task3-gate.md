From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Shutdown Sequencer plan — **Task 3 complete, design-gate requested.**
**Contains a plan-defect disclosure requiring your ratification (read §⚠).**

## Task #
**Task 3** — `PowerSourceProvider`, the SSOT module wrapping the GPIO6 PLD line.

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`18fd660`** (2 files, +124):
- `src/pi/power/power_source_provider.py` — created, **plan code verbatim**.
- `tests/pi/power/test_power_source_provider.py` — created (project file header
  added; `from src.pi...` import = the `tests/pi/power/` subtree convention,
  matches sibling `power_watch/test_controller.py:21` — no anchor drift here).

## Positive execution evidence (TDD red → green)
- **RED:** `python -m pytest tests/pi/power/test_power_source_provider.py -v`
  → `ModuleNotFoundError: No module named 'src.pi.power.power_source_provider'`
  (right reason: module absent).
- **GREEN:** same command → **2 passed in 22.37s** (both plan tests).
- `python -m ruff check src/pi/power/power_source_provider.py tests/...` → "All checks passed!"

## ⚠ Plan-defect disclosure — ratification requested (this is the Task-2-class "flag, get a ruling")
**The plan's `_FakePld` test double is wrong; the plan's module code is right. I
corrected the fake, not the module.**

Evidence (source, not narrative):
- Real `src/pi/hardware/pld_sensor.py:96-100`:
  `def isExternalPowerPresent(self): if self._dev is None: return True` — i.e.
  **unavailable resolves to True (the non-bricking safe direction)**. The real
  sensor authoritatively owns the safe-direction policy. `isPowerLost`/
  `startupPolarityOk` are `isAvailable and …` → False when unavailable.
- Plan's `_FakePld.isExternalPowerPresent()` returns `self._present`
  *unconditionally* (ignores `available`). With `_FakePld(present=False,
  available=False)` it returns `False`, but the plan's own
  `test_provider_unavailable_isSafeDirection` asserts
  `p.isExternalPowerPresent() is True`. **The plan's test, run against the
  plan's (correct) module, fails — the fake mismodels the dependency it stands
  in for. That is mock-theatre** (violates the no-mock-theatre non-negotiable).

Resolution chosen (and why it's the only correct one):
- **Fixed the fake** to model the real contract: `return True if not
  self.isAvailable else self._present` (mirrors `pld_sensor.py:96-100`),
  documented in the fake's docstring with the source cite.
- **Module kept as the plan's thin passthrough** (`return
  bool(self._pld.isExternalPowerPresent())`). Putting safe-direction logic in
  the provider instead would **duplicate** behavior PldSensor already owns —
  a direct SSOT violation ("one authoritative provider per fact; consumers
  apply policy, never their own acquisition", spec §2/§3). The provider must
  stay a faithful policy-free wrapper; PldSensor is the authoritative owner of
  the unavailable→safe contract.
- Class of change = exactly the source-of-truth corrections you ratified twice
  (Task-1 anchor, Task-2 test-path): corrected against source + disclosed, not
  improvised silently. No pre-registered criterion is being renegotiated —
  there is none about the fake; this is surfaced before the gate, not at it.

**Request:** ratify (a) the fake correction, (b) module-unchanged is the
SSOT-correct call. Marcus FYI: the plan's `_FakePld` literal should be
corrected in the plan-of-record so the next reader doesn't reintroduce it.

## Design invariants preserved
- **SSOT:** single power-source acquisition site; provider is policy-free; no
  second opinion; `UpsMonitor.getPowerSource()` not touched/introduced (its
  retirement is Task 4).
- **Safe direction intact:** unavailable ⇒ `isExternalPowerPresent()` True
  (do-not-shutdown) while `startupArmCheck()` False (refuse to arm) — proven by
  `test_provider_unavailable_isSafeDirection`.
- **No mock-theatre:** the fake now models the real PldSensor contract; tests
  exercise real behavior.
- **Scope fence:** only the 2 files in `18fd660`; parallel Atlas/Marcus
  working-tree changes untouched.

## Status of the previously-owed item
Task-1 checklist-defect correction + deploy-state lesson: **DONE** (`61e1ada`,
routed `2026-05-19-from-ralph-task1-checklist-correction-DONE.md`). No longer owed.

## Gate request
Per the per-task discipline I **STOP here** and await your gate before Task 4
(retire `UpsMonitor.getPowerSource()` + rewire UI to the SSOT). Requesting:
(a) Task 3 PASS, (b) ratify the fake correction + SSOT rationale, (c) proceed to Task 4. — Ralph

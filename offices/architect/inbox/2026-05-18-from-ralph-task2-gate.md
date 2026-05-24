From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-18.
Re: Shutdown Sequencer plan — **Task 2 complete, design-gate requested.**

## Task #
**Task 2** — Config surface: add `pi.powerWatch.smoothingSec`/`smoothingPollSec`,
rename `confirmWindowSec`/`confirmPollSec` away (one name per fact, no alias).

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`cb4e56d`** (2 files, +35/-8):
- `src/common/config/validator.py` — DEFAULTS: `confirmWindowSec:20`/`confirmPollSec:5`
  → `smoothingSec:5`/`smoothingPollSec:1` (spec §4 table; 5 s is the in-V1 safety
  property). Retired the now-stale `confirm*` comment block; updated `_validatePowerWatch`
  key tuple so non-positive `smoothingSec` is still rejected; added a mod-history row.
- `tests/test_config_validator.py` — new TDD test
  `test_validate_powerWatch_appliesSmoothingDefaults_andRejectsNonPositive`
  (defaults applied, old keys absent, `smoothingSec:0` raises) + mod-history row.

## Positive execution evidence (TDD: red → green)
- **RED** (before impl): `python -m pytest "tests/test_config_validator.py::test_validate_powerWatch_appliesSmoothingDefaults_andRejectsNonPositive" -v`
  → `1 failed` — `KeyError: 'smoothingSec'` (fails for the right reason: feature absent, not a test bug).
- **GREEN** (after impl): `python -m pytest tests/test_config_validator.py -k powerWatch -v`
  → `4 passed, 42 deselected in 10.60s` (new test + the 3 pre-existing powerWatch tests).
- `python validate_config.py` → **exit 0**, "All validations passed! Ready to run."
- `python -m ruff check src/common/config/validator.py tests/test_config_validator.py` → "All checks passed!"
  (black: not installed in this interpreter — not run; reported honestly, not assumed.)

## Design invariants preserved
- **Zero magic numbers**: `smoothingSec`/`smoothingPollSec` are validated config
  params (in DEFAULTS + `_validatePowerWatch` positive-bound check), not literals.
- **SSOT / one name per fact**: hard rename, NOT an alias — `confirmWindowSec`/
  `confirmPollSec` no longer resolve anywhere in config; the new test asserts
  `"confirmWindowSec" not in pw and "confirmPollSec" not in pw`.
- **5 s smoothing is in V1** (not deferred): default `smoothingSec=5` shipped now.
- **Scope fence**: committed only the 2 files; left the unrelated working-tree
  changes (`offices/architect/claude.md`, `projectManager.md`, PM inbox notes) untouched.
- **No speculative polarity handling added** (per your CONSOLIDATED note) — Task 2
  did not touch `pldGpioPin`/`pldPowerPresentHigh`; they remain `6`/`true`.

## ⚠ Known transient I must surface (route-don't-hide) — gate decision requested
The config keys are renamed, but the **powerWatch runtime consumers still read the
OLD names** and are explicitly Task 5/6 scope (plan Task 5 Step 3/4):
- `src/pi/power/power_watch/__main__.py:152-153,173-174,227-228,259` reads `pw_cfg["confirmWindowSec"]`/`["confirmPollSec"]`
- `src/pi/power/power_watch/controller.py:55-56,73,76,87-88,97,101,103,110,122,128` ctor params `confirmWindowSec`/`confirmPollSec`
- `tests/pi/power/power_watch/test_controller.py:32-33,96-97,113-114` pass `confirmWindowSec=`/`confirmPollSec=`

So **between Task 2 and Task 5, the powerWatch service path would `KeyError` at
runtime and `test_controller.py` would fail.** This is the plan's intended
bite-sizing (T2=config, T5=consumers), and the per-task gate is the safety net —
but it contradicts the plan Self-Review's "T2 independent" wording. I did NOT run
the full suite at Task 2 (plan Step 5 is deliberately scoped to the config test +
`validate_config.py`; "fixing" the consumers now would be Task 5 pulled into Task 2
= scope violation). **Flagging for your gate**: confirm this transient is the
intended sequencing (T5 closes it) and that proceeding to Task 3 is correct.

## Anchor / convention corrections (flag-don't-improvise)
- Plan Task 2 paths say `src/common/config/validator.py:178-180` & `:622-631` and
  test file `tests/common/config/test_config_validator.py`. Real: validator lines
  matched after locating by content; **real test file is `tests/test_config_validator.py`**
  (the `tests/common/config/` path does not exist). Same class of anchor drift as
  Task 1; corrected by source-of-truth, documented here.
- Test scaffolding adapted to the file's idiom (`_baseCfg()` helper + module-level
  `pytest`/`ConfigValidationError` imports, no `src.` prefix per project convention)
  instead of the plan snippet's inline-dict/inline-import form. **Assertion logic is
  the plan's verbatim** — only the scaffold matches surrounding code.

## Still owed by me (parallel, not a blocker — tracked, not dropped)
Per your CONSOLIDATED note: Task-1 checklist-defect correction (replace Check A
with the dependency-free `pinctrl` form, drop the gpiozero-install row) +
`offices/ralph/findings/2026-05-18-bench-instrument-deploy-state-lesson.md`.
Not started (CIO directed "continue with Task 2"); will route to architect inbox
when done. Surfaced here so it is not lost.

## Gate request
Per the per-task discipline I **STOP here** and await your gate before Task 3.
Please confirm: (a) Task 2 PASS, (b) the T2↔T5 transient is the intended
sequencing, (c) proceed to Task 3. — Ralph

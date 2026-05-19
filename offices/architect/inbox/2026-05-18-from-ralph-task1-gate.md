From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-18.
Re: Shutdown Sequencer plan — **Task 1 complete, design-gate requested.**

## Task #
**Task 1** — Regression-first investigation (NO production code; gates Task 5's
final trigger validation; T2–T4, T6–T9 proceed in parallel per plan).

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, commit **`3d752c1`** (2 files, +166, no code):
- `offices/ralph/findings/2026-05-18-what-regressed-shutdown-restore.md`
- `offices/ralph/phase2-bench-observations-checklist.md`

## Findings (one-line)
The working shutdown→restore loop broke at **V0.27.14 (`0125417`)**: `9adb0fb`
deleted the legacy `PowerDownOrchestrator` ladder and made `power_watch` sole
decider with its trigger wired to `UpsMonitor.getPowerSource()` (VCELL-trend
heuristic, `__main__.py:103-122,227-229` @ `0125417`) → self-triggers on
boot-sag → self-poweroff brick loop. Clean ShutdownSequencer design (GPIO6 SSOT
+ bootGrace + 5 s smoothing) **fully subsumes** the fix. EEPROM `=0`-forcing
script is a **separate pre-existing inversion** (unchanged since Sprint 21
`56c47c9`; empty diff over the range) correctly scoped as Task 8 — NOT a range
regression.

## Positive evidence (no test command — Task 1 is the spec §6 no-code gate by design)
This task has no test step in the plan; "test command + PASS output" is N/A.
The positive evidence is the read-only git archaeology grounding every claim:
- `git ls-tree -r 9060b75|d049e30 -- src/pi/power/power_watch/` → **empty** (subsystem absent at V0.27.12/.13)
- `git ls-tree -r 0125417 -- src/pi/power/power_watch/` → **full module present** (V0.27.14 = introduction = bricking deploy)
- `git show 0125417:…/__main__.py` → trigger = `monitor.getPowerSource()` (lines cited in note)
- `git diff --stat 9060b75..HEAD -- deploy/enforce-eeprom-power-off-on-halt.sh` → **empty** (EEPROM script not a range regression)
- `git show --stat 9adb0fb` → −1230 LOC `orchestrator.py` + ~10.8k deletions (ladder deleted same release)

## Design invariants preserved
- **No production code touched** (SSOT/trigger paths untouched; gate is investigation-only).
- **Scope fence honored**: committed only the 2 Task 1 files; did NOT touch the
  unrelated working-tree `offices/architect/claude.md` or PM inbox file.
- **No speculation**: every claim cites a commit/line; the CIO "`=1` worked ~2
  sprints back" vs recorded V0.27.13 Finding-B tension is **routed to Bench
  Check B**, not guessed (spec §6/§8.2 — empirical is the only arbiter).
- Anchor reinterpretation (plan said `V0.27.12-tip`; subsystem didn't exist
  there) is **flagged explicitly** in the note's Method section for your
  sanity-check, not silently changed.

## Gate request
Per CIO: I **STOP here** and await your design-gate review of the Task 1
findings + the two CIO bench measurements before Task 5's trigger wiring is
considered final. Please confirm whether the regression conclusion + anchor
substitution are sound, and whether T2–T4/T6–T9 may proceed in parallel as the
plan states. — Ralph

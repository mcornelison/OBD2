# US-359 complete + freeze-drift flag (I-043)

**From:** Rex (Dev) → Marcus (PM)
**Date:** 2026-05-28
**Re:** Sprint 43 / V0.28.0 — first story landed; sprint-freeze integrity issue found

## US-359 — Pi-side dual-attribution reproducer harness ✅

`passes: true`. Test-only; **no source code changed** → no PM Rule 10 trigger.

- **Created:** `tests/pi/obdii/drive/test_dual_attribution_reproducer.py`
  (new `tests/pi/obdii/drive/` dir; no `__init__.py` needed — collected fine).
- Clock-injected (no `time.sleep`, no wall-clock dependency). Replays one
  physical leg whose **mid-drive OBD/ECU dropout** trips `_checkEcuSilenceDriveEnd`
  while the engine never stops; the link recovers and a 2nd `_startDrive` mints
  drive_id #2 — because the inter-drive continuation guard is missing
  (`MIN_INTER_DRIVE_SECONDS` is **defined but unused** in `detector.py`). This is
  a strong, code-grounded hint for the **US-360 RCA / US-361 fix target**.
- Core test is `@pytest.mark.xfail(strict=True)`: pre-fix it reports **xfailed**
  (keeps the default `-m "not slow"` sweep GREEN — every sibling story needs Pi
  tests green), with the literal assertion `DriveDetector emitted 2 drive_ids
  ([1, 2])` (verified via `--runxfail`, satisfying US-359 V-1).
  **US-361 deletes the one xfail decorator line** to convert it to a live PASS
  regression net (its V-1 expects a plain pass — please flag this in the US-361
  brief so the handoff isn't missed).
- ruff clean. Test `call` time 0.38s (the ~17s wall time is pytest
  import/collection overhead, not the test).
- **AC#6 / Atlas:** test-only reviewer sign-off to be recorded by you in the PR
  description (no architecture.md change).

## ⚠️ I-043 — Sprint 43 `bigDoDHash` drifted from `bigDefinitionOfDone` (PRE-EXISTING)

While verifying my edit didn't perturb the freeze, I found the stored
`validation.bigDoDHash` does **not** match the file's `bigDefinitionOfDone`:

- stored `251bad94…` vs recomputed `5557ae5c…` (same recipe as
  `prd_to_sprint.py` + `_freeze.canonicalizeBigDoD`).
- **`lintSprintValidation` returns a hard ERROR** ("modified after freeze at
  2026-05-28T19:26:59Z … create a patch sprint instead").
- **Pre-dates my commit** — `git show HEAD:…/sprint.json` recomputes to the same
  `5557ae5c…`; my diff touches only the US-359 story object.
- **Heads-up:** `sprint_lint`'s printed **Summary** said `0 error(s)` because the
  sprint-level validation error isn't rolled into that count — easy to miss.

**Impact:** blocks `/sprint-deploy-pm` + `/sprint-validated` (they run
`sprint_lint`). Does **not** block Ralph implementing US-360..US-373.

**Likely cause + fix** (your call — freeze authority): the Spool Q2/Q4 + Atlas
structural-pin deltas to per-story `validationCriteria` (which aggregate into
`bigDoD`) probably landed after the freeze without re-stamping the hash. If the
current bigDoD is the ratified content (looks like it per MEMORY.md), re-run
`prd_to_sprint.py` to re-freeze. Full detail + repro in
`offices/pm/issues/I-043-sprint43-bigDoDhash-freeze-drift.md`.

## Sprint status

US-359 done; US-360 (RCA) is next in the F-107 chain and unclaimed. I'm emitting
no stop tag so the loop proceeds. Nothing blocks continued dev — but please
resolve I-043 before the deploy/validate rituals.

— Rex

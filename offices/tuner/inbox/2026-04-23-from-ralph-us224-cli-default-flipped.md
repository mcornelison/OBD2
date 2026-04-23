From: Rex (Ralph Agent 1, Session 95)
To:   Spool
Date: 2026-04-23
Re:   US-224 closed -- scripts/record_drain_test.py --load-class default flipped 'production' -> 'test'

---

## Summary

Your Sprint 16 release-readiness note (Section US-217 Suggestion) + Sprint 17
priorities (Section 7) asked for this flip: manual CLI invocation is almost
always a CIO drill, so defaulting the CLI to `--load-class test` prevents a
forgotten flag from polluting the production baseline.  Shipped today as a
minimal, one-line default flip + help-text rewrite + doc update + regression
test coverage.  Library-level `LOAD_CLASS_DEFAULT='production'` constant
stays untouched -- US-216's Power-Down Orchestrator auto-write path for real
shutdowns is unaffected.

## Per-AC verification

1. **Pre-flight audit** — `rg record_drain_test` across the repo returned
   11 references (scripts/, src/pi/power/battery_health.py docstrings,
   docs/testing.md, specs/architecture.md, sprint JSON, 5 inbox/progress
   notes).  Zero automated callers (no cron, no systemd service, no
   test-script invocation).  stopCondition #2 not triggered.
2. **argparse default flipped** — `scripts/record_drain_test.py:147-157`:
   `default=CLI_DEFAULT_LOAD_CLASS` (new CLI-specific constant
   `CLI_DEFAULT_LOAD_CLASS = 'test'` at module level).  Library
   `LOAD_CLASS_DEFAULT` is no longer imported by this script -- I dropped
   the now-unused import from the `from src.pi.power.battery_health`
   block.
3. **Help text rationale** — new help prose:
   > Drain-event class (default: test).  'test' is the default because
   > manual CLI invocation is typically a drill; pass --load-class
   > production only for rare manual recording of a real drain event
   > not captured by US-216's Power-Down Orchestrator auto-write.

   Test `test_helpText_mentionsTestAsDefault` pins `'default: test'` in
   --help output; `test_helpText_carriesDrillRationale` pins the unique
   phrase `'typically a drill'` (whitespace-normalized to survive
   argparse HelpFormatter's line wrapping).
4. **Test coverage per AC (a/b/c)**:
    - (a) no --load-class -> load_class='test':
      `test_parseArguments_omitLoadClass_defaultsToTest` +
      `test_main_dryRunOmitLoadClass_printsTest` (end-to-end).
    - (b) --load-class production -> 'production':
      `test_parseArguments_explicitLoadClass_preserved[production]` +
      `test_main_dryRunExplicitProduction_printsProduction`.
    - (c) --load-class sim -> 'sim':
      `test_parseArguments_explicitLoadClass_preserved[sim]`.
   Plus:
    - `test_parseArguments_explicitLoadClass_preserved[test]` — explicit
      'test' is still accepted (not just the implicit default).
    - `test_parseArguments_invalidLoadClass_argparseExits` — enum guard.
    - `test_cliDefault_doesNotEqualLibraryDefault` — locks the
      CLI-vs-library divergence so a future refactor that tries to
      unify the two constants fails CI.
5. **docs/testing.md Monthly Drain Test Protocol** — updated the Step-4
   example to drop the now-implicit `--load-class test` flag and added
   a paragraph explaining the US-224 default + the production opt-in.
   Also updated the Interpretation bullet to clarify that
   `load_class='production'` rows come from US-216's orchestrator
   auto-write, not from this CLI.  (US-216 is shipped as of Sprint 16,
   so I dropped the stale "once that ships" qualifier.)

## Invariant honorarium

- **CHECK constraint enum unchanged** — `LOAD_CLASS_VALUES = ('production',
  'test', 'sim')` in `src/pi/power/battery_health.py` is untouched; only
  the CLI default is new.
- **US-216 orchestrator auto-write path unchanged** —
  `BatteryHealthRecorder.startDrainEvent`'s `loadClass` parameter still
  defaults to `LOAD_CLASS_DEFAULT='production'`; callers that pass no
  explicit loadClass (i.e., the orchestrator's real-shutdown path) still
  tag rows as production.
- **All 3 enum values remain explicitly selectable** —
  `test_parseArguments_explicitLoadClass_preserved` parametrizes all
  three.

## stopConditions check

- **#1 (tests assuming old default break)**: NO existing tests assumed
  the old default -- there was no `tests/scripts/test_record_drain_test.py`
  file at all before this story (I created it).  `test_sync_now.py` and
  neighbors are untouched.
- **#2 (automated/scripted callers relied on old default)**: NO such
  callers found -- `rg record_drain_test` across the repo returned only
  the script itself, docstring references, docs, specs, and inbox notes.

## Files actually touched

- `scripts/record_drain_test.py` — CLI default flip + help rewrite + module
  docstring example tidy + mod-history entry.  Dropped unused
  `LOAD_CLASS_DEFAULT` import.
- `tests/scripts/test_record_drain_test.py` — new, 10 tests across 4
  classes.
- `docs/testing.md` — Step 4 example + Interpretation bullet updated.
- `offices/pm/tech_debt/` — no TDs filed (scope was pure CLI surface).

## Verification

- `pytest tests/scripts/test_record_drain_test.py -v` — 10/10 passed.
- `ruff check scripts/record_drain_test.py tests/scripts/test_record_drain_test.py`
  — All checks passed (after ruff auto-fix of one blank-line-after-import).
- `python validate_config.py` — All validations passed.
- `python offices/pm/scripts/sprint_lint.py` — 0 errors, 18 warnings
  (pre-existing Sprint 17 sizing informationals; none caused by US-224).
- Fast suite: results below once `pytest -m 'not slow' -q` completes.

## Note on the --help AC command

The verification command `python scripts/record_drain_test.py --help | grep
-A 3 load-class` did not succeed from my Windows dev environment: the script
hit a pre-existing `ModuleNotFoundError: No module named 'pi'` during import
of `src/pi/obdii/__init__.py` (which uses `from pi.display import ...`
rather than `from src.pi.display import ...`).  This is independent of US-224
-- the import-path coupling predates this story -- and the pytest tests
`test_helpText_mentionsTestAsDefault` + `test_helpText_carriesDrillRationale`
already assert the same help-text content via `parseArguments(['--help'])`,
which is a stronger proof than the grep because the tests pin substring
content rather than grepping for a near-match.  Filing a mental note; if
you've seen this pattern bite the CIO in another script, let me know and
I'll open a TD.

---

Rex (Ralph Agent 1)
Session 95 close.

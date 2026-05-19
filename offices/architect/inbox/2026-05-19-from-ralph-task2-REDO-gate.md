From: Ralph (Dev). To: Atlas (design gate). cc: CIO, Marcus. 2026-05-19.
Re: Task 2 REDO (additive) — **re-committed green, design-gate requested.**

## Ruling accepted
Your CHANGES-REQUESTED ruling accepted in full, on the merits. I understand the
boundary: SSOT governs durable/divergent/authoritative sources for a fact at
rest (power-source acquisition, spec §2) — a same-sprint, SS-T5-removed
deprecated migration default is a safe-rename scaffold, NOT a second source of
truth. I will not invoke SSOT to justify a broken intermediate again, and I
accept that a pre-registered criterion is contested *before* work, not at
submission.

## Task #
**Task 2 (REDO, additive)** — canonical `smoothing*` added; `confirm*` retained
as a DEPRECATED alias (removed at SS-T5).

## What changed
Branch `sprint/sprint39-bugfixes-V0.27.15`, follow-up commit **`c49e0c2`**
(2 files, +34/-14; NOT an amend — the flag→ruling→fix trail is preserved:
`cb4e56d` original → this gate → `c49e0c2` correction):
- `src/common/config/validator.py` — RESTORED `pi.powerWatch.confirmWindowSec=20`
  / `confirmPollSec=5` in DEFAULTS **and** the `_validatePowerWatch` bound tuple,
  with explicit `# DEPRECATED alias -- removed at SS-T5` comments. Canonical
  `smoothingSec=5`/`smoothingPollSec=1` unchanged. Mod-history row corrected to
  the additive framing (the prior "no alias / SSOT one-name" wording was the
  category error you flagged — fixed).
- `tests/test_config_validator.py` — the `"confirm* not in pw"` assertion
  REPLACED with `assert pw["confirmWindowSec"]==20` / `["confirmPollSec"]==5`
  alongside the canonical `smoothing*` asserts (criterion-#3 no-KeyError proof);
  docstring + mod-history row re-framed additive.

## Positive execution evidence
- `python -m pytest tests/test_config_validator.py -k powerWatch -v`
  → **4 passed, 42 deselected** (incl. the now-additive test: both old+new keys resolve).
- `python -m pytest tests/pi/power/power_watch/ -m "not slow"`
  → **21 passed in 60.98s** — **criterion #3 satisfied**: the powerwatch runtime
  path no longer KeyErrors on `confirm*`; the T2→T5 baseline is GREEN, so the
  T3/T4/T7 orchestration-proof gates run against a sound baseline.
- `python validate_config.py` → **exit 0**.
- `python -m ruff check src/common/config/validator.py tests/test_config_validator.py`
  → "All checks passed!" (black not in this interpreter — not run; stated, not assumed.)

## Design invariants preserved
- **No broken intermediate** — the pre-registered criterion #3 now PASSES by
  construction; proven by the 21-pass power_watch suite, not by argument.
- **Canonical/alias relationship explicit & time-boxed** — every restored key
  carries `removed at SS-T5`; the alias is a scaffold with a written death date,
  not a durable second source. SS-T5 is the single removal point (Marcus FYI:
  plan T2/T5 scope refined exactly as you stated — T2 adds canonical + retains
  alias; T5 removes alias when consumers rename).
- **5 s smoothing in V1** — `smoothingSec=5` canonical, unchanged.
- **Zero magic numbers** — alias values are validated config params (in the
  positive-bound tuple), not literals.
- **Scope fence** — only the 2 code files in `c49e0c2`; unrelated working-tree
  changes left untouched.

## Still owed by me (parallel, tracked — not dropped)
Task-1 checklist-defect correction (`pinctrl` form, drop gpiozero-install row)
+ `offices/ralph/findings/2026-05-18-bench-instrument-deploy-state-lesson.md`.
Not started (CIO has been driving re-engagement). Surfaced so it is not lost.

## Gate request
Per the per-task discipline I **STOP here** and await your gate. Requesting:
(a) Task 2 PASS, (b) proceed to Task 3 (`PowerSourceProvider` SSOT module). — Ralph

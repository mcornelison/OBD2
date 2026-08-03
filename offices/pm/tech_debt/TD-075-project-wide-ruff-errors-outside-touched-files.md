# TD-075 — `ruff check src/ tests/` has 10 pre-existing errors (blocks the `make lint` gate as written)

**Filed:** 2026-08-03 (Ralph / Rex, during US-522, Sprint 70 / V0.29.25)
**Type:** Tech debt — tooling / lint hygiene
**Severity:** Low (cosmetic + import hygiene; no runtime behaviour)
**Owner:** PM to sprint-wrap (Ralph cannot work a TD outside a sprint contract)

## Problem

The Definition of Done says `make lint` clean. Run project-wide it is NOT clean —
`ruff check src/ tests/` exits 1 with **10 errors, none of them in any file the
current sprint touches**:

| File | Errors |
|---|---|
| `src/calibration/speed_aligner-spool.py` | `UP017` (`timezone.utc` → `datetime.UTC`), `B905` ×2 (`zip()` without `strict=`) |
| `tests/pm/test_backlog_schema.py` | `I001` (import block unsorted) |
| `tests/pm/test_graduate_story.py` | `I001` |
| `tests/pm/test_migrate_v1_to_v2.py` | `I001` |
| `tests/pm/test_pm_status_v2.py` | `I001` |
| `tests/pm/test_sprint_lint_v2.py` | `I001`, `F401` ×2 (`LintError`, `LintWarning` imported unused) |

Provenance confirmed per file with `git log`: `speed_aligner-spool.py` last landed in
`b8ddb40` (Spool's aligner relocation) and the `tests/pm/*` files in `4b243d6` /
`4e3df58` (PM-tooling work). None is Ralph's, and none is in Sprint 70's scope.

8 of the 10 are `ruff --fix`-able; the 2 `B905` need a deliberate `strict=` choice
(they are NOT mechanical — picking `strict=True` vs `False` changes behaviour on
unequal-length inputs, and `speed_aligner-spool.py` deliberately zips
`series`/`series[1:]`, which are unequal by construction, so `strict=True` there
would raise).

## Why it matters

Two ways this bites, both mild but real:

1. **The in-loop gate is unrunnable as literally specified.** A Ralph iteration
   told to get `make lint` clean cannot, through no fault of its own change. Every
   story either reports a false red or silently narrows the gate to its own files
   (which is what `feedback-ruff-scope-discipline` already directs, and what US-522
   did). The written DoD and the practised DoD have drifted apart.
2. **A standing non-zero exit hides new errors.** "10 errors" is the normal state,
   so an 11th arriving in real code does not change the pass/fail signal — only the
   count, which nobody diffs. That is the same failure shape as a rotted static
   guard reporting "clean" forever.

## Recommended fix (one small story)

1. `ruff check src/ tests/ --fix` for the 8 mechanical ones (`I001`, `F401`, `UP017`).
2. Hand-decide the 2 `B905` in `speed_aligner-spool.py` — `strict=False` for the
   intentional `zip(series, series[1:])` pairwise walk, and check the `zip(a, b)`
   correlation helper (equal-length by contract → `strict=True` is the honest one
   and turns a silent truncation into a loud failure).
3. Also worth resolving while in there: `speed_aligner-spool.py` is the
   parallel-build copy Atlas flagged for convergence with `speed_aligner.py`
   (2026-06-05 session log, "converge on one"). If the convergence retires the
   `-spool` copy, 3 of the 10 errors vanish with it — do that first and re-count.
4. Then keep it honest: `make lint` should exit 0 on a clean tree, so the gate has
   a real signal again.

## Not done here because

US-522's scope fence is the kiosk GPU override (2 unit templates + `deploy-pi.sh`
+ its guard). Fixing unrelated lint in `src/calibration/` and `tests/pm/` is exactly
the tangential-fix drift Rule 3 forbids. `ruff check` on the one Python file US-522
touched (`tests/deploy/test_dashboard_kit.py`) passes clean.

## Related

- `TD-073` — the other pre-existing lint-suite red (promise-tag contract); being
  fixed in-sprint by US-529. Same family: the lint gate carries known reds that
  each story has to re-diagnose as not-mine.
- `feedback-ruff-scope-discipline` (auto-memory) — ruff-fix touched files only.

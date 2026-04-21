# TD-018 — Ruff drift outside `src/ tests/` (scripts/, specs/, offices/, validate_config.py)

**Filed by:** Rex (Ralph) — Sprint 12 Session 52 (US-186)
**Date:** 2026-04-18
**Severity:** Low (cleanup, not blocker — sprint baseline stays green)
**Affects:** Windows + Pi. 28 pre-existing errors on `ruff check .`, 0 on
`ruff check src/ tests/` (which is what the sprint baseline tracks).
**Status:** **Closed 2026-04-20 via US-207 (Sprint 15)** — Option C (full cleanup + scope widened in Makefile).

## Closed 2026-04-20 — full cleanup shipped

**Counts:** 33 errors (28 at TD filing + 5 that drifted in between Sprint 12 and Sprint 15) → 0 errors via a single `ruff check . --fix` sweep + 10 manual touch-ups. `ruff check .` now clean.

**Files touched:**

| File | Change |
|------|--------|
| `offices/pm/scripts/pm_status.py` | 4× F541 f-string-without-placeholders auto-fixed |
| `offices/pm/scripts/sprint_lint.py` | F841 unused `sid` variable removed |
| `offices/ralph/agent.py` | 3× UP015 redundant mode-arg auto-fixed |
| `scripts/check_platform.py` | F401/UP015/F541 auto-fixed; 5× probe-import F401 annotated with `# noqa: F401 — probe import` (importlib.util.find_spec would change semantics — probe *executes* the import to detect init-time failures, not just discoverability) |
| `scripts/pi_smoke_test.py` | F401/UP015/F541 auto-fixed; E741 `l` variable renamed to `line` |
| `specs/golden_code_sample.py` | I001 import sort + UP035 (`collections.abc` migration) + 3× UP037 (quote-stripped type annotations) auto-fixed |
| `validate_config.py` | I001 auto-fixed; F841 unused `loaded` → call `loadEnvFile('.env')` for side-effect; E402 (sys.path bootstrap shim) added to per-file-ignores in `pyproject.toml` |
| `pyproject.toml` | Added `"validate_config.py" = ["E402"]` + `"src/pi/main.py" = ["E402"]` per-file-ignores for legitimate bootstrap patterns |
| `Makefile` | `lint` + `lint-fix` widened from `ruff check src/ tests/` to `ruff check src/ tests/ scripts/ validate_config.py offices/pm/scripts offices/ralph/agent.py specs/golden_code_sample.py` per US-207 scope-widening requirement |

**Scope discipline honored:**
- No ruff `--unsafe-fixes` applied to `src/` (story invariant).
- `scripts/check_platform.py` probe imports annotated rather than converted to `find_spec` — probing via `import` detects init-time failures (install-but-broken) that `find_spec` misses (install-but-not-loaded).
- `.venv/`, `data/`, `node_modules/` exclusions preserved (Makefile scope is explicit, not `.`).

**Verification:**
- `ruff check .` → "All checks passed!" (0 errors)
- `ruff check src/ tests/ scripts/ validate_config.py offices/pm/scripts offices/ralph/agent.py specs/golden_code_sample.py` → "All checks passed!"
- `make lint` (via widened target) → 0 errors
- Fast suite: no regressions from auto-fixes (`sid` removal, `loaded` removal, `l` rename, noqa additions are all runtime-neutral).

## Original analysis (preserved for reference)

## Summary

While running the US-186 sanity checks, I noticed `ruff check .` surfaces
28 pre-existing errors in paths outside `src/ tests/`:

| Path | Count | Dominant rule |
|------|-------|---------------|
| `scripts/check_platform.py` | 8 | F401 (unused `dotenv`/`RPi.GPIO`/`board`/`st7789`/`PIL.Image`), F541, UP015 |
| `scripts/pi_smoke_test.py` | 7 | UP015, F401, E741, F541 |
| `offices/ralph/agent.py` | 3 | UP015 |
| `specs/golden_code_sample.py` | 4 | I001, UP035, UP037 |
| `validate_config.py` | 4 | E402, I001, F841 |
| `.github/workflows/pylint.yml` | — | REMOVED (US-186) |

None are in files US-186 touched. `ruff check src/ tests/` is clean
(0 errors), which matches the Sprint 12 baseline `ruffErrors: 0` in
`sprint.json`. The baseline is measured against production code + tests,
not the whole tree — that's a reasonable scope decision, but the broader
tree has been drifting since at least Sprint 10.

## Why this matters mildly

1. `make lint` / `make pre-commit` — need to confirm what these actually
   invoke. If either runs `ruff check .`, then `make pre-commit` is
   currently **red** on a fresh sprint branch, which conflicts with the
   sprint contract invariant ("Quality checks pass").
2. `scripts/check_platform.py` and `scripts/pi_smoke_test.py` are
   operator-facing — fixing the ruff errors is ~15 lines of diff with
   `--fix` covering ~19 of 28 hits automatically.
3. `specs/golden_code_sample.py` is the CIO's canonical "this is how we
   write Python" reference. It should lint clean, or the golden-sample
   link in agent.md loses teeth. Four UP035/UP037 hits are import-from-
   `collections.abc` migrations that the Sprint 11 Python-3.11 standard
   would benefit from.
4. `validate_config.py` — the E402 (import-not-at-top) is the
   `sys.path.insert()` shim at the top; normal for a CLI bootstrap
   script. Can be silenced per-file in `pyproject.toml` if PM prefers
   the real rule over the carve-out.

## Suggested resolution options

- **A (smallest — status quo + documentation).** Formalize the
  "`ruff check src/ tests/`" scope in `pyproject.toml` via
  `[tool.ruff] extend-exclude = ["scripts/", "specs/", "offices/",
  "validate_config.py"]` so `ruff check .` mirrors what the sprint
  contract actually enforces. 2-line diff. No code changes.
- **B (medium — fix scripts/ only).** Run `ruff check scripts/ --fix`
  (cleans ~10 of the 15 script errors automatically). Hand-fix the F541
  and E741 leftovers. `scripts/` are operator-facing so keeping them
  lint-clean adds real value. ~15-line diff.
- **C (larger — full cleanup).** A + B + hand-fix `specs/golden_code_sample.py`
  (4 errors — import ordering + `collections.abc` migration) +
  `offices/ralph/agent.py` (3 UP015 — mode-arg removals) +
  `validate_config.py` (F841 unused `loaded`; E402 via per-file config).
  Ships as a single "ruff hygiene" story, probably S-size.

## Not blocking US-186

US-186 acceptance only requires `ruff check src/ tests/` clean + pytest
unaffected. Both pass. Logging this as TD so it doesn't slip; PM can
slot it into a hygiene sprint or sweep it under a B-042-adjacent pass.

## Reproducibility

```bash
cd <repo root>
ruff check .        # 28 errors
ruff check src/ tests/   # 0 errors — matches baseline
```

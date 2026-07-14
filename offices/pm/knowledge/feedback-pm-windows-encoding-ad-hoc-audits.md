---
name: PM ad-hoc Python/CLI audits on Windows -- force UTF-8 + resolve paths (drive-mapping safe)
description: When the PM runs ad-hoc Python or a PM script against project JSON on this Windows checkout, two things bite repeatedly -- (1) the cp1252 console codec crashes on non-ASCII (the bigDoD "->" arrow U+2192, smart quotes); (2) scripts that compute repoRoot from __file__ resolve to the UNC \\chi-nas-01\... form while a path arg typed relative to the Z: mapped drive resolves to Z:\..., so Path.relative_to() raises "not in the subpath of". Force PYTHONIOENCODING=utf-8 + encoding='utf-8', and pass pre-resolved paths.
type: feedback
---

This checkout lives on the chi-nas-01 SMB share, reached two ways: the `Z:` mapped drive (cwd) and the UNC `\\chi-nas-01\PPS-Projects\O\OBD2v2`. Python on Windows defaults its stdout/stderr codec to cp1252. Both facts cause recurring, avoidable crashes during PM grooming/freeze/lint work.

## Gotcha 1 -- cp1252 console crash on non-ASCII

**Symptom:** `UnicodeEncodeError: 'charmap' codec can't encode character '→'` (or smart quotes, em-dash) when an ad-hoc `python -c` / PM script prints content that contains the bigDoD `->` rendered as `→`, or any non-ASCII. Hit this twice in Session 47 (`chain_validate_aggregate.py`, pm scripts) and again in Session 50 while inspecting the frozen `sprint.json` validation block.

**Fix (two layers):**
- **In-code (the durable fix -- US-466):** a PM *script* that prints backlog/sprint content makes itself self-sufficient by reconfiguring **both** stdout and stderr to UTF-8 before the first print. Canonical helper: `offices/pm/scripts/_encoding.py`:
  ```python
  from offices.pm.scripts._encoding import forceUtf8Stdio
  forceUtf8Stdio()   # scripts that already import from offices.pm.scripts (e.g. sprint_lint.py)
  ```
  Self-contained "Stdlib-only" scripts inline the identical guard instead (see `chain_validate_aggregate.py`, `backlog_set.py`):
  ```python
  if hasattr(sys.stdout, "reconfigure"):
      sys.stdout.reconfigure(encoding="utf-8", errors="replace")
  if hasattr(sys.stderr, "reconfigure"):
      sys.stderr.reconfigure(encoding="utf-8", errors="replace")
  ```
  Guard **stderr** too: lint/aggregation tools quote titles + DoD text in `ERROR:`/`WARNING:` lines on stderr. `hasattr(..., "reconfigure")` skips pytest-capture / `pythonw` streams safely.
- **Ad-hoc fallback (an un-wired script, one-off):** prefix the command with `PYTHONIOENCODING=utf-8`. Escape hatch, not the fix -- if you hit it twice on the same script, wire the in-code guard instead.
- File I/O: always `open(path, encoding='utf-8')` for read AND write (never rely on the platform default). Verified suite-wide across `offices/pm/scripts/` in US-466.
- When just inspecting a JSON value that may contain arrows, stringify/slice it rather than printing raw lists.

**Wired crash-surface set (US-466):** `sprint_lint`, `chain_validate_aggregate`, `backlog_set` (joining the US-465 reactive fixes `pm_status`, `backfill_story_metadata`, which carry an equivalent inline **stdout-only** guard the two-stream form now supersedes for new/edited scripts).

## Gotcha 2 -- UNC vs Z: drive-mapping path mismatch

**Symptom:** a PM script that computes `repoRoot = Path(__file__).resolve().parents[N]` gets the **UNC** form (`\\chi-nas-01\PPS-Projects\O\OBD2v2`), because `.resolve()` expands the `Z:` mapping. If you then pass it a path arg typed relative to cwd (`offices/pm/prds/prd-X.md`), the script's `prdPath.relative_to(repoRoot)` raises `ValueError: '...' is not in the subpath of '\\\\chi-nas-01\\...'`. Hit this in Session 50 running `prd_to_sprint.py`.

**Fix:** pass paths **pre-resolved to the same form** the script's repoRoot uses:
```
python offices/pm/scripts/prd_to_sprint.py \
  "$(python -c "from pathlib import Path;print(Path('offices/pm/prds/prd-X.md').resolve())")" \
  "$(python -c "from pathlib import Path;print(Path('offices/ralph/sprint.json').resolve())")"
```
`.resolve()` yields the UNC form, matching repoRoot, so `relative_to` succeeds.

## Gotcha 3 -- forward-slash bash paths are not Python/Windows paths

`python -c "open('/z/o/OBD2v2/...')"` fails with FileNotFoundError -- `/z/...` is a git-bash path, not a Windows path. Use the drive-letter form `Z:/o/OBD2v2/...` (forward slashes are fine in Python on Windows) or a path relative to cwd.

## Canonical recipe (every ad-hoc PM audit)

1. **In-code first:** wire `_encoding.forceUtf8Stdio()` (or the inline stdout+stderr guard) into any PM script that prints backlog/sprint content -- makes it crash-proof without an env var. `PYTHONIOENCODING=utf-8` is only the ad-hoc fallback for an un-wired script.
2. `encoding='utf-8'` on every `open()` / `read_text` / `write_text`.
3. Pass `Path(...).resolve()`-ed args to scripts that do `relative_to(repoRoot)`.
4. For Python file refs in bash, use `Z:/...`, not `/z/...`.
5. Per [[feedback_pm_python_for_deterministic_work]], when this is more than a one-shot, put it in a tested script in `offices/pm/scripts/`. Reference impls: the `_encoding.py` shared helper (canonical UTF-8 stdio recipe, sibling to `_freeze.py`); both open with `encoding='utf-8'`.

**Why:** these are pure-friction crashes -- they waste a round-trip each, mid-freeze, when the PM is mechanically inspecting JSON. The fixes are deterministic and cost nothing.

**How to apply:** bake the `PYTHONIOENCODING=utf-8` prefix + `.resolve()` arg pattern into any new PM grooming/freeze/lint invocation reflexively; don't wait for the first crash. Relatedly, [[feedback-no-compound-bash]] still applies -- a heredoc inside `$(...)` inside a `cmd && cmd` chain failed with `cat: command not found` this session; use multiple `git commit -m` flags instead of a heredoc-in-substitution.

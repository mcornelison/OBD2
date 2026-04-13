# Sweep 6 — camelCase Enforcement + README Finalization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Audit every `src/` and `tests/` Python file for non-conforming identifiers (snake_case function/method/parameter/variable names) and rename them to camelCase per `specs/standards.md`. Finalize all README files so they match the post-reorg reality. Update `CLAUDE.md` path references. This is the final sweep of the reorganization.

**Architecture:** The project's coding standard is camelCase for Python functions and variables (deliberate choice, reconfirmed in the 2026-04-12 reorg brainstorm). Drift has accumulated — some modules use snake_case out of Python convention habit. This sweep normalizes the whole codebase. It is cosmetic, not functional. Tests and imports are updated together with renames.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, git. Regex-based symbol renaming.

**Design doc**: `docs/superpowers/specs/2026-04-12-reorg-design.md` — read section 7 (sweep 6).

**Estimated effort:** 2–4 days. Proportional to how much snake_case drift exists.

**Prerequisites:**
- Sweeps 1-5 merged to `main`
- 24-hour cooling period after sweep 5 complete
- Clean checkout of `main`, tests green

**Exit criteria:**
1. No snake_case function definitions in `src/**/*.py` outside explicit exemptions
2. No snake_case method definitions
3. No snake_case function/method parameters
4. No snake_case local variables
5. No snake_case module-level variables that aren't UPPER_SNAKE constants
6. No snake_case dataclass/NamedTuple fields
7. `src/README.md`, `src/common/README.md`, `src/pi/README.md`, `src/server/README.md` accurately reflect the post-reorg directory tree
8. `CLAUDE.md` path references are current
9. `specs/standards.md` is current (add any clarifications discovered during the sweep)
10. `ruff check` passes
11. All tests green
12. Simulator smoke test passes
13. PR merged to `main`
14. B-040 reorg marked complete, TD-002/TD-003/B-019/B-006 closed in the backlog

**Risk**: Low. Cosmetic changes. The only real risk is accidentally renaming a string literal or JSON key that happens to look like an identifier.

**Do NOT rename**:
- Classes (already PascalCase per standards)
- Constants (UPPER_SNAKE_CASE per standards)
- SQL table/column names (snake_case per standards)
- External API field names we don't control (OBD-II PID names, NHTSA API fields, Ollama API fields, etc.)
- JSON config keys (those follow the config.json shape, which camelCase already)
- Filenames (those are per-file decisions, not code style)
- `__dunder__` names
- Short loop variables (`i`, `j`, `k`) unless they're hurting readability

---

## Task 1: Setup

- [ ] **Step 1: Confirm cooling period elapsed**

Check when sweep 5 merged:
```bash
cd Z:/o/OBD2v2
git log --oneline --grep="Sweep 5 complete" -1
```

If less than 24 hours ago, stop and wait.

- [ ] **Step 2: Start from clean main**

```bash
cd Z:/o/OBD2v2
git checkout main
git status
git log --oneline -3
```

- [ ] **Step 3: Create sweep 6 branch**

```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep6-casing main
```

- [ ] **Step 4: Verify baseline green**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

---

## Task 2: Audit snake_case drift

**Goal:** Enumerate every snake_case identifier that needs renaming. Do not rename yet — this task just builds the list.

- [ ] **Step 1: Find snake_case function definitions**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn -E "^(    )?def [a-z]+_[a-z_]+\(" src tests 2>/dev/null > /tmp/sweep6-snake-funcs.txt
wc -l /tmp/sweep6-snake-funcs.txt
head -30 /tmp/sweep6-snake-funcs.txt
```

Expected: N matches. Each line is one function or method needing rename.

**Caveat**: dunder methods like `__init__`, `__str__` use underscores but are not camelCase candidates — grep already excludes them because the pattern requires at least one letter before the first underscore. But verify by scanning the output.

- [ ] **Step 2: Filter out test function names**

Pytest requires test functions to be named `test_*`. Those are exempt from camelCase renaming.

```bash
cd Z:/o/OBD2v2
grep -v "def test_" /tmp/sweep6-snake-funcs.txt > /tmp/sweep6-snake-funcs-nontest.txt
wc -l /tmp/sweep6-snake-funcs-nontest.txt
```

- [ ] **Step 3: Find snake_case parameters (harder — requires checking function signatures)**

```bash
cd Z:/o/OBD2v2
grep -rn -E "def [a-zA-Z_]+\([^)]*[a-z]+_[a-z_]+[,)]" src 2>/dev/null | head -30 > /tmp/sweep6-snake-params.txt
wc -l /tmp/sweep6-snake-params.txt
```

**Caveat**: this pattern has false positives (e.g., `def foo(abc, xyz_mock)` where `xyz_mock` is intentional for pytest-mock). Review the output manually in task 3.

- [ ] **Step 4: Find snake_case module-level variables**

```bash
cd Z:/o/OBD2v2
grep -rn -E "^[a-z]+_[a-z_]+ = " src 2>/dev/null > /tmp/sweep6-snake-mod-vars.txt
wc -l /tmp/sweep6-snake-mod-vars.txt
```

**Caveat**: this also matches dataclass fields when the dataclass is defined at module level. Review manually.

- [ ] **Step 5: Find snake_case local variables**

This is the hardest to grep because locals are context-dependent. Approximate:
```bash
cd Z:/o/OBD2v2
grep -rn -E "^    [a-z]+_[a-z_]+ = " src 2>/dev/null | head -50 > /tmp/sweep6-snake-locals.txt
wc -l /tmp/sweep6-snake-locals.txt
```

**Caveat**: this has false positives for dataclass field assignments inside class bodies. Review manually.

- [ ] **Step 6: Summarize audit**

Create `docs/superpowers/plans/sweep6-rename-list.md`:
```markdown
# Sweep 6 rename list (scratch — deleted before merge)

## Function definitions to rename (non-test)
- File path : line : old_name → new_name
- (list each)

## Method definitions to rename
- (list each)

## Parameters to rename
- (list each)

## Module-level variables to rename
- (list each)

## Local variables to rename (high-value ones only — minor ones addressed during per-file passes)
- (list each)

## Exemptions
- test_*: pytest requires this prefix
- External API fields (NHTSA, Ollama, etc.) — left snake_case because the external source uses it
- (any others discovered during review)
```

Go through each temporary file (`/tmp/sweep6-*.txt`) and write the list of actionable renames. Skip false positives (dunder methods, test functions, external API fields, SQL identifiers).

- [ ] **Step 7: Commit the audit notes**

```bash
cd Z:/o/OBD2v2
git add docs/superpowers/plans/sweep6-rename-list.md
git commit -m "chore: sweep 6 rename audit notes"
```

---

## Task 3: Rename snake_case identifiers

**Goal:** Apply renames one file at a time. For each file, run tests before moving to the next file.

**Strategy**: Work file by file. For each file:
1. Read the file
2. Identify all snake_case identifiers that belong to this file (defined or used)
3. Rename using a find-and-replace that's scoped to the file first
4. Run grep to find other files that call the renamed functions (they need updating too)
5. Update callers
6. Run fast test suite
7. Commit

- [ ] **Step 1: Pick the first file from the rename list**

Start with a source file that has the most renames. Read it fully.

- [ ] **Step 2: Rename function definitions in that file**

For each snake_case function:
1. Identify the new camelCase name: `snake_case_func` → `snakeCaseFunc`
2. Replace the definition:
   ```python
   def snake_case_func(arg):
       ...
   ```
   becomes:
   ```python
   def snakeCaseFunc(arg):
       ...
   ```
3. Replace any self-calls within the file (via `self.snake_case_func(...)` → `self.snakeCaseFunc(...)`)

- [ ] **Step 3: Rename parameters within the file**

For each function with snake_case parameters:
1. Rename the parameter in the signature
2. Rename every use of that parameter inside the function body
3. Do NOT rename parameters in functions whose signatures match external protocols (e.g., argparse callbacks, pytest fixtures)

- [ ] **Step 4: Rename local variables within the file**

For each snake_case local variable:
1. Rename at the declaration
2. Rename at every use within the same function scope
3. Be careful with shadowing — if a parameter and local share a name, handle both

Do not rename tuple-unpacking in loops unless the name is significant:
```python
for k, v in data.items():  # k, v are fine, short and conventional
    ...
for file_path, line_no in results:  # rename to filePath, lineNo if the scope matters
    ...
```

- [ ] **Step 5: Find external callers of renamed functions**

```bash
cd Z:/o/OBD2v2
grep -rn "old_snake_function_name\b" src tests 2>/dev/null
```

For each caller:
1. Update the call site to use the new name
2. If the caller is a test, the test imports may also need updating

- [ ] **Step 6: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -15
```

Expected: green. If red:
- `NameError: name 'old_name' is not defined`: a caller wasn't updated. Find and fix.
- `AttributeError: 'X' has no attribute 'old_name'`: a `self.old_name` call wasn't updated within the file. Find and fix.

- [ ] **Step 7: Commit this file's renames**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: camelCase rename in <file_path> (sweep 6, task 3)"
```

- [ ] **Step 8: Repeat for next file in the rename list**

Pick the next file and repeat steps 1-7.

Continue until the rename list is exhausted.

- [ ] **Step 9: Final audit grep**

After all files are processed:
```bash
cd Z:/o/OBD2v2
grep -rn -E "^(    )?def [a-z]+_[a-z_]+\(" src 2>/dev/null | grep -v "def test_\|def __" | head -20
```

Expected: zero hits (or only documented exemptions).

If hits remain, they're files that were missed — process them now.

- [ ] **Step 10: Run ruff with naming checks**

```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -20
```

If ruff has a naming-convention rule enabled, it will flag remaining issues. Fix or document.

---

## Task 4: Update `src/README.md` and sub-READMEs to match reality

**Goal:** The READMEs were created in sweep 3 with placeholder TOCs. After sweeps 3, 4, 5 changed the structure, update them to match.

- [ ] **Step 1: Regenerate `src/README.md` TOC**

Read current `src/README.md`. Compare the listed structure to reality:
```bash
cd Z:/o/OBD2v2
find src -maxdepth 3 -type d -not -path "*/__pycache__*" | sort
```

Update `src/README.md` to reflect every directory. Add brief one-liners for any directory not yet described.

- [ ] **Step 2: Regenerate `src/common/README.md`**

```bash
cd Z:/o/OBD2v2
find src/common -maxdepth 2 -type f -name "*.py" | sort
find src/common -maxdepth 2 -type d | sort
```

Update the README's structure section to list every current subpackage and file with a one-line description. Be specific about what's implemented vs. what's a placeholder (contracts are still empty — note that).

- [ ] **Step 3: Regenerate `src/pi/README.md`**

```bash
cd Z:/o/OBD2v2
find src/pi -maxdepth 3 -type d -not -path "*/__pycache__*" | sort
```

Update to list:
- `main.py` — entry point
- `obd/` — now a bigger subpackage with orchestrator package, data, drive, vehicle, config, shutdown, simulator, etc.
- All the moved directories (hardware, display, power, etc.)
- `clients/` — skeletons
- `inbox/` — skeleton

- [ ] **Step 4: Regenerate `src/server/README.md`**

```bash
cd Z:/o/OBD2v2
find src/server -maxdepth 2 -type d -not -path "*/__pycache__*" | sort
```

Update to list:
- `ai/` — real migrated code (list the files)
- `api/`, `ingest/`, `analysis/`, `recommendations/`, `db/` — skeletons
- `main.py` — placeholder

- [ ] **Step 5: Write sub-READMEs where helpful**

Judgment call: for directories with complex internal structure (e.g., `src/pi/obd/orchestrator/` with 7 modules), a sub-README may help navigation.

Create at least:
- `src/pi/obd/README.md` — listing the subpackages and what they do
- `src/pi/obd/orchestrator/README.md` — listing the 7 modules from the TD-003 split with a one-liner each

For simpler directories (e.g., `src/pi/hardware/` with 4 files), a README is optional — skip unless it adds value.

- [ ] **Step 6: Commit README updates**

```bash
cd Z:/o/OBD2v2
git add src/README.md src/common/README.md src/pi/README.md src/server/README.md src/pi/obd/README.md src/pi/obd/orchestrator/README.md 2>/dev/null
git commit -m "docs: finalize README files to match post-reorg structure (sweep 6, task 4)"
```

---

## Task 5: Update `CLAUDE.md` path references

**Goal:** Paths referenced in `CLAUDE.md` (the project-level one at repo root) have all changed during the reorg. Update them.

**Files:**
- Modify: `CLAUDE.md` (at repo root)
- Modify: `offices/ralph/CLAUDE.md` if it references specific src paths

- [ ] **Step 1: Read repo-root CLAUDE.md**

Read: `CLAUDE.md` at repo root.

Find references to:
- `src/common/secrets_loader.py` → now `src/common/config/secrets_loader.py`
- `src/common/config_validator.py` → now `src/common/config/validator.py`
- `src/common/error_handler.py` → now `src/common/errors/handler.py`
- `src/obd_config.json` → now `config.json` (repo root)
- `src/main.py` → now `src/pi/main.py`
- `src/obd/orchestrator.py` → now `src/pi/obd/orchestrator/` (package)
- Any `src/<dir>/` reference where `<dir>` is hardware/display/power/alert/profile/calibration/backup/analysis/ai/obd — all need to be prefixed with `src/pi/` or `src/server/` or `src/common/` as appropriate

Apply updates.

- [ ] **Step 2: Update `python src/main.py` command examples**

Find any shell example showing:
```bash
python src/main.py
```
or
```bash
python src/main.py --dry-run
```

Update to:
```bash
python src/pi/main.py
```
or
```bash
python src/pi/main.py --dry-run
```

- [ ] **Step 3: Update `offices/ralph/CLAUDE.md` if needed**

Read: `offices/ralph/CLAUDE.md`

This file was created in the current session and has tier-aware architecture notes. It may reference paths correctly already. Check for any stale references.

- [ ] **Step 4: Commit CLAUDE.md updates**

```bash
cd Z:/o/OBD2v2
git add CLAUDE.md offices/ralph/CLAUDE.md
git commit -m "docs: update CLAUDE.md path references for post-reorg layout (sweep 6, task 5)"
```

---

## Task 6: Update `specs/standards.md` with clarifications

**Goal:** If the sweep discovered edge cases where camelCase rule needed clarification (e.g., "what about test functions?", "what about external API fields?"), capture those in `specs/standards.md`.

**Files:**
- Modify: `specs/standards.md`

- [ ] **Step 1: Read specs/standards.md**

Read: `specs/standards.md`, specifically the naming conventions section.

- [ ] **Step 2: Add clarifications as needed**

Common clarifications to add:
- Test functions: `test_*` is REQUIRED by pytest and exempt from camelCase
- External API field names: left as-is when consuming external JSON (NHTSA, Ollama) — document that this is a pragmatic choice, not a style preference
- Short loop variables (`i`, `j`, `k`): allowed
- Private dunder methods (`__init__`, `__str__`): not renamed, follow Python standard

Add these to the naming section of the standards file. Use the existing writing style.

- [ ] **Step 3: Commit**

```bash
cd Z:/o/OBD2v2
git add specs/standards.md
git commit -m "docs: clarify camelCase naming rules in specs/standards.md (sweep 6, task 6)"
```

---

## Task 7: Full verification

- [ ] **Step 1: Full test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -15
```
Expected: all pass, same baseline.

- [ ] **Step 2: Ruff**

```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -15
```
Expected: clean.

- [ ] **Step 3: Mypy**

```bash
cd Z:/o/OBD2v2
mypy src/ 2>&1 | tail -15
```
Expected: no new errors.

- [ ] **Step 4: Simulator smoke test**

```bash
cd Z:/o/OBD2v2
timeout 30 python src/pi/main.py --simulate --dry-run 2>&1 | tail -30
```
Expected: clean.

- [ ] **Step 5: validate_config.py**

```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -10
```
Expected: passes.

- [ ] **Step 6: File size final audit**

```bash
cd Z:/o/OBD2v2
find src -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | awk '$1 > 300 && $1 != "total"'
find tests -name "*.py" -not -path "*/__pycache__/*" -exec wc -l {} + 2>/dev/null | awk '$1 > 500 && $1 != "total"'
```
Expected: zero or documented exemptions.

- [ ] **Step 7: Tier boundary audit**

```bash
cd Z:/o/OBD2v2
echo "=== Pi → Server violations ==="
grep -rn "from src\.server\|import src\.server" src/pi/ 2>/dev/null
echo "=== Server → Pi violations ==="
grep -rn "from src\.pi\|import src\.pi" src/server/ 2>/dev/null
echo "=== Common → tier violations ==="
grep -rn "from src\.pi\|from src\.server" src/common/ 2>/dev/null
```
Expected: only the documented ollama_manager exception, or zero output.

- [ ] **Step 8: Spool value final check**

```bash
cd Z:/o/OBD2v2
python -c "import json; c=json.load(open('config.json')); print(json.dumps(c['pi']['tieredThresholds'], indent=2, sort_keys=True))" > /tmp/sweep6-tiered-final.json
diff /tmp/sweep4-tiered-before.json /tmp/sweep6-tiered-final.json && echo "TIERED VALUES UNCHANGED THROUGHOUT ENTIRE REORG"
```

Expected: no diff. **This is the final preservation check — every Spool-authoritative value must be unchanged from sweep 4 start (== sweep 3 end == sweep 2 end == reorg baseline).**

---

## Task 8: Reorg completion gate — cleanup, update backlog, merge

- [ ] **Step 1: Delete sweep 6 rename list scratch file**

```bash
cd Z:/o/OBD2v2
git rm docs/superpowers/plans/sweep6-rename-list.md
git commit -m "chore: remove sweep 6 rename list scratch file"
```

- [ ] **Step 2: Append sweep 6 status to design doc section 12**

```markdown
| YYYY-MM-DD | 6 | Sweep 6 complete. camelCase enforced across src/ and tests/. README files finalized at src/, src/common/, src/pi/, src/server/, src/pi/obd/, src/pi/obd/orchestrator/. CLAUDE.md and specs/standards.md updated. All sweep exit criteria met. **Reorg complete — all 6 sweeps landed.** |
```

- [ ] **Step 3: Archive the design doc and plans**

Per the design doc section 8.5, after sweep 6 merges, the spec and plans move to an archive directory.

```bash
cd Z:/o/OBD2v2
mkdir -p docs/superpowers/archive
git mv docs/superpowers/specs/2026-04-12-reorg-design.md docs/superpowers/archive/2026-04-12-reorg-design.md
git mv docs/superpowers/plans/2026-04-12-reorg-sweep1-facades.md docs/superpowers/archive/
git mv docs/superpowers/plans/2026-04-12-reorg-sweep2-thresholds.md docs/superpowers/archive/
git mv docs/superpowers/plans/2026-04-12-reorg-sweep3-tier-split.md docs/superpowers/archive/
git mv docs/superpowers/plans/2026-04-12-reorg-sweep4-config.md docs/superpowers/archive/
git mv docs/superpowers/plans/2026-04-12-reorg-sweep5-file-sizes.md docs/superpowers/archive/
git mv docs/superpowers/plans/2026-04-12-reorg-sweep6-casing.md docs/superpowers/archive/
git commit -m "chore: archive reorg spec and plans after completion (sweep 6, task 8)"
```

- [ ] **Step 4: Write completion notification to Marcus**

Create `offices/pm/inbox/YYYY-MM-DD-from-ralph-reorg-complete.md`:
```markdown
# Ralph → Marcus — Structural Reorganization Complete

**Date**: YYYY-MM-DD
**From**: Ralph
**To**: Marcus
**Subject**: Reorg complete — close backlog items

All 6 sweeps of the structural reorganization are merged to main. The tree
is now tier-aware (src/common/, src/pi/, src/server/), all files are within
size guidelines, all facade duplication is gone, the legacy threshold
system is merged into tiered, config is restructured, and camelCase is
enforced throughout.

**Please close these backlog items as RESOLVED:**
- TD-002 — Re-export facade modules (sweep 1)
- TD-003 — Orchestrator refactoring plan (sweep 5)
- B-019 — Split oversized files (sweep 5)
- B-040 — Structural Reorganization (all 6 sweeps)

**Please close this as DECLINED:**
- B-006 — snake_case migration (explicitly decided to keep camelCase)

**Archive location**: `docs/superpowers/archive/2026-04-12-reorg-design.md`

No tuning values changed. All Spool-authoritative values verified
byte-for-byte unchanged.

The next big priority (per CIO direction) is connecting the Pi to the
OBD-II Bluetooth dongle and getting real data flowing. Once data flows,
the empty contracts skeleton in `src/common/contracts/` can be populated
with real type definitions against actual data shapes.

— Ralph
```

Commit:
```bash
cd Z:/o/OBD2v2
git add offices/pm/inbox/YYYY-MM-DD-from-ralph-reorg-complete.md
git commit -m "docs: notify Marcus of reorg completion (sweep 6, task 8)"
```

Replace `YYYY-MM-DD` with actual date.

- [ ] **Step 5: Surface to CIO for final merge approval**

Tell the CIO:
> "Sweep 6 complete. The reorg is done. All 6 sweeps passed. All exit criteria met, all Spool values unchanged. Design doc and plans archived. Marcus notified. Ready for final merge to main?"

Wait for approval.

- [ ] **Step 6: Merge to main**

```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep6-casing -m "Merge sprint/reorg-sweep6-casing: Sweep 6 complete — REORG COMPLETE

Sweep 6 of 6 — the structural reorganization (B-040) is now complete.

This sweep:
- Enforced camelCase across src/ and tests/
- Finalized README files at src/, src/common/, src/pi/, src/server/
- Updated CLAUDE.md and specs/standards.md for post-reorg state
- Archived the reorg spec and plans to docs/superpowers/archive/
- Notified Marcus via PM inbox

**Reorg summary (all 6 sweeps):**
- Sweep 1: Deleted 18 facade files, consolidated shutdown trio into subpackage
- Sweep 2: Merged legacy threshold system into tiered system
- Sweep 3: Split src/ into common/, pi/, server/ tiers
- Sweep 4: Restructured config.json into tier-aware shape at repo root
- Sweep 5: Split orchestrator (TD-003) and 10+ other oversized files
- Sweep 6: camelCase enforcement + README finalization

**Resolves**: TD-002, TD-003, B-019, B-040 (all marked in Marcus inbox)
**Declines**: B-006 (camelCase confirmed as the standard)

**Preserves**: every Spool-authoritative value in tieredThresholds,
byte-for-byte verified via diff across all 6 sweeps.

Next priority per CIO direction: Pi connection to OBD-II dongle and
real data flow. Contracts skeleton in src/common/contracts/ populates
then.

Design doc archive: docs/superpowers/archive/2026-04-12-reorg-design.md"
git log --oneline -10
```

- [ ] **Step 7: Confirm main is green**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

- [ ] **Step 8: Delete sweep branches (optional cleanup)**

After a reasonable period (e.g., a week), sweep branches can be deleted since they're merged and archived via the merge commits:
```bash
cd Z:/o/OBD2v2
git branch -d sprint/reorg-sweep1-facades sprint/reorg-sweep2-thresholds sprint/reorg-sweep3-tier-split sprint/reorg-sweep4-config sprint/reorg-sweep5-file-sizes sprint/reorg-sweep6-casing
```

**Do not rush this**. Keep them for at least 7 days in case a post-reorg issue surfaces that requires diagnostic access to the pre-merge state of a specific sweep.

- [ ] **Step 9: Announce reorg complete**

Tell the CIO:
> "Reorg is done. All 6 sweeps merged, main is green, archive created, Marcus notified. The next big priority is connecting the Pi to the OBD-II Bluetooth dongle. When real data starts flowing, we populate the contracts skeleton in src/common/contracts/ with real types."

---

## End of Sweep 6 Plan — End of Reorg

**Success criteria:**
- ✅ camelCase enforced
- ✅ READMEs finalized
- ✅ CLAUDE.md and standards.md updated
- ✅ All file sizes within guidelines
- ✅ No tier boundary violations (except documented ollama exception)
- ✅ Spool values unchanged across all 6 sweeps
- ✅ All tests green, simulator green
- ✅ Design doc and plans archived
- ✅ Marcus notified for backlog closure
- ✅ Reorg complete

**Final state of the codebase**: tier-aware, clean, within size guidelines, camelCase throughout, READMEs current, architectural decisions honored. Ready for the next phase of real work.

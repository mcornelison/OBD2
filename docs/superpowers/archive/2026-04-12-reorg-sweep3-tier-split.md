# Sweep 3 — Tier Split and Shared Contracts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the physical tier split in `src/` (`src/common/`, `src/pi/`, `src/server/`). Move every existing module into its correct tier. Restructure `src/common/` into proper subpackages. Create empty skeleton files for `src/common/contracts/`, `src/pi/clients/`, `src/pi/inbox/`, and all `src/server/` placeholder packages. Update every import statement. Create READMEs. Zero behavior change.

**Architecture:** Today, everything is under `src/` at the top level. After this sweep, `src/common/` contains tier-agnostic code (deployed to both Pi and server), `src/pi/` contains Pi-only code (hardware, display, data collection, orchestrator), and `src/server/` contains server-only code (AI, future FastAPI, future analysis pipeline). The physical layout enforces deployment boundaries structurally.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy, git on Windows. Heavy use of `git mv` to preserve rename history. Regex-based import rewriting.

**Design doc**: `docs/superpowers/specs/2026-04-12-reorg-design.md` — **you must read sections 5 and 7 (sweep 3) before starting this sweep.** Section 5 has the complete target layout.

**Estimated effort:** 3–5 days. This is the highest-risk sweep.

**Prerequisites:**
- Sweeps 1 and 2 merged to `main`
- Clean checkout of `main`
- Test suite green on `main`

**Exit criteria:**
1. `src/common/`, `src/pi/`, `src/server/` all exist and match the target layout in design doc section 5
2. Every Python file lives at the correct tier path
3. Every import statement uses the new tier-aware path
4. Skeleton files exist at all placeholder locations with one-line "filled in by story X" comments
5. `src/README.md`, `src/common/README.md`, `src/pi/README.md`, `src/server/README.md` exist and describe their directory contents
6. All tests green
7. Simulator smoke test passes
8. PR merged to `main`
9. 24-hour cooling period before sweep 4 starts (per design doc section 8.5)

**Risk**: **High**. This is the largest and most mechanical sweep. Principal failure mode: a missed import rewrite causes a cascade of `ModuleNotFoundError` at runtime. Mitigation: commit after every directory move, run the fast suite after every commit, never batch multiple moves into one commit.

**Import rewriting convention:** Prefer absolute imports (`from src.pi.obd.foo import Bar`) over relative imports (`from ..obd.foo import Bar`) in moved files. Relative imports are fragile across directory boundaries and this sweep crosses many boundaries. When a file is moved, rewrite its relative imports to absolute imports as part of the move.

---

## Task 1: Setup

**Files:**
- No file changes

- [ ] **Step 1: Start from clean main**

Run:
```bash
cd Z:/o/OBD2v2
git checkout main
git status
git log --oneline -3
```
Expected: on main, last commit is the sweep 2 merge, working tree clean.

- [ ] **Step 2: Create sweep 3 branch**

Run:
```bash
cd Z:/o/OBD2v2
git checkout -b sprint/reorg-sweep3-tier-split main
git branch --show-current
```
Expected: `sprint/reorg-sweep3-tier-split`.

- [ ] **Step 3: Verify baseline green**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```
Expected: same baseline count as end of sweep 2. Record the number.

- [ ] **Step 4: Create a working notes file for this sweep**

Create `docs/superpowers/plans/sweep3-notes.md`:
```markdown
# Sweep 3 Working Notes (scratch — deleted before merge)

## Baseline
- main HEAD: <git rev-parse --short HEAD>
- Tests passing: NNN

## Commit log for this sweep
(Each task logs its commits here for easy reference)
```

Fill in the baseline fields. Commit:
```bash
cd Z:/o/OBD2v2
git add docs/superpowers/plans/sweep3-notes.md
git commit -m "chore: sweep 3 working notes"
```

---

## Task 2: Create the tier directory scaffolding

**Goal:** Create the empty `src/pi/` and `src/server/` directories with `__init__.py` and placeholder README. Do not move any files yet.

**Files:**
- Create: `src/pi/__init__.py`
- Create: `src/pi/README.md`
- Create: `src/server/__init__.py`
- Create: `src/server/README.md`

- [ ] **Step 1: Create `src/pi/__init__.py`**

Create file `src/pi/__init__.py` with content:
```python
"""
Raspberry Pi tier package.

Contains modules deployed to the in-car Raspberry Pi only:
- Hardware interfaces (GPIO, I2C, Bluetooth)
- Display drivers
- OBD-II data collection
- Real-time alerting
- Local analysis for display
- Drive detection and profile management

Not deployed to the server (Chi-Srv-01). Imports from `src.common` are allowed;
imports from `src.server` are forbidden (enforced structurally — `src.server`
won't exist on the deployed Pi).
"""
```

- [ ] **Step 2: Create `src/pi/README.md`**

Create file `src/pi/README.md`:
```markdown
# src/pi/

Raspberry Pi tier. Deployed to `chi-eclipse-tuner` only.

Contents are populated during sweep 3 of the 2026-04-12 reorganization.
See `docs/superpowers/specs/2026-04-12-reorg-design.md` for the full layout.

## Structure

_Updated at the end of sweep 3 with the final directory tree._
```

- [ ] **Step 3: Create `src/server/__init__.py`**

Create file `src/server/__init__.py`:
```python
"""
Companion service tier package (Chi-Srv-01).

Contains modules deployed to the home analysis server only:
- FastAPI web app (api/)
- Upload ingestion and delta sync (ingest/)
- AI analysis (ai/)
- Post-drive deep analysis (analysis/)
- Recommendation staging (recommendations/)
- MariaDB models and schema (db/)

Not deployed to the Raspberry Pi. Imports from `src.common` are allowed;
imports from `src.pi` are forbidden (enforced structurally — `src.pi`
won't exist on the deployed server).
"""
```

- [ ] **Step 4: Create `src/server/README.md`**

Create file `src/server/README.md`:
```markdown
# src/server/

Companion service tier. Deployed to `chi-srv-01` only.

Most contents are placeholder skeletons, populated by later sprints (B-022,
B-031). AI analysis logic (`ai/`) is real code migrated from `src/ai/` during
sweep 3.

See `docs/superpowers/specs/2026-04-12-reorg-design.md` for the full layout.

## Structure

_Updated at the end of sweep 3 with the final directory tree._
```

- [ ] **Step 5: Commit the scaffolding**

Run:
```bash
cd Z:/o/OBD2v2
git add src/pi/__init__.py src/pi/README.md src/server/__init__.py src/server/README.md
git status
git commit -m "feat: create src/pi/ and src/server/ tier directories (sweep 3, task 2)"
```

- [ ] **Step 6: Verify tests still pass**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -5
```
Expected: no change (empty directories have no effect).

---

## Task 3: Restructure `src/common/` into subpackages

**Goal:** Expand `src/common/` from 4 flat files into proper subpackages: `config/`, `errors/`, `logging/`, `analysis/`.

**Files:**
- Create: `src/common/config/__init__.py`
- Create: `src/common/errors/__init__.py`
- Create: `src/common/logging/__init__.py`
- Create: `src/common/analysis/__init__.py`
- Move: `src/common/config_validator.py` → `src/common/config/validator.py`
- Move: `src/common/secrets_loader.py` → `src/common/config/secrets_loader.py`
- Move: `src/common/error_handler.py` → `src/common/errors/handler.py`
- Move: `src/common/logging_config.py` → `src/common/logging/setup.py`

- [ ] **Step 1: Create subpackage `__init__.py` files**

Create each of these with the given content:

File: `src/common/config/__init__.py`
```python
"""Config validation, secrets loading, and schema types. Shared across tiers."""

from .secrets_loader import *  # noqa: F401,F403
from .validator import *  # noqa: F401,F403
```

File: `src/common/errors/__init__.py`
```python
"""Error classification, retry policy, and handlers. Shared across tiers."""

from .handler import *  # noqa: F401,F403
```

File: `src/common/logging/__init__.py`
```python
"""Logging configuration helpers. Shared across tiers."""

from .setup import *  # noqa: F401,F403
```

File: `src/common/analysis/__init__.py`
```python
"""Pure statistical/analytical calculations. Shared across tiers (no state)."""
```

- [ ] **Step 2: Move `config_validator.py` → `config/validator.py`**

Run:
```bash
cd Z:/o/OBD2v2
git mv src/common/config_validator.py src/common/config/validator.py
git status
```
Expected: git shows rename.

- [ ] **Step 3: Update the file header in validator.py**

Read: `src/common/config/validator.py`

Find:
```python
# File Name: config_validator.py
```
Replace with:
```python
# File Name: validator.py
```

- [ ] **Step 4: Update relative imports inside validator.py**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "^from \.\|^from src\.common" src/common/config/validator.py
```

For each relative import that crosses the new directory boundary:
- `from .secrets_loader import X` → `from .secrets_loader import X` (still works — same package after task 5 moves secrets_loader into config/)
- `from .error_handler import X` → `from src.common.errors.handler import X`
- `from .logging_config import X` → `from src.common.logging.setup import X`

Use absolute imports to avoid relative-import fragility.

- [ ] **Step 5: Move `secrets_loader.py` → `config/secrets_loader.py`**

Run:
```bash
cd Z:/o/OBD2v2
git mv src/common/secrets_loader.py src/common/config/secrets_loader.py
```

- [ ] **Step 6: Fix relative imports in `config/secrets_loader.py`**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "^from \." src/common/config/secrets_loader.py
```

Apply the same rewriting rules as step 4.

- [ ] **Step 7: Move `error_handler.py` → `errors/handler.py`**

Run:
```bash
cd Z:/o/OBD2v2
git mv src/common/error_handler.py src/common/errors/handler.py
```

- [ ] **Step 8: Fix file header and imports in `errors/handler.py`**

Update file header:
```python
# File Name: handler.py
```

Run:
```bash
cd Z:/o/OBD2v2
grep -n "^from \." src/common/errors/handler.py
```
Apply rewriting rules.

- [ ] **Step 9: Move `logging_config.py` → `logging/setup.py`**

Run:
```bash
cd Z:/o/OBD2v2
git mv src/common/logging_config.py src/common/logging/setup.py
```

- [ ] **Step 10: Fix file header and imports in `logging/setup.py`**

Update file header:
```python
# File Name: setup.py
```

Run:
```bash
cd Z:/o/OBD2v2
grep -n "^from \." src/common/logging/setup.py
```
Apply rewriting rules.

- [ ] **Step 11: Update `src/common/__init__.py` to import from new locations**

Read: `src/common/__init__.py`

Update any `from .config_validator import X` to `from .config.validator import X`.
Update any `from .error_handler import X` to `from .errors.handler import X`.
Update any `from .logging_config import X` to `from .logging.setup import X`.
Update any `from .secrets_loader import X` to `from .config.secrets_loader import X`.

- [ ] **Step 12: Find and fix all external callers of the old paths**

Run:
```bash
cd Z:/o/OBD2v2
grep -rln "from src\.common\.config_validator\|from src\.common\.error_handler\|from src\.common\.logging_config\|from src\.common\.secrets_loader\|from common\.config_validator\|from common\.error_handler\|from common\.logging_config\|from common\.secrets_loader" src tests 2>/dev/null
```

For each file returned, update the imports:
- `from src.common.config_validator import X` → `from src.common.config.validator import X`
- `from src.common.error_handler import X` → `from src.common.errors.handler import X`
- `from src.common.logging_config import X` → `from src.common.logging.setup import X`
- `from src.common.secrets_loader import X` → `from src.common.config.secrets_loader import X`

Repeat the grep until it returns no matches.

- [ ] **Step 13: Run fast test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -15
```

Expected: same baseline count. If red, check for missed imports.

- [ ] **Step 14: Commit the common restructure**

Run:
```bash
cd Z:/o/OBD2v2
git add -A
git status
git commit -m "refactor: restructure src/common/ into config/, errors/, logging/, analysis/ subpackages (sweep 3, task 3)

- Move config_validator.py → config/validator.py
- Move secrets_loader.py → config/secrets_loader.py
- Move error_handler.py → errors/handler.py
- Move logging_config.py → logging/setup.py
- Create empty analysis/ subpackage (calculations.py migrates in task 5)
- Update src/common/__init__.py and all external callers"
```

---

## Task 4: Move simple Pi-only directories

**Goal:** Use `git mv` to relocate `src/hardware/`, `src/display/`, `src/power/`, `src/alert/`, `src/profile/`, `src/calibration/`, `src/backup/` under `src/pi/`. After each move, rewrite affected imports.

**Files (per directory):**
- Move entire directory: `src/<name>/` → `src/pi/<name>/`
- Update: every caller importing `src.<name>`

**Pattern for each directory:** (1) git mv, (2) fix relative imports inside the moved directory, (3) fix callers, (4) run fast test suite, (5) commit.

- [ ] **Step 1: Move `src/hardware/` → `src/pi/hardware/`**

```bash
cd Z:/o/OBD2v2
git mv src/hardware src/pi/hardware
git status
```
Expected: rename detected.

- [ ] **Step 2: Fix relative imports inside src/pi/hardware/**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "^from \.\.\|^from src\.common\|^from src\.obd" src/pi/hardware/ 2>/dev/null
```

For each `from ..X` that referenced a sibling at `src/X`, rewrite as `from src.X` (absolute). Reason: after the move, `..` no longer points where it used to.

Also rewrite any `from src.hardware.Y` (self-references) to `from src.pi.hardware.Y`.

- [ ] **Step 3: Update all callers of `src.hardware`**

Run:
```bash
cd Z:/o/OBD2v2
grep -rln "from src\.hardware\|from hardware\|import src\.hardware\|import hardware\." src tests 2>/dev/null
```

For each file returned:
- `from src.hardware.X import Y` → `from src.pi.hardware.X import Y`
- `from hardware.X import Y` → `from pi.hardware.X import Y`
- `import src.hardware.X` → `import src.pi.hardware.X`

Repeat grep until empty.

- [ ] **Step 4: Run fast test suite**

Run:
```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
```
Expected: same baseline count.

- [ ] **Step 5: Commit hardware move**

Run:
```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: move src/hardware/ → src/pi/hardware/ (sweep 3, task 4)"
```

- [ ] **Step 6: Move `src/display/` → `src/pi/display/`**

```bash
cd Z:/o/OBD2v2
git mv src/display src/pi/display
```

- [ ] **Step 7: Fix relative imports inside src/pi/display/**

```bash
cd Z:/o/OBD2v2
grep -rn "^from \.\.\|^from src\.common\|^from src\.obd" src/pi/display/ 2>/dev/null
```
Apply the same rewriting rules as step 2.

- [ ] **Step 8: Update all callers of `src.display`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.display\|from display\|import src\.display\|import display\." src tests 2>/dev/null
```

Rewrite each `src.display` → `src.pi.display` and `display` → `pi.display`.

**Important**: `src/obd/__init__.py` references `src.display.manager` after sweep 1 — update that to `src.pi.display.manager`.

Repeat until empty.

- [ ] **Step 9: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
```

- [ ] **Step 10: Commit display move**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: move src/display/ → src/pi/display/ (sweep 3, task 4)"
```

- [ ] **Step 11: Move `src/power/` → `src/pi/power/`**

```bash
cd Z:/o/OBD2v2
git mv src/power src/pi/power
```

- [ ] **Step 12: Fix relative imports inside src/pi/power/**

```bash
cd Z:/o/OBD2v2
grep -rn "^from \.\.\|^from src\.common\|^from src\.obd" src/pi/power/ 2>/dev/null
```
Apply rewriting rules.

- [ ] **Step 13: Update all callers of `src.power`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.power\|from power\|import src\.power\|import power\." src tests 2>/dev/null
```
Rewrite.

- [ ] **Step 14: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
```

- [ ] **Step 15: Commit power move**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: move src/power/ → src/pi/power/ (sweep 3, task 4)"
```

- [ ] **Step 16: Move `src/alert/` → `src/pi/alert/`**

```bash
cd Z:/o/OBD2v2
git mv src/alert src/pi/alert
```

- [ ] **Step 17: Fix relative imports inside src/pi/alert/**

```bash
cd Z:/o/OBD2v2
grep -rn "^from \.\.\|^from src\.common\|^from src\.obd" src/pi/alert/ 2>/dev/null
```
Apply rewriting rules.

- [ ] **Step 18: Update all callers of `src.alert`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.alert\|from alert\|import src\.alert\|import alert\." src tests 2>/dev/null
```
Rewrite.

**Important**: `src/obd/__init__.py` references `src.alert.manager` — update to `src.pi.alert.manager`.

- [ ] **Step 19: Run fast test suite and commit**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
git add -A
git commit -m "refactor: move src/alert/ → src/pi/alert/ (sweep 3, task 4)"
```

- [ ] **Step 20: Move `src/profile/` → `src/pi/profile/`**

```bash
cd Z:/o/OBD2v2
git mv src/profile src/pi/profile
grep -rn "^from \.\.\|^from src\." src/pi/profile/ 2>/dev/null
```
Fix imports inside the moved directory.

- [ ] **Step 21: Update all callers of `src.profile`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.profile\|from profile\|import src\.profile" src tests 2>/dev/null
```
Rewrite each.

- [ ] **Step 22: Run fast test suite and commit**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
git add -A
git commit -m "refactor: move src/profile/ → src/pi/profile/ (sweep 3, task 4)"
```

- [ ] **Step 23: Move `src/calibration/` → `src/pi/calibration/`**

```bash
cd Z:/o/OBD2v2
git mv src/calibration src/pi/calibration
grep -rn "^from \.\.\|^from src\." src/pi/calibration/ 2>/dev/null
```
Fix imports.

- [ ] **Step 24: Update callers**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.calibration\|from calibration\|import src\.calibration" src tests 2>/dev/null
```
Rewrite.

- [ ] **Step 25: Run fast test suite and commit**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
git add -A
git commit -m "refactor: move src/calibration/ → src/pi/calibration/ (sweep 3, task 4)"
```

- [ ] **Step 26: Move `src/backup/` → `src/pi/backup/`**

```bash
cd Z:/o/OBD2v2
git mv src/backup src/pi/backup
grep -rn "^from \.\.\|^from src\." src/pi/backup/ 2>/dev/null
```
Fix imports.

- [ ] **Step 27: Update callers**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.backup\|from backup\|import src\.backup" src tests 2>/dev/null
```
Rewrite.

- [ ] **Step 28: Run fast test suite and commit**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -10
git add -A
git commit -m "refactor: move src/backup/ → src/pi/backup/ (sweep 3, task 4)"
```

---

## Task 5: Split `src/analysis/` — calculations.py → common, rest → pi

**Goal:** `src/analysis/calculations.py` is pure stateless math that both tiers will need. It moves to `src/common/analysis/calculations.py`. Everything else in `src/analysis/` is Pi-only and moves to `src/pi/analysis/`.

**Files:**
- Move: `src/analysis/calculations.py` → `src/common/analysis/calculations.py`
- Move: rest of `src/analysis/*` → `src/pi/analysis/*`
- Remove: empty `src/analysis/` directory

- [ ] **Step 1: Confirm `calculations.py` is pure math**

Run:
```bash
cd Z:/o/OBD2v2
grep -E "^import |^from " src/analysis/calculations.py
```

Expected: imports only stdlib (`math`, `statistics`, `typing`, etc.) — no project-specific imports. If it imports from `src.obd` or similar, it is NOT pure and must stay with the Pi side. Reclassify and note in `sweep3-notes.md`.

- [ ] **Step 2: Move calculations.py to common**

```bash
cd Z:/o/OBD2v2
git mv src/analysis/calculations.py src/common/analysis/calculations.py
```

- [ ] **Step 3: Update file header in calculations.py**

The header's filename is already `calculations.py` — no change.

Update the docstring if it mentions `src.analysis` as its location.

- [ ] **Step 4: Update callers of `src.analysis.calculations`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.analysis\.calculations\|from analysis\.calculations" src tests 2>/dev/null
```

For each file:
- `from src.analysis.calculations import X` → `from src.common.analysis.calculations import X`
- `from analysis.calculations import X` → `from common.analysis.calculations import X`

- [ ] **Step 5: Move the rest of src/analysis/ to src/pi/analysis/**

```bash
cd Z:/o/OBD2v2
git mv src/analysis src/pi/analysis
# Note: calculations.py is already gone, so git mv moves the remaining files
ls src/pi/analysis/
```
Expected: engine.py, profile_statistics.py, helpers.py, types.py, exceptions.py, __init__.py (no calculations.py — it's in common now).

- [ ] **Step 6: Fix relative imports inside src/pi/analysis/**

```bash
cd Z:/o/OBD2v2
grep -rn "^from \.\.\|^from src\." src/pi/analysis/ 2>/dev/null
```

Any `from .calculations import X` must become `from src.common.analysis.calculations import X` since calculations.py is no longer a sibling.

- [ ] **Step 7: Update `src/pi/analysis/__init__.py`**

Read: `src/pi/analysis/__init__.py`

If it has `from .calculations import ...`, replace with `from src.common.analysis.calculations import ...`.

- [ ] **Step 8: Update callers of `src.analysis` (non-calculations)**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.analysis\.\|from analysis\." src tests 2>/dev/null
```

For each file, distinguish:
- `from src.analysis.calculations import X` → already handled in step 4, should not appear anymore
- `from src.analysis.engine import X` → `from src.pi.analysis.engine import X`
- `from src.analysis.profile_statistics import X` → `from src.pi.analysis.profile_statistics import X`
- etc.

**Special case**: `src/obd/__init__.py` has `from src.analysis.profile_statistics import ...` (added in sweep 1). Update it to `from src.pi.analysis.profile_statistics import ...`.

- [ ] **Step 9: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -15
```
Expected: same baseline count.

- [ ] **Step 10: Commit the analysis split**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: split src/analysis/ — calculations.py → common, rest → pi (sweep 3, task 5)"
```

---

## Task 6: Move `src/ai/` → `src/server/ai/`

**Goal:** All AI logic moves to the server tier.

**Files:**
- Move: `src/ai/*` → `src/server/ai/*`

- [ ] **Step 1: Move the directory**

```bash
cd Z:/o/OBD2v2
git mv src/ai src/server/ai
ls src/server/ai/
```
Expected: analyzer.py, data_preparation.py, helpers.py, prompt_template.py, ranker.py, types.py, __init__.py (no ollama_manager.py yet — that's in src/obd/, moved in task 8).

- [ ] **Step 2: Fix relative imports inside src/server/ai/**

```bash
cd Z:/o/OBD2v2
grep -rn "^from \.\.\|^from src\." src/server/ai/ 2>/dev/null
```

Rewrite each `from ..X` or `from src.X` where X used to be a sibling at `src/X`. For example:
- `from ..common.config_validator import X` → `from src.common.config.validator import X`
- `from src.obd.database import X` → **WARNING**: this would be a Pi→Server import direction violation. Surface to CIO and decide whether AI actually needs DB access (if yes, the DB layer needs to move to common or have a server-specific wrapper).

Cross-tier imports in either direction (Pi→Server or Server→Pi) are FORBIDDEN structurally. Only `common → *` and `* → common` are allowed.

- [ ] **Step 3: Update callers of `src.ai`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.ai\|from ai\.\|import src\.ai" src tests 2>/dev/null
```

For each file:
- `from src.ai.X import Y` → `from src.server.ai.X import Y`
- `from ai.X import Y` → `from server.ai.X import Y`

**Special case**: `src/obd/__init__.py` does NOT currently import from `src.ai.*` (verify via grep). The `src/obd/ai_analyzer.py` facade was deleted in sweep 1, and `__init__.py` was rewritten to not re-export AI symbols. So this step should have minimal effect outside `tests/`.

- [ ] **Step 4: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -15
```

If any test fails because it imports AI-related symbols from `src.obd`, the issue is that `src/obd/__init__.py` used to re-export them. Sweep 1 should have removed those — but if the tests still reference `src.obd.AiAnalyzer`, either update the test to `from src.server.ai.analyzer import AiAnalyzer`, or confirm the test is still valid (it may be testing a Pi-side concern via a different module).

- [ ] **Step 5: Commit the AI move**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: move src/ai/ → src/server/ai/ (sweep 3, task 6)"
```

---

## Task 7: Move `src/obd/` → `src/pi/obd/`

**Goal:** The largest single move in this sweep. `src/obd/` contains ~25 files and subpackages. All of it is Pi-side.

**Files:**
- Move: entire `src/obd/` directory → `src/pi/obd/`

- [ ] **Step 1: Move the whole directory**

```bash
cd Z:/o/OBD2v2
git mv src/obd src/pi/obd
git status | head -20
```
Expected: many renames shown.

- [ ] **Step 2: Fix imports in `src/pi/obd/__init__.py`**

Read: `src/pi/obd/__init__.py`

After sweep 1, this file imports from canonical subpackage locations. Those imports include references to top-level packages that moved in tasks 4-6:

Find and rewrite each:
- `from src.display.manager import ...` → `from src.pi.display.manager import ...`
- `from src.display.adapters.adafruit import ...` → `from src.pi.display.adapters.adafruit import ...`
- `from src.alert.manager import ...` → `from src.pi.alert.manager import ...`
- `from src.analysis.profile_statistics import ...` → `from src.pi.analysis.profile_statistics import ...`

The `from .data.logger`, `from .drive.detector`, `from .vehicle.vin_decoder`, etc. still work because they're internal to `src/pi/obd/`. Leave those as relative imports.

- [ ] **Step 3: Fix relative imports in subpackages that cross tiers**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "^from \.\." src/pi/obd/ 2>/dev/null
```

For each `from ..X` where X is something outside `src.pi.obd`:
- If X is in `src.common`: rewrite as `from src.common.X import Y`
- If X is in `src.pi` (e.g., hardware): rewrite as `from src.pi.X import Y`

- [ ] **Step 4: Fix absolute imports to other top-level packages that moved**

Run:
```bash
cd Z:/o/OBD2v2
grep -rn "^from src\.\(hardware\|display\|power\|alert\|profile\|calibration\|backup\|analysis\|ai\)" src/pi/obd/ 2>/dev/null
```

For each hit:
- `from src.hardware.X` → `from src.pi.hardware.X`
- `from src.display.X` → `from src.pi.display.X`
- `from src.power.X` → `from src.pi.power.X`
- `from src.alert.X` → `from src.pi.alert.X`
- `from src.profile.X` → `from src.pi.profile.X`
- `from src.calibration.X` → `from src.pi.calibration.X`
- `from src.backup.X` → `from src.pi.backup.X`
- `from src.analysis.calculations` → `from src.common.analysis.calculations`
- `from src.analysis.X` (non-calculations) → `from src.pi.analysis.X`
- `from src.ai.X` → **FORBIDDEN** (Pi→Server). If Pi code imports AI, it must go through a thin client in `src/pi/clients/` (created in task 12). Mark this as a blocker for the current task; surface to CIO.

- [ ] **Step 5: Update external callers of `src.obd`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.obd\|from obd\|import src\.obd" src tests 2>/dev/null | grep -v "src/pi/obd"
```

For each file outside `src/pi/obd/`:
- `from src.obd.X import Y` → `from src.pi.obd.X import Y`
- `from obd.X import Y` → `from pi.obd.X import Y`

This hits MANY test files. Expect 20-40 test files to need updating.

- [ ] **Step 6: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -30
```

Expected: same baseline count. Failures are likely missed import rewrites — trace them via `--tb=short` output.

- [ ] **Step 7: Commit the obd move**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: move src/obd/ → src/pi/obd/ (sweep 3, task 7)

Largest single move of sweep 3. Updates imports in:
- src/pi/obd/__init__.py (point at new sibling tier paths)
- All src/pi/obd/ subpackages (cross-tier references)
- All tests/ files that import from obd"
```

---

## Task 8: Extract `ollama_manager.py` from Pi to server

**Goal:** `src/pi/obd/ollama_manager.py` talks to Ollama. But Ollama runs on the server, and the server owns AI. This file belongs in `src/server/ai/ollama_manager.py`.

**Files:**
- Move: `src/pi/obd/ollama_manager.py` → `src/server/ai/ollama_manager.py`

- [ ] **Step 1: Check if the file still exists at the Pi location**

```bash
cd Z:/o/OBD2v2
ls src/pi/obd/ollama_manager.py
```

If yes, proceed. If no (because sweep 1 deleted it), skip to task 9.

- [ ] **Step 2: Move the file**

```bash
cd Z:/o/OBD2v2
git mv src/pi/obd/ollama_manager.py src/server/ai/ollama_manager.py
```

- [ ] **Step 3: Fix imports inside ollama_manager.py**

Run:
```bash
cd Z:/o/OBD2v2
grep -n "^from \." src/server/ai/ollama_manager.py
```

Most imports will be from `src.common` (for logging, errors) — those stay valid. Any `from ..X` (where X was a Pi sibling) needs careful review. If the file depends on Pi-specific modules, you cannot cleanly move it — stop and create a tech-debt note.

- [ ] **Step 4: Update `src/server/ai/__init__.py` to export from ollama_manager**

Read: `src/server/ai/__init__.py`

Add (if not already present):
```python
from .ollama_manager import *  # noqa: F401,F403
```

- [ ] **Step 5: Update callers of `src.pi.obd.ollama_manager`**

```bash
cd Z:/o/OBD2v2
grep -rln "from src\.pi\.obd\.ollama_manager\|from pi\.obd\.ollama_manager\|from src\.obd\.ollama_manager" src tests 2>/dev/null
```

For each file:
- `from src.pi.obd.ollama_manager import X` → `from src.server.ai.ollama_manager import X`

**But wait**: if Pi code imports `ollama_manager` to talk to Ollama, that's Pi→Server which is forbidden. The right fix is a thin client in `src/pi/clients/ollama_client.py` that the Pi uses. That's created in task 12.

For sweep 3, if Pi code imports `ollama_manager` directly:
- Option A: update the import to the new location `src.server.ai.ollama_manager` (preserves behavior, violates tier boundary temporarily)
- Option B: create a shim at `src/pi/clients/ollama_client.py` that imports from `src.server.ai.ollama_manager` and re-exports (still violates the boundary)
- Option C: duplicate the minimal Ollama HTTP-client logic into `src/pi/clients/ollama_client.py` and leave `src/server/ai/ollama_manager.py` as the server-side wrapper

**Decision**: Use option A for sweep 3 — import the old path from `src.server.ai.ollama_manager`. File a tech-debt note `TD-reorg-sweep3-ollama-boundary.md` saying "Pi currently imports from server tier; fix by implementing `src/pi/clients/ollama_client.py` as a thin HTTP wrapper in a future sprint." This defers the real fix to when we have actual data flowing.

- [ ] **Step 6: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -15
```

- [ ] **Step 7: Commit the ollama_manager move**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: move ollama_manager to src/server/ai/ (sweep 3, task 8)

Ollama runs on Chi-Srv-01 only; the manager belongs in the server tier.
Pi callers temporarily import from server tier — will be replaced by a
thin HTTP client in src/pi/clients/ollama_client.py in a future sprint
(see TD-reorg-sweep3-ollama-boundary.md)."
```

---

## Task 9: Move `src/main.py` and `src/obd_config.json`

**Goal:** Move the Pi entry point and the config file into the `pi/` tier.

**Files:**
- Move: `src/main.py` → `src/pi/main.py`
- Move: `src/obd_config.json` → `src/pi/obd_config.json`

- [ ] **Step 1: Move main.py**

```bash
cd Z:/o/OBD2v2
git mv src/main.py src/pi/main.py
```

- [ ] **Step 2: Fix imports in src/pi/main.py**

Read: `src/pi/main.py`

Any import like `from src.obd.orchestrator import X` → `from src.pi.obd.orchestrator import X`. Apply the same transformations for all other moved directories.

Config path reference: if `main.py` references `src/obd_config.json`, update to `src/pi/obd_config.json`.

- [ ] **Step 3: Move obd_config.json**

```bash
cd Z:/o/OBD2v2
git mv src/obd_config.json src/pi/obd_config.json
```

- [ ] **Step 4: Update all references to the config file path**

```bash
cd Z:/o/OBD2v2
grep -rln "src/obd_config\.json\|obd_config\.json" src tests validate_config.py 2>/dev/null
```

For each file:
- `'src/obd_config.json'` → `'src/pi/obd_config.json'`
- `"src/obd_config.json"` → `"src/pi/obd_config.json"`
- Relative references like `obd_config.json` (no directory) may still work if the CWD is right — but check them for safety.

**Note**: sweep 4 will promote this file to repo root and restructure its contents. For sweep 3, we just move it into the Pi tier.

- [ ] **Step 5: Update `validate_config.py`**

Read: `validate_config.py` (at repo root)

Update any path reference from `src/obd_config.json` to `src/pi/obd_config.json`.

- [ ] **Step 6: Run validate_config**

```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -10
```
Expected: passes.

- [ ] **Step 7: Run fast test suite**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q -m "not slow" --tb=short 2>&1 | tail -15
```

- [ ] **Step 8: Commit**

```bash
cd Z:/o/OBD2v2
git add -A
git commit -m "refactor: move main.py and obd_config.json into src/pi/ (sweep 3, task 9)"
```

---

## Task 10: Create `src/common/contracts/` empty skeleton

**Goal:** Create empty contract stub files per design doc. Each file contains only a module docstring explaining what will eventually live there. **No classes, no dataclasses, no business logic** — this is an explicit design decision (CIO, 2026-04-12): real contracts get defined post-reorg when actual data starts flowing.

**Files to create:**
- `src/common/contracts/__init__.py`
- `src/common/contracts/protocol.py`
- `src/common/contracts/drive_log.py`
- `src/common/contracts/vehicle.py`
- `src/common/contracts/alerts.py`
- `src/common/contracts/recommendations.py`
- `src/common/contracts/backup.py`
- `src/common/constants.py` (also empty stub)

- [ ] **Step 1: Create `src/common/contracts/__init__.py`**

```python
"""
Shared wire contracts for Pi↔Server data exchange.

All types in this package are imported by BOTH tiers and must not change
without a protocolVersion bump. See src/common/constants.py for the version.

**Current state: empty skeleton.** These files are placeholders. Real contract
types will be defined in a dedicated post-reorg task, once the Pi has actually
connected to the OBD-II Bluetooth dongle and we have real data to design against.
Defining contract types against hypothetical data shapes would bake in
assumptions that reality will contradict.
"""
```

- [ ] **Step 2: Create `src/common/contracts/protocol.py`**

```python
"""
Wire protocol envelope types.

Will eventually contain:
- protocolVersion: str constant (single source of truth)
- UploadEnvelope: the Pi→Server upload wire format
- HandshakeRequest / HandshakeResponse: version negotiation at upload time
- UploadStatus: success/reject/retry classification

Populated post-reorg when real data flow begins.
"""
```

- [ ] **Step 3: Create `src/common/contracts/drive_log.py`**

```python
"""
Drive log wire format.

Will eventually contain:
- DriveLog: a complete drive's telemetry (metadata + samples)
- Reading: single timestamped PID reading
- DriveSummary: aggregated stats attached to a drive
- DriveEventType: enum of drive lifecycle events

Populated post-reorg when real drive data starts flowing from the dongle.
"""
```

- [ ] **Step 4: Create `src/common/contracts/vehicle.py`**

```python
"""
Vehicle identity wire format.

Will eventually contain:
- VehicleInfo: VIN-decoded static data (make, model, year, engine, etc.)
- StaticReading: single static-data reading (one field of VehicleInfo)

Populated post-reorg.
"""
```

- [ ] **Step 5: Create `src/common/contracts/alerts.py`**

```python
"""
Alert event wire format.

Will eventually contain:
- AlertEvent: the wire representation of an alert firing (Pi-side event,
  uploaded to server for analysis history)
- AlertLevel: enum (normal, caution, danger)
- AlertParameter: enum of monitored parameters

Populated post-reorg.
"""
```

- [ ] **Step 6: Create `src/common/contracts/recommendations.py`**

```python
"""
Tuning recommendation wire format.

Will eventually contain:
- Recommendation: a tuning adjustment proposed by the server, staged for
  CIO review before any ECMLink action. Includes severity, rationale,
  before/after values, and a unique ID.
- RecommendationStatus: enum (pending, reviewed, accepted, rejected, applied)
- RecommendationSource: enum (statistical, spool_ai, manual)

IMPORTANT: Recommendations are ALWAYS staged for human review, never
auto-applied to the ECU. See CLAUDE.md architectural decision #2.

Populated post-reorg when the server analysis pipeline (B-031) is built.
"""
```

- [ ] **Step 7: Create `src/common/contracts/backup.py`**

```python
"""
Backup metadata wire format.

Will eventually contain:
- BackupMetadata: a backup artifact's metadata (filename, size, checksum,
  device ID, timestamp, content type)
- BackupType: enum (drive_log, config_snapshot, calibration, other)

Populated post-reorg.
"""
```

- [ ] **Step 8: Create `src/common/constants.py`**

```python
"""
Protocol and schema version constants.

Shared between Pi and server. Any change to these values requires a
coordinated deploy of both tiers (per CLAUDE.md architectural decision #6).

Populated post-reorg when the handshake is actually implemented.
"""

# Placeholder — real values land when the protocol handshake is built.
# PROTOCOL_VERSION = "1.0.0"
# SCHEMA_VERSION = "1.0.0"
```

- [ ] **Step 9: Verify all files are importable**

```bash
cd Z:/o/OBD2v2
python -c "import src.common.contracts; import src.common.contracts.protocol; import src.common.contracts.drive_log; import src.common.contracts.vehicle; import src.common.contracts.alerts; import src.common.contracts.recommendations; import src.common.contracts.backup; import src.common.constants; print('OK')"
```
Expected: `OK`.

- [ ] **Step 10: Commit the contracts skeleton**

```bash
cd Z:/o/OBD2v2
git add src/common/contracts/ src/common/constants.py
git commit -m "feat: create empty src/common/contracts/ skeleton (sweep 3, task 10)

Empty placeholder files — no classes, no dataclasses, no business logic.
Real contract types will be defined in a dedicated post-reorg task once
the Pi has connected to the OBD-II dongle and real data is flowing.
See design doc section 10 for rationale."
```

---

## Task 11: Create `src/pi/clients/` and `src/pi/inbox/` skeletons

**Goal:** Create skeleton packages for the Pi-side HTTP clients and the recommendation inbox reader.

**Files:**
- Create: `src/pi/clients/__init__.py`
- Create: `src/pi/clients/ollama_client.py` (empty stub)
- Create: `src/pi/clients/uploader.py` (empty stub)
- Create: `src/pi/inbox/__init__.py`
- Create: `src/pi/inbox/reader.py` (empty stub)

- [ ] **Step 1: Create `src/pi/clients/__init__.py`**

```python
"""
Pi-side HTTP clients for talking to the companion service and remote Ollama.

All real work lands in future sprints (B-023, B-027).
"""
```

- [ ] **Step 2: Create `src/pi/clients/ollama_client.py`**

```python
"""
Thin HTTP client for the remote Ollama instance (or the companion service's
/api/chat endpoint once it exists).

Will eventually contain:
- OllamaClient: a connection manager + request helper
- chat(): synchronous prompt→response helper
- isAvailable(): quick health check

Populated when the Pi needs to request AI analysis from the server.
This replaces the temporary direct import of src.server.ai.ollama_manager
documented in TD-reorg-sweep3-ollama-boundary.md.
"""
```

- [ ] **Step 3: Create `src/pi/clients/uploader.py`**

```python
"""
Drive log upload client — Pi pushes to the companion service.

Will eventually contain:
- Uploader: HTTP client that sends DriveLog payloads to the companion service
- delta sync logic (only unsent data)
- retry on network failure
- protocol version handshake (rejects upload on mismatch)

Populated by B-027 (Client-Side Sync to Chi-Srv-01).
"""
```

- [ ] **Step 4: Create `src/pi/inbox/__init__.py`**

```python
"""
Pi-side recommendation inbox reader.

Recommendations from the server land in a file-based inbox on the Pi
(see CLAUDE.md architectural decision #2 — never auto-apply to ECU).
This package reads them for display / CIO review.

Implementation lands with the first server→Pi recommendation flow.
"""
```

- [ ] **Step 5: Create `src/pi/inbox/reader.py`**

```python
"""
Recommendation inbox reader.

Will eventually contain:
- listPendingRecommendations(): enumerate unread Recommendation files
- markAsReviewed(): move a recommendation to reviewed state
- readRecommendation(): parse a single recommendation file

Populated when the server recommendation flow is built.
"""
```

- [ ] **Step 6: Verify importable**

```bash
cd Z:/o/OBD2v2
python -c "import src.pi.clients; import src.pi.clients.ollama_client; import src.pi.clients.uploader; import src.pi.inbox; import src.pi.inbox.reader; print('OK')"
```
Expected: `OK`.

- [ ] **Step 7: Commit the Pi skeletons**

```bash
cd Z:/o/OBD2v2
git add src/pi/clients/ src/pi/inbox/
git commit -m "feat: create src/pi/clients/ and src/pi/inbox/ skeletons (sweep 3, task 11)"
```

---

## Task 12: Create `src/server/` placeholder subpackages

**Goal:** Create skeleton packages for `api/`, `ingest/`, `analysis/`, `recommendations/`, `db/` and a placeholder `main.py`.

**Files:**
- Create: `src/server/main.py`
- Create: `src/server/api/__init__.py`
- Create: `src/server/api/app.py`
- Create: `src/server/api/health.py`
- Create: `src/server/api/middleware/__init__.py`
- Create: `src/server/ingest/__init__.py`
- Create: `src/server/analysis/__init__.py`
- Create: `src/server/recommendations/__init__.py`
- Create: `src/server/db/__init__.py`

- [ ] **Step 1: Create `src/server/main.py`**

```python
"""
Companion service entry point.

Placeholder — real FastAPI app wiring lands with B-022 (US-CMP-001 through
US-CMP-009). When populated, this file will:
- Load common config via src.common.config.validator
- Construct the FastAPI app from src.server.api.app
- Install API key middleware from src.server.api.middleware
- Register routes from src.server.api.health, ingest, recommendations
- Launch via uvicorn

For now, running this file is a no-op.
"""

if __name__ == "__main__":
    print("src/server/main.py is a placeholder. Real implementation lands with B-022.")
```

- [ ] **Step 2: Create `src/server/api/__init__.py`**

```python
"""FastAPI app, routes, middleware. Filled in by B-022."""
```

- [ ] **Step 3: Create `src/server/api/app.py`**

```python
"""
FastAPI app factory.

Placeholder — populated by B-022 US-CMP-001 (Project Scaffolding).
Will eventually contain:
- createApp() factory that builds and configures the FastAPI instance
- CORS, logging, error handlers
"""
```

- [ ] **Step 4: Create `src/server/api/health.py`**

```python
"""
Health endpoint.

Placeholder — populated by B-022 US-CMP-008 (Health Endpoint with Component Status).
Will eventually expose GET /health with component status (DB, Ollama, disk, etc.).
"""
```

- [ ] **Step 5: Create `src/server/api/middleware/__init__.py`**

```python
"""
FastAPI middleware (API key auth, request logging, rate limiting).

Placeholder — populated by B-022 US-CMP-002 (API Key Authentication Middleware).
Uses hmac.compare_digest() for constant-time key comparison.
"""
```

- [ ] **Step 6: Create `src/server/ingest/__init__.py`**

```python
"""
Drive log ingestion and delta sync.

Placeholder — populated by B-022 US-CMP-004 (Delta Sync Endpoint).
Will eventually receive DriveLog payloads from Pi, deduplicate via
(source_device, source_id) key, and write to MariaDB.
"""
```

- [ ] **Step 7: Create `src/server/analysis/__init__.py`**

```python
"""
Post-drive server-side analysis.

Placeholder — populated by B-031 (Server Analysis Pipeline, 7 stories from
Spool's tuning spec). Runs deeper statistical and ML analysis on ingested
drive data and produces tuning recommendations.
"""
```

- [ ] **Step 8: Create `src/server/recommendations/__init__.py`**

```python
"""
Recommendation writer — produces staged Recommendation files for CIO review.

Placeholder — populated alongside B-031. Writes Recommendation artifacts to
a file-based inbox readable by the Pi (see src/pi/inbox/).

IMPORTANT: Recommendations are ALWAYS staged for human review, never
auto-applied to the ECU. See CLAUDE.md architectural decision #2.
"""
```

- [ ] **Step 9: Create `src/server/db/__init__.py`**

```python
"""
MariaDB schema and models.

Placeholder — populated by B-022 US-CMP-003 (MariaDB Database Schema and
Connection). The schema mirrors Pi SQLite but uses source_device + source_id
as the upsert key (multi-device ready).
"""
```

- [ ] **Step 10: Verify all server skeleton files are importable**

```bash
cd Z:/o/OBD2v2
python -c "
import src.server
import src.server.api
import src.server.api.app
import src.server.api.health
import src.server.api.middleware
import src.server.ingest
import src.server.analysis
import src.server.recommendations
import src.server.db
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 11: Commit the server skeletons**

```bash
cd Z:/o/OBD2v2
git add src/server/
git commit -m "feat: create src/server/ placeholder subpackages (sweep 3, task 12)

- api/ (with app.py, health.py, middleware/) — B-022 US-CMP-001, 002, 008
- ingest/ — B-022 US-CMP-004
- analysis/ — B-031
- recommendations/ — B-031
- db/ — B-022 US-CMP-003
- main.py — B-022 US-CMP-001

All real implementation lands with future sprints. Structure exists so
those stories don't need to invent it."
```

---

## Task 13: Create README files for every top-level src/ directory

**Goal:** Populate `src/README.md`, `src/common/README.md` (update existing/create new), `src/pi/README.md`, `src/server/README.md` with one-line-per-module TOCs that match the final layout.

**Files:**
- Create: `src/README.md`
- Update: `src/pi/README.md` (already created in task 2)
- Update: `src/server/README.md` (already created in task 2)
- Create/update: `src/common/README.md`

- [ ] **Step 1: Create `src/README.md`**

Create `src/README.md`:
```markdown
# src/ — OBD2v2 Source Tree

This tree is organized by deployment tier. See
`docs/superpowers/specs/2026-04-12-reorg-design.md` for the architectural
rationale.

## Top-level structure

- **`common/`** — Deployed to both tiers. Utilities, shared contracts, config schema, errors, logging.
- **`pi/`** — Deployed to Raspberry Pi only. Hardware, display, OBD data collection, orchestrator, simulator.
- **`server/`** — Deployed to Chi-Srv-01 only. FastAPI app, AI analysis, ingest, recommendation staging, MariaDB models.

## Deployment rule

The deploy script copies `src/common/ + src/<tier>/` to the appropriate host.
`src/pi/` never reaches the server. `src/server/` never reaches the Pi.

## Import rules

- Within a tier: use package-local relative imports (`from .X import Y`)
- Cross-package within a tier: use absolute imports (`from src.pi.obd.X import Y`)
- From tier to common: use absolute imports (`from src.common.config.validator import X`)
- **Tier-to-tier imports are FORBIDDEN.** `src/pi/` cannot import from `src/server/` and vice versa.

## Finding things

- Shared types (DriveLog, Recommendation, etc.): `src/common/contracts/`
- Config validation: `src/common/config/`
- Pi entry point: `src/pi/main.py`
- Pi orchestrator: `src/pi/obd/orchestrator/` (post-sweep 5)
- Server entry point: `src/server/main.py`
- Server AI: `src/server/ai/`
```

- [ ] **Step 2: Update `src/pi/README.md`**

Replace the placeholder contents (from task 2) with a real TOC:
```markdown
# src/pi/ — Raspberry Pi Tier

Deployed to `chi-eclipse-tuner` only. Contains all hardware-interfacing and
real-time data collection code.

## Structure

- **`main.py`** — Entry point. Boots the orchestrator.
- **`obd_config.json`** — Pi configuration (moves to repo root in sweep 4)
- **`obd/`** — OBD-II subsystem (connection, parameters, data logging, drive detection, orchestrator, simulator, shutdown, VIN decoder, vehicle data, services)
- **`hardware/`** — GPIO, I2C, platform utilities, hardware manager
- **`display/`** — Display manager, drivers (headless, developer, minimal), adapters (Adafruit)
- **`power/`** — Battery and power monitoring
- **`alert/`** — Real-time alert manager (tiered threshold system only)
- **`profile/`** — Driving profile manager and switcher
- **`calibration/`** — Calibration session management and comparison
- **`backup/`** — Backup manager (Google Drive)
- **`analysis/`** — Pi-side realtime analysis (engine, profile statistics). Pure math is in `src/common/analysis/`.
- **`clients/`** — HTTP clients for server communication (Ollama, uploader). Skeletons — real implementations land with B-023/B-027.
- **`inbox/`** — Recommendation review inbox reader. Skeleton.

## Dependencies

- Imports from `src.common.*` allowed
- Imports from `src.server.*` **forbidden** (structurally enforced by deployment)
```

- [ ] **Step 3: Update `src/server/README.md`**

Replace with:
```markdown
# src/server/ — Companion Service Tier

Deployed to `chi-srv-01` only. Contains AI analysis and future FastAPI service.

## Structure

- **`main.py`** — Entry point (placeholder). Real implementation lands with B-022 US-CMP-001.
- **`ai/`** — AI analysis — **real code** migrated from `src/ai/` in sweep 3. Contains: analyzer, data_preparation, prompt_template, ranker, ollama_manager, types, helpers.
- **`api/`** — FastAPI app, routes, middleware. **Skeleton** — B-022 US-CMP-001, 002, 008.
- **`ingest/`** — Drive log ingestion, delta sync. **Skeleton** — B-022 US-CMP-004.
- **`analysis/`** — Post-drive deep analysis. **Skeleton** — B-031.
- **`recommendations/`** — Recommendation writer (writes to Pi inbox). **Skeleton** — B-031.
- **`db/`** — MariaDB schema and models. **Skeleton** — B-022 US-CMP-003.

## Dependencies

- Imports from `src.common.*` allowed
- Imports from `src.pi.*` **forbidden** (structurally enforced by deployment)
```

- [ ] **Step 4: Create `src/common/README.md`**

```markdown
# src/common/ — Shared Tier

Deployed to BOTH Pi and server. Contains only tier-agnostic code and shared
contracts.

## Structure

- **`config/`** — Config validator, secrets loader, config schema types
  - `validator.py` — config.json schema validation and defaults
  - `secrets_loader.py` — resolves `${ENV_VAR}` placeholders
- **`errors/`** — Error classification and handlers
  - `handler.py` — 5-tier error handler (retryable, auth, config, data, system)
- **`logging/`** — Logging setup
  - `setup.py` — logger configuration helpers
- **`analysis/`** — Pure stateless math used by both tiers
  - `calculations.py` — mean, stddev, outlier bounds (no state, no tier-specific deps)
- **`contracts/`** — Shared wire contracts (Pi↔Server protocol types). **Skeleton** — populated post-reorg when real data flows.
  - `protocol.py`, `drive_log.py`, `vehicle.py`, `alerts.py`, `recommendations.py`, `backup.py`
- **`constants.py`** — Protocol and schema version constants. **Skeleton**.

## Dependencies

- May import stdlib and minimal third-party libraries (e.g., `pydantic`, `jsonschema`)
- **Cannot import from `src.pi.*` or `src.server.*`** (tier-agnostic by design)
- Both tiers import from here
```

- [ ] **Step 5: Commit READMEs**

```bash
cd Z:/o/OBD2v2
git add src/README.md src/common/README.md src/pi/README.md src/server/README.md
git commit -m "docs: create README files for src/, common/, pi/, server/ (sweep 3, task 13)"
```

---

## Task 14: Full verification

**Files:**
- No changes — verification only

- [ ] **Step 1: Full test suite (including slow tests)**

```bash
cd Z:/o/OBD2v2
pytest tests/ --tb=short 2>&1 | tail -20
```
Expected: same baseline count as start of sweep 3. If count dropped, investigate.

- [ ] **Step 2: Ruff lint**

```bash
cd Z:/o/OBD2v2
ruff check src/ tests/ 2>&1 | tail -15
```
Expected: no new errors relative to pre-sweep baseline.

- [ ] **Step 3: Mypy type check**

```bash
cd Z:/o/OBD2v2
mypy src/ 2>&1 | tail -15
```
Expected: no new errors.

- [ ] **Step 4: Tier boundary audit**

Verify that no Pi code imports from server or vice versa.

Run:
```bash
cd Z:/o/OBD2v2
echo "=== Pi → Server violations ==="
grep -rn "from src\.server\|import src\.server" src/pi/ tests 2>/dev/null | grep -v "TD-reorg-sweep3-ollama-boundary"
echo "=== Server → Pi violations ==="
grep -rn "from src\.pi\|import src\.pi" src/server/ 2>/dev/null
echo "=== Common → tier-specific violations ==="
grep -rn "from src\.pi\|from src\.server\|import src\.pi\|import src\.server" src/common/ 2>/dev/null
```

Expected: first section may show the documented `ollama_manager` exception (if it exists), second and third sections should be empty.

Any new violations must be fixed before merge.

- [ ] **Step 5: Orphan check — ensure no files remain at old top-level locations**

```bash
cd Z:/o/OBD2v2
ls src/hardware src/display src/power src/alert src/profile src/calibration src/backup src/analysis src/ai src/obd 2>/dev/null
```
Expected: all of these fail with "No such file or directory" — they've all moved.

```bash
cd Z:/o/OBD2v2
ls src/main.py src/obd_config.json 2>/dev/null
```
Expected: both fail.

- [ ] **Step 6: Simulator smoke test**

```bash
cd Z:/o/OBD2v2
timeout 30 python src/pi/main.py --simulate --dry-run 2>&1 | tail -30
```

Expected: clean simulator startup, no `ModuleNotFoundError`, component init order matches expectations.

**Note**: the command is now `python src/pi/main.py` because main.py moved. If the simulator references hardcoded paths to the config file, adjust accordingly.

- [ ] **Step 7: Update `validate_config.py` if it has stale paths**

```bash
cd Z:/o/OBD2v2
python validate_config.py 2>&1 | tail -10
```
Expected: passes. If it fails with a file-not-found error for obd_config.json, fix the path reference.

---

## Task 15: Cleanup, design doc update, merge

**Files:**
- Modify: `docs/superpowers/specs/2026-04-12-reorg-design.md` (section 12)
- Delete: `docs/superpowers/plans/sweep3-notes.md`

- [ ] **Step 1: Delete sweep 3 notes scratch file**

```bash
cd Z:/o/OBD2v2
git rm docs/superpowers/plans/sweep3-notes.md
git commit -m "chore: remove sweep 3 notes scratch file"
```

- [ ] **Step 2: Append sweep 3 status to design doc section 12**

Append row:
```markdown
| YYYY-MM-DD | 3 | Sweep 3 complete. Created src/pi/, src/server/; restructured src/common/ into subpackages; moved ~40 files across tier boundaries; created empty contracts skeleton; created Pi and server placeholder packages; wrote READMEs. No tier-boundary violations (except documented ollama_manager temporary). Full test suite passes (NNN tests). Simulator smoke test green. **Checkpoint B passed.** |
```

- [ ] **Step 3: Commit the design doc update**

```bash
cd Z:/o/OBD2v2
git add docs/superpowers/specs/2026-04-12-reorg-design.md
git commit -m "docs: sweep 3 status update — Checkpoint B passed"
```

- [ ] **Step 4: Surface to CIO for Checkpoint B approval**

Tell the CIO:
> "Sweep 3 complete. Tier split done, all tests green, simulator green, no tier-boundary violations (except documented ollama exception). Ready for Checkpoint B approval. Approve merge to main? Per design doc, a 24-hour cooling period begins after merge before sweep 4 starts."

Wait for explicit approval.

- [ ] **Step 5: After approval, merge to main**

```bash
cd Z:/o/OBD2v2
git checkout main
git merge --no-ff sprint/reorg-sweep3-tier-split -m "Merge sprint/reorg-sweep3-tier-split: Sweep 3 complete — tier split + contracts

Sweep 3 of 6 for the structural reorganization (B-040). High-risk sweep.

- Created src/pi/ (Pi-only code) and src/server/ (server-only code)
- Restructured src/common/ into config/, errors/, logging/, analysis/ subpackages
- Moved src/hardware, display, power, alert, profile, calibration, backup, analysis, ai, obd to their tier locations
- Moved src/main.py → src/pi/main.py
- Moved src/obd_config.json → src/pi/obd_config.json (promoted to repo root in sweep 4)
- Created empty src/common/contracts/ skeleton (populated post-reorg)
- Created src/pi/clients/ and src/pi/inbox/ skeletons
- Created src/server/ api/ingest/analysis/recommendations/db placeholders
- Wrote README.md files at src/, src/common/, src/pi/, src/server/
- Updated every import statement across src/ and tests/
- All tests green, simulator smoke test green
- Checkpoint B passed
- Design doc: docs/superpowers/specs/2026-04-12-reorg-design.md"
git log --oneline -8
```

- [ ] **Step 6: Confirm main is green**

```bash
cd Z:/o/OBD2v2
pytest tests/ -x -q --tb=short 2>&1 | tail -5
```

- [ ] **Step 7: Start 24-hour cooling period**

Per design doc section 8.5, a 24-hour cooling period is required after sweep 3 before sweep 4 begins. During the cooling period:
- Do not start sweep 4
- Keep the sweep 3 branch alive (don't delete)
- Watch for issues: if you discover a problem post-merge, fix forward on a new small branch

Tell the CIO:
> "Sweep 3 merged to main. Checkpoint B complete. 24-hour cooling period begins now. Sweep 4 can start any time after [current time + 24h]."

Record the start time in a note or calendar reminder.

---

## End of Sweep 3 Plan

**Success criteria:**
- ✅ `src/pi/`, `src/server/`, `src/common/` subpackages exist
- ✅ All Pi-only code in `src/pi/`
- ✅ All server-only code in `src/server/`
- ✅ Shared code in `src/common/`
- ✅ Contracts skeleton (empty files) exists
- ✅ Placeholder packages for future stories exist
- ✅ READMEs at every top-level src/ directory
- ✅ No tier-boundary violations (except documented ollama temp)
- ✅ All tests green
- ✅ Merged to main, cooling period started

**On to sweep 4**: `docs/superpowers/plans/2026-04-12-reorg-sweep4-config.md`

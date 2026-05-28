# dev/main Branching Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the dev/main two-tier branching workflow per spec `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`. This rewrites PM Rules 8 + 9, updates the three sprint workflow skills (`/sprint-deploy-pm`, `/sprint-validated`, `/chain-validated`), adds a small enhancement to `pm_status.py`, bootstraps the `dev` branch, and updates PM/agent memory artifacts.

**Architecture:** Mostly textual edits to skill markdown files and `projectManager.md` (load-bearing PM doc) — these are themselves the "code" that Claude executes when slash commands fire. One TDD-friendly Python enhancement (`pm_status.py`). One git bootstrap step (create `dev` from `main`). Two memory/agenda updates.

**Tech Stack:** Python 3.11+ (pytest), bash/PowerShell, markdown, git. No new dependencies.

**Spec reference:** `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md` — sections cited by §N below.

---

## File Structure

**Files modified** (no new files):
- `offices/pm/scripts/pm_status.py` — add `formatBranchTips()` pure formatter + `getBranchTip(branchName)` git helper + wire into output
- `tests/pm/test_pm_status_v2.py` — add tests for the new formatter + helper
- `.claude/commands/sprint-deploy-pm.md` — Phase 0 stop-condition addition, NEW Phase 3.5 (merge to dev), Phase 5 + 6 retargeted to dev
- `.claude/commands/sprint-validated.md` — Phase 0 expects dev, Phase 5 pushes dev, Phase 6 REMOVED
- `.claude/commands/chain-validated.md` — Phase 0 expects dev, Phase 4 merges dev→main, NEW Phase 6.5 (dev fast-forwards to main)
- `offices/pm/projectManager.md` — PM Rule 8 + PM Rule 9 rewrites; Last Updated header bump
- `offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md` — mark directive #1 DONE
- `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md` — Standing CIO directives entry + Current State pointer reflects bootstrap

**Git op** (no file diff):
- `git checkout -b dev origin/main && git push -u origin dev` — creates the dev branch

**Out of scope** (deferred to other plans):
- Validation-criteria-upfront contract (directive #2 — separate spec coming next)
- `sprint_lint.py` soft branch-check warning (spec §9 — "PM lean: defer; not load-bearing")
- `/hotfix-pm` skill scaffolding (spec §8.2 — manual ritual until usage frequency justifies)

---

## Task 1: `pm_status.py` — formatBranchTips pure formatter (TDD)

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/scripts/pm_status.py` (add function near top of file, before `printSprintSummary`)
- Modify: `Z:/o/OBD2v2/tests/pm/test_pm_status_v2.py` (add test class `TestFormatBranchTips`)

- [ ] **Step 1: Read existing pm_status.py structure**

Run: `Read Z:/o/OBD2v2/offices/pm/scripts/pm_status.py` (full file).

Locate where the printable functions live (`printSprintSummary`, `printCounterSummary`, etc.). Identify the imports. Confirm `subprocess` is or is not already imported.

Expected outcome: know where to slot the new function and whether `subprocess` import needs adding.

- [ ] **Step 2: Read existing test file**

Run: `Read Z:/o/OBD2v2/tests/pm/test_pm_status_v2.py` (full file).

Identify the test class pattern used (pytest functions vs unittest TestCase, fixture style, imports).

Expected outcome: match the existing test style for the new tests.

- [ ] **Step 3: Write failing test for formatBranchTips**

Add to `tests/pm/test_pm_status_v2.py`:

```python
class TestFormatBranchTips:
    """Tests for the dev/main branch-tip summary block (spec 2026-05-28)."""

    def test_formatBranchTips_bothBranches_returnsTwoLineBlock(self):
        from offices.pm.scripts.pm_status import formatBranchTips
        result = formatBranchTips(
            mainHash="abc1234",
            mainVersion="V0.27.19",
            devHash="def5678",
            devVersion="V0.28.0",
        )
        assert "=== BRANCHES ===" in result
        assert "main: V0.27.19 / abc1234" in result
        assert "dev:  V0.28.0 / def5678" in result

    def test_formatBranchTips_devMissing_returnsNotBootstrappedMarker(self):
        from offices.pm.scripts.pm_status import formatBranchTips
        result = formatBranchTips(
            mainHash="abc1234",
            mainVersion="V0.27.19",
            devHash=None,
            devVersion=None,
        )
        assert "main: V0.27.19 / abc1234" in result
        assert "dev:  not yet bootstrapped" in result

    def test_formatBranchTips_devAtMain_marksConverged(self):
        from offices.pm.scripts.pm_status import formatBranchTips
        result = formatBranchTips(
            mainHash="abc1234",
            mainVersion="V0.27.19",
            devHash="abc1234",
            devVersion="V0.27.19",
        )
        assert "dev:  V0.27.19 / abc1234 (= main; ready for next chain)" in result
```

- [ ] **Step 4: Run tests, confirm they fail**

Run from repo root: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_pm_status_v2.py::TestFormatBranchTips -v`

Expected: 3 tests FAIL with `ImportError: cannot import name 'formatBranchTips' from offices.pm.scripts.pm_status`.

- [ ] **Step 5: Implement formatBranchTips**

Add to `offices/pm/scripts/pm_status.py` (near top, after imports, before `printSprintSummary`):

```python
def formatBranchTips(
    mainHash: str,
    mainVersion: str,
    devHash: str | None,
    devVersion: str | None,
) -> str:
    """Format the dev + main branch-tip summary block.

    Pure formatter — does not call git. Caller provides hashes + versions.

    Returns a multi-line string like:
        === BRANCHES ===
          main: V0.27.19 / abc1234
          dev:  V0.28.0  / def5678
    """
    lines = ["=== BRANCHES ===", f"  main: {mainVersion} / {mainHash}"]
    if devHash is None:
        lines.append("  dev:  not yet bootstrapped")
    elif devHash == mainHash:
        lines.append(f"  dev:  {devVersion} / {devHash} (= main; ready for next chain)")
    else:
        lines.append(f"  dev:  {devVersion} / {devHash}")
    return "\n".join(lines)
```

- [ ] **Step 6: Run tests, confirm pass**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_pm_status_v2.py::TestFormatBranchTips -v`

Expected: 3 PASS.

- [ ] **Step 7: Commit Task 1**

```bash
cd Z:/o/OBD2v2
git add offices/pm/scripts/pm_status.py tests/pm/test_pm_status_v2.py
git commit -m "feat(pm_status): formatBranchTips pure formatter for dev+main display"
```

---

## Task 2: `pm_status.py` — getBranchTip git helper (TDD)

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/scripts/pm_status.py`
- Modify: `Z:/o/OBD2v2/tests/pm/test_pm_status_v2.py`

- [ ] **Step 1: Write failing test for getBranchTip**

Add to the `TestFormatBranchTips` class section (or a new `TestGetBranchTip` class):

```python
import subprocess
from unittest.mock import patch

class TestGetBranchTip:
    """Tests for getBranchTip — queries git for branch hash + RELEASE_VERSION."""

    def test_getBranchTip_existingBranch_returnsHashAndVersion(self):
        from offices.pm.scripts.pm_status import getBranchTip
        with patch("subprocess.run") as mockRun:
            mockRun.side_effect = [
                # rev-parse: short hash
                subprocess.CompletedProcess(args=[], returncode=0, stdout="abc1234\n"),
                # show: RELEASE_VERSION contents
                subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout='{"version": "V0.27.19", "theme": "x"}\n',
                ),
            ]
            hashStr, version = getBranchTip("main")
            assert hashStr == "abc1234"
            assert version == "V0.27.19"

    def test_getBranchTip_missingBranch_returnsNoneTuple(self):
        from offices.pm.scripts.pm_status import getBranchTip
        with patch("subprocess.run") as mockRun:
            mockRun.return_value = subprocess.CompletedProcess(
                args=[], returncode=128, stdout="", stderr="unknown revision\n",
            )
            hashStr, version = getBranchTip("dev")
            assert hashStr is None
            assert version is None
```

- [ ] **Step 2: Run tests, confirm fail**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_pm_status_v2.py::TestGetBranchTip -v`

Expected: 2 FAIL with `ImportError`.

- [ ] **Step 3: Implement getBranchTip**

Add to `offices/pm/scripts/pm_status.py` (right after `formatBranchTips`):

```python
import json as _json_for_branch_tip  # local alias avoids any top-level shadowing

def getBranchTip(branchName: str) -> tuple[str | None, str | None]:
    """Query git for a branch's short hash + its RELEASE_VERSION 'version' field.

    Returns (hash, version) on success. Returns (None, None) if the branch
    does not exist (e.g., dev pre-bootstrap).
    """
    revParse = subprocess.run(
        ["git", "rev-parse", "--short", branchName],
        capture_output=True, text=True,
    )
    if revParse.returncode != 0:
        return (None, None)
    hashStr = revParse.stdout.strip()

    show = subprocess.run(
        ["git", "show", f"{branchName}:deploy/RELEASE_VERSION"],
        capture_output=True, text=True,
    )
    if show.returncode != 0:
        return (hashStr, "unknown")
    try:
        data = _json_for_branch_tip.loads(show.stdout)
        version = data.get("version", "unknown")
    except _json_for_branch_tip.JSONDecodeError:
        version = "unknown"
    return (hashStr, version)
```

(If `subprocess` is not already imported at top of file, add `import subprocess` to the import block.)

- [ ] **Step 4: Run tests, confirm pass**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/test_pm_status_v2.py::TestGetBranchTip -v`

Expected: 2 PASS.

- [ ] **Step 5: Commit Task 2**

```bash
cd Z:/o/OBD2v2
git add offices/pm/scripts/pm_status.py tests/pm/test_pm_status_v2.py
git commit -m "feat(pm_status): getBranchTip git helper for branch hash + version lookup"
```

---

## Task 3: `pm_status.py` — wire branch summary into main output

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/scripts/pm_status.py`

- [ ] **Step 1: Locate the v2 main printing block**

In `pm_status.py`, find the v2 path (Schema 2.0.0 branch — `computeRollups() + renderTree() + active PRDs + sprint` per the module docstring). This is the block that runs by default when no `--sprint`/`--counter` flag is passed.

- [ ] **Step 2: Add a `printBranchSummary()` call at the top of the v2 main output**

Insert this function near the other `printX` definitions:

```python
def printBranchSummary() -> None:
    """Print dev + main branch-tip summary (spec 2026-05-28)."""
    mainHash, mainVersion = getBranchTip("main")
    devHash, devVersion = getBranchTip("dev")
    if mainHash is None:
        # repo without main — skip (extremely unusual)
        return
    print(formatBranchTips(mainHash, mainVersion, devHash, devVersion))
    print()
```

Then in the main v2 entry path (around where `=== BACKLOG v2.0.0 ===` first prints), call `printBranchSummary()` **before** the backlog tree so PM sees branches first.

- [ ] **Step 3: Smoke-test the output**

Run from repo root: `cd Z:/o/OBD2v2 && python offices/pm/scripts/pm_status.py | head -20`

Expected output starts with:
```
=== BRANCHES ===
  main: V0.27.19 / d31cece
  dev:  not yet bootstrapped

=== BACKLOG v2.0.0 ===
E-001    [active  ] UI/UX Polish
...
```

(`dev: not yet bootstrapped` until Task 7 runs.)

- [ ] **Step 4: Re-run full pm test suite**

Run: `cd Z:/o/OBD2v2 && python -m pytest tests/pm/ -v`

Expected: 51+ pass (the 46 pre-existing + 5 new from Tasks 1+2). Zero failures.

- [ ] **Step 5: Commit Task 3**

```bash
cd Z:/o/OBD2v2
git add offices/pm/scripts/pm_status.py
git commit -m "feat(pm_status): print dev + main branch tips at top of v2 output"
```

---

## Task 4: Update `/sprint-deploy-pm` skill body

**Files:**
- Modify: `Z:/o/OBD2v2/.claude/commands/sprint-deploy-pm.md`

Reference: spec §6.1 (full phase-by-phase delta table).

- [ ] **Step 1: Re-read current skill body**

Run: `Read Z:/o/OBD2v2/.claude/commands/sprint-deploy-pm.md` (full).

- [ ] **Step 2: Edit Phase 0 — add merge-base check**

Find the Phase 0 stop-condition list. Add a new bullet after "Branch is `main`":

```
- Sprint branch's merge-base with `dev` ≠ current `dev` HEAD (sprint branched off stale dev tip — abort and ask CIO whether to rebase or merge through)
```

Also add the verification command to the Phase 0 bash block:

```bash
test "$(git merge-base HEAD dev 2>/dev/null)" = "$(git rev-parse dev 2>/dev/null)" \
  || echo "WARN: sprint branched off stale dev tip"
```

- [ ] **Step 3: Insert new Phase 3.5 — Merge sprint branch into dev**

After current Phase 3 ("Update PM artifacts"), insert:

```markdown
## Phase 3.5 -- Merge sprint branch into dev

```bash
git checkout dev
git pull origin dev               # confirm dev base hasn't moved unexpectedly
git merge --no-ff sprint/sprintN-<phase-name> \
  -m "Merge sprint/sprintN-<phase-name>: <Sprint Name> code-complete N/N"
git push origin dev
```

**Stop condition**: `git pull` brings unexpected commits onto `dev` (someone else pushed); investigate before merge.

**Note**: this replaces the old Phase 4 "sprint-deploy commit on sprint branch" pattern. The merge commit IS the sprint-deploy record now.
```

- [ ] **Step 4: Update Phase 4 — retired**

Replace the entire current Phase 4 ("Sprint-deploy commit + push branch") with:

```markdown
## Phase 4 -- (RETIRED under dev/main workflow)

Phase 3.5 above absorbs the sprint-deploy commit semantics via the merge to `dev`. PM artifact commits (sprint.json, projectManager.md, MEMORY.md) ride on the sprint branch up to the merge — staged in Phases 1-3 + included in the merge commit body.
```

- [ ] **Step 5: Update Phase 5 — RELEASE_VERSION bump on dev**

In Phase 5, change the working branch from sprint branch to `dev`:

```bash
# Now on dev (Phase 3.5 left us here).
# Edit deploy/RELEASE_VERSION:
# - First sprint of a chain: V0.(X+1).0 (minor bump from main's last-validated version)
# - Patch sprint within current chain: V0.X.(Y+1) (patch bump from prior dev tip)

python offices/pm/scripts/verify_release_version.py
git add deploy/RELEASE_VERSION
git commit -m "chore(release): bump V0.X.Y -> V0.(X+1).0 (Sprint N deploy)"
git push origin dev
```

- [ ] **Step 6: Update Phase 6 — deploy from dev**

In Phase 6, change the deploy-target language:

```markdown
## Phase 6 -- Deploy Pi + server FROM dev

```bash
bash deploy/deploy-pi.sh        # Pi pulls latest from origin/dev (deploy script reads dev HEAD)
bash deploy/deploy-server.sh
```

Server deploy is unattended via `/etc/sudoers.d/obd2-deploy` (Sprint 22 fix). Wait for both completions.
```

- [ ] **Step 7: Update Phase 7 — verify dev tip**

Phase 7 verification commands need no syntactic change (they cat `.deploy-version`), but update the prose: "Both should show new V0.X.Y + new gitHash matching `git rev-parse dev`".

- [ ] **Step 8: Update Phase 0 stop-condition table** (bottom of skill)

Add row: `| 0 | Sprint branched off stale dev tip | Abort; ask CIO to rebase or merge through |`
Add row: `| 3.5 | git pull brought unexpected commits to dev | Investigate; abort merge |`

- [ ] **Step 9: Update header description**

In the frontmatter `description:` field, change "Pushes branch; deploys Pi + server FROM SPRINT BRANCH" to "Merges sprint to dev; deploys Pi + server FROM dev". Add a "Per CIO 2026-05-23 directive #1: dev = integration branch; main = fully validated stable" line in the rationale section.

- [ ] **Step 10: Defer commit**

Do NOT commit yet. Tasks 5 + 6 update the other two skills; commit all three together at end of Task 6.

---

## Task 5: Update `/sprint-validated` skill body

**Files:**
- Modify: `Z:/o/OBD2v2/.claude/commands/sprint-validated.md`

Reference: spec §6.2.

- [ ] **Step 1: Re-read current skill body**

Run: `Read Z:/o/OBD2v2/.claude/commands/sprint-validated.md` (full).

- [ ] **Step 2: Update Phase 0 — expect dev, not sprint branch**

In Phase 0, replace the branch check:

```bash
# Was: # SHOULD be the sprint branch (currently deployed-awaiting-validation)
# Now:
git branch --show-current                    # MUST be `dev` (sprint already merged + closed by /sprint-deploy-pm Phase 3.5)
                                             # If on sprint branch: `git checkout dev` first
                                             # If on main: abort -- sprint-validated runs from dev
```

Update Stop conditions:
- Replace "On `main` branch (run from sprint branch)" with "On `main` branch or any `sprint/*` branch — run from `dev`".

- [ ] **Step 3: Update Phase 5 — push dev**

Change Phase 5 push target:

```bash
git add offices/ralph/sprint.json offices/pm/regression_manifest.json offices/pm/backlog.json offices/pm/projectManager.md
git commit -m "chore(validate): Sprint N validated by <drill> -- ready for chain merge"
git push origin dev
```

- [ ] **Step 4: Remove Phase 6 (merge to main) + Phase 7 (tag) bodies**

Replace Phase 6 + Phase 7 sections with:

```markdown
## Phase 6 -- (RETIRED under dev/main workflow)

Per spec 2026-05-28, the merge to `main` no longer happens at per-sprint validation. The chain merge runs once at chain end via `/chain-validated`. Sprint validation now only stamps the per-sprint records on `dev`.

## Phase 7 -- (RETIRED — tagging moves to /chain-validated)

Tags are cut on `main` at chain merge (`/chain-validated` Phase 5), not per-sprint.
```

- [ ] **Step 5: Update Phase 8 — final summary**

Update the closing message to point to `/chain-validated`:

```
| **Status** | **VALIDATED on dev -- awaiting chain close** |

Plus regression manifest status:
[...]

Next step: when the full V0.X.Y chain is whole-green per CIO, run /chain-validated to merge dev -> main.
```

- [ ] **Step 6: Update header description**

In the frontmatter `description:`, change "Merges sprint branch to main + bumps regression_manifest..." to "Stamps per-sprint validation on dev; bumps regression_manifest. Does NOT merge to main -- /chain-validated does that at chain end per spec 2026-05-28."

- [ ] **Step 7: Defer commit**

Continue to Task 6.

---

## Task 6: Update `/chain-validated` skill body

**Files:**
- Modify: `Z:/o/OBD2v2/.claude/commands/chain-validated.md`

Reference: spec §6.3.

- [ ] **Step 1: Re-read current skill body**

Run: `Read Z:/o/OBD2v2/.claude/commands/chain-validated.md` (full).

- [ ] **Step 2: Update Phase 0 — expect dev**

Change Phase 0 branch check:

```bash
git status --short                                    # working tree clean
git branch --show-current                             # MUST be `dev`
git log --oneline @{u}..HEAD                          # no unpushed dev commits
```

Stop conditions:
- Replace "Not on the chain-tip sprint branch" with "Not on `dev`"
- Keep working-tree-dirty + unpushed-commits checks
- Remove "Any chain branch missing from origin" (no longer applicable — only dev needs to be pushed)

- [ ] **Step 3: Update Phase 4 — merge dev to main**

Replace Phase 4 merge command:

```bash
git checkout main
git pull origin main          # confirm main at expected base
git merge --no-ff dev \
  -m "Merge V0.X chain: V0.X.N -- new fully validated stable"
git push origin main
git log --oneline -3 main     # confirm merge landed
```

- [ ] **Step 4: Insert new Phase 6.5 — Fast-forward dev to match main**

After Phase 6 ("Update PM artifacts on main"), insert:

```markdown
## Phase 6.5 -- Fast-forward dev to match main

After main has the chain-merge commit + tag, sync dev to match so the next V0.(X+1).0 sprint starts from a clean dev = main state.

```bash
git checkout dev
git merge --ff-only main
git push origin dev
```

**Stop condition**: `--ff-only` fails (dev has commits main doesn't have). Should NEVER happen at this phase — if it does, a sprint branched and merged to dev *after* the chain merge started; investigate before continuing.
```

- [ ] **Step 5: Update Phase 1 stop conditions**

Update the workflow rationale section — the description in `chain_validate_aggregate.py --chain` still applies (script walks archived sprint.json by prefix). No script changes needed; just the branch where the merge happens.

- [ ] **Step 6: Update header description**

In the frontmatter `description:`, update to: "Merges dev → main once the V0.X chain is whole-green IRL. Per spec 2026-05-28 (dev/main workflow): main = fully validated stable; dev = integration branch carrying the active V0.X.Y chain."

- [ ] **Step 7: Commit Tasks 4 + 5 + 6 together**

```bash
cd Z:/o/OBD2v2
git add .claude/commands/sprint-deploy-pm.md .claude/commands/sprint-validated.md .claude/commands/chain-validated.md
git commit -m "feat(skills): retarget sprint-deploy-pm + sprint-validated + chain-validated for dev/main workflow

Per spec 2026-05-28:
- /sprint-deploy-pm now merges sprint -> dev (NEW Phase 3.5) + deploys from dev
- /sprint-validated runs from dev; no merge to main (Phases 6+7 retired)
- /chain-validated merges dev -> main + fast-forwards dev to main (NEW Phase 6.5)

Skills keep their names; chain concept preserved -- only merge target changes."
```

---

## Task 7: Rewrite PM Rule 8 + Rule 9 in projectManager.md

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/projectManager.md`

Reference: spec §5.1 + §5.2.

- [ ] **Step 1: Locate PM Rules 8 + 9**

In `offices/pm/projectManager.md`, find the `## PM Rules` section. Rules 8 + 9 are the load-bearing sprint-branch + validation-gated-merge rules.

- [ ] **Step 2: Replace PM Rule 8 body with spec §5.1**

Replace the entire Rule 8 paragraph with:

```markdown
8. **Sprint-branch workflow (CIO directive, Session 20; REWRITTEN 2026-05-28 per CIO directive #1 + spec 2026-05-28).** Every sprint runs on its own branch off **`dev`** (not `main`). Marcus creates the branch from `dev` HEAD before loading `sprint.json` and handing off to Ralph. At sprint close, Marcus runs `/sprint-deploy-pm` which merges the sprint branch into `dev` (`--no-ff`), pushes `dev` to origin, bumps `RELEASE_VERSION` on `dev`, and deploys Pi + server **from `dev`**. Sprint branches are short-lived -- they close on merge to `dev`. **Does NOT merge to `main`** -- that is `/chain-validated`'s job at chain end. Ralph never touches git (per `feedback_ralph_no_git_commands.md`).
```

- [ ] **Step 3: Replace PM Rule 9 body with spec §5.2**

Replace the entire Rule 9 paragraph with:

```markdown
9. **Validation-gated chain merge (Mike directive, 2026-05-08; REWRITTEN 2026-05-28 per CIO directive #1 + spec 2026-05-28).** `main` = "fully validated stable" -- untouched between chain merges. `dev` = integration branch carrying the active V0.X.Y chain (V0.X.0 minor sprint + V0.X.1..V0.X.N patch sprints stacked). Validation drills target `dev`. `/sprint-validated` stamps per-sprint `validation.validatedAt` + bumps `regression_manifest` for the sprint's `validatesFeatures` (no merge -- sprint already in dev). When the whole V0.X.Y chain is drill-green per IRL hardware tests AND CIO confirms, `/chain-validated` merges `dev` -> `main` (`--no-ff`), tags V0.X.N on `main`, fast-forwards `dev` to match `main`, pushes everything. If a drill reveals regression: new patch sprint forks from `dev` -> fix -> merge to `dev` via `/sprint-deploy-pm` with V0.X.(Y+1) patch bump -> retry validation. Loop until validated. **Source of truth**: `regression_manifest.json` (features list), `sprint.json validation` block (per-sprint criteria; required Sprint 28+ per `sprint_lint.lintSprintValidation`).
```

- [ ] **Step 4: Bump the Last Updated header**

In the projectManager.md header `**Last Updated**:` line, prepend a new entry:

```
**Last Updated**: 2026-05-28 (Session 44 -- **dev/main branching workflow LANDED** per CIO directive #1. PM Rules 8 + 9 rewritten; `/sprint-deploy-pm` + `/sprint-validated` + `/chain-validated` skills retargeted to dev/main two-tier; `dev` branch bootstrapped from main; pm_status.py shows both tips. Spec at `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`; plan at `docs/superpowers/plans/2026-05-28-dev-main-branching-workflow.md`. Previous Last Updated below preserved:) [...existing text...]
```

- [ ] **Step 5: Commit Task 7**

```bash
cd Z:/o/OBD2v2
git add offices/pm/projectManager.md
git commit -m "docs(pm): rewrite PM Rules 8 + 9 for dev/main two-tier workflow

Per spec 2026-05-28 + CIO directive 2026-05-23 #1.
PM Rule 10 (design-gate DoD) unchanged.
Last Updated header bumped for Session 44 landing."
```

---

## Task 8: Bootstrap — create `dev` branch from `main`

**Files:**
- Git op only (no file diff)

Reference: spec §7.

- [ ] **Step 1: Confirm we're on main with clean working tree**

```bash
cd Z:/o/OBD2v2
git branch --show-current     # MUST be: main
git status --short            # MUST be: clean (modulo settings.local.json drift per skill rule)
git pull origin main          # confirm main is at expected tip
```

If branch is not main or working tree has unexpected changes, abort and reconcile first.

- [ ] **Step 2: Create dev branch + push to origin**

```bash
cd Z:/o/OBD2v2
git checkout -b dev
git push -u origin dev
```

Expected output: "Branch 'dev' set up to track remote branch 'dev' from 'origin'."

- [ ] **Step 3: Verify origin/dev exists**

```bash
cd Z:/o/OBD2v2
git ls-remote origin dev      # MUST return one line: <hash> refs/heads/dev
```

Expected: one line with the same hash as `main`'s HEAD.

- [ ] **Step 4: Return to main (PM works on main when no sprint active)**

```bash
cd Z:/o/OBD2v2
git checkout main
```

- [ ] **Step 5: Run pm_status.py to verify dev now appears**

```bash
cd Z:/o/OBD2v2
python offices/pm/scripts/pm_status.py | head -10
```

Expected:
```
=== BRANCHES ===
  main: V0.27.19 / <hash>
  dev:  V0.27.19 / <same hash> (= main; ready for next chain)
```

(No file commit step — bootstrap is a git op, not a file change. The branch existence is its own artifact.)

---

## Task 9: Mark agenda directive #1 as DONE

**Files:**
- Modify: `Z:/o/OBD2v2/offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md`

- [ ] **Step 1: Read current agenda doc**

Run: `Read Z:/o/OBD2v2/offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md`.

- [ ] **Step 2: Mark §1 as DONE**

At the top of section "## 1. New branching workflow: main = production; dev = integration", insert:

```markdown
**STATUS**: DONE 2026-05-28 -- spec committed `b277f8b`; implementation landed per `docs/superpowers/plans/2026-05-28-dev-main-branching-workflow.md`. PM Rules 8 + 9 rewritten; three skills retargeted; `dev` branch bootstrapped from main. `pm_status.py` now shows both branch tips.
```

- [ ] **Step 3: Update Sequencing list (bottom of agenda doc)**

In the "## Sequencing (post-chain-merge order)" section, mark item 2 as DONE:

```markdown
2. **Item 1** [DONE 2026-05-28]: dev branch created from main; PM Rule 8 + Rule 9 rewritten; skill updates land in `.claude/commands/`
```

- [ ] **Step 4: Commit Task 9**

```bash
cd Z:/o/OBD2v2
git add offices/pm/knowledge/v0.28.0-grooming-agenda-cio-2026-05-23-directives.md
git commit -m "docs(pm): mark CIO directive #1 (dev/main branching) DONE in V0.28.0 agenda"
```

---

## Task 10: Update MEMORY.md Standing CIO directives + Current State pointer

**Files:**
- Modify: `C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`

- [ ] **Step 1: Read current MEMORY.md**

Run: `Read C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md`.

- [ ] **Step 2: Add Standing CIO directive entry**

In the "## Standing CIO directives (preserved)" section, append:

```markdown
- **Branching workflow (CIO directive 2026-05-23 #1; landed 2026-05-28):** `main` = fully validated stable (untouched between chain merges); `dev` = integration branch carrying the active V0.X.Y chain; sprint branches fork from `dev`, merge back to `dev` on code-complete via `/sprint-deploy-pm` Phase 3.5. Deploy + IRL validation target `dev`. `/sprint-validated` stamps per-sprint validation on dev (no merge). `/chain-validated` merges dev → main + tags + fast-forwards dev. Spec at `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`.
```

- [ ] **Step 3: Update Current State pointer**

Update the "## Current state pointer" line to reflect Session 44 landing:

```markdown
## Current state pointer (2026-05-28 Session 44 -- dev/main branching LANDED on main; dev bootstrapped; V0.28.0 Sprint 1 prep continues with directive #2)
```

(Leave the rest of the Current state block — backlog v2 + V0.27 chain status — as-is below.)

- [ ] **Step 4: Commit Task 10**

```bash
cd Z:/o/OBD2v2
git add "C:\Users\mcorn\.claude\projects\Z--o-OBD2v2\memory\MEMORY.md"
git commit -m "memory: add dev/main branching standing CIO directive; bump Current State pointer for Session 44"
```

(MEMORY.md is auto-memory under `~/.claude/projects/`; it's not part of the OBD2v2 git repo. The commit step is a no-op for OBD2v2 repo but a saved-to-disk artifact for the auto-memory system. Skip the `git add`/`git commit` if MEMORY.md is outside the repo's git tracking — the edit alone is sufficient.)

- [ ] **Step 5: Verify MEMORY.md is well-formed**

Quick check via `head -50` that the edit didn't corrupt frontmatter or break the structure. Edit alone is the artifact.

---

## Task 11: Final integration verification + push

**Files:**
- No file changes — verification + push only.

- [ ] **Step 1: Full pm test suite green**

```bash
cd Z:/o/OBD2v2
python -m pytest tests/pm/ -v
```

Expected: 51+ pass, 0 fail.

- [ ] **Step 2: pm_status.py renders cleanly with dev tip**

```bash
cd Z:/o/OBD2v2
python offices/pm/scripts/pm_status.py | head -20
```

Expected: `=== BRANCHES ===` block with both main + dev (showing dev = main / ready for next chain), then backlog tree.

- [ ] **Step 3: sprint_lint green**

```bash
cd Z:/o/OBD2v2
python offices/pm/scripts/sprint_lint.py
```

Expected: 0 errors (existing accepted warnings OK).

- [ ] **Step 4: Push main**

```bash
cd Z:/o/OBD2v2
git push origin main
```

Expected: main + all Task commits land on origin/main.

- [ ] **Step 5: Verify origin/dev exists and matches main**

```bash
cd Z:/o/OBD2v2
git ls-remote origin main dev
```

Expected: two lines, both with the SAME hash (since dev was created from main and no commits happened on dev since bootstrap).

- [ ] **Step 6: Run git log on main**

```bash
cd Z:/o/OBD2v2
git log --oneline -10 main
```

Expected: top entries are this plan's commits (Task 1, 2, 3, 6, 7, 9, 10 commits), then `b277f8b` (spec), then `d31cece` (Session 43 closeout).

---

## Self-Review

### Spec coverage check (against `docs/superpowers/specs/2026-05-28-dev-main-branching-workflow-design.md`)

- §2 Branch shape → Task 8 (bootstrap creates the missing `dev` branch). ✓
- §3 Per-sprint flow → Task 4 implements steps 3+5 in `/sprint-deploy-pm`; Task 5 implements step 5 in `/sprint-validated`. ✓
- §4 Chain close → Task 6 implements step 7 in `/chain-validated`. ✓
- §5.1 PM Rule 8 → Task 7 step 2. ✓
- §5.2 PM Rule 9 → Task 7 step 3. ✓
- §5.3 PM Rule 10 unchanged → no task needed. ✓
- §6.1 `/sprint-deploy-pm` deltas → Task 4 steps 2–9. ✓
- §6.2 `/sprint-validated` deltas → Task 5 steps 2–6. ✓
- §6.3 `/chain-validated` deltas → Task 6 steps 2–6. ✓
- §7 Bootstrap → Task 8. ✓
- §8.1 Concurrent grooming — judgement guidance; no code task. ✓ (documented in projectManager.md via Rule 8 prose; covered)
- §8.2 SEV-1 hotfix escape hatch — no skill scaffolding per non-goals. ✓
- §8.3 regression_manifest semantics — no code change; documented in PM Rule 9. ✓
- §8.4 + §8.5 — no code change required. ✓
- §9 Script impacts → `pm_status.py` covered by Tasks 1–3; others marked "no change required" → no task needed. ✓
- §10 Non-goals — confirmed; nothing slipped in. ✓
- §11 Cross-references — Task 9 updates the agenda doc; Task 10 updates MEMORY.md. ✓
- §12 Open questions deferred — no task; deferred per spec. ✓

### Placeholder scan

No "TBD", "TODO", "fill in later", or "similar to Task N" patterns. Each step has either exact code or exact bash. ✓

### Type / name consistency

- `formatBranchTips(mainHash, mainVersion, devHash, devVersion)` — same signature in Task 1 test + impl + Task 3 wiring. ✓
- `getBranchTip(branchName) -> tuple[str | None, str | None]` — same in Task 2 test + impl + Task 3 wiring. ✓
- `printBranchSummary()` — defined in Task 3, no other reference. ✓
- Skill name references: `/sprint-deploy-pm`, `/sprint-validated`, `/chain-validated` — consistent across Tasks 4–6. ✓
- File path: `Z:/o/OBD2v2/...` absolute paths used consistently. ✓

---

## Execution handoff notes

- Tasks 1–3 (`pm_status.py` TDD) are independent of tasks 4–6 (skill body edits). Could parallelize via subagent dispatch if desired, but tasks 4–6 share a single commit and must execute sequentially to stay clean.
- Task 7 (PM rule rewrites) and Task 9 (agenda doc) are independent of everything; can land any time before Task 11.
- Task 8 (bootstrap) MUST run after Tasks 4–6 (skills retargeted) and Task 7 (rules rewritten) — otherwise `dev` exists but rituals still target main. Bootstrap-too-early = inconsistent state for whoever starts the next sprint.
- Task 11 (final verify + push) MUST be last.
- Total commits: 7 (Tasks 1, 2, 3, 6, 7, 9, 10). Task 10 may be a no-op for OBD2v2 git if MEMORY.md lives outside the repo.

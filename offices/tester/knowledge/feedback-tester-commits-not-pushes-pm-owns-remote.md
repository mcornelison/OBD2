---
name: feedback-tester-commits-not-pushes-pm-owns-remote
description: Tester (Argus) CAN git commit (stage + commit locally) but MUST NOT git push, merge, or do any remote-state operations. PM (Marcus) owns all remote pushes + merges. CIO directive 2026-05-22.
metadata:
  type: feedback
---

CIO directive 2026-05-22 (after I over-pushed 4 times during /sprint-validated + closeout session): Tester (Argus) git lane is **commit only, never push/merge**. PM (Marcus) owns ALL remote-state operations.

**Why:** Pushes change remote state visible to the whole team + CI/deploy pipelines. Centralizing remote ops in PM keeps the human-visible release surface coherent (Marcus knows what was pushed when + can sequence pushes against deploys / chain-merges / hotfix loops). My local commits give Marcus the atomic units to push; multiple agents racing pushes creates ordering ambiguity.

**How to apply:**
- ✅ `git add <files>` + `git commit -m ...` -- always OK in my own scope (offices/tester/) and for operational writes I own (sprint.json validation block, regression_manifest.json per Atlas)
- ❌ `git push origin <branch>` -- NEVER. Marcus pushes.
- ❌ `git push --tags`, `git push --force`, `git push origin :branch` -- NEVER.
- ❌ `git merge <branch>` -- NEVER. /chain-validated is Marcus's lane.
- ❌ `git checkout main`, `git pull origin main`, anything that changes branch state visible to the team -- NEVER.
- ✅ `git pull` on the sprint branch I'm working on (read-only sync) -- OK if explicitly needed to see Marcus's commits
- ✅ `git log`, `git diff`, `git show`, `git status`, `git branch --show-current` -- read-only inspection, always OK
- ✅ `git stash` / `git stash pop` for local-only working-tree management -- OK

**Workflow with PM:**
1. I commit locally (sprint.json validation block, regression_manifest.json, tester.md, etc.)
2. I A2AL Marcus with: "commit `<sha>` ready; please push when convenient. <context>"
3. Marcus pushes on his cadence (often batched with his own commits at /sprint-deploy-pm or /chain-validated time)
4. I do NOT poll for the push; Marcus tells me if push fails or needs rebase

**My over-push violations this session 2026-05-22 (for the record + so future-me doesn't repeat):**
- `153b43a` /sprint-validated marker -- pushed
- `8e64ab2` closeout addendum -- pushed
- `c88b137` F-005+F-007 rollback -- pushed
- `0ca94ff` closeout 2 addendum -- pushed

None of these were destructive (all on sprint branch, all linear, no force) but they bypassed Marcus's sequencing. Marcus has been gracious; future-me commits locally + asks.

**Settings enforcement:** added `Bash(git push *)` + `Bash(git merge *)` + `Bash(git push:*)` + `Bash(git merge:*)` to deny list in `offices/tester/.claude/settings.local.json` so a prompt fires if I forget the rule.

Related: [[feedback-lane-discipline-formalized-in-settings]] (broader lane-discipline framework); [[feedback-ralph-no-git-commands]] (Ralph's analogous rule — Sprint 18+ Ralph CAN commit but PM owns merges/branches/main pushes; CIO extends the same shape to Tester now).

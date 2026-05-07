---
name: sprint-close-pm
description: "Sprint-close ritual for Marcus (PM). Validates sprint complete; archives sprint.json + progress.txt with timestamp; bumps status fields; merges to main; bumps RELEASE_VERSION; deploys Pi + server. Run after Ralph finishes a sprint when CIO directs sprint-close + deploy. NEVER run mid-sprint while Ralph is working."
---

# Sprint Close (PM-driven)

End-of-sprint ritual for Marcus (PM). Codifies the workflow refined across Sprint 14/21/22/23/24 closes + V0.24.1 hotfix. Replaces the prior ad-hoc "13-step manual sequence."

**WHEN to run**: CIO explicitly directs sprint-close + deploy after Ralph finishes a sprint (all stories `passes:true`).

**WHEN NOT to run**: mid-sprint (Ralph still iterating); during a hotfix that doesn't follow the sprint-branch pattern; when sprint contract has unresolved blockers (BL-XXX active).

**Authority**: This is high-blast-radius (pushes to main + remote deploys to Pi + server). Per system prompt, must have explicit CIO authorization. Treat the user's directive as scope-bounded — don't expand beyond the stated sprint.

---

## Phase 0 — Pre-flight gates (HALT-EARLY)

Before touching anything, verify state:

```bash
cd $REPO_ROOT
git status --short                                   # working tree clean except known noise
git branch --show-current                            # MUST be the sprint/* branch
python offices/pm/scripts/pm_status.py | head -25    # confirm 5+ stories all passes:true
python offices/pm/scripts/sprint_lint.py             # MUST be 0 errors
```

**Stop conditions** — abort + report to CIO if:
- Branch is `main` (sprint-close runs FROM the sprint branch, not main)
- Any story has `passes: false` AND `status: pending` (sprint not actually done)
- `sprint_lint.py` shows errors (US-274 phantom-path or US-282 commit-vs-claim drift — fix first)
- Working tree has unexpected modifications (settings drift OK; src/ tests/ scripts/ deploy/ NOT OK without explanation)

If `sprint_lint.py --check-feedback` (US-282 commit-vs-claim verifier) flags any `feedback claim missing from commits`, **HALT** and execute the rescue-commit pattern (mirror commit `096dade` Sprint 22 / `6d8af99` Sprint 23): `git add` the missing working-tree files + commit with message `feat: [US-XXX] rescue Sprint N work uncommitted on disk`. Then re-run Phase 0.

---

## Phase 1 — Status field hygiene

Ralph's standing hygiene gap: stories with `passes: true` may still have `status: pending`. PM bumps to `passed`.

```python
import json
p = 'offices/ralph/sprint.json'
d = json.load(open(p, encoding='utf-8'))
bumped = []
for s in d['stories']:
    if s.get('passes') is True and s.get('status') == 'pending':
        s['status'] = 'passed'
        bumped.append(s['id'])
with open(p, 'w', encoding='utf-8', newline='\n') as f:
    json.dump(d, f, indent=2, ensure_ascii=False)
    f.write('\n')
print(f'Bumped pending->passed: {bumped}')
```

Re-run `sprint_lint.py` post-bump. Must still be 0 errors.

---

## Phase 2 — Archive sprint.json + progress.txt with timestamp

Preserve the as-shipped sprint contract + Ralph's session log for historical reference. Convention:

- **Filenames**: `sprint.archive.YYYY-MM-DD_HHMMSSZ.json` and `progress.archive.YYYY-MM-DD_HHMMSSZ.txt`
- **Location**: `offices/ralph/archive/` (existing flat-archive pattern; do NOT use legacy nested-dir pattern)
- **Timestamp**: UTC; filesystem-safe (no colons; underscore between date + time; trailing `Z` for UTC marker)

```bash
TS=$(python -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M%SZ'))")
SPRINT_NAME=$(python -c "import json; print(json.load(open('offices/ralph/sprint.json',encoding='utf-8'))['sprint'].split('--')[0].strip().replace(' ','-').lower())")
echo "Archive timestamp: $TS"
echo "Sprint name: $SPRINT_NAME"

cp offices/ralph/sprint.json "offices/ralph/archive/sprint.archive.${TS}.json"
cp offices/ralph/progress.txt "offices/ralph/archive/progress.archive.${TS}.txt"
ls -la "offices/ralph/archive/sprint.archive.${TS}.json" "offices/ralph/archive/progress.archive.${TS}.txt"
```

**Note**: `cp` not `mv` — sprint.json + progress.txt stay in place for the sprint-close commit + the next sprint's grooming. Archive is a snapshot, not a move.

**Stop condition**: if archive files already exist for that exact timestamp (re-run within 1 sec), abort + investigate (likely accidental double-run).

---

## Phase 3 — Update PM artifacts

Three files to update before commit:

### 3a — `offices/pm/backlog.json`

Bump the active B-XXX phase entry from `in_progress` → `complete`. Add `completedDate` + summary of what shipped.

```python
import json
p = 'offices/pm/backlog.json'
d = json.load(open(p, encoding='utf-8'))
# Find the B-XXX phase that matches the current sprint
# (typically B-043 phases.<phase-name> for power-mgmt sprints; B-037 for Pi pipeline)
# Edit by hand based on which phase the sprint targeted
# Set: status: complete, completedDate: YYYY-MM-DD, note: <one-paragraph summary>
```

Edit by hand if multiple B-XXX phases were touched (e.g., Sprint 25 hit B-037 + B-043 both).

### 3b — `MEMORY.md` (auto-memory at user-dir, not in repo)

Rewrite the "Current State" section header + first paragraph to reflect SHIPPED state. Move prior-state content into a "Prior State" subsection. Add new "Sprint X stories shipped" section. Cross-reference any TDs closed.

### 3c — `offices/pm/projectManager.md`

Update **Last Updated** header line + **Current Phase** descriptor. Insert new Session narrative at top of "Last Session Summary" section (preserve prior session's narrative one level down via heading promotion).

Session narrative shape (~30-50 lines):
- What was accomplished (bullet list of stories shipped + key fixes)
- Key decisions (with rationale)
- Key artifacts produced (commit hashes + file paths)
- What's next (concrete pickup items for next session)
- Post-session git state (main HEAD, branch state)

---

## Phase 4 — Sprint-close commit + push branch

Stage ALL relevant files together (sprint-close exception to PM Rule 8 dev-only-domain):

```bash
git add offices/ralph/sprint.json offices/ralph/progress.txt offices/ralph/archive/sprint.archive.${TS}.json offices/ralph/archive/progress.archive.${TS}.txt offices/pm/backlog.json offices/pm/projectManager.md offices/pm/story_counter.json
# Plus any other PM-touched files this session (spec docs, action-items.md, sprint_26_candidates.md, etc.)
git status --short  # verify no unintended staged files

git commit -m "$(cat <<'EOF'
feat(sprint-N): <Sprint Name> SHIPPED N/N

[Session narrative — 30-50 lines covering what shipped, key decisions,
artifact list, drain/drive verdicts if relevant, anti-blocker discipline
notes]

sprint_lint clean: 0 errors, 0 warnings.

Sprint archive: offices/ralph/archive/sprint.archive.${TS}.json
Progress archive: offices/ralph/archive/progress.archive.${TS}.txt

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"

git push origin sprint/sprintN-<phase-name>
```

---

## Phase 5 — Merge to main + push main

```bash
git checkout main
git pull origin main                     # confirm main is at expected base
git merge --no-ff sprint/sprintN-<phase-name> -m "Merge sprint/sprintN-<phase-name>: Sprint N (<Sprint Name>) SHIPPED N/N"
git push origin main
git log --oneline -3 main                # confirm merge landed
```

**Stop condition**: if `git pull` fast-forwards main beyond expected base, the world has moved (CIO landed a hotfix). Investigate before merging.

---

## Phase 6 — RELEASE_VERSION bump

Separate `chore(release):` commit per `feedback_pm_sprint_close_version_bump.md`. Decide MINOR vs PATCH per SemVer:
- **MINOR** (V0.X.0 → V0.X+1.0): new feature surface area / new tests / new instrumentation
- **PATCH** (V0.X.Y → V0.X.Y+1): bug fixes, hygiene closures, no new code paths visible to consumers

```python
# deploy/RELEASE_VERSION shape:
# {"version": "V0.X.Y", "theme": "<Sprint Name>", "description": "<Sprint summary 1-3 sentences>"}
# CRITICAL: description MUST be ≤400 chars (US-241 validator; TD-040 lesson — Sprint 22+23+24 all hit this on first try)
```

```bash
# After writing the new RELEASE_VERSION:
python -c "import json; d=json.load(open('deploy/RELEASE_VERSION',encoding='utf-8')); print(f'description: {len(d[\"description\"])} chars (cap 400)')"
# If >400, trim and re-check before commit
git add deploy/RELEASE_VERSION
git commit -m "chore(release): bump V0.X.Y -> V0.X+1.0 (Sprint N close)"
git push origin main
```

---

## Phase 7 — Deploy Pi + server (parallel background)

```bash
bash deploy/deploy-pi.sh      # run_in_background; ~1-3 min on warm cache, ~5-10 min cold
bash deploy/deploy-server.sh  # run_in_background; ~30 sec
```

Server deploy is unattended via `/etc/sudoers.d/obd2-deploy` (Sprint 22 fix). Pi deploy uses tar-over-ssh fallback (rsync install on Windows MINGW64 is an optional CIO speedup; never blocking).

Wait for both background-task notifications before proceeding to Phase 8.

---

## Phase 8 — Verify both targets running new version

```bash
ssh mcornelison@10.27.27.28 "cat /home/mcornelison/Projects/Eclipse-01/.deploy-version"
ssh mcornelison@chi-srv-01 "cat /mnt/projects/O/OBD2v2/.deploy-version && systemctl is-active obd-server.service"
```

Both should show:
- New version + new gitHash (matching post-bump main HEAD)
- Service active
- Server health check 200 OK

**Stop condition**: if either target's `.deploy-version` still shows the OLD version, deploy ran but service didn't restart (Sprint 22 hidden-bug pattern). Investigate before reporting sprint-close complete.

---

## Phase 9 — Final summary

Single concise message to CIO covering:

| Step | Result |
|---|---|
| Sprint validation | N/N SHIPPED (US-XXX through US-XXX) |
| sprint_lint | 0 errors / 0 warnings |
| Archives written | `sprint.archive.${TS}.json` + `progress.archive.${TS}.txt` |
| Sprint-close commit | `<short-hash>` |
| Merge to main | `<merge-hash>` |
| RELEASE_VERSION | V0.X.Y → V0.X+1.0 |
| Pi deploy | V0.X+1.0 active on chi-eclipse-01 |
| Server deploy | V0.X+1.0 active on chi-srv-01 (unattended) |

Plus any **post-sprint action items** for CIO (drain tests, drive validations, manual data cleanup) per the sprint's `sprintNotes` POST-SPRINT block.

Plus any **next-sprint candidates** queued (B-XXX PRDs that became sprint-ready this sprint, items in `offices/pm/sprint_N+1_candidates.md`, etc.).

---

## Stop-condition flowchart (consolidated)

| Phase | Stop condition | Action |
|---|---|---|
| 0 | Branch is main | Abort; sprint-close runs FROM sprint branch |
| 0 | Any story `passes:false` + `status:pending` | Abort; sprint not done |
| 0 | `sprint_lint.py` errors | Fix per error; re-run |
| 0 | `--check-feedback` flags missing files | Run rescue-commit pattern; re-run Phase 0 |
| 0 | Unexpected working-tree modifications outside `.claude/settings.local.json` | Investigate; do NOT auto-stage |
| 2 | Archive timestamp collision | Abort; investigate accidental double-run |
| 5 | `git pull` fast-forwards beyond expected base | CIO landed a hotfix; investigate before merge |
| 6 | RELEASE_VERSION description >400 chars | Trim before commit (TD-040 lesson) |
| 8 | Either target shows old version post-deploy | Sprint 22 hidden-bug pattern; investigate before reporting close |

---

## Why this exists

The sprint-close ritual was done ad-hoc 5+ times (Sprint 14, 21, 22, 23, 24, V0.24.1) with the same 13-step manual sequence. Sprint 26 next-actions list flagged the missing skill in projectManager.md ("Build `sprint-close-pm.md` skill — Session 25 sprint-close was done ad-hoc..."). This command codifies the ritual + adds the per-CIO-2026-05-05 timestamped archive of sprint.json + progress.txt that prior ad-hoc closes didn't include.

## Related

- `closeout-pm` (existing) — END-OF-SESSION ritual; explicitly NEVER merges. Used most days.
- `closeout-session-pm` — Smaller per-session handoff variant.
- `feedback_pm_sprint_close_version_bump.md` — RELEASE_VERSION bump rule reference.
- `feedback_chi_srv_01_sudo_dash_S.md` — superseded for deploy-server.sh by Sprint 22 sudoers fix.
- US-274 (Sprint 23) `sprint_lint.py` file-existence check — runs at Phase 0.
- US-282 (Sprint 24) `sprint_lint.py --check-feedback` commit-vs-claim verifier — runs at Phase 0.

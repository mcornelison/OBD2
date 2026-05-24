# Sprint Turnover

You are acting as the **Expert Project Manager** for the DataWarehouse ETL project. Ralph has finished a sprint and you need to turn it over: archive the completed work, check for new inputs, and groom the backlog for the next sprint.

**CRITICAL: Execute phases in order. Do NOT skip or reorder. Each phase depends on the previous one.**

---

## Phase 1: Verify Ralph is Done

Read `offices/ralph/sprint.json` and `offices/ralph/progress.txt` in parallel.

**Gate check on prd.json:**
- If ALL stories have `"passes": true` or `"passes": false` (none are `null`) -> Sprint is complete, proceed
- If ANY stories still have `"passes": null` -> Sprint is NOT complete. Tell the user: "Sprint is still in progress -- [X/Y] stories have results. Run `/ralph-status` for details." **STOP HERE.**
- If `offices/ralph/sprint.json` is empty or has no userStories -> Nothing to archive. Tell the user: "No active sprint found." **STOP HERE.**

Present a quick summary:
```
Sprint: [branch name]
Stories: X passed, Y failed out of Z total
```

---

## Phase 2: Capture Lessons Learned

### 2a. Load Sources

Read the following in parallel:
- `offices/ralph/progress.txt` - Developer execution notes (full file)
- `offices/pm/lessons-learned.md` - Existing lessons (to avoid duplicates)
- `git log --oneline -20` - Recent commits

### 2b. Identify Learnings

From `progress.txt` "Learnings for future iterations" sections, identify:
- **New patterns** that worked well
- **Anti-patterns** or gotchas to avoid
- **Process improvements** discovered

Cross-check each against existing content in `offices/pm/lessons-learned.md` -- **no duplicates**.

### 2c. Apply Updates

If new learnings found:
- Add numbered lessons to "What Works Well" or "What Doesn't Work" sections (next sequential number)
- Add entries to "Patterns Quick Reference" table if applicable
- Show the user what was added

If no new learnings: Say "No new learnings identified" and move on. Do NOT fabricate learnings.

---

## Phase 3: Archive Sprint

### 3a. Create Archive

```bash
mkdir -p offices/pm/completed_sprints/YYYY-MM-DD-feature-name/
cp offices/ralph/sprint.json offices/pm/completed_sprints/YYYY-MM-DD-feature-name/prd.json
cp offices/ralph/progress.txt offices/pm/completed_sprints/YYYY-MM-DD-feature-name/progress.txt
```

Use today's date and the feature name from `prd.json` (without `offices/ralph/` prefix) for the folder name.

### 3b. Update Story Counter

Read `offices/pm/story_counter.json` and add a history entry with outcome:
```json
{
  "feature": "ralph/branch-name",
  "range": "US-XXX to US-YYY",
  "date": "YYYY-MM-DD",
  "outcome": "X/Y passed - brief summary of what was accomplished"
}
```

### 3c. Update Reference Files

- Read `offices/pm/reference/completed-prds.md` and add a row with sprint date, name, branch, story count, pass rate, and key outcome
- If new architecture decisions were made during the sprint, read `offices/pm/reference/decision-log.md` and add entries

### 3d. Update Backlog

Read `offices/pm/backlog.json` and:
- Set `metadata.currentSprint` to `null`
- Update `metadata.lastArchived` to the sprint name
- Mark any backlog items completed by this sprint's stories (check story descriptions for B-xxx references)
- Update notes on any partially addressed items

### 3e. Clear Ralph Working Files

- Write empty object `{}` to `offices/ralph/sprint.json`
- Write empty string to `offices/ralph/progress.txt`

### 3f. Update PM Context

Update `offices/pm/pm-context.md` with current state so the next `/init-pm` session starts with accurate context:
- **Last Updated** date and source
- **Active Sprint** set to null
- **Last 3 Sprints** table (add just-archived sprint, remove oldest)
- **Top Open Backlog Items** (refresh from backlog.json changes)
- **Active Risks & Blockers** (update based on completed work)

### 3g. Confirm Archive

Show the user:
```
Sprint archived to: offices/pm/completed_sprints/YYYY-MM-DD-feature-name/
Stories: X/Y passed
Backlog items completed: [list or "none"]
offices/ralph/ working files cleared.
```

---

## Phase 4: Read Inbox

### 4a. Check for New Messages

List files in `offices/pm/inbox/` (exclude `offices/pm/inbox/archive/`).

- If inbox is empty: Say "Inbox is empty -- no new messages from agents." Move to Phase 5.
- If files found: Read each file and present a summary:

```
## Inbox: [N] messages

1. **[filename]** - [1-2 sentence summary of what the agent is reporting]
2. ...
```

### 4b. Triage Inbox Items

For each inbox message, determine if it:
- Creates a **new backlog item** (add B-xxx to `offices/pm/backlog.json`)
- Updates an **existing backlog item** (update notes/status)
- Is **informational only** (no action needed)
- Requires **Mike's attention** (flag as mike-todo)

Present the triage recommendations to the user. Apply after approval.

**Do NOT archive inbox files** -- that's Mike's responsibility after he's reviewed them.

---

## Phase 5: Groom Backlog for Next Sprint

### 5a. Analyze Open Items

Read `offices/pm/backlog.json` and categorize open items by priority:

**Tier 1 - High Priority** (blocks other work or addresses active issues)
**Tier 2 - Medium Priority** (important improvements, tech debt)
**Tier 3 - Low Priority** (nice-to-have, future planning)

### 5b. Check for Sprint Prerequisites

Read `offices/pm/inbox/` findings and `offices/QA/findings/` for any items that should influence sprint selection:
- Tester-reported issues needing fixes
- DW Architect recommendations
- Failed stories rolled from previous sprints

### 5c. Present Sprint Options

Recommend 2-4 sprint options, each with:
- **Sprint name** and focus area
- **Backlog items** it would address (B-xxx references)
- **Estimated stories** (target: 7-12 stories per sprint)
- **Risk level** (doc-only = low, code changes = medium, architecture = high)
- **Why now** (rationale for prioritizing this sprint)

Mark the recommended option with "(Recommended)" and list it first.

```
## Next Sprint Options

### Option A: [Name] (Recommended)
- **Items**: B-xxx, B-yyy, B-zzz
- **Est. Stories**: ~N
- **Risk**: [low/medium/high]
- **Why now**: [rationale]

### Option B: [Name]
...
```

### 5d. Wait for User Decision

Ask the user which sprint option they'd like to pursue. Once selected, inform them:
```
Ready to create PRD. Run `/groom-product-requirements` to generate the PRD for [selected sprint].
```

**Do NOT auto-create the PRD** -- the user will invoke the PRD command separately.

---

## Edge Cases

### Sprint has failures (passes: false stories)
- Still archive (failures are valid outcomes)
- Note failed stories in the outcome summary
- Check if failed stories should become new backlog items (B-xxx "Rolled from US-YYY")
- Mention rollover items during Phase 5 grooming

### Inbox has urgent items
- If any inbox message flags a production issue or data loss, call it out prominently before grooming
- Urgent items should be prioritized in sprint recommendations

### No open backlog items
- If backlog is empty after archiving, say so
- Suggest the user check with stakeholders for new requirements
- Consider suggesting a documentation, testing, or tech debt sprint

### Multiple sprints completed since last turnover
- Only the current `offices/ralph/sprint.json` gets archived
- Previous sprints should already be archived; if not, warn the user

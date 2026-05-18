---
name: resize-sprint
description: "PM final sizing review -- the last of 4 sign-offs before Ralph executes. Sizes each story, splits oversized ones into sub-stories with zero information loss, ensures sprint fits within 60% of developer context memory, records PM final sizing sign-off, moves approved PRD to offices/ralph/sprint.json. Triggers on: kunai is finished, resize sprint, sizing review, ready for ralph, approve sprint."
---

# PM Final Sizing Review

Run this command after the DW Architect and Tester (QA) have both reviewed and signed off on `offices/pm/prd.json`. This is the **4th and final gate** before Ralph executes the sprint.

**Sign-off sequence (all 4 required):**
1. PM Initial Review (`/groom-user-stories`) -- PRD created, pre-flight done
2. DW Architect Review (Kunai) -- technical accuracy, annotations
3. QA Review (Tester) -- testability, acceptance criteria quality
4. **PM Final Sizing** (this command) -- story sizing, splitting, handoff to Ralph

---

## Why This Matters

Ralph is a junior developer agent. His context window is his working memory. When stories are too big, his context compresses mid-story, and **compression causes hallucinations** -- he forgets AC items, invents API patterns, or breaks things that were working. This command prevents that by:

1. **Sizing each individual story** against concrete metrics (files, concerns, AC count)
2. **Splitting oversized stories** into sub-stories -- preserving ALL information
3. Ensuring the total sprint fits within ~60% of developer context memory
4. Making each story self-contained with all the pointers Ralph needs

**You NEVER write code.** You are optimizing the sprint document for developer consumption.

**THE PROMISE: Splitting stories NEVER loses information.** Every AC, note, example, reference file, and doNoHarm item from a parent story must appear in exactly one sub-story. This is verified in Step 5.

---

## Before Starting

1. Read `offices/pm/pm-context.md` for current project state
2. Read `offices/pm/prd.json` in full
3. Read `offices/ralph/sprint.json` if it exists -- verify no active sprint
4. Read the referenced spec files to understand what Ralph will need
5. Read the last 50 lines of `offices/ralph/progress.txt` for calibration -- how long did stories actually take? Which ones caused problems?

---

## The Job

1. **Verify prior sign-offs**: Confirm `signOffs.pmInitialReview`, `signOffs.architectReview`, and `signOffs.qaReview` all have status != `PENDING`. If any are missing, STOP and tell the user which review is still outstanding.
2. Size every story against the 5-dimension matrix (Step 1)
3. Check for splitting triggers (Step 2)
4. Evaluate each story for self-containment (Step 3)
5. Split oversized stories with zero information loss (Steps 4-5)
6. Measure sprint-level budget (Step 6)
7. Add Dev Cheat Sheet (Step 7)
8. Record PM final sizing sign-off
9. **Move** the approved file from `offices/pm/prd.json` to `offices/ralph/sprint.json`
10. Declare the sprint ready for Ralph

---

## Step 1: Size Each Story

For each story in the sprint, measure these dimensions:

| Dimension | Green (OK) | Yellow (Watch) | Red (Must Split) |
|-----------|-----------|---------------|------------------|
| Files modified + created | 1-3 | 4-5 | 6+ |
| Independently testable concerns | 1 | 2 | 3+ |
| Acceptance criteria lines | 3-6 | 7-9 | 10+ |
| Reference files to read | 1-3 | 4-5 | 6+ |
| Notes + examples word count | <300 | 300-500 | 500+ |

**Splitting rules:**
- **2+ Red dimensions** -> MUST split
- **3+ Yellow dimensions** -> SHOULD split (present to owner)
- **Any single Red** -> flag for review, may need splitting depending on context

**How to count "files modified":**
Don't guess -- actually count. Look at the story's AC, examples, and specsDocReference. If examples show code changes in 3 files but the scope covers "all notebooks for a source," the real count is likely 10+. The scope description is the truth, not the examples sample.

**How to count "concerns":**
A concern is an independently testable behavior change. Ask: "Could I verify this works without doing the other parts?" If yes, it's a separate concern. Examples:
- "Add to pipeline JSON" vs. "Regenerate notebooks" = 2 concerns
- "Parse boolean flags" vs. "Extract numeric values" = 2 concerns (but OK together since same entity)
- "Add entity to registry" vs. "Redesign notebook generator pattern" = 2 concerns (split these)

### Exception: Batch Similar Fixes (Rule 5)

Stories that apply the **same mechanical pattern** across many files (e.g., adding 3 Silver notebooks to a pipeline parameter array) may exceed the 1-3 file limit. This is acceptable when:
- Every file gets the **identical** change pattern
- Each individual file change is < 10 lines
- The architect has provided a clear reference pattern
- Total effort is still < 500 lines

Flag these as "sizing exception -- Batch Similar Fixes (Rule 5)" in the review.

---

## Step 2: Check Splitting Triggers

Beyond the metrics table, check for these patterns that always indicate a story needs splitting:

- [ ] **"Add X everywhere"** -> Verify all rendering/execution contexts support X. If some contexts require redesign (e.g., generator doesn't support the notebook pattern), the story is actually TWO stories: one for compatible contexts, one for the redesign.
- [ ] **"Same change across many files"** with >5 files -> Split by file group (max 5 files per sub-story). Group files that share the same modification strategy.
- [ ] **Story uses "AND" between unrelated tasks** -> "Update registry AND redesign generator AND add to pipeline" = likely 2-3 stories.
- [ ] **Mixes data setup + code changes + documentation** -> Always 2-3 stories. These have different risk profiles and verification methods.
- [ ] **Story touches 3+ unrelated files** -> Split by file group.
- [ ] **Can you describe the story without "and"?** If not, it might be 2+ stories.
- [ ] **Does it mix concerns from different layers?** (entity registry, notebook generator, pipeline JSON, deploy script) -> Split by layer.

---

## Step 3: Evaluate Each Story

For each story (or sub-story after splitting), verify:

- [ ] **Self-contained?** Can Ralph understand this story without reading the whole sprint?
- [ ] **Reference files listed?** Every file Ralph needs is explicitly in `specsDocReference` with what to look for.
- [ ] **Acceptance criteria clear?** A junior dev can test each criterion without asking questions.
- [ ] **Definition of done obvious?** Ralph knows exactly when to stop.
- [ ] **No assumed knowledge?** Nothing relies on "Ralph should know this from last time."

For each story, ensure `specsDocReference` includes:
- The **file path** (relative to project root)
- **What to look for** in that file (section name, specific detail, line numbers if known)
- **Why it matters** for this story

---

## Step 4: Split Oversized Stories

When Step 1 or Step 2 flags a story for splitting:

### 4a. Identify Split Boundaries

Choose the pattern that best fits:

**Pattern A: "Same change, many files"**
-> Split by classification group. Group files that share the same modification strategy (max 5 files per sub-story).

Example: Adding canonical notebooks across 15 entity registries:
- Sub-story a: Registry entries for source A entities (5 entries)
- Sub-story b: Registry entries for source B entities (5 entries)
- Sub-story c: Registry entries for source C entities (5 entries)

**Pattern B: "Mixed concerns"**
-> Split by concern type. Each independently testable behavior = separate sub-story.

Example: New entity with registry + generator + pipeline:
- Sub-story a: Entity registry definition + notebook generation
- Sub-story b: Pipeline orchestration integration + deploy manifest
- Sub-story c: Documentation sync

**Pattern C: "Hidden redesign"**
-> Split display from infrastructure. The PM failed to investigate a technical constraint, turning an "add X" story into a redesign story.

Example: Adding a derived entity but the generator doesn't support the pattern:
- Sub-story a: Add entity to registry with column definitions
- Sub-story b: Create new generator function for the pivot/derived pattern
- Sub-story c: Generate notebook and integrate into pipeline

**Pattern D: "Investigation + implementation"**
-> Only combine if the investigation outcome is certain. If the investigation might change the implementation approach, split them.

Example: Validate API fields + build Silver entity:
- Keep as separate stories (US-564 validate, US-566 implement) -- already done correctly in this PRD

### 4b. Create Sub-Stories

Use naming: `US-NNN-a`, `US-NNN-b`, `US-NNN-c` (letter suffix on parent story number).

Each sub-story MUST have its own complete:
- **id** -- `US-NNN-a` format
- **title** -- what this sub-story does (not the parent's full title)
- **description** -- scoped to this sub-story only
- **acceptanceCriteria** -- AC items from the parent that belong to THIS sub-story
- **doNoHarm** -- scoped to this sub-story:
  - `alreadyWorking`: includes anything the PREVIOUS sub-story in the chain built
  - `scopeFence`: TIGHTER than the parent's -- only this sub-story's files/scope
  - `regressionCheck`: what to verify didn't break
- **examples** -- only the implementation hints relevant to THIS sub-story
- **specsDocReference** -- only the files needed for THIS sub-story
- **notes** -- only the context relevant to THIS sub-story
- **dependencies** -- which sub-stories must complete first (e.g., `["US-566-a"]`)

**doNoHarm format:**
```json
"doNoHarm": {
  "alreadyWorking": ["List of things previous sub-stories built that must not break"],
  "scopeFence": ["Only modify these specific files/sections"],
  "regressionCheck": ["Verify these still work after changes"]
}
```

### 4c. Sub-Story Sizing Check

After splitting, re-run Step 1 on each sub-story. If any sub-story is still Yellow/Red, split further. Every sub-story should be Green on all dimensions.

---

## Step 5: Verify Zero Information Loss

**This step is MANDATORY for every split. Do not skip it.**

After splitting a parent story into sub-stories, verify 100% coverage:

```
FOR EACH split parent story:
  [ ] List EVERY acceptance criteria line from the parent
    -> Each must appear in exactly ONE sub-story
    -> None may be dropped or reworded to lose meaning
    -> "ruff check passes" goes on the LAST sub-story in the chain only

  [ ] List EVERY examples entry and code snippet from the parent
    -> Each must appear in the relevant sub-story
    -> Code examples stay with the sub-story that uses them
    -> General warnings go on ALL relevant sub-stories

  [ ] List EVERY specsDocReference from the parent
    -> Each must appear in at least one sub-story
    -> May appear in multiple sub-stories if both need it

  [ ] doNoHarm sections created:
    -> Each sub-story has its OWN doNoHarm appropriate to its narrower scope
    -> Later sub-stories list earlier sub-stories' output in "alreadyWorking"
    -> "scopeFence" is TIGHTER than the parent's

  [ ] Total AC count across all sub-stories >= parent AC count
    -> Sub-stories may ADD clarifying AC but must NEVER remove any
```

**Present the verification as a mapping table to the owner:**

```
Parent Story: US-566 (Silver DocuSign Fee Agreement)
===============================================================
Parent AC Item                                    -> Sub-story
---------------------------------------------------------------
"New Silver entity FeeAgreement in registry"      -> 566-a
"Entity config uses silverTable, runLevel=1"      -> 566-a
"Entity pivots custom fields into typed columns"  -> 566-b
"Columns include envelopeId, clientNumber..."     -> 566-b
"DecimalType columns specify precision/scale"     -> 566-b
"FingerPrintHash computed via D-38"               -> 566-b
"clientNumber joins to Silver_3E_Client.Number"   -> 566-b
"Dedup config: partitionKey=envelopeId"           -> 566-a
"Silver notebook generated and executes"          -> 566-b
"Notebook added to silverRunLevel1Notebooks"      -> 566-b
"Envelopes without fee agreement = no rows"       -> 566-b
"ruff check passes on modified files"             -> 566-b (last)
===============================================================
Coverage: 12/12 AC items mapped    |  0 dropped
```

**If any parent AC item is NOT mapped to a sub-story -> STOP and fix it before proceeding.**

---

## Step 6: Measure Sprint Total

After all story-level splits are done, re-measure the full sprint:

- Count total stories (including sub-stories -- each sub-story counts as 1)
- Target: **5-8 Green-zone stories per sprint** = good sprint
- Hard limit: **10 stories** per sprint max (including sub-stories)
- If over 10, split into two sequential sprints and update `story_counter.json` accordingly

Sprint-level context budget:
- The entire sprint (all stories + cheat sheet) should be digestible in ~60% of context
- Each individual story should target ~20% of context, hard ceiling at 40%

---

## Step 7: Add Dev Cheat Sheet

Add a `devCheatSheet` field to the top level of the sprint JSON:

```json
"devCheatSheet": {
  "readFirst": [
    {"file": "path/to/file", "reason": "one-line reason"},
    {"file": "path/to/file", "reason": "one-line reason"}
  ],
  "keyReminders": [
    "Important pattern or convention",
    "Important constraint from decisions (e.g., D-40: Bronze captures raw only)",
    "Common gotcha from previous sprints"
  ]
}
```

This goes at the top of the JSON so Ralph sees it before any story. Include:
- Files Ralph should skim before starting (shared modules, registries, existing patterns)
- Key decisions in effect (D-25, D-38, D-40, etc.) relevant to this sprint
- Gotchas from previous sprints (from `progress.txt` or `lessons-learned.md`)

---

## Phase E: Record PM Final Sizing Sign-Off

Update only the `pmFinalSizing` entry in the `signOffs` section:

```json
"pmFinalSizing": {
  "reviewer": "Ledger (PM)",
  "reviewDate": "YYYY-MM-DD",
  "status": "APPROVED",
  "notes": "[Summary: N stories, all Green. N splits performed. Sprint fits 60% context budget. Note any sizing exceptions.]"
}
```

**Do NOT overwrite the other 3 sign-offs.** Only update `pmFinalSizing`.

**Legacy PRDs:** If you encounter a PRD that has the old `architectReview` / `pmSizingReview` top-level fields instead of the `signOffs` section, migrate them into the new structure before proceeding.

---

## Phase F: Hand Off to Ralph

**Gate check:** Before moving, verify `offices/ralph/sprint.json` does not already contain an active sprint (stories with `passes: null` or `passes: false` that haven't been attempted). If it does, STOP and warn the user -- Ralph may still be working on a sprint.

If clear:
1. Copy `offices/pm/prd.json` to `offices/ralph/sprint.json`
2. Delete `offices/pm/prd.json` (it now lives in offices/ralph/)
3. Confirm the move was successful

```bash
cp offices/pm/prd.json offices/ralph/sprint.json
rm offices/pm/prd.json
```

---

## Phase G: Declare Ready

Print the final status:

```
## Sprint Approved

**Sprint:** [branch name]
**Stories:** [N] (US-XXX to US-YYY) [+N sub-stories if any splits]
**Sizing:** All stories Green [+ N batch exceptions]
**Context Budget:** [estimated %] of 60% target

**Sign-Offs:**
1. PM Initial Review: APPROVED ([date])
2. DW Architect Review: [status] ([date])
3. QA Review: [status] ([date])
4. PM Final Sizing: APPROVED ([date])

**Handed off:** offices/pm/prd.json -> offices/ralph/sprint.json

Ralph can start:
./offices/ralph/ralph.sh [N]
```

---

## Present Results (Before Writing)

Show the owner BEFORE writing the updated files:

1. **Story sizing table** -- Green/Yellow/Red assessment for each story:
   ```
   US-563: Files=1(G) Concerns=1(G) AC=9(R) Refs=3(G) Notes=180(G) -> Flag: AC Red
   US-564: Files=2(G) Concerns=1(G) AC=8(Y) Refs=3(G) Notes=250(G) -> Watch
   US-565: Files=3(G) Concerns=1(G) AC=7(Y) Refs=2(G) Notes=200(G) -> OK
   ```
2. **Split proposals** -- before/after for any oversized stories
3. **Information loss verification** -- mapping tables for all splits
4. **Before/after story count** -- "Sprint went from 6 stories to 8 sub-stories"
5. **Risk flags** -- any stories that are still borderline
6. **Dev cheat sheet** content
7. **Confirm with owner before writing** the updated sprint file

---

## Checklist

- [ ] **Prior sign-offs verified**: `signOffs.pmInitialReview`, `signOffs.architectReview`, and `signOffs.qaReview` all have non-PENDING status
- [ ] Every story sized against 5-dimension matrix (Step 1)
- [ ] Splitting triggers checked (Step 2)
- [ ] Every story evaluated for self-containment (Step 3)
- [ ] Oversized stories split with sub-story naming (US-NNN-a) (Step 4)
- [ ] Zero information loss verified with mapping tables for every split (Step 5)
- [ ] Sprint total within budget: <=10 stories, ~60% context (Step 6)
- [ ] Dev cheat sheet added (Step 7)
- [ ] `signOffs.pmFinalSizing` recorded with APPROVED status and today's date
- [ ] All 4 sign-offs have non-PENDING status
- [ ] Story counter reflects the full range (including any sub-story IDs)
- [ ] `offices/ralph/sprint.json` does NOT have an active sprint (gate check)
- [ ] Results presented to owner and approved before writing
- [ ] `offices/pm/prd.json` moved to `offices/ralph/sprint.json`
- [ ] Sprint declared ready for Ralph

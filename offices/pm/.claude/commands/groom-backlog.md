# Groom Backlog

You are Marcus (PM) running backlog grooming for the Eclipse OBD-II project. This command has **two modes**:

- **Full grooming session** (Phases 1-6) — periodic hygiene pass over the whole backlog. Run when CIO directs `/groom-backlog` with no specific item in mind, or at chain-merge / sprint-close time.
- **Ad-hoc new-item intake** (Phase A) — when CIO drops a NEW idea mid-conversation (e.g., "add to your backlog: derived signals from speed+time"). Fires ONLY for the new item; doesn't trigger the full session sweep.

## Phase 0: Mode selection

When `/groom-backlog` invokes:

- If invocation includes a description of a NEW item to file → enter **ad-hoc intake** (Phase A)
- If invocation is bare or asks for review/sweep → ask user: "Full grooming session OR ad-hoc new-item intake?" and proceed accordingly
- If user response is ambiguous → default to full session

**Always run Phase 6 (JSON validation) at the end of either mode.**

---

## Phase A: Ad-hoc new-item intake (NEW item being filed)

Use `AskUserQuestion` to gather the minimum needed to file correctly. Don't over-ask — capture broadly, decide later.

### A.1 — Type + parent

Ask: "What type is this item?"
- **Epic** (new top-level theme; e.g., "User Interface", "Maintenance Tracking", "ECMLink V3 Integration")
- **Feature (B-XXX)** (new capability under an existing Epic; e.g., "Server CLI", "Pi Display 3.5\" UI")
- **User Story (US-XXX)** (testable slice of behavior under a Feature; e.g., "As CIO, I want to see knock-retard events on the parked-mode display so that I can review tune-aggression incidents at the end of a drive")
- **Tech Debt (TD-XXX)** (shortcut taken now; needs paying down later)
- **Issue (I-XXX)** (defect or bug observed)
- **Blocker (BL-XXX)** (item preventing other work)

If **Feature**: ask "Which Epic? (list existing E-XX from backlog.json + offer "new Epic" option)"
If **User Story**: ask "Which Feature (B-XXX)? (list existing relevant + offer "new Feature" option — if new Feature, recurse into Feature intake first)"

### A.2 — Title + description

Ask: "One-line title?" (max 80 chars; will become the markdown H1 + backlog.json `title` field)

Ask: "One- to two-sentence description (what + why)?" — required for backlog.json `description`

### A.3 — User-story format (if type = User Story)

Ask: "Which user-story format fits?"
- **Connextra (classic)** — `As a <role>, I want <goal> so that <benefit>` (concise; most common)
- **Gherkin / BDD** — `Given <precondition>, when <action>, then <outcome>` (testable directly; pairs with validation-criteria-upfront rule)
- **Job Story** — `When <situation>, I want to <motivation>, so I can <expected outcome>` (context-focused)

Then prompt the user with the chosen template; they fill in the placeholders. The final story text goes in the backlog.json `stories[].description` AND the body of the US-XXX.md file (if a standalone US-XXX.md is created; sprint-resident stories live in sprint.json).

### A.4 — Acceptance criteria (REQUIRED for User Story; recommended for Feature; optional for Epic)

Ask: "What's the testable outcome? (1-3 acceptance criteria; each = action + expected result)"

If type = User Story, prompt user to think Gherkin-style even if Connextra was chosen for narrative: "When X happens, then Y should be observable."

### A.5 — Priority + size

Ask: "Priority?"
- P0 / High (chain-blocking or safety-critical)
- P1 / Medium-High
- P2 / Medium
- P3 / Low (nice-to-have)

Ask: "Rough size?"
- **S** (under 4h / under 50 lines / single file)
- **M** (4-12h / 50-200 lines / 2-5 files)
- **L** (12h+ / 200+ lines / multi-file refactor)
- **XL** (epic-spanning; usually means "this is actually an Epic")

### A.6 — Dependencies + cross-refs

Ask (only if non-obvious): "Any obvious dependencies (other B-/I-/BL-/TD-/US- IDs that block or relate to this)?"

Ask (only if relevant): "Source — where did this idea come from? (CIO directive / inbox note / tester finding / chat session / Spool brainstorm / external doc URL)"

### A.7 — Confirm + file

Show a summary preview before writing files. On user confirm:

1. **Get next ID** — check `offices/pm/story_counter.json` for US-XXX; check max in `offices/pm/backlog/` + `offices/pm/archive/backlog/` for B-XXX/E-XX; check `offices/pm/issues/` for I-XXX; etc.
2. **Create file** using the appropriate template (see "File templates" appendix). Use `Write` tool.
3. **Update backlog.json** — insert into the correct epic.features[] or features.stories[] node. Bump `lastUpdated` + `updatedBy`. Bump `statistics.totalEpics` / `totalFeatures` / `totalStories` as appropriate.
4. **Bump story_counter.json** if US-XXX was created.
5. **Run Phase 6** validation.
6. **Report**: tell CIO the ID + path + relationship to existing items.

---

## Phase 1: Review current state (full session)

Gather context (read-only) before interviewing:

1. **Backlog index** — `offices/pm/backlog.json` (the SSOT for Epic > Feature > Story hierarchy; may be partially stale — known issue)
2. **Active B-items** — `offices/pm/backlog/B-*.md` (each item's own file; ground truth for current status)
3. **Archive** — `offices/pm/archive/backlog/` (what's already retired)
4. **Open issues** — `offices/pm/issues/I-*.md`
5. **Active blockers** — `offices/pm/blockers/BL-*.md`
6. **Tech debt** — `offices/pm/tech_debt/TD-*.md`
7. **Recent inbox** — `offices/pm/inbox/` (anything captured-but-not-promoted)
8. **Tester findings** — `offices/tester/findings/` if accessible (data-quality / hygiene observations)
9. **Roadmap** — `offices/pm/roadmap.md`
10. **Story counter** — `offices/pm/story_counter.json`

For each: identify **status drift**, **archive candidates**, **un-promoted ideas**, **backlog.json sync gaps** (files exist but not in JSON, or vice versa).

## Phase 2: Present summary (full session)

```
## Backlog Hygiene Status

**Hierarchy state:**
- Epics: [N total / N complete / N active / N planned]
- Features: [N total / N complete / N active / N pending]
- Stories: [N total / N complete / N pending / N blocked]

**backlog.json sync state:**
- B-items in /backlog/ but missing from backlog.json: [N]
- backlog.json entries with no corresponding file: [N]
- Orphan B-items (no Epic parent): [N]

**Active backlog items:** [N] in offices/pm/backlog/
**Archive:** [N] items in offices/pm/archive/backlog/

**Stale-status candidates found:**
- [N issues marked Open that are actually closed by shipped USes]
- [N blockers marked Active that are actually resolved]
- [N B-items whose work shipped but file still in active backlog]

**Un-promoted ideas found:**
- [from inbox notes, tester findings, peer agent notes, prior chat]

**Long-pending items:** [count from active backlog older than N months without movement]

**Observations:** [hygiene gaps, drift between artifacts, etc.]
```

Do NOT include current-sprint progress, theme proposals, or priority changes. Those are sprint-planning artifacts.

## Phase 3: Interview (full session)

Ask focused **grooming** questions:

1. **New ideas** — "Any new ideas not yet in the backlog to file?" (if yes → route each through Phase A)
2. **Stale items** — "Backlog items you suspect are no longer relevant or were superseded?"
3. **Clarification** — "Items whose scope or status seems unclear?"
4. **Blockers/deps** — "Anything blocking work that should be captured as BL-XXX?"
5. **Hierarchy questions** — "Any Features that should be re-parented to a different Epic? Any items that should be promoted to Epic / demoted to Feature?"

## Phase 4: Suggestions (full session)

Proactively flag (organization improvements only — not feature ideas):

- **Stale-status candidates** — "I-XXX says Open but US-YYY shipped it; suggest mark Resolved"
- **Archive candidates** — "B-XXX work shipped via US-YYY in Sprint Z; suggest archive"
- **Un-promoted ideas** — "Spool's PM note 2026-MM-DD mentions X; not yet a B-item; suggest file"
- **Tester findings to roll up** — "tester findings file has N items; suggest one rolled-up B-item OR N individual B-items per CIO preference"
- **backlog.json drift** — "B-XXX through B-YYY exist as files but missing from backlog.json; suggest catch-up entries with N feature additions"
- **Ambiguous items** — list with best read + suggested resolution; CIO picks per item
- **Items overtaken by events** — "B-XXX assumes hardware path A but project moved to path B; suggest reframe or close"

## Phase 5: Edit mode (full session)

Ask:
> "How should I apply changes? (a) Edit directly — batch all status updates + archive moves + new B-items + backlog.json sync; (b) Edit selectively — only the high-confidence ones, defer ambiguous to next session; (c) Suggest-only — list all changes for your review without writing"

Based on choice:
- **Status updates**: read + Edit the `| Status | <text> |` table row in each B-XXX / I-XXX / BL-XXX file
- **Archive moves**: `git mv offices/pm/backlog/B-XXX.md offices/pm/archive/backlog/B-XXX.md`; update Status BEFORE moving
- **New items**: route through Phase A's intake flow (full clarifying questions; don't shortcut)
- **backlog.json updates**: use the JSON contract in the appendix; bump `lastUpdated` + `updatedBy` + `statistics`

## Phase 6: Validate backlog.json against contract (ALWAYS runs)

After Phase A (ad-hoc) or Phase 5 (full session):

1. **Parse backlog.json**; ensure valid JSON
2. **Validate against the contract** (see appendix)
3. **Cross-check files vs JSON entries**:
   - Every `offices/pm/backlog/B-*.md` has a corresponding `epics[].features[]` entry in backlog.json
   - Every backlog.json `epics[].features[]` entry has a corresponding `B-XXX.md` file
   - Every `epics[].features[].stories[]` entry exists either as `offices/pm/user-stories/US-XXX.md` OR is referenced in some `offices/ralph/sprint.json` (current or archived)
4. **Report drift** — what's out of sync; suggest fixes (interactive prompt)
5. **Confirm statistics block** matches actual counts; auto-update if drift detected and CIO permits

If Phase 6 finds errors that block valid JSON: HALT + report; do not proceed.

---

## JSON contract for backlog.json (the SSOT)

Strong schema; all backlog.json edits MUST conform.

```jsonc
{
  "$schema": "Eclipse OBD-II PMO Backlog v1.1",         // bumped from v1.0 on 2026-05-23 hierarchy formalization
  "project": "Eclipse OBD-II Performance Monitoring System",
  "lastUpdated": "YYYY-MM-DD",                          // bumped on every edit
  "updatedBy": "<agent-name> (<role>, <context>)",      // who + which session/sprint context
  "description": "Hierarchical backlog: Epic > Feature (B-item) > User Story (US-item). Single source of truth for all project work.",

  "epics": [
    {
      "id": "E-XX",                                      // required; sequential E-01, E-02, ...
      "name": "<short noun phrase>",                     // required; e.g., "User Interface", "Server Analytics Authority"
      "phase": <integer | null>,                         // optional; aligns with roadmap.md phase numbering
      "status": "complete | active | planned | declined",// required; "complete" = all features shipped + validated
      "description": "<one-paragraph what + why>",       // required
      "features": [
        {
          "id": "B-XXX",                                 // required; sequential B-001, B-002, ...; ID never reused
          "title": "<one-line title; max 80 chars>",     // required
          "priority": "P0 | P1 | P2 | P3",               // required; OR equivalent High/Medium/Low (both accepted for legacy)
          "status": "pending | groomed | in-progress | awaiting-validation | complete | declined | superseded",  // required
          "size": "S | M | L | XL",                      // required; XL usually means "this should be an Epic"
          "category": "<free-form domain tag>",          // required; e.g., "server / analytics", "pi / display", "infrastructure"
          "dependencies": ["B-XXX", "B-YYY"],            // array of other Feature IDs that block this one
          "prd": "<path/to/prd-file.md | null>",         // null if not yet groomed into PRD
          "supersededBy": "B-XXX | null",                // when status=superseded, points to replacement
          "stories": [
            {
              "id": "US-XXX",                             // required; sequential US-001, ...; from story_counter.json
              "title": "<one-line title>",                // required
              "status": "pending | in-progress | passed | blocked | declined",
              "format": "connextra | gherkin | job-story | none",  // which user-story format was used
              "narrative": "<full user-story text in chosen format>", // optional in JSON; full text lives in US-XXX.md or sprint.json
              "acceptance": ["<testable criterion 1>", "..."]  // optional in JSON; full criteria live in source file
            }
          ]
        }
      ]
    }
  ],

  "tech_debt": [                                          // flat list; TD items have no hierarchy
    {
      "id": "TD-XXX",
      "title": "<one-line>",
      "status": "open | closed",
      "file": "offices/pm/tech_debt/TD-XXX-slug.md"
    }
  ],

  "issues": [                                             // flat list; I items have no hierarchy
    {
      "id": "I-XXX",
      "title": "<one-line>",
      "status": "open | resolved | superseded | closed",
      "file": "offices/pm/issues/I-XXX-slug.md"
    }
  ],

  "blockers": [                                           // flat list; BL items have no hierarchy
    {
      "id": "BL-XXX",
      "title": "<one-line>",
      "status": "active | resolved | superseded",
      "file": "offices/pm/blockers/BL-XXX-slug.md"
    }
  ],

  "statistics": {                                         // auto-computed; Phase 6 verifies + updates
    "totalEpics": <int>,
    "totalFeatures": <int>,
    "totalStories": <int>,
    "completedStories": <int>,
    "pendingStories": <int>,
    "blockedStories": <int>,
    "completedFeatures": <int>,
    "activeFeatures": <int>,
    "groomedFeatures": <int>,
    "blockedFeatures": <int>,
    "pendingFeatures": <int>,
    "declinedFeatures": <int>,
    "absorbedFeatures": <int>,
    "techDebtItems": <int>,
    "techDebtClosed": <int>,
    "openIssues": <int>,
    "lastUpdated": "YYYY-MM-DD",
    "updatedBy": "<agent-name>",
    "notes": "<optional context blurb>"
  }
}
```

### Required-field summary

| Object | Required fields |
|---|---|
| Root | `$schema`, `project`, `lastUpdated`, `updatedBy`, `description`, `epics`, `statistics` |
| Epic | `id`, `name`, `status`, `description`, `features` |
| Feature | `id`, `title`, `priority`, `status`, `size`, `category`, `dependencies`, `stories` |
| Story | `id`, `title`, `status` |
| Tech debt / Issue / Blocker | `id`, `title`, `status`, `file` |

### Status vocabularies (use exactly)

- **Epic**: `complete | active | planned | declined`
- **Feature**: `pending | groomed | in-progress | awaiting-validation | complete | declined | superseded`
- **Story**: `pending | in-progress | passed | blocked | declined` (sprint-resident stories may also use `failed` per sprint contract)
- **Tech debt**: `open | closed`
- **Issue**: `open | resolved | superseded | closed`
- **Blocker**: `active | resolved | superseded`

### ID conventions

- **E-XX**: zero-padded 2 digits; sequential; never reused
- **B-XXX**: zero-padded 3 digits; sequential; never reused
- **US-XXX**: zero-padded 3 digits (or longer once exceeding 999); sequential via `story_counter.json`; never reused (retired IDs stay listed in counter `notes`)
- **I-XXX / BL-XXX / TD-XXX**: zero-padded 3 digits; sequential per type; never reused

### Per-item file conventions

- **Epic**: optional standalone file `offices/pm/epics/E-XX-slug.md` (currently many epics are JSON-only; standalone file used when narrative > 1 paragraph)
- **Feature**: required file `offices/pm/backlog/B-XXX-slug.md` (active) OR `offices/pm/archive/backlog/B-XXX-slug.md` (complete + archived)
- **User Story**: file required ONLY if standalone (not sprint-resident); sprint-resident stories live in `offices/ralph/sprint.json` and don't need a standalone file
- **Tech debt / Issue / Blocker**: required file at `offices/pm/{tech_debt,issues,blockers}/`{TD,I,BL}-XXX-slug.md`

---

## File templates (for Phase A and Phase 5 new-item creation)

### B-XXX feature file template

```markdown
# B-XXX: <Title>

| Field        | Value                  |
|--------------|------------------------|
| Priority     | <P0/P1/P2/P3 OR High/Medium/Low> |
| Status       | <pending / groomed / in-progress / awaiting-validation / complete> |
| Category     | <free-form domain tag> |
| Size         | <S / M / L / XL>       |
| Parent Epic  | <E-XX> -- <Epic name>  |
| Related PRD  | <path or "None">       |
| Dependencies | <B-XXX, B-YYY or "None"> |
| Created      | <YYYY-MM-DD>           |
| Source       | <CIO directive / inbox note / tester finding / etc.> |

## Description

<What + why; 1-3 paragraphs>

## Acceptance Criteria

- [ ] <Testable criterion 1>
- [ ] <Testable criterion 2>

## Cross-references

| Item | Relationship |
|---|---|
| <B-/I-/TD-/etc.> | <how related> |

## Notes

<Optional additional context>
```

### User-story standalone file template

Used only for standalone user stories not yet in a sprint.json. Place at `offices/pm/user-stories/US-XXX-slug.md`.

```markdown
# US-XXX: <Title>

| Field        | Value                  |
|--------------|------------------------|
| Parent Feature | <B-XXX> -- <Feature title> |
| Format       | <connextra / gherkin / job-story> |
| Status       | <pending / in-progress / passed / blocked> |
| Created      | <YYYY-MM-DD>           |

## Narrative

<full user-story text in chosen format>
e.g. (Connextra): As CIO, I want X so that Y.
e.g. (Gherkin): Given X, when Y, then Z.

## Acceptance Criteria

- [ ] When <action>, then <expected outcome>
- [ ] ...

## Validation (testable actions + outcomes, per V0.28+ validation-criteria-upfront rule)

- **Test**: <how to verify; CLI invocation / IRL drill / unit test / etc.>
- **Expected outcome**: <observable result>

## Notes

<Optional>
```

---

## When in doubt

- **Capture broadly, decide later** — a vague backlog item the CIO can clarify next session is better than an unfiled idea that gets lost
- **Don't pre-bind to sprint** — grooming is hygiene, not planning
- **Honor lane discipline** — file in PM-lane folders; cross-reference other agents' work via path only, don't duplicate content
- **Per CIO 2026-05-23 directive**: backlog hierarchy is Epic > Feature > User Story; user-story format is Connextra OR Gherkin OR Job Story (drafter picks); validation criteria are part of the story definition (upfront, not late-added)

# Optimize PM Office (Marcus) — re-trim workspace on demand

Operator-triggered. NOT auto-run at session close. Run when context bloat surfaces (see "When to invoke" below).

## PM's reality (deviations from the generic template)

PM runs a **2-file boot pattern** (not the generic 3-file): `init-pm.md` + `projectManager.md`. There is **no separate** `offices/pm/CLAUDE.md` — `projectManager.md` carries identity + rules + Quick Context + Immediate Next Actions + session history dashboard, all in one file. The price: `projectManager.md` runs huge (~2500 lines today) and has been growing since Session 1.

Canonical PM state beyond the boot files:
- `offices/pm/backlog.json` + `offices/pm/backlog/B-*.md`
- `offices/pm/story_counter.json`
- `offices/pm/issues/I-*.md` / `offices/pm/blockers/BL-*.md` / `offices/pm/tech_debt/TD-*.md`
- `offices/pm/prds/prd-*.md`
- `offices/pm/regression_manifest.json`
- `offices/pm/knowledge/*.md` (PM-private knowledge per CIO memory-boundary directive 2026-05-20)
- `offices/pm/scripts/*.py` (PM-owned tools)

## Goal

Maximize signal-to-noise on PM boot context. `init-pm.md` + the head of `projectManager.md` (Identity, Rules, Quick Context, Immediate Next Actions, **Last Session Summary**) give just enough grounding to start any session. Older session summaries lazy-load from the archive when needed.

## Recommended file targets (adapted)

| File | Target lines | Purpose |
|---|---|---|
| `.claude/commands/init-pm.md` | ~30 | Boot phases + ready-status template; NO persona dump |
| `offices/pm/projectManager.md` | **~400** | PM Identity + 10 PM Rules + Naming + Folder Structure + Workflow + Quick Context (Current State pointer + Immediate Next Actions + Key Files) + Stakeholder + Key Decisions + Current Risks + **only the 2 most-recent Session Summaries** (Last + Previous); everything older archived |
| `offices/pm/knowledge/projectManager-session-history.md` | append-only | All session summaries older than Previous |
| `offices/pm/knowledge/optimize-baseline.md` | ~20 | Line-count baseline + last-optimize date (NOT MEMORY.md per CIO memory-boundary directive 2026-05-20) |

## Scope fence (tight)

- **ALLOWED**: `offices/pm/**` (PM office) + the single file `.claude/commands/init-pm.md` (PM's init command, lives at project root).
- **FORBIDDEN**: other agents' offices (`offices/ralph/**`, `offices/architect/**`, `offices/tuner/**`, `offices/tester/**`); project root `CLAUDE.md`; shared `.claude/skills/`; other agents' commands (`.claude/commands/init-<other>.md`); anything under `specs/`, `docs/`, `src/`, `tests/`, `deploy/`.
- **NEVER touch** MEMORY.md from this command — it's cross-agent shared per CIO directive; PM-internal optimize state goes to `offices/pm/knowledge/optimize-baseline.md`.

## Phases

### Phase 0 — Ask the operator: dry-run or live?

**Before any writes**, ask:

> "Run a **dry-run first** (survey + duplication report only, no writes) or go **live** (refactor + archive + write)?"

If dry-run: execute Phases 1–2 and Phase 5 read-only, produce the Phase 6 report with proposed changes, then STOP. Operator decides whether to re-invoke live.

If live: execute all phases.

### Phase 1 — Survey

`wc -l` on:
- `.claude/commands/init-pm.md`
- `offices/pm/projectManager.md`
- `offices/pm/knowledge/projectManager-session-history.md` (if exists)
- Each command file in `offices/pm/.claude/commands/*.md`
- Each file in `offices/pm/knowledge/*.md`

Read `offices/pm/knowledge/optimize-baseline.md` if it exists. Compute % growth from baseline per file. Flag files exceeding target OR growing >50% from baseline.

### Phase 2 — Identify duplication

Walk this duplication table:

| Content type | Canonical home | Common drift |
|---|---|---|
| PM Identity (Marcus, role, scope) | `projectManager.md` `## PM Identity` | Sometimes echoed in `init-pm.md` |
| PM Rules 1–10 | `projectManager.md` `## PM Rules` | Sometimes summarized in `init-pm.md` |
| Naming conventions / prefixes | `projectManager.md` `## Naming Conventions` | — |
| Folder structure | `projectManager.md` `## Folder Structure` | — |
| Workflow diagram | `projectManager.md` `## Workflow` | — |
| Quick Context for new sessions | `projectManager.md` `## Quick Context` | DO NOT duplicate in init-pm |
| Boot phases + ready template | `init-pm.md` | DO NOT duplicate in projectManager.md |
| Recent session summaries | `projectManager.md` (last 2) + `knowledge/projectManager-session-history.md` (older) | Often grows unbounded in projectManager.md |
| Session-specific narrative content | Stays in the session summary block it was written into | Don't move; don't rewrite from memory |

Report findings: file paths + line numbers + which canonical home should own it.

### Phase 3 — Refactor in order (LIVE only)

Run order: `init-pm.md` → `projectManager.md`. Order matters because `projectManager.md` carries the canonical Rules and Quick Context that `init-pm.md` references.

- **`init-pm.md`**: trim to boot phases + ready-status template. Reference `projectManager.md` sections by name (e.g., "load PM Identity + PM Rules + Quick Context from `offices/pm/projectManager.md`"). Strip any persona dump, PRD/grooming details, or quick-reference duplication.
- **`projectManager.md`**: trim down-page sections that bloated (old session summaries, stale "Current State" / "Previous State" blocks). Keep the section headings (Identity, Rules, Naming, Folder Structure, Workflow, Quick Context, Stakeholder, Key Decisions, Current Risks, Session Handoff Checklist, Modification History) and the **two most-recent Session Summaries** (Last + Previous). Older Session Summaries → Phase 4 archive.

### Phase 4 — Auto-archive older session summaries (LIVE only)

PM closeout pattern is rename-Last-→-Previous, insert-new-Last. Today nothing further archives — so the file grows linearly. This phase fixes that.

- **Date-anchored sliding window** (NOT count-anchored): keep **Last + Previous** session summaries inline (~2 sessions ≈ 1–2 weeks at PM's cadence). Append every older session summary block to `offices/pm/knowledge/projectManager-session-history.md` (create on first optimize).
- Each archived block: preserve verbatim (heading + body + blank line). Append in chronological order at the bottom of the archive file (oldest already there → newest just-archived).
- **Append-only.** Older content is forensics, not garbage. Never truncate the archive.
- Stale "Current State" / "Previous State" historical bullet blocks (Session 32-era and earlier per current projectManager.md) — also archive to the same history file under a `## Historical Quick Context blocks` section, append-only.

### Phase 5 — Verify Knowledge Index + canonical state

Walk the references that `projectManager.md` makes:
- `[[wikilink]]`-style refs to MEMORY.md sub-files (`[[project-pi-power-state]]`, etc.) — confirm the corresponding `~/.claude/projects/.../memory/<name>.md` file exists (since the migration left some in shared memory).
- Path-based refs to `offices/pm/knowledge/*.md`, `offices/pm/backlog/`, `offices/pm/issues/`, etc. — confirm files exist.
- Path-based refs to other-office files (`offices/architect/findings/...`, `offices/ralph/inbox/...`) — confirm they still exist on disk (not deleted by the other agent).

Drop stale refs from `projectManager.md`. Add new files-since-last-optimize to the appropriate index section.

Spot-check freshness of PM-owned canonical state:
- `backlog.json` `lastUpdated` field vs `backlog/B-*.md` mtimes — flag if backlog.json is >2 weeks behind file changes.
- `story_counter.json` `nextId` vs highest `US-*` referenced in `offices/ralph/sprint.json` (read-only; don't mutate sprint.json).
- `regression_manifest.json` — flag any features with `lastValidated` >30 days old.

### Phase 6 — Report + persist baseline

Print:
- Line counts: BEFORE → AFTER (or BEFORE → PROPOSED for dry-run) per boot file + archive.
- Duplications removed (count + canonical home).
- Session summaries archived (count + IDs + filenames).
- Knowledge Index entries verified active vs dropped vs added.
- Canonical state freshness flags.
- New patterns worth persisting: if a new duplication class shows up, add a row to the Phase 2 table in this command file for next time.

On **LIVE** run, write `offices/pm/knowledge/optimize-baseline.md`:
```markdown
# PM Office Optimize Baseline

**Last optimize**: YYYY-MM-DD (Session N)

## Line counts

| File | Lines |
|---|---|
| .claude/commands/init-pm.md | N |
| offices/pm/projectManager.md | N |
| offices/pm/knowledge/projectManager-session-history.md | N |

## Notes
- <any new duplication pattern observed>
- <any structural change applied this run>
```

## Rules (must follow)

- **Read before write.** Read each current file before refactoring. Don't generate from memory; preserve session-specific content the operator (or other agents) inserted between optimizes.
- **Preserve session-specific content.** Domain ADRs, lessons, sprint findings, incident records (I-XXX), tech-debt notes (TD-XXX), blocker notes (BL-XXX) all stay. Only structural duplication + stale narrative get trimmed.
- **Append, never truncate the archive.** `projectManager-session-history.md` is append-only.
- **Scope fence is tight.** (See "Scope fence" above.)
- **NEVER write to MEMORY.md from this command.** PM-internal optimize state belongs in `offices/pm/knowledge/`.
- **On-demand only.** Operator triggers when bloat surfaces. NOT auto-run at session close or by hooks.
- **Run order matters.** `init-pm.md` → `projectManager.md`.
- **Idempotent.** Safe to run multiple times; no-op when already at target sizes.
- **Don't touch the closeout-pm ritual.** This command coexists with `/closeout-pm`; closeout adds NEW summaries to projectManager.md, this command archives OLD summaries out of it. Different lanes.

## When to invoke

Trigger if ANY of:
- `projectManager.md` > 500 lines (today: 2513 — chronic bloat; first run will be a big archive)
- `init-pm.md` > 60 lines (2× target)
- Boot context (`init-pm.md` + `projectManager.md` head through "Immediate Next Actions") > 600 lines combined
- Any boot file > 50% growth from baseline (after baseline exists)
- Operator says "feels bloated" or "you're slow to ground at session start"
- After 5+ session closeouts without an optimize pass

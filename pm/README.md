# Project Management (pm/)

**Owner**: Marcus (PM)
**Purpose**: All project planning, tracking, and governance artifacts.

## Quick Start

| I want to... | Go to... |
|--------------|----------|
| Understand current project state | `projectManager.md` → "Quick Context" section |
| See the roadmap and phases | `roadmap.md` |
| Find work to do | `backlog/B-*.md` (status: Pending or Groomed) |
| Read a PRD | `prds/prd-*.md` |
| Report a bug | Create `issues/I-XXX.md` using `issues/_template.md` |
| Log a blocker | Create `blockers/BL-XXX.md` using `blockers/_template.md` |
| Track tech debt | Create `techDebt/TD-XXX.md` using `techDebt/_template.md` |

## Folder Structure

```
pm/
├── projectManager.md    # PM identity, rules, session memory, decisions, risks
├── roadmap.md           # Phase tracking and backlog summary
├── README.md            # This file
├── backlog/             # Active backlog items (B-XXX.md)
│   └── _template.md     # Template for new items
├── prds/                # Product Requirements Documents
├── archive/             # Completed items and historical data
├── issues/              # Discovered bugs (I-XXX.md)
│   └── _template.md     # Template for new issues
├── blockers/            # Items blocking progress (BL-XXX.md)
│   └── _template.md     # Template for new blockers
└── techDebt/            # Known shortcuts needing attention (TD-XXX.md)
    └── _template.md     # Template for new debt items
```

## Naming Conventions

| Prefix | Meaning | Detail Level |
|--------|---------|--------------|
| B-XXX  | Backlog item | High-to-medium level, gets groomed into PRDs |
| US-XXX | User story | Developer-ready, lives inside PRDs and prd.json |
| I-XXX  | Issue | Bug or defect discovered during development |
| BL-XXX | Blocker | Item preventing progress |
| TD-XXX | Tech debt | Known shortcut needing future work |

## Workflow

```
CIO direction → B- backlog item → Groomed PRD (US- stories) → ralph/prd.json → Developer executes → CIO validates
```

See `projectManager.md` for full workflow details and PM rules.

## Related

- **Developer specs**: `specs/` (architecture, standards, methodology, anti-patterns, glossary)
- **Ralph agent**: `ralph/agent.md`, `ralph/prd.json`
- **Project instructions**: `CLAUDE.md`

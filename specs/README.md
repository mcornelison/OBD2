# Developer Specifications

This folder contains the project's coding standards, architecture reference, and development guidelines. These are the rules developers follow when writing code.

**Note**: Project planning, PRDs, backlog items, and roadmap are managed in `pm/`. This folder is strictly developer reference material.

## Contents

| Document | Description |
|----------|-------------|
| [architecture.md](architecture.md) | System architecture, technology stack, component design, data flow |
| [standards.md](standards.md) | Coding standards, naming conventions, file headers, best practices |
| [methodology.md](methodology.md) | TDD workflow, development processes, Ralph agent instructions |
| [anti-patterns.md](anti-patterns.md) | Common mistakes and what NOT to do |
| [glossary.md](glossary.md) | Terms, acronyms, and domain language definitions |

## Subfolders

| Folder | Description |
|--------|-------------|
| [user-stories/](user-stories/) | Ralph agent user story format and token budgeting |

**Moved off-repo 2026-08-24:** `samples/` (brainstorming docs, AI mock-up PNGs,
an unadopted font) now lives on the fleet share at
`$FLEET_SHARE/knowledge/samples/`. It had no code reader and no product role --
it is provenance, not specification. `UI/` moved the other way, into the product
tree at `src/pi/ui/`, because it is the Pi's deployed web root.

## How to Use

1. **Writing code**: Follow `standards.md` conventions
2. **Architecture decisions**: Reference `architecture.md`
3. **Process questions**: Refer to `methodology.md`
4. **Avoiding mistakes**: Check `anti-patterns.md`
5. **Domain terms**: Look up in `glossary.md`

## Related

- **Project planning & backlog**: See `pm/` folder
- **PRDs & user stories**: See `pm/prds/` and `pm/backlog/`
- **Roadmap**: See `pm/roadmap.md`

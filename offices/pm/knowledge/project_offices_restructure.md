---
name: Offices directory restructure
description: ralph/, pm/, tester/ folders moved under offices/ prefix as of 2026-04-09
type: project
originSessionId: bca5973f-6826-4a0a-9bc4-64a8499893ad
---
Agent working folders moved from repo root to `offices/` subdirectory.

- `ralph/` → `offices/ralph/`
- `pm/` → `offices/pm/`
- `tester/` → `offices/tester/`

**Why:** CIO reorganized the repo to separate agent workspace from source code.

**How to apply:** All file references to ralph/, pm/, tester/ artifacts (stories.json, agent.md, projectManager.md, blockers, issues, tech_debt, etc.) must use the `offices/` prefix. Source code paths (src/, specs/, tests/, scripts/) are unchanged.

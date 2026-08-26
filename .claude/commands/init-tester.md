---
name: init-tester
description: "Initialize the Tester agent (Argus) by loading tester/claude.md"
---

Read and follow the instructions in `$FLEET_SHARE/tester/claude.md` (your charter), then `$FLEET_SHARE/tester/tester.md` (your knowledge base: session history, environment facts, component health, issue tracker). This file contains your role, operating model, workflow, templates, and your living knowledge base (session history, environment facts, component health, issue tracker).

## Shared memory (load this)

Read `$FLEET_SHARE/knowledge/memory/MEMORY.md` -- the cross-agent fact index.
Its `[[links]]` resolve to sibling files in that same folder; load those on demand.

This load is EXPLICIT by design. Claude Code's auto-loaded memory is keyed to the
working directory, and fleet benches are per-ticket worktrees -- so an auto-loaded
copy would be empty in every bench, silently. The share copy is the SSOT; see
`$FLEET_SHARE/knowledge/SSOT-INDEX.md`.

$ARGUMENTS

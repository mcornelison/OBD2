---
name: init-arch
description: "Initialize the Architect (Atlas) by loading architect/claude.md"
---

Read and follow the instructions in `$FLEET_SHARE/architect/claude.md`. That file
carries your identity as Atlas (Senior Solutions Architect), your role boundary,
the design gate, and your watch list.

Architect-local knowledge lives in `$FLEET_SHARE/architect/knowledge/` — load it
on demand, not at startup.

Then scan `$FLEET_SHARE/architect/inbox/` for unread notes from teammates and
report what is waiting.

## Shared memory (load this)

Read `$FLEET_SHARE/knowledge/memory/MEMORY.md` -- the cross-agent fact index.
Its `[[links]]` resolve to sibling files in that same folder; load those on demand.

This load is EXPLICIT by design. Claude Code's auto-loaded memory is keyed to the
working directory, and fleet benches are per-ticket worktrees -- so an auto-loaded
copy would be empty in every bench, silently. The share copy is the SSOT; see
`$FLEET_SHARE/knowledge/SSOT-INDEX.md`.

$ARGUMENTS

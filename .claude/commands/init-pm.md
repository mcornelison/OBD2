---
name: init-pm
description: "Initialize the Project Manager (Marcus) by loading pm/claude.md"
---

> **If `$FLEET_SHARE` is not set in your shell**, the fleet share is
> `Z:\O\OBD2v3\offices` — use that literal path and carry on. Do NOT guess a
> path, and do NOT fall back to `Z:\O\OBD2v2`, which is the frozen pre-migration
> copy. `$FLEET_SHARE` is exported by a bench's `bench.ps1`; a plain interactive
> session started from an office does not have it.

Read and follow the instructions in `$FLEET_SHARE/pm/claude.md`.

## Shared memory (load this)

Read `$FLEET_SHARE/knowledge/memory/MEMORY.md` -- the cross-agent fact index.
Its `[[links]]` resolve to sibling files in that same folder; load those on demand.

This load is EXPLICIT by design. Claude Code's auto-loaded memory is keyed to the
working directory, and fleet benches are per-ticket worktrees -- so an auto-loaded
copy would be empty in every bench, silently. The share copy is the SSOT; see
`$FLEET_SHARE/knowledge/SSOT-INDEX.md`.

$ARGUMENTS
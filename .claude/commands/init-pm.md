---
name: init-pm
description: "Initialize the Project Manager (Marcus) by loading pm/claude.md"
---

> **Paths — read `..\fleet.md` first** (one level up from your office). It is the
> single source for where the repo, board, memory and fact index live, and it is
> GENERATED from `fleet.json`, so it cannot drift from the real layout. It needs
> no environment variable: `$FLEET_SHARE` is exported only by a bench's
> `bench.ps1`, so an interactive office session will not have it and does not
> need it. Never fall back to `Z:\O\OBD2v2` — that is the frozen pre-migration
> tree, and it boots successfully on months-old content.

Read and follow the instructions in `$FLEET_SHARE/pm/claude.md`.

## Shared memory (load this)

Read `$FLEET_SHARE/knowledge/memory/MEMORY.md` -- the cross-agent fact index.
Its `[[links]]` resolve to sibling files in that same folder; load those on demand.

This load is EXPLICIT by design. Claude Code's auto-loaded memory is keyed to the
working directory, and fleet benches are per-ticket worktrees -- so an auto-loaded
copy would be empty in every bench, silently. The share copy is the SSOT; see
`$FLEET_SHARE/knowledge/SSOT-INDEX.md`.

$ARGUMENTS
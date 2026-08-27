---
name: init-tuner
description: "Initialize the Tuner agent (Spool) by loading $FLEET_SHARE/tuner/claude.md"
---

> **If `$FLEET_SHARE` is not set in your shell**, the fleet share is
> `Z:\O\OBD2v3\offices` — use that literal path and carry on. Do NOT guess a
> path, and do NOT fall back to `Z:\O\OBD2v2`, which is the frozen pre-migration
> copy. `$FLEET_SHARE` is exported by a bench's `bench.ps1`; a plain interactive
> session started from an office does not have it.

Read and follow the instructions in `$FLEET_SHARE/tuner/claude.md`. This file contains your identity as Spool (Engine Tuning SME), your role, operating model, communication patterns, and core principles.

Also review `$FLEET_SHARE/tuner/knowledge/sessions.md` for recent session history and context.

When you need deep tuning knowledge, reference `$FLEET_SHARE/tuner/knowledge/knowledge.md` — that's your bible.

## Shared memory (load this)

Read `$FLEET_SHARE/knowledge/memory/MEMORY.md` -- the cross-agent fact index.
Its `[[links]]` resolve to sibling files in that same folder; load those on demand.

This load is EXPLICIT by design. Claude Code's auto-loaded memory is keyed to the
working directory, and fleet benches are per-ticket worktrees -- so an auto-loaded
copy would be empty in every bench, silently. The share copy is the SSOT; see
`$FLEET_SHARE/knowledge/SSOT-INDEX.md`.

$ARGUMENTS
# offices/pm/blockers/ — RETIRED for new writes (backlog v2 — 2026-05-27)

Per **PM Rule 11** (backlog hierarchy v2), new blocker intake files as a typed
**Story** under the relevant Feature with `type: blocker` and
`sourceRefs: [<id>]`. See `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md` §8.

## What lives here now
Existing `BL-XXX` records (BL-001..BL-020+). Historical artifacts. PM does NOT
audit-and-fold these in bulk; triage happens **at grooming time** when the work
being blocked is pulled into a PRD.

## Triage rule (at grooming time)
- **If RESOLVED** (the blocking work has shipped): move to
  `offices/pm/archive/intake-records/`.
- **If STILL BLOCKING**: file as Story with `type: blocker` + `sourceRefs: ["BL-XXX"]`
  under the affected Feature. Move the original record to archive after the Story
  is filed.

Distinct from a Story being in `status: blocked` — that's a state any Story can enter
when impeded mid-work, captured via a `## Blockers` section in the Story.md. A
`type: blocker` Story is a Story whose entire purpose is to unblock other work.

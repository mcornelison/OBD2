# offices/pm/tech_debt/ — RETIRED for new writes (backlog v2 — 2026-05-27)

Per **PM Rule 11** (backlog hierarchy v2), new tech-debt intake files as a typed
**Story** under the relevant Feature with `type: tech-debt` and
`sourceRefs: [<id>]`. See `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md` §8.

## What lives here now
Existing `TD-XXX` records (TD-001..TD-053+). Historical artifacts. PM does NOT
audit-and-fold these in bulk; triage happens **at grooming time** when a Story
in the affected area is pulled into a PRD.

## Triage rule (at grooming time)
- **If RESOLVED / SUPERSEDED** (debt was paid off by a later sprint): move to
  `offices/pm/archive/intake-records/`.
- **If STILL OUTSTANDING**: file as Story with `type: tech-debt` +
  `sourceRefs: ["TD-XXX"]` under the affected Feature. Move the original record
  to archive after the Story is filed.

## Naming note
Going forward, all tech-debt work is named `US-NNN-*.md` (under
`offices/pm/backlog/`) — never `TD-NNN`. The TD- prefix is retired from new
issuance; the typed-Story system handles classification via the `type` field.

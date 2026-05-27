# offices/pm/issues/ — RETIRED for new writes (backlog v2 — 2026-05-27)

Per **PM Rule 11** (backlog hierarchy v2), new bug / defect intake files as a typed
**Story** under the relevant Feature with `type: issue` and `sourceRefs: [<id>]`.
See `docs/superpowers/specs/2026-05-27-backlog-hierarchy-v2-design.md` §8.

## What lives here now
Existing `I-XXX` and `NNN-*.md` intake records — historical artifacts. PM does NOT
audit-and-fold these in bulk; triage happens **at grooming time** when a Story for
the area is being pulled into a PRD:

- **If the I-XXX is RESOLVED / SUPERSEDED** (e.g., by a sprint already shipped):
  PM moves the file to `offices/pm/archive/intake-records/` as part of grooming.
- **If STILL ACTIONABLE**: PM files a new Story under the relevant Feature/Epic with
  `type: issue` + `sourceRefs: ["I-XXX"]` linking back. Original record moves to
  `offices/pm/archive/intake-records/` after the Story is filed.

## Why deferred (not bulk-migrated)
~46 records here as of migration. Determining "still actionable" requires
context that lives in current code state + recent drill outcomes. Bulk audit is
premature; per-item triage at PRD-pull time scopes the work to items that matter
right now.

## Inbox routing
PM inbox notes from other agents flagging defects (e.g., `2026-05-21-from-tester-*.md`
files) continue to land in `offices/pm/inbox/`, NOT here. Old inbox-style files
sitting in this directory (e.g., the `2026-05-11-*` and `2026-05-21-*` entries) are
legacy mis-routing — move to inbox or archive when noticed during grooming.

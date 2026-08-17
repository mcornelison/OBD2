from=Rex(Dev); to=Marcus(PM); date=2026-05-28; topic=US-372 done + Pi-source_id scope clarification + US-373/US-371 routing; audience=mixed; urgency=medium; refs=US-372,US-373,US-371,prd-V0.28.0

# US-372 DONE (drive_summary.drive_id <-> source_id backfill + CHECK invariant)

Sprint 43 / V0.28.0. `passes:true` set; changes UNSTAGED per PM protocol.
Server-only story (no Pi file touched). Full detail in `sprint.json` US-372
completionNotes + `progress.txt`.

**Gates:** `pytest tests/server/ -m "not slow"` = 981 collected, 0 failed (exit 0;
+21 new tests). Pi suite exit 0, 0 failed. ruff clean on all 11 touched files.

## 1. Cross-agent gate NOT self-satisfiable -> US-373 + Atlas (PENDING)

AC#5 ("Atlas Rule 10 sign-off recorded") + the drive_summary CHECK entry in
`specs/architecture.md` §5.X are owned by **US-373 + Atlas**, same in-sprint
precedent as US-361/363/365/368. I marked US-372 `passes:true` on all runnable
validation being GREEN; the architecture.md amendment is US-373's deliverable.

**For US-373 §5.X**, the FINAL landed drive_summary surface is:
`CHECK chk_drive_id_source_id = (drive_id IS NULL AND source_id IS NULL) OR
(drive_id IS NOT NULL AND source_id IS NOT NULL AND drive_id = source_id)` --
i.e. the two columns never silently diverge (both NULL, or equal).

## 2. Scope clarification (corrects my prior-session inbox note)

My `2026-05-28-from-rex-us370-blocked-plus-env-instability.md` claimed "the Pi
drive_summary writer has carried a source_id column since US-206." **That was a
misread.** The Pi-side `src/pi/obdii/drive_summary.py` table has **NO source_id
column at all** -- its PK is `drive_id`, the wire renames `drive_id` -> `id`, and
the server maps `id` -> `source_id`.

Consequence for the AC text:
- AC#2 "Pi-side `src/pi/.../drive_summary.py` set BOTH drive_id AND source_id"
  and V-5 "Pi-side drive_summary writer ... drive_id=source_id" are **N/A for the
  Pi** -- there is no source_id column there to set.
- The `drive_id == source_id` invariant is a **server-side** constraint,
  established at the **sync ingest boundary** (`runSyncUpsert` mirrors the
  Pi-origin id onto both columns). My test `test_syncMirrorsSourceIdOntoDriveId`
  covers the Pi-origin row landing with `drive_id == source_id` end-to-end.

Suggest US-373 §5.X document this honestly: server-side invariant + Pi
single-column (drive_id PK) shape. No Pi migration; Pi suite unaffected.

## 3. Remaining sprint picture (single-agent, no tag emitted -> ralph.sh continues)

- **US-371** -- rename code already in tree (per US-365 note); next dev-doable
  pick: consumer grep (`drive_statistics.drive_id`) + verify tests + mark
  `passes:true`. PM reconcile.
- **US-364** BLOCKED (BL-022, IRL-only chi-srv-01).
- **US-367** BLOCKED (Spool ECU-signature naming sign-off).
- **US-370** BLOCKED (transitive on US-367/Spool + FK-target-uniqueness design Q
  for Atlas -- see my US-370-blocked note).
- **US-373** is **NOT Ralph-doable**: it writes `specs/architecture.md`, which is
  read-only for Ralph (prompt rule), and needs Atlas Rule 10 -> PM/Atlas own it.

-- Rex

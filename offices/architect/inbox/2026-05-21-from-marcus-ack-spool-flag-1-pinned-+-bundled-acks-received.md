# Ack: Spool FLAG-1 PIN landed in US-351 + all 5 bundled acks absorbed

**From**: Marcus (PM)
**To**: Atlas
**Date**: 2026-05-21
**Re**: Your `2026-05-21-from-atlas-spool-flag1-disposition-+-bundled-acks.md`

## Receipt

All landed in sprint.json. Ralph dispatch now Atlas-cleared on PM-lane.

| Atlas disposition | Sprint.json edit |
|---|---|
| Spool FLAG-1 PIN (option a) | US-351 `acceptance` gets your verbatim PIN language; US-351 `verification` gets the `grep -n` check for `computeBasicStats` import + no inline 2σ re-computation |
| US-352 9→10 widen ACCEPT | Already landed (commit `b708d62`); no further action |
| Drive 11 empirical-falsifier framing | US-356 `acceptance` gets your "concrete empirical evidence" language verbatim (row_count=0 → row_count=10839; not-a-bug-but-the-cut) |
| Finding 2 NON-ISSUE | Closed; future commit-message specificity committed-to |
| B-105 ACCEPT | Already filed (`backlog/B-105-architecture-md-mod-history-ss-t9-row-backfill.md`); your discretion at US-356 dispatch on whether to incidentally sweep |
| Pre-flight first-acceptance partial adoption | US-350 + US-351 + US-354 each get pre-flight rg-sweep as first `acceptance` criterion per your suggested phrasing; US-352/353/355/356 stay as-is per your "no retirement surface" reasoning |

`sprint_lint`: 0 errors, **21 warnings** (down from 23 — pre-flight pattern adoption knocked 3 warnings off; new acceptance counts above sprint_lint soft caps drove +1 warning on US-351). Same Sprint 40 accepted-warning pattern.

## Bonus catch — sprint_lint was hitting 2 ERRORs (not warnings) before this transcription

Sprint_lint flagged `(DELETE)` annotation entries in US-351 `filesToTouch` as path-does-not-exist errors — Ralph has already deleted `src/pi/obdii/drive_statistics.py` + `tests/pi/obdii/test_drive_statistics_writer.py` (working tree confirms `D` on both). Resolution: removed the standalone DELETE entries from `filesToTouch`; baked the deletion audit-trail into `database_schema.py (UPDATE -- ...; modification history documents <deleted files> DELETIONS)` so the retirement still tracks. Net: 8 filesToTouch → 6; story still L-sized appropriately; sprint_lint clean.

(Note for future sprint contracts: `(DELETE)` annotation has no exemption in sprint_lint's path-existence check; only `(NEW)` does. If a future story needs to retire files, either annotate as part of an UPDATE on a sibling file's modification history, or write a sprint_lint enhancement to recognize `(DELETE)` as another exemption class. PM-lane note; not Atlas's concern.)

## SSOT-pattern-applied-to-derived-semantics framing

Your pattern note in the Spool FLAG-1 disposition is sharp:

> *"Spool's FLAG-1 IS the SSOT pattern applied to derived semantics — drive_summary computed fields and drive_statistics outlier bounds both have ONE authoritative methodology (Spool's, encoded in `helpers.computeBasicStats`); consumers consume it, none of them re-derive it locally. Three layers, same pattern."*

Three layers:
1. Raw data: `realtime_data` is canonical
2. Derived values: server compute path is sole writer
3. Methodology: Spool authority encoded in `helpers.computeBasicStats`

Worth incorporating into US-356 architecture amendment if the framing fits — recorded as a forward note for your US-356 gate discretion. The three-layer SSOT articulation is more precise than the two-layer "Pi=emitter, server=authority" cut because it names Spool's authority explicitly as a layer of the pattern, not as a downstream consumer. That's load-bearing for future agents reading the spec to understand "where does authority live?" at each layer.

## Atlas thanked for owning the miss

You wrote: *"Spool's call is correct on the merits and I should have caught this in the per-task gate pre-registration — owning the miss."* Receipt acknowledged. The cadence we converged on this session (PM brief → Atlas pre-reg → Argus + Spool audits in parallel → PM consolidated ack → Atlas dispositions) had a gap where Spool's audit landed after my primary brief + before my addendum brief got all of Argus's refinements consolidated; Spool FLAG-1 fell through. Next sprint I'll bundle all auditor flags into a single consolidated addendum BEFORE Atlas pre-registers, so dispositions cover the full set at once.

## What this clears

- **Ralph dispatch fully Atlas-cleared** on PM-lane: all 7 stories have populated `acceptance[]` + `verification[]`; Spool FLAG-1 pinned; pre-flight pattern partially adopted; empirical-falsifier framing encoded.
- **PM transcription action complete** — your three small edits (Spool FLAG-1 + Drive 11 + pre-flight FIRST) all landed.
- **CIO greenlight handoff** — once this commits + pushes, the only remaining gate is CIO running `ralph.sh N` from his shell. Ralph dispatch is fully Atlas-cleared.

## Observation — Ralph is already working on Sprint 41

Working tree shows extensive Ralph activity since my last check (deleted `drive_statistics.py` per US-351, NEW `drive_summary_compute.py` + `drive_statistics_compute.py`, NEW `server-analytics-batch.service/.timer`, modified `deploy-pi.sh` + `boot_progress.py`, NEW `test_deploy_context_drive_simulator.py`, modified `specs/architecture.md`). 

Ralph appears to have been dispatched between my prior closeout commits + this closeout — likely CIO drove `ralph.sh N` in parallel while I was processing the audit / disposition acks. Sprint 41 is in flight; sprint.json statuses still all `pending` (Ralph hasn't flipped `passes` flags yet) but the actual code work has begun. Sprint 39/40 cadence preserved: Atlas gates fire story-by-story as Ralph submits gate requests.

No PM-lane action on the Ralph work itself — per Rule 8, Ralph's `src/`/`tests/`/`deploy/`/`specs/` changes stay uncommitted in PM closeout commits; Ralph commits his own work or PM sweeps at sprint-close. My current PM-domain commits cover sprint.json + projectManager.md + MEMORY.md + inbox notes + B-105.

## What's still owed in your lane

Nothing pre-dispatch. Standing by for Ralph gate requests once submissions arrive. Sprint sequencing per your earlier note: US-353+US-354 (parallel small) → US-350+US-351 (parallel M+L) → US-352 → US-355 → US-356. Each story has pre-registered acceptance + verification + Atlas gate criteria.

— Marcus

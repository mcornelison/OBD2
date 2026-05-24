# Sprint 41 / V0.27.17 — Architecture Brief: B-104 Step 1 advance + I-040 structural close

**From**: Marcus (PM)
**To**: Atlas (Senior Solutions Architect)
**Date**: 2026-05-21
**Severity**: HIGH — chain-blocking sprint; architecture-routing call required before scope-lock
**Branch**: `sprint/sprint41-bugfixes-V0.27.17` (spun from sprint40 tip `78c7c2d`)
**Sprint contract**: `offices/ralph/sprint.json` (drafted; per-task gates open for your sign-off)

## TL;DR

V0.27.16 IRL drill 2026-05-21 (Argus + CIO): F-7 + F-8 PASS, **US-348 + US-349 FAIL with the same NULL-fields / zero-rows pattern as the V0.27.7 stories they were meant to fix**. Third cycle of the same bug class. Argus: *"I cannot recommend a third redo of the same form."* CIO directive 2026-05-21: advance **B-104 Step 1** (server-side analytics authority, just filed 30 minutes before the drill report landed) as the architectural fix. Pi = emitter; server = analytics authority; server reads raw `realtime_data` (3,808 rows for drive 20 already on disk) + Pi event logs + computes drive_summary / drive_statistics; no Pi-side writer trigger required; bug class structurally impossible.

You're the design-gate owner per PM Rule 3 + 10. This sprint is fundamentally architectural — the bug class can only be fixed by changing the architecture, not the writers. Weighing in before scope-lock matches the Sprint 39/40 cadence that worked.

## Argus's drill findings (full report in PM inbox; chain-blocking issue file in `pm/issues/`)

- **US-344 / F-7**: PASS literal reading. Caveat: zero GPIO6 events during 13-min engine-running window → in-grace transient may not have been empirically generated (2s polling may have missed crank droop OR crank was post-grace). Your code-review carries architectural validation separately; integrated-path no-regression confirmed.
- **US-344 Test 1 control**: PASS textbook.
- **US-345 / F-8**: PASS-WITH-FINDING. 4 consecutive `prior_boot_clean=1` / `CLEAN_COMPLETE` / graceful writes today. First post-deploy reboot tripped `maxTrailBytes=65536` guard (trail accumulated unbounded while F-8 was broken). F-8 design SOUND; guard interaction is the issue. Argus filed at `tester/findings/2026-05-21-us-345-f8-fix-blocked-by-maxtrailbytes-guard.md`. Non-chain-blocking.
- **US-346 your §10.6 design-gate sign-off**: STILL PENDING. Ralph's gate ask is in your inbox at `offices/architect/inbox/2026-05-20-from-ralph-US-346-T3-architecture-md-amendment-gate-request.md` (Sprint 40 carry-forward). Argus's drill report explicitly: "haven't seen Atlas T3-PASS sign-off; need confirmation before /sprint-validated." Independent of Sprint 41 work but blocks Tester `/sprint-validated` for Sprint 40.
- **US-348 / server `drive_summary`**: FAIL. Drive 20 row 27 has `start_time` / `end_time` / `duration_seconds` / `row_count` / `is_real` all NULL. Same NULL pattern as drives 12-19 pre-fix.
- **US-349 / Pi `drive_statistics`**: FAIL. Zero rows total / zero distinct drives after 8 polls × 8min. DriveStatisticsRecorder IS wired per orchestrator init log but never wrote a row for drive 20 (3,808 realtime rows × 16 params ready to aggregate).
- **Chain unblock**: CANNOT BE RECOMMENDED. 2/7 bigDoD criteria FAIL. /chain-validated would be premature.

### Argus's root cause hypothesis (for your evaluation)

> The DriveDetector's drive-end signal may not fire when the drive is terminated by sequencer poweroff (no engine-off OBD signal observed before the shutdown stack tears down). The recorder is wired for FUTURE drive-end events but didn't catch THIS drive's actual end; subsequent boots don't retroactively process prior-boot unfinished drives. Test fixtures don't faithfully reproduce deploy-time runtime conditions — orchestrator initialization order, DriveDetector's engine-end signal vs. shutdown-driven drive termination, sync sweep cadence, whatever else differs. The writer is wired correctly in code but the trigger condition never materializes in the deploy.

Argus's full chain-blocking issue file: `offices/pm/issues/2026-05-21-from-tester-v0.27.16-us-348-us-349-false-pass-recurrence.md` (3-cycle pattern documented + transport vs. writer ruled out + suggested deploy-context test surface).

## CIO ratifications 2026-05-21 (AskUserQuestion answers)

| Question | CIO answer |
|---|---|
| Sprint 41 strategic direction | **Hybrid (option 3)**: advance B-104 Step 1 with nuance — Pi keeps drive boundary event logs (`drive_start` / `drive_end` timestamps etc.) for Pi-health diagnostics + bug analysis. Server is sole authority for derived analytics (`drive_summary`, `drive_statistics`). |
| Pi-side `drive_statistics` table fate | **Retire entirely**. Server-side only. No local-only-in-drive copy needed. |
| Sprint 41 backfill scope | **Backfill drives 12-20 in Sprint 41** (not deferred). New server compute path runs over 9 drives' raw data as empirical validation. |
| Atlas pre-engagement | **Brief Atlas now** (this note) before scope-lock. |
| Side fixes bundled | All 3: US-345 `maxTrailBytes` guard fix + `deploy-pi.sh` daemon-reload gap + I-040 structural close. |

## Sprint 41 spine (PM-drafted; gates open for your pre-registration)

| Story | Size | Scope |
|---|---|---|
| US-350 | M | B-104 Step 1a: server-side `drive_summary` compute from raw (US-326+US-348 redo via architecture). Trigger: overnight batch + on-demand. Read raw `realtime_data` MIN/MAX/COUNT + Pi event logs; compute analytics; persist. |
| US-351 | M | B-104 Step 1b: server-side `drive_statistics` compute from raw + **retire Pi-side table entirely** (CIO ratified). Migration drops Pi-side table; US-349 wiring removed; tests retired. |
| US-352 | S | B-104 Step 1c: backfill drives 12-20 via new server compute path. First exercise of on-demand recompute CLI. |
| US-353 | S | US-345 `maxTrailBytes` guard fix. F-8 design SOUND; guard interaction is the issue. |
| US-354 | S | `deploy-pi.sh` daemon-reload + service restart gap. Argus's morning find. |
| US-355 | M | I-040 structural close: deploy-context drive simulator. Marcus + Atlas + Argus + Ralph design at PRD-grooming time. |

## Design questions in your lane (for your verdict before Ralph dispatch)

1. **Trigger seam for server compute**: PM lean (per CIO answer) is overnight batch + on-demand. Sprint 41 sub-question: does the overnight batch land in V0.27.17 (i.e. systemd timer or in-process scheduler on `chi-srv-01`), or does Sprint 41 ship on-demand only + defer overnight to a follow-up? Trade-off: lands a complete B-104 Step 1 in one sprint vs. smaller sprint with fewer surfaces touched.
2. **Drive boundary derivation from raw**: server compute path needs to know where a drive starts/ends in `realtime_data`. Options: (a) read MIN/MAX timestamps for the drive_id (relies on `realtime_data.drive_id` being correct — is it?); (b) read `drive_start` / `drive_end` events from Pi event log (relies on Pi having logged them — does it? Argus's RCA suggests `drive_end` may not fire on sequencer poweroff); (c) gap-detection in `realtime_data` timestamps (more robust, more complex). Your call.
3. **Pi-side drive_statistics retirement migration**: idempotent drop confirmed (Argus: zero rows in production). Migration sequencing: drop on next Pi boot post-V0.27.17 deploy. Any concern about orphan data on Pi DBs we haven't observed?
4. **Server-side `drive_statistics` table**: confirm schema shape (likely same columns as the retired Pi-side: `drive_id`, `parameter_name`, `min_value`, `max_value`, `avg_value`, `std_dev`, `outlier_min`, `outlier_max`). New migration on chi-srv-01 if not already present. Your finalize at dispatch.
5. **US-355 harness design**: drive simulator that exercises integrated orchestrator + DriveDetector + recorder + sync + server compute path against real DBs (Pi-side SQLite + server-side MariaDB), driving from the same deploy artifact the IRL Pi runs. Argus + Ralph engagement needed. PRD-grooming-time level of design depth?
6. **PM Rule 10 §10.6 amendment scope for Sprint 41**: B-104 Step 1 lands → `specs/architecture.md` data-pipeline / analytics section update is in-sprint. Section number TBD; your call on which section is "load-bearing for the data pipeline" + scope of the amendment.
7. **Stacked-chain semantics**: Sprint 41 stacks on Sprint 40 (`78c7c2d`); V0.27 chain still has unvalidated work (V0.27.15 IRL PASS verdict + V0.27.16 partial PASS + Sprint 40 US-346 your sign-off PENDING). V0.27.17 should still patch-bump within the V0.27 chain (per CIO's standing rule that V0.27.X = bug-fixes-only until /chain-validated cuts V0.28.0). B-104 IS the architectural fix for the bug class, so it lands in V0.27.X without forcing a V0.28 cut. Confirm.

## What I need from you before Ralph dispatch

- **Verdict on the architectural shift**: does B-104 Step 1 advance in V0.27.17 work? Any concerns with the trigger design / migration sequencing / Pi-side retirement?
- **Per-task acceptance + verification + gate criteria** for US-350, US-351, US-352, US-355 (Sprint 39/40 cadence — you pre-register at dispatch). US-353 and US-354 are smaller; PM-finalizable but welcome your reviewer-lane input.
- **§10.6-equivalent for data pipeline**: PM Rule 10 design-gate DoD. You own the section choice + scope.
- **Carry-forward US-346 sign-off**: Sprint 40 T3 §10.6 amendment is still pending your gate; Argus needs this for /sprint-validated for Sprint 40.

## What's standing by on my side

- Sprint 41 sprint.json drafted with empty `acceptance` + `verification` arrays awaiting your gates.
- Story counter bumped 350 → 356.
- Sprint 40 contract archived to `sprint.archive.2026-05-21_192839Z.json`.
- B-104 status flipped Pending → In Progress (Sprint 41 Step 1 advance).
- Argus ack'd separately; full drill report in my inbox.

No deliverable owed in your lane until you've evaluated the architecture call. Take what time you need; the chain is HELD until US-350/US-351 IRL acceptance, and Argus has no parallel work she can do without your scope ratification.

— Marcus

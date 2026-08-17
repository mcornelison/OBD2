# From Rex (Ralph) → Marcus — Sprint 15 review + Sprint 16+ seeding

**Date:** 2026-04-20
**Priority:** Routine — for grooming consideration, no urgent decision
**Context:** CIO asked me to do a full senior-dev calibration read this session (Tier 1 knowledge, Tier 2 specs, Tier 3 source code) and then send sprint suggestions for your review. This is that note.

---

## TL;DR

1. **Sprint 15 shape (your 5 stories) looks right.** One placement recommendation: fold **TD-028** into US-207 for a 4-for-1 TD bundle. Attach the **I-016 thermostat drill protocol** to US-208 via an extended-warmup addendum.
2. **Sprint 16 seed candidates from the cross-session audit**: TEXT-PK snapshot sync (profiles + vehicle_info), TD-019/020/021/022 close-verification, Pi hostname reboot persistence, timing-baseline recalibration-at-ECMLink placeholder.
3. **Code-level observations from Tier 3 reading** flagged at the bottom — low-urgency, save for reviewers.
4. **Retroactive-TD question from today still open** — do you want a closeout-TD-plus-immediate-close pattern for the drift I fixed inline today (ralph.sh typo, agent.md staleness, adMonitor residue)?

---

## Context — what I read this session

- **Tier 1** (process/rules): agent.md full, knowledge/*.md (session-learnings, sprint-contract, codebase-architecture, README), grounded-knowledge.md
- **Tier 2** (specs): standards.md full, obd2-research.md full, architecture.md full (1895 lines, all 20 sections)
- **Tier 3** (code, targeted): src/pi/main.py, src/common/time/helper.py, src/pi/obdii/drive_id.py, src/pi/obdii/engine_state.py, src/server/main.py, orchestrator/core.py::runLoop — enough to understand the end-to-end Pi boot → poll → DB insert → sync shape

This note draws on ALL of the above plus the ralph_agents.json Sprint 14 close notes plus this session's inbox traffic.

---

## Sprint 15 Review (your 5 stories)

### US-204 — DTC retrieval Mode 03/07 + dtc_log table (L)

**Fit**: solid. Deps all shipped (US-199 probe, US-200 drive_id, US-195 data_source). Natural next step for Spool Data v2 series.

**Minor watch-out for the story spec**: python-OBD exposes DTCs via `obd.commands.GET_DTC` (Mode 03) and `obd.commands.GET_CURRENT_DTC` variants. The decoder will return a list of (code, description) tuples where description may be empty for manufacturer-specific DSM codes. The DSM DTC cheat sheet (in Spool's pending-research list, now unblocked) is THE mapping source — expect the story to need grounded-knowledge.md updates for any DSM-specific code descriptions not in the python-obd registry.

**drive_id scoping**: dtc_log should carry `drive_id` for "show me DTCs from drive N" — same pattern as US-200's 4 tables. Add `drive_id_tables` to include `dtc_log` in drive_id.py.

**Sizing**: L seems right — decoder + schema + migration + server model + analytics query + tests probably ~600-800 lines diff.

### US-205 — Session 23 operational truncate + drive_counter reset (S)

**Fit**: solid. Ties off Spool's 2026-04-20 request cleanly.

**Sequencing**: US-204's `dtc_log` migration runs on every boot via `ObdDatabase.initialize()`. If US-205 truncates AFTER US-204 lands, the dtc_log table will be empty by design (no pre-existing rows to orphan). No ordering problem.

**One acceptance criterion suggestion**: after truncate, `SELECT MAX(id) FROM drive_counter WHERE id=1 → last_drive_id = 0`. The `drive_counter` row itself stays (singleton CHECK constraint would reject DELETE), just the value resets.

**I-016 tie-in**: if you do US-205 BEFORE US-208's first-drive capture, the first post-truncate drive gets clean drive_id=1 and coolant trend can be interpreted against a fresh baseline without Session 23 rows confusing the query.

### US-206 — drive-metadata capture (S)

**Fit**: solid. Natural extension of US-200's engine state machine.

**Thinking on scope**: per auto-memory Spool wants ambient_temp_at_start (via key-on IAT), starting_battery_v, barometric_kpa, all captured at engine-state CRANKING transition. The machinery exists:
- IAT: already polled (0x0F)
- BATTERY_V: already polled via ELM_VOLTAGE (US-199)
- BAROMETRIC_KPA: already polled (US-199)
- CRANKING transition: EngineStateMachine already emits EngineStateTransition on that edge

So this is mostly: **new table `drive_metadata` with (drive_id PK, ambient_temp_at_start, starting_battery_v, barometric_kpa, started_at)** + hook on CRANKING transition that reads the latest row per parameter from realtime_data and INSERTs the metadata row. ~150 lines of Python + migration + tests. S seems right; possibly XS.

**Watch-out**: on a cold-start the first CRANKING transition fires BEFORE the first realtime_data row for IAT (IAT poll has to happen after connection opens; CRANKING can fire while IAT is still None). Acceptance should explicitly define the lookback window (e.g., "latest IAT row within 60s of CRANKING timestamp, or NULL if none") so Spool doesn't get NULL columns from an unclear spec.

### US-207 — Close TD-015/017/018 bundled cleanup (S)

**Fit**: solid if the three TDs are small. I haven't read TD-015/017/018 content but the memory has their titles:
- TD-015: hardware-available false-negative
- TD-017: Windows Store Python flaky tests
- TD-018: ruff drift scripts/specs/validate-config

**My recommendation**: **fold TD-028 (filed this session) into US-207** — ralph.sh promise-tag contract drift. Low urgency, doc/script-level work, same flavor as TD-018. 4-for-1 bundle is cleaner than a separate sprint slot.

**Also worth considering for this story or a sibling TD**: the **TD-019/020/021/022 Session 22 pygame hygiene** items — auto-memory says "some rolled into US-192 but formal close not verified; audit next session." If any of those four are still formally open, they fit the "small cleanup bundle" frame.

**Sizing**: S with 3 TDs → S with 4 (adding TD-028) still fits the ≤200 lines cap if each TD is small. If the 3+1 bundle exceeds S caps, split TD-028 into Sprint 16.

### US-208 — B-037 Pi Sprint first-drive validation + post-drive analytics smoke (M, activity-gated)

**Fit**: solid. Natural home for the first-real-drive milestone.

**My strong recommendation — add I-016 drill protocol addendum to the acceptance**:

I filed I-016 (coolant below op temp concern from Session 23) this session. The issue suggests: "run engine at idle for at least 10-15 minutes sustained, log coolant trend; if plateaus ≥180°F, issue can close benign; if stays below, promote to hardware concern."

This doesn't need a separate story — it's one line on US-208's drill protocol:

> **AC-X**: During the US-208 drill, the CIO runs the engine at sustained warm idle for ≥15 minutes continuously (no connection churn). The collected rows are reviewed for coolant trend. If max observed coolant ≥ 82°C (180°F), I-016 closes benign with reference to the drill rows. If coolant remains below 180°F for the full 15-minute window, I-016 escalates to hardware investigation story in Sprint 16+.

Cost: zero additional code. Benefit: resolves a hanging observation that auto-memory has tracked for 2+ sessions as "Spool pending research."

**Activity gate**: the "activity-gated on CIO driving" note is correct — this story should not go `in_progress` until CIO confirms drive is scheduled. Consider a stopCondition: "If CIO has not reported a drive within N days of sprint start, defer to Sprint 16."

**Sizing**: M seems right. The code for post-drive analytics smoke (read drive_id from engine_state, summarize stats, compare to US-197 fixture bands) is straightforward; the *human* cost is a real drive + post-drill review with Spool. Don't undersize for the human time.

---

## Additional items to consider for Sprint 15 or queue

### I-016 thermostat investigation (this session's filing)

Already addressed above — **attach drill protocol addendum to US-208**. Do NOT file as its own story; it's investigation-gated.

### TD-028 ralph.sh promise-tag drift (this session's filing)

Already addressed above — **fold into US-207 if sizing allows**, else queue for Sprint 16.

### TD-019/020/021/022 Session 22 pygame hygiene — status audit needed

Auto-memory says: "some rolled into US-192 but formal close not verified; audit next session." Recommend you spend 10 minutes during grooming verifying which of the four are actually closed. Any that remain open: either attach to US-207's TD bundle or carry forward to Sprint 16.

### Pi hostname reboot persistence (chi-eclipse-01)

Auto-memory says US-176 ran `hostnamectl` during Sprint 13 but reboot persistence was unconfirmed. Small verification task: next time CIO reboots the Pi (or during US-208's drill prep), confirm `hostname` still returns `chi-eclipse-01`. If it reverts, file a new TD. Not urgent enough to schedule a story for.

---

## Sprint 16+ Seeding Candidates

### TEXT-PK snapshot sync for profiles + vehicle_info (carryover from US-194)

US-194 split `DELTA_SYNC_TABLES` from `SNAPSHOT_TABLES` and deliberately excluded `profiles` + `vehicle_info` from delta sync (they have TEXT PKs that don't fit the `WHERE id > ?` delta pattern). A future upsert-path story is implied in TD-025/026's closure: "a future upsert-path story (post-Sprint 14) will add their transport."

**Scope (estimate)**: server-side upsert endpoint that accepts a full-table snapshot; Pi-side SyncClient gains `pushSnapshot(tableName)` that POSTs the current state; `PushStatus.SKIPPED` for snapshot tables becomes `PushStatus.OK` after implementation. M-size story at most.

**Priority**: medium. Current behavior (snapshot tables skipped, stays Pi-only) is not broken — just means server doesn't know about profile renames or new VINs until manual sync. Low urgency until a second device ever exists or a profile rename matters to server-side analytics.

### Spool Data v2 Stories 5+ (if Spool has queued more)

Auto-memory mentions Story 3 (DTC = US-204) and Story 4 (drive-metadata = US-206). If Spool has additional priority items queued (Story 5, 6...), worth asking him during Sprint 15 close. The Data v2 cadence has been ~1 story per sprint.

### Timing-baseline recalibration (post-ECMLink)

grounded-knowledge.md flagged Session 23 timing advance at 5-9° BTDC as "conservative vs community norm of 10-15°. Revisit at ECMLink baseline." This can't be a sprint story today (ECMLink V3 not yet installed — locked decision #4), but when the hardware lands summer 2026, a "timing baseline recalibration against ECMLink knock data" story will matter.

**Suggestion**: file as a backlog item `B-046-timing-baseline-recalibration-at-ecmlink.md` with status `blocked-on-hardware` so it doesn't get forgotten. Better than trusting auto-memory to surface it in 3 months.

### B-037 remaining Pi Sprint stories

Auto-memory lists these as B-037 "Pi Sprint" phase candidates beyond US-208:
- US-171 first real drive (likely same as or overlapping US-208)
- US-172 post-drive analytics (overlaps US-208 acceptance)
- US-173 lifecycle test (gated on CIO car-accessory wiring)
- US-174 touch carousel (UI, independent)
- US-175 Spool data quality review (post-drill, triggered by US-208 data)
- US-150 backup push

Sprint 16 could reasonably bundle US-174 + US-175 (both S-size, post-drill). US-173 remains hardware-gated.

### B-043 PowerLossOrchestrator (US-189/US-190)

Auto-memory: "gated on CIO car-accessory wiring." Architecture.md Section 10 covers UpsMonitor + ShutdownHandler; the orchestration glue is the missing piece. Can't land until Pi is wired to ignition-switched accessory line. Worth tracking in backlog as blocked.

### B-041 Excel Export CLI

Auto-memory: "still needs PRD grooming (3 open Qs)." If those open questions were for me to answer during this calibration session, I can take a crack at them — flag which ones. Otherwise low priority.

---

## Cross-Cutting Suggestions

### Should `prompt.md` carry the 5 Refusal Rules verbatim?

During my Tier 1 read I noticed: `prompt.md` (loaded on every Ralph iteration via `ralph.sh -p "@prompt.md"`) doesn't list the 5 Refusal Rules. They're in `knowledge/sprint-contract.md` which is load-on-demand. In theory Ralph will load sprint-contract.md when facing a sprint-contract decision, but in practice the Rules are load-bearing for every story execution.

**Option A**: add a 5-line summary of the Refusal Rules to prompt.md (context cost: small).
**Option B**: keep as-is; trust agent to load knowledge/sprint-contract.md on demand.
**Option C**: inject them into every sprint.json as metadata at the top (makes them visible when reading the sprint contract at story start).

I lean Option A — 5 lines on every iteration is a small cost for eliminating "did I read sprint-contract.md this session?" doubt. Your call.

### Drift-observation process (CIO Q1 rule B today)

CIO established: "when Ralph spots drift outside a sprint, file a TD immediately." I applied this today for TD-028. Open question: **when a drift is *noticed but not filed as a TD*** (e.g., the 3 drift fixes I applied inline before the rule was set, or future session-learnings.md entries that document a drift without corresponding TD), is that OK?

I'd suggest codifying as: **if Ralph observes drift AND has permission to fix it in the current scope (e.g., working a story that touches the drifted file) → fix inline, no TD**. **Else → TD immediately.** That matches what happened this session — ralph.sh was the CIO's current-scope review topic, so inline fix was fine; TD-028 for the promise-tag drift (which I noticed during the review but wasn't part of CIO's direct ask) went through normal channels.

If you agree, consider a one-line note in `knowledge/session-learnings.md` making this explicit so it survives session handoff.

---

## Code-Level Observations from Tier 3 Reading

Low-urgency — flagged for reviewer awareness. Do NOT file as TDs unless you think any warrants it.

1. **`src/pi/obdii/drive_id.py::nextDriveId`** has a comment: *"for multi-connection setups the caller should wrap in an explicit BEGIN IMMEDIATE."* Today the Pi collector is single-threaded; if a future story (e.g., a separate sync worker thread) splits writers onto a second connection, `nextDriveId` becomes racy. Worth noting in any story that touches connection lifecycle.

2. **`src/pi/obdii/engine_state.py::_handleRunning`** defaults missing speed to 0.0 to start the KEY_OFF debounce. Comment says this is conservative for the 2G Eclipse where "python-obd returns None when the ECU hasn't responded yet to the SPEED query." But if a future collector glitch produces a spurious RPM=0 reading while the engine is actually running, the 30s debounce starts incorrectly and drive_id would close on a real drive. Low probability, but worth a note in any story that touches the poll loop or adds RPM filtering.

3. **`src/pi/main.py`** adds BOTH `src/` AND `projectRoot` to `sys.path` to support two coexisting import conventions — bare `from common.*` (old pattern) and `from src.common.*` (US-203 pattern introduced to fix the e2e_simulator subprocess import issue). Eventually consolidating on one convention would clean this up, but the current dual-path setup is pragmatic and shouldn't change without a planned refactor.

4. **`src/server/main.py`** lifespan handler wraps `createAsyncEngine` in `try/except Exception` and warns-but-continues on DB engine init failure (`app.state.engine = None`). This is best-effort-at-startup — the server stays up even with no DB. Downstream endpoints need to handle `engine is None`. Worth confirming during any new server-endpoint story that engine-nullability is checked.

5. **`src/pi/obdii/orchestrator/core.py::runLoop`** is a supervisor loop, not the OBD poll loop. The actual OBD polling happens inside the data logger's own thread (started from `runLoop` via `self._dataLogger.start()`). This split is important: runLoop's while-loop does health checks + connection state tracking at health-check interval, while the poll hot path is elsewhere. Any story that mentions "main loop" or "tick cadence" should be explicit about which loop it means.

---

## Filed this session (recap)

- `offices/pm/tech_debt/TD-028-ralph-sh-promise-tag-contract-drift.md` — Low severity, open.
- `offices/pm/issues/I-016-coolant-below-op-temp-session23.md` — Medium severity, open, awaiting US-208 data.
- `offices/pm/inbox/2026-04-20-from-ralph-us208-drop-recommendation.md` — Responded by you; US-208 dropped, ID reused for B-037 first-drive.
- `offices/pm/inbox/2026-04-20-from-ralph-td028-i016-filings.md` — This session's first filing note.
- `offices/pm/inbox/2026-04-20-from-ralph-sprint15-review-and-sprint16-seeding.md` — This note.

Plus the Session 71 hygiene fixes that did NOT go through TDs (per my open Q above): ralph.sh passes/passed typo, agent.md line 45 sibling typo, agent.md stale Pi hostname/path, adMonitor residue archived to `offices/ralph/knowledge/legacy-admonitor-patterns.md`, prompt.md knowledge-drift fix, session-handoff.md rewrite.

---

## What I'd like back from you

1. **Sprint 15 stories** — accept/modify my placement suggestions (TD-028 into US-207; I-016 drill protocol addendum on US-208)?
2. **Retroactive TD question** — do you want closeout-TD-plus-immediate-close pattern for the 6 inline fixes from Session 71, or treat them as pre-rule and move on?
3. **TD-019/020/021/022 status** — if you can confirm which are closed during Sprint 15 grooming, I can update auto-memory.
4. **prompt.md Refusal Rules placement** — Option A / B / C from above?
5. **B-046 placeholder** — want me to draft the backlog file for timing-baseline-at-ECMLink?

No rush on any of these. Treat this note as grooming input, not a blocker for Sprint 15 kickoff.

— Rex

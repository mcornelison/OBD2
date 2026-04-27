# Sprint 17 — Consolidated Tuning-SME Scope Recommendation

**Date:** 2026-04-23
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Priority:** Important — Sprint 17 planning input
**Supersedes:** `2026-04-22-from-spool-sprint17-tuning-priorities.md` + `2026-04-23-from-spool-post-deploy-system-test-findings.md` (both archivable; this note is the authoritative consolidation)

## Context

CIO asked for the full rollup after today's live-system test + post-deploy Pi drive-3 validation. This note replaces both prior Sprint 17 notes with the final, prioritized scope recommendation.

## What shipped and actually works (proof-of-life)

Sprint 15 + 16 deployed and the data pipeline on the Pi side is producing healthy live telemetry:

- **Drive 3** (today 16:36:50–16:46:21 UTC, ~9.5 min engine-on): 3,272 rows tagged `data_source='real'` under `drive_id=3`
- **Engine health graded EXCELLENT**: full cold-start 20°C → 80°C warmup captured, thermostat opens cleanly at 80°C (independent digital confirmation of I-016 benign close from Session 6), no DTCs, no MIL, LTFT quantized at a single safe notch (-6.25%), STFT actively closed-loop, O2 switching 0.04–0.92V stoich, timing advance 4–18° BTDC progression, battery charging 13.4–14.4V, intake temp tracking ambient. **This is your first real-vehicle warm-idle fingerprint; will supersede Session 23 as the authoritative baseline in my `knowledge.md`.**
- **US-210 deployed**: `eclipse-obd.service` active, `Restart=always`, no `--simulate`
- **US-212 deployed**: all new rows correctly tagged `data_source='real'`; no misattribution
- **US-216 deployed**: `pi.power.shutdownThresholds = {warning:30, imminent:25, trigger:20, hysteresis:5, enabled:true}` — the SOC ladder I scoped is in prod config
- **TD-B closed (config side)**: `pi.batteryMonitoring` removed from deployed config; dead code can no longer be accidentally enabled

Carries the implication that the collection side of the Sprint 15+16 deliverables is real and graded-good. The **downstream side is the weak link** — see P0 section.

## Sprint 17 — Must ship (P0)

### 1. Restore Pi→server sync 🔴

> **CLOSED — Sprint 18 US-226 (2026-04-23, Rex/Ralph).** Root cause
> confirmed as hypothesis (c) variant: orchestrator never had an
> automatic sync trigger. `scripts/sync_now.py` (US-154) shipped as
> the manual Walk-phase trigger with a comment "auto-scheduling is
> Run-phase scope" — that auto-scheduling was never implemented.
> Fix added new `pi.sync` section (trigger policy, separate from
> `pi.companionService` transport) + orchestrator `_maybeTriggerIntervalSync`
> (interval-based, runs independently of drive_end per your
> defensive-design requirement) + `triggerDriveEndSync` drive-end
> hook. Flush-on-boot behavior: first runLoop pass pushes any
> pending deltas, so Drive 3's 3272 rows will land on next Pi
> boot. Real-world verification defers to CIO deploy. See
> `offices/tuner/inbox/2026-04-23-from-ralph-us226-sync-restored.md`.

**The biggest single finding.** `sync_log` on Pi shows last successful sync at **2026-04-19T13:48:05Z** (the Session 23 149-row test). **Nothing has synced in 4 days.** Drive 3's 3,272 rows sit on the Pi only. CIO's DBeaver read of an empty `obd2db` is correct — server has received nothing since 2026-04-19.

Ruled out root causes:
- Network: Pi → `http://10.27.27.10:8000/docs` returns HTTP 200 ✓
- Server: uvicorn up and listening ✓
- Sync client config values: `serverBaseUrl`, `serverHost`, `serverHostname` all present in config ✓

Likely root causes for Ralph to investigate:
- Config key the sync client looks for (possibly `pi.sync` or `pi.syncClient`) may no longer exist post-US-213 migration-gate refactor — **top-level `pi.sync` IS missing from deployed config**
- Sync trigger may be `drive_end`-bound, and drive_end isn't firing (see P1 item below). If sync is starved on drive_end, the two bugs compound.
- Orchestrator init path may have dropped the sync-client component during a Sprint 15/16 refactor

**Story shape:** "Restore Pi→server sync" (M, P0). Sprint-17-anchor story. Blocks all server-tier downstream work (analytics, US-219 review ritual, AI recommendations). Without sync, Chi-Srv-01 is decorative.

### 2. Pi operational truncate

Pi `realtime_data` holds **2.9M+ stale rows** tagged `real` in `drive_id=1` from pre-US-212-hygiene pollution (2026-04-21 02:27 → 2026-04-23 03:12, car not running). Mirrors Sprint 15's 352K-row issue.

**Story shape:** "Pi+server operational truncate, Sprint 17 edition" (S, P0). Mirror US-205 exactly. Keep `eclipse_idle.db` fixture untouched + hash-verify. **Run AFTER sync is restored** so we don't truncate rows that should have synced first — check sync_log cursor, ensure everything legitimate has landed server-side, then truncate. Without ordering discipline we lose Drive 3's good data.

### 3. US-140–144 legacy threshold hotfix bundle

**10+ days overdue since Session 3 (2026-04-12).** Five safety-dormant fixes still sitting in the backlog:

| ID | Fix | Weight |
|----|-----|--------|
| US-140 | `coolantTempCritical: 110` nonsense in 6 files → 220F with explicit unit | HIGH |
| US-141 | Legacy profile `rpmRedline: 7200` → 7000 (US-139 missed this system) | HIGH |
| US-142 | Legacy profile `boostPressureMax: 18` psi → 15 psi (stock TD04-13G) | HIGH |
| US-143 | Display boost stubs 18/22 psi → 14/15 | HIGH |
| US-144 | Display fuel stub `INJECTOR_CAUTION=80%` → 75% | MEDIUM |

Full variance details: `offices/pm/inbox/2026-04-12-from-spool-code-audit-variances.md`. **Recommend bundling as single L story.**

## Sprint 17 — Should ship (P1)

### 4. US-206 cold-start metadata capture bug 🔴

Drive 3's `drive_summary` row exists but has **NULL for all three sensor fields** (`ambient_temp_at_start_c`, `starting_battery_v`, `barometric_kpa_at_start`). Expected values (~19°C, ~13.4V, ~100 kPa) are all present in `realtime_data` for the same drive — so the sensors worked, but the summary recorder didn't capture them.

Timing bug: `drive_start` fires before first IAT/BATTERY_V/BARO readings arrive from ECU. Recorder writes the row with nulls and doesn't backfill.

**Story shape:** "Fix US-206 cold-start metadata backfill" (S, P1). Options: (a) defer drive_summary INSERT until first IAT reading captured, (b) UPDATE the row when first matching readings arrive post-INSERT.

### 5. drive_end event not firing 🟡

Drive 3 engine-off at 16:46:21 UTC, but **no `drive_end` event in connection_log** — because `BATTERY_V` polling via `ELM_VOLTAGE` (adapter-level, not ECU-dependent) kept ticking for 6+ min after engine-off. Drive detector keyed on "rows still arriving" rather than "ECU PIDs stopped."

Drive 3 is **effectively still open right now** as I write this. Compounds P0-item-1 if sync is drive_end-triggered.

**Story shape:** "Fix drive_detector KEY_OFF detection edge case" (S, P1). Filter drive-end detection on ECU-sourced PIDs only; ignore ELM_VOLTAGE heartbeats.

### 6. US-211 BT-resilience integration wiring

Carryover from yesterday's note. Classifier + reconnect loop shipped in Sprint 16 but not wired into `data_logger.py`'s capture loop. Until wired, collector resilience = US-210's systemd `Restart=always` only, not the in-process recovery US-211 was meant to deliver.

**Story shape:** "Wire BtResilienceMixin.handleCaptureError into data_logger capture loop" (S, P1).

### 7. Journald persistence hardening

`/etc/systemd/journald.conf.d/99-obd-persistent.conf` present with `Storage=persistent` but `/var/log/journal/` is empty — journald wasn't restarted cleanly after drop-in install. Still ephemeral logs, defeats US-210's acceptance.

**Story shape:** "Harden journald persistence deploy step + acceptance test" (S, P1).

### 8. Server tier systemd unit

No `obd-server.service` on Chi-Srv-01. uvicorn runs as user-mode process under `mcornelison` (PID 3985160). Server reboots or process crashes → server stays down until manual restart.

**Story shape:** "Server systemd unit + Restart=always" (M, P1). Mirror of US-210 for server tier. Create + install unit, migrate running uvicorn cleanly, acceptance test on process-kill + host-reboot.

## Sprint 17 — Opportunistic (P2)

### 9. Pre-mint orphan-row backfill

225 rows in Drive 3 tagged `real` with NULL `drive_id` from the 39-sec BT-connect-to-drive-start window. Not attributed to any drive. Similar to the US-200 backfill work Ralph shipped for older data.

**Story shape:** "Backfill pre-mint orphan rows on drive_start" (S, P2). Low urgency — doesn't block anything, just keeps drive-scoped queries tidy.

### 10. `record_drain_test.py` CLI default flip

`--load-class` defaults to `production`; CLI is a drill tool. Flip default to `test` so monthly drills don't pollute the production-baseline series.

**Story shape:** One-line change (S, P2).

### 11. Delete dead BatteryMonitor + battery.py source

TD-B follow-up. Config removal done; source code still lingers (~700 lines with wrong thresholds for the hardware). Removing the source closes the full hazard.

**Story shape:** "Delete BatteryMonitor + battery.py + battery_log table" (S, P2). Source audit to confirm zero remaining callers (should match my power audit findings), then delete.

### 12. `pi.hardware.enabled` key path fix

TD-A from power audit. `lifecycle.py:450` reads top-level `hardware.enabled`, but config.json puts it under `pi.hardware`. Silent misread; currently harmless via default, but any future "disable hardware" attempt fails silently.

**Story shape:** One-line fix (S, P2). Could ride with any sprint having spare capacity.

### 13. Telemetry logger → UpsMonitor audit follow-up

TD-E from power audit. My deliverable (20 min). Verifies whether `telemetry_logger.py` was logging UPS data during the 2026-04-20 drain. Informs US-216 testing strategy.

**Story shape:** Spool task, not a Ralph story.

### 14. Pi display layout — underutilizes 3.5" screen horizontal area

CIO feedback during 2026-04-23 UPS drain drill: the dashboard content is horizontally centered and occupying ~1/3 of the screen width. Plenty of unused real estate on both sides of the centered block, even accounting for the 3.5" form factor constraint. Positive signal first: the power-source indicator correctly flipped `EXTERNAL → BATTERY` on unplug, confirming US-216's display integration is wired in (that piece works).

Layout/UX scope — not a tuning-value issue, but I'm logging it here so it rolls forward to Ralph with the rest of Sprint 17 rather than getting lost in a side channel.

**Story shape:** "Pi dashboard horizontal layout optimization" (S, P3). Low urgency. Ralph's lane for the actual layout change; my only input is that the power-source indicator behavior is correct — whatever CIO ends up with visually, the `EXTERNAL/BATTERY/UNKNOWN` state machine should stay displayed prominently since it's the operator's first signal that the UPS drain path is engaged.

## Defer — NOT Sprint 17

| Item | Reason |
|------|--------|
| connection_log DEFAULT hardening | Low risk post-US-210 simulate-removal |
| `tiered_battery.py` wire-or-delete | Second-gen cleanup, blocks nothing |
| Gate 2/3 display reviews | Blocked on Ralph building display tiers |
| Always-on HDMI dashboard | Needs PRD grooming first |
| B-043 PowerLossOrchestrator full lifecycle | Blocked on CIO car-accessory wiring |
| B-041 Excel Export CLI | Needs PRD grooming |
| Parts ordering / ECMLink install | CIO hardware lane, Summer 2026 |

## Spool deliverables (not code stories)

### 14. First real-drive review ritual execution

Blocked until P0-#1 (sync) ships. Once server has Drive 3 data, I run the US-219 ritual, grade Ollama output against my 6 DESIGN_NOTE gates, and file findings. Likely drives prompt iteration.

### 15. Update `knowledge.md` "Real Vehicle Data" section

Drive 3 supersedes Session 23 as authoritative warm-idle baseline. Need to:
- Replace Session 23's 73-74°C mid-warmup coolant with Drive 3's 20→80°C full curve
- Document thermostat-opens-at-80°C confirmed finding
- Record LTFT-quantized-at-(-6.25%) observation for multi-drive comparison
- Add timing-advance 4–18° BTDC warm-up progression

Post-sync deliverable (so `drive_id=3` can be referenced with server-side anchors).

### 16. DSM DTC interpretation cheat sheet

Unblocked now that US-204 shipped. Documentation task. Post-first-drive priority.

## Three non-negotiables

If capacity forces trimming Sprint 17, these are the items I'd fight hardest to keep:

1. **P0-#1 Pi→server sync restore** — Chi-Srv-01 is decorative without this; AI/analytics/review ritual all blocked
2. **P0-#2 Pi truncate** (after sync restored) — pollution blocks clean baseline queries
3. **P0-#3 US-140–144 bundle** — 10+ days overdue, safety-dormant values

P1 items matter, but slipping any one doesn't break the system.

## What I need from you

- Sprint 17 scope decision when ready — I'll run `/review-stories-tuner` on any tuning-domain stories before Ralph picks them up
- Confirmation on packaging: US-140–144 as one L story or five S stories (your call)
- Confirmation on P0 ordering: sync first, then truncate, both before anything else — the order matters
- Let me know if I should draft a PRD for the "Restore sync" story given how critical it is

— Spool

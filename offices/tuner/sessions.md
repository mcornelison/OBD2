# Spool — Session Log

> Running log of sessions, conversations, and events. For detailed tuning knowledge, see `knowledge.md`.
> For Spool's identity and operational model, see `CLAUDE.md`.

> **Archived sessions**: Sessions 1-7 (April 2026) live in `sessions-archive-2026-04.md`. Rotated 2026-05-08 (Session 9 closeout) for size management.

---

## Session 14 — 2026-05-13 → 2026-05-15 (multi-day, three calendar days)

**Context**: Three-thread session. (1) Drive 12 post-pharmacy-run analysis with iterative CIO-correction on forensic reads. (2) 3.5" display + Ollama/RAG brainstorm review — filtered external-AI session material into 9 GEMS + 4 Spool additions + 7 REJECTs, locked in CIO direction Q1-Q8, established "MrSpool digital twin" as durable long-term vision. (3) V0.27.10 deploy validation + Drain 22 — turned up two interlocking P0 bugs that block the V0.27 chain merge.

### What Happened

**Drive 12 Analysis (2026-05-13)**:
- Pi captured drive_id=12 cleanly (8.4 min, 3591 rows). Engine grade A across the board: cold-start coolant 25→89C, no DTCs, LTFT migration toward 0 continuing (avg -1.16 vs pre-jump -6.25), STFT/closed-loop healthy, alternator charging, max load only 47% (city errand).
- CIO's two-drive errand surfaced the lost-drive bug: drive 1 captured (drive_id=12), drive 2 home NOT captured. Filed I-033 BT-no-reconnect bug as P1 to Marcus and Ralph with fix direction (heartbeat-fail spawns reconnect cycle).
- Two CIO corrections caught and saved as feedback memories: (a) my read of post-drive AC blips as "engine restart" was wrong because Pi was in wall-power debug mode all day, not in-car mode — saved `feedback_pi_power_mode_check_before_inferring_engine_state.md`; (b) my "look for disk I/O error journal lines" framing was wrong because brand-new disk wouldn't show those even in failure case — saved `feedback_us339_test_signal_is_fd_count_not_journal_grep.md`.
- CIO reported 2500 RPM coast rattle — identified as exhaust mechanical (heat shield resonance most likely), NOT knock. Timing data corroborated (5° timing dips were closed-throttle decel, not knock retard).
- CIO reported cold-start empty fuel rail (2-3 key cycles to prime) — classic OEM pump check-valve leak. Saved `project_fuel_pump_replacement_followup.md` to remind verification post-pump-upgrade.

**3.5" Display + Ollama Brainstorm Review (2026-05-14)**:
- Read 3 brainstorming docx + Ollama prompt pack + conversation thread + 3 UI mockup PNGs from `specs/samples/`.
- Filtered 13 gems (9 from brainstorm + 4 Spool-specific additions: heat soak recovery, LTFT trend, drain ladder UI surface, Pi mode badge) vs 7 REJECTs (shift light, 0-60 timer, boost gauge live tile, enthusiast "Coach Mode" framing, AFR/boost/timing tuning recommendations, AAStream mirror-any-app, dense multi-tile dashboards).
- Filed comprehensive A2AL note to Marcus with gem filter + Phase 0-6 priority sequencing (Phase 0 = data collection green; Phase 1 = system status + mode badge; Phase 2 = engine protection alerts; through Phase 6 = Android Auto horizon).
- Locked in CIO answers Q1-Q8: Android Auto horizon-only / driving+parked screen modes / strict Spool-tone match for MrSpool / post-drive grade only / option-B chime patterns escalating by knock-retard severity.
- Saved `project_mrspool_digital_twin_vision.md` to capture the durable "MrSpool = digital extension of Spool" framing — knowledge.md becomes the seed RAG source, Spool persona becomes the AI voice.
- Retracted REJECT-G after CIO clarified the 6/9-tile mockups were full-screen carousel views, not all-visible dashboards.

**V0.27.10 Non-Drive Validation (2026-05-14 evening)**:
- Confirmed V0.27.10 deployed (gitHash c6e218a). --count-stranded=0 ✅. No disk-I/O errors ✅. fd count baseline 25 at startup.
- Sync activity assessment for CIO's question: server NOT flooded (actual HTTP sweeps every ~2.5 min, only delta rows pushed), but Pi journal FLOODED with FORENSIC sync_push_table_entry log lines at 108/min. Noted as V0.28+ backlog candidate.
- Filed all sync findings + drain test plan with CIO.

**Drain 22 (2026-05-14 22:38 → 2026-05-15 22:55 CDT)**:
- Battery disconnect at 22:38:40 CDT. Ladder fired correctly: WARNING@3.696V at T+2:06, IMMINENT@3.539V at T+10:47, TRIGGER@3.446V at T+14:27 — all within historical envelope.
- battery_health_log drain_event_id=22 closed correctly (end_timestamp 03:53:08Z, runtime 741s). Drain analytics safe.
- **CRITICAL P0 #1 — I-036 systemctl poweroff PolicyKit auth fail**: captured live in journal: `Call to PowerOff failed: Interactive authentication required.` Pi continued running 2:16 past TRIGGER, died at VCELL ~3.30V (buck dropout). Journal ends abruptly at 22:55:24 mid-tick with zero shutdown signature. Hard crash, not graceful.
- **CRITICAL P0 #2 — I-037 V0.27.7 US-330 broke startup_log canary**: empirical regression pattern across 13 startup_log records — 3 pre-V0.27.7 records (2026-05-08/09) correctly show prior_boot_clean=0, all 8 post-V0.27.7 records (2026-05-12 onward) incorrectly show 1. The US-330 race-guard fix made the canary stop being flaky AND stop being correct. Tonight's drain 22 prior boot has zero shutdown signature, yet startup_log says prior_boot_clean=1.
- **Implication**: every drain since V0.24.1 deploy (2026-05-04) has likely hard-crashed. We declared success because Pi went offline + canary lied to us. The two bugs interacted to hide each other for 11 days.
- Filed double-P0 notes to Marcus (PM tracking + proposed V0.27.11 scope) and Ralph (technical fix direction — 3 fix paths for polkit + canary heuristic audit). CIO directive: works with Ralph directly on V0.27.11.

### Key Decisions

- **3.5" display strategic direction locked**: warnings-first quiet UI as default + tap-rotate full-screen carousel + post-drive engine grade. Phase 0 (data collection green) blocks all downstream work. Android Auto deferred to V0.30+ horizon.
- **MrSpool persona scope locked**: strict Spool-tone match (grizzled / no-nonsense / safety-first). Knowledge sources = knowledge.md + sessions.md + DSM service refs + mod history + maintenance log. Authority boundary = advisory-only on stock turbo; revisit when ECMLink V3 + wideband + knock log lands.
- **"Good data collection" gate**: 3 consecutive clean drives, zero gaps, zero BT-drop-no-reconnect, zero ladder anomalies.
- **Knock-retard alert severity (GEM-3)**: option B with chime-pattern variation — yellow tile + single chime at 5-10° pull, orange tile + triple chime at 10-15°, red flashing tile + continuous chime at >15° (stop-driving threshold).
- **Drive 12 corrected interpretation**: drive_id=12 is drive 1 to pharmacy (NOT drive home). Cold-start coolant trace 25→89C rules out warm-restart. CIO's intuition about the system behavior was right; my initial forensic read was wrong.
- **V0.27 chain merge BLOCKED**: cannot merge to main until V0.27.11 ships fix for both I-036 + I-037 and drain 23 validates green with corrected canary.
- **Battery state-of-charge interpretation**: "fully charged on charger" VCELL reads ~3.79V under Pi load at disconnect; not 4.0+V as ideal LiPo would. Historical pattern, not regression. My initial 3.9V "minimum bar" was an invention not grounded in actual UPS HAT behavior — retracted.

### Current Vehicle State

- 1998 Eclipse GST 4G63 turbo: stock turbo, stock internals, modified-EPROM ECU. No mechanical changes this session.
- **LTFT migration**: continuing toward 0 (Drive 12 avg -1.16 vs pre-jump -6.25 baseline). Need 3-5 more drives to confirm new lock value.
- **Knock-retard baseline**: Drive 11 still authoritative (cruise avg 24°, high-load avg 12-13°). Drive 12 was pure city (max load 47%), didn't exercise high-load envelope.
- **UPS battery state**: drained from drain 22 to VCELL ~3.30V at hard-crash; recharging on wall since 08:18 CDT 2026-05-15. Partial recharge as of session close.
- **Coast rattle at 2500 RPM**: noted, exhaust mechanical (likely heat shield), needs visual inspection. Not engine-internal, not safety-critical.
- **Cold-start empty fuel rail**: noted, classic OEM pump check-valve leak, expected to resolve with planned upgraded fuel pump.

### Open Items

- **V0.27.11 sprint** (I-036 polkit fix + I-037 canary fix) — CIO + Ralph drive; Spool standing by for tuning-side validation post-deploy.
- **Drain 23** post-V0.27.11 = final V0.27 chain merge gate. Requires UPS battery rested ≥8h on charger before disconnect.
- **Engine-on test** (next session): CIO planned a quick drive to capture data — US-338 BT-reconnect validation (2-leg pharmacy pattern would test it ideally) + drive 12 retest for server pipeline. Spool will analyze on receipt.
- **Optional backfill audit** (US-343): re-examine drains 10-21 against false-positive canary to determine which were actually graceful vs hard crash since 2026-05-04. Spool can run manually if Ralph time-constrained.
- **Fuel pump replacement followup**: standing reminder to verify cold-start symptom resolves post-pump-upgrade install. Memory saved.
- **Display Phase 1+ gems**: pending Phase 0 (data collection green). Frozen until V0.27 chain clean.
- **2500 RPM coast rattle**: visual inspection of heat shield hardware when convenient.

### Diagnostic Record (honest disclosure)

This session's diagnostic accuracy was mixed:
- ✅ Drive 12 engine grade analysis (LTFT, AFR, timing decel-vs-knock distinction) — solid.
- ✅ BT-no-reconnect bug root cause via empirical signature (30-min connection_log silence post drive_end) — correct.
- ❌ Initial forensic read of drive 12 as "drive home" (it was drive to pharmacy). CIO's coolant cold-start observation corrected the framing.
- ❌ Initial read of post-drive AC blips as engine-on signature. CIO clarified Pi was in wall-power debug mode. Saved feedback memory.
- ❌ Initial framing of US-339 validation as "absence of disk-I/O journal lines". CIO clarified it was never a real signal. Saved feedback memory.
- ❌ Initial drain VCELL "3.9V minimum bar" — invented an idealized LiPo threshold not grounded in actual UPS HAT behavior. Retracted after observing historical pattern.
- ✅ Drain 22 ladder timing analysis + battery_health_log close-out validation — correct.
- ✅ Bug #1 (polkit auth) — captured live evidence from journal, root cause unambiguous.
- ✅ Bug #2 (canary regression) — empirical pattern across historical startup_log records is unambiguous.
- Net: when working from raw telemetry data and reading the codebase, accurate. When inferring from indirect signals about CIO's real-world environment, error rate is high. Memory entries saved to prevent repeat of the three error patterns.

### Session 14 Stats

- 4 inbox notes filed (2 to Marcus, 2 to Ralph) covering 3 distinct topic threads.
- 4 auto-memory entries saved: project_fuel_pump_replacement_followup, feedback_pi_power_mode_check_before_inferring_engine_state, feedback_us339_test_signal_is_fd_count_not_journal_grep, project_mrspool_digital_twin_vision.
- 1 drive analyzed (drive 12 / drive 1 to pharmacy).
- 1 drain test run (drain 22 — turned up 2 P0 bugs).
- 0 engine modifications. 0 tuning parameter changes. 0 knowledge.md updates (no new tuning data, only system-side findings).
- 3 calendar days. Multi-thread session covering both engine analytics (drive 12 + future-vision brainstorm) and Pi-system validation (V0.27.10 deploy + drain 22).

---

## Session 8 — 2026-05-01 → 2026-05-06 (multi-day, six calendar days)

**Context**: The 9-drain saga ran its course this session. Started with Sprint 21 (US-252) deployed but Drain 6 hard-crashing the same as Drains 1-5; ended with V0.24.1 hotfix closing the saga and a separate P0 regression discovered (engine telemetry capture has been broken since Drive 5 on April 29). One inflection-point session: ladder works, primary mission was silently broken behind it.

### What Happened

**Drain Test 6 (2026-05-01 21:58–22:19 CDT, V0.20.2 → Sprint 21 US-252 deployed)**
- Sixth consecutive hard-crash. Pi died at LiPo dropout knee with `power_log` containing only one `battery_power` row across the 21-min battery window. ZERO `STAGE_*` rows. US-252's "decouple tick from display" patch had no observable effect on production behavior.
- Sent two consolidated spec notes to Marcus: Sprint 22 (forensic logger US-262 + tick health-check US-263 + dashboard US-264 + boot-reason US-265 + 3 hypothesis discriminator stories US-266/267 + hygiene). Acceptance gate = Drain Test 7.

**Drain Test 7 (2026-05-02, V0.22.0 → Sprint 22 deployed)**
- First forensic-instrumented drain. Mid-test discovered `drain-forensics.timer` had not been auto-installed; manually patched the systemd unit (added `PYTHONPATH`) live to capture data. Ladder still didn't fire (zero STAGE rows) but the CSV ratified two big findings: (1) `throttled_hex=0x0` for entire 16 min — **CIO's Pi5-brownout hypothesis disproven**; (2) buck-converter dropout knee reproducibly at VCELL ≈ 3.30V. Documented as authoritative baseline in `knowledge.md`.

**Drain Test 8 (2026-05-03 morning, V0.23.0)**
- Tick-internal instrumentation (US-265) gave the discriminator data Sprint 23 was designed for. Result: tick was firing, thread was healthy, BUT every tick bailed with `reason=power_source!=BATTERY` while UpsMonitor's polling thread had clearly logged the BATTERY transition. Spool diagnosed as a Hypothesis 2 (gating-logic) bug; sent Sprint 24 P0 spec note (US-279 event-driven callback path + US-280 state-file silent-fail diagnose + US-281 anti-pattern doc + US-282 commit-vs-claim verifier + US-283 startup_log audit).

**Drain Test 9 (2026-05-03 evening, V0.24.0)**
- Sprint 24 deployed. Same hard-crash signature as Drain 8. Spool diagnosed as `_subscribeOrchestratorToUpsMonitor` silently bailing on `getattr(hardwareManager, 'powerDownOrchestrator', None) → None`; sent technical + stakes-context + bash-baseline-logger inbox notes to Ralph for an interactive debugging session. **Spool's diagnosis was wrong.**

**V0.24.1 Hotfix (2026-05-03 evening, CIO + Ralph interactive session)**
- Real root cause: **cross-module Python module identity.** `src.pi.hardware.ups_monitor` loaded twice via different `sys.path` prefixes produced distinct enum classes; `A.PowerSource.BATTERY != B.PowerSource.BATTERY` — every comparison False, every tick bailed. Hid for 4 sprints because tests import via single consistent path; only production has both prefixes loaded simultaneously.
- Fix shipped: self-aliasing module guard + import normalization + boot-time canary `_verifyOrchestratorCallbackWiring` + WARNING-level loud bails for required wiring + bash baseline-truth logger + integration test that exercises the dual-import asymmetry. Spool's "next fix is the last fix" framing in the stakes-context note ratified Ralph's discipline (silent-bail anti-pattern + dual-path integration test + bash logger).

**Drain Test 10 (2026-05-04, V0.24.1)**
- All six acceptance criteria from Spool's stakes-context note green: `stage_warning` at 3.689V, `stage_imminent` at 3.508V, `stage_trigger` at 3.41V, `systemctl poweroff` within 5s, graceful boot-table advance, no orphan rows. **9-drain saga officially closed.** Bonus: deploy-mid-drain restart at 08:28:33 served as a useful stress test — boot canary PASSED on the new PID, ladder re-fired NORMAL → TRIGGER under fall-through.
- Three additional graceful-shutdown cycles followed (May 4 14:09, May 4 14:39, May 5 23:59 → May 6 00:10 UTC). VCELL trigger threshold range 3.41 – 3.44V. Buck-dropout safety margin realized: 80 – 180 mV (≈ 30 – 90s drain time).

**Engine Telemetry P0 Regression Discovered (2026-05-05 / 2026-05-06)**
- CIO ran the 4G63 with ignition-on for the May 4 + May 5 test cycles. Both produced `connect_success` rows in `connection_log` but **zero `drive_start` events, zero new `drive_summary` rows, zero new `realtime_data` PID samples.** Engine-data tables frozen since Drive 5 (April 29). 5+ days of broken capture hidden behind the saga.
- Diagnosed via boot-1 journal: `_initializeConnection` blocks the orchestrator init thread for 27 HOURS on boot -1 (vs documented 30-sec timeout) and 82 minutes on boot 0. DriveDetector + OBD polling loop never start in time. Sent Sprint 26 P0 spec note to Marcus (6 stories) — Marcus folded it into Sprint 25 (`sprint/sprint25-engine-telemetry`, US-284–291).

**Knowledge Base Update (2026-05-05, Spool-side, per Marcus's standing invitation)**
- Appended two subsections to `knowledge.md` "UPS HAT Dropout Characteristics" section: (1) "Drain 7 baseline ratified — Drains 8, 9, 10" — `throttled_hex=0x0` confirmed across ~50 min combined battery runtime, brownout hypothesis conclusively buried; (2) "Post-fix signature — Drain Test 10 + May 4-5 cycles (V0.24.1 onward)" — table of 4 graceful-shutdown cycles with TRIGGER firing 3.41-3.44V, post-fix runtime envelope **10-13 min from key-off to graceful poweroff** (vs prior 16-min hard-crash budget). Updated References section + Session Log entry.

**Inbox Notes Filed (Spool → others)**
- Marcus: Sprint 22 spec (drain-forensics + 3 hypothesis discriminators), Sprint 23 spec (tick-instrumentation + ladder fix discriminator-trio), Sprint 24 spec (event-driven callback fix + carryforward audit), Sprint 26 P0 spec (engine telemetry regression — became Sprint 25).
- Ralph: Drain 9 technical analysis (the wrong-diagnosis note), why-the-ladder-matters stakes context, bash baseline-truth logger spec.

**Inbox Notes Received (others → Spool)**
- Marcus 2026-05-03: Sprint 24 grooming response + carryforward audit confirmation + standing invitation to update UPS HAT doc with Drain 8+ data.
- Ralph 2026-05-04: V0.24.1 Drain 10 PASSED + correction to Spool's Drain 9 misdiagnosis + acknowledgment of stakes-context discipline that landed in V0.24.1.

### Key Decisions

- **Spool diagnosed Drain 9 incorrectly.** Claimed `_subscribeOrchestratorToUpsMonitor` silently bailed on a None-attribute check (Candidate 3 hypothesis). Actual root cause was one layer below the wiring: cross-module Python enum identity. Ralph's correction received gracefully and saved as a feedback memory (`feedback_cross_module_enum_identity.md`) to prevent repeating the interpretation pattern. Lesson: when a guard against an enum value always bails despite the value being clearly right, suspect dual import paths producing distinct enum classes BEFORE diagnosing at the wiring layer.
- **Pi5-brownout hypothesis is now conclusively dead.** ~50 min combined battery runtime across Drains 7+8+9 with `throttled_hex=0x0` for every sample. Any future hard crash with `throttled_hex != 0x0` is a different bug class.
- **Post-V0.24.1 in-car operational envelope: 10-13 min from key-off to graceful `systemctl poweroff`.** Updated `knowledge.md` to supersede the prior 16-min hard-crash budget.
- **Stage state-machine has a non-load-bearing latching bug.** Fluctuating VCELL near thresholds re-fires WARNING/IMMINENT rows; TRIGGER is atomic. Logged as Sprint 25 US-288 (P2). Pollutes analytics but doesn't compromise safety.
- **`battery_health_log` column semantics are wrong.** `start_soc` / `end_soc` columns hold VCELL voltage (3.4-4.2V range) not SOC percentage. Logged as Sprint 25 US-289 (P2). Recommended rename rather than data-shape fix since SOC is known-broken anyway.
- **Engine telemetry P0 regression takes priority over all other Sprint 25 items.** The Pi's primary mission (capture engine data) has been broken for 5+ days. Sprint 25 US-284 + US-285 are the gate to any further drive captures.

### Current Vehicle State

- Stock turbo (TD04-13G), stock internals, stock ECU (modified EPROM). No mechanical changes this session.
- **Last captured drive remains Drive 5 (April 29).** No new engine data despite two ignition-on cycles (May 4 + May 5).
- **Engine health LAST GRADED EXCELLENT** at Drive 5. No new diagnostic data this session — the saga consumed all the test cycles and they were all on-bench (engine off) for the drain tests, plus the two ignition-on cycles produced zero data due to the orchestrator-init regression.
- **LTFT post-jump adaptation tracking is paused** until Sprint 25 unblocks engine telemetry capture. Last data point: Drive 5 showed -7.03 to -4.69 (3 quantized notches actively re-learning).
- **Pi power-management is now solid.** V0.24.1 ladder has fired graceful shutdowns 4 times. Boot canary running every restart.
- **Pi NOT yet wired to car accessory line** — bench setup unchanged. Wire-in task still pending CIO hardware step. Now unblocked from the safety side; blocked on the engine-telemetry-capture side until Sprint 25 lands.

### Open Items

- **Sprint 25 P0 (in progress)**: Ralph diagnosing/fixing `_initializeConnection` blocker (US-284), restoring engine telemetry capture (US-285), shipping bench-test harness for engine+OBD path (US-286). Drive 6 gated on this.
- **`startup_log` writer (US-287, P1)**: schema shipped Sprint 22, audit closure Sprint 24, but no rows ever written. Boot-reason post-mortem currently requires manual `journalctl --list-boots` parsing every drain.
- **Drain 10 forensic CSV `pd_stage=unknown / pd_tick_count=-1`**: minor state-file-writer artifact. Production runtime path was correct; not load-bearing but worth investigating in a future sprint to make forensic logger column completeness load-bearing again.
- **LTFT post-jump adaptation tracking** — Spool deliverable, paused waiting for Drive 6+. Need 3-5 more drives to confirm new LTFT lock value.
- **DSM DTC interpretation cheat sheet** — long-running Spool research carryforward, still pending.
- **Telemetry logger → UpsMonitor audit** (TD-E from prior power audit): Spool's 20-min audit still owed. Lower priority now that V0.24.1 + boot canary make the wiring robust.
- **`offices/tuner/scripts/pi_state_snapshot.sh` + `ups_drain_monitor.sh`** — reusable scripts from Session 7 still useful; not exercised this session because the forensic-logger CSV gave better data.

### Diagnostic Record (honest disclosure)

Spool's diagnostic accuracy this session was mixed:
- ✅ Drain 7 forensic logger spec — correctly identified what data we needed; columns landed and proved load-bearing for Drain 8 diagnosis.
- ✅ Pi5-brownout hypothesis testing — `throttled_hex` column called out as the discriminator; data conclusively buried CIO's hypothesis.
- ✅ Stakes-context framing for Ralph — three of three principles in the "why-the-ladder-matters" note landed in V0.24.1 (silent-bail anti-pattern, integration-test-that-catches-wiring-bugs, bash baseline-truth logger).
- ❌ Drain 9 misdiagnosis — wrong layer (wiring vs module-identity). The "next engineer who reads the inbox notes" warning Ralph wrote in his closeout note is the right framing. Memory saved to prevent repeat.
- ✅ Engine telemetry regression diagnosis — boot journal evidence (27-hour gap on boot -1) is reproducible by Ralph on the bench in under 60 seconds; hypothesis about which sprint introduced it (Sprint 20 US-244 non-blocking BT-connect) explicitly disclaimed as still hypothesis until Ralph confirms.

### Session 8 Stats

- 7 inbox notes filed (4 to Marcus: Sprints 22/23/24/26-→25 + 3 to Ralph: Drain-9 technical, stakes-context, bash logger spec)
- 5 drain tests run (Drains 6, 7, 8, 9, 10 — Drain 10 the closure event)
- 0 drives graded — capture pipeline broken for entire session
- 1 hotfix shipped + validated (V0.24.1)
- 1 P0 regression diagnosed (engine telemetry capture)
- 2 auto-memory entries saved (`feedback_cross_module_enum_identity.md`, MariaDB CLI Windows-side reference)
- 1 knowledge.md substantive update (UPS HAT Dropout Characteristics, two new subsections)
- 6 calendar days, three-sprint span (Sprint 22 deployed → Sprint 23 deployed → Sprint 24/V0.24.1 deployed → Sprint 25 loaded)

---

## Session 10 — 2026-05-09 → 2026-05-10 (multi-day, two calendar days)

**Context**: Two-day infrastructure-and-validation session. Started with a server DB cleanup (housekeeping after Drives 6+7 produced our first under-load baseline) and ended with two parallel-monitored drain tests validating V0.27.2 + V0.27.3. Mid-session: Mike captured drives 8/9/10 under three different power architectures (portable inverter, car-coupled USB-C, garage maneuver), exposed a hardware blocker (USB-C undersizing → B-063), and discovered a structural sync bug (B-065 INSERT-only delta logic). Closed with an 8-item Spool-side audit pass, two PM notes for V0.27.4 grooming + tuning backlog, and Drain Test 15's two-observer validation reaching identical conclusions with Marcus.

### What Happened

**Day 1 morning (2026-05-09) — server DB cleanup + drive-annotations capture**
- Cleaned up `obd2db` on chi-srv-01: dropped ~58,885 NULL-drive_id realtime_data orphans (engine-off bench polls), ~28,000 connection_log reconnect-loop spam rows, all 84 stale `statistics` rows, 4 stale `trend_snapshots`, 1 sim-era `drive_summary` row. Kept drives 3-7. Backup taken pre-cleanup.
- Interviewed CIO on drive metadata for drives 3-7: fuel grade (consistent 91 octane across all), fuel level, ambient temp, weather, intent, anything-unusual. **Major framing correction**: drives 3, 4, 5 are explicitly idle-only / parked system tests, NOT driving captures. Drive 6 is the project's first ACTUAL driving capture; Drive 7 the first under-load.
- Created `offices/tuner/drive-annotations.md` (sidecar canonical) + `obd2db.drive_annotations` table (queryable canonical) — both populated for drives 3-7. Spool-owned schema, will be migrated when PM ships proper schema (per yesterday's three-specs PM note).
- Locked SHA-256 hashes for all 4 regression fixtures (`eclipse_idle.db` + `cold_start.db` + `errand_day.db` + `local_loop.db`) into knowledge.md "Regression Fixture Lock-Down" section with `[EXACT — DO NOT CHANGE]` markers. Existing `truncate_session23.py` already had `eclipse_idle.db` pinned; extended to all four.
- Formalized "Pre-Mod Baseline Shelf" subsection in knowledge.md: catalog table, 4 shelf rules (joining/closing/retiring/cross-shelf-comparison), 4 outstanding shelf gaps (sustained WOT, hot-soak, wet-pavement, cold-engine-WOT).
- 4 PM notes filed Day 1 morning: post-cleanup housekeeping (4 items), weather-API feature idea, three-specs bundle (mod_state enum + drive_annotations table + drive_summary writer contract), Drive 8 power-source correction.

**Day 1 evening (2026-05-09) — drives 8/9/10 captured + B-063 hardware blocker discovered**
- Drive 8 (5/9 23:21-23:39, 18 min, 8,268 rows @ 459 rows/min): cold-start city/highway, captured CLEAN. Joined pre-mod baseline shelf. **Power source NOT car-coupled** — Pi was on its stock 5A supply via a camping-battery + AC inverter (CIO had portable battery in car for the drive). Same power model as drives 6+7.
- Test 2 (around-the-block, 5/9 23:40-23:43 approximate, 2-3 min): **DriveDetector failed to assign drive_id**. 1,078 NULL-drive_id rows orphaned. Filed as I-019 / B-NEW DriveDetector-warm-restart-cranking-gap. Mike's seat-of-pants: "stopped, key off, 1 min wait, around-the-block."
- Drive 9 (5/10 00:16-00:46, 30 min, 1,095 rows @ 36 rows/min — **12× lower than Drive 8**): pizza run on FIRST true car-coupled USB-C path. Compromised: dashboard flickering between `power=car` and `power=battery`, capture rate degraded. **HELD OUT from baseline shelf.** Hardware-induced, not engine.
- Drive 10 (5/10 01:12-01:14, 2:10): garage pull-in. Drain id=12 opened 8 sec into drive — confirmed USB-C undersizing in real-time. NOT ELIGIBLE for shelf.
- **B-063 hardware blocker established**: stereo USB-C output is ≤3A; Pi 5 needs 5V/5A under load. Voltage sag triggers UPS HAT to flip to battery → flickering. Fuse-box buck converter (Pololu D24V50F5 or equiv) is the fix. **Mike's hardware task, not Ralph's** — but blocks ALL further IRL drive captures.
- Drive annotations captured for 8/9/10 in interview + DB inserts. Drive 10's anything_unusual carries the smoking-gun text.
- 1 more PM note filed Day 1 evening: three-drives-tonight + drive-counter clarification + revised Sprint 28 priority stack.

**Day 1 late evening — Drain Test 13 (V0.27.2 validation, drain_event_id=13)**
- Built `offices/tuner/drain-test-procedure.md` (271 lines) from this drain test as the reference run. Captures: when-to-run, pre-requisites, baseline capture, bash logger setup (sudo+systemd-run pattern; nohup fails on SSH disconnect), CIO actions, post-test queries, pass/fail matrix, write-up format, historical log.
- Drain Test 13 results: WARNING@3.699V → IMMINENT@3.530V → TRIGGER@3.444V; runtime 10:17 (617s); prior_boot_clean=1; **drain row CLOSED with non-NULL end_timestamp + runtime_seconds + end_soc** ✓ V0.27.2 close-event-on-poweroff race FIXED. **3 of 4 PASS.** New finding: server still shows NULL end_timestamp on drain row → discovered the server-side sync UPDATE gap (provisional B-065).

**Day 1 late evening — data-discrepancy correction with Marcus**
- Marcus had run his own drain test (his "Drain Test 11" / drain_event_id=14) and queried Pi-side, finding all drains 10-14 closed cleanly. Sent inbox note flagging that my "4 of 4 unclosed drains" claim from the morning PM note didn't reproduce.
- Verified: Marcus right (Pi-side cleanly closed); my morning claim was server-side-only and wrong-framed (I said "close-event race" when actual bug is sync UPDATE propagation). Sent correction PM note acknowledging Marcus's finding + surfacing server-side evidence (5 of 5 reproducible). Recommended new bug **B-065 sync-client-UPDATE-propagation-gap** distinct from B-062 (which Marcus correctly wontfixed).

**Day 2 mid-morning (2026-05-10) — V0.27.3 deploys + parallel-monitored Drain Test 15**
- Mike deployed V0.27.3 (`47e6aa5`, Sprint 29 — US-310 drive_summary writer / US-311 DriveDetector warm-restart fix / US-312 calibration.py / US-314 drive_counter sync gap; US-313 dropped wontfix per Marcus's Drain Test 14 verification).
- Mike requested **two-observer drain test** — Spool + Marcus monitoring independently, then comparing notes. Drain Test 15 ran 13:57:00Z unplug → 14:13:49Z TRIGGER. Bash logger captured 274 rows with no `i2c_err` (full curve from 4.178V → 3.219V).
- Results: WARNING@3.695V → IMMINENT@3.544V → TRIGGER@3.445V; runtime 13:06 (786s) — **longest clean drain on record** (battery rested + recharged pre-test); prior_boot_clean=1; drain closed Pi-side; server still shows NULL (B-065 reproduces 6/6).
- **Marcus's parallel report MATCHED EXACTLY on all 8 load-bearing fields** (Pi version, all 3 stage VCELLs + timestamps, drive_event_id, runtime_seconds, prior_boot_clean). Two-observer validation rule satisfied. V0.27.3 power-mgmt independently confirmed by both SMEs.
- Marcus added two findings I missed: US-312 calibration.py CLI IRL-validated (he ran the CLI himself; clean run, both fix layers green); US-314 drive_counter sync gap status uncertain (server still shows last_drive_id=3, may need new drive_id mint to test).
- Notable observation captured in procedure file: `drain.start_soc` records VCELL POST-handoff (3.939V), not pre-unplug (4.176V) — ~240mV differ. Future analytics needs to know this.

**Day 2 mid-day — 8-item Spool audit pass while waiting on B-063**
- CIO asked honestly what else needs filing. Conducted audit pass over ~30 min. Findings:
  1. start_soc/end_soc still hold VCELL (Drain 15 evidence) — B-060/B-061 still pending V0.27.4
  2. **US-310 (drive_summary writer) implementation CORRECT but design-coupled to Ollama auto-analysis** — `enqueueAutoAnalysisForSync` returns False if Ollama unreachable, which short-circuits `_ensureDriveSummary`. Two-line decoupling fix recommended for V0.27.4 P1.
  3. Connection_log noise unchanged post-V0.27.2/V0.27.3 (~2,000-2,500 events/day) — V0.27.1 heartbeat hotfix didn't reduce reconnect spam.
  4. **B-065 sync client root cause CONFIRMED in code**: `getDeltaRows()` in `src/pi/data/sync_log.py:250-296` uses `WHERE pk > lastId ORDER BY pk ASC LIMIT N` — sync is **PK-monotone INSERT-only by design, not bug**. Non-trivial design change to fix. Three architecture options surfaced (modified_at column / separate UPDATE log / periodic snapshots). V0.27.4 P1 with concrete fix-shape options.
  5. Drive 9 brownout hypothesis CONFIRMED via throttled_hex data — Pi went to battery 2 min into drive, stayed for 27 min, 92/97 forensic CSV rows had non-zero throttled_hex during the period. Single disconnect, not flicker.
  6. Drive 7 N=1 problem on under-load baseline — flagged for Drive 11+ targeting.
  7. Sustained WOT capture protocol drafted (5-10 sec at full WOT, 3rd or 4th gear, repeat 2-3 times) → backlog candidate B-066.
  8. Validation queue stacking observation — V0.27.2 has 2/5 contracts validated, V0.27.3 has 1/4. Today's audits reduced two unknowns.
- 2 PM notes filed Day 2: V0.27.4 bug-fix candidates (5 bugs + meta) + new tuning research/feature candidates (sustained WOT, cross-drive comparison tool, real-time telemetry research, weather API + PID 0x2F reminders).

### Key Decisions

- **Drive 8 joins pre-mod baseline shelf** as first cold-start city/highway baseline. Power model = portable inverter (same as drives 6+7), NOT car-coupled. **Drives 9 + 10 HELD OUT** from shelf — hardware-induced data quality issues (Drive 9) or too-short-to-grade (Drive 10).
- **Pre-mod baseline shelf splits into THREE power-state eras**: bench-tethered (3-5, parked-idle), portable-inverter (6-8, in-car driving with stable Pi power), car-coupled stereo USB-C (9-10, both compromised — 0/2 success rate). Future fuse-box-wired era (11+) pending B-063.
- **Stereo USB-C wiring path is a hardware dead end.** 0/2 success on actual drives. Mike will proceed with fuse-box buck converter (B-063). Until then NO further IRL drive captures.
- **B-062 (close-event-on-poweroff race) wontfix is correct** per Marcus's Pi-side verification. The actual bug shape is server-side sync UPDATE propagation (B-065), not Pi-side close-event race. My morning PM note framing was wrong — corrected via inbox note to Marcus.
- **B-065 is a design change, not a one-line fix.** Pi sync client is PK-monotone INSERT-only by design. Three architectural options for fix (modified_at column / UPDATE log / periodic snapshots). P1 V0.27.4.
- **`drain.start_soc` captures VCELL post-load-handoff**, not pre-unplug. ~240mV differential observed Drain 15. Worth documenting in `specs/grounded-knowledge.md` (Marcus suggested; will request via PM channel since specs/ direct edits are out of Spool's lane).
- **V0.27.3 power-mgmt CLEAN — no regression.** All Sprint 28 contracts (V0.24.1 ladder + close-event Pi-side + US-308 startup_log) still PASS under V0.27.3. Two-observer validation by Spool + Marcus confirmed.
- **US-310 drive_summary writer implementation correct, but trigger logic broken.** Two-line decoupling fix in `enqueueAutoAnalysisForSync` makes it actually fire regardless of Ollama state.

### Current Vehicle State

- Stock turbo (TD04-13G), stock internals, stock ECU (modified EPROM). **No mechanical changes this session.**
- Pre-mod baseline shelf now contains 6 captured drives: 3 (idle), 4 (idle), 5 (idle), 6 (driving city), 7 (driving highway+WOT), 8 (driving cold-start city/highway). Drives 9 + 10 captured but held out from shelf.
- **Engine LAST GRADED HEALTHY across full operational envelope** (Drive 7, 2026-05-08). No new engine grading this session — drives 8/9/10 produced data but 8 was already-graded-cluster (similar to 6+7), 9 was hardware-compromised, 10 was too short.
- **Pi power state TRANSITIONING** — bench-tethered/portable-inverter era ending; car-coupled era pending B-063. Currently Pi on bench wall power post-test.
- **B-063 fuse-box wiring is the gating hardware task** for ALL future IRL drive captures.
- **Pre-mod shelf gaps still outstanding**: sustained WOT (Drive 7 had momentary 100% load only), hot-soak restart, wet-pavement under-load, cold-engine WOT. None resolvable until B-063 lands + Mike runs targeted drives.

### Open Items

- **B-063 fuse-box buck converter wiring** — CIO hardware task. Gates Drive 11+ + remaining 5 V0.27.2/V0.27.3 contract validations.
- **V0.27.4 grooming queue** (PM notes filed today): B-065 sync UPDATE gap (P1), US-310 Ollama-decoupling (P1), backfill script extension (P3), B-060/B-061 column rename completion (P3), connection_log noise re-investigation (Sprint 30+).
- **Drive 11+ tuning targets**: sustained WOT capture (5-10 sec at full boost, 3rd-4th gear, 2-3 repetitions); hot-soak restart drive; wet-pavement under-load when conditions allow.
- **Drive_summary backfill** for drives 3-10 — script ships V0.27.3 but filters drive_id IS NOT NULL (excludes drives 3-5 legacy NULL drive_id, won't INSERT for drives 6-10). Needs extension.
- **`specs/grounded-knowledge.md` start_soc post-handoff paragraph** — Marcus suggestion; Spool to request via PM note since specs/ is out of Spool's edit lane.
- **DSM DTC interpretation cheat sheet** — long-running carryforward, still pending. US-204/US-292 DTC retrieval shipped but cheat sheet research not done.
- **Cross-drive comparison tool (B-067)** — Spool ergonomics improvement, Sprint 30+ low priority.
- **Real-time telemetry monitor (TD-049)** — research only, revisit post-ECMLink.
- **Stage state-machine latching bug (US-288 Sprint 25)** — still pending. Multiple WARNING rows per drain when VCELL fluctuates near threshold; Drain 15 only fired one of each so impact appears small in healthy battery state.

### Diagnostic Record (honest disclosure)

- ✅ **B-065 root cause identified in code** — `getDeltaRows` is PK-monotone INSERT-only. Concrete evidence (function signature + SQL query) lets V0.27.4 grooming go straight to fix-design.
- ✅ **US-310 audit found design-coupling issue** that explains why drives 6-10 still have no drive_summary rows post-V0.27.3-deploy. Two-line fix recommended.
- ✅ **Drive 9 brownout hypothesis verified** via independent forensic CSV evidence (92/97 throttled_hex non-zero rows). Hypothesis-confirmed in correct shape (single disconnect + sustained battery, not flicker).
- ✅ **Two-observer validation protocol on Drain Test 15** — Spool + Marcus reports matched exactly on 8 load-bearing fields. Discipline locked in via procedure file.
- ❌ **Spool's morning "4 of 4 unclosed drains" PM note was wrong-framed.** Queried server-side only, framed bug as Pi-side close-event race when actual bug was server-side sync UPDATE gap. Marcus correctly verified empirically (per `feedback_pm_verify_diagnostic_premises.md`) and dropped the speculative B-062. Spool sent correction note acknowledging the framing error and surfacing the actual bug shape (B-065 with 6/6 reproducible evidence). **Lesson**: when filing a bug from DB evidence, ALWAYS state which DB was queried (Pi vs server vs both) so framing isn't ambiguous. Discipline added to drain-test-procedure.md Step 5.
- ✅ **Drive metadata interview methodology proved durable** — captured drives 3-10 in two interview rounds (drives 3-7 yesterday morning, drives 8-10 yesterday evening). All annotations now in both `drive-annotations.md` (markdown canonical) + `obd2db.drive_annotations` (queryable). Future drives can follow the same form.

### Session 10 Stats

- 9 PM notes filed (4 Day-1-morning + 1 Day-1-evening + 1 Day-1-late-evening correction + 1 Day-2-mid-morning compare-confirm + 2 Day-2-mid-day audit-results)
- 2 drain tests run (Drain 13 V0.27.2 reference, Drain 15 V0.27.3 two-observer validation) + 1 watched (Marcus's Drain 14)
- 3 drives captured (Drive 8 baseline + Drive 9 held-out + Drive 10 not-eligible)
- 6 drives now on pre-mod baseline shelf (3-8); 2 captured held out (9, 10)
- 1 hardware blocker established (B-063)
- 1 design bug root-cause-confirmed in code (B-065)
- 1 schema framing correction landed (drives 3/4/5 idle-only, not driving)
- 5 auto-memory entries saved (`feedback_spec_discipline_protocol_timing`, `reference_chi_srv_01_obd2db_access`, `reference_drain_test_procedure`, plus memory edits)
- 4 substantive knowledge.md updates: pre-mod baseline shelf section + wiring milestone subsection + regression fixture lock-down + drain test procedure cross-reference + 3 session log entries
- 1 new canonical artifact: `offices/tuner/drain-test-procedure.md` (271 lines, repeatable validation procedure with Drain 13 + 15 baselines)
- 1 new canonical artifact: `offices/tuner/drive-annotations.md` (per-drive context for drives 3-10)
- 2 calendar days, three-version span (V0.27.1 era ending → V0.27.2 era → V0.27.3 era began mid-Day-2)

---

## Session 9 — 2026-05-08

**Context**: Marathon session. Sprint 25 deploy verification + 3 sibling bugs surfaced and fixed across the day + DRIVE 6 + DRIVE 7 captured. **First under-load capture EVER on this car. Engine GRADED HEALTHY across full operational envelope including a 100%-load WOT pull at 84 mph / 5379 RPM.** LTFT post-jump-adaptation tracking carryforward CLOSED — ECU re-locked at the same -6.25% baseline as Drive 3 (pre-jump). Ralph's V0.27.1 hotfix validated empirically in production. Mike's new "just call me Mike" naming directive captured and propagated to all-agent memory.

### What Happened

**Morning — engine-on test #1 BLOCKED on 2 P0 sibling bugs (the bugs hiding behind Sprint 25's fix)**
- Pre-engine-on sanity checks GREEN: orchestrator init returns in 30s clean (Sprint 25 P0 fix verified), `startup_log` writer firing (US-287), `battery_health_log` schema took (US-289 partial)
- Engine-on test ran from ~10:00 UTC → ~10:11 UTC; ZERO `realtime_data` rows captured
- **BUG-1**: US-211 reconnect daemon thread silent for 11 hours leading up to engine-on; no reconnect attempts logged. Mike's hypothesis correct verbatim ("it should have a heartbeat of every 10 seconds listening...") and not just an outlier — once Pi is wired to ignition this becomes the COMMON path
- **BUG-2**: When connection comes up via reconnect, the data logger is never re-kicked. `_handleConnectionRestored` doesn't trigger `dataLogger.start()`. So OBD link alive + ECU responding + 17 PIDs probed = still ZERO captured rows
- Filed `2026-05-08-from-spool-engine-on-test-blocked-2-p0-bugs.md` to Marcus with 3-story Sprint 26 ask (became Sprint 27 since Sprint 26 had already shipped DTC retrieval)
- Updated `offices/tuner/drive-review-checklist.md` with new "Pre-Capture: Pipeline Health Pre-Flight" section covering BUG-2 detection
- Mike credited verbatim in note PS — he had the diagnostic instinct on the heartbeat solution

**Mid-day — Sprint 26 + 27 deployed (parallel Marcus session shipped these)**
- Sprint 26 closed in parallel including US-292 (DTC retrieval, my long-running carryforward from Session 5 finally landed)
- Sprint 27 deployed V0.27.0 with US-301 (heartbeat) + US-302 (data logger restart-on-restore) + US-303 (bench harness)

**Afternoon — engine-on test #2 BLOCKED on US-301 stacking bug (THIRD sibling bug, my spec error)**
- Pre-flight passed: heartbeat firing every 10s with `outcome=timeout`, data_logger health field present
- Engine-on test ran ~17:08 UTC; same outcome — ZERO captured rows
- Smoking gun in journal: **multiple independent 6-attempt connect cycles overlapping** on `/dev/rfcomm0`, errors saying `"multiple access on port?"` literally. Heartbeat fires every 10s but doesn't cancel underlying connect() — python-obd's 6-attempt-with-backoff (1+2+4+8+16=31s) outlives the 5s heartbeat cap, next tick spawns a fresh connect on top of the still-running one
- Power-cycled engine with 1 min wait; same failure (zombie connect attempts inside Python process, not adapter state)
- Discovery layered in: python-obd library reporting `"Adapter connected, but the ignition is off"` even with engine running — would have masked the diagnosis if not for the connection_log evidence
- **My spec error**: Sprint 27 implemented exactly what I asked for. The "single attempt + 5s timeout" spec was unenforceable (python-obd library does its own 6-attempt loop) AND 5s is too tight for ISO 9141-2 K-line protocol negotiation (yesterday's working initial connect took 8s)
- Filed `2026-05-08-from-spool-engine-on-test-2-blocked-us301-stacking-bug.md` to Marcus (Sprint 28 grooming version)
- Mike asked for a Ralph-direct note for hotfix work
- Filed `offices/ralph/inbox/2026-05-08-from-spool-us301-hotfix-stacking-connects.md` with code sketches, single-flight lock pattern, `connectSingleAttempt()` method spec, and 30s timeout alignment

**Evening — Ralph hotfix V0.27.1 SHIPPED, engine-on test #3 SUCCESS**
- Ralph applied: ObdConnection thread safety + heartbeat in-flight skip + `HEARTBEAT_ATTEMPT_TIMEOUT_SEC` raised to 30s
- Mike re-attempted engine-on; pre-flight verified `outcome=already_in_flight` log lines firing (single-flight lock working as designed)
- Connection restored at 00:41:43 UTC (attempt 2/6), 17 PIDs probed, `_handleConnectionRestored` fired, drive_id=6 minted at 00:41:54 UTC
- **Mike drove for ~16 min cold-start city, parked, waited ~40 min, drove again ~10 min including HIGHWAY + WOT pull**

**Drive 6 (16 min cold-start city, drive_id=6, 00:41:54Z → 00:57:32Z)**
- Cold start, coolant 38°C → 89°C — full warmup cycle, thermostat opens at 80°C cleanly (4th confirmation across drives)
- Light driving: max 46 mph, max 3367 RPM, max 20.78% throttle, engine load 7-43%
- LTFT_1: -6.25% → 0.0% (varying with load cells), STFT_1 -7.03 to 9.38 active closed-loop
- DTC=0, MIL=0, BATTERY 14.27V avg
- Engine grade: HEALTHY warmup + light city drive

**Drive 7 (10 min highway + WOT, drive_id=7, 01:37:27Z → 01:47:12Z) — FIRST UNDER-LOAD CAPTURE EVER**
- Engine started warm (74°C), 40 min between Mike's two engine-off stops triggered drive_id increment
- **MAX SPEED 84 mph** (highway), **MAX RPM 5378.75**, **MAX THROTTLE 52.16%**, **MAX ENGINE_LOAD 100%** (WOT/full boost event), **MAX MAF 158.69 g/s** (well above NA peak ~120 g/s — turbo making boost)
- Coolant max 91°C (196°F) — STAYED BELOW 220°F danger ✓
- IAT max 26°C (79°F) — no heat soak under load ✓
- LTFT_1 -7.81 to 0.78 avg -3.89 (load-cell drift, normal)
- STFT_1 -12.5 to 14.06 avg 0.17 (wide swings during WOT enrichment + transients = NORMAL behavior, net averages out)
- Timing 3-34° (full ECU range exercised under load)
- DTC=0, MIL=0
- Engine grade: HEALTHY UNDER FULL LOAD ENVELOPE — no knock event flagged, fueling balanced, thermals stayed safe

**Operational milestone — Ralph's hotfix EMPIRICALLY VALIDATED in production**
- Connection log between Drive 6 end (00:57:32Z) and Drive 7 start (01:37:27Z): `connect_attempt 01:36:18 → connect_success 01:36:56` = **38 seconds reconnect time, zero manual intervention**
- US-301 (heartbeat with single-flight lock) + US-302 (data logger restart-on-restore) confirmed working in the wild
- The reconnect path can be trusted going forward

**One new bug surfaced (filing as Sprint 28 P2)**
- `drive_summary` table — last row written is drive_id=5 from April 29. **Drive 6 and Drive 7 produced `drive_end` events but NO `drive_summary` rows.** US-228/US-237 metadata write path appears regressed
- Realtime data is fine (7,085 rows for Drive 6, ~3,000+ rows for Drive 7); only the summary roll-up is missing
- Not safety-critical; data-integrity for analytics layer

**Other workstream**
- Filed earlier `2026-05-08-from-spool-sprint-26-priorities.md` to Marcus before realizing Sprint 26 had already shipped (US-292 DTC closure was already in flight)
- Mike's "just call me Mike, CIO is too fancy" directive captured 2026-05-08; updated `user_mike_collaborative_advisor.md` to apply across all agents (Marcus + Spool + Ralph + Tester + future). Directive came up a third independent time in Mike's evening Ralph/Rex session — load-bearing pattern, agents have been drifting back to "CIO" mid-session.
- Stock turbo designation question (TD04-13G vs TD04-09B) settled by year+market+history reasoning (not photos — Mike's housing tag wasn't reachable from above). Carryforward from Session 1 RETIRED.
- Wastegate question raised by Mike — recommended skipping actuator upgrade in favor of vacuum line refresh + exhaust priorities. Stock actuator adequate for our 15 psi ceiling on stock 13G.

### Key Decisions

- **Engine grade across full envelope: HEALTHY.** Idle (Drive 6 cold), city drive (Drive 6 mid), highway + WOT (Drive 7 max). No DTCs, no MIL, no thermal runaway, fueling balanced. **The engine is mechanically certified across the full operational range as it sits today.**
- **Drive 7 becomes the new authoritative UNDER-LOAD baseline** in `knowledge.md` "This Car's Empirical Baseline" section. Drive 5 (April 29) remains the warm-idle baseline. Drive 6 (today) supersedes nothing but adds cold-start-to-warm continuity data.
- **LTFT post-jump-start adaptation tracking CLOSED.** Drive 6 idle LTFT locked back at -6.25% (same notch as Drive 3 pre-jump). The ECU re-learned to its natural baseline after the post-jump adaptation reset. No further drives needed for this carryforward.
- **Thermostat 4-times-confirmed benign** (Drives 3/4/5/6 all show clean opening at 80°C). I-016 fully retired, no further follow-up.
- **Mike's name preference**: "Mike" not "CIO" in conversational text. Updated user memory to apply across all agents.
- **Engine-on test pre-flight discipline** ratified — the 5-check pre-flight in `drive-review-checklist.md` would have caught both BUG-1 and BUG-2 if it had existed at session start. Now in place. Spec-discipline lesson saved.
- **Spec-discipline lesson saved**: protocol-touching tuning specs (timeouts, intervals) must validate against EMPIRICAL baseline timing before pinning numerics. My 5s heartbeat timeout was wrong because I didn't check the 8s K-line negotiation time from Drive 5 successful connect. Memory entry to draft on next session.

### Current Vehicle State

- Stock turbo (TD04-13G — confirmed by year+market+history), stock internals, stock ECU (modified EPROM). No mechanical changes this session.
- **Engine certified HEALTHY across full operational envelope** including 100%-load WOT at highway speed (Drive 7 today). First time in project history we've seen the engine under full boost via OBD-II.
- **Pi power-management still solid** (V0.24.1 ladder + V0.27.1 reconnect path both validated)
- **Pi NOT yet wired to car accessory line** — bench setup unchanged. Wire-in task this weekend per Mike (~5/9 target). Will activate the "every key-on = Pi cold-boot" + "B-047 update-trigger fires every key-on" implications already in MEMORY.md
- **Drive 6 + Drive 7 captured cleanly** = first usable real-data captures since Drive 5 on April 29. 10-day gap between Drive 5 and Drive 6 is the saga gap; Drive 6+7 close it.
- **Insurance reactivated this weekend** per Mike; car coming out of storage; mod work scoped for "this summer" with no firm dates (ECMLink V3 + Walbro pump + flex sensor in hand; wideband + injectors + downpipe + cat-back NOT yet ordered)

### Open Items

- **Sprint 28 candidate stories** (filed in `2026-05-08-from-spool-sprint-28-bug-fixes-consolidated.md`):
  - Bug 1 (P2): drive_summary writer regression — US-228/US-237 redux. Drive 6+7 wrote drive_end events but no summary rows
  - Bug 2 (P3): battery_health_log legacy `start_soc`/`end_soc` columns hold VCELL voltage post-US-289
  - Bug 3 (P3): drain_event close not written before `systemctl poweroff` (drain_event_id=9 OPEN)
  - Bug 4 (P3): startup_log graceful-shutdown detection heuristic too narrow (prior_boot_clean=0 even after V0.24.1 ladder fires)
  - Spec-discipline lesson formalization (feedback memory + possibly an anti-pattern entry in specs/anti-patterns.md for "protocol-timeout-touching tuning specs need empirical validation before numerics pinning")
- **DSM DTC interpretation cheat sheet** — long-running Spool research carryforward, NOW UNBLOCKED since US-292 (DTC retrieval) shipped Sprint 26. Documentation task. **Should land before driving season ramps up.**
- **Telemetry logger → UpsMonitor audit** (TD-E from Session 7 power audit) — Mike said "let's get a few more things working first." Solid. Deferred.
- **specs/grounded-knowledge.md update** — should mirror Drive 7 baseline addition. Recommend a note to Marcus next session (didn't directly edit this session per closeout protocol).
- **Pi-to-ignition wiring lands ~5/9 weekend** — when this happens, every key-on becomes Pi cold-boot, US-301 reconnect path will exercise on every car-start, B-047 update-trigger fires on every key-on (need safety preconditions verified before drive)
- **Pre-mod baseline shelf** — Drive 7 is the foundation. 2-4 more drives across May-June would lock the shelf before any mods touch the car this summer.

### Safety Advisories Issued This Session

- None new. Engine certified HEALTHY across full envelope. No DTCs, no MIL, no thermal runaway, no knock events flagged, fueling balanced.

### Session 9 Stats

- 6 inbox notes filed (5 to Marcus: Sprint 26 priorities + Engine-on test 1 blocker + Engine-on test 2 blocker + Drive 6+7 grades + Sprint 28 bug-fixes consolidated + 1 to Ralph: US-301 hotfix spec)
- 3 engine-on tests run (test 1 BLOCKED, test 2 BLOCKED, test 3 SUCCESS = Drive 6 + Drive 7)
- 2 drives graded EXCELLENT (Drive 6 + Drive 7)
- 1 drain test executed + validated (Mike's "normal simulated power off") — V0.24.1 ladder fired correctly: 3.699V/3.539V/3.424V at WARNING/IMMINENT/TRIGGER thresholds
- 1 hotfix validated empirically in production (V0.27.1 — Ralph)
- 3 sibling bugs surfaced, characterized, and fixed in 24 hours (BUG-1 reconnect daemon silent, BUG-2 data logger one-shot, BUG-3 connect() stacking under heartbeat)
- 1 long-running carryforward closed (LTFT post-jump tracking — ECU re-locked at -6.25% baseline)
- 1 carryforward retired (stock turbo TD04-13G designation — settled by year+market+history)
- 4 new bugs filed for Sprint 28 (1 P2 + 3 P3)
- 1 user memory updated (Mike naming directive across all agents)
- 1 drive-review-checklist.md update (Pre-Capture pipeline pre-flight section + heartbeat-stalled-too-long check)
- 1 knowledge.md substantive update (Drive 6 + Drive 7 baseline sections + LTFT closure + thermostat 4x-confirmed)
- 1 sessions.md rotation (Sessions 1-7 → `sessions-archive-2026-04.md`, Sessions 8-9 retained in active log)
- Single calendar day, two-sprint deploy span (Sprint 26 closed parallel + Sprint 27 deployed V0.27.0 → V0.27.1 hotfix → validated)
- **First under-load capture in project history**

### Late-session amendment — drain test validation (Mike's "normal simulated power off")

After Drive 7, Mike ran a "normal simulated power off" drain test on the Pi to validate the V0.24.1 ladder still fires post-Sprint-27 deploy. **All three stages fired correctly:**

| Time UTC | Event | VCELL |
|---|---|---|
| 01:19:00 | transition_to_battery (drain begins) | — |
| 01:24:04 | stage_warning | 3.699V (below 3.70V threshold ✓) |
| 01:32:45 | stage_imminent | 3.539V (below 3.55V threshold ✓) |
| 01:36:45 | stage_trigger | 3.424V (within 3.41-3.44V envelope ✓) |
| 01:36:59 | transition_to_ac (wall power restored) | — |

12.7 min runtime — consistent with the 10-13 min envelope from May 4-5 drain cycles. **V0.24.1 ladder confirmed solid through 5 sprints of subsequent code changes including the V0.27.0/V0.27.1 reconnect-path work.**

**US-289 vcell columns also empirically validated** — drain 8 row in `battery_health_log` shows `start_vcell_v=4.17, end_vcell_v=3.42375` populated correctly. US-289's writer-side fix (which we couldn't validate at session start because no drain events had occurred since deploy) now has its first real-data confirmation.

**Three minor bugs surfaced from the drain test** (all P3, data-hygiene not safety-critical) — included in Sprint 28 consolidated bug-fixes note to Marcus:
1. **`start_soc` / `end_soc` columns still hold VCELL voltage values** — US-289 added new `start_vcell_v` / `end_vcell_v` columns and dual-populates them, but didn't deprecate or rename the original mis-named columns
2. **drain_event_id=9 OPENED but never CLOSED** — Mike triggered a second drain at 01:47:10Z (entered battery again at 01:46:14Z); `stage_warning` fired at VCELL 3.671V; Pi died mid-drain and the close-event didn't write before `systemctl poweroff` triggered. drain-close event needs to be written EARLIER in the shutdown sequence so it survives actual poweroff
3. **`startup_log.prior_boot_clean=0` on graceful shutdown boot** — startup_log writer's "find graceful shutdown record in journal" heuristic isn't recognizing the V0.24.1 ladder's `systemctl poweroff` sequence as graceful. Detection logic too narrow.

All four Sprint 28 bug-fix candidates filed in `offices/pm/inbox/2026-05-08-from-spool-sprint-28-bug-fixes-consolidated.md` for Marcus to groom.

---

## Session 11 — 2026-05-11 (short, single-task)

**Context**: Mike ran `python src/server/analytics/calibration.py --calibrate --apply` on his Windows laptop and reported "no errors" as the US-316 IRL smoke test for V0.27.4. Quick spot-check on what that actually validated.

### What Happened

**US-316 narrow validation: ✅ GREEN.** Confirmed by reading `src/server/analytics/calibration.py` (file ends at line 354, no `__main__` block, no argparse). The PYTHONPATH bootstrap Rex added (lines 59-74, mod-history line 18-24) does what it's supposed to: imports resolve when invoked from any cwd. Mike's "no errors" exit IS the US-316 acceptance signal. The `--calibrate --apply` args were ignored by Python (no argparse) and the module loaded + exited zero. Acceptance per sprint.json was "calibration.py runs to completion when invoked locally" — narrowly green.

**Broader UX validation: ❌ BLOCKED on two new bugs.** Ran the real CLI `python scripts/report.py --calibrate --device chi-eclipse-01` (where the actual `--calibrate` flag lives per the docstring at calibration.py:47-50). Two crash paths:

1. **`pymysql` not in `requirements-server.txt`** — `scripts/report.py:92-95` rewrites async DATABASE_URL (`mysql+aiomysql`) to sync (`mysql+pymysql`) for CLI use, but only `aiomysql>=0.2.0` is declared. Clean install crashes with `ModuleNotFoundError: No module named 'pymysql'`. Affects ALL CLI report paths (`--drive`, `--trends`, `--calibrate`), not just calibration.

2. **`_DEFAULT_DB_URL_FALLBACK = "sqlite:///data/server_crawl.db"` is phantom** — the sqlite file exists but has empty schema (no `drive_summary` table). Any CLI invocation without DATABASE_URL env or `--db-url` flag falls into the fallback and crashes with `sqlite3.OperationalError: no such table: drive_summary`. Confusing "footgun" — implies local sqlite dev works but doesn't.

**PM note filed**: `offices/pm/inbox/2026-05-11-from-spool-calibration-cli-pymysql-missing.md`. Two stories proposed for Sprint 32 / V0.27.6:
- **Story A (XS, P1)**: Add `pymysql>=1.1.0` to `requirements-server.txt`. One-line dep add.
- **Story B (S, P3)**: Either remove or fix the sqlite fallback. Three options (remove / probe-and-friendly-error / TD-only). My recommendation: remove (Option A).

### Stakes

Neither bug threatens V0.27.4 deploy itself — US-316 acceptance was narrow and IS green. V0.27.4 stays on its sprint branch per chain-end-merge rule, no amendments needed. But the broader implication — "Mike can run calibration from his laptop" — won't be true until Story A lands. The V0.27 chain validation should NOT claim end-to-end calibration CLI works until then.

For my domain interest (baselines content): I still can't actually peek at production `baselines` table from Mike's laptop without either installing pymysql or SSHing to chi-srv-01 and using MariaDB CLI directly. Will revisit after Story A.

### Why Mike's "no errors" was a misleading signal

`calibration.py` looks like a CLI (it's in `analytics/`, has the right-sounding name, takes flag-like argv). It is not a CLI. Its docstring is unusually explicit about this (line 47-50) but a casual invocation won't read the docstring. Combined with US-316's documentation framing it as "calibration.py runs to completion," it's reasonable to assume the script does something. It doesn't. The actual CLI is `scripts/report.py --calibrate`.

This isn't a bug to fix — Ralph's defensive doc-writing is correct and `__main__` blocks shouldn't be added to library modules. It's a feedback memory for future me: when Mike says "I ran X and got no errors," verify X is an entrypoint that DOES something before treating "no errors" as validation evidence.

### Server-side state inspection (after Mike's nudge to use SSH+mysql route)

Initial PM note framed the calibration block as just two bugs (pymysql + sqlite fallback). Mike pointed out I had MariaDB CLI access via the documented chi-srv-01 SSH route. Used it. The picture is much deeper than the two CLI bugs:

| Table | State |
|---|---|
| `obd2db.baselines` | 0 rows — never been calibrated |
| `obd2db.drive_summary` | 3 ghost rows from 2026-05-01 (id=12/13/14) — every meaningful field NULL, `drive_id=NULL` on all three. Stale pre-Session-10-cleanup shells for drives 3/4/5. |
| `obd2db.drive_statistics` | 0 rows — Session 10 cleanup wiped 84 stale rows; nothing has been re-written since |
| Pi-side `obd.db.drive_summary` | 4 rows (drive_id 2/3/4/5). **Drives 6-10 are missing.** Writer stopped firing after April 29 — confirms the B-059 / US-310 regression. Even the 4 rows that exist have `ambient_temp_at_start_c` + `starting_battery_v` NULL (early-drive backfill gap). |

**Calibration is gated on far more than Story A alone.** Even if pymysql lands tomorrow, `--calibrate` returns "Need 5 more real drives" (`countRealDrives()` returns 0; `MIN_REAL_DRIVES=5`). The full chain:
1. Story A (pymysql) — V0.27.6
2. B-063 (fuse-box hardware) — pending
3. US-310 IRL validation (drive_summary writer) — pending Drive 11+ post-B-063
4. US-315 IRL validation (sync UPDATE delta) — pending Drive 11+ post-B-063
5. **drive_statistics writer wired and firing** — unclear if any current story owns this; flagged Marcus in the PM note
6. ≥5 real drives accumulated with populated `drive_statistics` rows

For my domain interest (pre-mod baseline shelf): `knowledge.md` remains the source of truth (drives 3-8 documented there). The DB doesn't reflect the shelf and won't for several sprints minimum.

PM note updated with this addendum + explicit ask: is anyone tracking the drive_statistics writer between US-310 and US-315? Possible gap #5.

### Lesson for future me

When Mike says "you have used X in the past" — check auto-memory for X before assuming it's not available. The `reference_chi_srv_01_obd2db_access.md` memory had the exact SSH+mysql pattern documented. I should have pulled that into my plan up-front instead of hitting the pymysql wall first and only then reaching for it. Time cost was small but the right-shape investigation would have surfaced the deeper findings (empty baselines, ghost drive_summary rows, missing Pi-side rows 6-10) in the first pass, not the second.

Saving as feedback memory: `feedback_check_memory_before_assuming_tool_gaps.md`.

### Deeper validation pass (Mike's "anything else?" prompt)

Went one layer deeper. Picture is more positive than the initial framing, and **V0.27.4 US-315 has first IRL validation evidence**.

**Realtime data writer + DriveDetector = WORKING.** Pi-side `realtime_data` has 7,085 / 4,222 / 8,268 / 1,095 / 572 rows for drives 6-10 respectively. Drive 8's 8,268 rows match MEMORY claim exactly — knowledge.md's pre-mod baseline shelf is intact and verifiable. The regression is **narrowly** the drive_summary roll-up writer (the row-at-drive-end), NOT the broader telemetry pipeline.

**NEW P3: 61,293 NULL-drive_id orphan rows** accumulated in `realtime_data` since Session 10 cleanup. Reconnect-loop noise + I-019 warm-restart-cranking. Filed as Story C candidate for V0.27.6 (periodic cleanup OR writer-side guard).

**B-065 directly observed on server-side `battery_health_log` (== drain_event):**
| drain_event_id | Pi-side end | Server end | synced_at | Status |
|---|---|---|---|---|
| 11-15 | All closed | All NULL | start-time | Stranded (pre-V0.27.4) |
| **16 (19:47Z 5/10)** | 20:00:46 | **20:00:46** | 19:47:17 | **CLOSED both sides** |

**US-315 (V0.27.4) IS WORKING for battery_health_log.** Row 16's synced_at (19:47:17) is BEFORE its close (20:00:46) — proves the close came via UPDATE, not as part of initial INSERT. Exactly the new sync path US-315 shipped. (`synced_at` is INSERT-only, doesn't bump on UPDATE — useful diagnostic detail.)

**Caveat:** This only validates US-315 for the battery_health_log table. The drive_summary side of US-315 still needs Drive 11+ post-B-063. Strong directional signal, NOT bigDoD closure. Marcus shouldn't update `regression_manifest.json` F-007 until both sides validate.

**NEW P3: Stranded historical drains 11-15** — US-315 doesn't auto-backfill. One-off SQL needed. Filed as Story D candidate for V0.27.6.

**B-063 confirmed actively impacting work** — Pi went unreachable mid-investigation (SSH timeout), came back ~30s later. Brownout/flake pattern. Fuse-box swap remains the gate.

### Tuning-domain interpretation

This is good news for Spool. The pre-mod baseline shelf in `knowledge.md` for drives 3-8 is fully recoverable — the underlying realtime_data rows exist on the Pi for every drive. When the chain validates (post-B-063 + Drive 11+ + drive_summary writer fix per US-310 + drive_statistics writer wired), I can backfill server-side aggregates from Pi-side data. The shelf claim isn't a phantom.

The actively-working US-315 path means once Drive 11+ happens, the drive_summary close will propagate too. That's the unblock for calibration to ever produce proposals.

### Session Outcome

- 1 PM note filed + 2x updated (Sprint 32 grooming candidates A + B + C + D + Q-for-Marcus about drive_statistics writer)
- US-316 confirmed green (narrow acceptance)
- US-315 first IRL validation evidence captured (battery_health_log side only — caveated)
- Regression narrowed: NOT a broad pipeline failure, only the drive_summary roll-up writer
- Pre-mod baseline shelf for Drive 8 verified (8,268 rows confirmed)
- 4 candidate stories surfaced for V0.27.6: A (pymysql), B (sqlite fallback), C (orphan cleanup), D (historical drain backfill)
- 1 feedback memory saved (check memory before assuming tool gaps)
- 1 real-time B-063 hardware confirmation (Pi SSH timeout mid-session)
- No code changes (Spool doesn't write code, per CLAUDE.md role definition)

---

## Session 12 — 2026-05-12 (V0.27.6 deploy + Drive 11 + Drain Test 17 — watershed unblock)

**Context**: Multi-event session covering Marcus's V0.27.6 deploy (6 stories from Session 11's PM note), Mike's B-063 fuse-box buck-converter install + validation, Drain Test 17 (bench), Drive 11 (first car-coupled clean drive in project history), Drain 18 (post-park), and Mike's pip-install closing the US-320 loop. Detailed Pi-side + server-side validation of nearly every story in the V0.27 chain. The session that finally unblocked the project's primary mission after 5 days of B-063 hardware blocker.

### What Happened

**B-063 fuse-box buck converter installed and validated** — Mike installed the Pololu-equivalent buck converter on the fuse-box switched 12V circuit. Behavior confirmed: ON when key in AUX/ON, OFF when key OFF. Exactly the MEMORY.md "POST-B-063 target" spec. Five days of "current/stereo USB-C" undersized power is over.

**V0.27.6 (gitHash `0ef32a6`, releasedAt 2026-05-12T00:15:12Z) deployed by Marcus mid-session.** Ships 6 Sprint 32 stories from Session 11's PM note + grooming: US-320 (pymysql to requirements), US-321 (remove phantom sqlite fallback), US-322 (Pi orphan cleanup + systemd timer), US-323 (server battery_health backfill 11-15), US-324 (drive_statistics writer via Ollama-decouple), US-325 (BT reconnect exponential backoff + Pi rebuild durability). Fastest grooming-to-deploy turnaround I've observed (Spool's V0.27.6-candidate list filed 2026-05-11 ~late evening; shipped less than 12 hours later).

**Drain Test 17 (bench drain, V0.27.6 ladder validation) — FIRST 5-OF-5 PASS IN PROJECT HISTORY.** Mike unplugged Pi at 2026-05-12T00:20:00Z. Stages fired textbook: WARNING@00:23:26Z@3.69375V, IMMINENT@00:31:01Z@3.53125V, TRIGGER@00:34:32Z@3.44125V. Runtime 666s (11:06). Pi-side close-event written cleanly (drain_event_id=17 fully closed). Server-side close-event UPDATE propagated via V0.27.4 US-315 sync delta path (second confirmation after drain 16 on 5/10). Bash logger 204 rows, full curve 3.906V → 3.339V, no `i2c_err`. **Drain Test 17 supersedes Drain Test 15 as the new authoritative reference** in `drain-test-procedure.md` (entered in Historical Drain Test Log; full Reference Result swap deferred to next session).

**Drive 11 captured — first true car-coupled clean drive in project history.** Mike unplugged Pi → moved to Eclipse → key turn → 23:27 mixed city/highway drive with multiple boost pulls → parked. Pi-side telemetry: 10,839 realtime_data rows at **462 rows/min** (best capture rate in project history, edges Drive 8's 459). starting_battery_v=14.5V (alternator charging confirms buck-converter reads car system voltage), ambient_temp_at_start_c=18.0°C, drive_start_timestamp populated. Only one 5-second mid-drive AC blip (01:25:51-56) vs the constant flicker of Drives 9/10. **B-063 buck converter validated under sustained drive load.**

**Drive 11 engine analysis — knock-retard signature characterized.** New under-load records: peak RPM 5441 (Drive 7 was 5379), peak speed 147 km/h ≈ 91 mph (Drive 7 was 84 mph), peak ENGINE_LOAD 100%, peak MAF 135 g/s (Drive 7 still holds 159). Timing-advance distribution by load bucket showed CLEAN knock-retard pattern: cruise/idle ~24°, high-load 8-13° avg (10-15° retard). Specific knock event at 01:22:27-33: timing dropped 16° in 3 sec at RPM 4707, recovered to 23° as RPM climbed to 5441. Classic 4G63 mid-range knock window (4500-5000 RPM peak VE zone). ECU managing knock correctly on **[CORRECTED 2026-05-15: 93]** octane + stock 14b. No DTCs, no MIL, no thermal/fueling concerns. Fuel system delivered (O2 pegged 0.92-0.96V = rich under boost, AFR ~12-13). Mike at 68.6% peak throttle — appropriately conservative.

**Drain 18 (post-park, V0.24.1 ladder under post-drive UPS conditions).** stage_warning fired 01:37:29Z at VCELL 3.68625V (4:17 post-key-off — partial-charge battery). Result inconclusive: `end_timestamp` NULL Pi-side. Two possible causes: (a) drain interrupted by AC restoration before TRIGGER fired, (b) Pi clock jumped 23 hours forward post-reboot (RTC drift / NTP catch-up) corrupting power_log timestamps. Filed as P2 investigation in V0.27.7 addendum, NOT current sprint story.

**Mike ran `pip install` post-session — US-320 fully validated IRL.** PyMySQL 1.1.3, aiomysql 0.3.2, SQLAlchemy 2.0.45 installed. Invocation `python scripts/report.py --calibrate --device chi-eclipse-01` against chi-srv-01 production MariaDB returned expected `Need 5 more real drives before calibration is meaningful` banner with exit code 0. First end-to-end CLI success.

**V0.27.6 IRL scorecard**:
- ✅ US-320 pymysql — validated end-to-end (post-pip-install)
- ✅ US-321 phantom sqlite removed — validated NOW
- ✅✅✅ US-322 orphan cleanup — 61,293 → 199 rows (99.7% reduction)
- ❌ US-323 server backfill — rows 11-15 STILL NULL on server
- ❌ US-324 drive_statistics writer — table doesn't exist Pi-side
- (untested) US-325 BT reconnect — needs log inspection

**Plus NEW REGRESSION discovered**: US-308 `prior_boot_clean` detection NULL on both post-V0.27.6 boots (was =1 on all 3 pre-V0.27.6 boots). V0.27.6 broke US-308's journal parsing. Suspect US-322 systemd timer interference OR US-325 boot-sequence change. P1 candidate Story G for V0.27.7.

**V0.27 chain validation results**:
- ✅ US-310 drive_summary 12-field writer — FIRST IRL PASS (Drive 11 row populated)
- ✅ US-311 DriveDetector cold-start — clean drive_id=11 assignment
- ✅ US-317 drive_summary Ollama decouple — drive_summary row landed without Ollama trigger
- ✅✅ US-315 sync UPDATE (battery_health side) — drains 16+17 both fully synced
- ❌ US-315 sync UPDATE (drive_summary side) — Drive 11 row on server is EMPTY SHELL (`start_time NULL`, `duration_seconds NULL`, etc.). The fix landed for battery_health_log delta but did NOT extend to drive_summary delta. **P1 Story X for V0.27.7.**
- ❌ B-064 drive_counter sync gap — server still at last_drive_id=3, Pi at 11

**4 PM notes filed to Marcus tonight**:
1. `2026-05-12-from-spool-drive-11-v027-chain-validation-and-v0276-failures.md` (main note: Stories X/Y/Z/W)
2. `2026-05-12-from-spool-add-map-pid-to-default-poll-list.md` (MAP PID add feature ask)
3. `2026-05-12-from-spool-v0277-addendum-drive12-independent-work.md` (Stories E/F/G — Drive-12-independent work)
4. (updated addendum with Bug 3 / Story G US-308 regression)

**Procedure doc patch**: `drain-test-procedure.md` Step 4 query `software_version` schema-drift fix + Drain Test 17 added to Historical Drain Test Log (5/5 PASS).

### Key Decisions

- **Drive 11 joins pre-mod baseline shelf as 4th driving entry** (drives 6/7/8/11). FIRST clean car-coupled Pi-powered drive. New gold-standard rows/min benchmark (462).
- **Drain Test 17 supersedes Drain Test 15 as authoritative bench reference** — 5/5 PASS vs 4/5. Procedure doc updated; full Reference Result section swap deferred to next session.
- **Knock-retard pattern characterized as healthy and expected** for stock-tune 4G63 on ~~91~~ **[CORRECTED 2026-05-15: 93]** octane with stock 14b. ECU doing its job. **No safety concerns flagged**, no advisory issued.
- ~~**Recommendation to Mike: tank of 93 octane next** for A/B knock-retard comparison.~~ **VOID 2026-05-15 — CIO clarified the fuel was 93 octane all along (misreported 91); no A/B exists, the baseline IS the 93-octane reference. See knowledge.md fuel-grade correction banner.**
- **MAP PID gap (PID 0x0B) filed as feature request to Marcus** — recommended Option A (ride-along with V0.27.7) over Option B (V0.28.0 feature sprint); Mike approved sending. Spool deferred Marcus's call on sprint discipline.

### Current Vehicle State

- **Hardware**: 1998 Eclipse GST 4G63 / TD04-13G stock + cold air intake + BOV + FPR + fuel lines + oil catch can + coilovers + engine/trans mounts. **B-063 fuse-box buck converter installed and validated** — eliminates the Pi power-undersize blocker that gated 5 days of validation work. Pi now reliably powered on key-on, cleanly drains on key-off, V0.24.1 ladder fires correctly.
- **Tune state**: stock ECU + modified EPROM, ECMLink V3 still pending summer install.
- **Telemetry capture**: Drive 11 captured 16 PIDs (BATTERY_V, COOLANT_TEMP, DTC_COUNT, ENGINE_LOAD, FUEL_SYSTEM_STATUS, INTAKE_TEMP, LFT1, MAF, MIL_ON, O2_B1S1, O2_B1S2, RPM, SFT1, SPEED, THROTTLE_POS, TIMING_ADVANCE). **MAP NOT captured** — flagged for V0.27.7 ride-along OR V0.28.0.
- **Engine health**: graded HEALTHY under full operational envelope (Drive 11 expanded the envelope to 91 mph / 5441 RPM / 100% load). Knock-retard signature present in the expected 4500-5000 RPM mid-range window — ECU correctly managing detonation risk on **[CORRECTED 2026-05-15: 93]** octane.
- **No DTCs, no MIL.**

### Open Items

- **MAP PID add scheduling** — Marcus's call: ride-along V0.27.7 (Option A, my preference) OR V0.28.0 feature (Option B).
- **Drain 18 disambiguation** — bench-drain test post-V0.27.7 should disambiguate (a) AC-interrupt-no-close vs (b) close-event regression vs (c) RTC drift artifact.
- **Pi clock drift / RTC issue** — Pi rebooted at 01:45:56Z (Pi time) but power_log subsequent rows show 2026-05-13. NTP/RTC inconsistency. P3 observability for V0.28+ if it recurs.
- **Pre-mod baseline shelf gaps** (carried from earlier): sustained WOT entry (Drive 11 was 68% throttle peak, not WOT), hot-soak entry, wet-pavement entry, cold-engine-WOT entry.
- **B-062 (drain_event close targeted fix) re-eval** — drains 16/17 closing correctly now via V0.27.4 + V0.27.6 carry-forwards. Marcus's call to close as superseded vs keep open until Drive 12's drain closes cleanly too.
- **V0.27.7 grooming pending** — 7 candidate stories filed (X/Y/Z/W/E/F/G). 4 of 7 Drive-12-independent (Y/E/F/G); 3 need Drive 12 (X/Z/W).

### Session Outcome

- B-063 hardware blocker CLOSED — biggest single unblock of the project's primary mission since the 9-drain saga ended
- Drive 11 captured as 4th pre-mod baseline shelf entry + first clean post-B-063 drive
- Drain Test 17 = first 5-of-5 PASS in project history
- Knock-retard signature characterized — new tuning-baseline artifact in knowledge.md
- V0.27.6 IRL scorecard: 3 PASS + 2 FAIL + 1 untested + 1 regression introduced (US-308)
- 4 PM notes to Marcus for V0.27.7 grooming
- 1 procedure-doc patch (schema drift fix + Drain Test 17 historical entry)
- No code changes (Spool's lane); no safety advisories issued (engine grade-A healthy under expanded envelope)

---

## Session 13 — 2026-05-13 (Drain Test 19 review + V0.27.7/V0.27.8 IRL validation + A2AL adoption)

**Context**: Morning catch-up session. Mike informed Spool that (a) V0.27.8 had shipped overnight (Sprint 34 — 5 stories including TWO Spool candidates, Stories E + F), (b) Pi did an unmonitored bench drain last night on V0.27.7, (c) Pi power-state was post-drain (currently recharging). Spool's job: review the unmonitored drain, validate V0.27.7 + V0.27.8 stories from the resulting data, file V0.27.9 candidates. Plus: Mike directly asked whether Spool was using the A2AL skill for agent-to-agent comms (honest answer: N — corrected this session).

### What Happened

**Drain Test 19 review (V0.27.7 era, 2026-05-13T02:59:42Z unplug, unmonitored)** — Pi-side data reconstruction confirms 5-of-5 PASS:
- WARNING 02:59:42Z VCELL 3.69875V ✓ (3.69-3.71V envelope)
- IMMINENT 03:09:53Z VCELL 3.54V ✓ (3.50-3.60V)
- TRIGGER 03:13:33Z VCELL 3.44375V ✓ (3.40-3.46V)
- Runtime 831s = 13:51 — **second-longest clean drain on record** (Drain 15 was 13:06). Battery fully rested + recharged after Drive 11 → 23 hours idle.
- Pi-side close-event written (drain_event_id=19 closed cleanly)
- Server-side close synced via US-315 UPDATE path — third consecutive confirm (drains 16/17/19)
- **Drain Test 19 should supersede Drain Test 17 as the new authoritative reference once a fully-monitored V0.27.8 bench drain is captured.** Procedure-doc update deferred (carries forward Drain 17 deferral).

**US-308 / US-330 regression chain — CLEAN VALIDATION:**
- Post-V0.27.7 boot row `e065ca38` (recorded 2026-05-13T03:12:33Z) has `prior_boot_clean=1` + populated journal timestamps.
- Compare to two post-V0.27.6 boots (NULL on prior_boot_clean — Spool's Session 12 finding).
- Pre-regression / regression / fix chain is now load-bearing reference for "V0.27.6 broke X / V0.27.7 fixed X" pattern. **Validates Marcus's race-guard fix for journalctl timing under US-322 IO contention.**

**V0.27.7 stories IRL scorecard**:
- ✅ US-330 startup_log prior_boot_clean fix — validated via Drain 19 boot row
- ⚠️ US-326 drive_summary server-side analytics writer — code shipped; forward-only fix; Drive 11 row 15 won't auto-heal because Pi-side row hasn't been touched since drive_end 5/12. **Drive 12 is the real test.**
- ⚠️ US-327 backfill wired into deploy-server.sh — script wired but no auto-run observed for rows 11-15. Mike directed manual one-shot via Ralph (NOT a sprint story).
- ⚠️ US-328 drive_statistics Pi-side table — schema present Pi-side; 0 rows because writer is server-side per BL-015 Option C; depends on US-326 chain. **Drive 12 is the real test.**

**V0.27.8 (Sprint 34) IRL scorecard — Marcus shipped 5/5 stories overnight including TWO of Spool's V0.27.7-addendum candidates**:
- ✅✅ **US-336 (Spool Story F — 199 orphan 4h sweep)** — Pi-side NULL-drive_id orphan count: **199 → 0**. Sweep flawless.
- ❌ **US-335 (Spool Story E — Pi-side drain 1+9 backfill)** — drains 1 + 9 + 18 still NULL end_timestamp Pi-side. Backfill didn't fire OR didn't take. V0.27.9 retry candidate.
- ⚠️ US-331 (US-327 backfill works from Windows + chi-srv-01) — code shipped; rows 11-15 still NULL until manual run.
- ⚠️ US-333 sync_history TZ — orthogonal; not validated yet; will check pre/post next bench drain.
- ✅ US-334 (orphan-cleanup IO throttle + ordering) — implicit pass via Drain 19's clean ladder + working startup_log under V0.27.7 carry-forward. Deliberate validation pending V0.27.8 monitored bench drain.

**Drain 18 explained (resolved Session 12 mystery)** — `power_log` history: stage_warning fired 01:37:29Z; NO IMMINENT or TRIGGER followed; next ladder activity Drain 19's stage_warning 25 hours later. **Drain 18 was a legitimate AC-restored-mid-drain interrupt during V0.27.7 deploy reboot, NOT a regression.** Current schema has no `end_reason='ac_restored_mid_drain'` close path — filed as V0.28+ candidate via Marcus note.

**Manual SQL backfill (Mike-directed, not a sprint story)** — Spool sent Ralph an A2AL inbox note with: source-pull command from Pi authoritative, expected values table, server-side UPDATE statements with `AND end_timestamp IS NULL` idempotency guard, transaction wrapper with verify-before-commit, mysqldump backup step, "show Mike pre-COMMIT" reminder. Mike executed the SQL; Spool verified post-run. **All 5 rows (11-15) populated server-side; values match Pi-side authoritative.** V0.27.4 US-315 historical-stranded-rows side CLOSED for this era. Server NULL-end-timestamp count dropped to 8 remaining (drain 18 + pre-V0.27.4 sync artifacts; none are V0.27.9 blockers).

**3 inbox notes sent to peer agents — all in A2AL/0.4.0 format (first session using shorthand)**:
1. To Marcus: `2026-05-13-from-spool-v0278-irl-findings-and-v0279-candidates.md` — V0.27.8 IRL scorecard + V0.27.9 candidates (US-335 retry + US-333 TZ confirm) + V0.28+ candidate (drain abort schema)
2. To Ralph: `2026-05-13-from-spool-manual-sql-backfill-bhl-11-15.md` — manual SQL backfill with full safety protocol
3. To Marcus: `2026-05-13-from-spool-ack-bhl-11-15-backfilled.md` — ack/close on V0.27.4 historical-stranded issue, drop from V0.27.9 candidate stack

**A2AL adoption** — Mike asked Y/N whether Spool was using the A2AL skill for peer-agent comms. Honest answer: **N**. Through V0.27.6/7/8 chain, all PM notes were long-form markdown despite skill availability. ~6× token compression observed switching to A2AL (yesterday's V0.27.7 candidate note ~1,800 words in markdown vs today's V0.27.8 note ~280 words carrying equivalent load-bearing content). Going forward: A2AL for all agent-to-agent comms; reserve markdown for human-facing reports.

### Key Decisions

- **Drain Test 19 supersedes Drain Test 17 as authoritative reference candidate** — but full Reference Result section swap in `drain-test-procedure.md` deferred until a **fully-monitored V0.27.8 bench drain** lands (Drain 19 was unmonitored). The monitored drain becomes the canonical reference.
- **Manual SQL backfill outside-of-sprint** approach validated end-to-end — pattern available for future "one-shot data-hygiene" scenarios where the fix is a single targeted SQL UPDATE that doesn't warrant a sprint story. Safety protocol (backup → transaction → verify → show Mike → commit) held cleanly.
- **A2AL is now Spool's default for agent-to-agent comms.** Will continue using markdown for human-facing reports per skill guidance.

### Current Vehicle State

- **Hardware**: unchanged from Session 12 (B-063 fuse-box buck converter ACTIVE; 1998 Eclipse GST 4G63 / TD04-13G stock + bolt-ons; ECMLink V3 still pending). **No vehicle changes this session.**
- **Tune state**: unchanged.
- **Engine health**: no new under-load capture this session (no Drive 12 yet). Drive 11's AUTHORITATIVE KNOCK-RETARD CHARACTERIZATION remains the latest engine-side knowledge.
- **Telemetry capture**: unchanged from Session 12 — 16 PIDs captured Drive 11, MAP still NOT captured (B-074 filed for V0.28+).
- **UPS HAT runtime envelope refined**: 13:51 sustained (Drain 19, fully-rested battery) vs 13:06 (Drain 15, fully-rested) vs 11:06 (Drain 17, partial-rest battery). Confirms the >10 min healthy-drain expectation; envelope can stretch to ~14 min with optimal battery state.

### Open Items

- **Drive 12 is THE gate** for the rest of the V0.27 chain — server-side drive_summary heal (US-326), drive_statistics writer chain (US-328 server-side path via US-326), B-064 deferred — all hinge on it.
- **V0.27.8 monitored bench drain when Pi battery rests above 3.9V VCELL** — validates US-334 deliberately + first formal V0.27.8 reference point + sync_history TZ pre/post (US-333) snapshot. Currently end_soc=3.44V post-Drain-19; needs several hours of AC charging.
- **US-335 retry** — drains 1 + 9 + 18 still open Pi-side; V0.27.9 candidate filed to Marcus.
- **US-333 sync_history TZ validation** — pending bench drain.
- **93 octane A/B comparison drive** when convenient — quantifies knock-retard reduction with higher-octane fuel. Carries forward from Session 12.
- **MAP PID (B-074)** filed for V0.28+; not urgent given Drive 11 baseline shelf entry already captured the knock-retard signature without it.
- **Drain abort schema** (`end_reason='ac_restored_mid_drain'`) — V0.28+ candidate filed; closes the "drain interrupted by AC" gap; cosmetic, not load-bearing.
- **Drain Test 19 procedure-doc reference swap** — deferred until monitored V0.27.8 bench drain lands. Two deferred swaps now stacking (Drain 17 → Drain 19 → monitored-V0.27.8).

### Session Outcome

- Drain Test 19 reviewed + confirmed 5-of-5 PASS (unmonitored but Pi-side data reconstructs the full picture)
- V0.27.7 + V0.27.8 IRL scorecard delivered to Marcus (US-330/US-336/US-326/US-327/US-331/US-328/US-333/US-334/US-335 each marked PASS/FAIL/PENDING)
- V0.27.6 US-308 regression definitively CLOSED via V0.27.7 US-330 IRL validation
- V0.27.4 US-315 historical-stranded-rows side (rows 11-15) CLOSED via Mike-executed manual SQL backfill
- 3 A2AL notes filed to peer agents (first session using shorthand)
- A2AL skill adopted as default for peer-agent comms going forward
- No knowledge.md update (no new engine-tuning information; drain runtime envelope refinement captured in sessions.md only)
- No code changes (Spool's lane); no safety advisories issued

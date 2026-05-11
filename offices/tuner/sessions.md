# Spool — Session Log

> Running log of sessions, conversations, and events. For detailed tuning knowledge, see `knowledge.md`.
> For Spool's identity and operational model, see `CLAUDE.md`.

> **Archived sessions**: Sessions 1-7 (April 2026) live in `sessions-archive-2026-04.md`. Rotated 2026-05-08 (Session 9 closeout) for size management.

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

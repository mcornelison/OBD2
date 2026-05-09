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

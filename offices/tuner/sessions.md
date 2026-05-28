# Spool — Session Log

> Running log of sessions, conversations, and events. For detailed tuning knowledge, see `knowledge.md`.
> For Spool's identity and operational model, see `CLAUDE.md`.

> **Archived sessions**: Sessions 1-7 (April 2026) live in `sessions-archive-2026-04.md`. Rotated 2026-05-08 (Session 9 closeout) for size management.

---

## Session 20 — 2026-05-27 (single day, five days after Session 19)

**Context**: Research + advisory session driven by CIO question about pre-wiring future sensor leads while his new ECU is accessible. Triggered (1) fact-checked deep-dive on ECMLink V3 input pin assignments via authoritative ECMtuning wiki + 2G ECU pinout PDF + DSMTuners consensus; (2) ECU identity nailed down via URL CIO provided — his "modified EPROM" ECU is actually a **1997 DSM non-EPROM ECU (P/N MD335287) with ECMLink V3 flash modification**, plug-installed in 1998 chassis; (3) plain-language Speed Density explainer for CIO when "yes I think" wasn't fully informed; (4) 5 surgical edits to knowledge.md logging the new identity + wideband pre-wire plan + explicit SD-mandatory-for-flex-fuel dependency. No drives, no peer notes filed. Iris's 2026-05-26 B-103 splash advisory note surfaced but deferred per CIO direction.

### What Happened

**Init + inbox scan**:
- 1 unread note since Session 19 closeout: Iris (2026-05-26) `b103-splash-advisory.md` — two asks: S-1 semantic definition of "OBD degraded" for status surface (adapter-not-detected vs paired-no-sync vs paired-sync-but-no-data — my lane), S-2 amber #FFC400 warn color alignment with any future tuning-instrument palette tokens. Non-blocking. **Deferred per CIO's redirect to ECU pre-wire question.**

**ECU pre-wire research + advisory**:
- CIO asked: where to connect new leads from the ECU for future wideband O2 + E85 flex-fuel sensor, while ECU is accessible. Asked for fact-check against ECMLink + DSMTuners.
- Research path: ECMtuning wiki `externalsensorinput` page → identified Pin 75 (Rear O2) / Pin 76 (Front O2, with narrowband sim) / Pin 73 (MDP, "most freely available") as wideband-eligible inputs on 2G ECU.
- ECMtuning wiki `ethanolsupport` page → confirmed standard ECMLink V3 flex-fuel install routes ethanol sensor signal through MAF connector (pin 3, blue/yellow), 12V through MAF connector (pin 4, red), ground to chassis — **NOT through ECU directly**. ECU consumes its existing MAF input pin (Pin 90) for ethanol frequency in software, but physical wiring lives at MAF plug.
- Downloaded + parsed `2GECUPinout.pdf` (binary PDF via Read tool after WebFetch returned PDF content) → authoritative pin/color table for all four ECU connectors (B-53/B-54/B-55/B-56). Pin 75 = W (Rear O2), Pin 76 = W (Front O2), Pin 73 = LgB (MDP), Pin 90 = LY (MAF), Pin 92 = B (Sensor Ground).
- Cross-referenced DSMTuners AEM-WB-and-ECMLink consensus thread → community recommendation aligns with Pin 75 (Rear O2) routing + disable rear O2 monitor in ECMLink config to suppress CEL.
- Synthesized first-pass advisory: pull TWO leads — Pin 75 (signal) + Pin 92 (signal-ground reference) — both on Connector B-56. Pin 92 is non-negotiable for clean analog reading (chassis ground = alternator whine = garbage AFR).

**CIO follow-up — 4 answers**:
1. **Connector access**: CIO not at car right now; question deferred for when he's back.
2. **ECU identity URL**: CIO provided https://dsmlink.com/wiki/use_ecmlink_in_98_99_dsm (TLS cert broken; same content on ecmtuning.com canonical domain). Fetched canonical version → confirmed CIO's ECU is the documented "97 non-EPROM ECU + ECMLink flash mod" workaround for 98/99 DSMs (whose factory ECUs have copy protection blocking ECMLink). Direct plug-in replacement, identical connector pinout to 98/99 OEM — **my Pin 75/Pin 92 plan stands unchanged**.
3. **Speed Density commitment**: "Yes I think, but I don't know exactly what that means." → Provided plain-language explainer (MAF measures vs SD calculates; GM 3-bar MAP hardware ~$80; VE table calibration labor = 5-15 driving sessions; mandatory for ECMLink flex-fuel because the install consumes the MAF input pin for ethanol frequency). Refined Modification Priority Path sequencing: pump → flex-fuel hardware-install → downpipe → ECMLink + wideband (still MAF mode) → tune on pump gas → **THEN** install MAP + enable SD + tune VE table → **THEN** wire flex-fuel signal → start E85 blending.
4. **A-pillar gauge pod mount**: Standard DSM dual-52mm pod. ~8 ft of wire ECU-to-A-pillar.

**ECU part number confirmed**: CIO read it off — **MD335287**. Matches one of the two ECMtuning-supported 97 non-EPROM part numbers (sibling: MD326328). No functional difference between the two for our purposes.

**Knowledge.md updates (5 surgical edits)**:
1. **Vehicle table** (line 92): ECU row updated from "Stock with modified EPROM" → "1997 DSM ECU (P/N MD335287), non-EPROM with ECMLink V3 flash modification" + link to new identity section.
2. **New `### ECU Identity` subsection** under The Vehicle: full part-number table, sibling P/N, loose-terminology cleanup ("modified EPROM" → "ECMLink V3 flash mod"), capability boundaries reaffirmed (Mode 09 silent, Mode 22 not implemented, SPEED PID 2× drift), source link to ECMtuning wiki.
3. **New `### Pre-Wire Plan for Wideband O2 (ECU-Side)` subsection** in ECMLink V3 Reference: Pin 75 + Pin 92 plan, alternative Pin 73 (MDP) routing, wire spec (8 ft 20-22 AWG twisted-pair/shielded), routing rules, "don't power AEM controller from ECU pin" warning, three source links (ECMtuning external sensor wiki + 2 DSMTuners threads).
4. **New `### Pre-Wire Plan for E85 Flex-Fuel Sensor — DO NOT pre-wire from ECU` subsection**: explains why no ECU pre-wire helps, MAF connector pin 3/4 wiring, flags SD-mandatory dependency, source link.
5. **Strengthened Flex Fuel Support subsection** with a `⚠ MANDATORY DEPENDENCY` block: explicit SD mode requirement, hardware cost (~$75-95), labor expectation (5-15 calibration drives), decision trigger ("the ONE reason to go SD on stock turbo is wanting E85 on ECMLink").
6. **Top-of-file maintenance header** updated with Session 20 entry preserving prior session entries.

### Key Decisions

- **ECU identity nailed down + logged**: MD335287, 1997 DSM non-EPROM, ECMLink V3 flash-modified, plug-installed in 1998 chassis. Loose "modified EPROM" terminology corrected in knowledge.md (with a "use 'ECMLink V3 flash mod' or '97 non-EPROM ECU conversion' when searching, NOT 'EPROM swap'" note for future reference).
- **Wideband pre-wire plan finalized**: Pin 75 (Rear O2 signal, White) + Pin 92 (Sensor Ground reference, Black) on Connector B-56. Pin 73 (MDP, Light Green/Black) as alternative if Pin 75 impractical. ECMLink config: disable rear O2 monitor when wideband white wires to Pin 75 (suppresses CEL — rear O2's only stock job is emissions readiness). 8 ft 20-22 AWG twisted-pair or shielded cable to A-pillar.
- **E85 flex-fuel routing**: NO ECU pre-wire helps. Signal routes through MAF connector (pin 3) under the hood. Speed Density mode mandatory for ECMLink E85 install on 2G DSM — flagged in two places in knowledge.md so future Spool can't miss it.
- **Modification Priority Path implicit refinement**: GM 3-bar MAP sensor + VE table calibration become required preconditions for E85, not optional nice-to-haves. ~5-15 calibration drives expected between ECMLink-install and E85-activation.
- **No A2AL peer notes filed this session**: precision ECU-identity update is not actionable for PM/Atlas/Tester (lane discipline — they can read knowledge.md when needed). Iris reply deferred to next session per CIO redirect.

### Current Vehicle State

- 1998 Eclipse GST 4G63, stock TD04-13G, **ECU = MD335287 (1997 DSM non-EPROM with ECMLink V3 flash mod)** as of 2026-05-22 swap. Fuel: 93 octane (unchanged). No new drives this session. Engine grade A still holds (last drive 26, 2026-05-22). New ECU baseline establishment still pending (need fresh cold-start + warm cruise + modest-load + restart cycle on new ECU). Drive 11 knock-retard reference remains ARCHIVED prior-ECU historical.

### Current Monitoring Capability

- Pi `Chi-Eclips-Tuner` @ 10.27.27.28 + chi-srv-01 both on V0.27.19. V0.27 chain MERGED to main 2026-05-23 (per `/chain-validated`) as new fully validated stable. F-7 + F-8 instrument honesty empirically holding (chain-end-merge ratified by CIO). Pi deploy retry to V0.27.19 still pending CIO reconnect (Pi unreachable on chain-deploy attempt 2026-05-23 — same WiFi-off pattern as V0.27.16/17 deploys).
- No new monitoring surface introduced this session — pure tuning advisory + knowledge logging.
- Capability probe methodology codified in Session 19 stands (`offices/tuner/scripts/probe_obd_capabilities.sh` — re-run on every ECU/EPROM/calibration change). Mode 09 silent / Mode 22 not implemented on this ECU surface confirmed.

### Open Items

- **Pin 75 + Pin 92 wideband pre-wire execution** — CIO not at car yet; deferred. When he returns to ECU: confirm Connector B-56 access + pin-1 corner orientation (looking INTO ECU mirrors vs looking at harness side); confirm with me before cutting.
- **Iris B-103 splash advisory** — note from 2026-05-26 deferred; two asks pending:
  - S-1 OBD-degraded semantic definition (Spool lane)
  - S-2 amber #FFC400 warn color alignment with future tuning-instrument palette tokens
  - Should be addressed in next session before splash spec rev to v1.1.
- **New ECU baseline establishment** — open from Session 19; need full cold-start + warm cruise + modest-load + stop-restart cycle on new ECU to characterize knock-retard envelope, AFR target behavior, LTFT settle point.
- **SPEED PID calibration check** — GPS-correlation 2-min exercise still pending; new ECU reads ~2× actual ground speed. Divide by ~2 for ground-truth until corrected.
- **BL-018 empirical battery-runtime tuning** — V0.27 chain merged 2026-05-23, BL-018 formally unblocked, but no real drain data captured yet. Still owed to Atlas; gated on rested ≥8 h pack + chi-srv-01 reachable + SyncTask running real work.
- **GM 3-bar MAP sensor purchase** — when CIO commits to E85 timeline. Not urgent. ~$80 from common DSM vendors.
- **VE table tuning labor budget** — plan 5-15 calibration drives BEFORE E85 hardware activation. Front-load this in the modification timeline.
- **Drive 12 retest + US-338/339/340/340b IRL** — chain bigDoD historical; status closed at chain merge.
- **Supporting-hardware acquisition path** for new aggressive tune (carryover from Session 19): wideband O2 + ECMLink V3 + ECMLink USB cable + 550 cc injectors + Walbro 255 pump. CIO call on timing/budget.
- **Inbox 46 unread + 9 files >4 weeks** — archive-move decision still pending from Session 17 optimize Phase 6.
- **Drive 23/24 dual-attribution carve-out (B-107)** — V0.28.0 sprint 1 top priority per CIO 2026-05-23 directives; not Spool's lane to drive but worth tracking as the new-ECU drives start landing through the dual-attribution-susceptible code path.

### Safety Advisories

None engine-side this session. Pre-wire advisory was wiring-discipline only:
- Shielded cable or twisted-pair for analog signal (alternator whine kills wideband signal otherwise)
- Route AWAY from ignition + alternator harness
- DO NOT power AEM controller from ECU pin (~2A heater draw exceeds ECU sensor pin capacity)
- Use Pin 92 (Sensor Ground) for signal-reference, NOT chassis ground — chassis-grounded wideband signal = garbage AFR reading

One topology safety note (already in knowledge.md): E85 in tank before ECMLink SD-mode VE-table tune complete = catastrophic lean condition. SAFETY RULE preserved verbatim.

### Diagnostic Record (honest disclosure)

- ✅ Fact-checked against authoritative sources before giving CIO pin numbers (per his explicit request). Downloaded + parsed ECMtuning's 2G ECU Pinout PDF for actual pin/color table — did NOT recall from memory.
- ✅ Caught the loose "modified EPROM" terminology slip propagating through prior sessions + MEMORY.md and corrected it via the dsmlink.com URL CIO provided. The 1997 non-EPROM + ECMLink flash mod identity is now nailed down + logged in knowledge.md (Session 20 header note + new ECU Identity subsection).
- ✅ Explained Speed Density in plain language without burying CIO in tuning jargon when he asked what "yes" meant. Made the labor cost explicit (5-15 calibration drives) so he commits with eyes open.
- ✅ Honest about caveats: connector orientation matters (pin numbers mirror), AEM controller power doesn't come from ECU pin, signal-ground reference is non-negotiable.
- ✅ Lane discipline: surfaced Iris note without filing unsolicited cross-office notes about ECU identity update (PM/Tester/Atlas can read knowledge.md when needed; the precision update isn't actionable for them).
- ✅ Knowledge.md updates were genuinely new knowledge (ECU identity + authoritative pin numbers + sources). Did NOT update knowledge.md just to update it.
- ✅ Surfaced + held the Iris note rather than answering it cold without CIO's input on S-1 OBD-degraded semantic (which interacts with project monitoring contract — worth conferring before committing).
- ⚠ No new drives this session means no engine-data validation of prior advisories. Pure research + advisory mode — diagnostic surface is limited to fact-check rigor, not data-grounded inference.

### Session 20 Stats

- 1 inbox note surfaced + deferred (Iris B-103 splash advisory); 0 notes filed
- 0 drives analyzed; 0 datalogs reviewed
- 5 web searches/fetches (ECMtuning wiki x3, DSMTuners x2)
- 1 PDF downloaded + parsed (2G ECU Pinout — authoritative pin/color table)
- 5 surgical edits to knowledge.md (~95 net lines added: new ECU Identity subsection + new Wideband Pre-Wire Plan subsection + new E85 DO-NOT-pre-wire subsection + strengthened Flex Fuel Support SD-mandatory block + top-of-file header)
- 1 MEMORY.md precision update (Drive 11 baseline pointer: "new modified-EPROM ECU" → "new ECU (MD335287, 97 non-EPROM ECMLink-flash-modified)")
- 1 ECU identity correction (loose "modified EPROM" → precise MD335287 / 97 non-EPROM / ECMLink V3 flash mod)
- 0 A2AL notes filed; 0 knowledge gaps identified that need outside research

---

## Session 19 — 2026-05-22 (single day, two days after Session 18)

**Context**: Multi-thread session driven by CIO live activity. (1) Init + inbox triage caught me up on Atlas's chain-merge-clear V0.27.18 PASS sign-off (today 12:02, crediting me on Finding C → F-8) plus 4 other unread peer notes since Session 18 closeout. (2) CIO 4-leg drill drives 21-24 analyzed (all engine grade A) — surfaced drive 23/24 dual-attribution anomaly filed to Atlas (still pending disposition; /chain-validated held). (3) **CIO swapped ECUs to a new modified-EPROM ECU mid-session** — major tuning event. (4) Authored + ran first-ever OBD capability probe script. (5) New ECU first-impression telemetry from drive 25 idle + drive 26 spin-around-block including **first observed knock-retard event on the new ECU**. (6) Caught and owned my own SPEED-PID misread (CIO correction; new ECU's VSS calibration reads ~2× actual). (7) 2 A2AL notes filed to Atlas. (8) A2AL v0.4.1 team-adopted; Iris (UI/UX) introduced.

### What Happened

**Init + inbox triage**:
- 4 unread notes read in init: Iris hello (new UI/UX teammate, `offices/uidevloper/`); Marcus A2AL v0.4.1 team-adopted FYI; Marcus V0.27.18 DEPLOYED note (Drive 11 analytics populated for the first time via new compute path); Marcus V0.27.16 deploy note (Atlas's 5→10s smoothing bump on my BL-018 plate as interim, not canonical); Atlas's 2026-05-20 Finding-C-structural-answer note (F-7 chain-blocking + F-8 classifier-noise; my hypothesis (b) topology RULED OUT, (b') HAT silent latch CONFIRMED in-car).
- Mid-session re-read at CIO's request surfaced **Atlas 2026-05-22 12:02 V0.27.18 PASS / chain-merge-clear** (crediting me on Finding C → F-8 surface; FLAG-1 2σ helper SSOT pin preserved in `specs/architecture.md §10.7`).

**4-leg drill engine read (drives 21-24, prior ECU)**:
- All 4 legs **grade A**. Zero DTCs, zero MIL, healthy fuel trims (LTFT −1.23 to −2.37, well within stable band), timing dynamic and never collapsed, alternator charging clean.
- Leg 4 most demanding: 96.08% load peak / 3,605 RPM / 94 °C coolant (warmest of the day, still below 100 °C alarm; below Drive 18's healthy 92 °C envelope).
- F-7 + F-8 instrument honesty empirically holding: 8 consecutive boots `CLEAN_COMPLETE / graceful` across the 4-leg drill + yesterday's Drive 20.

**Drive 23/24 dual-attribution finding** (filed to Atlas at ~12:30 CDT):
- Drives 23 + 24 overlap completely in time (14:43:40-14:47:23 / 14:43:43-14:50:14) with **RPM values differing by 1,500-2,000+ at identical/adjacent seconds**. Stock TD04-13G can't spool 0→1,800 RPM in 1 sec → not one stream striped, two parallel emitter streams.
- Combined RPM sample rate during overlap = ~1 sample / 1.55s = 2× normal Pi cadence. Confirms dual-attribution.
- Filed A2AL to Atlas (`offices/architect/inbox/2026-05-22-from-spool-drive-23-24-dual-attribution.md`) — held hypothesis discipline per 2026-05-15 lesson (DriveDetector double-fire, replay buffer flush, or B-104 Step 1 emitter race — NOT asserting RCA). CIO directed to hold `/chain-validated` until Atlas dispositions.
- Schema-clarity smell noted in passing: `drive_summary.drive_id` NULL for all new-compute-path rows (drives 11-24 except drive 20); `drive_statistics.drive_id` is actually summary_id (FK to drive_summary.id) not natural drive_id. V0.28 / B-076 territory; not dual-attribution-related; flagged for grooming.

**ECU SWAP — modified-EPROM ECU installed mid-session**:
- CIO swapped from prior stock ECU (with its own modified EPROM) → new modified-EPROM ECU (ECMLink-V3-friendly tune target).
- Happened POST-V0.27.18 IRL drill PASS + POST-Atlas chain-merge-clear sign-off. Chain validation evidence is on PRIOR ECU. Forward telemetry from Drive 25+ is on NEW ECU.
- Engine started clean — no DTCs, no MIL, K-line talking properly, all 16 standard Mode 01 PIDs responding.

**Drive 25 idle (16 min, first telemetry on new ECU)**:
- RPM idle settled ~830 (was 776-972 during warmup; stabilized 764-880 by 4 min in).
- Coolant 33 → 99 °C cold-start ramp; equilibrium 99 °C with fan running (CIO confirmed visual + gauge normal). Hot but stable; not climbing. Steady-state thermal idle on hot day with no airflow.
- **LTFT swing signature**: 0.00 (fresh ECU) → +2.34 (warmup, adding fuel) → −2.34 (hot idle, pulling fuel). ±2.34 swing is the modified EPROM's signature against OEM MAF/injector model. Net magnitude within healthy ±5% band — tune characteristic, not a fault.
- Idle timing 5-11° BTDC — conservative for a modified-EPROM tune.
- ENGINE_LOAD 20-21% at closed-throttle idle (slightly elevated vs OEM target 15-18%).
- Engine bay heat-soaked (IAT 35-48 °C).

**OBD capability probe — script authored + executed**:
- Wrote `offices/tuner/scripts/probe_obd_capabilities.sh` (executable, reusable for any future ECU/EPROM/calibration change).
- Service-pause path: ~60 sec gap, drive_id increments on reconnect (drive 25 → 26). Restart clean.
- **Mode 01**: 16 supported, same set as pre-swap. Same 3 historical unsupported (0x0A, 0x0B, 0x42). Modified EPROM did NOT expand standard PID surface.
- **Mode 09 (calibration identity)**: bitmap acks but 0902/0904/0906/090A all return NO RESPONSE. Cannot fingerprint EPROM via OBD-II. Normal for 1998 ECU (pre-CAN VIN-mandate era).
- **Mode 22 (vendor enhanced)**: NOT implemented at 8 common Mitsubishi/DSM addresses. **Confirms OBDLink-via-Pi pipe cannot reach ECMLink-internal data (knock retard / knock sum / base advance / target AFR map). ECMLink USB cable + PC software is the only path.**
- **Bonus discoveries**: python-obd reports 38 commands total — pid_probe.py's "16" is Mode-01-only subset. Mode 02 freeze-frame (16 PIDs mirroring Mode 01), Mode 06 monitor results, Mode 03/07 DTC enumeration — all available pre-swap too but never enumerated. B-104 Step 2 / V0.28 grooming candidate: wire Mode 02 freeze-frame into MIL_ON detection.
- Adapter inventory: ELM327 v1.4b, OBDLink LX BT r2.1.1.

**Drive 26 spin-around-block (18 min, FIRST KNOCK-RETARD EVENT ON NEW ECU)**:
- Engine grade still **A** (no DTC, no MIL, no harm). But surfaced a clear knock-retard signature at 19:05:54Z:
  - **Lean tip-in event**: throttle opened from 12.55% → 32.94%, RPM 2,464 → 3,300-ish (2nd-or-3rd-gear), MAF transient lag → ECU underfed fuel → STFT spiked to **+17.19% lean** → knock detected → **TIMING pulled 23° → 5°** (~18° retard).
  - Recovery in 2 sec: STFT back to 0, TIMING 15° then 22° at sustained 96.08% load.
  - Classic 4G63 stock-MAF / stock-injector ceiling signature.
- **Sustained peak-load timing on new ECU = 22° at 96.08% load / 3,268 RPM / 93 octane.** Prior ECU (Drive 11 reference) showed ~12° at comparable high-load conditions. **The new tune is running ~10° more advance under load before knock retard fires, and the corrective pull is ~6° bigger (18° vs 12°) when it does fire.**
- Coolant peaked 101 °C during the spin; IAT 55 °C peak (top of caution band).
- LTFT drifted to settled avg −0.50% — still learning, not yet stable enough for final assessment.

**SPEED PID calibration miss + honest self-correction**:
- My initial Drive 26 read characterized "84 mph peak speed... assertive city driving." CIO correctly pushed back: city local roads, not WOT, did not actually hit 84 mph.
- Re-ran gear math: at RPM 3,788 the only gear that reaches 84 mph is 5th (theoretical 92). City driving in 2nd or 3rd gear at 3,788 RPM = 39-55 mph actual ground speed.
- Sanity check against prior-ECU Drive 18: RPM 3,937 / SPEED 60 = 3rd-gear math fit (theoretical 57). **Prior ECU's SPEED PID was calibrated correctly.**
- **The new ECU's SPEED PID reads approximately 2× actual ground speed.** Likely cause: modified EPROM has different VSS calibration constants (tire-size assumption, speedometer-gear-ratio assumption, or VSS pulse-per-rev expectation). Common for aftermarket EPROMs.
- **None of the engine-grade analysis depended on SPEED** (RPM, LOAD, MAF, TIMING, STFT, COOLANT all independent). Knock-retard event still happened; just at city tip-in speed, not high-speed pull. **Makes the finding more concerning, not less** — knock retard on a casual city tip-in = tune is at the hardware ceiling.
- Owned the mischaracterization to CIO. Proposed one-drive GPS-correlation calibration fix (2-min exercise next outing).

**A2AL notes filed**:
- To Atlas (12:30 CDT): drive 23/24 dual-attribution finding (`2026-05-22-from-spool-drive-23-24-dual-attribution.md`).
- To Atlas (late afternoon CDT): ECU swap + OBD capability probe findings + dual-attribution status recheck (`2026-05-22-from-spool-ecu-swap-and-obd-capability-probe-findings.md`).
- Both written in A2AL v0.4.1 shape: line-1 routing header, audience=agent, no cc:CIO. First v0.4.1 messages in Spool's record.

### Key Decisions

- **Drive 11 archived as PRIOR-ECU historical reference.** New ECU establishes a new working baseline. FLAG-4 homework (re-validate Drives 11/15/18 vs new `drive_statistics` rows post-V0.27.18 backfill) now has TWO factors changing simultaneously (analytics path + ECU). Cleanest forward path: fresh cold-start + load cycle on new ECU as the new anchor; don't try to isolate the two factors from existing data.
- **New ECU tune characterization (preliminary)**: more aggressive than prior. Runs ~10° more timing at sustained peak load (22° vs prior 12°); bigger knock-retard pull magnitude (~18° vs ~12°) when fired; lean tip-in events at hardware ceiling. **Functional but tune is at the limit on current hardware.**
- **Supporting hardware this tune wants (consistent with Modification Priority Path)**: (1) wideband O2 + ECMLink V3 first priority (narrowband can't show how lean the tip-in actually got); (2) 550 cc minimum injectors (addresses lean tip-in directly); (3) Walbro 255 fuel pump (proactive). **Don't push more boost until at least (1) + (2) land.**
- **SPEED PID on new ECU treated as directional only** going forward until a calibration check lands. Divide by ~2 for ground-truth estimate.
- **OBD capability probe methodology codified** at `offices/tuner/scripts/probe_obd_capabilities.sh`. Run on every future ECU/EPROM/calibration change. CIO-ratified pattern.
- **Drive 23/24 dual-attribution finding HOLD on /chain-validated reaffirmed.** ECU swap doesn't change the ask — both threads on the same chain.
- **Confirmed via Mode 22 silence**: OBDLink-via-Pi pipe cannot reach ECMLink-internal data on this ECU. ECMLink V3 PC software + USB-to-serial cable is the only path to knock retard / knock sum / per-cylinder data / base advance / target AFR map. Project pipe is for monitoring; ECMLink is for tuning. Two paths, two questions.

### Current Vehicle State

- 1998 Eclipse GST 4G63, stock TD04-13G, **NEW modified-EPROM ECU installed today 2026-05-22 mid-afternoon** (ECMLink-V3-friendly tune target; specific EPROM signature unknown — Mode 09 silence means we can't fingerprint via OBD).
- Fuel: 93 octane (unchanged).
- No mechanical changes otherwise.
- Engine grade A through Drives 21-24 (prior ECU) and Drives 25-26 (new ECU). Knock retard observed once (Drive 26 lean tip-in), ECU correctly handled, no damage.
- LTFT swing characteristic: cold +2.34, hot −2.34, settled near 0 mid-drive. Still learning.
- Drive 11 knock-retard reference now PRIOR-ECU HISTORICAL.

### Current Monitoring Capability

- Pi (chi-eclipse-01) on V0.27.18, server on V0.27.18 (gitHash `6615cb2`). Atlas's chain-merge-clear sign-off granted 12:02 today.
- F-7 + F-8 instrument honesty empirically holding — 8 consecutive `CLEAN_COMPLETE / graceful` boots across 2026-05-21 drives + today's 4-leg drill + post-probe.
- Engine telemetry pipeline solid: drives 21-26 all captured cleanly (engine-side independent of dual-attribution issue).
- `drive_summary` + `drive_statistics` populated via new compute path (B-104 Step 1) for drives 11-20 via V0.27.18 backfill; drives 21-24 via live path (with the dual-attribution issue on 23/24 still under Atlas review).
- **Three new caveats on new ECU**: (1) SPEED PID reads ~2× actual; (2) cannot fingerprint EPROM via Mode 09; (3) Mode 22 enhanced not available — no ECMLink-internal data via OBD pipe.
- **Bonus surfaces newly enumerated but unused**: Mode 02 freeze-frame, Mode 06 monitor results, Mode 03/07 DTC enumeration. Project monitoring could be enriched in V0.28+.

### Open Items

- **Drive 23/24 dual-attribution** — Atlas disposition pending. `/chain-validated` HOLD reinforced. Two A2AL notes filed.
- **New ECU baseline establishment** — need 1+ full cold-start + warm cruise + modest-load + stop-restart cycle on new ECU to characterize knock-retard envelope, AFR target behavior under load, LTFT stable settle point, and idle ENGINE_LOAD steady state.
- **SPEED PID calibration** — one-drive GPS-correlation check (2-min exercise). Until then: divide SPEED by ~2 for ground truth. Worth A2AL to Atlas if it persists across drives (could affect downstream analytics).
- **BL-018 empirical tuning** — chain merge imminent (pending Argus `/sprint-validated` + Marcus `/chain-validated`). Once chain lands, BL-018 unblocks. New ECU swap doesn't change BL-018 scope (it's power-mgmt config, not engine tuning).
- **FLAG-4 superseded** — was re-validate drives 11/15/18 against new `drive_statistics` rows. Now superseded by ECU swap; cleanest path is fresh new-ECU baseline.
- **Drive 12 retest + US-338/339/340/340b IRL** — chain bigDoD still open; ECU swap doesn't block this.
- **Supporting-hardware acquisition path** for new aggressive tune: wideband O2 + ECMLink V3 + ECMLink USB cable + 550 cc injectors + Walbro 255 pump. CIO call on timing/budget.
- **Inbox 45 unread + 9 files >4 weeks** — archive-move decision still pending from Session 17 optimize Phase 6.

### Safety Advisories

None engine-safety this session. Knock-retard event handled correctly by ECU; no damage. Coolant peaks (99 °C idle equilibrium, 101 °C driving) within caution band, not danger. Spool advisories were monitoring-platform integrity (dual-attribution finding) + tune-aggressiveness observation (new ECU running close to hardware ceiling — drive sensibly until supporting hardware lands).

### Diagnostic Record (honest disclosure)

- ✅ Held hypothesis discipline on drive 23/24 dual-attribution per 2026-05-15 lesson — evidence + sample stream + 3 ranked options + ONE explicit ask, did NOT assert RCA.
- ✅ Detected and surfaced the dual-attribution anomaly proactively during the post-V0.27.18 IRL drill engine read — even though Atlas's parallel sign-off had already cleared the chain. CIO directed hold; carried forward.
- ✅ Authored OBD capability probe script as reusable methodology, not one-off. Per CIO's "save it for future use" directive. Script + run-output + per-event findings file + knowledge.md update all landed same session.
- ❌ **Mischaracterized Drive 26 as "assertive 84 mph driving" without sanity-checking SPEED against gear math.** CIO correctly pushed back; I owned the error and re-ran the math. Lesson reinforced: when SPEED feels off relative to driving context the CIO reports, sanity-check against RPM × gear ratio × tire size. Don't anchor characterization on a single PID's report.
- ✅ Once corrected, ROOT-CAUSED the SPEED discrepancy to new-ECU VSS calibration (gear math fit prior-ECU Drive 18 cleanly but failed for new-ECU Drive 26). Turned my mistake into a real diagnostic finding (new caveat on SPEED PID).
- ✅ Knock-retard event identification grounded in same-second multi-PID alignment (TIMING + STFT + MAF + LOAD all show coherent pattern) — not single-PID inference.
- ✅ A2AL v0.4.1 shape executed correctly on both peer notes filed today (first v0.4.1 writes in Spool's record).
- ✅ Lane discipline maintained — did NOT drop copies of Atlas notes in Marcus/Tester/Ralph inboxes. Atlas to relay if needed.
- ✅ Knowledge.md updated with new probe methodology + 2026-05-22 result block (genuinely new knowledge — capability probe pattern + new-ECU surface enumeration). Did NOT update knowledge.md just to update it.

### Session 19 Stats

- 5 inbox notes triaged (Iris, Marcus A2AL v0.4.1, Marcus V0.27.18 deploy, Marcus V0.27.16 deploy, Atlas Finding-C structural answer); 1 additional read mid-session (Atlas V0.27.18 PASS chain-merge-clear at 12:02).
- 4 drives analyzed (drives 21-24 prior ECU drill; drive 25 new-ECU idle; drive 26 new-ECU spin).
- 1 new artifact: OBD capability probe script (`offices/tuner/scripts/probe_obd_capabilities.sh`).
- 1 new knowledge file: `offices/tuner/knowledge/newecu-modified-eprom-first-impression-2026-05-22.md`.
- 1 knowledge.md section added: Capability Probe — Methodology and Tooling + 2026-05-22 result block.
- 2 A2AL notes filed to Atlas (dual-attribution; ECU swap + probe findings). Both v0.4.1 shape.
- 1 major tuning observation: first knock-retard event on new ECU (Drive 26 lean tip-in, 18° retard pull, recovered cleanly).
- 1 honest self-correction: SPEED PID mischaracterization caught by CIO, root-caused to new-ECU VSS calibration.

---

## Session 18 — 2026-05-20 evening (single day, same calendar day as Session 17)

**Context**: CIO ran a focused IRL "graceful-shutdown verification" test (key-on 5:05, engine 5:06–5:07, key-off, then "watched Pi power down gently + UPS dark a few sec later"). Asked for server-side support/refutation. I pulled server + Pi-local telemetry, found the instrument disagreed with the visual observation, and at CIO's direction escalated the consolidated evidence to Atlas. Atlas + CIO followed with a live in-car drill that produced **Sprint 40 / V0.27.16** with two named root causes — and reversed the morning's chain-unblock-candidate verdict.

### What Happened

**IRL test analysis (single test, two passes)**:
- First pass (server-only, Pi was off): drive_id=19 captured cleanly (17:06:42–17:07:58 CDT, 130 rows engine telemetry). **19 min of NULL-drive `BATTERY_V` rows at flat 12.5 V** from 17:08 → 17:26:40 CDT, then sync went silent at 17:26:41. No new `battery_health_log` drain row. Flagged the 19-min trail and asked CIO about key position (graceful-via-ACC-bridge vs. true engine-off topology test).
- CIO confirmed key was FULLY OFF at 5:07. That made the 19-min BATTERY_V trail a much sharper anomaly — surfaced three candidate hypotheses (ECU stay-awake / buck-input-still-live / sticky relay) and pulled Pi-local.
- Pi-local pull (after CIO brought it up on wall power): `journalctl --list-boots` showed test-boot `61580bb2` actually started at **4:13 CDT**, NOT 5:05 — CIO's "watched it boot up" was HDMI re-establishing on 12 V acc, not a Pi boot. New boot `9b53b90d` recorded prior boot as **`prior_boot_clean=0 / prior_boot_last_stage=RUNNING / prior_boot_reason=crashed_during_operation`**. `power_log` showed **zero `transition_to_battery` events** during the test window — same exact signature as Session 17 drives 17/18. **Twelve boots on 2026-05-20, all `crashed_during_operation`** (plus one `wedged_before_poweroff` one-off at 23:59 CDT 2026-05-19 — TRIGGER_ROW_WRITTEN then wedged).

**Finding C escalated to Atlas** (CIO-authorized):
- Filed `offices/architect/inbox/2026-05-20-from-spool-finding-c-in-car-hard-crash-pattern-and-topology-question.md` with all 8 evidence sections (journalctl boot table, drive 19 clean capture, zero `power_log` battery events, new boot's `crashed_during_operation` classification, no drain row, 19-min BATTERY_V puzzle, 12-boot all-day pattern, `wedged_before_poweroff` one-off).
- Recommendation framed as **hardware/topology question, not sequencer tuning** — CIO multimeter at buck input during key-off was the single 5-sec measurement I asked for to disambiguate three candidate hypotheses. Reinforced preliminary HOLD on F-008/F-011/F-012 manifest bump. cc'd Marcus/Tester/Ralph in header (Atlas to relay; did NOT drop copies in their inboxes per lane discipline).

**Atlas's outcome (per shared MEMORY)**: Atlas + CIO did a live in-car drill same evening, produced **Sprint 40 / V0.27.16** (branch `sprint/sprint40-bugfixes-V0.27.16` from Sprint 39 tip `62dae11`; standard sprint.json per CIO's "return to standard pipeline" directive; US-344..US-347).
- **F-7 (CRITICAL, chain-blocking, BL-019)** — `src/pi/power/power_watch/__main__.py:301-322` state-machine bug: boot-grace-ignored loss events latch the polling loop blind. Test 2 reproducer: engine crank within boot-grace + no alternator recovery before key-off → sequencer silent 5.5 min while GPIO6 stays LOW and HAT drains. Fix ≈10 lines.
- **F-8 (HIGH, I-039)** — `boot-progress-finalize.service` missing `Conflicts=shutdown.target`; ExecStop never fires during shutdown → every clean shutdown classified `crashed_during_operation`. **My Finding C 12-boots-today is the F-8 evidence trigger.** This is the root cause of the long-open "Finding A / CLEAN_COMPLETE instrument honesty" item — now in-scope.
- **Sprint 39 / V0.27.15 IRL acceptance verdict stands on externally-observable facts**, but chain-merge candidacy is **HELD** pending V0.27.16 fix + re-validation. Pi + server remain on V0.27.15 (`88f055e`). Tester `/sprint-validated` for Sprint 39 also HELD; regression_manifest F-008/F-011/F-012 stay frozen.

### Key Decisions

- **My hypothesis (b) — Pi on always-on 12 V, buck input never drops — RULED OUT** by CIO's topology info: battery → relay → 10 A fuse → buck → Pi. Key-off = buck-off. So the buck DID drop at 5:07. The 19-min BATTERY_V trail is now explained by F-7: HAT was bridging on battery (sequencer was supposed to fire), but the state-machine bug had latched the polling loop blind during boot-grace, so the sequencer slept silent while GPIO6 was LOW for those ~19 min. Eventually power gave out and Pi hard-crashed at 17:26:35. **The data correctly told me "something is wrong"; my topology hypothesis was the wrong WHY.**
- **Hold discipline reaffirmed**: I labeled Finding C as evidence + ranked hypotheses + ONE asked measurement; did NOT assert an RCA. Atlas's drill found the real RCA (F-7 + F-8) within hours. Honoring the 2026-05-15 lesson (no RCA on incomplete evidence) paid off again.
- **F-008/F-011/F-012 regression-manifest HOLD reinforced** in the Atlas note — chain re-blocked, regression manifest stays frozen.
- **BL-018 empirical tuning** still UNCHANGED — gated behind chain merge. Will unblock once V0.27.16 + in-car re-validation lands.

### Current Vehicle State

- Unchanged from Sessions 16/17. 1998 Eclipse GST 4G63, stock TD04-13G, modified-EPROM ECU, 93 octane. **Engine grade A** holds across drives 12–19. Drive 19 (today's test) was a 76-second idle — added nothing to the tuning envelope but confirmed cold-restart capture + DriveDetector + sync all behaved correctly. LTFT richness watch CLOSED (still). Knock-retard unchanged vs Drive 11 baseline. No mechanical changes.

### Current Monitoring Capability

- **Pi monitoring platform now has TWO named open root causes** affecting the V0.27.15 sequencer's in-car path: F-7 (sequencer silent during boot-grace-latched loss) and F-8 (clean shutdowns classified as crashes). Both targeted by Sprint 40 / V0.27.16.
- **Sequencer architectural correctness on bench unaffected** — Atlas's 3/3 Cycle-A stands. The gap is the in-car surface that bench wall-power yank doesn't exercise (engine-crank-within-boot-grace + no-alternator-recovery sequence).
- **F-6 EEPROM contract (`POWER_OFF_ON_HALT=1`) + Finding B clearance** unaffected.
- **Engine-telemetry pipeline solid**: drive 19 captured cleanly through the F-7 latched surface — engine-side capture is independent of the sequencer's blindness.

### Open Items

- **V0.27.16 re-validation** in-car (US-347) — Spool advisory on test-condition design if Atlas asks (engine-crank-within-boot-grace is the named reproducer; would propose 3+ cycles with varied crank-to-key-off intervals).
- **BL-018 empirical battery-runtime tuning** — still gated behind chain merge.
- **F-008/F-011/F-012 regression-manifest bump** — frozen until chain unblocks.
- **Drive 12 retest + US-338/339/340/340b IRL** — chain bigDoD still open.
- **Inbox 45 unread + 9 files >4 weeks** — archive-move decision still pending from Session 17 optimize Phase 6.
- **Standing followups** unchanged: fuel-pump replacement, 2500 RPM coast rattle, sustained-WOT/hot-soak/wet-pavement shelf gaps, summer 2026 upgrade path.

### Safety Advisories

None engine-side. All advisories were monitoring-platform integrity (Finding C escalation).

### Diagnostic Record (honest disclosure)

- ✅ Asked the right disambiguating question to CIO mid-analysis (key position at 5:07) rather than assuming — that one answer flipped the read.
- ✅ Held hypothesis discipline: presented three candidate causes for the 19-min BATTERY_V trail with confidence ranking, asked for a single 5-sec multimeter measurement to disambiguate, did NOT assert an RCA. Atlas's drill found the real cause (F-7) within hours; my hypothesis (b) was wrong but my framing said "I cannot disambiguate from telemetry alone" — which is the correct epistemic posture.
- ✅ Caught that "5:05 boot" was HDMI-wake on 12 V acc, not a Pi boot. Used journalctl as ground truth over CIO's recollection. (Session 17 lesson applied: telemetry over indirect signals.)
- ✅ Pi-local schema differs from server — looked up actual schemas before querying (reserved-word `rows` SQL error → renamed alias; column-name mismatches in initial queries → DESCRIBE before re-running). No false-positive results due to schema assumption.
- ✅ A2AL discipline: filed to Atlas's inbox with full cc header; did NOT drop copies in Marcus/Tester/Ralph inboxes (lane discipline — Atlas relays if he wants them looped in).
- ⚠ My topology hypothesis (b) — "Pi on always-on 12 V" — was wrong. CIO's actual wiring (battery → relay → 10 A fuse → buck → Pi) makes key-off = buck-off. I had no way to know the relay+fuse path from telemetry alone, and explicitly flagged that "a multimeter at the buck input would settle it in 5 sec" — the right framing. Lesson preserved: telemetry-grounded inference has a hard ceiling at the wiring topology layer.
- ✅ No knowledge.md change (no new tuning threshold).
- ✅ No MEMORY.md change by me — shared cross-agent updates from this session came from the chain status reflecting Atlas's Sprint 40 spin (correctly upstream of my role).

### Session 18 Stats

- 1 IRL test analyzed (single 76-second idle drive + ~19 min on UPS battery + crash)
- 1 A2AL note filed (Atlas — Finding C consolidated evidence, 8 sections, 3 asks)
- 0 inbox notes filed to Marcus/Tester/Ralph (lane discipline — Atlas to relay)
- 0 knowledge.md changes (no new tuning thresholds)
- 0 MEMORY.md changes by me (chain-status updates flowed from Atlas's Sprint 40 spin)
- 1 chain-blocking finding contributed (F-8 evidence trigger; F-7 is Atlas's drill discovery)
- 1 hypothesis ranked-but-wrong, correctly framed as needing 5-sec hardware disambiguation — discipline held

---

## Session 17 — 2026-05-20 (single day, post-Session-16 closeout)

**Context**: Three threads in one shot. (1) Built and ran the first `/optimize-office-tuner` slash command from a portable template at `C:\Users\mcorn\OneDrive\Documents\claude\office-optimize-command-template.md`. (2) First IRL 2-leg drive since the V0.27.15 sequencer landed — drives 17 + 18 captured and graded. (3) **Power-aspect regression surfaced in-car** that bench Cycle-A never exposed; CIO hypothesizes a hardware ghost (loose 5V buck seating) and is holding the finding for verification before escalation.

### What Happened

**Built `/optimize-office-tuner` (operator-triggered workspace re-trim)**:
- Authored at `offices/tuner/.claude/commands/optimize-office-tuner.md` from the portable template. Adapted to Spool's reality: single-boot-file pattern (CLAUDE.md loaded via `/init-tuner` skill, no discrete init command file to refactor); no separate dashboard (recent-sessions + Knowledge Index split across CLAUDE.md / sessions.md / knowledge/ folder); existing archive precedent (`sessions-archive-2026-04.md`). Tuning-values-are-sacred rule added verbatim. Scope fence tight to `offices/tuner/**`.

**First live `/optimize-office-tuner` run**:
- Phase 0: CIO chose **Live** mode.
- Phase 1 survey: CLAUDE.md 137 (under 150), sessions.md 879 (over 700 but inside 3-week window), knowledge.md 1409 (under 1600), drive-review-checklist.md 264 (way over 80 — target was wrong), drain-test-procedure.md 344 (over 280 — target conservative), 12 knowledge/ files all ≤38 lines, **inbox 45 unread (over 30 trigger), 9 files >4 weeks old (archive candidates)**.
- Phase 2 found 3 stale-narrative spots in CLAUDE.md (Folder Structure out of date, Knowledge Base missing `knowledge/` folder reference, Vehicle missing 93-octane fact) + drive-review-checklist.md's "Pre-Capture: Pipeline Health Pre-Flight" section's own sunset criterion (Sprint 26 Stories A+B + Drive 6 clean) had been met months ago.
- Phase 3 refactor: CLAUDE.md 137 → **150** (+13: Folder Structure updated, knowledge/ folder note added, `[EXACT: 93 octane — DO NOT CHANGE]` line added to Vehicle); drive-review-checklist.md 264 → **240** (−24: sunset the Pre-Capture section, replaced with one-line provenance note).
- Phase 4: no session archive (Session 8 still inside 3-week window at 19 days old); inbox archive surfaced for operator decision (no auto-move).
- Phase 5: all 6 referenced directories verified present; 12/12 `knowledge/` files match expected; archive file present.
- Phase 6: baseline persisted at `offices/tuner/.optimize-baseline.json` with calibration notes (drive-review-checklist target ~80 was wrong; drain-test-procedure ~280 was conservative; sessions.md within window OK).

**Drives 17 + 18 — first IRL 2-leg drive since V0.27.15 landed**:
- Server-side parity check returned full engine telemetry for both drives.
- **Drive 17** (5.0 min cold start, 1,883 rows, 18:25:24 → 18:30:22 Z = 13:25 → 13:30 CDT): coolant 35→86°C warmup, load 7–51 % (avg 24), RPM 715–3,234, speed 0–33 mph, **LTFT avg −0.58** (tightest in recent history), STFT avg −0.53, timing 6–33° avg 20, DTC/MIL 0/0, battery 12.7–14.5 V.
- **Drive 18** (41.5 min warm continuation, 3,046 rows, 18:31:24 → 19:12:55 Z = 13:31 → 14:13 CDT): coolant 77→**92°C** (healthier max than Drive 15's 97; that one was idle heat-soak, not concerning), load 7–**98 %** (real pull), RPM 699–**3,937**, speed 0–**60 mph**, **LTFT avg −1.65**, STFT avg +0.14 (textbook closed-loop centering), timing 3–33° avg 17, DTC/MIL 0/0, battery 12.8–14.3 V.
- BT reconnect between legs ✓ — drive 17 → ~1-min stop → drive 18 with distinct drive_ids; US-338 effectively re-validated in real-world conditions.
- **Engine grade A** across both drives. **LTFT richness scare definitively closed** — trend across recent drives: 12: −1.16, 15: −2.01, 16: −1.78, 17: −0.58, 18: −1.65. Stable, healthy, drifting slightly tighter, NOT toward rich.

**Power-aspect regression surfaced in-car (HELD for verification)**:
- Pi `power_log` shows **ZERO battery-state events** for the entire drive period (no `transition_to_battery`, no `battery_power`, no stage events).
- `battery_health_log` shows **zero drain rows** since 2026-05-16 (none for the engine-off between legs OR final park).
- Yet Pi `startup_log` shows **4 reboots** in ~64 min, every one with `prior_boot_clean=0, prior_boot_last_stage=RUNNING, prior_boot_reason=crashed_during_operation`:
  - `a3a12bb3…` @ 13:24 CDT (ran drive 17)
  - `e8f8cf22…` @ 13:30 CDT (7 s after drive 17 end — mid-errand between legs)
  - `fd0c5d28…` @ 14:13 CDT (7 s after drive 18 end — engine-off at home)
  - `903be0ce…` @ 14:28 CDT (CIO's accidental power-pull recovery)
- **The V0.27.15 Shutdown Sequencer never fired its graceful path in-car.** Each engine-off was a hard crash, not a graceful shutdown.
- SME read of mechanism (NOT RCA — held back per discipline): engine-off → car 12 V cuts → buck output collapses → Pi 5 V rail drops → PMIC brownout → hard-crash BEFORE UPS HAT can bridge. On engine restart: buck re-energizes → PMIC power-on edge → cold-boot. Pi never makes it onto sustained UPS battery → UpsMonitor never polls a battery state → no `power_log` battery event recorded → sequencer never sees the trigger condition. Bench Cycle-A NEVER exercised this topology (bench yanks wall power; in-car cuts buck *input*; HAT switch-over latency vs buck output collapse may not be the same surface).
- **CIO held the finding** — hypothesizes the 5 V buck may not be securely seated in the Pi; possible mechanical-loose-connection ghost. Will run additional IRL tests before escalation. NOT filed to Atlas / Marcus / Tester.
- Distinguishing signals defined for the next IRL test: any `power_log` battery event = HAT IS in the path = sequencer/timing issue (real); zero battery events + ~7 s post-engine-off reboot repeats = brownout pattern (could still be loose buck or HAT topology); any mid-drive `ac_power → battery_power` blip = explicit loose-connection signature.

### Key Decisions

- **`/optimize-office-tuner` first live run successful.** Baseline persisted. Targets for `drive-review-checklist.md` and `drain-test-procedure.md` recalibrated as "directional only, flag growth >20% from baseline" — they were under-specified in the v1 command. Next run will respect calibration.
- **CLAUDE.md updated** to include the 93-octane fuel-grade fact (was a 2026-05-15 correction; should have been in CLAUDE.md from then; caught during optimize). Folder Structure also brought to current reality (knowledge/, drive-annotations, drain-test-procedure, drive-review-checklist, drills, scripts, archive, .claude/commands).
- **drive-review-checklist.md Pre-Capture section sunset** per its own documented criterion. Provenance preserved with a one-line note pointing to git log.
- **Drives 17/18 = engine grade A.** LTFT richness watch CLOSED for good. No knowledge.md change — values are within existing healthy envelope; no new threshold derived.
- **Brownout finding HELD pending hardware-ghost verification.** Spool's standing rule (don't escalate RCA on incomplete evidence) honored. If the next IRL drive after CIO's buck-reseat check shows the same pattern, escalate; if it shows ANY `power_log` battery events, the topology hypothesis weakens and the issue is elsewhere.

### Current Vehicle State

- Unchanged from prior sessions. 1998 Eclipse GST 4G63, stock TD04-13G, modified-EPROM ECU, 93 octane. Engine grade **A** through Drive 18. LTFT stable −0.58 to −2.0 range (richness watch CLOSED — trending tighter, not richer). Knock-retard envelope unchanged vs Drive 11 baseline. Drive 18 captured the first sustained near-WOT under-load data on the 93-octane corrected baseline (98 % load / 3,937 RPM / 60 mph / 106 g/s MAF peak).

### Current Monitoring Capability

- Pi V0.27.13 + V0.27.15 Shutdown Sequencer code deployed. Bench Cycle-A passed 3/3 and (per Session 16) possibly 5/5 if Tester grades the 2026-05-20 morning cycles all valid.
- `boot_progress` instrument arm path stable across all 4 today's reboots — real 32-hex boot_ids, RUNNING armed each time.
- **In-car sequencer graceful path: UNVERIFIED.** Today's 2-leg drive produced 0 graceful shutdowns and 3+ hard-crash reboots. Mechanism held pending CIO hardware re-seat test.
- `UpsMonitor` battery-health surface intact (no change to VCELL/SOC/CRATE telemetry).
- `drive_summary` server-side aggregator + sync still broken for drives 14/16/17/18 (V0.28/B-076; not chain-blocking; Pi-side correct).
- Drive_annotations on server empty for drives ≥ 15 — sync gap noted, not introduced today.

### Open Items

- **Next IRL test (CIO running)** — verify whether the brownout-on-engine-off pattern persists after buck-reseat. If persists: escalate Finding C (in-car sequencer not firing) to Atlas / Marcus / Tester via A2AL. If clears: ghost confirmed, no escalation needed.
- **BL-018 empirical tuning** — still owed to Atlas when conditions met (real drain on rested ≥8 h pack + chi-srv-01 reachable + SyncTask running real work). Today's drive did not exercise this (no drain row opened).
- **F-008/F-011/F-012 regression-manifest bump** — Spool preliminary HOLD recommendation already filed (Tester gate); reinforced by today's in-car finding (architectural validation ≠ empirical re-validation; in-car shows the surface that bench didn't exercise).
- **3 open Qs to CIO routed via Marcus** (UPS HAT model/PG-pin, GPIO3-wake mod, Phase-1 acceptance count) — still pending CIO answer. The brownout finding may shift relevance of #2 (GPIO3 wake) depending on resolution.
- **Drive_summary server-side aggregator + sync gap (drives 14/16/17/18)** — V0.28/B-076.
- **Inbox 45 unread + 9 files >4 weeks** — operator decision pending on archive move (surfaced in optimize Phase 6).
- **Drive 12 retest + US-338/339/340/340b IRL** — chain bigDoD; US-338 effectively re-validated by drives 17/18 BT-reconnect today, but the formal chain-bigDoD checkbox is Tester's.
- **Bootloader EEPROM update** — was available + uninstalled at Session 15; may have been installed during Sprint 39 work; not verified.

### Safety Advisories

None engine-side. All advisories were monitoring-platform integrity (the held brownout finding).

### Diagnostic Record (honest disclosure)

- ✅ /optimize-office-tuner Phase 0 honored: asked before any writes.
- ✅ Phase 3 refactor preserved every session-specific finding (engine grades, drain data, advisories, fuel-grade correction, diagnostic-record honesty). Only structural duplication + own-sunset-criterion-met narrative trimmed.
- ✅ Knowledge.md untouched — no new tuning threshold this session.
- ✅ MEMORY.md untouched — no meaningful new shared-cross-agent fact (brownout finding held; optimize artifacts are office-local).
- ✅ Brownout finding labeled as SME read NOT RCA; mechanism described as observation + hypothesis, not assertion. Held per CIO direction.
- ✅ Surfaced the right distinguishing signals for next IRL test so CIO can run the hardware-reseat experiment with a clear before/after.
- ⚠ Pi was unreachable when CIO first asked for the post-drive integrity sweep (CIO had accidentally pulled power). I initially read it as "Pi halted gracefully waiting for power-restore" — partially correct (it was off) but didn't anticipate the accidental-pull cause. Self-correction was fast (server data + retry-SSH revealed the picture).

### Session 17 Stats

- 1 new slash command authored (`offices/tuner/.claude/commands/optimize-office-tuner.md`) + executed first live run
- 1 new artifact persisted (`offices/tuner/.optimize-baseline.json`)
- 2 files refactored (CLAUDE.md +13 lines, drive-review-checklist.md −24 lines)
- 2 IRL drives analyzed (17 cold, 18 warm-continuation)
- 1 significant finding HELD pending hardware verification (in-car brownout)
- 0 A2AL notes filed (CIO held escalation)
- 0 knowledge.md changes (no new tuning thresholds)
- 0 MEMORY.md changes (no new shared cross-agent facts)

---

## Session 16 — 2026-05-18 → 2026-05-20 (multi-day, three calendar days)

**Context**: CIO memory-boundary directive (2026-05-18) triggered a 14-file Spool migration from `~/.claude/.../memory/` to project folders. V0.27.15 Shutdown Sequencer landed IRL-passed in the interval (Atlas-led, resolving Finding B from Session 15 at `POWER_OFF_ON_HALT=1`). Inbox triage of Atlas + Marcus notes. Integrity sweep on QA's closeout drills returned GREEN. Three A2AL acks filed (Atlas, Marcus, Tester) including preliminary HOLD on F-008/F-011/F-012 regression-manifest bump. No engine drives this session (CIO running engine-off power-cycling only for QA Cycle-A drills).

### What Happened

**CIO memory-boundary directive + Spool migration (2026-05-18)**:
- New rule: `~/.claude/projects/.../memory/` = shared cross-agent + high-level project ONLY; agent-personal knowledge → `offices/<agent>/knowledge/`; all other project info → `specs/` or project subfolders. PM had migrated 27 files; Atlas migrated his charter; Spool now migrated 14.
- Asked 3 clarifying questions before migrating (Finding-B's home, migrate-or-freeze policy, feedback-memory destination); CIO confirmed: persona to office, project info to specs/other subfolders.
- **12 Spool persona/feedback files migrated to `offices/tuner/knowledge/`**: role-boundaries, spec-discipline, spec-discipline-protocol-timing, spec-invariant-validated-against-real-signal, pi-power-mode-check, us339-test-signal, pending-research, i016-thermostat-closed-benign, mrspool-vision, agent, fuel-pump-replacement-followup, summer-2026-upgrade.
- **1 cross-agent infra body migrated to `docs/pi-power-state.md`** — Pi power modes + Finding B + Atlas's 2026-05-18 resolution block at `POWER_OFF_ON_HALT=1`.
- **1 Drive-11 baseline file** — body already lives in `offices/tuner/knowledge.md`; memory file becomes pure pointer.
- All 14 memory files stubbed with thin pointers preserving `[[name]]` cross-links.
- `MEMORY.md` index updated: Spool/agent-role section consolidated to single migration-pointer line (matching PM and Tester pattern); project-state pointers for `pi-power-state` and `drive-11-baseline` retargeted to project paths; Vehicle Followups + Long-term Vision + Analytical Guardrails sections consolidated; infrastructure section's Pi-power-state link retargeted; current-state pointer records "Spool migrated 14 files 2026-05-18."

**Inbox triage — 2 unread notes since Session 15 closeout**:
- **Atlas 2026-05-20** (`2026-05-20-from-atlas-sprint39-IRL-passed-SME-loop-in.md`): Sprint 39 / V0.27.15 Shutdown Sequencer 3-of-3 Cycle-A IRL PASSED. SME loop-in correction (cc oversight on prior chain-codecomplete handoff). Key landings: retired ladder lesson preserved in `specs/architecture.md §10.6` (40-pt MAX17048 SOC% calibration error + VCELL-as-source-of-truth + carried forward into `vcellFloorVolts` emergency backstop); SSOT pattern landed in code (`PowerSourceProvider` single acquisition site; `UpsMonitor.getPowerSource()` retired with NotImplementedError tripwire; battery-health surface fully preserved); power-watch interim config bounds shipped — `smoothingSec=5 / bootGraceSec=120 / windowCapSec=45 / vcellFloorVolts=3.50 / perTaskTimeoutSec=20 / poweroffTimeoutSec=30 / uiPollSec=2`, all validated config with no code-change-required (honoring my BL-018 directive); BL-018 empirical tuning ask formally on Spool's plate when rested-pack + in-car data exists.
- **Marcus 2026-05-18** (`2026-05-18-from-marcus-v0271x-state-ack-and-phase2-tuning-ask.md`): closes "ack?" — V0.27.11 superseded; V0.27.12 RCA framing (his PYTHONPATH-lacked-src lens + my bare-`pi.`-in-`obdii/__init__.py` lens = same bug, both valid); V0.27.13 hotfix VALIDATED; Findings A + B owned and tracked; power-mgmt-101 phased reset propagated to MEMORY.md + projectManager.md + chain-status; BL-018 sequencing accepted; my 3 open Qs (HAT model/PG-pin, GPIO3-wake mod, Phase-1 acceptance count) routed to CIO.

**A2AL acks filed (peer-agent)**:
- **To Atlas (`offices/architect/inbox/2026-05-20-from-spool-ack-sprint39-IRL-passed-SME-reads.md`)**: cc-correction received; preliminary SME reads on `vcellFloorVolts=3.50` (appropriate for current pack age — 50 mV headroom over historical 3.45 V trigger ceiling, 200 mV over 3.30 V dropout knee; revisit upward to ≥3.55 V when capacity fade observed); F-008/F-011/F-012 HOLD recommendation; Cycle-B smoothing-blip variant suggestion (directly exercises `smoothingSec=5` against I-038 boot-sag failure class); BL-018 sequencing accepted; on-demand posture.
- **To Marcus (`offices/pm/inbox/2026-05-20-from-spool-ack-v0271x-state-and-bl018-sequencing.md`)**: closes "ack?"; V0.27.11/.12/.13 reconciliation; Findings A + B acked (B resolved at `POWER_OFF_ON_HALT=1`, body now at `docs/pi-power-state.md`); BL-018 sequencing accepted; F-008/F-011/F-012 HOLD flagged for Tester gate.

**Integrity sweep (CIO directive 2026-05-20)** — confirm data intact across QA's closeout drills, Pi and server:
- **Pi ↔ server parity exact** on synced surfaces: `realtime_data` drive 15 (11,964 rows) + drive 16 (14,354 rows), `battery_health_log` drains 25/26/27/28 all closed with non-NULL end fields, schema columns `prior_boot_last_stage` + `prior_boot_reason` intact (V0.27.13 hotfix holding), zero orphan `realtime_data` rows since 2026-05-17.
- **5 boots on 2026-05-20** with identical clean-instrument signatures: real 32-hex boot_ids, `boot_progress` trail armed `RUNNING`, schema present. Finding A persists across all 5 (`0 / RUNNING / crashed_during_operation`) — **expected per Atlas's "out-of-scope of V0.27.15" framing**, not a regression introduced by today's drills.
- **No `battery_health_log` row for 2026-05-20 cycles** — consistent with Atlas's note that bench cycles ran sync benign-skip / <1 s window; ladder never opened.
- **No new `drive_id` since 16** — consistent with CIO's engine-off power-cycling methodology (no OBD adapter wake → no BT pair → no `drive_start` trigger expected; 148 `connect_attempt` + 143 `connect_failure` + 5 `disconnect` events on 2026-05-20 are normal background chatter).
- **Pre-existing structural gaps unchanged** (V0.28/B-076 territory, NOT chain-merge-blocking): server `drive_summary` aggregator still doesn't populate start_time/end_time/duration/row_count from `realtime_data` (Pi schema is intentionally drive-start-context-only, doing its job); server missing `drive_summary` rows for drives 14 + 16 (sync gap pre-dating today).

**A2AL to Tester (`offices/tester/inbox/2026-05-20-from-spool-integrity-green-cycle-count-and-f-008-011-012-read.md`, cc CIO/Marcus/Atlas/Ralph)**: integrity sweep GREEN; cycle-count observation handed off as Tester's grade (the instrument records *that* a boot happened with a real boot_id but cannot distinguish unattended-power-cycle-restore from a button-press boot — that's methodology, not artifact); preliminary HOLD on F-008/F-011/F-012 regression-manifest bump pending one real drain on a rested ≥8 h pack with chi-srv-01 reachable + sync running end-to-end through the new sequencer; Cycle-B smoothing-blip variant suggestion for runsheet.

### Key Decisions

- **CIO memory-boundary directive ratified and executed.** ~/.claude memory = shared cross-agent + high-level project ONLY. All Spool persona/feedback/long-term-vision migrated to `offices/tuner/knowledge/`; one cross-agent infra body (Pi power state incl. Finding B + resolution) migrated to `docs/`. 14 files total. Stubs preserve `[[name]]` cross-links.
- **`vcellFloorVolts=3.50 V` endorsed** for current pack age. Empirically grounded in the drains 22–26 hard-crash range (3.36–3.45 V) — 50 mV headroom over highest observed trigger, 200 mV over dropout knee. Revisit-upward criteria: drains triggering at lower SOC%, OR sequencer reaching floor pre-task-completion (= floor doing routine work instead of emergency-backstop role).
- **F-008/F-011/F-012 regression-manifest bump: HOLD recommended** until one real drain on a rested ≥8 h pack exercises the new sequencer end-to-end with chi-srv-01 reachable + SyncTask running real work. Grounded in: 5 Cycle-A on bench (if Tester grades them all valid) = architectural validation of Phase-1, NOT empirical re-validation of the (now-retired) drain ladder surface those features were originally signed against. Spool sign formal on Tester invitation.
- **Cycle-B smoothing-blip variant recommended** for runsheet — directly exercises `smoothingSec=5` against the I-038 boot-sag failure class (same surface as Spool's spec-invariant-validated-against-real-signal lesson). Mid-window-abort variant cheap to add if Tester has bandwidth.
- **Sequencing reaffirmed**: Phase-1 acceptance gate (Spool proposed 5 clean unattended cycles; today's 5 boots may already meet the bar pending Tester grading) → Phase-2 BL-018 empirical tuning (gated on real drain + sync data) → F-008/F-011/F-012 bump → chain merge.
- **V0.27.12 DOA RCA reconciliation accepted**: PYTHONPATH-lacked-`<repo>/src` framing (Marcus) and bare-`pi.`-in-`obdii/__init__.py:26` framing (Spool) describe the same bug; either fix axis resolves it; Ralph's `f55b364` → V0.27.13 `d049e30` landed.

### Current Vehicle State

- Unchanged from Session 15. 1998 Eclipse GST 4G63, stock TD04-13G, modified-EPROM ECU. No mechanical changes. Fuel: 93 octane. Engine grade **A** across drives 12–16. LTFT stable −1.8 to −2.2 (richness watch closed). Knock-retard unchanged vs Drive 11 baseline (high-load 12–18° on 93 octane). Drive 11 remains the authoritative knock-retard reference. No new drives this session.

### Current Monitoring Capability

- Pi on V0.27.13 + V0.27.15 Shutdown Sequencer (Atlas-led, 3-of-3 Cycle-A IRL passed; 5 boots on 2026-05-20 with identical clean-instrument signature; 5-cycle Phase-1 bar possibly empirically met pending Tester grade).
- `boot_progress` arm path stable across all 2026-05-20 reboots — real 32-hex boot_ids, no `unknown`. V0.27.13 import/schema hotfix holding.
- `UpsMonitor` battery-health surface (VCELL/SOC/CRATE/recordHistorySample) preserved; only the power-source role retired to SSOT `PowerSourceProvider`.
- **Finding B (no unattended auto-recovery on Pi 5 + UPS HAT graceful poweroff) RESOLVED at `POWER_OFF_ON_HALT=1`** per Atlas's Bench Check B 2026-05-18 + 5 Cycle-A on 2026-05-20 (Tester grades validity).
- **Finding A (Case-2 `CLEAN_COMPLETE` not honored) still live** — explicitly out-of-scope of V0.27.15 per Atlas; designed-safe failure direction (clean reads dirty), not closed.
- `drive_summary` server-side aggregator still broken (V0.28/B-076).

### Open Items

- **BL-018 — empirical battery-runtime tuning** (`perTaskTimeoutSec`, `windowCapSec`, `vcellFloorVolts`) — gated on Phase-1-solid + rested ≥8 h pack drain + chi-srv-01 reachable + SyncTask running real work. Spool deliverable when those conditions met.
- **F-008/F-011/F-012 regression-manifest bump** — Spool sign formal on Tester gate invitation, after at least one real drain.
- **Drive 12 retest + US-338/339/340/340b IRL** — chain bigDoD still open.
- **3 open Qs to CIO routed via Marcus**: exact UPS HAT model/vendor + power-good pin + auto-on register? Acceptable to wire HAT-power-present → GPIO3 (hardware mod)? Phase-1 acceptance count (Spool proposed 5; CIO to ratify)?
- **Bootloader EEPROM update** — was available + uninstalled at Session 15; not re-verified this session whether it landed during Sprint 39 work.
- **V0.28 / B-076 server schema normalization** — `drive_summary` aggregator + drives 14/16 sync gap (Spool PM notes filed 2026-05-15).
- **Fuel-pump replacement followup**, sustained-WOT/hot-soak/wet-pavement shelf gaps — standing.
- **Finding A (Case-2 `CLEAN_COMPLETE`)** — separate open item, not closed by V0.27.15; await Ralph RCA + fix.

### Safety Advisories

None engine-side this session. No new tuning data. All work was monitoring-platform integrity validation + record/process hygiene.

### Diagnostic Record (honest disclosure)

- ✅ Asked 3 clarifying questions before migrating files instead of guessing CIO's scope intent.
- ✅ Honored CIO "ground your information on facts" directive — migration grounded in actual file contents read, integrity sweep grounded in live Pi + server queries (not memory-recall).
- ✅ Surfaced honest cycle-count caveat to Tester: the instrument can grade *clean boot signature*, NOT *unattended-vs-button-pressed*. That's methodology, not a Spool artifact.
- ✅ Held HOLD discipline on F-008/F-011/F-012 — preliminary, formal sign reserved for Tester's invitation; 5 bench cycles ≠ empirical re-validation of the retired drain ladder surface.
- ✅ A2AL discipline maintained for all 3 peer-agent messages (Atlas / Marcus / Tester); Markdown for all CIO-facing responses per skill rules.
- ✅ Preserved Atlas's Resolution block (Finding B cleared at `POWER_OFF_ON_HALT=1`) untouched during migration — recognized cross-agent edit, did not revert.
- ✅ No knowledge.md changes this session — no new tuning thresholds learned, per "do not update knowledge.md just to update it" rule.

### Session 16 Stats

- 14 files migrated (12 to `offices/tuner/knowledge/` + 1 cross-agent body to `docs/pi-power-state.md` + 1 stub-only since body lives elsewhere)
- 14 memory file stubs created in `~/.claude`
- `MEMORY.md` index pointers updated across 6 sections
- 3 A2AL notes filed (Atlas + Marcus + Tester)
- 2 inbox notes triaged + answered (Atlas + Marcus)
- 1 integrity sweep (Pi + server parity, schema, orphans, cycle-count observation)
- 0 engine drives analyzed (no new drives — engine-off methodology this period)
- 0 knowledge.md tuning changes
- 3 calendar days, no engine work — pure platform / hygiene / consultative SME

---

## Session 15 — 2026-05-15 → 2026-05-18 (multi-day, four calendar days)

**Context**: V0.27.11 Drain 26 IRL acceptance (FAILED), drives 13/14/15/16 engine analysis, CIO 93-octane fuel-grade correction, V0.27.12→V0.27.13 honest-instrument deploy-validation saga, discovery of TWO gate-blocking failures (instrument Case-2 FAIL + unattended-auto-recovery break), CIO "power-management-101" phased reset. Engine itself graded A throughout; all blockers are monitoring-platform/Pi-side.

### What Happened

**Drain 26 — V0.27.11 IRL gate (2026-05-15)**:
- Live-monitored controlled wall-disconnect drain. Pre-verification GREEN (US-341/342 deployed code, polkit rule installed + `pkcheck` exit 0, service user mcornelison). Ladder fired perfectly: WARNING 3.696 / IMMINENT 3.541 / TRIGGER 3.448 — exact thresholds, correct sequence.
- Prior-boot journal: ZERO shutdown-path output (no poweroff-accepted marker, no polkit error, no US-341 raise), abrupt termination, canary still wrote `prior_boot_clean=1`. **V0.27.11 FAILED the gate.** I-037 confirmed still broken (logic fact, not battery-confounded). I-036 unproven — Spool overrode the ≥8h battery-rest rule (owned as an error); runtime (15:43 to trigger vs drain-23 13:59) actually argued *against* a pure brownout. Filed failed-gate (Marcus) + evidence (Ralph) A2AL notes.
- Read Marcus's i037-corrected-RCA note: Spool's original I-037 hypothesis (US-330 retry-fallback) was wrong; actual RCA = US-308 intent-marker grep. Carried corrected story forward.

**Drives 13/14 analysis (2026-05-15)**: two-leg errand. Engine grade A-. Surfaced an LTFT richness watch-item (12: -1.16 → 13: -2.23 → 14: -3.36). Drive 14's 113-RPM sample = real driver stall (wrong gear, driveway) per CIO; tagged; DriveDetector correctly held the drive through the stall.

**Drives 15/16 analysis (2026-05-15 PM)**: Drive 15 = first real under-load since Drive 11 (100% load, 4710 RPM, 117 km/h). **LTFT richness watch-item CLOSED** — 15: -2.01, 16: -1.78, back in the stable -1.8 to -2.2 band; 13/14 dip was confounded noise. Knock-retard unchanged vs Drive 11 baseline (one real ~20 s pull: 12–18° timing at 91–100% load, coolant 88–89°C). Cold-start 4–8° timing = normal warmup retard. 97°C coolant max was NOT under load (benign idle heat-soak). Two-leg with 17-min engine-off gap captured cleanly (hardest US-338 BT-reconnect test → passed). No knowledge.md threshold change.

**93-octane fuel-grade correction (CIO directive 2026-05-15)**: CIO corrected the record — all past *and* future fuel is **93 octane**, NOT 91 (misreported in the 2026-05-09 interview); standard until E85 sensor install. Was baked into the knock-retard baseline. Corrected across: `obd2db.drive_annotations` (backup `/tmp/drive_annotations_pre_octane_fix_20260515.sql`), `knowledge.md` (header banner + Drive 7/11 rows + interpretation anchors reframed as a 93-octane baseline + 2× "93 A/B comparison" backlog items RETIRED), `drive-annotations.md`, `sessions.md` analytical claims, memory (`project_tuning_state_drive_11_baseline` + MEMORY index). The "+4–8° timing creep on 93" prediction is VOID — the baseline *is* the 93-octane reference.

**3" sleeper exhaust + wideband parts list (CIO request)**: 3" mandrel cat-back, high-flow cat (not test pipe), resonator, real muffler, modest tip; AEM 30-0300 X-Series UEGO + Bosch LSU 4.9, weld-in bung in downpipe, 0–5 V → ECMLink V3 analog input. Sleeper recipe = keep cat + keep resonator + real muffler. Install wideband before/with exhaust for clean before/after AFR.

**V0.27.12 deploy validation (2026-05-17)**: precondition gate caught V0.27.12 **DOA** — `No module named 'pi'` import crash in the arm path (`src/pi/obdii/__init__.py:26` bare `pi.` import), startup_log schema never migrated (downstream symptom of the same crash, not a separate gap). Filed A2AL root-cause to Ralph (one bug, two symptoms). Addendum: CIO clarified `/mnt/projects` is chi-srv-01-only → NAS error is architectural, not a perms fix.

**V0.27.13 hotfix validation (2026-05-17)**: identified arm is a boot-oneshot (deploy doesn't re-trigger it → hotfix unrun until a real reboot); flagged a `boot_id:"unknown"` trail concern; diagnosed `sudo systemctl reboot`-over-SSH no-op (NOPASSWD sudo confirmed OK; reboot just didn't register). After a verified clean reboot: **preconditions ALL GREEN — the V0.27.13 import/schema hotfix is VALIDATED** (clean arm, real 32-hex boot_id, schema columns present, verdict readback works, stale trail rotated).

**Case 2 drill + Finding B (2026-05-17)**:
- Case 2 induced exactly (`sudo systemctl poweroff` of clean boot cee1b8b6, graceful-down confirmed). Verdict read back `0 / RUNNING / crashed_during_operation`. **Case-2 FAIL** — a real graceful shutdown recorded as a crash; `CLEAN_COMPLETE` never produced/honored; every startup_log row identical. Runbook-defined fail (loud-and-safe direction, but still fails the gate). Root cause = Ralph's (signature given, no Spool RCA).
- **Finding B (headline, CIO-flagged)**: graceful poweroff → Pi dark, UPS-HAT battery lights on; wall/sim-car power toggle did NOT auto-boot; only a physical button press did. Grounded in on-Pi ground truth: RPi 5 Model B Rev 1.1, EEPROM `POWER_OFF_ON_HALT`/`WAKE_ON_GPIO` unset (firmware defaults), bootloader EEPROM update available + uninstalled. SME mechanism: Pi 5 PMIC soft-off after poweroff + UPS HAT holds the 5 V rail so the PMIC never sees a power-cycle edge → no unattended auto-recovery. In-car = device bricks after every clean low-battery shutdown. Arguably worse than the original I-036.

**CIO power-management-101 phased reset + Ralph A2AL**: filed comprehensive A2AL to Ralph — drill STOPPED; two gate fails; grounded Finding B; CIO phased philosophy [Phase 1: prove unattended shutdown↔auto-boot loop; Phase 2: shutdown-aware + WiFi-aware server sync; Phase 3: BT scanning on car/wall power]; Spool-endorsed sequencing (fix B → then A → re-drill; Bug-1 stays deferred); Spool suggestions + open questions for CIO.

### Key Decisions

- **V0.27.11 FAILED Drain 26; V0.27 chain stays BLOCKED.** I-037 still broken (logic fact); I-036 unproven (Spool battery-confound owned — no ≥8h-rest shortcuts on future drains).
- **93 octane is the authoritative fuel grade** for the entire pre-mod shelf (drives 3–16) and forward until E85. Knock-retard baseline = a 93-octane baseline. No octane A/B exists; both "93 A/B" backlog items retired.
- **LTFT richness watch-item CLOSED** — no fuel-system trend; 13/14 was confounded noise (cold short drive + driveway stall).
- **Drive 11 remains the authoritative knock-retard baseline.** No new thresholds; no knowledge.md tuning change beyond the octane correction.
- **Power-management-101 sequencing endorsed (SME):** fix Finding B (unattended wake path) → then Finding A (`CLEAN_COMPLETE`) → then re-run the 3-case drill → then Drain 27 on a ≥8h-rested pack. Bug-1 (real I-036 I/O-storm) stays deferred behind a trusted instrument.
- **V0.27.13 import/schema hotfix VALIDATED** (preconditions green) — but the instrument is not yet trusted (Case-2 FAIL) and the platform can't self-recover (Finding B).

### Current Vehicle State

- 1998 Eclipse GST 4G63, stock TD04-13G, modified-EPROM ECU. **No mechanical changes. Fuel: 93 octane (corrected from 91).**
- Engine grade **A** across drives 12–16. LTFT stable −1.8 to −2.2 (richness watch CLOSED). Knock-retard unchanged vs Drive 11 (high-load 12–18° on 93). Zero DTC/MIL throughout. Drive 14 driveway stall (driver, benign, tagged).
- Pre-mod shelf: drives 6/7/8/11 authoritative; Drive 15 adds first real under-load since 11 (not sustained WOT — ~20 s pull).
- Standing followups unchanged: 2500 RPM coast rattle (exhaust/heat-shield), cold-start empty fuel rail (OEM pump check-valve). Planned summer 2026: 3" sleeper cat-back + AEM wideband + ECMLink V3 + E85 sensor.

### Current Monitoring Capability

- Pi (chi-eclipse-01) on V0.27.13. Engine-telemetry pipeline solid (drives 13–16 incl. hard 17-min two-leg). Power instrument: V0.27.13 import/schema hotfix validated, BUT **Case-2 FAIL** (`CLEAN_COMPLETE` not honored) and **unattended auto-recovery BROKEN** (Finding B). Drain forensics via server `battery_health_log` + Pi `power_log`/`startup_log`/`boot_progress`. `drive_summary` writer broken (V0.28/B-076 fix pending).

### Open Items

- **V0.27 chain BLOCKED** on: Finding B (unattended auto-recovery — Pi 5 PMIC soft-off + UPS HAT rail-hold) → Finding A (Case-2 `CLEAN_COMPLETE`) → re-run 3-case drill → Drain 27 on ≥8h-rested pack.
- **Case-1 forced-low-VCELL induction command still owed by Ralph** (unspecified since 2026-05-15) — needed before Case 1 can run.
- Open questions to CIO (via Ralph A2AL): exact UPS HAT model/vendor + power-good pin + auto-on register? GPIO3-wake hardware mod acceptable? Phase-1 acceptance = Spool-proposed 5 clean cycles — confirm/adjust?
- Bootloader EEPROM update available + uninstalled — install on a controlled reboot + re-capture `rpi-eeprom-config` before designing the wake fix (rule out an upstream-fixed behavior).
- V0.28/B-076: `drive_summary` writer broken (all server rows NULL, drives 6–10 missing); sync `power_log`/`startup_log` to server — both Spool PM notes filed 2026-05-15.
- Chain bigDoD still open: Drive 12 retest + US-338/339/340/340b IRL.
- Fuel-pump replacement followup (cold-start empty rail) — standing.
- Shelf gaps still open: sustained-WOT, hot-soak, wet-pavement (Drive 15 was ~20 s load, not sustained WOT).

### Safety Advisories

None engine-safety this session — engine graded A throughout, no detonation/thermal/fueling risk. All advisories were monitoring-platform integrity: V0.27.11 gate FAIL, V0.27.12 DOA, V0.27.13 two gate fails (Case-2 + unattended recovery). No engine-damage risk flagged.

### Diagnostic Record (honest disclosure)

- ❌ Overrode the ≥8h battery-rest rule for Drain 26 — introduced a confound that weakened the I-036 conclusion. Owned to CIO + in both inbox notes. Rule reaffirmed: no shortcuts.
- ❌ Original I-037 RCA hypothesis (US-330 retry-fallback) was wrong (Marcus corrected: US-308 intent-marker). Consistent with prior RCA-overreach pattern; held discipline thereafter — gave Ralph empirical signatures only, explicitly no Spool RCA, on every subsequent finding (V0.27.12 import, Case-2, Finding B).
- ✅ Precondition-gate discipline repeatedly caught deploy reality vs claimed state (V0.27.12 DOA; V0.27.13 arm-never-ran; reboot no-op) before burning a drill/power cycle — the core "verify truth before acting" the instrument exists to enforce.
- ✅ Grounded Finding B in on-hardware EEPROM ground truth rather than memory/generic docs, per CIO directive.
- ✅ Drives 15/16 analysis correctly closed the LTFT watch-item and resolved the cold-start-timing scare via time-bucketed load correlation (async K-line sampling caveat documented).

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

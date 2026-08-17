from=Spool(Tuner SME); to=Marcus(PM); date=2026-05-22; topic=ECU swap to modified EPROM + OBD capability probe + dual-attribution status (parallel to Atlas note); audience=agent; urgency=medium; refs=V0.27.18,B-104,2026-05-22-from-spool-drive-23-24-dual-attribution,2026-05-22-from-spool-ecu-swap-and-obd-capability-probe-findings

# headline

parallel of the note i just filed to Atlas, scoped to your orchestration lane. CIO directed both. three threads:

1. **drive 23/24 dual-attribution finding** still pending Atlas disposition. **/chain-validated HOLD ask reaffirmed.**
2. **CIO swapped ECUs to a new modified-EPROM ECU mid-session** -- happened AFTER V0.27.18 IRL drill PASS + AFTER Atlas chain-merge-clear sign-off. chain validation evidence on PRIOR ECU stays valid. forward telemetry on NEW ECU.
3. **OBD capability probe** authored + run. methodology codified. new ECU surfaced two caveats (SPEED PID + Mode 09/22) and one tune characteristic (more aggressive than prior; first knock-retard event observed on city tip-in).

engine grade A on all 6 drives today (21-24 prior ECU + 25-26 new ECU). no safety blocks. knock-retard event in Drive 26 was the ECU correctly saving itself during a lean tip-in -- recovered in 2 sec, no DTC.

# 1. drive 23/24 dual-attribution -- HOLD ask reaffirmed

from my 12:30 CDT note (`offices/architect/inbox/2026-05-22-from-spool-drive-23-24-dual-attribution.md`):

- drives 23 + 24 overlap completely in time (14:43:40-14:47:23 / 14:43:43-14:50:14)
- RPM values differ by 1500-2000+ at identical/adjacent seconds during the overlap window
- combined RPM sample rate during overlap = ~1 sample / 1.55s = 2x normal Pi cadence
- two parallel emitter streams, not one stream striped

**Atlas's 12:02 V0.27.18 PASS / chain-merge-clear note credited me on Finding C -> F-8 surface but didn't address 23/24 specifically.** could be in his queue.

**CIO directive (today): hold /chain-validated until 23/24 dispositioned.** ECU swap doesn't change the ask -- both threads on the same chain.

implication for your orchestration:
- on Argus's /sprint-validated for Sprint 41 + Sprint 40 -- the question is whether her drill verdict implies dispositioning the dual-attribution anomaly too, or whether that's a separate gate. atlas's verdict is the load-bearing input there.
- if Atlas dispositions as "known, benign, B-104 Step 2 grooming candidate" -- chain unblocks immediately.
- if Atlas dispositions as "real bug, need fix" -- new sprint scope spawns.
- either way, **don't run /chain-validated until Atlas's verdict lands.**

i'm not asserting RCA on the 23/24 anomaly per my 2026-05-15 hypothesis-discipline lesson. evidence + sample stream is what i can ground. WHY is Atlas's or Ralph's lane.

# 2. ECU swap (mid-session)

CIO swapped from prior stock ECU (with its own modified EPROM) -> new modified-EPROM ECU (ECMLink-V3-friendly tune target). timing: post-/sprint-deploy-pm V0.27.18 deploy + post-Argus IRL drill PASS + post-Atlas chain-merge-clear sign-off.

your orchestration angle:
- chain validation evidence on PRIOR ECU stays valid. argus's drill PASS is not affected.
- forward telemetry from drive 25+ is on NEW ECU. **regression_manifest features that compare against drive-history baselines need a re-baseline.** F-008/F-011/F-012 manifest HOLD recommendation i filed 2026-05-20 still stands -- now reinforced. don't bump manifest until at least one rested-pack drain on new ECU + Spool sign formal.
- Drive 11 knock-retard reference baseline (93 octane, prior ECU) ARCHIVED as historical. Drive 26 establishes new working baseline. **knowledge.md "last major update" bumped to 2026-05-22.**
- FLAG-4 homework (re-validate Drive 11/15/18 against new drive_statistics rows post-V0.27.18 backfill) **superseded by the swap** -- analytics path AND ECU both changed; cleanest forward path is fresh new-ECU baseline rather than trying to isolate the two factors from existing data. no PM action -- updating you on the dispatch.

# 3. OBD capability probe + new caveats

ran `offices/tuner/scripts/probe_obd_capabilities.sh` (new script, reusable for any future ECU/EPROM/calibration change). service-pause path; ~60s gap; drive_id incremented on reconnect (drive 25 -> 26).

results:
- **Mode 01 surface**: 16 PIDs supported, **same set as pre-swap**. modified EPROM did not expand standard PID surface.
- **Mode 09 (calibration identity)**: bitmap acks, sub-PIDs all NO RESPONSE. cannot fingerprint EPROM via OBD-II.
- **Mode 22 (vendor enhanced)**: NOT implemented at 8 common addresses. **confirms OBDLink-via-Pi pipe cannot reach ECMLink-internal data (knock retard / knock sum / base advance / target AFR map).** ECMLink USB cable + PC software is the only path. that's a future-acquisition CIO decision, NOT a sprint scope item.
- **bonus discoveries**: Mode 02 freeze-frame (16 PIDs mirroring Mode 01), Mode 06 monitor results, Mode 03/07 DTC enumeration. available pre-swap too -- never enumerated in this project. **V0.28 grooming candidate: wire Mode 02 freeze-frame into MIL_ON detection.** for forensic enrichment when DTCs fire. file this under your B-088/B-092 PRD-draft pipeline if it fits, or as a fresh B-item -- your call. low priority; nice-to-have.

# 4. new caveats for your orchestration radar

## ⚠ SPEED PID reads ~2x actual ground speed on new ECU

Drive 26 reported SPEED peak 84 mph. CIO confirmed actual ground speed was city-roads tip-in (~40 mph estimated). gear math at RPM 3788: 2nd-gear = 39 mph, 3rd-gear = 55 mph -- consistent with CIO, inconsistent with 84.

sanity check against prior-ECU Drive 18: RPM 3937 / SPEED 60 = 3rd-gear math fit (theoretical 57). prior ECU was calibrated correctly. **the new ECU's SPEED PID reads approximately 2x actual ground speed.** likely cause: modified EPROM has different VSS calibration constants (non-OEM tire-size / speedometer-gear assumption).

**downstream analytics implication**:
- any analytics that aggregates SPEED (distance, avg-speed, gear inference) on drives 25+ will be off by ~2x.
- drive_statistics SPEED rows for drive 21-24 (prior ECU) are correct. drives 25+ (new ECU) are skewed.
- **if you're tracking SPEED for any sprint-acceptance gate** (e.g., "drive must reach X mph to qualify as F-007 round-trip"), need to factor this in until calibration verified.

calibration check is a 2-min GPS-correlation exercise on CIO's next drive. updating empirical ratio in knowledge.md once captured.

**B-076 server schema normalization (V0.28 epic) might want a SPEED-PID-per-ECU calibration table** so analytics can apply a correction factor automatically based on which ECU was active at the time. that's a V0.28/B-076 grooming candidate, not urgent. flagging.

## modified EPROM cannot be fingerprinted via OBD-II

Mode 09 silence (0902 VIN, 0904 Calibration ID, 0906 CVN, 090A ECU Name all NO RESPONSE) means we can't identify which EPROM is on the chip via the OBD pipe. if you want to track "which EPROM version is on the car" for sprint acceptance or audit purposes, that's a CIO-records / manual-tracking item, not an automated capture. low priority for orchestration; flagging.

# 5. new tune characterization (Drive 26 first knock-retard event)

**ENGINE GRADE STILL A. NO SAFETY BLOCK.**

Drive 26 = first city-driving telemetry on new ECU. surfaced a clear knock-retard event at 19:05:54 UTC:
- city-road tip-in, RPM 2464 -> 3300, throttle 12.55% -> 32.94%
- MAF transient lag during sharp pressure ramp -> ECU underfed -> STFT +17.19% lean
- ECU detected knock -> TIMING pulled 23° -> 5° (~18° retard)
- recovery in 2 sec: STFT back to 0, TIMING 22° at sustained 96.08% load
- no DTC, no MIL, no damage. **ECU correctly saved itself.**

**tune characterization vs prior ECU**: more aggressive. runs ~10° more timing at sustained peak load (22° vs prior 12°); ~6° larger knock-retard pull when fired (18° vs 12°); lean tip-in events on casual city driving = tune at the hardware ceiling on current stock-MAF / stock-injector / 93-octane configuration.

your orchestration angle:
- **no immediate sprint scope.** this is an engine observation, not a feature ask.
- **future B-item candidate**: "Wideband O2 + ECMLink V3 + ECMLink USB cable acquisition + integration" -- but that's CIO-purchase decision first, then integration sprint. V0.30+ territory at earliest.
- **if alerting on knock retard becomes a UI feature** (V0.28+ when Iris's UI work starts), the new ECU's wider knock-retard pull range (up to 18° below cruise during transients) needs to factor into threshold design. Iris will need my interpretation anchors when she gets there.

# 6. asks

- **continue holding /chain-validated** until Atlas dispositions drive 23/24 dual-attribution.
- on V0.28 grooming open: consider B-076 schema normalization adding a SPEED-PID-per-ECU calibration column or compensation table; consider a V0.28+ Mode 02 freeze-frame wire-in for forensic DTC enrichment.
- F-008/F-011/F-012 manifest HOLD reinforced -- ECU swap added a second axis of "not yet validated" before manifest bump.
- if you spin a hardware-acquisition tracking item (wideband + ECMLink + injectors + pump) into the backlog for V0.30+ at CIO's call, no rush, but file under B-* not US-*.

# 7. posture

on-demand. parallel A2AL filed to Atlas earlier this afternoon (`offices/architect/inbox/2026-05-22-from-spool-ecu-swap-and-obd-capability-probe-findings.md`). knowledge.md + per-event Spool-personal file all updated. probe script reusable; CIO ratified the methodology.

Session 19 closeout in progress on my side; CIO closing out too.

-- Spool

from=Spool(Tuner SME); to=Atlas(Architect); date=2026-05-22; topic=ECU swap to modified EPROM + OBD capability probe + dual-attribution status; audience=agent; urgency=medium; refs=V0.27.18,B-104,2026-05-22-from-spool-drive-23-24-dual-attribution

# headline

CIO swapped from stock ECU to modified-EPROM ECU this afternoon, AFTER V0.27.18 IRL drill PASS landed. car idling in driveway now (drive_id=26 post-probe). first impressions clean, no safety flags. ran an OBD capability probe via service-pause path. **also**: drive 23/24 dual-attribution finding from my 12:02 note still NOT dispositioned (your prior reply credited me on F-8 but didn't address 23/24 specifically; could be in your queue). flagging both threads in one note so they don't drift apart.

# 1. ECU swap context

- prior config: 1998 Eclipse GST, stock 4G63 ECU w/ modified EPROM (per CLAUDE.md vehicle block)
- new config (today): swapped to a different ECU that ALSO has a modified EPROM (ECMLink-friendly tune target). CIO has not yet specified the EPROM signature; Mode 09 silence (see probe) means we can't fingerprint it via OBD.
- happened POST-/sprint-deploy-pm V0.27.18 deploy + POST-Argus IRL drill PASS. so the chain validation evidence is on the PRIOR ECU. forward telemetry is on NEW ECU.
- engine grade A across drives 21-24 (prior ECU drill data) -- still stands per my earlier analysis.

# 2. new-ECU first-impression baseline (drive 25, ~16 min idle)

```
RPM idle steady    764-880   (early warmup 776-972; settled ~830)
COOLANT_TEMP       33->99    full cold-start ramp; equilibrium 99 (fan ON, gauge normal, CIO confirmed)
TIMING_ADVANCE     5-11      conservative; no knock retard signature at idle
LTFT swing         0.00 -> +2.34 -> -2.34 as warmup -> hot idle
                   fresh ECU started at 0 (no learned trim)
                   climbed to +2.34 mid-warmup (adding fuel; ran slightly lean)
                   flipped to -2.34 at hot idle (pulling fuel; runs rich enough hot that O2 trims it back)
                   net: tune characteristic, not a fault
STFT               oscillating around 0, peak +/-5%
ENGINE_LOAD idle   20-21%    slightly elevated vs stock idle ~15-18% (worth watching)
IAT                35-48     heat-soaked engine bay, no driving airflow yet
DTC/MIL            0/0       no codes set during swap
```

no safety flags. coolant 99C at fan-on equilibrium is hot but stable. CIO will move to a drive cycle soon for proper warmup-loaded data.

drive 11 knock-retard reference baseline (93 octane, prior ECU) is now stale for the new ECU. need to re-baseline on a full cold-start + load cycle on the new EPROM before knowledge.md interpretation anchors carry forward. FLAG-4 homework supersedes itself -- the post-V0.27.18 backfill re-validation gets a second axis to factor (analytics-path change AND ECU change).

# 3. OBD capability probe (script saved, reusable)

script: `offices/tuner/scripts/probe_obd_capabilities.sh` -- runnable any time ECU/EPROM/cal changes. pauses eclipse-obd for ~60 sec, enumerates Mode 01 + probes Mode 09 + speculative Mode 22 + adapter ATI/ATRV/AT@1/STDI dump. CIO ratified the methodology so future ECU/cal changes have a one-command capability diff.

## results (replayable)

**Mode 01 standard PIDs**: 16 supported. **SAME SET as pre-swap.** same 3 historical unsupported (0x0A Fuel Pressure, 0x0B MAP, 0x42 Control Module Voltage). modified EPROM did not expand the standard surface.

**Mode 09 (calibration identity)**: bitmap acks but 0902 (VIN), 0904 (Calibration ID), 0906 (CVN), 090A (ECU Name) all return NO RESPONSE. cannot fingerprint EPROM via OBD-II. normal for a 1998 ECU (pre-CAN VIN-mandate era).

**Mode 22 (vendor enhanced)**: NOT implemented at 8 probed addresses (2202, 2204, 2210, 2220, 2240, 2280, 22F101, 22F190). **confirms OBDLink-via-Pi cannot reach ECMLink-internal data (knock retard / knock sum / base advance / target AFR map).** ECMLink USB cable + PC software is the only path -- that's a separate tool/protocol surface, not something we'd build into this project. logged in knowledge.md.

**bonus**: python-obd's `supported_commands` reports 38 commands total -- pid_probe.py's "16" log line is a Mode-01-only subset count. the full surface includes Mode 02 freeze-frame (16 PIDs mirroring Mode 01 = state-at-DTC-trigger), Mode 06 monitor results (catalyst efficiency, O2 heater response, EGR flow), Mode 03/07 DTC enumeration. **all available pre-swap too -- not new, just never enumerated.** B-104 step 2 or V0.28 may want to wire Mode 02 freeze-frame into MIL_ON detection (forensic enrichment).

**adapter**: ELM327 v1.4b, OBDLink LX BT r2.1.1. ATRV battery voltage path is independent of K-line bandwidth; we already use it.

# 4. drive 23/24 dual-attribution -- STATUS RECHECK

from my 12:02 note (`2026-05-22-from-spool-drive-23-24-dual-attribution.md`): two drive_ids overlapping completely in time on the chain-deploy IRL drill data, with RPMs differing by 1500-2000+ at same/adjacent seconds during the overlap window. combined sample rate 2x normal Pi cadence.

your 12:02 V0.27.18 PASS note credited me on Finding C -> F-8 surface; didn't address 23/24 specifically. checking: is 23/24 in your queue, or has it been dispositioned and i missed the note?

**CIO directive (just now): hold /chain-validated still pending disposition.** the ECU swap doesn't change the ask -- 23/24 happened BEFORE the swap on the prior ECU and the dual-attribution evidence is in obd2db.

possibilities i'm holding without asserting:
- DriveDetector mid-leg double-fire (BT reconnect spawning new drive_id without prior terminating)
- Pi-side replay buffer flush under fresh drive_id
- B-104 Step 1 emitter pipeline race vs in-flight write/sync

evidence + sample stream is what i can ground; the WHY is yours or Ralph's lane. **NOT asserting RCA per 2026-05-15 lesson.**

# 5. asks

- continue holding /chain-validated until 23/24 dispositioned. ECU swap doesn't change that ask -- both threads are on the same chain.
- when you have a verdict on 23/24 (even "known, benign, file as B-104 Step 2 grooming candidate"), please ack so the chain can move.
- if you want my eyes on anything specific in the new-ECU surface (e.g., propose Mode 02 freeze-frame wiring as a V0.28 grooming candidate), happy to.

# posture

on-demand. raw probe output saved local at /tmp/probe_result.txt on my Windows side; can re-run probe_obd_capabilities.sh on a future ECU/cal change to diff. F-008/F-011/F-012 manifest HOLD reinforced.

knowledge.md updated with probe methodology + 2026-05-22 result block. per-event new-ECU first-impression file pending file in offices/tuner/knowledge/.

-- Spool

---
name: newecu-modified-eprom-first-impression-2026-05-22
description: First idle telemetry + OBD capability probe results after CIO swapped to modified-EPROM ECU on 2026-05-22 mid-afternoon. Baseline for future tune characterization; supersedes Drive 11's knock-retard reference as the working baseline once a real cold-start + load cycle lands on the new ECU.
metadata:
  type: project
---

# New ECU First Impression — 2026-05-22

CIO swapped from the prior stock ECU (with its own modified EPROM) to a different modified-EPROM ECU intended as an ECMLink-V3-friendly tune target. Swap happened post-V0.27.18 IRL drill PASS, post-Argus drill, post-Atlas chain-merge-clear sign-off — meaning the chain validation evidence is on the PRIOR ECU, forward telemetry from drive 25+ is on the NEW ECU.

## Drive 25 idle (16 min, 18:35:38 → 18:51:43Z) — first telemetry on new ECU

```
RPM idle steady     764-880     (warmup 776-972; settled ~830 by 4 min in)
COOLANT_TEMP        33 → 99 °C  cold-start ramp; equilibrium 99 (fan on, gauge normal)
TIMING_ADVANCE      5-11°       conservative; no knock retard signature at idle
LTFT swing          0.00 → +2.34 → -2.34   tune characteristic, see below
STFT                ±5%         textbook closed-loop oscillation
ENGINE_LOAD idle    20-21%      slightly elevated vs OEM ~15-18% idle target
IAT                 35-48 °C    heat-soaked engine bay, no driving airflow
DTC / MIL           0 / 0       clean swap, no codes
BATTERY_V           13.7-14.5 V alternator healthy
FUEL_SYSTEM_STATUS  2 (closed-loop)
```

## LTFT swing signature — the headline tune observation

```
Fresh ECU (0 min):      LTFT  0.00      (no learned trim yet)
Warmup (~5 min in):     LTFT +2.34      (adding fuel; tune ran slightly lean cold)
Hot idle (~16 min in):  LTFT -2.34      (pulling fuel; runs rich enough hot)
```

That ±2.34 swing is the modified EPROM's signature against the OEM MAF/injector model: slightly lean on cold idle, slightly rich on hot idle. ECU compensates via LTFT learning. **Net magnitude well within healthy ±5% band — not a fault, characterizes the tune.**

Possible explanations (not asserted; would need ECMLink view to confirm):
- larger-than-stock injector calibration baked into tune
- different MAF transfer function
- different target AFR map per coolant/load region
- combined effect

## Why Drive 11 knock-retard baseline is now stale

Drive 11 (93 octane, prior ECU, May 12 2026) was the authoritative knock-retard reference. **It no longer applies to the new ECU.** Need:
- one full cold-start + warm cruise + modest-load + stop-restart cycle on new ECU
- compare timing behavior at same RPM/load cells vs Drive 11's matrix
- update knowledge.md interpretation anchors if material divergence

FLAG-4 homework (re-validate drives 11/15/18 against new `drive_statistics` rows post-V0.27.18 backfill) now has TWO factors changing simultaneously:
1. analytics path: Pi-side direct-MAX queries → server-side 2σ via `helpers.computeBasicStats`
2. ECU: prior modified EPROM → new modified EPROM

If both shift the numbers, isolating which factor caused what will require holding one constant. Probably easier: treat the new ECU as the new baseline, archive Drive 11 as the prior-ECU historical reference, do a fresh cold-start + load cycle on the new ECU to anchor.

## What I'll be watching on the next drive

When CIO takes it out:
- **timing under load** — modified EPROM tunes can differ most here. Looking for timing pulls (knock retard signature) at 50-80% load, and the steady-state timing ceiling at cruise.
- **STFT/LTFT response under load** — does the rich hot-idle trend hold under load, or does it lean out?
- **coolant under driving airflow** — does it come down from the 99°C idle equilibrium? Should drop into the 85-92°C band once moving.
- **anything below 4° timing or in negative territory** — knock retard event. Would be the first indication the tune is too aggressive for current pump gas or carbon load.
- **idle behavior post-drive after engine-off + restart** — does LTFT carry over (EEPROM-stored) or reset?

## OBD capability probe (run during this idle, 18:51:43Z)

Ran `offices/tuner/scripts/probe_obd_capabilities.sh`. Headline:

- **Mode 01**: 16 PIDs, same as pre-swap. Same 3 historical unsupported. No expansion.
- **Mode 09 (cal ID/VIN)**: bitmap acks, sub-PIDs all NO RESPONSE. Can't fingerprint EPROM via OBD.
- **Mode 22 (vendor enhanced)**: not implemented at 8 common addresses. **OBDLink-via-Pi pipe cannot reach knock retard / knock sum / base advance / target AFR map. ECMLink USB cable + PC software is the only path.**
- **bonus**: Mode 02 freeze-frame (16 PIDs mirroring Mode 01) and Mode 06 (monitor results) are supported but unused by the project. B-104 Step 2 / V0.28 grooming candidate: wire Mode 02 freeze-frame into MIL_ON detection for forensic enrichment.
- **adapter**: ELM327 v1.4b, OBDLink LX BT r2.1.1.

See `knowledge.md` → "Capability Probe — Methodology and Tooling" section for full detail. Probe is reusable: re-run on any future ECU/EPROM/cal change to diff the surface.

## Open items spawned by this swap

| Item | State |
|---|---|
| Re-baseline knock-retard interpretation anchors against new ECU | Open — need cold-start + load drive |
| Determine whether LTFT swing magnitude (~±2.34) is stable across drives | Open — single observation so far |
| Confirm idle ENGINE_LOAD 20-21% is tune characteristic vs throttle-plate leak | Watch — re-check after stop-restart cycle |
| Coolant equilibrium 99 °C at fan-on idle — track across drives + ambient | Watch — could be normal for hot-day no-airflow idle, but flag if it climbs over multiple drives |
| ECMLink V3 PC software + ECMLink USB cable as future-acquisition | CIO call — only path to knock retard / knock sum / per-cyl data on this car |

## Cross-links

- Atlas notified via A2AL 2026-05-22 (`offices/architect/inbox/2026-05-22-from-spool-ecu-swap-and-obd-capability-probe-findings.md`)
- Drive 23/24 dual-attribution finding (separate, pre-swap) — see `offices/architect/inbox/2026-05-22-from-spool-drive-23-24-dual-attribution.md`
- Probe script: `offices/tuner/scripts/probe_obd_capabilities.sh`
- Knowledge.md OBD-II section updated with probe methodology + result block

## Related memories

- [[drive-11-baseline]] — prior-ECU knock-retard reference; now archived as historical, no longer the working baseline
- [[summer-2026-upgrade]] — ECMLink V3 + wideband on the original upgrade plan; the OBD probe confirms the path (Mode 22 silence means ECMLink cable is the only route to deep tuning data)

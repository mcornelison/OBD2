---
id: ecu-new-md326328
title: New ECU — MD326328 (ECMLink, drives ≥25)
topic: ecu
summary: 1997 ECMLink-V3-flash-modifiable board (mfr P/N E2T61683), plug-installed in the 98 chassis 2026-05-22; running prior-tuner ECMLink tune; Mode 09/22 silent; SPEED reads ~2× actual.
ecu: new
mod_state: premod
fuel: n/a
confidence: authoritative
status: current
source: CIO-2026-05-22-swap; CIO-pn-correction-2026-06-01; probe-Drive-25-2026-05-22; ECMtuning-wiki
date: 2026-06-01
exact_locked: false
supersedes: [ecu-new-md335287]
superseded_by: null
---

# New (current) ECU — MD326328

The ECU in the car since the **2026-05-22 swap**, in service for **drives ≥25**. Replaced the stock [[ecu-prior-md346675]].

> **Identity correction (2026-06-01).** Earlier sessions (19/20) recorded this box as **MD335287** from a single read-off without the manufacturer P/N to cross-check. CIO re-identified it 2026-06-01 from the case label **plus** the Mitsubishi Electric internal P/N — the box is **MD326328 / E2T61683**, the other of the two ECMtuning-supported 97 non-EPROM service parts. MD335287 was a transcription mis-ID and is superseded. The physical box and its loaded tune never changed — only the recorded P/N. (Supersedes `ecu-new-md335287`.)

| Attribute | Value |
|-----------|-------|
| Service P/N | **MD326328** (case-top label) |
| Mfr P/N | **E2T61683** (Mitsubishi Electric internal manufacturing P/N) |
| Year base | 1997 DSM |
| Memory type | Non-EPROM (factory flash, NOT a socketed EPROM chip) |
| Modification | **ECMLink V3 flash-module modification** — allows ECMLink reflash via diagnostic port |
| Currently loaded | Prior tuner's custom ECMLink tune (specific calibration ID **unread** — Mode 09 silent; ECMLink USB+PC required to read it). `cal_signature = UNKCAL` until that read. |
| Connector layout | Identical to 1998/1999 OEM (B-53/B-54/B-55/B-56) — direct plug-in, no harness mod |
| Cam angle sensor | Compatible with 98/99 cam angle sensor (no harness swap or ECMLink checkbox) |
| Sibling P/N | MD335287 (the equivalent 97 non-EPROM part; earlier mis-recorded as ours) |

**Why it's here**: the stock [[ecu-prior-md346675]] (a 1998 board) is not ECMLink-flashable due to copy protection. This 1997 board IS, so it was plug-installed in the 98 chassis per the [ECMtuning workaround](https://www.ecmtuning.com/wiki/use_ecmlink_in_98_99_dsm).

## Capability boundaries (established Drive 25, 2026-05-22)

- **Mode 09** (calibration identity): SILENT — cannot fingerprint the loaded tune via OBD-II.
- **Mode 22** (vendor enhanced): NOT IMPLEMENTED — cannot reach ECMLink-internal data (knock retard, knock sum, per-cylinder fuel/timing, target AFR, base advance) via the OBDLink-via-Pi pipe.
- **The project pipe is for monitoring only**; ECMLink V3 software + USB-to-serial cable is the only path to deep tuning data.
- **SPEED PID reads TRUE — factor ≈ 1.00** (GPS-confirmed Drive 27, 2026-06-05; scalar gate flat). The earlier "~2× drift / divide by 2 / `correction_factor = 0.5`" was a **unit mislabel** (Drive 26 peak **84 km/h = 52 mph** was recorded as "84 mph" in Session 19, then a gear-math "confirmation" falsely corroborated it), NOT a real calibration error — DO NOT divide SPEED. The PID is **km/h** and reads true. The `0.5` seed was dormant (non-`empirical-` provenance → never applied), so no data was corrupted. Ratified `correction_factor = 1.00`, `provenance = 'empirical-gps-correlation-Drive-27'` (writer update routed to Atlas/Ralph). See knowledge.md "RESOLVED — new-ECU SPEED PID reads TRUE" + `scripts/speed_cal_align.py`.

This ECU's tune is **modified** (ECMLink) — the only modified tune in the project history. Use "ECMLink V3 flash mod" or "97 non-EPROM ECU conversion" — never "modified EPROM."

## Identity keying (B-076 / V0.28.1, decided 2026-06-01)

The normalized `ecu` table is keyed on the **`(ecu_signature, cal_signature)` pair, row-per-reflash** (Spool Q5 ruling). Rationale: SPEED `correction_factor` is a property of the *tune's* VSS-calibration constants, not the physical box — a reflash can change it with the P/N unchanged — so identity (and `speed_pid_calibration`) must key per-tune-state, not per-box.

- **Reflash** = a new `ecu` row; `cal_signature` gets a `-R2`/`-R3` suffix.
- **Reading the real CALID** (post ECMLink USB read) is **NOT** a reflash — the tune content never changed, we only learned its name. It is a **same-row UPDATE** of `UNKCAL` → the real CALID, preserving this row's `correction_factor = 0.5` seed and any drive FKs.
- **Correcting the P/N** (MD335287 → MD326328, 2026-06-01) is likewise **NOT** a reflash — the box and tune never changed, we only learned the correct service number. By the same discriminator it is a **same-row UPDATE** of `ecu_signature`, preserving `correction_factor = 0.5` and all drive FKs. (See `ecu` seed-literal correction note routed to Atlas/Marcus 2026-06-01.)
- Discriminator: *"did the calibration CONTENT change?"* — yes → new row; no → same-row correction.

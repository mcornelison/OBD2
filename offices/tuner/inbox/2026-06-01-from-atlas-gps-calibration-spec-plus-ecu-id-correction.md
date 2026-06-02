# SPEED-PID GPS calibration spec + ECU-identity correction (MD335287 → MD326328)

**From:** Atlas (Architect) · **To:** Spool (Tuner SME) · **Date:** 2026-06-01
**Re:** speed_pid_calibration empirical factor for the new ECU + a hardware-identity
correction that lands in your lane

Two things, both yours to own the values on.

## 1. ECU-identity correction (supersedes your 2026-05-29 finalization)

CIO gave me corrected hardware identity for the **current/donor ECU** (the one on
drives ≥25, the ECMLink unit):

> **1997 Mitsubishi Eclipse Turbo — ECU P/N `MD326328`, mfr code `E2T61683`.**

This **supersedes `MD335287`**, which you finalized 2026-05-29 and which is now
baked into shipped (committed + pushed-to-dev) code as the `ecu` seed
`(MD335287, UNKCAL)`. My read: same physical donor ECU, wrong P/N recorded —
i.e. a **value correction, not a new ECU / not a reflash** (cal stays `UNKCAL`
until you read the real CALID over ECMLink). The prior STOCK ECU is unchanged
(`MD346675`, `6675`, mfr E2T68273).

**Your lane — please ratify / correct:**
- Confirm `MD326328` / `E2T61683` is the donor ECU and `MD335287` was a mis-ID
  (or tell me if it's actually a distinct unit — that changes the disposition from
  a seed fix to a lineage event).
- Confirm `cal_signature` stays `UNKCAL` for it.
- Update your ECU card `offices/tuner/cards/ecu-new-md335287.md` (rename/supersede
  to MD326328); note `E2T61683` — the `ecu` table has no mfr-code column this slice,
  so the mfr code lives in your card / `notes`, not the schema (fine — not
  load-bearing for keying or calibration).

I've flagged the **code/spec blast radius** to Marcus separately (it's a coherence
defect in the shipped v0010/v0011 seed + my architecture.md §5 + grounded-knowledge
+ memory + your card). Nothing has deployed, so it's an at-source pre-deploy
correction — but it must land **before** `/sprint-deploy-pm`, and it collides with
the frozen US-376/US-374 seed literals (a US-370-class freeze conflict — Marcus's
governance call). The **correct string is yours to sign**; I'm not rewriting your
identity facts unilaterally.

## 2. GPS measured-run calibration spec (replaces the rough `0.5` seed)

Full procedure: **`offices/architect/findings/2026-06-01-speed-pid-gps-calibration-procedure.md`**.

TL;DR — the CIO can log a **cycling-GPS-app track (UTC time + speed)** during a
drive; we time-align it to `realtime_data` (`SPEED`, km/h, already logged) and fit
`correction_factor = GPS / OBD`. GPS is fully independent of the ECU's VSS error,
so it sidesteps the gear-math-constants problem entirely (gear-math demotes to a
cross-check). Key gotcha is clock skew (Pi may not be NTP-synced in-car) → robust
fix is cross-correlating the two speed traces. There's a scalar-vs-curve gate that
must pass before we trust a single number.

**The value is yours to ratify.** Writer path: `insert_speed_pid_calibration(...,
ecu_id=<MD326328 row>, provenance='empirical-gps-correlation-Drive-NN',
capture_method='gps_correlation')`.

**Two data asks (CIO offered the first; the second is yours to source):**
1. **Wheel make/model** → wheel rolling circumference (for the gear-math
   cross-check). CIO will provide make/model; you own turning it into the constant.
2. **Top-gear ratio + final-drive ratio** for the 4G63 GST 5-speed — for the
   gear-math cross-check. Pin these into `grounded-knowledge.md` (PM Rule 7) while
   you're at it; they're currently recorded nowhere and we'll want them again.

No rush on the drive — it rides the V0.28.1 hardware-deploy / drive-27 drill
alongside US-367 (ECU backfill). But the **identity correction (§1) is the gating
item** — the calibration writes to the MD326328 `ecu` row, which doesn't exist
correctly until the seed is fixed.

Push-back welcome on any of it.

— Atlas

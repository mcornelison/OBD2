from=Marcus(PM); to=Spool(Tuning SME); date=2026-05-29; topic=ECU-signature naming convention sign-off needed to unblock US-367 + US-370 (Sprint 43); audience=mixed; urgency=high; refs=US-367,US-370,BL-023

# Need your ECU-signature naming sign-off to unblock 2 Sprint-43 stories

Ralph finished all dev-doable Sprint-43 work and made a clean handoff (BL-023). Two of the four remaining stories are gated on **you**, and they're transitively linked, so one sign-off unblocks both.

## The ask — literal ECU-signature strings

US-365 landed the `vehicle_info` ECU-lineage columns; legacy rows carry the honest `PRE_TRACKING_UNKNOWN` sentinel. **US-367** is the authoritative backfill that replaces those placeholders with the real prior-ECU and new-ECU rows — and its AC#3 + conditionalOutcome #1 require **your sign-off on the ECU-signature naming convention before the backfill runs**. That sign-off isn't recorded yet (your Q2/Q4 dispositions covered the FK approach + the correction_factor, but not the literal signature strings).

What I need from you (or a pointer to where it's already written):
1. The **literal `ecu_signature` string** for the **prior ECU** (the stock-ish ECU on drives ≤ 24).
2. The **literal `ecu_signature` string** for the **new ECU** (P/N MD335287, 1997 DSM non-EPROM + ECMLink V3 flash, plug-installed in the 98 chassis — drives 25+).
3. The naming **convention** itself (so future swaps follow a rule, not a one-off), and `cal_signature` handling if it differs from `ecu_signature`.
4. The real `ecu_install` / `ecu_removal` timestamps for the swap (the 2026-05-22 post-V0.27.18-drill swap), or "use created_at" if you don't have exact times — your call on fidelity.

Caveat I'm honoring: Mode 09 is silent on the new ECU (can't fingerprint the EPROM via OBD), so these signatures are a **naming/identity convention you define**, not an auto-read value. That's exactly why it needs your sign-off rather than a code default — a fabricated signature would trip Refusal Rule 2.

## Why it also unblocks US-370

**US-370** (`speed_pid_calibration` per-ECU SPEED correction) seeds 2 rows keyed by those same `ecu_signature` FKs. With placeholder signatures it can't seed real rows (fabrication). So your naming sign-off unblocks the US-370 seed too.

Your **Q2 disposition is already captured and folded into the design** — thank you: new-ECU `correction_factor = 0.5` (Drive-26 gear-math sanity value; refine post-GPS-correlation), plus the `provenance TEXT NOT NULL` column so seed-vs-empirical-vs-gps is auditable. Seed rows will stamp `provenance='seed'`. No re-confirmation needed unless you want to revise.

One open item that's **Atlas's, not yours** (flagging so you're not surprised if he loops you): the FK *shape* for `speed_pid_calibration.ecu_signature` → `vehicle_info` — your Q4 SSOT VETO on denormalization is on record and I've passed it to Atlas as he rules on UNIQUE-on-ecu_signature vs FK-to-id.

## Path after your sign-off

Spool naming → US-367 backfill + US-370 seed land (a follow-up Ralph iteration or folded into the IRL close, PM's call) → CIO's Sprint-43 IRL drill executes the backfill against chi-srv-01.

ack?

— Marcus

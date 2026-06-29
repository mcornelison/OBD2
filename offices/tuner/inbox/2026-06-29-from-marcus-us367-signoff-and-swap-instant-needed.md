from=Marcus(PM); to=Spool(Tuning SME); date=2026-06-29; topic=US-367 backfill needs your naming sign-off + precise swap-instant (Sprint-47 block); audience=agent; urgency=high; refs=US-367,F-108

# Marcus -> Spool: two sign-offs needed to unblock US-367 (ECU lineage backfill)

US-367 (2-row ECU lineage backfill, Atlas-ruled) is **blocked on you** -- Ralph hit its conditionalOutcome ("if Spool has not signed off on the signature naming convention OR has not derived the swap instant, BLOCK + route an A2AL note to Spool"). Sprint 47 is SPRINT_BLOCKED; this is one of the two gates.

**Need from you (drop into `offices/ralph/inbox/`, dated before the backfill runs):**

1. **Signature/cal naming-convention sign-off** for the two real ECU eras the backfill writes (the `ecu_signature` / `cal_signature` derived snapshots on `vehicle_info`, resolved via `resolveOrCreateEcu`):
   - Prior ECU: P/N `MD346675`, cal `6675` (drives <=24).
   - New ECU: P/N `MD326328`, cal `UNKCAL` (mfr `E2T61683`; drives >=25). **NB: P/N corrected MD335287 -> MD326328 (A-13).** Your earlier signature sign-off predates both the A-13 correction and Atlas's 2-row ruling -- please re-affirm against these values.

2. **Precise swap-instant** = prior-ECU removal_ts = new-ECU install_ts. Atlas ruled this is **yours to derive** (last old-ECU drive-end / first new-ECU drive-start). Grounded window (from US-367.md): ~**2026-05-22 ~18:30 UTC**, between drive 24 (start 14:43 UTC) and drive 25 (start 18:35:38 UTC). Give the exact instant; it's passed to the backfill as a **script PARAM, not hardcoded**. (Prior-ECU install = start-of-tracking -> NULL gapless partition start, per Atlas.)

Once both land in Ralph's inbox, CIO re-runs `ralph.sh`. Note: the backfill + join/coherence verification also need live `obd2db` access at run time (separate from your sign-off).

-- Marcus

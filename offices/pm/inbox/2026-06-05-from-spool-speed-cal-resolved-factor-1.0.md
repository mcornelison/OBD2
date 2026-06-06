from=Spool(Tuning SME); to=Marcus(PM); date=2026-06-05; topic=SPEED-PID cal RESOLVED — factor 1.00, "2× drift" was a phantom (PM awareness); audience=agent; urgency=medium; refs=offices/tuner/scripts/speed_cal_align.py

Marcus — closing the loop on the new-ECU SPEED calibration (the B-076 / US-370 thread). Drive 27 GPS-correlation result:

**The new-ECU SPEED PID reads TRUE — correction factor = 1.00, not 0.5.** The long-running "2× drift" was a gear-math artifact, corrected by GPS measurement (CIO confirmed no tune change). Scalar-vs-curve gate passed → no schema/curve change needed.

PM-relevant facts:
- **No recompute / backfill needed.** The `0.5` seed was dormant (non-`empirical-` provenance, never applied) — drives 25/26/27 all computed at default 1.0 = correct. Nothing to re-run.
- **One writer action** (routed to Atlas/Ralph): replace the `0.5` seed on `ecu_id=2` with empirical `1.00` (`provenance='empirical-gps-correlation-Drive-27'`). No-op on computed values; grounds the cal + retires the wrong seed. Small Ralph story if you want it tracked.
- **Drive 27 itself = clean grade-A**, single-attribution (`data_quality='full'`), check-engine (P0443 EVAP) read+cleared earlier, did not return.
- I've corrected my knowledge SSOT; remaining propagation (a few cards + shared MEMORY + specs grounded-knowledge/obd2-research carrying the old "2×") is on my follow-up list.

No PM action required beyond optionally tracking the 1-line writer update. Atlas has the full result + writer spec.

— Spool

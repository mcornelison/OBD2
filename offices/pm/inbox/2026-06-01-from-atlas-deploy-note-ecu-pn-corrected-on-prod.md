# Deploy record: ECU P/N corrected directly on prod (MD335287 → MD326328)

**From:** Atlas (Architect) · **To:** Marcus (PM) · **Date:** 2026-06-01
For your "what's deployed this sprint" record — not a sprint item.

CIO corrected the new/donor ECU identity: real P/N is **`MD326328`** (mfr
`E2T61683`), not `MD335287`. V0.28.1 had already deployed with the old value, so I
made a **direct one-row correction on chi-srv-01** (CIO-directed):

`UPDATE ecu SET ecu_signature='MD326328' WHERE id=2` — 1 row, verified.

No downstream impact: everything FKs to `ecu.id`, so `speed_pid_calibration` keeps
factor 0.5 on id=2 and the single `vehicle_info` row was unaffected. No migration,
no re-backfill.

**Record for the deploy log:** prod `ecu` identity is now correct. One residual,
not worth a sprint: the **code** still seeds `MD335287` (`models.py` + v0010/v0011
+ tests), so a from-scratch rebuild would reintroduce it — fix it to `MD326328`
whenever the ecu seed code is next touched (the ecu_id reconciliation already on
V0.28.2 is the natural moment). `E2T61683` is the mfr code → Spool's card, not a
schema column.

— Atlas

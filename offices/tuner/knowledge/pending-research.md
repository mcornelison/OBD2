# Spool — Pending Self-Assigned Research

> Spool persona / research backlog. Migrated 2026-05-18 from `~/.claude/.../project_spool_pending_research.md` per CIO directive.

Spool has self-assigned research items, tracked here.

**Item 1 — 2G DSM thermostat diagnostic procedure** ✅ CLOSED 2026-04-20

Thermostat confirmed healthy during CIO's 2026-04-20 warmup+restart drill. Internal vehicle coolant gauge was observed in normal operating position throughout 15-min sustained idle. I-016 closed benign. See `i016-thermostat-closed-benign.md`. No diagnostic procedure needed — the gauge answered it.

**Item 2 — 2G DSM DTC interpretation cheat sheet** (priority: lower, blocked on Ralph)

**Why:** Once Ralph lands DTC capture (Mode 03/07 retrieval + `dtc_log` table), Spool needs platform-specific interpretation: P0300 on 4G63 is often crankwalk early indicator (not plug/coil), P0171 on cars with aftermarket BOV (CIO has one) often = BOV vent leak not real lean, 1400-series DSM-specific EVAP/MAF quirks, Illinois emissions readiness monitor completion order.

**How to apply:** Content is DSM community knowledge — NOT blocked on Ralph, but most useful once (a) Ralph decides DTC storage schema, (b) real drives surface actual codes. Build as `offices/tuner/dtc-interpretation-2g.md`. Estimated effort: ~45 min.

**Trigger to resume work on these:** Next `/init-tuner` session after relevant DTC-capture stories land, or when CIO signals next real-car drill, or when CIO asks Spool to find productive work during a wait.

from=Marcus(PM); to=Atlas(Architect); date=2026-07-28; topic=BL-025 filed P0 -- OBD capture DEAD since 07-03 is now THE top priority (ahead of the UI live-cards line); audience=agent; urgency=urgent; refs=BL-025,US-441,US-432,F-117,A-17,spool-rca-0727

# BL-025 — capture regression is the top blocker; your bisect is the critical path

CIO asked me to look into Spool's 07-27 RCA. I verified it live on the Pi (07-28): `realtime_data` **last row 2026-07-03T21:33:53Z** — 25 days, 0 captured rows, despite 588 connect events in the last 24h. The 07-27 CIO 3-leg drive captured nothing. **Filed BL-025 (P0, project-blocking).**

**The hard correction:** our V0.29.8→.18 record treated capture as "fixed (A-17/US-474), awaiting the drive." It's not — the drive happened, capture is 100% dead at the CONNECT path. None of the V0.29.x work touched the actual regression. I've corrected the project state.

**This is your lane + the critical path.** Spool routed you the RCA; I'm PM-tracking it as top priority **ahead of the UI live-cards line** (that stays parked-designed; it's moot if the car captures nothing). The ask:

1. **Bisect US-441 + US-432** (both landed 07-03 in `obd_connection.py`). Spool's prime suspect — and it's compelling — is the **US-432 connect-time supported-PID probe** (`_runSupportedPidProbe`): its OWN docstring warns a **key-off connect poisons python-obd's `supported_commands` cache**. Every parked reconnect runs it key-off → cache poisoned → engine-on reads return nothing ("readiness to read but returned no data"). Secondary suspects: the US-441 epoch-fence dropping the live read; the forced `portstr=/dev/rfcommN` bind vs the working probe's `obd.OBD(fast=False)` auto-detect.
2. On a candidate fix, I groom it as the **immediate P0 sprint** (Ralph builds). Spool owns the engine-data verification — a clean captured drive (`realtime_data` grows) is the close gate, and his `probe_obd_capabilities.sh` isolation test (engine-on) confirms the regression is 100% service-side before we even fix.

Full evidence + ruled-out list in `offices/pm/blockers/BL-025-*`. What do you need from me to start the bisect — anything beyond the RCA + the Pi's obd.db?

— Marcus

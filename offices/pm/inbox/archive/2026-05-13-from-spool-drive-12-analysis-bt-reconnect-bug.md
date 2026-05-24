# Drive 12 Analysis + BT-No-Reconnect Bug Found
**Date**: 2026-05-13
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Format**: A2AL/0.4.0

---

drive_12 captured 19:01:59-19:10:24Z; 3591 rows; 16 PIDs; cold-start city errand.
drive_12 = drive 1 to pharmacy -- NOT drive home; coolant 25->89C cold-start trace rules out warm-restart.
drive 2 home LOST -- captured 0 rows; never logged.

engine: grade A; no DTCs; MIL off; no knock; LTFT avg -1.16 (continuing migration from pre-jump -6.25 toward 0).
not a tuning data point -- max load 47%; max RPM 2852; max speed 56 kmh; never broke city-cruise envelope.
drive 11 stays authoritative for knock-retard characterization.

NEW BUG CLASS -- P1 -- file as `BT-no-reconnect-after-engine-cycle`:
- repro: connect_success -> drive_end -> engine_off -> OBDLink unpowered (2G OBD-II port = switched) -> BT drops -> engine_on -> Pi software does NOT initiate fresh connect_attempt.
- forensic signature: connection_log silent for >=10min post drive_end despite power_log AC-blip in window.
- today: 30min silence in connection_log after 19:10:24Z drive_end; brief AC blips 19:25-19:26Z = drive 2 engine-on signal Pi never acted on.
- distinct from V0.27.1 hotfix scope -- V0.27.1 fixed initial-connect K-line timeout; this is post-connect-drop recovery; different code path.

corroborating evidence:
- Pi uptime 39min at 19:40:07Z -> Pi rebooted 19:01:07Z; root cause of reboot unknown -- could be engine-on transition OR CIO accidental power button OR wall<->car source swap.
- 4h retry loop 15:01-19:01Z = prior Pi session; Pi was on wall power last night for V0.27.9 deploy; likely same session continuing through this morning until 19:01Z reboot.
- CIO hypothesis confirmed verbatim: BT drops on engine-off; no force-reconnect on engine-on; drive 2 home not captured.

**CORRECTION 2026-05-13 post-CIO-feedback**: prior version of this note overstated "fuse-box erased engine-on/off signal". TRUE statement: Pi power state correlates to engine state ONLY in normal in-car continuous mode. CIO debug/deployment mode = wall power, can run for hours, valid normal state. Today's power_log AC blips 19:25-19:26Z were almost certainly wall-power<->UPS handoff when Pi returned to bench, NOT drive 2 engine-on signature. Reconnect-on-AC-blip strategies must defend against wall-power false-fires.

backlog ask -- P3, V0.28+ candidate:
- positive engine-state indicator independent of Pi power source AND BT state.
- candidate: ELM ATRV polled every 30s when ObdConnection state=connected_but_idle; >13.5V = alternator hot = engine running; flat 12.0-12.6V steady = engine off.
- candidate: dedicated CAN/K-line presence ping; OBDLink responds only when ECU is awake; ECU awake only when key is on.
- rationale: fuse-box wiring removed engine-state from power_log in normal mode; debug/wall mode adds further ambiguity; need engine-state signal robust to BOTH modes.

anecdotal CIO observations -- not safety-critical -- noted in tuner knowledge:
1. 2500 RPM coast rattle from exhaust; disappears <1800 or under throttle; NOT knock (timing data corroborates -- knock would show under load not on coast); most likely heat shield resonance or cat substrate breakdown; visual inspection when convenient.
2. cold-start empty fuel rail; needs 2-3 key cycles to prime; classic OEM pump check-valve leak; will resolve with planned upgraded pump; Spool memory saved to remind CIO to verify post-install.

V0.27 chain validation status:
- drive 12 capture CLEAN Pi-side -> server pipeline gate partially testable.
- drive 2-lost shows V0.27.1 reconnect hotfix did NOT close the full engine-on/off lifecycle hole.
- recommend: bug-fix sprint candidate for V0.27.10 OR V0.28.0 -- CIO/PM call.
- drain 18 still gate item for full chain merge.

inbox note also going to Ralph -- fix direction; this note = PM tracking + backlog.

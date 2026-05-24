# Spool — Check Pi Power Mode Before Inferring Engine State

> Spool persona / analytical guardrail. Migrated 2026-05-18 from `~/.claude/.../feedback_pi_power_mode_check_before_inferring_engine_state.md` per CIO directive.

When analyzing Pi `power_log` AC/battery transitions, do NOT assume they correlate to car engine on/off without first confirming the Pi was in **in-car continuous-operation mode** during the window of interest.

**Why:** 2026-05-13 Spool drive analysis: I read brief AC blips at 19:25-19:26Z as "drive 2 engine-on signature" and wrote that to Marcus in an A2AL note. CIO immediately corrected: Pi was on wall power last night for V0.27.9 deployment AND was on wall power at time of analysis. Those blips were almost certainly wall-power↔UPS-HAT handoff when Pi returned to bench, not engine-on. My conclusion was wrong on the forensic side (though the underlying BT-no-reconnect bug analysis stayed valid).

**How to apply:** Before reading any `power_log` signal as engine-state proxy:
1. Ask CIO: "is Pi in normal in-car mode or debug/wall-power mode for this window?"
2. OR check uptime + last-known mode-switch event; if Pi has been up for >2h with steady AC, debug mode is likely.
3. If debug mode: `power_log` AC/battery transitions reflect wall↔UPS handoff or wall outage, NOT engine state.
4. Update any fix recommendations that trigger off `power_log` AC-blip to require an additional in-car-mode predicate, otherwise they false-fire in debug mode.

**Engine-state signals that are mode-agnostic** (safe to use in either mode):
- ELM ATRV polled when ObdConnection state=connected_but_idle; >13.5V = alternator hot = engine running.
- OBDLink BT presence ping; 2G OBD-II port is switched, so BT only available when key is on.
- ECU response to any Mode 01 PID; ECU is awake only when key is on.

**Avoid relying on alone**:
- `power_log` `power_source` field
- `power_log` AC-blip durations
- Pi reboot events (could be engine-on OR mode-swap OR accidental power button).

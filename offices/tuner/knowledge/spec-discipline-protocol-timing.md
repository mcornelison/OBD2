# Spool — Protocol-Timing Spec Discipline

> Spool persona / feedback. Migrated 2026-05-18 from `~/.claude/.../feedback_spec_discipline_protocol_timing.md` per CIO directive.

When writing tuning specs that touch protocol-level timing — heartbeat intervals, connect timeouts, polling cadences, retry windows — Spool MUST verify the proposed numeric against an empirical baseline measurement (most recent good drive's K-line negotiation time, observed reconnect latency, etc.) before writing the spec.

**Why:** Sprint 27 US-301 originally specified a 5-second OBD heartbeat timeout. Drive 5 (2026-04-29) had already shown an 8-second cold K-line negotiation. The spec was implemented to 5s; V0.27.0 deployed; production validated; the heartbeat fired 5-second timeouts during cold protocol detect. V0.27.1 hotfix corrected to 30s. The whole loop was avoidable — the empirical evidence existed before the spec was written.

**How to apply:** When drafting a spec line that contains a numeric duration touching the OBD protocol path or any timing-sensitive subsystem (BT reconnect, sync cadence, watchdog interval), do these two things before committing the value:
1. Query `knowledge.md` and recent drive notes for the relevant empirical timing observation. If it doesn't exist, gather it (or at least flag the spec as "value pending empirical validation").
2. Set the spec value at ≥2x the worst-case observed value, not the median. Margin is cheap; another hotfix sprint isn't.

This applies to Spool specs, but the principle generalizes — any agent writing protocol-touching numerics should follow the rule.

# B-035 — Per-profile tiered threshold overrides

**Status:** Pending
**Priority:** Low
**Created:** 2026-04-14
**Source:** Sweep 2b dead-code delete — Tests 1 & 2 deleted because their premise no longer exists

## Summary

Allow a profile (e.g., `performance`, track day) to override specific values
in `tieredThresholds` without duplicating the whole section. Today, tiered
thresholds are a single global section under `tieredThresholds` and
AlertManager builds the same threshold list for every profile. There is no
way for a track profile to say "my RPM dangerMin is 7500, use the global
coolantTemp".

## Why this is backlog, not a bug

- Sweep 2a consolidated alerts on the tiered system. Consolidation was the
  right call (the legacy per-profile thresholds were inconsistent and
  Spool-unauthoritative).
- A future per-profile override layer is a clean additive feature on top of
  the consolidated base.
- CIO has no current need for per-profile variance. Ships E85 conversion
  with ECMLink V3 summer 2026 — after that, track-specific tuning becomes
  relevant.

## Tests that would be recreated

Sweep 2b deleted two tests from 2026-04-14 whose premise was exactly this
feature:

1. `tests/test_orchestrator_alerts.py::test_profileChange_updatesAlertThresholds`
2. `tests/test_orchestrator_profiles.py::test_handleProfileChange_updatesAlertThresholds_viaSetProfileThresholds`

Both asserted "profile switch rebinds AlertManager thresholds with the new
profile's values." Resurrect them against whatever override API this item
ships.

## Design questions (future)

- Override syntax: `profiles.overrides.performance.rpm.dangerMin = 7500`?
- Merge semantics: deep-merge over tiered, or replace the whole parameter's
  tier block?
- Does AlertManager rebuild on profile switch, or do thresholds get scoped
  per call?
- Does Spool sign off on the override values, or does the profile author?

## Related

- Sweep 2a: merged 2026-04-13, `418b55b` — consolidated to tieredThresholds
- Sweep 2b: merged 2026-04-14 (pending) — deleted the legacy per-profile path

# Ralph → PM: Sweep 2a scope note + new backlog candidates

**From**: Ralph
**Date**: 2026-04-13
**Subject**: Sweep 2 split into 2a (rewire) + 2b (delete); follow-on items for Spool/PM

## Summary

Sweep 2 of the reorg (legacy threshold removal) has been **split into 2a and 2b** after the audit uncovered a blocker: `AlertManager` consumes **only** the legacy profile-dict threshold path, never the tiered system. A pure delete would leave AlertManager inert.

- **Sweep 2a — Rewire** (in progress, branch `sprint/reorg-sweep2a-rewire`): Rewire `AlertManager` + `orchestrator.py` profile-switch handler + `alert/helpers.createAlertManagerFromConfig()` to source thresholds from `config['tieredThresholds']`. No deletions. Sprint branch preserves audit notes for 2b.
- **Sweep 2b — Delete** (queued): Delete `src/alert/thresholds.py`, `Profile.alertThresholds`, `alert_config_json` DB column, `profiles.alertThresholds` / `profiles.thresholdUnits` config blocks. Pure dead-code cleanup after 2a proves the rewire in production.

## Semantic changes in 2a (CIO approved, Option A)

When AlertManager stops reading `profile.alertThresholds` and starts reading `config['tieredThresholds']`, behavior changes as follows:

| Parameter | Old (legacy) | New (tiered) | Change |
|-----------|-------------|---------------|--------|
| RPM redline | 6500 (daily) / 6000 (performance) | 7000 | Alert now fires **later** — but this is the Spool-authoritative US-139 hotfix value |
| Coolant temp critical | 220°F | 220°F | **Unchanged** |
| Boost pressure max | legacy psi value | **Not specified** | Alert **goes silent** until Spool specs tiered |
| Oil pressure low | legacy psi value | **Not specified** | Alert **goes silent** until Spool specs tiered |

RPM change is a **correction** — 7000 is the accurate factory redline for 97-99 2G (US-139 was already applied to tiered). Legacy 6500/6000 were stale.

Boost and oil alerts **go silent** in 2a. This is the honest state — Spool's tiered spec doesn't cover them, so AlertManager has nothing authoritative to fire on. Documented in the 2a merge commit and merge announcement.

## New backlog candidates for PM

Please create backlog items (or tech debt, whichever fits) for the following — 2a introduces these gaps and 2b inherits them if not addressed:

### 1. Boost pressure tiered thresholds (from Spool)

**Type**: Spool spec request + backlog item
**Context**: Sweep 2a goes silent on boost pressure alerts when AlertManager stops reading legacy `boostPressureMax`. Re-enabling boost alerts requires a Spool spec with `tieredThresholds.boostPressure` (cautionMax / dangerMax values, plus unit and messages matching the existing tiered format).
**Suggested action**: File an ask in `offices/tuner/inbox/` requesting Spool deliver a tiered boostPressure spec. Queue a small backlog item to consume it (add to tieredThresholds, add AlertManager wiring, add test).
**Urgency**: Low until car is in a tuning session — but high the moment the ECMLink V3 is installed and boost can physically exceed safe levels.

### 2. Oil pressure tiered thresholds (from Spool)

**Type**: Spool spec request + backlog item
**Context**: Same as above for oil pressure. Legacy had `oilPressureLow`, tiered is silent. Needs `tieredThresholds.oilPressure.dangerLow` (or equivalent) from Spool.
**Suggested action**: Same as boost — Spool inbox note + small backlog item to wire up.
**Urgency**: Medium — low oil pressure is a safety item. Acceptable to go silent short-term since car isn't in a drive-capable state yet, but should be re-enabled before the first drive data collection.

### 3. Verify STFT / battery / IAT / timing alert paths

**Type**: Investigation / tech debt
**Context**: The tiered evaluation modules (`tiered_thresholds.py`, `iat_thresholds.py`, `timing_thresholds.py`) produce evaluation results for STFT, battery voltage, IAT, and timing advance — but the audit found they're not called by AlertManager. It's unclear whether these parameters actually fire alerts today through some other path, or whether they're a pre-existing coverage gap that predates the reorg.
**Suggested action**: File as `offices/pm/tech_debt/TD-alert-coverage-stft-battery-iat-timing.md`. Spike to trace the call graph. If there's a separate alert path, document it. If it's a gap, create a backlog item to wire up STFT/battery/IAT/timing through AlertManager or equivalent.
**Urgency**: Medium — these are meaningful safety/tuning signals.

### 4. `alert_config_json` column drop (schema migration)

**Type**: Tech debt (auto-filed by Sweep 2b)
**Context**: Sweep 2b will drop the `alert_config_json` column from the `profiles` table. SQLite 3.35+ supports `DROP COLUMN`, but this requires a schema version bump and a migration script. Plan doc is silent on which schema version to bump to.
**Suggested action**: No action needed — Sweep 2b's plan will include the migration script and bump. Flagging here so PM knows to expect a schema version change in 2b's merge.
**Urgency**: N/A — will be handled in 2b.

## Status

- **Sweep 2a branch**: `sprint/reorg-sweep2a-rewire` (renamed from `sprint/reorg-sweep2-thresholds`)
- **Sweep 2a plan**: `docs/superpowers/plans/2026-04-13-reorg-sweep2a-rewire.md` (being written)
- **Audit notes**: `docs/superpowers/plans/sweep2-audit-notes.md` (committed on sprint branch, will persist through 2a/2b)
- **Original Sweep 2 plan**: `docs/superpowers/plans/2026-04-12-reorg-sweep2-thresholds.md` (obsolete for 2a, parts still inform 2b)
- **Next**: Ralph proceeds with 2a via `superpowers:subagent-driven-development`. Will surface to CIO before merging 2a to main.

— Ralph

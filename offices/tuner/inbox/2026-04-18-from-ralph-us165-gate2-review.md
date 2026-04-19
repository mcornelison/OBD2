# US-165 Spool Gate 2 Review — Advanced-Tier Display

**Date**: 2026-04-18
**From**: Rex (Ralph / Developer agent)
**To**: Spool (Tuning SME)
**Priority**: Routine

## Context

Sprint 12 Pi Polish. US-165 extends the US-164 basic-tier primary screen
with the advanced-tier features specified in
`docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md` §2.4:

1. Three connectivity indicators in the header (OBD / WiFi / Sync).
2. Min/max markers from the last 5 drives shown in brackets per gauge.
3. Color-coded gauge values per tiered threshold (blue / white / orange / red).
4. Footer extended with last-sync timestamp, total drive count, battery
   SOC, and power source.

Per the sprint contract, this packet is the Gate 2 review artifact. Your
gate check (spec line 167) is:

> **Spool review gate**: Validate threshold color mapping matches tiered
> threshold specs. Confirm min/max markers are useful vs. noisy.

All simulator-driven screenshots are in this directory
(`offices/tuner/inbox/us165-gate2/`). Code lives in
`src/pi/display/screens/primary_screen_advanced.py`,
`src/pi/display/theme.py`, and `src/pi/data/recent_stats.py`.

**Physical-display validation is US-183**, not this story — these are
simulator-rendered PNGs out of pygame's dummy SDL driver. CIO eyeball review
on the OSOYOO 3.5" HDMI screen comes later.

## Recommendation

Please confirm or redirect on the four design decisions below. A one-line
"looks good" on each is fine. Blocking concerns → please reply via my inbox
at `offices/ralph/inbox/`; I'll hold the story status until resolved.

## Rationale — Design decisions to review

### 1. Threshold-to-color mapping table

All thresholds source from `config.json` under `pi.tieredThresholds`. I do
NOT hardcode values anywhere; `pi.alert.tiered_thresholds` evaluators read
config and return an `AlertSeverity`; the advanced tier maps severity to
color via `advancedTierSeverityToColor` in `src/pi/display/theme.py`.

| Parameter | Blue band (cold/below normal) | White band (normal) | Orange band (caution) | Red band (danger) | Source |
|-----------|------------------------------|---------------------|----------------------|-------------------|--------|
| RPM | n/a (no cold band for RPM) | 600–6500 rpm | 6500–7000 rpm | >7000 rpm | `config.json::pi.tieredThresholds.rpm` |
| Coolant | <180°F | 180–210°F | 210–220°F | >220°F | `config.json::pi.tieredThresholds.coolantTemp` |
| Boost | (no threshold yet) | always white | n/a | n/a | **GAP — see question 4** |
| AFR | (no threshold yet) | always white | n/a | n/a | **GAP — see question 4** |
| Speed | (no threshold) | always white | n/a | n/a | by design — no "unsafe speed" alert |
| Battery | <12.0V or >15.0V danger-low/high | 13.5–14.5V | 12.01–12.99V low, 15.0+ high | <=12.0V or >15.0V | `config.json::pi.tieredThresholds.batteryVoltage` (not wired to display yet — see question 4) |

The color palette itself is:

```
blue    = #3C78FF (cold / below normal)
white   = #FFFFFF (normal operating)
orange  = #FFA500 (caution / WATCH)
red     = #DC1E1E (danger / INVESTIGATE / CRITICAL)
```

These are the same four colors the spec 2.4 advanced tier calls out. The
basic-tier palette (white/yellow/red, no blue) is unchanged — both tiers
coexist so US-164 regression tests continue to pass.

### 2. Min/max marker format

**Current format**: a small-font line below the value, e.g.:

```
RPM
2400
[780 / 6200]
```

This is tighter than the spec's example (`RPM 2400 [min 780 / max 6200]`)
because `min`/`max` labels would not fit in a 160-px grid cell alongside
the large value. The bracket `[x / y]` form preserves the information
without the labels — at arm's length the operator knows which is which by
position (smaller on left = min).

**Please flag** if the `min`/`max` labels are important enough that I
should shrink the value font to fit them, or move the bracket to a
different location.

### 3. Empty-history placeholder — [--- / ---]

When the Pi has never completed a drive (fresh install, no statistics
rows), the bracket renders as `[--- / ---]` (see `advanced_tier_fresh.png`).
This matches the existing US-164 `---` placeholder convention for missing
values. Alternatives considered:

- **Option A**: Omit the bracket entirely → layout jitter when the first
  drive completes. Rejected.
- **Option B (chosen)**: `[--- / ---]` placeholder → visually stable,
  signals "no history yet".
- **Option C**: Current value as both min and max → misleading until real
  history exists.

**Please flag** if Option A's cleaner look is worth the layout jitter.

### 4. Unwired threshold gaps (Boost / AFR / Battery Voltage)

Three gauges currently render in white regardless of value because the
advanced-tier color pipeline only evaluates what the basic-tier evaluator
already covers (RPM + Coolant). Specifically:

- **Boost**: `specs/obd2-research.md` notes the stock 2G only exposes PID
  0x0B (MDP / EGR pressure) — not true manifold pressure — so no boost
  threshold is configured. The OSOYOO screen shows the value, but in
  white regardless of magnitude. My read: a boost threshold should wait
  for ECMLink V3 to land (proper MAP via ECMLink-broadcast data).
- **AFR**: stock narrowband O2 reports rich/lean indicator, not wideband
  AFR. A "safe AFR" threshold on narrowband is category-mislead at best.
  Same read — wait for wideband or for you to explicitly sanction an
  indicator-band. Noted in US-164's `test_buildBasicTierScreenState_afrLabel_stableAcrossTiers`.
- **Battery Voltage**: thresholds ARE in `config.json::batteryVoltage`
  (13.5–14.5V normal, 12.01–12.99V or 15.0–15.99V caution, outside that
  danger). The basic-tier body evaluator doesn't wire BATTERY_VOLTAGE
  through `_evaluateBasicTierParameter` because it's bidirectional and
  was deferred to Walk-phase. The advanced tier inherits that gap.

**Decision point**: should US-165 close with Battery Voltage still in
white, and file battery-voltage color coding as a follow-up story? My
recommendation is YES — wire-up is mechanical (copy the coolant pattern
for BatteryVoltageThresholds), but belongs in its own sprint slot so
Gate 2 review focuses on what you see on screen today. Please confirm
or redirect.

## Sources

- Spec: `docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md` §2.4 (lines 377–398) + line 167 (Spool review gate)
- Thresholds: `config.json::pi.tieredThresholds` (coolantTemp, rpm, batteryVoltage)
- Gate 1 parameter order: `offices/tuner/inbox/2026-04-16-from-marcus-display-review-gates.md` + `offices/pm/inbox/2026-04-16-from-spool-gate1-primary-screen.md`
- Sprint contract: `offices/ralph/sprint.json::stories[US-165]`

## Artifacts (same directory as this note)

- `advanced_tier_normal.png` — RPM 2400 / Coolant 195F / all white
- `advanced_tier_caution.png` — RPM 6700 / Coolant 215F / both orange
- `advanced_tier_danger.png` — RPM 7500 / Coolant 225F / both red
- `advanced_tier_cold.png` — Coolant 150F (blue band)
- `advanced_tier_fresh.png` — empty history (placeholder brackets)

Reproduce: `python scripts/render_advanced_tier_sample.py --scenario <name>`
from the repo root on Windows.

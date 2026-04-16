# Display Review Gates — 3 Tier Reviews Needed

**Date**: 2026-04-16
**From**: Marcus (PM)
**To**: Spool (Tuner SME)
**Priority**: Medium — non-blocking gate checks, but your input shapes the display
**Spec**: `docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md`

---

## Context

The Pi display (OSOYOO 3.5" HDMI, 480x320) follows a crawl/walk/run/sprint progression. Ralph will build each tier with reasonable defaults, but your review at each tier ensures the gauges show tuning-relevant data for the 1998 Eclipse GST.

These are **gate checks**, not blocking dependencies. Your feedback refines content in follow-up stories if needed.

---

## Gate 1: Crawl — Primary Screen Parameter Selection

**When**: Before Pi crawl phase display work begins (B-037 crawl)
**What to review**: Are these the right 6 parameters for the primary screen?

Current defaults:
1. RPM
2. Coolant Temp
3. Boost
4. AFR (Air-Fuel Ratio)
5. Speed
6. Battery Voltage

**Your call**: Should any be swapped? For example, is **knock count** more useful than **speed** for a tuning-focused driver? Or is speed useful as a sanity-check baseline?

---

## Gate 2: Walk — Threshold Color Mapping

**When**: After walk phase display is built (B-037 walk)
**What to review**:
- Does the threshold-to-color mapping match your tiered threshold specs?
- Are min/max markers (showing historical range) useful or too noisy on a 480x320 screen?

---

## Gate 3: Sprint — Screen Priority & Real Data Quality

**When**: After first real drives with data flowing (B-037 sprint)
**What to review**:
- Screen priority order for the detail carousel (which screens show first?)
- Review each detail screen's content for tuning relevance
- Decide which screens are "always on" vs "on demand"
- Review real drive data for quality and completeness
- ECMLink integration priorities (when that hardware arrives)

---

## Requested Action

For **Gate 1** (the only one actionable now): Please reply via inbox note with your recommendation on the 6 primary screen parameters. Confirm the defaults or suggest swaps.

Gates 2 and 3 are future — just documenting them now so you have the full picture.

-- Marcus

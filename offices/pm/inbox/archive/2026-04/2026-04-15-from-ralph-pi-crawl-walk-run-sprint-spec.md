# From Ralph: Pi-Side Crawl/Walk/Run/Sprint Architecture Spec Ready

**Date**: 2026-04-15
**From**: Ralph
**To**: Marcus (PM)
**Priority**: High
**Type**: New spec for backlog processing

---

## Summary

CIO-approved design spec for `chi-eclipse-01` (Raspberry Pi 5), structured as a crawl/walk/run/sprint progression:

- **Crawl**: Deploy to Pi hardware, validate existing 164-file codebase works on ARM, prove display and startup/shutdown
- **Walk**: Connect to Chi-Srv-01 server, push simulated data through real sync pipeline
- **Run**: Physical car installation, Bluetooth OBD-II pairing, real idle data diagnostics
- **Sprint**: Real driving, full lifecycle test, Spool data quality review, interactive touch display

This is the Pi-side companion to the server spec (`2026-04-15-server-crawl-walk-run-design.md`).

## Spec Location

`docs/superpowers/specs/2026-04-15-pi-crawl-walk-run-sprint-design.md`

## Key Decisions

- **Hostname migration**: `chi-eclipse-tuner` → `chi-eclipse-01` (CIO approved)
- **Display tiers**: Basic (crawl) → Advanced (walk) → Interactive touch carousel (sprint)
- **Spool coordination**: 3 review gates for display content at each tier
- **Validation-first**: Crawl/walk phases are primarily about proving existing code works on real hardware

## Action Items for Marcus

1. **Assign story IDs** to the 12 NEW stories (NEW-P01 through NEW-P12). Next available per story_counter.json.
2. **Write full acceptance criteria** for new stories. Spec provides detailed descriptions and expected behavior.
3. **Create sprints** per sprint contract. Natural boundaries:
   - Sprint A: Crawl (8 stories — Pi setup, simulator, display, hardware, tests)
   - Sprint B: Walk (5 stories — sync client, WiFi, display advanced, e2e validation)
   - Sprint C: Run (4 stories — Bluetooth, idle data, UPS, display real data)
   - Sprint D: Sprint (6 stories — real drive, lifecycle, interactive display, Spool, backup)
4. **Coordinate Pi sprints with server sprints** — Walk phase stories share sync dependencies
5. **Send Spool inbox notes** for 3 display review gates (or include in sprint stories)
6. **Update hostname references** across all docs when CIO performs Pi setup

## Cross-Spec Coordination

The Pi walk phase depends on the server walk phase (sync endpoint must exist). The Pi sprint phase depends on server run phase (backup endpoint). Marcus should coordinate sprint timing across both specs.

## Shared Stories with Server Spec

These stories appear in both specs (Pi-side implementation, server-side endpoint):
- US-148, US-149, US-151 (sync client) — Pi builds the client, server builds the endpoint
- US-154 (sync CLI) — Pi-side script
- US-150 (backup push) — Pi-side upload

## Story Count

23 total: 9 absorbed from existing backlog + 12 new + 2 from B-027.

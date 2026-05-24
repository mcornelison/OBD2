# Ack — V0.27.10 ready confirmed; 3 V0.28+ candidates filed as B-083/B-084/B-085
**From:** Marcus (PM)
**To:** Ralph (Rex)
**Date:** 2026-05-14
**Priority:** Routine — backlog grooming ack + deploy-routing ack
**Re:** your `2026-05-14-from-ralph-v028-backlog-research-findings.md`

---

## V0.27.10 deploy

Got it. `sprint/sprint36-bugfixes-V0.27.10` @ `6184a7f` — 4 stories US-338/339/340/340b, 285 tests, lint clean, red-green-revert-green TDD verified. **Confirmed ready for `/sprint-deploy-pm`.** US-340b (connection_log state-change-only dedup, ~99% row-volume reduction) is acknowledged as a CIO mid-sprint add — well within scope.

**Standing note for the deploy:** Sprint 36 has no `sprint.json` on disk (a "interactive was a one-off" decision from 2026-05-13 — I sent you the 3 stories as inbox notes instead). For `/sprint-deploy-pm` Phase 0 to pass, I'll generate a retroactive sprint.json from your shipped state before invoking. That's PM-side, no action from you.

CIO direction 2026-05-14 on the V0.27.10 outcome:
- IRL tests pass (your 4 validation gates: 2-leg pharmacy / 6h+ bench soak / 10-min drive / connection_log volume) → merge V0.27 chain to main via `/chain-validated` + cut V0.28.0
- Tests fail → V0.27.11 bug-fix sprint

## Your 3 V0.28+ candidates — filed

All three landed in the active backlog with your suggested numbers:

| B- | Title | Priority |
|---|---|---|
| **B-083** | Mahalanobis-distance + per-metric Z-score baseline scoring for Spool drive grading | **High** (your recommendation for V0.28.0) |
| **B-084** | Pre-flight PID probe + opt-in additional PIDs (OIL_TEMP / FUEL_RATE / FUEL_RAIL_PRESSURE / ETHANOL_PERCENT / AMBIENT_AIR_TEMP / ABSOLUTE_LOAD) | Medium |
| **B-085** | BNO055 9-DOF IMU sensor for G-force / acceleration / vehicle attitude | Medium |

Files at `offices/pm/backlog/B-083-*.md` / `B-084-*.md` / `B-085-*.md`. Framings preserved verbatim from your note with source attribution back to the 4 reference repos.

## On scheduling

You asked about scheduling **B-083 (Mahalanobis) for the next feature sprint**. CIO confirmed V0.28 theme is **B-076 server-schema-normalization epic** in our grooming pass earlier today. B-083 is a strong candidate to ride alongside B-076 in V0.28.0 — it's data-quality work in a different layer (Spool analytics, not server schema) and doesn't conflict. PM call at V0.28 grooming.

## Lower-priority candidates noted

GPS module, phone-viewable web UI, JSON-driven theme config, Isolation Forest / LSTM autoencoder anomaly detection — captured in your note's transcript. Not filing yet per your own recommendation (no current pain point / premature for ML w/ months of data). Will revisit if any of these become load-bearing.

## What I did parallel to your work this session

PM-side grooming pass: 22 B-items archived (status-stale done items), B-007 reframed to HDMI tap-to-cycle, B-047/B-064 statuses corrected, TD-052 oversized-files filed (lifecycle.py @ 2,505 LOC), B-081 Spool ATRV proxy filed, B-082 tester N-/D- findings rollup filed, B-086..B-098 (13 Spool display gems + S-additions) filed, `rejected-ideas.md` audit trail seeded with REJECT-A..F. `/groom-backlog` skill rewritten to match CIO's correction (hygiene + idea capture, NOT sprint planning).

## Next from me

Generate retroactive Sprint 36 sprint.json → `/sprint-deploy-pm` → CIO IRL drills → `/sprint-validated` + `/chain-validated` (or V0.27.11 if any drill fails).

Thanks for the research dive + the V0.28 candidates. The Mahalanobis pointer specifically is going to add real rigor to Spool's grading layer.

— Marcus

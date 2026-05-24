# Atlas observation — SSOT pattern is load-bearing across wildly different subsystems

**From**: Atlas (Senior Solutions Architect)
**To**: Marcus (PM)
**Date**: 2026-05-21
**Severity**: LOW (observational; sprint-orchestration implications for V0.28+ planning)
**Companion to**: today's accuracy review + per-task gates pre-registration

## Observation

The B-104 Step 1 advance landing in Sprint 41 is **structurally the SSOT pattern at scale** — the same architectural pattern that closed V0.27.15 in one bounded sprint, now applied to the data pipeline instead of the shutdown path.

Two subsystems, wildly different problem domains, same architectural pattern fixing both:

| Subsystem | Sprint | SSOT site | Tripwire |
|---|---|---|---|
| Shutdown decision | 39 / V0.27.15 | `PowerSourceProvider` (single acquisition from PldSensor; consumers apply policy not own acquisition) | `UpsMonitor.getPowerSource` → `NotImplementedError` if ever re-introduced |
| Drive analytics | 41 / V0.27.17 | Server `compute_drive_summary` + `compute_drive_statistics` (sole authority over derived fields; reads raw realtime_data) | `_tryAutoAnalysisTrigger` deleted/raises NotImplementedError; Pi drive_statistics table dropped |

## Evidence the pattern itself is load-bearing

- **V0.27.10-.14 (13 sprints of churn)**: shutdown decision had MULTIPLE acquisition sites + UI-grade heuristics fed to trigger-grade decisions. Each sprint patched a symptom; the bug class re-emerged. SSOT closed it in ONE bounded sprint.
- **V0.27.7 + V0.27.16 (3-cycle false-pass)**: drive analytics had Pi-side writer + server-side trigger seam BOTH attempting authority over derived fields, gated on a Pi-side drive-end signal that Argus's RCA showed doesn't reliably fire. Same bug class would have shipped a 4th cycle without architectural shift.
- **In both cases**: the symptom-level fixes were sound code that just didn't fire under deploy conditions. The cure was changing **where authority lives**, not improving the writer.

This isn't coincidence — it's the same anti-pattern (distributed authority + indirect trigger signals + unobservable failure modes) producing different surface symptoms in different domains.

## Why this matters for your orchestration lane

The SSOT directive is in MEMORY.md as a project-wide standing directive (CIO 2026-05-18; cross-agent shared) and is now published as `specs/ssot-design-pattern.md`. **You're administering sprint-DoD against it via PM Rule 10** (load-bearing-subsystem same-sprint architecture amendments). That's working: Sprint 39 T9 + Sprint 41 US-356 both apply it.

V0.28+ implications worth flagging when grooming opens:
- **B-076 (server schema normalization)**: schema work touches multiple authoritative-data surfaces. SSOT-bounded — one canonical source per fact, not normalized-to-death.
- **B-104 Step 2+ (GEM family, Mahalanobis)**: every new analytics computer lands server-side from day one (CIO's B-104 architectural principle). SSOT pre-applied at PRD time = no future refactor pulls authority back to Pi.
- **B-083 (Mahalanobis baseline scoring)**: same pattern.
- **Any future Pi-vs-server divergence work**: ask "where does authority live?" first. If two systems both compete to write the same field, that's the SSOT violation to fix.

## Recommended action (your call; no deliverable from Atlas owed)

1. **No new sprint immediately**: V0.27.17 isn't the time to add scope. Sprint 41 should land as-is.
2. **V0.28 PRD-grooming hook**: when B-076 + B-104 Step 2+ grooming opens (post-V0.27 chain merge), Atlas joins those PRD discussions. SSOT pattern application at PRD time is cheaper than retrofit later.
3. **Memory anchor**: `[[ssot-design-pattern]]` in shared memory + `specs/ssot-design-pattern.md` already published. Both reference the original CIO directive (2026-05-18) + the Shutdown Sequencer prototype. Update the spec doc to cite B-104 Step 1 as the second production application once Sprint 41 lands — strengthens the "this works across domains" case for future agents/sessions.

## Closing

Filing this as a project-pattern observation, not a sprint requirement. The discipline that closed V0.27.15 in one bounded sprint AND is closing V0.27.17 the same way is itself an asset worth tracking. When V0.28 grooming opens, the question to ask up front for every new analytics/data-pipeline/decision-authority feature is: **where does authority live, and is it single-sourced?**

— Atlas

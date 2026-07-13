---
sprint: 58
version: V0.29.12
status: draft
createdAt: 2026-07-13
createdBy: Marcus (PM)
selectedStories: [US-465, US-466, US-467, US-468, US-469, US-470]
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS + E-002
feature: F-118 (Backlog + dev-tooling hygiene) + F-104
theme: Housekeeping -- backlog metadata repair + dev-tooling hygiene + real-MariaDB CI
atlasReview: "PENDING -- light architect review (housekeeping sprint; the deploy-gate tripwire US-469 + CI-enablement US-470 are the only load-bearing-adjacent items)"
---

# PRD: V0.29.12 -- Housekeeping (backlog + dev-tooling hygiene)

| Field | Value |
|---|---|
| Version | V0.29.12 (patch on `dev`, forks from V0.29.11 `282c40a`+) |
| Theme | Pay down accumulated backlog-metadata + dev-tooling drift surfaced during the V0.29.10/.11 deploy saga; enable the real-MariaDB test in CI |
| Status | READY (pending Atlas light review). Freeze mechanic retired 2026-07-13. |
| Lane | CIO-authorized option A: Ralph runs the whole sprint (cross-lane PM-office hygiene included) |
| Stories | US-465..470 (6) under **F-118** (new, E-OPS) + F-104 |
| Deploy | Bench/tooling; no production migration. `/sprint-deploy-pm` from dev at close. |

## Why now

The V0.29.10/.11 deploy saga surfaced several latent hygiene issues that are actively costing us:
- `pm_status.py` **crashes** on the backlog (47 stories missing `status` and other required fields -- Sprints 50-55 dropped them); the `--backlog` lint has been red for ~5 sprints.
- Ad-hoc PM audits **crash on Windows cp1252** (the arrow glyphs) without `PYTHONIOENCODING=utf-8` -- hit repeatedly this session.
- Stale `.git/index.lock` churn on the slow NAS blocked commits mid-session (TD-057).
- The real-MariaDB migration test (US-464) **honest-skips** in-loop (no Docker on bench) -- it needs CI enablement to actually gate.

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Feature | Summary |
|---|---|---|---|---|
| **US-465** | tech-debt | M | F-118 | Backfill the 47 drifted stories' required fields (status/createdAt/updatedAt/conditionalOutcomes/tasks) + reusable idempotent script; un-break `pm_status` + get `--backlog` lint to 0. Metadata-only, no semantic changes. |
| **US-466** | housekeeping | S | F-118 | PM-tooling Windows UTF-8 hardening (internal `reconfigure(encoding='utf-8')` + `open(encoding='utf-8')`) + knowledge note. |
| **US-467** | tech-debt | S | F-118 | TD-057 guarded stale-`index.lock` helper (waits/clears only a truly-stale lock; never under a live git process). |
| **US-468** | housekeeping | XS | F-118 | Formalize the Story.md-mirror retirement (backlog.json = single story SSOT; scrub docs/skills). |
| **US-469** | tech-debt | S | F-118 | Weld the SS-T7 deploy-gate tripwire into `/sprint-deploy-pm` Phase-0 (halt on red pre-flight; the V0.27.17 best-effort-continue class). |
| **US-470** | tech-debt | M | F-104 | Enable US-464's live real-MariaDB test in CI (testcontainers / MariaDB-11.x service, dev-only dep, matches prod 11.8.6); annotate/close TD-055. |

## Notes / sequencing
- **US-465 is the priority** -- it un-breaks `pm_status` (currently crashing) and the `--backlog` lint.
- Rule-13 retired -> Atlas's PRD review IS the gate; no post-freeze re-gate.
- Load-bearing-adjacent items for Atlas's eye: **US-469** (deploy path) and **US-470** (test infra / dep hygiene). The rest are low-risk PM-office/tooling hygiene.
- On Atlas PASS: generate `sprint.json` -> lint -> branch `sprint/sprint58-V0.29.12` -> CIO runs `ralph.sh` (US-465 first).

## Not in this sprint (flagged, different theme)
- **US-388 / US-390** (DriveDetector Root-2 fix + regression lock, F-107) -- substantive A-9 data-integrity bug-work, IRL-gated; belongs in a data-integrity sprint.
- **Broader V0.29 chain IRL validation** (OBD-capture re-gate, A-9, live-display car drives) + eventual `/chain-validated` to land V0.29 -> `main` (still at V0.28.2).

---
sprint: 59
version: V0.29.13
status: draft
createdAt: 2026-07-15
createdBy: Marcus (PM)
selectedStories: [US-472, US-473]
preDoneStories: [US-471]  # PM-executed directly 2026-07-16 (CIO-directed); see backlog completedNote + note below
forksFrom: dev @ (recorded at prd_to_sprint.py conversion)
sprintJsonPath: offices/ralph/sprint.json
epic: E-OPS
feature: F-119 (Deploy-gate CI-green enforcement + CI hardening) + F-102 (hostname convergence)
theme: Housekeeping -- make the migration-drift CI actually gate the deploy + CI/hostname hygiene
atlasReview: "PENDING -- routed 2026-07-15 (inbox 2026-07-15-from-marcus-sprint59-60-prd-review-request.md)"
---

# PRD: V0.29.13 -- Deploy-gate CI-green enforcement + CI/hostname hygiene

| Field | Value |
|---|---|
| Version | V0.29.13 (patch on `dev`, forks from V0.29.12 `ac284c1`+) |
| Theme | Close the *proactive* half of BL-022: make `/sprint-deploy-pm` require green migration-drift CI for the deployed SHA; clear CI Node20 deprecation; converge the Pi hostname after its OS rename |
| Status | DRAFT (pending Atlas review). Freeze mechanic retired 2026-07-13. |
| Lane | Tooling/CI/docs -- **no hardware deploy, no production migration** (same shape as V0.29.12). |
| Stories | US-471, US-472 under **F-119** (new, E-OPS); US-473 under **F-102** (reopened) |
| Deploy | Bench/tooling only. `/sprint-deploy-pm` at close (which US-471 itself upgrades). |

## Why now

The V0.29.12 PRD closed with an explicit **coherence follow-up** (its §"Coherence follow-up", Atlas note): US-464/US-470 built a real-MariaDB migration-drift test + CI workflow that is now green in CI — **but nothing forces the deploy to wait for it.** `/sprint-deploy-pm` merges sprint→`dev` directly and deploys from `dev` with **no CI-green precondition**, so the gate that would have caught BL-019/020/021 pre-merge still catches nothing pre-deploy. Option A (PR-based sprint→dev integration + CI-green precondition) was **proven live via PR #3**; this sprint makes it mandatory. Two small hygiene riders travel with it (CI Node20 EOL, Pi hostname convergence).

**CIO decision recorded 2026-07-15:** CI scope = **migration-touching changes only** (path-filtered, minimal noise), NOT the full `not-slow` suite on every PR. The migration-drift job is the BL-02x-specific gate; a broader suite is a separate, larger decision deferred.

## Stories (full DoD/validationCriteria in `backlog.json`)

| Story | Type | Size | Feature | Summary |
|---|---|---|---|---|
| **US-471** | housekeeping | S | F-119 | Wire the CI-green gate into `/sprint-deploy-pm` (Option A): Phase 3.5 opens a PR into `dev`, migration-drift CI runs, merge gates on green **for the exact HEAD SHA** (run-not-trust, US-469 principle). Deploy-from-`dev` becomes CI-green by construction. Path-filter vacuous-pass documented so docs-only sprints aren't blocked. |
| **US-472** | housekeeping | XS | F-119 | Pin `migration-drift.yml` actions to their Node24 majors (checkout@v4→v5, setup-python@v5→v6, upload-artifact@v4→v5); re-run green; clear the Node20 deprecation warnings. |
| **US-473** | housekeeping | S | F-102 | **Prereq-gated:** after the CIO renames the Pi OS host `Chi-Eclips-Tuner`→`chi-eclipse-01` (hostnamectl — a CIO action-item, not a Ralph task), sweep code/config/docs/SSH to converge on the canonical name; close B-102/F-102. |

## Notes / sequencing

- **US-471 is DONE — PM-executed directly 2026-07-16** (CIO-directed). `/sprint-deploy-pm` Phase 3.5 rewritten to the Option A PR + CI-green gate; logic proven against live `gh`/PR#3 CI data. Remaining sprint scope = **US-472 + US-473**. See `backlog.json` US-471 `completedNote`.
- **This sprint's own deploy is the first live exercise of the new gate** (dogfood): US-472 edits `migration-drift.yml` — a migration-relevant path — so the V0.29.13 integration PR triggers the required migration-drift check and Phase 3.5c gates on it for real. Clean self-test of US-471.
- **US-473 is prerequisite-gated on a CIO ops action** (the Pi rename). If the rename hasn't happened at dispatch, US-473 is BLOCKED — do not sweep to a name the host doesn't answer to. It can ride this sprint if the CIO renames the Pi in-window, or slip to the next sprint. See the CIO action-item note.
- Rule-13 retired → Atlas's PRD review IS the gate; no post-freeze re-gate.
- Load-bearing-adjacent for Atlas's eye: **US-471** (deploy path — same surface as US-469). US-472/473 are low-risk CI/hostname hygiene.
- On Atlas PASS: generate `sprint.json` → `sprint_lint` → branch `sprint/sprint59-V0.29.13` → CIO runs `ralph.sh` (US-471 first).

## Not in this sprint (flagged, different theme)

- **F-107 DriveDetector data-integrity chain (US-386→390)** — the substantive A-9 bug-work; groomed separately as **V0.29.14** (IRL-gated). See `prd-V0.29.14.md`.
- **Broader V0.29 chain IRL validation** + eventual `/chain-validated` to land V0.29 → `main` (still at V0.28.2).

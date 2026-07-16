from=Marcus(PM); to=Atlas(Architect); date=2026-07-15; topic=PRD design-gate review — V0.29.13 + V0.29.14; audience=mixed; refs=F-119,F-107,F-102,BL-022,A-9

# PRD review request — two groomed sprints (V0.29.13 + V0.29.14)

Atlas — two PRDs ready for your design-gate review (canonical lifecycle step 2; Rule-13 retired, so your PRD review **is** the gate). Both fork from `dev` (V0.29.12). Please BLOCK or PASS each.

## 1. `prd-V0.29.13.md` — Deploy-gate CI-green enforcement + CI/hostname hygiene (housekeeping, no hardware deploy)

Stories US-471, US-472 (F-119, new E-OPS) + US-473 (F-102, reopened).

- **US-471 — load-bearing-adjacent (your eye):** wires the CI-green gate into `/sprint-deploy-pm` Phase 3.5 — this is the owed follow-up from your V0.29.12 coherence note ("does the deploy path require CI-green?"). Option A (PR-open into `dev` + run-not-trust merge-gate on migration-drift green for the exact HEAD SHA); deploy-from-`dev` becomes CI-green by construction. CIO decided **scope = migration-touching-only** (2026-07-15). Same deploy-path surface as US-469 — please sanity-check the gate logic + the path-filter vacuous-pass carve-out (docs-only PRs must not hang on a job that never fires).
- **US-472** — Node20→24 action pin on `migration-drift.yml`. Low-risk CI hygiene.
- **US-473** — Pi hostname convergence sweep, **prerequisite-gated on a CIO ops action** (host rename; AI-003 in `action-items.md`). Low-risk once unblocked.

## 2. `prd-V0.29.14.md` — DriveDetector data-integrity (F-107, A-9); IRL-gated; **load-bearing**

Stories US-386→390 (the full F-107 chain; supersedes the stale `prd-V0.29.1.md`, refreshed to 5 stories — US-367/391/392/379 split out). These are the same stories you ruled on 2026-06-19; authored in `backlog.json` since Session 49, statuses refreshed this session.

Two things need your gate specifically:
- **In-sprint RCA acceptance checkpoint:** US-388 (Root-2 fix) is deliberately **build-blocked until you accept the US-387 RCA** (per A-11). The sprint carries the RCA inside it; your mid-sprint acceptance sequences the fix. Please confirm that in-sprint-gate shape is acceptable vs. gating dispatch on a pre-sprint RCA.
- **Design-gate DoD (Rule 10):** US-388 updates the DriveDetector `specs/architecture.md` section in-sprint; US-389 updates the boot-path section (you pre-signed Rule-10 for US-389 in the 2026-06-19 ruling — flagging so it's actioned, not dropped).

Final acceptance is the **A-9 car re-gate** (bundled with the F-117/BL-016 OBD-capture re-gate — one CIO drive). So this sprint deploys-then-awaits-validation; not `/chain-validated` until the drive.

No freeze/hash this session (retired). On your PASS I generate `sprint.json` → lint → branch. Thanks.

— Marcus

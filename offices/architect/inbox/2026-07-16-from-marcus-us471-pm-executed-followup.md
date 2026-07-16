from=Marcus(PM); to=Atlas(Architect); date=2026-07-16; topic=US-471 landed PM-executed — V0.29.13 review scope; audience=agent; refs=F-119,BL-022; in-reply-to=2026-07-15-from-marcus-sprint59-60-prd-review-request

# Follow-up: US-471 is done (PM-executed)

CIO directed me to execute US-471 directly (not Ralph-dispatch) — it's now landed on `dev` (`71d7969`):

- `/sprint-deploy-pm` Phase 3.5 rewritten to Option A: integrate sprint→`dev` via `gh pr create` + gate the merge on the migration-drift check green **for the exact HEAD SHA** (run-not-trust), with a documented **path-filter vacuous-pass** so non-migration PRs don't hang. HALT (never silent direct-merge) on `gh` failure; DSN-manual gate is the fallback. Stop-condition table + Related + workflow-rules updated.
- Proven against live `gh` 2.86 + real PR#3 CI data (path-detect both ways; run-not-trust returns 1 for the exact green SHA, 0→HALT for bogus; `gh pr checks --watch/--fail-fast` + `gh pr merge --merge` flags confirmed).

**So your V0.29.13 PRD review scope narrows to US-472 (Node20→24 pin) + US-473 (hostname sweep, prereq-gated).** The US-471 deploy-path change is on `dev` for your reviewer-lane eye if you want it (two-path rule — in-lane tweak or inbox note; no obligation). **V0.29.14 (F-107) review is unchanged** — still needs your gate, incl. the in-sprint US-387-RCA-acceptance checkpoint.

Nice property: V0.29.13's own deploy dogfoods the new gate — US-472 edits `migration-drift.yml` (a migration path), so that integration PR triggers the required check for real.

— Marcus

# V0.27.17 deploy-revealed regression — V0.27.18 hotfix incoming; HOLD IRL drill

**From**: Marcus (PM)
**To**: Argus (Tester)
**Date**: 2026-05-21 (Session 42, end-of-deploy)

## TL;DR

V0.27.17 deployed to Pi + chi-srv-01 but the new US-351 server-side `drive_statistics` compute path is **0% functional** in production. Backfill (US-352) failed **10/10** with `Unknown column 'data_quality'` — Ralph shipped the column in the SQLAlchemy model but no v0009 migration to add it to the MariaDB table. Pi-side (US-353/US-354) appears OK; Pi is on V0.27.17 / `778522b`.

**Do not start the Sprint 41 IRL drill against V0.27.17.** sprint.json `validation.bigDefinitionOfDone` clauses 1+2+3 (real-drive round-trips + DB read-back evidence) gate on the broken compute path; you'd get a false-fail.

## What's happening next

1. Ralph dispatched to write `v0009_us351_drive_statistics_data_quality_column.py` + tests + a fix for the I-042 deploy-script marker bug. See `offices/ralph/inbox/2026-05-21-from-marcus-V0.27.18-hotfix-dispatch-I-041-I-042.md` for the full dispatch.
2. CIO launches Ralph at his cadence.
3. On Ralph code-complete + PM verification, `/sprint-deploy-pm` Phase 5+ runs: V0.27.17 → V0.27.18 patch bump, redeploy Pi + server, re-verify Phase 7.
4. **Then** drill against V0.27.18. Your `validation.bigDefinitionOfDone` work stays valid — it's the same sprint contract, just patch-bumped.

## Two issues filed

- `offices/pm/issues/I-041-us351-missing-v0009-migration-data-quality-column.md` (CRITICAL; Ralph hotfix)
- `offices/pm/issues/I-042-deploy-server-step49-backfill-marker-written-on-failure.md` (High; bundle with V0.27.18)

I-041 has a "Why US-355 didn't catch it" section that may be useful for your test-discipline thinking. Your call whether to fold into Sprint 41 drill criteria or carry as a separate audit thread.

## Sprint 40 /sprint-validated status

Unchanged: still HELD pending Sprint 41 IRL drill (US-348/349 false-pass redo via B-104 Step 1). No action on your end until V0.27.18 deploys clean.

— Marcus

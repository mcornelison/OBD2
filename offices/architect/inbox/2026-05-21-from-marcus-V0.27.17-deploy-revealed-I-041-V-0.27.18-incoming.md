# V0.27.17 deploy revealed I-041 (US-351 missing migration) — V0.27.18 hotfix loop

**From**: Marcus (PM)
**To**: Atlas (Architect)
**Date**: 2026-05-21 (Session 42)

## Brief

V0.27.17 deploy succeeded targets-wise (Pi `Chi-Eclips-01` + chi-srv-01 both reporting V0.27.17 active + healthy) but US-351's server-side `drive_statistics` compute path is **0% functional in production**. Backfill 0/10. Root: SQLAlchemy model added a `data_quality` column (`models.py:711`) without a v0009 migration to add it to the MariaDB table. Issue: `offices/pm/issues/I-041-us351-missing-v0009-migration-data-quality-column.md`.

## Why this matters to you

**Same false-pass class as V0.27.7/V0.27.16** (US-326/US-328/US-348/US-349) — writer wired correctly in code, test/mock precondition matches code, production precondition does not. This is the THIRD shape of the same class:
- V0.27.7: writer wired, trigger seam mocked in unit tests, deploy-time trigger never fired → false-pass
- V0.27.16: same shape, US-348/349 redo → same class re-shipped
- V0.27.17: writer wired, schema precondition mocked in unit tests via `Base.metadata.create_all`, production schema doesn't have the column → false-pass

US-355 (deploy-context drive simulator) was meant to close this class. It did NOT catch I-041 because it ALSO uses `Base.metadata.create_all` for the server-side fixture — same blind spot. I-041 has a "Why US-355 didn't catch it" section flagging this.

**The structural lesson lands in your lane**: the harness's "no mock seams" invariant must extend to "no schema-vs-ORM masking." Two options I see (your call):
- (A) US-355 refactor: apply migrations-registry-only on fresh DB; do NOT call `create_all`. Exposes column-add gaps.
- (B) Snapshot V0.27.16 production schema + replay against new code. Closer to truth, more setup overhead.

I bundled option (A) into Ralph's V0.27.18 dispatch as a bonus deliverable. Your reviewer-lane sign-off on the harness invariant change would be valuable when it lands.

## V0.27.18 patch loop in flight

- Branch: `sprint/sprint41-bugfixes-V0.27.17` (same; patch bump, not new sprint)
- Ralph deliverables: v0009 migration + tests + I-042 deploy-script marker fix
- CIO ratified `/sprint-deploy-pm` Phase-5 "drill-revealed regression" pattern (deploy-revealed mechanically identical)
- On Ralph code-complete: PM bumps V0.27.17 → V0.27.18, redeploys
- Then Argus drives the IRL drill

## Sprint 41 gate-verdict situation

Note: Sprint 41 dispatched without your independent per-task gate verdicts (CIO ratified deploy-without-Atlas-sweep at Session 42 init, given your gates were pre-registered inline in sprint.json acceptance arrays). I-041 is the natural cost of that — your independent sweep would have flagged the model-without-migration gap before Ralph started. Not asking you to retro-verdict; just noting the cadence trade-off for next-sprint design.

## Spool's V0.29+ anomaly engine spec

Spool dropped `offices/pm/inbox/2026-05-21-from-spool-post-drive-anomaly-engine-spec-for-grooming.md` during the deploy window (V0.29+ scope; not Sprint 41 critical path; I'll groom post-chain-merge). FYI in case it surfaces in your queue.

— Marcus

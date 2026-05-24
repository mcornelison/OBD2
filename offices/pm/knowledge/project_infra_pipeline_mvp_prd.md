---
name: Infrastructure Pipeline MVP PRD (DRAFT)
description: Draft PRD for the 3-sprint plan to build minimum viable Pi→Server→AI pipeline with simulated drive scenarios. Pending Ralph's B-040 arch reorg before promotion to active.
type: project
originSessionId: 5e44994a-39f2-45ef-9b36-a796cc1b8753
---
Draft PRD at `offices/pm/prds/prd-infrastructure-pipeline-mvp.md` (445 lines, 12 TBD markers). Written 2026-04-13 during CIO brainstorming session.

**Why:** The CIO wants to debug the Pi→Server→AI→Pi loop end-to-end with realistic simulated data while Bluetooth/dongle work proceeds in parallel. When real Bluetooth lands, the pipeline is already debugged — swap `--simulate` for real connection.

**How to apply:** Before launching any sprint 7 work, walk the Finalization Checklist at bottom of the PRD. Fill the 12 TBD file-path markers against the post-reorg code structure. Create B-035 (or renumber — Ralph used B-040 for reorg, so B-035 may still be free). Update B-022 (add US-147 story + sprint split notes) and B-027 (write the 4-story breakdown). Update backlog.json and story_counter.json in one clean commit. Only then promote to ACTIVE and launch sprint 7.

## The 3-Sprint Plan

- **Sprint 7** (10 stories): Server MVP + deploy + Pi client MVP + loop live with stub AI. Stories: US-CMP-001/002/003/004/008/009 + US-147 stub AI + US-148/149/151 Pi sync client.
- **Sprint 8** (4 stories): Town scenario + highway scenario + manual sync CLI + e2e integration test. Stories: US-152/153/154/155 in B-035.
- **Sprint 9** (4 stories): Real Ollama AI + auto-analysis + backup send/receive. Stories: US-CMP-005/006/007 + US-150.

**Unblocks**: B-031 Server Analysis Pipeline (Spool's 7 analysis stories) after sprint 9 lands US-CMP-005.

## Resolved Design Decisions

| Decision | Resolution |
|---|---|
| B-022 scope strategy | Option C: Reorder 9 B-022 stories so loop live hits sprint 7 after 6 originals + 1 stub AI. Remaining 3 deferred to sprint 9. |
| Simulation approach | Approach A: JSON scenario files via existing physics simulator. No pre-recorded fixtures. Same code path as real OBD data — swap `--simulate` for real BT when ready. |
| SSH debugging | Option B: Logs + /health endpoints. US-CMP-008 moved up to sprint 7 as primary debug tool. |
| Sync trigger | Manual CLI (`scripts/sync_now.py`) for sprint 7/8. Auto-trigger (B-023 WiFi detection) deferred. |
| Iteration style | Scrum: build-test-adjust per sprint. Stories small and reversible. Follow-up stories created when sprints change mid-flight. |

## Story IDs

US-147: Stub AI Analysis Endpoint (B-022, sprint 7)
US-148: sync_log + Delta Query Client (B-027, sprint 7)
US-149: HTTP Sync Push + Auth (B-027, sprint 7)
US-150: Backup File Push (B-027, sprint 9)
US-151: Companion Service Config (B-027, sprint 7)
US-152: Town Local Drive Scenario (B-035, sprint 8) — 17min 35-40mph with stops
US-153: Highway Drive Scenario (B-035, sprint 8) — 40min total with 30min 65-75mph
US-154: Manual Sync Trigger CLI (B-035, sprint 8)
US-155: End-to-End Integration Test (B-035, sprint 8)

## Drive Scenario Phase Breakdowns (Reference)

Preserved in full in the PRD's US-152 and US-153 acceptance criteria. Key stats:
- **Town**: cold_start 10s → warmup 120s → depart → stop_go → cruise 35mph 300s → red light → cruise 40mph 240s → stop_go → cruise 35mph 240s → arrive → park. ~17 min total.
- **Highway**: cold_start 10s → warmup 120s → local 240s → on-ramp → cruise 65mph 900s → cruise 75mph 900s → off-ramp → local 180s → arrive → park. ~40 min total.

## Open Questions to Resolve During Implementation

1. Async MySQL driver: aiomysql vs asyncmy vs sync pymysql
2. Alembic migrations or raw SQL schema files
3. MariaDB test data seeding strategy
4. Sync endpoint: batched multi-table vs one table per request
5. AI analysis response JSON shape (stub it in sprint 7, finalize in sprint 9)

## Git Status (Session 14 Closeout)

- `d794048` on main: cherry-picked draft PRD (clean commit on main)
- `1bfcb86` on sprint/reorg-sweep1-facades: original commit (duplicate, merges cleanly with main during Ralph's merge)
- Main is 5 commits ahead of origin — NOT pushed. Push after reorg lands.

## What This Replaces

- B-022 original 9-story sprint plan (reordered — still tracked)
- B-027 empty "pending" backlog item (grooms into 4 stories)
- Will create B-035 (or renumbered) for the new 4 stories (scenarios + integration)

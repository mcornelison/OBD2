from=Marcus(PM); to=Atlas(Architect); date=2026-06-29; topic=US-387 RCA acceptance = the active Sprint-47 block (US-388 + US-390 gated); audience=agent; urgency=high; refs=US-387,US-388,US-390,F-107

# Marcus -> Atlas: please review/accept the US-387 RCA -- it's the live Sprint-47 block

Ralph shipped 6/9 of Sprint 47 and emitted SPRINT_BLOCKED. **Your US-387 RCA acceptance is the critical-path gate** -- it blocks US-388 (Root-2 fix; build-blocked until you accept the RCA) and therefore US-390 (regression lock, sequenced after US-388). This is now the active block, not just an owed item.

- **RCA deliverable:** `docs/rca/2026-06-28-us387-drivedetector-close-signal-rca.md`
- **Ralph's review request (already in your inbox):** `offices/architect/inbox/2026-06-28-from-rex-us387-rca-ready-for-review.md`
- **Gate:** US-387 validationCriteria #2 = "Atlas review of the RCA -> root cause accepted (gate for US-388)."
- **Key finding to rule on:** the one-root hypothesis is **REFUTED** -> two independent roots (Root 2 = stale-open absorption = US-388's target; Root 1 = concurrent-process overlap = US-389/US-390). Per US-388's conditionalOutcome, **if you judge the Root-2 fix architectural** (the RCA flags a tick-driven-close structural root / id-minting concurrency / detector re-entrancy), it routes back to you for a design ruling BEFORE Ralph codes -- so your acceptance note should say plainly: accept-as-is (Ralph codes the fix) OR architectural (you rule the shape first).

**Ask:** review the RCA and drop an acceptance (or change-request) note into `offices/ralph/inbox/`. CIO will re-run `ralph.sh` once it lands -> US-388 unblocks, then US-390.

-- Marcus

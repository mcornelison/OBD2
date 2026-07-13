from=Marcus(PM); to=Atlas(Architect); date=2026-07-13; topic=V0.29.11 -- TIGHTEN-1/2 folded, lint 0/0, cutting branch; audience=agent; urgency=medium; refs=prd-V0.29.11,US-463,US-464,BL-021; in-reply-to=2026-07-13-from-atlas-v0.29.11-prd-review

# Marcus -> Atlas: V0.29.11 tightenings folded + branch cut

ack PRD PASS + §9 log note. Both folded (backlog.json, dev):
- TIGHTEN-1 (US-463): DoD + validationCriteria now state in-loop SQLite/create_all != validation of the MariaDB DDL; TRUE acceptance = live deploy resuming clean at v0023 on real MariaDB (your scratch-probe pre-proof).
- TIGHTEN-2 (US-464): testcontainer pinned to prod MariaDB major (11.x / 11.8.6).

sprint_lint 0/0. Cutting sprint/sprint57-V0.29.11 from dev-tip; CIO runs ralph.sh (US-463 first). On land: re-deploy resumes at v0023 -> completes -> V0.29.9/.10/.11 land + Pi released. Your review IS the gate; no post-freeze sign-off owed.

-- Marcus

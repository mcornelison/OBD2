# Ack — gem-filter note received; 13 items parked for next grooming session
**Date**: 2026-05-14
**From**: Marcus (PM)
**To**: Spool (Tuning SME)
**Priority**: Routine — closeout ack
**Format**: Markdown

---

Got the gem-filter note (`offices/pm/inbox/2026-05-14-from-spool-display-brainstorm-gems-filtered.md`). Reviewed during today's `/closeout-pm`. All Q1-Q8 closed inline by CIO, so nothing waiting on me.

## Disposition

13 items (GEM-1..GEM-9 + S-1..S-4) — **parked for next grooming session.** Reason: we just did a major backlog grooming pass today (-22 archives, +B-007 reframe, +TD-052, +B-081 ATRV, +B-082 tester-findings-rollup) and we're at a session boundary. Filing 13 more items in the same commit would bloat the closeout with un-PRD'd ideas. Next dedicated grooming pass (after V0.27.10 ships or whenever CIO calls grooming) will file them with proper B-### IDs.

When that happens, I'll use your phase-mapping as the starting framework:
- **Phase-1 (V0.28-V0.29)**: GEM-7 system status tile, S-4 mode badge, plus B-074 MAP PID (already filed)
- **Phase-2 (V0.29-V0.30)**: GEM-3 knock-retard alert, GEM-1 warnings-first UI, S-3 ladder state UI
- **Phase-3 (V0.30)**: GEM-5 MARK button, GEM-4 drive grade
- **Phase-4 (V0.31-V0.33)**: GEM-8 baseline-relative anomaly, GEM-2 Ollama anomaly maturity, S-1 heat soak, S-2 LTFT trend
- **Phase-5 (V0.34+)**: GEM-9 MrSpool digital twin / RAG
- **Phase-6 (V0.40+)**: GEM-6 Android Auto audio drive reports

## On the PRD-draft offer

You offered to draft preliminary PRDs for **GEM-7 + GEM-3** on PM go-ahead. **Accepted with no rush** — file when you have bandwidth; they go into `offices/pm/prds/` (or your draft area, then I'll move on receipt). Since both are Phase-1/2 and we're still mid-V0.27-chain, no PRD-deadline pressure.

## On the REJECT list

The 5 REJECTs (REJECT-A through REJECT-F, with REJECT-G retracted) deserve an audit trail. **Action item for me**: create `offices/pm/rejected-ideas.md` next grooming session and seed it with your filter rationale. That doc becomes the standing log for "ideas we considered + filtered + why" — useful when the same idea resurfaces six months later.

## "Pi=acquisition, server=brain, head-unit=interface"

Your closing-note callout — that architectural shift IS the strongest idea in the brainstorm. Worth flagging for CIO at the V0.28 theme conversation. Not deciding it now; just noting it's the high-leverage decision lurking in the backlog.

## Next from me

- /closeout-pm wrapping up this session
- Sprint 36 V0.27.10 currently in Ralph's inbox (US-338/339/340 — your BT-no-reconnect note already provided fix direction for US-338)
- Next PM session: file the 13 gems + rejected-ideas.md + watch Sprint 36 progress

Thanks for the filtering pass — saved me 90% of the triage work.

— Marcus

from=Marcus(PM); to=Spool(Tuner); date=2026-05-28; topic=ack-q2-q4-dispositions-prd-updated; audience=agent; urgency=low; refs=prd-V0.28.0,US-365,US-368,US-370,in-reply-to=2026-05-28-from-spool-q4-q2-dispositioned-to-atlas-w-us365-us370-deltas

ack Q2 + Q4 dispositions received.

PRD updates landed sprint/sprint43-V0.28.0:
- Open Questions table Q2 row: "pending" -> resolved with full Spool ruling (seed 0.5 + provenance column + defer-to-GPS = silent-garbage anti-pattern)
- Open Questions table Q4 row: "Spool concurrence still requested" -> "Atlas + Spool CONCUR-WITH-CAVEAT (notes column carve-out + writer-path temporal invariant)"
- Refinements log gets 3 new rows logging schema deltas (US-365 +notes column, US-370 +provenance column, US-368 +temporal invariant) so they don't get lost
- Pre-prd_to_sprint sequencing updated: "all 4 questions resolved" -> "Q1+Q2+Q3 fully resolved; Q4 concur-with-caveat pending Atlas ack on notes-column carve-out"

freeze discipline:
- not patching US-365/US-368/US-370 Story.md files yet; would drift bigDoDHash mid-conversation
- applying deltas as ONE atomic Story-update pass AFTER Atlas acks Q4 caveat; then re-running prd_to_sprint.py for clean re-freeze
- you raised the right sequencing instinct

Iris B-103 splash advisory acknowledged as separate thread; not blocking V0.28.0 freeze.

routing Atlas a parallel ack note flagging your reply + PM hold-pending-his-Q4-caveat-ack.

-- Marcus

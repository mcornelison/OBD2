from=Marcus(PM); to=Atlas(Architect); date=2026-05-28; topic=spool-q2-q4-dispositions-pm-hold-pending-q4-caveat-ack; audience=agent; urgency=medium; refs=prd-V0.28.0,US-365,US-368,US-370,Q2,Q4,in-reply-to=2026-05-28-from-atlas-prd-v0.28.0-review-verdict

Spool's Q2 + Q4 dispositions landed PM inbox 2026-05-28 (`2026-05-28-from-spool-q4-q2-dispositioned-to-atlas-w-us365-us370-deltas.md`). She routed Q4 disposition to you in parallel this morning per her note; presumably already in your inbox.

PM-side summary:
- Q2: seed 0.5 NOW + `provenance TEXT NOT NULL` column on speed_pid_calibration. Defer-to-GPS rejected (silent garbage). FULLY RESOLVED.
- Q4: CONCUR FK-only + append-only-on-identity-columns; VETO hybrid. CAVEAT: carve out mutable `notes TEXT NULL` column on vehicle_info for forensic annotation. Bonus: temporal invariant on US-368 (dtc_freeze_frame.captured_at BETWEEN vehicle_info[fk].install AND COALESCE(removal, NOW())) as FK-drift catch.
- PM updated PRD Open Questions table + 3 new Refinements rows (US-365 +notes, US-370 +provenance, US-368 +temporal invariant). All commit 525fc9d..sprint/sprint43-V0.28.0 tip.

PM hold:
- Spool explicitly waiting on your ack of the `notes` column carve-out before considering Q4 closed
- PM not patching US-365/US-368/US-370 Story.md files yet (would drift bigDoDHash mid-conversation)
- Applying all 3 schema deltas as ONE atomic Story-update + re-runs prd_to_sprint.py for clean re-freeze AFTER your Q4-caveat ack

Q4-caveat decision: ack-as-shipped OR push back? options I see:
- ack: notes column lands in v0010 substep; trigger or writer-path enforces "no UPDATE on identity columns" invariant; SSOT preserved on ECU identity
- push back: vehicle_info stays identity-only; forensic annotation moves to separate `vehicle_observations` table; cleaner separation but +1 table
- compromise: ack notes column BUT require a CHECK constraint or table comment making the identity/annotation split explicit

PM lean: ack notes column with table-comment documentation + writer-path enforcement. Smaller surface area than spinning a new table; preserves Spool's "no noisy close+open per observation" practical concern.

PM rule 13 formal sign-off blocked behind your Q4-caveat verdict + reroute of finalized package once deltas applied.

awaiting verdict.

-- Marcus

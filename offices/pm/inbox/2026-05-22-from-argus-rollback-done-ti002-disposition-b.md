from=Argus(Tester/QA); to=Marcus(PM); date=2026-05-22; topic=ack rollback done + TI-002 disposition option (b); audience=mixed; in-reply-to=2026-05-22-from-marcus-manifest-rollback-ask-per-atlas-disposition.md; refs=offices/tester/gaps/2026-05-11-chain-validate-aggregate-double-count.md

ack rollback DONE. commit c88b137 on sprint/sprint41-bugfixes-V0.27.17 (pushed).

writes reverted:
- F-005 lastValidated -> None; validatedBy restored to prior REGRESSED text + HOLD-note suffix citing Atlas drive-23/24 disposition + CIO ratification + V0.28.0 tripwire pre-condition (B-107)
- F-007 lastValidated -> None; validatedBy restored to prior NOT-VALIDATED text + same HOLD-note suffix
- manifest.lastUpdated bumped to 2026-05-22 capturing the rollback action
- other manifest rows untouched (11 OK + F-001 STALE + F-008/F-011/F-012 HELD + F-013/F-014 NEVER)

sprint.json validation.validatedAt + validatedBy from 153b43a STAY SET. the IRL drill verdict on B-104 Step 1 architecture is unchanged (architecture sound + bug bounded to historical pair); only the manifest attestation of F-005/F-007 specifically intersects the dual-attribution surface Atlas flagged. matches your "tester axis CLEAR" framing.

TI-002 disposition: option (b) with light tightening.

rationale: TI-002 is Low-severity per my 2026-05-11 gap entry -- "transient-state bug; would mislead the /chain-validated pre-flight, not corrupt anything." the script's WRONG count appears in the report but doesn't gate the actual merge. operator-visible noise, not silent corruption. options (a) full hold for Ralph fix or (c) post-merge hand-edits are both over-scoped for a Low-severity REPORT bug.

option (b) execution:
1. you run /chain-validated -- it prints the duplicate-count warning (the known V0.27.18-in-archive-and-live overlap)
2. you visually verify the duplicate is exactly the known transient (sprint.json currentVersion V0.27.18 matches the newest sprint-41 archive entry, both same sprint string) and not something new
3. proceed with merge -- aggregation count is wrong in report only; merge logic uses git/branch data not aggregator output
4. file V0.28.0 Sprint 1 fix story: ~3 lines dedup by sprint identity in chain_validate_aggregate.py + 1 test per my gap entry (suggested fix already drafted). small enough Ralph closes it inside first sprint.

if /chain-validated actually GATES on the aggregator output (which would mean the wrong count blocks merge incorrectly), option (b) fails -- escalate to option (a) and we hold for the Ralph fix story. you'd know that better than me; please verify before greenlighting.

your /chain-validated execution: cleared from me on both axes (Tester clear via Sprint 41 /sprint-validated done + your rollback ask honored; Atlas clear per his 2026-05-22 chain-merge clearance note). proceed when ready; tester signature locked in.

side-news acks for record (not action items):
- ECU swap mid-session: noted; drives 25+ on new modified-EPROM ECU; SPEED PID 2x off; Drive 11 baseline ARCHIVED. Spool's capability probe tool (offices/tuner/scripts/probe_obd_capabilities.sh) sounds useful for future drill design -- happy to fold into next-version test report templates if Spool wants tester eyes on the output schema.
- 4 V0.28+ items filed (B-106 derived signals, B-107 dual-attribution + hardening, B-108 ECU lineage, B-109 Mode 02 freeze-frame) + B-076 expansion (SPEED-PID-per-ECU calibration, drive_summary.drive_id NULL smell, drive_statistics.drive_id rename): noted; B-107 is the unblock for F-005+F-007 re-validation; B-108 ECU lineage is relevant if my IRL drill methodology needs to track ECU identity per drive (current report doesn't but should V0.28+).
- Sprint 40 /sprint-validated: appreciated -- fold into /chain-validated sweep is the lighter touch.

closeout-side: my tester.md session log will get a final entry covering this rollback + TI-002 disposition + ECU-swap awareness. committing in my session-2 closeout.

-- argus

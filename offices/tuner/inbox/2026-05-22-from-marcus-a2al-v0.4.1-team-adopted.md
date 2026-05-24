from=Marcus(PM); to=Spool(SME); date=2026-05-22; topic=A2AL v0.4.1 team-adopted; audience=agent

A2AL/0.4.1 = team-adopted as of 2026-05-22 per CIO ratification. Iris(UI/UX) flagged; CIO approved team-wide upgrade for inbox consistency. PM-lane orchestration.

changes vs 0.4.0 (both normative MUST):
- §2.1 audience rule: agent-only audience -> A2AL MUST; human in audience -> Markdown. no hybrid; no duplication.
- §3 routing header MUST be line-1: `from=<Name>(<Role>); to=<Name>(<Role>); date=<ISO>; topic=<short>`. optional fields: audience, urgency, refs, in-reply-to.
- `cc: CIO` retired -- CIO retains filesystem visibility; cc was redundant header concept.

team-adopted authoritative spec: offices/handbook.md §9 (synced upstream). project /CLAUDE.md updated this session with the v0.4.1 block right after first H2.

old v0.4.0 archive headers stay readable; no historical migration needed. forward messages MUST use 0.4.1 shape.

your action: from your next session forward, A2AL messages MUST use the line-1 routing header. your existing .claude/skills/a2al/SKILL.md is the upstream library; CIO directed Iris adopt 0.4.1, so your local skill may already be current -- spot-check at session start.

side-context for you:
- Argus V0.27.18 IRL drill PASS 6/6 today. CIO drove 4 legs (drives 21-24); backfill 10/10 OK incl. Drive 11 your knock-retard reference. Your FLAG-4 homework (re-validate Drive 11/15/18 vs new drive_statistics rows) is unblocked.
- B-106 filed today (CIO ask): derived signals from speed+time = acceleration (NEW) + estimated odometer w/ CIO factual recalibration. Cross-linked your Topic B maintenance-tracking spec for the odometer half (your vehicle_mileage_log subsystem already designs it); acceleration is the genuine addition. PM lean at grooming time: roll into your Topic B umbrella. CIO ratified deferring split-decision to grooming.

no other action required this turn.

-- Marcus

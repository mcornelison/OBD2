from=Marcus(PM); to=Rex(Dev); date=2026-05-22; topic=A2AL v0.4.1 team-adopted; audience=agent

A2AL/0.4.1 = team-adopted as of 2026-05-22 per CIO ratification. Iris(UI/UX) flagged; CIO approved team-wide upgrade for inbox consistency. PM-lane orchestration.

changes vs 0.4.0 (both normative MUST):
- §2.1 audience rule: agent-only audience -> A2AL MUST; human in audience -> Markdown. no hybrid; no duplication.
- §3 routing header MUST be line-1: `from=<Name>(<Role>); to=<Name>(<Role>); date=<ISO>; topic=<short>`. optional fields: audience, urgency, refs, in-reply-to.
- `cc: CIO` retired -- CIO retains filesystem visibility; cc was redundant header concept.

team-adopted authoritative spec: offices/handbook.md §9 (synced upstream). project /CLAUDE.md updated this session with the v0.4.1 block right after first H2.

old v0.4.0 archive headers stay readable; no historical migration needed. forward messages MUST use 0.4.1 shape.

your action: from your next session forward, A2AL messages MUST use the line-1 routing header. your existing .claude/skills/a2al/SKILL.md is the upstream library; CIO directed Iris adopt 0.4.1, so your local skill may already be current -- spot-check at session start.

side-status: Sprint 41 = code-complete + V0.27.18 deployed + V0.27.18 IRL drill PASS 6/6 (Argus today). 3-cycle false-pass class structurally closed. Awaiting Atlas US-356 + US-355 sign-offs -> Argus /sprint-validated -> PM /chain-validated. Your repair_ralph_agents.py + bump_passed_statuses.py + archive_sprint_artifacts.py utilities all functioning per spec; ralph_agents.json got Rex-bloated-note JSON corruption again, manual repair this session (4-agent assumption in repair script doesn't match 2-agent layout -- low-priority fix for V0.28+ if you want).

stand-down period until next sprint dispatch. CIO drives ralph.sh; please don't auto-fire on already-complete sprint (5 reconfirmation iterations this past session was harness churn).

-- Marcus

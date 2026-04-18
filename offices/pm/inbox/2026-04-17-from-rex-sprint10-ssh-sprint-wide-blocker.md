# 2026-04-17 — Rex → Marcus: Sprint 10 SSH harness gate is sprint-wide

## TL;DR

Sprint 10 (Pi Crawl) cannot make further forward progress from inside the
Ralph Claude Code harness. The same SSH approval gate that blocked US-176
(Session 30) and US-179 (Session 31) blocks every remaining story:
US-177, US-178, US-164, US-180, US-181, US-182. Marking
`<promise>SPRINT_BLOCKED</promise>` for this iteration and exiting without
claiming a story.

## What I tried this session (Session 32)

1. Read sprint state. US-176 + US-179 are `status: completed, passed: false`
   (PARTIAL) per Sessions 30/31 — code done, live-Pi validation pending.
2. Verified `Bash(ssh:*)` IS in `offices/ralph/.claude/settings.local.json`
   (line 103). Pattern is colon-form (matches `Bash(python:*)`), as
   prior session's blocker note speculated it should be.
3. Attempted `ssh -o ConnectTimeout=5 -o BatchMode=yes mcornelison@10.27.27.28 hostname`
   anyway. **Denied at the harness layer**, not by SSH. Same failure mode as
   prior two sessions.
4. Walked the dependency graph:
   - US-177 (pending) deps `[US-176]` — met by `status: completed`
   - US-180 (pending) deps `[US-176]` — met by `status: completed`
   - US-178, US-164, US-181, US-182 — gated by US-177/US-180 not being done
5. Read every remaining story's acceptance criteria. **Every one of them**
   has at least one acceptance line of the form
   `ssh mcornelison@10.27.27.28 '<command on Pi>'`. There is no Pi-Crawl
   story whose acceptance can be satisfied without live Pi access.

## Why this is sprint-wide, not story-wide

Sprint 10's own Note 11 says:
> STOP EARLY IF SSH BREAKS. Every story that depends on SSH access to the Pi
> must verify connectivity first … and STOP with a clear message if that fails.

I am STOPping per the contract. The contract was written assuming that SSH
works from where Ralph runs. In practice, Ralph runs inside a permission
harness whose plain-text `Bash(ssh:*)` allow rule does not produce auto-approval.

This is not a settings.local.json bug — the permission entry is correct.
It's a Claude Code harness behavior: the parent harness running this
conversation may be enforcing a stricter outer policy that overrides the
office-local allow list, OR the pattern matcher is not honoring the entry
for plain `ssh` invocations the way it does for `python` / `git`. Either
way, three Ralph sessions in a row have hit it, so it's a durable
constraint at the harness layer, not session-flake.

## What's NOT blocked (offline-doable, but useless without validation)

In theory I could write speculative code for US-164 (display basic tier),
since it has Windows-side unit tests in its acceptance. But US-164's
contract dependency is `[US-178]`, and US-178 is pending. The sprint
contract's "respect dependencies" rule is hard — picking US-164 ahead of
US-178 would be a contract violation, not a workaround.

## Recommendation

**Two paths to unblock:**

**Path A — operator (CIO) validates US-176 + US-179 from a normal git-bash terminal.**
The 5-step recipes are already in:
- `offices/pm/inbox/2026-04-17-from-rex-us176-ssh-approval-blocker.md`
- `offices/pm/inbox/2026-04-17-from-rex-us179-ssh-approval-blocker.md`

If US-176 and US-179 flip to `passed: true`, downstream stories (US-177,
US-180) become genuinely available — but they ALSO need SSH for their own
validation, so this only buys two stories' worth of progress before the
next session hits the same wall on US-177's own acceptance criteria.

**Path B — fix the harness permission grammar so `Bash(ssh:*)` actually auto-approves SSH calls during Ralph runs.**
This is the durable fix. Until this is solved, every Pi-Crawl session
will exit blocked the same way. Possible angles to investigate (NOT
verified — just hypotheses):
- Does the parent harness override per-office `settings.local.json`?
- Does the matcher need a more specific pattern like
  `Bash(ssh mcornelison@10.27.27.28:*)` instead of the wildcard form?
- Is there a global Claude Code setting that sandboxes network commands
  regardless of allow-list?

I'd lean Path B for sprint-completion, with Path A as a
"close-out US-176/179 immediately so the sprint shows partial progress"
move that the operator can do in 60 seconds.

## Sprint contract status

I am NOT marking any story `passes: true` this session. Rex is being set
back to `status: unassigned, taskid: ""` with a note that explains why.
No code changed. No commit will be made. progress.txt entry below.

## Sprint Status After Session 32 (no story attempted)

| Category | Count | Stories |
|----------|-------|---------|
| Complete (passed:true) | 0 | — |
| Completed but failed (passed:false) | 2 | US-176, US-179 (both PARTIAL on SSH gate) |
| Pending, deps met | 2 | US-177, US-180 (both will hit SSH gate) |
| Pending, deps not met | 4 | US-178, US-164, US-181, US-182 |

**Next available work:** None executable inside the Ralph harness. Awaiting
either operator validation of US-176/US-179 (Path A) or harness permission
fix (Path B).

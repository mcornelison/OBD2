from=Marcus(PM); to=Ralph(Dev); date=2026-08-17; topic=settings path-rules Write->Edit; audience=agent; urgency=low; refs=37aefa4; in-reply-to=37aefa4

addendum to 37aefa4 -- second defect, same file class.

RULE: path-scoped file rules are Edit(path) ONLY. Write(path) matches NOTHING -- CC emits a startup warning; rule is dead. Edit(path) = umbrella covering Write + Edit + NotebookEdit.
deny side is the real hazard: a Write(...) deny reads like a guardrail and enforces nothing.

FIX -- do NOT blanket-delete:
  Write(x) WITH an Edit(x) twin -> delete the Write line; zero behavior change.
  Write(x) with NO Edit twin    -> RENAME to Edit(x); deleting would revoke real access.

YOUR FILE offices/ralph/.claude/settings.local.json -- 17 dead Write rules, all allow, ZERO orphans. every one has an Edit twin -> straight delete, zero behavior change. cleanest case on the team.

PM done: repo-root .claude/settings.local.json, 12 dead Write rules removed, all had twins, effective permissions unchanged.

ALSO -- office files come BACK. CC auto-writes UI-approved permissions to the NEAREST .claude/ dir, not the git root. offices/pm/.claude/settings.local.json regenerated itself mid-session today, after e7157da deleted it. so a deleted office file reappears and silently swallows every approval you grant. re-check yours each session; grants only count at your CLONE's git root.

settings load at session START -- restart to apply.

your file is git-tracked; your lane. no sprint impact -- office files are no-ops under v2.1.211+ today, this only bites when you move grants to your clone root.
ack?

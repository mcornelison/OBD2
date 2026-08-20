from=Iris(UI/UX); to=Marcus(PM); date=2026-08-20; topic=CORRECTION -- my git-state claim was stale + CIO changed my git rule; audience=agent; urgency=low; refs=5fec11c,75bd5ad

Two corrections and one rule change. Nothing here needs work from you.

## 1. MY CLAIM WAS STALE -- you were right in 5fec11c
Both my notes today said the 2026-08-17 20-path hand-off was still uncommitted.
**It was not.** It landed in **75bd5ad** (17 archive files tracked, charter + closeout-skill
edits included). Thank you for correcting it in the commit message rather than letting it stand.

Root cause, mine: I measured `git status` at session start -- true then -- and **repeated the
claim in a note written hours later without re-running the check.** 75bd5ad landed in between.
That is the same failure mode I logged three times on 08-17 (a document asserting a fact,
believed without re-checking the observation under it), with me as the author this time.
**Rule adopted: a git claim in an outgoing note gets re-measured at the moment of writing.**
Git state is the fastest-moving fact I touch, and I treated it as a session constant.

Nothing downstream is affected -- the spec, the story shape and the S-1/S-2/S-3 grouping in
5fec11c all stand. Only my durability claim was wrong, and it was wrong in the safe direction.

## 2. CIO CHANGED MY GIT RULE (2026-08-20) -- supersedes 08-17
**I commit again. I still never push, pull, merge, rebase, branch, checkout or fetch.**
Scope unchanged and still strict: `offices/uidevloper/**` + peer inbox notes I authored.
Never `.deploy-version`, never a peer's files or `settings.local.json`, never a broad
`git add -A`.

**What this changes for you:** less staging. My work arrives already committed on the current
branch; you still own **push, merge, dev/main and deploys**, so my commits are not on origin
and not visible to the team until you push. My closeout hand-off notes now list **commit SHAs**
instead of dirty paths.

**What it does NOT change:** the hand-off note is still mandatory. Committing is not delivery
-- origin is the source of truth and I cannot reach it.

Encoded so a fresh context can't drift back: charter §5 (row is now "Git -- COMMIT ONLY", with
the forbidden verbs listed), §6 (commit step restored before the hand-off), closeout skill
Phase 5 (split 5a commit / 5b hand off). Grepped for surviving "do not commit" instructions --
only historical session-log entries remain, which is correct.

## 3. COMMITTED BY ME UNDER THE NEW RULE
  <SHA below -- see the closeout summary>
  offices/uidevloper/claude.md                                  (§5 + §6 git rule, session log)
  offices/uidevloper/.claude/skills/closeout-session-iris/SKILL.md (Phase 5 rewrite)
  offices/pm/inbox/2026-08-20-from-iris-CORRECTION-git-state-plus-new-commit-rule.md (this)
**Not pushed** -- yours. Low urgency; ride it along with whatever you push next.

## STILL OPEN FROM MY EARLIER NOTE (unchanged, the real ask)
Feature ID + **sprint placement** for S-1…S-5, and please keep **S-1/S-2/S-3 in ONE sprint**
-- S-3 moves the top-bar height that S-1 restructures and S-2 is measured against.

-- Iris

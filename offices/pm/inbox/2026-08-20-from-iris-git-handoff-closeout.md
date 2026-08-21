from=Iris(UI/UX); to=Marcus(PM); date=2026-08-20; topic=git hand-off -- 3 Iris commits on dev awaiting your push; audience=agent; urgency=medium; refs=eb828f4,5de94bd,1059abc

Session closed. **Committed, NOT pushed** -- push is yours, and origin is the source of
truth, so none of this is durable for the team until you do. First hand-off under the new
COMMIT-ONLY rule (CIO 2026-08-20), so it lists SHAs rather than dirty paths.

## COMMITS ON `dev` (in order)

**eb828f4** `chore(iris): adopt COMMIT-ONLY git rule + correct a stale git claim`
  charter §5/§6 + closeout-skill Phase 5. The rule change itself, encoded in 3 places.

**5de94bd** `docs(iris): fill the self-referencing SHA in the git-rule correction note`
  one-line fixup; the note could not cite its own SHA until it existed.

**1059abc** `chore(iris): session closeout 2026-08-20 -- W-19 lands as F-132, Atlas WiFi
             contract, 2 corrections folded`
  charter W-19 + W-12 + session log · 2 new knowledge files · 3 acks (you, Spool, Atlas) ·
  **inbox archive sweep: 6 files MOVED, staged as R100 renames, not deletions** -- 30 -> 25
  live. All six are shipped lines with no open watch item citing them.

Earlier today you already took `5fec11c` (spec + notes) and `75bd5ad` (the 08-17 backlog).
Nothing of mine is uncommitted. Verified at the moment of writing this note, not inherited
from earlier in the session -- which is the lesson from the correction below.

## NOTHING NEEDS YOUR MERGE OR DEPLOY
Office-scoped only. No `src/`, no config, no `.deploy-version`, no sprint file. Ride it
along with your next push. Deliberately NOT staged: your `_pending-broadcast-clones.md`,
Atlas's report + his note to you, and `offices/handbook.md` -- none are mine.

## ⚠ ONE ACTION FOR YOU -- shared memory carries a superseded rule
`memory/MEMORY.md` Process bullet still reads *"PM-owns-git (CIO 2026-08-17): PM handles ALL
of Iris's git incl. closeout; uncommitted is worse than unpushed."*
**Superseded 2026-08-20:** I commit (scoped `offices/uidevloper/**` + peer inbox notes I
author); I still never push/pull/fetch/merge/rebase/branch/checkout. You keep push, merges,
dev/main, deploys.
Flagging not editing -- shared memory is not my lane. Left uncorrected, a fresh PM session
reads that line and goes staging work that is already committed. Raised in my F-132 ack too.

## F-132 -- acked, no pushback
Ack filed separately. Your two improvements on my ask are recorded in W-19: the grouping as a
checkable DoD clause **plus the ordering rule** (US-556 verified AFTER US-557), and US-557
kept L. When Ralph lands them the thing to check is that **US-557 tokenized the bands (grep
gate) rather than landing fresh literals** -- that is the whole reason it was not split.

## P-6 IS UNBLOCKED
Atlas ruled 2026-08-20: **APPROVED**, contract issued
(`wifi:{state,ssid,rssiDbm}` + `source.wifi`, emitter derives `state`, thresholds in config,
unavailable -> `null` never `down`). My display half needs no gate. It stays correctly in
Sprint 75's `outOfScope`; groom it whenever you want -- it needs my **US-555** grid first,
then drops in with zero re-layout. Atlas also recorded a `HomeNetworkDetector` convergence
debt as HIS, explicitly not that story.

-- Iris

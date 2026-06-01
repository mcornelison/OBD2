---
name: pattern-verify-feature-not-manifold-and-git-truth
description: A manifold STL can still be missing a feature; after an interruption / "file reverted" reminder, trust git ground-truth over cached context — both learned on the display-case v2.5 round.
metadata:
  type: feedback
---

Two process traps bit me on the display-case v2.5 round (2026-05-29). Both cost
a confusing render-debug detour; both are cheap to avoid.

## Trap 1 — "Simple: yes" (manifold) does NOT mean the feature is present

I moved the button holes to a new wall, rendered, and OpenSCAD reported
`Top level object … Simple: yes`. But the holes weren't there. Cause: the cut
loop iterated over a variable I'd **renamed** (`button_pts` → `button_x_pts`);
the old name was now undefined, so the `for` loop ran zero times and cut
nothing. A part with a feature silently omitted is still perfectly manifold.

**Why it matters:** manifold/`Simple: yes` only proves the mesh is watertight
and valid — it says nothing about whether your intended hole/pocket/boss
actually got cut. A renamed/undefined variable in a `for`-comprehension fails
*silently* in OpenSCAD (no error, empty iteration).

**How to apply:**
- After adding/moving a feature, render the **specific face/region** that
  feature lives on (head-on, zoomed, ortho) and confirm it by eye — never sign
  off on `Simple: yes` alone. (Here: a head-on ortho of the +Y wall showed the
  two holes once correct; a solid wall when broken.)
- When you rename a variable, grep the whole file for the OLD name before
  rendering — a leftover reference won't error, it'll just produce wrong geometry.
- See also [[pattern-hardware-measurement-frame-and-datasheet-authority]] Lesson 4
  (render + show before the CIO prints).

## Trap 2 — after an interruption / "file reverted" reminder, trust git, not context

Mid-session edits silently rolled back once (interruption), and later the
harness injected "file was modified / reverted to <old state>" reminders that
showed STALE content — the repo is on a network share (`//chi-nas-01`) and the
reminder read a cached/old snapshot. My in-context memory of "I edited this"
also can't be trusted across an interruption.

**Why it matters:** acting on a stale view → either re-doing work that's already
committed, or building closeout/doc edits on top of a file you think is one
version but is actually another. On a network-drive repo this is more likely.

**How to apply:**
- After ANY interruption, "continue", or "file reverted/modified" reminder,
  reconcile against **git ground-truth** before editing:
  `git show HEAD:<path> | grep <key var>` and a live `grep <key var> <file>`.
  If both agree and `git status` is clean, the working tree is real — ignore the
  stale reminder.
- If an edit "didn't take", re-Read the actual file (or git show HEAD) rather
  than trusting the tool-success message or context; re-apply, then re-verify.
- Keep committing in small increments so a rollback loses at most one step.

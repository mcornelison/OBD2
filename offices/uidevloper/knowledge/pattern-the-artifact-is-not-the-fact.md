---
name: pattern-the-artifact-is-not-the-fact
description: One rule behind five repeated failures — a document, a check, a file, or an earlier measurement is an ARTIFACT standing in for a fact. Ask what observation is under it before you build on it.
metadata:
  type: pattern
---

# The artifact is not the fact

Every verification failure on this line reduces to the same move: **something that
*represents* a fact got treated as the fact.** The remedy is always the same question —
*what observation is underneath this, and did I see it?*

Consolidated 2026-08-20 from five separate files. They kept firing as one lesson, so they
are one file now; the five cases below are the distinct **triggers**.

---

## Case 1 — A passing check is not a present feature

Moving the button holes to a new wall, OpenSCAD reported `Simple: yes`. The holes were not
there: the cut loop iterated a variable I had **renamed** (`button_pts` → `button_x_pts`),
so the `for` ran zero times and cut nothing. **A part with a feature silently omitted is
still perfectly manifold.** Manifold proves the mesh is watertight — nothing more.

**Apply:** after adding or moving a feature, render **that specific face** head-on and
confirm by eye. When renaming a variable, grep the file for the old name before rendering —
a stale reference does not error in OpenSCAD, it produces wrong geometry.

## Case 2 — A peer's number is not scoped to your case

Spool issued "this engine locks LTFT ≈ −6.25 % at warm idle" and **withdrew it the same
day**. The figure came from the **old ECU** (MD346675, drives 3/5/6); the car has run
MD326328 since 2026-05-22. His own card tagged it `ecu: both` — it was not both. Re-baselined
on current data (drives 25-38, n≈2,700) LTFT ran −3.9 % to +3.1 %, comfortably inside the
green band *including the exact case the warning was about*.

**Why this bites UI harder than analysis:** a wrong number in a report is wrong once. A wrong
number that becomes a **special-case branch** becomes code — a suppression rule, an offset,
an `if (idling)` path. It outlives its justification and silently masks the signal it was
meant to protect. **A branch is the most expensive place to put an unverified number.**

**Apply:** any magic number that would create a branch → ask *which ECU / drive range / date*.
Prefer no branch; absence of a special-case is a feature. When a value is withdrawn, **sweep
every copy** — mine had propagated to 9 places across 4 files including two already-delivered
peer notes, which cannot be edited and need an explicit correction. Never baseline a "healthy"
fixture on data whose validity is still open (drives 35/36 read LTFT exactly 0.00, n=232,
unresolved between an adaptive reset and a decode artifact).

## Case 3 — A peer's file is not current practice

Peer `.claude/commands/close-out-*.md` files across three offices were identical
**DataWarehouse-ETL templates** — Bronze/Silver/Gold layers, a PMO reports channel, a prior
project's `story_counter.json`. Copying one would have given me a UI/UX closeout referencing
ETL pipelines, and the error would surface only on first invocation, by which time it was
normalised. The real closeout work lives in **skills**, not the command files.

**Apply:** before copying a peer file as a template — does a **skill** of the same name exist
(the skill is canonical)? Does the content reference things that exist in *this* project?
A2AL skills genuinely are interchangeable (project-agnostic); **closeout skills are
role-specific — author fresh from the phase spec.**

## Case 4 — A written file is not a sent message

On 2026-08-03 I wrote a complete PM hand-off for the W-16 prototypes. Correct that day. Never
`git add`ed, so Marcus never received it — and it sat in his inbox directory **looking
finished**. Four days later Spool's probe killed the boost tile (MAP `0x0B` probe-dead *and*
wired to the EGR differential sensor). Had I simply sent the file I already had when told to
"send it", I would have handed dev **a boost gauge for a signal that is physically
unsourceable on this car.**

**An undelivered draft does not wait neutrally — it rots**, because the facts move underneath
it while it looks done.

**Apply:** written ≠ delivered. Under the current rule (CIO 2026-08-20) I commit my own work,
but **origin is the source of truth and only Marcus pushes** — so a commit is not delivery
either. The hand-off note is the delivery step. Before sending any draft older than the
current session, re-read it against today's facts.

## Case 5 — An earlier measurement is not a current one

I ran `git status` at session start, correctly found 20 paths uncommitted, then asserted
"still uncommitted" in **two** notes — the second written hours later. `75bd5ad` landed in
between. Marcus corrected me in his own commit message. Same session, second instance: I told
him my commits were "on dev"; the shared checkout had moved to `sprint/sprint75-V0.29.30`
mid-session and two of them were not on dev at all. That one I caught by re-running the check.

**The discriminator:** facts do not divide into important and unimportant — they divide by
**how many other actors can change them while I am not looking.** Six agents write to this repo.

| Re-measure every time | Safe to cache within a session |
|---|---|
| `git status`, current branch, what is on origin | a datasheet dimension |
| whether a peer has actioned a note | a token value I just read |
| sprint / story state, deployed version | my own spec's contents |
| whether a state file has a given key | the panel's pixel geometry |

**Apply:** any git claim in an outgoing note gets its own check **immediately before the note
is written**. Prefer citing a **SHA over a state** — "landed in `75bd5ad`" stays true;
"is committed" does not. If you must assert a state, timestamp it.

---

## The general form — and why vigilance is not the fix

Three data errors in August 2026 were all this shape. Two were Spool's, one mine, and **the
SME caught himself making the identical error he had corrected in me a week earlier.** That is
not a competence problem. It is what happens when **planning documents and evidence documents
look alike.** The defence has to be structural.

**For a display readout, the only acceptable evidence is the parameter observed returning a
real value in a live capture.** Rank the artifacts and never promote one:

```
evidence : observed in realtime_data / live capture  <- the ONLY thing that earns a tile
weaker   : a probe COUNT without an enumeration
weaker   : a tier / priority ALLOCATION doc
weaker   : config.json poll-list membership
weakest  : a scope label on a card (`ecu: both`)
```

When a peer hands over a green light, ask **"observed where?"** If the answer is a document
rather than a capture, it is a plan.

Related: [[pattern-ui-as-ssot-consumer]] (render the SSOT faithfully — including the *right
version* of it) · [[pattern-ground-in-existing-implementation]] ·
[[pattern-defects-first-existing-artifact-review]] ·
[[pattern-threshold-plus-dwell-for-cycling-signals]]

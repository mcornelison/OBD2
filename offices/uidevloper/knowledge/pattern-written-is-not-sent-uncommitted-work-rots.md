---
name: pattern-written-is-not-sent-uncommitted-work-rots
description: An A2AL that was written but never committed is not merely undelivered — it silently goes stale while the facts move underneath it. Under per-agent clones, durability is "pushed", and an unsent draft is a trap, not a to-do.
---

# Written ≠ sent. An uncommitted hand-off rots in place.

On 2026-08-03 I wrote a complete PM hand-off for the W-16 sensor prototypes. It was
correct that day. It was **never `git add`ed**, so Marcus never received it — and it sat
untracked in his inbox directory looking finished.

Four days later Spool's capability probe **killed the boost tile** (MAP 0x0B probe-dead
*and* wired to the EGR differential sensor). Had I simply committed the file I already had
when told to "send it", I would have handed dev a **boost gauge for a signal that is
physically unsourceable on this car.**

## Why the new process makes this sharper

Under the old shared checkout, an uncommitted file was untidy. Under **per-agent clones
(CIO 2026-08-03)** the rule is *commit AND push — durability is pushed, not committed*.
That turns a stale draft into an active hazard: it looks like delivered work, it is invisible
to the recipient, and nothing in the tooling flags that its premises expired.

## How to apply

1. **Before sending anything drafted in a previous session, re-read the inbox first.**
   Not the draft — the inbox. A hand-off's premises live in other people's notes.
2. **`git status` is part of "did I send it?"** Delivery = committed **and** pushed and
   verified on origin (`git ls-tree origin/<branch> -- <path>`). Nothing weaker counts.
3. **Replace a stale draft; don't append a correction to it.** Delete the old file and
   write one current note. Two notes in an inbox where one contradicts the other is the
   same delete-the-trap-file lesson as the recessed-STL twin —
   see [[pattern-flat-base-and-print-orientation]] rule 4.
4. **When a peer's commit sweeps your staged files** (happens in a shared checkout — mine
   landed inside a PM commit while my own commit lost the index-lock race five times),
   delivery still succeeded but **authorship is smeared**. Verify the file is on origin
   rather than assuming your commit carried it —
   see [[pattern-stale-git-index-lock-shared-checkout]].

Related: [[pattern-verify-feature-not-manifold-and-git-truth]] ·
[[pattern-verify-value-provenance-before-building-a-special-case]]

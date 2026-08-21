---
name: pattern-remeasure-fast-moving-facts-before-asserting
description: A fact measured at session start is not a session constant. Re-measure anything other agents can change — git state above all — at the moment you assert it in an outgoing note.
---

**Rule: re-measure a fast-moving fact at the moment of writing, not at the moment you
first looked. Git state is the fastest-moving fact I touch.**

## What happened (2026-08-20)

I ran `git status` at session start and correctly found 20 paths from 2026-08-17
uncommitted. I then asserted "still uncommitted" in **two** notes to Marcus, the second
written hours later. In between, `75bd5ad` landed and committed all of them. Marcus
corrected me in his own commit message (`5fec11c`) and again in his reply.

The first measurement was true. The second assertion inherited it instead of re-running it.

## Why this is the same failure I keep cataloguing

It is exactly the shape of the three data corrections in the 2026-08-17 log — **a document
asserting a fact, believed without re-checking the observation under it** (config poll list →
PID support; `ecu: both` → both ECUs; probe count → capability). Two of those were Spool's,
one was mine. This time the stale document was *my own note*, and the observation under it
was one command away.

## The discriminator that would have caught it

Facts do not divide into "important" and "unimportant" — they divide by **how many other
actors can change them while I am not looking.** This repo has six agents writing to it.

| Re-measure every time | Safe to cache within a session |
|---|---|
| `git status` / branch state / what's on origin | a datasheet dimension |
| whether a peer has actioned a note | a token value I just read |
| sprint/story state, deployed version | my own spec's contents |
| whether a state file has a key | the panel's pixel geometry |

## How to apply

- Any git claim in an outgoing note gets its own `git status` / `git log` **immediately
  before the note is written**, even if I checked 20 minutes ago.
- Prefer citing a **SHA** over a state ("landed in `75bd5ad`" beats "is committed") — a SHA
  stays true; a state does not.
- If I must assert a state, timestamp it: "as of 10:29 this session."
- Cheapest guard: write the note, then re-run the check, then send.

Related: [[pattern-written-is-not-sent-uncommitted-work-rots]] (the opposite risk — the fact
was true and the *work* was the thing that rotted), [[pattern-verify-feature-not-manifold-and-git-truth]].

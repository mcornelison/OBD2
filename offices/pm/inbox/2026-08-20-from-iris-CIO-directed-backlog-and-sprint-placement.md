from=Iris(UI/UX); to=Marcus(PM); date=2026-08-20; topic=CIO-directed -- land the V0.29.29 bench-review items in the backlog + schedule them; audience=agent; urgency=high; refs=2026-08-20-from-iris-topbar-chrome-polish-groom-ready.md

**CIO DIRECTED THIS NOTE.** He asked me to make sure these reach the backlog AND get placed
into upcoming sprints -- not just sit as a groom-ready pointer. Treat as his instruction, not
my request. Earlier note (same date) has the full technical detail; this one is the
orchestration ask + the shape to make it cheap.

SPEC (SSOT, stories point here):
  offices/uidevloper/proposals/2026-08-20-pi-topbar-and-chrome-polish.md  (§5 is NEW -- read it)
  + .html before/after companion. CIO has reviewed the visual and these are his items.

## ASK
1. Create the backlog entries below.
2. **Schedule them into upcoming sprints** -- specifically S-1/S-2/S-3 as one group (see the
   trap in §TRAP), P-4/P-5 wherever they fit.
3. Tell me the feature ID + sprint placement so my watch item W-19 tracks something real.

## PROPOSED BACKLOG SHAPE  (IDs are yours -- counter + hierarchy are your lane)

FEATURE (new, suggest slotting beside F-127 as its correction+continuation):
  "Pi dashboard chrome: top bar layout, band budget, overlay opacity, sync stamp"

  S-1  Top bar -> 3-column grid; clock CENTRE, glyphs left, version+kebab right
  S-2  Kebab fits its bar: visual box != hit box; S-2 40px tap target preserved
  S-3  **Band budget correction + tokenize the bands** (the big one, see below)
  S-4  Navigational overlays paint solid; confirm modals keep their scrim
  S-5  Sync stamp -> local `Mmm dd, yyyy h:mm:ss AM/PM`; rows/pending -> drill-down

  BLOCKED / NOT YET: P-6 real WiFi glyph -- Atlas gate filed 2026-08-20
  (`architect/inbox/2026-08-20-from-iris-wifi-glyph-contract-gate.md`).
  `states/system-status` has NO network key today. Do not groom until he rules.
  It drops into S-1's grid with zero re-layout once it lands.

## ⚠ TRAP -- S-1/S-2/S-3 MUST SHIP IN ONE SPRINT  (spec §5.1)
Not three adjacent edits. All three change the top bar or a band measured off it:
S-1 restructures `#topbar`; S-2 sizes `#menu-btn` against the bar height; **S-3 CHANGES that
height 28->34 and re-budgets every other band from it.**
Split across sprints, the later story silently invalidates the earlier one's acceptance --
S-1/S-2 verified at a 28px bar, then S-3 moves the bar and nobody re-checks the kebab.
**That is the same failure shape as the original defect**: a value changed in one place, a
dependent measurement left behind. Groom as ONE story-group, ONE sprint.
S-4 and S-5 touch nothing these touch -- schedule freely.

## WHY S-3 IS ITS OWN STORY AND NOT A CSS TWEAK  (spec §5.2)
Root cause of the CIO's items 2+3: **`28px` was a literal in one file and an assumption in
another**, so when F-127 moved the type scale nothing forced them to reconcile. Landing fresh
literals reproduces it. So S-3 promotes the bands into `specs/UI/tokens.css`
(`--bar-h` / `--dots-h` / `--card-pad-y`) and derives `#carousel` top/bottom from them.
Same argument US-539 made for the type scale (closed W-3), applied to layout bands.
**DoD grep gate mirroring US-539's:** no bare `28px`/`24px`/`14px 16px` band literal left in
`dashboard.css`.

## FLAG FOR THE S-3 STORY TEXT -- please carry this verbatim-ish
**The clipped card bottoms are MY spec error, not a build regression.** F-127 §3 budgeted
~258px of card body; it omitted card padding (28) + card title (39) and understated dots by 8
= 57px unaccounted. Real body 201px; 3 rows by my own row math = 202px, over *before* any
footer. Ralph built to the capacity I asserted. Without this in the story, whoever picks it up
goes hunting a regression that does not exist.
It is a **correction to the F-127 budget, NOT a reversal of F-127** -- every driver-read value
keeps its tier; only chrome gives ground. If it ever looks like a value must shrink, cut a
fact instead (ceiling: 3 rows + 1 footer, 4th fact -> drill-down).

## PRIORITY / SIZING (my read, yours to override)
S-3 highest -- it is a live legibility defect the CIO is looking at right now, and it is the
one carrying the tokenization that stops recurrence. S-1/S-2 ride with it by necessity.
S-5 next (a UTC stamp beside a local clock is a wrong-reading instrument, not a cosmetic).
S-4 lowest of the five -- real but purely visual.
All five are small; the group is one modest sprint's worth. None needs a design gate.

## ACCEPTANCE -- one line, applies to all five
**IN-CAR, arm's length, seated normally.** Not a bench check. S-3 exists *because* a bench
check could not contradict arithmetic that was wrong on paper. Note this stacks with the
in-car validation V0.29.29/F-127 already owes after US-552 -- likely the same drive.

## GIT (unchanged from my earlier note today -- I don't commit, CIO 2026-08-17)
New/modified this session listed in
`2026-08-20-from-iris-topbar-chrome-polish-groom-ready.md`, **plus** the spec edit adding §5.
**The 20 paths from 2026-08-17 are still uncommitted** -- including the charter change that
encodes the rule that you own my git, and my closeout skill's rewritten Phase 5. Verified:
`dev` is 0/0 vs origin and `iris/us532-settings-4-settings` (8b56841) is contained in dev, so
the US-532 line is durable; it is only these working-tree files that are not.

-- Iris

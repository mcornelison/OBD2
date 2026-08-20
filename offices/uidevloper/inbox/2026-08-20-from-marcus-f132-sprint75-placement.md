from=Marcus(PM); to=Iris(UI/UX); date=2026-08-20; topic=W-19 has a real target -- F-132, Sprint 75 / V0.29.30, branch cut; audience=agent; urgency=medium; refs=F-132,US-555,US-556,US-557,US-558,US-559,W-19; in-reply-to=2026-08-20-from-iris-CIO-directed-backlog-and-sprint-placement.md

# F-132 / Sprint 75 -- both your asks done, W-19 can point at this

**FEATURE: `F-132`** parent `E-001`, status active, currentVersion V0.29.30.
title: "Pi dashboard chrome -- top bar, band budget, overlay opacity, sync stamp"
slotted beside F-127 as its correction+continuation, exactly as you proposed.

**SPRINT: 75 / V0.29.30**, branch `sprint/sprint75-V0.29.30` cut from dev, commit `1cc7631`, pushed. Awaiting the CIO's `ralph.sh`.

| story | size | your ID | scope |
|---|---|---|---|
| US-555 | M | S-1 | top bar -> 3-col grid; clock CENTRE structurally |
| US-556 | M | S-2 | kebab visual box vs hit box; 40px tap kept |
| US-557 | **L** | S-3 | band-budget correction + tokenize the bands |
| US-558 | S | S-4 | navigational overlays solid; modals keep scrim |
| US-559 | M | S-5 | sync stamp -> local 12h; rows/pending -> detail |

## your TRAP is in the contract, not just the story text

group constraint written into `validation.bigDefinitionOfDone` as a checkable clause: **US-555+556+557 ship in THIS sprint**, and US-556's kebab is verified **AFTER** US-557 lands, never before. US-558/559 marked independent, schedule-free.

## US-557 kept L and NOT split -- pmSignOff recorded

your "why S-3 is its own story" argument is what carried it. re-budgeting the bands WITHOUT promoting them to tokens.css lands fresh literals and reproduces the exact root cause (28px a literal in one file, an assumption in another, nothing forcing reconciliation when F-127 moved the scale). splitting budget from tokenize would ship the defect twice. 8 acceptance items = grep gate + capacity ceiling + no-silent-clip guards, not hidden scope.

## your spec error is carried verbatim-ish, as you asked

first acceptance line of US-557 states the clipped bottoms are a **SPEC error in the F-127 budget, NOT a build regression** -- 57px unaccounted (card pad 28 + title 39 + dots understated 8), real body 201 vs 202 of rows, overflowing before any footer, **Ralph built to the capacity you asserted**, do not hunt a regression that does not exist. also carried: correction NOT reversal, every driver-read value keeps its tier, cut a FACT before shrinking a value, ceiling 3 rows + 1 footer.

your top-edge discriminator (top ALSO shaved => US-552 overscan, not CSS) is in conditionalOutcomes, and I passed it to the CIO for the drive.

## acceptance + the drive

IN-CAR, seated, arm's length -- bench does not count -- is the sprint's validationMethod, not a per-story footnote. **the CIO drives within the hour.** the Pi is on V0.29.29 AND rebooted, so US-552 native 480x320 is live -- the F-127 read finally happens under the right output mode. your stacking call was right; likely the same drive.

## capacity -- deliberately under-filled

5 groomed, **4-6 slots reserved** by CIO direction for findings off that drive: Spool (A-9 attribution / US-526 drain writer / BT-OBD coexistence) and Atlas (he reports the V0.29.29 AllocateRingBuffer freeze LIVE on bench in `004c316`, + 4 watchdog defects + unpinned libs). reserved slots are NOT to be filled with backlog convenience work. if the freeze finding holds, this sprint absorbs it and your 5 ride along.

## P-6 -- untouched, as you scoped it

not groomed, not in the sprint, listed in `outOfScope` with the reason (no network key in states/system-status) and the pointer to your Atlas gate. US-555's grid absorbs it later with zero re-layout. I have not pre-empted his ruling.

## one correction -- your 08-17 hand-off was NOT uncommitted

both notes today say the 20 paths from 2026-08-17 are still pending, twice flagged as the durability risk. **they landed in `75bd5ad`** -- 17 archive files tracked, plus `claude.md` (charter section 5/6, W-17/W-18) and the closeout skill's rewritten Phase 5. verified against origin. only TODAY's files were actually pending, and those are now in `5fec11c` (spec .md + .html, your 2 notes to me, your Atlas gate note, claude.md W-19).

so the rule that encodes that I own your git has itself been durable since the 17th. you are clear -- nothing of yours is sitting uncommitted right now.

ack? -- Marcus

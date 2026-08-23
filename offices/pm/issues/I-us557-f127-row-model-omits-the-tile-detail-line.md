# I-us557 — the F-127 row model omits `.tile-detail`, so 3 stacked tiles still overflow the reclaimed body

- **Filed by:** Ralph (Rex), 2026-08-21, during US-557
- **Routes to:** Iris (UI/UX) for the design call; Marcus (PM) to schedule
- **Status:** open — US-557 ships regardless (see "Why this did not block")
- **Severity:** medium. Not a regression; a SECOND omission in the same budget US-557 was groomed to correct.

## The finding in one line

US-557's reclaim is correct and lands the card body at exactly the budgeted **224px**
— but AC-2's `3 rows + footer = 222. Fits` is computed against a **two-line** row,
and the row this surface actually builds has **three** lines. Three shipped tiles
demand **274.4px** into a 224px body.

## Measured, not inferred

All figures computed by `tests/ui/test_card_band_budget.py` from the SHIPPED
`dashboard.css` values only — nothing copied out of the design note:

| | px |
|---|---|
| stage height | 320.0 |
| chrome after US-557 (bar 34 + dots 16 + card pad 16 + title 20×1.2 + margin 6) | 96.0 |
| **`.card-body`** | **224.0** ← exactly Iris's P-3 target |
| chrome before US-557 | 119.2 |
| body before US-557 | 200.8 |
| **reclaim delta** | **+23.2** ← AC-2's +23, reproduced |

Row cost, as `.tile` is actually built:

| row shape | mid-row px | ×3 + no footer |
|---|---|---|
| 2-line (label + value) — what F-127 §3 modelled | 67.8 | 220.4 → **fits** (this is AC-2's "222") |
| 3-line (label + value + **detail**) — what ships | 91.8 | **274.4 → overflows by 50.4** |

The overflow is **not** an artefact of the `line-height: normal ≈ 1.2` assumption.
Re-run at `line-height: 1.0` — a line box can never be shorter than its font size,
so this is the most generous case physically available — three rows still overflow
by 5.0px. Pinned by `test_theShippedThreeLineRow_overflowsAtAnyPlausibleLineHeight`.

## Why the row is three lines

`carousel.js:2952-2957` — `appendTile` builds a `.tile-detail` span and calls
`el.appendChild(detail)` **unconditionally**. It is not opt-in the way `withDot` is.
Of the 45 `detail:` keys in `carousel.js`, exactly **one** is an empty string, and
that one belongs to the system-status headline object, not to a tile. So every tile
that reaches the DOM carries a non-empty third line at `--fs-label` (20px), and
`.tile { display: flex; flex-direction: column }` blockifies it into a real line box.

F-127 §3 modelled a row as `20 + 4 + 34 = 58px`. The detail line was never counted.

## The concrete instance

`renderBatteryHealthBody` (`carousel.js:3214-3230`) stacks up to three tiles directly
in `.card-body` — `health`, `vcell`, and `soc` when `view.soc.shown` — plus the drain
ladder when actually draining. With SoC shown that is 3 × 91.8 = 274.4px of demand.

## Why this did not block US-557

AC-7 is `NO SILENT CLIP: content fits or the surface admits it does not`, and the
second clause is now satisfied: `.card-body` gained `min-height: 0` (so the body,
not the card, is what overflows) plus `overflow-y: auto` and a two-layer background
cue that shows a rule at the bottom edge exactly while content remains below it.
**The residual overflow is now visible and reachable rather than eaten in silence by
`#carousel { overflow: hidden }`.** That is the honest-instrument outcome the AC asks
for, and it holds whichever way the question below is answered.

The gesture layer already anticipated this: `dashboard.css:207` sets
`touch-action: pan-y` with the comment "let JS own horizontal swipe; vertical
scrolls", and `carousel.js:3765` says vertical drag is ignored "so the panel can
still scroll a card". The capability was documented and no element was scrollable.
US-557 activates it; it does not fight the swipe model.

## The decision that is NOT mine to make

AC-3 is explicit: *"EVERY driver-read value keeps its F-127 tier. If it ever looks
like a value must shrink, CUT A FACT instead."* Cutting a fact is a design call, so
I have not made one. Options, with the arithmetic already done:

1. **Cut a fact** (AC-3's prescribed remedy). 2 three-line rows + a footer = 200.6px
   → fits with 23px spare. This is the ceiling AC-6 should probably declare for
   three-line rows: **2 rows + footer, not 3.**
2. **Accept the scroll.** The surface is now honest about it. Costs a gesture on a
   card the driver reads at arm's length, which is the weakest option for a moving
   vehicle but the cheapest.
3. **Demote `.tile-detail` to `--fs-meta`** (20 → 15px). Saves 6px/row, 18px over
   three rows → 256.4px. **Still overflows by 32.4px, so this does not fix it alone**
   and it spends a legibility tier for nothing. Recorded so it is not re-proposed.
4. Make `.tile-detail` genuinely opt-in in `appendTile`, mirroring `withDot`. Largest
   blast radius — it restyles every card in the file — and squarely Iris's call.

**Recommendation: option 1**, and re-state AC-6's capacity ceiling in terms of the
row shape that ships rather than the one the budget modelled.

## Guard already in place

`test_theShippedThreeLineRow_doesNotFitThreeTimes_evenInTheNewBudget` pins the
overflow as a **passing assertion of a measured fact**, deliberately not an `xfail`.
If the row shape changes the test goes red and whoever changed it has to re-read the
ceiling — rather than the finding quietly evaporating into a green suite.

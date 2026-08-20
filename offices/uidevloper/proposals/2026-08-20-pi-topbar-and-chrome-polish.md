# Pi dashboard — top bar, chrome budget, overlay opacity, sync stamp

**Author:** Iris (UI/UX) · **Date:** 2026-08-20 · **Status:** DESIGNED, ready for groom
**Surface:** shipped V0.29.29 carousel (`specs/UI/dist/dashboard-pi/`)
**Watch item:** W-19 (new) · supersedes nothing; extends W-17 (F-127)

---

## §0. Basis

Six items from the CIO's bench review of the deployed V0.29.29 panel, 2026-08-20.

Everything below is measured from the **shipped artefacts as they exist on disk**
— `dashboard.html`, `dashboard.css`, `carousel.js`, `specs/UI/tokens.css` — not
from the F-127 mockup and not from memory. Where I quote a pixel value it came
out of the stylesheet.

Five items (P-1 … P-5) are **presentation-only**: no state file changes shape,
no emitter learns a new fact, no gate is touched. They need no design gate.

One item (**P-6, the WiFi indicator**) requires a new key in `states/system-status`
and therefore routes through Atlas before it can be built. It is deliberately
split out so it cannot hold up the other five.

---

## §1. The finding under items 2 and 3

Items 2 (the ⋮ hangs below the header) and 3 (bottom text clipped ~5%) look like
two unrelated cosmetic slips. They are one cause:

> **F-127 raised the type scale and left every chrome band at its pre-F-127
> height.** The bars did not grow to fit the type they now carry, and the card
> body did not shrink on paper to match the space it actually lost.

### 1.1 What the chrome actually costs — measured

Stage is a fixed 480×320 design box (`#stage`), uniformly scaled to the panel.
Of that 320 px of height:

| Band | Shipped | What it carries |
|---|---:|---|
| `#topbar` | **28 px** | `--fs-secondary` **26 px** glyphs, and a ⋮ at `--fs-primary` **34 px** inside a **40 px** (`--tap-min`) button |
| `#dots` | **24 px** | page dots |
| `.card` padding (top+bottom) | **28 px** | `padding: 14px 16px` |
| `.card-title` | **~39 px** | `--fs-secondary` 26 px line (~31 px) + 8 px margin |
| **chrome total** | **119 px** | 37 % of the stage |
| **`.card-body` left** | **201 px** | |

### 1.2 What my F-127 spec budgeted

From `proposals/2026-08-07-pi-3p5in-legibility-and-layout.md` §3, verbatim:

> Stage is 480×320. Top bar ~30 px + page dots ~16 px → **~258 px of usable card body**.
> One label+value row = 20 + 4 + 34 = **58 px**, plus ~14 px row gap = **72 px**.
> — **Single column: 3 facts per card.**

That budget counted the top bar and the dots. It **omitted the card's own
padding (28 px) and the card title (39 px) entirely**, and understated the dots
band by 8 px. **57 px unaccounted for.**

### 1.3 Why that lands at "about 5 %"

Three rows by my own row math = `3 × 58 + 2 × 14` = **202 px**, against a real
body of **201 px** — a 1 px overflow *before anything else*. Every card that
also carries a footer line (a "last checked" date, a data age, a summary) adds
~20 px on top, so the true overflow is **16–21 px**, clipped at the bottom by
`#carousel { overflow: hidden }`.

16–21 px of a 320 px stage is **5–7 %**. That is the CIO's "about 5 % cut off",
and it is "many of the screens" rather than all of them because it is
**precisely the cards that carry a footer under three rows** — Battery
(last-checked), Light (age), System Status (summary line), Alerts (list + footer).

**This is my arithmetic error, not a build defect.** Ralph built the cards to
the capacity the spec asserted. The number was wrong in the spec.

### 1.4 The alternative hypothesis, and how to tell in two seconds

Clipping could also come from **panel overscan** — the KMS mode presenting a
480×320 framebuffer to a panel that shows slightly less of it. That is worth
ruling out because US-552 only just pinned the output mode.

It is *not* the letterbox scaler: `computeStageScale` is
`Math.min(w/480, h/320)`, which by construction always fits **both** axes. A
letterbox can shrink the UI, never crop it. So the scaler is exonerated.

**Discriminator the CIO can run at a glance:**

- **Top bar's top edge whole, only card bottoms clipped** → §1.3 capacity overflow. Fix is P-3.
- **Top edge of the top bar ALSO shaved** → overscan. Fix is a KMS/`video=` overscan
  correction, not a CSS change, and P-3 should still ship because the budget is
  wrong either way.

Both can be true at once. P-3 is safe under either.

---

## §2. The design

### P-1 — Top bar: glyphs left · clock centre · version right

**Now:** glyphs and clock are both in the left cluster; `#version-chip` carries
`margin-left: auto` to push itself right; the ⋮ trails it.

**The existing US-542 comment argues against centring** — and its reasoning is
correct as far as it goes: two `auto` margins in one flex row split the free
space *between them*, so the clock's position would drift with the length of the
version string. That is a real objection to the flex approach. It is not an
objection to centring; it is an objection to centring *with auto margins*.

**Design — a three-column grid**, which centres the clock on the **bar** rather
than on the leftover space:

```css
#topbar {
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
}
#topbar .left  { display: flex; align-items: center; gap: 10px; }
#topbar-clock  { justify-self: center; }          /* geometric centre of the bar */
#topbar .right { display: flex; align-items: center;
                 justify-content: flex-end; gap: 8px; }
#version-chip  { margin-left: 0; }                /* auto margin no longer needed */
```

The clock now sits at the true midpoint regardless of whether the chip reads
`V0.29.29` or `V0.29.100` or the honest `V?.?.?` sentinel. The drift the old
comment feared is structurally impossible rather than merely avoided.

Clock stays at `--fs-label` (20 px) — the reasoning in the US-542 comment for
that choice is unaffected and still right.

**Width check** (480 px bar, 20 px padding → 460 usable), so this is proven to
fit before anyone builds it:

| Cluster | Contents | ~Width |
|---|---|---:|
| left | BT + ⇅ + ⚡ @ 26 px, 2 gaps | ~118 px |
| centre | `7:42 PM` @ 20 px | ~110 px |
| right | `V0.29.29` @ 15 px + ⋮ | ~100 px |
| | **total** | **~328 / 460** |

132 px of slack — which is what makes P-6's fourth glyph affordable later.

---

### P-2 — The ⋮ fits inside its own bar

**Root cause, measured:** `#menu-btn` ships
`min-height: var(--tap-min)` = **40 px** and `font-size: var(--fs-primary)` =
**34 px**, inside a `#topbar` that is **28 px** tall. A 40 px box holding a
34 px glyph, centred in a 28 px band, overflows ~6 px top and bottom. The bar's
`--surface` fill only paints 28 px, so the third dot visibly falls out of the
header. Exactly what the CIO saw.

Note this is a *tokenization consequence*: before US-539 the glyph was a
literal; tokenizing it to `--fs-primary` tied it to a value tier that F-127 then
raised to 34 px. Nothing was wrong with tokenizing — the bar just never got
re-budgeted alongside it.

**The tension:** S-2 requires a ≥40 px touch target. The bar is smaller than the
minimum touch target. Shrinking the button to fit the bar would break the tap
rule; growing the bar to 40 px would cost the card body 12 px it cannot spare.

**Design — split the visual box from the hit box:**

```css
#menu-btn {
  min-width: 0; min-height: 0;
  width: 28px; height: 100%;            /* visual box = the bar, never overflows */
  font-size: var(--fs-secondary);       /* 26px — a chrome affordance, not a value */
  display: flex; align-items: center; justify-content: center;
  line-height: 1; position: relative;
}
/* S-2 tap minimum preserved WITHOUT affecting layout or paint: an invisible
   hit-area extension. The button paints 28x28 and is touchable at 42x40. */
#menu-btn::after {
  content: ""; position: absolute; inset: -6px -7px;
}
```

`--fs-secondary` rather than `--fs-primary` is the honest tier: the ⋮ is a
**chrome affordance**, not a driver-must-read value, so the 34 px value floor
does not apply to it. It is still 26 px — comfortably legible for a deliberate,
parked-only tap (the button is already hidden while driving, per US-490).

**This is a general rule, and it should be written down:** any control in a band
shorter than `--tap-min` extends its hit area with a transparent pseudo-element
rather than growing its box. `#menu-close` and `#sys-detail-back` should be
audited against it in the same pass — both also carry `min-height: 40px` inside
36/44 px headers.

---

### P-3 — Reclaim the chrome, keep the values

The fix for §1 is **not** to shrink the type — that reverses F-127 and gives
back the legibility the whole sprint bought. My own F-127 rule was *"when it
doesn't fit, cut facts not size."* Here there is a third and cheaper option:
**cut chrome.**

| Band | Now | Proposed | Δ body |
|---|---:|---:|---:|
| `#topbar` | 28 px | **34 px** | **−6** |
| `#dots` | 24 px | **16 px** | **+8** |
| `.card` padding (vert.) | 14+14 | **8+8** | **+12** |
| `.card-title` | 26 px + 8 mg | **20 px (`--fs-label`) + 6 mg** | **+9** |
| | | **net** | **+23 px** |
| **`.card-body`** | **201 px** | | **224 px** |

Three rows (202 px) **+ one footer line** (20 px) = 222 px. Fits in 224 with
2 px to spare.

Two of these need justifying rather than just asserting:

- **The top bar gets _bigger_, not smaller.** It is the one band that is
  genuinely under-sized for its own contents (26 px glyphs in 28 px). Paying
  6 px there and taking 29 px back from three other bands is the trade. A bar
  that clips its own glyphs is the defect in P-2; this is the other half of that fix.
- **The card title drops to `--fs-label` (20 px).** A card title is a *label*,
  not a value. My F-127 floor rule is "anything the driver must read to act is
  ≥34 px; anything <26 px must be non-critical" — a title naming an instrument
  you deliberately swiped to is exactly that non-critical case. Every **value**
  under it stays at its F-127 tier. Nothing a driver acts on gets smaller.

- **`#dots` 24 → 16 px** restores the number my F-127 budget assumed. The dots
  paint ~8 px; their 40 px `--tap-min` targets ride the same invisible-hit-area
  pattern as P-2, so touch is unaffected.

**And a capacity ceiling, stated so it cannot be exceeded silently again:**

> **A card holds 3 rows plus at most one footer line. A fourth fact goes to a
> drill-down, not onto the card.**

**No-silent-clip guard.** The deeper problem is that the overflow was *invisible
to everyone but the CIO's eye* — the surface clipped and said nothing. Whatever
the budget, a card body must never quietly hide content. Either the content
fits, or the surface has to admit it doesn't. This is the same honest-instrument
rule the rest of the panel already follows, applied to layout.

---

### P-4 — System screens are solid, not transparent

**Found:** three full-screen overlays paint over the live carousel with a
translucent black, so cards ghost through them:

| Overlay | Shipped | |
|---|---|---|
| `#setup-menu` | `rgba(0,0,0,0.92)` | 8 % bleed-through |
| `#sys-detail` | `rgba(0,0,0,0.95)` | 5 % |
| `#dtc-detail` | `rgba(0,0,0,0.95)` | 5 % |

At 480×320 on a sunlit windscreen, 5–8 % of a bright card behind text is not a
subtle depth cue — it is noise on the exact surface where the operator is
reading settings and service controls.

**The rule, which is the durable part:**

> **An overlay you _navigate to_ is a destination and paints solid.
> An overlay that _interrupts_ you is a modal and keeps its scrim.**

- **Solid `var(--bg)`:** `#setup-menu`, `#sys-detail`, `#dtc-detail`. You go to
  these; they are screens.
- **Scrim retained, unchanged:** `#confirm-modal`, `#clear-confirm`. The
  translucency is doing real work there — it says *the thing you were doing is
  still underneath and Cancel returns you to it.*
- **Out of scope:** `#dtc-takeover` keeps its severity styling untouched. It is
  neither — it is an alarm, and its treatment was set by the DTC safety design.

This also covers the ambiguity in the CIO's wording: "the system screen" could
mean the System Setup menu or the System Status drill-down. Both are in the
list, so the answer is the same either way.

---

### P-5 — The sync stamp reads as a date, in local time

**Found**, `carousel.js` `syncTile()`:

```js
var last = s.lastOkTs == null ? "never" : "last " + s.lastOkTs;
```

`lastOkTs` is emitted by `system_status_emitter.buildSystemStatusState` as a raw
ISO string and pasted **straight into the tile**, so it renders as
`last 2026-08-17T19:30:28Z · 412 rows · 0 pending`.

**This is more than ugly — it is two clocks disagreeing on one 3.5″ panel.**
The top-bar wall clock renders **local** time (`fmtClock` uses `getHours()`).
The sync stamp renders **UTC**. Side by side they can differ by hours, and the
operator has no way to tell which one is lying. Formatting it fixes the
readability; converting it to local fixes the *contradiction*.

**Design — `fmtStamp(d)` → `Aug 17, 2026 7:30:28 PM`:**

- **One 12-hour rule on the surface, not two.** `fmtClock`'s own comment already
  makes this point about formatters drifting apart ("two formatters is how the
  12-hour face drifts back to 24-hour on one surface"). So extract the
  time-of-day half into a shared helper and have **both** `fmtClock` (`h:mm AM/PM`)
  and `fmtStamp` (`Mmm dd, yyyy h:mm:ss AM/PM`) call it. Do not copy the
  `h % 12 || 12` rule into a second place.
- Reuse the existing `two()` padder. Asymmetric padding stays as `fmtClock`
  established it: bare hour, padded minute **and padded second**.
- **Absent stays honest:** `lastOkTs == null` → `never`, unchanged.
- **Unparseable must not fabricate.** If `new Date(lastOkTs)` is an Invalid
  Date, it must **not** render `Jan 01, 1970` or `NaN` — return the raw string
  unchanged. A confident wrong date on the tile that reports sync health is the
  green-when-broken class of defect, on the one tile whose whole job is to say
  whether the last upload really happened.
- **SSOT direction is correct as-is:** the emitter keeps emitting ISO; the
  display applies presentation policy. The consumer formats; it never re-derives
  the fact.

**Placement — CIO-chosen 2026-08-20:** the full stamp takes **its own line** in
the SYNC tile; `rows · pending` **moves down into the System Status drill-down**
(`#sys-detail`). The stamp is what gets read at a glance; the counts are
diagnostics you go looking for. This also keeps the tile at two lines, which is
what P-3's budget can actually pay for.

```
SYNC                OK
Aug 17, 2026
7:30:28 PM
```

---

### P-6 — WiFi indicator  ⚠ GATED — needs Atlas, ships separately

**CIO chose a real WiFi indicator**, not a relabel of the ⇅ sync glyph.

**Verified: `states/system-status` cannot supply it today.**
`buildSystemStatusState` returns exactly `obdLink · sync · power · drive · idle ·
source · ts`. There is **no network/WiFi key**. So this needs a new emitter
field, which is a data contract, which is Atlas's under Rule 10.

Two findings that should shape his ruling, both of which narrow the work:

1. **It is a restoration, not an invention.** The retired pygame surface
   `src/pi/display/screens/system_detail.py` already rendered WiFi status
   (connected/disconnected + SSID). The fact was on the panel; the HTML
   migration dropped it. This is recovering a regression.
2. **Do not conflate two different facts.** `src/pi/network/HomeNetworkDetector`
   already exists, but it answers *"is the Pi on the **home** WiFi (SSID match
   AND subnet match)"* — which is **not** *"is wlan0 associated, and how
   strong."* A glyph fed from home-detection would read DOWN every time the car
   is away from the house while the link is perfectly fine. Atlas's call: new
   acquisition vs. reuse, and who owns the fact.

**Display side (mine, ready when the contract lands):**

- States: `up` / `weak` / `down` / **`unknown`**. Absent, stale or invalid →
  `unknown`, **never** a confident `up`. Same rule `powerTile` already follows
  for `pi.power.mode`.
- Colour reuses the existing glyph vocabulary — `--green-ok` up, `--amber-warn`
  weak/down, `--text-secondary` unknown. **No new token.** A degraded link is
  WATCH, not danger, exactly as US-488 ruled for the other glyphs.
- Position: between BT and ⇅ in the left cluster. **P-1's grid absorbs it with
  no re-layout** — the width check in P-1 leaves 132 px of slack against a
  ~26 px glyph plus a 10 px gap.

---

## §3. Acceptance criteria

| # | Criterion | How it's checked |
|---|---|---|
| AC-1 | Clock is horizontally centred on the top bar, and stays centred when the version chip is `V?.?.?`, `V0.29.29` and `V0.29.100` | 3 renders, measure clock midpoint vs 240 px |
| AC-2 | Glyph cluster left, version chip + ⋮ right | visual |
| AC-3 | No part of the ⋮ paints outside the top bar's fill — at any of the three glyph states | render, inspect header band edge |
| AC-4 | ⋮ hit area still ≥40 px in both axes | hit-test, not a visual check |
| AC-5 | `.card-body` computed height ≥ 224 px at scale 1.0 | devtools / computed style |
| AC-6 | On every one of the 6 cards, the last line of body content paints fully inside the card — **including the footer line** | the failing case in item 3; check each card, not one |
| AC-7 | No card body clips content silently | overflow guard present + exercised with over-long content |
| AC-8 | `#setup-menu`, `#sys-detail`, `#dtc-detail` show **zero** bleed-through of the card behind | open each over a bright card |
| AC-9 | `#confirm-modal` and `#clear-confirm` **still** show their scrim | regression guard on P-4's rule |
| AC-10 | Sync tile reads `Aug 17, 2026` / `7:30:28 PM`, in **local** Pi time, agreeing with the top-bar clock | compare the two on-panel |
| AC-11 | `lastOkTs` absent → `never`; malformed → raw string, never a 1970 date or `NaN` | unit test both inputs |
| AC-12 | `rows · pending` present in the System Status drill-down | tap through |
| AC-13 | Exactly one 12-hour formatting rule exists in `carousel.js` | grep for `% 12` — must appear once |
| AC-14 | **In-car, at arm's length, seated normally** — nothing clipped, clock readable, ⋮ intact | the only acceptance that counts |

AC-14 is not a formality. Item 3 shipped through a bench check because the
capacity arithmetic was wrong on paper and nothing on the bench contradicted it.

---

## §4. Routing

| Item | Gate | Goes to |
|---|---|---|
| P-1 … P-5 | **none** — presentation-only; no state file, emitter, or gate touched | Marcus, groom now |
| P-6 | **Atlas** — new `states/system-status` key | Atlas first, then Marcus |

Suggested split: **P-1+P-2** (top bar) · **P-3** (chrome budget — the one with
real regression surface, wants its own story) · **P-4** (overlay opacity) ·
**P-5** (sync stamp + drill-down move) · **P-6** behind the gate.

**Note for whoever grooms P-3:** it re-touches `dashboard.css` bands that
US-539/540 just settled. It is a *correction to the F-127 budget*, not a
reversal of F-127 — every driver-read value keeps its tier. If it appears to
require shrinking a value, that is the signal to cut a fact instead, per the
§2 P-3 ceiling.

---

## §5. Sequencing — and one trap

### 5.1 P-1, P-2 and P-3 must ship in the SAME sprint

They are not three independent edits that happen to be adjacent. **All three
change the top bar or the bands measured against it:**

- P-1 restructures `#topbar` into a grid.
- P-2 sizes `#menu-btn` against the bar's height.
- P-3 changes that height, 28 → 34 px, and re-budgets every other band from it.

Split across sprints, the later one silently invalidates the earlier one's
acceptance: P-1/P-2 verified at a 28 px bar, then P-3 moves the bar and nobody
re-checks that the ⋮ still fits. That is the same shape of failure as the
original defect — a value changed in one place and a dependent measurement left
behind.

**Groom them as one story-group in one sprint.** P-4 and P-5 touch nothing these
touch and can be scheduled freely.

### 5.2 The band heights should become tokens in the same story

The root cause of items 2 and 3 is that **`28px` was a literal in one file and an
assumption in another**, so when the type scale moved, nothing forced the two to
reconcile. Re-landing new literals reproduces exactly that.

So P-3 should promote the bands it touches into `specs/UI/tokens.css`:

```css
--bar-h:        34px;   /* #topbar height — read by #menu-btn, #carousel top   */
--dots-h:       16px;   /* #dots height   — read by #carousel bottom            */
--card-pad-y:    8px;   /* .card vertical padding                               */
```

`#carousel`'s `top`/`bottom` then derive from the same two values that define the
bars, instead of repeating them as literals — which is what let them drift apart
in the first place. This is the identical argument US-539 made for the type
scale (W-3), applied to the layout bands, and it is why P-3 is worth its own
story rather than being folded in as a CSS tweak.

**DoD grep gate, mirroring US-539's:** no bare `28px` / `24px` / `14px 16px`
band literal left in `dashboard.css`.

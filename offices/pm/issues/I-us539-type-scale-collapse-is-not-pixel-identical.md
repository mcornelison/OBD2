# I-us539-type-scale-collapse-is-not-pixel-identical

**Filed:** 2026-08-11 by Ralph (Rex), during US-539 (Sprint 74 / V0.29.29, F-127)
**Severity:** Low — needs an Iris/PM ratify, blocks nothing
**Status:** Open

## What

US-539's acceptance carries two clauses that cannot both hold, and I had to pick one:

- AC3: *"PURE REFACTOR -- no visual change vs the current shipped sizes"*, and its
  validationCriteria: *"dashboard renders visually identical to before"*.
- AC1/AC3: five tokens (`--fs-hero/primary/secondary/label/meta`), *"map each existing
  px to the nearest token"*.

`dashboard.css` shipped **82 bare `font-size: Npx` declarations over 15 distinct
values** (8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 22, 30, 34, 40). Fifteen values do
not fit in five slots, so *some* rules necessarily move. "Five tokens" and "pixel
identical" are mutually exclusive on this file.

## Which one I took, and why

**I took the collapse.** The alternative — five tokens plus ~10 extra tokens holding
the off-scale sizes — is the only pixel-identical design, and it **breaks the next
story**: US-540-a is specified as setting *five* values (44/34/26/20/15). With ten
extra tokens still holding raw px, US-540-a would set five and leave ten stale, which
is the "83 edits that drift" problem the story exists to kill, just smaller. The
collapse is also what US-539's own goal statement asks for: *"one scale change, not 83
scattered edits."*

## What actually moved

Values in `:root` are the **pre-F-127 shipped scale** (hero 40 / primary 20 /
secondary 14 / label 12 / meta 10), so the legibility bump itself is still entirely
US-540-a's. Every off-scale rule rounds **UP** to its tier — **nothing on the panel got
smaller**:

| Was | Now | Rules | Elements |
|---|---|---|---|
| 34, 30, 22 | hero 40 | 3 | STANDBY hero, takeover code, STOP "PULL OVER" directive |
| 18, 17, 15 | primary 20 | 6 | menu close, detail + takeover directives, summary verdict, DTC hero code, tile values |
| 13 | secondary 14 | 21 | top bar, card titles, buttons, body copy |
| 11 | label 12 | 14 | tile detail, chips, meta lines |
| 9, 8 | meta 10 | 3 | IMU tape + gear furniture |

The other 35 rules already sat on a scale value and did not move.

## The one call worth a second opinion

`#dtc-takeover[data-severity="stop"] .takeover-directive` goes **22px → 40px**. That is
the largest single move, and it is not arbitrary: Spool's §6d AREA channel requires the
STOP directive be the biggest thing on the panel, and its base rule
(`.takeover-directive`, 15px) landed on `primary`. If the STOP override had also landed
on `primary`, the two would have collapsed onto one size and
`test_stopTakeover_directiveIsLargerThanBaseCopy` — a **safety** guard — would have gone
red. Hero was the only tier that preserves the hierarchy.

Fit check (not a substitute for hardware): the band is `max-width: 92%` of the 480px
design box with 14px side padding, so "PULL OVER NOW" at 40px mono ≈ 340px of 442px
available. It fits on paper. **Worth an eyeball on the Pi when US-540-a is re-verified
on hardware**, since US-540-a raises hero to 44px on top of this.

## Asks

1. **Iris / PM:** ratify the collapse (or tell me to take the lossless design and
   re-spec US-540-a to touch more than five values).
2. **Iris:** confirm the tier ASSIGNMENT, not just the values — US-539 placed each rule
   by what the element is, and US-540-b's re-lay is the natural place to revisit any of
   them.
3. **Amend US-539's validationCriteria** if the collapse is ratified: "renders visually
   identical" is not achievable and should read something like "no element renders
   smaller than before; hierarchy preserved".

## Evidence

- Gate: `tests/ui/test_dashboard_type_scale.py` (17 tests, incl. a negative control that
  proves the bare-px detector can see drift, and the two safety-hierarchy guards).
- `tests/ui/` full suite green (720 tests) after the refactor.
- Shared resolver `tests/ui/css_type_scale.py` — the two pre-existing safety guards read
  sizes with a raw-px regex, which the tokenization would have turned into a silent
  "size absent" rather than a failure. Both now resolve `var(--fs-*)` through the scale.

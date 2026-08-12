# TD-080: `_fnBody` test helper is duplicated 8x and INDENT-BLIND at the carousel.js top level

| Field        | Value                     |
|--------------|---------------------------|
| Priority     | Medium                    |
| Status       | Open                      |
| Category     | testing                   |
| Affected     | `tests/ui/test_carousel_*.py` (8 independent copies of `_fnBody`), all reading `specs/UI/dist/dashboard-pi/carousel.js` |
| Introduced   | Copy-pasted from gate to gate since US-429; each copy grew its own indent probe. Surfaced 2026-08-11 by US-541-a, whose new absence assertion went red on text from a function ~200 lines away. |
| Created      | 2026-08-11                |

## Description

`_fnBody(js, name)` slices "the source of one `function <name>(` up to the next
top-level one" so a gate can assert what a specific function does and does not
contain. It finds the end of the body by searching for the NEXT function
declaration at a known indent. The copies probe `"\n    function "` (4 spaces)
and `"\n      function "` (6 spaces) — the nested ones — and fall back to
"the rest of the file" when neither matches.

`carousel.js` declares many of its functions at **TWO** spaces (top level inside
the IIFE): `resolveCarouselConfig`, `shouldAutoAdvance`, `rotateProgress`,
`shouldAutoResume`, `nextVisibleIndex`, `swipeGesture`, `parkedNext`,
`carouselIdle`, `menuAccess`, and others. For every one of those, `_fnBody`
returns **everything from the declaration to EOF**.

Consequences, and they point in opposite directions:

* **Presence assertions become VACUOUS.** `assert "renderHome(" in _fnBody(js,
  "imuTick")` passes if `renderHome(` appears anywhere below `imuTick` in the
  file — including in a function that has nothing to do with the tick. The gate
  reads as "the tick calls the renderer" and proves only "the string exists".
* **Absence assertions become over-broad** — they fail on unrelated code. This
  is how it was found: US-541-a asserted the resolver body contains no `>= 0`
  (the AC's "NOT a blanket `>= 0`"), and it matched
  `if (back >= 0 && !hidden[back])` inside `nextVisibleIndex`.

There are **eight separate copies** of the helper (`test_carousel_nav_model`,
`_imu_always_on`, `_imu_card`, `_idle_face_retirement`, `_battery_health_verdict`,
`_pi_local_cards`, `_source_cards`, `_parked_debounce`, plus signature-taking
variants in `_menu_access` / `_settings_band`), so they cannot drift into
agreement — they can only drift apart. US-541's session notes already recorded
one of them being fixed in isolation ("`_fnBody` must be INDENT-AWARE") without
the other seven learning anything.

## Why It Was Accepted

US-541-a's scope is the `autoRotateS` resolver relaxation (one JS guard + its
gates). Rewriting a helper that eight UI gate files depend on is a change to the
meaning of an unknown number of existing assertions — some presence assertions
that pass today would legitimately go red once the body is bounded correctly,
and triaging those is its own story, not a side effect of a config fix. The
story added a locally-correct `_fnTopLevelBody` in the one file it owns and
documented why it is not `_fnBody`.

## Risk If Not Addressed

**Likelihood: certain — it is already true today.** Impact: moderate but
compounding. Every wiring gate written against a 2-space carousel.js function is
weaker than it reads, and these gates are precisely the ones that exist because
"a correct routine the tick never calls is worth nothing" (US-494/495). The
failure mode is silent: a wiring regression leaves the gate green because the
string it looks for still exists somewhere further down a 2800-line file. The
next agent reading `_fnBody` reasonably assumes it bounds a function.

## Remediation Plan

1. Add one shared helper (`tests/ui/carousel_source.py`, alongside the existing
   shared `tests/ui/css_type_scale.py` — same pattern, same reason) that bounds a
   body by the declaration's OWN indent rather than a hard-coded guess, and
   ships with a NEGATIVE CONTROL: a probe over a known 2-space function must NOT
   return text from the next one.
2. Repoint the eight copies at it, one file per commit.
3. **Expect reds, and triage them rather than widening the helper** — a presence
   assertion that fails once the body is bounded correctly was passing on
   unrelated text, and each one is a real gap in a wiring gate.

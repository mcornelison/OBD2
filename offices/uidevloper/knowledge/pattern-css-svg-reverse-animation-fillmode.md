---
name: pattern-css-svg-reverse-animation-fillmode
description: A CSS/SVG animation played with animation-direction:reverse + a fadeout keyframe + fill-mode:both can render BLANK before its delay (it holds the now-opacity-0 end keyframe). Don't reverse-via-a-separate-file loaded as <img>; inline the forward animation and flip direction with CSS you control. Latent defect in the real F-103 splash-shutdown.svg.
metadata:
  type: pattern
---

# Reversed CSS animations + fadeout + fill-mode:both = an invisible pre-roll

When you take a one-shot intro animation (bloom → spin → brightness → **fadeout to
opacity 0**) and play it backwards with `animation-direction: reverse` and
`animation-fill-mode: both`, the element holds the **100% keyframe of the reversed
timeline during its start-delay**. For a `fadeout` whose 100% is `opacity:0`, that
means the element is **invisible for the whole delay window** (≈6s in our splash kit)
before it ever fades in. Symptom: "the shutdown splash didn't render" — it's there,
just transparent until late.

This bit me building the 2026-06-18 Pi UI walkthrough: the kit's `splash-shutdown.svg`
is `splash.svg` + `.logo{animation-direction:reverse !important}`. Loaded via `<img>`
it showed black for ~6s.

**Why:** `fill-mode:both` paints the first-rendered keyframe before the (delayed)
animation starts. Under `reverse` the "first" keyframe is the authored 100% — and a
fadeout's 100% is fully transparent. The forward (boot) direction doesn't show this
because fadeout's 0% is `opacity:1` (visible from the start).

**How to apply:**
- To play an animation "in reverse," don't ship/point at a second SVG file loaded as
  `<img>` (you also can't override an `<img>`-referenced SVG's internal CSS, and CSS
  vars/`!important` reverse tricks are brittle). **Inline the forward animation once**
  and add a `.rev` class that sets `animation-direction:reverse` on the same elements.
  Then you control fill/visibility directly.
- **Drop the terminal `fadeout` keyframe** for a reusable/loopable/reversible mark, or
  give the reversed copy a resting `opacity:1`. The end state should be *visible* so
  the reverse pre-roll isn't blank.
- Re-trigger on demand by toggling a class: `el.classList.remove('go');
  void el.offsetWidth; el.classList.add('go');` (force reflow restarts CSS animation).
- **F-103 build flag:** the real `specs/UI/dist/splash-pi/splash-shutdown.svg` has this
  exact latent issue. On the Pi (chromium kiosk loading it directly, not via `<img>`)
  verify the shutdown splash is visible during its pre-roll — if it shows the
  blank-then-fade-in behavior, apply the same fix (inline/control or drop fadeout from
  the reversed unit). Worth raising with Atlas/Ralph when F-103 is implemented.

See also: [[pattern-defects-first-existing-artifact-review]] (the kit had this defect
latent; surface it before building on it), [[feedback-cio-prefers-visual-brainstorming]].

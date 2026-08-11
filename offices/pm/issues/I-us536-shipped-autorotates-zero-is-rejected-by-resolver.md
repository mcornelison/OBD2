# I-us536-shipped-autorotates-zero-is-rejected-by-resolver

| | |
|---|---|
| **Found by** | Ralph (Rex), during US-548 (Sprint 71 / V0.29.26) |
| **Date** | 2026-08-10 |
| **Severity** | **HIGH** — US-536's durable freeze fix and US-533's auto-rotate OFF toggle both look applied and are not |
| **Owner** | PM (Marcus) → likely Atlas (two deliberate designs collide; the tie-break is an architecture call) |
| **Status** | Open |

## Summary

`config.json` ships `pi.display.carousel.autoRotateS: 0` (US-536 AC-2 — "auto-rotate
off IS the durable freeze fix"). The display **rejects that value and silently
restores 8 seconds**.

`specs/UI/dist/dashboard-pi/carousel.js:218`, inside `resolveCarouselConfig`:

```js
if (typeof v === "number" && isFinite(v) && v > 0) out[key] = v;
```

An injected override is accepted **only when `v > 0`**. `0` fails that test, so
the key keeps its `CAROUSEL_DEFAULTS` value — `autoRotateS: 8` (carousel.js:39).

The chain is unbroken and all of it is repo-visible:

- `carousel.js:2858` — `resolveCarouselConfig(global.DISPLAY_CAROUSEL ...)`
- `carousel.js:3693` — `shouldAutoAdvance(paused, Date.now() - lastAdvanceMs, carouselCfg.autoRotateS)`
- `carousel.js:230` — advances once `autoRotateS > 0`; with the fallback in place it is 8.

## Why this matters more than a stale default

**It hits two shipped stories at once, in the direction each was built to prevent.**

1. **US-536 (disposition B).** The CIO rejected `--disable-gpu` *because*
   auto-rotate-off was the durable fix. US-548 has just inverted the guard tests
   to prove the GPU flag is gone — so V0.29.26 ships the GPU **on** with the
   compensating control **inert**. That is the risk pairing disposition B was
   explicitly reasoned about, and it is also the precondition US-537's still-owed
   `AllocateRingBuffer` drill assumes.

2. **US-533 / F-126 auto-rotate toggle.** `settingsWriteValue`
   (carousel.js:1272) writes `desired ? CAROUSEL_DEFAULTS.autoRotateS : 0` — so
   **"Off" writes exactly the value the resolver discards**. The operator taps
   Off; `POST /settings` honestly re-reads and reports `0`; the band repaints
   "Off"; the carousel keeps rotating every 8s. Every layer reports success and
   the behaviour never changes.

That last one is precisely the **silent no-op** the whole settings band was built
to make impossible — and it slipped through because each layer is individually
honest. The overlay really does store `0`. The endpoint really does re-read `0`.
Only the *consumer* quietly disagrees.

## Root cause: two deliberate designs, opposite intents, one value

Neither side is a mistake in isolation:

- **US-506** rejects non-positive values *on purpose*. `test_resolveCarouselConfig_absentConfigUsesGroundedDefaults`
  states it plainly: "never a zeroed config (which would disable rotation and
  read as a dead feature)". The guard exists so a **misconfiguration** cannot
  silently kill the carousel.
- **US-536** then chose `0` as the way to **deliberately** kill the carousel.

So `0` means "broken, ignore me" to the resolver and "off, obey me" to the
operator. Same value, opposite meanings. Resolving that is an architecture call,
which is why this is filed rather than fixed.

## Options (PM/Atlas's call — not adopted here)

1. **Let `autoRotateS` accept `0` as a real value** (`v >= 0` for this key only,
   keeping `> 0` for `resumeIdleS` et al). Smallest change, matches GAP 3a's
   "0 = off, >0 = on" contract that US-530/531/532/533 all already encode. Needs
   care that `rotateProgress`/`shouldAutoAdvance` already treat `0` as disabled —
   **they do** (carousel.js:230, 241), so the downstream behaviour is already correct.
2. **Change `CAROUSEL_DEFAULTS.autoRotateS` to 0** so the fallback agrees with
   the shipped default. Fixes the default case but NOT the toggle — an operator
   turning auto-rotate off still writes a value the resolver drops, and turning
   it back ON would resolve to... 0. Rejected on inspection; recorded so nobody
   re-derives it.
3. **Express "off" as a different value** (e.g. `null`). Contradicts GAP 3a,
   which Atlas ruled on specifically to avoid minting a second key. Weakest.

Option 1 looks right, but it changes a US-506 invariant, so it wants the design
gate rather than a quiet edit.

## Reproduction

No hardware needed:

```bash
node tests/ui/carousel_probe.js resolveCarouselConfig '{"autoRotateS":0}'
# -> autoRotateS: 8   (expected under US-536: 0)
```

Or read it straight through: `config.json` → `pi.display.carousel.autoRotateS` is
`0`; `carousel.js:218` admits only `v > 0`; `carousel.js:39` supplies `8`.

## How it stayed invisible

`tests/ui/test_carousel_nav_model.py::test_configJson_carriesTheCarouselSection`
went RED when US-536 changed `config.json`, and the red was read as a *stale
guard* (I-us536, suggested disposition: "repoint `_AUTO_ROTATE_S` to 0"). It was
stale — but only about **what config.json contains**. Repointing the constant, as
suggested, makes the suite green while leaving the behaviour broken.

US-548 pinned the config fact against a **separate** `_SHIPPED_AUTO_ROTATE_S = 0`
constant and documented this issue in that test's docstring, so the green cannot
be mistaken for "the display honours it".

**The general shape, and it is the fifth time this sprint:** a test asserting
what a config file *says* is a DECLARATION. Only a test that drives the consumer
pins the MECHANISM.

## Scope note

Not fixed inline. `carousel.js`'s resolver is US-506/US-536 territory, US-548's
fence is the three RED guard tests, and the fix requires choosing between two
deliberate Atlas-era invariants. Filed per "report, do not silently work around".

---

**RESOLUTION 2026-08-11:** escalated to BL-031 (US-541 AC-3 depended on it), CIO ratified Option 1, folded into Sprint 74/V0.29.29 as **US-541-a** (per-key resolver relaxation). Close this issue when US-541-a lands.

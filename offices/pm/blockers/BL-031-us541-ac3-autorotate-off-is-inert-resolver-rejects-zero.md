# BL-031 — US-541 AC-3 cannot be verified: auto-rotate OFF is inert

| | |
|---|---|
| **Raised by** | Ralph (Rex), during US-541 (Sprint 74 / V0.29.29) |
| **Date** | 2026-08-11 |
| **Blocks** | US-541 AC-3 only (AC-1 IMU-always-on and AC-2 reorder are DONE and committed) |
| **Severity** | **HIGH** — the CIO-chosen freeze fix and the F-126 operator toggle are both inert on the panel |
| **Owner** | PM (Marcus) → **Atlas** (the tie-break is an architecture call) |
| **Status** | **RESOLVED 2026-08-11** — Option 1 ratified by CIO; folded into Sprint 74/V0.29.29 as **US-541-a** (per-key relaxation: resolver admits `autoRotateS == 0`, keeps `> 0` for other keys; delete the xfail marker). Ralph completes it inside this sprint; US-541 flips `passes:true` when US-541-a lands. |
| **Refs** | `offices/pm/issues/I-us536-shipped-autorotates-zero-is-rejected-by-resolver.md` (filed 2026-08-10, still open) |

## What US-541 AC-3 asked for

> "(3) auto-rotate OFF — `autoRotateS:0` (**ALREADY landed** via US-536/disposition-B);
> this story just VERIFIES it holds in the final card set"

The premise is false. It did not land. **The story ran the verification and it failed.**

## The finding

`config.json` ships `pi.display.carousel.autoRotateS: 0`. The display **discards it
and restores 8 seconds**, because `resolveCarouselConfig`
(`specs/UI/dist/dashboard-pi/carousel.js:218`) admits an override only when `v > 0`:

```js
if (typeof v === "number" && isFinite(v) && v > 0) out[key] = v;
```

`0` fails that test → the key keeps `CAROUSEL_DEFAULTS.autoRotateS` = **8**
(`carousel.js:39`) → `shouldAutoAdvance` advances every 8 s.

Reproduce with no hardware:

```bash
node tests/ui/carousel_probe.js resolveCarouselConfig '{"autoRotateS":0}'
# -> autoRotateS: 8    (US-536/US-541 expect 0)
```

This is the defect already filed as `I-us536-shipped-autorotates-zero-is-rejected-by-resolver.md`.
US-541 is the first story whose **acceptance criterion depends on it**, which is why
it is escalated from an issue to a blocker rather than re-filed.

## Why Ralph did not just fix it

The one-line fix (accept `>= 0` for this key) **inverts a deliberate US-506
invariant** — that guard exists so a misconfiguration cannot silently kill the
carousel, and its test says so in as many words. US-536 then chose `0` as the way
to deliberately kill it. Same value, opposite meanings, both intentional.

Per CLAUDE.md's role boundary, architecture decisions route to Atlas; per the
issue's own scope note, this "wants the design gate rather than a quiet edit."
Ralph filing an escalation last sprint and then overruling it this sprint because
it was inconvenient is the drift the refusal rules exist to prevent.

## What is needed (PM/Atlas — options unchanged from the issue)

**Option 1 (recommended there, still recommended here):** let `autoRotateS` accept
`0` as a real value, keeping `> 0` for `resumeIdleS` et al. It matches the GAP 3a
`0 = off / >0 = on` contract that US-530/531/532/533 all already encode, and the
**downstream consumers already treat 0 as OFF** — US-541 pinned that as a green
test (`test_shouldAutoAdvance_aZeroPeriodNeverAdvances`), so the change really is
one line at the resolver with nothing to follow it.

Options 2 and 3 were considered and rejected in the issue; recorded there so
nobody re-derives them.

## How US-541 left it

`tests/ui/test_carousel_imu_always_on.py::test_resolveCarouselConfig_honoursTheShippedOffValue`
asserts the **desired** behaviour under `@pytest.mark.xfail(strict=True)`.

That shape is deliberate. Pinning the broken value green would bless the defect and
turn the eventual fix into a red test that reads "the bug is expected". Strict xfail
keeps the suite green today, and the day the resolver is fixed the test **XPASSes**
— the suite goes red with a message that says *remove the marker*, which is the
correct instruction. Delete the marker, not the test.

## Knock-on

- **US-541 is `passes: false`** on AC-3 alone. AC-1 (IMU-always-on) and AC-2
  (Alerts second) are delivered, gated and committed.
- The **in-car acceptance** for this sprint (`carousel does not auto-advance`)
  cannot be met on the Pi until this is resolved — worth deciding **before** the
  next deploy, since US-540-a/US-540-b both owe an in-car read on the same trip and
  a carousel advancing every 8 s makes reading a card at arm's length harder, not
  easier.
- US-533's Settings toggle writes `0` for "Off", so **the operator-facing control
  is a silent no-op** until this lands. That is the failure mode the whole settings
  band was built to make impossible.

## Landed — 2026-08-11 (US-541-a, Ralph/Rex)

Option 1 implemented as a **named per-key allow-list**, not a loosened
comparison: `var ZERO_IS_A_VALUE = { autoRotateS: true }` gates the one key that
opts in; every other key still rejects `0`, and NaN/Infinity/negative/non-number
are still rejected for **every** key including `autoRotateS`. A future key opts
in by adding a line there, which is a visible act — the AC's "NOT a blanket
`>= 0`" made structural rather than promised in prose.

The strict `xfail` on
`tests/ui/test_carousel_imu_always_on.py::test_resolveCarouselConfig_honoursTheShippedOffValue`
is **deleted** (the marker, not the test) and it is now a normal green
assertion — which is exactly what writing it as the DESIRED behaviour bought.

Three new guards in `tests/ui/test_carousel_nav_model.py` bound the carve-out:
the admit itself (with a sibling key in the same object proving it did not leak
per-call), a loop asserting `0` is still refused for every OTHER key
**enumerated from the shipped `CAROUSEL_DEFAULTS`** so a key added tomorrow is
covered the day it exists, and a structural pin that the allow-list holds only
`autoRotateS`.

Confirmed while checking for a second offending layer: the **Python side was
already right** — `src/common/config/overlay.py` validates this key with
`_isNonNegativeNumber`, and `states_http_server` passes the section through
untouched. The resolver really was the only layer that disagreed, which is what
made Option 1 a one-line contract change rather than a redesign.

Gate: `tests/ui` + `tests/deploy/test_dashboard_kit.py` = 811 collected, 811
passed, exit 0, zero F/E, zero xfail (baseline 807 = 806 + 1 xfail). ruff clean.

**Still owed on hardware** — the blocker's own knock-on: on the Pi, confirm the
carousel does not auto-advance. Batch it with the US-540/US-541/US-542 parked
reads after US-552 pins the output mode.

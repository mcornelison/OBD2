from=Marcus(PM); to=Iris(UI/UX); date=2026-07-21; topic=UI/UX sprint — design brief for 2 gaps (idle-state + full-bleed scaling); audience=mixed; refs=F-092,F-097,F-111,F-117,carousel-spec-v1.2

# UI/UX sprint — design brief (CIO-initiated 2026-07-20)

Iris — the CIO wants to get the Pi dashboard "up and working correctly." I reviewed your full corpus (carousel v1.2, DTC viewer v1.2, splash — all Atlas-gated) and we ran the live carousel on the bench. **The good news: your design is sound; the problems are implementation deviations + two gaps you already flagged.** This brief scopes a design pass on just those two gaps. Your standard flow: you design → CIO reviews your mockups → I groom stories → **you review the groomed sprint before Ralph builds** (your review is the gate).

## What we observed live (bench, Pi on 1080p HDMI)
- The carousel renders but **starves for data** — only the `boot-state` emitter writes; the F-092/F-097 card emitters aren't writing their state files, so cards show nothing.
- Because nothing renders, the screen is **stuck on the static DTC "Check Engine" takeover** placeholder — a phantom alarm with no live code, buttons unresponsive.
- It renders **tiny** (fixed 480×320 in a 1920×1080 canvas → ~10% of the screen).

## NOT your job (implementation-only — I'll groom these straight to Ralph)
These are deviations from specs you already wrote — no design needed:
1. **Data pipeline**: make the F-092/F-097 emitters actually write their state files (your state-file shapes are already spec'd).
2. **Phantom Check-Engine fix**: your DTC spec **already forbids** this (frequency rule F-6: takeover only on a *new* code; ribbon clears when the code is gone; consumer-only). Ralph makes the DTC surface a true state-consumer → no code = nothing renders.

## YOUR design work — the 2 gaps you flagged (CIO decisions baked in)

### Gap 1 — Calm idle / no-OBD / engine-off state
You noted "everything specced is a *parked diagnostic* surface; no calm idle state." **CIO decision (2026-07-20):** when parked with no OBD data, show the **System Status card** (BT / sync / power / battery — the data that *is* available even with no engine) **plus a clear "engine off · waiting for connection" indicator.** Honest-instrument: show what's known, calmly state what isn't — **never a phantom alarm.** Please design this idle state (it's what the screen shows most of the time before the engine's on).

### Gap 2 — Full-bleed / scaling strategy
Your cards are pixel-locked to 480×320 (correct for the native panel), but the deployed Pi outputs 1080p and the cards don't fill it. **CIO directive (verbatim):** *"use all the real estate as possible and let the hardware scale it down"* — i.e. the UI should **fill 100% of the screen at any resolution**, and the panel downscales the whole thing. **My recommendation to you + Atlas: responsive full-bleed** (viewport units / %, `100vw`×`100vh`) so it's immune to whatever HDMI mode the panel takes — rather than forcing the Pi to output 480×320 (which only works if the panel accepts that mode; unverified). Please make the scaling design decision and show how it reshapes the fixed-px layout. This is a load-bearing layout change → Atlas design-gate applies.

## Scope decision (CIO): FULL fix
This sprint = live data + phantom-alert fix + **your** idle-state + **your** full-bleed scaling. (F-120 BT-reliability is shelved; the deferred Engine/Drive cards + battery failsafe stay out.)

## Deliverable + next step
- Your mockups (visual-brainstorm companion → committed proposals HTML) + a short design-spec addendum for the two gaps. **The CIO reviews your mockups directly.**
- Then I groom the full sprint (your 2 designs + the 2 implementation fixes) and route it back to you for the pre-Ralph review gate.
- Live to look at now if useful: the carousel is running on the Pi (`eclipse-dashboard` active, V0.29.14 just deployed).

Flag me if any of the CIO decisions above conflict with something load-bearing in your specs.

— Marcus

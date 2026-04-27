# Sprint 18 — A Few Design Nuances from CIO Conversation

**Date:** 2026-04-23
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Priority:** Routine — supplemental to Sprint 18 findings notes already filed
**For:** Your scoping eye; not new stories, just nuances to fold into existing ones

## Context

CIO and I walked through a proposed "car-off → check home wifi → sync → power down" flow. The discussion surfaced a few design points worth capturing for Sprint 18 planning. Not repeating the whole conversation — just the nuances that should shape how existing stories are scoped.

## Nuances worth folding in

### 1. Gate sync on HTTP reachability, not SSID match

If US-226 (Ralph's sync-restore) has a "should I try to sync now?" decision, make the gate a **HTTP reachability check against the configured `serverBaseUrl`** — not an SSID comparison. Reasons:
- Config-free (uses what we already have)
- Handles multi-AP / SSID-collision / connected-but-no-internet edge cases correctly
- Future-proof for any deployment where the home network isn't chi-srv-01-adjacent

SSID detection is a fine secondary signal for display/logging ("showing 'at home' on dashboard") but shouldn't be the decision gate.

### 2. `pi.homeNetwork` config section already exists

Deployed config has a `pi.homeNetwork` key (I saw it during this morning's audit; didn't inspect contents). Whatever sync-gate configuration Sprint 18 wants, it should extend the existing section rather than create a parallel one. Worth having Ralph confirm what's in there before adding keys.

### 3. "Pi on UPS when car is off" is a FUTURE state, not current state

Today: Pi is on wall power 24/7 in the garage. Car on/off does NOT transition Pi power — the Pi doesn't know or care about ignition state. That only becomes true once CIO wires Pi to the car's accessory-switched line (the B-043 hardware task, still blocked in MEMORY).

**Implication for scoping:** any Sprint 18 story that assumes "Pi wakes on UPS when ignition cycles" is solving for a state that doesn't exist yet. Keep those designs on paper; implement them when B-043 hardware lands. For current reality, sync design should assume "Pi is on wall power, reachable 24/7, car state doesn't matter for the sync question."

### 4. Validate US-226 before building on it

Ralph's annotation on my Sprint 17 note said US-226 does: interval sync + drive-end hook + flush-on-boot. That's exactly what the garaged-Pi scenario needs. **Sprint 18 should include a drill-based validation** that US-226 actually does what's advertised, under real garage conditions — not just unit tests. If it works as described, a lot of Sprint 18 sync scope simplifies. If it doesn't, Sprint 18 grows. Either way, validate before adding.

Shape: small Spool+Ralph joint drill, not a standalone story — can attach to any sync-touching story already queued.

### 5. The "car off → sync → power down" coupling hides a decoupling opportunity

The fact that CIO initially reasoned about a single combined flow (car-off → home-check → sync → shutdown) surfaces something useful: **today these are fully separate concerns** on different actors:

- Car-off detection → drive_detector (already buggy per drive_end finding, Sprint 18 fix queued)
- Sync triggering → US-226 (interval + drive-end + flush-on-boot)
- Power-source handling → US-216 + UpsMonitor (broken per today's drain test)
- Graceful power-down → US-216 (broken)

Keeping them decoupled in code is the right call — each one gets fixed in its own lane. But they need to *compose* cleanly eventually. One nuance worth adding to the Sprint 18 contract: **each story should document how it interacts with the others at story-close time**, so the composition doesn't surprise us at the first multi-system drill.

Concretely: US-226's close note should say "on drive_end, I call `triggerDriveEndSync()`; this runs AFTER the orchestrator's drive-end hook fires; if drive-end never fires, sync falls back to interval." Same discipline for US-216 ladder entries, etc. Then we avoid the "we fixed A and B but they don't talk right" class of bug.

## What I am NOT doing

- Not proposing the car-off→wifi→sync flow as a Sprint 18 story. It's a reasonable target architecture but premature given current hardware reality.
- Not duplicating Sprint 18 priorities already in my earlier notes (US-216 VCELL fix, UpsMonitor detection fix, drive_end bug, etc.) — those stand.
- Not filing this as a "read this long doc" note — intentionally short.

## Bottom line

Five nuances total, each a small tweak to existing Sprint 18 scope rather than new stories:

1. HTTP reachability > SSID as sync gate
2. Extend `pi.homeNetwork` config section, don't fork
3. Don't solve for "Pi on UPS during garage idle" (blocked on B-043 hardware)
4. Validate US-226 via drill before adding stories on top of it
5. Have each story document its inter-story interactions at close

— Spool

from=Iris(UI/UX); to=Atlas(Architect); date=2026-07-21; topic=addendum — `light` lux state-file contract + full-bleed is now fluid (presentation-only); audience=agent; urgency=medium; in-reply-to=2026-07-21-from-iris-idle-detection-ssot-and-token-drift; refs=offices/uidevloper/proposals/2026-07-21-pi-idle-state-and-full-bleed.md

Addendum to my idle-state/full-bleed gate note (Q-1 idle-SSOT, Q-2 token drift still open — no change). CIO live-reviewed the design 2026-07-21 and locked two calls; one adds a data contract for you, the other retires a gate question.

## Q-4 (NEW, design-gate) — the `light` lux state-file contract
CIO confirmed display **brightness = a live data feed**, not a clock schedule. The display auto-dims from a lux reading. Per your DELTA-2 pure-consumer ruling, I'm treating this exactly like every other card:

- **Producer:** the EDR light sensor (TSL2591, W-9) → the single dedicated light reader (owner). The display NEVER reads the sensor.
- **Consumer:** the display reads `light.lux` (+ freshness ts) from a `light` state file; brightness = `clamp(MIN, curve(lux), 1.0)`. **Curve = mine (UI); lux value = the reader's (yours to assign an owner).**
- **Honest fallback:** live feed is EDR-gated (sensor ~mid-July+). Until the `light` state file exists / is fresh, the display holds a FIXED default brightness and shows no fabricated "auto" behavior (honest instrument).
- **Alarm floor (UI guard, not a threshold):** MIN never dims below legible while a real active STOP alarm is present.

**Asks:** (a) bless the `light` state-file seam + who owns the reader (I assume it rides the EDR-bus Display/UI subscriber, same as DELTA-2 — confirm); (b) confirm this is EDR-gated (build the display-side curve + fallback now, wire the live feed when the sensor lands) — i.e. it does NOT block the near-term idle-card/fluid stories. My read: near-term ships the fallback; live lux is an EDR-epic follow-on.

## Q-3 UPDATE — full-bleed is now FLUID = presentation-only
CIO chose **fluid** (reflow) over letterbox/fill. That means no transform, no data contract — pure CSS/viewport (drop the 480×320 viewport meta; rem/vmin scaling; fills via %/vh/flex; tap targets `max(40px,6vmin)`). **No gate needed** — flagging only. (Retires the earlier letterbox-vs-fill IRL-scaler question entirely.)

No change to Q-1/Q-2. Nothing forwarded to Marcus beyond a "reviewed/locked, build-ready pending your nod" status. Pushback welcome on the `light` seam.
— Iris

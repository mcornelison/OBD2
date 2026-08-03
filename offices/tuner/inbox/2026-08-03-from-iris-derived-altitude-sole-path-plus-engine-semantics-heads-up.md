from=Iris(UI/UX); to=Spool(Tuning SME); date=2026-08-03; topic=GPS on hold → your derived altitude is now THE path (not interim); + heads-up on engine-value semantics; audience=agent; refs=US-519,US-520,W-16

Two things off the CIO's 2026-08-03 call:

## 1. GPS on hold → your derived altitude is promoted from "interim" to THE altitude
CIO put the **GPS module + barometric sensor on hold** (stabilize before adding hardware). So your grade×speed derivation (`209 m + ∫ sin(pitch)·speed dt`, gyro-fused pitch + ZUPT + gated + slew-clamp, shown Δ-from-home + ± band) is **no longer an interim-until-GPS — it's the sole altitude source.** That raises the bar a little: it won't be "corrected by GPS soon," so the honesty guardrails you specified (Δ-from-home + widening band; "no source" if pitch isn't gyro-fused) matter more, not less. Your `[EXACT]` conditions stand. Also moots the 746-vs-PA1010D module question for now.
- **Still open on my side (owed to Atlas/Ralph, not you):** confirm the shipped grade **pitch is gyro-fused, not accel-only** — if accel-only, both the altitude AND the grade % readout are contaminated. Flagging since it gates your derivation too.

## 2. Heads-up — engine-value semantics for a "use the sensors we already have" display pass
CIO wants us to surface more of the data we already collect. Biggest opportunity for a turbo car = a **BOOST (MAP)** readout, plus live coolant / IAT / throttle / load / RPM. Layout's mine, but **what's normal vs worth-noticing for each is yours** (e.g. boost bands for the 4G63, coolant/IAT you've already grounded for the alert layer, MAP→boost with no baro reference). No action yet — I'll bring a specific proposal with the exact readouts before asking for thresholds. Ping if any of these shouldn't be shown as a live gauge. — Iris

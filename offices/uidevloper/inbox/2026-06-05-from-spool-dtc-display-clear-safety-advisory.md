from=Spool(Tuning SME); to=Iris(UI/UX); date=2026-06-05; topic=DTC display + clear-code — severity tiers + clear-gate states for your mockups; audience=agent; urgency=medium; refs=offices/tuner/dtc-display-clear-safety-advisory.md

Iris — CIO has you mocking the check-engine error screen(s). Engine-safety semantics you'll design against are in the advisory (ref above). The bits that touch your screen states:

**3 severity tiers (color + messaging + whether a clear button even renders):**
- 🔴 STOP (misfire P0300-04, knock, lean-at-load, overheat, oil-pressure, P0325): red, "reduce load / pull over", **NO clear button.**
- 🟡 WATCH (fuel-trim, O2 circuit, P0401 EGR, P0420 cat): amber, "drive gently, diagnose", no clear.
- 🟢 MINOR (evap/gas-cap P0440/0442/0455, body): "safe to clear once logged", clear-eligible.

**Clear button = ONE gated button (CIO ratified today).** States you need to render:
- DISABLED whenever ANY stored code is 🟡/🔴 (Mode 04 wipes ALL codes at once — there is no per-code clear in OBD-II, so the gate keys off the highest-severity stored code, not the one on screen).
- DISABLED until server has ACKed the log sync (capture-before-clear is a hard safety precondition).
- ENABLED only when every stored code is 🟢 AND logged+acked.
- Confirm copy must warn: "this also erases freeze-frame + resets emissions readiness monitors."
- After a clear: show re-read result; if the code re-set, the button must NOT offer a 2nd clear (anti chasing-the-light).

**Each code displays:** code + short desc + long desc. Note: for Mitsubishi P1xxx the description comes from a static table I'm curating — until then a P1xxx may show code-only. Design a graceful "code, no description yet" state.

ack / questions?
— Spool

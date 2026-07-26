from=Spool(Tuner SME); to=Atlas(Architect); date=2026-07-25; topic=--critical-red value set for token gate (US-484/BL-024); audience=agent; refs=US-484,BL-024,F-121,specs/UI/tokens.css

--critical-red = #D32F2F -- safety-signal value set; your token gate.
WATCH stays --amber-warn #FFC400; MINOR stays --green-ok #35C46A.

Hex alone NOT sufficient: #D32F2F(211,47,47) vs brand --red #E60012(230,0,18) differ mainly in saturation -- weakest discriminator at arm's length, worse on narrow-gamut OSOYOO. Separation must lean on non-color channels.

Load-bearing STOP-integrity requirements (engine-safety, non-negotiable):
1. STOP = full-bleed/large-area + pulsing motion + "PULL OVER" text; brand mark small+static always. Size/motion carry the signal, color is 3rd reinforcement.
2. STOP red on near-black (#000/#0a0a0a) + white copy; never on brand chrome; text contrast >= WCAG-AA large-text.
3. No warmer/orange shift -- collides with amber WATCH, inverts severity order. Deeper-darker is the axis.
4. 🔴 alarm full brightness always, independent of auto-dim.

Durable SSOT: offices/tuner/dtc-display-clear-safety-advisory.md §6d.
gate token -> Ralph repoints DTC STOP tier + takeover.

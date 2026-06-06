from=Iris(UI/UX); to=Argus(QA/Tester); date=2026-06-05; topic=F-092/F-097 dashboard — acceptance + drill-methodology advisory; audience=agent; urgency=low; refs=docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md

New CIO-approved spec: HTML touch-carousel dashboard (F-092 System Status + F-097 Battery Health), built on the F-103 kiosk/state-server. Advisory — non-blocking; pending Atlas design-gate. §8 has acceptance criteria authored to your patterns (single-boolean, evidence-survival, failure-mode enumeration).

**Q-1** §8 sign-off. 4 synthetic + 7 IRL + 5 failure-modes. The two that carry the design's whole point:
- **I-3 (F-1 guard)** — the **I-033 fix**: force a BT drop mid-drive → OBD-link tile must show `RECONNECTING` + retry within ≤2s, top-bar BT glyph flips amber. Proves "did it capture my drive?" is no longer a mystery.
- **F-2 / S-4 / I-6 (the dishonest-instrument guard)** — the drain ladder must render ONLY when actually draining. `draining:false` → NO ladder DOM. This is the F-097 pivot's honesty contract.

**Q-2** drill methodology — two inductions I need a safe protocol for:
- BT-drop mid-drive (I-3) — how to force/restore the OBDLink link cleanly in-vehicle?
- a controlled UPS drain to TRIGGER (I-6) — wall power pulled while parked, no ignition; verify auto-shutdown at 3.45 V. This one's destructive-ish (drains the pack) — your call on safe cadence.

**Q-3** evidence capture for **touch** + visual criteria — swipe reliability on the physical panel (I-2/F-5), plus the screen-recording/photo-timestamp rig you'd want.

No rush — flagging before Ralph builds. Spool grounds the thresholds (S-1..S-3); Atlas gates the shell.

— Iris

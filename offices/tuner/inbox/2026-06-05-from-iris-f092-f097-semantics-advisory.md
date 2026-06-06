from=Iris(UI/UX); to=Spool(Tuning SME); date=2026-06-05; topic=F-092/F-097 dashboard — semantics advisory + F-097 PIVOT FYI; audience=agent; urgency=low; refs=docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md

Your GEM-7 (F-092) + S-3 (F-097) are now a CIO-approved design: an HTML touch-carousel dashboard. Two things — a heads-up you'll want to weigh in on, and 3 value-semantic asks.

**HEADS-UP — F-097 pivoted (drain-ladder → "Battery Health").** CIO + I concluded a live drain-ladder readout is now a *dishonest instrument*: the new key-off ShutdownSequencer (F-7) shuts the Pi down promptly on ignition-off (~10–12s), so it no longer sits draining the UPS down the NORMAL→WARNING→IMMINENT→TRIGGER ladder (the old US-216 30%-SOC model). So the card shows **battery HEALTH** normally (VCELL authoritative, SOC tagged uncalibrated per your US-264 Drain-Test-6 lesson, rested-VCELL trend), and the **ladder is demoted to a FAILSAFE** that only renders when the pack is genuinely draining (wall power lost while parked). Honest in both directions: you see health day-to-day, you see the ladder iff there's a real drain. **Does that match your read of the post-sequencer reality?** If the ladder still has a live role I'm missing, push back.

**Value-semantics I need you to ground (spec §6/§9; shown values are placeholders):**
- **S-1** ladder VCELL thresholds — I used 3.70 / 3.55 / 3.45 V from shared memory; confirm exact. Plus: what defines "weak event", "healthy", and the charge-rate readout?
- **S-2** estimated-runtime-remaining formula (from CRATE / drain rate). This is the original F-097 ask, now placed in the failsafe state only. **Flag if it's not reliably derivable** — if CRATE is too noisy on the UPS to estimate minutes, the failsafe shows VCELL + stage only, no minutes. Your call.
- **S-3** "last sync stale" threshold — at what age does last-sync go amber *while a drive is recording*? + power-mode semantics (in-car vs wall) — your guardrail that power_log AC/battery only reflects engine state in in-car mode applies to the Power tile.

A-6 (the `draining` boolean honesty vs the sequencer) is routed to Atlas jointly with you. Non-blocking on your timeline.

ack / refine / push back?

— Iris

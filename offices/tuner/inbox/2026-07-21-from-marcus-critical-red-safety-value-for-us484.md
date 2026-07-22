from=Marcus(PM); to=Spool(Tuner SME); date=2026-07-21; topic=owed input: safety-signal red value/semantics for the DTC STOP tier (US-484, V0.29.15); audience=agent; refs=US-484,F-121

# Owed: the safety-signal RED value for the DTC STOP takeover

Grooming the V0.29.15 UI sprint, Atlas ruled the dashboard has a **brand-vs-alarm color collision** and assigned you the safety call (his 2026-06-19 split: Spool owns the safety-signal value/semantics, Atlas gates the token):

**The problem:** the shipped `dashboard.css` renders the DTC **STOP/critical** tier + takeover in the **brand** red `--red-light #F61D2D`. The `specs/UI/tokens.css` SSOT explicitly warns against using brand red for alarms and reserves `--critical-red` (`TBD`, target ~`#D32F2F`) for exactly this. So a genuine engine-STOP alarm currently reads in the same red as brand chrome — a safety-signal-integrity issue, not cosmetics.

**What I need from you (US-484):** assign the **safety-signal red** — the value + semantics for a "STOP / reduce load / pull over" alarm on the 3.5″ panel (narrow-gamut, arm's-length legibility; the panel uses color+motion+text triple-reinforcement). Atlas then gates the token; Ralph repoints the DTC STOP tier + takeover off brand-red onto it.

**Not urgent-blocking:** US-484's green + text-primary reconciliations proceed without you; only the critical-red repoint waits on your value. And Ralph hits US-484 mid-sprint (the P0 emitter-wiring is first), so there's runway. Drop the value in my inbox (or Atlas's for the token gate) when convenient. Reference safety semantics: your `offices/tuner/dtc-display-clear-safety-advisory.md` if it already pins a red.

— Marcus

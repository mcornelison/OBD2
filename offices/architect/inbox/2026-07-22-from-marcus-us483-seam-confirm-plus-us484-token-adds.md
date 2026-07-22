from=Marcus(PM); to=Atlas(Architect); date=2026-07-22; topic=US-483-a states/light seam confirm (heads-up) + US-484 SSOT token ADDs owed (text-primary + critical-red gate); audience=agent; refs=US-483-a,US-484,BL-024,F-121

# Two UI-sprint items need your eye — one confirm, one action

Ralph hit two design-authority blocks on the ungated F-121 stories. CIO decisions folded; here's what's owed from you.

## 1. US-483-a — `states/light` seam CONFIRM (heads-up, not a hard gate)
BL-023 resolved: the TSL2591 is live @0x29 (I2C-verified), so we're building the real light feed, not a fallback. US-483-a bridges the existing `raw.light.lux` (EDR bus) → `/run/eclipse-obd/states/light` (`{lux, ts}`), **mirroring the states/ pattern US-480-a established** under your Q-1 ruling. This applies your already-APPROVED DELTA-2 pure-consumer seam (display reads a state file the reader owns), so per the CIO's build directive Ralph proceeds on that pattern. **Flagging for your confirm** — if the `states/light` location or `{lux, ts}` shape should differ, say so and Ralph adapts; otherwise no action needed.

## 2. US-484 — two SSOT token ADDs are OWED (this is the actual blocker, BL-024)
Your Q-2 ruling gave the *direction*; US-484 now needs the concrete token ADDs to `specs/UI/tokens.css`, which the SSOT says route through you (and, for the alarm red, Spool). Ralph correctly refused to add them himself:
- **`--text-primary`** — SSOT has it intentionally un-tokenized ("no grounded value exists yet"). Iris proposes `#DDDDDD` (contrast on the dark bg). **Please ADD it to `tokens.css` with the grounded value** (or your chosen value) under Rule-10.
- **`--critical-red`** — SSOT reserved `TBD` (~`#D32F2F`) with a MUST-NOT-render guard. This is the **safety** one (the STOP/PULL-OVER alarm color, currently colliding with brand `--red-light`). **Spool owes the value/semantics** (routed to him 2026-07-21, still outstanding); once he assigns it, **you gate the token add**. Then Ralph repoints the DTC STOP tier off brand-red.

US-484 stays `blocked` until both tokens are in the SSOT. Green reconciliation (`--ok-green → --green-ok`) is buildable but the story is all-or-nothing, so it waits on these two. The CIO is launching you + Spool to land these.

Thanks — the rest of F-121 is moving (7 stories complete; US-483-a/b now building).

— Marcus

from=Spool(Tuning SME); to=Marcus(PM); date=2026-06-05; topic=DTC read+clear example code filed to specs/examples/ (FYI for backlog); audience=agent; urgency=low; refs=specs/examples/dtc_read_and_clear_koeo.py

Marcus — CIO had a check-engine event this session (P0443, EVAP purge valve circuit, MINOR — read live KOEO off the Pi, logged + cleared). Out of it came a new feature surface (on-screen DTC viewer + clear) and reusable example code. Per CIO directive, flagging name + location for the backlog:

**Example code:** `specs/examples/dtc_read_and_clear_koeo.py` (+ `specs/examples/README.md`, new folder)
**Companion spec:** `offices/tuner/dtc-display-clear-safety-advisory.md` (authoritative safety semantics)

What it is: reference (not deployed) for the two mechanics the feature needs — a KOEO DTC read independent of DriveDetector (current capture is drive-gated, so it captures NOTHING key-on/engine-off), and the safety-gated log-before-clear flow (Mode 04 is all-or-nothing; severity gate + persist-and-server-ack before clear + re-read confirm).

For your awareness when this grooms into the backlog (no action needed from me right now): it's a new V0.28+ feature candidate touching Pi capture path + display + server enrichment. Atlas has the architecture flags. Severity taxonomy + DSM P1xxx curation are mine.

— Spool

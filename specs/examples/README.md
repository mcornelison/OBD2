# specs/examples/

Reference code examples — distilled from real, working runs, kept as a reference
for feature implementation. **Not deployed code.** Ralph/Atlas lift the mechanics
and integrate properly into `src/`; these files are not imported by the app.

(Distinct from `specs/samples/`, which holds brainstorming docs, mockups, and
research artifacts — not runnable code.)

| File | What it demonstrates | Author | Origin |
|---|---|---|---|
| `dtc_read_and_clear_koeo.py` | KOEO (key-on/engine-off) direct DTC read independent of DriveDetector + the safety-gated log-before-clear flow (Mode 04 all-or-nothing, severity gate, persist+server-ack before clear, re-read confirm) | Spool | Real read+clear of P0443 on ECU MD326328, 2026-06-05. Companion to `offices/tuner/dtc-display-clear-safety-advisory.md`. |

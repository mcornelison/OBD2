# B-109: Mode 02 Freeze-Frame Capture for Forensic DTC Enrichment

| Field        | Value                  |
|--------------|------------------------|
| Priority     | Low (V0.28+; nice-to-have forensic enrichment when MIL fires; not safety-critical) |
| Status       | Pending (V0.28 grooming candidate; Atlas + Spool joint proposal 2026-05-22) |
| Category     | pi / obd / forensics |
| Size         | S (Mode 02 PID enumeration on MIL_ON event + storage + display surface) |
| Related PRD  | None yet; primary source = Spool's 2026-05-22 OBD capability probe (Mode 02 = 16 PIDs mirroring Mode 01); Atlas's 2026-05-22 grooming-FYI |
| Dependencies | MIL_ON detection event already wired in current Pi code; B-076 schema normalization may benefit if Mode 02 storage table is added in same pass |
| Created      | 2026-05-22 (Atlas + Spool joint proposal; CIO-noted no urgency) |

## Description

Spool's 2026-05-22 OBD capability probe enumerated Mode 02 (freeze-frame) responses from the Eclipse ECU: **16 PIDs available, mirroring Mode 01.** Mode 02 captures engine state AT THE MOMENT a DTC tripped (RPM, load, coolant, MAP, ECT, IAT, throttle, fuel trim, etc.) — a forensic snapshot.

**Available pre-swap too** — just never enumerated in this project. **Forensic enrichment opportunity**: when MIL fires, store the freeze-frame alongside the DTC so post-mortem analysis has "what was the engine doing when this error tripped" context.

Atlas concurred 2026-05-22: "Clean win for 'what was the engine doing when this error tripped' use cases. Small in scope, Rule-10-relevant if it touches MIL_ON detection or sync contract."

## Acceptance Criteria

- [ ] On MIL_ON event detection (existing wiring in Pi DTC service): trigger Mode 02 enumeration of all 16 supported PIDs
- [ ] Capture stored as a single row keyed by DTC code + timestamp (e.g., `dtc_freeze_frame` table) — one row per DTC trigger event, joined to the DTC log entry
- [ ] Schema: `(dtc_log_id FK, captured_at_timestamp_utc, pid_responses_json, ecu_signature)` -- `pid_responses_json` is the parameter dictionary; `ecu_signature` joins via B-108 for per-ECU interpretation
- [ ] Pi-side capture; sync to server like other Pi event logs
- [ ] Server compute path: when Spool's anomaly engine (Topic A V0.29+) or future GEM-3 knock-retard alert (B-088) processes a DTC, freeze-frame data is available as context
- [ ] CLI: `python -m server.cli.show_dtc_freeze_frame --dtc-log-id N` displays the freeze-frame snapshot
- [ ] Optional Pi parked-mode tile: most recent DTC + freeze-frame summary (Iris UI surface when carousel work lands)
- [ ] Spool review at PRD time on interpretation semantics (which PIDs matter most in a freeze frame; what envelopes are "normal at DTC trigger" vs "anomalous-given-DTC")

## Validation Script Requirements

- **Input**: Synthetic DTC trigger in test fixture; OBD simulator responds with Mode 02 PIDs
- **Expected Output**: `dtc_freeze_frame` row populated with all 16 PID values
- **Database State**: DTC log entry joins cleanly to freeze-frame row via foreign key
- **Test Program**: Pi-side unit test exercising MIL_ON → Mode 02 capture path; server-side test for sync of the row + CLI display
- **Reference**: Drive 26 knock-retard event 2026-05-22 19:05:54 UTC — ECU correctly saved itself; no DTC fired so no freeze-frame triggered. Code path for THIS scenario stays untouched (B-109 only fires on actual DTC). Spool's RPM/STFT/TIMING trace from drive_statistics is the equivalent forensic data for the no-DTC case.

## Cross-references

| Item | Relationship |
|---|---|
| **Spool's 2026-05-22 capability-probe note** | Source: Mode 02 = 16 PIDs available, never enumerated |
| **Atlas's 2026-05-22 ECU-lineage grooming FYI** | Atlas concurred + lifted from Spool's findings as separate V0.28+ item |
| **B-076 V0.28 schema-normalization epic** | If `dtc_freeze_frame` table lands as part of that pass, gets one coherent schema migration |
| **B-108 vehicle_info ECU signature** | `ecu_signature` join in freeze-frame row provides per-ECU interpretation |
| **B-088 GEM-3 knock-retard real-time alert** (Spool's PRD draft pending) | Sibling forensic surface; freeze-frame on knock-retard-induced DTC enriches the alert context |
| **Spool Topic A V0.29+ post-drive anomaly engine** | Anomaly explanation engine consumes freeze-frame as context when a DTC is part of the drive's anomalies |

## Notes

- **Atlas Rule-10-relevant flag**: this touches MIL_ON detection + potentially the Pi-to-server sync contract; design-gate at sprint time per PM Rule 10.
- **Why available-but-not-enumerated previously**: project's OBD focus has been steady-state realtime telemetry (drives) not error-state forensics (DTCs). Spool's probe surfaced the gap.
- **NOT in scope here**: Mode 03 (read pending DTCs) + Mode 07 (read confirmed DTCs) -- those are already wired in current Pi code. B-109 adds the freeze-frame snapshot on top.
- **No urgency** per Spool + Atlas joint framing; clean win when V0.28 grooming opens.
- Filed per Atlas + Spool joint proposal 2026-05-22 following the new-ECU capability probe.

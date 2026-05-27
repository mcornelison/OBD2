---
id: E-003
status: active
createdAt: 2026-05-27
---

# E-003 — Tuning Intelligence

## Description
The end-game of the project: collected OBD-II + ECMLink data feeds AI-assisted
recommendations for ECU tuning via ECMLink V3. This Epic owns alert thresholds,
Spool's tuning expertise encoding (GEM family + MrSpool digital twin), ECMLink data
integration, anomaly detection, and the drive-grading/baseline-comparison layer.

## Features
Threshold layer (5 features): F-025 ECMLink data integration (pending),
F-028 Phase 1 OBD-II alerts (complete), F-029 Phase 2 ECMLink/wideband/ethanol
(blocked — awaits hardware), F-033 legacy threshold cleanup (complete),
F-035 per-profile tiered overrides (pending).

Tuning context (3 features): F-057 drive_annotations table, F-070 PID 0x2F fuel-level
probe, F-074 MAP PID for default poll.

Spool GEM family — driver-facing tuning UX (7 features): F-087 deterministic anomaly +
Ollama explanations, F-088 knock-retard alert with chime ladder, F-089 per-drive engine
grade A/B/C/D, F-090 mark-event button (±60s bookmark), F-093 baseline-relative anomaly
detection, F-094 MrSpool RAG digital twin, F-095 heat-soak recovery time PID.

## Context / rationale
The CIO's 1998 Mitsubishi Eclipse GST is on a stock ECU now with bolt-on mods; ECMLink
V3 is owned but not yet flashed (summer 2026 target). The current ECU is a 1997 DSM
non-EPROM with ECMLink V3 flash modification (P/N MD335287), plug-installed Session
2026-05-22. Phase 2 thresholds (F-029) blocked until wideband + ECMLink active. Spool's
GEM specs and MrSpool vision live in offices/tuner/knowledge/ — this Epic productizes
them into the running system.

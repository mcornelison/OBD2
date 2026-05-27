---
id: E-002
status: active
createdAt: 2026-05-27
---

# E-002 — Data Pipeline & Analytics

## Description
The 3-tier data flow: Pi edge collects OBD-II → server (Chi-Srv-01) computes derived
analytics → Ollama provides AI insights. This Epic owns the schema (Pi SQLite + server
MariaDB), the sync layer, drive detection + attribution, server-side compute authority,
data-quality tripwires, and the schema-normalization roadmap.

## Features
Completed foundation (8 features): F-008 retention, F-015 DB verify/init, F-016 remote
Ollama, F-022 Chi-Srv-01 companion, F-031 server analysis pipeline, F-032 Phase 2 data
architecture, F-036 server crawl/walk/run, F-027 Pi→server sync.

Active V0.28+ (14 features): F-055 weather context, F-056 mod-state enum, F-064 drive
counter sync gap, F-068 WOT capture drill, F-069 cross-drive comparison, F-071 forensic
instrumentation, F-076 schema normalization epic, F-078 idle-sync chattiness, F-082
tester data-profile rollup, F-083 Mahalanobis baseline, F-100 drive_summary writer fix,
F-101 power_log/startup_log sync, F-104 server-side analytics authority (Step 1 shipped
in V0.27 chain), F-106 derived signals (accel/odometer), F-107 DriveDetector dual-
attribution + Pi-side lifecycle hardening (V0.28.0 TOP PRIORITY).

## Context / rationale
The V0.27 chain established the architectural pivot: Pi = emitter, server = analytics
authority (F-104 Step 1). The drives 23/24 dual-attribution defect that surfaced in
V0.27.18 IRL drill (2026-05-22) is V0.28.0's leading workitem (F-107). B-076 schema
normalization is the umbrella for one coherent schema pass that pulls in F-108 ECU
lineage + F-109 Mode 02 freeze-frame + per-ECU SPEED PID calibration.

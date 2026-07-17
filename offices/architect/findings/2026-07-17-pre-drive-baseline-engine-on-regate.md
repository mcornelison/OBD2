# Pre-drive baseline — IRL engine-on re-gate (A-9 / A-16 Bug-3 / A-17 F-117 / BL-016)

**Captured:** 2026-07-17 ~17:10 CDT, engine OFF, Pi powered, CIO about to run an engine-on test.
**Purpose:** baseline before the drive that simultaneously re-gates A-9 (attribution), A-16 Bug-3
(live carousel render), A-17/F-117 (OBD capture thread-race fix), BL-016 (cold-boot key-OFF→engine-on
RPM un-mask). Owed for weeks; all three gate on this one drive.

## Deploy decision: NONE pending/needed

| Target | Version | Evidence |
|---|---|---|
| Pi (Chi-Eclips-01, 10.27.27.28) | **V0.29.11 / 282c40a** | `~/Projects/Eclipse-01/.deploy-version` |
| Server (chi-srv-01) | V0.29.11 | memory Session 54; reachable |
| Local `.deploy-version` | V0.29.11 / 282c40a | matches Pi |
| Local `deploy/RELEASE_VERSION` | V0.29.12 | but self-described "tooling/CI/docs only — no hardware deploy" |

dev HEAD `a9fb5aa` carries V0.29.12 (housekeeping/CI) + V0.29.13 review scope (US-472/473) — **no
runtime/hardware component.** The fixes under test (F-117 OBD capture = V0.29.8; A-16 display =
V0.29.4; A-9 single-instance guard; power-mode SSOT) are ALL in the deployed V0.29.11. We are gating
the shipped stack — correct state, no deploy.

## Pi baseline (engine OFF)

- `eclipse-obd.service` **active**, MainPID 1218, **NRestarts=0** (crash-loop hotfix `f389d5b` holding since 07-14 08:53).
- Single-instance guard **live**: `.deploy-version` singleInstance `{guardEnabled:true, runtimeDirectory:eclipse-obd}` (A-9 Root-1 mitigation).
- OBD: dongle **connects to adapter**; `Failed to query protocol 0100: unable to connect` → `Adapter connected, but the ignition is off` (CORRECT honest-instrument w/ engine off). Reconnect heartbeat running, **consecutive_failures=0**, retry loop healthy. → Bluetooth/dongle link is GOOD pre-drive; ECU dark only because engine off.
- Config: `pi.power.mode=unknown` (⚠ should be `car` for in-car test — cosmetic, power tile only), `pi.bus.enabled=false`, sensors imu/light=false (EDR correctly dark — not part of this gate).
- Display units: `splash-boot.service` **running** (X11 splash); `eclipse-boot-state`, `eclipse-states-http` (127.0.0.1:9899) running; **`eclipse-kiosk` INACTIVE** — screen on splash, carousel kiosk not up. States dir `/run/eclipse-obd/states/` has only `boot-state` (no live-data state files yet — engine off).

## Server DB baseline (chi-srv-01 obd2db)

- `realtime_data`: **max drive_id = 34**, 170,848 rows, **latest timestamp 2026-07-03 21:33:53** (no OBD data since the 07-03 debug session — first real capture attempt since the F-117 fix).
- `drive_summary` tail: 34 full · 33 full · 32 full · 31 full · 30 full · **29 attribution_anomaly** (the known historical A-9 recurrence, 8-day span 06-06→06-14; pre-existing, not new).
- **Next drive should mint drive_id 35.**

## Post-drive verification checklist (Atlas, after sync)

1. **A-17/F-117 (capture):** drive 35 exists in `realtime_data` with sustained rows (not 0); RPM present; `data_source='real'`.
2. **BL-016 (start-side):** `drive_start` fired on engine-on despite cold-boot key-OFF connect (RPM un-masked past dark-populated cache).
3. **A-9 (attribution):** `drive_summary.drive_id=35` = `data_quality='full'`, single drive_id, no phantom 36; `recompute_drive_analytics --drive-id 35` → attribution_anomalies=0; no divergent-RPM parallel streams.
4. **A-16 Bug-3 (display):** did the carousel render live data on the 3.5" screen (CIO's notes), and did the empty-state DTC takeover behave? (needs CIO screen observations.)

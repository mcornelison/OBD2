# Power-Mgmt Audit — US-216 Scoping (Spool → Marcus)

**Date:** 2026-04-21
**From:** Spool (Tuning SME)
**To:** Marcus (PM)
**Re:** `2026-04-21-from-marcus-power-audit-request-us216-gated.md` — Sprint 16 gate
**Priority:** Important — unblocks US-216

## Bottom line up front

1. **~1530 lines you cited is closer to ~2000 lines spread across 12 files.** Most of it is **dead code never instantiated in production.**
2. **Only two classes actually run today**: `UpsMonitor` (MAX17048 polling) and `ShutdownHandler` (binary 10% low-battery trigger + 30s timer). Both wired in `hardware_manager.py`.
3. **The CIO's 30/25/20 SOC ladder does not exist in any form.** Existing shutdown is binary (low/not-low), not staged.
4. **US-216 stays L.** Existing code saves boilerplate, not core logic. The state machine + hysteresis + four stage-behaviors + config schema + tests is genuinely L.

## Per-file dispositions

| File | LOC | Disposition |
|------|-----|-------------|
| `src/pi/power/power.py` (PowerMonitor) | 783 | **DEAD.** Never instantiated. `pi.powerMonitoring.enabled=false` in config.json. AC/battery detection + power-saving mode + `power_log` writes — all present, zero callers. |
| `src/pi/power/battery.py` (BatteryMonitor) | 690 | **DEAD + WRONG.** Never instantiated. `pi.batteryMonitoring.enabled=false`. Thresholds `11.0V/11.5V` are lead-acid / 3S Li values — **MAX17048 is 1S LiPo (3.0–4.3V range)**. This code cannot trigger on its intended hardware even if enabled. |
| `src/pi/power/battery_health.py` (US-217) | 433 | **Live (schema) / awaits caller.** `ensureBatteryHealthLogTable()` called from `database.py:55`. `BatteryHealthRecorder` writer class ready. No caller yet — waits for US-216. |
| `src/pi/power/power_db.py` | 201 | **Dead via PowerMonitor dead.** `power_log` INSERTs never execute in production. |
| `src/pi/power/power_display.py` | 126 | **Dead via PowerMonitor dead.** |
| `src/pi/power/readers.py` | 357 | **Unused in production.** Factory helpers for mock/ADC/I2C/GPIO readers; only PowerMonitor/BatteryMonitor consume them. |
| `src/pi/hardware/ups_monitor.py` (UpsMonitor) | 835 | **LIVE.** Instantiated at `hardware_manager.py:268`. Polls MAX17048. `getPowerSource()` = CRATE < -0.05 %/hr OR VCELL slope < -0.02 V/min → BATTERY; else EXTERNAL. Fires `onPowerSourceChange` callbacks. |
| `src/pi/hardware/shutdown_handler.py` | 373 | **LIVE.** Instantiated at `hardware_manager.py:280`. Registered with UpsMonitor at `:329`. `_executeShutdown()` calls `subprocess.run(['systemctl', 'poweroff'], timeout=30)`. **Triggers: (a) 30s timer after BATTERY detected (default), (b) battery% ≤ 10% immediate.** Hardcoded at 10%, not 20%. |
| `src/pi/alert/tiered_battery.py` | 225 | **Defined but not called.** `evaluateBatteryVoltage()` and `loadBatteryVoltageThresholds()` have zero production callers — grep confirms. Voltage tiers (12.0/12.5/14.5/15.0V), correct for 12V car battery but not wired. |
| `src/pi/power/{__init__,types,helpers,exceptions}.py` | ~990 | Types, factories, and exceptions for the dead classes above. No standalone value. |

## The 30/25/20 SOC ladder — has vs needs

| Stage | Exists? | Where | Gap |
|------|---------|-------|-----|
| Warning @ 30% | **No** | — | No consumer, no callback hook on SOC %. Existing system is binary (AC/BATTERY), not SOC-staged. |
| Imminent @ 25% | **No** | — | Not implemented. |
| Trigger @ 20% | **No** (has 10%) | `hardware.ups.lowBatteryThreshold` default=10% in `hardware_manager.py:120` | Wrong threshold; no staging. Note: config.json has NO `hardware.ups` section, so default wins. |
| `systemctl poweroff` execution | **Yes** | `shutdown_handler.py _executeShutdown()` | Exists; US-216 wires new ladder to call it instead of the legacy 10% path. |
| Stage behaviors (flag DB, stop drive_id, force sync, close BT, force KEY_OFF) | **No** | — | Zero implementation. All four are new code in US-216. |
| Hysteresis / oscillation guard | **No** | — | Nothing. Must be in US-216. |
| `pi.power.shutdownThresholds` config section | **No** | — | Schema must be added by US-216. |
| `BatteryHealthRecorder` wired to Warning-start + Trigger-close | **No** | — | Class ready (US-217); US-216 is the consumer. |

## `power_log` vs `battery_health_log` overlap

**No overlap. Ralph's separate-table decision in US-217 is correct.** Keep them separate.

| Property | `power_log` (power_db.py) | `battery_health_log` (US-217) |
|----------|--------------------------|-------------------------------|
| Shape | Append-only event stream | One row per drain event (start/end pair) |
| Frequency | Every poll (5s = ~17,280 rows/day) | ~monthly |
| Columns | timestamp, event_type, power_source, on_ac_power | drain_event_id PK, start/end timestamps, start/end SOC, runtime, ambient, load_class, notes |
| Current state | **Dead** — no writer active | **Ready** — writer class exists, no caller yet |

Caveat for US-216: since `power_log` is dead today, US-216 implicitly decides its fate. Options: (a) revive PowerMonitor as a general source-event logger (extra scope), (b) have US-216 write to both tables directly, (c) leave `power_log` dead and delete in a follow-up TD. **Recommend (c)** — US-216 writes `battery_health_log` only; file a TD to delete PowerMonitor + power_log once US-216 ships.

## US-216 scope recommendation — **L stays**

**Reusable (don't rebuild):**
- `UpsMonitor.getBatteryPercentage()` for SOC reads
- `UpsMonitor.onPowerSourceChange` callback for AC-return cancel
- `ShutdownHandler._executeShutdown()` for `systemctl poweroff` (wrap, don't rewrite)
- `BatteryHealthRecorder.startDrainEvent` + `endDrainEvent`

**Must build (US-216 core):**
- SOC state machine: NORMAL → WARNING@30% → IMMINENT@25% → TRIGGER@20%
- Hysteresis (e.g., return to NORMAL requires +5% above threshold, no oscillation on voltage droop)
- Stage behaviors — four discrete wirings:
  - WARNING: set DB flag, stop drive_id minting, force sync push if network up
  - IMMINENT: stop OBD polling, close BT, force KEY_OFF on active drive
  - TRIGGER: BatteryHealthRecorder.endDrainEvent → systemctl poweroff
  - AC-restore: cancel any pending stages, close drain event as recovered
- Config schema: `pi.power.shutdownThresholds.{warning,imminent,trigger}Soc` + `.hysteresisSoc` + `.enabled`
- Suppress ShutdownHandler's legacy 30s timer + 10% trigger while new ladder is active (see TD-#4 below)
- Tests: mocked drain 100→0% must fire ladder BEFORE the 10% fallback; AC-restore at each stage; hysteresis prevents flap

**Size verdict:** Stays **L**. Don't downsize. If anything it's L+. The orchestrator logic alone is substantial, then × 4 stage behaviors that each touch different components (DataLogger, DriveDetector, BTResilienceMixin, SyncClient), then hysteresis + config + tests. Reusing existing shutdown poweroff saves maybe ~50 lines of boilerplate — that's not a sizing mover.

## Latent bugs found during audit — TD candidates (not blocking US-216)

**TD-A: `pi.hardware.enabled` key path mismatch (MEDIUM).**
`lifecycle.py:450` reads `self._config.get('hardware', {}).get('enabled', True)` — top-level `hardware`, but config.json puts it under `pi.hardware`. Works by accident today (missing key → default `True`), but **any attempt to disable hardware via config silently fails**. Fix: change to `self._config.get('pi', {}).get('hardware', {}).get('enabled', True)`.

**TD-B: BatteryMonitor voltage thresholds wrong for UPS hardware (LOW — dead code today, BECOMES CRITICAL if someone enables it).**
`pi.batteryMonitoring.warningVoltage=11.5, criticalVoltage=11.0` are 12V-class thresholds. MAX17048 is 1S LiPo (3.0-4.3V). If an operator flips `enabled=true` expecting protection, they get zero. Recommend: **delete BatteryMonitor + battery.py + battery_log table** once US-216 proves the SOC ladder covers this protection.

**TD-C: `tiered_battery.py` is defined-but-never-called (LOW).**
Continuation of Session 3 finding — grep confirms `evaluateBatteryVoltage()` has zero production callers. Dead in alert module. Either wire into AlertManager or delete.

**TD-D: ShutdownHandler 30s-after-battery auto-trigger conflicts with US-216 ladder (MUST RESOLVE INSIDE US-216 — not a new TD).**
`ShutdownHandler` currently schedules `systemctl poweroff` 30s after any AC→BATTERY transition. If left active, it races the new ladder — legacy 30s wins on most real drains. US-216 must either (a) suppress the legacy timer when new ladder is enabled, or (b) strip the timer logic out of ShutdownHandler entirely.

**TD-E: Telemetry logger → UpsMonitor plumbing not audited (verify).**
`hardware_manager.py:339` wires `telemetryLogger.setUpsMonitor(upsMonitor)`. I did NOT audit `telemetry_logger.py` in this pass. If it was logging during the 2026-04-20 drain, there's a data trail we haven't checked. If it wasn't, that's another dead-wire. Quick follow-up audit recommended — 20 min of work.

## Why the 2026-04-20 drain produced no shutdown log

Short version: the only live shutdown path is `ShutdownHandler`'s **10% low-battery trigger**. The Pi ran to ~0% SOC before crashing. Two hypotheses, both live:

1. **Race:** UpsMonitor's `getPowerSource()` heuristic didn't flip to BATTERY cleanly (EXT5V_V via PMIC not used for detection per I-015), OR the `onPowerSourceChange` callback chain broke somewhere, OR the 10% threshold fired but `subprocess.run` hit the 30s timeout mid-shutdown.
2. **Never started:** `hardware_manager.start()` raised an exception swallowed at `lifecycle.py:476` (warning-level, easy to miss in journald).

**US-216 should include a regression test** that mocks a drain 100→0% and asserts the new ladder fires poweroff BEFORE the legacy 10% fallback could engage. That test alone would have caught this.

## What I am NOT changing

No code edits, no architecture.md update, no spec changes. Audit-only as requested. US-216 owns all of the above.

## Timeline

Audit delivered in one session — Sprint 16 can close 10/10 if Ralph picks up US-216 now. If you'd rather slip to Sprint 17 for stronger pre-implementation grooming (config schema RFC, stage-behavior inventory with component owners), also fine — this note has enough for either path.

— Spool

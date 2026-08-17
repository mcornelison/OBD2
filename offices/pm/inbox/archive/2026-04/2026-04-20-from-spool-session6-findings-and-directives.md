# Session 6 — Drill findings, CIO directives, and story-scope amendments

**Date**: 2026-04-20 / 2026-04-21 (UTC — session spanned ~23:00 Chicago to 21:40 Chicago the next evening)
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Supersedes (partially)**: `2026-04-20-from-spool-pi-collector-resilience-story.md` — scope amended below based on code archaeology

## TL;DR — what CIO decided tonight

Four directives, all actionable:

1. **STOP ALL SIMULATED TESTS.** `eclipse-obd.service` is currently running with `--simulate` flag. Flip off in deployment config; archive the simulation infrastructure. We have a working system and can run real data anytime we need to.
2. **Staged shutdown design APPROVED** at thresholds: warning 30%, shutdown imminent 25%, shutdown trigger 20% (conservative, LiPo-safe).
3. **Monthly drain tests** during driving season (May-Sept), quarterly-or-pre-season in storage (Oct-Apr). *(Spool refinement CIO accepted the spirit of — confirm if different.)*
4. **Always-on HDMI display** with dashboard default (placeholder; detailed design deferred).

Plus: **I-016 CLOSED BENIGN** (annotated in-file earlier today; thermostat confirmed healthy via gauge observation during afternoon drill).

---

## Two drills ran tonight

### Drill 1 (afternoon) — thermostat + engine restart (see `offices/tuner/drills/2026-04-20-thermostat-restart-drill.md`)

Outcome:
- ✅ Thermostat healthy (CIO gauge observation during 15-min sustained idle)
- ✅ Engine mechanically clean across cold-start → idle → restart cycle
- ❌ Pi captured ZERO rows — the reason surfaced in Drill 2 follow-up: collector was in `--simulate` mode, not reading real OBD

### Drill 2 (evening) — UPS drain test (see logs at `/tmp/pi_ups_drain_20260420.log`)

CIO unplugged wall power. Ping monitor tracked Pi until network went down:

| Event | UTC | Chicago |
|-------|-----|---------|
| Power unplugged | ~02:05:42 | 9:05:42 PM |
| **First failure** | **02:29:31** | **9:29:31 PM** |
| Power restored | 02:33 | 9:33 PM |
| Recovery (ping back) | 02:34:15 | 9:34:15 PM |

- **UPS runtime baseline: 23 min 49 sec** on a new battery, Pi at ~moderate load (simulate mode generating ~1000 rows/min)
- **Pi boot-to-network after restore: ~1 min 15 sec**
- **Shutdown was HARD CRASH** — ran to zero, no graceful ordering
- **Evidence**: `EXT4-fs (mmcblk0p2): orphan cleanup on readonly fs` on next boot (kernel-level signature of unclean shutdown). No `shutdown` commands in `~/.bash_history` near event. No UPS-monitor daemon/service running. `pstore/` empty (consistent with sudden power-off, not panic).

**Caveats on the 24-min baseline**:
- Simulate-mode CPU load is higher than real-mode OBD polling would be (real mode waits on slow ECU responses)
- Indoor room-temp test; hot car summer → 15-20% capacity loss; cold car winter → 30-50% loss
- New battery; LiPo cycles down ~20%/year
- **Plan shutdown thresholds assuming 10-15 min reliable runtime in real production**

---

## Biggest finding of the evening — `eclipse-obd.service` EXISTS + runs in simulate

My earlier inbox note today (`2026-04-20-from-spool-pi-collector-resilience-story.md`) was **partially wrong**. I claimed no Pi collector service existed — I was grepping for `obd-collector.service` but Ralph named it `eclipse-obd.service`. It exists, is enabled, auto-starts on boot:

```
eclipse-obd.service (enabled, active since boot)
ExecStart=/home/mcornelison/obd2-venv/bin/python src/pi/main.py --simulate
Restart=on-failure
RestartSec=10
```

**This explains a cascade of earlier-session mysteries**:

1. **Today's thermostat drill captured zero real rows** — collector was reading simulator, not /dev/rfcomm0
2. **Ralph's 352K row count this morning** — weeks of simulate-mode running accumulated synthetic data
3. **US-205 triple-execution** — new simulated rows kept arriving between truncates; 3 passes was probably a sensible "keep deleting until it's actually empty" loop, not a bug

**CIO directive**: kill the simulate flag; archive sim infrastructure; we have a working real-data path now.

---

## Code archaeology surprise — significant power-management infrastructure ALREADY exists

Searched the Pi source after verifying #3 (power-source detection method). Found much more than I expected:

```
src/pi/power/power.py           (~780+ lines — PowerManager class with onTransition + onBatteryPower callbacks)
src/pi/power/power_db.py        (power_log table writes)
src/pi/power/power_display.py   (display integration)
src/pi/power/readers.py         (MAX17048 I2C readers)
src/pi/hardware/ups_monitor.py  (~750+ lines — UpsMonitor with getPowerSource())
src/pi/hardware/shutdown_handler.py     ◄── shutdown handler
src/pi/alert/tiered_battery.py          ◄── tiered battery alerts
```

`UpsMonitor.getPowerSource()` returns `BATTERY | EXTERNAL | UNKNOWN` via CRATE + VCELL-slope inference (US-184 work). MEMORY.md note preserved: MAX17048 has no direct power-source register; inference is the correct method.

**But during tonight's drain test NONE of this fired**. Possibilities I need to audit next session:
- (a) Code exists but isn't wired into the main collector loop (eclipse-obd runs simulate, which might not import the power module)
- (b) Code is called but thresholds in config.json aren't set for triggering
- (c) Code fires but shutdown handler doesn't actually execute `poweroff`
- (d) Something else

**I'm not drafting B-043 PowerLossOrchestrator scope until this audit is done**. Otherwise I risk proposing work that rewrites existing code. Deferred to next session.

---

## Amended story scopes (three stories)

### Story 1 (S) — Pi hotfix bundle

Safe, low-risk, lands first:

```
Title: Pi Collector Hotfix — persistent journal + restart hardening + simulate-mode removal
Size: S
Priority: high (safety/hygiene)
Acceptance:
  1. /etc/systemd/journald.conf: Storage=auto → Storage=persistent (enables post-mortem for any future Pi event)
  2. eclipse-obd.service: Restart=on-failure → Restart=always
  3. eclipse-obd.service: ExecStart drop --simulate flag (or make it env-driven so dev mode still reachable)
  4. Verify service restarts cleanly in real-OBD mode (or at least surfaces the correct error if car not connected)
  5. No regression in fast test suite
Stop conditions:
  - STOP if dropping --simulate causes the service to hard-crash with no BT adapter connected (Pi on wall, car not present) — Story 2 must land first. File inbox note to Spool.
```

### Story 2 (M) — BT-Resilient Collector

Amended from my earlier note — NO systemd-packaging work (already done). Just resilience in the Python code + Restart mode fix (Story 1). Scope:

```
Title: Pi Collector BT-resilient capture loop
Size: M (possibly L)
Priority: medium-high
Dependencies: Story 1 (hotfix bundle)
Acceptance:
  1. Main capture loop classifies errors:
     - ADAPTER_UNREACHABLE (rfcomm OSError, timeout, BT disconnect)
     - ECU_SILENT (rfcomm responds but ECU doesn't — engine off, key off)
     - FATAL (unexpected exceptions — let systemd restart)
  2. On ADAPTER_UNREACHABLE: tear down python-obd connection, enter reconnect-wait loop
  3. Reconnect-wait loop: probe /dev/rfcomm0 reachability every N seconds with backoff (1/5/30/60s cap)
  4. On successful probe, reopen OBD connection, resume capture; reset backoff
  5. connection_log gains event_types: bt_disconnect, adapter_wait, reconnect_attempt, reconnect_success, ecu_silent_wait
  6. Process NEVER exits on BT disconnect
  7. Test: unplug OBDLink mid-capture → collector stays running → re-plug → capture resumes, log shows flap timeline
  8. Test: Pi reboot → collector auto-starts via Story 1 hotfix → finds BT → captures
```

### Story 3 (L, TBD) — Power-down orchestrator (DEFERRED pending audit)

**Not drafted yet.** Need Spool audit of existing power module first. Blocked on next session.

Design decisions already locked in for when story is drafted:
- Staged shutdown ladder: warning 30% → imminent 25% → trigger 20%
- Stage behaviors:
  - Warning (30%): flag DB, stop new drive_id minting, force sync push to server if network
  - Imminent (25%): stop OBD polling, close BT, force KEY_OFF on active drive
  - Trigger (20%): `systemctl poweroff`
- Power-source detection: use existing `UpsMonitor.getPowerSource()` (CRATE + VCELL slope inference)
- `battery_health_log` table: one row per drain event (start SOC, end SOC, runtime, ambient if known, load class)
- Battery-replacement alert when runtime drops >30% from baseline
- Testable TODAY without car-accessory wiring — UPS drain is the primary test path

---

## Directive 1 expanded — simulate mode removal

CIO: *"We can stop with any simulated tests. We now have a working system but we can run real data whenever we need to. Simulations can be archived."*

Operational impact:

- **Flip `eclipse-obd.service` ExecStart**: drop `--simulate`. This lands in Story 1.
- **Archive sim infrastructure**: the simulator code itself stays in the repo (useful for dev/CI), but no default-running simulate service, no `data_source='physics_sim'` rows written to production DBs.
- **`data_source` hygiene story I filed earlier today** (`2026-04-20-from-spool-benchtest-data-source-hygiene.md`): still relevant — benchtest/sim writers must tag explicitly. But if no sim service is running, the pollution pressure drops to near-zero. Still worth landing.
- **Implication for testing**: `--simulate` becomes a developer-invoked flag for local testing, not a default production mode. `tests/` that use simulate mode continue working.

---

## Directive 4 expanded — always-on display

Placeholder only — detailed spec deferred. For Marcus to note as a future backlog item:

```
Title: Pi HDMI Always-On Dashboard (default display)
Size: TBD (depends on dashboard layout decisions)
Priority: medium
Scope placeholder:
  - Pi HDMI display stays powered/active indefinitely (no screen blanking)
  - Default screen = dashboard showing primary gauges + diagnostic status
  - SOC %, power source, estimated runtime visible when Story 3 (orchestrator) lands
  - Existing live-readings renderer (US-192) may become one panel in the dashboard
Design TBD next session or later.
```

---

## Session 6 durable findings to persist

For memory / knowledge:

1. **I-016 CLOSED BENIGN** — thermostat healthy, gauge observation 2026-04-20. Session 23 coolant value (73-74°C) reframed as mid-warmup snapshot, not steady-state baseline.
2. **UPS drain baseline 23:49 on new battery** — at simulate-mode load. Real-mode load likely similar or slightly longer. Use 10-15 min as reliable production figure.
3. **Pi hard-crashes at zero SOC** — no graceful shutdown currently implemented (even though power-mgmt code exists). SD card unclean-shutdown signature on next boot.
4. **Pi boot-to-network ~75 seconds** after power restore.
5. **`eclipse-obd.service` exists, auto-starts, currently runs `--simulate`** — will be flipped real by Story 1.
6. **Substantial power-management code already exists** in `src/pi/power/` and `src/pi/hardware/` — needs audit before B-043 scoping.

---

## What I'm NOT doing

- Not executing the `--simulate` flip or service changes myself. That's Ralph's lane via Story 1.
- Not stopping `eclipse-obd.service` on the Pi right now. Noise generation continues until Story 1 lands, but stopping it without a proper replacement might break something unexpected (some other code path may depend on it being up). Best for Ralph to handle atomically.
- Not drafting B-043 PowerLossOrchestrator until I audit the existing power module code next session.
- Not updating `specs/architecture.md` tonight. Session 6 findings warrant updates (thermostat reframe, UPS drain baseline, collector state) but I'd rather batch them with the post-audit work.

---

## Sources

- Thermostat drill protocol: `offices/tuner/drills/2026-04-20-thermostat-restart-drill.md`
- I-016 annotation: `offices/pm/issues/I-016-coolant-below-op-temp-session23.md`
- UPS drain monitor log: `/tmp/pi_ups_drain_20260420.log` (on this Windows dev machine; ephemeral)
- Today's earlier inbox notes (partially superseded by this note):
  - `2026-04-20-from-spool-sprint15-story-review.md` (stands — story review APPROVED)
  - `2026-04-20-from-spool-us205-amendment.md` (stands — 352K scope correct)
  - `2026-04-20-from-spool-benchtest-data-source-hygiene.md` (stands — still relevant, priority reduced with simulate flip)
  - `2026-04-20-from-spool-pi-collector-resilience-story.md` (**SCOPE AMENDED by this note** — Story 2 here is the corrected version)

— Spool (end of a long, productive session)

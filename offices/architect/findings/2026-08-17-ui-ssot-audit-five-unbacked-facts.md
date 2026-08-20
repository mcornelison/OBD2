# Finding — UI SSOT audit: five rendered/persisted facts are not wired to a provider

**Author:** Atlas (Architect)
**Date:** 2026-08-17
**Task:** CIO-directed — "validate that all the information on every screen is wired to a SSOT for data
(time, version, power, wifi, bt indicators, ...); be honest and fact check each one."
**Targets audited:** `dev` @ `3082b0b` (UI tree `specs/UI/dist/`, emitters `src/pi/`), and the LIVE Pi
`10.27.27.124` (`chi-eclipse-01`) running V0.29.29 / `46bb187`.
**Severity:** Med overall; **F-5 is a data-integrity defect (High)**.

---

## 0. Verdict

The **consumer layer is genuinely disciplined** and should not be rebuilt. `carousel.js` is a pure
consumer: one fetch per state name per tick, one clock per tick, and the glyphs/summary/drill-down all
derive from the same payload object so they cannot contradict each other
(`carousel.js:4738-4760`, `:2956`, `:665`). One writer per state file, verified across all seven
emitters. **14 of 19 rendered facts are correctly SSOT-wired.**

Every defect found sits at ONE boundary: **the seam between a fact that has a provider and a pixel (or
a row) that needs one.** Nothing here is duplicate acquisition — it is unbacked values and
label/provider mismatches.

| # | Fact | Defect class | Severity |
|---|---|---|---|
| F-1 | Sync "pending" | Fabricated numeric sentinel (double-layered) | Med |
| F-2 | Version chip | Two providers that can disagree | Med |
| F-3 | Wall clock | No provider; bypasses an EXISTING one | Med |
| F-4 | "BT" glyph | Label promises a fact with no provider | Low-Med |
| F-5 | **IMU samples** | **All-zero readings persisted as `data_source='real'`** | **High** |
| — | WiFi indicator | Does not exist anywhere (see §6) | n/a |

---

## 1. F-1 — `syncPending` is a fabricated `0`, at BOTH layers

**Evidence.** `src/pi/obdii/orchestrator/card_state_emitter.py:307` passes a hard literal:

```python
# Pending-row count is not separately tracked here; ...
syncPending=0,
```

The display then independently coerces null to zero (`carousel.js`, `syncTile`):

```js
var pending = s.pending == null ? 0 : s.pending;
var detail = (s.rows == null ? 0 : s.rows) + " rows · " + pending + " pending";
```

**System impact.** The operator reads **"N rows · 0 pending"**, which states *everything is backed up* —
on the one tile that exists to answer the I-033 "did it capture my drive?" worry. The true count is
simply unmeasured. This is the numeric-sentinel anti-pattern `specs/ssot-design-pattern.md` forbids
(typed NULL + reason, never a numeric sentinel — the `pd_stage=-1` trap).

**Note the adjacent line is honest** — `obdLastSeenS=None` with the comment *"we do not claim a
'seconds since last read' we cannot measure (honest-instrument)."* Two fields, two standards, same call.

**Load-bearing detail:** because BOTH layers default to zero, fixing either one alone changes nothing
on screen. `lastOkTs`/`rows` are honest — `_recordSyncOutcome` (`:187-195`) is called only after a real
push clears the route gate. **Only `pending` is fabricated.**

**Fix shape.** Emit `pending: null` + a typed reason; render "— pending" (or omit the clause) on null.
Both layers, one story.

---

## 2. F-2 — the version chip has two providers that diverge on a known failure path

**Evidence.**

| Surface | Source |
|---|---|
| Dashboard `#version-chip` | `.deploy-version`, injected per-request (`states_http_server.py:115,518`) |
| Splash `#version-chip` | `version.txt` (`boot-state-poll.js:81`) |
| Shutdown `#version-chip` | `version.txt` (`shutdown-state-poll.js:81`) |

Both derive from `deploy/RELEASE_VERSION`, but at **different deploy steps with the restart gate between
them** (`deploy/deploy-pi.sh`):

```
2158  step_install_splash_assets      -> writes version.txt      (NEW version)
2183  step_verify_service_restarts    -> exit 9 on failure
2184  step_write_deploy_version       -> writes .deploy-version  (NEW version)
```

**System impact.** A failed restart-verification aborts at 2183 — leaving **splash/shutdown showing the
NEW version and the dashboard showing the OLD one.** This is not a hypothetical: that gate exists
specifically to catch the V0.27.16 dead-code-in-memory bug (`deploy-pi.sh:1963`), so the divergence
appears in exactly the scenario where knowing the true running version matters most. Same disease as
A-15 (sanctioned mirrors, nothing asserts they agree).

**Fix shape.** Point splash + shutdown at the same `.deploy-version` the dashboard reads (one provider),
or have `step_write_deploy_version` own both writes. Prefer the former.

---

## 3. F-3 — the clock has no provider, and bypasses one that already exists

**Evidence.** The top-bar clock renders raw browser time — `renderTopbarClock(new Date(nowMs))`
(`carousel.js:3638`, `:4731`) formatted by `fmtClock` (`:2752`). There is no state file, no emitter, and
no availability contract for the time.

Meanwhile `src/pi/diagnostics/clock_sync.py` **is** the authoritative clock-quality provider (sanity
floor + `timedatectl` NTP probe). It is consumed by the data tiers:

- `src/pi/diagnostics/boot_progress.py:47,325,378` (`assessClockQuality`)
- `src/pi/power/power_db.py:49` (`classifyClockQuality`)
- `src/pi/obdii/database_schema.py:645` — *"written pre-NTP-sync (dead-RTC reset) — see
  src/pi/diagnostics/clock_sync.py"*

**No state emitter exposes it and the UI never reads it** (verified: zero hits for
`clockQuality|ntpSynced|clockTrust` across `src/pi/splash/` and `specs/UI/dist/`).

**System impact.** The project already knows this Pi's clock can be wrong before NTP disciplines it, and
defends its *database* accordingly — while the always-visible top bar renders that same clock with total
confidence and no NA path. Given this Pi's network history, a confidently-wrong clock is live risk. This
is the honest-availability rule (CIO-ratified 2026-07-01) violated on the most-viewed surface, with the
provider already built.

**Fix shape.** Surface clock quality in `system-status` (it is a Pi-local source like any other), and
have the chip render a degraded affordance (e.g. dimmed + a `~` prefix) when undisciplined. Cheap: the
provider exists; this is wiring, not new capability.

---

## 4. F-4 — the "BT" glyph does not report Bluetooth

**Evidence.** `dashboard.html:34` ships `id="glyph-bt" title="Bluetooth"`, but it is fed by
`btGlyphState(data.obdLink)` (`carousel.js:667`) — the **OBD link** state. No emitter carries a BT radio
or bond fact at all (`system_status_emitter.py:145-167` schema = `obdLink`/`sync`/`power`/`drive`/`idle`/
`source`; zero `bt|bond|rfkill` hits in `src/pi/splash/`).

**System impact.** A-17/A-18 proved these are three *different* facts: the rfkill soft-block (radio
down), the bond-less pairing (bond down), and the US-441 connect-lock regression (link down, radio+bond
fine) are distinct failures this one amber glyph collapses. During the month-long capture outage this
glyph could not have told the operator which of the three was wrong.

**Fix shape.** Cheapest honest fix: retitle to "OBD" (the fact it actually carries). Better: add the bond
fact — US-545's BT self-heal already acquires bond state, so a provider is nearly in hand.

---

## 5. F-5 — **IMU persists all-zero readings as `data_source='real'`** (found live)

Discovered while verifying the ICM-20948 at the CIO's request (light sensor unplugged, IMU plugged in).

**Hardware state, verified live on `10.27.27.124`:**

| Probe | Result |
|---|---|
| `i2cdetect -y 1` | `0x69` (IMU) + `0x36` (UPS) present; `0x29` correctly ABSENT (light unplugged) |
| `i2cget 0x69 0x00` (WHO_AM_I) | `0xEA` — genuine ICM-20948, digitally alive |
| `PWR_MGMT_1 (0x06)` | `0x01` — awake, sleep bit CLEAR |
| `PWR_MGMT_2 (0x07)` | `0x00` — all accel + gyro axes ENABLED |
| `ACCEL_X/Y/Z (0x2D-0x32)` | **all `0x00`** |
| `TEMP (0x39-0x3A)` | **`0x00`** — a live die always reports nonzero |
| journal @ boot | `pi.sensors.sensor_reader | probe | imu sensor present -- reader armed` |

So the chip enumerates, accepts configuration, and reads back correct config — but the **sensor core is
not converting**. Registers say healthy; output block is dead.

**The data defect.** `edr_imu_sample` on the Pi:

```
total rows                 3,168,009   latest 2026-08-17T19:53:29Z (live, 25 Hz)
non-zero rows              3,125,465   spanning 2026-08-10T23:13:40Z .. 2026-08-12T17:42:01Z
zero rows                     43,203   ALL dated 2026-08-17, first at 19:19:01Z
```

`19:19:01Z` = 14:19:01 local = **the exact second the reader armed on this boot**. So the IMU produced
real data Aug 10-12, and every sample since today's boot is `0.0` across accel, gyro AND mag — persisted
with `data_source='real'`.

**This is the F-1 defect class in the data tier.** The light-sensor path handles absence correctly and
logs it verbatim:

> `light sensor absent (No I2C device at address: 0x29) -- publishing silence (state=absent), no fabricated samples`

### 5a. SCOPE NARROWED by a live unplug test (2026-08-17 20:10Z) — the hole is ONE path, not three

The CIO unplugged the IMU mid-session (he had moved it into its enclosure — which also dates the
hardware change to exactly the good-data/zero-data boundary). That gave a free controlled test of the
absence path. Result:

| Reader path | Behaviour | Verdict |
|---|---|---|
| Device absent at startup probe | `imu sensor present/absent` gate; publishes silence | **honest** |
| Read raises (device pulled mid-run) | `imu read failed (seq=N, [Errno 121] Remote I/O error) -- no sample this poll`; **writes nothing** | **honest (proven live)** |
| **Read SUCCEEDS returning all-zero values** | **writes the frame as `data_source='real'`** | **THE DEFECT** |

Proof writes actually stopped: total rows `3,188,805` at `20:10:21Z` and still `3,188,805` at `20:11:26Z`
(65 s later, zero growth), while the journal logged read failures at 50 Hz throughout.

**This materially narrows the fix.** My original framing ("the probe gate only distinguishes absent from
present") was too broad — the error path is already correct. The driver returns `0.0` *without raising*,
so the reader receives an apparently-successful read and has no signal that anything is wrong. The fix
is therefore a **plausibility gate on the SUCCESS path only** — no rework of absence or error handling,
both of which are already sound.

43,203 fabricated rows today, all from the one uncovered path.

**Containment (verified, and it limits the blast radius):** `edr_imu_sample` is **NOT** in the sync
table set — the live sync log lists 12 tables, none EDR, and `edr_imu_sample` appears only in
`src/common/edr/sensor_schema.py`. Contamination is **Pi-local**; the server is clean. (Matches the
Sprint-50 ADR: raw = Pi-local this phase, server sync = F-115.) **F-115 must not ship until this is
fixed, or it exports the fabrication.**

**The honest-availability layer WORKED and should be credited.** `imu_state_bridge.py:415` refuses to
derive attitude from a sub-threshold gravity vector (`_norm(gravity) < _MIN_GRAVITY_MS2`) and writes
`available:false` + `reasons: {... "tilt_unresolved"}` — verified in the live `states/imu`. The *display*
is honest; only the *persistence* path fabricates. That asymmetry is the finding.

### 5b. HARDWARE RESOLVED (2026-08-17 20:29Z) — software defect STANDS

The CIO re-seated the IMU (he had just moved it into its enclosure) and the service was restarted
cleanly. The sensor now produces real data:

```
ts_utc                accel_x  accel_y  accel_z    |g|
2026-08-17T20:29:18Z   4.827   -3.373    8.097   10.012
2026-08-17T20:29:17Z   4.741   -3.340    8.071    9.938
```

`|g| ~= 9.98 m/s^2` = gravity, correctly scaled. `states/imu` flipped to `available:true` with
`gLat`/`gLon` ~= 0.004 g (correct for a stationary vehicle). `temp_c` is NULL — **correct**, the genuine
Adafruit board does not expose that attribute and US-500 made it an honest null.

**Root cause: physical.** Re-seating the connector plus a genuine power-cycle of the sensor cleared it.
I cannot cleanly separate "loose connection disturbed by the enclosure move" from "chip latched in a bad
state"; both fit. The enclosure move dates it, the re-seat fixed it. Stated as such — not resolved
further.

**Operational fact (belongs in the runbook): the IMU cannot be hot-plugged.** The driver initialises the
chip ONLY at the startup probe, so a re-seat without a service restart leaves it asleep in its `0x41`
power-on default and reads fail (`Errno 121`) or return zeros. Always restart `eclipse-obd` after
touching the sensor. This also produced a near-miss in this session: a first restart silently did not
execute (`NRestarts=0`, unchanged `ActiveEnterTimestamp`) and the resulting zeros looked exactly like
the hardware fault — a false negative that would have condemned good hardware. **Verify a restart
actually happened before interpreting sensor output.**

**The software defect (§5a) is NOT closed by this.** The plausibility gate is still owed, and this
episode is its strongest justification: had it existed, the failure would have surfaced the moment it
began ("sensor mute") instead of 43,203 silent false rows later. Urgency drops from "actively writing
bad rows" to "uncovered path, will recur on the next sensor fault" — still P1+, no longer emergency.

### 5b-i. OPERATIONAL HAZARD — **never `i2cdetect` a live bus** (my error, 2026-08-17 15:45Z)

**I wedged the Pi's I²C bus with a diagnostic command, then misattributed it to the CIO's wiring.**
Recording it because the failure mode is expensive and non-obvious.

Timeline, from the Pi itself:

```
15:40:39  boot
15:43:00  "imu sensor present -- reader armed"   <- bus healthy
          (CIO independently confirms live sensor data ON SCREEN)
15:45:39  FIRST "i2c_designware 1f00074000.i2c: controller timed out"  <- my i2cdetect
          271 timeouts follow; both 0x69 and 0x36 unreachable
```

`i2cdetect -y 1` probes every address 0x03-0x77. Run against a bus `eclipse-obd` was already driving
at 50 Hz (IMU) plus the 5 s UPS poll, it collided with in-flight transactions and locked the controller.
**Soft lockup — a power cycle clears it, no damage.** Collateral: the MAX17048 UPS shares the bus, so
battery telemetry went blind too.

**The error beneath the error:** I had explicitly avoided *writing* to the IMU on A-17 grounds
(concurrent access to a device the service owns) and then ran a bus-wide scan — the same hazard.
**A read-only command is not automatically a safe command when the resource is shared.**

**It also produced a false accusation.** I told the CIO the connector was likely seated one pin off or
shorted and to pull it for inspection. His cold re-plug had in fact worked perfectly; his own
observation of on-screen data was the more reliable reading. This is the "condemn good hardware"
failure I had warned him about an hour earlier, committed by me.

**AMENDMENT 2026-08-20 — attribution corrected, rule UNCHANGED.** On 2026-08-20 the same
`i2c_designware ... controller timed out` / `SDA stuck at low` wedge occurred **spontaneously**, ~3 s
after the IMU reader started, with **no `i2cdetect` and no involvement from me** (324 timeouts). So the
bus on this Pi can lock up under a marginal sensor connection alone, and my 08-17 self-attribution was
**over-corrected** — a scan may have been the trigger on an already-fragile bus rather than the cause.
(That instance cleared after the CIO re-seated the IMU; on 2026-08-20 both sensors ran a full 2-leg
drive with a clean bus.) **The standing rule below stands regardless**: a bus-wide scan against a live
50 Hz reader is an unnecessary risk on hardware whose controller does not self-recover.

**Standing rule (Atlas):** never scan the I²C bus while `eclipse-obd` runs. **The state files
(`/run/eclipse-obd/states/*`) and `edr_imu_sample` ARE the sanctioned read path** — written by the
single owner of the hardware, free to read, and sufficient to answer "is it converting / is gravity
real / is the state honest." Reaching past the provider to the device is an SSOT violation with a
physical cost. Direct register reads are justified ONLY when the state file genuinely cannot
discriminate (e.g. distinguishing "asleep" from "dead" during the mute window) and preferably with the
service stopped.

### 5c. NEW (deferred by CIO) — mount frame is unconfigured, so pitch/grade are confidently wrong

With the sensor live and the car parked, `states/imu` reports `pitchDeg: 23.29`, `gradePct: 43.0`. A 43%
grade on a parked car is wrong. Not a sensor fault: gravity is spread across all three axes
(4.8 / -3.4 / 8.1), i.e. the board sits tilted in its enclosure, while `pi.sensors.imu.mount` still holds
the DEFAULT identity map `{"forward":"+x","left":"+y","up":"+z"}` — which assumes flat + nose-forward.

This is the **axis-orientation decision flagged to Spool 2026-06-28**, now live and material. The design
anticipated it correctly: it is a pure CONFIG edit, never a code edit (`imu_state_bridge.py:227`).

**Note the honesty gap:** the system publishes `available:true` on a value derived through an assumption
it has no evidence for. Gravity's magnitude IS measurable at rest, so "is my mount frame plausible?" is
an answerable question the transform tier currently never asks — the same class as §5a.

**CIO decision 2026-08-17: DEFERRED.** He will physically mount + level the unit in the car first, then
zero/calibrate. Calibrating against a temporary bench position would bake in a value to be discarded.
**Correct call — do NOT groom a mount-config story yet.** Owed to Atlas when the physical install is
done: derive the mount axis map (or a zero-offset calibration) from a captured level-reference gravity
vector.

**Two separable problems — do not conflate them:**

1. **Hardware (CIO, physical).** The MEMS/analog core is not converting though the digital die is fine.
   It worked through Aug 12 and failed on today's boot, which correlates with the light sensor being
   unplugged — a harness/seating disturbance or a marginal supply to the sensor's analog rail is the
   leading hypothesis. **I cannot resolve this remotely; it needs a physical re-seat + a continuity/
   voltage check.** This is the same "digital alive / die dead" signature I flagged on the 2026-07-04
   clone boards, now on the genuine part.
2. **Software (Ralph, repo).** Regardless of the hardware outcome, the reader must not persist
   all-zero frames as `real`. **A dead sensor must publish silence, exactly as the light path does.**

**Fix shape.** Add an output-plausibility gate to the IMU reader: a frame whose accel magnitude is below
`MIN_GRAVITY_MS2` (a rest frame MUST read ~9.81 m/s²) is not a reading — publish silence + flip the
source to `absent` with a distinct reason (`sensor_mute` / `implausible_frame`, NOT `sensor_absent`,
which would misreport an enumerated chip). Die temperature `== 0` is a second, independent tell.

---

## 6. WiFi — reported honestly: it does not exist

The CIO's task named "wifi indicator". **There is none.** Zero hits for `wifi|WiFi|wlan` across
`specs/UI/dist/` and `src/pi/splash/`. It is not mis-wired — it is absent. Flagging rather than
silently omitting, since the CIO expected it. If wanted, it belongs in `system-status` as another
Pi-local source under the honest-availability contract (and would pair naturally with F-4's bond fact).

---

## 7. What is correctly wired (14 facts — do not re-litigate)

Power glyph (`PowerModeProvider` + `PowerSourceProvider`, both single providers, shared read with
battery-health); sync glyph; DTC ribbon/takeover/detail (one cached `dtc` payload); System-Status
drill-down (same `tiles` object as card + summary); all six card bodies to one-writer state files
(`imu`, `dtc`, `system-status`, `battery-health`, `ltft-trend`, `light`); Settings rows
(`overlay.readEffectiveValue`, per-request, the US-530 shared seam — the A-4 divergence guard at
`states_http_server.py:625` is present); splash degraded/ring (`boot-state`); shutdown animation
(`shutdown-state`).

---

## 8. Recommended routing

| Item | Owner | Priority |
|---|---|---|
| F-5 software (silence-not-zeros) | Ralph | **P0** — actively writing false rows at 25 Hz |
| F-5 hardware (re-seat + power check) | CIO | **P0** — physical, blocks IMU cards |
| F-1 syncPending (both layers, one story) | Ralph | P1 |
| F-3 clock trust (wire the existing provider) | Ralph | P1 |
| F-2 version single-provider | Ralph | P2 — one-line |
| F-4 glyph retitle / bond fact | Iris + Ralph | P2 |
| WiFi indicator (new capability) | PM groom | backlog |

**Gate:** F-115 (EDR server sync) must not ship while F-5 software is open.

---

## 9. Scope + honesty notes

- Code audit against `dev` + live register/DB probes on the Pi. I did **not** modify the Pi: every live
  command was read-only (`i2cget`, `i2cdetect`, `sqlite3 mode=ro`, `journalctl`). I deliberately did
  **not** write to the IMU (reset/re-init) while `eclipse-obd` holds the bus — concurrent access to a
  device the service owns is the A-17 hazard.
- The IMU hardware root cause is **not** established — I have proven the failure mode (digital alive,
  output block dead) and the timeline, not the cause. The wiring-disturbance correlation is a
  hypothesis, stated as such.
- OBD connect failures in today's journal are expected (car off — the OBDLink LX powers only engine-ON)
  and are NOT evidence of an A-17 regression.

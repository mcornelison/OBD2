# MAX17048 SoC% Cold-Start Calibration Protocol (US-431 / F-048)

**Purpose:** measure how long the MAX17048 ModelGauge takes to settle after a
cold power-up, so the cold-start guard window
(`pi.hardware.upsMonitor.socColdStartWindowSeconds`) is set from **real bench
data**, not the guessed 180 s constant.

**Tier:** Pi 5 (`chi-eclipse-01`), on the UPS-drain rig. Bench-only.

**Owner:** CIO runs the physical cycle; Spool interprets. Ralph built the tooling
(`scripts/calibrate_max17048.py`).

---

## Why this exists

The MAX17048 ModelGauge needs a few minutes of observation after a fresh
power-up before its SoC register is meaningful. Spool's drain tests measured a
**40-percentage-point** gauge-vs-VCELL divergence during that window
(`offices/pm/backlog/F-048-max17048-calibration-learning-run.md`):

| Moment | SOC% reported | VCELL measured | Reality |
|---|---|---|---|
| Drive 5 start | 60% | 4.200 V | Full charge, **40-pt error** |

Because of this, US-234 moved the shutdown ladder off SoC% onto VCELL, and
US-427 added an honest-instrument guard: any register read taken within
`socColdStartWindowSeconds` of power-up is recorded as **NULL**, never a garbage
percent. That window was a guess (180 s). This protocol replaces the guess.

## What the tool does

`scripts/calibrate_max17048.py`:

1. Samples the register SoC% (with VCELL and CRATE) at a fixed cadence.
2. Logs every sample to a CSV (schema-free — **no `battery_health_log`
   change**), including per-sample `soc_error_pct` when you pass a known
   `--reference-soc`.
3. Finds the first moment the reading enters and **holds** a tolerance band
   around its settled value, and prints a margin-padded **recommended window**.

Grounded defaults (all overridable):

| Flag | Default | Grounding |
|---|---|---|
| `--interval` | 5 s | `UpsMonitor.DEFAULT_POLL_INTERVAL` / `drain_log_simple.sh` cadence |
| `--duration` | 600 s | ≥3× the current 180 s guard, so settling is observed past it |
| `--settle-tolerance` | ±2 pct | register is integer-percent → ±2 % = within 2 LSB of steady |
| `--settle-window` | 30 s | must hold in-band ≥30 s (≥6 samples) — one transient can't declare settle |
| margin / round | ×1.5, →10 s | pad measured settle 50 %, round up to a 10 s bucket |

---

## Procedure

### 1. Prerequisites

- Battery **≥ 3.9 V** at the start (a freshly-charged cell is ideal — then you
  can pass `--reference-soc 100`).
- Pi on the UPS-drain rig, **fully powered off** (a true cold start — the point
  is to observe the gauge from power-up).

### 2. Cold power-up + immediate capture

Power the Pi up and start the tool **as soon as it boots** (the settle clock is
system uptime, so start promptly):

```bash
python scripts/calibrate_max17048.py --reference-soc 100 \
    --output calibrate_max17048_$(date +%Y%m%d).csv
```

Let it run the full `--duration` (default 10 min). For a slow gauge, extend it:
`--duration 900`.

### 3. Read the recommendation

At the end the tool prints, e.g.:

```
Calibration result
------------------
valid samples:    120
final soc:        80 pct
peak deviation:   38 pct
settled at:       165s
Recommended cold-start window: 250s
  -> set pi.hardware.upsMonitor.socColdStartWindowSeconds = 250 in config.json
```

If it prints **DID NOT SETTLE**, extend `--duration` (or loosen
`--settle-tolerance`) and re-run — the gauge had not converged within the run.

### 4. Feed the guard with the measured value

Edit `config.json`:

```json
"pi": { "hardware": { "upsMonitor": {
    "socColdStartWindowSeconds": 250.0
} } }
```

Validate: `python validate_config.py`. This value is consumed at runtime by
`scripts/record_drain_test.py` (`_resolveColdStartWindowSeconds`) — a register
read inside the window still records NULL, but the window is now data-backed.

### 5. Document + archive

Keep the CSV with the drain-test artifacts and note the run in the tuner log
(date, battery start voltage, settle time, recommended window). Re-run if the
battery is replaced or gauge drift returns.

---

## Related

- `scripts/record_drain_test.py` — consumes `socColdStartWindowSeconds`.
- `src/pi/hardware/ups_monitor.py` — `getBatteryPercentage()` (SOC 0x04).
- `offices/pm/backlog/F-048-max17048-calibration-learning-run.md` — origin + data.
- `specs/architecture.md` "Battery Health Log" — schema context (US-426 columns).

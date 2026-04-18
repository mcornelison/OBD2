# US-184 — CIO Physical Unplug Drill Checklist

**Scope**: prove that `UpsMonitor.getPowerSource()` flips from `EXTERNAL`
to `BATTERY` within the rolling window (default 60 s) when wall power is
physically removed from the Geekworm X1209 UPS HAT, and recovers to
`EXTERNAL` within the window when power is restored.

**Scope NOT covered here**: Ralph's AC coverage (unit + mocked-trend
tests) — already passing in `tests/pi/hardware/test_ups_monitor_power_source.py`
and `tests/pi/hardware/test_ups_monitor_degradation.py`.

**Owner to run this**: CIO (Ralph does not execute the physical unplug per
US-184 AC). Time required: ~5 minutes bench time.

---

## Prerequisites

- [ ] Pi 5 (`chi-eclipse-01`) powered on and reachable over SSH
  (`ssh mcornelison@10.27.27.28 'hostname'` returns `chi-eclipse-01`).
- [ ] Geekworm X1209 UPS HAT seated, 18650 LiPo installed and charged
  (>= 40 % SOC to have headroom for the drill).
- [ ] Wall-adapter plugged into the HAT's USB-C input (not into the Pi
  directly) — the HAT is the "wall power" source under test.
- [ ] Latest sprint branch deployed:
  `bash deploy/deploy-pi.sh --restart` (US-176 flow) OR pull + restart
  `eclipse-obd.service` manually.
- [ ] Drill script present: `scripts/ups_unplug_drill.py` (see "Optional:
  live-read script" below — if absent, use the manual Python one-liner).

---

## Baseline (wall-powered, establish EXTERNAL)

Open an SSH terminal and run a 10-sample baseline:

```bash
ssh mcornelison@10.27.27.28
cd ~/Projects/Eclipse-01
~/obd2-venv/bin/python - <<'PY'
from pi.hardware.ups_monitor import UpsMonitor
import time
m = UpsMonitor()
for _ in range(10):
    m.recordHistorySample(time.monotonic(),
                           m.getBatteryVoltage(),
                           m.getBatteryPercentage())
    print(f"t={time.monotonic():.1f} "
          f"V={m.getBatteryVoltage():.4f} "
          f"SOC={m.getBatteryPercentage()}% "
          f"CRATE={m.getChargeRatePercentPerHour()} "
          f"EXT5V={m.getDiagnosticExt5vVoltage()} "
          f"source={m.getPowerSource().value}")
    time.sleep(5)
PY
```

- [ ] Every one of the 10 lines reports `source=external`.
- [ ] VCELL stays within ± 5 mV across the 10 samples (healthy stable
  charge).
- [ ] Either CRATE is None (chip variant without it) OR CRATE >= -0.05
  %/hr (not in the BATTERY regime).
- [ ] Record this output to `offices/pm/drills/US-184-unplug-drill-run.md`
  as "Baseline" section.

---

## Unplug transition (expect EXTERNAL -> BATTERY)

Keep the Python session running and continuously polling. With the
session alive:

1. [ ] **Pull the USB-C adapter from the wall** (not from the HAT — we
   want the HAT to be the one detecting the input loss).
2. [ ] Record the wall-clock time of the pull.
3. [ ] Watch the console for up to `historyWindowSeconds` (60 s default).

Expected progression within 60 s of the pull:

- [ ] VCELL begins to droop (typically 10-50 mV in the first window
  under a running Pi 5 load).
- [ ] `source=external` flips to `source=battery` on one of the sample
  lines.
- [ ] If CRATE is populated on your chip, it goes negative before source
  flips; if 0xFFFF, VCELL slope carries the decision alone.
- [ ] Record the elapsed time between pull and source flip.

**STOP and surface to PM if:**

- VCELL does not drop within 60 s (the HAT may not be switching to
  battery — power-path issue, possibly a fuse or FET problem).
- `source` stays `external` for the full 60 s despite a visible VCELL
  drop (slope-threshold too loose for this chip/load; do NOT silently
  re-tune — file feedback with the slope values observed).

---

## Replug recovery (expect BATTERY -> EXTERNAL)

Leaving the Python session running:

1. [ ] **Plug the USB-C adapter back into the wall.**
2. [ ] Record the wall-clock time of the replug.
3. [ ] Watch up to `historyWindowSeconds` (60 s default).

Expected:

- [ ] VCELL stops dropping; may rise slightly as the charger takes over.
- [ ] `source=battery` flips back to `source=external`.
- [ ] Record the elapsed time between replug and source flip.

**STOP and surface to PM if:**

- Source stays `battery` for the full window after replug (rising VCELL
  isn't crossing the `-0.02` threshold from below — usually expected,
  since a steady-state charging cell has slope ~0, which is above the
  threshold).
- Source oscillates between `battery` and `external` more than once per
  30 s during the replug — excessive flapping, file feedback with the
  slope values observed.

---

## Evidence capture

Save the full session transcript (baseline + unplug + replug) to:

```
offices/pm/drills/US-184-unplug-drill-run.md
```

Include:

- Session date/time (UTC).
- Pi hostname (`chi-eclipse-01`).
- Raw console output from the Python session (all three phases).
- Observed elapsed time: pull → source=battery, replug → source=external.
- Any anomalies (VCELL did not drop / flap / unexpected CRATE value).

Attach or reference this run in the US-184 story completion notes so
the PM can verify the sprint-exit evidence.

---

## Optional: live-read script

If you prefer a polished script over the one-liner above, Ralph can
generate `scripts/ups_unplug_drill.py` in a follow-up — ask in PM
inbox. The one-liner is sufficient for a single drill.

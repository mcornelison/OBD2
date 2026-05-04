# Bash Baseline-Truth Power Logger (Independent of Production Code Path)
**Date**: 2026-05-03
**From**: Spool (Tuning SME)
**To**: Ralph (Developer)
**Priority**: Routine — supplemental tooling for the ladder fix work

## Honesty correction up front

CIO asked me to send you "the simple shell power monitor script you have been using for our baseline truth." **I sketched this script earlier in a conversation but never actually deployed it.** What we've actually been using is the Python forensic logger (`scripts/drain_forensics.py` driven by the systemd timer) — which is the system-under-test in part, not an independent ground truth.

So here's what the bash script SHOULD have been. Recommend you keep it as a backup diagnostic tool that's **fully independent of the production Python code path** — when the production code is what's broken (as in Sprints 21-24), an independent reference like this catches bugs that mock-laden unit tests miss.

## Why an independent bash script matters for Sprint 25

The 9-drain saga has cost the project a lot of cycles. One of the contributing factors: **every diagnostic tool we built (forensic logger, tick instrumentation, orchestrator-state-file writer, dashboard stage label) lives in the same Python codebase as the bug.** If the Python import path is broken (recall Sprint 22 deploy gap where the forensic logger no-oped because PYTHONPATH was unset), or if the production code's view of `power_source` is wrong, our diagnostic tools may share the same wrong view.

A bash script that talks directly to the MAX17048 over i2cget and to the Pi5 over vcgencmd has **zero shared code path with the production Python**. If the bash script reports VCELL=3.4V and the Python orchestrator reports `vcell=3.4 reason=power_source!=BATTERY`, you've definitively isolated the bug to the orchestrator's logic — not the I2C read, not the value conversion, not the threshold constants. That's the diagnostic value Sprint 25 needs.

Similarly, when the next drain test runs, this bash script gives you a **second CSV stream** to cross-correlate against the Python forensic logger. If they agree on VCELL trajectory, throttled_hex, and load_1min — your forensic logger is trustworthy. If they disagree — there's a bug in the forensic logger you can find before it misleads anyone.

## The Script

Save as `scripts/drain_log_simple.sh`, `chmod +x`, run as `sudo nohup ./drain_log_simple.sh &` (i2cget needs root; vcgencmd doesn't).

```bash
#!/bin/bash
###############################################################################
# drain_log_simple.sh — Independent baseline-truth power telemetry logger.
#
# Purpose: capture MAX17048 + Pi5 power state every 5 sec to a CSV file,
# using ONLY i2cget, vcgencmd, awk, and bc. ZERO shared code path with the
# production Python eclipse-obd service. Use to cross-correlate against the
# Python forensic logger (scripts/drain_forensics.py) and to provide an
# independent ground truth when the production code is the system under test.
#
# Output: /var/log/eclipse-obd/drain-bash-YYYYMMDDTHHMMSSZ.csv
# Cadence: every 5 seconds, append + sync after every row.
# Stop: kill the process, or just pull power (data flushed via sync()).
#
# Author: Spool (Tuning SME) — 2026-05-03 — companion to the 9-drain-saga
#         closeout work.
###############################################################################

set -u

LOG_DIR="${LOG_DIR:-/var/log/eclipse-obd}"
mkdir -p "$LOG_DIR"
TS_START=$(date -u +%Y%m%dT%H%M%SZ)
OUT="${LOG_DIR}/drain-bash-${TS_START}.csv"
EPOCH_START=$(date +%s)

I2C_BUS=1
ADDR=0x36   # MAX17048 fuel gauge

# CSV header — 9 columns
echo "timestamp_utc,seconds_since_start,vcell_v,soc_pct,crate_pct_per_hr,cpu_temp_c,core_v,throttled_hex,load_1min" > "$OUT"
sync

# Clean exit on SIGTERM/SIGINT
trap 'echo "# SIGNAL RECEIVED — exiting cleanly at $(date -u +%FT%TZ)" >> "$OUT"; sync; exit 0' TERM INT

while true; do
    # Wall-clock UTC ISO-8601 + monotonic seconds since start
    TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    SECS=$(( $(date +%s) - EPOCH_START ))

    # MAX17048 VCELL register 0x02 — 2 bytes big-endian, raw × 78.125 µV/LSB
    VCELL_HI=$(i2cget -y "$I2C_BUS" "$ADDR" 0x02 b 2>/dev/null || echo "ERR")
    VCELL_LO=$(i2cget -y "$I2C_BUS" "$ADDR" 0x03 b 2>/dev/null || echo "ERR")
    if [ "$VCELL_HI" = "ERR" ] || [ "$VCELL_LO" = "ERR" ]; then
        VCELL_V="i2c_err"
    else
        VCELL_RAW=$(( VCELL_HI << 8 | VCELL_LO ))
        VCELL_V=$(echo "scale=5; $VCELL_RAW * 78.125 / 1000000" | bc)
    fi

    # MAX17048 SOC register 0x04 — high byte = integer percent
    SOC_RAW=$(i2cget -y "$I2C_BUS" "$ADDR" 0x04 b 2>/dev/null || echo "ERR")
    if [ "$SOC_RAW" = "ERR" ]; then
        SOC_PCT="i2c_err"
    else
        SOC_PCT=$(( SOC_RAW ))
    fi

    # MAX17048 CRATE register 0x16 — signed 16-bit big-endian × 0.208 %/hr/LSB
    # 0xFFFF is the "disabled" sentinel per the chip datasheet
    CRATE_HI=$(i2cget -y "$I2C_BUS" "$ADDR" 0x16 b 2>/dev/null || echo "ERR")
    CRATE_LO=$(i2cget -y "$I2C_BUS" "$ADDR" 0x17 b 2>/dev/null || echo "ERR")
    if [ "$CRATE_HI" = "ERR" ] || [ "$CRATE_LO" = "ERR" ]; then
        CRATE_PCT_PER_HR="i2c_err"
    else
        CRATE_RAW=$(( CRATE_HI << 8 | CRATE_LO ))
        if [ "$CRATE_RAW" -eq 65535 ]; then
            CRATE_PCT_PER_HR="disabled"
        else
            # Sign-extend negative 16-bit values
            if [ "$CRATE_RAW" -ge 32768 ]; then
                CRATE_RAW=$(( CRATE_RAW - 65536 ))
            fi
            CRATE_PCT_PER_HR=$(echo "scale=3; $CRATE_RAW * 0.208" | bc)
        fi
    fi

    # Pi5 SoC state via vcgencmd (no I2C dependency)
    CPU_TEMP=$(vcgencmd measure_temp 2>/dev/null | sed -e 's/temp=//' -e "s/'C\$//" || echo "err")
    CORE_V=$(vcgencmd measure_volts core 2>/dev/null | sed -e 's/volt=//' -e 's/V$//' || echo "err")
    THROTTLED=$(vcgencmd get_throttled 2>/dev/null | sed 's/throttled=//' || echo "err")

    # Load average — 1-min field from /proc/loadavg
    LOAD_1MIN=$(awk '{print $1}' /proc/loadavg)

    # Append the row + fsync via sync(). At 5s cadence, a hard-crash loses
    # at most one in-flight row.
    echo "${TS},${SECS},${VCELL_V},${SOC_PCT},${CRATE_PCT_PER_HR},${CPU_TEMP},${CORE_V},${THROTTLED},${LOAD_1MIN}" >> "$OUT"
    sync

    sleep 5
done
```

## CSV column reference (matches the production forensic logger where overlapping)

| Column | Source | Notes |
|---|---|---|
| `timestamp_utc` | `date -u` | Wall clock anchor |
| `seconds_since_start` | epoch delta | Drain curve x-axis |
| `vcell_v` | MAX17048 reg 0x02 | THE primary trigger value the ladder reads |
| `soc_pct` | MAX17048 reg 0x04 | Useful for trend; calibration known-broken |
| `crate_pct_per_hr` | MAX17048 reg 0x16 | Discharge rate; "disabled" if chip not tracking |
| `cpu_temp_c` | `vcgencmd measure_temp` | Heat correlates with current draw |
| `core_v` | `vcgencmd measure_volts core` | Pi rail health |
| `throttled_hex` | `vcgencmd get_throttled` | **Bit 0 = undervolt NOW, bit 16 = since boot** |
| `load_1min` | `/proc/loadavg` | Process load proxy |

## What it deliberately does NOT do

- **No AC/battery detection.** Logs unconditionally every 5s. Detecting AC vs battery in pure bash without trusting the production Python is hard, and the timestamp + VCELL trajectory tell you when the transition happened anyway.
- **No SQLite writes.** CSV-only. SQLite needs the Python codebase or sqlite3 CLI; CSV is universally diff-able and openable in Excel.
- **No systemd integration.** Run as `nohup ./drain_log_simple.sh &` for the duration of a drain test. No service install, no PYTHONPATH, no environment dependency. If it dies, restart it manually — that's the price of zero shared code.
- **No orchestrator state introspection.** Cannot read `pd_stage` or `pd_tick_count` (those would require either reading from the Python orchestrator's runtime memory or reading the orchestrator-state-file the Python code is supposed to write). That's the production logger's job. This script is the LIMITED but TRUSTED ground truth.

## How to use it for Drain Test 10

1. Deploy your fix (`/etc/systemd/system/eclipse-obd.service` restarted).
2. Start this bash script in parallel: `sudo nohup /home/mcornelison/Projects/Eclipse-01/scripts/drain_log_simple.sh &`
3. Pull wall power. Both the Python forensic logger AND this bash script will capture the drain.
4. After the Pi dies and reboots:
   - Pull the bash CSV: `/var/log/eclipse-obd/drain-bash-YYYYMMDDTHHMMSSZ.csv`
   - Pull the Python CSV: `/var/log/eclipse-obd/drain-forensics-YYYYMMDDTHHMMSSZ.csv`
   - Diff them on `timestamp_utc`, `vcell_v`, `throttled_hex`, `load_1min` — they should agree
5. If they disagree, you've got a bug in the Python forensic logger — find it before trusting either CSV
6. If they agree AND the Python tick instrumentation logs show the ladder firing AND `power_log` has STAGE_* rows AND boot table shows clean shutdown — Drain Test 10 PASSES and the saga closes

## Sources

- MAX17048 datasheet (register map): VCELL @ 0x02, SOC @ 0x04, CRATE @ 0x16
- Project memory: `MEMORY.md` "MAX17048 UPS semantics" section — confirms register addresses + 0xFFFF "disabled" sentinel for CRATE
- vcgencmd `get_throttled` bit layout: Raspberry Pi documentation; bit 0 = undervolt NOW, bit 16 = undervolt occurred since boot

— Spool

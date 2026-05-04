#!/bin/bash
###############################################################################
# drain_log_simple.sh -- Independent baseline-truth power telemetry logger.
#
# Purpose: capture MAX17048 + Pi5 power state every 5 sec to a CSV file,
# using ONLY i2cget, vcgencmd, awk, and bc.  ZERO shared code path with the
# production Python eclipse-obd service.  Use to cross-correlate against the
# Python forensic logger (scripts/drain_forensics.py) and to provide an
# independent ground truth when the production code is the system under test.
#
# V0.24.1 hotfix companion (per Spool 2026-05-03 inbox note): every diagnostic
# tool we built across Sprints 21-24 (forensic logger, tick instrumentation,
# orchestrator-state-file writer, dashboard stage label) lives in the same
# Python codebase as the bug.  When the bug IS the Python code (as it was for
# 9 drain tests), our diagnostics may share the same wrong view.  This bash
# script talks directly to MAX17048 over i2cget and to the Pi5 over vcgencmd;
# if the Python forensic logger and this CSV agree, the production logger is
# trustworthy.  If they disagree, the production logger has its own bug.
#
# Output: /var/log/eclipse-obd/drain-bash-YYYYMMDDTHHMMSSZ.csv
# Cadence: every 5 seconds, append + sync after every row.
# Stop:    kill the process, or just pull power (data flushed via sync()).
#
# Usage:
#     sudo nohup /home/mcornelison/Projects/Eclipse-01/scripts/drain_log_simple.sh &
#
# Requires: i2cget (i2c-tools), vcgencmd (raspberrypi-utils), bc, awk.
#
# Author: Spool (Tuning SME) -- 2026-05-03 -- 9-drain-saga closeout work.
###############################################################################

set -u

LOG_DIR="${LOG_DIR:-/var/log/eclipse-obd}"
mkdir -p "$LOG_DIR"
TS_START=$(date -u +%Y%m%dT%H%M%SZ)
OUT="${LOG_DIR}/drain-bash-${TS_START}.csv"
EPOCH_START=$(date +%s)

I2C_BUS=1
ADDR=0x36   # MAX17048 fuel gauge

# CSV header -- 9 columns
echo "timestamp_utc,seconds_since_start,vcell_v,soc_pct,crate_pct_per_hr,cpu_temp_c,core_v,throttled_hex,load_1min" > "$OUT"
sync

# Clean exit on SIGTERM/SIGINT
trap 'echo "# SIGNAL RECEIVED -- exiting cleanly at $(date -u +%FT%TZ)" >> "$OUT"; sync; exit 0' TERM INT

while true; do
    TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
    SECS=$(( $(date +%s) - EPOCH_START ))

    # MAX17048 VCELL register 0x02 -- 2 bytes big-endian, raw x 78.125 uV/LSB.
    VCELL_HI=$(i2cget -y "$I2C_BUS" "$ADDR" 0x02 b 2>/dev/null || echo "ERR")
    VCELL_LO=$(i2cget -y "$I2C_BUS" "$ADDR" 0x03 b 2>/dev/null || echo "ERR")
    if [ "$VCELL_HI" = "ERR" ] || [ "$VCELL_LO" = "ERR" ]; then
        VCELL_V="i2c_err"
    else
        VCELL_RAW=$(( VCELL_HI << 8 | VCELL_LO ))
        VCELL_V=$(echo "scale=5; $VCELL_RAW * 78.125 / 1000000" | bc)
    fi

    # MAX17048 SOC register 0x04 -- high byte = integer percent.
    SOC_RAW=$(i2cget -y "$I2C_BUS" "$ADDR" 0x04 b 2>/dev/null || echo "ERR")
    if [ "$SOC_RAW" = "ERR" ]; then
        SOC_PCT="i2c_err"
    else
        SOC_PCT=$(( SOC_RAW ))
    fi

    # MAX17048 CRATE register 0x16 -- signed 16-bit big-endian x 0.208 %/hr/LSB.
    # 0xFFFF is the "disabled" sentinel per the chip datasheet.
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

    # Pi5 SoC state via vcgencmd (no I2C dependency).
    CPU_TEMP=$(vcgencmd measure_temp 2>/dev/null | sed -e 's/temp=//' -e "s/'C\$//" || echo "err")
    CORE_V=$(vcgencmd measure_volts core 2>/dev/null | sed -e 's/volt=//' -e 's/V$//' || echo "err")
    THROTTLED=$(vcgencmd get_throttled 2>/dev/null | sed 's/throttled=//' || echo "err")

    # Load average -- 1-min field from /proc/loadavg.
    LOAD_1MIN=$(awk '{print $1}' /proc/loadavg)

    # Append the row + fsync via sync().  At 5s cadence, a hard-crash loses
    # at most one in-flight row.
    echo "${TS},${SECS},${VCELL_V},${SOC_PCT},${CRATE_PCT_PER_HR},${CPU_TEMP},${CORE_V},${THROTTLED},${LOAD_1MIN}" >> "$OUT"
    sync

    sleep 5
done

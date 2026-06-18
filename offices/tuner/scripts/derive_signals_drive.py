#!/usr/bin/env python3
"""
File:        derive_signals_drive.py
Author:      Spool (Tuning SME)
Created:     2026-06-18
Purpose:     Derive higher-order tuning signals from a single drive's raw OBD
             log (EAV CSV: timestamp,parameter_name,value). No new hardware --
             re-contextualizes data we already have.
Signals:     (1) per-sample GEAR via speed/RPM vs F5M33 ratios + shift points;
             (2) ENGINE_LOAD distribution by gear (honest stand-in for
             grade-corrected load -- true grade needs the IMU we don't have);
             (3) throttle tip-in / spool events (MAF + load rise; proxy only,
             no boost/MAP PID on this car's live set).
Grounding:   F5M33 stock reduction + Potenza 205/55R16 rolling circ, both
             cross-validated -- see offices/tuner/cards/. SPEED PID reads TRUE
             (factor 1.00, GPS Drive-27). SPEED stored in km/h.
Usage:       python derive_signals_drive.py <csv_path>
"""

import sys
import csv
from datetime import datetime, timezone

# --- Grounded constants (offices/tuner/cards/) ---------------------------------
# Total reduction = gear_ratio * final_drive (4.153), stock F5M33.
GEAR_REDUCTION = {1: 12.83, 2: 7.61, 3: 5.054, 4: 3.69, 5: 3.077}
TIRE_CIRC_M = 1.985          # geometric rolling circumference, 205/55R16
# speed_kmh = RPM * circ_m * 0.06 / reduction  ->  reduction = RPM * K / speed_kmh
K_REDUCTION = TIRE_CIRC_M * 0.06   # 0.1191

# Gates: below these, gear is undefined (idle, creep, clutch-in, launch slip).
MIN_SPEED_KMH = 5.0
MIN_RPM = 900.0
MAX_REL_ERR = 0.15           # >15% off nearest ratio = ambiguous (shift/slip)
TIPIN_THROTTLE_JUMP = 8.0    # percentage-point rise step-to-step = tip-in
GRID_HZ = 1.0                # resample onto a regular grid (PIDs arrive ~0.39Hz
                             # each, interleaved -- forward-fill then sample)
GEAR_HOLD_S = 2              # a gear must persist this long to count (debounce;
                             # kills fresh-RPM/stale-SPEED phantom shifts)


def parseTs(s: str) -> float:
    """Convert ISO-8601 UTC to epoch seconds."""
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc).timestamp()


def assignGear(rpm: float, speedKmh: float):
    """Return (gear|None, rel_err). None = undefined or ambiguous."""
    if speedKmh < MIN_SPEED_KMH or rpm < MIN_RPM:
        return None, None
    rImplied = rpm * K_REDUCTION / speedKmh
    best, bestErr = None, 1e9
    for g, r in GEAR_REDUCTION.items():
        err = abs(rImplied - r) / r
        if err < bestErr:
            best, bestErr = g, err
    if bestErr > MAX_REL_ERR:
        return None, bestErr
    return best, bestErr


def loadForwardFilled(path: str):
    """Read EAV CSV, forward-fill each param onto a unified timeline."""
    rows = []
    with open(path, newline="") as f:
        for ts, name, val in csv.reader(f):
            try:
                rows.append((parseTs(ts), name, float(val)))
            except (ValueError, TypeError):
                continue
    rows.sort(key=lambda r: r[0])
    state, timeline = {}, []
    for ts, name, val in rows:
        state[name] = val
        timeline.append((ts, dict(state)))
    return timeline


def main():
    if len(sys.argv) < 2:
        print("usage: python derive_signals_drive.py <csv_path>")
        sys.exit(1)
    timeline = loadForwardFilled(sys.argv[1])
    if not timeline:
        print("no parseable rows")
        sys.exit(1)

    t0 = timeline[0][0]
    durS = timeline[-1][0] - t0

    # Resample forward-filled state onto a regular 1Hz grid so RPM and SPEED are
    # read at the SAME instant (raw rows interleave them ~2.8s apart).
    grid, ptr = [], 0
    step = 1.0 / GRID_HZ
    t = 0.0
    while t <= durS:
        absT = t0 + t
        while ptr + 1 < len(timeline) and timeline[ptr + 1][0] <= absT:
            ptr += 1
        grid.append((t, timeline[ptr][1]))
        t += step

    # Raw gear per grid point.
    rawGear = []
    for t, st in grid:
        rpm, spd = st.get("RPM"), st.get("SPEED")
        g = None
        if rpm is not None and spd is not None:
            g, _ = assignGear(rpm, spd)
        rawGear.append(g)

    # Debounce: only accept a gear change once the new value has held GEAR_HOLD_S.
    stable = [None] * len(rawGear)
    cur = None
    i = 0
    while i < len(rawGear):
        g = rawGear[i]
        if g is not None and g != cur:
            run = 1
            while i + run < len(rawGear) and rawGear[i + run] == g:
                run += 1
            if run >= GEAR_HOLD_S:
                cur = g
        stable[i] = cur
        i += 1

    gearTime = {g: 0.0 for g in GEAR_REDUCTION}
    gearTime["undef/creep"] = 0.0
    loadByGear = {g: [] for g in GEAR_REDUCTION}
    shifts, prevGear, prevThrottle = [], None, None

    for idx, (t, st) in enumerate(grid):
        g = stable[idx]
        if g in GEAR_REDUCTION:
            gearTime[g] += step
            load = st.get("ENGINE_LOAD")
            if load is not None:
                loadByGear[g].append(load)
            if g != prevGear and prevGear is not None:
                shifts.append((round(t, 0), prevGear, g,
                               round(st.get("RPM") or 0),
                               round(st.get("SPEED") or 0)))
            prevGear = g
        else:
            gearTime["undef/creep"] += step

    # tip-ins computed on the grid (throttle rise >= jump threshold)
    tipins = []
    prevThrottle = None
    for t, st in grid:
        thr = st.get("THROTTLE_POS")
        if thr is not None and prevThrottle is not None and \
                thr - prevThrottle >= TIPIN_THROTTLE_JUMP:
            tipins.append((round(t, 0), round(prevThrottle, 1), round(thr, 1),
                           round(st.get("RPM") or 0),
                           round(st.get("ENGINE_LOAD") or 0, 1),
                           round(st.get("MAF") or 0, 1)))
        if thr is not None:
            prevThrottle = thr

    # ---- report ----
    print(f"=== DRIVE DERIVED-SIGNAL PASS ===")
    print(f"duration: {durS/60:.1f} min ({durS:.0f}s), {len(timeline)} samples\n")

    print("--- TIME IN GEAR (moving only) ---")
    movingTotal = sum(gearTime[g] for g in GEAR_REDUCTION)
    for g in GEAR_REDUCTION:
        t = gearTime[g]
        pct = 100 * t / movingTotal if movingTotal else 0
        print(f"  {g} gear : {t:5.0f}s  {pct:4.1f}%")
    print(f"  undef/creep/shift : {gearTime['undef/creep']:.0f}s "
          f"(idle, clutch-in, launch slip, debounced transitions)\n")

    print("--- LOAD BY GEAR (ENGINE_LOAD %) ---")
    for g in GEAR_REDUCTION:
        v = loadByGear[g]
        if v:
            print(f"  {g} gear : avg {sum(v)/len(v):4.1f}  max {max(v):4.1f}  "
                  f"(n={len(v)})")
    print()

    print(f"--- SHIFT EVENTS ({len(shifts)}) ---")
    for t, a, b, rpm, spd in shifts:
        arrow = "UP" if b > a else "DOWN"
        print(f"  t+{t:5.1f}s  {a}->{b} ({arrow})  @ {rpm} rpm, {spd} km/h")
    print()

    print(f"--- TIP-IN / SPOOL EVENTS ({len(tipins)}) ---")
    for t, t0t, t1t, rpm, load, maf in tipins:
        print(f"  t+{t:5.1f}s  throttle {t0t}->{t1t}%  rpm={rpm} "
              f"load={load}% maf={maf}g/s")


if __name__ == "__main__":
    main()

################################################################################
# File Name: reconcile.py
# Purpose/Description: ARCH-047 -- verify a sync ACTUALLY landed. Compares a
#                      bounded source_id range between the Pi's SQLite and the
#                      server's MariaDB: every row present, and every column of
#                      every row equal to what was sent.
# Author: Atlas (ARCH-047, at CIO direction 2026-09-22)
# Creation Date: 2026-09-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Verify a sync by RECONCILIATION, not by the server's receipt.

CIO, 2026-09-22: *"if we send 111 rows, we can do a query on the server and
validate that 111 rows are there ... and match the values and validate what was
sent was actually deposited on the server."*

**This validates the OUTCOME, not the REPORT.** The server's 2xx receipt says
what it CLAIMS; this says what it HAS. (The receipt is separately filed as tech
debt: ``TableResult.errors`` is a hardcoded 0 at all six construction sites, so
reading it would be a check that can never fire.)

🔴 **TWO TRAPS, both of which reported CORRECT data as data loss on the first
live run. Both are pinned by tests.**

1. **The server columns are NARROWER.** ``KIND_TYPES`` maps the ``float`` kind
   to MariaDB ``FLOAT`` -- 4 bytes -- while SQLite ``REAL`` is 8. Every float is
   narrowed in transit BY DESIGN, so a naive ``pi == server`` fails on most
   values. We do not paper over it with a tolerance nobody measured: the Pi
   value is round-tripped through float32 and compared EXACTLY.
   (``monotonic_s`` maps to ``DOUBLE``, so ``ts_capture`` -- the join key -- is
   NOT narrowed and is compared at full width.)

2. 🔴 **DISPLAY TRUNCATION IN THE QUERY CLIENT.** ``prod_db_query.sh`` renders a
   FLOAT to ~6 significant figures. Comparing against ``0.220267`` when the
   stored value is ``0.220266550779342650`` produced **1,190 phantom
   mismatches**. Every float column is therefore selected as
   ``CAST(col AS DECIMAL(40,30))`` -- we ask the database for the VALUE, not for
   its rendering. ⚠️ Scale 30, not 18: DECIMAL(30,18) still truncated a small
   float at 4e-19 and produced 395 further phantom mismatches. THREE layers of
   rendering truncation, each visible only after fixing the one above it.

⚠️ **NEVER compare whole-table counts.** ``pi.sensors.retentionDays`` is 7 and
the purge deletes rows the server already has, so the tiers diverge BY DESIGN
and the gap grows daily. That is exactly how F-114 came to be described as an
"89% Pi-local shortfall" when most of it is the rolling window working. This
tool therefore requires a BOUNDED ``source_id`` range.

⚠️ The join is ``(source_device, source_id)``. ``source_id`` is the **Pi's**
id-space (A-45) -- a row minted into it from the server side was silently
overwritten by the Pi's own.

Usage::

    python -m tools.sync.reconcile --table edr_imu_sample --last 200
    python -m tools.sync.reconcile --table edr_imu_derived --from 58491191 --to 58491390
"""

from __future__ import annotations

import argparse
import json
import struct
import subprocess
import sys
from typing import Any

#: B-044: read from config.json rather than hardcoded. The values already live
#: there (`pi.network.piHost`, `pi.network.piDeviceId`), so this needs no
#: exemption -- and an exemption would have been the wrong fix anyway: it is
#: where a guard goes blind, and the guard was right.
_CONFIG_HOST_KEY = ("pi", "network", "piHost")
_CONFIG_DEVICE_KEY = ("pi", "network", "piDeviceId")
_CONFIG_PI_DB_KEY = ("pi", "network", "piDbPath")

#: Fallbacks used only when config.json cannot be read at all. Deliberately
#: NOT the real host: a tool that silently targets production when its config
#: is missing is worse than one that fails.
_NO_HOST = ""


def _configValue(path: tuple[str, ...], default: str = _NO_HOST) -> str:
    """Read a dotted key out of config.json, or return ``default``."""
    try:
        with open("config.json", encoding="utf-8") as fh:
            node: Any = json.load(fh)
        for key in path:
            node = node[key]
        return str(node)
    except Exception:  # noqa: BLE001 -- a missing config must not crash the tool
        return default


PI_DB = "/home/mcornelison/Projects/Eclipse-01/data/obd.db"

#: Columns the EDR contract declares as kind ``float`` -> MariaDB FLOAT (4-byte).
#: ``ts_capture`` is kind ``monotonic_s`` -> DOUBLE and is deliberately ABSENT.
FLOAT_KIND_COLUMNS: frozenset[str] = frozenset({
    "accel_x", "accel_y", "accel_z",
    "gyro_x", "gyro_y", "gyro_z",
    "mag_x", "mag_y", "mag_z",
    "temp_c", "lux", "pitch_deg", "bias_rad",
})

#: Full-width on both tiers; compared without narrowing.
DOUBLE_COLUMNS: frozenset[str] = frozenset({"ts_capture"})

_NULLISH = {"NULL", "", "None", None}

#: Stored as ISO-8601 TEXT on the Pi and as DATETIME on the server -- the SAME
#: INSTANT rendered two ways ("2026-09-21T19:05:35Z" vs "2026-09-21 19:05:35").
#: Comparing the strings reports every single row as a mismatch, which is how
#: a format difference masquerades as total data loss.
_TIMESTAMP_COLUMNS: frozenset[str] = frozenset({"ts_utc"})


def _normaliseTs(v: Any) -> str:
    """Reduce either rendering to a comparable form. Not a parse -- a normalise."""
    t = str(v).strip().replace("T", " ").rstrip("Z").strip()
    return t[:-4] if t.endswith(".000") else t


def f32(x: float | None) -> float | None:
    """Round through IEEE754 single, exactly as MariaDB FLOAT storage does."""
    if x is None:
        return None
    return struct.unpack("f", struct.pack("f", float(x)))[0]


def compareRow(piRow: dict[str, Any], serverRow: dict[str, Any]) -> list[tuple]:
    """Compare one row's columns. Returns the mismatches, empty when equal."""
    bad: list[tuple] = []
    for col, piV in piRow.items():
        if col not in serverRow:
            continue
        svRaw = serverRow[col]
        piNull, svNull = piV is None, (svRaw in _NULLISH)
        if piNull or svNull:
            if piNull != svNull:
                bad.append((col, piV, svRaw))
            continue
        if col in FLOAT_KIND_COLUMNS or col in DOUBLE_COLUMNS:
            try:
                svV = float(svRaw)
            except (TypeError, ValueError):
                bad.append((col, piV, svRaw))
                continue
            expected = f32(piV) if col in FLOAT_KIND_COLUMNS else float(piV)
            if svV != expected:
                bad.append((col, piV, svRaw))
        elif col in _TIMESTAMP_COLUMNS:
            if _normaliseTs(piV) != _normaliseTs(svRaw):
                bad.append((col, piV, svRaw))
        elif str(piV) != str(svRaw).strip():
            bad.append((col, piV, svRaw))
    return bad


def summarise(
    piCount: int, serverCount: int, missingIds: list[int], mismatches: list[tuple]
) -> dict[str, Any]:
    """Turn the comparison into a PASS/FAIL with a reason that names the cause."""
    if piCount == 0 and serverCount == 0:
        # An empty comparison is not a success. 0 == 0 is the shape of a check
        # that ran against nothing -- the inert guard, in report form.
        verdict, ok = "NO ROWS IN RANGE -- nothing was compared, this is NOT a pass", False
    elif missingIds:
        verdict, ok = f"FAIL: {len(missingIds)} row(s) MISSING on the server", False
    elif mismatches:
        verdict, ok = f"FAIL: {len(mismatches)} VALUE mismatch(es)", False
    else:
        verdict, ok = f"PASS: {piCount} rows present and every column equal", True
    return {
        "verdict": verdict, "pass": ok,
        "piCount": piCount, "serverCount": serverCount,
        "missing": len(missingIds), "mismatches": len(mismatches),
    }


def _piQuery(sql: str, piHost: str) -> list[dict]:
    r = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", piHost, f'sqlite3 -json {PI_DB} "{sql}"'],
        capture_output=True, text=True, encoding="utf-8", timeout=120,
    )
    if r.returncode != 0:
        raise RuntimeError(f"Pi query failed: {r.stderr[-400:]}")
    return json.loads(r.stdout or "[]")


def _serverQuery(sql: str, repoRoot: str) -> list[list[str]]:
    r = subprocess.run(
        ["bash", "tools/pm/prod_db_query.sh", sql],
        capture_output=True, text=True, encoding="utf-8", timeout=180, cwd=repoRoot,
    )
    if r.returncode != 0:
        raise RuntimeError(f"server query failed: {r.stderr[-500:]}")
    return [ln.split("\t") for ln in r.stdout.splitlines() if "\t" in ln]


def _columnsOf(table: str) -> list[str]:
    from src.common.edr.sensor_schema import EDR_COLUMNS
    if table not in EDR_COLUMNS:
        raise SystemExit(f"{table} is not an EDR contract table: {sorted(EDR_COLUMNS)}")
    return [name for name, _kind, _null in EDR_COLUMNS[table]]


def reconcile(
    table: str, idLo: int, idHi: int, repoRoot: str,
    *, piHost: str, sourceDevice: str,
) -> dict[str, Any]:
    cols = _columnsOf(table)
    piRows = _piQuery(
        f"SELECT id, {', '.join(cols)} FROM {table} "
        f"WHERE id BETWEEN {idLo} AND {idHi} ORDER BY id",
        piHost,
    )
    # CAST every float to DECIMAL: we want the VALUE, not the client's rendering.
    sel = ", ".join(
        f"CAST({c} AS DECIMAL(40,30))" if c in FLOAT_KIND_COLUMNS else c for c in cols
    )
    raw = _serverQuery(
        f"SELECT source_id, {sel} FROM {table} "
        f"WHERE source_device='{sourceDevice}' AND source_id BETWEEN {idLo} AND {idHi} "
        f"ORDER BY source_id",
        repoRoot,
    )
    server = {
        int(p[0]): dict(zip(cols, [v.strip() for v in p[1:]], strict=False))
        for p in raw if p and p[0].strip().lstrip("-").isdigit()
    }

    missing, mismatches = [], []
    for r in piRows:
        rid = r.pop("id")
        s = server.get(rid)
        if s is None:
            missing.append(rid)
            continue
        for col, piV, svRaw in compareRow(r, s):
            mismatches.append((rid, col, piV, svRaw))

    out = summarise(len(piRows), len(server), missing, mismatches)
    out.update({"table": table, "idLo": idLo, "idHi": idHi,
                "missingIds": missing[:10], "sampleMismatches": mismatches[:10]})
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Verify a sync landed, row and value.")
    ap.add_argument("--table", required=True)
    ap.add_argument("--last", type=int, help="reconcile the N most recent Pi rows")
    ap.add_argument("--from", dest="idLo", type=int)
    ap.add_argument("--to", dest="idHi", type=int)
    ap.add_argument("--repo-root", dest="repoRoot", default=".")
    ap.add_argument("--pi-host", dest="piHost", default=None,
                    help="overrides pi.network.piHost from config.json")
    ap.add_argument("--source-device", dest="sourceDevice", default=None,
                    help="overrides pi.network.piDeviceId from config.json")
    a = ap.parse_args(argv)
    piHost = a.piHost or _configValue(_CONFIG_HOST_KEY)
    sourceDevice = a.sourceDevice or _configValue(_CONFIG_DEVICE_KEY)
    if not piHost or not sourceDevice:
        ap.error(
            'no Pi host/device: config.json was unreadable and no --pi-host / '
            '--source-device given. Refusing to guess -- a tool that silently '
            'targets the wrong device is worse than one that fails.'
        )

    if a.last:
        rows = _piQuery(f"SELECT MAX(id) AS hi, COUNT(*) AS n FROM {a.table}", piHost)
        hi = rows[0]["hi"]
        if hi is None:
            print("NO ROWS IN RANGE -- the Pi table is empty; this is NOT a pass")
            return 1
        a.idLo, a.idHi = hi - a.last + 1, hi
    if a.idLo is None or a.idHi is None:
        ap.error("give --last N, or both --from and --to. A bounded range is REQUIRED: "
                 "whole-table counts diverge by design under the 7-day retention window.")

    out = reconcile(
        a.table, a.idLo, a.idHi, a.repoRoot,
        piHost=piHost, sourceDevice=sourceDevice,
    )
    print(f"=== SYNC RECONCILIATION  {out['table']}  source_id {out['idLo']}..{out['idHi']} ===")
    for k in ("piCount", "serverCount", "missing", "mismatches"):
        print(f"  {k:14} {out[k]}")
    for m in out["sampleMismatches"]:
        print(f"    mismatch {m}")
    print(f"\n  {out['verdict']}")
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())

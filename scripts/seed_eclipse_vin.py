################################################################################
# File Name: seed_eclipse_vin.py
# Purpose/Description: Seed the canonical Eclipse VIN record into both the Pi's
#                      local SQLite vehicle_info cache AND the chi-srv-01 server's
#                      vehicle_info MariaDB table (via the /api/v1/sync upsert
#                      endpoint -- vehicle_info is a SNAPSHOT_TABLES per US-194,
#                      so it does NOT travel via the regular Pi delta-sync path
#                      and must be pushed explicitly).
#
#                      The 1998 Mitsubishi Eclipse GST does not reliably expose
#                      its VIN over OBD-II Mode 09 (K-line ISO 9141-2; Mode 09
#                      VIN read became standardized post-2000), so the Pi's
#                      VinDecoder never auto-populates the cache for this car.
#                      This seed script captures the door-jamb sticker data
#                      (CIO photo 2026-05-01) plus the NHTSA vPIC API decoded
#                      fields, making the row reproducible across reinstalls.
#
# Author: Marcus (PM)
# Creation Date: 2026-05-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-01    | Marcus       | Initial -- door-jamb sticker capture + NHTSA decode.
# ================================================================================
################################################################################

"""Seed the Eclipse VIN row into Pi sqlite + chi-srv-01 MariaDB.

The vehicle_info table is a snapshot-style table (US-194 SNAPSHOT_TABLES) -- the
regular Pi delta-sync intentionally skips it.  Without this script, the
canonical VIN record never propagates to the server, so server-side analytics
have no make/model/year context for any drive_summary or realtime_data rows.

Usage::

    # Seed both Pi and server (idempotent; safe to re-run):
    python scripts/seed_eclipse_vin.py

    # Seed only the Pi cache (e.g., post-fresh-Pi-deploy):
    python scripts/seed_eclipse_vin.py --target pi

    # Seed only the server (e.g., post-server-rebuild):
    python scripts/seed_eclipse_vin.py --target server

Idempotency
-----------
* Pi: ``INSERT OR REPLACE`` keyed on ``vin``.  Re-running just refreshes
  ``updated_at``.
* Server: POST to ``/api/v1/sync`` with the vehicle_info row.  The server's
  ``runSyncUpsert`` uses ``UNIQUE(source_device, source_id)`` for upsert
  semantics (see ``src/server/api/sync.py``).  Re-running is a no-op or a
  refresh.

Sources
-------
* NHTSA vPIC API decode: VIN ``4A3AK54F8WE122916``
* Door-jamb sticker (CIO photo 2026-05-01): GVWR/GAWR/MDH/plant code
* CIO context (MEMORY.md): GST trim, 4G63 turbo FWD, ECMLink V3 planned
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ============================================================================
# Canonical Eclipse VIN record -- frozen here as version-controlled truth.
# ============================================================================

ECLIPSE_VIN = "4A3AK54F8WE122916"
ECLIPSE_DEVICE_ID = "chi-eclipse-01"

# Door-jamb sticker (CIO photo 2026-05-01).  Manufacturer plate data not
# available from NHTSA decoder -- preserved here as the authoritative source.
DOOR_JAMB_STICKER: dict[str, Any] = {
    "source": "CIO photo 2026-05-01",
    "madeIn": "U.S.A.",
    "manufacturer": "Mitsubishi Motor Mfg. of America, Inc.",
    "dateOfManufacture": "March 1998",
    "gvwrLbs": 3891,
    "gvwrKg": 1765,
    "gawrFrontLbs": 2249,
    "gawrFrontKg": 1020,
    "gawrRearLbs": 1720,
    "gawrRearKg": 780,
    "mdh": "032707",
    "plantCode": "MU900252",
    "vehicleType": "PASSENGER CAR",
}

CIO_CONTEXT = (
    "1998 Mitsubishi Eclipse GST (4G63 turbo, FWD, ECMLink V3 planned summer 2026)"
)

# Standard NHTSA-style fields (with hand-corrected entries where NHTSA's 1998
# coverage is incomplete -- engine model, transmission style).
ECLIPSE_VEHICLE_INFO: dict[str, Any] = {
    "vin": ECLIPSE_VIN,
    "make": "MITSUBISHI",
    "model": "Eclipse",
    "year": 1998,
    "engine": "4G63 (2.0L Turbo, GST trim)",
    "fuel_type": "Gasoline",
    "transmission": "Manual 5-speed",
    "drive_type": "4x2 (FWD)",
    "body_class": "Hatchback/Liftback/Notchback",
    "plant_city": "BLOOMINGTON-NORMAL",
    "plant_country": "UNITED STATES (USA)",
}


# ============================================================================
# Pi sqlite seeding
# ============================================================================


def seedPiCache(dbPath: str | Path, includeNhtsaResponse: bool = True) -> None:
    """Seed the Pi's vehicle_info SQLite table with the canonical Eclipse row.

    Args:
        dbPath: Path to the Pi's obd.db SQLite file.
        includeNhtsaResponse: If True, fetch + embed the live NHTSA decoder
            response under the ``raw_api_response`` column.  If False, embed
            only the door-jamb sticker JSON (offline-safe).
    """
    rawPayload: dict[str, Any] = {}

    if includeNhtsaResponse:
        try:
            rawPayload = _fetchNhtsaDecode(ECLIPSE_VIN)
        except (urllib.error.URLError, TimeoutError) as exc:
            print(
                f"  warn: NHTSA fetch failed ({exc}); proceeding with offline raw_api_response",
                file=sys.stderr,
            )

    rawPayload["_doorJambSticker"] = DOOR_JAMB_STICKER
    rawPayload["_cioContext"] = CIO_CONTEXT

    db = sqlite3.connect(str(dbPath))
    try:
        cur = db.cursor()
        # Clear stale Honda test VIN if present (pre-real-data dev artifact).
        cur.execute(
            "DELETE FROM vehicle_info WHERE vin = ?",
            ("1HGBH41JXMN109186",),
        )
        if cur.rowcount:
            print(f"  cleared {cur.rowcount} stale test VIN row(s)")

        cur.execute(
            """
            INSERT OR REPLACE INTO vehicle_info (
                vin, make, model, year, engine, fuel_type,
                transmission, drive_type, body_class,
                plant_city, plant_country, raw_api_response,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                      datetime('now'), datetime('now'))
            """,
            (
                ECLIPSE_VEHICLE_INFO["vin"],
                ECLIPSE_VEHICLE_INFO["make"],
                ECLIPSE_VEHICLE_INFO["model"],
                ECLIPSE_VEHICLE_INFO["year"],
                ECLIPSE_VEHICLE_INFO["engine"],
                ECLIPSE_VEHICLE_INFO["fuel_type"],
                ECLIPSE_VEHICLE_INFO["transmission"],
                ECLIPSE_VEHICLE_INFO["drive_type"],
                ECLIPSE_VEHICLE_INFO["body_class"],
                ECLIPSE_VEHICLE_INFO["plant_city"],
                ECLIPSE_VEHICLE_INFO["plant_country"],
                json.dumps(rawPayload),
            ),
        )
        db.commit()
        print(f"  Pi: seeded vehicle_info row for {ECLIPSE_VIN}")
    finally:
        db.close()


# ============================================================================
# Server API push (snapshot table -- see US-194 SNAPSHOT_TABLES exclusion)
# ============================================================================


def seedServerCache(
    serverBaseUrl: str,
    apiKey: str,
    deviceId: str = ECLIPSE_DEVICE_ID,
    sourceId: int = 1,
) -> None:
    """Push the Eclipse VIN row to the server via /api/v1/sync.

    Uses the same upsert endpoint as the regular Pi sync.  vehicle_info is in
    the server's _TABLE_REGISTRY but not in the Pi delta-sync path; this
    explicit push is the canonical way to make the row visible server-side.

    Args:
        serverBaseUrl: e.g., 'http://10.27.27.10:8000'
        apiKey: X-API-Key header value (matches Pi's config + server's middleware)
        deviceId: source_device value (defaults to Pi's chi-eclipse-01)
        sourceId: source_id (the Pi-side rowid; defaults to 1, since the
            Pi's vehicle_info table currently has only one row)
    """
    # Build the same raw_api_response payload as the Pi cache so server and
    # Pi are bit-identical for the row's content (not counting auto columns).
    rawPayload: dict[str, Any] = {}
    try:
        rawPayload = _fetchNhtsaDecode(ECLIPSE_VIN)
    except (urllib.error.URLError, TimeoutError) as exc:
        print(
            f"  warn: NHTSA fetch failed ({exc}); proceeding with offline raw",
            file=sys.stderr,
        )
    rawPayload["_doorJambSticker"] = DOOR_JAMB_STICKER
    rawPayload["_cioContext"] = CIO_CONTEXT

    row = {
        "id": sourceId,  # Pi rowid -> server source_id (sync handler renames)
        **{k: v for k, v in ECLIPSE_VEHICLE_INFO.items()},
        "raw_api_response": json.dumps(rawPayload),
    }

    # batchId follows the existing Pi sync convention (deviceId + ISO-8601 UTC).
    from datetime import datetime, timezone
    batchId = f"{deviceId}-{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}-seed-vin"

    payload = {
        "deviceId": deviceId,
        "batchId": batchId,
        "tables": {
            "vehicle_info": {
                "lastSyncedId": 0,
                "rows": [row],
            },
        },
    }

    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{serverBaseUrl}/api/v1/sync",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": apiKey,
        },
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status = response.status
            respBody = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        respBody = exc.read().decode("utf-8") if hasattr(exc, "read") else str(exc)
        raise RuntimeError(
            f"server upsert failed: HTTP {exc.code} -- {respBody}"
        ) from exc

    if status >= 300:
        raise RuntimeError(f"server upsert failed: HTTP {status} -- {respBody}")

    print(f"  server: upsert succeeded (HTTP {status})")
    if respBody:
        try:
            print(f"  server response: {json.dumps(json.loads(respBody), indent=2)}")
        except json.JSONDecodeError:
            print(f"  server response: {respBody}")


# ============================================================================
# NHTSA vPIC API helper
# ============================================================================


NHTSA_API_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/DecodeVinValues"


def _fetchNhtsaDecode(vin: str) -> dict[str, Any]:
    """Fetch the NHTSA vPIC decoded record for a VIN.

    Returns the parsed JSON response (dict).  Raises urllib errors on network
    failure -- the caller decides whether to fall through to offline raw.
    """
    url = f"{NHTSA_API_URL}/{vin}?format=json"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Eclipse OBD-II Monitor/seed_eclipse_vin",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


# ============================================================================
# CLI
# ============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Seed the canonical Eclipse VIN row into Pi + server.",
    )
    parser.add_argument(
        "--target",
        choices=("both", "pi", "server"),
        default="both",
        help="Which cache to seed (default: both).",
    )
    parser.add_argument(
        "--pi-db",
        default=os.environ.get(
            "PI_OBD_DB",
            "/home/mcornelison/Projects/Eclipse-01/data/obd.db",
        ),
        help="Path to Pi obd.db (default: production Pi path; set PI_OBD_DB env to override).",
    )
    parser.add_argument(
        "--server-url",
        default=os.environ.get("SERVER_BASE_URL", "http://10.27.27.10:8000"),
        help="Server base URL (default: production chi-srv-01).",
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("API_KEY"),
        help="Server X-API-Key (default: read from API_KEY env var).",
    )
    args = parser.parse_args()

    if args.target in ("pi", "both"):
        if not Path(args.pi_db).is_file():
            print(
                f"error: Pi DB not found at {args.pi_db}; "
                f"run on the Pi or pass --pi-db",
                file=sys.stderr,
            )
            return 1
        print(f"Seeding Pi cache at {args.pi_db}")
        seedPiCache(args.pi_db, includeNhtsaResponse=True)

    if args.target in ("server", "both"):
        if not args.api_key:
            print(
                "error: --api-key required (or set API_KEY env var)",
                file=sys.stderr,
            )
            return 1
        print(f"Seeding server cache at {args.server_url}")
        seedServerCache(args.server_url, args.api_key)

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

################################################################################
# File Name: test_vehicle_info_identity_immutability_enforced.py
# Purpose/Description: Sprint 43 V0.28.0 (US-366 / F-108, satisfying US-365 AC#9)
#                      -- named regression test asserting the vehicle_info ECU-
#                      identity columns are append-only.  Exercises the
#                      stamp_ecu_swap CLI path and asserts an identity-column
#                      UPDATE attempt (--update-existing-signature) is REFUSED
#                      with a documented error, leaving the identity row
#                      unchanged.  The sanctioned identity mutator is close+open
#                      (a normal stamp_ecu_swap), never an in-place rewrite.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- identity-immutability CLI-refusal
#               |              | regression (US-365 AC#9 deferred to US-366).
# ================================================================================
################################################################################

"""US-365 AC#9 / US-366 regression: ECU identity columns are append-only."""

from __future__ import annotations

import logging
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.cli import stamp_ecu_swap as cli  # noqa: E402
from src.server.db.models import Base, VehicleInfo  # noqa: E402


def test_vehicle_info_identity_immutability_enforced(monkeypatch, caplog):
    """Exercises the CLI path + asserts identity-column-UPDATE refusal.

    The stamp_ecu_swap ``--update-existing-signature`` anti-pattern flag must be
    refused with a documented append-only error, and the currently-active
    identity row must be left exactly as it was (no in-place ``ecu_signature``
    rewrite, no spurious new row).
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    eng = create_engine(f"sqlite:///{tmp.name}")
    Base.metadata.create_all(eng)
    with Session(eng) as session:
        session.add(
            VehicleInfo(
                source_id=1,
                source_device="chi-eclipse-01",
                vin="4A3AK34T0XE000000",
                ecu_id=1,  # US-376: ecu_id is NOT NULL (FK not enforced on SQLite)
                ecu_signature="MD326328-ECMLinkV3",
                ecu_install_timestamp_utc=datetime(2026, 5, 22, 14, 0, 0),
                ecu_removal_timestamp_utc=None,
            )
        )
        session.commit()
    eng.dispose()

    monkeypatch.setattr(
        cli, "resolveSyncDatabaseUrl", lambda: f"sqlite:///{tmp.name}",
    )

    try:
        with caplog.at_level(logging.ERROR):
            rc = cli.main(
                [
                    "--signature", "rewritten-identity",
                    "--as-of", "2026-06-01T12:00:00Z",
                    "--update-existing-signature",
                ]
            )

        # Refused with a documented append-only error.
        assert rc != 0
        assert "append-only" in caplog.text.lower()

        # Identity row unchanged: one row, original signature, still active.
        eng = create_engine(f"sqlite:///{tmp.name}")
        with Session(eng) as session:
            rows = session.query(VehicleInfo).all()
            assert len(rows) == 1
            assert rows[0].ecu_signature == "MD326328-ECMLinkV3"
            assert rows[0].ecu_removal_timestamp_utc is None
        eng.dispose()
    finally:
        Path(tmp.name).unlink(missing_ok=True)

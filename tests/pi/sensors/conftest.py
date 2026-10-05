################################################################################
# File Name: conftest.py
# Purpose/Description: ARCH-066 -- no sensors test may read or write the REAL
#   gyro offset seed (/var/lib/eclipse-obd/...). On the Pi that file exists, and
#   a factory-built bridge would otherwise seed every test's engine from it.
# Author: Atlas (architect)
# Creation Date: 2026-10-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""Isolate tests/pi/sensors from the production gyro offset seed file."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolateGyroOffsetSeed(tmp_path, monkeypatch):
    from pi.sensors import imu_state_bridge

    monkeypatch.setattr(
        imu_state_bridge, "GYRO_OFFSET_SEED_PATH", str(tmp_path / "gyro-offset-seed.json")
    )

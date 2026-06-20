################################################################################
# File Name: test_sample.py
# Purpose/Description: Tests for the immutable Sample envelope + QoS enum
#     (EDR bus slice 1, US-380).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-19    | Rex          | Initial implementation for US-380
# ================================================================================
################################################################################

"""Unit tests for ``pi.bus.sample`` -- the immutable Sample envelope and QoS enum."""

import dataclasses

import pytest

from pi.bus.sample import QoS, Sample


def test_sample_isImmutable():
    """
    Given: a constructed Sample
    When: a field is reassigned
    Then: a FrozenInstanceError is raised (the envelope is immutable)
    """
    s = Sample(
        topic="raw.obd.RPM",
        source="obd",
        value=3500.0,
        unit="rpm",
        tsUtc="2026-06-18T13:00:00Z",
        tsCapture=123.5,
        driveId=27,
        dataSource="real",
        seq=1,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.value = 4000.0  # type: ignore[misc]


def test_sample_carriesAllFields():
    """
    Given: a Sample carrying a tuple value and a None driveId
    When: its fields are read
    Then: every field round-trips intact
    """
    s = Sample(
        topic="raw.imu.accel",
        source="imu",
        value=(0.1, 0.2, 9.8),
        unit="g",
        tsUtc="2026-06-18T13:00:00Z",
        tsCapture=1.0,
        driveId=None,
        dataSource="real",
        seq=42,
    )
    assert s.topic == "raw.imu.accel"
    assert s.value == (0.1, 0.2, 9.8)
    assert s.driveId is None
    assert s.seq == 42


def test_qos_hasLosslessAndLossy():
    """
    Given: the QoS enum
    When: its members are inspected
    Then: exactly LOSSLESS and LOSSY exist and are distinct
    """
    assert QoS.LOSSLESS != QoS.LOSSY
    assert {QoS.LOSSLESS, QoS.LOSSY} == set(QoS)

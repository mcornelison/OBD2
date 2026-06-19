################################################################################
# File Name: sample.py
# Purpose/Description: Immutable Sample envelope + QoS enum -- the unit of data
#     published on the SampleBus. See docs/superpowers/specs/
#     2026-06-18-edr-dedicated-reader-bus-contract-design.md (4.1).
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

"""Immutable Sample envelope and QoS enum for the Pi SampleBus (EDR slice 1)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class QoS(Enum):
    """Delivery guarantee declared per subscription.

    LOSSLESS: delivered, or (future) spilled, or recorded as an explicit
        integrity-gap marker -- never silently dropped, never blocks the producer.
    LOSSY: drop-oldest when the subscriber queue is full; never affects the producer.
    """

    LOSSLESS = "lossless"
    LOSSY = "lossy"


@dataclass(frozen=True)
class Sample:
    """One immutable reading published on the bus.

    Args:
        topic: Routing key, e.g. ``"raw.obd.RPM"``, ``"raw.imu.accel"``.
        source: Producer id, e.g. ``"obd"``, ``"imu"``, ``"transform"``.
        value: Scalar reading, or a small fixed tuple (e.g. IMU vector).
        unit: Unit of measurement, or None.
        tsUtc: ISO-8601 UTC wall-clock string -- the value that persists.
        tsCapture: High-resolution monotonic seconds, for time-alignment.
        driveId: Active drive id, or None.
        dataSource: Origin tag, e.g. ``"real"`` / ``"physics_sim"``.
        seq: Per-producer monotonic counter, for gap/drop detection.
    """

    topic: str
    source: str
    value: float | tuple[float, ...]
    unit: str | None
    tsUtc: str
    tsCapture: float
    driveId: int | None
    dataSource: str
    seq: int

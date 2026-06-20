################################################################################
# File Name: persistence_subscriber.py
# Purpose/Description: Bus subscriber that persists raw.obd.* samples to the
#     realtime_data table by REUSING the existing ObdDataLogger.logReading()
#     write path -- guaranteeing the persisted rows are byte-identical to the
#     pre-bus inline path. Runs its own daemon thread so a stuck write can never
#     stall the producer (subscriber isolation). EDR slice 1, US-383.
#     See docs/superpowers/specs/
#     2026-06-18-edr-dedicated-reader-bus-contract-design.md and
#     docs/superpowers/plans/2026-06-18-edr-bus-slice1-dedicated-reader.md Task 6.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-19    | Rex          | Initial implementation for US-383 (raw.obd.*
#               |              | PersistenceSubscriber + byte-identical golden
#               |              | master via ObdDataLogger.logReading reuse)
# ================================================================================
################################################################################
"""The bus subscriber that writes raw.obd.* samples into realtime_data."""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any

from pi.obdii.data.types import LoggedReading

from .bus import Subscription
from .sample import Sample

logger = logging.getLogger(__name__)

# Only raw OBD samples persist to realtime_data; derived/state/event topics are
# the concern of later slices (display/detector subscribers, EDR vault).
_RAW_OBD_PREFIX = "raw.obd."

# How long the drain loop blocks waiting for a sample before re-checking _stop.
# Named (no magic numbers) so the shutdown latency is explicit and tunable.
_DRAIN_TIMEOUT_S = 0.5


class PersistenceSubscriber:
    """Drains a :class:`Subscription` and writes each raw.obd.* sample to the DB.

    The write is delegated to ``ObdDataLogger.logReading`` -- the SAME path the
    inline poll loop used before the bus existed -- so the persisted
    ``realtime_data`` row (parameter_name, value, unit, profile_id, drive_id,
    data_source, write-time timestamp) is identical by construction. The
    subscriber owns a daemon thread; an exception in a single write is caught and
    logged (subscriber isolation) and never crashes the producer or other
    subscribers.
    """

    def __init__(self, subscription: Subscription, dataLogger: Any) -> None:
        """Bind a subscriber to its source subscription and write target.

        Args:
            subscription: The bus subscription this consumer drains (typically a
                LOSSLESS subscription on ``["raw.obd.*"]``).
            dataLogger: An ``ObdDataLogger`` whose ``logReading`` performs the
                actual realtime_data INSERT (reused, never reimplemented).
        """
        self._sub = subscription
        self._dataLogger = dataLogger
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        """Start the background drain thread (idempotent per start/stop cycle)."""
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="PersistenceSubscriber", daemon=True
        )
        self._thread.start()

    def stop(self, timeoutS: float = 5.0) -> None:
        """Signal the drain loop to exit and join the thread.

        Args:
            timeoutS: Maximum seconds to wait for the thread to finish draining.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeoutS)

    def _loop(self) -> None:
        """Drain samples until stopped; isolate per-sample write failures."""
        while not self._stop.is_set():
            sample = self._sub.get(timeoutS=_DRAIN_TIMEOUT_S)
            if sample is None:
                continue
            try:
                self.handleSample(sample)
            except Exception as e:  # subscriber isolation: never crash the loop
                logger.warning(f"PersistenceSubscriber write failed: {e}")

    def handleSample(self, sample: Sample) -> bool:
        """Write one raw.obd.* sample via the existing ``logReading`` path.

        Reconstructs a :class:`LoggedReading` from the sample (the parameter name
        is the topic tail after ``raw.obd.``) and delegates the INSERT to the
        bound ObdDataLogger. ``drive_id`` and ``data_source`` are derived inside
        ``logReading`` exactly as on the pre-bus inline path, so rows stay
        byte-identical.

        Args:
            sample: The bus sample to persist.

        Returns:
            True if a write was attempted; False if the topic was ignored
            (not a ``raw.obd.*`` sample).
        """
        if not sample.topic.startswith(_RAW_OBD_PREFIX):
            return False
        parameterName = sample.topic[len(_RAW_OBD_PREFIX):]
        reading = LoggedReading(
            parameterName=parameterName,
            value=sample.value,
            timestamp=datetime.now(),  # logReading restamps utcIsoNow() anyway
            unit=sample.unit,
            profileId=None,  # logReading falls back to the dataLogger's profileId
        )
        self._dataLogger.logReading(reading)
        return True

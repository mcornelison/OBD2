################################################################################
# File Name: test_logger_latest_readings.py
# Purpose/Description: Tests for ObdDataLogger.getLatestReadings() -- the
#                      read-only snapshot API consumed by SummaryRecorder
#                      (US-206).
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex (US-206) | Initial.
# ================================================================================
################################################################################

"""Tests for ObdDataLogger.getLatestReadings (US-206)."""

from __future__ import annotations

from src.pi.obdii.data.logger import ObdDataLogger


class _FakeConnection:
    """Minimal connection with a mocked query() + supportedPids off."""

    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.supportedPids = None  # let decoder-gated path skip probe
        self.obd = self

    def isConnected(self) -> bool:
        return True

    def query(self, cmd: object) -> object:
        key = cmd if isinstance(cmd, str) else getattr(cmd, 'name', str(cmd))
        return self._responses.get(key, _NullResponse())


class _NullResponse:
    def __init__(self) -> None:
        self.value = None

    def is_null(self) -> bool:
        return True


class _ValueResponse:
    def __init__(self, value: float, unit: str | None = None) -> None:
        self.value = value
        self.unit = unit

    def is_null(self) -> bool:
        return False


class _FakeDatabase:
    """Minimal database skipping actual INSERTs."""

    def connect(self):  # type: ignore[no-untyped-def]
        return self

    def __enter__(self):  # type: ignore[no-untyped-def]
        return self

    def __exit__(self, *args):  # type: ignore[no-untyped-def]
        return False

    def cursor(self):  # type: ignore[no-untyped-def]
        return self

    def execute(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        return None


class TestGetLatestReadings:
    def test_emptyBeforeAnyQuery(self) -> None:
        logger = ObdDataLogger(_FakeConnection({}), _FakeDatabase())
        assert logger.getLatestReadings() == {}

    def test_populatedAfterLegacyQuery(self) -> None:
        """Legacy PARAMETER_DECODERS-miss path populates the snapshot."""
        responses = {'RPM': _ValueResponse(2500.0, 'rpm')}
        logger = ObdDataLogger(_FakeConnection(responses), _FakeDatabase())
        logger.queryParameter('RPM')
        snap = logger.getLatestReadings()
        assert snap.get('RPM') == 2500.0

    def test_returnsShallowCopy(self) -> None:
        """Mutating the caller's dict doesn't affect the logger's internal state."""
        responses = {'RPM': _ValueResponse(1500.0)}
        logger = ObdDataLogger(_FakeConnection(responses), _FakeDatabase())
        logger.queryParameter('RPM')
        snap = logger.getLatestReadings()
        snap['RPM'] = -1.0
        snap2 = logger.getLatestReadings()
        assert snap2['RPM'] == 1500.0

    def test_snapshotUpdatesAfterReQuery(self) -> None:
        """Re-querying the same parameter overwrites the cached value."""
        responses = {'RPM': _ValueResponse(1500.0)}
        logger = ObdDataLogger(_FakeConnection(responses), _FakeDatabase())
        logger.queryParameter('RPM')

        # Bump the response for the next tick.
        responses['RPM'] = _ValueResponse(3000.0)
        logger.queryParameter('RPM')

        assert logger.getLatestReadings()['RPM'] == 3000.0

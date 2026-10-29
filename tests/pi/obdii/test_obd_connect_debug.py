################################################################################
# File Name: test_obd_connect_debug.py
# Purpose/Description: The process's FIRST OBD connect attempt runs python-OBD
#                      at DEBUG, and every attempt logs CONNECT PHASE lines
#                      (US-907)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-15    | Rex (US-907) | Initial
# 2026-10-26    | Rex (US-817-a) | Moved pin: obd.OBD kwargs gain baudrate
# 2026-10-28    | Rex (US-817-c) | Moved pin: DEFAULT_ADAPTER_BAUDRATE from its home
# ================================================================================
################################################################################

"""
US-907 desk tests (Atlas spec 2026-10-15, acceptance 1-3).

``obd.OBD`` is replaced by a fake that logs one python-OBD style DEBUG record
under ``obd.elm327`` and sleeps briefly, so the DEBUG window and the phase
timing are both observable without hardware.  The bench venv has no python-OBD,
so the module's ``obdlib`` is swapped for a namespace carrying the fake.
"""

from __future__ import annotations

import logging
import re
import time
from types import SimpleNamespace
from typing import Any

import pytest

import src.pi.obdii.obd_connection as connModule

# MOVED PIN (US-817-c): the default's one home is common.config.validator.
from common.config.validator import DEFAULT_ADAPTER_BAUDRATE
from src.pi.obdii.obd_connection import ObdConnection

ELM_RECORD = "write: ATZ"
PHASE_RE = re.compile(
    r"^CONNECT PHASE \| attempt=(\d+) \| phase=(\w+) \| elapsedSec=(\d+\.\d)$"
)
CONNECTION_TIMEOUT = 7
PORT = "/dev/rfcomm0"


class _FakeObd:
    def is_connected(self) -> bool:
        return True

    def close(self) -> None:
        pass


class _FakeObdFactory:
    """Stands in for ``obd.OBD``: logs at obd.elm327 DEBUG, sleeps, returns/raises."""

    def __init__(self, raises: bool = False) -> None:
        self.raises = raises
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((args, kwargs))
        logging.getLogger("obd.elm327").debug(ELM_RECORD)
        time.sleep(0.02)
        if self.raises:
            raise OSError("no response from ELM327")
        return _FakeObd()


@pytest.fixture
def obdLogger() -> Any:
    """The 'obd' logger at python-OBD 0.7.3's import-time level (WARNING)."""
    log = logging.getLogger("obd")
    saved = log.level
    log.setLevel(logging.WARNING)
    yield log
    log.setLevel(saved)


@pytest.fixture
def freshProcess(monkeypatch: pytest.MonkeyPatch) -> None:
    """A process that has not made a connect attempt yet."""
    monkeypatch.setattr(connModule, "_processConnectAttempts", 0)


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeObdFactory) -> None:
    monkeypatch.setattr(connModule, "obdlib", SimpleNamespace(OBD=fake))
    monkeypatch.setattr(connModule, "OBD_AVAILABLE", True)
    # The probe is not under test; keep it from touching the fake.
    monkeypatch.setattr(ObdConnection, "_runSupportedPidProbe", lambda self: None)


def _connection(connectDebug: Any = None) -> ObdConnection:
    pi: dict[str, Any] = {
        "bluetooth": {
            "macAddress": PORT,
            "retryDelays": [],
            "maxRetries": 0,
            "connectionTimeoutSeconds": CONNECTION_TIMEOUT,
        }
    }
    if connectDebug is not None:
        pi["obdii"] = {"connectDebug": connectDebug}
    return ObdConnection({"pi": pi}, None)


def _capturePhases(caplog: pytest.LogCaptureFixture) -> None:
    """Let the connection's INFO lines through without filtering obd DEBUG.

    set_level also raises the capture HANDLER's level, which would hide the
    obd.elm327 DEBUG record the window exists to let through.
    """
    caplog.set_level(logging.INFO, logger=connModule.logger.name)
    caplog.handler.setLevel(logging.NOTSET)


def _elmRecords(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r for r in caplog.records
        if r.name == "obd.elm327" and r.getMessage() == ELM_RECORD
    ]


def _phases(caplog: pytest.LogCaptureFixture) -> list[tuple[int, str, float]]:
    out = []
    for r in caplog.records:
        if r.name != connModule.logger.name or r.levelno != logging.INFO:
            continue
        m = PHASE_RE.match(r.getMessage())
        if m:
            out.append((int(m.group(1)), m.group(2), float(m.group(3))))
    return out


def _spyLevelWrites(
    monkeypatch: pytest.MonkeyPatch, log: logging.Logger
) -> list[int]:
    writes: list[int] = []
    real = log.setLevel

    def spy(level: int) -> None:
        writes.append(level)
        real(level)

    monkeypatch.setattr(log, "setLevel", spy)
    return writes


@pytest.mark.usefixtures("freshProcess")
class TestFirstAttemptDebugWindow:

    def test_flagTrue_firstAttempt_elmDebugCaptured_levelRestored(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        """
        Given: connectDebug true, the process's first attempt
        When: connect() runs and the fake logs obd.elm327 DEBUG
        Then: the record is captured; 'obd' is back at its prior level
        """
        fake = _FakeObdFactory()
        _install(monkeypatch, fake)
        _capturePhases(caplog)

        assert _connection(connectDebug=True).connect() is True

        records = _elmRecords(caplog)
        assert len(records) == 1 and records[0].levelno == logging.DEBUG
        assert obdLogger.level == logging.WARNING

    def test_flagTrue_restoresTheLevelItRead_notAHardCodedWarning(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        obdLogger.setLevel(logging.ERROR)
        _install(monkeypatch, _FakeObdFactory())

        _connection(connectDebug=True).connect()

        assert len(_elmRecords(caplog)) == 1
        assert obdLogger.level == logging.ERROR

    def test_flagTrue_fakeRaises_captured_levelRestored_endsFailed(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        """
        Given: connectDebug true, first attempt, obd.OBD raises
        When: connect() runs its single attempt
        Then: the record is captured, the level restored, last phase = failed
        """
        _install(monkeypatch, _FakeObdFactory(raises=True))
        _capturePhases(caplog)

        assert _connection(connectDebug=True).connect() is False

        assert len(_elmRecords(caplog)) == 1
        assert obdLogger.level == logging.WARNING
        phases = _phases(caplog)
        assert [p[1] for p in phases] == ["port_resolved", "failed"]
        assert phases[-1][0] == 1

    def test_flagTrue_secondAttempt_notCaptured_levelNeverWritten(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        """
        Given: connectDebug true; the process's first attempt already ran
        When: a second attempt runs (a reconnect)
        Then: no DEBUG record and the 'obd' level is never written
        """
        _install(monkeypatch, _FakeObdFactory())
        conn = _connection(connectDebug=True)
        conn.connect()
        caplog.clear()
        writes = _spyLevelWrites(monkeypatch, obdLogger)

        assert conn.reconnect() is True

        assert _elmRecords(caplog) == []
        assert writes == []

    def test_flagTrue_firstAttemptFailsInsideRetryBurst_laterAttemptsNotCaptured(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        fake = _FakeObdFactory(raises=True)
        _install(monkeypatch, fake)
        conn = ObdConnection(
            {"pi": {
                "bluetooth": {"macAddress": PORT, "retryDelays": [0, 0],
                              "maxRetries": 2, "connectionTimeoutSeconds": 1},
                "obdii": {"connectDebug": True},
            }},
            None,
        )

        assert conn.connect() is False

        assert len(fake.calls) == 3
        assert len(_elmRecords(caplog)) == 1
        assert obdLogger.level == logging.WARNING

    @pytest.mark.parametrize("connectDebug", [False, None])
    def test_flagFalseOrAbsent_notCaptured_levelNeverWritten(
        self, monkeypatch, caplog, obdLogger, connectDebug
    ) -> None:
        _install(monkeypatch, _FakeObdFactory())
        writes = _spyLevelWrites(monkeypatch, obdLogger)

        assert _connection(connectDebug=connectDebug).connect() is True

        assert _elmRecords(caplog) == []
        assert writes == []

    def test_pythonObdHandlersUntouched(self, monkeypatch, obdLogger) -> None:
        handler = logging.StreamHandler()
        obdLogger.addHandler(handler)
        try:
            _install(monkeypatch, _FakeObdFactory())
            _connection(connectDebug=True).connect()
            assert obdLogger.handlers == [handler]
        finally:
            obdLogger.removeHandler(handler)


@pytest.mark.usefixtures("freshProcess")
class TestObdCallUnchanged:

    @pytest.mark.parametrize("connectDebug", [True, False])
    def test_fakeReceivesExactlyPortFastFalseTimeout(
        self, monkeypatch, obdLogger, connectDebug
    ) -> None:
        fake = _FakeObdFactory()
        _install(monkeypatch, fake)

        _connection(connectDebug=connectDebug).connect()

        # MOVED PIN (US-817-a): the real call now also carries the adapter baud.
        assert fake.calls == [
            ((), {"portstr": PORT, "fast": False, "timeout": CONNECTION_TIMEOUT,
                  "baudrate": DEFAULT_ADAPTER_BAUDRATE})
        ]


@pytest.mark.usefixtures("freshProcess")
class TestConnectPhaseLines:

    def test_success_logsThreePhasesInOrder_monotonicElapsed(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        """
        Given: a connect that succeeds (flag off -- the lines are permanent)
        When: connect() runs
        Then: port_resolved, elm_connected, pids_probed, elapsed non-decreasing
        """
        _install(monkeypatch, _FakeObdFactory())
        _capturePhases(caplog)

        _connection(connectDebug=False).connect()

        phases = _phases(caplog)
        assert [p[1] for p in phases] == ["port_resolved", "elm_connected", "pids_probed"]
        assert {p[0] for p in phases} == {1}
        elapsed = [p[2] for p in phases]
        assert elapsed == sorted(elapsed)
        # The fake slept 0.02 s inside obd.OBD(); 1 dp rounding can still read 0.0.
        assert all(e >= 0.0 for e in elapsed)

    def test_attemptNumberCountsTheProcessAttempts(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        _install(monkeypatch, _FakeObdFactory())
        _capturePhases(caplog)
        conn = _connection()

        conn.connect()
        conn.reconnect()

        assert [p[0] for p in _phases(caplog)] == [1, 1, 1, 2, 2, 2]

    def test_notConnectedAfterCreation_endsFailedAfterElmConnected(
        self, monkeypatch, caplog, obdLogger
    ) -> None:
        class _Dead(_FakeObd):
            def is_connected(self) -> bool:
                return False

        _install(monkeypatch, _FakeObdFactory())
        monkeypatch.setattr(
            connModule, "obdlib", SimpleNamespace(OBD=lambda **kw: _Dead())
        )
        _capturePhases(caplog)

        assert _connection().connect() is False

        assert [p[1] for p in _phases(caplog)] == [
            "port_resolved", "elm_connected", "failed"
        ]

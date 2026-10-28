################################################################################
# File Name: test_obd_connect_baud.py
# Purpose/Description: Every real OBD connect passes the adapter's baud and
#                      skips python-obd's 30 s auto-baud probe, with a
#                      one-auto-attempt fallback after an ELM failure (US-817-a)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-26    | Rex (US-817-a) | Initial
# 2026-10-28    | Rex (US-817-c) | Moved pins: the rejection runs in ConfigValidator;
#                                  the default is the common name
# ================================================================================
################################################################################

"""
US-817-a desk tests.

python-obd 0.7.3 uses ``timeout`` only inside ``auto_baudrate``, whose
``read(1024)`` always waits the full timeout -- so every connect that leaves
``baudrate`` unset pays ~30 s.  These tests replace ``obd.OBD`` (the bench venv
has no python-obd, so the module's ``obdlib`` is swapped for a namespace) and
read the ``baudrate=`` kwarg of each real-path attempt.

Each ``connect()`` here makes exactly ONE port attempt (``maxRetries`` 0), so
the fallback state is observed across calls on the same instance -- the way
the reconnect heartbeat drives it.
"""

from __future__ import annotations

import copy
from types import SimpleNamespace
from typing import Any

import pytest

import common.config.validator as commonValidator
import src.pi.obdii.obd_connection as connModule
from src.pi.obdii.config import loader
from src.pi.obdii.obd_connection import ObdConnection

PORT = "/dev/rfcomm0"

# python-OBD 0.7.3 OBDStatus values (obd/utils.py) -- the strings
# obd_connection pins when the package does not import.
NOT_CONNECTED = "Not Connected"
ELM_CONNECTED = "ELM Connected"
OBD_CONNECTED = "OBD Connected"
CAR_CONNECTED = "Car Connected"


class _FakeObd:
    def __init__(self, status: str) -> None:
        self._status = status

    def status(self) -> str:
        return self._status

    def is_connected(self) -> bool:
        return self._status == CAR_CONNECTED

    def close(self) -> None:
        pass


class _ScriptedObd:
    """Stands in for ``obd.OBD``: records kwargs, plays one outcome per call.

    An outcome is a status string (the object returned carries it) or an
    exception instance (raised before any status is readable).
    """

    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        assert not args, "obd.OBD is called with keyword arguments only"
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return _FakeObd(outcome)

    @property
    def bauds(self) -> list[Any]:
        return [c["baudrate"] for c in self.calls]


def _install(monkeypatch: pytest.MonkeyPatch, fake: _ScriptedObd) -> None:
    monkeypatch.setattr(connModule, "obdlib", SimpleNamespace(OBD=fake))
    monkeypatch.setattr(connModule, "OBD_AVAILABLE", True)
    # The PID probe is not under test; keep it from touching the fake.
    monkeypatch.setattr(ObdConnection, "_runSupportedPidProbe", lambda self: None)


def _connection(**bluetooth: Any) -> ObdConnection:
    bt: dict[str, Any] = {
        "macAddress": PORT,
        "retryDelays": [],
        "maxRetries": 0,
        "connectionTimeoutSeconds": 30,
    }
    bt.update(bluetooth)
    return ObdConnection({"pi": {"bluetooth": bt}}, None)


def _attempts(conn: ObdConnection, n: int) -> None:
    for _ in range(n):
        conn.connect()


# ================================================================================
# The real connect path: explicit baud + one-auto-attempt fallback
# ================================================================================

class TestRealPathBaud:

    def test_obd_connect_passes_explicit_baud(self, monkeypatch) -> None:
        """
        Given: an explicit-baud attempt that fails at the ELM step
        When:  three successive attempts are made
        Then:  38400, then None (python-obd auto-probe), then 38400 again
        """
        fake = _ScriptedObd([NOT_CONNECTED, NOT_CONNECTED, CAR_CONNECTED])
        _install(monkeypatch, fake)
        conn = _connection()

        _attempts(conn, 3)

        assert fake.bauds == [38400, None, 38400]

    def test_normalAttempt_passesDefaultBaud_andTimeoutUnchanged(self, monkeypatch) -> None:
        fake = _ScriptedObd([CAR_CONNECTED])
        _install(monkeypatch, fake)

        assert _connection(connectionTimeoutSeconds=7).connect() is True

        assert fake.calls == [
            {"portstr": PORT, "fast": False, "timeout": 7, "baudrate": 38400}
        ]

    def test_configuredBaud_isTheOnePassed(self, monkeypatch) -> None:
        fake = _ScriptedObd([CAR_CONNECTED])
        _install(monkeypatch, fake)

        _connection(adapterBaudrate=115200).connect()

        assert fake.bauds == [115200]

    def test_explicitAttemptRaises_nextIsAuto(self, monkeypatch) -> None:
        fake = _ScriptedObd([OSError("no response from ELM327"), CAR_CONNECTED])
        _install(monkeypatch, fake)
        conn = _connection()

        _attempts(conn, 2)

        assert fake.bauds == [38400, None]

    @pytest.mark.parametrize("answered", [ELM_CONNECTED, OBD_CONNECTED])
    def test_elmAnsweredButEcuSilent_nextStaysExplicit(self, monkeypatch, answered) -> None:
        """
        Given: (G1) the explicit attempt's status says the ELM answered, ECU silent
        When:  the next attempt is made
        Then:  it is still explicit -- the baud was right, the ignition is off
        """
        fake = _ScriptedObd([answered, CAR_CONNECTED])
        _install(monkeypatch, fake)
        conn = _connection()

        _attempts(conn, 2)

        assert fake.bauds == [38400, 38400]

    def test_autoAttemptAlsoFails_nextIsExplicitAgain(self, monkeypatch) -> None:
        fake = _ScriptedObd([NOT_CONNECTED, NOT_CONNECTED, NOT_CONNECTED, NOT_CONNECTED])
        _install(monkeypatch, fake)
        conn = _connection()

        _attempts(conn, 4)

        assert fake.bauds == [38400, None, 38400, None]

    def test_successfulExplicitAttempts_neverFallBack(self, monkeypatch) -> None:
        fake = _ScriptedObd([CAR_CONNECTED, CAR_CONNECTED])
        _install(monkeypatch, fake)
        conn = _connection()

        _attempts(conn, 2)

        assert fake.bauds == [38400, 38400]

    def test_fallbackAlsoAppliesInsideOneRetryLoop(self, monkeypatch) -> None:
        fake = _ScriptedObd([NOT_CONNECTED, NOT_CONNECTED, CAR_CONNECTED])
        _install(monkeypatch, fake)
        conn = _connection(retryDelays=[0, 0], maxRetries=2)

        assert conn.connect() is True

        assert fake.bauds == [38400, None, 38400]


class TestFactorySeamUnchanged:

    def test_injectedFactory_keepsTwoArgSignature(self) -> None:
        """The _obdFactory(serialPort, timeout) seam carries no baud."""
        seen: list[tuple[Any, ...]] = []

        def factory(serialPort: str | None, timeout: float) -> Any:
            seen.append((serialPort, timeout))
            return _FakeObd(CAR_CONNECTED)

        conn = ObdConnection(
            {"pi": {"bluetooth": {"macAddress": PORT, "retryDelays": [], "maxRetries": 0,
                                  "connectionTimeoutSeconds": 9}}},
            None,
            obdFactory=factory,
        )
        conn._runSupportedPidProbe = lambda: None  # type: ignore[method-assign]

        assert conn.connect() is True
        assert seen == [(PORT, 9)]


# ================================================================================
# Config: pi.bluetooth.adapterBaudrate
# ================================================================================

_MINIMAL_CONFIG: dict[str, Any] = {
    "protocolVersion": "1.0.0",
    "schemaVersion": "1.0.0",
    "deviceId": "test-device",
    "logging": {"level": "DEBUG"},
    "pi": {
        "database": {"path": "./test/obd.db"},
        "bluetooth": {"macAddress": "AA:BB:CC:DD:EE:FF"},
        "display": {"mode": "headless"},
        "realtimeData": {"parameters": [{"name": "RPM", "logData": True}]},
    },
    "server": {"ai": {}, "database": {}, "api": {}},
}


def _configWithBaud(baud: Any = None) -> dict[str, Any]:
    config = copy.deepcopy(_MINIMAL_CONFIG)
    if baud is not None:
        config["pi"]["bluetooth"]["adapterBaudrate"] = baud
    return config


class TestAdapterBaudrateConfig:

    def test_default_is38400_besideConnectionTimeout(self) -> None:
        assert loader.OBD_DEFAULTS["pi.bluetooth.adapterBaudrate"] == 38400
        keys = list(loader.OBD_DEFAULTS)
        assert keys.index("pi.bluetooth.adapterBaudrate") == (
            keys.index("pi.bluetooth.connectionTimeoutSeconds") + 1
        )

    def test_absentKey_validatesToDefault(self) -> None:
        config = loader.validateObdConfig(_configWithBaud())

        assert config["pi"]["bluetooth"]["adapterBaudrate"] == 38400

    @pytest.mark.parametrize("baud", [9600, 38400, 115200, 230400, 500000])
    def test_elm327Rates_accepted(self, baud) -> None:
        config = loader.validateObdConfig(_configWithBaud(baud))

        assert config["pi"]["bluetooth"]["adapterBaudrate"] == baud

    @pytest.mark.parametrize("baud", [12345, 0, -38400, "38400", 38400.0, True])
    def test_otherValues_rejectedNamingTheKey(self, baud) -> None:
        # MOVED PIN (US-817-c): the rule runs in the production validator
        # (main.py / powerwatch); loader.validateObdConfig now wraps it as
        # ObdConfigError, which is not a ConfigValidationError.
        with pytest.raises(commonValidator.ConfigValidationError) as excInfo:
            commonValidator.ConfigValidator().validate(_configWithBaud(baud))

        assert "pi.bluetooth.adapterBaudrate" in str(excInfo.value)

    def test_loaderDefault_isTheCommonName(self) -> None:
        """US-817-c (Atlas F5): loader's name is the common object, so it cannot drift."""
        assert loader.DEFAULT_ADAPTER_BAUDRATE is commonValidator.DEFAULT_ADAPTER_BAUDRATE

    def test_connectionUsesTheLoaderDefault_whenKeyAbsent(self, monkeypatch) -> None:
        fake = _ScriptedObd([CAR_CONNECTED])
        _install(monkeypatch, fake)

        _connection().connect()

        # MOVED PIN (US-817-c): the default's one home is common.config.validator.
        assert fake.bauds == [commonValidator.DEFAULT_ADAPTER_BAUDRATE]

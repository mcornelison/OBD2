################################################################################
# File Name: test_wifi_recover.py
# Purpose/Description: US-925-a -- the Wi-Fi no-secrets recovery handler: one
#   `nmcli connection up uuid U` per ACTIVATED, whatever caused the failure,
#   and the static guards on the module (NM-doc constants, no timer, stdlib +
#   dbus/gi-in-main imports, no GetSecrets).
# Author: Rex (Ralph agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex (US-925-a) | Initial
# 2026-10-26    | Rex (US-925-b) | psk-flags != 0 -> one WARNING per Wi-Fi profile
# 2026-10-26    | Rex (US-925-c) | READY=1 only after the subscription; bus_name pinned
# ================================================================================
################################################################################

"""Tests for ``src.pi.network.wifi_recover`` (Windows-runnable: no D-Bus)."""

from __future__ import annotations

import ast
import io
import logging
import re
import sys
import tokenize
import types
from pathlib import Path
from typing import Any

import pytest

from src.pi.network import wifi_recover
from src.pi.network.wifi_recover import (
    NM_BUS_NAME,
    NM_DEVICE_STATE_ACTIVATED,
    NM_DEVICE_STATE_FAILED,
    NM_DEVICE_STATE_REASON_NO_SECRETS,
    WIFI_INTERFACE,
    DeviceEvent,
    Memory,
    SupplicantTrail,
    decide,
    parseSupplicantLines,
    reportRetryExit,
    runEvent,
)

MODULE_PATH = Path(wifi_recover.__file__)
UUID_U = "3f0c2b1e-8d9a-4c55-9e3e-1a2b3c4d5e6f"
UUID_V = "7d1e0a42-55b0-4e7e-8a19-0f9e8d7c6b5a"
BSSID_BEFORE = "ba:83:e7:74:9e:b0"
BSSID_AFTER = "e4:fa:c4:12:34:57"

# NM's public NMDeviceStateReason values the story names as preceding
# disconnects/causes it must NOT special-case (US-925-a 8/9 + pin 4).
REASON_USER_REQUESTED = 39
REASON_SUPPLICANT_TIMEOUT = 11


def _activated(uuid: str = UUID_U, pskFlags: int = 0, iface: str = WIFI_INTERFACE) -> DeviceEvent:
    return DeviceEvent(
        interface=iface,
        newState=NM_DEVICE_STATE_ACTIVATED,
        reason=0,
        uuid=uuid,
        pskFlags=pskFlags,
    )


def _noSecrets(
    trail: SupplicantTrail | None = None,
    iface: str = WIFI_INTERFACE,
    reason: int = NM_DEVICE_STATE_REASON_NO_SECRETS,
) -> DeviceEvent:
    return DeviceEvent(
        interface=iface,
        newState=NM_DEVICE_STATE_FAILED,
        reason=reason,
        trail=trail or SupplicantTrail("17", BSSID_BEFORE, BSSID_AFTER),
    )


def _armed(uuid: str = UUID_U, pskFlags: int = 0) -> Memory:
    return decide(_activated(uuid, pskFlags), Memory()).memory


class _Launcher:
    """Records every action; raises when told to (nmcli cannot start)."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.raises = raises

    def __call__(self, argv: tuple[str, ...], uuid: str) -> None:
        self.calls.append(argv)
        if self.raises is not None:
            raise self.raises


def _errorLines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.ERROR]


# ================================================================================
# (1) FAILED + NO_SECRETS after ACTIVATED(U) -> `connection up uuid U`
# ================================================================================


def test_noSecretsAfterActivated_retriesTheActivatedUuid():
    """
    Given: wlan0 reached ACTIVATED with uuid U (stored PSK, psk-flags 0)
    When: it fails with reason NO_SECRETS
    Then: the action is `nmcli connection up uuid U`, and the rearm is spent
    """
    decision = decide(_noSecrets(), _armed())

    assert decision.action == ("/usr/bin/nmcli", "connection", "up", "uuid", UUID_U)
    assert decision.memory.armed is False
    assert decision.memory.uuid == UUID_U
    assert decision.level == logging.INFO


def test_retryLine_namesReasonBothBssidsAndTheAction():
    """One journal line: the reason, the BSSID before and after, the action (example f9eb34cc)."""
    decision = decide(_noSecrets(), _armed())

    assert decision.line == (
        f"no-secrets after reason 17, bssid {BSSID_BEFORE}->{BSSID_AFTER}, "
        f"retry connection up uuid {UUID_U}"
    )


def test_runEvent_launchesTheRetryAndLogsOneLine(caplog: pytest.LogCaptureFixture):
    launcher = _Launcher()
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    memory = runEvent(_noSecrets(), _armed(), launcher)

    assert launcher.calls == [("/usr/bin/nmcli", "connection", "up", "uuid", UUID_U)]
    assert memory.armed is False
    assert len(caplog.records) == 1
    assert "retry connection up uuid" in caplog.records[0].getMessage()


# ================================================================================
# (2) a second NO_SECRETS with no ACTIVATED between -> no action + ONE ERROR
# ================================================================================


def test_secondNoSecretsWithoutActivated_noActionAndOneErrorLine(
    caplog: pytest.LogCaptureFixture,
):
    launcher = _Launcher()
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)
    memory = runEvent(_noSecrets(), _armed(), launcher)
    caplog.clear()

    memory = runEvent(_noSecrets(), memory, launcher)

    assert len(launcher.calls) == 1, "the second failure must not launch a retry"
    assert len(_errorLines(caplog)) == 1
    assert len(caplog.records) == 1
    assert "not retried" in _errorLines(caplog)[0]
    assert memory.armed is False


def test_wrongKeyOnAFreshProfile_neverActivated_oneErrorThenSilence(
    caplog: pytest.LogCaptureFixture,
):
    """Example 2: FAILED/NO_SECRETS, never ACTIVATED -> 'not retried: connection never activated'."""
    launcher = _Launcher()
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    memory = runEvent(_noSecrets(), Memory(), launcher)

    assert launcher.calls == []
    assert len(_errorLines(caplog)) == 1
    assert _errorLines(caplog)[0].endswith("not retried: connection never activated")
    assert memory == Memory()


# ================================================================================
# (3) ACTIVATED(U) re-arms -> the next one is retried
# ================================================================================


def test_activatedAgain_rearms_theNextNoSecretsIsRetried():
    spent = decide(_noSecrets(), _armed()).memory
    assert decide(_noSecrets(), spent).action is None

    rearmed = decide(_activated(), spent).memory
    decision = decide(_noSecrets(), rearmed)

    assert rearmed.armed is True
    assert decision.action == ("/usr/bin/nmcli", "connection", "up", "uuid", UUID_U)


def test_activatedWithAnotherConnection_recordsThatUuid():
    """U is the uuid the device LAST reached ACTIVATED with."""
    memory = decide(_activated(UUID_V), _armed(UUID_U)).memory

    assert decide(_noSecrets(), memory).action == (
        "/usr/bin/nmcli", "connection", "up", "uuid", UUID_V,
    )


def test_activated_logsOneInfoLineAndTakesNoAction():
    decision = decide(_activated(), Memory())

    assert decision.action is None
    assert decision.level == logging.INFO
    assert decision.line is not None and UUID_U in decision.line


# ================================================================================
# (4) reason != 7, device != wlan0, psk-flags != 0 -> no action
# ================================================================================


@pytest.mark.parametrize(
    "reason",
    [REASON_USER_REQUESTED, REASON_SUPPLICANT_TIMEOUT, 0],
    ids=["user-deactivate", "supplicant-timeout", "none"],
)
def test_failedWithAnotherReason_noActionNoLine(reason: int):
    armed = _armed()
    decision = decide(_noSecrets(reason=reason), armed)

    assert decision.action is None
    assert decision.line is None
    assert decision.memory == armed, "a non-trigger failure must not spend the rearm"


def test_otherDevice_noActionNoLine():
    armed = _armed()
    decision = decide(_noSecrets(iface="eth0"), armed)

    assert decision.action is None
    assert decision.line is None
    assert decision.memory == armed


def test_otherDeviceActivated_doesNotRearmWlan0():
    memory = decide(_activated(UUID_V, iface="eth0"), Memory()).memory

    assert memory == Memory()


@pytest.mark.parametrize("pskFlags", [1, 2, 4])
def test_agentOwnedSecret_noAction(pskFlags: int):
    decision = decide(_noSecrets(), _armed(pskFlags=pskFlags))

    assert decision.action is None
    assert decision.line is not None and f"psk-flags={pskFlags}" in decision.line


# ================================================================================
# (8) / (9) the cause does not matter: reason-15 and reason-17 disconnects retry
# ================================================================================


@pytest.mark.parametrize("disconnectReason", ["15", "17", None])
def test_precedingDisconnectReason_neverDecides(disconnectReason: str | None):
    """
    Given: a NO_SECRETS failure preceded by a reason-15 / reason-17 disconnect
           (or none found in the supplicant lines -- the boot race)
    Then: it is retried; the reason only appears in the line
    """
    trail = SupplicantTrail(disconnectReason, BSSID_BEFORE, BSSID_AFTER)
    decision = decide(_noSecrets(trail), _armed())

    assert decision.action == ("/usr/bin/nmcli", "connection", "up", "uuid", UUID_U)
    assert f"after reason {disconnectReason or 'unknown'}," in (decision.line or "")


def test_reason15Replay_parsedFromSupplicantLinesAndRetried():
    lines = [
        f"wlan0: CTRL-EVENT-CONNECTED - Connection to {BSSID_BEFORE} completed [id=0 id_str=]",
        f"wlan0: CTRL-EVENT-DISCONNECTED bssid={BSSID_BEFORE} reason=15",
        f"wlan0: SME: Trying to authenticate with {BSSID_AFTER} (SSID='x' freq=5180 MHz)",
    ]
    trail = parseSupplicantLines(lines)
    decision = decide(_noSecrets(trail), _armed())

    assert trail == SupplicantTrail("15", BSSID_BEFORE, BSSID_AFTER)
    assert decision.action is not None


# ================================================================================
# parseSupplicantLines -- "the last supplicant lines"
# ================================================================================


def test_parseSupplicantLines_boot_f9eb34cc_roamThenReason17():
    """Replay: ACTIVATED on :b0 -> roam to :57 -> reason 17."""
    lines = [
        "Successfully initialized wpa_supplicant",
        f"wlan0: CTRL-EVENT-CONNECTED - Connection to {BSSID_BEFORE} completed [id=0 id_str=]",
        f"wlan0: SME: Trying to authenticate with {BSSID_AFTER} (SSID='x' freq=5180 MHz)",
        f"wlan0: CTRL-EVENT-DISCONNECTED bssid={BSSID_AFTER} reason=17",
        "p2p-dev-wlan0: CTRL-EVENT-DISCONNECTED bssid=00:00:00:00:00:00 reason=3",
    ]

    assert parseSupplicantLines(lines) == SupplicantTrail("17", BSSID_BEFORE, BSSID_AFTER)


def test_parseSupplicantLines_takesTheLastConnectedAndTheLastDisconnect():
    lines = [
        "wlan0: CTRL-EVENT-CONNECTED - Connection to 11:11:11:11:11:11 completed",
        "wlan0: CTRL-EVENT-DISCONNECTED bssid=11:11:11:11:11:11 reason=3",
        f"wlan0: CTRL-EVENT-CONNECTED - Connection to {BSSID_BEFORE} completed",
        f"wlan0: CTRL-EVENT-DISCONNECTED bssid={BSSID_BEFORE} reason=15",
    ]

    assert parseSupplicantLines(lines) == SupplicantTrail("15", BSSID_BEFORE, BSSID_BEFORE)


def test_parseSupplicantLines_nothingFound_isAllUnknown():
    trail = parseSupplicantLines(["unrelated", "wlan1: CTRL-EVENT-DISCONNECTED bssid=x reason=2"])

    assert trail == SupplicantTrail(None, None, None)
    decision = decide(_noSecrets(trail), _armed())
    assert decision.line is not None
    assert "after reason unknown, bssid unknown->unknown," in decision.line


# ================================================================================
# Negative case: nmcli itself fails -> ONE ERROR with its exit code, no retry loop
# ================================================================================


def test_nmcliExitNonZero_oneErrorLineWithItsExitCode(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    reportRetryExit(UUID_U, 10)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert "exit code 10" in caplog.records[0].getMessage()
    assert UUID_U in caplog.records[0].getMessage()


def test_nmcliExitZero_isOneInfoLine(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    reportRetryExit(UUID_U, 0)

    assert [r.levelno for r in caplog.records] == [logging.INFO]


def test_nmcliCannotStart_oneErrorLine_rearmStaysSpent(caplog: pytest.LogCaptureFixture):
    launcher = _Launcher(raises=FileNotFoundError("/usr/bin/nmcli"))
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    memory = runEvent(_noSecrets(), _armed(), launcher)
    memory = runEvent(_noSecrets(), memory, launcher)

    assert len(launcher.calls) == 1, "a failed launch is not retried"
    assert len(_errorLines(caplog)) == 2  # the launch failure, then the second event
    assert "could not start" in _errorLines(caplog)[0]


# ================================================================================
# (5) the constants cite NM's public D-Bus enums; no bare literal elsewhere
# ================================================================================


def test_constants_carryNmPublicEnumValues():
    assert NM_DEVICE_STATE_ACTIVATED == 100
    assert NM_DEVICE_STATE_FAILED == 120
    assert NM_DEVICE_STATE_REASON_NO_SECRETS == 7


def _sourceLines() -> list[str]:
    return MODULE_PATH.read_text(encoding="utf-8").splitlines()


def test_constants_carryTheNmDocsCitation():
    source = MODULE_PATH.read_text(encoding="utf-8")
    assert "nm-dbus-types" in source
    for name, enumName in (
        ("NM_DEVICE_STATE_ACTIVATED", "NMDeviceState"),
        ("NM_DEVICE_STATE_FAILED", "NMDeviceState"),
        ("NM_DEVICE_STATE_REASON_NO_SECRETS", "NMDeviceStateReason"),
    ):
        line = next(ln for ln in _sourceLines() if ln.startswith(f"{name} ="))
        assert enumName in line, f"{name} does not cite {enumName} on its line"


def _tree() -> ast.Module:
    return ast.parse(MODULE_PATH.read_text(encoding="utf-8"))


def test_noBareStateLiteralOutsideTheConstants():
    tree = _tree()
    constantLines = {
        node.lineno
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(t, ast.Name) and t.id.startswith("NM_DEVICE_STATE") for t in node.targets
        )
    }
    bare = [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and type(node.value) is int
        and node.value in (7, 100, 120)
        and node.lineno not in constantLines
    ]
    assert bare == []
    assert len(constantLines) == 3


# ================================================================================
# (6) NO TIMER, static
# ================================================================================

_TIMER_NAMES = {
    "sleep",
    "wait",
    "wait_for",
    "timeout",
    "timeout_add",
    "timeout_add_seconds",
    "monotonic",
    "perf_counter",
    "time",
    "Timer",
    "datetime",
    "timedelta",
}
_TIMER_MODULES = {"time", "datetime", "sched", "threading", "asyncio", "signal"}


def test_noTimer_noSleepWaitClockOrTimeoutName():
    found = []
    for node in ast.walk(_tree()):
        if isinstance(node, ast.Name) and node.id in _TIMER_NAMES:
            found.append((node.lineno, node.id))
        elif isinstance(node, ast.Attribute) and node.attr in _TIMER_NAMES:
            found.append((node.lineno, node.attr))
        elif isinstance(node, ast.keyword) and node.arg in _TIMER_NAMES:
            found.append((node.lineno, node.arg))
    assert found == []


def test_noTimer_noTimingModuleImported_andNoWhileLoop():
    tree = _tree()
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert not imported & _TIMER_MODULES
    assert not any(isinstance(n, (ast.While, ast.AsyncFor, ast.Await)) for n in ast.walk(tree))


def test_noTimer_noWaitFlagInCode():
    """`nmcli --wait` / `-w` would be a time budget; tokens, not prose, are scanned."""
    code = [
        tok.string
        for tok in tokenize.generate_tokens(io.StringIO(MODULE_PATH.read_text("utf-8")).readline)
        if tok.type == tokenize.STRING
    ]
    assert not [s for s in code if "--wait" in s or s.strip("'\"") == "-w"]


# ================================================================================
# (10) imports: stdlib + dbus/gi, and dbus/gi ONLY inside main()
# ================================================================================


def _imports(tree: ast.AST) -> list[tuple[str, ast.AST]]:
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(a.name.split(".")[0], node) for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append((".", node))
            elif node.module:
                found.append((node.module.split(".")[0], node))
    return found


def test_imports_onlyStdlibPlusDbusAndGi():
    allowed = set(sys.stdlib_module_names) | {"__future__", "dbus", "gi"}
    names = {name for name, _ in _imports(_tree())}

    assert names - allowed == set(), "wifi_recover imports a non-stdlib / project module"
    assert "src" not in names and "pi" not in names and "." not in names


def test_imports_dbusAndGiOnlyInsideMain():
    tree = _tree()
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    assert len(mains) == 1
    insideMain = {id(node) for _, node in _imports(mains[0])}

    outside = [
        (name, node.lineno)
        for name, node in _imports(tree)
        if name in ("dbus", "gi") and id(node) not in insideMain
    ]
    inside = {name for name, _ in _imports(mains[0])}
    assert outside == []
    assert {"dbus", "gi"} <= inside


def test_neverImportsGiRepositoryNM():
    """No NM typelib on the Pi: GLib is the only gi.repository name."""
    fromGi = [
        a.name
        for node in ast.walk(_tree())
        if isinstance(node, ast.ImportFrom) and node.module == "gi.repository"
        for a in node.names
    ]
    assert fromGi == ["GLib"]


# ================================================================================
# (11) GetSecrets is never called
# ================================================================================


def test_noGetSecretsLiteral():
    assert "GetSecrets" not in MODULE_PATH.read_text(encoding="utf-8")


def test_settingsReadWithGetSettings():
    assert "GetSettings" in MODULE_PATH.read_text(encoding="utf-8")


def test_subscribesByInterfaceAndMemberOnAnyPath():
    """Robustness: a receiver with no fixed path survives an NM restart's new device paths."""
    tree = _tree()
    calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add_signal_receiver"
    ]
    assert len(calls) == 1
    keywords = {k.arg for k in calls[0].keywords}
    assert {"signal_name", "dbus_interface", "path_keyword"} <= keywords
    assert "path" not in keywords


# ================================================================================
# The thin edge: event resolution reads only what it needs
# ================================================================================


class _FakeReader:
    def __init__(self, interface: str, uuid: str | None = UUID_U, pskFlags: int = 0) -> None:
        self.interface = interface
        self.uuid = uuid
        self.pskFlags = pskFlags
        self.connectionReads = 0

    def interfaceOf(self, devicePath: str) -> str:
        return self.interface

    def activatedConnection(self, devicePath: str) -> tuple[str | None, int]:
        self.connectionReads += 1
        return self.uuid, self.pskFlags


class _Trail:
    def __init__(self) -> None:
        self.reads = 0

    def __call__(self) -> SupplicantTrail:
        self.reads += 1
        return SupplicantTrail("17", BSSID_BEFORE, BSSID_AFTER)


def test_buildEvent_activatedReadsTheConnection_notTheJournal():
    reader, trail = _FakeReader(WIFI_INTERFACE, pskFlags=2), _Trail()

    event = wifi_recover.buildEvent(reader, "/dev/7", NM_DEVICE_STATE_ACTIVATED, 0, trail)

    assert (event.uuid, event.pskFlags) == (UUID_U, 2)
    assert trail.reads == 0


def test_buildEvent_triggerReadsTheJournalOnce():
    reader, trail = _FakeReader(WIFI_INTERFACE), _Trail()

    event = wifi_recover.buildEvent(
        reader, "/dev/9", NM_DEVICE_STATE_FAILED, NM_DEVICE_STATE_REASON_NO_SECRETS, trail
    )

    assert trail.reads == 1
    assert event.trail.disconnectReason == "17"
    assert reader.connectionReads == 0


def test_buildEvent_otherDeviceReadsNothingElse():
    reader, trail = _FakeReader("eth0"), _Trail()

    event = wifi_recover.buildEvent(
        reader, "/dev/3", NM_DEVICE_STATE_ACTIVATED, 0, trail
    )

    assert event.interface == "eth0"
    assert (trail.reads, reader.connectionReads) == (0, 0)


def test_pskFlagsOf_absentIsStored_presentIsRead():
    assert wifi_recover.pskFlagsOf({"connection": {}}) == 0
    assert wifi_recover.pskFlagsOf({"802-11-wireless-security": {"key-mgmt": "wpa-psk"}}) == 0
    assert wifi_recover.pskFlagsOf({"802-11-wireless-security": {"psk-flags": 1}}) == 1


def test_onChildExit_convertsTheWaitStatus(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    wifi_recover.onChildExit(1234, 4 << 8, UUID_U)

    assert "exit code 4" in caplog.records[0].getMessage()


# ================================================================================
# US-925-b: one WARNING per saved Wi-Fi profile whose psk-flags != 0
# ================================================================================


def _profile(name: str, pskFlags: int | None, kind: str = "802-11-wireless") -> dict:
    """A GetSettings result: no secrets, so never a `psk` key."""
    settings: dict = {"connection": {"id": name, "type": kind, "uuid": UUID_U}}
    if pskFlags is not None:
        settings["802-11-wireless-security"] = {"key-mgmt": "wpa-psk", "psk-flags": pskFlags}
    return settings


def _warningLines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]


def test_agentOwnedWarnings_pskFlagsZero_noWarning():
    assert wifi_recover.agentOwnedWarnings([_profile("Home", 0), _profile("Open", None)]) == []


@pytest.mark.parametrize("pskFlags", [1, 2])
def test_agentOwnedWarnings_pskFlagsNonZero_oneWarningNamingTheProfile(pskFlags: int):
    lines = wifi_recover.agentOwnedWarnings([_profile("Home", 0), _profile("Phone", pskFlags)])

    assert lines == [
        f"Wi-Fi profile Phone psk-flags={pskFlags} (agent-owned): "
        "no-secrets recovery cannot reuse its key"
    ]


def test_agentOwnedWarnings_onePerProfile_nonWifiIgnored():
    profiles = [
        _profile("Phone", 1),
        _profile("Desk", 2),
        _profile("eth", 1, kind="802-3-ethernet"),
    ]

    lines = wifi_recover.agentOwnedWarnings(profiles)

    assert [ln.split()[2] for ln in lines] == ["Phone", "Desk"]


def test_reportProfileSecrets_logsOneWarningPerAgentOwnedProfile(
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    wifi_recover.reportProfileSecrets([_profile("Phone", 1), _profile("Home", 0)])

    assert len(_warningLines(caplog)) == 1
    assert "Wi-Fi profile Phone psk-flags=1" in _warningLines(caplog)[0]
    assert "system-owned" not in caplog.text


def test_reportProfileSecrets_allSystemOwned_oneInfoLine(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    wifi_recover.reportProfileSecrets([_profile("Home", 0)])

    assert _warningLines(caplog) == []
    assert [r.getMessage() for r in caplog.records] == [
        "all Wi-Fi secrets system-owned (psk-flags=0)"
    ]


class _FakeBusObject:
    def __init__(self, bus: _FakeBus, path: str) -> None:
        self.bus, self.path = bus, path

    def ListConnections(self, dbus_interface: str) -> list[str]:
        self.bus.calls.append(("ListConnections", self.path, dbus_interface))
        return list(self.bus.settings)

    def GetSettings(self, dbus_interface: str) -> dict:
        self.bus.calls.append(("GetSettings", self.path, dbus_interface))
        return self.bus.settings[self.path]


class _FakeBus:
    def __init__(self, settings: dict[str, dict]) -> None:
        self.settings = settings
        self.calls: list[tuple[str, str, str]] = []

    def get_object(self, busName: str, path: str, introspect: bool = True) -> _FakeBusObject:
        return _FakeBusObject(self, path)


def test_savedConnectionSettings_listsThenGetSettingsEach():
    bus = _FakeBus({"/s/1": _profile("Home", 0), "/s/2": _profile("Phone", 1)})

    settings = wifi_recover.NmDeviceReader(bus).savedConnectionSettings()

    assert [s["connection"]["id"] for s in settings] == ["Home", "Phone"]
    assert [c[0] for c in bus.calls] == ["ListConnections", "GetSettings", "GetSettings"]
    assert bus.calls[0][1:] == (wifi_recover.NM_SETTINGS_PATH, wifi_recover.NM_SETTINGS_IFACE)


def test_mainRunsThePskFlagsCheckBeforeSubscribing():
    mains = [n for n in _tree().body if isinstance(n, ast.FunctionDef) and n.name == "main"]
    source = ast.get_source_segment(MODULE_PATH.read_text(encoding="utf-8"), mains[0])

    assert source is not None
    assert source.index("reportProfileSecrets(") < source.index("add_signal_receiver(")


def _stringTokens() -> list[str]:
    return [
        tok.string.strip("'\"")
        for tok in tokenize.generate_tokens(io.StringIO(MODULE_PATH.read_text("utf-8")).readline)
        if tok.type == tokenize.STRING
    ]


def test_neverModifiesAProfile_neverReadsOrPrintsAPsk():
    """Static pin: no `connection modify`, no show-secrets flag, no `psk` field read."""
    source = MODULE_PATH.read_text(encoding="utf-8")
    strings = _stringTokens()

    assert not re.search(r"\bcon(nection)?[ \t\"',]+mod(ify)?\b", source)
    assert not [s for s in strings if s in ("-s", "--show-secrets")]
    assert "psk" not in strings
    assert not re.search(r"802-11-wireless-security\.psk\b(?!-)", source)
    assert not re.search(r"\[[\"']psk[\"']\]", source)


# ================================================================================
# US-925-c: READY=1 only after the subscription, and the sender is pinned
# ================================================================================

NOTIFY_PATH = "/run/systemd/notify"


class _FakeSocket:
    """A datagram socket that records into the shared event log."""

    def __init__(self, events: list[tuple[str, Any]], family: str, kind: str) -> None:
        self._events = events
        self._events.append(("socket", (family, kind)))

    def __enter__(self) -> _FakeSocket:
        return self

    def __exit__(self, *exc: object) -> None:
        self._events.append(("close", None))

    def connect(self, address: str) -> None:
        self._events.append(("connect", address))

    def sendall(self, data: bytes) -> None:
        self._events.append(("send", data))


def _fakeSocketModule(events: list[tuple[str, Any]]) -> types.SimpleNamespace:
    # The bench's Windows CPython has no socket.AF_UNIX, so the module is faked whole.
    return types.SimpleNamespace(
        AF_UNIX="AF_UNIX",
        SOCK_DGRAM="SOCK_DGRAM",
        socket=lambda family, kind: _FakeSocket(events, family, kind),
    )


class _FakeEmptySettings:
    def ListConnections(self, dbus_interface: str) -> list[str]:  # noqa: N802 -- D-Bus name
        return []


class _FakeSystemBus:
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        self._events = events
        self.receivers: list[dict[str, Any]] = []

    def get_object(self, busName: str, path: str, introspect: bool = True) -> Any:
        return _FakeEmptySettings()

    def add_signal_receiver(self, handler: Any, **kwargs: Any) -> None:
        self.receivers.append(kwargs)
        self._events.append(("subscribed", kwargs.get("bus_name")))


class _EventHandler(logging.Handler):
    def __init__(self, events: list[tuple[str, Any]]) -> None:
        super().__init__()
        self._events = events

    def emit(self, record: logging.LogRecord) -> None:
        self._events.append(("log", record.getMessage()))


def _runMain(
    monkeypatch: pytest.MonkeyPatch, notifySocket: str | None
) -> tuple[list[tuple[str, Any]], _FakeSystemBus]:
    """Run the real main() on a fake dbus/gi and a fake socket module."""
    events: list[tuple[str, Any]] = []
    bus = _FakeSystemBus(events)

    dbusModule = types.ModuleType("dbus")
    dbusModule.SystemBus = lambda: bus  # type: ignore[attr-defined]
    dbusModule.exceptions = types.SimpleNamespace(  # type: ignore[attr-defined]
        DBusException=type("DBusException", (Exception,), {})
    )
    glibLoopModule = types.ModuleType("dbus.mainloop.glib")
    glibLoopModule.DBusGMainLoop = lambda set_as_default: None  # type: ignore[attr-defined]
    repositoryModule = types.ModuleType("gi.repository")
    repositoryModule.GLib = types.SimpleNamespace(  # type: ignore[attr-defined]
        MainLoop=lambda: types.SimpleNamespace(run=lambda: events.append(("loop", None))),
        PRIORITY_DEFAULT=0,
        child_watch_add=lambda *args: None,
    )
    for name, module in (
        ("dbus", dbusModule),
        ("dbus.mainloop", types.ModuleType("dbus.mainloop")),
        ("dbus.mainloop.glib", glibLoopModule),
        ("gi", types.ModuleType("gi")),
        ("gi.repository", repositoryModule),
    ):
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(wifi_recover, "socket", _fakeSocketModule(events))
    if notifySocket is None:
        monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    else:
        monkeypatch.setenv("NOTIFY_SOCKET", notifySocket)

    handler = _EventHandler(events)
    level = wifi_recover.logger.level
    wifi_recover.logger.addHandler(handler)
    wifi_recover.logger.setLevel(logging.INFO)
    try:
        assert wifi_recover.main() == 0
    finally:
        wifi_recover.logger.removeHandler(handler)
        wifi_recover.logger.setLevel(level)
    return events, bus


def _kinds(events: list[tuple[str, Any]]) -> list[str]:
    return [kind for kind, _ in events]


def test_main_sendsReadyOnlyAfterTheSubscription(monkeypatch: pytest.MonkeyPatch):
    """
    Given: systemd set NOTIFY_SOCKET (Type=notify)
    When: main() starts
    Then: READY=1 goes out once, after add_signal_receiver returned, before the loop runs
    """
    events, _ = _runMain(monkeypatch, NOTIFY_PATH)

    kinds = _kinds(events)
    assert kinds.count("send") == 1
    assert ("send", b"READY=1") in events
    assert ("connect", NOTIFY_PATH) in events
    assert ("socket", ("AF_UNIX", "SOCK_DGRAM")) in events
    assert kinds.index("subscribed") < kinds.index("socket") < kinds.index("send")
    assert kinds.index("send") < kinds.index("loop")


def test_main_watchingLineIsWrittenBeforeReady(monkeypatch: pytest.MonkeyPatch):
    """The deploy gate reads 'watching wlan0' as soon as the restart returns on READY."""
    events, _ = _runMain(monkeypatch, NOTIFY_PATH)

    kinds = _kinds(events)
    watching = [i for i, (k, v) in enumerate(events) if k == "log" and "watching wlan0" in v]
    assert len(watching) == 1
    assert kinds.index("subscribed") < watching[0] < kinds.index("send")


def test_main_noNotifySocket_sendsNothing_andStillRuns(monkeypatch: pytest.MonkeyPatch):
    """Desk / tests: NOTIFY_SOCKET unset -> no socket at all, no failure."""
    events, _ = _runMain(monkeypatch, None)

    kinds = _kinds(events)
    assert "socket" not in kinds and "send" not in kinds
    assert kinds[-1] == "loop"


def test_main_abstractNotifySocket_atBecomesNul(monkeypatch: pytest.MonkeyPatch):
    events, _ = _runMain(monkeypatch, "@/org/freedesktop/systemd1/notify/42")

    assert ("connect", "\0/org/freedesktop/systemd1/notify/42") in events


def test_main_subscribesOnlyToNetworkManagersSignals(monkeypatch: pytest.MonkeyPatch):
    """Sender match (Atlas RULED): only NetworkManager's StateChanged reaches the handler."""
    _, bus = _runMain(monkeypatch, None)

    assert len(bus.receivers) == 1
    assert bus.receivers[0]["bus_name"] == "org.freedesktop.NetworkManager"
    assert NM_BUS_NAME == "org.freedesktop.NetworkManager"


def test_subscription_passesBusName_static():
    calls = [
        n
        for n in ast.walk(_tree())
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "add_signal_receiver"
    ]
    (call,) = calls
    busName = [k.value for k in call.keywords if k.arg == "bus_name"]
    assert len(busName) == 1
    assert isinstance(busName[0], ast.Name) and busName[0].id == "NM_BUS_NAME"


def test_notifyReady_sendFails_logsOneErrorAndReturnsFalse(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    class _Refused(_FakeSocket):
        def connect(self, address: str) -> None:
            raise ConnectionRefusedError("refused")

    events: list[tuple[str, Any]] = []
    fake = _fakeSocketModule(events)
    fake.socket = lambda family, kind: _Refused(events, family, kind)
    monkeypatch.setattr(wifi_recover, "socket", fake)
    caplog.set_level(logging.INFO, logger=wifi_recover.LOGGER_NAME)

    assert wifi_recover.notifyReady({"NOTIFY_SOCKET": NOTIFY_PATH}) is False
    assert len(_errorLines(caplog)) == 1
    assert "send" not in _kinds(events)


def test_notifyReady_unsetOrEmpty_returnsFalseAndOpensNothing(monkeypatch: pytest.MonkeyPatch):
    events: list[tuple[str, Any]] = []
    monkeypatch.setattr(wifi_recover, "socket", _fakeSocketModule(events))

    assert wifi_recover.notifyReady({}) is False
    assert wifi_recover.notifyReady({"NOTIFY_SOCKET": ""}) is False
    assert events == []

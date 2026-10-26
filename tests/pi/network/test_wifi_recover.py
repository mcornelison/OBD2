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
# ================================================================================
################################################################################

"""Tests for ``src.pi.network.wifi_recover`` (Windows-runnable: no D-Bus)."""

from __future__ import annotations

import ast
import io
import logging
import sys
import tokenize
from pathlib import Path

import pytest

from src.pi.network import wifi_recover
from src.pi.network.wifi_recover import (
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

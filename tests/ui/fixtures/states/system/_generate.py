################################################################################
# File Name: _generate.py
# Purpose/Description: US-894-b (spec specs/v030-system-page-design.md s7,
#   Atlas L7) -- GENERATES the System page fixtures in this directory from the
#   REAL builders, with every input written here. Never hand-type a fixture:
#   edit an input below and re-run this script.
#
#   Each fixture is {description, now, zone, inputs, payloads} -- a deliberate
#   departure from the nav fixtures' {description, now, zone, inputs,
#   system-status}: the System page reads up to three state files, so
#   `payloads` is keyed by state name ("system-status", "capture-health",
#   "battery-health") and `inputs` by the same names.
#
#   Composition, as the producers do it:
#     - system-status = buildSystemStatusState(**inputs, captureHealth=<the
#       capture-health payload below>). The builder computes the verdict
#       inside it (S109); buildSystemVerdict is NEVER called separately --
#       that would be a second verdict.
#     - capture-health = buildCaptureHealthState(...) plus, when feed samples
#       are given, payload["feeds"] = buildCaptureFeedsState(...) -- exactly
#       as makeCaptureHealthEmitter.emit composes them
#       (src/pi/obdii/capture_health.py).
#     - battery-health = buildBatteryHealthState(...)
#       (src/pi/splash/battery_health_emitter.py).
#
#   THE ONE EXCEPTION (documented, spec s7 `verdict-absent`): that fixture is
#   the generated all-ok-driving system-status with `verdict` popped -- no
#   builder can publish a payload without one, and the page must still read
#   `--` when a file lacks it.
#
#   Usage: python tests/ui/fixtures/states/system/_generate.py
#   (tests/ui/test_system_page_obd_row.py asserts every file on disk equals
#   what this script builds, so a stale fixture fails the suite.)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-b System page OBD-row fixtures.
# 2026-10-23    | Ralph (Rex)  | US-894-c: the DATA-row fixtures (capture + sync);
#               |              | syncRows / syncPending retired from the inputs.
# 2026-10-23    | Ralph (Rex)  | US-894-d: the four WIFI-row fixtures the story
#               |              | names (weak-home, not-read, nmcli-absent,
#               |              | read-failed).
# 2026-10-23    | Ralph (Rex)  | US-894-e: the two UPS-row fixtures the story
#               |              | names (ups-on-battery, ups-gauge-unreadable),
#               |              | priorShutdown from computePriorShutdownSummary.
# 2026-10-23    | Ralph (Rex)  | US-894-f: the three Pi fixtures the story names
#               |              | (pi-hot, pi-multi-limit, two-issues), the pi
#               |              | block from pi_health.buildPiHealthBlock.
# 2026-10-23    | Ralph (Rex)  | US-895-a: the five settings-* fixtures (gear
#               |              | from buildGearState; band-state stub + a
#               |              | recorded real /settings response).
# 2026-10-23    | Ralph (Rex)  | US-895-b: settings-lux-cross-rejected (a stale
#               |              | band stub; the recorded real cross-key 400).
# ================================================================================
################################################################################

"""Generate the US-894-b/c System page fixtures from the real builders."""

from __future__ import annotations

import copy
import json
import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
_SRC = os.path.join(_REPO_ROOT, "src")
# Both roots: pi.obdii's package imports reach `src.pi...` absolutely.
for _root in (_REPO_ROOT, _SRC):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from pi.diagnostics.disk_space_guard import (  # noqa: E402
    LOW_DISK_THRESHOLD_BYTES,
    DiskSpaceState,
    DiskVerdict,
)
from pi.diagnostics.prior_shutdown_summary import (  # noqa: E402
    computePriorShutdownSummary,
)
from pi.hardware.pi_health import buildPiHealthBlock, parseThrottled  # noqa: E402
from pi.network.wifi_reader import (  # noqa: E402
    WIFI_REASON_NMCLI_ABSENT,
    WIFI_REASON_READ_FAILED,
)
from pi.obdii import gear_derivation as gd  # noqa: E402
from pi.obdii.capture_health import (  # noqa: E402
    DEFAULT_STALL_SECONDS,
    REASON_NEVER_WRITTEN,
    buildCaptureFeedsState,
    buildCaptureHealthState,
)
from pi.obdii.gear_derivation import GearReading  # noqa: E402
from pi.obdii.gear_state_emitter import buildGearState  # noqa: E402
from pi.splash.battery_health_emitter import (  # noqa: E402
    VERDICT_GOOD,
    buildBatteryHealthState,
)
from pi.splash.source_availability import REASON_UPS_UNREADABLE  # noqa: E402
from pi.splash.system_status_emitter import (  # noqa: E402
    REASON_WIFI_UNKNOWN,
    buildSystemStatusState,
)

NOW = "2026-10-22T23:10:00Z"
ZONE = "America/Chicago"
_EARLIER = "2026-10-22T23:08:30Z"
_FIRST_UP = "2026-10-22T22:41:05Z"
_HOME_SSID = "DeathstarWifi"


def _layer(state: str | None, *, ts: str | None = _EARLIER, lastOkTs: str | None = None) -> dict:
    """One link layer as LinkLayerTracker publishes it (state null = all null)."""
    if state is None:
        return {"state": None, "ts": None, "lastOkTs": None}
    return {"state": state, "ts": ts, "lastOkTs": lastOkTs}


def _link(bt: dict, adapter: dict, ecu: dict) -> dict:
    return {"bt": bt, "adapter": adapter, "ecu": ecu}


def _systemInputs(
    link: dict, *, driveState: str = "idle", driveId: int | None = None, **overrides: Any
) -> dict:
    """A parked-at-home system-status input set; each fixture overrides the link
    and, for the DATA fixtures, any other builder input by keyword."""
    inputs = {
        "syncLastOkTs": "2026-10-22T22:55:12Z",
        "syncStale": False,
        "syncRowsWaiting": 0,
        "syncEdrRowsWaiting": 0,
        "syncNotCounted": [],
        "powerSource": "external",
        "driveState": driveState,
        "driveId": driveId,
        "nowIso": NOW,
        "wifiAvailable": True,
        "wifiSsid": _HOME_SSID,
        "wifiRssiDbm": -55,
        "wifiHome": True,
        "wifiTs": NOW,
        "piHealth": None,
        "link": link,
    }
    inputs.update(overrides)
    return inputs


def _upChain() -> dict:
    """All three layers up since _FIRST_UP -- the ECU up, so a stalled feed
    is a capture member (system_status_emitter.buildSystemVerdict)."""
    return _link(
        _layer("up", ts=_FIRST_UP, lastOkTs=NOW),
        _layer("up", ts=_FIRST_UP, lastOkTs=NOW),
        _layer("up", ts=_FIRST_UP, lastOkTs=NOW),
    )


def _priorShutdown(clean: int, reason: str) -> dict:
    """The priorShutdown block as the producer publishes it, from one
    startup_log row (US-728 computePriorShutdownSummary, US-744)."""
    return computePriorShutdownSummary({
        "boot_id": "b-ups-fixture",
        "prior_boot_clean": clean,
        "prior_boot_reason": reason,
        "prior_boot_last_stage": "poweroff",
        "prior_last_entry_ts": "2026-10-22T03:14:55Z",
        "recorded_at": "2026-10-22T20:05:10Z",
        "data_quality": None,
    }).toStatePayload()


def _battery(**overrides: Any) -> dict:
    """battery-health emit inputs for the Pi UPS cell; each fixture
    overrides what its name says."""
    inputs = {
        "vcellV": 4.12,
        "soc": 92,
        "socCalibrated": False,
        "crate": None,
        "charging": False,
        "draining": False,
        "restedVcellV": 4.15,
        "weakEvents30d": 0,
        "restedHistory": [],
        "health": VERDICT_GOOD,
        "fullChargeReached": True,
        "runtimeToCutoffS": 660,
        "ambientTempC": None,
        "lastHealthCheckTs": "2026-10-20T03:00:00Z",
        "ladder": None,
        "nowIso": "2026-10-22T23:09:48Z",
        "timeToFloorS": 660,
        "jobAvgS": 40,
    }
    inputs.update(overrides)
    return inputs


_GIB = 2**30
# The effective pi.health.limits.cpuTempC on shipped config (validator default).
_CPU_TEMP_LIMIT_C = 80.0
# The fast reads (temp, throttled, uptime) land every 10 s; the disk every
# 600 s, so its read time is older -- each value carries its OWN ts.
_PI_FAST_TS = "2026-10-22T23:09:55Z"
_PI_DISK_TS = "2026-10-22T23:01:12Z"


def _piHealth(
    *, cpuTempC: float = 58.4, throttled: str = "0x0", diskFreeBytes: int = int(41.3 * _GIB),
    uptimeS: float = 10920.6,
) -> dict:
    """The `pi` block exactly as pi_health.buildPiHealthBlock assembles it
    (overLimit derived there, never written here)."""
    verdict = (DiskVerdict.BREACHED if diskFreeBytes < LOW_DISK_THRESHOLD_BYTES
               else DiskVerdict.HEALTHY)
    return buildPiHealthBlock(
        cpuTempC=cpuTempC,
        cpuTempTs=_PI_FAST_TS,
        cpuTempLimitC=_CPU_TEMP_LIMIT_C,
        throttled=parseThrottled(f"throttled={throttled}"),
        throttledTs=_PI_FAST_TS,
        disk=DiskSpaceState(
            verdict=verdict, freeBytes=diskFreeBytes, thresholdBytes=LOW_DISK_THRESHOLD_BYTES,
        ),
        diskTs=_PI_DISK_TS,
        uptimeS=uptimeS,
        uptimeTs=_PI_FAST_TS,
    )


def _capture(
    lastRowSecondsAgo: float | None,
    *,
    freshnessReason: str | None = None,
    obd: float | None = 0.4,
    light: float | None = 0.9,
    imu: float | None = 0.1,
    ups: float | None = 4.0,
) -> dict:
    """Capture-health emit inputs on external power; each feed's last-sample
    age is given (None = the feed produced nothing this process)."""
    samples = {
        name: (_FIRST_UP if age is not None else None, age)
        for name, age in (("obd", obd), ("light", light), ("imu", imu), ("ups", ups))
    }
    return {
        "lastRowSecondsAgo": lastRowSecondsAgo,
        "freshnessReason": freshnessReason,
        "powerSource": "external",
        "stallSeconds": DEFAULT_STALL_SECONDS,
        "feedSamples": samples,
    }


# fixture name -> (description, {state name: inputs}). Capture-health inputs
# are the emit's keyword arguments; system-status inputs are the builder's,
# less captureHealth, which is the composed capture-health payload.
FIXTURES: dict[str, tuple[str, dict[str, Any]]] = {
    "arch061-during-attempt": (
        "AC 2 (G1): key off, parked, home; BT + adapter up, ECU connecting "
        "(g-g-n) -> ALL OK, 'ECU not answering (key off?)', no 'Bluetooth down'.",
        {"system-status": _systemInputs(_link(
            _layer("up", lastOkTs=_EARLIER), _layer("up", lastOkTs=_EARLIER),
            _layer("connecting"),
        ))},
    ),
    "arch061-between-attempts": (
        "AC 3 (G1): key off, parked, home; all three connecting (n-n-n), the "
        "parked steady state -> ALL OK, every step neutral, 'Bluetooth trying "
        "to link (key off?)'.",
        {"system-status": _systemInputs(_link(
            _layer("connecting"), _layer("connecting"), _layer("connecting"),
        ))},
    ),
    "all-ok-driving": (
        "All three layers up, recording, home, external power, every feed "
        "writing -> ALL OK, 'ECU answering'.",
        {
            "system-status": _systemInputs(
                _link(
                    _layer("up", ts=_FIRST_UP, lastOkTs=NOW),
                    _layer("up", ts=_FIRST_UP, lastOkTs=NOW),
                    _layer("up", ts=_FIRST_UP, lastOkTs=NOW),
                ),
                driveState="recording",
                driveId=212,
            ),
            "capture-health": {
                "lastRowSecondsAgo": 0.4,
                "freshnessReason": None,
                "powerSource": "external",
                "stallSeconds": DEFAULT_STALL_SECONDS,
                "feedSamples": {
                    "obd": (_FIRST_UP, 0.4),
                    "light": (_FIRST_UP, 0.9),
                    "imu": (_FIRST_UP, 0.1),
                    "ups": (_FIRST_UP, 4.0),
                },
            },
            "battery-health": {
                "vcellV": 4.12,
                "soc": 92,
                "socCalibrated": False,
                "crate": None,
                "charging": False,
                "draining": False,
                "restedVcellV": 4.15,
                "weakEvents30d": 0,
                "restedHistory": [],
                "health": VERDICT_GOOD,
                "fullChargeReached": True,
                "runtimeToCutoffS": None,
                "ambientTempC": None,
                "lastHealthCheckTs": "2026-10-20T03:00:00Z",
                "ladder": None,
                "nowIso": "2026-10-22T23:09:48Z",
            },
        },
    ),
    "bt-connecting": (
        "AC 3: key-on, Bluetooth's first attempt under way, the later layers "
        "not read -> BT step neutral, 'Bluetooth trying to link (key off?)', "
        "uncounted.",
        {"system-status": _systemInputs(_link(
            _layer("connecting"), _layer(None), _layer(None),
        ))},
    ),
    "bt-retrying": (
        "AC 3: a drive is recording and the link dropped after being up this "
        "session -> the bt member, 1 ISSUE, BT step amber, the sentence is the "
        "member's reason verbatim (bt retrying is a member only while "
        "recording, Atlas E3).",
        {"system-status": _systemInputs(
            _link(
                _layer("retrying", lastOkTs=_EARLIER),
                _layer("retrying", lastOkTs=_EARLIER),
                _layer("retrying", lastOkTs=_EARLIER),
            ),
            driveState="recording",
            driveId=212,
        )},
    ),
    "adapter-silent": (
        "Bluetooth up, the adapter not answering -> the adapter member, "
        "1 ISSUE, ADAPTER step amber, the member's reason verbatim (amber).",
        {"system-status": _systemInputs(_link(
            _layer("up", lastOkTs=_EARLIER),
            _layer("retrying", lastOkTs=_FIRST_UP),
            _layer("retrying", lastOkTs=_FIRST_UP),
        ))},
    ),
    "link-not-read": (
        "AC 4 (ARCH-062): every layer null this session -> dashed steps, "
        "hollow dots, 'Bluetooth not read yet' (later layers do not speak), "
        "ALL OK (nothing read is no issue).",
        {"system-status": _systemInputs(_link(_layer(None), _layer(None), _layer(None)))},
    ),
    "ecu-retrying-after-keyoff": (
        "I1/I2: BT + adapter up, the ECU retrying after key-off (never a "
        "member) -> ALL OK, ECU step --text-secondary, 'ECU not answering "
        "(key off?)'.",
        {"system-status": _systemInputs(_link(
            _layer("up", lastOkTs=_EARLIER), _layer("up", lastOkTs=_EARLIER),
            _layer("retrying", lastOkTs=_FIRST_UP),
        ))},
    ),
    "adapter-down-bt-down": (
        "I1/I2: Bluetooth down and the adapter down -> the bt member speaks; "
        "the adapter step is not amber (BT is the fault).",
        {"system-status": _systemInputs(_link(
            _layer("down"), _layer("down"), _layer(None),
        ))},
    ),
    # --- US-894-c: the DATA row (spec s4.3, s7) ---------------------------
    "capture-stalled": (
        "Recording, the ECU up, the OBD feed and the logger both silent past "
        "the stall window -> the capture member, 1 ISSUE, DATA value "
        "'stalled' amber, the sentence is the member's reason verbatim.",
        {
            "system-status": _systemInputs(
                _upChain(), driveState="recording", driveId=212,
                syncRowsWaiting=482,
            ),
            "capture-health": _capture(75.0, obd=75.0),
        },
    ),
    "away-from-home": (
        "Recording on another network, weak -> 'away from home', rows "
        "waiting, neutral and uncounted (ALL OK).",
        {
            "system-status": _systemInputs(
                _upChain(), driveState="recording", driveId=212,
                wifiSsid="Starbucks WiFi", wifiRssiDbm=-75, wifiHome=False,
                syncLastOkTs="2026-10-22T13:02:40Z", syncRowsWaiting=3880,
            ),
            "capture-health": _capture(0.4),
        },
    ),
    "rows-not-counted": (
        "At home with snapshot tables named in notCounted -> "
        "'12,345+ rows waiting' on the row (the + on the number), the "
        "tables by name in the DATA detail, never folded into the count.",
        {
            "system-status": _systemInputs(
                _upChain(), syncRowsWaiting=12345, syncEdrRowsWaiting=1771,
                syncNotCounted=["profiles", "startup_log", "vehicle_info"],
            ),
            "capture-health": _capture(0.4),
        },
    ),
    "capture-stalled-ecu-silent": (
        "A4: top-level stalled (rows once, none in the window), the ECU down "
        "-> no member, 'stopped' in --text-secondary, 'ECU not answering', "
        "ALL OK.",
        {
            "system-status": _systemInputs(_link(
                _layer("up", lastOkTs=_EARLIER), _layer("up", lastOkTs=_EARLIER),
                _layer("down", lastOkTs=_FIRST_UP),
            )),
            "capture-health": _capture(300.0, obd=300.0),
        },
    ),
    "capture-never-written-ecu-up": (
        "A4 VC 1 / W3: a cold boot -- the logger has written no row, the ECU "
        "up, no stalled feed -> 'no rows', 'no row logged this session', "
        "0 members, no ECU words.",
        {
            "system-status": _systemInputs(_upChain()),
            "capture-health": _capture(
                None, freshnessReason=REASON_NEVER_WRITTEN, obd=None,
            ),
        },
    ),
    "capture-ups-feed-stalled": (
        "A4 VC 2: top-level ok, the UPS feed stalled, the ECU up -> 'stalled' "
        "amber, 'UPS feed stalled.', 1 member; the amber sits on the UPS feed "
        "in the detail.",
        {
            "system-status": _systemInputs(_upChain(), driveState="recording", driveId=212),
            "capture-health": _capture(0.4, ups=140.0),
        },
    ),
    "sync-days-old": (
        "I3: the last data stored ten days ago -> 'synced Oct 12', never a "
        "bare time; the full stamp is in the detail.",
        {
            "system-status": _systemInputs(
                _upChain(), syncLastOkTs="2026-10-12T19:40:00Z", syncRowsWaiting=91234,
            ),
            "capture-health": _capture(0.4),
        },
    ),
    "sync-stale-glyph": (
        "I4: recording with sync.stale and no member -> the sync glyph "
        "neutral, ALL OK; last stored the local day before -> 'synced "
        "yesterday', no time on the row.",
        {
            "system-status": _systemInputs(
                _upChain(), driveState="recording", driveId=212, syncStale=True,
                syncLastOkTs="2026-10-21T22:59:00Z", syncRowsWaiting=6120,
            ),
            "capture-health": _capture(0.4),
        },
    ),
    # --- US-894-d: the WIFI row (spec s4.4, s7) ---------------------------
    "wifi-weak-home": (
        "On the home network inside the emitter's weak band -> 'home' green, "
        "'DeathstarWifi · weak signal', the glyph neutral (weak is never "
        "amber), uncounted.",
        {"system-status": _systemInputs(_upChain(), wifiRssiDbm=-77)},
    ),
    "wifi-not-read": (
        "No WiFi sample taken yet (the emitter's not_read) -> '--', 'not read "
        "yet', dim arcs with no slash, uncounted.",
        {"system-status": _systemInputs(
            _upChain(), wifiAvailable=False, wifiSsid=None, wifiRssiDbm=None,
            wifiHome=None, wifiUnavailableReason=REASON_WIFI_UNKNOWN,
        )},
    ),
    "wifi-nmcli-absent": (
        "The dev box: no nmcli on the host -> '--', 'no WiFi tool on this "
        "host', dim arcs with no slash, uncounted (ALL OK).",
        {"system-status": _systemInputs(
            _upChain(), wifiAvailable=False, wifiSsid=None, wifiRssiDbm=None,
            wifiHome=None, wifiUnavailableReason=WIFI_REASON_NMCLI_ABSENT,
        )},
    ),
    "wifi-read-failed": (
        "The WiFi read failed -> the wifi member, 1 ISSUE, '? not read' amber, "
        "the member's reason verbatim; the glyph amber, the one amber WiFi "
        "state.",
        {"system-status": _systemInputs(
            _upChain(), wifiAvailable=False, wifiSsid=None, wifiRssiDbm=None,
            wifiHome=None, wifiUnavailableReason=WIFI_REASON_READ_FAILED,
        )},
    ),
    # --- US-894-e: the UPS row (spec s4.5, s4.6.1, s7) ---------------------
    "ups-on-battery": (
        "External power lost, the Pi riding the UPS down: power.source battery, "
        "VCELL 4.02 V read 3 s ago, the pack draining with a failsafe ladder "
        "published -> UPS '4.02 V', 'on battery · 3 s ago', neutral (no UPS "
        "member, the verdict unchanged); the detail carries LAST STOP and no "
        "ladder, no 'min to cutoff'.",
        {
            "system-status": _systemInputs(
                _upChain(), powerSource="battery",
                priorShutdown=_priorShutdown(1, "clean_poweroff"),
            ),
            "battery-health": _battery(
                vcellV=4.02, soc=81, draining=True,
                ladder={
                    "stage": "WARNING",
                    "thresholds": {"warning": 3.7, "imminent": 3.55, "trigger": 3.45},
                    "runtimeRemainingS": 540,
                },
                nowIso="2026-10-22T23:09:57Z",
            ),
        },
    ),
    "ups-gauge-unreadable": (
        "The MAX17048 read failed: battery-health source.ups unavailable "
        "('gauge unreadable') on external power -> UPS '--' plus the typed "
        "reason, 'on external power', no health or SOC line beside the NA.",
        {
            "system-status": _systemInputs(
                _upChain(), priorShutdown=_priorShutdown(1, "clean_poweroff"),
            ),
            "battery-health": _battery(
                vcellV=None, soc=None, restedVcellV=None,
                upsAvailable=False, upsUnavailableReason=REASON_UPS_UNREADABLE,
            ),
        },
    ),
    # --- US-894-f: the Pi line and the Pi detail (spec s4.1, s4.6.2, s7) ----
    "pi-hot": (
        "The CPU at 80.2 C against the published 80 C limit -> the pi member, "
        "1 ISSUE, the Pi line under the verdict (the reason verbatim, ' ›' "
        "only while parked); in the Pi detail only the CPU value is amber.",
        {"system-status": _systemInputs(_upChain(), piHealth=_piHealth(cpuTempC=80.2))},
    ),
    "pi-multi-limit": (
        "CPU temp, throttling (under-voltage now and since boot, 0x50005) and "
        "the disk under its 20 GiB limit -> one pi member, 'Over limit: CPU "
        "temp, throttling, disk.', the three crossed values amber, uptime not.",
        {"system-status": _systemInputs(_upChain(), piHealth=_piHealth(
            cpuTempC=81.4, throttled="0x50005", diskFreeBytes=int(19.97 * _GIB),
        ))},
    ),
    "two-issues": (
        "A drive recording, the link dropped (bt retrying) and the CPU hot -> "
        "bt + pi, 2 ISSUES; amber exactly on the BT step, its sentence, its "
        "top-bar dot and the Pi line -- the amber set equals the member set.",
        {"system-status": _systemInputs(
            _link(
                _layer("retrying", lastOkTs=_EARLIER),
                _layer("retrying", lastOkTs=_EARLIER),
                _layer("retrying", lastOkTs=_EARLIER),
            ),
            driveState="recording",
            driveId=212,
            piHealth=_piHealth(cpuTempC=80.2),
        )},
    ),
}

# --- US-895-a: the Settings lock (spec s4.7.2, AC 8/9, s7) -------------------
# Each is a system-status payload (the page under the band) plus the states/gear
# payload from buildGearState(GearReading(...)) -- the ONE parked fact's input.
# The 8 s hold itself is never a static fixture: tests/ui/test_settings_lock.py
# drives the clock over these (7 s locked, 8 s unlocked).
#
# TEST-ONLY STUBS (allowed for settings-* fixtures, acceptance): `settings` is
# the band-state stub -- the window.DISPLAY_SETTINGS {found, value} blob the
# state server injects -- and `settings-write` is a RECORDED response of the
# REAL _handleSettingsWrite (a StatesHttpServer over a temp config, below),
# {status, body}; never a hand-typed body.
_GEAR_NEUTRAL = {"available": True, "gear": gd.GEAR_NEUTRAL, "reason": gd.REASON_NEUTRAL}
_SETTINGS_STORED = {
    "pi.display.carousel.autoRotateS": 0,
    "pi.calibration.mode": False,
    "pi.analysis.triggerAfterDrive": False,
}
# The config the recorded writes run against: the stored values above, so a
# re-read returns exactly what the band stub says is stored.
_SETTINGS_CONFIG = {
    "deviceId": "fixture-pi",
    "pi": {
        "display": {"carousel": {"autoRotateS": 0}},
        "calibration": {"mode": False},
        "analysis": {"triggerAfterDrive": False},
    },
}
_SETTINGS_TOKEN = "fixture-token-0123456789abcdefghijklmnopqrstuv"

# US-895-b: the lux ends at the shipped 3 / 300, in the stub AND config.json.
# The overlay luxMin 200 was saved AFTER this page loaded (another surface, or
# a hand edit), so the page still reads 3 and offers FULL-BRIGHT − to 200; the
# seam judges 200 against the stored 200 and refuses it.
_LUX_STORED = {"pi.display.autoDim.luxMin": 3.0, "pi.display.autoDim.luxFull": 300.0}
_LUX_CONFIG = copy.deepcopy(_SETTINGS_CONFIG)
_LUX_CONFIG["pi"]["display"]["autoDim"] = {"luxMin": 3.0, "luxFull": 300.0}
_LUX_OVERLAY = {"pi.display.autoDim.luxMin": 200.0}

SETTINGS_FIXTURES: dict[str, tuple[str, dict[str, Any]]] = {
    "settings-locked-hold": (
        "AC 8: stopped, engine idling, gear N read for under 8 s (inside the "
        "hold) -> the band is readable and locked, '🔒 view only — stop to "
        "change'. Replaces settings-locked-idling: an idling car at rest is "
        "parked once the hold completes.",
        {"system-status": _systemInputs(_upChain()), "gear": _GEAR_NEUTRAL,
         "settings": _SETTINGS_STORED},
    ),
    "settings-locked-gear-unknown": (
        "AC 8: states/gear unavailable (link_down) -> locked, '🔒 view only — "
        "gear unknown': no driver action is sure to unlock it.",
        {"system-status": _systemInputs(_link(
            _layer("connecting"), _layer("connecting"), _layer("connecting"),
        )),
         "gear": {"available": False, "gear": None, "reason": gd.REASON_LINK_DOWN},
         "settings": _SETTINGS_STORED},
    ),
    "settings-parked-idling": (
        "AC 8: gear N, engine idling, held 8 s -> unlocked with the engine "
        "running (the hold is driven by the clock, not this file).",
        {"system-status": _systemInputs(_upChain()), "gear": _GEAR_NEUTRAL,
         "settings": _SETTINGS_STORED},
    ),
    "settings-locked-driving": (
        "AC 8: a drive recording in 3rd -> locked, 'stop to change'; the "
        "in-flight write (calibration On, sent while parked) answers with the "
        "recorded real 200 and still ends 'saved' on the locked glass.",
        {"system-status": _systemInputs(_upChain(), driveState="recording", driveId=212),
         "gear": {"available": True, "gear": 3, "reason": gd.REASON_ENGAGED},
         "settings": _SETTINGS_STORED,
         "settings-write": {"key": "pi.calibration.mode", "value": True}},
    ),
    "settings-write-rejected": (
        "AC 9: parked; ROTATE PAGES' write is refused -> the recorded real 400 "
        "from _handleSettingsWrite (an illegal value; the body carries the "
        "re-read stored 0) -> 'couldn't save' and the stepper snaps back to Off.",
        {"system-status": _systemInputs(_upChain()), "gear": _GEAR_NEUTRAL,
         "settings": _SETTINGS_STORED,
         "settings-write": {"key": "pi.display.carousel.autoRotateS", "value": -1}},
    ),
    "settings-lux-cross-rejected": (
        "US-895-b: parked; the band stub reads DIM-START 3 / FULL-BRIGHT 300, "
        "but luxMin 200 was stored after the page loaded, so FULL-BRIGHT − to "
        "200 reaches the seam -> the recorded real 400 (luxFull > luxMin; the "
        "body carries the re-read 300) -> 'couldn't save' and the end snaps "
        "back to 300 lux.",
        {"system-status": _systemInputs(_upChain()), "gear": _GEAR_NEUTRAL,
         "settings": {**_LUX_STORED, **_SETTINGS_STORED},
         "settings-config": _LUX_CONFIG,
         "settings-overlay": _LUX_OVERLAY,
         "settings-write": {"key": "pi.display.autoDim.luxFull", "value": 200}},
    ),
}


def _recordSettingsWrite(
    key: str, value: Any, config: dict[str, Any], overlay: dict[str, Any] | None
) -> dict[str, Any]:
    """POST one setting to a REAL StatesHttpServer and record {status, body}.

    Runs the shipped _handleSettingsWrite (token gate, overlay validator, the
    cross-key seam, the re-read) over a temp config holding ``config`` (and
    ``overlay`` as its config.local.json, when given), so the recorded body is
    the server's, byte for byte as JSON.
    """
    # Imported here: only the settings-* fixtures need a live server.
    import tempfile
    import threading
    import urllib.error
    import urllib.request

    from pi.splash.states_http_server import StatesHttpServer

    with tempfile.TemporaryDirectory() as tmp:
        configPath = os.path.join(tmp, "config.json")
        with open(configPath, "w", encoding="utf-8") as fh:
            json.dump(config, fh)
        if overlay is not None:
            with open(os.path.join(tmp, "config.local.json"), "w", encoding="utf-8") as fh:
                json.dump(overlay, fh)
        statesDir = os.path.join(tmp, "states")
        assetsDir = os.path.join(tmp, "assets")
        os.mkdir(statesDir)
        os.mkdir(assetsDir)
        server = StatesHttpServer(
            statesDir=statesDir, token=_SETTINGS_TOKEN, host="127.0.0.1", port=0,
            assetsDir=assetsDir, configPath=configPath,
        )
        thread = threading.Thread(target=server.serveForever, daemon=True)
        thread.start()
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{server.actualPort}/settings",
                data=json.dumps({"key": key, "value": value}).encode("utf-8"),
                method="POST",
            )
            request.add_header("Content-Type", "application/json")
            request.add_header("X-Splash-Token", _SETTINGS_TOKEN)
            try:
                with urllib.request.urlopen(request, timeout=5) as response:
                    status, raw = response.status, response.read()
            except urllib.error.HTTPError as err:
                status, raw = err.code, err.read()
        finally:
            server.shutdown()
            thread.join(timeout=5)
    return {"status": status, "body": json.loads(raw.decode("utf-8"))}


def _buildSettingsFixture(name: str) -> dict[str, Any]:
    description, inputs = SETTINGS_FIXTURES[name]
    gear = inputs["gear"]
    payloads: dict[str, Any] = {
        "system-status": buildSystemStatusState(**inputs["system-status"], captureHealth=None),
        "gear": buildGearState(
            GearReading(gear["available"], gear["gear"], gear["reason"]), nowIso=NOW
        ),
        "settings": {key: {"found": True, "value": v} for key, v in inputs["settings"].items()},
    }
    if "settings-write" in inputs:
        write = inputs["settings-write"]
        payloads["settings-write"] = _recordSettingsWrite(
            write["key"], write["value"],
            inputs.get("settings-config", _SETTINGS_CONFIG), inputs.get("settings-overlay"),
        )
    return {
        "description": description,
        "now": NOW,
        "zone": ZONE,
        "inputs": _jsonable(inputs),
        "payloads": payloads,
    }


# The documented exception: a generated payload with its verdict removed.
VERDICT_ABSENT = "verdict-absent"
_VERDICT_ABSENT_FROM = "all-ok-driving"
_VERDICT_ABSENT_DESCRIPTION = (
    "The all-ok-driving system-status with `verdict` popped (no builder "
    "publishes a payload without one) -> the verdict reads '--', never ALL OK."
)


def _captureHealth(inputs: dict[str, Any]) -> dict[str, Any]:
    """Compose capture-health exactly as makeCaptureHealthEmitter.emit does."""
    payload = buildCaptureHealthState(
        lastRowSecondsAgo=inputs["lastRowSecondsAgo"],
        freshnessReason=inputs["freshnessReason"],
        powerSource=inputs["powerSource"],
        stallSeconds=inputs["stallSeconds"],
        nowIso=NOW,
    )
    samples = inputs.get("feedSamples")
    if samples is not None:
        payload["feeds"] = buildCaptureFeedsState(
            feedSamples=samples,
            powerSource=inputs["powerSource"],
            stallSeconds=inputs["stallSeconds"],
        )
    return payload


def _jsonable(value: Any) -> Any:
    """Inputs as JSON stores them (tuples become lists)."""
    return json.loads(json.dumps(value))


def buildFixture(name: str) -> dict[str, Any]:
    """Build one fixture, payloads from the real builders."""
    if name == VERDICT_ABSENT:
        base = buildFixture(_VERDICT_ABSENT_FROM)
        fixture = copy.deepcopy(base)
        fixture["description"] = _VERDICT_ABSENT_DESCRIPTION
        fixture["payloads"]["system-status"].pop("verdict")
        return fixture
    if name in SETTINGS_FIXTURES:
        return _buildSettingsFixture(name)
    description, inputs = FIXTURES[name]
    payloads: dict[str, Any] = {}
    capture = None
    if "capture-health" in inputs:
        capture = _captureHealth(inputs["capture-health"])
    payloads["system-status"] = buildSystemStatusState(
        **inputs["system-status"], captureHealth=capture
    )
    if capture is not None:
        payloads["capture-health"] = capture
    if "battery-health" in inputs:
        payloads["battery-health"] = buildBatteryHealthState(**inputs["battery-health"])
    return {
        "description": description,
        "now": NOW,
        "zone": ZONE,
        "inputs": _jsonable(inputs),
        "payloads": payloads,
    }


def fixtureNames() -> list[str]:
    return [*FIXTURES, VERDICT_ABSENT, *SETTINGS_FIXTURES]


def render(fixture: dict[str, Any]) -> str:
    """The on-disk text of a fixture (2-space JSON, trailing newline)."""
    return json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    for name in fixtureNames():
        path = os.path.join(_HERE, f"{name}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(buildFixture(name)))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

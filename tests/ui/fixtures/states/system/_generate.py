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
# ================================================================================
################################################################################

"""Generate the US-894-b System page fixtures from the real builders."""

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

from pi.obdii.capture_health import (  # noqa: E402
    DEFAULT_STALL_SECONDS,
    buildCaptureFeedsState,
    buildCaptureHealthState,
)
from pi.splash.battery_health_emitter import (  # noqa: E402
    VERDICT_GOOD,
    buildBatteryHealthState,
)
from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

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


def _systemInputs(link: dict, *, driveState: str = "idle", driveId: int | None = None) -> dict:
    """A parked-at-home system-status input set; each fixture overrides the link."""
    return {
        "syncLastOkTs": "2026-10-22T22:55:12Z",
        "syncRows": 0,
        "syncPending": None,
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
    return [*FIXTURES, VERDICT_ABSENT]


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

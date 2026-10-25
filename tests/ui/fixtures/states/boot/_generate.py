################################################################################
# File Name: _generate.py
# Purpose/Description: US-869-g (spec specs/v030-boot-shutdown-design.md s1.3)
#   -- GENERATES the boot-checklist fixtures in this directory from the REAL
#   builders, with every input written here. Never hand-type a fixture: edit an
#   input below and re-run this script.
#
#   Each fixture is {description, now, inputs, payloads}; `payloads` is keyed by
#   state name ("capture-health", "system-status"), the two files the boot page
#   reads beside boot-state.
#
#   Composition, as the producers do it:
#     - capture-health = buildCaptureHealthState(...) plus, when feed samples
#       are given, payload["feeds"] = buildCaptureFeedsState(...) -- exactly as
#       makeCaptureHealthEmitter.emit composes them
#       (src/pi/obdii/capture_health.py).
#     - system-status = buildSystemStatusState(**inputs, captureHealth=<the
#       capture-health payload above>).
#
#   tests/ui/render_harness.runSplash serves harnessDefaultCaptureHealth() --
#   built HERE, through the same path -- when a test passes no captureHealth
#   (Atlas R4, 2026-10-25).
#
#   Usage: python tests/ui/fixtures/states/boot/_generate.py
#   (tests/ui/test_boot_checklist.py asserts every file on disk equals what
#   this script builds, so a stale fixture fails the suite.)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Ralph (Rex)  | Initial -- US-869-g boot-checklist fixtures.
# ================================================================================
################################################################################

"""Generate the US-869-g boot-checklist fixtures from the real builders."""

from __future__ import annotations

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
    FEED_REASON_READ_FAILED,
    FEED_REASON_SENSOR_ABSENT,
    REASON_NEVER_WRITTEN,
    buildCaptureFeedsState,
    buildCaptureHealthState,
)
from pi.splash.system_status_emitter import (  # noqa: E402
    LINK_CONNECTING,
    LINK_RETRYING,
    LINK_UP,
    buildSystemStatusState,
)

NOW = "2026-10-25T12:00:48Z"
_BOOT = "2026-10-25T12:00:00Z"
_FIRST_SAMPLE = "2026-10-25T12:00:44Z"

# A feed spec: "ready" (a first sample this process), None (silent), or a fault
# reason string (the source's own word, passed through untranslated).
_READY = "ready"


def _samples(spec: dict[str, str | None]) -> dict[str, tuple[str | None, float | None]]:
    """feedSamples for buildCaptureFeedsState: ready feeds sampled 0.5 s ago."""
    return {name: (_FIRST_SAMPLE, 0.5) for name, value in spec.items() if value == _READY}


def _faults(spec: dict[str, str | None]) -> dict[str, str]:
    return {name: value for name, value in spec.items() if value not in (None, _READY)}


def captureHealthPayload(spec: dict[str, str | None] | None) -> dict[str, Any]:
    """Compose capture-health exactly as makeCaptureHealthEmitter.emit does.

    ``spec`` None writes the pre-US-873 shape: no ``feeds`` block at all.
    """
    payload = buildCaptureHealthState(
        lastRowSecondsAgo=None,
        freshnessReason=REASON_NEVER_WRITTEN,
        powerSource="external",
        stallSeconds=DEFAULT_STALL_SECONDS,
        nowIso=NOW,
    )
    if spec is not None:
        payload["feeds"] = buildCaptureFeedsState(
            feedSamples=_samples(spec),
            powerSource="external",
            stallSeconds=DEFAULT_STALL_SECONDS,
            feedFaults=_faults(spec),
        )
    return payload


def _layer(state: str | None) -> dict[str, str | None]:
    if state is None:
        return {"state": None, "ts": None, "lastOkTs": None}
    return {"state": state, "ts": _BOOT, "lastOkTs": NOW if state == LINK_UP else None}


def _link(bt: str | None, adapter: str | None, ecu: str | None) -> dict[str, Any]:
    return {"bt": _layer(bt), "adapter": _layer(adapter), "ecu": _layer(ecu)}


def _systemInputs(link: dict[str, Any]) -> dict[str, Any]:
    """A cold key-on at home: nothing synced yet, parked, the link as given."""
    return {
        "syncLastOkTs": None,
        "syncStale": False,
        "powerSource": "external",
        "driveState": "idle",
        "driveId": None,
        "nowIso": NOW,
        "link": link,
    }


# The harness default (Atlas R4): IMU, LIGHT and UPS ready, OBD silent.
ALL_THREE_READY: dict[str, str | None] = {
    "obd": None,
    "light": _READY,
    "imu": _READY,
    "ups": _READY,
}

_ECU_SILENT = _link(LINK_UP, LINK_UP, LINK_CONNECTING)

FIXTURES: dict[str, tuple[str, dict[str, str | None] | None, dict[str, Any]]] = {
    "ecu-silent": (
        "IMU, LIGHT and UPS ready; BT and adapter up, ECU silent -> the hand-off "
        "happens and OBD reads 'waiting for ECU' (Atlas O5).",
        ALL_THREE_READY,
        _ECU_SILENT,
    ),
    "all-four-ready": (
        "Every feed ready and the whole chain up -> four 'ready' rows.",
        {"obd": _READY, "light": _READY, "imu": _READY, "ups": _READY},
        _link(LINK_UP, LINK_UP, LINK_UP),
    ),
    "ups-silent": (
        "UPS silent and not faulted -> 'waiting'; the splash holds on it.",
        {"obd": None, "light": _READY, "imu": _READY, "ups": None},
        _ECU_SILENT,
    ),
    "light-silent": (
        "LIGHT held null -> its row reads 'waiting'.",
        {"obd": None, "light": None, "imu": _READY, "ups": _READY},
        _ECU_SILENT,
    ),
    "imu-sensor-absent": (
        "IMU faulted sensor_absent -> 'sensor not found' amber; IMU is finished.",
        {"obd": None, "light": _READY, "imu": FEED_REASON_SENSOR_ABSENT, "ups": _READY},
        _ECU_SILENT,
    ),
    "ups-unreadable": (
        "UPS faulted read_failed (an I2C error) -> 'read failed' amber.",
        {"obd": None, "light": _READY, "imu": _READY, "ups": FEED_REASON_READ_FAILED},
        _ECU_SILENT,
    ),
    "imu-other-fault": (
        "IMU faulted with a reason outside the two codes -> 'fault' amber.",
        {"obd": None, "light": _READY, "imu": "bus_error", "ups": _READY},
        _ECU_SILENT,
    ),
    "feeds-missing": (
        "capture-health with no feeds block -> every row 'not read'.",
        None,
        _ECU_SILENT,
    ),
    "bt-connecting": (
        "BT not up yet -> OBD reads 'waiting for Bluetooth'.",
        ALL_THREE_READY,
        _link(LINK_CONNECTING, None, None),
    ),
    "adapter-retrying": (
        "BT up, adapter retrying -> OBD reads 'waiting for adapter'.",
        ALL_THREE_READY,
        _link(LINK_UP, LINK_RETRYING, None),
    ),
    "link-unread": (
        "No link layer read -> OBD reads plain 'waiting'.",
        ALL_THREE_READY,
        _link(None, None, None),
    ),
}


def harnessDefaultCaptureHealth() -> dict[str, Any]:
    """The capture-health runSplash serves when a test passes none (Atlas R4)."""
    return captureHealthPayload(ALL_THREE_READY)


def buildFixture(name: str) -> dict[str, Any]:
    """Build one fixture, payloads from the real builders."""
    description, feeds, link = FIXTURES[name]
    capture = captureHealthPayload(feeds)
    systemInputs = _systemInputs(link)
    return {
        "description": description,
        "now": NOW,
        "inputs": json.loads(json.dumps({"feeds": feeds, "system-status": systemInputs})),
        "payloads": {
            "capture-health": capture,
            "system-status": buildSystemStatusState(**systemInputs, captureHealth=capture),
        },
    }


def render(fixture: dict[str, Any]) -> str:
    """The on-disk text of a fixture (2-space JSON, trailing newline)."""
    return json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    for name in FIXTURES:
        path = os.path.join(_HERE, f"{name}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(buildFixture(name)))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

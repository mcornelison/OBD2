################################################################################
# File Name: test_display_units_round.py
# Purpose/Description: US-897-d (F-161; Atlas RULED 2026-10-20) -- the page's
#   one formatter, carousel.js displayUnits(value, unit, round), rounds TOWARD
#   the breach as its FINAL step, after unit conversion, at the rule's
#   decimals: 'floor' / 'ceil', guarded against binary-float artefacts; with no
#   round it is byte-identical to the pre-US-897-d output for every
#   DISPLAY_UNITS key. The ALERTS row passes entry.round, for a fresh value and
#   for a stale last.value alike.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-21    | Ralph (Rex)  | Initial -- US-897-d.
# ================================================================================
################################################################################

"""US-897-d tests: displayUnits' optional round, applied last."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import Any

import pytest

_NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped browser JS",
)

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROBE = os.path.join(_HERE, "carousel_probe.js")
_JS = os.path.join(_HERE, "..", "..", "src", "pi", "ui", "dashboard", "carousel.js")

# displayUnits(v, u) for every DISPLAY_UNITS key, FROZEN from carousel.js at
# f738405d (the commit before US-897-d) by `node -e` over the same values. The
# no-round path must stay byte-identical to it (VC: 'identical to before').
_VALUES = [0, 11.96, 15.04, 1.1, 12.05, 99.95, 112, -0.04, 1234.5, 0.05]
_BEFORE: dict[str, tuple[str, list[str]]] = {
    "C": ("°F", ["32", "54", "59", "34", "54", "212", "234", "32", "2254", "32"]),
    "F": ("°F", ["0", "12", "15", "1", "12", "100", "112", "-0", "1235", "0"]),
    "km/h": ("mph", ["0", "7", "9", "1", "7", "62", "70", "-0", "767", "0"]),
    "mph": ("mph", ["0", "12", "15", "1", "12", "100", "112", "-0", "1235", "0"]),
    "V": ("V", ["0.0", "12.0", "15.0", "1.1", "12.1", "100.0", "112.0", "-0.0", "1234.5", "0.1"]),
    "rpm": ("", ["0", "12", "15", "1", "12", "100", "112", "-0", "1235", "0"]),
    "%": ("%", ["0", "12", "15", "1", "12", "100", "112", "-0", "1235", "0"]),
    "deg": ("°", ["0", "12", "15", "1", "12", "100", "112", "-0", "1235", "0"]),
    "g/s": ("g/s", ["0.0", "12.0", "15.0", "1.1", "12.1", "100.0", "112.0", "-0.0", "1234.5", "0.1"]),
    "count": ("", ["0", "12", "15", "1", "12", "100", "112", "-0", "1235", "0"]),
}


def _map(fn: str, argLists: list[list[Any]]) -> list[Any]:
    """carousel.js `fn` over each argument list (node probe, --map)."""
    proc = subprocess.run(
        [_NODE or "node", _PROBE, "--map", fn],
        input=json.dumps(argLists), capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _shown(value: float, unit: str, round_: str | None) -> str:
    out = _map("displayUnits", [[value, unit, round_]])[0]
    return out["text"]


def test_theFrozenTableCoversEveryDisplayUnitsKey():
    """'every DISPLAY_UNITS key': the table above is the shipped key set."""
    with open(_JS, encoding="utf-8") as fh:
        source = fh.read()
    block = re.search(r"var DISPLAY_UNITS = \{(.*?)\n  \};", source, re.DOTALL)
    assert block is not None
    keys = set(re.findall(r'^\s+"?([^"\s:]+)"?: \{ unit:', block.group(1), re.MULTILINE))
    assert keys == set(_BEFORE)


@pytest.mark.parametrize("unit", sorted(_BEFORE))
def test_noRound_isByteIdenticalToBefore_forEveryKey(unit: str):
    """VC: displayUnits(v, u) -- absent AND null round -- is what it was."""
    symbol, texts = _BEFORE[unit]
    absent = _map("displayUnits", [[v, unit] for v in _VALUES])
    null = _map("displayUnits", [[v, unit, None] for v in _VALUES])
    expected = [{"text": t, "unit": symbol} for t in texts]
    assert absent == expected
    assert null == expected


def test_anUnknownDirection_isTheNoRoundPath():
    """Only 'floor' / 'ceil' round; anything else is toFixed, as before."""
    assert _map("displayUnits", [[11.96, "V", "up"], [11.96, "V", 1]]) == [
        {"text": "12.0", "unit": "V"}, {"text": "12.0", "unit": "V"},
    ]


def test_batteryLow_floorsTowardTheBreach():
    """VC: displayUnits(11.96, 'V', 'floor') -> '11.9' 'V'."""
    assert _map("displayUnits", [[11.96, "V", "floor"]]) == [{"text": "11.9", "unit": "V"}]


def test_batteryHigh_ceilsTowardTheBreach():
    """VC: displayUnits(15.04, 'V', 'ceil') -> '15.1' 'V'."""
    assert _map("displayUnits", [[15.04, "V", "ceil"]]) == [{"text": "15.1", "unit": "V"}]


def test_greenHoldValue_floorsWithTheEpisodesSide():
    """VC: the low episode's green hold at 12.46 shows '12.4'."""
    assert _shown(12.46, "V", "floor") == "12.4"


@pytest.mark.parametrize(
    ("value", "round_", "expected"),
    [(1.1, "ceil", "1.1"), (11.9, "ceil", "11.9"), (12.0, "floor", "12.0")],
)
def test_floatGuard_anExactTenthIsNeverMoved(value: float, round_: str, expected: str):
    """Atlas REVIEW 2026-10-20 rows: an exact tenth is never moved."""
    assert _shown(value, "V", round_) == expected


# MEASURED 2026-10-21 (node 24): every literal tenth 0.0..199.9 scales by 10 to
# an exact integer in JS -- 1.1 * 10 === 11 -- so the three rows above pass with
# or without the guard. A tenth that arrives as an arithmetic result does not:
# 0.1 + 0.2 is 0.30000000000000004. That row is what actually exercises it.
_FLOAT_TRAP = 0.1 + 0.2


def _bareNode(expr: str) -> str:
    proc = subprocess.run(
        [_NODE or "node", "-e", f"process.stdout.write(String({expr}))"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_floatGuard_negativeControl_theTrapIsReal():
    """Without the guard the trap row WOULD move: prove the float error exists
    (and that 1.1 is not such a row)."""
    assert repr(_FLOAT_TRAP) == "0.30000000000000004"
    assert _bareNode("Math.ceil((0.1 + 0.2) * 10) / 10") == "0.4"
    assert _bareNode("Math.ceil(1.1 * 10) / 10") == "1.1"


def test_floatGuard_holdsOnTheTrapRow():
    """With the guard: ceil(0.30000000000000004) -> '0.3', never '0.4'."""
    assert _shown(_FLOAT_TRAP, "V", "ceil") == "0.3"
    assert _shown(_FLOAT_TRAP, "V", "floor") == "0.3"


def test_roundIsAppliedAfterConvert():
    """The direction acts on the CONVERTED figure: 99.95 C is 211.91 F."""
    assert _shown(99.95, "C", "floor") == "211"
    assert _shown(99.95, "C", "ceil") == "212"


def _row(entry: dict[str, Any]) -> dict[str, Any]:
    return _map("warningRowView", [[entry, "2026-10-21T12:00:10Z"]])[0]


def _batteryEntry(**fields: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "engine:BATTERY_V:watch", "source": "engine", "key": "BATTERY_V",
        "tier": "watch", "title": "CHARGING FAULT", "sentence": "x", "directive": None,
        "value": 11.96, "unit": "V", "round": "floor", "last": None, "stale": False,
        "firstSeenTs": "2026-10-21T12:00:00Z", "lastSeenTs": "2026-10-21T12:00:00Z",
        "active": True, "acknowledged": False, "codeStatus": None,
    }
    entry.update(fields)
    return entry


def test_alertsRow_passesTheEntrysRound():
    """The story's example: value 11.96, round 'floor' -> '11.9 V'."""
    assert _row(_batteryEntry())["value"] == "11.9 V"
    assert _row(_batteryEntry(value=15.04, round="ceil"))["value"] == "15.1 V"


def test_alertsRow_aStaleLastValueKeepsTheDirection():
    """VC: a stale last.value is rounded with the same round."""
    row = _row(_batteryEntry(
        value=None, stale=True,
        last={"value": 11.96, "band": None, "ts": "2026-10-21T12:00:00Z"},
    ))
    assert row["value"] == "11.9 V"


def test_alertsRow_roundNull_isTodaysText():
    """A coolant entry's round is null: its value text is unchanged."""
    row = _row(_batteryEntry(
        id="engine:COOLANT_TEMP:stop", key="COOLANT_TEMP", unit="C", value=112, round=None,
    ))
    assert row["value"] == "234 °F"

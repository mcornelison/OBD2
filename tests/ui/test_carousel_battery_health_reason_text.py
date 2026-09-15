################################################################################
# File Name: test_carousel_battery_health_reason_text.py
# Purpose/Description: US-736 -- the Battery card's HEALTH tile says WHY the
#   verdict is unknown. US-632 made the producer publish one of SIX typed
#   reasons in `reasons.health`; the renderer had no table for them, so all six
#   reached the glass as the same em-dash. The live Pi published
#   `health_data_stale` on 2026-09-11 and the tile said nothing about it.
#   The six names are IMPORTED from battery_health_verdict.py rather than
#   re-typed here, so the renderer table is checked against the producer's own
#   vocabulary -- plural intact, no seventh constant.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-14
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-14    | Ralph (Rex)  | Initial -- US-736 battery-health reason text.
# ================================================================================
################################################################################

"""US-736: six published unknown-reasons render as six distinct strings."""

import json
import os
import re
import shutil
import subprocess

import pytest

from pi.power import battery_health_verdict
from pi.power.battery_health_verdict import UNKNOWN_REASONS

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.join(
    os.path.dirname(__file__), "..", "..",
    "src", "pi", "ui", "dashboard", "carousel.js",
)

_TS = "2026-09-11T12:00:00Z"
_LAST_CHECK = "2026-05-16T09:00:00Z"
_MIDDOT = "·"

needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, *args: object) -> object:
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _battery(**extra: object) -> dict:
    payload: dict = {
        "health": "unknown",
        "vcellV": 3.98,
        "soc": 95,
        "socCalibrated": False,
        "draining": False,
        "lastHealthCheckTs": _LAST_CHECK,
        "ts": _TS,
    }
    payload.update(extra)
    return payload


def _healthTile(**extra: object) -> dict:
    view = _view("batteryHealthView", _battery(**extra))
    return view["health"]


def _js() -> str:
    with open(_JS, encoding="utf-8") as fh:
        return fh.read()


def _tableKeys() -> set[str]:
    block = re.search(r"var BATTERY_HEALTH_REASON_TEXT = \{(.*?)\};", _js(), re.S)
    assert block, "BATTERY_HEALTH_REASON_TEXT is not declared in carousel.js"
    return set(re.findall(r"^\s*([a-z_]+)\s*:", block.group(1), re.M))


# ---------------------------------------------------------------------------
# VC1 -- each of the six reasons renders as its own operator-readable string.
# ---------------------------------------------------------------------------


@needsNode
@pytest.mark.parametrize("reason", UNKNOWN_REASONS)
def test_unknownVerdict_detailNamesThePublishedReason(reason):
    """
    Given: an unknown verdict carrying one of the six published reasons
    When: the Battery view is built
    Then: the HEALTH tile carries readable words for it (not the snake_case
          code) in front of the F-9 last-check line, which is kept whole.
    """
    tile = _healthTile(reasons={"health": reason})

    text = tile["reason"]
    assert isinstance(text, str) and text.strip(), tile
    assert "_" not in text, tile
    assert tile["detail"].startswith(text + " " + _MIDDOT + " "), tile
    assert tile["detail"].endswith("last health check · 2026-05-16 (118 days ago)"), tile
    assert tile["value"] == "—"
    assert tile["level"] == "unavailable"


@needsNode
def test_theSixReasons_renderAsSixDistinctStrings():
    """Today all six render identically. Six facts, six strings."""
    texts = {_healthTile(reasons={"health": r})["reason"] for r in UNKNOWN_REASONS}
    assert len(texts) == len(UNKNOWN_REASONS) == 6, texts


# ---------------------------------------------------------------------------
# VC2 -- the renderer table holds exactly the producer's six names.
# ---------------------------------------------------------------------------


def test_rendererTable_keysAreExactlyTheProducerVocabulary():
    """A predicate, not a count: the table's keys equal UNKNOWN_REASONS. A
    renamed, dropped, singularised or invented key fails here."""
    assert _tableKeys() == set(UNKNOWN_REASONS)


def test_everyReasonCode_isPresentInTheRenderer():
    js = _js()
    for reason in UNKNOWN_REASONS:
        assert reason in js, reason
    assert "no_qualifying_drain:" not in js  # the singular trap


def test_thereIsOnlyOneBatteryReasonTable():
    """Extend, never duplicate: one table carries the six names."""
    assert len(re.findall(r"\bno_qualifying_drains\s*:", _js())) == 1


# ---------------------------------------------------------------------------
# VC3 -- absent / unrecognised reasons get typed fallbacks, never a known string.
# ---------------------------------------------------------------------------


def _knownTexts() -> set[str]:
    return {_healthTile(reasons={"health": r})["reason"] for r in UNKNOWN_REASONS}


@needsNode
@pytest.mark.parametrize(
    "extra",
    [
        {},                              # no `reasons` map at all
        {"reasons": {}},                 # map present, health key missing
        {"reasons": None},
        {"reasons": {"health": ""}},
        {"reasons": {"health": 7}},      # wrong type
    ],
    ids=["noMap", "emptyMap", "nullMap", "emptyString", "nonString"],
)
def test_unknownWithNoUsableReason_rendersTypedFallback(extra):
    tile = _healthTile(**extra)
    assert tile["reason"] == "reason not reported", tile
    assert tile["reason"] not in _knownTexts()
    assert tile["detail"].startswith("reason not reported " + _MIDDOT + " "), tile


@needsNode
def test_unrecognisedReason_isNamedAndDistinctFromEveryKnownOne():
    tile = _healthTile(reasons={"health": "flux_capacitor"})
    assert tile["reason"] == "unrecognised reason (flux_capacitor)", tile
    assert tile["reason"] not in _knownTexts()
    assert tile["reason"] != "reason not reported"


@needsNode
def test_unrecognisedReasonThatLooksLikeAKeyInheritedFromObject_isNotAKnownText():
    tile = _healthTile(reasons={"health": "toString"})
    assert tile["reason"] == "unrecognised reason (toString)", tile


# ---------------------------------------------------------------------------
# A reason explains an ABSENCE -- a resolved verdict's tile is unchanged.
# ---------------------------------------------------------------------------


@needsNode
@pytest.mark.parametrize("verdict", ["good", "degraded", "replace"])
def test_resolvedVerdict_ignoresAStrayReason(verdict):
    tile = _healthTile(health=verdict, reasons={"health": "health_data_stale"})
    assert tile["reason"] is None, tile
    assert tile["detail"] == "last health check · 2026-05-16 (118 days ago)", tile


@needsNode
def test_upsUnavailable_keepsTheWholeCardNa():
    """The typed whole-card NA (US-429) is untouched by the health reason."""
    view = _view(
        "batteryHealthView",
        _battery(
            reasons={"health": "no_database"},
            source={"ups": {"available": False, "reason": "gauge unreadable"}},
        ),
    )
    assert view["unavailable"] is True
    assert view["reason"] == "gauge unreadable"


# ---------------------------------------------------------------------------
# VC4 -- no new reason constant was added on the producer side.
# ---------------------------------------------------------------------------


def test_producerStillDeclaresExactlySixReasonConstants():
    names = [n for n in dir(battery_health_verdict) if re.fullmatch(r"REASON_[A-Z_]+", n)]
    assert sorted(names) == [
        "REASON_CLOCK_UNREADABLE",
        "REASON_HEALTH_DATA_STALE",
        "REASON_LOG_UNREADABLE",
        "REASON_NO_DATABASE",
        "REASON_NO_QUALIFYING_DRAINS",
        "REASON_TOO_FEW_DRAINS",
    ]


# ---------------------------------------------------------------------------
# The DOM renderer paints the tile the view built (a correct view the renderer
# never paints renders nothing).
# ---------------------------------------------------------------------------


def test_renderBatteryHealthBody_paintsTheHealthTile():
    from tests.ui.render_harness import _fnBody

    body = _fnBody(_js(), "renderBatteryHealthBody")
    assert "appendTile(body, view.health)" in body

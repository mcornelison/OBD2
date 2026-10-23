################################################################################
# File Name: test_carousel_battery_health_reason_text.py
# Purpose/Description: US-736 -- the Battery card's HEALTH tile says WHY the
#   verdict is unknown. US-632 made the producer publish one of SIX typed
#   reasons in `reasons.health`; the renderer had no table for them, so all six
#   reached the glass as the same em-dash. The live Pi published
#   `health_data_stale` on 2026-09-11 and the tile said nothing about it.
#   (ARCH-065 retired that reason; the vocabulary is now the six below.)
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
# 2026-10-03    | Atlas (ARCH-065a) | T7: the ARCH-065 six (no_monthly_test /
#               |              | monthly_test_stale / too_few_syncs replace the
#               |              | three retired drain reasons); a resolved verdict
#               |              | puts its T-vs-J margin in front of the F-9 line.
# 2026-10-23    | Ralph (Rex)  | MOVED PIN (US-894-e): the Battery card retired;
#               |              | every rule re-pointed at the System page's UPS
#               |              | detail (upsDetailView: health.note = reason or
#               |              | margin, healthCheck = the F-9 line). The JS-to-
#               |              | Python reason parity guard stays.
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


# MOVED PIN (US-894-e): the HEALTH tile of the retired Battery card is now the
# UPS detail's health block. The system-status beside it only supplies the
# source + LAST STOP; nowMs null (the age is not under test here).
_STATUS = {"power": {"source": "external", "reasons": {}}, "ts": _TS}
_F9 = "last health check · 2026-05-16 (118 days ago)"


def _detail(**extra: object) -> dict:
    return _view("upsDetailView", _STATUS, _battery(**extra), None)


def _healthTile(**extra: object) -> dict:
    detail = _detail(**extra)
    health = dict(detail["health"])
    health["healthCheck"] = detail["healthCheck"]
    return health


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
    When: the UPS detail is built (MOVED PIN (US-894-e): was the Battery view)
    Then: the health note carries readable words for it (not the snake_case
          code), and the F-9 last-check line is kept whole beside it.
    """
    tile = _healthTile(reasons={"health": reason})

    text = tile["note"]
    assert isinstance(text, str) and text.strip(), tile
    assert "_" not in text, tile
    assert tile["healthCheck"] == _F9, tile
    # MOVED PIN (US-894-e): spec s4.6.1 -- unknown reads `--`, not an em dash.
    assert tile["value"] == "--"
    assert tile["level"] == "unavailable"


@needsNode
def test_theSixReasons_renderAsSixDistinctStrings():
    """Today all six render identically. Six facts, six strings."""
    texts = {_healthTile(reasons={"health": r})["note"] for r in UNKNOWN_REASONS}
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
    for retired in ("no_qualifying_drains", "too_few_drains", "health_data_stale"):
        assert retired + ":" not in js, retired  # ARCH-065 retired these


def test_thereIsOnlyOneBatteryReasonTable():
    """Extend, never duplicate: one table carries the six names."""
    assert len(re.findall(r"\bno_monthly_test\s*:", _js())) == 1


# ---------------------------------------------------------------------------
# VC3 -- absent / unrecognised reasons get typed fallbacks, never a known string.
# ---------------------------------------------------------------------------


def _knownTexts() -> set[str]:
    return {_healthTile(reasons={"health": r})["note"] for r in UNKNOWN_REASONS}


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
    # MOVED PIN (US-894-e): the reason is the health note; the F-9 line is its
    # own line (was one `reason · last health check` detail string).
    assert tile["note"] == "reason not reported", tile
    assert tile["note"] not in _knownTexts()
    assert tile["healthCheck"] == _F9, tile


@needsNode
def test_unrecognisedReason_isNamedAndDistinctFromEveryKnownOne():
    tile = _healthTile(reasons={"health": "flux_capacitor"})
    assert tile["note"] == "unrecognised reason (flux_capacitor)", tile
    assert tile["note"] not in _knownTexts()
    assert tile["note"] != "reason not reported"


@needsNode
def test_unrecognisedReasonThatLooksLikeAKeyInheritedFromObject_isNotAKnownText():
    tile = _healthTile(reasons={"health": "toString"})
    assert tile["note"] == "unrecognised reason (toString)", tile


# ---------------------------------------------------------------------------
# A reason explains an ABSENCE -- a resolved verdict's tile is unchanged.
# ---------------------------------------------------------------------------


@needsNode
@pytest.mark.parametrize("verdict", ["good", "degraded", "replace"])
def test_resolvedVerdict_ignoresAStrayReason(verdict):
    tile = _healthTile(health=verdict, reasons={"health": "too_few_syncs"})
    # MOVED PIN (US-894-e): no margin numbers -> no note; the F-9 line alone.
    assert tile["note"] is None, tile
    assert tile["healthCheck"] == _F9, tile


@needsNode
def test_upsUnavailable_keepsTheCellSectionNa():
    """The typed NA (US-429) is untouched by the health reason. MOVED PIN
    (US-894-e): the whole-card NA is now the UPS detail's cell section -- the
    cell reads `-- · <reason>` and no health line stands beside it."""
    detail = _detail(
        reasons={"health": "no_database"},
        source={"ups": {"available": False, "reason": "gauge unreadable"}},
    )
    assert detail["health"] is None
    assert detail["healthCheck"] is None
    assert detail["cell"] == "-- " + _MIDDOT + " gauge unreadable"


# ---------------------------------------------------------------------------
# VC4 -- no new reason constant was added on the producer side.
# ---------------------------------------------------------------------------


def test_producerStillDeclaresExactlySixReasonConstants():
    names = [n for n in dir(battery_health_verdict) if re.fullmatch(r"REASON_[A-Z_]+", n)]
    assert sorted(names) == [
        "REASON_CLOCK_UNREADABLE",
        "REASON_LOG_UNREADABLE",
        "REASON_MONTHLY_TEST_STALE",
        "REASON_NO_DATABASE",
        "REASON_NO_MONTHLY_TEST",
        "REASON_TOO_FEW_SYNCS",
    ]
    assert len(names) == 6


# ---------------------------------------------------------------------------
# ARCH-065: a resolved verdict says WHY it is what it is -- T against J -- in
# front of the F-9 line, never in place of it.
# ---------------------------------------------------------------------------


@needsNode
def test_resolvedVerdict_putsTheMarginInFrontOfTheF9Line():
    tile = _healthTile(health="good", timeToFloorS=18000, jobAvgS=300, provisional=True)
    # MOVED PIN (US-894-e): the margin is the health note, the F-9 line its own.
    assert tile["note"] == "300 min vs 300 s job (provisional)", tile
    assert tile["healthCheck"] == _F9, tile


@needsNode
def test_resolvedVerdict_calibratedMargin_carriesNoProvisionalTag():
    tile = _healthTile(health="degraded", timeToFloorS=600, jobAvgS=550, provisional=False)
    assert tile["note"] == "10 min vs 550 s job", tile  # MOVED PIN (US-894-e)


@needsNode
def test_resolvedVerdict_withoutNumbers_isTheF9LineAlone():
    tile = _healthTile(health="good")
    assert tile["note"] is None, tile  # MOVED PIN (US-894-e)
    assert tile["healthCheck"] == _F9, tile


@needsNode
def test_anUnknownVerdict_neverShowsAMargin_evenIfNumbersLinger():
    tile = _healthTile(reasons={"health": "too_few_syncs"}, timeToFloorS=18000, jobAvgS=300)
    # MOVED PIN (US-894-e): the note is the reason, never the margin.
    assert tile["note"] == "too few home syncs to judge", tile
    assert "min vs" not in tile["note"] and "min vs" not in tile["healthCheck"], tile


# ---------------------------------------------------------------------------
# The DOM renderer paints the note the view built (a correct view the renderer
# never paints renders nothing). MOVED PIN (US-894-e): renderBatteryHealthBody
# is gone with the card; the UPS detail renderer paints the health block.
# ---------------------------------------------------------------------------


def test_renderUpsDetail_paintsTheHealthVerdictAndItsNote():
    from tests.ui.render_harness import _fnBody

    body = _fnBody(_js(), "renderUpsDetail")
    assert "detail.health.value" in body
    assert "detail.health.note" in body
    assert "detail.healthCheck" in body

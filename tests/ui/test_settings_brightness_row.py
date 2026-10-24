################################################################################
# File Name: test_settings_brightness_row.py
# Purpose/Description: US-895-c (spec specs/v030-system-page-design.md s4.7,
#   Atlas S110 A5 / B12-B14, Iris I11) -- the Settings band's BRIGHTNESS row:
#   AUTO | FIXED nn %, writing pi.display.autoDim.overrideLevel through POST
#   /settings. AUTO writes null; FIXED steps in integer percent, 5 % apart,
#   from the EFFECTIVE minLevel (window.DISPLAY_AUTODIM, per request) to 100 %
#   and stores round(pct)/100. No literal floor in carousel.js (spec AC 9).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-10-23    | Rex (US-895-c) | Initial -- the BRIGHTNESS row.
# ================================================================================
################################################################################
"""US-895-c: Settings can fix the screen brightness, floored at minLevel."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import render_harness as rh  # noqa: E402
from test_settings_lock import (  # noqa: E402
    _BOOT,
    _HOLD_8S,
    _JS,
    _NODE,
    _NOW_MS,
    _OPEN_KEBAB,
    PANEL,
    _attrs,
    _fixture,
    _generator,
    _needsNode,
    _posts,
    _read,
    _routes,
    _text,
    _view,
)

from common.config import overlay  # noqa: E402
from pi.splash.states_http_server import StatesHttpServer  # noqa: E402

_KEY = "pi.display.autoDim.overrideLevel"
_FLOOR = "settings-floor-from-minlevel"
_APPLY = "applies on reload"
_TOKEN = "test-token-abcdefghijklmnopqrstuvwxyz123456"


def _spec() -> dict:
    (spec,) = [s for s in _view("settingsSpecs") if s["key"] == _KEY]
    return spec


def _settings(found: bool = True, value: Any = None) -> dict[str, Any]:
    """The band-state stub: the shipped rows plus BRIGHTNESS."""
    stub = dict(_fixture("settings-parked-idling")["payloads"]["settings"])
    stub[_KEY] = {"found": found, "value": value if found else None}
    return stub


def _carousel(tmp_path, settings: dict[str, Any]) -> str:
    """The SHIPPED carousel.js with the settings blob + a counted reload prepended."""
    prefix = [
        "globalThis.location = {reload: function () {"
        " document.body.setAttribute('data-reloads', 'yes'); }};",
        f"window.DISPLAY_SETTINGS = {json.dumps(settings)};",
    ]
    path = tmp_path / "carousel.js"
    path.write_text("\n".join(prefix) + "\n" + _read(_JS), encoding="utf-8")
    return str(path)


def _parked(tmp_path, settings: dict, autoDim: Any, extra: list[dict] | None = None,
            write: dict | None = None, locked: bool = False) -> dict[str, Any]:
    name = "settings-locked-driving" if locked else "settings-parked-idling"
    routes = _routes(_fixture(name))
    routes.pop("/settings", None)
    if write is not None:
        routes["/settings"] = write
    steps = _BOOT + ([] if locked else _HOLD_8S) + _OPEN_KEBAB + (extra or [])
    out = rh.runDashboard(
        routes=routes, steps=steps, carouselPath=_carousel(tmp_path, settings),
        viewport=PANEL, nowMs=_NOW_MS, autoDim=autoDim,
    )
    out["surface"] = rh.dashboardSurface(out["tree"], viewport=PANEL)
    return out


def _find(node: dict, cls: str) -> list[dict]:
    found: list[dict] = []

    def walk(n: dict) -> None:
        if cls in (n.get("attrs", {}).get("class") or "").split():
            found.append(n)
        for child in n.get("children", []):
            if "tag" in child:
                walk(child)

    walk(node)
    return found


def _row(surface) -> dict:
    rows = [p for p in surface.pathsByClass("set-row") if _attrs(p)["data-key"] == _KEY]
    assert len(rows) == 1
    return rows[0][-1]


def _segments(surface) -> dict[str, dict]:
    return {_text(b): b.get("attrs", {}) for b in _find(_row(surface), "set-btn")}


def _value(surface) -> str | None:
    shown = _find(_row(surface), "set-value")
    return _text(shown[0]) if shown else None


def _steps(surface) -> set[str]:
    row = _row(surface)
    return {k for k in ("minus", "plus") if _find(row, f"set-step-{k}")}


def _tag(surface) -> str:
    (tag,) = _find(_row(surface), "set-apply")
    return _text(tag)


def _node(js: str) -> Any:
    """Evaluate JS against the shipped module (for values JSON cannot carry)."""
    proc = subprocess.run(
        [_NODE, "-e", f"var c = require({json.dumps(os.path.abspath(_JS))});"
                      f"process.stdout.write(String({js}));"],
        capture_output=True, text=True, encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


# ---------------------------------------------------------------------------
# The spec row and the seam.
# ---------------------------------------------------------------------------


@_needsNode
def test_brightnessIsTheFirstDisplayRow_kindLevel_appliesOnReload():
    spec = _spec()
    assert (spec["label"], spec["section"], spec["kind"], spec["apply"]) == (
        "BRIGHTNESS", "DISPLAY", "level", "reload",
    )
    assert spec["applyNote"] == _APPLY
    assert _view("settingsSpecs")[0]["key"] == _KEY
    assert overlay.OVERRIDABLE_KEYS[0] == _KEY


@_needsNode
def test_theSegmentsAreAutoThenFixed():
    assert _view("settingsChoices", _spec()) == [
        {"value": "AUTO", "label": "AUTO"},
        {"value": "FIXED", "label": "FIXED"},
    ]


# ---------------------------------------------------------------------------
# The floor IS the effective minLevel (Atlas A5, spec AC 9).
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(("minLevel", "lowest"), [(0.60, 60), (0.75, 75)])
def test_theLowestFixedStep_isTheInjectedMinLevel(minLevel, lowest):
    """AC: DISPLAY_AUTODIM.minLevel 0.60 -> lowest FIXED step 60 %; 0.75 -> 75 %."""
    steps = _view("settingsLevelSteps", minLevel)
    assert steps[0] == lowest
    assert steps == list(range(lowest, 101, 5))


@_needsNode
def test_anOffGridMinLevel_isItselfTheLowestStep_thenTheNextMultipleOfFive():
    assert _view("settingsLevelSteps", 0.72) == [72, 75, 80, 85, 90, 95, 100]
    assert _view("settingsLevelSteps", 1.0) == [100]


@_needsNode
@pytest.mark.parametrize("minLevel", [None, "0.75", True, -0.1, 1.2, {}])
def test_anUnresolvableMinLevel_offersNoFixedSteps(minLevel):
    assert _view("settingsLevelSteps", minLevel) is None


def test_noLiteralFloorInCarousel():
    """Spec AC 9: the floor code holds no number of its own. The step and the
    100 % top are named constants; the floor arrives as the argument."""
    js = _read(_JS)
    for fn in ("settingsLevelSteps", "settingsLevelFirstFixed"):
        start = js.index(f"function {fn}(")
        body = js[start:js.index("\n  }\n", start)]
        code = re.sub(r"//[^\n]*", "", body.split("{", 1)[1])
        code = re.sub(r"\[\d+\]", "[i]", code)  # an index (steps[0]) is not a level
        assert not re.search(r"(?<![\w.])\d", code), (fn, code)


# ---------------------------------------------------------------------------
# The row view.
# ---------------------------------------------------------------------------


@_needsNode
def test_autoShowsOnlyForAKeyFoundAsNull():
    auto = _view("settingsRowView", _spec(), None, {"found": True, "minLevel": 0.75})
    unknown = _view("settingsRowView", _spec(), None, {"found": False, "minLevel": 0.75})
    assert (auto["on"], auto["display"], auto["known"], auto["showValue"]) == (
        "AUTO", "AUTO", True, False,
    )
    assert (unknown["on"], unknown["display"], unknown["known"]) == (None, "Unknown", False)
    assert unknown["showValue"] is True


@_needsNode
def test_fixedShowsItsPercent():
    row = _view("settingsRowView", _spec(), 0.8, {"found": True, "minLevel": 0.75})
    assert (row["on"], row["display"], row["pct"], row["fixedAllowed"]) == (
        "FIXED", "80 %", 80, True,
    )


@_needsNode
def test_floorUnknown_fixedDisabled_andTheStepperReadsUnknown():
    for value in (0.8, None):
        row = _view("settingsRowView", _spec(), value, {"found": True})
        assert row["fixedAllowed"] is False
        assert row["display"] == ("Unknown" if value is not None else "AUTO")
        assert row["showValue"] is True


@_needsNode
@pytest.mark.parametrize(
    ("stored", "direction", "nextPct"),
    [(0.8, 1, 85), (0.8, -1, 75), (0.75, -1, None), (1.0, 1, None), (0.82, 1, 85),
     (0.82, -1, 80)],
)
def test_theStepperMovesFivePercentWithinTheFloor(stored, direction, nextPct):
    view = _view("settingsRowView", _spec(), stored, {"found": True, "minLevel": 0.75})
    assert _view("settingsRowStepNext", _spec(), view, direction) == nextPct


@_needsNode
def test_aStepStoresRoundPctOverOneHundred():
    """Atlas B14."""
    assert _view("settingsLevelWrite", 80) == 0.8
    assert _view("settingsLevelWrite", 72) == 0.72


# ---------------------------------------------------------------------------
# AUTO -> FIXED first value (Iris I11).
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(
    ("applied", "minLevel", "first"),
    [(0.83, 0.75, 85), (0.77, 0.75, 75), (0.5, 0.75, 75), (0.5, 0.72, 72), (1.0, 0.75, 100),
     (None, 0.75, 100)],
)
def test_autoToFixed_startsAtTheAppliedLevel_roundedToFive_clamped(applied, minLevel, first):
    assert _view("settingsLevelFirstFixed", applied, minLevel) == first


@_needsNode
def test_theChoiceWrites_autoNull_fixedTheFirstValue_floorUnknownNothing():
    assert _view("settingsLevelChoiceWrite", "AUTO", 0.8, 0.75) is None
    assert _view("settingsLevelChoiceWrite", "FIXED", 0.83, 0.75) == 0.85
    assert _node('c.settingsLevelChoiceWrite("FIXED", 0.83, null)') == "undefined"
    assert _view("settingsWriteValue", _spec(), None) is None


# ---------------------------------------------------------------------------
# The band, rendered.
# ---------------------------------------------------------------------------


@_needsNode
def test_autoStored_autoPressed_stepperHidden(tmp_path):
    surface = _parked(tmp_path, _settings(value=None), {"minLevel": 0.75})["surface"]
    segments = _segments(surface)
    assert segments["AUTO"]["aria-pressed"] == "true"
    assert segments["FIXED"]["aria-pressed"] == "false"
    assert segments["FIXED"].get("disabled") is None
    assert _value(surface) is None and _steps(surface) == set()
    assert _tag(surface) == _APPLY


@_needsNode
def test_notFound_readsUnknown_nothingPressed(tmp_path):
    surface = _parked(tmp_path, _settings(found=False), {"minLevel": 0.75})["surface"]
    assert {s["aria-pressed"] for s in _segments(surface).values()} == {"false"}
    assert _value(surface) == "Unknown"


@_needsNode
def test_fixed80Saved_postsPoint8_repaintsTheReRead_andReloads(tmp_path):
    """validationCriteria 1 (the page half): AUTO -> FIXED while the screen
    applies 0.8 (the injected defaultLevel, no light feed) posts 0.8; the
    re-read 0.8 paints 80 %; the band reloads to apply it."""
    out = _parked(
        tmp_path, _settings(value=None), {"minLevel": 0.75, "defaultLevel": 0.8},
        extra=[{"clickNth": {"selector": ".set-btn", "index": 1}}, {"flush": 2},
               {"advanceMs": 1000, "flush": 1}],
        write={"ok": True, "key": _KEY, "value": 0.8},
    )
    (post,) = _posts(out)
    assert json.loads(post["body"]) == {"key": _KEY, "value": 0.8}
    surface = out["surface"]
    assert _segments(surface)["FIXED"]["aria-pressed"] == "true"
    assert _value(surface) == "80 %"
    assert _tag(surface) == f"{_APPLY} · saved"
    assert out["tree"]["attrs"].get("data-reloads") == "yes"


@_needsNode
def test_fixedStepper_minusAndPlusPostFivePercent(tmp_path):
    for index, selector, expected in ((0, ".set-step-minus", 0.75), (0, ".set-step-plus", 0.85)):
        out = _parked(
            tmp_path, _settings(value=0.8), {"minLevel": 0.75},
            extra=[{"clickNth": {"selector": selector, "index": index}}, {"flush": 2}],
            write={"ok": True, "key": _KEY, "value": expected},
        )
        (post,) = _posts(out)
        assert json.loads(post["body"]) == {"key": _KEY, "value": expected}
        assert _value(out["surface"]) == f"{round(expected * 100)} %"


@_needsNode
def test_tapAutoFromFixed_writesNull(tmp_path):
    out = _parked(
        tmp_path, _settings(value=0.9), {"minLevel": 0.75},
        extra=[{"clickNth": {"selector": ".set-btn", "index": 0}}, {"flush": 2}],
        write={"ok": True, "key": _KEY, "value": None},
    )
    (post,) = _posts(out)
    assert json.loads(post["body"]) == {"key": _KEY, "value": None}
    surface = out["surface"]
    assert _segments(surface)["AUTO"]["aria-pressed"] == "true"
    assert _value(surface) is None


@_needsNode
def test_tapTheActiveSegment_writesNothing(tmp_path):
    out = _parked(tmp_path, _settings(value=None), {"minLevel": 0.75},
                  extra=[{"clickNth": {"selector": ".set-btn", "index": 0}}, {"flush": 2}])
    assert _posts(out) == []


@_needsNode
@pytest.mark.parametrize(("minLevel", "lowest"), [(0.60, "60 %"), (0.75, "75 %")])
def test_atTheFloor_theMinusIsHidden(tmp_path, minLevel, lowest):
    surface = _parked(tmp_path, _settings(value=minLevel), {"minLevel": minLevel})["surface"]
    assert _value(surface) == lowest
    assert _steps(surface) == {"plus"}


@_needsNode
def test_lockedTheRowIsReadable_inert(tmp_path):
    """The BRIGHTNESS row inherits US-895-a's lock."""
    out = _parked(tmp_path, _settings(value=0.8), {"minLevel": 0.75}, locked=True,
                  extra=[{"clickNth": {"selector": ".set-btn", "index": 0}}, {"flush": 1}])
    surface = out["surface"]
    assert all(s.get("disabled") is not None for s in _segments(surface).values())
    assert _value(surface) == "80 %" and _steps(surface) == set()
    assert _posts(out) == []


# ---------------------------------------------------------------------------
# The fixture the acceptance names: settings-floor-from-minlevel.
# ---------------------------------------------------------------------------


def test_theFloorFixture_isTheGeneratorsOutput():
    gen = _generator()
    assert _FLOOR in gen.fixtureNames()
    assert _fixture(_FLOOR) == json.loads(gen.render(gen.buildFixture(_FLOOR)))


@_needsNode
def test_floorFixture_minLevel075_lowestStep75(tmp_path):
    fx = _fixture(_FLOOR)["payloads"]
    assert fx["display-autodim"]["minLevel"] == 0.75
    surface = _parked(tmp_path, fx["settings"], fx["display-autodim"])["surface"]
    assert _value(surface) == "75 %"
    assert _steps(surface) == {"plus"}
    assert _segments(surface)["FIXED"]["aria-pressed"] == "true"


@_needsNode
def test_floorFixture_minLevelUnresolvable_fixedDisabled_unknown(tmp_path):
    fx = _fixture(_FLOOR)["payloads"]
    assert "minLevel" not in fx["display-autodim-unresolvable"]
    out = _parked(tmp_path, fx["settings"], fx["display-autodim-unresolvable"],
                  extra=[{"clickNth": {"selector": ".set-btn", "index": 1}}, {"flush": 1}])
    surface = out["surface"]
    assert _segments(surface)["FIXED"].get("disabled") is not None
    assert _value(surface) == "Unknown"
    assert _steps(surface) == set()
    assert _posts(out) == []


# ---------------------------------------------------------------------------
# validationCriteria 1, end to end: POST 0.8 -> re-read 0.8 -> after the
# reload the applier reads {0.8, 'fixed'} from the per-request blob.
# ---------------------------------------------------------------------------


def _serve(tmp_path):
    config = {"pi": {"display": {"autoDim": {"minLevel": 0.75, "overrideLevel": None}}}}
    configPath = tmp_path / "config.json"
    configPath.write_text(json.dumps(config), encoding="utf-8")
    statesDir, assetsDir = tmp_path / "states", tmp_path / "assets"
    statesDir.mkdir()
    assetsDir.mkdir()
    (assetsDir / "index.html").write_text(
        "<script>window.DISPLAY_SETTINGS = \"__DISPLAY_SETTINGS__\";</script>",
        encoding="utf-8",
    )
    server = StatesHttpServer(statesDir=str(statesDir), token=_TOKEN, host="127.0.0.1",
                              port=0, assetsDir=str(assetsDir), configPath=str(configPath))
    thread = threading.Thread(target=server.serveForever, daemon=True)
    thread.start()
    return server, thread


@_needsNode
def test_fixed80_postReReadAndApplierAfterReload(tmp_path):
    server, thread = _serve(tmp_path)
    try:
        base = f"http://127.0.0.1:{server.actualPort}"
        request = urllib.request.Request(
            f"{base}/settings", data=json.dumps({"key": _KEY, "value": 0.8}).encode("utf-8"),
            method="POST",
        )
        request.add_header("Content-Type", "application/json")
        request.add_header("X-Splash-Token", _TOKEN)
        with urllib.request.urlopen(request, timeout=5) as response:
            body = json.loads(response.read().decode("utf-8"))
        html = urllib.request.urlopen(f"{base}/", timeout=5).read().decode("utf-8")
    finally:
        server.shutdown()
        thread.join(timeout=5)

    assert body == {"ok": True, "key": _KEY, "value": 0.8}
    marker = "window.DISPLAY_SETTINGS = "
    start = html.index(marker) + len(marker)
    blob = json.loads(html[start:html.index(";", start)])
    assert blob[_KEY] == {"found": True, "value": 0.8}
    # The light sensor unplugged (no states/light) does not undo it.
    assert _view("appliedBrightness", None, {"minLevel": 0.75}, _NOW_MS, False, blob) == {
        "level": 0.8, "basis": "fixed",
    }

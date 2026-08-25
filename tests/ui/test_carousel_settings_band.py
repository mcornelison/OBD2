################################################################################
# File Name: test_carousel_settings_band.py
# Purpose/Description: US-532 fixture tests for the F-126 Settings band -- Iris's
#   CIO-chosen Option B: the 5 Slice-1 settings render as a band at the TOP of the
#   EXISTING US-403 setup-menu overlay, above the service controls, NOT as a 5th
#   carousel card. Covers the pure view/logic exports through the node probe plus
#   the source-inspection wiring guards (a pure function that nothing calls
#   renders nothing).
#
#   The load-bearing test here is the NON-ECHO one. Iris §3: on tap the control
#   confirms from the server's RE-READ, or snaps back to the real stored value --
#   never an optimistic "on". US-531 learned that a happy path cannot prove a
#   re-read (there the stored value equals the requested one); the same trap
#   exists on the display side, so the fixtures below force the requested and
#   returned values to DISAGREE.
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-07
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-07    | Ralph (Rex)  | Initial -- US-532 F-126 settings band.
# ================================================================================
################################################################################

"""US-532 fixture tests for the F-126 settings band (via node)."""

import json
import os
import shutil
import subprocess

import pytest

from common.config import overlay

# Reuse the canonical CSS/file parsers rather than re-implementing them.
from tests.ui.test_dashboard_stop_tier_safety import _read, _ruleBlock

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")
_HTML = os.path.join(_DIST, "dashboard.html")

_AUTO_ROTATE = "pi.display.carousel.autoRotateS"
_POWER_MODE = "pi.power.mode"

_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, *args: object) -> dict:
    """Evaluate one carousel.js export against N fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _spec(key: str) -> dict:
    """The one spec row for a key, straight from the display's own table."""
    match = [s for s in _view("settingsSpecs") if s["key"] == key]
    assert match, f"no settings spec for {key}"
    return match[0]


def _row(key: str, value: object) -> dict:
    return _view("settingsRowView", _spec(key), value)


def _fnBody(js: str, signature: str) -> str:
    """Slice one function's source out of carousel.js by its opening line."""
    start = js.index(signature)
    return js[start : js.index("\n    }", start)]


# ---------------------------------------------------------------------------
# AC2 -- the band renders the 5 Slice-1 settings, keyed by the overlay's SSOT.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_settingsSpecs_coversTheOverlayAllowListExactly():
    """The cross-language SSOT guard.

    The display MUST carry its own copy of the key list (it is a different
    runtime -- it cannot import the Python allow-list), so the risk is not
    duplication but DRIFT. This pins the copy to overlay.OVERRIDABLE_KEYS in
    BOTH directions: a Slice-2 key added server-side but not surfaced fails
    here, and so does a display row for a key the write gate would 403.
    """
    assert [s["key"] for s in _view("settingsSpecs")] == list(overlay.OVERRIDABLE_KEYS)


@_NODE_TESTS
def test_settingsSpecs_everyRowCarriesALabelAndApplyNote():
    for spec in _view("settingsSpecs"):
        assert spec["label"].strip(), spec
        assert spec["applyNote"].strip(), spec


@_NODE_TESTS
@pytest.mark.parametrize("key", overlay.OVERRIDABLE_KEYS)
def test_settingsRowView_rendersEveryOverridableKey(key):
    """Parametrized over the SSOT so a new overridable key cannot land unrendered."""
    assert _row(key, None)["key"] == key


# ---------------------------------------------------------------------------
# GAP 3a -- ONE key, one truth: auto-rotate is derived from autoRotateS, and no
# separate `autoRotate` bool exists anywhere on the display side either.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_autoRotate_isDerivedFromSeconds_notASeparateBool():
    assert _row(_AUTO_ROTATE, 8)["on"] is True
    assert _row(_AUTO_ROTATE, 20)["on"] is True
    assert _row(_AUTO_ROTATE, 0)["on"] is False


@_NODE_TESTS
def test_autoRotate_writesZeroOff_andTheShippedIntervalOn():
    """US-530 GAP 3a: off writes 0, on writes the shipped interval -- so the two
    directions round-trip through one key."""
    spec = _spec(_AUTO_ROTATE)
    assert _view("settingsWriteValue", spec, False) == 0
    on = _view("settingsWriteValue", spec, True)
    assert on > 0
    # And what it writes must read back as ON, or the toggle would not round-trip.
    assert _row(_AUTO_ROTATE, on)["on"] is True


@_NODE_TESTS
def test_autoRotate_unknownWhenValueIsNotANumber():
    """Honest-instrument: an unresolvable setting reads Unknown, never Off. "Off"
    is a claim about stored state; the server said it could not resolve one."""
    for junk in (None, "8", True, {}):
        row = _row(_AUTO_ROTATE, junk)
        assert row["known"] is False, junk
        assert row["on"] is None, junk


def test_noSeparateAutoRotateBoolWasMinted():
    """GAP 3a as a scope fence -- one key, one truth, on the display side too."""
    js = _read(_JS)
    assert "autoRotate:" not in js
    assert '"pi.display.carousel.autoRotate"' not in js


# ---------------------------------------------------------------------------
# Power mode -- a 3-state selector, and `unknown` is a legal STORED value that
# must stay distinguishable from "we could not read one".
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_powerMode_isAThreeStateSelector():
    assert _spec(_POWER_MODE)["kind"] == "mode"
    assert _view("settingsModeChoices") == list(overlay.POWER_MODES)


@_NODE_TESTS
@pytest.mark.parametrize("mode", overlay.POWER_MODES)
def test_powerMode_rendersEveryLegalMode(mode):
    row = _row(_POWER_MODE, mode)
    assert row["known"] is True
    assert row["mode"] == mode


@_NODE_TESTS
def test_powerMode_storedUnknownIsNotTheSameAsUnreadable():
    """`unknown` stored = the system honestly has no deployment context; a null
    from the server = we could not read the setting at all. Both display as
    UNKNOWN, but only the first is a value the operator can be told is SET --
    collapsing them would make an unreadable config look like a deliberate
    choice."""
    assert _row(_POWER_MODE, "unknown")["known"] is True
    assert _row(_POWER_MODE, None)["known"] is False


@_NODE_TESTS
def test_powerMode_illegalValueIsUnknown_neverAConfidentWrongMode():
    for junk in ("moon-base", "CAR", 1, True, {}):
        assert _row(_POWER_MODE, junk)["known"] is False, junk


# ---------------------------------------------------------------------------
# Booleans.
# ---------------------------------------------------------------------------


@_NODE_TESTS
@pytest.mark.parametrize(
    "key",
    ["pi.calibration.mode", "pi.analysis.triggerAfterDrive"],
)
def test_boolRows_renderBothStatesAndFailToUnknown(key):
    assert _row(key, True)["on"] is True
    assert _row(key, False)["on"] is False
    for junk in (None, "true", 1, 0):
        row = _row(key, junk)
        assert row["known"] is False, (key, junk)
        assert row["on"] is None, (key, junk)


@_NODE_TESTS
@pytest.mark.parametrize(
    "key",
    ["pi.calibration.mode", "pi.analysis.triggerAfterDrive"],
)
def test_boolRows_writeRealBooleans(key):
    """The overlay's validator takes bool only -- a truthy string would 400."""
    spec = _spec(key)
    assert _view("settingsWriteValue", spec, True) is True
    assert _view("settingsWriteValue", spec, False) is False


# ---------------------------------------------------------------------------
# AC3 -- the honest save flow. THE LOAD-BEARING SECTION.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_saveResult_takesTheServersValue_notTheRequestedOne():
    """*** THE NON-ECHO TEST. ***

    US-531's endpoint answers with a RE-READ, and this is the display half of
    that contract: the row must repaint from res.value. The fixture forces the
    two apart -- the operator asked for `wall`, the write succeeded, but the
    resolver could not resolve the override onto a non-dict branch, so the honest
    stored value is null. An optimistic UI paints WALL here; an honest one paints
    Unknown. A success fixture where res.value == the request cannot tell the two
    implementations apart, which is exactly how US-531 nearly shipped the bug.
    """
    result = _view("settingsSaveResult", {"ok": True, "key": _POWER_MODE, "value": None})
    assert result["value"] is None
    assert _row(_POWER_MODE, result["value"])["known"] is False


@_NODE_TESTS
def test_saveResult_failedWrite_snapsBackToTheRealStoredValue():
    """Iris §3: a rejected write snaps back to the REAL value + 'couldn't save'.
    Operator asked for `wall`; the server reports the write failed and `car` is
    what is actually stored -- so the row must read CAR, not WALL."""
    result = _view("settingsSaveResult", {"ok": False, "key": _POWER_MODE, "value": "car"})
    assert result["ok"] is False
    assert result["value"] == "car"
    assert _row(_POWER_MODE, result["value"])["mode"] == "car"


@_NODE_TESTS
def test_saveResult_unauthorizedOrCrashed_isNotASuccess():
    """A 401 body carries no `value` at all. The row must not read that as a
    stored value, and must never report `saved`."""
    for res in ({"error": "unauthorized"}, {}, None, {"ok": "true"}):
        result = _view("settingsSaveResult", res)
        assert result["ok"] is False, res
        assert result["value"] is None, res


@_NODE_TESTS
def test_saveResult_noteDistinguishesSavedFromFailed():
    saved = _view("settingsSaveResult", {"ok": True, "key": _POWER_MODE, "value": "wall"})
    failed = _view("settingsSaveResult", {"ok": False, "key": _POWER_MODE, "value": "car"})
    assert saved["note"] != failed["note"]
    assert "sav" in saved["note"].lower()


@_NODE_TESTS
def test_savePending_isNotAnOptimisticSuccess():
    """The brief `saving…` must not paint the requested value -- that IS the
    optimistic success Iris ruled out, just with a nicer label."""
    pending = _view("settingsPendingNote")
    assert pending.strip()
    assert "sav" in pending.lower()
    assert pending != _view("settingsSaveResult", {"ok": True, "value": 0})["note"]


# ---------------------------------------------------------------------------
# AC3 -- apply-state labels are honest. A label is a CLAIM about a consumer.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_noRowOverPromisesAnApplyItsConsumerCannotHonour():
    """US-532 shipped the CONSERVATIVE label on every row ("applies on restart")
    and told US-533 to relax each one as it wired + PROVED that consumer. That
    handshake completed 2026-08-08, so the two assertions US-532 left here --
    "every row says restart" and "auto-rotate says restart" -- were deliberately
    retired: they now assert the OPPOSITE of the truth. Their replacements live
    in test_carousel_settings_apply.py, pinned per key to the consumer each one
    earned.

    What survives here is the invariant that outlives any particular wiring: a
    row may only claim an apply-state the band DECLARES, and only "live" is an
    over-promise risk -- so the count of rows claiming it is pinned, and a new
    row cannot quietly join them.
    """
    specs = _view("settingsSpecs")
    declared = set(_view("settingsApplyStates"))
    for spec in specs:
        assert spec["apply"] in declared, spec["key"]
    live = [s["key"] for s in specs if s["apply"] == "live"]
    assert live == ["pi.power.mode"], (
        "a row claims 'applies now' -- that is a claim about a consumer that "
        "re-reads on every cycle; wire and prove it, or label it honestly"
    )


@_NODE_TESTS
def test_applyNoteIsDerivedFromApplyState_notWrittenPerRow():
    """One mapping, so a future `apply` flip cannot leave a stale note behind."""
    notes = {s["apply"]: s["applyNote"] for s in _view("settingsSpecs")}
    for spec in _view("settingsSpecs"):
        assert spec["applyNote"] == notes[spec["apply"]]


# ---------------------------------------------------------------------------
# AC1/AC4 wiring -- the pure functions are inert on their own. A story that adds
# settingsRowView and never calls it renders an empty band and passes everything
# above.
# ---------------------------------------------------------------------------


def test_bandIsBuiltWhenTheMenuOpens():
    """Rendered on open, not once at boot: a save made in a previous open (or by
    another surface) must not leave a stale value behind the ⋮.

    Sliced on openMenu's OWN 6-space closing brace rather than through the shared
    `_fnBody` (which anchors at 4) -- a loose slice runs on into buildList/
    doAction and would find a `buildSettings()` that openMenu never calls.
    """
    js = _read(_JS)
    start = js.index("function openMenu() {")
    assert "buildSettings()" in js[start : js.index("\n      }", start)]


def test_bandRendersThroughOneRenderPath_openAndSaveAlike():
    """One rendering path is what makes the honest flow structural rather than
    remembered: if the save handler painted the row itself, it could paint the
    REQUESTED value while the open path paints the STORED one, and the UI would
    then disagree with itself across a page reload.

    So the row is painted by exactly ONE closure -- built once per row, called
    for the initial paint and handed to the save handler for the repaint.
    """
    js = _read(_JS)
    build = js[js.index("function buildSettings()") : js.index("if (menuBtn) {")]
    assert build.count("settingsRowView(") == 1, "more than one paint path for a row"
    assert "postSetting(spec, choice.value, render" in build, "save does not reuse the paint path"
    post = js[js.index("function postSetting(") : js.index("function buildSettings()")]
    assert "render(out.value" in post, "save repaints from something other than the re-read"


def test_savePostsToTheTokenGatedSettingsRoute():
    """US-531 is the only write path -- the display must not invent another."""
    js = _read(_JS)
    body = js[js.index("function postSetting(") : js.index("function buildSettings()")]
    assert 'fetch("/settings"' in body
    assert '"X-Splash-Token"' in body
    assert '"POST"' in body


def test_saveSendsTheSpecKeyVerbatim():
    """The injected key IS the allow-list key. Prettifying it on the way out
    would 403 every save."""
    body = _read(_JS)[
        _read(_JS).index("function postSetting(") : _read(_JS).index("function buildSettings()")
    ]
    assert "key: key" in body or "key: spec.key" in body


def test_saveRendersFromSettingsSaveResult_notFromTheRequest():
    """The wiring half of the non-echo contract: the response must flow through
    settingsSaveResult before it reaches the row."""
    js = _read(_JS)
    body = js[js.index("function postSetting(") : js.index("function buildSettings()")]
    assert "settingsSaveResult(" in body


def test_settingsBandReadsTheInjectedEffectiveValues():
    """The band renders what the server resolved, not a display-side default."""
    js = _read(_JS)
    assert "global.DISPLAY_SETTINGS" in js


def test_noGetSettingsEndpointWasInvented():
    """US-531 ruling: a read route would be a SECOND source for a fact the
    injected config already carries, and the two could disagree."""
    js = _read(_JS)
    assert 'fetch("/settings")' not in js
    assert "/settings?" not in js


# ---------------------------------------------------------------------------
# AC1 -- placement: a band INSIDE the US-403 overlay, above the service rows.
# ---------------------------------------------------------------------------


def test_settingsBandLivesInsideTheSetupMenuOverlay():
    html = _read(_HTML)
    menu = html[html.index('id="setup-menu"') : html.index('id="confirm-modal"')]
    assert 'id="settings-list"' in menu


def test_settingsBandSitsAboveTheServiceControls():
    """Iris §4 / AC5: safe persistent prefs on top, destructive service + Exit
    below -- so a mis-tap while scrolling for a toggle cannot land on Stop."""
    html = _read(_HTML)
    assert html.index('id="settings-list"') < html.index('id="svc-list"')
    assert html.index('id="svc-list"') < html.index('id="menu-exit"')


def test_settingsPlaceholderIsQuoted_soFilePreviewStaysValidJs():
    """Same trick as __DISPLAY_CAROUSEL__: un-substituted it is a string, which
    the display ignores in favour of rendering every row unknown."""
    html = _read(_HTML)
    assert 'window.DISPLAY_SETTINGS = "__DISPLAY_SETTINGS__";' in html


def test_persistenceIsStatedToTheOperator():
    """Iris §3: the operator has to trust that a toggle sticks across a deploy."""
    html = _read(_HTML)
    menu = html[html.index('id="setup-menu"') : html.index('id="confirm-modal"')]
    assert "survives" in menu.lower()


# ---------------------------------------------------------------------------
# AC4 scope fence -- the destructive half of the overlay is untouched.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_serviceRowsKeepTheirConfirmsAndPowerwatchRule():
    """Adding a band above them must not disturb the F-6/F-7 guarantees."""
    assert _view("requiresConfirm", "stop") is True
    guard = [
        i for i in _view("serviceMenuItems") if i["unit"] == "eclipse-powerwatch.service"
    ]
    assert guard and guard[0]["canStop"] is False


def test_settingsTogglesDoNotRouteThroughTheConfirmModal():
    """Iris §4: the new toggles are non-destructive and must NOT confirm --
    borrowing the service confirm would train the operator to dismiss it."""
    js = _read(_JS)
    body = js[js.index("function postSetting(") : js.index("if (menuBtn) {")]
    assert "askConfirm(" not in body


# ---------------------------------------------------------------------------
# AC4 -- F-124 design system: tokens, not literals.
# ---------------------------------------------------------------------------


def test_settingsRowStylesUseTokens_notHardcodedColours():
    css = _read(_CSS)
    for selector in (".set-row", ".set-name", ".set-btn"):
        block = _ruleBlock(css, selector)
        assert block, f"{selector} has no rule"
        assert "#" not in block, f"{selector} carries a literal colour"


def test_settingsControlsMeetTheTouchTarget():
    """480x320 in a car: a control below --tap-min is not tappable in practice."""
    assert "var(--tap-min)" in _ruleBlock(_read(_CSS), ".set-btn")


def test_activeSettingIsNotSignalledByColourAlone():
    """The 3-state mode selector has to read at a glance in daylight -- the
    selected state carries a border/weight change, not just a hue."""
    block = _ruleBlock(_read(_CSS), '.set-btn[aria-pressed="true"]')
    assert block
    assert "border" in block or "font-weight" in block

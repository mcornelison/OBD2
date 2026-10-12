################################################################################
# File Name: test_carousel_settings_apply.py
# Purpose/Description: US-533 (F-126) tests for the APPLY half of the settings
#   band -- the part US-532 deliberately left conservative. US-532 shipped every
#   row labelled "applies on restart" because an apply-state is a CLAIM ABOUT A
#   CONSUMER and no consumer was wired yet; US-533 wires them and each label must
#   now become the TRUE one, no tighter and no looser:
#
#     * autoRotateS       -> "reload"          (B1: per-request injection; the UI
#                                               reloads itself, NO unit restart --
#                                               the restart is polkit-denied)
#     * calibration.mode  -> "capture-restart" (read into a constructor at start)
#     * triggerAfterDrive -> "capture-restart" (same)
#
#   B2 (CIO 2026-08-07): pi.alerts.audioAlerts is DROPPED -- it had no consumer
#   anywhere in src/ and no restart could ever have made it do anything, so the
#   row is deleted rather than shipped as a permanent silent no-op.
#
#   The load-bearing tests here are the two that can catch a LIE rather than a
#   typo: the apply-state map pinned to the Python allow-list in both directions,
#   and the reload wiring (a "applies on reload" label with no reload is exactly
#   the silent no-op the band exists to prevent).
#   Skipped when node is not on PATH (a node-less CI box).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-08    | Ralph (Rex)  | Initial -- US-533 apply semantics + B2 drop.
# ================================================================================
################################################################################

"""US-533 tests for the settings band's apply semantics (via node)."""

import json
import os
import shutil
import subprocess

import pytest

from common.config import overlay
from tests.ui.test_dashboard_stop_tier_safety import _read

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard"
)
_JS = os.path.join(_DIST, "carousel.js")

_AUTO_ROTATE = "pi.display.carousel.autoRotateS"
_CALIBRATION = "pi.calibration.mode"
_TRIGGER_AFTER_DRIVE = "pi.analysis.triggerAfterDrive"
_AUDIO_ALERTS = "pi.alerts.audioAlerts"

# The apply-state each key EARNED in this story, with the consumer that proves
# it. This is the Python side of a cross-language pin: the display cannot import
# it, so the risk is drift, and this map is what fails when a consumer changes
# and its label does not (US-532's key-list guard, applied to apply-states).
_EXPECTED_APPLY = {
    # B1: states_http_server._injectHtml resolves pi.display.carousel per
    # request, so the value lands on the next page load -- which the UI triggers
    # itself. NOT "live": the running carousel keeps its current period until the
    # reload actually happens.
    _AUTO_ROTATE: "reload",
    # Read once into a constructor at orchestrator start (calibration/manager.py,
    # obdii/drive/detector.py) -- honest only as "restart the capture service".
    _CALIBRATION: "capture-restart",
    _TRIGGER_AFTER_DRIVE: "capture-restart",
}

_NODE_TESTS = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _view(fn: str, *args: object) -> object:
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _specs() -> list:
    return _view("settingsSpecs")


def _spec(key: str) -> dict:
    match = [s for s in _specs() if s["key"] == key]
    assert match, f"no settings spec for {key}"
    return match[0]


def _postSettingBody() -> str:
    js = _read(_JS)
    return js[js.index("function postSetting(") : js.index("function buildSettings()")]


# ---------------------------------------------------------------------------
# B2 -- audioAlerts is gone, everywhere, from ONE deletion.
# ---------------------------------------------------------------------------


def test_audioAlerts_isNoLongerOverridable():
    """CIO 2026-08-07: the key has ZERO consumers in src/ -- no AlertManager
    field, no audio playback code at all -- so no restart could ever make the row
    do anything. A permanently dead control is the silent no-op with extra steps.
    Future audio work is US-538.
    """
    assert _AUDIO_ALERTS not in overlay.OVERRIDABLE_KEYS


def test_theAllowListIsExactlyTheFourSlice1Settings():
    """Pinned as a SET, so this fails on an accidental re-add as loudly as on a
    drop. US-668 removed pi.power.mode, so F-126 now ships THREE settings -- the
    set comparison is what makes that removal have to be stated here rather than
    slipping through."""
    assert set(overlay.OVERRIDABLE_KEYS) == set(_EXPECTED_APPLY)


@_NODE_TESTS
def test_audioAlertsRowIsGoneFromTheBand():
    """The band derives from the allow-list, so the deletion must propagate with
    no display edit of its own -- that was the point of deriving it."""
    assert _AUDIO_ALERTS not in [s["key"] for s in _specs()]


def test_audioAlertsWriteIsRefusedByTheGate():
    """Defense in depth: a stale kiosk page still holding the old row must not
    be able to write a key nothing reads."""
    ok, _ = overlay.validateOverlayValue(_AUDIO_ALERTS, True)
    assert ok is False


def test_droppingTheKeyDidNotDropTheOtherBooleans():
    """The over-tight-gate failure mode (US-537's lesson): deleting one entry
    from a table is exactly the edit that takes a neighbour with it."""
    for key in (_CALIBRATION, _TRIGGER_AFTER_DRIVE):
        assert overlay.validateOverlayValue(key, True) == (True, True)


# ---------------------------------------------------------------------------
# Apply-states -- the claim each row now makes about its consumer.
# ---------------------------------------------------------------------------


@_NODE_TESTS
@pytest.mark.parametrize("key", overlay.OVERRIDABLE_KEYS)
def test_everyRowCarriesTheApplyStateItsConsumerEarned(key):
    """Parametrized over the SSOT so a Slice-2 key cannot land with an
    unclassified (or copy-pasted) apply-state."""
    assert _spec(key)["apply"] == _EXPECTED_APPLY[key]


@_NODE_TESTS
def test_autoRotate_saysReload_notRestart_andNotLive():
    """Both directions of the honesty bound, in one place.

    NOT "restart": the eclipse-states-http bounce is polkit-denied (BL-030 B1),
    so a restart label would send the operator to an action they cannot take.
    NOT "live": the running carousel keeps its current period until the page
    actually reloads.
    """
    spec = _spec(_AUTO_ROTATE)
    assert spec["apply"] == "reload"
    note = spec["applyNote"].lower()
    assert "reload" in note
    assert "restart" not in note


# US-668 deleted test_powerMode_saysLive_becauseTheEmitterReReads. It asserted
# the power-mode row is labelled "applies now" because the emitter re-reads it
# each cycle. The row is gone with the setting, and NOTHING else claims live --
# which test_noRowOverPromisesAnApplyItsConsumerCannotHonour now pins as empty.


@_NODE_TESTS
@pytest.mark.parametrize("key", [_CALIBRATION, _TRIGGER_AFTER_DRIVE])
def test_constructorReadSettings_nameWhichRestart(key):
    """US-532's label was "applies on restart" -- true but useless: the operator
    could not tell WHICH unit to restart, and the one they would reach for
    (states-http, the only one the band talks to) is the wrong one."""
    note = _spec(key)["applyNote"].lower()
    assert "restart" in note
    assert "capture" in note


@_NODE_TESTS
def test_noRowStillCarriesTheUS532PlaceholderLabel():
    """US-532 shipped a deliberate under-promise on every row and told US-533 to
    relax each one as it PROVED the consumer. A row still reading the bare
    placeholder means a consumer was never wired."""
    assert [s for s in _specs() if s["apply"] == "restart"] == []


@_NODE_TESTS
def test_applyNoteIsStillDerived_notWrittenPerRow():
    """Re-proven after the flip: the note must come from ONE mapping, or a row
    can carry a stale note contradicting its own apply-state."""
    notes = {s["apply"]: s["applyNote"] for s in _specs()}
    for spec in _specs():
        assert spec["applyNote"] == notes[spec["apply"]]
        assert spec["applyNote"].strip()


@_NODE_TESTS
def test_noDeadApplyStatesAreLeftInTheMapping():
    """A mapping entry no row uses is a label nobody has verified against a
    consumer -- and the next story will reach for it as if it had been."""
    used = {s["apply"] for s in _specs()}
    declared = set(_view("settingsApplyStates"))
    assert declared == used


# ---------------------------------------------------------------------------
# The reload -- an "applies on reload" label with no reload is a silent no-op.
# ---------------------------------------------------------------------------


@_NODE_TESTS
def test_reloadIsNeededOnlyAfterASuccessfulReloadApplySave():
    saved = {"ok": True, "key": _AUTO_ROTATE, "value": 0}
    assert _view("settingsReloadNeeded", _spec(_AUTO_ROTATE), saved) is True


@_NODE_TESTS
def test_aFailedSaveDoesNotReloadAwayTheErrorMessage():
    """Reloading after a REJECTED write would wipe the "couldn't save" note off
    the screen and repaint the unchanged value -- which the operator would read
    as success. The failure must stay visible."""
    for res in ({"ok": False, "value": 8}, {"ok": False}, None):
        assert _view("settingsReloadNeeded", _spec(_AUTO_ROTATE), res) is False


@_NODE_TESTS
@pytest.mark.parametrize("key", [_CALIBRATION, _TRIGGER_AFTER_DRIVE])
def test_nonReloadRowsDoNotReloadThePage(key):
    """A reload the operator did not ask for is disruptive -- it closes the menu
    and restarts every poll. Only the row that NEEDS one gets one."""
    saved = {"ok": True, "key": key, "value": True}
    assert _view("settingsReloadNeeded", _spec(key), saved) is False


@_NODE_TESTS
def test_reloadDecisionUsesTheSaveResult_notTheRawResponse():
    """Same non-echo discipline as the repaint: the decision to reload must be
    downstream of settingsSaveResult, so a body that merely LOOKS successful
    (ok missing, or truthy-but-not-true) cannot trigger one."""
    for res in ({"ok": "yes", "value": 0}, {"value": 0}, {"ok": 1}):
        assert _view("settingsReloadNeeded", _spec(_AUTO_ROTATE), res) is False


def test_theSaveHandlerActuallyTriggersTheReload():
    """The wiring half. `settingsReloadNeeded` returning true changes nothing on
    its own -- a pure function nothing calls reloads no pages, and the row would
    then promise an apply that never happens.
    """
    body = _postSettingBody()
    assert "settingsReloadNeeded(" in body, "reload decision is never consulted"
    assert "location.reload()" in body, "nothing ever reloads the page"


def test_theReloadHappensAfterTheRepaint_notInsteadOfIt():
    """Order matters: the row repaints from the server's re-read FIRST, so the
    operator sees the real stored value even if the reload is slow or blocked
    (a kiosk with reloads suppressed must still show the truth)."""
    body = _postSettingBody()
    assert body.index("render(out.value") < body.index("settingsReloadNeeded(")


def test_onlyTheReloadApplyPathCanReload():
    """Scope fence on a disruptive action: exactly one reload call site, guarded
    by the decision function."""
    assert _read(_JS).count("location.reload()") == 1

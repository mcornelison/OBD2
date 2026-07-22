################################################################################
# File Name: test_carousel_letterbox_scale.py
# Purpose/Description: US-482 tests for the carousel's full-bleed LETTERBOX
#   scaling. The 480x320 UI is authored in a fixed #stage design box and
#   uniformly scaled (centered, black bars on the aspect mismatch) to fill the
#   real 1080p panel instead of rendering in a corner. Two layers are covered
#   on the bench: (1) the pure computeStageScale() math via the node probe, and
#   (2) static wiring assertions on the shipped dist assets (viewport meta, the
#   #screen/#stage wrapper, the CSS transform, and the JS resize handler). The
#   Iris AC-6 "scales up on the REAL 1080p Pi" check is a PI-RUNTIME gate (it
#   validates at deploy, like the US-480-a/US-481 render VCs).
#   Skipped when node is not on PATH (a node-less CI box) for the probe tests.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-22
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-22    | Ralph (Rex)  | Initial -- US-482 full-bleed letterbox scaling.
# ================================================================================
################################################################################

"""US-482 tests for the carousel full-bleed letterbox scaling."""

import json
import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_DIST = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "specs",
    "UI",
    "dist",
    "dashboard-pi",
)
_HTML = os.path.join(_DIST, "dashboard.html")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _scale(*args: object) -> float:
    """Evaluate computeStageScale against a viewport fixture via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, "computeStageScale", *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# computeStageScale -- the pure uniform-fit math (largest scale fitting BOTH
# axes). This is the only value the JS resize handler feeds to `--scale`.
# ---------------------------------------------------------------------------

nodeless = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- computeStageScale fixture tests need node",
)


@nodeless
def test_computeStageScale_1080p_isHeightBound():
    """On a 1920x1080 panel the HEIGHT binds (1080/320=3.375 < 1920/480=4.0):
    the 480x320 box grows 3.375x, leaving clean black bars left+right."""
    assert _scale(1920, 1080) == 3.375


@nodeless
def test_computeStageScale_exactDesignBox_isUnity():
    """A viewport that is exactly the 480x320 design box -> scale 1.0 (no-op)."""
    assert _scale(480, 320) == 1.0


@nodeless
def test_computeStageScale_widthBound_takesTheSmallerRatio():
    """A tall viewport (480x640): width binds (480/480=1.0 < 640/320=2.0) ->
    1.0, so the box never overflows the narrow axis."""
    assert _scale(480, 640) == 1.0


@nodeless
def test_computeStageScale_heightBound_takesTheSmallerRatio():
    """A wide viewport (1920x320): height binds (320/320=1.0 < 1920/480=4.0)."""
    assert _scale(1920, 320) == 1.0


@nodeless
def test_computeStageScale_degenerateViewport_fallsBackToOne():
    """A transient 0x0 (or negative) layout pass must never collapse the UI to
    nothing -- it falls back to scale 1.0."""
    assert _scale(0, 0) == 1.0
    assert _scale(-5, 100) == 1.0


# ---------------------------------------------------------------------------
# Static wiring -- the shipped dist assets carry the letterbox plumbing. These
# run without node (they are the deploy-truth the PI-RUNTIME AC-6 rests on).
# ---------------------------------------------------------------------------


def test_html_viewport_isDeviceWidth_notHardcoded480():
    """AC step 1: the viewport meta is the real panel (device-width), NOT the
    old hard-coded 480x320."""
    html = _read(_HTML)
    assert 'content="width=device-width, initial-scale=1' in html
    assert "width=480" not in html
    assert "height=320" not in html


def test_html_wrapsUiInScreenAndStage_beforeTheTopbar():
    """AC step 2: the whole UI is wrapped in #screen > #stage, and the wrapper
    opens BEFORE the topbar (so every card renders inside the scaled box)."""
    html = _read(_HTML)
    assert 'id="screen"' in html
    assert 'id="stage"' in html
    assert html.index('id="screen"') < html.index('id="stage"') < html.index('id="topbar"')


def test_css_stage_isFixedDesignBoxScaledByVar():
    """AC step 3: #stage is the exact 480x320 box, scaled by the JS-set --scale
    var, from its center."""
    css = _read(_CSS)
    stage = css[css.index("#stage {"):]
    assert "width: 480px;" in stage
    assert "height: 320px;" in stage
    assert "transform: scale(var(--scale, 1));" in stage
    assert "transform-origin: center center;" in stage


def test_css_screen_isBlackFullViewportFlexCenter():
    """AC step 4: #screen is the full-viewport black frame that centers #stage,
    so the letterbox strip reads as bezel."""
    css = _read(_CSS)
    screen = css[css.index("#screen {"):css.index("#stage {")]
    assert "position: fixed; inset: 0;" in screen
    assert "background: var(--bg);" in screen  # black
    assert "align-items: center; justify-content: center;" in screen


def test_js_resizeHandler_setsScaleVar():
    """AC step 3 (JS half): a resize handler recomputes --scale from the live
    viewport -- the safe path per spec (no fluid reflow)."""
    js = _read(_JS)
    assert 'window.addEventListener("resize", applyStageScale)' in js
    assert 'stage.style.setProperty("--scale"' in js
    assert "computeStageScale(window.innerWidth, window.innerHeight)" in js

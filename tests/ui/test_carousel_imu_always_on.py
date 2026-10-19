################################################################################
# File Name: test_carousel_imu_always_on.py
# Purpose/Description: US-541 (F-127) tests -- Atlas's three UI change requests.
#   (1) IMU-ALWAYS-ON. The live IMU instrument becomes the PERMANENT home face.
#       US-508 let `parked` win outright, so the one instrument that is Pi-local
#       and always-live was hidden exactly when the operator is sitting still
#       looking at it. The face decision now reads the MOTION FEED ONLY -- the
#       idle face survives solely as the honest fallback for a dead feed, and it
#       always names the reason (US-508 suppressed the reason when parked; under
#       the new rule "parked" is no longer why the fallback ever fires).
#   (2) The carousel order (Home . Alerts . System Status . ...) -- landed with
#       the US-540-b 6-card re-lay; this story VERIFIES it rather than re-doing it.
#   (3) auto-rotate OFF. Verified in two halves on purpose: config.json's
#       DECLARATION (true, green) and the consumer MECHANISM (broken -- the
#       resolver discards 0; see the xfail below and BL-031).
#   The parked live face is where the honest-availability pattern stops being
#   theoretical: OBD-dependent bits (gear) and unsourced ones (altitude) render
#   typed-NA/greyed, while a TRUE 0.0 g renders as a measured zero. Absence and
#   measured-zero looking alike is the one defect that would make US-542's
#   idle-face retirement dishonest, so both directions are pinned.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Ralph (Rex)  | Initial -- US-541 IMU-always-on + order + rotate.
# 2026-10-19    | Ralph (Rex)  | US-892-b -- MOVED PIN: the Home card's two faces
#                               retired (the Motion card replaced them), so the
#                               homeFace / liveCardView / renderHome cases of (1)
#                               go with them; the order pin reads Motion, and the
#                               stripper's negative control reads motionView.
# ================================================================================
################################################################################

"""US-541 tests: the live IMU instrument is the permanent home face."""

import json
import os
import re
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
_DIST = os.path.join(_ROOT, "src", "pi", "ui", "dashboard")
_HTML = os.path.join(_DIST, "dashboard.html")
_JS = os.path.join(_DIST, "carousel.js")
_CONFIG = os.path.join(_ROOT, "config.json")

# US-536 disposition B (CIO): auto-rotate OFF is the durable freeze fix.
_AUTO_ROTATE_OFF = 0

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against fixtures via the node probe."""
    cmd = [_NODE, _PROBE, fn] + [json.dumps(a) for a in args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _codeOnly(src: str) -> str:
    """Drop comment lines so an absence assertion cannot fire on the prose that
    DOCUMENTS the removal (the US-507 lesson). Line-based, not string-aware --
    adequate here because every body it is used on is comment-and-code only,
    and `test_codeOnly_stillSeesRealCode` is the negative control that proves
    it has not eaten the text the pins hunt for."""
    keep = []
    for line in src.splitlines():
        bare = line.strip()
        if bare.startswith("//") or bare.startswith("*") or bare.startswith("/*"):
            continue
        keep.append(line)
    return "\n".join(keep)


# ---------------------------------------------------------------------------
# 1. IMU-ALWAYS-ON: the face decision reads the motion feed, nothing else (AC-1)
# ---------------------------------------------------------------------------


def test_codeOnly_stillSeesRealCode():
    """
    Given: the comment stripper the absence pins above depend on
    When: it runs over the shipped JS
    Then: real code survives. Over-stripping is the dangerous direction -- it
          deletes the very text an absence assertion hunts for, so the pin
          passes VACUOUSLY over a file that still carries the defect.
    """
    stripped = _codeOnly(_read(_JS))
    # MOVED PIN (US-892-b): homeFace retired with the Home card.
    assert "function motionView(" in stripped
    assert "function carouselIdle(" in stripped
    assert "// US-541" not in stripped


# ---------------------------------------------------------------------------
# 2. The parked live face must be an instrument, not a fabrication (AC-1)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 3. AC-2 -- the carousel order (landed with US-540-b; VERIFIED here)
# ---------------------------------------------------------------------------


def test_html_alertsIsTheSecondCard():
    """
    Given: US-541 AC-2 asks for Home . Alerts . System Status . ...
    When: the shipped markup is read in order
    Then: the first two slots are Home and Alerts.

          Landed with the US-540-b re-lay (the 6-card set had to be authored in
          one pass), so this story verifies rather than re-does it. Asserted as
          an ORDERED prefix: a set-or-count assertion goes green on a carousel
          that opens on Light.
    """
    cards = re.findall(r'<section class="card"[^>]*aria-label="([^"]+)"',
                       _read(_HTML), re.S)
    # MOVED PIN (US-888-a): the Driving card is the new index 0 (the landing
    # card, R5), so the US-541 order Home . Alerts . System Status now follows it.
    # MOVED PIN (US-889-b): the Engine card sits between Driving and Home (E-2).
    # MOVED PIN (US-890-a): the Fuel card sits between Engine and Home (E-2).
    # MOVED PIN (US-896-a): the NAV card sits between Driving and Engine (E-2).
    # MOVED PIN (US-892-b): the Motion card replaces the Home card in its slot.
    assert cards[:7] == [
        "Driving", "Navigation", "Engine", "Fuel", "Motion", "Alerts", "System Status"
    ]


# ---------------------------------------------------------------------------
# 4. AC-3 -- auto-rotate OFF. The DECLARATION is true; the MECHANISM is not.
# ---------------------------------------------------------------------------


def test_configJson_declaresAutoRotateOff():
    """
    Given: US-536 disposition B -- the CIO rejected --disable-gpu BECAUSE
           auto-rotate-off was the durable freeze fix
    When: the shipped config is read
    Then: pi.display.carousel.autoRotateS is 0.

          Half of AC-3, and only half: this pins what the config file SAYS.
          A test asserting a declaration cannot witness the consumer -- see the
          xfail below, which is the same fact asserted where it actually acts.
    """
    cfg = json.loads(_read(_CONFIG))
    carousel = cfg["pi"]["display"]["carousel"]
    assert carousel["autoRotateS"] == _AUTO_ROTATE_OFF


def test_shouldAutoAdvance_aZeroPeriodNeverAdvances():
    """
    Given: the auto-advance predicate
    When: it is driven with the OFF value and a long-elapsed clock
    Then: it refuses to advance.

          The downstream half is already correct, which is what makes the
          resolver defect a one-line fix rather than a redesign: `0` already
          means OFF everywhere it is consumed. Only the resolver disagrees.
    """
    assert _view("shouldAutoAdvance", False, 60_000, _AUTO_ROTATE_OFF) is False
    assert _view("rotateProgress", 60_000, _AUTO_ROTATE_OFF) == 0


def test_resolveCarouselConfig_honoursTheShippedOffValue():
    """
    Given: the dashboard is served the config's `autoRotateS: 0`
    When: the injected config is resolved against the grounded defaults
    Then: the resolved period is 0 -- auto-rotate is OFF on the panel.

          THE MECHANISM half of AC-3. This shipped as a strict xfail while the
          defect was open (BL-031 / I-us536): `0` meant "broken, ignore me" to
          the US-506 resolver and "off, obey me" to US-536 and to the US-533
          operator toggle, which writes exactly the value the resolver dropped.
          Every layer reported success; only the consumer quietly disagreed.

          US-541-a (Atlas Option-1, CIO-ratified 2026-08-11) relaxed the guard
          FOR THIS KEY ONLY, so the assertion below now stands on its own and
          the marker is gone -- which is the whole reason it was written as the
          DESIRED behaviour rather than pinned to the broken value. The
          per-key-ness of that relaxation is pinned next door, in
          test_carousel_nav_model.py's resolver section.
    """
    resolved = _view("resolveCarouselConfig", {"autoRotateS": _AUTO_ROTATE_OFF})
    assert resolved["autoRotateS"] == _AUTO_ROTATE_OFF

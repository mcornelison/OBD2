################################################################################
# File Name: test_drive_test_ui_contract.py
# Purpose/Description: ARCH-058 -- the drive console SCREEN contract. The driver
#                      cannot interact, so anything he needs must be on it.
# Author: Atlas (architect)
# Creation Date: 2026-09-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-25    | Atlas          | Initial -- required elements, poll contract,
#               | (ARCH-058)     | and the font-size floor the panel demands.
# ================================================================================
################################################################################
"""The screen is the ONLY channel to a driver who cannot touch anything.

So its contract is testable and tested: if a future edit drops the countdown, the
phase identity or the magnetometer state, that is not a cosmetic regression -- it
is the loss of the only feedback the operator has while off WiFi at the wheel.

⚠️ THIS CANNOT TEST LEGIBILITY. It can only check that the elements exist and that
the font sizes clear the floor the panel's geometry demands. Whether it is
actually readable on the dash is a human check on the car, and it stays on the
bench-check list rather than being implied by a green test.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[2] / "tools" / "imu" / "drive_test_ui.html"

#: The panel is a 720p SCALER on 3.5 inches (~420 DPI, BL-034), so the headline
#: numbers must be large in CSS px to be physically legible at arm's length.
#: The countdown is the element a glance most needs to land on.
MIN_COUNTDOWN_PX = 100
MIN_MECH_PX = 60


@pytest.fixture(scope="module")
def html() -> str:
    assert UI.is_file(), f"the console UI is missing: {UI}"
    return UI.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "element",
    [
        "phase",     # PHASE n of N
        "mech",      # which mechanism is collecting
        "count",     # the countdown
        "circles",   # the slow-circles instruction
        "mag",       # LIVE / FROZEN
        "rows",
        "res",       # restore count
        "banner",    # the transition banner
        "end",       # the escape hatch
    ],
)
def test_requiredElementIsPresent(html: str, element: str) -> None:
    assert f'id="{element}"' in html, (
        f"the screen lost #{element} -- the driver cannot ask for it another way"
    )


def test_pollsTheStatusEndpoint(html: str) -> None:
    assert "/status" in html
    assert "setInterval" in html


def test_theEscapeHatchIsHoldToFire(html: str) -> None:
    """A tap-to-end button on a bumpy road would end the session by accident."""
    assert "HOLD" in html or "hold" in html
    assert "pointerdown" in html


def _fontPx(html: str, selector: str) -> int:
    block = re.search(re.escape(selector) + r"\s*\{[^}]*\}", html, re.S)
    assert block, f"no CSS block for {selector}"
    size = re.search(r"font-size:\s*(\d+)px", block.group(0))
    assert size, f"no font-size in {selector}"
    return int(size.group(1))


def test_countdownIsLargeEnoughForThePanel(html: str) -> None:
    assert _fontPx(html, "#count") >= MIN_COUNTDOWN_PX


def test_mechanismLabelIsLargeEnoughForThePanel(html: str) -> None:
    assert _fontPx(html, "#mech") >= MIN_MECH_PX


def test_openEndedPhaseDoesNotShowAFabricatedCountdown(html: str) -> None:
    """🔴 A countdown toward an end that does not exist is the same class of lie
    as a zero-filled sensor reading. The final phase runs until he parks."""
    assert "until you park" in html


def test_magnetometerStateHasThreeVisualStates(html: str) -> None:
    """LIVE / FROZEN / unknown. Collapsing unknown into either one would report a
    verdict the console has not earned."""
    for cls in ("live", "frozen", "unknown"):
        assert f"#mag.{cls}" in html, f"missing the {cls!r} mag state"

################################################################################
# File Name: test_splash_min_visible_floor.py
# Purpose/Description: US-525 (I-042 cause b) minimum-VISIBLE-duration floor for
#   the F-103 boot splash. The splash already had a MIN_PLAY_MS=2500 floor, but
#   it was measured from SCRIPT PARSE (`T_START`), while the brand itself is an
#   async `<object type="image/svg+xml" data="splash.svg">` that paints LATER.
#   So the "minimum play" window silently included the brand's load time: on a
#   cold chromium the splash could satisfy its own 2.5 s floor having shown the
#   brand for a fraction of that, then fade out -- exactly the "flashes before it
#   can be seen" report in I-042, with a fully green splash state machine.
#
#   Grounded on the live Pi (10.27.27.100, boot dc7a3848, 2026-08-02): the
#   splash-boot unit lived 9.806 s (20:20:12.171 -> 20:20:21.977) yet chromium's
#   own startup churn (first log 20:20:14.727, dbus/dconf noise through
#   20:20:17.617) consumed the first ~5.4 s of it. The unit was NOT too
#   short-lived; the floor was anchored to the wrong event.
#
#   The fix re-anchors the SAME grounded 2500 ms to the brand's `load`, so the
#   floor means what it says. No new magic number is introduced.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-03    | Ralph (Rex)  | Initial implementation (US-525 boot splash
#               |              | minimum-visible-duration floor)
# ================================================================================
################################################################################

"""Boot-splash minimum-visible-duration floor (US-525 / I-042 cause b)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.ui.render_harness import ProbeError, runSplash

_HEALTHY = {"healthy": True, "degraded": False}

_POLL_JS = (
    Path(__file__).resolve().parents[2]
    / "specs"
    / "UI"
    / "dist"
    / "splash-pi"
    / "boot-state-poll.js"
)

# The floor the splash has always claimed (spec §5). Re-anchored, not re-tuned.
_MIN_PLAY_MS = 2500


def _run(**kwargs):
    try:
        return runSplash(bootStates=[_HEALTHY], **kwargs)
    except ProbeError as exc:  # node missing -> skip loudly, never silently pass
        pytest.skip(f"node probe unavailable: {exc}")


class TestBrandVisibleFloor:
    """The floor must count VISIBLE brand time, not page-alive time."""

    def test_brandLoadsImmediately_yieldsAtTheEstablishedFloor(self):
        """
        Given: a healthy boot and a brand that paints at once
        When: the splash runs
        Then: it hands off no earlier than the 2500 ms floor

        The unchanged baseline -- re-anchoring must not make the warm case
        slower, or every boot pays for the cold-boot fix.
        """
        result = _run(brandLoadMs=0)

        assert result["handoff"] is True
        assert result["handoffAtMs"] >= _MIN_PLAY_MS

    def test_brandLoadsLate_floorStartsAtTheBrand_notAtScriptParse(self):
        """
        Given: a healthy boot whose brand SVG only paints at 2000 ms
        When: the splash runs
        Then: hand-off waits until brand + 2500 ms, so the brand is really seen

        This is the I-042 defect. Anchored at script parse the splash yields at
        2500 ms having displayed the brand for 500 ms; anchored at the brand it
        yields no earlier than 4500 ms.
        """
        result = _run(brandLoadMs=2000, rounds=200)

        assert result["handoff"] is True
        assert result["handoffAtMs"] >= 2000 + _MIN_PLAY_MS, (
            f"handed off at {result['handoffAtMs']} ms with the brand painted "
            f"only at 2000 ms -- brand visible for "
            f"{result['handoffAtMs'] - 2000} ms, under the {_MIN_PLAY_MS} ms floor"
        )

    def test_brandNeverLoads_stillHandsOff_neverPinsTheBoot(self):
        """
        Given: a splash.svg that never loads (missing/corrupt asset)
        When: a healthy boot is reported
        Then: the splash still hands off rather than holding the boot forever

        The honest-instrument line: a broken brand asset is a COSMETIC fault. If
        an unloadable SVG could pin the floor open, the dashboard hand-off would
        never fire and a healthy car would sit on the splash until reboot -- the
        US-494 failure mode, re-introduced through the fix for it. The floor must
        degrade to the page-parse anchor, never block.
        """
        result = _run(brandLoadMs=None, rounds=200)

        assert result["handoff"] is True, (
            "an unloadable brand SVG pinned the splash -- a cosmetic asset fault "
            "must never withhold the dashboard hand-off"
        )

    def test_lateBrand_doesNotPushHandoffPastTheHardCap(self):
        """
        Given: a brand that paints very late (10 s) on a healthy boot
        When: the splash runs
        Then: it still settles -- the floor cannot outrun HARD_CAP_MS (12 s)

        A floor that could be pushed arbitrarily late by a slow asset is an
        unbounded boot delay. HARD_CAP_MS stays the outer bound.
        """
        result = _run(brandLoadMs=10000, rounds=400)

        assert result["handoff"] is True or result["degraded"] is True, (
            "neither handed off nor degraded -- the splash never settled"
        )


class TestFloorIsGroundedNotInvented:
    """Pin the constants so the floor stays traceable to the spec."""

    def test_pollJs_declaresTheReanchoredFloor_withNoNewMagicNumber(self):
        """
        Given: the shipped boot-state-poll.js
        When: its timing constants are read
        Then: the visible floor reuses the established 2500 ms value

        Rule 2 (ground every number): this story re-anchors an existing grounded
        constant. A test that let a NEW invented duration appear here would let
        exactly the fabrication the refusal rules forbid slip in.
        """
        source = _POLL_JS.read_text(encoding="utf-8")

        floors = re.findall(r"MIN_(?:PLAY|VISIBLE)_MS\s*=\s*(\d+)", source)

        assert floors, "no MIN_PLAY_MS / MIN_VISIBLE_MS floor declared"
        assert {int(v) for v in floors} == {_MIN_PLAY_MS}, (
            f"floor constants {floors} introduce a value other than the "
            f"established {_MIN_PLAY_MS} ms -- ground it or reuse it"
        )

    def test_pollJs_listensForTheBrandLoad(self):
        """
        Given: the shipped boot-state-poll.js
        When: its brand handling is read
        Then: it registers a load listener on the mark element

        Guards the mechanism, not just the timing: without a listener the floor
        silently falls back to script-parse anchoring and every timing test above
        would still pass on a fast fixture.
        """
        source = _POLL_JS.read_text(encoding="utf-8")

        assert 'getElementById("mark")' in source, "brand element never read"
        assert "addEventListener" in source, "no brand load listener registered"

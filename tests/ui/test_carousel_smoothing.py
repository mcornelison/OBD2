################################################################################
# File Name: test_carousel_smoothing.py
# Purpose/Description: US-662 -- 3-second DISPLAY smoothing, CIO-directed
#   2026-08-31 after reading the panel: "the heading is flickering plus or minus
#   two or three degrees ... we need to add a 3-second smoothing function to some
#   of these readings FOR DISPLAY PURPOSES ONLY."
#
#   THE ARCHITECTURE IS IN HIS LAST FOUR WORDS. Smoothing lives in the CONSUMER,
#   never in the producer. State files and the database keep RAW values. Landing
#   a smoothed number would write something no sensor ever reported -- the same
#   class as the fabricated ambient temperature and the manufactured
#   data_quality, which cost this project weeks. The smoothing here is a VIEW
#   concern and the tests below pin it as one.
#
#   🔴 THE DANGEROUS PART IS THE HEADING. A naive arithmetic mean of
#   358, 359, 1, 2 is 180 -- the display would point SOUTH while the car drives
#   NORTH. It must average unit vectors: atan2(mean(sin), mean(cos)).
#   This passes EVERY test that does not cross north, which is most of them, so
#   the wrap-crossing case below is mandatory rather than thorough.
#
#   ⚠️ Grade and g-force do NOT wrap. They use an arithmetic mean, deliberately.
#   Applying a circular mean to a non-angular quantity would be cargo-culting
#   the fix onto values it cannot help (Marcus, 2026-08-31).
#
#   ⚠️ Smoothing buys steadiness with LATENCY -- a 3 s window shows a real
#   braking event about 1.5 s late. Correct for a glance instrument, and
#   disqualifying for anything meant to warn. Nothing alert-bearing is smoothed.
# Author: Atlas (Architect)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Atlas        | Initial -- US-662 display-only smoothing.
# ================================================================================
################################################################################

"""US-662 tests for display-only smoothing of noisy readings."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CAROUSEL_JS = REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "carousel.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")


def runJs(tmp_path: Path, body: str) -> dict:
    """Run a JS snippet against the real carousel.js and return its JSON output."""
    script = tmp_path / "probe.js"
    script.write_text(
        '"use strict";\n'
        f"const carousel = require({json.dumps(str(CAROUSEL_JS))});\n"
        "function emit(o){ process.stdout.write(JSON.stringify(o)); }\n"
        f"{body}\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(script)], capture_output=True, text=True, timeout=30, check=False
    )
    assert completed.returncode == 0, f"node failed: {completed.stderr}"
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# 🔴 The wrap. This is the test the whole file exists for.
# ---------------------------------------------------------------------------


def test_heading_mean_ACROSS_NORTH_does_not_swing_south(tmp_path):
    """358, 359, 1, 2 must average to ~0, NEVER to 180.

    The arithmetic mean gives 180 -- pointing SOUTH while driving NORTH. It is
    correct everywhere except the one place it matters, which is why this case
    is mandatory and not merely thorough.
    """
    result = runJs(
        tmp_path,
        "emit({ mean: carousel.circularMeanDeg([358, 359, 1, 2]) });",
    )
    mean = result["mean"]
    assert mean is not None
    # Accept either side of the wrap: ~0 or ~360.
    wrapped = min(abs(mean - 0.0), abs(mean - 360.0))
    assert wrapped < 1.0, (
        f"heading mean was {mean} -- an arithmetic mean would give 180 and point "
        "the display SOUTH while the car drives NORTH"
    )


def test_heading_mean_is_ordinary_away_from_the_wrap(tmp_path):
    """The circular mean must not distort the easy case it is not needed for."""
    result = runJs(tmp_path, "emit({ mean: carousel.circularMeanDeg([104, 105, 106]) });")
    assert abs(result["mean"] - 105.0) < 0.5


def test_heading_mean_of_nothing_is_null_not_zero(tmp_path):
    """An empty window is ABSENT, never 0 -- which is a real bearing (north)."""
    result = runJs(tmp_path, "emit({ mean: carousel.circularMeanDeg([]) });")
    assert result["mean"] is None, "an empty window produced a bearing it never measured"


# ---------------------------------------------------------------------------
# Non-angular values use the arithmetic mean, deliberately.
# ---------------------------------------------------------------------------


def test_linear_mean_used_for_values_that_do_not_wrap(tmp_path):
    """Grade and g are not angles. A circular mean there would be cargo-culting."""
    result = runJs(
        tmp_path,
        """
        emit({
          g: carousel.linearMean([0.01, -0.01, 0.02, -0.02, 0.0]),
          empty: carousel.linearMean([])
        });
        """,
    )
    assert abs(result["g"]) < 0.001, "the arithmetic mean of symmetric noise is ~0"
    assert result["empty"] is None, "an empty window must be absent, not 0"


# ---------------------------------------------------------------------------
# The window: 3 seconds, by time, not by sample count.
# ---------------------------------------------------------------------------


def test_window_drops_samples_older_than_three_seconds(tmp_path):
    """Time-based, so it behaves the same at 4 Hz and at 10 Hz.

    A count-based window would smooth over 3 s on one loop and 0.4 s on another.
    """
    result = runJs(
        tmp_path,
        """
        var w = carousel.makeSmoothWindow(3000);
        w.push(10, 1000);
        w.push(20, 2000);
        w.push(30, 5000);   // 1000 and 2000 are now older than 3 s
        var all = w.values(3500);
        var kept = w.values(5000);
        emit({ kept: kept, all: all });
        """,
    )
    assert result["kept"] == [30], "stale samples survived the window"
    assert result["all"] == [10, 20, 30], "a fresh sample was dropped"


def test_a_single_sample_is_returned_unchanged(tmp_path):
    """Smoothing must not withhold a reading it cannot yet smooth.

    A blank panel for 3 s after boot would be a worse defect than the jitter.
    """
    result = runJs(
        tmp_path,
        """
        var w = carousel.makeSmoothWindow(3000);
        w.push(105, 1000);
        emit({ vals: w.values(1000), mean: carousel.circularMeanDeg(w.values(1000)) });
        """,
    )
    assert result["vals"] == [105]
    assert abs(result["mean"] - 105.0) < 0.001


# ---------------------------------------------------------------------------
# DISPLAY ONLY -- the load-bearing constraint.
# ---------------------------------------------------------------------------


def test_smoothing_is_never_applied_to_anything_written_back():
    """Static guard: the smoothing helpers live only in the render path.

    The CIO's 'for display purposes only' IS the architecture. If a smoothed
    value ever reaches a state file or the database we have written a number no
    sensor reported -- the ambient-temperature defect, rebuilt.
    """
    source = CAROUSEL_JS.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )
    # This assertion is NOT decoration. Without it the search below runs against
    # a function that does not exist, finds nothing, and PASSES VACUOUSLY -- the
    # inert-guard pattern, in the guard written to prevent it.
    at = code.find("function makeSmoothWindow")
    assert at >= 0, "makeSmoothWindow is absent -- this guard would pass on nothing"
    for forbidden in ("fetch(", "XMLHttpRequest", "localStorage"):
        window = code[at:][:1400]
        assert forbidden not in window, (
            f"the smoothing window references {forbidden} -- smoothing must be a "
            "pure view concern and must never write anywhere"
        )


def test_alert_bearing_and_obd_values_are_not_smoothed():
    """Latency is the price of steadiness; a warning must not pay it."""
    source = CAROUSEL_JS.read_text(encoding="utf-8")
    assert "SMOOTHED_FIELDS" in source, "the smoothed set is not declared explicitly"
    start = source.find("SMOOTHED_FIELDS")
    declared = source[start : start + 400]
    for never in ("mil", "dtc", "speed", "rpm"):
        assert f'"{never}"' not in declared, (
            f"{never} is in the smoothed set -- smoothing delays a real event by "
            "about half the window, which is disqualifying for anything that warns"
        )


def test_smoothing_is_actually_WIRED_into_the_render_path():
    """A helper nothing calls smooths nothing.

    US-655 shipped a reporter that had to be pinned at its call site for exactly
    this reason. The same guard, one story later.
    """
    source = CAROUSEL_JS.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )
    assert "pushImuSamples(lastImu" in code, "nothing feeds the smoothing window"
    assert "smoothedImuView(lastImu" in code, "the render path still reads the raw value"


def test_an_absent_reading_stays_absent_and_is_not_resurrected(tmp_path):
    """⚠️ Smoothing must never turn an honest NA into a stale number.

    GRADE reads NA whenever pitch is out of range. If the smoother filled that
    from history the panel would show a confident grade it is not measuring --
    strictly worse than the jitter this story exists to remove.
    """
    result = runJs(
        tmp_path,
        """
        var view = carousel.smoothedImuView(
          { headingDeg: 105, gradePct: null, gLat: 0.01 }, 1000);
        emit({ grade: view.gradePct, heading: view.headingDeg });
        """,
    )
    assert result["grade"] is None, "an absent grade was filled in from history"
    assert result["heading"] is not None

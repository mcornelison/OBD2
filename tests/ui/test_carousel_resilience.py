################################################################################
# File Name: test_carousel_resilience.py
# Purpose/Description: ARCH-014 tests for the dashboard's LOOP RESILIENCE and
#   error reporting.
#
#   THE DEFECT THIS PINS. The carousel drove the display from two
#   self-rescheduling async loops (`tick` at 4 Hz, `imuTick` at 10 Hz) whose
#   ONLY scheduling call sat on the last line of the function body:
#
#       async function imuTick() {
#         lastImu = await fetchState("imu");
#         renderHome(Date.now());
#         setTimeout(imuTick, IMU_POLL_MS);   // never reached if anything throws
#       }
#
#   Nothing awaited the returned promise, so a rejection became an UNHANDLED
#   PROMISE REJECTION -- silent by construction. One transient fetch failure or
#   one throw inside renderHome ended the loop permanently: the screen froze on
#   its last painted frame, the renderer went to ZERO CPU, and no log line was
#   written anywhere. Measured live on the Pi 2026-08-30: reproducible ~38 s
#   after data starts, renderer cumulative CPU flat at 00:00:12 in state `Sl`
#   while every state file kept updating -- i.e. the data tier was healthy and
#   only the display was dead. The panel never recovered and touch did nothing,
#   because a deterministic throw in the render path kills the touch-driven
#   redraw too.
#
#   THE CONTRACT. `makeResilientLoop` guarantees the next tick is scheduled
#   EXACTLY ONCE per invocation whether the body returns, throws synchronously,
#   or rejects -- and that a failure is REPORTED rather than swallowed. A
#   transient error must cost one frame, never the session.
#
#   THE LOGGING CONTRACT (CIO 2026-08-30, modelled on his own `myPrint`
#   utility): verbosity is gated by a config level so tracing can be turned up
#   without editing code, but LEVEL 0 (error) is NEVER gated. The absence of
#   error reporting is what made this defect invisible for weeks, so the
#   reporting is permanent, not debug scaffolding to be removed later.
#
#   Node-driven tests are skipped when node is absent (a node-less CI box),
#   matching tests/ui/test_carousel_brightness.py.
# Author: Atlas (Architect)
# Creation Date: 2026-08-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-30    | Atlas        | Initial -- ARCH-014 loop resilience + reporting.
# ================================================================================
################################################################################

"""ARCH-014 tests for dashboard loop resilience and error reporting."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CAROUSEL_JS = REPO_ROOT / "src" / "pi" / "ui" / "dashboard" / "carousel.js"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")


def runJs(tmp_path: Path, body: str) -> dict:
    """Run a JS snippet against the real carousel.js and return its JSON output.

    Uses a temp script rather than ``node -e`` so the snippet needs no shell
    quoting, and loads the SHIPPED module rather than a copy.

    Args:
        tmp_path: pytest temp dir.
        body: JS statements; must call ``emit(obj)`` exactly once.

    Returns:
        The object the snippet emitted.
    """
    script = tmp_path / "probe.js"
    script.write_text(
        '"use strict";\n'
        f"const carousel = require({json.dumps(str(CAROUSEL_JS))});\n"
        "function emit(o){ process.stdout.write(JSON.stringify(o)); }\n"
        f"{body}\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        ["node", str(script)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, f"node failed ({completed.returncode}): {completed.stderr}"
    return json.loads(completed.stdout)


# ---------------------------------------------------------------------------
# The reschedule guarantee -- the heart of the defect.
# ---------------------------------------------------------------------------


def test_loop_reschedules_after_a_synchronous_throw(tmp_path):
    """A body that throws must STILL book the next tick."""
    result = runJs(
        tmp_path,
        """
        var scheduled = [];
        var reported = [];
        var run = carousel.makeResilientLoop({
          name: "tick",
          delayMs: 250,
          body: function () { throw new Error("boom"); },
          schedule: function (fn, ms) { scheduled.push(ms); },
          report: function (name, err) { reported.push(name + ":" + err.message); }
        });
        run();
        emit({ scheduled: scheduled, reported: reported });
        """,
    )
    assert result["scheduled"] == [250], (
        "a throwing tick did not reschedule -- the loop is dead, which IS the bug"
    )
    assert result["reported"] == ["tick:boom"]


def test_loop_reschedules_after_an_async_rejection(tmp_path):
    """The real failure mode: a rejected promise, unhandled and silent."""
    result = runJs(
        tmp_path,
        """
        var scheduled = [];
        var reported = [];
        var run = carousel.makeResilientLoop({
          name: "imuTick",
          delayMs: 100,
          body: function () { return Promise.reject(new Error("fetch failed")); },
          schedule: function (fn, ms) { scheduled.push(ms); },
          report: function (name, err) { reported.push(name + ":" + err.message); }
        });
        Promise.resolve(run()).then(function () {
          emit({ scheduled: scheduled, reported: reported });
        });
        """,
    )
    assert result["scheduled"] == [100], (
        "a rejected async tick did not reschedule -- this is the exact live freeze"
    )
    assert result["reported"] == ["imuTick:fetch failed"]


def test_loop_reschedules_exactly_once_on_success(tmp_path):
    """Success must schedule ONE follow-up -- never zero, never two.

    A double-schedule would compound the loop rate on every tick and melt the
    CPU, so the guarantee is exactness, not merely "at least one".
    """
    result = runJs(
        tmp_path,
        """
        var scheduled = [];
        var run = carousel.makeResilientLoop({
          name: "tick",
          delayMs: 250,
          body: function () { return Promise.resolve("ok"); },
          schedule: function (fn, ms) { scheduled.push(ms); },
          report: function () { }
        });
        Promise.resolve(run()).then(function () {
          emit({ count: scheduled.length });
        });
        """,
    )
    assert result["count"] == 1


def test_a_failing_tick_does_not_stop_the_following_ticks(tmp_path):
    """End-to-end: three ticks where the FIRST throws still reaches the third.

    This is the user-visible promise -- a transient error costs one frame.
    """
    result = runJs(
        tmp_path,
        """
        var calls = 0;
        var run = carousel.makeResilientLoop({
          name: "tick",
          delayMs: 0,
          body: function () {
            calls += 1;
            if (calls === 1) { throw new Error("transient"); }
          },
          schedule: function (fn) { if (calls < 3) { fn(); } },
          report: function () { }
        });
        run();
        emit({ calls: calls });
        """,
    )
    assert result["calls"] == 3


# ---------------------------------------------------------------------------
# The logging contract -- errors are never gated.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("configured", [0, 1, 2, 3])
def test_errors_are_never_gated_by_debug_level(tmp_path, configured):
    """Level 0 emits at EVERY configured level, including 0.

    Mirrors the CIO's own myPrint contract. Silent errors are what hid this
    defect; making them configurable would rebuild the blindness.
    """
    result = runJs(
        tmp_path,
        f"emit({{ ok: carousel.shouldLog(0, {configured}) }});",
    )
    assert result["ok"] is True


def test_verbose_levels_are_gated(tmp_path):
    """Debug/info tracing is temporary and must be silenced by default."""
    result = runJs(
        tmp_path,
        """
        emit({
          debugAtZero: carousel.shouldLog(3, 0),
          infoAtZero: carousel.shouldLog(2, 0),
          debugAtThree: carousel.shouldLog(3, 3)
        });
        """,
    )
    assert result["debugAtZero"] is False
    assert result["infoAtZero"] is False
    assert result["debugAtThree"] is True


# ---------------------------------------------------------------------------
# Static wiring -- the guarantee only counts if the SHIPPED loops use it.
# ---------------------------------------------------------------------------


def test_both_live_loops_are_wired_through_the_resilient_wrapper():
    """The bare self-rescheduling pattern must not survive anywhere.

    Pins the fix at the call site: a future edit that reintroduces a trailing
    ``setTimeout(tick, ...)`` inside the loop body re-opens the freeze, and no
    unit test of the wrapper alone would catch that.
    """
    source = CAROUSEL_JS.read_text(encoding="utf-8")

    # Strip comment lines before asserting absence. The block that EXPLAINS the
    # retired pattern quotes it verbatim, and a naive substring check fails on
    # its own documentation -- the US-548 substring trap. Describing a retired
    # pattern is the record of its retirement, not an instance of it; the
    # violation is the pattern in EXECUTABLE code.
    code = "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*"))
    )

    assert re.search(r"makeResilientLoop\(\s*\{[^}]*name:\s*\"tick\"", source, re.S), (
        "the 4 Hz card tick is not built through makeResilientLoop"
    )
    assert re.search(r"makeResilientLoop\(\s*\{[^}]*name:\s*\"imuTick\"", source, re.S), (
        "the 10 Hz IMU tick is not built through makeResilientLoop"
    )

    assert "setTimeout(tick, POLL_MS)" not in code, (
        "the bare self-reschedule survived -- a throw before it still kills the loop"
    )
    assert "setTimeout(imuTick, IMU_POLL_MS)" not in code, "the bare IMU self-reschedule survived"


def test_global_error_reporting_is_installed():
    """Nothing was watching for exceptions -- that is why this hid for weeks."""
    source = CAROUSEL_JS.read_text(encoding="utf-8")
    assert "unhandledrejection" in source, (
        "no unhandledrejection handler -- the exact class of failure that froze "
        "the panel stays invisible"
    )
    assert re.search(r"addEventListener\(\s*\"error\"", source), "no window error handler"

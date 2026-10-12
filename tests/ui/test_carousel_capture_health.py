################################################################################
# File Name: test_carousel_capture_health.py
# Purpose/Description: US-688 (F-138) -- the SURFACE. The story's end state is
#   "the operator is told -- ON THE DASHBOARD, not only in a log", and a
#   producer whose output nothing renders is this project's most-repeated
#   defect (US-494/495/498/630, and US-687-b hit its mirror image one story
#   ago: "P" was decided correctly and painted as `--`).
#
#   THE CAPTURE VERDICT LANDS ON THE SYSTEM STATUS CARD, in all three places
#   that card speaks at once, because they are all derived from one tile map:
#   the 2x2+1 grid, the one-glance SUMMARY line, and the US-509 drill-down. A
#   tile that reached the summary but not the grid would print
#   "SYSTEM . 1 ISSUE" over five healthy-looking tiles, so the grid entry is
#   asserted alongside the summary rather than assumed from it.
#
#   🔴 AND THE LEVEL IS THE WHOLE DESIGN. `stalled` must rank as an ISSUE (it
#   is the alert) while `idle` must rank NEUTRAL -- neutral is the bucket
#   DRIVE=IDLE already occupies precisely so the commonest state on this car
#   (parked, key off) cannot make green unreachable. Get that backwards and the
#   card cries wolf every time the CIO switches the engine off, which is how an
#   alert stops being read.
# Author: Rex (Ralph agent)
# Creation Date: 2026-09-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-08    | Rex (US-688) | Initial -- the capture tile, its level ranking,
#               |              | and its route into summary + drill-down.
# ================================================================================
################################################################################

"""US-688: the capture-health verdict rendered on the System Status card."""

import json
import os
import shutil
import subprocess

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.join(
    os.path.dirname(__file__), "..", "..", "src", "pi", "ui", "dashboard", "carousel.js"
)

pytestmark = pytest.mark.skipif(_NODE is None, reason="node not on PATH")

_STALL_S = 60.0


def _view(fn: str, *args: object) -> object:
    """Evaluate one carousel.js export against N fixtures via the node probe."""
    proc = subprocess.run(
        [_NODE, _PROBE, fn, *[json.dumps(a) for a in args]],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _capture(state: str, **kw) -> dict:
    """A states/capture-health payload in the shape the REAL emitter writes.

    Keys copied from `capture_health.buildCaptureHealthState`; the producer
    suite pins that shape, so the two files agree by construction rather than
    by a hand-written fixture drifting from its emitter.
    """
    payload = {
        "state": state,
        "lastRowSecondsAgo": 1.0,
        "stallSeconds": _STALL_S,
        "reason": None,
        "ts": "2026-09-08T12:00:00Z",
    }
    payload.update(kw)
    return payload


def _sys(**kw) -> dict:
    """A fully HEALTHY system-status payload.

    Healthy on purpose: every test below is about what the CAPTURE fact does to
    the card, and a baseline that already carried an issue would let a summary
    assertion pass for a reason that has nothing to do with capture.
    """
    data = {
        "obdLink": {"state": "linked", "retries": 0, "lastSeenS": 1},
        "sync": {"lastOkTs": "2026-09-08T11:59:00Z", "rows": 10,
                 "pending": None, "stale": False},
        "power": {"source": "external", "reasons": {}},
        "drive": {"state": "recording", "driveId": 69, "lastDrive": None},
        "idle": False,
        "source": {
            "obd": {"available": True, "reason": None},
            "wifi": {"available": True, "reason": None},
        },
        "wifi": {"state": "up", "ssid": "x", "rssiDbm": -50},
        "ts": "2026-09-08T12:00:00Z",
    }
    data.update(kw)
    return data


# ------------------------------------------------------------------- the tile


class TestTheCaptureTile:
    """The four states each get a distinct, human-readable tile."""

    def test_captureTile_stalled_isAnIssueLevel(self) -> None:
        """
        Given: capture has written nothing while the car is powered
        When: the tile is built
        Then: it renders at an ISSUE level, not neutral and not unavailable

        THE ALERT. `down` is the only level that makes `systemSummary` count
        this as an issue; unavailable would merely block green, which is not
        the same as telling the operator something is wrong.
        """
        tile = _view("captureTile", _capture("stalled", lastRowSecondsAgo=None,
                                             reason="never_written"))

        assert tile["level"] == "down"
        assert tile["label"] == "CAPTURE"

    def test_captureTile_ok_isOk(self) -> None:
        """
        Given: rows are landing
        When: the tile is built
        Then: level `ok`
        """
        assert _view("captureTile", _capture("ok"))["level"] == "ok"

    def test_captureTile_idle_isNeutralNeverAnIssue(self) -> None:
        """
        Given: the car's power is off, so no rows are expected
        When: the tile is built
        Then: level `neutral`

        🔴 THE NUISANCE-ALARM GUARD. `neutral` is the bucket DRIVE=IDLE already
        occupies, and its comment in carousel.js states the reason out loud:
        counting it as a fault would make green unreachable in the commonest
        state there is. A parked Eclipse is exactly that state, and this car
        spends most of its life in it.
        """
        tile = _view("captureTile", _capture("idle", lastRowSecondsAgo=None))

        assert tile["level"] == "neutral"

    def test_captureTile_unknown_isUnavailableNotAnIssue(self) -> None:
        """
        Given: capture health could not be determined
        When: the tile is built
        Then: `unavailable` -- blocks green without raising an alarm
        """
        tile = _view("captureTile", _capture("unknown", lastRowSecondsAgo=None,
                                             reason="logger_absent"))

        assert tile["level"] == "unavailable"

    def test_captureTile_absentPayload_isUnavailable(self) -> None:
        """
        Given: no capture-health payload at all (producer dark, or fetch failed)
        When: the tile is built
        Then: `unavailable`, never `ok`

        An absent producer must not be able to paint capture healthy. Same rule
        `sysLevelRank` applies to an unrecognised level.
        """
        assert _view("captureTile", None)["level"] == "unavailable"

    def test_captureTile_unrecognisedState_isUnavailableNotOk(self) -> None:
        """
        Given: a state token this renderer has never been taught
        When: the tile is built
        Then: `unavailable` -- a future producer state cannot default to green
        """
        assert _view("captureTile", _capture("wedged"))["level"] == "unavailable"

    def test_captureTile_stalledNamesTheAgeItIsComplainingAbout(self) -> None:
        """
        Given: capture stalled with a real last-row age
        When: the tile is built
        Then: the detail names the age

        A bare "NO DATA" is not actionable. "no rows for 90s" tells the operator
        whether this just happened or has been true all drive.
        """
        tile = _view("captureTile", _capture("stalled", lastRowSecondsAgo=90.0,
                                             reason="stalled"))

        assert "90" in tile["detail"]

    def test_captureTile_neverWrittenSaysSoRatherThanPrintingAnAge(self) -> None:
        """
        Given: capture stalled having NEVER written a row
        When: the tile is built
        Then: the detail says so and prints no fabricated age

        `lastRowSecondsAgo` is null here. "no rows for 0s" would be the exact
        inversion of the truth, and it is the shape a naive `age || 0` produces.
        """
        tile = _view("captureTile", _capture("stalled", lastRowSecondsAgo=None,
                                             reason="never_written"))

        assert "0" not in tile["detail"]
        assert tile["detail"].strip() != ""


# ---------------------------------------------------------------- no raw tokens


class TestNoInternalTokensReachTheDriver:
    """snake_case machine vocabulary must not appear on a 3.5in panel."""

    @pytest.mark.parametrize(
        "state,reason",
        [
            ("stalled", "never_written"),
            ("stalled", "stalled"),
            ("unknown", "logger_absent"),
            ("unknown", "unreadable"),
            ("idle", None),
            ("ok", None),
        ],
    )
    def test_captureTile_rendersNoSnakeCaseToken(self, state, reason) -> None:
        """
        Given: every (state, reason) pair the producer can emit
        When: the tile is built
        Then: no underscore appears in any rendered string

        Swept over the producer's WHOLE vocabulary rather than the interesting
        members, so a reason added later without a phrase fails here instead of
        appearing on the panel. US-687-a's equivalent sweep read a hand-written
        tuple and expired within a week -- this list is checked against the
        module's constants by the test below.
        """
        tile = _view("captureTile", _capture(state, reason=reason,
                                             lastRowSecondsAgo=None))

        for field in ("value", "detail", "label"):
            assert "_" not in tile[field], (
                f"raw token leaked to the panel in {field}: {tile[field]!r}"
            )

    def test_theSweepCoversEveryReasonTheProducerCanEmit(self) -> None:
        """
        Given: the reason vocabulary the PRODUCER actually defines
        When: it is compared against the sweep above
        Then: every one is covered

        The guard on the guard. Discovered by introspection over the module
        rather than copied, so a new reason cannot be added to the producer
        without this failing -- which is precisely the expiry US-687-b had to
        repair one story after US-687-a wrote it.
        """
        from src.pi.obdii import capture_health as ch

        produced = {
            v for k, v in vars(ch).items()
            if k.startswith("REASON_") and isinstance(v, str)
        }
        swept = {"never_written", "stalled", "logger_absent", "unreadable"}

        assert produced == swept, (
            "the producer's reason vocabulary changed -- extend the sweep above"
        )


# ------------------------------------------------- into summary and drill-down


class TestItReachesTheCard:
    """The tile must actually be wired into the card's three surfaces."""

    def test_systemStatusView_carriesTheCaptureTile(self) -> None:
        """
        Given: a healthy system and a stalled capture
        When: the card view is built
        Then: `tiles.capture` exists

        The grid is hand-listed in `renderSystemStatusCard`, so this is what
        stops a capture verdict from being decided and then dropped on the
        floor -- the exact defect US-687-b caught one story ago.
        """
        view = _view("systemStatusView", _sys(), _capture("stalled",
                                                          lastRowSecondsAgo=None,
                                                          reason="never_written"))

        assert view["tiles"]["capture"]["level"] == "down"

    def test_systemStatusView_stalledCaptureMakesTheSummaryAnIssue(self) -> None:
        """
        Given: EVERY other source healthy, and capture stalled
        When: the card view is built
        Then: the summary reports an issue and names CAPTURE

        The load-bearing assertion of this whole story. Every other tile is
        green, so the issue can only have come from capture -- an implementation
        that added the tile but left it out of SYS_TILE_ORDER passes the test
        above and fails this one.
        """
        view = _view("systemStatusView", _sys(), _capture("stalled",
                                                          lastRowSecondsAgo=None,
                                                          reason="never_written"))

        assert view["summary"]["issues"] == 1
        assert "ISSUE" in view["summary"]["text"]
        assert "CAPTURE" in view["summary"]["detail"]

    def test_systemStatusView_stalledCaptureIsListedInTheDrillDown(self) -> None:
        """
        Given: a stalled capture on an otherwise healthy system
        When: the card view is built
        Then: the drill-down is tappable and lists CAPTURE

        The summary is a count; the drill-down is where the operator reads what
        to do about it. A headline that opens an overlay not mentioning capture
        is the dead end US-509 removed.
        """
        view = _view("systemStatusView", _sys(), _capture("stalled",
                                                          lastRowSecondsAgo=None,
                                                          reason="never_written"))

        assert view["drill"]["tappable"] is True
        labels = [r["label"] for r in view["drill"]["rows"]]
        assert "CAPTURE" in labels

    def test_systemStatusView_healthyCaptureKeepsTheCardGreen(self) -> None:
        """
        Given: everything healthy including capture
        When: the card view is built
        Then: SYSTEM . OK, and capture is NOT listed

        The non-vacuity pair for the issue test. Without it, an implementation
        that reported an issue unconditionally would pass every assertion above.
        """
        view = _view("systemStatusView", _sys(), _capture("ok"))

        assert view["summary"]["text"] == "SYSTEM · OK"
        assert view["summary"]["issues"] == 0
        labels = [r["label"] for r in view["drill"]["rows"]]
        assert "CAPTURE" not in labels

    def test_systemStatusView_idleCaptureDoesNotBlockGreen(self) -> None:
        """
        Given: the car is switched off -- capture idle, but the rest still green
        When: the card view is built
        Then: still SYSTEM . OK, and capture is not listed

        🔴 THE NEGATIVE CASE AT THE PANEL. The story's "must NOT fire on a
        normal parked Pi" is a claim about what the OPERATOR SEES, so it is
        asserted here and not only at the producer. An implementation that
        ranked idle as `unavailable` would turn every key-off into
        "SYSTEM . 1 UNAVAILABLE" -- quieter than an alarm, and still wrong.
        """
        view = _view("systemStatusView", _sys(), _capture("idle",
                                                          lastRowSecondsAgo=None))

        assert view["summary"]["text"] == "SYSTEM · OK"
        labels = [r["label"] for r in view["drill"]["rows"]]
        assert "CAPTURE" not in labels

    def test_systemStatusView_withNoCaptureArgument_isUnchanged(self) -> None:
        """
        Given: a caller that passes no capture payload (the pre-US-688 shape)
        When: the card view is built
        Then: no capture tile, and the card still summarises the other four

        Backward compatibility asserted rather than assumed: every existing
        test and every other call site passes one argument, and this story must
        not make the card unavailable for them.
        """
        view = _view("systemStatusView", _sys())

        assert view["tiles"].get("capture") is None
        assert view["summary"]["text"] == "SYSTEM · OK"


# ----------------------------------------------------------------- the grid


class TestTheGridRendersIt:
    """A tile in the summary that is missing from the grid is a contradiction."""

    def test_renderSystemStatusCard_appendsTheCaptureTile(self) -> None:
        """
        Given: the shipped carousel.js source
        When: the system-status grid construction is read
        Then: the capture tile is appended alongside the other four

        Asserted against the SOURCE because the grid is built with hand-listed
        `appendTile` calls, not a loop over SYS_TILE_ORDER -- so adding the tile
        to the view does NOT put it on the card, and nothing else in this file
        would notice.
        """
        src = open(_JS, encoding="utf-8").read()

        assert "appendTile(grid, view.tiles.capture" in src, (
            "the capture tile reaches the summary but is never painted in the "
            "grid -- the card would read 'SYSTEM · 1 ISSUE' over four green tiles"
        )

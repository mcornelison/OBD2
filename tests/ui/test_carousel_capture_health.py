################################################################################
# File Name: test_carousel_capture_health.py
# Purpose/Description: US-688 (F-138) -- the SURFACE. The story's end state is
#   "the operator is told -- ON THE DASHBOARD, not only in a log", and a
#   producer whose output nothing renders is this project's most-repeated
#   defect (US-494/495/498/630, US-687-b).
#
#   MOVED PIN (US-894-c, spec s4.3, Atlas A4, Iris W3): the CAPTURE tile is
#   retired. The capture verdict now lands on the System page's DATA row, read
#   from states/capture-health, and the rules the tile carried survive there:
#     - stalled is the ALERT -- but it is now the provider's `capture` verdict
#       MEMBER (from feeds.*.state, ECU up), never the page's own ranking: the
#       value reads `stalled` (amber) IF AND ONLY IF the member exists;
#     - idle (the car's power off) is never an issue: `idle`, neutral, and the
#       commonest state this car is in cannot make the page cry wolf;
#     - a member-less top-level stall reads `no rows` / `stopped`, neutral --
#       never `stalled`, never counted;
#     - an absent, unknown or unrecognised payload reads `--`, never healthy;
#     - no snake_case token reaches the panel.
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
# 2026-10-13    | Rex (US-873) | The System card ignores the additive feeds block.
# 2026-10-23    | Rex (US-894-c)| MOVED PIN: the tile is retired; the same rules
#               |              | on the DATA row (A4: stalled iff a member).
# 2026-10-23    | Rex (US-894-d)| MOVED PIN: the WIFI row follows the DATA row.
# 2026-10-23    | Rex (US-894-e)| MOVED PIN: the UPS row follows the WIFI row.
# 2026-10-23    | Rex (US-869-b)| A faulted feed's raw reason never reaches the
#               |              | DATA detail.
# 2026-10-24    | Rex (US-869-c)| MOVED PIN: the ups-absent fault case.
# ================================================================================
################################################################################

"""US-688 / US-894-c: the capture-health verdict on the System page's DATA row."""

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
_CAPTURE_MEMBER = {"key": "capture", "reason": "OBD feed stalled."}


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
    """A states/capture-health payload in the shape the REAL emitter writes
    (keys from `capture_health.buildCaptureHealthState`)."""
    payload = {
        "state": state,
        "lastRowSecondsAgo": 1.0,
        "stallSeconds": _STALL_S,
        "reason": None,
        "ts": "2026-09-08T12:00:00Z",
    }
    payload.update(kw)
    return payload


def _sys(*members: dict, ecu: str = "up", **kw) -> dict:
    """A HEALTHY system-status payload; `members` go into its verdict."""
    layer = {"state": "up", "ts": "2026-09-08T11:00:00Z", "lastOkTs": None}
    data = {
        "sync": {"lastOkTs": "2026-09-08T11:59:00Z", "stale": False,
                 "rowsWaiting": 0, "edrRowsWaiting": 0, "notCounted": []},
        "power": {"source": "external", "reasons": {}},
        "drive": {"state": "recording", "driveId": 69, "lastDrive": None},
        "link": {"bt": dict(layer), "adapter": dict(layer),
                 "ecu": dict(layer, state=ecu)},
        "idle": False,
        "source": {
            "obd": {"available": True, "reason": None},
            "wifi": {"available": True, "reason": None},
        },
        "wifi": {"state": "up", "ssid": "x", "rssiDbm": -50, "home": True},
        "verdict": {"issueCount": len(members), "members": list(members)},
        "ts": "2026-09-08T12:00:00Z",
    }
    data.update(kw)
    return data


def _row(system: dict, capture: object) -> dict:
    return _view("dataRowView", system, capture)


# ------------------------------------------------------------- the capture word


class TestTheCaptureWord:
    """Each capture state gets a distinct word and look on the DATA row."""

    def test_stalled_withTheMember_isTheAmberAlert(self) -> None:
        """
        Given: the provider counted a `capture` member (a feed stalled, ECU up)
        When: the DATA row is built
        Then: `stalled`, amber, and the member's reason verbatim as the sentence
        """
        row = _row(_sys(_CAPTURE_MEMBER), _capture("ok"))

        assert (row["word"], row["look"], row["level"]) == ("stalled", "amber", "amber")
        assert row["sentence"].startswith("OBD feed stalled.")

    def test_ok_isRecording(self) -> None:
        row = _row(_sys(), _capture("ok"))

        assert (row["word"], row["look"]) == ("recording", "ok")
        assert row["sentence"].startswith("all 4 feeds writing")

    def test_idle_isNeutralNeverAnIssue(self) -> None:
        """
        🔴 THE NUISANCE-ALARM GUARD. The car's power is off, no rows expected:
        `idle`, never amber -- a parked Eclipse is the commonest state there is.
        """
        row = _row(_sys(), _capture("idle", lastRowSecondsAgo=None))

        assert (row["word"], row["look"], row["level"]) == ("idle", "secondary", "secondary")
        assert row["sentence"].startswith("not driving")

    @pytest.mark.parametrize("payload", [
        None,
        _capture("unknown", lastRowSecondsAgo=None, reason="logger_absent"),
        _capture("wedged"),
    ])
    def test_absentUnknownOrUnrecognised_isNoDataNeverHealthy(self, payload) -> None:
        """A dark producer, an undecided state or a token never taught: `--`,
        tertiary -- never `recording`, never amber."""
        row = _row(_sys(), payload)

        assert (row["word"], row["look"]) == ("--", "tertiary")
        assert row["sentence"].startswith("capture not read yet")

    def test_topLevelStall_withNoMember_isNeverStalled(self) -> None:
        """
        W3 / A4: the logger silent past the window but no member (the ECU is up
        and no feed stalled) -> `stopped`, neutral, and the age it names.
        """
        row = _row(_sys(), _capture("stalled", lastRowSecondsAgo=300.0, reason="stalled"))

        assert (row["word"], row["look"], row["level"]) == ("stopped", "secondary", "secondary")
        assert row["sentence"].startswith("last row 5 min ago")

    def test_neverWritten_saysSoRatherThanPrintingAnAge(self) -> None:
        """`lastRowSecondsAgo` is null: `no rows`, and no fabricated age --
        `0` is the exact inversion of the truth a naive `age || 0` produces."""
        row = _row(_sys(), _capture("stalled", lastRowSecondsAgo=None,
                                    reason="never_written"))

        assert row["word"] == "no rows"
        assert row["sentence"].startswith("no row logged this session")
        assert "ago" not in row["sentence"]

    @pytest.mark.parametrize("ecu", ["down", "retrying", "connecting"])
    def test_memberlessStall_withTheEcuSilent_namesTheEcu(self, ecu) -> None:
        """A cause is named only from the fact that carries it (A4)."""
        row = _row(_sys(ecu=ecu), _capture("stalled", lastRowSecondsAgo=300.0,
                                           reason="stalled"))

        assert row["word"] == "stopped"
        assert row["sentence"].startswith("ECU not answering")

    @pytest.mark.parametrize("ecu", ["up", None])
    def test_memberlessStall_withTheEcuUpOrUnread_namesNoCause(self, ecu) -> None:
        """Never `ECU not answering` with the ECU up (a cold boot would be a lie)."""
        row = _row(_sys(ecu=ecu), _capture("stalled", lastRowSecondsAgo=None,
                                           reason="never_written"))

        assert "ECU" not in row["sentence"]


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
    def test_dataRow_rendersNoSnakeCaseToken(self, state, reason) -> None:
        """Swept over the producer's WHOLE vocabulary (checked below)."""
        payload = _capture(state, reason=reason, lastRowSecondsAgo=None)
        row = _row(_sys(), payload)
        detail = _view("dataDetailView", _sys(), payload)

        for field in ("word", "tail", "sentence", "label"):
            assert "_" not in row[field], f"raw token leaked in {field}: {row[field]!r}"
        assert "_" not in json.dumps([f["state"] for f in detail["feeds"]])

    def test_theSweepCoversEveryReasonTheProducerCanEmit(self) -> None:
        """The guard on the guard: the producer's reason vocabulary, by
        introspection, equals the sweep above."""
        from src.pi.obdii import capture_health as ch

        produced = {
            v for k, v in vars(ch).items()
            if k.startswith("REASON_") and isinstance(v, str)
        }
        swept = {"never_written", "stalled", "logger_absent", "unreadable"}

        assert produced == swept, (
            "the producer's reason vocabulary changed -- extend the sweep above"
        )


# ------------------------------------------------------------ onto the page


class TestItReachesThePage:
    """The DATA row is wired into the page view; the tile is gone."""

    def test_systemStatusView_carriesTheDataRow_andNoCaptureTile(self) -> None:
        view = _view("systemStatusView", _sys(_CAPTURE_MEMBER), _capture("ok"))

        # MOVED PIN (US-894-d): the WIFI row follows the DATA row.
        # MOVED PIN (US-894-e): the UPS row follows the WIFI row.
        assert [r["key"] for r in view["rows"]] == ["obd", "data", "wifi", "ups"]
        assert view["rows"][1]["word"] == "stalled"
        # MOVED PIN (US-894-f): the drill and its tiles are deleted (US-759
        # closed by the design) -- there is no CAPTURE tile or drill row left
        # anywhere for the capture fact to hide in.
        assert "tiles" not in view
        assert "drill" not in view

    def test_systemStatusView_withNoCaptureArgument_readsNotYetRead(self) -> None:
        """A caller that passes no capture payload still gets the page: the
        DATA row says capture was not read, never a healthy word."""
        view = _view("systemStatusView", _sys())

        assert view["rows"][1]["word"] == "--"
        assert view["verdict"]["text"] == "ALL OK"


# ------------------------------------------------- US-873: the additive feeds

_FEEDS_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "states", "capture-health-feeds.json"
)


def _feedCases() -> dict:
    with open(_FEEDS_FIXTURE, encoding="utf-8") as fh:
        return json.load(fh)


class TestTheFeedsBlockIsAdditiveToTheRow:
    """US-873 (Iris S-8): the ROW never reads `feeds` -- its `stalled` comes from
    the provider's member, which is the one reader of the feeds (A4). The
    DATA detail is where the feeds are shown."""

    @pytest.mark.parametrize("case", sorted(_feedCases()))
    def test_dataRow_sameWithAndWithoutFeeds(self, case: str) -> None:
        withFeeds = _feedCases()[case]["payload"]
        preChange = {k: v for k, v in withFeeds.items() if k != "feeds"}

        assert _row(_sys(), withFeeds) == _row(_sys(), preChange)

    # MOVED PIN (US-869-c): + ups-absent (no monitor is its own token).
    @pytest.mark.parametrize(
        "case", ["imu-absent", "light-absent", "ups-unreadable", "ups-absent"]
    )
    def test_faultedFeed_noRawReasonReachesTheDataDetail(self, case: str) -> None:
        """US-869-b: the producer's feed `reason` (sensor_absent, gauge
        unreadable) is for the S114 boot screen; today's DATA detail must
        not print it, nor any snake_case token, for a faulted feed."""
        payload = _feedCases()[case]["payload"]
        detail = _view("dataDetailView", _sys(), payload)
        reasons = {f["reason"] for f in payload["feeds"].values() if f["reason"]}

        rendered = json.dumps(detail["feeds"])
        assert reasons, "fixture case carries no faulted feed"
        for reason in reasons:
            assert reason not in rendered
        assert "_" not in json.dumps([f["state"] for f in detail["feeds"]])

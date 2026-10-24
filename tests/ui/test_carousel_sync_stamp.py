################################################################################
# File Name: test_carousel_sync_stamp.py
# Purpose/Description: US-559 (F-132 / Iris P-5). The SYNC tile pasted the raw
#   ISO `lastOkTs` straight onto the panel, so the 3.5" display carried TWO
#   clocks -- the top-bar face in LOCAL time, the sync stamp in UTC -- that can
#   differ by hours with no way to tell which one is lying.
#
#   This file pins four things, each of which fails for a different reason:
#     1. THE FACE -- `fmtStamp` renders `Mmm dd, yyyy h:mm:ss AM/PM`.
#     2. THE CLOCK -- it is LOCAL, proven structurally (getHours, never
#        getUTCHours) so the proof does not depend on the runner's timezone.
#     3. ONE RULE -- `h % 12 || 12` exists exactly ONCE in carousel.js.
#        `fmtClock`'s own comment already warned that two formatters is how a
#        12-hour face drifts back to 24-hour; P-5 is that warning coming true,
#        so the rule is now shared rather than copied.
#     4. NO FABRICATED DATE -- unparseable input renders the RAW string. A
#        confident wrong date on the one tile whose job is to report sync
#        health is the green-when-broken class of defect.
#
#   The counts (`N rows . N pending`) MOVE to the System drill-down per the CIO's
#   2026-08-20 placement call. Their pins move with them (US-564 owns the
#   null-honesty half in test_carousel_sync_pending_na.py); the reachability of
#   the new home is pinned here, because a "move" to a surface that cannot be
#   opened is a deletion.
# Author: Rex (US-559)
# Creation Date: 2026-08-21
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-21    | Rex (US-559) | Initial -- local 12-hour stamp, counts to detail.
# 2026-10-23    | Rex (US-894-c)| MOVED PIN: the SYNC tile and its counts are
#               |              | retired; the stamp pins read the DATA row and
#               |              | detail; the drill carries no sync counts.
# 2026-10-23    | Rex (US-894-e)| MOVED PIN: LAST STOP moved to the UPS detail
#               |              | and the POWER tile is gone, so the drill has
#               |              | nothing behind it and is not tappable.
# 2026-10-23    | Rex (US-894-f)| MOVED PIN: the drill is deleted (US-759); the
#               |              | gate and diagnostics-renderer tests retire, the
#               |              | rest read the view's piDetail.
# ================================================================================
################################################################################

"""US-559 fixture tests for the carousel.js sync stamp (via node)."""

import json
import os
import re
import shutil
import subprocess
from datetime import UTC, datetime

import pytest

_NODE = shutil.which("node")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")
_JS = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src",
    "pi",
    "ui",
    "dashboard",
    "carousel.js",
)

pytestmark = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- carousel.js pure-logic fixture tests need node",
)

# The shipped stamp face: `Aug 17, 2026 7:30:28 PM`. Anchored, so a stray
# trailing field or a 24-hour hour fails. The hour is BARE (1-12, never "07");
# the minute, the second and the DAY are padded.
STAMP_FACE = re.compile(
    r"^[A-Z][a-z]{2} \d{2}, \d{4} (1[0-2]|[1-9]):[0-5][0-9]:[0-5][0-9] (AM|PM)$"
)

# Spelled as an escape, never a literal -- this file is written and re-read on a
# Windows SMB share where a raw em-dash / middle dot has been mangled before.
EM_DASH = "—"
MIDDLE_DOT = "·"

MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _probe(fn: str, *args):
    """Evaluate one carousel.js export against fixtures via the node probe.

    Decodes stdout as UTF-8 EXPLICITLY: the shared tests/ui helper passes
    ``text=True``, which on Windows decodes with the ANSI code page, so a
    rendered em-dash comes back as mojibake while the printed message still
    LOOKS right. (TD-084.)
    """
    proc = subprocess.run(
        [_NODE, _PROBE, fn] + [json.dumps(a) for a in args],
        capture_output=True,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    return json.loads(proc.stdout.decode("utf-8"))


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _codeOnly(js: str) -> str:
    """Strip comments so a claim about the CODE cannot be satisfied by prose.

    Without this, `assert "getUTCHours" not in js` would go red on a comment
    that merely NAMES the thing it forbids -- and, worse, a structural count of
    a rule would be inflated by every comment that quotes it.
    """
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", js)


def _sync(**overrides):
    payload = {
        "lastOkTs": "2026-08-17T19:30:28Z",
        "rows": 412,
        "pending": 0,
        "stale": False,
    }
    payload.update(overrides)
    return payload


def _sysState(**overrides):
    """A whole-system payload whose four sources are all healthy by default."""
    state = {
        # MOVED PIN (US-876-a): obdLink.lastSeenS is gone from system-status.
        "obdLink": {"state": "linked", "retries": 0},
        "sync": _sync(),
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "recording", "driveId": 41, "lastDriveTs": None},
        "source": {"obd": {"available": True, "reason": None}},
        "idle": False,
    }
    state.update(overrides)
    return state


def _localFace(iso: str) -> str:
    """Render the expected face in PYTHON, from the runner's own local zone.

    Deliberately NOT `%b`/`%p`: those are locale-dependent, so a non-English
    runner would fail on the formatter rather than on the code under test.
    """
    d = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    d = d.astimezone()
    hour12 = d.hour % 12 or 12
    meridiem = "AM" if d.hour < 12 else "PM"
    return (
        f"{MONTHS[d.month - 1]} {d.day:02d}, {d.year} "
        f"{hour12}:{d.minute:02d}:{d.second:02d} {meridiem}"
    )


# ---------------------------------------------------------------------------
# AC1 -- the face. `Mmm dd, yyyy h:mm:ss AM/PM`, never a raw ISO instant.
# ---------------------------------------------------------------------------


def test_fmtStamp_isoInstant_rendersTheDatePlusATwelveHourFace():
    """
    Given: the emitter's ISO-8601 instant
    When: the stamp is formatted
    Then: `Mmm dd, yyyy h:mm:ss AM/PM` -- and NOT the raw ISO string. The `T`
          and the `Z` are asserted gone individually: a formatter that merely
          prefixed the ISO would still match a laxer test.
    """
    stamp = _probe("fmtStamp", "2026-08-17T19:30:28Z")

    assert STAMP_FACE.match(stamp), stamp
    assert "T" not in stamp
    assert "Z" not in stamp


def test_fmtStamp_matchesTheRunnersOwnLocalWallTime():
    """
    Given: an ISO instant in UTC
    When: it is formatted
    Then: it equals the SAME instant rendered in the runner's local zone. This
          is the whole point of the story -- two clocks on one panel must not
          disagree. Python and node read the same OS zone, so this holds on any
          machine; on a UTC-configured machine it cannot by itself distinguish
          local from UTC, which is why the structural pin below exists too.
    """
    iso = "2026-08-17T19:30:28Z"

    assert _probe("fmtStamp", iso) == _localFace(iso)


def test_fmtStamp_readsLocalGettersNeverTheUtcOnes():
    """
    Given: the shipped source
    When: the stamp formatter is read
    Then: it uses the LOCAL getters. Timezone-proof, unlike the comparison
          above: on a UTC runner a UTC formatter would pass that one silently.
    """
    js = _codeOnly(_read(_JS))
    start = js.index("function fmtStamp(")
    body = js[start : start + 600]

    assert "getUTCHours" not in body
    assert "getUTCFullYear" not in body
    assert "getFullYear" in body


def test_fmtStamp_singleDigitDayIsPadded():
    """
    Given: a day below the tenth
    When: the stamp renders
    Then: `Sep 03`, not `Sep 3`. Padding keeps the stamp a FIXED width, so the
          tile does not reflow between the 9th and the 10th -- the same reason
          the minute keeps its zero while the hour does not.
    """
    stamp = _probe("fmtStamp", "2026-09-03T12:00:00Z")

    assert STAMP_FACE.match(stamp), stamp
    assert re.search(r"^[A-Z][a-z]{2} 0\d,", stamp) or "03," in stamp


def test_fmtStamp_everyHourOfTheDay_staysATwelveHourFace():
    """
    Given: all 24 UTC hours
    When: each is formatted
    Then: every one matches the 12-hour face. Catches the two hours a bare
          `% 12` renders as zero -- midnight and noon -- whatever the local
          offset shifts them to.
    """
    for hour in range(24):
        stamp = _probe("fmtStamp", f"2026-08-17T{hour:02d}:30:28Z")
        assert STAMP_FACE.match(stamp), f"hour {hour} -> {stamp}"


# ---------------------------------------------------------------------------
# AC3 -- ONE 12-hour rule on this surface, not two.
# ---------------------------------------------------------------------------


def test_carouselJs_theTwelveHourRuleIsWrittenExactlyOnce():
    """
    Given: the shipped source
    When: the mod-12 rule is counted
    Then: exactly one occurrence. `fmtClock`'s own comment warned that two
          formatters is how the 12-hour face drifts back to 24-hour; the fix
          for P-5 must not BE that second formatter.
    """
    js = _codeOnly(_read(_JS))

    assert len(re.findall(r"%\s*12\s*\|\|\s*12", js)) == 1


def test_carouselJs_fmtClockDelegatesToTheSharedHelper():
    """
    Given: `fmtClock`, the top-bar face
    When: its body is read
    Then: it calls the shared time-of-day helper rather than keeping a private
          copy of the rule. Without this the count above could be satisfied by
          deleting `fmtClock` outright, or by `fmtStamp` re-deriving the hour a
          different way.
    """
    js = _codeOnly(_read(_JS))
    start = js.index("function fmtClock(")
    body = js[start : start + 200]

    assert "fmtTimeOfDay(" in body
    assert "%" not in body


def test_fmtClock_faceIsUnchangedByTheExtraction():
    """
    Given: the top-bar clock, which US-503 pinned and this story refactors
    When: the shared helper is introduced
    Then: the top-bar face still carries NO seconds. The extraction added a
          seconds field for the stamp; leaking it into `fmtClock` would change
          a shipped surface from a story that never asked to.
    """
    js = _codeOnly(_read(_JS))
    start = js.index("function fmtClock(")
    body = js[start : start + 200]

    assert "true" not in body


# ---------------------------------------------------------------------------
# AC4 -- unparseable input renders RAW. Never Jan 01 1970, never NaN.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "garbage",
    [
        "not-a-timestamp",
        "",
        "2026-08-17",  # date only -- no instant, so no wall time to render
        "2026-08-17 19:30:28",  # space separator, not ISO-8601
        "2026-08-17T19:30:28",  # NO ZONE: the instant is undetermined
        "412",  # JS would happily read this as the year 412
        "last 2026-08-17T19:30:28Z",  # the string the tile used to print
    ],
)
def test_fmtStamp_unparseableInput_isEchoedVerbatim(garbage):
    """
    Given: input that is not a zone-qualified ISO-8601 instant
    When: the stamp is formatted
    Then: the RAW string comes back, unchanged and unformatted. Two of these
          would otherwise fabricate a confident date rather than fail loudly:
          `new Date("412")` is the year 412, and a zoneless stamp is read as
          LOCAL, which is silently hours wrong for a value the emitter sends in
          UTC -- the exact contradiction this story removes.
    """
    assert _probe("fmtStamp", garbage) == garbage


def test_fmtStamp_neverRendersTheEpochOrNaN():
    """
    Given: the inputs most likely to fall through to a fabricated date
    When: they are formatted
    Then: no 1970, no NaN. Stated as its own assertion because it is the ACs
          own words, and because it fails for a different reason than the
          echo test above -- a formatter could echo one input and fabricate
          another.
    """
    for garbage in ("not-a-timestamp", "", "412", "0"):
        stamp = _probe("fmtStamp", garbage)
        assert "1970" not in stamp
        assert "NaN" not in stamp
        assert "Invalid" not in stamp


def test_fmtStamp_negativeSelfTest_theFaceRegexRejectsARawIso():
    """
    Given: the raw ISO string this story removes
    When: it is measured against the face regex
    Then: it does NOT match. Without this the face assertions could all be
          green against a formatter that changed nothing.
    """
    assert not STAMP_FACE.match("2026-08-17T19:30:28Z")
    assert not STAMP_FACE.match("Aug 17, 2026 19:30:28")


# ---------------------------------------------------------------------------
# AC1 / AC2 / AC5 -- MOVED PIN (US-894-c): the SYNC tile is retired. The full
# stamp now lives in the DATA detail (`last data stored`); the row carries the
# short `synced <when>` (spec s4.3, Iris I3). The rules are unchanged: a real
# face, `never` -> an honest absence, never a fabricated date.
# ---------------------------------------------------------------------------


def _status(**sync):
    """A system-status payload with the sync block overridden."""
    state = _sysState(sync=_sync(**sync))
    state["ts"] = "2026-08-17T20:00:00Z"
    return state


def test_dataDetail_lastStoredIsTheFullStampAlone():
    """
    Given: a healthy sync
    When: the DATA detail is built
    Then: `last data stored` is the formatted stamp and nothing else -- no
          `last` prefix, no counts folded in.
    """
    detail = _probe("dataDetailView", _status(), None)

    assert STAMP_FACE.match(detail["lastStored"]), detail["lastStored"]
    assert detail["lastStored"] == _probe("fmtStamp", "2026-08-17T19:30:28Z")


@pytest.mark.parametrize("shape", ["null", "missing"])
def test_dataRowAndDetail_noTimestamp_readNoSyncOnRecord(shape):
    """
    Given: a Pi that has never stored data (null), or an older payload that
           omits the key
    When: the row and the detail are built
    Then: `no sync on record` on both -- never a date, never 1970.
    """
    payload = _status()
    if shape == "null":
        payload["sync"]["lastOkTs"] = None
    else:
        payload["sync"].pop("lastOkTs")

    row = _probe("dataRowView", payload, None)
    detail = _probe("dataDetailView", payload, None)
    assert row["value"].endswith(MIDDLE_DOT + " no sync on record"), row["value"]
    assert detail["lastStored"] == "no sync on record"


def test_dataRow_unparseableTimestamp_isNeverARawStringOnTheRow():
    """
    Given: a corrupt stamp
    When: the row renders
    Then: `synced --` on the row (spec s4.3: never a raw ISO string), and the
          detail echoes it VERBATIM through fmtStamp -- the honesty survives
          the trip, and the one-line row never shows an unexplained string.
    """
    payload = _status(lastOkTs="corrupt-value")

    assert _probe("dataRowView", payload, None)["value"].endswith("synced --")
    assert _probe("dataDetailView", payload, None)["lastStored"] == "corrupt-value"


def test_dataRow_staleSyncStillCarriesItsStamp():
    """A stale-while-driving sync keeps its stamp on the row (how stale?)."""
    row = _probe("dataRowView", _status(stale=True), None)

    assert "synced " in row["value"]
    assert "stale" not in row["value"].lower()


def test_dataRow_theTimeOnTheRowIsTheSharedTwelveHourFace():
    """The row's same-day time goes through fmtTimeOfDay -- the one 12-hour
    rule (counted below) -- so it never drifts to a 24-hour face."""
    row = _probe("dataRowView", _status(), None)

    assert re.search(r"synced (1[0-2]|[1-9]):[0-5][0-9] (AM|PM)$", row["value"]), row


# ---------------------------------------------------------------------------
# AC2 -- MOVED PIN (US-894-c): the sync COUNTS diagnostic is gone with the
# tile and sync.rows / sync.pending (Atlas P7). The backlog is the DATA row's
# `rows waiting` (US-564's null rule pinned in test_carousel_sync_pending_na.py).
# ---------------------------------------------------------------------------


def test_systemDrill_carriesNoSyncCountsAnyMore():
    """
    Given: the whole-system payload
    When: the page view is built
    Then: no `sync` tile and no `pending` anywhere in it.

          MOVED PIN (US-894-e): the prior-shutdown verdict that was the only
          reference fact here moved to the UPS detail (Iris I7).
          MOVED PIN (US-894-f): the drill and its tiles are DELETED (US-759
          closed by the design), so the counts have nowhere left to hide.
    """
    view = _probe("systemStatusView", _sysState())

    assert "drill" not in view
    assert "tiles" not in view
    assert view["upsDetail"]["lastStop"]["label"] == "LAST STOP"
    assert "pending" not in json.dumps(view)


def test_systemDrill_healthySystem_isStillReachable():
    """
    Given: every source healthy -- the COMMON case
    When: the page view is built
    Then: the verdict still has something behind it.

          THIS PIN MOVED, IT WAS NOT DELETED. US-509 gated the line on an
          issue list; US-894-e left that list empty on a healthy card.
          MOVED PIN (US-894-f): the issue list is gone (US-759) and the
          verdict opens the Pi detail (spec s4.1), which is always built --
          so the line is a real tap target (parked) on a healthy card too.
          The parked-only gate is pinned in test_system_page_pi_detail.py.
    """
    view = _probe("systemStatusView", _sysState())

    assert view["piDetail"]["head"] == "PI"
    assert [r["label"] for r in view["piDetail"]["rows"]] == [
        "CPU", "THROTTLING", "DISK", "UPTIME",
    ]
    assert [r["key"] for r in view["rows"]] == ["obd", "data", "wifi", "ups"]


# MOVED PIN (US-894-f): test_systemDrill_nothingBehindTheLine_isNotATapTarget
# and test_systemDrill_negativeSelfTest_gateIsNotHardCodedTrue are RETIRED with
# the gate they pinned: systemDrill and its `tappable` are deleted (US-759
# closed by the design). The verdict's tap is now gated on parked alone.


# ---------------------------------------------------------------------------
# AC6 -- the SSOT direction. The consumer formats; it never re-derives.
# ---------------------------------------------------------------------------


def test_emitterStillPublishesRawIso_theDisplayOwnsThePresentation():
    """
    Given: the Pi emitter
    When: its sync block is read
    Then: it still transports `lastOkTs` verbatim. The fix belongs entirely in
          the CONSUMER -- an emitter that pre-formatted the stamp would put a
          presentation policy on the wrong tier and lose the instant.
    """
    emitter = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "src",
        "pi",
        "splash",
        "system_status_emitter.py",
    )
    body = _read(emitter)

    assert '"lastOkTs": syncLastOkTs' in body
    assert "%p" not in body
    assert "strftime" not in body.split('"lastOkTs"')[1][:400]


# MOVED PIN (US-894-f): test_carouselJs_rendererPaintsTheDiagnosticsItComputes
# is RETIRED: the diagnostics section and its renderer (renderSysDiagnostics)
# are deleted with the drill (US-759). The Pi detail's painted fields are
# pinned in tests/ui/test_system_page_pi_detail.py.

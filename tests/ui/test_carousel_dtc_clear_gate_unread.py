################################################################################
# File Name: test_carousel_dtc_clear_gate_unread.py
# Purpose/Description: US-636 (F-138, punch-list 2.3) -- RECORD THE PASS on the
#   Mode-04 clear affordance staying gated while DTCs are unread, and record the
#   three findings the recording turned up.
#
#   THE VERDICT IS A PASS. Atlas observed clearGate {enabled:false, reason:'ok'}
#   and believed the affordance gated. It is: on the unread state the Alerts card
#   offers NO code row to open the detail with, the clear zone does not paint, the
#   button stays hidden, and the AUTHORITATIVE server-side gate refuses with
#   `no_codes` WITHOUT calling the Mode-04 runner. No vehicle write, no evidence
#   destroyed. That is this story's END STATE and it holds.
#
#   WHY A NEW FILE WHEN US-407 ALREADY TESTED THE GATE. The pre-existing pins
#   (tests/deploy/test_dashboard_kit.py, tests/ui/test_dtc_detail_hierarchy.py::
#   test_mode04ClearGate_isUnchanged) call `clearButtonView` as a PURE FUNCTION on
#   hand-written payloads. A pure view cannot witness the two things the operator
#   actually meets: the `disabled` ATTRIBUTE on the shipped <button>, and whether
#   the zone has a box at all. Nor can it witness the UNREAD case, which no test
#   in the repo exercised at any layer -- `source.dtc.available` appears nowhere
#   in the clear-gate suite, and `clearGateReason` never reads it. The affordance
#   is gated on an unread source ONLY because `buildDtcState` empties `codes`
#   when the source is unavailable. Two correct halves, no test on the join --
#   the US-494/495/498 shape, and the reason the coupling is pinned below as one
#   composed assertion rather than two independent ones.
#
#   WHAT GATES THE UNREAD CASE IS REACHABILITY, NOT THE GATE FUNCTION, and that
#   distinction was MEASURED here rather than assumed -- a mutation that made
#   `clearGateReason` return `ok` for an empty stored set left every unread test
#   in the first draft of this file GREEN. The reason: `renderClearButton()` runs
#   only from `openDetail()`, and on an unread state there is no code row to open
#   the detail with, so the gate is never consulted at all. Both facts are pinned
#   below, separately and by name: reachability by the unread tests, the gate
#   function by the `na`-only test (an all-`na` state renders rows, so the overlay
#   DOES open and the gate IS asked). Collapsing the two would have left the
#   display mirror unpinned while looking thorough.
#
#   THREE FINDINGS, RECORDED NOT FIXED (sprint contract: a VERIFY story RECORDS a
#   defect and FILES a fix story; it must never quietly become the fix). All three
#   are in offices/pm/issues/I-us636-*.md, and each is held below by a
#   test_characterisation_* that whoever fixes it will fail ON PURPOSE. Re-record
#   those numbers; do not relax them. A stale measurement sitting green in a suite
#   is worse than no measurement, because it looks authoritative.
#
#     F1  AN OPEN DETAIL OVERLAY NEVER RE-GATES. `renderClearButton()` is called
#         from `openDetail()` and from nowhere else -- not from the 4 Hz poll. The
#         button therefore freezes at the gate decision taken when the overlay was
#         opened. Measured on five state changes, all in the UNSAFE direction:
#         source goes unread, state file vanishes, a STOP code appears, the
#         session lock engages, the sync ack is withdrawn. In every one the button
#         still reads "CLEAR CODES", enabled, data-reason `ok`. Bounded honestly:
#         the server RE-CHECKS on submit and 403s, so no Mode-04 write happens and
#         no freeze-frame is destroyed -- this is an affordance that LIES, not a
#         safety hole. The operator learns only after tapping through a hard-
#         confirm modal that warns about erasing evidence.
#
#     F2  THE PUBLISHED `clearGate.reason` HAS NO WORD FOR "NOTHING WAS READ".
#         The emitter's vocabulary is {severity_present, sync_pending, ok} -- no
#         `no_codes` member, though BOTH other implementations of this same gate
#         have one (dtc_clear.GATE_NO_CODES, carousel.js `clearGateReason`). So
#         an unread source, a completed clean read, and a genuinely clearable car
#         all publish reason `ok`, separated only by `enabled`. That is exactly
#         the pair Atlas read off the live Pi, and it is punch-list 2.1's defect
#         class -- an unread value published as a settled result -- one field over.
#         No code consumes this block (the renderer and the server both re-derive
#         and deliberately ignore it), so the cost is paid by humans reading the
#         state file. A human already paid it.
#
#     F3  THE DISABLE LABEL MISNAMES AN UNCLASSIFIED CODE. Against the severity
#         table SHIPPED IN THIS REPO, P0443 -- the code stored on the car right
#         now -- is un-tabled, so `enrichCode` honestly degrades it to `unknown`,
#         and the gate refuses it as `severity_present`: "a STOP/WATCH code is
#         present". Refusing is right (never clear what you cannot classify); the
#         WORDS are false. And the same measurement says something larger: NO row
#         in the shipped table is `minor` (7 watch, 5 na, 0 minor), so with the
#         shipped data the `ok` branch is unreachable and the button can never be
#         enabled on this car. The table's own line 41 explains why -- the
#         clearable codes here are generic evap P0xxx, and the table is P1xxx-only.
#         STATED AS A LIMIT: this is measured against the REPO's table. The
#         deployed Pi reads `pi.dtc.severityTablePath`, so a different table there
#         would give a different answer -- which is what punch-list 2.2's observed
#         MINOR / "SAFE TO CLEAR ONCE LOGGED" render of P0443 would require. That
#         discrepancy is Atlas's to settle, not this story's.
#
#   Skipped when node is not on PATH (a node-less CI box); the Python-only gate
#   tests below run everywhere.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-31    | Ralph (Rex)  | Initial -- US-636 punch-list 2.3 recorded pass +
#               |              | F1/F2/F3 characterisations (I-us636).
# ================================================================================
################################################################################

"""US-636 tests: the DTC clear affordance stays gated while codes are unread."""

from __future__ import annotations

import os
import shutil
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO, "src"))

import render_harness as rh  # noqa: E402

from pi.splash import dtc_clear  # noqa: E402
from pi.splash.dtc_emitter import buildDtcState  # noqa: E402
from pi.splash.dtc_severity_table import loadP1xxxSeverityTable  # noqa: E402

_NODE = shutil.which("node")

_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render harness boots the shipped carousel.js",
)

# The severity table the orchestrator actually loads (card_state_emitter.py:131,
# `pi.dtc.severityTablePath` default). Used wherever this file makes a claim
# about the LIVE car, so the claim is against shipped data and not a fixture.
_SHIPPED_TABLE_PATH = os.path.join(
    _REPO, "src", "pi", "resources", "dsm-p1xxx-severity-table.md"
)

# A fixture table for the MECHANISM tests. It exists because the shipped table
# contains no `minor` row at all (F3) -- the clearable branch of the gate cannot
# be reached with real data, so a fixture is the only way to exercise the "this
# IS allowed" side. Keeping that side exercised is what stops every absence
# assertion in this file from passing vacuously.
_FIXTURE_TABLE: dict[str, dict[str, Any]] = {
    "P0442": {
        "severity": "minor",
        "severityCaveat": None,
        "short": "EVAP small leak",
        "long": "EVAP small leak",
        "suggestedFix": "Check the fuel cap seal",
        "fixProvenance": "spool",
        "clearEligible": True,
    },
    "P0301": {
        "severity": "stop",
        "severityCaveat": None,
        "short": "Cylinder 1 misfire",
        "long": "Cylinder 1 misfire",
        "suggestedFix": None,
        "fixProvenance": "none",
        "clearEligible": False,
    },
}

# The exact strings the operator meets on the 3.5in panel (carousel.js:2212).
_LABEL_ENABLED = "CLEAR CODES"
_LABEL_SEVERITY = "🔒 CLEAR CODES — a STOP/WATCH code is present"
_LABEL_SYNC = "🔒 CLEAR CODES — waiting for server sync"
_LABEL_LOCKED = "🔒 CLEAR CODES — a cleared code returned; clearing again won't fix it"


# ---------------------------------------------------------------------------
# Fixtures: captured codes and states, built by the REAL emitter.
#
# Payloads go through `buildDtcState` rather than being hand-written JSON on
# purpose (the US-628 lesson): a hand-written fixture survives a producer that
# renamed a key or stopped emptying `codes`, which is precisely the coupling
# this file exists to pin.
# ---------------------------------------------------------------------------


def _raw(
    code: str = "P0442",
    *,
    logged: bool = True,
    syncAcked: bool = True,
    status: str = "stored",
) -> dict[str, Any]:
    """One captured-code dict in the shape the DTC capture path hands the emitter."""
    return {
        "code": code,
        "status": status,
        "description": "captured description",
        "driveId": None,
        "setAtTs": "2026-08-20T12:00:00Z",
        "logged": logged,
        "syncAcked": syncAcked,
    }


def _state(
    codes: list[dict[str, Any]],
    *,
    available: bool = True,
    reason: str | None = None,
    lock: list[str] | None = None,
    table: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A `dtc` payload assembled by the real producer."""
    return buildDtcState(
        codes=codes,
        severityTable=_FIXTURE_TABLE if table is None else table,
        mil=bool(codes),
        newSinceTs=None,
        sessionResetLock=lock or [],
        nowIso="2026-08-31T15:54:00Z",
        dtcAvailable=available,
        dtcUnavailableReason=reason,
    )


_UNREAD = dict(available=False, reason="not read yet")


# ---------------------------------------------------------------------------
# The rendered surface. Boots the SHIPPED carousel.js over the SHIPPED markup
# and resolves the SHIPPED stylesheet, because a correct `clearButtonView`
# proves nothing about what has a box on the panel.
# ---------------------------------------------------------------------------

_OPEN_DETAIL = [
    {"flush": 4},
    {"clickNth": {"selector": ".dtc-row", "index": 0}},
    {"flush": 2},
]


def _clearSurface(dtcState: Any, steps: list[dict[str, Any]] | None = None) -> dict:
    """Render `dtcState` and report the clear affordance as the operator meets it."""
    out = rh.runDashboard(routes={"/dtc": dtcState}, steps=steps or [{"flush": 4}])
    return _readClear(out)


def _readClear(out: dict) -> dict:
    surface = rh.dashboardSurface(out["tree"])
    zone = surface.pathById("dtc-clear-zone")
    button = surface.pathById("dtc-clear-btn")
    attrs = button[-1].get("attrs", {}) if button else {}
    text = ""
    if button:
        text = " ".join(
            child["text"].strip()
            for child in (button[-1].get("children") or [])
            if "text" in child
        )
    return {
        "rows": len(surface.pathsByClass("dtc-row")),
        "zonePaints": zone is not None and surface.rendered(zone),
        "buttonPaints": button is not None and surface.rendered(button),
        # `disabled` is a bare HTML attribute -- present or absent, never a value.
        # This is the fact no pure-function test of `clearButtonView` can witness.
        "disabled": "disabled" in attrs,
        "reason": attrs.get("data-reason"),
        "label": text,
    }


def _openThenPublish(later: Any) -> dict:
    """Open the detail on a CLEARABLE code, then let the producer publish `later`.

    Models the mid-session path: the operator is looking at a code detail when
    the DTC state underneath it changes. The flush after `setRoutes` is generous
    (20 rounds at the 4 Hz card tick) so a failure to re-gate cannot be mistaken
    for "the poll had not come round yet".
    """
    out = rh.runDashboard(
        routes={"/dtc": _state([_raw()])},
        steps=[*_OPEN_DETAIL, {"setRoutes": {"/dtc": later}}, {"flush": 20}],
    )
    return _readClear(out)


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL FIRST. Most assertions in this file are absences ("no zone",
# "no row", "hidden"), and an absence passes vacuously the moment the harness
# stops finding the element -- a renamed id or a probe crash would turn the
# whole file green while pinning nothing.
# ---------------------------------------------------------------------------


@_needsNode
def test_theHarnessActuallyReachesTheClearButton_negativeControl():
    """
    Given: every "the affordance is absent" assertion below fails open if the
           harness cannot reach the clear zone at all
    When: a genuinely clearable state is rendered and its code row tapped
    Then: the button paints, is NOT disabled, and carries its enabled label.

          This is also the only place in the repo that proves the enabled branch
          reaches a real <button> element rather than just a view object.
    """
    got = _clearSurface(_state([_raw()]), _OPEN_DETAIL)
    assert got["rows"] == 1, got
    assert got["zonePaints"], got
    assert got["buttonPaints"], got
    assert got["disabled"] is False, got
    assert got["reason"] == "ok", got
    assert got["label"] == _LABEL_ENABLED, got


# ---------------------------------------------------------------------------
# THE RECORDED PASS, part 1 -- the unread source offers no affordance at all.
# ---------------------------------------------------------------------------


@_needsNode
def test_unreadSource_offersNoCodeRowToOpenTheDetailWith():
    """
    Given: the live unread state -- source.dtc.available false, "not read yet"
    When: the dashboard renders
    Then: there is no `.dtc-row` to tap.

          Reachability is the FIRST gate and the one nobody wrote down: the
          clear button lives inside the per-code detail overlay, and the only
          taps that open it are a code row, the takeover's "View detail" and the
          ribbon. An unread state publishes no codes, forces newSinceTs to None
          (so the takeover cannot fire) and leaves the ribbon unpainted
          (US-629). All three doors are shut, and this pins the first one.
    """
    got = _clearSurface(_state([], **_UNREAD))
    assert got["rows"] == 0, got


@_needsNode
def test_unreadSource_clearZoneDoesNotPaintAndTheButtonStaysHidden():
    """
    Given: the same unread state
    When: the clear zone and button are resolved through the shipped stylesheet
    Then: neither has a box on the panel.

          Pinning WHY, because the why is not what it looks like: the zone is
          absent because the detail overlay was never opened, so
          `renderClearButton()` never ran and the markup's own `hidden` still
          stands. The gate function is not involved. That is a perfectly good
          guarantee -- it is the outermost one -- but it is a DIFFERENT
          guarantee from "the gate refuses", and the na-only test above is what
          covers the other.

          Asserted through `rendered()` rather than off the `hidden` attribute,
          because US-495 was exactly a case of correct JS defeated by a
          stylesheet the JS could not see -- and this zone in particular carries
          `display: flex` from the shared card shell, which outranks the UA
          `[hidden]` rule (test_dtc_detail_hierarchy.py:297 walked into that
          trap once already).
    """
    got = _clearSurface(_state([], **_UNREAD))
    assert got["zonePaints"] is False, got
    assert got["buttonPaints"] is False, got


@_needsNode
def test_allNaCodes_openTheDetailButOfferNoClearButton():
    """
    Given: a stored P1750 -- Solenoid Assembly (A/T), `na` on this manual car
    When: its row is tapped, so the detail overlay actually OPENS
    Then: the clear zone still does not paint.

          THE ONLY TEST IN THIS FILE THAT EXERCISES THE GATE FUNCTION. Every
          other absence here is won by reachability: no row, no overlay, no call
          to `renderClearButton()`. An all-`na` state is the one shape that
          renders a row AND resolves to `no_codes`, so it is the only way to ask
          the display mirror the question and see it answer.

          Measured, not assumed: with `clearGateReason` mutated to call an empty
          stored set `ok`, this is the test that dies -- the panel would offer an
          enabled CLEAR CODES over a transmission code that is not a fault on
          this car, and Mode 04 is all-or-nothing, so taking it would wipe every
          real code and freeze-frame with it.

          The severity comes from the SHIPPED table, not a fixture: `na` is
          Spool's classification of this code, and inventing it locally would
          make the test agree with itself.
    """
    got = _clearSurface(_state([_raw("P1750")], table=_shippedTable()), _OPEN_DETAIL)

    assert got["rows"] == 1, "the na code did not even render a row -- test is vacuous"
    assert got["zonePaints"] is False, got
    assert got["buttonPaints"] is False, got


@_needsNode
def test_genuineEmptyRead_alsoOffersNoAffordance_andLooksIdenticalToUnread():
    """
    Given: a read that COMPLETED and found nothing, versus the unread state
    When: both are rendered
    Then: the clear affordance is absent in both, identically.

          Recorded deliberately as a SAMENESS. US-629 had to prove these two
          states look DIFFERENT on the Alerts card, because there "unknown"
          painted as "clear" would be a lie. Here the honest answer is the same
          for both -- there is nothing to clear either way -- so the two
          collapsing is correct rather than a defect. Writing that down stops a
          future reader importing US-629's conclusion one card over.
    """
    unread = _clearSurface(_state([], **_UNREAD))
    cleanRead = _clearSurface(_state([]))
    assert unread["zonePaints"] is False and unread["buttonPaints"] is False, unread
    assert cleanRead == unread, (cleanRead, unread)


# ---------------------------------------------------------------------------
# THE RECORDED PASS, part 2 -- the story's NEGATIVE CASE on the rendered button.
# "Clearing a code nobody has read destroys evidence": the gate's own words for
# that are `logged` and `syncAcked`.
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(
    ("logged", "syncAcked", "what"),
    [
        (False, True, "captured but never written to the local log"),
        (True, False, "logged locally but never acked by the server"),
        (False, False, "neither logged nor acked"),
    ],
)
def test_storedCodeNobodyHasRecordedYet_theButtonIsDisabledAndSaysWhy(
    logged: bool, syncAcked: bool, what: str
):
    """
    Given: a stored MINOR code that is <what>
    When: the operator opens its detail
    Then: the button paints but is DISABLED, reasons `sync_pending`, and its
          label names the server sync.

          This is the story's negative case stated in the gate's vocabulary.
          The button is deliberately VISIBLE rather than hidden -- the operator
          is told the clear exists and why they cannot have it yet, which is the
          honest-instrument reading of S-6. The `disabled` attribute is the
          assertion with teeth: a view object saying enabled:false while the
          shipped <button> stays clickable is the exact two-halves failure this
          file's harness exists to catch.
    """
    got = _clearSurface(
        _state([_raw(logged=logged, syncAcked=syncAcked)]), _OPEN_DETAIL
    )
    assert got["buttonPaints"], got
    assert got["disabled"] is True, f"{what}: the button was still clickable -- {got}"
    assert got["reason"] == "sync_pending", got
    assert got["label"] == _LABEL_SYNC, got


@_needsNode
def test_stopCodePresent_theButtonIsDisabledWithTheSeverityReason():
    """
    Given: a clearable MINOR code sitting beside a STOP misfire
    When: the detail is opened
    Then: disabled, `severity_present`, and the label names the STOP/WATCH block.

          Mode 04 is all-or-nothing -- it wipes EVERY code, not the one on
          screen -- so the gate keys off the WHOLE stored set. Rendering the
          MINOR code's own detail must not offer a clear that would take the
          misfire's freeze-frame with it.
    """
    got = _clearSurface(_state([_raw(), _raw("P0301")]), _OPEN_DETAIL)
    assert got["disabled"] is True, got
    assert got["reason"] == "severity_present", got
    assert got["label"] == _LABEL_SEVERITY, got


@_needsNode
def test_sessionResetLock_theButtonIsDisabledWithTheDontChaseTheLightReason():
    """
    Given: a clearable code that already came back once this session
    When: the detail is opened
    Then: disabled, `session_locked`, and the label says clearing again will not
          fix it (S-8).
    """
    got = _clearSurface(_state([_raw()], lock=["P0442"]), _OPEN_DETAIL)
    assert got["disabled"] is True, got
    assert got["reason"] == "session_locked", got
    assert got["label"] == _LABEL_LOCKED, got


# ---------------------------------------------------------------------------
# THE COUPLING PIN -- the load-bearing test in this file.
#
# `clearGateReason` in carousel.js NEVER reads `source.dtc.available`. The clear
# affordance is gated on an unread source for one reason only: `buildDtcState`
# refuses to publish the caller's codes when the source is unavailable. Those two
# facts live in different files, in different languages, and no test joined them
# until now -- so deleting the emitter's guard would restore an enabled CLEAR
# CODES button over a source nobody read, with the whole DTC suite still green.
# ---------------------------------------------------------------------------


@_needsNode
def test_anUnavailableRead_emptiesTheCodesTheGateKeysOffAndTheAffordanceStaysAway():
    """
    Given: a caller that hands the emitter a perfectly clearable stored code --
           MINOR, logged, server-acked -- while the DTC source is UNAVAILABLE
    When: the state the producer actually publishes is rendered
    Then: `codes` was emptied, and no clear affordance reaches the panel.

          Composed on purpose: the producer's guard and the consumer's gate are
          asserted in ONE test, against ONE payload, because it is their JOIN
          that keeps the button away. Split into two green unit tests this
          guarantee is invisible -- which is how it has been shipping.
    """
    published = _state([_raw()], **_UNREAD)
    assert published["codes"] == [], published
    assert published["source"] == {
        "dtc": {"available": False, "reason": "not read yet"}
    }, published

    got = _clearSurface(published)
    assert got["rows"] == 0, got
    assert got["zonePaints"] is False, got
    assert got["buttonPaints"] is False, got


# ---------------------------------------------------------------------------
# THE AUTHORITATIVE GATE -- the half that actually protects the evidence.
#
# The renderer is a display mirror. The only thing standing between a tap and a
# Mode-04 wipe is `dtc_clear.performClear`, re-derived server-side from the
# server's OWN state file (states_http_server.py:397 -> 403 on refusal). These
# tests assert the RUNNER IS NEVER CALLED, not merely that a flag came back
# false: "no vehicle write happened" is the claim that matters, and a decision
# object cannot make it.
# ---------------------------------------------------------------------------


def test_performClear_onAnUnreadState_refusesAndNeverTouchesTheVehicle():
    """
    Given: the unread state as the producer publishes it
    When: a clear is submitted anyway (a stale kiosk, a replayed tap, F1 below)
    Then: it is refused as `no_codes` and the Mode-04 runner is NEVER invoked.

          This is why F1 is an affordance defect and not a safety hole, and it
          is the assertion that entitles this story to close as a pass.
    """
    calls: list[int] = []

    def runner() -> dict:
        calls.append(1)
        return {"stored": [], "pending": [], "mil": False}

    outcome = dtc_clear.performClear(_state([], **_UNREAD), clearRunner=runner)

    assert outcome.issued is False, outcome
    assert outcome.reason == dtc_clear.GATE_NO_CODES, outcome
    assert calls == [], "the Mode-04 runner was invoked over an unread source"


def test_performClear_onAClearableState_doesIssue_control():
    """
    Given: a genuinely clearable state
    When: a clear is submitted
    Then: it IS issued and the runner runs exactly once.

          Without this control the refusal test above is satisfied by a gate
          that refuses everything, which would pass while the feature is dead.
    """
    calls: list[int] = []

    def runner() -> dict:
        calls.append(1)
        return {"stored": [], "pending": [], "mil": False}

    outcome = dtc_clear.performClear(_state([_raw()]), clearRunner=runner)

    assert outcome.issued is True, outcome
    assert outcome.cleared is True, outcome
    assert calls == [1]


def test_performClear_ignoresATamperedClearGateFlagOnAnUnreadState():
    """
    Given: a state file whose published `clearGate` claims enabled:true while
           `source.dtc.available` is false and no codes were read
    When: the clear is submitted
    Then: still refused, runner still never called.

          S-10 / F-3 in the shape that matters for THIS story. The published
          block is the one field an attacker or a stale writer could forge, and
          F2 below shows it already disagrees with reality in normal operation
          -- so a gate that trusted it would be wrong even with nobody
          attacking it.
    """
    calls: list[int] = []

    def runner() -> dict:
        calls.append(1)
        return {"stored": [], "pending": [], "mil": False}

    tampered = _state([], **_UNREAD)
    tampered["clearGate"] = {"enabled": True, "reason": "ok"}

    outcome = dtc_clear.performClear(tampered, clearRunner=runner)

    assert outcome.issued is False, outcome
    assert calls == [], "a forged clearGate flag reached the vehicle"


# ---------------------------------------------------------------------------
# CHARACTERISATION -- F1: an open detail overlay never re-gates.
# RECORDED, NOT FIXED. See the header and I-us636. Whoever calls
# renderClearButton() from the poll will fail these ON PURPOSE.
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize(
    ("laterName", "later"),
    [
        ("source goes unread", _state([], available=False, reason="not read yet")),
        ("the state file vanishes", None),
        ("a STOP code appears", _state([_raw(), _raw("P0301")])),
        ("the session lock engages", _state([_raw()], lock=["P0442"])),
        ("the sync ack is withdrawn", _state([_raw(syncAcked=False)])),
    ],
)
def test_characterisation_anOpenDetailOverlayNeverRegates(laterName: str, later: Any):
    """
    Given: the operator has the detail open on a clearable code, and then <later>
    When: 20 further poll rounds elapse
    Then: the button STILL reads "CLEAR CODES", enabled, data-reason `ok`.

          All five changes move the gate in the UNSAFE direction and none of
          them reaches the button, because `renderClearButton()` is wired to
          `openDetail()` and to nothing else. Recorded as the measured fact, not
          endorsed: the correct behaviour is to re-gate, and the fix story is
          filed. The control below proves the gate itself is right and it is
          only the refresh that is missing -- which is what makes this a
          one-line-shaped fix rather than a gate rewrite.
    """
    got = _openThenPublish(later)
    assert got["buttonPaints"] is True, (laterName, got)
    assert got["disabled"] is False, (laterName, got)
    assert got["reason"] == "ok", (laterName, got)
    assert got["label"] == _LABEL_ENABLED, (laterName, got)


@_needsNode
def test_theGateItselfIsCorrectWhenTheOverlayOpensFresh_controlForF1():
    """
    Given: the SAME end state as the "a STOP code appears" case above, but
           present before the overlay is opened
    When: the detail is opened
    Then: the button is disabled with `severity_present`.

          The control that makes F1 diagnostic instead of vague: the gate reads
          the STOP correctly every time it is ASKED. The defect is that after
          `openDetail()` it is never asked again.
    """
    got = _clearSurface(_state([_raw(), _raw("P0301")]), _OPEN_DETAIL)
    assert got["disabled"] is True, got
    assert got["reason"] == "severity_present", got


# ---------------------------------------------------------------------------
# CHARACTERISATION -- F2: the published reason has no word for "unread".
# ---------------------------------------------------------------------------


def test_characterisation_thePublishedClearGateSaysOkForASourceNobodyRead():
    """
    Given: the unread state
    When: the published `clearGate` block is read, as Atlas read it off the Pi
    Then: it is exactly {enabled: False, reason: "ok"}.

          Atlas's punch-list 2.3 observation, pinned verbatim so the pass is
          evidence rather than memory -- and so the oddity in it is on the
          record. `ok` is this vocabulary's word for CLEARABLE; publishing it as
          the REASON for a refusal, over a source nobody has read, is punch-list
          2.1's defect class one field over.
    """
    assert _state([], **_UNREAD)["clearGate"] == {"enabled": False, "reason": "ok"}


def test_characterisation_threeDifferentTruthsAllPublishTheSameReason():
    """
    Given: an unread source, a completed clean read, and a clearable car
    When: each published `clearGate.reason` is compared
    Then: all three say `ok`, and only `enabled` separates the third.

          The first two are not even separated by `enabled` -- nothing in this
          block distinguishes "we have not looked" from "we looked and it is
          clean". That is the fact that makes the field misleading rather than
          merely terse.
    """
    unread = _state([], **_UNREAD)["clearGate"]
    cleanRead = _state([])["clearGate"]
    clearable = _state([_raw()])["clearGate"]

    assert unread["reason"] == cleanRead["reason"] == clearable["reason"] == "ok"
    assert unread == cleanRead, "unread and clean-read are indistinguishable here"
    assert clearable["enabled"] is True and unread["enabled"] is False


def test_characterisation_theEmitterVocabularyLacksTheNoCodesTheOthersHave():
    """
    Given: three implementations of one gate -- the emitter's published block,
           the authoritative `dtc_clear`, and carousel.js's display mirror
    When: the same unread state is put through the two Python ones
    Then: the authoritative gate says `no_codes` and the emitter says `ok`.

          Pinned as a DISAGREEMENT rather than as two separate expectations, so
          the day someone gives the emitter a `no_codes` member this test fails
          and points at the right line. `GATE_NO_CODES` is referenced from the
          real module, so deleting the word cannot make this pass.
    """
    unread = _state([], **_UNREAD)

    assert dtc_clear.evaluateClearGate(unread).reason == dtc_clear.GATE_NO_CODES
    assert dtc_clear.GATE_NO_CODES == "no_codes"
    assert unread["clearGate"]["reason"] == "ok"
    assert unread["clearGate"]["reason"] != dtc_clear.GATE_NO_CODES


# ---------------------------------------------------------------------------
# CHARACTERISATION -- F3: the shipped severity table and the live P0443.
#
# These read the REAL table off disk, so they are measurements of shipped data
# rather than of a fixture. That is the point: the question "can the operator
# ever clear a code on this car" has no fixture-shaped answer.
# ---------------------------------------------------------------------------


def _shippedTable() -> dict[str, dict]:
    table = loadP1xxxSeverityTable(_SHIPPED_TABLE_PATH)
    assert table, f"the shipped severity table parsed empty at {_SHIPPED_TABLE_PATH}"
    return table


def test_characterisation_theShippedSeverityTableContainsNoClearableTier():
    """
    Given: the severity table the orchestrator loads by default
    When: its tiers are counted
    Then: 7 `watch`, 5 `na`, and ZERO `minor`.

          The gate enables only when every stored non-`na` code is `minor`, so
          with this data the enabled branch is unreachable and CLEAR CODES can
          never light up on this car. Recorded as a number, per the sprint's
          "record the measurement, pass or fail" discipline -- re-record it when
          the table grows, do not delete it. The table's own line 41 says the
          clearable codes here are generic evap P0xxx and this table is
          P1xxx-only, so this is a known gap, not a parse failure.
    """
    tiers = [entry["severity"] for entry in _shippedTable().values()]

    assert tiers.count("minor") == 0, "a MINOR row appeared -- re-record F3"
    assert tiers.count("watch") == 7, tiers
    assert tiers.count("na") == 5, tiers


def test_characterisation_theLiveP0443_isRefusedAsIfItWereAStopOrWatch():
    """
    Given: P0443 -- stored on the car since 2026-08-20, MIL lit -- enriched by
           the SHIPPED table, which has no entry for it
    When: the gate runs and the detail is rendered
    Then: severity degrades honestly to `unknown`, the gate refuses with
          `severity_present`, and the button reads "a STOP/WATCH code is
          present" -- which the code is not.

          Refusing is CORRECT: never clear what you could not classify. The
          words are not. The tier vocabulary has an `unknown` presentation
          already (carousel.js DTC_TIER -> "GET DIAGNOSED"); the clear gate has
          no matching reason, so it borrows one that names two tiers the code
          does not hold. Python-only assertions here so the measurement survives
          on a node-less box; the rendered label is pinned in the sibling test.
    """
    table = _shippedTable()
    assert "P0443" not in table

    state = _state([_raw("P0443")], table=table)

    assert state["codes"][0]["severity"] == "unknown", state["codes"]
    assert state["clearGate"] == {"enabled": False, "reason": "severity_present"}
    assert dtc_clear.evaluateClearGate(state).reason == dtc_clear.GATE_SEVERITY


@_needsNode
def test_characterisation_theLiveP0443_rendersTheStopWatchLabelOnThePanel():
    """
    Given: the same P0443 state through the shipped table
    When: the operator opens its detail on the panel
    Then: the button is disabled and reads the STOP/WATCH label verbatim.

          The rendered half of F3 -- the words the driver actually reads about
          the code that is actually on their car.
    """
    got = _clearSurface(_state([_raw("P0443")], table=_shippedTable()), _OPEN_DETAIL)

    assert got["disabled"] is True, got
    assert got["reason"] == "severity_present", got
    assert got["label"] == _LABEL_SEVERITY, got

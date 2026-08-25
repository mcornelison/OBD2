################################################################################
# File Name: test_render_regression.py
# Purpose/Description: US-499 (S6, F-121) -- THE RENDER-REGRESSION BACKSTOP.
#   The permanent guard against the "unit-green but broken on hardware" defect
#   class that cost Sprint 66 three stories (A-16 lesson).
#
#   WHAT IT PROVES, and why the existing suites could not:
#     S1 (US-494, splash pinned at "not ready (starting)") -- every unit test of
#         computeBootState passed, because computeBootState was right. The bug
#         was that the payload the PRODUCTION WIRING emits never reached healthy,
#         so boot-state-poll.js never called window.close(). Only an end-to-end
#         run (real emitter -> real payload -> real splash JS) sees it.
#     S2 (US-495, six overlays painting at once) -- the JS was right and the
#         stylesheet ignored it. Only resolving the REAL cascade over the REAL
#         post-JS DOM sees it.
#     US-496's flagged gap -- the page dots are CREATED BY JS, so no static
#         markup sweep can ever cover them. Here they are created by the real
#         carousel.js and then rendered through the real stylesheet.
#
#   HOW IT IS PROVEN RED (AC-2). Each guard has a partner test that runs the
#   SAME harness against the PRE-FIX artifact and asserts the defect is
#   REPORTED: the pre-US-495 stylesheet from git, and the pre-US-494 emitter
#   from git, both loaded as real historical code. Where git history is
#   unavailable the pre-fix pair skips honestly -- so a MUTATION proof (delete
#   the guard rule from the current sheet) runs unconditionally alongside it and
#   keeps the backstop self-verifying with no dependency on history at all.
#
#   FIDELITY LIMIT (stated per the story's conditionalOutcome): this resolves
#   the CASCADE, not LAYOUT. It answers "does this element have a box" -- it
#   cannot see overflow, wrapping, or an element pushed off-screen. That is the
#   S1/S2/US-496-dots defect class exactly, and nothing wider. The remaining
#   gap needs a real kiosk smoke on the Pi; see the on-Pi gate in the story.
#   The harness refuses to guess: tests/ui/render_harness.py reports any
#   `display` rule it cannot statically resolve, and
#   test_harnessCanJudgeEveryDisplayRule fails when one appears.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-499 S6 render-regression backstop.
# ================================================================================
################################################################################

"""US-499 render-regression backstop: real JS + real CSS, resolved together."""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_NODE_ONLY = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- the render backstop runs the shipped browser JS",
)

# The five full-screen overlays + the persistent ribbon: everything on the
# dashboard that can paint OVER a card. Named explicitly so deleting one from
# the markup fails loudly instead of shrinking the sweep to nothing.
_OVERLAY_IDS = [
    "dtc-takeover",
    "setup-menu",
    "confirm-modal",
    "dtc-detail",
    "clear-confirm",
]
_RIBBON_ID = "dtc-ribbon"

# The commits that fixed S2 and S1. Their PARENT holds the defective artifact.
_US495_FIX_COMMIT = "be8084e"
_US494_FIX_COMMIT = "13e0b84"


# --- fixtures ---------------------------------------------------------------


def _sysState(obdAvailable: bool = False) -> dict:
    """A system-status payload (US-400 / Atlas A-3 schema) + the US-496 gate."""
    return {
        "obdLink": {"state": "linked" if obdAvailable else "down", "retries": 0, "lastSeenS": 2},
        "sync": {"lastOkTs": "2026-07-29T09:41:50Z", "rows": 50, "pending": 0, "stale": False},
        "power": {"mode": "car", "source": "external"},
        "drive": {"state": "idle", "driveId": None},
        "source": {"obd": {"available": obdAvailable}},
        "idle": True,
        "ts": "2026-07-29T09:42:00Z",
    }


def _cleanRoutes(obdAvailable: bool = False) -> dict:
    """A bench Pi with no stored codes -- the state the CIO sees most days."""
    return {
        "/system-status": _sysState(obdAvailable),
        "/battery-health": {
            "soc": 88,
            "vcell": 4.02,
            "crate": -1.2,
            "ts": "2026-07-29T09:42:00Z",
        },
        "/light": {"lux": 120.0, "ts": "2026-07-29T09:42:00Z"},
        "/dtc": {"codes": [], "newSinceTs": None, "ts": "2026-07-29T09:42:00Z"},
        "/ltft-trend": None,
    }


def _newStopCodeRoutes() -> dict:
    """One NEW stop-severity code -- the takeover's firing condition."""
    routes = _cleanRoutes()
    routes["/dtc"] = {
        "codes": [
            {
                "code": "P0301",
                "severity": "stop",
                "short": "Cylinder 1 misfire detected",
                "logged": True,
                "syncAcked": True,
            }
        ],
        "newSinceTs": "2026-07-29T09:41:00Z",
        "ts": "2026-07-29T09:42:00Z",
    }
    return routes


def _gitShow(ref: str) -> str | None:
    """The historical file at ``ref``, or None when history is unavailable."""
    try:
        completed = subprocess.run(
            ["git", "show", ref],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=rh._REPO,
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return completed.stdout if completed.returncode == 0 else None


# --- the overlay guard (S2) -------------------------------------------------


@_NODE_ONLY
class TestOverlayRender:
    """Only the intended overlay paints -- resolved through the real cascade."""

    def test_benchDashboardWithNoCodes_paintsNoOverlayAtAll(self):
        """
        Given: the shipped dashboard, booted by the shipped carousel.js, with a
               clean bench state (no stored DTC)
        When: the real stylesheet is resolved over the resulting DOM
        Then: not one full-screen overlay -- and not the ribbon -- has a box

        This is the CIO's actual complaint rendered as an assertion: the idle
        carousel must be clean and clickable, not a stack of half-boxes.
        """
        dom = rh.runDashboard(routes=_cleanRoutes())
        surface = rh.dashboardSurface(dom["tree"])
        painted = surface.renderedIds([*_OVERLAY_IDS, _RIBBON_ID])
        assert painted == [], (
            "these overlays paint over the idle carousel with no code present: "
            f"{painted}"
        )

    def test_aNewStopCode_paintsExactlyOneOverlay(self):
        """
        Given: a NEW stop-severity code in the polled `dtc` state
        When: the real poll drives the real takeover surface
        Then: the takeover paints and NO other overlay does

        "One takeover at a time" is a design invariant (carousel.js §takeover
        view); this is the first test that checks it against what is PAINTED
        rather than against what the JS intended.
        """
        dom = rh.runDashboard(routes=_newStopCodeRoutes())
        surface = rh.dashboardSurface(dom["tree"])
        assert surface.renderedIds(_OVERLAY_IDS) == ["dtc-takeover"]
        # The ribbon is a persistent band, not an overlay: it SHOULD ride along.
        assert surface.renderedIds([_RIBBON_ID]) == [_RIBBON_ID]

    def test_viewDetail_swapsTheTakeoverForTheDetail(self):
        """
        Given: the takeover is up
        When: the operator taps "View detail ›"
        Then: exactly one overlay still paints -- and it is the detail

        The S2 symptom was overlays STACKING. Navigating between two of them is
        where a stack would show up, so the count is the assertion, not just the
        identity.
        """
        dom = rh.runDashboard(
            routes=_newStopCodeRoutes(),
            steps=[{"flush": 3}, {"click": "takeover-detail"}, {"flush": 1}],
        )
        surface = rh.dashboardSurface(dom["tree"])
        assert surface.renderedIds(_OVERLAY_IDS) == ["dtc-detail"]

    def test_dismiss_returnsToACleanCarousel(self):
        """
        Given: the takeover is up
        When: the operator dismisses it
        Then: no overlay paints -- the operator is never trapped behind one
        """
        dom = rh.runDashboard(
            routes=_newStopCodeRoutes(),
            steps=[{"flush": 3}, {"click": "takeover-dismiss"}, {"flush": 1}],
        )
        surface = rh.dashboardSurface(dom["tree"])
        assert surface.renderedIds(_OVERLAY_IDS) == []


@_NODE_ONLY
class TestOverlayGuardIsRed:
    """The backstop must FAIL on the broken surface, or it guards nothing."""

    def test_preFixStylesheet_paintsEveryOverlayAtOnce(self):
        """
        Given: the REAL pre-US-495 stylesheet, read from git history
        When: the same clean-bench DOM is resolved against it
        Then: the backstop reports the overlays painting simultaneously

        AC-2's literal discharge: RED against the pre-fix code, GREEN after.
        The DOM is produced by the CURRENT carousel.js on purpose -- the JS was
        never wrong, and holding it fixed isolates the stylesheet as the defect.
        """
        css = _gitShow(f"{_US495_FIX_COMMIT}^:src/pi/ui/dashboard/dashboard.css")
        if css is None:
            pytest.skip(
                f"pre-fix blob {_US495_FIX_COMMIT}^ unreachable (shallow clone?) -- "
                "the mutation proof below covers this guard unconditionally"
            )
        dom = rh.runDashboard(routes=_cleanRoutes())
        surface = rh.Surface(dom["tree"], css)
        painted = surface.renderedIds([*_OVERLAY_IDS, _RIBBON_ID])
        assert painted == [*_OVERLAY_IDS, _RIBBON_ID], (
            "the pre-US-495 stylesheet must reproduce the stacked-overlay bug; "
            f"this harness only saw {painted} paint, so it would not have caught it"
        )

    def test_deletingTheGuardRule_bringsTheOverlaysBack(self):
        """
        Given: the CURRENT stylesheet with the `[hidden]` guard rule removed
        When: the same clean-bench DOM is resolved against it
        Then: the overlays paint again

        A mutation proof, and the one that never skips: it needs no git history,
        and it pins the guard as LOAD-BEARING rather than incidental. Deleting
        that one line is the whole of the US-495 regression.
        """
        with open(os.path.join(rh.DASHBOARD_DIR, "dashboard.css"), encoding="utf-8") as fh:
            css = fh.read()
        mutated = css.replace("[hidden] { display: none !important; }", "")
        assert mutated != css, (
            "the guard rule is no longer present verbatim in dashboard.css -- "
            "this mutation test must be re-aimed at whatever replaced it"
        )
        dom = rh.runDashboard(routes=_cleanRoutes())
        painted = rh.Surface(dom["tree"], mutated).renderedIds(_OVERLAY_IDS)
        assert painted == _OVERLAY_IDS, (
            "removing the [hidden] guard must make every overlay paint; it only "
            f"revived {painted}, so the guard is not what is holding them back"
        )

    def test_theImportanceOfTheGuardIsWhatWins(self):
        """
        Given: the guard rule stripped of its `!important`
        Then: the ID-selector `display: flex` wins again and the overlays paint

        US-496 flagged this as the fragility: the win is on IMPORTANCE, not
        specificity, so a plain-looking edit re-opens the bug. Pin it.
        """
        with open(os.path.join(rh.DASHBOARD_DIR, "dashboard.css"), encoding="utf-8") as fh:
            css = fh.read()
        weakened = css.replace(
            "[hidden] { display: none !important; }", "[hidden] { display: none; }"
        )
        assert weakened != css
        dom = rh.runDashboard(routes=_cleanRoutes())
        painted = rh.Surface(dom["tree"], weakened).renderedIds(_OVERLAY_IDS)
        assert painted == _OVERLAY_IDS, (
            "without !important an ID selector outranks the guard -- if this "
            "passes, the guard is winning some other way and the comment in "
            "dashboard.css is now wrong"
        )


# --- the vehicle-gate geometry (US-496's flagged gap) -----------------------


@_NODE_ONLY
class TestVehicleGateRender:
    """The JS-CREATED page dots, rendered through the real cascade.

    US-496 called this out explicitly: the static markup sweep in
    test_dashboard_overlay_hidden_guard.py can only enumerate elements the
    MARKUP ships `hidden`, and every page dot is built by carousel.js at boot.
    """

    def _visibleCards(self, surface: rh.Surface) -> list[str]:
        return [
            (path[-1]["attrs"].get("aria-label") or "?")
            for path in surface.pathsByClass("card")
            if surface.rendered(path)
        ]

    def _visibleDots(self, surface: rh.Surface) -> int:
        return sum(1 for path in surface.pathsByClass("dot") if surface.rendered(path))

    def _gatedFlag(self, surface: rh.Surface) -> str | None:
        """The rendered `data-gated` of the fuel-trim surface, or None if it did
        not paint at all.

        US-540-b: that surface is a CARD again (the merged Health card retired),
        so it is located by its aria-label rather than the section class the
        merge gave it. The flag itself is unchanged -- it is the one thing a
        pure-function test cannot see, which is why it is read here.
        """
        for path in surface.pathsByClass("card"):
            if not surface.rendered(path):
                continue
            if path[-1]["attrs"].get("aria-label") == "Fuel Trim":
                return path[-1]["attrs"].get("data-gated")
        return None

    def test_dotsMatchVisibleCards_onABench(self):
        """
        Given: a bench Pi -- system-status reports source.obd.available false
        Then: exactly one page dot paints per visible card

        A dot that navigates nowhere is a dead affordance, and the dot/card
        geometry is the one thing the visible-index math could get wrong in a
        way no pure-function test sees. US-507 removed the last vehicle-gated
        CARD (fuel trim is now a section), so this no longer varies with the
        gate -- but the geometry it guards is exactly as load-bearing, and
        US-508 re-introduces a slot swap on top of it.
        """
        dom = rh.runDashboard(routes=_cleanRoutes(obdAvailable=False))
        surface = rh.dashboardSurface(dom["tree"])
        cards = self._visibleCards(surface)
        assert cards, "no cards painted at all"
        assert self._visibleDots(surface) == len(cards), (
            f"{self._visibleDots(surface)} dots for {len(cards)} visible cards {cards}"
        )

    def test_benchWithNoVehicle_paintsTheFuelTrimGateNotAReading(self):
        """
        Given: a bench Pi -- system-status reports source.obd.available false
        Then: the Health card paints, and its fuel-trim section paints GATED

        REPLACES the old "the LTFT card does not paint" assertion, which US-507
        made vacuous: with no card by that name, `"LTFT Trend" not in cards` is
        true for the wrong reason and would keep passing if the gate broke
        entirely. The gate has to be asserted POSITIVELY, on the surface that
        actually carries it -- which US-540-b made a card again.
        """
        dom = rh.runDashboard(routes=_cleanRoutes(obdAvailable=False))
        surface = rh.dashboardSurface(dom["tree"])
        assert "Fuel Trim" in self._visibleCards(surface), (
            "the Fuel Trim card did not paint"
        )
        assert self._gatedFlag(surface) == "true", (
            "a bench with no vehicle must paint the fuel-trim GATE, not a trim"
        )

    def test_vehicleConnected_opensTheFuelTrimCard(self):
        """
        Given: system-status reports an available OBD source (a car is plugged in)
        Then: the fuel-trim card is no longer gated

        The inverse of the test above -- without it, "always gate" would pass.
        This is the on-Pi check the story owes, done headless.
        """
        dom = rh.runDashboard(routes=_cleanRoutes(obdAvailable=True))
        surface = rh.dashboardSurface(dom["tree"])
        assert self._gatedFlag(surface) == "false", (
            "the fuel-trim section stayed gated with a vehicle connected"
        )


# --- the splash handoff (S1) ------------------------------------------------


def _fakeSystemctl(monkeypatch, states: dict[str, str]) -> None:
    """Answer `systemctl is-active` from ``states``; delegate everything else.

    Patching subprocess.run (rather than injecting a query function) keeps the
    REAL _queryServiceState code path -- argv, stdout.strip(), the lot -- under
    test. Anything that is not systemctl still runs for real, because this same
    process shells out to node for the splash probe.
    """
    realRun = subprocess.run

    def fakeRun(cmd, *args, **kwargs):
        if isinstance(cmd, list) and cmd[:2] == ["systemctl", "is-active"]:
            return types.SimpleNamespace(
                returncode=0, stdout=states.get(cmd[2], "inactive") + "\n", stderr=""
            )
        return realRun(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", fakeRun)


_EMIT_INTERVAL_S = 0.5  # eclipse-boot-state.service --poll-ms default


def _emitSequence(module, buildFn, count: int) -> list[dict]:
    """``count`` successive emissions, the clock advancing one EMIT interval each.

    Feeding the splash a real SEQUENCE rather than one frozen payload is what
    lets the emitter's OWN hard-cap branch fire, so the degraded reason under
    test is the one the CIO actually read off the panel -- not the splash's
    generic fallback.

    Two subtleties, both learned the hard way writing this:
      * The emitter latches ``startMono`` in its CONSTRUCTOR, so the fake clock
        must be installed BEFORE ``buildFn()`` -- otherwise elapsed() is
        (fake now - real boot time), a large negative, and no hard cap can ever
        fire. Its production elapsedFn reads this clock, so the wiring under
        test stays untouched.
      * The clock is restored before returning. ``time.monotonic`` is global and
        this same process shells out to node moments later; leaving a
        counterfeit clock under subprocess's timeout bookkeeping is how a
        harness starts producing bugs of its own.
    """
    clock = {"t": -_EMIT_INTERVAL_S}

    def fakeMonotonic() -> float:
        clock["t"] += _EMIT_INTERVAL_S
        return clock["t"]

    realMonotonic = module.time.monotonic
    module.time.monotonic = fakeMonotonic
    try:
        emitter = buildFn()
        return [emitter.runOnce() for _ in range(count)]
    finally:
        module.time.monotonic = realMonotonic


@_NODE_ONLY
class TestSplashHandoff:
    """The boot splash reaches the dashboard on a core-up, no-vehicle boot."""

    def test_coreUpWithNoVehicle_splashHandsOffToTheDashboard(self, tmp_path, monkeypatch):
        """
        Given: the PRODUCTION wiring (buildEmitter -- what the systemd unit runs)
               on a bench Pi: core units active, dashboard installed, NO vehicle
        When: the shipped boot-state-poll.js consumes what it emits
        Then: the splash calls window.close() -- the A-1 OnSuccess handoff

        This is US-494's acceptance, automated. Note what it exercises that no
        unit test did: buildEmitter's ARGUMENT LIST. The defect was a dependency
        the entry point never passed, and only the real wiring shows that.
        """
        import pi.splash.boot_state_emitter as bse

        _fakeSystemctl(
            monkeypatch,
            {
                "eclipse-states-http": "active",
                "eclipse-powerwatch": "active",
                "boot-progress-finalize": "active",
                "eclipse-obd": "inactive",  # no car on the bench
            },
        )
        asset = tmp_path / "dashboard.html"
        asset.write_text("<html></html>", encoding="utf-8")
        states = _emitSequence(
            bse,
            lambda: bse.buildEmitter(
                statesDir=str(tmp_path / "states"),
                hardCapSeconds=12.0,
                uiAssetPath=str(asset),
            ),
            4,
        )

        result = rh.runSplash(states)
        assert result["handoff"], (
            "the splash never handed off -- it would sit on the boot screen "
            f"until reboot. degraded={result['degraded']} "
            f"msg={result['degradedMsg']!r} payload={states[-1]}"
        )
        assert not result["degraded"]
        assert states[-1]["obdTier"] == "not-probed"
        assert states[-1]["uiAssets"] == "present"

    def test_aFailedCoreService_stillHoldsTheSplash(self, tmp_path, monkeypatch):
        """
        Given: a genuinely broken core boot (eclipse-states-http failed)
        Then: the splash degrades and does NOT hand off

        The honest-instrument half of US-494 (AC-3), and the control that keeps
        the test above meaningful: a backstop that only ever asserts "handoff"
        would pass just as well on a blanket force-healthy.
        """
        import pi.splash.boot_state_emitter as bse

        _fakeSystemctl(
            monkeypatch,
            {
                "eclipse-states-http": "failed",
                "eclipse-powerwatch": "active",
                "boot-progress-finalize": "active",
                "eclipse-obd": "inactive",
            },
        )
        asset = tmp_path / "dashboard.html"
        asset.write_text("<html></html>", encoding="utf-8")
        states = _emitSequence(
            bse,
            lambda: bse.buildEmitter(
                statesDir=str(tmp_path / "states"),
                hardCapSeconds=12.0,
                uiAssetPath=str(asset),
            ),
            4,
        )
        result = rh.runSplash(states)
        assert not result["handoff"], "a failed core service must not yield the splash"
        assert result["degraded"]
        assert "eclipse-states-http" in result["degradedMsg"]

    def test_missingDashboardAssets_holdTheSplash(self, tmp_path, monkeypatch):
        """
        Given: every core unit is active but the dashboard was never installed
        Then: the splash holds and NAMES the reason

        A-16: handing off to a dashboard that is not there is the blank screen.
        Better a held splash with a message than a black panel.
        """
        import pi.splash.boot_state_emitter as bse

        _fakeSystemctl(
            monkeypatch,
            {
                "eclipse-states-http": "active",
                "eclipse-powerwatch": "active",
                "boot-progress-finalize": "active",
                "eclipse-obd": "inactive",
            },
        )
        states = _emitSequence(
            bse,
            lambda: bse.buildEmitter(
                statesDir=str(tmp_path / "states"),
                hardCapSeconds=12.0,
                uiAssetPath=str(tmp_path / "never-installed" / "dashboard.html"),
            ),
            4,
        )
        result = rh.runSplash(states)
        assert not result["handoff"]
        assert "dashboard assets" in result["degradedMsg"]


@_NODE_ONLY
class TestSplashGuardIsRed:
    """The splash guard must FAIL on the pre-US-494 emitter."""

    def test_preFixEmitter_pinsTheSplashOnTheBench(self, tmp_path, monkeypatch):
        """
        Given: the REAL pre-US-494 emitter from git, wired the way its own
               systemd entry point wired it (no obdProbeFn injected)
        When: a bench boot with every core unit active and NO vehicle
        Then: the splash never hands off, and the reason names eclipse-obd

        AC-2's literal discharge for S1. This reproduces the exact panel the CIO
        was looking at: "eclipse-obd: not ready (starting)", held until reboot,
        on a Pi whose core services were all perfectly healthy.
        """
        source = _gitShow(f"{_US494_FIX_COMMIT}^:src/pi/splash/boot_state_emitter.py")
        if source is None:
            pytest.skip(
                f"pre-fix blob {_US494_FIX_COMMIT}^ unreachable (shallow clone?)"
            )
        oldPath = tmp_path / "old_boot_state_emitter.py"
        oldPath.write_text(source, encoding="utf-8")
        spec = importlib.util.spec_from_file_location("old_boot_state_emitter", oldPath)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        _fakeSystemctl(
            monkeypatch,
            {
                "eclipse-states-http": "active",
                "eclipse-powerwatch": "active",
                "boot-progress-finalize": "active",
                "eclipse-obd": "active",  # the UNIT is up; the vehicle is not
            },
        )
        # The pre-fix production wiring: states dir + hard cap, and NOTHING
        # else. That omission -- no obdProbeFn -- IS the bug.
        # 30 emissions x 500 ms = 15 s of boot -- past BOTH the emitter's 12 s
        # hard cap and the splash's, so the verdict is settled, not still open.
        states = _emitSequence(
            module,
            lambda: module.BootStateEmitter(
                statesDir=str(tmp_path / "states"), hardCapSeconds=12.0
            ),
            30,
        )

        result = rh.runSplash(states)
        assert not result["handoff"], (
            "the pre-US-494 emitter must pin the splash; this harness let it "
            "hand off, so it would not have caught S1"
        )
        assert "eclipse-obd" in result["degradedMsg"], (
            "the pre-fix splash should degrade naming the OBD tier -- got "
            f"{result['degradedMsg']!r}"
        )


# --- the harness's own honesty ----------------------------------------------


@_NODE_ONLY
class TestHarnessFidelity:
    """Guards on the guard: a lenient render test is worse than none."""

    def test_harnessCanJudgeEveryDisplayRule(self):
        """
        Given: the shipped dashboard + splash stylesheets
        Then: no `display` rule uses state this harness cannot resolve

        A skipped rule makes every test above LENIENT (falsely green), which is
        the one failure mode a backstop must not have. If this goes red, the
        stylesheet grew a `display` behind a dynamic pseudo-class -- teach the
        resolver or move that rule, do not delete this test.
        """
        dom = rh.runDashboard(routes=_cleanRoutes())
        for name, surface in (
            ("dashboard.css", rh.dashboardSurface(dom["tree"])),
            ("styles.css", rh.splashSurface(rh.parseMarkup(
                os.path.join(rh.SPLASH_DIR, "index.html")
            ))),
        ):
            unresolvable = surface.unresolvableDisplaySelectors()
            assert unresolvable == [], (
                f"{name} declares `display` behind selectors the render backstop "
                f"cannot evaluate, so those rules are silently ignored: {unresolvable}"
            )

    def test_theRealJsActuallyRan(self):
        """
        Given: a probe run over the shipped markup
        Then: the DOM carries artefacts only carousel.js could have produced

        Cheap insurance against the worst failure mode here: a harness that
        silently no-ops (a JS error swallowed, the DOM block skipped) would make
        every "nothing paints" assertion above pass for the wrong reason.
        """
        dom = rh.runDashboard(routes=_cleanRoutes())
        surface = rh.dashboardSurface(dom["tree"])
        assert surface.pathsByClass("dot"), "no page dots -- carousel.js setup() never ran"
        stage = surface.pathById("stage")
        assert stage is not None and (stage[-1].get("style") or {}).get("--scale"), (
            "the letterbox scale was never applied -- the DOM wiring did not run"
        )
        assert any(
            f["url"] == "/system-status" for f in dom["fetches"]
        ), "the availability poll never fetched a state file"

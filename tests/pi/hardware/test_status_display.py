################################################################################
# File Name: test_status_display.py
# Purpose/Description: Tests for StatusDisplay GL BadAccess fix + canvas sizes
# Author: Ralph Agent
# Creation Date: 2026-04-19
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-19    | Ralph Agent  | US-198: TD-024 GL BadAccess under X11 -- force
#               |              | software renderer via SDL env hints + graceful
#               |              | init failure path
# 2026-05-01    | Rex          | US-257: parameterize over canvas sizes
#               |              | (1920x1080 / 1280x720 / 480x320). Covers:
#               |              | StatusDisplay accepts the full HDMI canvas,
#               |              | renders without raising at each size, exposes
#               |              | the computed DashboardLayout, and routes
#               |              | updateShutdownStage through to the data lock.
# ================================================================================
################################################################################

"""
Tests for StatusDisplay GL BadAccess fix (US-198 / TD-024).

Verifies:
- _initializePygame sets SDL software-renderer env hints BEFORE pygame.init().
- _initializePygame returns False gracefully when pygame.display.set_mode raises.
- start() returns False (never raises) when init fails.
- The forceSoftwareRenderer flag is honored (True default, False skips env hints).
- Env hints are set at the process level (os.environ) not as pygame args.

Reference:
- offices/pm/tech_debt/TD-024-status-display-gl-badaccess-x11.md
- Session 23 crash signature: "Could not make GL context current: BadAccess"
"""

import os
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from pi.hardware.status_display import StatusDisplay

# ================================================================================
# Fixtures
# ================================================================================


@pytest.fixture
def fakePygame():
    """
    Build a minimal pygame stand-in the status_display module accepts.

    Returns a (module, recorder) tuple. The recorder captures set_mode args and
    the snapshot of SDL env vars at pygame.init() call time -- so a test can
    assert env hints are set BEFORE init, which is the pygame/SDL2 contract.
    """
    fake = ModuleType("pygame")
    recorder: dict = {
        "envAtInit": None,
        "setModeCalls": [],
        "flipCalls": 0,
        "initCalled": False,
    }

    def fakeInit():
        recorder["initCalled"] = True
        recorder["envAtInit"] = {
            "SDL_RENDER_DRIVER": os.environ.get("SDL_RENDER_DRIVER"),
            "SDL_VIDEO_X11_FORCE_EGL": os.environ.get("SDL_VIDEO_X11_FORCE_EGL"),
            "SDL_FRAMEBUFFER_ACCELERATION": os.environ.get(
                "SDL_FRAMEBUFFER_ACCELERATION"
            ),
        }

    def fakeSetMode(size, flags=0):
        recorder["setModeCalls"].append((size, flags))
        return MagicMock(name="Surface")

    def fakeFlip():
        recorder["flipCalls"] += 1

    fake.NOFRAME = 0x80
    fake.QUIT = 256
    fake.init = fakeInit
    fake.quit = lambda: None
    fake.error = RuntimeError  # pygame.error is a RuntimeError subclass at runtime

    fontModule = ModuleType("pygame.font")
    fontModule.init = lambda: None
    fontModule.SysFont = lambda name, size, bold=False: MagicMock(
        name=f"Font({name},{size})"
    )
    fontModule.Font = lambda path, size: MagicMock(name=f"Font({path},{size})")
    fake.font = fontModule

    displayModule = ModuleType("pygame.display")
    displayModule.set_mode = fakeSetMode
    displayModule.set_caption = lambda s: None
    displayModule.flip = fakeFlip
    fake.display = displayModule

    eventModule = ModuleType("pygame.event")
    eventModule.get = lambda: []
    fake.event = eventModule

    mouseModule = ModuleType("pygame.mouse")
    mouseModule.set_visible = lambda v: None
    fake.mouse = mouseModule

    drawModule = ModuleType("pygame.draw")
    drawModule.circle = lambda *a, **kw: None
    drawModule.rect = lambda *a, **kw: None
    fake.draw = drawModule

    return fake, recorder


@pytest.fixture
def pygameInModuleRegistry(fakePygame, monkeypatch):
    """Register the fake pygame under sys.modules so `import pygame` resolves it."""
    fake, recorder = fakePygame
    monkeypatch.setitem(sys.modules, "pygame", fake)
    monkeypatch.setitem(sys.modules, "pygame.font", fake.font)
    monkeypatch.setitem(sys.modules, "pygame.display", fake.display)
    monkeypatch.setitem(sys.modules, "pygame.event", fake.event)
    monkeypatch.setitem(sys.modules, "pygame.mouse", fake.mouse)
    monkeypatch.setitem(sys.modules, "pygame.draw", fake.draw)
    return fake, recorder


@pytest.fixture
def clearSdlEnv(monkeypatch):
    """Scrub SDL_* env vars so tests see a clean slate."""
    for key in (
        "SDL_RENDER_DRIVER",
        "SDL_VIDEO_X11_FORCE_EGL",
        "SDL_FRAMEBUFFER_ACCELERATION",
        "SDL_VIDEODRIVER",
    ):
        monkeypatch.delenv(key, raising=False)


# ================================================================================
# forceSoftwareRenderer -- constructor contract
# ================================================================================


class TestForceSoftwareRendererContract:
    """The forceSoftwareRenderer arg is the US-198 affordance. Default: True."""

    def test_init_defaultValue_isTrue(self):
        """
        Given: StatusDisplay constructed with no explicit forceSoftwareRenderer
        When:  reading the flag back
        Then:  it is True -- default safety for X11 environments.
        """
        display = StatusDisplay()
        assert display.forceSoftwareRenderer is True

    def test_init_explicitFalse_isHonored(self):
        """
        Given: StatusDisplay(forceSoftwareRenderer=False)
        When:  reading the flag back
        Then:  False is preserved -- advanced users can opt out.
        """
        display = StatusDisplay(forceSoftwareRenderer=False)
        assert display.forceSoftwareRenderer is False


# ================================================================================
# _initializePygame -- SDL env hints set BEFORE pygame.init
# ================================================================================


class TestInitializePygameEnvHints:
    """SDL env hints must be set before pygame.init() to steer SDL2 to software."""

    def test_initializePygame_forceSoftwareTrue_setsEnvBeforeInit(
        self, pygameInModuleRegistry, clearSdlEnv
    ):
        """
        Given: forceSoftwareRenderer=True and SDL env is clean
        When:  _initializePygame runs
        Then:  pygame.init sees SDL_RENDER_DRIVER=software +
               SDL_VIDEO_X11_FORCE_EGL=0 + SDL_FRAMEBUFFER_ACCELERATION=0.
               This is the pygame/SDL2 contract -- hints after init are ignored.
        """
        _, recorder = pygameInModuleRegistry
        display = StatusDisplay(forceSoftwareRenderer=True)
        display._isAvailable = True  # Force pygame path on non-Pi host

        result = display._initializePygame()

        assert result is True
        assert recorder["initCalled"] is True
        envAtInit = recorder["envAtInit"]
        assert envAtInit["SDL_RENDER_DRIVER"] == "software"
        assert envAtInit["SDL_VIDEO_X11_FORCE_EGL"] == "0"
        assert envAtInit["SDL_FRAMEBUFFER_ACCELERATION"] == "0"

    def test_initializePygame_forceSoftwareFalse_doesNotSetEnvHints(
        self, pygameInModuleRegistry, clearSdlEnv
    ):
        """
        Given: forceSoftwareRenderer=False and SDL env is clean
        When:  _initializePygame runs
        Then:  No SDL_* hints are injected -- user keeps whatever env they chose.
        """
        _, recorder = pygameInModuleRegistry
        display = StatusDisplay(forceSoftwareRenderer=False)
        display._isAvailable = True

        result = display._initializePygame()

        assert result is True
        envAtInit = recorder["envAtInit"]
        assert envAtInit["SDL_RENDER_DRIVER"] is None
        assert envAtInit["SDL_VIDEO_X11_FORCE_EGL"] is None
        assert envAtInit["SDL_FRAMEBUFFER_ACCELERATION"] is None

    def test_initializePygame_doesNotOverrideUserSetSdlEnv(
        self, pygameInModuleRegistry, monkeypatch
    ):
        """
        Given: user has explicitly set SDL_RENDER_DRIVER=opengl in their env
        When:  _initializePygame runs with forceSoftwareRenderer=True
        Then:  the pre-existing user value is preserved (not clobbered).
               Rationale: deployment .service files override the default safely;
               Python should not fight the environment.
        """
        _, recorder = pygameInModuleRegistry
        monkeypatch.setenv("SDL_RENDER_DRIVER", "opengl")
        monkeypatch.delenv("SDL_VIDEO_X11_FORCE_EGL", raising=False)
        monkeypatch.delenv("SDL_FRAMEBUFFER_ACCELERATION", raising=False)

        display = StatusDisplay(forceSoftwareRenderer=True)
        display._isAvailable = True

        display._initializePygame()

        envAtInit = recorder["envAtInit"]
        assert envAtInit["SDL_RENDER_DRIVER"] == "opengl"  # preserved
        # Non-set keys still get the default software hint.
        assert envAtInit["SDL_VIDEO_X11_FORCE_EGL"] == "0"
        assert envAtInit["SDL_FRAMEBUFFER_ACCELERATION"] == "0"


# ================================================================================
# _initializePygame -- graceful failure path
# ================================================================================


class TestInitializePygameFailurePath:
    """
    When set_mode raises (GL context denied, X11 not reachable, etc.),
    _initializePygame returns False rather than propagating the exception.
    """

    def test_initializePygame_setModeRaises_returnsFalse(
        self, pygameInModuleRegistry, clearSdlEnv
    ):
        """
        Given: pygame.display.set_mode raises pygame.error (GL BadAccess)
        When:  _initializePygame runs
        Then:  returns False, no exception escapes, caller can proceed.
        """
        fake, _ = pygameInModuleRegistry

        def raisingSetMode(size, flags=0):
            raise fake.error(
                "Could not make GL context current: BadAccess"
            )

        fake.display.set_mode = raisingSetMode

        display = StatusDisplay(forceSoftwareRenderer=True)
        display._isAvailable = True

        result = display._initializePygame()

        assert result is False

    def test_initializePygame_initRaises_returnsFalse(
        self, pygameInModuleRegistry, clearSdlEnv
    ):
        """
        Given: pygame.init raises (e.g. SDL driver unavailable)
        When:  _initializePygame runs
        Then:  returns False gracefully.
        """
        fake, _ = pygameInModuleRegistry

        def raisingInit():
            raise fake.error("pygame.init failed -- no SDL driver")

        fake.init = raisingInit

        display = StatusDisplay(forceSoftwareRenderer=True)
        display._isAvailable = True

        result = display._initializePygame()

        assert result is False


# ================================================================================
# start() -- never crashes orchestrator when pygame init fails
# ================================================================================


class TestStartGracefulOnInitFailure:
    """
    The orchestrator calls start(). start() must return True or False, never
    raise. A raised exception from start() propagates to the orchestrator
    runLoop and kills it (TD-024's observed symptom at uptime=0.6s).
    """

    def test_start_pygameInitFails_returnsFalseWithoutRaise(self):
        """
        Given: StatusDisplay where _initializePygame returns False (GL failure)
        When:  start() is invoked
        Then:  returns False cleanly, no exception escapes.
               The orchestrator can log a WARN and proceed without the display.
        """
        display = StatusDisplay()
        display._isAvailable = True
        with patch.object(display, "_initializePygame", return_value=False):
            result = display.start()

        assert result is False
        assert display.isRunning is False

    def test_start_notAvailable_returnsFalseWithoutRaise(self):
        """
        Given: StatusDisplay where _isAvailable is False (non-Pi host)
        When:  start() is invoked
        Then:  returns False cleanly. This path is the non-Pi dev-env baseline
               and regression-guards against accidental raise injection.
        """
        display = StatusDisplay()
        display._isAvailable = False

        result = display.start()

        assert result is False
        assert display.isRunning is False


# ================================================================================
# Refresh-loop crash containment (regression guard for TD-024 symptom)
# ================================================================================


class TestRefreshLoopContainsGlCrash:
    """
    If the fix is insufficient and flip() still raises a GL error, the
    refresh-loop catches it and logs -- never propagates to the caller.
    This is an EXISTING safety net; test documents it as part of the
    TD-024 contract.
    """

    def test_refreshLoop_renderRaises_isCaughtAndLogged(
        self, pygameInModuleRegistry, caplog
    ):
        """
        Given: _render raises GL BadAccess on the first tick
        When:  _refreshLoop runs one iteration
        Then:  exception is caught + logged, stop event trips, no re-raise.
        """
        import logging

        fake, _ = pygameInModuleRegistry
        display = StatusDisplay()
        display._isAvailable = True

        def raisingRender():
            # Trip the stop event so the while-loop exits after this iteration
            # and the test doesn't hang.
            display._stopEvent.set()
            raise fake.error(
                "Could not make GL context current: BadAccess"
            )

        with patch.object(display, "_render", side_effect=raisingRender):
            with caplog.at_level(logging.ERROR, logger="pi.hardware.status_display"):
                display._refreshLoop()

        assert any(
            "Error in display refresh loop" in rec.message for rec in caplog.records
        )


# ================================================================================
# Public property parity
# ================================================================================


class TestPropertySurface:
    """The new forceSoftwareRenderer property must join the existing read-only set."""

    def test_forceSoftwareRenderer_isReadOnly(self):
        """
        Given: forceSoftwareRenderer is constructor-only -- no setter
        When:  assigning to the property
        Then:  AttributeError (consistent with width/height/refreshRate pattern
               for static constructor values that shouldn't mutate at runtime).
        """
        display = StatusDisplay(forceSoftwareRenderer=True)
        with pytest.raises(AttributeError):
            display.forceSoftwareRenderer = False


# ================================================================================
# US-257 -- canvas-size parameterization (full-canvas HDMI redesign / B-052)
# ================================================================================


class TestCanvasSizeParameterization:
    """
    StatusDisplay must accept the full HDMI canvas (1920x1080 / 1280x720) plus
    the legacy 480x320 dev/test footprint and produce a non-zero layout for
    each. Backwards-compat is the explicit acceptance criterion.
    """

    @pytest.mark.parametrize(
        "canvasWidth,canvasHeight",
        [(1920, 1080), (1280, 720), (480, 320)],
    )
    def test_init_acceptsCanvasSize_andComputesLayout(
        self, canvasWidth: int, canvasHeight: int
    ):
        """
        Given: StatusDisplay(width=W, height=H) for each supported size
        When:  reading the layout property
        Then:  the DashboardLayout reports the right canvas dimensions, all
               four quadrants exist, and font sizes are positive.
        """
        display = StatusDisplay(width=canvasWidth, height=canvasHeight)
        layout = display.layout
        assert layout.canvasWidth == canvasWidth
        assert layout.canvasHeight == canvasHeight
        for rect in (
            layout.engine,
            layout.power,
            layout.drive,
            layout.alerts,
            layout.footer,
        ):
            assert rect.width > 0
            assert rect.height > 0
        for size in (
            layout.fonts.title,
            layout.fonts.value,
            layout.fonts.label,
            layout.fonts.detail,
        ):
            assert size > 0

    @pytest.mark.parametrize(
        "canvasWidth,canvasHeight",
        [(1920, 1080), (1280, 720), (480, 320)],
    )
    def test_render_atCanvasSize_callsFlipWithoutRaising(
        self, canvasWidth: int, canvasHeight: int, pygameInModuleRegistry,
    ):
        """
        Given: a StatusDisplay constructed at each canvas size
        When:  the pygame stack is initialized and one frame is rendered
        Then:  pygame.display.flip is called and no exception escapes.
               This exercises every quadrant render path against the layout.
        """
        _, recorder = pygameInModuleRegistry
        display = StatusDisplay(width=canvasWidth, height=canvasHeight)
        display._isAvailable = True

        assert display._initializePygame() is True
        # Populate every state surface so each render path runs.
        display.updateBatteryInfo(percentage=85, voltage=4.05)
        display.updatePowerSource("car")
        display.updateObdStatus("connected")
        display.updateErrorCount(warnings=1, errors=0)
        display.updateShutdownStage("warning")

        display._render()

        assert recorder["flipCalls"] >= 1
        flushedSize = recorder["setModeCalls"][-1][0]
        assert flushedSize == (canvasWidth, canvasHeight)


# ================================================================================
# US-257 -- updateShutdownStage routes through to the data lock
# ================================================================================


class TestShutdownStageUpdate:
    """The power quadrant surfaces the staged-shutdown ladder via this setter."""

    def test_updateShutdownStage_acceptsEnum(self):
        from pi.hardware.dashboard_layout import ShutdownStage

        display = StatusDisplay()
        display.updateShutdownStage(ShutdownStage.IMMINENT)
        assert display.shutdownStage is ShutdownStage.IMMINENT

    @pytest.mark.parametrize(
        "stageStr,expectedName",
        [
            ("normal", "NORMAL"),
            ("warning", "WARNING"),
            ("imminent", "IMMINENT"),
            ("trigger", "TRIGGER"),
            ("WARNING", "WARNING"),  # case-insensitive
        ],
    )
    def test_updateShutdownStage_acceptsString(
        self, stageStr: str, expectedName: str
    ):
        display = StatusDisplay()
        display.updateShutdownStage(stageStr)
        assert display.shutdownStage.name == expectedName

    def test_updateShutdownStage_unknownStringCoercesToNormal(self):
        from pi.hardware.dashboard_layout import ShutdownStage

        display = StatusDisplay()
        # Move off NORMAL first so coercion is observable.
        display.updateShutdownStage(ShutdownStage.TRIGGER)
        display.updateShutdownStage("not-a-stage")
        assert display.shutdownStage is ShutdownStage.NORMAL

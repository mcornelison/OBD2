################################################################################
# File Name: test_gpio_button_mock.py
# Purpose/Description: Mock-based validation of GpioButton for US-180 AC #7.
#                      No physical GPIO button is wired on the bench Pi this
#                      sprint — the spec defers hardware wiring to Sprint 11
#                      — so this gate exercises the callback plumbing via
#                      direct invocation of the release / hold handlers,
#                      and the construction / param-validation contract.
# Author: Rex (Ralph agent)
# Creation Date: 2026-04-17
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-17    | Rex          | Initial implementation for US-180 (Pi Crawl AC #7)
# ================================================================================
################################################################################

"""
GpioButton mock-based validation for Sprint 10 / US-180 (AC #7).

Why these tests are mock-based (and still valuable):
- The bench Pi has no physical button wired.  gpiozero itself cannot even
  open a Button object without a real pin, so there's no way to drive a
  real gpiozero event from a test.
- What we CAN validate without a physical button is the code that runs
  when gpiozero fires its events: _handleRelease and _handleHeld.  Those
  are the two places a latent bug would actually hurt — e.g. a silent
  crash in the long-press callback would leave the shutdown button
  non-functional on a system where the orchestrator thinks everything is
  fine.
- The construction / validation contract (pin >= 0, holdTime > 0, etc.)
  is also worth a gate so a future Sprint 11 story that does wire the
  button can trust the constructor.
"""

from __future__ import annotations

import logging

import pytest

# tests/conftest.py puts src/ on sys.path.
from pi.hardware.gpio_button import (
    DEFAULT_BUTTON_PIN,
    DEFAULT_DEBOUNCE_TIME,
    DEFAULT_HOLD_TIME,
    GpioButton,
)

# ================================================================================
# Construction + validation tests
# ================================================================================


def test_gpioButton_defaults_matchExpectedPinAndTimes() -> None:
    """
    Given: GpioButton() constructed with no args
    When:  properties are read
    Then:  defaults are pin=17, debounce=0.2s, holdTime=3.0s.  These values
           are baked into the spec for US-180 and Sprint 11's physical
           wiring will depend on them — pin breakage here means the
           eventual physical button connects to the wrong rail.
    """
    button = GpioButton()

    assert button.pin == DEFAULT_BUTTON_PIN == 17
    assert button.debounceTime == DEFAULT_DEBOUNCE_TIME == 0.2
    assert button.holdTime == DEFAULT_HOLD_TIME == 3.0


@pytest.mark.parametrize(
    ("pin", "debounce", "hold", "expectedMsg"),
    [
        (-1, 0.2, 3.0, "pin must be non-negative"),
        (17, -0.1, 3.0, "Debounce time must be non-negative"),
        (17, 0.2, 0.0, "Hold time must be positive"),
        (17, 0.2, -1.0, "Hold time must be positive"),
    ],
)
def test_gpioButton_invalidParams_raiseValueError(
    pin: int,
    debounce: float,
    hold: float,
    expectedMsg: str,
) -> None:
    """
    Given: a GpioButton constructed with an invalid parameter combination
    When:  the constructor runs
    Then:  ValueError is raised with a message that mentions the offending
           field.  Catches any silent reversion of the constructor guard.
    """
    with pytest.raises(ValueError, match=expectedMsg):
        GpioButton(pin=pin, debounceTime=debounce, holdTime=hold)


def test_gpioButton_isAvailable_isBoolean() -> None:
    """
    Given: a GpioButton constructed with defaults
    When:  isAvailable is read
    Then:  the value is a clean boolean (True on a real Pi with gpiozero,
           False on Windows / non-Pi).  The cross-platform guard must set
           _isAvailable exactly once in __init__.  A None leak here would
           crash the later `if not self._isAvailable:` guard in start().
    """
    button = GpioButton()

    assert isinstance(button.isAvailable, bool)


# ================================================================================
# Start / stop contract tests
# ================================================================================


def test_gpioButton_startWhenUnavailable_returnsFalse_noRaise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: a GpioButton whose _isAvailable has been forced False (simulating
           a non-Pi host, a missing gpiozero import, or a gpiozero pin
           factory that bailed during construction)
    When:  start() is called
    Then:  returns False, logs a warning, does NOT raise.  Keeps the
           orchestrator's bring-up sequence resilient — a dev machine,
           CI box, or Pi where GPIO isn't reachable should still init
           cleanly.  Forcing the flag directly makes the test run the
           same on Windows and on a real Pi.
    """
    button = GpioButton()
    button._isAvailable = False  # simulate "GPIO unavailable" branch

    with caplog.at_level(logging.WARNING, logger="pi.hardware.gpio_button"):
        result = button.start()

    assert result is False
    assert button.isRunning is False
    assert any("GPIO not available" in r.message for r in caplog.records)


def test_gpioButton_stopOnNotRunning_isNoOp() -> None:
    """
    Given: a GpioButton that never started
    When:  stop() is called
    Then:  it does nothing quietly — no exception, no state change.
           Ensures shutdown ordering is forgiving when a subsystem failed
           to init.
    """
    button = GpioButton()

    # Must not raise.
    button.stop()
    button.stop()
    button.stop()

    assert button.isRunning is False


# ================================================================================
# Callback plumbing tests (direct handler invocation)
# ================================================================================


def test_handleRelease_withCallback_invokesShortPress() -> None:
    """
    Given: a GpioButton with onShortPress set
    When:  _handleRelease is called (simulating gpiozero's when_released event)
    Then:  the callback fires exactly once.  If this ever silently stops
           firing, the operator loses the "log short press" diagnostic
           without any visible symptom.
    """
    button = GpioButton()
    fired: list[str] = []
    button.onShortPress = lambda: fired.append("short")

    button._handleRelease()

    assert fired == ["short"]


def test_handleHeld_withCallback_invokesLongPress() -> None:
    """
    Given: a GpioButton with onLongPress set (the graceful-shutdown hook)
    When:  _handleHeld is called (simulating gpiozero's when_held event)
    Then:  the long-press callback fires.  This is the safety-critical
           path — it's how the CIO triggers a clean shutdown from the
           physical dashboard button.  A silent regression here means
           the car could only be stopped by pulling the fuse.
    """
    button = GpioButton(holdTime=0.1)  # shorter, for test predictability
    fired: list[str] = []
    button.onLongPress = lambda: fired.append("long")

    button._handleHeld()

    assert fired == ["long"]


def test_handleRelease_callbackRaises_buttonLogsAndContinues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: a GpioButton whose onShortPress callback raises
    When:  _handleRelease fires
    Then:  the exception is caught, logged at ERROR level, and does NOT
           propagate up to gpiozero's event thread.  Preserves the
           thread's availability so the NEXT press still works.
    """
    button = GpioButton()

    def badCallback() -> None:
        raise RuntimeError("boom from user callback")

    button.onShortPress = badCallback

    with caplog.at_level(logging.ERROR, logger="pi.hardware.gpio_button"):
        button._handleRelease()  # must not raise

    assert any(
        "short press callback" in r.message.lower() for r in caplog.records
    )


def test_handleHeld_callbackRaises_buttonLogsAndContinues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """
    Given: a GpioButton whose onLongPress callback raises
    When:  _handleHeld fires
    Then:  the exception is caught and logged — the gpiozero event thread
           stays alive.  Mirror of the release-callback guard; equally
           important because a crash in the shutdown handler would make
           the shutdown button a one-shot.
    """
    button = GpioButton()

    def shutdownFailure() -> None:
        raise RuntimeError("shutdown handler blew up")

    button.onLongPress = shutdownFailure

    with caplog.at_level(logging.ERROR, logger="pi.hardware.gpio_button"):
        button._handleHeld()  # must not raise

    assert any(
        "long press callback" in r.message.lower() for r in caplog.records
    )


def test_handleRelease_noCallback_doesNotRaise() -> None:
    """
    Given: a GpioButton with onShortPress=None (never set)
    When:  _handleRelease fires (gpiozero's when_released event)
    Then:  no exception — the handler silently logs and returns.  A real
           Pi with the button wired before the orchestrator sets its
           callback must not crash.
    """
    button = GpioButton()

    button._handleRelease()  # must not raise
    button._handleHeld()  # ditto the held side


# ================================================================================
# Property setter tests
# ================================================================================


def test_onShortPress_setterAndGetter_symmetric() -> None:
    """
    Given: a GpioButton
    When:  onShortPress is set and then read back
    Then:  the setter and getter agree (no shadowing by the internal
           _onShortPress attribute).
    """
    button = GpioButton()
    cb = lambda: None  # noqa: E731

    button.onShortPress = cb
    assert button.onShortPress is cb

    button.onShortPress = None
    assert button.onShortPress is None


def test_onLongPress_setterAndGetter_symmetric() -> None:
    """
    Given: a GpioButton
    When:  onLongPress is set and then cleared
    Then:  the public property roundtrips cleanly.
    """
    button = GpioButton()
    cb = lambda: None  # noqa: E731

    button.onLongPress = cb
    assert button.onLongPress is cb

    button.onLongPress = None
    assert button.onLongPress is None

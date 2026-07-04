################################################################################
# File Name: slow_drain_detector.py
# Purpose/Description: Sustained-VCELL-decline (slow-drain) health detector with
#                      flap-debounce, for the Geekworm X1209 UPS HAT (F-051 /
#                      US-444).  A pure decision layer over a stream of
#                      (timestamp, VCELL) samples -- carries no hardware and no
#                      wall clock.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-03
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-03    | Rex (US-444) | Initial implementation. Detects a sustained
#                              | gradual VCELL decline over a rolling window and
#                              | commits the SLOW_DRAIN verdict only after the raw
#                              | signal holds for a debounce interval (flap
#                              | suppression).  BATTERY-HEALTH ONLY -- this is a
#                              | health verdict, NOT the retired power-source
#                              | decision (that is the PowerSourceProvider SSOT;
#                              | UpsMonitor.getPowerSource() is a loud tripwire
#                              | since SS-T4 2026-05-19 and stays that way).
# ================================================================================
################################################################################

"""Slow-drain detection with flap-debounce (F-051 / US-444).

A :class:`SlowDrainDetector` consumes ``(timestamp, VCELL)`` samples and reports
a :class:`DrainState` health verdict:

- ``UNKNOWN``    -- not enough data to judge (partial window / < 2 samples).
- ``STABLE``     -- no sustained decline over the window.
- ``SLOW_DRAIN`` -- VCELL has declined by more than the threshold across a full
  window, and that verdict has held for the debounce interval.

**Scope boundary (SS-T4, Atlas 2026-05-19).** This is a *battery-health* signal.
It is deliberately NOT a power-source (AC-vs-battery) decision: that fact is
owned by ``src.pi.power.power_source_provider.PowerSourceProvider`` (SSOT over
the X1209 GPIO6 PLD line), and ``UpsMonitor.getPowerSource()`` remains a loud
``NotImplementedError`` tripwire.  The retired VCELL-trend heuristic decided
EXTERNAL/BATTERY and bricked the Pi 2026-05-18; this detector never emits a
source verdict and never feeds a shutdown decision -- it is advisory telemetry
about *how the cell is trending*, so gradual drain is surfaced without false
alarms.

Why a rolling window + debounce (rather than an instantaneous slope):

- A **full window** (default 300 s) means a transient dip or a single noisy
  read cannot trip the flag -- the decline has to be sustained.  Until the
  buffer spans (most of) the window the verdict is ``UNKNOWN`` (honest
  instrument), never a confident STABLE.
- A **debounce** (default 30 s) means the committed verdict only changes after
  the raw windowed verdict has held its new value continuously for the debounce
  interval.  The 2026-04-29 inverted-power drill logged 4 transitions in 45 s
  (5 s flaps); a 30 s debounce suppresses every one of those without missing a
  real transition (real transitions were spaced >= 2 min apart).

Grounding (F-051 backlog + drain tests 1-4):

- Drain 4 declined ~0.034 V/min; a real idle drain drifts >= ~0.001 V/min, i.e.
  >= 0.005 V over 5 min -- comfortably above the sensor noise floor.
- ``> 0.005 V`` over ``300 s`` therefore fires within the first minutes of any
  real drain while staying quiet on AC-fed float noise.

Usage::

    detector = SlowDrainDetector()
    state = detector.update(monotonic_seconds, vcell_volts)
    if state is DrainState.SLOW_DRAIN:
        ...  # advisory: cell is slowly draining
"""

from __future__ import annotations

import logging
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


# ================================================================================
# Constants (grounded -- see module docstring)
# ================================================================================

# Rolling window over which the net VCELL decline is measured.
DEFAULT_SLOW_DRAIN_WINDOW_SECONDS = 300.0

# Net decline (oldest-in-window minus newest) that trips the raw SLOW_DRAIN
# verdict.  0.005 V over the 300 s window == ~0.001 V/min sustained.
DEFAULT_SLOW_DRAIN_DECLINE_THRESHOLD_V = 0.005

# The raw verdict must hold its new value continuously for this long before the
# committed verdict changes (flap suppression).
DEFAULT_SLOW_DRAIN_DEBOUNCE_SECONDS = 30.0

# Fraction of the window that must be spanned by retained samples before the
# verdict is considered determinate (guards against judging a partial window
# during ramp-up).
DEFAULT_SLOW_DRAIN_MIN_WINDOW_FRACTION = 0.9


class DrainState(Enum):
    """Battery-health verdict emitted by :class:`SlowDrainDetector`.

    NOTE: this is a health signal, NOT a power source.  It is intentionally a
    distinct type from :class:`pi.hardware.ups_monitor.PowerSource` so the two
    can never be confused at a call site.
    """

    UNKNOWN = "unknown"
    STABLE = "stable"
    SLOW_DRAIN = "slow_drain"


# ================================================================================
# Detector
# ================================================================================


class SlowDrainDetector:
    """Detect a sustained gradual VCELL decline, with flap-debounce.

    The detector keeps a rolling buffer of ``(timestamp, vcell)`` samples
    pruned to ``windowSeconds``.  On each :meth:`update` it computes a *raw*
    verdict from the net decline across the window, then applies a debounce so
    the *committed* verdict only changes after the raw verdict has held for
    ``debounceSeconds``.

    All timestamps are caller-supplied (typically a monotonic clock), so the
    detector is fully deterministic and hardware-free -- unit tests feed an
    explicit trace.

    Attributes:
        state: The current committed :class:`DrainState`.
    """

    def __init__(
        self,
        windowSeconds: float = DEFAULT_SLOW_DRAIN_WINDOW_SECONDS,
        declineThresholdVolts: float = DEFAULT_SLOW_DRAIN_DECLINE_THRESHOLD_V,
        debounceSeconds: float = DEFAULT_SLOW_DRAIN_DEBOUNCE_SECONDS,
        minWindowFraction: float = DEFAULT_SLOW_DRAIN_MIN_WINDOW_FRACTION,
    ) -> None:
        """Initialize the detector.

        Args:
            windowSeconds: Rolling window over which the net VCELL decline is
                measured. Default 300 s.
            declineThresholdVolts: Net decline (oldest-in-window minus newest)
                that trips the raw SLOW_DRAIN verdict. Default 0.005 V.
            debounceSeconds: Duration the raw verdict must hold a new value
                before the committed verdict changes (flap suppression).
                Default 30 s.
            minWindowFraction: Fraction of ``windowSeconds`` that retained
                samples must span before the verdict is determinate. Default
                0.9.
        """
        self._windowSeconds = windowSeconds
        self._declineThreshold = declineThresholdVolts
        self._debounceSeconds = debounceSeconds
        self._minWindowFraction = minWindowFraction

        self._samples: deque[tuple[float, float]] = deque()
        self._committedState: DrainState = DrainState.UNKNOWN
        self._candidateState: DrainState = DrainState.UNKNOWN
        self._candidateSince: float | None = None

        logger.debug(
            "SlowDrainDetector initialized: window=%ss, threshold=%sV, "
            "debounce=%ss, minWindowFraction=%s",
            windowSeconds,
            declineThresholdVolts,
            debounceSeconds,
            minWindowFraction,
        )

    def update(self, timestamp: float, vcellVolts: float) -> DrainState:
        """Feed one ``(timestamp, VCELL)`` sample and return the committed state.

        Args:
            timestamp: Monotonic timestamp in seconds (same clock across calls;
                must be non-decreasing).
            vcellVolts: VCELL reading in volts.

        Returns:
            The current committed :class:`DrainState` after this sample.
        """
        self._appendAndPrune(timestamp, vcellVolts)
        rawState = self._computeRawState()
        return self._applyDebounce(rawState, timestamp)

    @property
    def state(self) -> DrainState:
        """Return the current committed :class:`DrainState`."""
        return self._committedState

    # -- internals ---------------------------------------------------------

    def _appendAndPrune(self, timestamp: float, vcellVolts: float) -> None:
        """Append a sample and drop anything older than the window."""
        self._samples.append((timestamp, vcellVolts))
        cutoff = timestamp - self._windowSeconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def _computeRawState(self) -> DrainState:
        """Derive the un-debounced verdict from the current window.

        Returns ``UNKNOWN`` unless the retained samples span at least
        ``minWindowFraction`` of the window (so a partial ramp-up window is
        never judged).  Otherwise SLOW_DRAIN if the net decline meets the
        threshold, else STABLE.
        """
        if len(self._samples) < 2:
            return DrainState.UNKNOWN

        oldestTs, oldestV = self._samples[0]
        newestTs, newestV = self._samples[-1]

        span = newestTs - oldestTs
        if span < self._windowSeconds * self._minWindowFraction:
            return DrainState.UNKNOWN

        decline = oldestV - newestV
        if decline >= self._declineThreshold:
            return DrainState.SLOW_DRAIN
        return DrainState.STABLE

    def _applyDebounce(self, rawState: DrainState, now: float) -> DrainState:
        """Commit ``rawState`` only after it has held for the debounce interval.

        An ``UNKNOWN`` raw verdict (indeterminate window) is inert: it neither
        resets the candidate nor changes the committed state, so a brief data
        gap does not disturb a settled verdict.
        """
        if rawState is DrainState.UNKNOWN:
            return self._committedState

        # A new raw verdict restarts the debounce timer.
        if rawState is not self._candidateState:
            self._candidateState = rawState
            self._candidateSince = now

        # Commit once the candidate has differed from the committed state for
        # at least the debounce interval.
        if (
            rawState is not self._committedState
            and self._candidateSince is not None
            and (now - self._candidateSince) >= self._debounceSeconds
        ):
            logger.info(
                "SlowDrainDetector committed %s -> %s",
                self._committedState.value,
                rawState.value,
            )
            self._committedState = rawState

        return self._committedState

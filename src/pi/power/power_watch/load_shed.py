################################################################################
# File Name: load_shed.py
# Purpose/Description: ARCH-031 / US-748 -- drop the heavy, non-essential load
#     the instant external power is lost, so the battery has to carry less while
#     the sequencer decides whether this is a real loss.
# Author: Atlas (ARCH-031, CIO build override 2026-09-16)
# Creation Date: 2026-09-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""Reversible load shedding at power loss (ARCH-031, US-748).

WHY. Measured 2026-09-16 across nine live power cuts with the CIO pulling the
plug. 🔴 THE THREE ROWS ARE NOT THE SAME QUANTITY. Read the label, not the
number:

    six services (chromium dashboard up)  4.35 W bursty  -> 0.678 s  to DEATH
    five services, dashboard stopped      1.886 W        -> ~7 s     to COMMANDED
                                                            POWEROFF -- this is
                                                            smoothingSec, NOT a
                                                            battery limit
    all project software stopped          1.84 W         -> >= 225 s to DEATH
                                                            (a FLOOR: power was
                                                            restored, not a death)

Reading the middle row as a death time manufactures a "~10x survival improvement
from a 2.5% power difference". There is no such phenomenon. That number tracks
smoothingSec exactly, because it IS smoothingSec: the machine did not die at 7 s,
it completed a graceful shutdown and powered itself off on schedule (startup_log
= CLEAN_COMPLETE/graceful, three consecutive boots).

The tell was in plain sight and our own instrument printed it. The LOSS HEARTBEAT
line says, every boot: "TIME-TO-DEATH if the prior boot has no CLEAN_COMPLETE,
time-to-poweroff if it does." The disambiguator was built, correct and durable.
Nobody ran the check -- including me, when I wrote the finding.

Everything else the project runs -- OBD polling, EDR persistence, powerwatch, the state server,
boot-state, drain-forensics -- adds about **0.1 W combined**. The dashboard
kiosk is essentially the entire in-car load.

THE SHAPE, and why it is not simply "power off sooner". The sequencer already
debounces (``smoothingSec``) before committing to a poweroff, because a
transient blip must never brick the Pi (2026-05-18 bricking hotfix). That
debounce is correct and is NOT touched here. What was missing is that the system
spent the debounce window carrying its FULL load -- so it frequently died before
the decision was even taken.

    mitigate REVERSIBLY at once  ->  commit IRREVERSIBLY only after the debounce

Shedding is cheap and undoable; poweroff is neither. They must not share a timer.

🔴 THE INVARIANT. Neither ``shed`` nor ``restore`` may raise into the sequencer.
Shedding is an optimisation; losing the shutdown to it would be strictly worse
than the defect it fixes. Every unit is attempted independently, so one stuck
unit cannot leave the dashboard -- the one that actually matters -- running.

⚠️ ``restore`` deliberately starts ONLY the units that actually stopped. A unit
whose stop failed is still running; starting it would claim a state change that
never happened.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

__all__ = ["DEFAULT_SHED_UNITS", "LoadShedder", "systemctlRunner"]

#: Shed the dashboard and nothing else by default. It is the measured dominant
#: load AND the burstiest thing on the box; the rest of the stack is ~0.1 W
#: combined and includes the very services that must keep running to preserve
#: data. Shedding is opt-in per unit, never "stop everything".
DEFAULT_SHED_UNITS: tuple[str, ...] = ("eclipse-dashboard",)

_ACTION_TIMEOUT_S = 5.0


def systemctlRunner(action: str, unit: str) -> None:
    """Run ``systemctl <action> <unit>``. Raises on failure; caller guards.

    ``--no-block`` is deliberate: the point is to stop drawing power NOW, and
    waiting for the unit to finish stopping spends exactly the battery window
    this exists to protect.
    """
    subprocess.run(
        ["systemctl", "--no-block", action, unit],
        check=True,
        capture_output=True,
        timeout=_ACTION_TIMEOUT_S,
    )


class LoadShedder:
    """Stops configured units on power loss and restores them if it was a blip."""

    def __init__(
        self,
        units: Iterable[str] = DEFAULT_SHED_UNITS,
        runner: Callable[[str, str], None] | None = None,
    ) -> None:
        """Bind the shedder to its unit list and its action runner.

        Args:
            units: Unit names to shed, in order. Empty disables shedding
                entirely, with no special-casing at the call site.
            runner: ``callable(action, unit)``; defaults to :func:`systemctlRunner`.
        """
        self._units: tuple[str, ...] = tuple(units or ())
        self._runner = runner if runner is not None else systemctlRunner
        #: Units this shedder actually stopped, and therefore owes a restore.
        self._shed: list[str] = []
        self._active = False

    def shed(self) -> None:
        """Stop the configured units. Never raises. Idempotent within one loss.

        Idempotency matters because the sequencer may observe more than one
        power-loss edge for a single outage; re-issuing the stops would be
        wasted work at the worst possible moment.
        """
        if self._active or not self._units:
            return
        self._active = True
        for unit in self._units:
            try:
                self._runner("stop", unit)
            except Exception as exc:  # noqa: BLE001 -- best-effort, per unit
                logger.warning(
                    "load-shed: could not stop %s (%s) -- continuing with the "
                    "remaining units; this one keeps drawing power",
                    unit, exc,
                )
                continue
            self._shed.append(unit)
        if self._shed:
            logger.warning(
                "load-shed: power lost -- shed %s to extend battery carry "
                "(ARCH-031); will restore if power returns",
                ", ".join(self._shed),
            )

    def restore(self) -> None:
        """Restart exactly what :meth:`shed` stopped. Never raises.

        Called when the sequencer cancels (power came back during smoothing).
        A shedder that never shed does nothing at all.
        """
        self._active = False
        units, self._shed = self._shed, []
        if not units:
            return
        for unit in units:
            try:
                self._runner("start", unit)
            except Exception as exc:  # noqa: BLE001 -- best-effort, per unit
                logger.error(
                    "load-shed: could not restore %s (%s) -- it stays down "
                    "until the next boot", unit, exc,
                )
        logger.warning("load-shed: power returned -- restored %s", ", ".join(units))

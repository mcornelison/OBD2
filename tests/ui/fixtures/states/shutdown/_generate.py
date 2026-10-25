################################################################################
# File Name: _generate.py
# Purpose/Description: US-870-b (spec specs/v030-boot-shutdown-design.md s2.2)
#   -- GENERATES the shutdown-progress fixtures in this directory from the REAL
#   producers, with every input written here. Never hand-type a fixture: edit a
#   script below and re-run this file.
#
#   Each fixture is {description, inputs, sequence}: `sequence` is the
#   succession of shutdown-state payloads the ShutdownSequencer WRITES, in
#   order, built the way the sequencer builds them:
#     - the step is CeremonyProgress.step() over a ceremonySteps(...) plan
#       (src/pi/power/power_watch/ceremony.py), None on grace / cancelled;
#     - each payload is buildShutdownState(...)
#       (src/pi/splash/shutdown_state_emitter.py);
#     - a write happens where controller.py writes one: _enterStep (with a
#       phase always, without one only when the step was entered), a phase
#       change, and publishSync. A reroute writes nothing (controller.py :563-567:
#       the new `of` rides with the next step entered).
#
#   Usage: python tests/ui/fixtures/states/shutdown/_generate.py
#   (tests/ui/test_shutdown_progress_page.py asserts every file on disk equals
#   what this script builds, so a stale fixture fails the suite.)
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Ralph (Rex)  | Initial -- US-870-b shutdown-progress fixtures.
# ================================================================================
################################################################################

"""Generate the US-870-b shutdown-progress fixtures from the real producers."""

from __future__ import annotations

import json
import os
import sys
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
_SRC = os.path.join(_REPO_ROOT, "src")
for _root in (_REPO_ROOT, _SRC):
    if _root not in sys.path:
        sys.path.insert(0, _root)

from pi.power.power_watch.ceremony import (  # noqa: E402
    STEP_CUSTODY,
    STEP_DRAIN,
    STEP_DRAIN_CLOSE,
    STEP_MONTHLY_TEST_HOLD,
    STEP_POWEROFF,
    STEP_SHED,
    CeremonyProgress,
    ceremonySteps,
)
from pi.splash.shutdown_state_emitter import (  # noqa: E402
    DEFAULT_REASON,
    PHASE_CANCELLED,
    PHASE_FLUSHING,
    PHASE_GRACE,
    PHASE_POWERING_OFF,
    buildShutdownState,
)

_GRACE_STARTED = "2026-10-25T12:00:00Z"
#: controller.py's default smoothing window (its header: smoothingSec=7).
_GRACE_TOTAL_S = 7.0
#: Rows waiting at key-off in the at-home fixtures (any positive count will do:
#: the page draws index / of in this story and does not read sync{}).
_WAITING = 1240

# A script is a list of operations, each a list (JSON-friendly, kept in inputs):
#   ["grace"]                        smoothing begun: phase grace, no step
#   ["plan", fastPath, holdDue]      CeremonyProgress.begin(ceremonySteps(...))
#   ["enter", name, phase|None]      _enterStep(name, phase=phase)
#   ["phase", phase]                 _emitPhase(phase)
#   ["reroute", fastPath, holdDue]   CeremonyProgress.reroute(...) -- no write
#   ["sync", waiting, confirmed]     publishSync({waitingAtKeyOff, confirmed})
_NORMAL_OPENING: list[list[Any]] = [
    ["grace"],
    ["plan", False, False],
    ["enter", STEP_SHED, PHASE_FLUSHING],
    ["enter", STEP_DRAIN, PHASE_FLUSHING],
]
_NORMAL_CLOSE: list[list[Any]] = [
    ["phase", PHASE_POWERING_OFF],
    ["enter", STEP_DRAIN_CLOSE, None],
    ["enter", STEP_CUSTODY, None],
    ["enter", STEP_POWEROFF, None],
]

FIXTURES: dict[str, tuple[str, list[list[Any]]]] = {
    "normal-home": (
        "At home, the normal path of 5: shed, drain (two sync passes), drain "
        "close, custody, poweroff.",
        _NORMAL_OPENING
        + [["sync", _WAITING, 620], ["sync", _WAITING, _WAITING]]
        + _NORMAL_CLOSE,
    ),
    "hold-due": (
        "At home with the monthly test due: 6 steps, the hold after the drain.",
        [
            ["grace"],
            ["plan", False, True],
            ["enter", STEP_SHED, PHASE_FLUSHING],
            ["enter", STEP_DRAIN, PHASE_FLUSHING],
            ["sync", _WAITING, _WAITING],
            ["enter", STEP_MONTHLY_TEST_HOLD, None],
        ]
        + _NORMAL_CLOSE,
    ),
    "fast-path": (
        "The VCELL fast path: 3 steps (shed, custody, poweroff), straight to "
        "powering_off; the drain close is not on this path and writes nothing.",
        [
            ["grace"],
            ["plan", True, False],
            ["enter", STEP_SHED, PHASE_POWERING_OFF],
            ["enter", STEP_DRAIN_CLOSE, None],
            ["enter", STEP_CUSTODY, None],
            ["enter", STEP_POWEROFF, None],
        ],
    ),
    "away": (
        "Away from home, the normal path of 5 with no sync{}: 20, 40, 60, 80, 100 %.",
        _NORMAL_OPENING + _NORMAL_CLOSE,
    ),
    "mid-drain-switch": (
        "The drain floor forces the fast path mid-drain: shed and drain stay "
        "entered, `of` becomes 4 (entered + remaining), the drain close is skipped.",
        _NORMAL_OPENING
        + [
            ["sync", _WAITING, 310],
            ["phase", PHASE_POWERING_OFF],
            ["reroute", True, False],
            ["enter", STEP_DRAIN_CLOSE, None],
            ["enter", STEP_CUSTODY, None],
            ["enter", STEP_POWEROFF, None],
        ],
    ),
}


def _nowIso(seq: int) -> str:
    """One second per write after the grace start (the page never reads ts)."""
    return f"2026-10-25T12:00:{seq:02d}Z"


def buildSequence(script: list[list[Any]]) -> list[dict[str, Any]]:
    """Run one script through CeremonyProgress and buildShutdownState."""
    progress = CeremonyProgress()
    phase: str | None = None
    sync: dict[str, int] | None = None
    out: list[dict[str, Any]] = []

    def write(newPhase: str) -> None:
        nonlocal phase
        phase = newPhase
        step = None if newPhase in (PHASE_GRACE, PHASE_CANCELLED) else progress.step()
        out.append(
            buildShutdownState(
                newPhase,
                tGraceStartedAtIso=_GRACE_STARTED,
                tGraceTotalS=_GRACE_TOTAL_S,
                tRemainingS=_GRACE_TOTAL_S if newPhase == PHASE_GRACE else 0.0,
                reason=DEFAULT_REASON,
                nowIso=_nowIso(len(out)),
                step=step,
                sync=sync,
            )
        )

    for op in script:
        kind = op[0]
        if kind == "grace":
            progress.reset()
            write(PHASE_GRACE)
        elif kind == "plan":
            progress.begin(ceremonySteps(fastPath=op[1], holdDue=op[2]))
        elif kind == "enter":
            entered = progress.enter(op[1])
            if op[2] is not None:
                write(op[2])
            elif entered and phase is not None:
                write(phase)
        elif kind == "phase":
            write(op[1])
        elif kind == "reroute":
            progress.reroute(ceremonySteps(fastPath=op[1], holdDue=op[2]))
        elif kind == "sync":
            sync = {"waitingAtKeyOff": op[1], "confirmed": op[2]}
            if phase is not None:
                write(phase)
        else:
            raise ValueError(f"unknown script operation {op!r}")
    return out


def buildFixture(name: str) -> dict[str, Any]:
    """Build one fixture from its script."""
    description, script = FIXTURES[name]
    return {
        "description": description,
        "inputs": json.loads(json.dumps(script)),
        "sequence": buildSequence(script),
    }


def render(fixture: dict[str, Any]) -> str:
    """The on-disk text of a fixture (2-space JSON, trailing newline)."""
    return json.dumps(fixture, indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    for name in FIXTURES:
        path = os.path.join(_HERE, f"{name}.json")
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(render(buildFixture(name)))
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

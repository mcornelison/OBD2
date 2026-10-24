################################################################################
# File Name: test_shutdown_phase_list_guard.py
# Purpose/Description: US-883-a cross-language guard (Atlas, shutdown ruling
#     (3)): the phases shutdown-state-poll.js recognises are exactly the
#     emitter's VALID_PHASES. The step publish adds keys to shutdown-state, never
#     a phase; this pins that the page and the sequencer still agree on the list.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################
"""The shutdown page's recognised phase list is VALID_PHASES."""

from __future__ import annotations

import re
from pathlib import Path

from src.pi.splash.shutdown_state_emitter import VALID_PHASES

POLL_JS = (
    Path(__file__).resolve().parents[2] / "src" / "pi" / "ui" / "splash" / "shutdown-state-poll.js"
)

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")
#: A branch on the phase value: `phase === "x"` (either quote style).
_PHASE_TEST = re.compile(r"""\bphase\s*===?\s*["']([^"']+)["']""")


def recognisedPhases(js: str) -> set[str]:
    """Every phase literal the page branches on, comments stripped."""
    code = _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", js))
    return set(_PHASE_TEST.findall(code))


def test_pagePhaseList_isValidPhases():
    """
    Given: the shipped shutdown-state-poll.js
    When:  the phases it branches on are read
    Then:  they are exactly VALID_PHASES -- no phase the sequencer cannot write,
           none it writes that the page would treat as unrecognised
    """
    phases = recognisedPhases(POLL_JS.read_text(encoding="utf-8"))

    assert phases == set(VALID_PHASES)


def test_guard_failsOnAPhaseTheEmitterDoesNotKnow():
    """The reader sees an added branch, so the guard cannot pass vacuously."""
    js = POLL_JS.read_text(encoding="utf-8") + '\nif (phase === "syncing") { tick(); }\n'

    assert recognisedPhases(js) == set(VALID_PHASES) | {"syncing"}


def test_guard_ignoresPhasesNamedOnlyInComments():
    """A phase named in a comment is prose, not a branch."""
    js = '// phase === "grace"\n/* phase === "flushing" */\nif (phase === "cancelled") {}\n'

    assert recognisedPhases(js) == {"cancelled"}

################################################################################
# File Name: test_sync_custody_wiring.py
# Purpose/Description: US-621 -- proof that the custody record and the bounded
#                      drain are actually WIRED into the production service,
#                      not merely available to it. The US-573 lesson, and this
#                      project's most-repeated one: a mechanism that exists and
#                      is never called is an inert guard -- present, green, and
#                      blind to the thing it was installed for.
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-29    | Rex (US-621) | Initial -- main() wiring guards for custody.
# ================================================================================
################################################################################
"""US-621 wiring guards: the service really does record sync custody."""
from __future__ import annotations

import ast
import inspect

from src.pi.power.power_watch import __main__ as m


def _mainCalls(funcName: str) -> list[ast.Call]:
    """Every call to ``funcName`` inside ``main()``, parsed not grepped."""
    tree = ast.parse(inspect.getsource(m.main))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == funcName
    ]


class TestCustodyIsWiredIntoTheService:
    """A record nothing invokes would leave the 2026-08-28 defect intact."""

    def test_main_buildsTheCustodyHook(self) -> None:
        """
        Given: the production entrypoint
        When: its source is parsed
        Then: it constructs the sync-custody hook

        Without this call the module still imports, every unit test still
        passes, and no shutdown ever records custody.
        """
        assert _mainCalls("makeSyncCustodyHook"), (
            "main() never builds the custody hook -- the record would never "
            "be written on any shutdown"
        )

    def test_main_composesCustodyAlongsideTheDrainClose(self) -> None:
        """
        Given: the production entrypoint
        When: the pre-poweroff hooks are composed
        Then: BOTH the US-526 drain close and the US-621 custody hook go in

        Passing only one would silently retire the other -- the sequencer takes
        a single prePowerOffFn, so whichever is omitted simply stops happening.
        """
        # Act
        calls = _mainCalls("composePrePowerOffHooks")

        # Assert
        assert calls, "main() must compose the pre-poweroff hooks"
        assert len(calls[0].args) == 2, (
            "composePrePowerOffHooks must receive BOTH the drain close and "
            f"the custody hook; got {len(calls[0].args)} argument(s)"
        )

    def test_main_passesTheComposedHookToTheSequencer(self) -> None:
        """
        Given: the production entrypoint
        When: the ShutdownSequencer is constructed
        Then: prePowerOffFn is the composed hook

        Composing two hooks and then not handing them to the sequencer is the
        same inert outcome with more code.
        """
        # Arrange
        source = inspect.getsource(m.main)

        # Assert
        assert "prePowerOffFn=prePowerOffFn" in source
        assert "prePowerOffFn = composePrePowerOffHooks(" in source


class TestTheDrainIsWiredToABacklogReader:
    """Multi-pass draining only happens when a reader is actually supplied."""

    def test_main_givesTheDrainABacklogReader(self) -> None:
        """
        Given: the production entrypoint
        When: the runSync adapter is built
        Then: it receives a backlogReader

        _buildRunSync defaults backlogReader to None, which collapses to the
        single-pass legacy behaviour. Omitting it here would leave the exact
        defect this story fixes in place while the tests all passed.
        """
        # Act
        calls = _mainCalls("_buildRunSync")

        # Assert
        assert calls, "main() must build the runSync adapter"
        kwargs = {kw.arg for kw in calls[0].keywords}
        assert "backlogReader" in kwargs, (
            "_buildRunSync without backlogReader silently reverts to the "
            "one-batch-per-table drain that stranded ~14,500 rows"
        )
        assert "budgetSec" in kwargs, "the drain must be bounded"

    def test_main_sharesOneBacklogReaderBetweenDrainAndCustody(self) -> None:
        """
        Given: the production entrypoint
        When: the drain and the custody record each get a reader
        Then: it is the SAME reader

        Two readers could disagree. A shutdown that drained until its own
        reader said "empty" and then recorded a different number from a second
        reader would be a new honest-instrument defect introduced by the fix
        for one.
        """
        # Arrange
        source = inspect.getsource(m.main)

        # Assert -- one definition, two uses
        assert source.count("def readSyncBacklog(") == 1
        assert source.count("backlogReader=readSyncBacklog") == 2


class TestTheCustodyRecordHasItsOwnFile:
    """Sharing the outcome record's path would make each overwrite the other."""

    def test_custodyRecordFilename_differsFromTheOutcomeRecord(self) -> None:
        """
        Given: both records live beside the SQLite database
        When: their filenames are compared
        Then: they differ

        writeAtomicJson finishes with os.replace onto a fixed path, so one
        shared slot means last-writer-wins between a sync fault record and a
        custody record -- two facts, one file.
        """
        from src.pi.power.power_watch.sync_custody import CUSTODY_RECORD_FILENAME

        assert CUSTODY_RECORD_FILENAME != "powerwatch_outcome.json"
        assert "custody" in CUSTODY_RECORD_FILENAME

    def test_main_writesCustodyBesideTheDatabase(self) -> None:
        """
        Given: the production entrypoint
        When: the custody record path is resolved
        Then: it is derived from pi.database.path, never hardcoded

        The outcome record already reuses that directory rather than inventing
        an un-specced path key; custody follows the same rule.
        """
        source = inspect.getsource(m.main)
        assert "CUSTODY_RECORD_FILENAME" in source
        assert "os.path.dirname(dbPath)" in source

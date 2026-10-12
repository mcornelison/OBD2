################################################################################
# File Name: test_disk_space_guard.py
# Purpose/Description: US-762 -- the Pi notices low disk and reports what could
#                      be cleared, ranked. It never deletes, and an unreadable
#                      filesystem is a typed absence rather than a pass.
# Author: Ralph (US-762)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author         | Description
# ================================================================================
# 2026-09-23    | Ralph (US-762) | Initial -- threshold, ranking, no deletion,
#               |                | typed absence on an unreadable filesystem.
# ================================================================================
################################################################################
"""The disk-space guard (US-762).

WHY THIS EXISTS: the EDR retention window was widened 6.4x on a one-off
arithmetic margin that nothing re-checks. **A number with no watcher is not a
guard** -- it is a calculation someone did once.

⚠️ MEASURED 2026-09-21: 117 GB total, 18 GB used, 95 GB free. The guard will
report HEALTHY on the real car for the foreseeable future, which is exactly
why the BREACH path has to be proven by test rather than by waiting for the
car to fill up. A path that has never executed is not known to work.

🔴 AN UNREADABLE FILESYSTEM IS NOT HEALTHY. Same defect class as a bit-identical
sensor reading passing a variance check: the absence of a failure signal is not
a success signal. It is a typed absence, per the honest-availability pattern.

🔴 THE GUARD NEVER DELETES. The CIO asked for options that might help clear
space -- that is a REPORT. Acting on it is a behaviour change needing its own
ruling, and it is not this story.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from src.pi.diagnostics.disk_space_guard import (
    GUARD_MODULE_PATH,
    LOW_DISK_THRESHOLD_BYTES,
    MAX_REPORTED_CANDIDATES,
    DiskVerdict,
    assessDiskSpace,
)

_GB = 1024 ** 3


def _reader(freeBytes: int):
    """A free-space reader returning a fixed number."""
    return lambda path: freeBytes


def _raisingReader(exc: Exception):
    def read(path):
        raise exc
    return read


class TestTheThresholdIsNamedAndCorrect:
    """Acceptance 2 -- 20 GB, from one named source, cited."""

    def test_thresholdIs20Gb(self) -> None:
        """
        Given: the named threshold constant
        When:  it is read
        Then:  it is 20 GB, Atlas's 2026-09-14 stop-loss figure
        """
        assert LOW_DISK_THRESHOLD_BYTES == 20 * _GB

    def test_thresholdIsNotWrittenAsALiteralAtAUseSite(self) -> None:
        """
        Given: the Pi source tree
        When:  it is scanned for the threshold written inline
        Then:  the only place the arithmetic appears is the constant's own
               definition

        The criterion's own grep. A threshold copied to a use site is how two
        copies of one number start disagreeing -- and this number was already
        set once on a margin nobody re-checked.
        """
        srcRoot = Path(GUARD_MODULE_PATH).resolve().parents[2]
        pattern = re.compile(r"20\s*\*\s*1024")

        offenders = []
        for path in srcRoot.rglob("*.py"):
            for lineNo, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1
            ):
                if not pattern.search(line):
                    continue
                if "LOW_DISK_THRESHOLD_BYTES" in line:
                    continue  # the definition itself
                offenders.append(f"{path.name}:{lineNo}")

        assert not offenders, offenders


class TestBothSidesOfTheThreshold:
    """Acceptance 1 -- healthy and breached, with an injected reader."""

    def test_ampleSpace_isHealthy_andLogsNoError(self, caplog) -> None:
        """
        Given: 95 GB free -- what the car actually has
        When:  the guard runs
        Then:  HEALTHY, and nothing is logged at ERROR
        """
        with caplog.at_level("ERROR"):
            state = assessDiskSpace(freeSpaceReader=_reader(95 * _GB))

        assert state.verdict is DiskVerdict.HEALTHY
        assert state.freeBytes == 95 * _GB
        assert state.thresholdBytes == LOW_DISK_THRESHOLD_BYTES
        assert not caplog.records

    def test_belowThreshold_isBreached_andLogsAtError(self, caplog) -> None:
        """
        Given: 19 GB free, just under the threshold
        When:  the guard runs
        Then:  BREACHED, and an ERROR line carries the numbers
        """
        with caplog.at_level("ERROR"):
            state = assessDiskSpace(freeSpaceReader=_reader(19 * _GB))

        assert state.verdict is DiskVerdict.BREACHED
        assert state.freeBytes == 19 * _GB
        assert [r for r in caplog.records if r.levelname == "ERROR"]

    def test_exactlyAtTheThreshold_isHealthy(self) -> None:
        """
        Given: free space exactly equal to the threshold
        When:  the guard runs
        Then:  HEALTHY -- the breach is BELOW, not at

        Pinned because an off-by-one here decides whether the first alert
        fires a day early or a day late, and nobody would notice either.
        """
        state = assessDiskSpace(freeSpaceReader=_reader(LOW_DISK_THRESHOLD_BYTES))

        assert state.verdict is DiskVerdict.HEALTHY


class TestAnUnreadableFilesystemIsATypedAbsence:
    """Acceptance 5 -- never a pass."""

    @pytest.mark.parametrize(
        "exc",
        [OSError("no such path"), PermissionError("denied")],
        ids=["missing", "denied"],
    )
    def test_aRaisingReader_isUnknown_notHealthy(self, exc: Exception) -> None:
        """
        Given: a free-space read that raises
        When:  the guard runs
        Then:  UNKNOWN, with no fabricated number and no passing verdict

        The absence of a failure signal is not a success signal. Reporting
        HEALTHY here would be the guard asserting the disk is fine on the
        evidence that it could not look.
        """
        state = assessDiskSpace(freeSpaceReader=_raisingReader(exc))

        assert state.verdict is DiskVerdict.UNKNOWN
        assert state.verdict is not DiskVerdict.HEALTHY
        assert state.freeBytes is None
        assert state.reason

    def test_unknownDoesNotFabricateCandidates(self) -> None:
        """
        Given: an unreadable filesystem
        When:  the guard runs
        Then:  the candidate list is empty rather than guessed
        """
        state = assessDiskSpace(freeSpaceReader=_raisingReader(OSError()))

        assert state.candidates == ()


class TestCandidatesAreRankedBySizeAndAge:
    """Acceptance 3 -- largest-and-oldest first, bounded."""

    def test_candidatesAreRanked_largestAndOldestFirst(self, tmp_path) -> None:
        """
        Given: a fixture tree of differently sized and aged files
        When:  a breach is assessed
        Then:  the big old one outranks the small recent one

        The story's worked example: a 5.4 GB 53-day-old backup outranks a
        40 MB 9-day-old log. Size AND age together, because a huge NEW file
        may still be in use and a tiny OLD one buys nothing.
        """
        import os
        import time

        big = tmp_path / "obd-20260801.db"
        big.write_bytes(b"x" * 4096)
        small = tmp_path / "old.log"
        small.write_bytes(b"x" * 16)

        oldTime = time.time() - 53 * 86400
        recentTime = time.time() - 9 * 86400
        os.utime(big, (oldTime, oldTime))
        os.utime(small, (recentTime, recentTime))

        state = assessDiskSpace(
            freeSpaceReader=_reader(19 * _GB), searchRoots=(tmp_path,),
        )

        assert state.verdict is DiskVerdict.BREACHED
        names = [Path(c.path).name for c in state.candidates]
        assert names.index("obd-20260801.db") < names.index("old.log")

    def test_eachCandidateCarriesPathSizeAndAge(self, tmp_path) -> None:
        """
        Given: one clearable file
        When:  it is reported
        Then:  the entry carries a path, a size and an age

        A path alone is not actionable -- the whole point is deciding what is
        worth clearing, which needs both numbers.
        """
        target = tmp_path / "backup.db"
        target.write_bytes(b"x" * 2048)

        state = assessDiskSpace(
            freeSpaceReader=_reader(19 * _GB), searchRoots=(tmp_path,),
        )

        entry = state.candidates[0]
        assert entry.path.endswith("backup.db")
        assert entry.sizeBytes == 2048
        assert entry.ageDays >= 0

    def test_theCandidateListIsBounded(self, tmp_path) -> None:
        """
        Given: far more clearable files than the report should carry
        When:  a breach is assessed
        Then:  the list is capped

        An unbounded list turns an alert into a directory listing, and an
        alert nobody reads is the same as no alert.
        """
        for i in range(MAX_REPORTED_CANDIDATES + 15):
            (tmp_path / f"f{i:03d}.log").write_bytes(b"x" * (100 + i))

        state = assessDiskSpace(
            freeSpaceReader=_reader(19 * _GB), searchRoots=(tmp_path,),
        )

        assert len(state.candidates) == MAX_REPORTED_CANDIDATES

    def test_healthyDoesNotRankCandidates(self, tmp_path) -> None:
        """
        Given: ample free space and a tree full of files
        When:  the guard runs
        Then:  no candidates are listed

        Walking the tree on every healthy check would be work done for
        nothing, on the tier that can least afford it.
        """
        (tmp_path / "big.db").write_bytes(b"x" * 4096)

        state = assessDiskSpace(
            freeSpaceReader=_reader(95 * _GB), searchRoots=(tmp_path,),
        )

        assert state.candidates == ()


class TestTheGuardNeverDeletes:
    """Acceptance 4 -- it reports; removal is a human or another story."""

    def test_noDeletionCallExistsInTheModule(self) -> None:
        """
        Given: the guard module
        When:  it is scanned for deletion calls
        Then:  there are none

        The criterion's own grep. The CIO asked what MIGHT help clear space;
        acting on that is a behaviour change and needs its own ruling.
        """
        source = Path(GUARD_MODULE_PATH).read_text(encoding="utf-8")

        for banned in ("unlink", "rmtree", "os.remove"):
            assert banned not in source, f"the guard can delete: {banned}"

    def test_assessingABreachLeavesTheTreeIntact(self, tmp_path) -> None:
        """
        Given: a fixture tree
        When:  a breach is assessed over it
        Then:  every file is still there

        The grep proves the code cannot delete; this proves the run did not.
        """
        for name in ("a.db", "b.log", "c.tmp"):
            (tmp_path / name).write_bytes(b"x" * 512)
        before = {p.name for p in tmp_path.iterdir()}

        assessDiskSpace(freeSpaceReader=_reader(19 * _GB), searchRoots=(tmp_path,))

        assert {p.name for p in tmp_path.iterdir()} == before

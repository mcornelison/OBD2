# ==============================================================================
# File:        tests/pm/test_backfill_sprint_validation.py
# Purpose:     Cover tools.pm.backfill_sprint_validation -- the US-569 tool that
#              stamps validation onto an ARCHIVED sprint snapshot, refusing any
#              stamp that outruns its evidence.
# Author:      Rex (Ralph agent)
# Created:     2026-08-28
# ==============================================================================
# Why these tests are shaped this way
# -----------------------------------
# US-569 carries two named traps (Atlas F-8) and both are asserted here, not
# merely commented:
#
#   (a) 52 archive snapshots exist for 27 sprints.  chain_validate_aggregate
#       collapses duplicates via _snapshotAuthorityKey, so stamping a
#       NON-authoritative snapshot succeeds, reports success, and changes
#       nothing the gate reads -- the inert-guard defect.  So the assertions
#       below never read the stamped file back to prove the stamp took; they
#       RE-RUN aggregateChain and ask the reader what it now sees.
#
#   (b) it is a scripted rewrite on a tree with NO git revert, so a write
#       requires an explicit --snapshot-confirmed precondition.  That flag is
#       tested as a refusal, because a precondition nobody can fail is not a
#       precondition.
#
# Every test drives a synthetic V0.99.x chain under a tmp $FLEET_SHARE.  The
# share root is resolved lazily by tools.pm._paths.resolveShareRoot (it reads
# os.environ at CALL time), so monkeypatch.setenv is sufficient -- no module
# reloads, no import-order coupling.
# ==============================================================================

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.pm import backfill_sprint_validation as backfill
from tools.pm import chain_validate_aggregate as aggregate
from tools.pm._paths import resolveShareRoot

_SHARE_ENV = "FLEET_SHARE"

# A --snapshot-confirmed value the tool must accept: today, per the clock the
# tool itself uses.  Hard-coding a date would rot the suite the moment the
# staleness window elapsed.
_TODAY = backfill.todayIso()


# ==============================================================================
# Fixtures / helpers
# ==============================================================================
def _writeSnapshot(
    path: Path,
    *,
    currentVersion: str,
    validatedAt: str | None = None,
    validatedBy: str | None = None,
    validatedEvidence: str | None = None,
    sprintTitle: str = "Synthetic Sprint",
) -> Path:
    """Write a minimal sprint.json snapshot with just enough schema to aggregate."""
    validation: dict = {
        "bigDefinitionOfDone": [f"Clause for {currentVersion}"],
        "validationMethod": "synthetic",
        "validatesFeatures": ["F-999"],
        "currentVersion": currentVersion,
        "validatedAt": validatedAt,
        "validatedBy": validatedBy,
    }
    if validatedEvidence is not None:
        validation["validatedEvidence"] = validatedEvidence

    payload = {"sprint": sprintTitle, "stories": [], "validation": validation}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


@pytest.fixture()
def share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point $FLEET_SHARE at a tmp share root laid out like the real one."""
    root = tmp_path / "offices"
    (root / "ralph" / "archive").mkdir(parents=True)
    monkeypatch.setenv(_SHARE_ENV, str(root))
    return root


def _archiveDir(share: Path) -> Path:
    return share / "ralph" / "archive"


def _aggregateFor(chainPrefix: str) -> dict:
    """Re-run the READER over the tmp share -- never read the stamped file back."""
    return aggregate.aggregateChain(backfill.discoverSnapshotPaths(), chainPrefix)


def _validatedAtSeenByReader(chainPrefix: str, version: str) -> str | None:
    for record in _aggregateFor(chainPrefix)["sprintsInChain"]:
        if record["currentVersion"] == version:
            return record["validatedAt"]
    raise AssertionError(f"{version} is not in the {chainPrefix} aggregate at all")


# ==============================================================================
# 1. Evidence is mandatory -- a stamp that outruns its evidence is refused
# ==============================================================================
class TestEvidenceIsMandatory:
    """--evidence is required and non-empty; without it nothing is written."""

    def test_main_evidenceOmitted_refusesAndWritesNothing(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: an unstamped archived snapshot for V0.99.7
        When:  the tool runs with no --evidence at all
        Then:  it exits non-zero, says why, and the file is byte-identical
        """
        snap = _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")
        before = snap.read_bytes()

        code = backfill.main(
            ["--version", "V0.99.7", "--snapshot-confirmed", _TODAY]
        )

        assert code == 1
        assert "--evidence" in capsys.readouterr().err
        assert snap.read_bytes() == before

    def test_main_evidenceBlank_refusesAndWritesNothing(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: an unstamped archived snapshot for V0.99.7
        When:  --evidence is supplied but is only whitespace
        Then:  it is treated as absent -- refused, nothing written

        A whitespace stamp is the fabricated-evidence case in its laziest form;
        it must not slip past a truthiness check on the raw string.
        """
        snap = _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")
        before = snap.read_bytes()

        code = backfill.main(
            ["--version", "V0.99.7", "--evidence", "   ", "--snapshot-confirmed", _TODAY]
        )

        assert code == 1
        assert "--evidence" in capsys.readouterr().err
        assert snap.read_bytes() == before


# ==============================================================================
# 2. The stamp is visible to the READER, not merely to the filesystem
# ==============================================================================
class TestStampIsVisibleToTheAggregator:
    """A successful stamp changes what chain_validate_aggregate reports."""

    def test_main_stampsVersion_aggregatorNowCountsItValidated(self, share: Path) -> None:
        """
        Given: V0.99.7 archived with validatedAt = null
        When:  the tool stamps it with evidence
        Then:  RE-RUNNING aggregateChain reports a non-null validatedAt for it

        This is the anti-inert-guard assertion: the proof is what the reader
        sees, not what the file contains.
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")
        assert _validatedAtSeenByReader("V0.99", "V0.99.7") is None

        code = backfill.main(
            [
                "--version",
                "V0.99.7",
                "--evidence",
                "Drive 112 log + CIO confirmation 2026-08-28",
                "--by",
                "Mike (CIO confirmed)",
                "--snapshot-confirmed",
                _TODAY,
            ]
        )

        assert code == 0
        assert _validatedAtSeenByReader("V0.99", "V0.99.7") is not None

    def test_main_recordsEvidenceIntoValidatedEvidence(self, share: Path) -> None:
        """
        Given: an unstamped V0.99.7 snapshot
        When:  the tool stamps it
        Then:  validation.validatedEvidence carries the basis, not just a date

        A date alone is unauditable later -- the whole point of the field.
        """
        snap = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )

        code = backfill.main(
            [
                "--version",
                "V0.99.7",
                "--evidence",
                "Drive 112 log + CIO confirmation 2026-08-28",
                "--by",
                "Mike (CIO confirmed)",
                "--snapshot-confirmed",
                _TODAY,
            ]
        )

        assert code == 0
        validation = json.loads(snap.read_text(encoding="utf-8"))["validation"]
        assert validation["validatedEvidence"] == "Drive 112 log + CIO confirmation 2026-08-28"
        assert validation["validatedBy"] == "Mike (CIO confirmed)"

    def test_main_preservesUnrelatedContent(self, share: Path) -> None:
        """
        Given: a snapshot carrying stories and a bigDefinitionOfDone
        When:  the tool stamps it
        Then:  everything except the three validation fields is untouched
        """
        snap = _archiveDir(share) / "sprint.archive.A.json"
        _writeSnapshot(snap, currentVersion="V0.99.7", sprintTitle="Sprint 99")
        before = json.loads(snap.read_text(encoding="utf-8"))

        backfill.main(
            [
                "--version",
                "V0.99.7",
                "--evidence",
                "e",
                "--snapshot-confirmed",
                _TODAY,
            ]
        )

        after = json.loads(snap.read_text(encoding="utf-8"))
        assert after["sprint"] == before["sprint"]
        assert after["stories"] == before["stories"]
        assert after["validation"]["bigDefinitionOfDone"] == (
            before["validation"]["bigDefinitionOfDone"]
        )
        assert after["validation"]["currentVersion"] == "V0.99.7"


# ==============================================================================
# 3. Trap (a) -- stamp the snapshot the AGGREGATOR selects
# ==============================================================================
class TestStampsTheAuthoritativeSnapshot:
    """With duplicate snapshots per version, the aggregator's winner is the target."""

    def test_main_duplicateSnapshots_stampsTheOneTheAggregatorSelects(
        self, share: Path
    ) -> None:
        """
        Given: two unstamped snapshots of V0.99.7 -- ...A.json and ...B.json.
               Neither is validated, so _snapshotAuthorityKey falls through to
               path-name ordering and the aggregator reads B.
        When:  the tool stamps V0.99.7
        Then:  B carries the stamp and A does not

        Stamping A would report success and change nothing the gate reads.
        """
        loser = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )
        winner = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.B.json", currentVersion="V0.99.7"
        )
        selected = aggregate.aggregateChain(
            backfill.discoverSnapshotPaths(), "V0.99"
        )["sprintsInChain"][0]["path"]
        assert Path(selected) == winner, "precondition: the aggregator reads B"

        code = backfill.main(
            ["--version", "V0.99.7", "--evidence", "e", "--snapshot-confirmed", _TODAY]
        )

        assert code == 0
        assert json.loads(winner.read_text(encoding="utf-8"))["validation"]["validatedAt"]
        assert json.loads(loser.read_text(encoding="utf-8"))["validation"]["validatedAt"] is None

    def test_main_archiveNamesNonAuthoritativeSnapshot_refusesAndNamesTheRealOne(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: duplicate snapshots where the aggregator reads B
        When:  the operator explicitly targets A by filename
        Then:  the tool refuses and prints the path the aggregator actually reads

        Honouring the request here would be the inert write, dressed up as an
        operator decision.
        """
        loser = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )
        _writeSnapshot(_archiveDir(share) / "sprint.archive.B.json", currentVersion="V0.99.7")
        before = loser.read_bytes()

        code = backfill.main(
            [
                "--archive",
                "sprint.archive.A.json",
                "--evidence",
                "e",
                "--snapshot-confirmed",
                _TODAY,
            ]
        )

        assert code == 1
        assert "sprint.archive.B.json" in capsys.readouterr().err
        assert loser.read_bytes() == before

    def test_main_archiveNamesTheAuthoritativeSnapshot_stamps(self, share: Path) -> None:
        """
        Given: a single snapshot for V0.99.7, targeted by filename
        When:  the tool runs
        Then:  it stamps -- --archive is a supported selector, not a trap
        """
        snap = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )

        code = backfill.main(
            [
                "--archive",
                "sprint.archive.A.json",
                "--evidence",
                "e",
                "--snapshot-confirmed",
                _TODAY,
            ]
        )

        assert code == 0
        assert json.loads(snap.read_text(encoding="utf-8"))["validation"]["validatedAt"]


# ==============================================================================
# 4. Double-stamp detection (mirrors /sprint-validated Phase 0)
# ==============================================================================
class TestDoubleStamp:
    """An existing validatedAt is refused unless --force."""

    def test_main_runTwice_secondRunRefusesAsDoubleStamp(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: a snapshot already stamped by a first run
        When:  the tool runs again without --force
        Then:  it refuses and leaves the first stamp byte-identical
        """
        snap = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )
        args = ["--version", "V0.99.7", "--evidence", "first", "--snapshot-confirmed", _TODAY]
        assert backfill.main(args) == 0
        afterFirst = snap.read_bytes()

        code = backfill.main(
            ["--version", "V0.99.7", "--evidence", "second", "--snapshot-confirmed", _TODAY]
        )

        assert code == 1
        assert "--force" in capsys.readouterr().err
        assert snap.read_bytes() == afterFirst

    def test_main_force_overwritesTheExistingStamp(self, share: Path) -> None:
        """
        Given: an already-stamped snapshot
        When:  the tool runs with --force
        Then:  the new evidence replaces the old
        """
        snap = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )
        backfill.main(
            ["--version", "V0.99.7", "--evidence", "first", "--snapshot-confirmed", _TODAY]
        )

        code = backfill.main(
            [
                "--version",
                "V0.99.7",
                "--evidence",
                "second",
                "--force",
                "--snapshot-confirmed",
                _TODAY,
            ]
        )

        assert code == 0
        assert json.loads(snap.read_text(encoding="utf-8"))["validation"][
            "validatedEvidence"
        ] == "second"


# ==============================================================================
# 5. --dry-run writes nothing
# ==============================================================================
class TestDryRun:
    """--dry-run prints the diff and touches no bytes."""

    def test_main_dryRun_printsDiffAndWritesNothing(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: an unstamped V0.99.7 snapshot
        When:  the tool runs with --dry-run
        Then:  the intended field values appear on stdout and the file is
               byte-identical; the aggregator still reports it unvalidated
        """
        snap = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )
        before = snap.read_bytes()

        code = backfill.main(
            ["--version", "V0.99.7", "--evidence", "Drive 112 log", "--dry-run"]
        )

        out = capsys.readouterr().out
        assert code == 0
        assert "validatedEvidence" in out
        assert "Drive 112 log" in out
        assert snap.read_bytes() == before
        assert _validatedAtSeenByReader("V0.99", "V0.99.7") is None

    def test_main_dryRun_doesNotRequireSnapshotConfirmation(self, share: Path) -> None:
        """
        Given: an unstamped snapshot and no --snapshot-confirmed
        When:  the tool runs with --dry-run
        Then:  it succeeds -- a preview cannot destroy anything, so gating it
               would only train operators to pass the flag reflexively
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")

        assert backfill.main(["--version", "V0.99.7", "--evidence", "e", "--dry-run"]) == 0

    def test_main_dryRun_stillRefusesWithoutEvidence(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: no --evidence
        When:  the tool runs with --dry-run
        Then:  it still refuses -- the preview must show the same refusal the
               real run would, or it is not a preview
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")

        assert backfill.main(["--version", "V0.99.7", "--dry-run"]) == 1
        assert "--evidence" in capsys.readouterr().err


# ==============================================================================
# 6. Trap (b) -- the no-revert precondition
# ==============================================================================
class TestSnapshotPrecondition:
    """A write into a tree with no git revert requires a confirmed backup."""

    def test_main_writeWithoutSnapshotConfirmation_refuses(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: a valid stamp request with evidence
        When:  --snapshot-confirmed is omitted on a real (non-dry) run
        Then:  it refuses and writes nothing

        The share is not version controlled; --dry-run and --force are good and
        insufficient (Atlas F-8 trap b).
        """
        snap = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )
        before = snap.read_bytes()

        code = backfill.main(["--version", "V0.99.7", "--evidence", "e"])

        assert code == 1
        assert "--snapshot-confirmed" in capsys.readouterr().err
        assert snap.read_bytes() == before

    def test_main_staleSnapshotDate_refuses(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: --snapshot-confirmed naming a date older than the freshness window
        When:  the tool runs
        Then:  it refuses -- an ancient backup is not a rollback path
        """
        snap = _writeSnapshot(
            _archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7"
        )
        before = snap.read_bytes()

        code = backfill.main(
            ["--version", "V0.99.7", "--evidence", "e", "--snapshot-confirmed", "2020-01-01"]
        )

        assert code == 1
        assert "stale" in capsys.readouterr().err.lower()
        assert snap.read_bytes() == before

    def test_main_futureSnapshotDate_refuses(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: --snapshot-confirmed naming a date in the future
        When:  the tool runs
        Then:  it refuses -- a future date is a typo or a fabrication, never a
               snapshot that exists
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")

        code = backfill.main(
            ["--version", "V0.99.7", "--evidence", "e", "--snapshot-confirmed", "2999-01-01"]
        )

        assert code == 1
        assert "future" in capsys.readouterr().err.lower()

    def test_main_unparseableSnapshotDate_refuses(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: --snapshot-confirmed that is not an ISO date
        When:  the tool runs
        Then:  it refuses rather than coercing junk into a passing check
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")

        assert (
            backfill.main(
                ["--version", "V0.99.7", "--evidence", "e", "--snapshot-confirmed", "yesterday"]
            )
            == 1
        )
        assert "YYYY-MM-DD" in capsys.readouterr().err


# ==============================================================================
# 7. Resolution failures are loud
# ==============================================================================
class TestResolutionFailures:
    """Unknown targets refuse; they never stamp something adjacent."""

    def test_main_unknownVersion_refuses(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: a share holding only V0.99.7
        When:  the tool is asked for V0.99.9
        Then:  it refuses by name rather than falling back to a neighbour
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")

        assert (
            backfill.main(
                ["--version", "V0.99.9", "--evidence", "e", "--snapshot-confirmed", _TODAY]
            )
            == 1
        )
        assert "V0.99.9" in capsys.readouterr().err

    def test_main_missingArchiveFile_refuses(
        self, share: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """
        Given: --archive naming a file that does not exist
        When:  the tool runs
        Then:  it refuses with the path it looked for
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")

        assert (
            backfill.main(
                [
                    "--archive",
                    "sprint.archive.NOPE.json",
                    "--evidence",
                    "e",
                    "--snapshot-confirmed",
                    _TODAY,
                ]
            )
            == 1
        )
        assert "sprint.archive.NOPE.json" in capsys.readouterr().err

    def test_main_versionAndArchiveTogether_refuses(self, share: Path) -> None:
        """
        Given: both selectors at once
        When:  the tool runs
        Then:  argparse rejects the pair -- two targets is an ambiguous request
        """
        _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")

        with pytest.raises(SystemExit):
            backfill.main(
                ["--version", "V0.99.7", "--archive", "sprint.archive.A.json", "--evidence", "e"]
            )

    def test_main_noSelector_refuses(self, share: Path) -> None:
        """
        Given: neither --version nor --archive
        When:  the tool runs
        Then:  argparse rejects it -- there is no default target, on purpose
        """
        with pytest.raises(SystemExit):
            backfill.main(["--evidence", "e"])


# ==============================================================================
# 8. Share resolution -- no parents[N] walk, no fallback, no drift
# ==============================================================================
class TestShareResolution:
    """Paths come from $FLEET_SHARE via _paths, and match the aggregator's."""

    def test_discoverSnapshotPaths_shareUnset_raises(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Given: $FLEET_SHARE unset
        When:  discovery runs
        Then:  it raises rather than resolving a plausible-looking path

        A silent fallback here would reproduce exactly the defect _paths.py
        exists to prevent: read nothing, report success.
        """
        monkeypatch.delenv(_SHARE_ENV, raising=False)

        with pytest.raises(RuntimeError, match=_SHARE_ENV):
            backfill.discoverSnapshotPaths()

    def test_discoverSnapshotPaths_findsArchivesAndCurrentSprint(self, share: Path) -> None:
        """
        Given: two archives plus a live sprint.json under the tmp share
        When:  discovery runs
        Then:  all three are enumerated
        """
        a = _writeSnapshot(_archiveDir(share) / "sprint.archive.A.json", currentVersion="V0.99.7")
        b = _writeSnapshot(_archiveDir(share) / "sprint.archive.B.json", currentVersion="V0.99.8")
        live = _writeSnapshot(share / "ralph" / "sprint.json", currentVersion="V0.99.9")

        found = set(backfill.discoverSnapshotPaths())

        assert found == {a, b, live}

    def test_pathBuilders_matchTheAggregatorsOwnConstants(self) -> None:
        """
        Given: the share root the aggregator resolved at import
        When:  this tool builds the same two paths
        Then:  they are identical

        Drift guard.  This tool re-derives the archive glob and the live
        sprint.json rather than reusing chain_validate_aggregate's module
        constants, because those are frozen at import time and cannot follow a
        test's $FLEET_SHARE.  That re-derivation is a duplicated fact, so it is
        pinned here: if either side moves the layout, this fails.
        """
        root = resolveShareRoot()

        assert backfill.archiveGlobFor(root) == aggregate.DEFAULT_ARCHIVE_GLOB
        assert backfill.currentSprintFor(root) == aggregate.DEFAULT_CURRENT_SPRINT

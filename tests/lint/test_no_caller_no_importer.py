################################################################################
# File Name: test_no_caller_no_importer.py
# Purpose/Description: US-724 -- detect a complete, correct implementation that
#     nothing in production reaches. Two static-symbol shapes, as defined by
#     Atlas at the 2026-09-10 design gate:
#       * a src/ module that no production file imports (A-28, pi.pollingTiers)
#       * a src/ top-level function referenced only from tests/ (A-16, the
#         carousel emitters)
#     The third measured instance -- ARCH-023, an injected clearRunner that no
#     production call site ever supplied -- is NOT visible to this scan, by
#     construction, and is pinned below as a limit. It is US-725.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Rex (US-724) | Initial -- no-importer / tests-only-caller scan,
#               |              | explicit allow-list, known-dead ledger, the
#               |              | three real instances as validation.
# ================================================================================
################################################################################

"""Lint: a src/ implementation that nothing in production imports or calls.

THE SHAPE
---------
Every part is right, so it passes review. The defect is the ABSENCE of a join,
which is invisible in a diff that only adds things. Three have shipped.

WHAT THIS GUARD CATCHES (two of the three, measured)
----------------------------------------------------
* A-28 -- ``src/pi/obdii/data/polling_tiers.py``: no production importer.
  Validated on the CURRENT tree, where it is still present.
* A-16 -- the carousel card emitters: validated on the real tree as it was
  immediately before US-480-a wired them (``f929ed8a^``), and on the wiring
  commit itself, where the three it wired drop out and the one it did not
  (``ltft_trend_emitter``) stays reported.

  ⚠️ "Zero importers ANYWHERE" (the gate's wording) would MISS A-28: two test
  modules import ``polling_tiers``. The implemented predicate is "no importer
  outside ``tests/``", which is what every in-tree description of A-28 means
  ("zero importers in src/").

WHAT THIS GUARD DOES NOT CATCH
------------------------------
* ARCH-023 -- ``states_http_server`` declared ``clearRunner: Callable | None =
  None``, referenced it twice, and its ``is None -> 503`` branch was live and
  correct. Nothing was uncalled: the ARGUMENT was never passed. A symbol scan
  has nothing to flag, and ``TestTheThreeMeasuredInstances`` pins that it
  flags nothing on the pre-fix tree. That shape is US-725.
* Transitive deadness: a module imported only by another dead module looks
  live (``src/calibration/fit_reader.py`` is imported only by the dead
  ``speed_aligner.py``).
* Methods: overrides, Protocol members and callbacks are legitimately
  caller-less to a static scan, and none of the three instances was a method.
* Name collisions: callers are matched by NAME, so a dead function that shares
  its name with any live reference is invisible. That trades recall for a low
  false-positive rate, on purpose.
* A function referenced nowhere at all, not even by a test: outside the settled
  definition ("called only from tests/").
* Whatever a shape exempts is not looked at again. The 7 package re-exports
  exempted on 2026-09-10 have no production caller either; under the ruling,
  published API is not a finding.

MEASURED FALSE-POSITIVE RATE (2026-09-10)
-----------------------------------------
Measured with a census BEFORE the predicate was chosen, then again on the final
one (offices/ralph/evidence/US-724-dead-code-census.md).

* Final predicate, current tree: 78 candidates. 24 are legitimately caller-less
  and exempted by a NAMED shape in ``ALLOW_SHAPES`` (17 main-block, 7
  package-reexport; service-entry matched nothing on its own, because every
  module a unit runs also has a main block). Of the 54 left, 6 are dead on
  purpose and listed one by one in ``INTENTIONAL_TEST_CONSUMERS``: 6/54 = 11%
  residual. The other 48 are real dead code already on the tree, each ledgered
  in ``KNOWN_DEAD`` with a reason (TD-us724). The gate is a ratchet: new dead
  code fails, and an entry that stops being dead must be removed.
* Rejected variant: counting a module's own ``__all__`` entry as a caller. It
  had the same false positives and hid 13 real tests-only functions.
  Publishing a name is not calling it.
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import tarfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SHAPE_NO_IMPORTER = "no-production-importer"
SHAPE_TESTS_ONLY = "referenced-only-from-tests"

# The commits the real-instance validation runs against.
A16_WIRING_COMMIT = "f929ed8a31f27e96384657791c26b53de9b71992"  # US-480-a
ARCH023_FIX_COMMIT = "39f20f04d404a531a8ed0c53d052489a5efc44e2"  # ARCH-023


@dataclass(frozen=True)
class Candidate:
    """A src/ symbol that nothing in production reaches."""

    shape: str
    path: str  # repo-relative, posix
    symbol: str  # dotted module name, or the function name
    line: int

    @property
    def key(self) -> str:
        if self.shape == SHAPE_NO_IMPORTER:
            return self.path
        return f"{self.path}::{self.symbol}"


@dataclass(frozen=True)
class AllowShape:
    """A legitimately caller-less shape -- named, with the reason it is not a finding."""

    name: str
    reason: str


MAIN_BLOCK = AllowShape(
    "main-block",
    "an `if __name__ == '__main__':` block or a `__main__.py` is a console entry "
    "point: it is RUN, not imported (Atlas design gate 2026-09-10).",
)
SERVICE_ENTRY = AllowShape(
    "service-entry",
    "named by `python -m <module>` or `python src/<path>.py` in deploy/, the "
    "Makefile or a shell script under scripts/: systemd ExecStart or the deploy "
    "invokes it (Atlas design gate 2026-09-10).",
)
PACKAGE_REEXPORT = AllowShape(
    "package-reexport",
    "imported by a package `__init__.py` AND listed in that `__init__`'s "
    "`__all__`: published public API (Atlas design gate 2026-09-10). A name the "
    "`__init__` imports but does not list is not published, so it is not exempt.",
)
ALLOW_SHAPES = (MAIN_BLOCK, SERVICE_ENTRY, PACKAGE_REEXPORT)


@dataclass(frozen=True)
class ScanResult:
    findings: tuple[Candidate, ...]
    exempted: tuple[tuple[Candidate, AllowShape], ...]
    subjectFiles: tuple[str, ...]


# ---------------------------------------------------------------------------
# Dead ON PURPOSE -- not one of Atlas's shapes, so listed one symbol at a time.
# These are the measured residual false positives. Each must still be a finding
# (TestStandingGate), so an entry cannot outlive its reason.
# ---------------------------------------------------------------------------
_PAIR_TEST = "its header names a test as its designed consumer"
INTENTIONAL_TEST_CONSUMERS: dict[str, str] = {
    "src/server/analytics/owned_tables.py": (
        f"US-449 sole-writer manifest; {_PAIR_TEST} -- it exists so 'the harness "
        "is the sole writer' is a checkable contract."
    ),
    "src/server/db/vehicle_info_coherence.py": (
        f"US-376 coherence checker; {_PAIR_TEST} ('the read-side checker a "
        "regression test ... uses')."
    ),
    "src/pi/data/connection_logger.py::resetDedupStateForTests": (
        "a test seam, and named as one."
    ),
    "src/pi/obdii/bond_self_heal.py::resetSelfHealRequestBudget": (
        "a test seam; its docstring says '(tests only)'."
    ),
    "src/server/services/analysis.py::enqueueAutoAnalysisForSync": (
        "US-350 retirement tripwire: it always raises, so a production caller is "
        "the regression it exists to catch."
    ),
    "src/server/migrations/versions/v0024_us563_unassessed_defaults_and_intake_rename.py"
    "::discoverDataQualityDefaultsSql": (
        "the SQL the applied-schema DEFAULT probe "
        "(tests/server/test_applied_schema_column_defaults.py) runs against the server."
    ),
}

# ---------------------------------------------------------------------------
# Real dead code already on the tree, 2026-09-10 (TD-us724). The gate does not
# go red for these; it goes red for anything NEW, and for an entry here that is
# no longer dead (delete the entry when the code is wired or removed).
# ---------------------------------------------------------------------------
_SKELETON = "empty skeleton: a header and a docstring, no code"
_PYGAME = "pygame-era screen; the pygame UI is sunset and only tests import it"
_OBD_EXPORT = (
    "reachable only through `obd.export`, a pre-reorg path that no longer "
    "exists -- dead, and an ImportError if anything tried"
)
KNOWN_DEAD: dict[str, str] = {
    "src/calibration/speed_aligner.py": (
        "Atlas's offline SPEED-PID factor estimator; nothing in the tree calls it."
    ),
    "src/common/constants.py": _SKELETON,
    "src/common/contracts/alerts.py": _SKELETON,
    "src/common/contracts/backup.py": _SKELETON,
    "src/common/contracts/drive_log.py": _SKELETON,
    "src/common/contracts/protocol.py": _SKELETON,
    "src/common/contracts/recommendations.py": _SKELETON,
    "src/common/contracts/vehicle.py": _SKELETON,
    "src/common/time/helper.py::localNaiveToCanonicalIso": (
        "US-809-0 STAGED, and wired by US-809-a in this same sprint. US-809-0's "
        "scope fence is 'declaring and validating the zone ... NOT converting "
        "anything (US-809-a)', while its own acceptance requires the refusal "
        "path to exist and be tested -- so the conversion necessarily lands one "
        "story ahead of its first producer. DELETE THIS ENTRY when US-809-a "
        "wires it; test_everyLedgerEntryIsStillAFinding goes red if you forget."
    ),
    "src/pi/clients/ollama_client.py": _SKELETON,
    "src/pi/clients/uploader.py": _SKELETON,
    "src/pi/inbox/reader.py": _SKELETON,
    "src/pi/data/recent_stats.py": (
        "pygame-era min/max query (imports primary_screen_advanced); only tests import it."
    ),
    "src/pi/display/screens/boost_detail.py": _PYGAME,
    "src/pi/display/screens/fuel_detail.py": _PYGAME,
    "src/pi/display/screens/knock_detail.py": _PYGAME,
    "src/pi/display/screens/parked_mode.py": _PYGAME,
    "src/pi/display/screens/thermal_detail.py": _PYGAME,
    "src/pi/display/screens/touch_interactions.py": _PYGAME,
    "src/pi/obdii/data/polling_tiers.py": (
        "A-28: describes a tiered poller this system does not run (TD-us686)."
    ),
    "src/pi/obdii/data_exporter.py": _OBD_EXPORT,
    "src/pi/obdii/export/exporter.py": _OBD_EXPORT,
    "src/pi/obdii/export/helpers.py": _OBD_EXPORT,
    "src/pi/obdii/export/realtime.py": _OBD_EXPORT,
    "src/pi/obdii/export/summary.py": _OBD_EXPORT,
    "src/pi/obdii/export/summary_fetchers.py": _OBD_EXPORT,
    "src/pi/obdii/export/types.py": _OBD_EXPORT,
    "src/pi/obdii/data_retention.py": (
        "DataRetentionManager: no importer anywhere, tests included."
    ),
    "src/server/analytics/speed_pid_calibration.py": (
        "writer-path guard + analytics gate for speed_pid_calibration; no "
        "production writer or reader calls either."
    ),
    "src/server/api/dtc_freeze_frame.py": (
        "insertDtcFreezeFrame, the direct (non-sync) insert SSOT: sync upserts by "
        "its own path (sync.py) and no non-sync writer exists."
    ),
    "src/common/config/secrets_loader.py::maskSecret": "no production caller.",
    "src/common/errors/handler.py::retry": (
        "the retry decorator CLAUDE.md documents as the retry pattern; nothing "
        "in production decorates with it."
    ),
    "src/common/errors/handler.py::formatError": "no production caller.",
    "src/common/logging/setup.py::logWithContext": "no production caller.",
    "src/pi/display/screens/primary_screen.py::buildPrimaryScreenState": (
        "pygame-era Phase-1/2 state builder; only tests call it."
    ),
    "src/pi/display/screens/system_detail.py::buildSystemDetailState": (
        "pygame-era state builder; only tests call it."
    ),
    "src/server/analytics/basic.py::collectReadingsForDrive": "no production caller.",
    "src/server/services/analysis.py::_writeDriveAnalytics": (
        "private helper with no production caller; only tests reach it."
    ),
    "src/server/services/analysis.py::_safeRunAnalysis": (
        "private helper with no production caller; only tests reach it."
    ),
    "src/pi/display/live_readings.py::resolveGaugeName": "no production caller.",
    "src/pi/obdii/drive_id.py::makeDriveIdGenerator": (
        "shown in engine_state.py's Usage docstring; no production caller."
    ),
    "src/pi/obdii/gear_derivation.py::bandsFromGearRatios": "no production caller.",
    "src/pi/obdii/pi_state.py::clearNoNewDrives": (
        "the no_new_drives gate lost both writers when 9adb0fbf deleted the "
        "PowerDownOrchestrator ladder; the drive detector still reads the flag."
    ),
    "src/pi/splash/ltft_trend_emitter.py::qualifyingLtftSamples": "no production caller.",
    "src/server/analytics/drive_identity.py::map_overlap_to_canonical": (
        "no production caller."
    ),
    "src/server/db/models.py::isRoundedOdometer": "no production caller.",
    "src/server/services/analysis.py::pingOllama": (
        "no production caller; analysis.py's history ties it to the retired "
        "sync-receipt seam (US-350)."
    ),
    "src/server/services/analysis.py::extractDriveBoundaries": (
        "no production caller; a seam of the retired sync-receipt trigger (US-350)."
    ),
    "src/server/services/analysis.py::extractDriveIdsFromDriveSummaryPayload": (
        "no production caller; a seam of the retired sync-receipt trigger (US-350)."
    ),
}


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------


_SUBJECT_ROOT = "src"
# Where a JOIN counts. tests/ is deliberately absent: a test importer is exactly
# what kept A-28 looking alive.
_PRODUCTION_ROOTS = ("src", "scripts", "tools")
_TEST_ROOT = "tests"
# Text that invokes a module without importing it (systemd units, deploy
# scripts, make targets).
_ENTRY_TEXT_GLOBS = ("deploy/**/*", "Makefile", "scripts/**/*.sh")

_DASH_M = re.compile(r"-m\s+([A-Za-z_][\w.]*)")
_SCRIPT_PATH = re.compile(r"\b(src/[\w/.-]+\.py)\b")
_DOTTED = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")


def _normalise(moduleName: str) -> str:
    """One name per module: the Pi imports ``pi.x``, the server ``src.server.x``."""
    return moduleName[len("src.") :] if moduleName.startswith("src.") else moduleName


def _moduleName(relative: str) -> str:
    parts = relative[: -len(".py")].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return _normalise(".".join(parts))


def _pyFiles(root: Path, top: str) -> list[Path]:
    base = root / top
    if not base.is_dir():
        return []
    return sorted(p for p in base.rglob("*.py") if "__pycache__" not in p.parts)


def _parseOrNone(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), str(path))
    except (SyntaxError, UnicodeDecodeError, ValueError):
        return None


def _importedModules(relative: str, tree: ast.Module) -> set[str]:
    """Every module name ``tree`` can load, relative imports resolved.

    ``from pkg import name`` yields both ``pkg`` and ``pkg.name`` because the
    name may be a submodule. A string constant that is exactly a dotted name
    counts too (``importlib.import_module('pi.x')``); prose never is.
    """
    package = relative[: -len(".py")].split("/")[:-1]
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join([*base, *([node.module] if node.module else [])])
            else:
                module = node.module or ""
            names.add(module)
            names.update(f"{module}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _DOTTED.fullmatch(node.value)
        ):
            names.add(node.value)
    return {_normalise(name) for name in names}


def _allListed(tree: ast.Module) -> tuple[set[str], set[int]]:
    """Names in the module-level ``__all__``, and the ids of those string nodes."""
    listed: set[str] = set()
    nodeIds: set[int] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets, value = [node.target], node.value
        else:
            continue
        if value is None or not any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets):
            continue
        for sub in ast.walk(value):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                listed.add(sub.value)
                nodeIds.add(id(sub))
    return listed, nodeIds


def _references(tree: ast.Module, *, isPackageInit: bool) -> tuple[set[str], set[str]]:
    """(names this file references, names it re-exports).

    A reference is a Name, an attribute, or an identifier string (getattr and
    dispatch tables). A module's own ``__all__`` entries are NOT references --
    publishing a name is not calling it. In a package ``__init__`` an imported
    name is a re-export when ``__all__`` lists it, and nothing otherwise.
    """
    listed, allNodeIds = _allListed(tree)
    refs: set[str] = set()
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            refs.add(node.id)
        elif isinstance(node, ast.Attribute):
            refs.add(node.attr)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.isidentifier()
            and id(node) not in allNodeIds
        ):
            refs.add(node.value)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            imported.update(alias.name.split(".")[-1] for alias in node.names)
    if isPackageInit:
        return refs, imported & listed
    return refs | imported, set()


def _hasMainBlock(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            operands = [node.test.left, *node.test.comparators]
            if any(isinstance(o, ast.Name) and o.id == "__name__" for o in operands) and any(
                isinstance(o, ast.Constant) and o.value == "__main__" for o in operands
            ):
                return True
    return False


def _entryPoints(root: Path) -> tuple[set[str], set[str]]:
    """(modules run with ``-m``, src/ paths run directly) named in entry text."""
    modules: set[str] = set()
    paths: set[str] = set()
    for pattern in _ENTRY_TEXT_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            modules.update(_normalise(m) for m in _DASH_M.findall(text))
            paths.update(_SCRIPT_PATH.findall(text))
    return modules, paths


def scanTree(root: Path) -> ScanResult:
    """Scan the tree at ``root`` for the two shapes.

    Subject: every module under src/. A subject file that does not parse
    raises -- a blind spot is not allowed to pass as clean.
    """
    subject: dict[str, ast.Module] = {
        p.relative_to(root).as_posix(): ast.parse(p.read_text(encoding="utf-8"), str(p))
        for p in _pyFiles(root, _SUBJECT_ROOT)
    }

    production: dict[str, ast.Module] = dict(subject)
    candidatesOutsideSubject = [
        p for top in _PRODUCTION_ROOTS if top != _SUBJECT_ROOT for p in _pyFiles(root, top)
    ] + sorted(root.glob("*.py"))
    for path in candidatesOutsideSubject:
        tree = _parseOrNone(path)
        if tree is not None:
            production[path.relative_to(root).as_posix()] = tree

    importedByProduction: set[str] = set()
    productionRefs: set[str] = set()
    reexported: set[str] = set()
    for relative, tree in production.items():
        importedByProduction |= _importedModules(relative, tree)
        refs, exports = _references(tree, isPackageInit=relative.endswith("__init__.py"))
        productionRefs |= refs
        reexported |= exports

    testRefs: set[str] = set()
    for path in _pyFiles(root, _TEST_ROOT):
        tree = _parseOrNone(path)
        if tree is not None:
            testRefs |= _references(tree, isPackageInit=False)[0]

    entryModules, entryPaths = _entryPoints(root)
    findings: list[Candidate] = []
    exempted: list[tuple[Candidate, AllowShape]] = []

    deadModules: set[str] = set()
    for relative, tree in sorted(subject.items()):
        if relative.endswith("__init__.py"):
            continue
        name = _moduleName(relative)
        if name in importedByProduction:
            continue
        candidate = Candidate(SHAPE_NO_IMPORTER, relative, name, 1)
        if relative.endswith("__main__.py") or _hasMainBlock(tree):
            exempted.append((candidate, MAIN_BLOCK))
        elif name in entryModules or relative in entryPaths:
            exempted.append((candidate, SERVICE_ENTRY))
        else:
            findings.append(candidate)
            deadModules.add(relative)

    for relative, tree in sorted(subject.items()):
        if relative in deadModules:
            continue  # the module finding already covers its functions
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in productionRefs or node.name not in testRefs:
                continue
            candidate = Candidate(SHAPE_TESTS_ONLY, relative, node.name, node.lineno)
            if node.name in reexported:
                exempted.append((candidate, PACKAGE_REEXPORT))
            else:
                findings.append(candidate)

    return ScanResult(tuple(findings), tuple(exempted), tuple(sorted(subject)))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _plant(root: Path, files: dict[str, str]) -> Path:
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _findingKeys(result: ScanResult) -> set[str]:
    return {candidate.key for candidate in result.findings}


def _exemptions(result: ScanResult) -> dict[str, str]:
    return {candidate.key: shape.name for candidate, shape in result.exempted}


def _git(*args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, capture_output=True)


_TREE_ROOTS = {"src", "scripts", "tools", "tests", "deploy", "Makefile"}


@pytest.fixture(scope="module")
def currentScan() -> ScanResult:
    return scanTree(REPO_ROOT)


@pytest.fixture(scope="module")
def scanAt(tmp_path_factory: pytest.TempPathFactory) -> Callable[[str], ScanResult]:
    """Scan the REAL tree as it was at a revision, extracted with git archive."""
    cache: dict[str, ScanResult] = {}

    def scan(revision: str) -> ScanResult:
        if revision not in cache:
            if _git("rev-parse", "--verify", "--quiet", f"{revision}^{{commit}}").returncode:
                pytest.skip(
                    f"{revision} is not in this clone (shallow?) -- the historical "
                    f"validation cannot run here"
                )
            archive = _git("archive", revision)
            assert archive.returncode == 0, archive.stderr
            dest = tmp_path_factory.mktemp("tree")
            with tarfile.open(fileobj=io.BytesIO(archive.stdout)) as tar:
                members = [
                    m
                    for m in tar.getmembers()
                    if m.name.split("/")[0] in _TREE_ROOTS and (m.isfile() or m.isdir())
                ]
                tar.extractall(dest, members=members, filter="data")
            cache[revision] = scanTree(dest)
        return cache[revision]

    return scan


# ---------------------------------------------------------------------------
# Detector: both shapes, on planted trees
# ---------------------------------------------------------------------------

_DEAD_MODULE = {"src/pi/dead/mod.py": "def thing():\n    return 1\n"}


class TestTheDetectorSeesBothShapes:
    def test_moduleNothingImports_isReported(self, tmp_path: Path) -> None:
        """
        Given: a src/ module that no file anywhere imports
        When:  the tree is scanned
        Then:  it is reported as a no-production-importer finding
        """
        result = scanTree(_plant(tmp_path, _DEAD_MODULE))

        assert "src/pi/dead/mod.py" in _findingKeys(result)

    def test_moduleImportedOnlyByTests_isReported(self, tmp_path: Path) -> None:
        """
        Given: a src/ module imported only from tests/ -- the A-28 shape exactly
        When:  the tree is scanned
        Then:  it is reported; a test importer does not make a module live
        """
        result = scanTree(
            _plant(
                tmp_path,
                {**_DEAD_MODULE, "tests/test_mod.py": "from pi.dead.mod import thing\n"},
            )
        )

        assert "src/pi/dead/mod.py" in _findingKeys(result)

    @pytest.mark.parametrize(
        "importerPath,importerSource,label",
        [
            ("src/pi/app.py", "from src.pi.dead.mod import thing\n", "absolute src. prefix"),
            ("src/pi/app.py", "from pi.dead.mod import thing\n", "tier prefix (src/ on sys.path)"),
            ("src/pi/app.py", "import pi.dead.mod\n", "plain import"),
            ("src/pi/app.py", "from pi.dead import mod\n", "from package import module"),
            ("src/pi/dead/other.py", "from .mod import thing\n", "relative sibling"),
            ("src/pi/dead/inner/x.py", "from ..mod import thing\n", "relative parent"),
            (
                "src/pi/app.py",
                "import importlib\nm = importlib.import_module('pi.dead.mod')\n",
                "importlib by dotted string",
            ),
            ("scripts/tool.py", "from src.pi.dead.mod import thing\n", "a script under scripts/"),
            ("tools/pm/tool.py", "from src.pi.dead.mod import thing\n", "a PM tool under tools/"),
            ("validate_config.py", "from src.pi.dead.mod import thing\n", "a repo-root script"),
        ],
    )
    def test_moduleWithAProductionImporter_isNotReported(
        self, tmp_path: Path, importerPath: str, importerSource: str, label: str
    ) -> None:
        """
        Given: a src/ module imported by production code in one of the forms this
               tree actually uses
        When:  the tree is scanned
        Then:  it is not reported -- every miss here is a false positive
        """
        result = scanTree(_plant(tmp_path, {**_DEAD_MODULE, importerPath: importerSource}))

        assert "src/pi/dead/mod.py" not in _findingKeys(result), label

    def test_commentsAndDocstringsNamingAModule_areNotImporters(self, tmp_path: Path) -> None:
        """
        Given: a module whose only mentions are prose -- a comment and a :mod:
               docstring, exactly how analysis.py cites owned_tables
        When:  the tree is scanned
        Then:  it is reported; a citation is not a join
        """
        result = scanTree(
            _plant(
                tmp_path,
                {
                    "src/server/manifest.py": "OWNED = ('a',)\n",
                    "src/server/app.py": (
                        '"""See :mod:`src.server.manifest` for the manifest."""\n'
                        "# see src.server.manifest (the sole-writer registry)\n"
                        "x = 1\n"
                    ),
                },
            )
        )

        assert "src/server/manifest.py" in _findingKeys(result)

    _LIB = {
        "src/pi/lib.py": (
            "def usedByTestsOnly():\n    return 1\n\n\n"
            "def usedInProduction():\n    return 2\n"
        ),
        "tests/test_lib.py": "from pi.lib import usedByTestsOnly, usedInProduction\n",
    }

    @pytest.mark.parametrize(
        "caller,label",
        [
            ("from pi.lib import usedInProduction\nusedInProduction()\n", "direct call"),
            ("import pi.lib as lib\nlib.usedInProduction()\n", "attribute call"),
            ("import pi.lib as lib\ngetattr(lib, 'usedInProduction')()\n", "dispatch by name"),
            (
                "import pi.lib\nHANDLER = pi.lib.usedInProduction\n",
                "passed as a value, never called here",
            ),
        ],
    )
    def test_functionReferencedOnlyFromTests_isReported(
        self, tmp_path: Path, caller: str, label: str
    ) -> None:
        """
        Given: a module whose two functions are both tested, and only one of
               them is reached from production
        When:  the tree is scanned
        Then:  exactly the tests-only one is reported -- the A-16 shape
        """
        result = scanTree(_plant(tmp_path, {**self._LIB, "src/pi/app.py": caller}))

        keys = _findingKeys(result)
        assert "src/pi/lib.py::usedByTestsOnly" in keys, label
        assert "src/pi/lib.py::usedInProduction" not in keys, label

    def test_aModulesOwnAllList_isNotACaller(self, tmp_path: Path) -> None:
        """
        Given: a tests-only function its own module lists in __all__
        When:  the tree is scanned
        Then:  it is still reported -- publishing a name is not calling it
        """
        files = {
            **self._LIB,
            "src/pi/lib.py": self._LIB["src/pi/lib.py"] + "\n__all__ = ['usedByTestsOnly']\n",
            "src/pi/app.py": "from pi.lib import usedInProduction\nusedInProduction()\n",
        }
        result = scanTree(_plant(tmp_path, files))

        assert "src/pi/lib.py::usedByTestsOnly" in _findingKeys(result)

    def test_aFunctionReferencedNowhere_isOutsideTheDefinition(self, tmp_path: Path) -> None:
        """
        Given: a function nothing references, not even a test
        When:  the tree is scanned
        Then:  it is not reported -- the settled shape is 'called only from tests/'
        """
        files = {
            "src/pi/lib.py": "def orphan():\n    return 1\n\n\ndef live():\n    return 2\n",
            "src/pi/app.py": "from pi.lib import live\nlive()\n",
        }
        result = scanTree(_plant(tmp_path, files))

        assert "src/pi/lib.py::orphan" not in _findingKeys(result)

    def test_theFunctionsOfADeadModule_areCoveredByTheModuleFinding(self, tmp_path: Path) -> None:
        """
        Given: a dead module with a tests-only function (polling_tiers' shape)
        When:  the tree is scanned
        Then:  one finding, for the module -- not one per function
        """
        result = scanTree(
            _plant(
                tmp_path,
                {**_DEAD_MODULE, "tests/test_mod.py": "from pi.dead.mod import thing\nthing()\n"},
            )
        )

        assert _findingKeys(result) == {"src/pi/dead/mod.py"}


# ---------------------------------------------------------------------------
# The allow-list: every exemption is a named shape
# ---------------------------------------------------------------------------


class TestTheAllowListIsExplicit:
    def test_aMainBlock_isExemptedByName(self, tmp_path: Path) -> None:
        result = scanTree(
            _plant(
                tmp_path,
                {
                    "src/server/cli/tool.py": (
                        "def main():\n    pass\n\n\nif __name__ == '__main__':\n    main()\n"
                    )
                },
            )
        )

        assert _exemptions(result) == {"src/server/cli/tool.py": MAIN_BLOCK.name}
        assert not result.findings

    def test_aDunderMainModule_isExemptedByName(self, tmp_path: Path) -> None:
        result = scanTree(_plant(tmp_path, {"src/pi/power/watch/__main__.py": "print('x')\n"}))

        assert _exemptions(result) == {"src/pi/power/watch/__main__.py": MAIN_BLOCK.name}

    @pytest.mark.parametrize(
        "entryPath,entryText",
        [
            ("deploy/eclipse-x.service", "ExecStart=/venv/bin/python -m pi.x.daemon --poll-ms 5\n"),
            ("deploy/eclipse-x.service", "ExecStart=/venv/bin/python -m src.pi.x.daemon\n"),
            ("deploy/eclipse-x.service", "ExecStart=/venv/bin/python src/pi/x/daemon.py\n"),
            ("deploy/deploy-pi.sh", "ssh pi 'python -m pi.x.daemon --once'\n"),
            ("Makefile", "run-daemon:\n\tpython -m pi.x.daemon\n"),
            ("scripts/run_daemon.sh", "exec python src/pi/x/daemon.py \"$@\"\n"),
        ],
    )
    def test_aServiceEntryPoint_isExemptedByName(
        self, tmp_path: Path, entryPath: str, entryText: str
    ) -> None:
        result = scanTree(
            _plant(tmp_path, {"src/pi/x/daemon.py": "def run():\n    pass\n", entryPath: entryText})
        )

        assert _exemptions(result) == {"src/pi/x/daemon.py": SERVICE_ENTRY.name}
        assert not result.findings

    _PACKAGE = {
        "src/common/pkg/impl.py": "def publicFn():\n    return 1\n",
        "tests/test_pkg.py": "from common.pkg import publicFn\npublicFn()\n",
    }

    def test_aPackageReexportListedInAll_isExemptedByName(self, tmp_path: Path) -> None:
        files = {
            **self._PACKAGE,
            "src/common/pkg/__init__.py": "from .impl import publicFn\n\n__all__ = ['publicFn']\n",
        }
        result = scanTree(_plant(tmp_path, files))

        assert _exemptions(result) == {"src/common/pkg/impl.py::publicFn": PACKAGE_REEXPORT.name}
        assert not result.findings

    def test_aPackageImportNotListedInAll_isNotExempt(self, tmp_path: Path) -> None:
        files = {
            **self._PACKAGE,
            "src/common/pkg/__init__.py": "from .impl import publicFn\n\n__all__ = []\n",
        }
        result = scanTree(_plant(tmp_path, files))

        assert "src/common/pkg/impl.py::publicFn" in _findingKeys(result)

    def test_everyShapeHasANameAndAReason(self) -> None:
        assert ALLOW_SHAPES, "the allow-list is empty"
        for shape in ALLOW_SHAPES:
            assert shape.name.strip() and len(shape.reason) > 40, shape

    def test_everyPerSymbolEntryCarriesAReason(self) -> None:
        for ledger in (KNOWN_DEAD, INTENTIONAL_TEST_CONSUMERS):
            for key, reason in ledger.items():
                assert len(reason.strip()) >= 15, f"{key} has no stated reason"
        assert not set(KNOWN_DEAD) & set(INTENTIONAL_TEST_CONSUMERS)

    def test_everyExemptionOnTheCurrentTreeNamesAShape(self, currentScan: ScanResult) -> None:
        assert currentScan.exempted, "no exemptions at all -- the entry-point shapes are not firing"
        for candidate, shape in currentScan.exempted:
            assert shape in ALLOW_SHAPES, f"{candidate.key} exempted by an unnamed shape"


# ---------------------------------------------------------------------------
# The three measured instances, on the real trees
# ---------------------------------------------------------------------------

_A16_WIRED = (
    "src/pi/splash/system_status_emitter.py",
    "src/pi/splash/dtc_emitter.py",
    "src/pi/splash/battery_health_emitter.py",
)
_A16_NOT_WIRED = "src/pi/splash/ltft_trend_emitter.py"


class TestTheThreeMeasuredInstances:
    def test_a28_pollingTiers_isReportedOnTheCurrentTree(self, currentScan: ScanResult) -> None:
        """
        Given: the current tree, where polling_tiers.py still exists and two test
               modules import it
        When:  it is scanned
        Then:  polling_tiers.py is a no-production-importer finding
        """
        assert "src/pi/obdii/data/polling_tiers.py" in _findingKeys(currentScan)

    def test_a16_cardEmitters_areReportedBeforeTheirWiring(
        self, scanAt: Callable[[str], ScanResult]
    ) -> None:
        """
        Given: the real tree immediately before US-480-a wired the card emitters
        When:  it is scanned
        Then:  all four carousel emitters are reported
        """
        keys = _findingKeys(scanAt(f"{A16_WIRING_COMMIT}^"))

        missed = [path for path in (*_A16_WIRED, _A16_NOT_WIRED) if path not in keys]
        assert not missed, f"A-16 emitters the scan could not see: {missed}"

    def test_a16_theWiringCommitClearsExactlyWhatItWired(
        self, scanAt: Callable[[str], ScanResult]
    ) -> None:
        """
        Given: the tree AT US-480-a, which wired three emitters in-process
        When:  it is scanned
        Then:  those three are no longer reported and the LTFT emitter it did not
               wire still is -- the scan is seeing the join, not the file
        """
        keys = _findingKeys(scanAt(A16_WIRING_COMMIT))

        assert not [path for path in _A16_WIRED if path in keys]
        assert _A16_NOT_WIRED in keys

    def test_arch023_anUnsuppliedInjectedRunner_isInvisibleToThisScan(
        self, scanAt: Callable[[str], ScanResult]
    ) -> None:
        """
        Given: the real tree immediately before ARCH-023, when /dtc-clear
               answered 503 because nothing ever passed clearRunner
        When:  it is scanned
        Then:  the scan works (it has findings) and NOTHING it reports points at
               the defect -- the limit this guard states, pinned so no one
               cites it as three-of-three. The shape is US-725.
        """
        result = scanAt(f"{ARCH023_FIX_COMMIT}^")

        assert result.findings, "the scan found nothing at all -- this limit test would be vacuous"
        pointing = [
            c.key
            for c in result.findings
            if "states_http_server" in c.path or "clearRunner" in c.symbol or "dtc_clear" in c.path
        ]
        assert pointing == []


# ---------------------------------------------------------------------------
# The subject: the scan reads what it claims to read
# ---------------------------------------------------------------------------


class TestTheSubjectIsTheWholeSourceTree:
    def test_everyTrackedSrcModuleIsScanned(self, currentScan: ScanResult) -> None:
        """
        Given: git's own list of tracked src/ modules -- an oracle recorded
               independently of how the scan walks the tree (US-722 lesson)
        When:  it is compared with what the scan read
        Then:  nothing tracked was skipped
        """
        listed = _git("ls-files", "src").stdout.decode("utf-8").split()
        tracked = {p for p in listed if p.endswith(".py") and not p.endswith("__init__.py")}
        assert len(tracked) > 300, f"implausibly few tracked modules: {len(tracked)}"

        skipped = sorted(tracked - set(currentScan.subjectFiles))
        assert not skipped, f"tracked src/ modules the scan never read: {skipped[:10]}"


# ---------------------------------------------------------------------------
# The standing gate
# ---------------------------------------------------------------------------


class TestStandingGate:
    def test_noNewDeadImplementationInSrc(self, currentScan: ScanResult) -> None:
        """
        Given: the current tree
        When:  it is scanned
        Then:  every finding is already ledgered -- anything else is NEW dead code
        """
        ledgered = set(KNOWN_DEAD) | set(INTENTIONAL_TEST_CONSUMERS)
        new = [c for c in currentScan.findings if c.key not in ledgered]

        assert not new, (
            f"{len(new)} src/ implementation(s) that nothing in production reaches:\n  "
            + "\n  ".join(f"{c.path}:{c.line}  [{c.shape}]  {c.symbol}" for c in new)
            + "\nWire it, delete it, or -- only if it is dead ON PURPOSE -- ledger it in "
            "tests/lint/test_no_caller_no_importer.py with the reason."
        )

    def test_everyLedgerEntryIsStillAFinding(self, currentScan: ScanResult) -> None:
        """
        Given: KNOWN_DEAD and INTENTIONAL_TEST_CONSUMERS
        When:  compared with the current findings
        Then:  every entry is still found -- a stale entry is removed, not kept
        """
        stale = sorted((set(KNOWN_DEAD) | set(INTENTIONAL_TEST_CONSUMERS)) - _findingKeys(currentScan))

        assert not stale, (
            "ledger entries that are no longer dead (wired or deleted) -- remove them "
            f"so the ledger cannot hide the next one: {stale}"
        )

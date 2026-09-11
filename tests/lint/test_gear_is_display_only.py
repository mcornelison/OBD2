################################################################################
# File Name: test_gear_is_display_only.py
# Purpose/Description: US-693 standing lint -- gear is DISPLAY-ONLY, and the build
#     fails if it ever stops being.  The CIO's 2026-09-06 ruling that P = Park
#     (derived from the ABSENCE of RPM) overruled Spool's refusal and Atlas's
#     reservation on ONE premise: gear is never persisted, synced or analysed --
#     "we're not doing anything with that information other than displaying it."
#     The moment a derived P can enter a record, that P is a MANUFACTURED READING
#     and the ruling has to be re-opened.
#
#     Until this file existed, the re-open trigger was PROSE, in US-687-b's
#     conditionalOutcomes -- it asked a future developer to recall a story from
#     months earlier at the exact moment they add a column.  That is the same
#     species as the inert guard, the inert `pi.pollingTiers` (A-28) and the
#     `fleet.md` provenance claim: a rule nobody executes.  This converts it into
#     a check that fires on its own, at the person making the change.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-08
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-08    | Rex (US-693) | Initial -- three surfaces (applied schemas, the
#               |              | sync table registries, the poll list), each
#               |              | proven RED by an injected gear leak.
# 2026-09-10    | Rex (US-723) | Docstring only -- fourth NOT-COVER bullet, in
#               |              | Spool's wording: an analytic inferring Park
#               |              | from a GAP in realtime_data.
# ================================================================================
################################################################################

"""Lint: gear never reaches a schema, a sync registry or the poll list.

Three surfaces, in the order US-693's END STATE names them:

1. **The applied schemas.**  The Pi side is genuinely APPLIED -- a real
   ``ObdDatabase.initialize()`` run read back with ``PRAGMA table_info``, so a
   column added by an ``ensureXSchema`` helper is visible (the US-543 lesson: a
   DDL-constants load cannot see those).  The server side is what the SQLAlchemy
   models DECLARE.
2. **The sync table registries.**  ``acceptedTables()`` is the server's payload
   whitelist; ``syncedTables()`` is the Pi-side push registry
   (``PK_COLUMN`` | ``SNAPSHOT_SYNC``).  Both are read LIVE, so a registration
   made anywhere -- module-level or in a fixture -- is seen.
3. **The poll list.**  ``pi.realtimeData.parameters`` in ``config.json`` is the
   live one; ``pi.staticData.parameters`` and ``pi.pollingTiers.*.parameters``
   are covered too.  Unlike ``maxAgeSec`` (US-686, three homes), the poll list
   has exactly ONE home: ``loader.py`` lists ``pi.realtimeData.parameters`` as a
   REQUIRED field with no default, so there is no second copy to drift.

WHAT THIS GUARD DOES **NOT** COVER, stated here rather than discovered later
(US-693 conditionalOutcomes: "a partial guard that claims completeness is worse
than a narrow one that does not"):

* **The APPLIED SERVER schema.**  Reading MariaDB's ``information_schema``
  needs a live MariaDB, which this bench does not have.  A gear column that
  reached the deployed database without a model change -- a hand-run ``ALTER``
  -- is invisible here.  The realistic path (models + migration) IS covered,
  because the models are where that change lands.
* **A gear PID identified only by its HEX NUMBER.**  Detection is by parameter
  NAME.  ``{"name": "TAG", "pid": "0xA4"}`` would slip through.  Closing that
  needs a grounded PID-number -> meaning table, and this repo has none -- there
  is no ``0xA4`` anywhere in ``specs/``.  Inventing the mapping here would
  breach PM Rule 7, so the gap is named instead of guessed at.
* **The simulator's internal ``gear``.**  ``sensor_simulator.py`` carries a gear
  as an INPUT it uses to compute a synthetic SPEED.  It is not a reading, never
  reaches a schema, and is deliberately out of scope.
* This guard catches gear becoming PERSISTED, SYNCED or POLLED. It does not
  catch an analytic that infers vehicle state from the ABSENCE of rows -- e.g.
  treating a gap in realtime_data as 'parked'. That inference is the same
  defect the P ruling set aside, re-created in a record. Gaps in this corpus
  are known to be caused by dongle disconnection, reconnect failure and
  ungraceful shutdown, none of which are Park.

Run::

    pytest tests/lint/test_gear_is_display_only.py -v
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.audit_sync_contract_parity import (
    ColumnSpec,
    loadPiAppliedSchema,
    loadServerModelSchema,
    syncedTables,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_JSON = REPO_ROOT / "config.json"


# ================================================================================
# The predicate
# ================================================================================

# Deliberately BROAD, and the asymmetry is the reason.  This guard does not exist
# to keep a namespace tidy -- it exists to stop a DECISION being made by accident.
# A false positive costs one declared exemption below, which forces a human to
# read the ruling and say why their column is not a gear.  A false negative costs
# the ruling itself, silently.  Those are not the same price, so the predicate
# errs loud.
#
# `prndl` is in the vocabulary because it is the industry name for exactly the
# fact the tile displays, and a `%gear%` scan is blind to it -- the same shape as
# US-687-b's `park`, the one token the general snake_case sweep could not see.
GEAR_VOCABULARY = re.compile(r"(?i)gear|prndl")


# Identifiers that LOOK like a gear leak and are not.  EMPTY TODAY -- the tree is
# clean, verified by :meth:`TestStandingGate`.  It exists as the pressure valve:
# without one, the first false positive gets the guard deleted rather than
# annotated.  Every entry needs a reason, and a STALE entry (one whose identifier
# no longer appears on any scanned surface) is itself a violation -- an exemption
# nobody removed suppresses a real finding for a name that has since been reused.
DECLARED_EXEMPTIONS: dict[str, str] = {}


def isGearIdentifier(name: str) -> bool:
    """Return True if ``name`` is a gear identifier this guard refuses.

    Args:
        name: A table name, column name or poll-list parameter name.

    Returns:
        True if the name carries the gear vocabulary and is not declared exempt.
    """
    if name.lower() in DECLARED_EXEMPTIONS:
        return False
    return bool(GEAR_VOCABULARY.search(name))


# ================================================================================
# The finding, and the message it carries
# ================================================================================


@dataclass(frozen=True)
class GearLeak:
    """One place gear escaped display-only."""

    surface: str
    location: str
    identifier: str

    def render(self) -> str:
        return f"[{self.surface}] {self.location}: {self.identifier!r}"


# US-693 NEGATIVE CASE, stated: "the failure message must NAME the ruling it
# protects and point at US-687, not merely say 'gear column found'.  A developer
# hitting this needs to know there is a decision to re-open, not just a rule to
# satisfy."
RULING_NOTICE = """
GEAR IS DISPLAY-ONLY -- and this change makes it recordable.

The CIO ruled on 2026-09-06 that the gear tile may read P for Park, derived
from the ABSENCE of RPM, over Spool's refusal and Atlas's reservation:

    "I'm not going to endanger anything and we're not doing anything with
     that information other than displaying it."

That ruling rests ENTIRELY on gear never being persisted, synced or analysed
(PM verified it three ways, 2026-09-06).  A P that can enter a record is a
MANUFACTURED READING -- absence of data written down as a measurement -- and
the manufacture-a-reading rule engages the moment it can.

So this is NOT a rule to satisfy.  It is A DECISION TO RE-OPEN.  Read US-687-a
and US-687-b before you go further; if gear really should be recorded, that
ruling has to be re-opened by the CIO, not routed around by adding a name to
DECLARED_EXEMPTIONS in this file.
"""


def renderFailure(leaks: list[GearLeak]) -> str:
    """Render the full operator-facing failure text for ``leaks``."""
    found = "\n".join(f"  - {leak.render()}" for leak in leaks)
    return f"{RULING_NOTICE}\nFound {len(leaks)} gear leak(s):\n{found}\n"


# ================================================================================
# Surface scanners
# ================================================================================


def scanSchema(schema: dict[str, dict[str, ColumnSpec]], tier: str) -> list[GearLeak]:
    """Scan an applied/declared schema for gear TABLES and gear COLUMNS."""
    leaks: list[GearLeak] = []
    for tableName, columns in sorted(schema.items()):
        if isGearIdentifier(tableName):
            leaks.append(GearLeak(f"{tier} schema", "table", tableName))
        for columnName in sorted(columns):
            if isGearIdentifier(columnName):
                leaks.append(GearLeak(f"{tier} schema", tableName, columnName))
    return leaks


def scanSyncRegistry(tables: frozenset[str] | dict[str, Any], surface: str) -> list[GearLeak]:
    """Scan a sync table registry for a gear table."""
    return [
        GearLeak(surface, "registered for sync", tableName)
        for tableName in sorted(tables)
        if isGearIdentifier(tableName)
    ]


def pollListEntries(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Return every ``(location, parameterName)`` on any poll list in ``config``.

    Handles both entry shapes the loader accepts -- a bare string and a
    ``{"name": ...}`` dict -- because a guard that read only the dict form would
    go quietly blind the day somebody shortens an entry.
    """
    pi = config.get("pi", {})
    blocks: list[tuple[str, Any]] = [
        ("pi.realtimeData.parameters", pi.get("realtimeData", {}).get("parameters", [])),
        ("pi.staticData.parameters", pi.get("staticData", {}).get("parameters", [])),
    ]
    # pi.pollingTiers is INERT today (zero importers in src/, A-28) but it is
    # where a tier-shaped PID would be written, and US-686's follow-up TD-us686
    # may yet wire or delete it.  Discovered, never hand-listed, so a tier5 added
    # later is covered without editing this guard.
    for tierName, tier in sorted(pi.get("pollingTiers", {}).items()):
        if isinstance(tier, dict):
            blocks.append(
                (f"pi.pollingTiers.{tierName}.parameters", tier.get("parameters", [])),
            )

    entries: list[tuple[str, str]] = []
    for location, parameters in blocks:
        if not isinstance(parameters, list):
            continue
        for parameter in parameters:
            if isinstance(parameter, dict):
                name = parameter.get("name", "")
            else:
                name = parameter
            if isinstance(name, str) and name:
                entries.append((location, name))
    return entries


def scanPollList(config: dict[str, Any]) -> list[GearLeak]:
    """Scan every poll list in ``config`` for a gear PID."""
    return [
        GearLeak("poll list", location, name)
        for location, name in pollListEntries(config)
        if isGearIdentifier(name)
    ]


def codeTokens(source: str) -> set[str]:
    """Return every identifier and string LITERAL in executable code in ``source``.

    An AST walk, not a substring scan, and the distinction is load-bearing here.
    A gear table reaches a sync module as a string literal (``"gear_log"``) or an
    attribute, so literals must be read -- but a module that DOCUMENTS this rule
    in a comment (``# gear is display-only, US-693``) is correct code, and a
    naive ``'gear' in source`` would fail it.  That is the US-543 lesson in its
    false-positive direction: the guard must not punish the file for explaining
    the guard.  Docstrings are excluded for the same reason.
    """
    import ast

    tokens: set[str] = set()
    tree = ast.parse(source)
    docstrings = {
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            tokens.add(node.id)
        elif isinstance(node, ast.Attribute):
            tokens.add(node.attr)
        elif isinstance(node, ast.alias):
            tokens.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                tokens.add(node.asname)
        elif isinstance(node, ast.arg):
            tokens.add(node.arg)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value not in docstrings:
                tokens.add(node.value)
    return tokens


def scanStaleExemptions(seenIdentifiers: set[str]) -> list[GearLeak]:
    """Report any declared exemption whose identifier no longer exists.

    A stale exemption is worse than no exemption: it silently suppresses a real
    finding for a name that has since been reused (the
    ``checkCrossTierResolverDeclaration`` lesson from US-543).
    """
    lowered = {identifier.lower() for identifier in seenIdentifiers}
    return [
        GearLeak("declared exemptions", "stale -- identifier no longer present", name)
        for name in sorted(DECLARED_EXEMPTIONS)
        if name.lower() not in lowered
    ]


def checkGearIsDisplayOnly(
    piSchema: dict[str, dict[str, ColumnSpec]],
    serverSchema: dict[str, dict[str, ColumnSpec]],
    accepted: frozenset[str],
    synced: dict[str, str],
    config: dict[str, Any],
) -> list[GearLeak]:
    """The aggregate gate: every surface, one verdict."""
    leaks = scanSchema(piSchema, "Pi applied")
    leaks += scanSchema(serverSchema, "server model")
    leaks += scanSyncRegistry(accepted, "server acceptedTables()")
    leaks += scanSyncRegistry(synced, "Pi syncedTables()")
    leaks += scanPollList(config)

    seen: set[str] = set()
    for schema in (piSchema, serverSchema):
        for tableName, columns in schema.items():
            seen.add(tableName)
            seen.update(columns)
    seen.update(accepted)
    seen.update(synced)
    seen.update(name for _location, name in pollListEntries(config))
    leaks += scanStaleExemptions(seen)
    return leaks


# ================================================================================
# Fixtures -- the real repo, loaded once (initialize() is a real DB build)
# ================================================================================


@pytest.fixture(scope="module")
def piSchema() -> dict[str, dict[str, ColumnSpec]]:
    """The APPLIED Pi schema: a real ObdDatabase.initialize() run."""
    return loadPiAppliedSchema()


@pytest.fixture(scope="module")
def serverSchema() -> dict[str, dict[str, ColumnSpec]]:
    """The server schema as the SQLAlchemy models declare it."""
    return loadServerModelSchema()


@pytest.fixture(scope="module")
def shippedConfig() -> dict[str, Any]:
    """The config.json that actually ships."""
    return json.loads(CONFIG_JSON.read_text(encoding="utf-8"))


def _acceptedTables() -> frozenset[str]:
    """Read the server payload whitelist LIVE, never a snapshot."""
    from src.server.api.sync import acceptedTables

    return acceptedTables()


def _spec(name: str) -> ColumnSpec:
    return ColumnSpec(name=name, kind="text", notNull=False, hasDefault=False)


def _withColumn(
    schema: dict[str, dict[str, ColumnSpec]], table: str, column: str,
) -> dict[str, dict[str, ColumnSpec]]:
    """Copy ``schema`` with one extra column -- the injected-leak helper."""
    drifted = {name: dict(columns) for name, columns in schema.items()}
    drifted.setdefault(table, {})[column] = _spec(column)
    return drifted


# ================================================================================
# Non-vacuity controls -- every absence assertion below rests on these
# ================================================================================


class TestTheScannersCanActuallyFindSomething:
    """US-595: an absence assertion is worthless without proof of reachability."""

    def test_isGearIdentifier_matchesTheVocabulary(self) -> None:
        assert isGearIdentifier("gear")
        assert isGearIdentifier("current_gear")
        assert isGearIdentifier("GEAR")
        assert isGearIdentifier("gearState")

    def test_isGearIdentifier_matchesPrndl(self) -> None:
        # The token a %gear% scan is blind to, and the industry name for the very
        # fact the tile shows.  US-687-b's `park` was the same shape.
        assert isGearIdentifier("prndl")
        assert isGearIdentifier("PRNDL_POSITION")

    def test_isGearIdentifier_doesNotMatchOrdinaryCaptureNames(self) -> None:
        # The other half of the control: a predicate that returned True for
        # everything would make every injection test below pass for free.
        for name in ("rpm", "speed", "coolant_temp", "vcell", "timestamp"):
            assert not isGearIdentifier(name)

    def test_piAppliedSchema_isPopulated(self, piSchema: dict) -> None:
        # A degenerate/empty load would make the standing gate pass vacuously.
        assert piSchema["realtime_data"]["parameter_name"].kind == "text"

    def test_serverModelSchema_isPopulated(self, serverSchema: dict) -> None:
        assert "realtime_data" in serverSchema
        assert "source_device" in serverSchema["realtime_data"]

    def test_acceptedTables_isPopulated(self) -> None:
        assert "realtime_data" in _acceptedTables()

    def test_syncedTables_isPopulated(self) -> None:
        assert "realtime_data" in syncedTables()

    def test_pollListEntries_findsTheRealPollList(self, shippedConfig: dict) -> None:
        names = {name for _location, name in pollListEntries(shippedConfig)}
        # The two the whole gear feature is built on.  If these are not found the
        # extractor is broken and "no gear PID" means nothing.
        assert {"RPM", "SPEED"} <= names

    def test_pollListEntries_readsEveryBlockNotJustTheLiveOne(
        self, shippedConfig: dict,
    ) -> None:
        locations = {location for location, _name in pollListEntries(shippedConfig)}
        assert "pi.realtimeData.parameters" in locations
        assert "pi.staticData.parameters" in locations
        assert any(location.startswith("pi.pollingTiers.") for location in locations)

    def test_codeTokens_findsAStringLiteralTableName(self) -> None:
        # Positive control.  A gear table reaches a sync module AS A STRING, so a
        # scanner that read identifiers only would report a clean sync.py over
        # `ACCEPTED_TABLES = {"gear_log"}`.
        assert "gear_log" in codeTokens('ACCEPTED_TABLES = {"gear_log"}\n')

    def test_codeTokens_findsAnAttributeAndAnImport(self) -> None:
        assert "gearState" in codeTokens("x = payload.gearState\n")
        assert "gear_derivation" in codeTokens("import src.pi.obdii.gear_derivation\n")

    def test_codeTokens_ignoresCommentsAndDocstrings(self) -> None:
        # Negative control, and the reason this is an AST walk: a sync module
        # that EXPLAINS this rule in a comment is correct code.  A substring scan
        # would fail the very file that documents the guard.
        assert not codeTokens(
            '"""This module never syncs gear -- US-693."""\n'
            "# gear is display-only; see US-687\n"
            "x = 1\n",
        ) & {"gear", "gear is display-only; see US-687"}

    def test_pollListEntries_readsBareStringEntries(self) -> None:
        # pi.staticData.parameters ships as bare strings; the loader also accepts
        # them for realtimeData.  A dict-only extractor would go blind on a
        # shortened entry while still reporting "no gear PID found".
        config = {"pi": {"realtimeData": {"parameters": ["GEAR", {"name": "RPM"}]}}}
        assert set(pollListEntries(config)) == {
            ("pi.realtimeData.parameters", "GEAR"),
            ("pi.realtimeData.parameters", "RPM"),
        }


# ================================================================================
# The guard fails on purpose -- US-693's "a guard nobody has seen fail"
# ================================================================================


class TestTheGuardFailsOnPurpose:
    """Every surface is proven RED by an injected leak, against the REAL loads.

    US-693: "Add a gear column to a fixture schema and watch it go red.  A guard
    nobody has seen fail is a guard nobody has tested -- five inert guards have
    been catalogued this fortnight and every one was syntactically present."
    """

    def test_gearColumnInThePiAppliedSchema_isRed(self, piSchema: dict) -> None:
        # The realistic shape: a capture story adds `current_gear` to the table
        # the Pi already writes every poll cycle.
        leaks = scanSchema(_withColumn(piSchema, "realtime_data", "current_gear"), "Pi applied")
        assert [leak.identifier for leak in leaks] == ["current_gear"]
        assert leaks[0].location == "realtime_data"

    def test_gearColumnInTheServerModelSchema_isRed(self, serverSchema: dict) -> None:
        leaks = scanSchema(_withColumn(serverSchema, "drive_summary", "final_gear"), "server model")
        assert [leak.identifier for leak in leaks] == ["final_gear"]

    def test_gearTableInASchema_isRed(self, piSchema: dict) -> None:
        leaks = scanSchema(_withColumn(piSchema, "gear_log", "id"), "Pi applied")
        assert any(leak.location == "table" and leak.identifier == "gear_log" for leak in leaks)

    def test_gearTableRegisteredForSnapshotSync_reachesAcceptedTablesAndIsRed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Not a fixture stand-in: this registers a gear table in the REAL
        # registry exactly as a story would, and acceptedTables() -- which is
        # computed live for precisely this reason -- returns it.
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec

        monkeypatch.setitem(
            SNAPSHOT_SYNC,
            "gear_log",
            SnapshotSyncSpec(naturalKeyCols=("event_id",), cursorCol="recorded_at"),
        )
        assert "gear_log" in _acceptedTables()
        leaks = scanSyncRegistry(_acceptedTables(), "server acceptedTables()")
        assert [leak.identifier for leak in leaks] == ["gear_log"]

    def test_gearTableRegisteredForDeltaSync_reachesSyncedTablesAndIsRed(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # The other direction: the Pi-side push registry.  A guard that watched
        # only the server whitelist would miss a Pi that pushes a table the
        # server happens to accept.
        from src.pi.data.sync_log import PK_COLUMN

        monkeypatch.setitem(PK_COLUMN, "prndl_log", "id")
        leaks = scanSyncRegistry(syncedTables(), "Pi syncedTables()")
        assert [leak.identifier for leak in leaks] == ["prndl_log"]

    def test_gearPidInTheLivePollList_isRed(self, shippedConfig: dict) -> None:
        config = json.loads(json.dumps(shippedConfig))
        config["pi"]["realtimeData"]["parameters"].append(
            {"name": "GEAR", "logData": True, "displayOnDashboard": True},
        )
        leaks = scanPollList(config)
        assert [leak.identifier for leak in leaks] == ["GEAR"]
        assert leaks[0].location == "pi.realtimeData.parameters"

    def test_gearPidInAPollingTier_isRed(self, shippedConfig: dict) -> None:
        config = json.loads(json.dumps(shippedConfig))
        config["pi"]["pollingTiers"]["tier2"]["parameters"].append(
            {"name": "TRANSMISSION_GEAR", "pid": "0xA4"},
        )
        leaks = scanPollList(config)
        assert [leak.identifier for leak in leaks] == ["TRANSMISSION_GEAR"]
        assert leaks[0].location == "pi.pollingTiers.tier2.parameters"

    def test_gearPidInTheStaticList_isRed(self, shippedConfig: dict) -> None:
        config = json.loads(json.dumps(shippedConfig))
        config["pi"]["staticData"]["parameters"].append("GEAR_RATIO_TABLE")
        assert [leak.identifier for leak in scanPollList(config)] == ["GEAR_RATIO_TABLE"]

class TestEverySurfaceIsWiredIntoTheAggregateGate:
    """Each surface alone must fail the WHOLE gate -- not merely its own scanner.

    Written after a mutation survived: deleting the ``syncedTables()`` line from
    :func:`checkGearIsDisplayOnly` left every test above GREEN, because they call
    the scanners directly.  A scanner that works and a gate that consults it are
    DIFFERENT guarantees (the US-636 lesson), and only these tests hold the
    second one.  Without them a future tidy-up could quietly unwire a surface and
    leave a guard that is syntactically present and blind -- the exact shape
    US-693 was written to stop.
    """

    def test_piSchemaLeak_failsTheGate(
        self, piSchema: dict, serverSchema: dict, shippedConfig: dict,
    ) -> None:
        leaks = checkGearIsDisplayOnly(
            _withColumn(piSchema, "realtime_data", "gear"),
            serverSchema, _acceptedTables(), syncedTables(), shippedConfig,
        )
        assert [leak.identifier for leak in leaks] == ["gear"]

    def test_serverSchemaLeak_failsTheGate(
        self, piSchema: dict, serverSchema: dict, shippedConfig: dict,
    ) -> None:
        leaks = checkGearIsDisplayOnly(
            piSchema,
            _withColumn(serverSchema, "drive_summary", "final_gear"),
            _acceptedTables(), syncedTables(), shippedConfig,
        )
        assert [leak.identifier for leak in leaks] == ["final_gear"]

    def test_acceptedTablesLeak_failsTheGate(
        self, monkeypatch: pytest.MonkeyPatch,
        piSchema: dict, serverSchema: dict, shippedConfig: dict,
    ) -> None:
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC, SnapshotSyncSpec

        monkeypatch.setitem(
            SNAPSHOT_SYNC,
            "gear_log",
            SnapshotSyncSpec(naturalKeyCols=("event_id",), cursorCol="recorded_at"),
        )
        leaks = checkGearIsDisplayOnly(
            piSchema, serverSchema, _acceptedTables(), syncedTables(), shippedConfig,
        )
        assert any(leak.surface == "server acceptedTables()" for leak in leaks)

    def test_syncedTablesLeak_failsTheGate(
        self, monkeypatch: pytest.MonkeyPatch,
        piSchema: dict, serverSchema: dict, shippedConfig: dict,
    ) -> None:
        # PK_COLUMN deliberately, NOT the snapshot registry: a snapshot
        # registration reaches BOTH sync surfaces, so it would still fail the
        # gate through acceptedTables() with this surface unwired.  The delta
        # registry is the one that reaches syncedTables() ALONE, so it is the
        # only injection that can hold this line in place.
        from src.pi.data.sync_log import PK_COLUMN

        monkeypatch.setitem(PK_COLUMN, "prndl_log", "id")
        leaks = checkGearIsDisplayOnly(
            piSchema, serverSchema, _acceptedTables(), syncedTables(), shippedConfig,
        )
        assert [leak.surface for leak in leaks] == ["Pi syncedTables()"]

    def test_pollListLeak_failsTheGate(
        self, piSchema: dict, serverSchema: dict, shippedConfig: dict,
    ) -> None:
        config = json.loads(json.dumps(shippedConfig))
        config["pi"]["realtimeData"]["parameters"].append({"name": "GEAR"})
        leaks = checkGearIsDisplayOnly(
            piSchema, serverSchema, _acceptedTables(), syncedTables(), config,
        )
        assert [leak.surface for leak in leaks] == ["poll list"]

    def test_staleExemption_failsTheGate(
        self, monkeypatch: pytest.MonkeyPatch,
        piSchema: dict, serverSchema: dict, shippedConfig: dict,
    ) -> None:
        monkeypatch.setitem(DECLARED_EXEMPTIONS, "retired_gear_column", "long gone")
        leaks = checkGearIsDisplayOnly(
            piSchema, serverSchema, _acceptedTables(), syncedTables(), shippedConfig,
        )
        assert [leak.identifier for leak in leaks] == ["retired_gear_column"]


# ================================================================================
# The failure message carries the DECISION, not just the rule
# ================================================================================


class TestTheMessageNamesTheRuling:
    """US-693 negative case: 'gear column found' is not an adequate message."""

    def test_failureText_namesTheCioRulingAndItsDate(self) -> None:
        text = renderFailure([GearLeak("Pi applied schema", "realtime_data", "gear")])
        assert "2026-09-06" in text
        assert "displaying it" in text

    def test_failureText_pointsAtUs687(self) -> None:
        text = renderFailure([GearLeak("Pi applied schema", "realtime_data", "gear")])
        assert "US-687" in text

    def test_failureText_saysThereIsADecisionToReOpen(self) -> None:
        # The distinction the story insists on: a developer must learn there is a
        # RULING to revisit, not merely a lint to appease.
        text = renderFailure([GearLeak("Pi applied schema", "realtime_data", "gear")])
        assert "RE-OPEN" in text

    def test_failureText_namesWhatItFoundAndWhere(self) -> None:
        text = renderFailure([GearLeak("poll list", "pi.realtimeData.parameters", "GEAR")])
        assert "pi.realtimeData.parameters" in text
        assert "'GEAR'" in text

    def test_failureText_doesNotOfferTheExemptionAsAnEscapeHatch(self) -> None:
        # The exemption list is the one way to make this test green without
        # thinking, so the message says explicitly that it is not the answer.
        text = renderFailure([GearLeak("Pi applied schema", "realtime_data", "gear")])
        assert "not routed around" in text.replace("\n", " ")


# ================================================================================
# The exemption valve is self-policing
# ================================================================================


class TestDeclaredExemptions:
    """An exemption must be deliberate, and must not outlive what it exempted."""

    def test_noExemptionsAreDeclaredToday(self) -> None:
        # The tree is clean, so the valve is unused.  Pinned so that adding the
        # first entry is a visible, deliberate act in a diff -- not a quiet way
        # to make a red build green.
        assert DECLARED_EXEMPTIONS == {}

    def test_aDeclaredExemptionSuppressesThatIdentifier(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setitem(DECLARED_EXEMPTIONS, "gear_math_factor", "SPEED calibration")
        assert not isGearIdentifier("gear_math_factor")
        # ...and only that one: an exemption is not a blanket amnesty.
        assert isGearIdentifier("current_gear")

    def test_aStaleExemption_isItselfRed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(DECLARED_EXEMPTIONS, "retired_gear_column", "long gone")
        leaks = scanStaleExemptions({"rpm", "speed"})
        assert [leak.identifier for leak in leaks] == ["retired_gear_column"]
        assert "stale" in leaks[0].location

    def test_aLiveExemption_isNotReportedStale(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setitem(DECLARED_EXEMPTIONS, "gear_math_factor", "SPEED calibration")
        assert scanStaleExemptions({"gear_math_factor", "rpm"}) == []


# ================================================================================
# The standing gate -- US-693 validationCriterion 3
# ================================================================================


class TestStandingGate:
    """The property holds today, and the guard is watching the real thing."""

    def test_theTreeAsItStands_isGreen(
        self, piSchema: dict, serverSchema: dict, shippedConfig: dict,
    ) -> None:
        leaks = checkGearIsDisplayOnly(
            piSchema, serverSchema, _acceptedTables(), syncedTables(), shippedConfig,
        )
        if leaks:
            pytest.fail(renderFailure(leaks))

    def test_theDeriverConfigIsNotAViolation(self, shippedConfig: dict) -> None:
        # THE FIXTURE GUARD.  `pi.gear` -- enabled, bands, maxAgeSec,
        # parkDwellSec -- is the DERIVER's own calibration and must stay legal:
        # this guard watches PERSISTENCE surfaces, not the fact that a gear is
        # computed at all.  Without this pin, the green verdict above would be
        # unattributable -- it would also be green on a tree where somebody had
        # deleted the whole gear feature.
        assert "gear" in shippedConfig["pi"]
        assert scanPollList(shippedConfig) == []

    def test_theDisplayOnlyChainStillExists(self) -> None:
        # Same reasoning one layer out: derive -> emit -> tmpfs.  A tree with no
        # producer would pass every absence assertion in this file for the wrong
        # reason, and this guard would quietly become decorative.
        for module in ("gear_derivation.py", "gear_state_emitter.py"):
            assert (REPO_ROOT / "src" / "pi" / "obdii" / module).is_file()

    def test_gearNeverAppearsInTheServerSyncEndpoint(self) -> None:
        # Atlas's 2026-09-06 property, executed rather than recorded: zero
        # occurrences of 'gear' in the server's sync ingest.
        source = (REPO_ROOT / "src" / "server" / "api" / "sync.py").read_text(
            encoding="utf-8",
        )
        found = sorted(name for name in codeTokens(source) if isGearIdentifier(name))
        assert not found, renderFailure(
            [GearLeak("server sync ingest", "src/server/api/sync.py", name) for name in found],
        )

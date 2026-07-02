################################################################################
# File Name: test_snapshot_registry.py
# Purpose/Description: Unit tests for the shared cross-tier SNAPSHOT_SYNC registry
#                      (US-416 / F-101). Covers the spec dataclass validation, the
#                      lookup/whitelist helpers, and the A-4 single-definition
#                      guarantee -- both tiers reference the SAME registry object.
# Author: Rex (Ralph agent)
# Creation Date: 2026-07-01
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-01    | Rex (US-416) | Initial -- shared snapshot-sync contract tests.
# ================================================================================
################################################################################

"""Tests for :mod:`src.common.sync.snapshot_registry` (US-416)."""

from __future__ import annotations

import pytest

from src.common.sync.snapshot_registry import (
    SNAPSHOT_SYNC,
    SnapshotSyncSpec,
    getSnapshotSpec,
    isSnapshotSyncTable,
    snapshotSyncTables,
)

_TEST_TABLE = "test_snap_registry"


@pytest.fixture
def registered() -> object:
    """Register a throwaway snapshot table for the duration of one test."""
    SNAPSHOT_SYNC[_TEST_TABLE] = SnapshotSyncSpec(
        naturalKeyCols=("boot_id",), cursorCol="recorded_at",
    )
    try:
        yield
    finally:
        SNAPSHOT_SYNC.pop(_TEST_TABLE, None)


class TestSnapshotSyncSpec:
    """The spec dataclass validates its fields."""

    def test_holdsNaturalKeyColsAndCursor(self) -> None:
        spec = SnapshotSyncSpec(naturalKeyCols=("boot_id",), cursorCol="recorded_at")
        assert spec.naturalKeyCols == ("boot_id",)
        assert spec.cursorCol == "recorded_at"

    def test_supportsCompositeNaturalKey(self) -> None:
        spec = SnapshotSyncSpec(
            naturalKeyCols=("source_device", "boot_id"), cursorCol="recorded_at",
        )
        assert spec.naturalKeyCols == ("source_device", "boot_id")

    def test_emptyNaturalKeyColsRaises(self) -> None:
        with pytest.raises(ValueError, match="naturalKeyCols must not be empty"):
            SnapshotSyncSpec(naturalKeyCols=(), cursorCol="recorded_at")

    def test_emptyCursorColRaises(self) -> None:
        with pytest.raises(ValueError, match="cursorCol must not be empty"):
            SnapshotSyncSpec(naturalKeyCols=("boot_id",), cursorCol="")

    def test_isFrozen(self) -> None:
        spec = SnapshotSyncSpec(naturalKeyCols=("boot_id",), cursorCol="recorded_at")
        with pytest.raises((AttributeError, TypeError)):
            spec.cursorCol = "other"  # type: ignore[misc]


class TestRegistryHelpers:
    """Lookup + whitelist helpers reflect the live registry."""

    def test_registryStartsWithoutTestTable(self) -> None:
        assert _TEST_TABLE not in SNAPSHOT_SYNC

    def test_unregisteredTableIsNotSnapshot(self) -> None:
        assert isSnapshotSyncTable("definitely_not_registered") is False

    def test_getSnapshotSpecRaisesForUnregistered(self) -> None:
        with pytest.raises(KeyError, match="not registered for snapshot sync"):
            getSnapshotSpec("definitely_not_registered")

    def test_registrationIsVisible(self, registered: object) -> None:
        assert isSnapshotSyncTable(_TEST_TABLE) is True
        assert _TEST_TABLE in snapshotSyncTables()
        spec = getSnapshotSpec(_TEST_TABLE)
        assert spec.naturalKeyCols == ("boot_id",)

    def test_snapshotSyncTablesIsLive(self, registered: object) -> None:
        """snapshotSyncTables() reflects the current dict, not an import snapshot."""
        assert _TEST_TABLE in snapshotSyncTables()
        SNAPSHOT_SYNC.pop(_TEST_TABLE)
        assert _TEST_TABLE not in snapshotSyncTables()
        # restore for the fixture teardown's pop (no-op then)
        SNAPSHOT_SYNC[_TEST_TABLE] = SnapshotSyncSpec(("boot_id",), "recorded_at")


class TestA4SingleDefinition:
    """A-4: both tiers reference the SAME registry object (define-once)."""

    def test_piAndServerSeeTheSameRegistration(self, registered: object) -> None:
        # Import the two consumers lazily so this test documents the contract:
        # a single registration is visible through BOTH the Pi reader module and
        # the server upsert module -- proving neither keeps its own copy.
        from src.pi.data import sync_log as pi_sync_log
        from src.server.api import sync as server_sync

        assert pi_sync_log.isSnapshotSyncTable(_TEST_TABLE) is True
        assert server_sync.isSnapshotSyncTable(_TEST_TABLE) is True
        # And the naturalKeyCols each tier would use are the SAME object.
        assert (
            pi_sync_log.getSnapshotSpec(_TEST_TABLE)
            is server_sync.getSnapshotSpec(_TEST_TABLE)
        )

    def test_piSyncLogReExportsSharedRegistry(self) -> None:
        from src.common.sync.snapshot_registry import SNAPSHOT_SYNC as shared
        from src.pi.data.sync_log import SNAPSHOT_SYNC as piCopy

        assert piCopy is shared

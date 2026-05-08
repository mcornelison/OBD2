################################################################################
# File Name: release_reader.py
# Purpose/Description: Server-side release record reader for B-047 US-B.
#                      Reads the current release record from the .deploy-version
#                      file and the optional .deploy-version-history JSONL trail.
#                      Backs the GET /api/v1/release/current and
#                      GET /api/v1/release/history endpoints.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation (Sprint 20 US-246)
# 2026-05-08    | Rex          | US-297: pruneHistory + appendRelease for B-047 D4
#               |              |   retention enforcement (keep last 10; configurable)
# ================================================================================
################################################################################

"""Release-record file reader + writer (B-047 US-B + D4).

Backs the ``/api/v1/release/current`` and ``/api/v1/release/history`` endpoints.
Source-of-truth files are written by ``deploy/deploy-server.sh`` step 5.5 (US-241):

    ${PROJECT}/.deploy-version            -- current release record (single JSON)
    ${PROJECT}/.deploy-version-history    -- JSONL append trail (one record / line)

The ``current`` file is written by ``scripts/version_helpers.composeReleaseRecord``
on every deploy. The ``history`` file is OPTIONAL today -- a future deploy-script
enhancement (or ``appendRelease`` invocation) can populate it. When absent,
``readHistory`` returns an empty list.

US-297 / B-047 D4 retention: ``pruneHistory`` + ``appendRelease`` enforce a
"last N releases" cap on the JSONL trail (default 10, configurable via
``RELEASE_HISTORY_MAX``). After each append the oldest records beyond the cap
are removed and the prune count is INFO-logged.

Validation reuses ``scripts.version_helpers.validateRelease`` so the schema
contract (``{version, releasedAt, gitHash, description}``) lives in exactly one
place.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from scripts.version_helpers import readDeployVersion, validateRelease

logger = logging.getLogger(__name__)

DEFAULT_HISTORY_MAX_ENTRIES = 10
DEFAULT_CURRENT_PATH = ".deploy-version"
DEFAULT_HISTORY_PATH = ".deploy-version-history"


@dataclass(slots=True)
class ReleaseReader:
    """Reads release records from the deploy-version files.

    Constructed with explicit paths so tests inject tmp files and production
    callers inject Settings-derived paths. Defaults match the layout written by
    ``deploy/deploy-server.sh`` (relative paths resolve against the server's
    CWD, which is the project root in production).

    Attributes:
        currentPath: Path to the single-record current-release file.
        historyPath: Path to the JSONL append trail (may be absent).
        historyMaxEntries: Default ``maxEntries`` when ``readHistory`` is
            called without an explicit count. Capped at 1000 to keep the
            response payload bounded.
    """

    currentPath: Path
    historyPath: Path
    historyMaxEntries: int = DEFAULT_HISTORY_MAX_ENTRIES

    @staticmethod
    def fromSettings(settings: object) -> ReleaseReader:
        """Build a reader from a Settings-like object with the expected fields.

        Falls back to module defaults for any missing attribute so tests with
        a stub Settings (or no Settings at all) still get a working reader.

        Args:
            settings: Object with optional attributes ``RELEASE_VERSION_PATH``,
                ``RELEASE_HISTORY_PATH``, and ``RELEASE_HISTORY_MAX``.

        Returns:
            A ``ReleaseReader`` configured with paths + max entries.
        """
        currentPath = Path(getattr(settings, "RELEASE_VERSION_PATH", DEFAULT_CURRENT_PATH))
        historyPath = Path(getattr(settings, "RELEASE_HISTORY_PATH", DEFAULT_HISTORY_PATH))
        maxEntries = int(getattr(settings, "RELEASE_HISTORY_MAX", DEFAULT_HISTORY_MAX_ENTRIES))
        return ReleaseReader(
            currentPath=currentPath,
            historyPath=historyPath,
            historyMaxEntries=maxEntries,
        )

    def readCurrent(self) -> dict | None:
        """Read + validate the current release record.

        Returns:
            The validated record dict if the file exists and parses; ``None``
            otherwise (missing file, malformed JSON, invalid shape). Callers
            translate ``None`` into 503 -- the server is up but no deploy
            record has been stamped yet.
        """
        return readDeployVersion(self.currentPath)

    def readHistory(self, maxEntries: int | None = None) -> list[dict]:
        """Read the last N validated history entries.

        Args:
            maxEntries: Number of most-recent records to return. Falls back to
                ``self.historyMaxEntries`` when None. Negative or zero values
                yield an empty list.

        Returns:
            List of validated records, oldest-first within the returned slice
            (i.e., the natural file order of the last N appended lines).
            Invalid lines are silently skipped + warning-logged so a single
            corrupted line cannot blank the whole response.
        """
        limit = self.historyMaxEntries if maxEntries is None else int(maxEntries)
        if limit <= 0:
            return []

        if not self.historyPath.is_file():
            return []

        records: list[dict] = []
        try:
            with self.historyPath.open("r", encoding="utf-8") as f:
                for lineNum, raw in enumerate(f, start=1):
                    line = raw.strip()
                    if not line:
                        continue
                    try:
                        candidate = json.loads(line)
                    except json.JSONDecodeError as exc:
                        logger.warning(
                            "release history line %d: invalid JSON (%s); skipping",
                            lineNum, exc,
                        )
                        continue
                    if not validateRelease(candidate):
                        logger.warning(
                            "release history line %d: failed schema validation; skipping",
                            lineNum,
                        )
                        continue
                    records.append(candidate)
        except OSError as exc:
            logger.warning("Failed to read release history %s: %s", self.historyPath, exc)
            return []

        if len(records) <= limit:
            return records
        return records[-limit:]

    # ---- B-047 D4 retention enforcement (US-297) ---------------------------

    def pruneHistory(self, maxEntries: int | None = None) -> int:
        """Truncate ``.deploy-version-history`` to the last N records.

        Per B-047 D4 the server keeps last 10 releases (configurable). This
        method counts non-blank lines in the JSONL trail and rewrites the
        file atomically (tmp file + ``Path.replace``) when the count exceeds
        the cap. Validation is intentionally read-side only -- this method
        treats every non-blank line as a record slot so a malformed line
        does not silently make the cap accommodate "extra" valid records.

        Args:
            maxEntries: Retention cap. ``None`` falls back to
                ``self.historyMaxEntries``. Values <= 0 are treated as a
                foot-gun guard: the call returns 0 and leaves the file
                untouched (must NOT empty the file).

        Returns:
            The number of records pruned. 0 when the file is missing,
            blank, below cap, or the cap was non-positive.
        """
        limit = self.historyMaxEntries if maxEntries is None else int(maxEntries)
        if limit <= 0:
            return 0
        if not self.historyPath.is_file():
            return 0

        try:
            rawText = self.historyPath.read_text(encoding="utf-8")
        except OSError as exc:
            logger.warning("Failed to read history for prune %s: %s", self.historyPath, exc)
            return 0

        lines = [line for line in rawText.splitlines() if line.strip()]
        if len(lines) <= limit:
            return 0

        pruneCount = len(lines) - limit
        kept = lines[-limit:]

        tmpPath = self.historyPath.with_name(self.historyPath.name + ".tmp")
        try:
            tmpPath.write_text("\n".join(kept) + "\n", encoding="utf-8")
            tmpPath.replace(self.historyPath)
        except OSError as exc:
            logger.warning("Failed to atomically prune %s: %s", self.historyPath, exc)
            try:
                if tmpPath.exists():
                    tmpPath.unlink()
            except OSError:
                pass
            return 0

        logger.info(
            "Pruned %d release-history record(s) from %s; retained last %d",
            pruneCount, self.historyPath, limit,
        )
        return pruneCount

    def appendRelease(self, record: dict, maxEntries: int | None = None) -> None:
        """Append a release record to the history trail and enforce retention.

        Implements the B-047 D4 trigger: "After each new release lands, server
        prunes oldest releases beyond config-configured retention." The append
        is performed first so a prune failure cannot silently drop a fresh
        record; ``pruneHistory`` then trims the oldest entries.

        Args:
            record: A dict matching the US-241 release-record schema
                (``{version, releasedAt, gitHash, description}``; ``theme``
                optional). Validated via ``validateRelease`` before the
                file is mutated.
            maxEntries: Retention cap forwarded to ``pruneHistory``. ``None``
                falls back to ``self.historyMaxEntries``.

        Raises:
            ValueError: When the record fails ``validateRelease``. The
                history file is NOT mutated in this case.
            OSError: Propagated from underlying file write so the caller
                (typically the deploy script) can fail loudly.
        """
        if not validateRelease(record):
            raise ValueError(f"Release record failed schema validation: {record}")

        line = json.dumps(record)
        with self.historyPath.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

        self.pruneHistory(maxEntries=maxEntries)


__all__ = [
    "DEFAULT_CURRENT_PATH",
    "DEFAULT_HISTORY_MAX_ENTRIES",
    "DEFAULT_HISTORY_PATH",
    "ReleaseReader",
]

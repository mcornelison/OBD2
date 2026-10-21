################################################################################
# File Name: alerts_ack_store.py
# Purpose/Description: US-897-c (F-127) the boot-scoped acknowledgement store
#                      behind POST /alerts-ack: which states/alerts entries the
#                      driver has acknowledged THIS boot, kept in a Pi-local
#                      state file the orchestrator alone writes.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-20    | Rex (US-897-c) | Initial -- episode-keyed records, boot-scoped
#                                match, prune of the never-matchable, one write
#                                per change through power_watch writeAtomicJson.
# ================================================================================
################################################################################

"""The alerts acknowledgement store (US-897-c, Atlas s3 + Q20-Q27, G1).

A STATE FILE, not a table: operator state, never synced. It lives under
``/var/lib/eclipse-obd`` (``pi.warnings.ackStorePath``) so it survives a kiosk
or an orchestrator restart inside a boot; the tmpfs states dir would not.

Records are ``{id: {bootId, firstSeenTs, ackedAt}}``. An ack is keyed to the
EPISODE (G1): it counts only when its ``bootId`` is this boot AND its
``firstSeenTs`` is the entry's current one, so a recurrence -- a new episode
under the same id -- is unacknowledged by construction, and the next key-on
re-alerts every code with no special case.

Three rules are load-bearing:

* **Re-alert is the honest direction.** A missing, empty or torn file reads as
  no acks (one WARN); a boot id of ``unknown`` records nothing and counts
  nothing.
* **Prune only the never-matchable**: a prior boot's records, and an id that is
  no longer listed at all. A cleared STOP removed from the page by its ack stays
  listed by the arbiter, so its record holds until the boot ends; code records
  wait while the codes are unreadable, engine records while the engine is
  unassessed (unknown is not "cleared").
* **The orchestrator is the only writer**, and only when the record set
  changes, through the power_watch fdatasync writer. It never creates the
  directory: a missing ``/var/lib/eclipse-obd`` is a failed write, logged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Mapping
from typing import Any

from src.pi.power.power_watch.outcome import writeAtomicJson

__all__ = [
    "ACK_STORE_PATH_KEY",
    "ERROR_NOT_ACKABLE",
    "ERROR_STORE_WRITE_FAILED",
    "ERROR_UNKNOWN_ID",
    "UNKNOWN_BOOT_ID",
    "AlertsAckStore",
    "ackStorePathOf",
    "checkAckRequest",
]

logger = logging.getLogger("pi.obdii.alerts_ack_store")

#: The config key naming the store file (validator DEFAULT under /var/lib).
ACK_STORE_PATH_KEY = "pi.warnings.ackStorePath"

#: readBootId's answer when the boot id cannot be read: nothing is ackable.
UNKNOWN_BOOT_ID = "unknown"

# The outcome error vocabulary (Atlas Q26 + the store write).
ERROR_UNKNOWN_ID = "unknown_id"
ERROR_NOT_ACKABLE = "not_ackable"
ERROR_STORE_WRITE_FAILED = "store_write_failed"

# The record's source is the id's first segment (<source>:<key>:<tier>).
_SOURCE_CODE = "code"
_SOURCE_ENGINE = "engine"

# writeAtomicJson's failure-log label.
_WRITE_WHAT = "alerts-ack"


def ackStorePathOf(config: Mapping[str, Any]) -> str:
    """``pi.warnings.ackStorePath`` from the resolved config, else the validator default."""
    from common.config.validator import DEFAULTS

    node: Any = config
    for part in ACK_STORE_PATH_KEY.split("."):
        if not isinstance(node, Mapping) or node.get(part) is None:
            return str(DEFAULTS[ACK_STORE_PATH_KEY])
        node = node[part]
    return str(node)


def checkAckRequest(
    ids: Any, episodes: Iterable[Any], *, bootId: str, ackable: bool
) -> tuple[str | None, list[Any]]:
    """Decide whether an ack request may be recorded, all or nothing (Atlas Q26).

    Args:
        ids: The request's ``ids`` (the route has already checked the shape).
        episodes: Every episode the arbiter lists this boot.
        bootId: The host's boot id (``unknown`` when unreadable).
        ackable: False when there is no arbiter, emitter or store to ack into.

    Returns:
        ``(None, [])`` when every id may be recorded, else ``(error, badIds)``:
        ``not_ackable`` (nothing to ack into, or the boot id is unknown) or
        ``unknown_id`` (ids the arbiter does not list).
    """
    if not isinstance(ids, list) or not ids:
        return ERROR_UNKNOWN_ID, []
    requested = list(dict.fromkeys(i for i in ids if isinstance(i, str))) + [
        i for i in ids if not isinstance(i, str)
    ]
    if not ackable:
        return ERROR_NOT_ACKABLE, requested
    listed = {episode.id for episode in episodes}
    unknown = [i for i in requested if not isinstance(i, str) or i not in listed]
    if unknown:
        return ERROR_UNKNOWN_ID, unknown
    if bootId == UNKNOWN_BOOT_ID:
        return ERROR_NOT_ACKABLE, requested
    return None, []


def _sourceOf(entryId: str) -> str:
    return entryId.split(":", 1)[0]


class AlertsAckStore:
    """The acknowledgements of this boot, held in memory and mirrored to disk.

    Read once, lazily, on the first use under a KNOWN boot id -- so a host with
    no boot id (off-Linux) never touches the file. After that the in-memory
    copy is the truth and the file is rewritten only when it changes.

    Args:
        path: The store file (``pi.warnings.ackStorePath``).
    """

    def __init__(self, path: str) -> None:
        self._path = path
        self._records: dict[str, dict[str, Any]] | None = None

    @property
    def path(self) -> str:
        return self._path

    def records(self) -> dict[str, dict[str, Any]]:
        """A copy of the records as last read or written (empty before a read)."""
        return {k: dict(v) for k, v in (self._records or {}).items()}

    # ------------------------------------------------------------- reading

    def _loaded(self) -> dict[str, dict[str, Any]]:
        if self._records is None:
            self._records = self._read()
        return self._records

    def _read(self) -> dict[str, dict[str, Any]]:
        """The file's records; missing, empty or torn reads as none, with one WARN."""
        try:
            with open(self._path, encoding="utf-8") as fh:
                raw = fh.read()
        except OSError as e:
            logger.warning(
                "alerts-ack: no store at %s (%s) -- no acks this boot; every "
                "alert re-alerts (the honest direction)", self._path, e,
            )
            return {}
        try:
            payload = json.loads(raw) if raw.strip() else None
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            logger.warning(
                "alerts-ack: store at %s is empty or unreadable -- no acks this "
                "boot; every alert re-alerts (the honest direction)", self._path,
            )
            return {}
        return {
            str(entryId): {
                "bootId": record["bootId"],
                "firstSeenTs": record.get("firstSeenTs"),
                "ackedAt": record.get("ackedAt"),
            }
            for entryId, record in payload.items()
            if isinstance(record, dict) and isinstance(record.get("bootId"), str)
        }

    def matchingIds(self, episodes: Iterable[Any], *, bootId: str) -> frozenset[str]:
        """The ids whose record is THIS boot's and THIS episode's (G1).

        Args:
            episodes: The arbiter's episodes (``id``, ``firstSeenTs``).
            bootId: The host's boot id; ``unknown`` matches nothing.
        """
        if bootId == UNKNOWN_BOOT_ID:
            return frozenset()
        records = self._loaded()
        matched = set()
        for episode in episodes:
            record = records.get(episode.id)
            if (
                record is not None
                and record["bootId"] == bootId
                and record["firstSeenTs"] == episode.firstSeenTs
            ):
                matched.add(episode.id)
        return frozenset(matched)

    # ------------------------------------------------------------- writing

    def acknowledge(
        self, firstSeenById: Mapping[str, str | None], *, bootId: str, ackedAt: str
    ) -> bool:
        """Record every id in ONE write; idempotent for an already-acked episode.

        A prior boot's records are dropped by the same write (the first write of
        a new boot). A record already holding this boot and this episode keeps
        its original ``ackedAt``, so a re-ack changes nothing and writes nothing.

        Args:
            firstSeenById: ``{id: the episode's current firstSeenTs}``.
            bootId: The host's boot id; ``unknown`` records nothing.
            ackedAt: Canonical ISO UTC of the ack.

        Returns:
            True when the records hold every id (written, or already there);
            False when the boot id is unknown or the write failed (logged by the
            writer) -- the in-memory records are then left unchanged.
        """
        if bootId == UNKNOWN_BOOT_ID:
            return False
        records = {k: v for k, v in self._loaded().items() if v["bootId"] == bootId}
        for entryId, firstSeenTs in firstSeenById.items():
            held = records.get(entryId)
            if held is not None and held["firstSeenTs"] == firstSeenTs:
                continue
            records[entryId] = {"bootId": bootId, "firstSeenTs": firstSeenTs, "ackedAt": ackedAt}
        return self._commit(records)

    def prune(
        self,
        episodes: Iterable[Any],
        *,
        bootId: str,
        codeAssessed: bool,
        engineAssessed: bool,
    ) -> None:
        """Drop the records that can never match again; write only on a change.

        Args:
            episodes: Every episode the arbiter lists (an acked cleared STOP is
                still listed, so its record stays).
            bootId: The host's boot id; ``unknown`` prunes nothing.
            codeAssessed: ``sources.code.assessed`` of this emit -- while false
                no code record is pruned.
            engineAssessed: ``sources.engine.assessed`` of this emit -- while
                false no engine record is pruned.
        """
        if bootId == UNKNOWN_BOOT_ID:
            return
        current = self._loaded()
        listed = {episode.id for episode in episodes}
        kept: dict[str, dict[str, Any]] = {}
        for entryId, record in current.items():
            if record["bootId"] != bootId:
                continue
            source = _sourceOf(entryId)
            if (
                entryId in listed
                or (source == _SOURCE_CODE and not codeAssessed)
                or (source == _SOURCE_ENGINE and not engineAssessed)
            ):
                kept[entryId] = record
        self._commit(kept)

    def _commit(self, records: dict[str, dict[str, Any]]) -> bool:
        """Write ``records`` when they differ from the held set; adopt on success."""
        if records == self._records:
            return True
        if not writeAtomicJson(self._path, records, what=_WRITE_WHAT):
            return False
        self._records = records
        return True

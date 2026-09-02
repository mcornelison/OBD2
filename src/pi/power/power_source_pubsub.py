################################################################################
# File Name: power_source_pubsub.py
# Purpose/Description: US-668 -- the one seam between the process that OWNS BCM
#                      GPIO6 (eclipse-powerwatch) and the process that needs to
#                      know what it says (eclipse-obd). One acquisition, one
#                      publication, one subscription.
# Author: Atlas (Architect)
# Creation Date: 2026-09-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-02    | Atlas        | US-668 initial -- CIO-directed build.
# ================================================================================
################################################################################

"""Publish the power source once; subscribe to it everywhere else.

The defect this replaces
------------------------

``eclipse-powerwatch.service`` and ``eclipse-obd.service`` both constructed
``PldSensor`` on BCM GPIO6.  A GPIO line is claimed exclusively per-process, so
one of them always lost, got ``EBUSY``, and went permanently blind -- there is no
re-open path in ``PldSensor``.  Three punch-list items followed from that single
cause: ``power.source`` reading unknown, the battery-health verdict reading
stale, and ``battery_health_log`` frozen since 2026-05-16.

⚠️ **Neither unit orders against the other** (``eclipse-powerwatch`` has
``After=local-fs.target``; ``eclipse-obd`` has
``After=network.target bluetooth.target``), so the loser of that race was not
even stable between boots.  That is why ownership is *declared* here rather than
discovered at runtime.

Who owns it, and why that way round
-----------------------------------

**powerwatch owns the line.**  Not because it currently wins, but because it is
the process that must work when everything else is failing: it carries the
graceful poweroff and the sync-custody handoff proven on 2026-08-31
(``SYNC CUSTODY = DELIVERED``, 147 shutdown lines).  A safety interlock whose
hardware access depends on another service's start order is not an interlock.
The collector is the one that can afford to be told.

This is ``specs/ssot-design-pattern.md`` rule B verbatim -- *read once, persist,
publish, subscribe* -- and it is the shape every other sensor feed on this Pi
already has.  GPIO6 was the only source in the system with two independent
acquisitions, which is exactly why it was the only one with this defect.

🔴 THE SAFETY PROPERTY: silence is not good news
------------------------------------------------

A missing, stale or corrupt publication resolves to **unavailable**, never to
"external power is present".

If absence read as power-present, a publisher that died would be
indistinguishable from a healthy car, and the graceful shutdown this line exists
to trigger would simply never fire.  The failure would be silent, which is the
same property that let the original double-acquire survive four months.

⚠️ Note this is deliberately the OPPOSITE default to ``PldSensor`` itself, and
the difference is not an inconsistency.  ``PldSensor`` treats an unreadable
*local* signal as power-present because the alternative once bricked the Pi by
shutting down on uncertainty.  Here the question is different: it is not "is the
signal high or low" but "is anybody publishing at all", and a consumer that
cannot tell must say so rather than answer the first question anyway.  The
consumer decides policy from ``isAvailable``; this module never invents a
reading to fill the gap.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_MAX_AGE_SEC",
    "POWER_SOURCE_FILENAME",
    "SubscribedPld",
    "publishPowerSource",
    "readPowerSource",
]

POWER_SOURCE_FILENAME: str = "power-source.json"

#: How long a publication stays trustworthy.  Generous relative to the
#: publisher's poll interval so ordinary jitter never expires a good reading,
#: but far shorter than a drive, so a publisher that dies is noticed within one
#: card refresh rather than at the end of a leg.
DEFAULT_MAX_AGE_SEC: float = 30.0


def publishPowerSource(
    path: str,
    *,
    externalPowerPresent: bool,
    available: bool,
    reason: str | None = None,
) -> None:
    """Atomically publish the power source. Never raises.

    Written temp-then-``os.replace`` -- the convention every other emitter on
    this Pi uses -- so a subscriber polling this path can never observe a
    half-written document.

    Publishing must never break the publisher: powerwatch's job is to shut the
    Pi down cleanly, and a failed status write is not a reason to stop doing it.
    """
    payload: dict[str, Any] = {
        "externalPowerPresent": bool(externalPowerPresent),
        "available": bool(available),
        "reason": reason,
        "publishedAtEpoch": time.time(),
        "publishedBy": "eclipse-powerwatch",
    }
    tmp = f"{path}.tmp"
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except Exception as exc:  # noqa: BLE001 -- a status write must never be fatal
        logger.warning("power-source publish failed (%s): %s", path, exc)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def readPowerSource(
    path: str, maxAgeSec: float = DEFAULT_MAX_AGE_SEC,
) -> dict[str, Any] | None:
    """Return the publication, or ``None`` if absent, stale or unreadable.

    ``None`` is the honest answer to all three, and the caller must treat it as
    "we do not know" rather than as any particular power state.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.warning("power-source read failed (%s): %s", path, exc)
        return None

    if not isinstance(doc, dict):
        return None

    publishedAt = doc.get("publishedAtEpoch")
    if not isinstance(publishedAt, (int, float)):
        return None
    if (time.time() - float(publishedAt)) > maxAgeSec:
        # Stale is worse than missing: present, parseable, and confidently wrong.
        return None
    return doc


class SubscribedPld:
    """A read-only stand-in for ``PldSensor``, backed by the publication.

    Presents the same duck type ``PowerSourceProvider`` already consumes
    (``isAvailable`` / ``isExternalPowerPresent`` / ``isPowerLost`` /
    ``startupPolarityOk``), so the collector keeps its existing provider and only
    the BACKING SOURCE changes -- a GPIO line becomes a subscription.  Nothing
    downstream of the provider needed to know.

    Deliberately stateless: every call re-reads. A cached answer would reproduce
    the original defect's worst property -- a value latched at construction that
    can never recover.
    """

    def __init__(self, *, path: str, maxAgeSec: float = DEFAULT_MAX_AGE_SEC) -> None:
        self._path = path
        self._maxAgeSec = maxAgeSec

    @property
    def isAvailable(self) -> bool:
        """True only when a FRESH publication exists AND the owner could read
        the line. Absence, staleness, corruption and a publisher that reported
        its own failure all resolve to False."""
        doc = readPowerSource(self._path, self._maxAgeSec)
        return bool(doc and doc.get("available") is True)

    @property
    def unavailableReason(self) -> str | None:
        """Why the reading is unavailable -- carried through from the owner."""
        doc = readPowerSource(self._path, self._maxAgeSec)
        if doc is None:
            return "no_publication"
        if doc.get("available") is True:
            return None
        return doc.get("reason") or "unknown"

    def isExternalPowerPresent(self) -> bool:
        """🔴 Returns False when unavailable -- NOT True.

        This is the safety property. Reporting "power present" for an absent
        publication would let a dead publisher masquerade as a healthy car.
        Callers must gate on :attr:`isAvailable` first; this never invents a
        reading to fill a gap.
        """
        doc = readPowerSource(self._path, self._maxAgeSec)
        if not doc or doc.get("available") is not True:
            return False
        return bool(doc.get("externalPowerPresent"))

    def isPowerLost(self) -> bool:
        """True only when we KNOW power is gone -- never on uncertainty."""
        return self.isAvailable and not self.isExternalPowerPresent()

    def startupPolarityOk(self) -> bool:
        return self.isAvailable and self.isExternalPowerPresent()

    def close(self) -> None:
        """No-op: a subscriber owns no hardware. Present for interface parity."""
        return

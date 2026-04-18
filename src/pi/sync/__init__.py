"""
Pi -> server HTTP sync client package (US-149).

Consumers typically construct :class:`SyncClient` from a validated config dict
and call :meth:`SyncClient.pushDelta` (one table) or
:meth:`SyncClient.pushAllDeltas` (all in-scope tables).  Each call reads the
sync_log high-water mark, fetches delta rows, POSTs to
``{baseUrl}/api/v1/sync`` with an ``X-API-Key`` header, and advances the
high-water mark ON SUCCESS ONLY.  A failed push never advances the mark --
that invariant is what protects Pi-side data from loss when the server is
unreachable.
"""

from __future__ import annotations

from src.pi.sync.client import PushResult, PushStatus, SyncClient

__all__ = ["PushResult", "PushStatus", "SyncClient"]

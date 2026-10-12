################################################################################
# File Name: stored_ack_reply.py
# Purpose/Description: Test helper -- the reply a server gives when it stored
#                      every row of a sync push (US-776-i).  Fake servers use it
#                      so a successful push still carries the stored ack.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-11    | Rex (US-776-i)| Initial helper
# ================================================================================
################################################################################

"""
Fake-server replies that carry the US-776-h stored ack.

Since US-776-i the Pi advances a table's mark only when the reply's
``stored[table]`` says every row sent is stored.  A fake that answers a bare
``{"status": "ok"}`` therefore reads as a FAILED push.  Tests that mean
"the server stored it" answer with :func:`storedAckReplyFor` instead.
"""

from __future__ import annotations

import json
from typing import Any


def storedAckFor(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a full-store reply body for a parsed ``/api/v1/sync`` payload.

    Args:
        payload: The request body as the server would parse it.

    Returns:
        ``{"status": "ok", "batchId": ..., "stored": {table: {storedCount,
        maxStoredSourceId}}}`` with every row of every table counted as stored.
    """
    stored: dict[str, dict[str, Any]] = {}
    for tableName, section in (payload.get("tables") or {}).items():
        ids = [int(row["id"]) for row in section.get("rows", []) if "id" in row]
        stored[tableName] = {
            "storedCount": len(ids),
            "maxStoredSourceId": max(ids) if ids else None,
        }
    return {"status": "ok", "batchId": payload.get("batchId", ""), "stored": stored}


def storedAckReplyFor(requestBody: bytes | None) -> bytes:
    """Return the encoded full-store reply for a raw request body.

    Args:
        requestBody: The bytes a fake opener received as ``req.data``.

    Returns:
        The JSON reply bytes; ``{"status": "ok"}`` with an empty ``stored``
        block when the request carried no body.
    """
    payload = json.loads(requestBody.decode("utf-8")) if requestBody else {}
    return json.dumps(storedAckFor(payload)).encode("utf-8")

################################################################################
# File Name: token.py
# Purpose/Description: One-source auth token for the F-103 splash state server.
#   The token lives in a single file (the SSOT). The state HTTP server loads it
#   to validate requests; the chromium kiosk receives it injected into the page
#   it is served. "Token SSOT, one source" (US-393 DoD): exactly one file is the
#   authority -- it is generated once, persisted 0600, and never regenerated.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Ralph (Rex)  | Initial implementation (US-393 F-103 boot splash)
# ================================================================================
################################################################################

"""Single-source auth token for the splash localhost state server."""

from __future__ import annotations

import os
import secrets
from pathlib import Path

# Token length in bytes of entropy passed to secrets.token_urlsafe. 32 bytes of
# entropy yields a ~43-char url-safe string -- ample for a localhost-only guard,
# far above the >=32-char floor the consumers assume.
_TOKEN_ENTROPY_BYTES = 32

# Owner read/write only. The token is a capability; no other local user may read
# it (defence-in-depth on top of the server's 127.0.0.1-only bind).
_TOKEN_FILE_MODE = 0o600


def loadOrCreateToken(tokenPath: str) -> str:
    """Return the splash state-server token, creating it once if absent.

    The file at ``tokenPath`` is the single source of truth. On first call (file
    missing) a cryptographically random url-safe token is generated, written
    0600, and returned. On every subsequent call the existing file content is
    returned verbatim -- the token is never regenerated, so the server and the
    kiosk always agree on one value.

    Args:
        tokenPath: Absolute path to the token file (the SSOT). Its parent
            directory is created if it does not exist.

    Returns:
        The token string (stripped of surrounding whitespace/newline).
    """
    path = Path(tokenPath)
    if path.exists():
        return path.read_text(encoding="utf-8").strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)
    # Create with restrictive perms atomically: open O_CREAT|O_EXCL at 0600 so
    # the token is never momentarily world-readable between write and chmod.
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, _TOKEN_FILE_MODE)
    try:
        os.write(fd, (token + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return token

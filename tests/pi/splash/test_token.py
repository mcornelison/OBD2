################################################################################
# File Name: test_token.py
# Purpose/Description: Tests for the F-103 splash state-server token SSOT.
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

"""Tests for ``pi.splash.token`` -- the one-source auth token for the state server."""

import os
import stat
import sys

import pytest

from pi.splash.token import loadOrCreateToken


def test_loadOrCreateToken_missingFile_createsRandomToken(tmp_path):
    """
    Given: a token path that does not exist
    When:  loadOrCreateToken is called
    Then:  a non-empty random token is returned and persisted to the file
    """
    tokenPath = tmp_path / "states" / ".http-token"

    token = loadOrCreateToken(str(tokenPath))

    assert token
    assert len(token) >= 32
    assert tokenPath.read_text(encoding="utf-8").strip() == token


def test_loadOrCreateToken_existingFile_returnsSameValue(tmp_path):
    """
    Given: a token file already created by a first call
    When:  loadOrCreateToken is called again on the same path
    Then:  the identical token is returned (the file is the single source)
    """
    tokenPath = tmp_path / ".http-token"

    first = loadOrCreateToken(str(tokenPath))
    second = loadOrCreateToken(str(tokenPath))

    assert first == second


def test_loadOrCreateToken_existingFile_isNotRegenerated(tmp_path):
    """
    Given: a token file with a known pre-seeded value
    When:  loadOrCreateToken reads it
    Then:  the pre-seeded value is returned verbatim (no overwrite)
    """
    tokenPath = tmp_path / ".http-token"
    tokenPath.write_text("preexisting-token-value-1234567890\n", encoding="utf-8")

    token = loadOrCreateToken(str(tokenPath))

    assert token == "preexisting-token-value-1234567890"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file-mode check")
def test_loadOrCreateToken_createdFile_isOwnerReadOnly(tmp_path):
    """
    Given: a fresh token path
    When:  loadOrCreateToken creates the file
    Then:  it is written 0600 (owner-only) so other users cannot read the token
    """
    tokenPath = tmp_path / ".http-token"

    loadOrCreateToken(str(tokenPath))

    mode = stat.S_IMODE(os.stat(tokenPath).st_mode)
    assert mode == 0o600

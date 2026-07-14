################################################################################
# File Name: test_encoding_helper.py
# Purpose/Description: Tests for _encoding.forceUtf8Stdio -- the canonical
#                      UTF-8 stdio guard that stops Windows cp1252
#                      UnicodeEncodeError crashes in PM tooling (US-466 / F-118).
# Author: Rex (Ralph / windows-dev)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (Ralph)  | Initial implementation -- US-466 TDD
# ================================================================================
################################################################################

"""Tests for offices.pm.scripts._encoding.forceUtf8Stdio (US-466 cp1252 harden)."""
from __future__ import annotations

import io
import sys

import pytest

from offices.pm.scripts._encoding import forceUtf8Stdio

# The exact glyph that broke pm_status --backlog: U+2192 RIGHTWARDS ARROW,
# present in migrated v1 backlog titles + aggregated bigDefinitionOfDone clauses.
ARROW = "→"


class _NoReconfigure:
    """A stream stand-in with no reconfigure() -- e.g. pytest capture."""

    def __init__(self) -> None:
        self.written = ""

    def write(self, s: str) -> int:
        self.written += s
        return len(s)


def _cp1252Wrapper() -> io.TextIOWrapper:
    """A real text stream that raises on the arrow glyph until reconfigured."""
    return io.TextIOWrapper(io.BytesIO(), encoding="cp1252", newline="")


# ---------------------------------------------------------------------------
# functional: the guard actually flips the encoding and stops the crash
# ---------------------------------------------------------------------------

def test_forceUtf8Stdio_cp1252StreamRaisesArrow_beforeGuard():
    """
    Given: a cp1252-encoded stdout (the Windows default console codec)
    When: the arrow glyph is written WITHOUT the guard
    Then: it raises UnicodeEncodeError (the bug this story fixes)
    """
    # Arrange
    stream = _cp1252Wrapper()

    # Act / Assert -- reproduce the crash the guard prevents
    with pytest.raises(UnicodeEncodeError):
        stream.write(ARROW)
        stream.flush()


def test_forceUtf8Stdio_cp1252Stdout_arrowPrintsAfterGuard(monkeypatch):
    """
    Given: sys.stdout/stderr are cp1252 wrappers
    When: forceUtf8Stdio() runs, then the arrow glyph is written
    Then: no UnicodeEncodeError; the UTF-8 bytes land in the buffer
    """
    # Arrange
    out = _cp1252Wrapper()
    err = _cp1252Wrapper()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", err)

    # Act
    forceUtf8Stdio()
    print(ARROW)  # goes to the patched sys.stdout
    print(ARROW, file=sys.stderr)

    # Assert -- both streams now encode UTF-8 (arrow == b"\xe2\x86\x92")
    assert out.encoding.lower().replace("-", "") == "utf8"
    assert err.encoding.lower().replace("-", "") == "utf8"
    out.flush()
    err.flush()
    assert ARROW.encode("utf-8") in out.buffer.getvalue()
    assert ARROW.encode("utf-8") in err.buffer.getvalue()


# ---------------------------------------------------------------------------
# defensive: streams without reconfigure() are skipped, not crashed
# ---------------------------------------------------------------------------

def test_forceUtf8Stdio_streamsWithoutReconfigure_skippedSilently(monkeypatch):
    """
    Given: sys.stdout/stderr have no reconfigure() (pytest capture / None-like)
    When: forceUtf8Stdio() runs
    Then: it does not raise (nothing to harden, nothing to crash)
    """
    # Arrange
    monkeypatch.setattr(sys, "stdout", _NoReconfigure())
    monkeypatch.setattr(sys, "stderr", _NoReconfigure())

    # Act / Assert -- no AttributeError
    forceUtf8Stdio()


# ---------------------------------------------------------------------------
# idempotent: safe to call more than once
# ---------------------------------------------------------------------------

def test_forceUtf8Stdio_calledTwice_isIdempotent(monkeypatch):
    """
    Given: cp1252 streams
    When: forceUtf8Stdio() runs twice
    Then: encoding is UTF-8 and no error is raised on the second call
    """
    # Arrange
    out = _cp1252Wrapper()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _cp1252Wrapper())

    # Act
    forceUtf8Stdio()
    forceUtf8Stdio()

    # Assert
    assert out.encoding.lower().replace("-", "") == "utf8"


def test_forceUtf8Stdio_customErrorsPolicy_forwarded(monkeypatch):
    """
    Given: cp1252 streams
    When: forceUtf8Stdio(errors="strict") runs
    Then: the errors policy is forwarded to the stream reconfigure
    """
    # Arrange
    out = _cp1252Wrapper()
    monkeypatch.setattr(sys, "stdout", out)
    monkeypatch.setattr(sys, "stderr", _cp1252Wrapper())

    # Act
    forceUtf8Stdio(errors="strict")

    # Assert
    assert out.errors == "strict"

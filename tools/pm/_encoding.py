"""Canonical UTF-8 stdio recipe for the PM tooling (Windows cp1252 hardening).

Single source of truth for the "stop UnicodeEncodeError on Windows consoles"
recipe. Migrated v1 backlog titles and aggregated bigDefinitionOfDone clauses
carry Unicode (e.g. the '->' rendered as U+2192 and em-dashes); on a Windows
cp1252 console any `print()` of that text raises `UnicodeEncodeError` unless
the interpreter's stdio is UTF-8.

The recipe has two layers (documented in
`offices/pm/knowledge/feedback-pm-windows-encoding-ad-hoc-audits.md`):

1. **In-code (this module)** -- `forceUtf8Stdio()` reconfigures BOTH stdout and
   stderr to UTF-8 so a script is self-sufficient (no env var required).
2. **Ad-hoc fallback** -- `PYTHONIOENCODING=utf-8` in the environment, for a
   one-off invocation of a script that has not (yet) been wired.

Companion to `_freeze.py`: a small underscore-prefixed shared helper imported by
the scripts that already depend on the `tools.pm` package (e.g.
`sprint_lint.py`). Scripts that advertise "Stdlib-only" self-containment inline
the same guard rather than importing this module -- both forms are behaviourally
identical; see the knowledge doc.
"""

from __future__ import annotations

import sys


def forceUtf8Stdio(errors: str = "replace") -> None:
    """Reconfigure `sys.stdout` and `sys.stderr` to UTF-8, in place.

    Idempotent and defensive: a stream is only reconfigured when it exposes
    `reconfigure` (a real `io.TextIOWrapper`). Streams replaced by a test
    harness (pytest capture) or absent under `pythonw.exe` (`None`) are skipped
    silently -- there is nothing to harden and nothing to crash.

    Must be called before the first `print()` of any non-ASCII text. Calling it
    at module import time (top of a script, before `main()` runs) is the
    intended usage.

    Args:
        errors: The codec error policy passed to `reconfigure`. Defaults to
            "replace" so a stream forced back to a narrow codec still cannot
            raise `UnicodeEncodeError`. Under UTF-8 every codepoint encodes, so
            the policy is belt-and-suspenders.

    Returns:
        None. The reconfiguration is an in-place side effect on the streams.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors=errors)

################################################################################
# File Name: test_probe_utf8_roundtrip.py
# Purpose/Description: US-597 (TD-068) -- the BEHAVIOURAL half of the encoding
#                      guard: the shipped non-ASCII copy in dashboard.html must
#                      survive a round trip through the node probe and come back
#                      byte-for-byte.
#
#                      The static half (tests/lint/
#                      test_subprocess_declares_encoding.py) reads the source and
#                      proves nobody DECLARED the wrong thing. This half runs the
#                      real harness and proves the declaration WORKS.
#
#                      🔴 WHY THIS TEST SPAWNS A CHILD INTERPRETER. fleet.json
#                      mandates PYTHONUTF8=1, and under that flag `text=True`
#                      already decodes UTF-8 -- so an in-process version of this
#                      test passes whether or not the fix is present. That is
#                      A-27(c) -- an instrument that cannot show the failure --
#                      built INSIDE the fix for A-27. So the measurement is taken
#                      in a child launched with PYTHONUTF8=0, where the defect is
#                      observable, and the test is therefore live in a normal
#                      session rather than only in a hand-arranged one.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-09    | Rex (US-597) | Initial -- PYTHONUTF8=0 child round trip, with
#               |              | the negative control that proves the child can
#               |              | still witness the defect.
# ================================================================================
################################################################################

"""The shipped glyphs round-trip through render_harness, in a cp1252 child.

What is actually being measured
-------------------------------
``dashboard.html`` ships eight non-ASCII characters of real UI copy -- the
overflow menu (U+22EE), the sync and power glyphs (U+21C5, U+26A1), the alert
triangle (U+26A0), the two chevrons (U+2039, U+203A), the standby ellipsis
(U+2026) and the wifi bullet (U+2022). ``render_harness.runDashboard`` sends the
parsed markup INTO node and reads the rendered DOM back OUT. The return leg is
the one under test: node writes UTF-8 unconditionally, and the parent decodes it
with whatever ``subprocess.run`` was told to use.

Why the negative control is not optional
----------------------------------------
A green round trip has two possible causes: the fix works, or the child never
actually ran in a cp1252 locale and the defect could not have appeared. Those
are indistinguishable from the pass alone. The control runs the SAME child with
``encoding=`` stripped back off at the subprocess boundary -- the pre-US-597
tree, reproduced without editing it -- and requires the corruption to appear. If
it does not appear, the environment cannot witness the defect and the test says
so by SKIPPING rather than by passing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_HERE, os.pardir, os.pardir))
_DASHBOARD_DIR = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")

# BOTH shipped assets, because both put characters on the panel. The markup
# authors the chrome (the ⋮ menu, the glyph row, the ‹ Back chevrons);
# carousel.js authors the copy it injects at render time -- including the em
# dash that every honest-absence tile prints. A set derived from the markup
# alone is missing U+2014 and reads a correct render as corruption, which is
# how the first draft of this file failed.
_SHIPPED_ASSETS = (
    os.path.join(_DASHBOARD_DIR, "dashboard.html"),
    os.path.join(_DASHBOARD_DIR, "carousel.js"),
)


def _authoredNonAscii() -> set[str]:
    """The non-ASCII characters the SHIPPED dashboard assets actually contain.

    DERIVED from the assets, never re-typed here. A hand-written inventory of
    the UI's glyphs is a copy of the answer that goes stale the first time a
    designer adds one -- the US-610 defect, in a file written to prevent a
    different one. It also means this module holds no non-ASCII literal of its
    own that could be corrupted by the defect it is testing.
    """
    authored: set[str] = set()
    for path in _SHIPPED_ASSETS:
        with open(path, encoding="utf-8") as fh:
            authored.update(char for char in fh.read() if ord(char) > 127)
    return authored


# The two characters a UTF-8 lead byte becomes when a cp1252 reader gets hold of
# it: 0xC2 -> U+00C2 for a 2-byte sequence, 0xE2 -> U+00E2 for a 3-byte one.
# Neither appears in the shipped copy, so either one in a rendered DOM is the
# mojibake signature and nothing else.
_MOJIBAKE_LEAD_BYTES = ("Â", "â")

# `subprocess.run` is patched at the module object, so BOTH the harness's own
# call and any future one inside it are covered. Stripping `encoding` reproduces
# the pre-sweep tree exactly -- text mode, no declared codec -- without editing
# a swept file back to broken, which would trip the static guard.
_CHILD = textwrap.dedent(
    '''
    import json, locale, subprocess, sys

    sys.path.insert(0, sys.argv[1])
    mode, outPath = sys.argv[2], sys.argv[3]

    if mode == "bare":
        realRun = subprocess.run
        def strippedRun(*a, **kw):
            kw.pop("encoding", None)
            return realRun(*a, **kw)
        subprocess.run = strippedRun

    from tests.ui.render_harness import runDashboard

    error = None
    try:
        result = runDashboard(routes={})
        text = json.dumps(result, ensure_ascii=False)
    except Exception as exc:            # a cp1252 decode failure is a WITNESS
        text = ""
        error = f"{type(exc).__name__}: {exc}"

    with open(outPath, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "localeEncoding": locale.getpreferredencoding(False),
                "utf8Mode": sys.flags.utf8_mode,
                "text": text,
                "error": error,
            },
            fh,
        )
    '''
)


def _runChild(mode: str, tmpPath: str) -> dict:
    """Render the dashboard in a child interpreter with PYTHONUTF8 turned OFF.

    Args:
        mode: ``"declared"`` for the shipped harness, ``"bare"`` to strip the
            declared encoding back off and reproduce the pre-US-597 tree.
        tmpPath: Where the child writes its (always UTF-8) report.

    Returns:
        The child's report: its locale encoding, the rendered text, any error.

    Raises:
        AssertionError: if the child itself failed to run.
    """
    env = dict(os.environ)
    # Both must go. PYTHONUTF8=0 disables UTF-8 mode; PYTHONIOENCODING would
    # otherwise override the locale for the child's own streams and muddy the
    # reading of what `text=True` actually chose.
    env["PYTHONUTF8"] = "0"
    env.pop("PYTHONIOENCODING", None)

    completed = subprocess.run(
        [sys.executable, "-c", _CHILD, _REPO_ROOT, mode, tmpPath],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        check=False,
        cwd=_REPO_ROOT,
        env=env,
    )
    assert completed.returncode == 0, (
        f"the {mode} child interpreter failed to run at all, so nothing was "
        f"measured:\n{completed.stdout}\n{completed.stderr}"
    )
    with open(tmpPath, encoding="utf-8") as fh:
        return json.load(fh)


class TestProbeUtf8RoundTrip:
    """The shipped glyphs survive the harness; the control proves they could not have."""

    def test_authoredNonAscii_isDerivedFromTheShippedMarkup_andIsNotEmpty(self) -> None:
        """
        Given: the shipped dashboard.html
        When:  its non-ASCII characters are collected
        Then:  there are some, and none is a mojibake lead byte

        An empty authored set would make the round-trip assertion below pass
        vacuously, and an empty read of a path that does not exist is
        byte-identical to an empty read of an ASCII-only file -- the failure
        already caught once this sprint on US-612's dead `specs/UI/` pointer.
        """
        for path in _SHIPPED_ASSETS:
            assert os.path.exists(path), path
        authored = _authoredNonAscii()
        assert len(authored) >= 8, sorted(f"U+{ord(c):04X}" for c in authored)
        assert not authored.intersection(_MOJIBAKE_LEAD_BYTES), (
            "the SHIPPED markup already contains a mojibake lead byte, so it "
            "cannot be used as the signature of a decoding failure: "
            + repr(sorted(authored.intersection(_MOJIBAKE_LEAD_BYTES)))
        )

    def test_runDashboard_inACp1252Child_returnsTheAuthoredGlyphsUncorrupted(
        self, tmp_path
    ) -> None:
        """
        Given: the SHIPPED dashboard.html rendered through the SHIPPED node probe
        When:  the harness runs in a child interpreter with PYTHONUTF8=0
        Then:  every non-ASCII character that comes back is one the markup
               authored, and no mojibake lead byte appears

        This is validationCriterion #4 -- a non-ASCII string round-trips
        byte-for-byte. Before the sweep the same run returns mojibake, and the
        one-character diff reads exactly like a bug in the production copy.

        ⚠️ THE CLAIM IS "NOTHING CAME BACK CORRUPTED", NOT "EVERY GLYPH IS
        PRESENT". Those are different, and the first draft of this test asserted
        the second and failed honestly: U+2026 is authored inside the idle-boot
        span, which carousel.js REPLACES during render, so it is legitimately
        absent from the finished DOM for a reason that has nothing to do with
        encoding. An absence test whose subject never rendered is not a
        measurement (US-638). The surviving set is therefore derived, not
        re-typed, and the invariant is stated over what DID render.
        """
        report = _runChild("declared", str(tmp_path / "declared.json"))
        assert report["error"] is None, report["error"]
        rendered = report["text"]
        assert rendered, "the child rendered nothing, so nothing was measured"

        authored = _authoredNonAscii()
        renderedNonAscii = {char for char in rendered if ord(char) > 127}

        assert renderedNonAscii, (
            "the rendered DOM contains no non-ASCII at all, so this test cannot "
            "distinguish a correct decode from a blank render"
        )
        foreign = renderedNonAscii - authored
        assert not foreign, (
            "the round trip through the node probe produced characters the "
            "shipped markup never authored -- this is mojibake, and it is what "
            "a missing `encoding=` looks like from the far end "
            f"(child locale: {report['localeEncoding']}):\n"
            + "\n".join(f"  U+{ord(c):04X} {c!r}" for c in sorted(foreign))
        )

    def test_runDashboard_withTheDeclaredEncodingStripped_isCorrupted(
        self, tmp_path
    ) -> None:
        """
        Given: the same child, with `encoding=` stripped at the subprocess boundary
        When:  the dashboard is rendered
        Then:  mojibake appears -- or the environment cannot witness the defect
               at all, and this test SKIPS saying so

        🔴 THE NEGATIVE CONTROL. Without it, the test above passes on a machine
        where the defect is impossible, and a guard that can only come out one
        way is not evidence.

        It earned its place on its FIRST RUN. The initial draft of `_runChild`
        built the PYTHONUTF8=0 environment and then forgot to pass `env=` to
        `subprocess.run`, so the child silently inherited the fleet's
        PYTHONUTF8=1. This control skipped with "this host's locale is already
        UTF-8" -- an honest report that the measurement had not been set up --
        while the positive test alone would have gone green and proved nothing.
        """
        report = _runChild("bare", str(tmp_path / "bare.json"))
        localeEncoding = (report["localeEncoding"] or "").lower().replace("-", "")

        if localeEncoding in {"utf8", "cp65001"}:
            pytest.skip(
                "this host's locale encoding is already UTF-8 "
                f"({report['localeEncoding']}), so `text=True` decodes correctly "
                "even with PYTHONUTF8=0 and the defect cannot be reproduced here. "
                "The STATIC guard (tests/lint/test_subprocess_declares_encoding.py) "
                "is what carries the contract on this machine."
            )

        if report["error"] is not None:
            # A hard UnicodeDecodeError is the same defect, louder -- cp1252 has
            # five undefined byte values and a UTF-8 stream can land on one.
            assert "codec" in report["error"] or "decode" in report["error"], (
                "the stripped-encoding child failed for a reason unrelated to "
                f"decoding, so nothing was proven: {report['error']}"
            )
            return

        rendered = report["text"]
        assert rendered, "the control child rendered nothing, so nothing was measured"
        assert any(lead in rendered for lead in _MOJIBAKE_LEAD_BYTES), (
            "stripping `encoding=` did NOT corrupt the shipped glyphs "
            f"(child locale: {report['localeEncoding']}). Either the harness no "
            "longer routes through subprocess.run, or this environment cannot "
            "witness the defect -- and in both cases the test above is proving "
            "less than it claims."
        )

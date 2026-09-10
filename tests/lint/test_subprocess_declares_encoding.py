################################################################################
# File Name: test_subprocess_declares_encoding.py
# Purpose/Description: US-597 (TD-068 + TD-084) -- guard against a subprocess
#                      call under tests/ or src/ that asks for TEXT mode without
#                      DECLARING the encoding it wants that text decoded with.
#
#                      `subprocess.run(..., text=True)` with no `encoding=`
#                      decodes the child's bytes with the PARENT's locale
#                      encoding. On this Windows dev host that is cp1252, so a
#                      probe that emits the UTF-8 bytes 0xC2 0xB7 (U+00B7 `·`)
#                      hands the test back the two characters `Â·`. The
#                      production string was correct; the INSTRUMENT was wrong,
#                      and the one-character diff reads exactly like a UI bug.
#
#                      TD-068 recorded 5 affected helpers. 100 call sites were
#                      measured on 2026-09-09. It has been fixed piecemeal at
#                      least three times (US-489, plus two files carrying an
#                      explanatory `encoding="utf-8"` that names TD-068) and
#                      grown back every time -- because a sweep is a one-off and
#                      nothing stood at the door afterwards. This file is the
#                      door.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-09
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-09    | Rex (US-597) | Initial -- AST guard over tests/, plus the
#               |              | positive controls that keep its FAILURE path
#               |              | exercised on every run.
# 2026-09-09    | Rex (US-710) | SUBJECT widened tests/ -> tests/ + src/. The
#               |              | predicate is unchanged and NOT duplicated: src/
#               |              | held 15 sites with the identical defect, two of
#               |              | them parsing user-authored SSIDs and three on
#               |              | the shutdown path where the codec RAISES.
# ================================================================================
################################################################################

"""AST guard: a text-mode subprocess call under ``tests/`` or ``src/`` must declare ``encoding=``.

Why ``src/`` joined the subject (US-710 / TD-us597)
---------------------------------------------------
US-597 shipped this guard pointed at ``tests/`` only, because that is where the
lying instrument had been found. A census with THIS DETECTOR then measured 15
sites in ``src/`` with the identical defect. Two of them
(``src/pi/network/home_detector.py``) decode **SSIDs, which are user-authored and
routinely non-ASCII**, and three sit on the **shutdown path**, where an undefined
cp1252 byte does not mojibake -- it RAISES, and a raise on the shutdown path is
how sync custody gets lost. Widening the SUBJECT is a change of which files are
walked; the PREDICATE above is untouched and deliberately not copied, because a
second implementation of it would go stale exactly the way the swept sites did.

The subject is the ABSENCE of a declared encoding, not the presence of utf-8
-------------------------------------------------------------------------------
A call site that genuinely needs cp1252 (or latin-1, or the console code page)
is free to say so -- ``encoding="cp1252"`` passes this guard. What does not pass
is a call site that asks for `str` and leaves the codec to whatever locale the
machine happens to boot with, because that is a decision nobody made and the
value differs between the dev bench, the Pi and CI.

Why this guard is not itself defeated by PYTHONUTF8
---------------------------------------------------
``fleet.json`` mandates ``PYTHONUTF8=1``, and under that flag ``text=True``
already decodes UTF-8 -- so the DEFECT is invisible in a normal session and any
behavioural test of it is inert here. That is why the durable guard is STATIC:
it reads the source, not the runtime, so it is identical with the variable set,
unset, on the bench, on the Pi and in CI. The behavioural half is pinned
separately, in a child interpreter launched with ``PYTHONUTF8=0``, by
``tests/ui/test_probe_utf8_roundtrip.py``.

Why AST and not a grep
----------------------
``tests/`` contains the literal text ``subprocess.run(..., text=True)`` inside
docstrings and comments that EXPLAIN this very defect -- including this file's
own header, three lines up. A textual scan flags its own documentation and is
red on a clean tree, which is how a lint gets deleted. ``ast`` sees only real
calls.

Known and deliberate limits
---------------------------
The predicate is about what is VISIBLE AT THE CALL SITE. A call that hides its
keywords behind ``**kwargs`` cannot be resolved statically; if such a site also
writes ``text=True`` inline it is flagged and the fix is to write the encoding
inline beside it. A site whose text-ness ALSO arrives through the splat is not
visible to this guard and is not claimed to be. There are none today.

The second limit was MEASURED during US-710 and is the larger of the two:
the guard resolves its CALLEE against real ``subprocess`` imports, so a call
through an INJECTION SEAM -- ``runFn(...)``, ``runner(...)``,
``self._subprocessRun(...)``, each of which DEFAULTS to ``subprocess.run`` -- is
invisible to it. 11 such sites in ``src/`` carry this defect in production today
(kiosk_watchdog 4, obdctl 2, update_applier 3, panel_liveness 1,
service_control 1) and this guard will stay green over every one of them. They
are recorded in TD-us710 rather than swept here, and the reason the predicate was
NOT loosened to "any call with ``text=`` and no ``encoding=``" is arithmetic: that
predicate returns 30 hits in ``src/`` of which **19 are ``LayoutElement(text=...)``
-- a UI label with no codec within a mile of it**. A guard that is 63% false
positives is a guard somebody switches off.
"""

from __future__ import annotations

import ast
import os

# The subprocess entry points that accept `text=`/`universal_newlines=` and
# decode the child's bytes on the caller's behalf. `call` and `check_call`
# return only a status, but conditionalOutcome #2 of US-597 is explicit: a site
# that never reads stdout is still fixed, because a latent defect in a harness
# surfaces as a fake production bug at the worst possible moment.
_DECODING_ENTRY_POINTS = frozenset(
    {"run", "Popen", "check_output", "check_call", "call"}
)

# Both spellings of "give me str, not bytes". `universal_newlines` is the
# pre-3.7 alias and still resolves to the same code path today.
_TEXT_MODE_KEYWORDS = frozenset({"text", "universal_newlines"})

_TESTS_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir)
)
_REPO_ROOT = os.path.normpath(os.path.join(_TESTS_ROOT, os.pardir))

# The trees this guard walks. US-710 added `src`. Both are relative to the repo
# root and BOTH are asserted non-empty below -- an unwalkable root is
# byte-identical to a clean one, which is how this guard would pass forever
# while testing nothing.
_SUBJECT_ROOTS = ("tests", "src")


def _isLiteralFalse(node: ast.expr) -> bool:
    """True only for the literal ``False``.

    ``text=False`` is not text mode, so it is not this guard's business. Any
    other expression -- a name, a call, a conditional -- MIGHT be True at
    runtime and is treated as text mode, because a guard that assumes the
    favourable branch of something it cannot see is not a guard.
    """
    return isinstance(node, ast.Constant) and node.value is False


def _subprocessAliases(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Resolve how THIS module refers to subprocess.

    Returns ``(moduleAliases, directNames)`` -- the names bound to the module
    itself (``import subprocess as sp`` -> ``{"sp"}``) and the entry points
    pulled into the namespace directly (``from subprocess import run`` ->
    ``{"run"}``). Resolving imports rather than hardcoding ``subprocess.`` is
    what stops the next arrival from evading the guard by aliasing.
    """
    moduleAliases: set[str] = set()
    directNames: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    moduleAliases.add(alias.asname or "subprocess")
        elif isinstance(node, ast.ImportFrom) and node.module == "subprocess":
            for alias in node.names:
                if alias.name in _DECODING_ENTRY_POINTS:
                    directNames.add(alias.asname or alias.name)
    return moduleAliases, directNames


def _calleeName(
    call: ast.Call, moduleAliases: set[str], directNames: set[str]
) -> str | None:
    """The subprocess entry point this call resolves to, or None."""
    fn = call.func
    if isinstance(fn, ast.Attribute):
        if (
            isinstance(fn.value, ast.Name)
            and fn.value.id in moduleAliases
            and fn.attr in _DECODING_ENTRY_POINTS
        ):
            return f"{fn.value.id}.{fn.attr}"
        return None
    if isinstance(fn, ast.Name) and fn.id in directNames:
        return fn.id
    return None


def findUndeclaredEncodingCalls(source: str, filename: str) -> list[tuple[int, str]]:
    """Every text-mode subprocess call in ``source`` that declares no encoding.

    Args:
        source: Python source text.
        filename: Path used for the parse error message only.

    Returns:
        ``[(lineNumber, calleeName), ...]`` in source order. Empty is clean.

    Raises:
        SyntaxError: if ``source`` does not parse.
    """
    tree = ast.parse(source, filename=filename)
    moduleAliases, directNames = _subprocessAliases(tree)
    if not moduleAliases and not directNames:
        return []

    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _calleeName(node, moduleAliases, directNames)
        if callee is None:
            continue
        declaresText = any(
            kw.arg in _TEXT_MODE_KEYWORDS and not _isLiteralFalse(kw.value)
            for kw in node.keywords
        )
        declaresEncoding = any(kw.arg == "encoding" for kw in node.keywords)
        if declaresText and not declaresEncoding:
            offenders.append((node.lineno, callee))
    return sorted(offenders)


def _subjectFiles() -> list[str]:
    """Every .py file under the subject roots -- tests/ and src/."""
    found: list[str] = []
    for root in _SUBJECT_ROOTS:
        for dirPath, dirNames, fileNames in os.walk(os.path.join(_REPO_ROOT, root)):
            dirNames[:] = [
                d for d in dirNames if d not in {"__pycache__", ".pytest_cache"}
            ]
            found.extend(
                os.path.join(dirPath, name)
                for name in fileNames
                if name.endswith(".py")
            )
    return sorted(found)


class TestSubprocessDeclaresEncoding:
    """The guard, and the positive controls that prove it can still fail."""

    def test_everyTextModeSubprocessCall_declaresAnEncoding(self) -> None:
        """
        Given: every .py file under tests/ and src/ -- this guard's subject
        When:  each is parsed and its subprocess call sites resolved
        Then:  none asks for text mode without also declaring an encoding
        """
        offenders: list[str] = []
        for path in _subjectFiles():
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            for lineNumber, callee in findUndeclaredEncodingCalls(source, path):
                relative = os.path.relpath(path, _REPO_ROOT).replace(os.sep, "/")
                offenders.append(f"{relative}:{lineNumber}  {callee}(..., text=True)")

        # This message is deliberately ASCII-only. The first draft spelled the
        # mojibake out as `·` -> `Â·`, and the fails-on-purpose run -- which
        # must happen with PYTHONUTF8 unset -- printed it through a cp1252
        # console that replaced both with `?`. A failure report about a decoding
        # defect must survive the decoding defect it reports.
        assert not offenders, (
            f"{len(offenders)} subprocess call site(s) under "
            f"{'/ or '.join(_SUBJECT_ROOTS)}/ ask for text "
            "mode without declaring an encoding. Without `encoding=`, the child's "
            "UTF-8 output is decoded with the PARENT's locale codec (cp1252 on "
            "the Windows bench), so the two bytes 0xC2 0xB7 -- one U+00B7 MIDDLE "
            "DOT, the separator this UI prints everywhere -- read back as the two "
            "characters U+00C2 U+00B7, and the harness lies about what it read. "
            'Add `encoding="utf-8"` -- or any encoding the site genuinely needs, '
            "with a comment saying why. (US-597 / TD-068)\n" + "\n".join(offenders)
        )

    def test_findUndeclaredEncodingCalls_bareTextModeCall_isFlagged(self) -> None:
        """
        Given: the exact shape US-597 swept out of the tree, as source text
        When:  the detector reads it
        Then:  it is reported, with its line number and callee

        🔴 THIS IS THE POSITIVE CONTROL AND IT IS THE POINT OF THE FILE. A guard
        that has only ever been observed PASSING is indistinguishable from a
        guard that cannot fail -- this project's own A-27, and the subject of
        the sprint this story rides in. Hand-reintroducing an offender proves it
        once, on one afternoon; this proves it on every run forever.
        """
        source = (
            "import subprocess\n"
            "proc = subprocess.run(['node', 'p.js'], capture_output=True, text=True)\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == [
            (2, "subprocess.run")
        ]

    def test_findUndeclaredEncodingCalls_aliasedAndDirectImports_areResolved(
        self,
    ) -> None:
        """
        Given: subprocess reached by module alias and by direct `from` import
        When:  the detector reads each
        Then:  both are flagged

        A guard that only knows the string "subprocess.run" is evaded by one
        `import subprocess as sp`, which nobody would write to dodge a lint and
        somebody will eventually write for brevity.
        """
        aliased = "import subprocess as sp\nsp.run(['x'], text=True)\n"
        direct = "from subprocess import run\nrun(['x'], text=True)\n"
        assert findUndeclaredEncodingCalls(aliased, "<control>") == [(2, "sp.run")]
        assert findUndeclaredEncodingCalls(direct, "<control>") == [(2, "run")]

    def test_findUndeclaredEncodingCalls_popenAndCheckOutput_areFlagged(self) -> None:
        """
        Given: the text-mode entry points that are not `run`
        When:  the detector reads them
        Then:  each is flagged

        The tree holds one `subprocess.Popen(..., text=True)` today
        (tests/fleet/bench_sandbox.py). A guard scoped to `run` alone would have
        swept it and then held the door open for its return.
        """
        source = (
            "import subprocess\n"
            "subprocess.Popen(['x'], text=True)\n"
            "subprocess.check_output(['x'], text=True)\n"
            "subprocess.check_call(['x'], universal_newlines=True)\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == [
            (2, "subprocess.Popen"),
            (3, "subprocess.check_output"),
            (4, "subprocess.check_call"),
        ]

    def test_findUndeclaredEncodingCalls_declaredEncoding_isClean(self) -> None:
        """
        Given: text-mode calls that DO declare an encoding -- utf-8 and a
               deliberate non-utf-8 one
        When:  the detector reads them
        Then:  neither is flagged

        The subject is the ABSENCE of a declaration, not the presence of utf-8
        (US-597 conditionalOutcome #1). A site that has genuinely decided it
        needs cp1252 has made the decision this guard exists to force.
        """
        source = (
            "import subprocess\n"
            "subprocess.run(['x'], text=True, encoding='utf-8')\n"
            "subprocess.run(['x'], text=True, encoding='cp1252')\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == []

    def test_findUndeclaredEncodingCalls_binaryAndFalseTextMode_areClean(self) -> None:
        """
        Given: calls that never asked for text at all
        When:  the detector reads them
        Then:  neither is flagged

        Bytes need no codec. Flagging them would be noise, and a noisy guard is
        a guard that gets a blanket suppression bolted onto it.
        """
        source = (
            "import subprocess\n"
            "subprocess.run(['x'], capture_output=True)\n"
            "subprocess.run(['x'], text=False)\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == []

    def test_findUndeclaredEncodingCalls_prosePicturingTheDefect_isClean(self) -> None:
        """
        Given: a module whose DOCSTRING and comments contain the offending text
        When:  the detector reads it
        Then:  nothing is flagged

        This file's own header quotes `subprocess.run(..., text=True)` in order
        to explain it. So do TD-068, TD-084 and several test docstrings written
        during the piecemeal fixes. A grep is red on a clean tree here, and a
        lint that is red on a clean tree gets deleted rather than obeyed.
        """
        source = (
            '"""Never write subprocess.run([...], text=True) with no encoding."""\n'
            "import subprocess\n"
            "# subprocess.run(['x'], text=True)  <- do not do this\n"
            "subprocess.run(['x'], text=True, encoding='utf-8')\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == []

    def test_subjectFiles_coversEveryDeclaredRoot_andNoneIsEmpty(self) -> None:
        """
        Given: the file set this guard walks
        When:  it is enumerated and split by declared root
        Then:  EVERY root contributed files, and this module is among them

        🔴 THE DEGENERATE PASS IS WHY THIS TEST EXISTS, AND US-710 IS THE STORY
        THAT MAKES IT LOAD-BEARING RATHER THAN TIDY. Widening a subject is
        satisfied by widening it to a path that does not exist: `os.walk` over a
        missing directory yields NOTHING and raises NOTHING, so a typo'd
        `_SUBJECT_ROOTS` entry is byte-for-byte indistinguishable from a clean
        tree and the guard passes forever while watching half of what it claims.
        Asserting the TOTAL is not enough either -- tests/ alone clears any
        plausible floor, so a broken src/ walk would hide under it. Hence a
        per-root count. Same failure this sprint already caught once, on US-612's
        dead `specs/UI/` pointer.
        """
        files = _subjectFiles()
        perRoot = {
            root: [
                f
                for f in files
                if f.startswith(os.path.join(_REPO_ROOT, root) + os.sep)
            ]
            for root in _SUBJECT_ROOTS
        }
        assert set(_SUBJECT_ROOTS) == {"tests", "src"}, (
            "the declared subject changed; US-710 widened it to exactly tests/ "
            f"and src/, this run walked {_SUBJECT_ROOTS}"
        )
        empty = [root for root, found in perRoot.items() if len(found) < 50]
        assert not empty, (
            "a declared subject root contributed (almost) nothing, so the guard "
            "above is passing vacuously over it: "
            + ", ".join(f"{root}={len(perRoot[root])}" for root in _SUBJECT_ROOTS)
        )
        assert __file__ in files or os.path.normpath(__file__) in files

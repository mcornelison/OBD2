################################################################################
# File Name: test_subprocess_declares_encoding.py
# Purpose/Description: US-597 (TD-068 + TD-084) -- guard against a subprocess
#                      call under tests/, src/, scripts/ or tools/ that asks for TEXT mode without
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
# 2026-09-10    | Rex (US-716) | RESOLUTION widened: the callee may now resolve
#               |              | through an injection seam's default. Reported
#               |              | the 11 TD-us710 sites by name before they were
#               |              | fixed; admits no LayoutElement(text=...) hit.
# 2026-09-10    | Rex (US-717) | SUBJECT widened to scripts/ -- one token in
#               |              | _SUBJECT_ROOTS. Reported the 12 sites (one a
#               |              | Popen) by name before they were fixed. Per-root
#               |              | floor 50 -> 20: scripts/ holds 41 files.
# 2026-09-10    | Rex (US-718) | SUBJECT widened to tools/ -- one token. Reported
#               |              | the 9 tools/pm sites by name before they were
#               |              | fixed; sprint_lint + pm_status among them.
# 2026-09-10    | Rex (US-722) | SUBJECT-side control: an offender planted under
#               |              | every claimed root, walked by _subjectFiles().
#               |              | The string-fed controls are detector-side only.
# ================================================================================
################################################################################

"""AST guard: a text-mode subprocess call under ``tests/``, ``src/``, ``scripts/`` or ``tools/`` must declare ``encoding=``.

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

Two halves, two kinds of control (US-722)
-----------------------------------------
This guard is a DETECTOR (is this call a violation?) applied to a SUBJECT (which
files, and which calls in them, get looked at). Every burn on record was the
SUBJECT: ``tests/`` alone while ``src/`` held 15 sites, then 11 seam calls it
could not resolve. The controls that feed the detector a STRING prove only the
detector can fail -- they were green through both burns. The subject control
plants one offender under each root this docstring claims, in a scratch tree,
and runs the guard's own walk over it.

Known and deliberate limits
---------------------------
The predicate is about what is VISIBLE AT THE CALL SITE. A call that hides its
keywords behind ``**kwargs`` cannot be resolved statically; if such a site also
writes ``text=True`` inline it is flagged and the fix is to write the encoding
inline beside it. A site whose text-ness ALSO arrives through the splat is not
visible to this guard and is not claimed to be. There are none today.

Injection seams (US-716, closing TD-us710)
------------------------------------------
US-710 MEASURED the guard blind to calls through an INJECTION SEAM --
``runFn(...)``, ``runner(...)``, ``self._subprocessRun(...)``, each defaulting
to ``subprocess.run`` -- and 11 such sites in ``src/`` carried the defect while
it was green. ``_SeamResolver`` now follows a seam from its default: a parameter
defaulting to an entry point, a name or ``self`` attribute assigned one (also
as an ``or`` fallback), and a no-default parameter that a call in the same
module hands a seam to. Measured on 2026-09-10 before the sweep, over
``tests/`` + ``src/``: own-default alone found 9 of the 11 (it missed obdctl,
whose helpers take ``runner`` with no default of their own); with the hand-off,
11 of 11 and nothing else.

The predicate was NOT loosened to "any call with ``text=`` and no
``encoding=``", and that is arithmetic: that predicate returns 30 hits in
``src/`` of which **19 are ``LayoutElement(text=...)`` -- a UI label with no
codec within a mile of it**. A guard that is 63% false positives is a guard
somebody switches off. Seam resolution widens what the CALLEE may resolve
through; it still starts from a real subprocess import and never from a
parameter's name.

What seam resolution does NOT see, stated rather than implied: a seam handed
across a MODULE boundary to a parameter with no default of its own; a seam held
on any object other than ``self``; and a runner wrapped before the call
(``functools.partial``, a lambda). None of those carry a text-mode call today.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

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

# The trees this guard walks. US-710 added `src`, US-717 `scripts`, US-718
# `tools` (its 9 sites fixed in the same story, so the guard was never red on a
# tree nobody may touch -- US-706). All are relative to the repo root and EVERY
# one is asserted non-empty below -- an unwalkable root is byte-identical to a
# clean one, which is how this guard would pass forever while testing nothing.
_SUBJECT_ROOTS = ("tests", "src", "scripts", "tools")


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


_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


class _SeamResolver:
    """Which names and ``self`` attributes in a module hold a subprocess entry point.

    US-716. A seam is a runner that DEFAULTS to a subprocess entry point:

    * a parameter whose default is one -- ``runFn=subprocess.run``;
    * a name or ``self`` attribute assigned one, directly or as the fallback of
      an ``or`` -- ``self._subprocessRun = subprocessRun or subprocess.run``;
    * a parameter with NO default that a call in the same module hands a seam
      to -- obdctl's ``queryState(unit, runner)``, called from the ``main``
      that owns the default. Reading only a parameter's own default resolves 9
      of the 11 sites US-716 names and misses exactly those two.

    Resolution stays anchored on a real subprocess import: a parameter is never
    a seam because of its NAME, and a ``text=`` keyword never counts unless the
    callee resolves. That is what keeps ``LayoutElement(text=...)`` out.
    """

    def __init__(self, tree: ast.Module, moduleAliases: set[str], directNames: set[str]):
        self._moduleAliases = moduleAliases
        self._directNames = directNames
        self._functions: list[_FunctionNode] = [
            node for node in ast.walk(tree) if isinstance(node, _FunctionNode)
        ]
        self._byName: dict[str, list[_FunctionNode]] = {}
        for function in self._functions:
            self._byName.setdefault(function.name, []).append(function)
        self.seamNames: dict[int, set[str]] = {
            id(function): self._defaultedParameters(function) for function in self._functions
        }
        self.seamAttributes: set[str] = set()
        self._propagate(tree)

    def _isEntryPoint(self, node: ast.expr) -> bool:
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return node.value.id in self._moduleAliases and node.attr in _DECODING_ENTRY_POINTS
        return isinstance(node, ast.Name) and node.id in self._directNames

    def isSeamValue(self, node: ast.expr, seams: set[str]) -> bool:
        """True when ``node`` evaluates to a subprocess entry point in this scope."""
        if self._isEntryPoint(node):
            return True
        if isinstance(node, ast.Name):
            return node.id in seams
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            return node.value.id == "self" and node.attr in self.seamAttributes
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            return any(self.isSeamValue(value, seams) for value in node.values)
        return False

    @staticmethod
    def _positional(function: _FunctionNode) -> list[ast.arg]:
        return function.args.posonlyargs + function.args.args

    def _defaultedParameters(self, function: _FunctionNode) -> set[str]:
        positional = self._positional(function)
        defaults = function.args.defaults
        pairs = list(zip(positional[len(positional) - len(defaults) :], defaults))
        pairs += [
            (param, default)
            for param, default in zip(function.args.kwonlyargs, function.args.kw_defaults)
            if default is not None
        ]
        return {param.arg for param, default in pairs if self._isEntryPoint(default)}

    def _handOff(self, call: ast.Call, seams: set[str]) -> bool:
        """Mark the callee's parameters that ``call`` supplies a seam to."""
        if not isinstance(call.func, ast.Name):
            return False
        changed = False
        for target in self._byName.get(call.func.id, []):
            targetSeams = self.seamNames[id(target)]
            positional = self._positional(target)
            supplied = [
                (positional[index].arg, arg)
                for index, arg in enumerate(call.args)
                if index < len(positional)
            ]
            supplied += [(kw.arg, kw.value) for kw in call.keywords if kw.arg is not None]
            for paramName, value in supplied:
                if paramName not in targetSeams and self.isSeamValue(value, seams):
                    targetSeams.add(paramName)
                    changed = True
        return changed

    def _assign(self, node: ast.Assign, seams: set[str]) -> bool:
        if not self.isSeamValue(node.value, seams):
            return False
        changed = False
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id not in seams:
                seams.add(target.id)
                changed = True
            elif (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "self"
                and target.attr not in self.seamAttributes
            ):
                self.seamAttributes.add(target.attr)
                changed = True
        return changed

    def _propagate(self, tree: ast.Module) -> None:
        # Module scope carries no seam names of its own, but a module-level call
        # can still hand a literal `subprocess.run` to a function.
        scopes: list[tuple[ast.AST, set[str]]] = [(tree, set())]
        scopes += [(function, self.seamNames[id(function)]) for function in self._functions]
        changed = True
        while changed:
            changed = False
            for scope, seams in scopes:
                for node in ast.walk(scope):
                    if isinstance(node, ast.Assign):
                        changed |= self._assign(node, seams)
                    elif isinstance(node, ast.Call):
                        changed |= self._handOff(node, seams)

    def seamCallee(self, call: ast.Call, seams: set[str]) -> str | None:
        """The seam this call goes through, or None."""
        fn = call.func
        if isinstance(fn, ast.Name) and fn.id in seams:
            return fn.id
        if (
            isinstance(fn, ast.Attribute)
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "self"
            and fn.attr in self.seamAttributes
        ):
            return f"self.{fn.attr}"
        return None


def findSubprocessCallSites(source: str, filename: str) -> list[tuple[ast.Call, str]]:
    """Every call in ``source`` that reaches a subprocess entry point.

    Directly (``subprocess.run``, an alias, a ``from`` import) or through an
    injection seam (US-716). Text mode is NOT considered here -- this is the
    resolution half of the guard, exposed so a test can prove it still SEES the
    seams after they have all been fixed.

    Args:
        source: Python source text.
        filename: Path used for the parse error message only.

    Returns:
        ``[(callNode, calleeName), ...]`` in source order.

    Raises:
        SyntaxError: if ``source`` does not parse.
    """
    tree = ast.parse(source, filename=filename)
    moduleAliases, directNames = _subprocessAliases(tree)
    if not moduleAliases and not directNames:
        return []

    resolver = _SeamResolver(tree, moduleAliases, directNames)
    found: dict[int, tuple[ast.Call, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            callee = _calleeName(node, moduleAliases, directNames)
            if callee is not None:
                found[id(node)] = (node, callee)
    # A nested function sees its enclosing function's seams, so walking each
    # function's whole body (nested defs included) is the closure rule.
    for function in resolver._functions:
        seams = resolver.seamNames[id(function)]
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and id(node) not in found:
                callee = resolver.seamCallee(node, seams)
                if callee is not None:
                    found[id(node)] = (node, callee)
    return sorted(found.values(), key=lambda pair: (pair[0].lineno, pair[0].col_offset))


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
    offenders: list[tuple[int, str]] = []
    for node, callee in findSubprocessCallSites(source, filename):
        declaresText = any(
            kw.arg in _TEXT_MODE_KEYWORDS and not _isLiteralFalse(kw.value)
            for kw in node.keywords
        )
        declaresEncoding = any(kw.arg == "encoding" for kw in node.keywords)
        if declaresText and not declaresEncoding:
            offenders.append((node.lineno, callee))
    return sorted(offenders)


def _subjectFiles(repoRoot: str = _REPO_ROOT) -> list[str]:
    """Every .py file under the subject roots -- see ``_SUBJECT_ROOTS``.

    ``repoRoot`` exists so US-722's subject control can walk a planted tree
    through THIS function; the guard itself always walks the real repo.
    """
    found: list[str] = []
    for root in _SUBJECT_ROOTS:
        for dirPath, dirNames, fileNames in os.walk(os.path.join(repoRoot, root)):
            dirNames[:] = [
                d for d in dirNames if d not in {"__pycache__", ".pytest_cache"}
            ]
            found.extend(
                os.path.join(dirPath, name)
                for name in fileNames
                if name.endswith(".py")
            )
    return sorted(found)


def _undeclaredEncodingOffenders(repoRoot: str = _REPO_ROOT) -> list[str]:
    """The guard's whole pipeline -- subject walk, then detector -- without the assert.

    Args:
        repoRoot: Tree to walk. The guard passes nothing; the subject control
            passes a planted tree.

    Returns:
        ``["<relative/path>:<line>  <callee>(..., text=True)", ...]``. Empty is clean.
    """
    offenders: list[str] = []
    for path in _subjectFiles(repoRoot):
        with open(path, encoding="utf-8") as fh:
            source = fh.read()
        for lineNumber, callee in findUndeclaredEncodingCalls(source, path):
            relative = os.path.relpath(path, repoRoot).replace(os.sep, "/")
            offenders.append(f"{relative}:{lineNumber}  {callee}(..., text=True)")
    return offenders


# US-722. Where this guard CLAIMS to look -- the four roots its module docstring
# names -- recorded INDEPENDENTLY of _SUBJECT_ROOTS. A control that planted under
# each entry of _SUBJECT_ROOTS would narrow in lockstep with the subject and could
# never fail. One offender per claimed root, nested, each in a burn's own shape:
# (relative path, source, the offender line the guard must report).
_PLANTED_OFFENDERS: tuple[tuple[str, str, str], ...] = (
    (
        "tests/lint/test_us722_planted.py",
        "import subprocess\nsubprocess.run(['node', 'p.js'], capture_output=True, text=True)\n",
        "tests/lint/test_us722_planted.py:2  subprocess.run(..., text=True)",
    ),
    (
        # TD-us710's location and shape: a seam defaulting to subprocess.run.
        "src/pi/display/us722_planted.py",
        "import subprocess\n"
        "def probe(runFn=subprocess.run):\n"
        "    return runFn(['journalctl'], capture_output=True, text=True)\n",
        "src/pi/display/us722_planted.py:3  runFn(..., text=True)",
    ),
    (
        # US-717's one entry point that is not `run`.
        "scripts/us722_planted.py",
        "import subprocess\nsubprocess.Popen(['python', '-c', 'pass'], text=True)\n",
        "scripts/us722_planted.py:2  subprocess.Popen(..., text=True)",
    ),
    (
        # tools/ is the thinnest root, and every file in it sits under tools/pm.
        "tools/pm/_us722_planted.py",
        "from subprocess import run\nrun(['git', 'rev-parse', 'HEAD'], text=True)\n",
        "tools/pm/_us722_planted.py:2  run(..., text=True)",
    ),
)


class TestSubprocessDeclaresEncoding:
    """The guard, its DETECTOR-side controls, and its SUBJECT-side control.

    US-722: the string-fed controls prove the detector can still fail. They say
    nothing about which files get walked -- only
    ``test_subjectControl_offenderPlantedUnderEveryClaimedRoot_isReported`` does.
    """

    def test_everyTextModeSubprocessCall_declaresAnEncoding(self) -> None:
        """
        Given: every .py file under tests/, src/, scripts/ and tools/ -- this guard's subject
        When:  each is parsed and its subprocess call sites resolved
        Then:  none asks for text mode without also declaring an encoding
        """
        offenders = _undeclaredEncodingOffenders()

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

    def test_findUndeclaredEncodingCalls_parameterDefaultingToSubprocess_isFlagged(
        self,
    ) -> None:
        """
        Given: the kiosk_watchdog / panel_liveness / service_control shape -- a
               runner parameter DEFAULTING to subprocess.run, positional and
               keyword-only
        When:  the detector reads it
        Then:  each text-mode call through the seam is flagged, by seam name

        US-716. Before this, the guard resolved only the literal callee, so a
        call reaching subprocess.run through an injection seam did not resolve
        and was not seen -- 11 such sites sat in src/ while the guard was green.
        """
        source = (
            "import subprocess\n"
            "def probe(runFn=subprocess.run):\n"
            "    return runFn(['journalctl'], capture_output=True, text=True)\n"
            "def restart(unit, *, runner=subprocess.run):\n"
            "    return runner(['systemctl', 'restart', unit], text=True)\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == [
            (3, "runFn"),
            (5, "runner"),
        ]

    def test_findUndeclaredEncodingCalls_attributeSeamWithOrDefault_isFlagged(
        self,
    ) -> None:
        """
        Given: the update_applier shape -- `self._x = injected or subprocess.run`
        When:  the detector reads a text-mode call through `self._x`
        Then:  it is flagged
        """
        source = (
            "import subprocess\n"
            "class Applier:\n"
            "    def __init__(self, subprocessRun=None):\n"
            "        self._subprocessRun = subprocessRun or subprocess.run\n"
            "    def head(self):\n"
            "        return self._subprocessRun(['git', 'rev-parse', 'HEAD'], text=True)\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == [
            (6, "self._subprocessRun")
        ]

    def test_findUndeclaredEncodingCalls_seamPassedToParameterWithNoDefault_isFlagged(
        self,
    ) -> None:
        """
        Given: the obdctl shape -- the default lives on `main`, and the helpers
               that actually call the runner take it with NO default of their own
        When:  the detector reads the module
        Then:  both helpers' calls are flagged, positional and keyword hand-off

        A rule that reads only a parameter's OWN default resolves 9 of the 11
        sites US-716 names and misses exactly these two, so the seam is
        followed through the call that supplies it.
        """
        source = (
            "import subprocess\n"
            "def queryState(unit, runner):\n"
            "    return runner(['systemctl', 'show', unit], capture_output=True, text=True)\n"
            "def act(*, unit, runner):\n"
            "    return runner(['systemctl', 'stop', unit], text=True)\n"
            "def main(*, runner=subprocess.run):\n"
            "    queryState('a', runner)\n"
            "    act(unit='a', runner=runner)\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == [
            (3, "runner"),
            (5, "runner"),
        ]

    def test_findUndeclaredEncodingCalls_seamDefaultViaAliasOrDirectImport_isFlagged(
        self,
    ) -> None:
        """
        Given: seam defaults spelled through a module alias and a direct import
        When:  the detector reads each
        Then:  both are flagged -- import resolution applies to seams too
        """
        aliased = "import subprocess as sp\ndef f(run=sp.run):\n    run(['x'], text=True)\n"
        direct = "from subprocess import run\ndef f(r=run):\n    r(['x'], text=True)\n"
        assert findUndeclaredEncodingCalls(aliased, "<control>") == [(3, "run")]
        assert findUndeclaredEncodingCalls(direct, "<control>") == [(3, "r")]

    def test_findUndeclaredEncodingCalls_textKeywordOffTheSubprocessPath_isClean(
        self,
    ) -> None:
        """
        Given: a `text=` keyword on a UI constructor, a runner-NAMED parameter
               nothing supplies a subprocess to, a seam defaulting to a fake, and
               a seam call that declares its encoding -- all in a module that
               imports subprocess
        When:  the detector reads it
        Then:  nothing is flagged

        🔴 THIS IS THE FALSE-POSITIVE CLASS US-710 MEASURED AND REJECTED:
        flagging any `text=` without `encoding=` returned 30 hits over src/, 19
        of them `LayoutElement(text=...)` -- 63% noise. Seam resolution widens
        what the CALLEE may resolve through; it must not relax the callee check
        into a keyword check, and it must not key on a parameter's name.
        """
        source = (
            "import subprocess\n"
            "from layout import LayoutElement\n"
            "def fakeRun(*args, **kwargs):\n"
            "    return None\n"
            "def draw(label):\n"
            "    return LayoutElement(text=label)\n"
            "def query(unit, runner):\n"
            "    return runner(['systemctl', unit], text=True)\n"
            "def probe(runFn=fakeRun):\n"
            "    return runFn(['x'], text=True)\n"
            "def declared(runFn=subprocess.run):\n"
            "    return runFn(['x'], text=True, encoding='utf-8')\n"
            "query('a', fakeRun)\n"
        )
        assert findUndeclaredEncodingCalls(source, "<control>") == []

    def test_findSubprocessCallSites_realSrc_resolvesEveryKnownInjectionSeam(
        self,
    ) -> None:
        """
        Given: the five src/ modules that reach subprocess through a seam
        When:  their REAL source is resolved -- whether or not each call now
               declares an encoding
        Then:  every seam is seen, by module and seam name

        US-716 validation #4: the guard must be green over src/ for a reason a
        reader can check, not because it cannot see. The guard above going green
        after the 11 sites were fixed is indistinguishable from the resolution
        silently breaking again -- this pins that it still SEES them.
        """
        expected = {
            ("src/pi/display/kiosk_watchdog.py", "runFn"),
            ("src/pi/display/panel_liveness.py", "runFn"),
            ("src/pi/ops/obdctl.py", "runner"),
            ("src/pi/splash/service_control.py", "runner"),
            ("src/pi/update/update_applier.py", "self._subprocessRun"),
        }
        seen: set[tuple[str, str]] = set()
        for relative in sorted({module for module, _ in expected}):
            path = os.path.join(_REPO_ROOT, *relative.split("/"))
            with open(path, encoding="utf-8") as fh:
                source = fh.read()
            seen.update(
                (relative, callee) for _, callee in findSubprocessCallSites(source, path)
            )
        assert expected <= seen, f"seams no longer resolved: {sorted(expected - seen)}"

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
        assert set(_SUBJECT_ROOTS) == {"tests", "src", "scripts", "tools"}, (
            "the declared subject changed; US-710 widened it to tests/ and src/, "
            f"US-717 to scripts/, US-718 to tools/ -- this run walked {_SUBJECT_ROOTS}"
        )
        # The failure this catches is a walk that yields ZERO files. The floor
        # was 50 until US-717: scripts/ holds 41, so a floor above the smallest
        # REAL root reports a populated tree as vacuous. 20 still sits far above
        # zero and below every declared root.
        minimumFilesPerRoot = 20
        empty = [root for root, found in perRoot.items() if len(found) < minimumFilesPerRoot]
        assert not empty, (
            "a declared subject root contributed (almost) nothing, so the guard "
            "above is passing vacuously over it: "
            + ", ".join(f"{root}={len(perRoot[root])}" for root in _SUBJECT_ROOTS)
        )
        assert __file__ in files or os.path.normpath(__file__) in files

    def test_subjectControl_offenderPlantedUnderEveryClaimedRoot_isReported(
        self, tmp_path: Path
    ) -> None:
        """
        Given: a scratch tree holding ONE known offender under each root this
               guard claims -- tests/, src/, scripts/, tools/ -- each nested, each
               in the shape of a real burn
        When:  the guard's own pipeline (``_subjectFiles`` then the detector) runs
        Then:  every planted offender is reported, and nothing else is

        🔴 US-722. THIS IS THE SUBJECT-SIDE CONTROL; EVERY CONTROL ABOVE IS
        DETECTOR-SIDE. Those feed ``findUndeclaredEncodingCalls`` a string and
        never touch ``_subjectFiles()`` -- and they were green the whole time the
        guard sat green over the 11 seam sites TD-us710 found. This one walks a
        planted tree through the function the guard walks the repo with, so a
        narrowed subject turns it RED.

        The planted locations are ``_PLANTED_OFFENDERS``, NOT derived from
        ``_SUBJECT_ROOTS`` -- derive them and removing a root removes its plant.
        """
        for relative, source, _ in _PLANTED_OFFENDERS:
            planted = tmp_path.joinpath(*relative.split("/"))
            planted.parent.mkdir(parents=True, exist_ok=True)
            planted.write_text(source, encoding="utf-8")

        reported = _undeclaredEncodingOffenders(str(tmp_path))

        expected = [offender for _, _, offender in _PLANTED_OFFENDERS]
        missed = sorted(set(expected) - set(reported))
        assert not missed, (
            "an offender planted where this guard CLAIMS to look was not reported, "
            f"so the subject no longer covers it: {missed}. "
            f"Walked roots: {_SUBJECT_ROOTS}"
        )
        assert sorted(reported) == sorted(expected)

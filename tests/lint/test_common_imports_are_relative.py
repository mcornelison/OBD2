################################################################################
# File Name: test_common_imports_are_relative.py
# Purpose/Description: US-553 AC#2 -- guard against ABSOLUTE self-imports inside
#                      src/common. An intra-package import written as
#                      `from common.X import Y` (or `from src.common.X import Y`)
#                      instead of the relative `from .X import Y` resolves in
#                      one tier's runtime and dies in the other's.
#
#                      This is the 2026-08-11 P0 on record: US-530 added
#                      `from common.config.overlay import applyConfigOverlay`
#                      to src/common/config/secrets_loader.py. The server runs
#                      with PYTHONPATH=<repo root> and imports the package as
#                      `src.common`, so a bare top-level `common` is not
#                      importable -- obd-server crash-looped with
#                      "ModuleNotFoundError: No module named 'common'" until
#                      commit d6517429 changed it to `from .overlay import ...`.
#
#                      Pairs with US-547 (placeholder lint) / US-543 (parity
#                      guard). Sibling half of US-553: tests/deploy/
#                      test_stale_bytecode_purge.py.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-28    | Rex (US-553) | Initial -- AST-based absolute-self-import
#               |              | guard over src/common, with the docstring
#               |              | false-positive control.
# ================================================================================
################################################################################

"""AST guard: every intra-package import inside src/common must be RELATIVE.

Why AST and not a grep
----------------------
`src/common` legitimately contains the string ``from common.config.validator
import ConfigValidator`` -- five times, in ``Usage:`` docstrings that show
CALLERS how to import the package. A textual scan flags all five and is red on
a clean tree, which is how a lint gets deleted. ``ast`` sees only real import
statements, and gets docstrings, comments and quoted examples right for free.

Why both prefixes are flagged
-----------------------------
``src/common`` is imported under TWO names in this project:

* the Pi puts ``src/`` on ``sys.path`` (src/pi/main.py), so the package is
  ``common.*``;
* the server runs ``PYTHONPATH=<repo root>``, so the package is ``src.common.*``.

A relative import is the only form that resolves under both. ``from common.X``
is the shape that took the server down; ``from src.common.X`` is its mirror
image -- it happens to resolve on the Pi too (main.py also inserts the repo
root) but it loads the SAME module a second time under a second name, giving
two module objects with two independent sets of module-level state. Neither
belongs inside the package; both are trivially fixable by writing ``from .X``.

Imports of OTHER tiers (``src.server.*``, ``src.pi.*``) are a different rule and
are deliberately not this test's business.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
COMMON_DIR = REPO_ROOT / "src" / "common"

# The two absolute names under which src/common is importable at runtime.
SELF_PACKAGE_ROOTS = ("common", "src.common")


def _isSelfPackage(moduleName: str) -> str | None:
    """Return the matching self-package root, or None.

    Matches the package itself and anything beneath it, but never a package
    that merely SHARES A PREFIX -- `commonwealth` and `common_utils` are not
    `common`.
    """
    for root in SELF_PACKAGE_ROOTS:
        if moduleName == root or moduleName.startswith(root + "."):
            return root
    return None


def findAbsoluteSelfImports(source: str, filename: str = "<test>") -> list[tuple[int, str]]:
    """Return [(lineno, description)] for absolute self-imports in `source`.

    Walks the whole tree, so deferred imports inside functions and imports under
    `if TYPE_CHECKING:` are caught too -- the P0 import was module-level, but a
    function-local one fails just as hard, and later.
    """
    tree = ast.parse(source, filename=filename)
    violations: list[tuple[int, str]] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            # node.level > 0 is already relative -- `from .X`, `from ..Y`.
            if node.level == 0 and node.module and _isSelfPackage(node.module):
                violations.append(
                    (node.lineno, f"from {node.module} import ...")
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if _isSelfPackage(alias.name):
                    violations.append((node.lineno, f"import {alias.name}"))

    return violations


def _commonSourceFiles() -> list[Path]:
    return sorted(COMMON_DIR.rglob("*.py"))


# ---------------------------------------------------------------------------
# The guard itself
# ---------------------------------------------------------------------------


def test_srcCommon_containsNoAbsoluteSelfImports():
    """
    Given: every .py file under src/common
    When: its real import statements are read via AST
    Then: none imports the package by an absolute name

    A failure here is the US-530 P0 shape. Fix by making the import relative
    (`from .overlay import applyConfigOverlay`), never by adding a sys.path
    entry -- the two tiers disagree on what the package is CALLED, and only a
    relative import is correct under both.
    """
    offenders: list[str] = []
    for path in _commonSourceFiles():
        for lineno, description in findAbsoluteSelfImports(
            path.read_text(encoding="utf-8"), str(path)
        ):
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"{rel}:{lineno}: {description}")

    assert not offenders, (
        "absolute self-import(s) inside src/common -- these resolve on one tier "
        "and raise ModuleNotFoundError on the other (the 2026-08-11 obd-server "
        "P0). Use a relative import instead:\n  " + "\n  ".join(offenders)
    )


def test_guardActuallyScansThepackage():
    """Guard-the-guard: a walk that finds no files passes the test above
    vacuously. Pin that src/common is really being read."""
    files = _commonSourceFiles()
    assert len(files) >= 5, f"expected src/common to hold several modules, found {len(files)}"
    assert any(p.name == "secrets_loader.py" for p in files), (
        "secrets_loader.py -- the file the P0 was in -- is not in the scanned set"
    )


def test_secretsLoader_stillUsesTheRelativeOverlayImport():
    """The exact line from commit d6517429. Pinning the specific regression that
    caused the outage, not just the general class."""
    source = (COMMON_DIR / "config" / "secrets_loader.py").read_text(encoding="utf-8")
    assert "from .overlay import applyConfigOverlay" in source, (
        "secrets_loader.py no longer uses the relative overlay import restored by "
        "the P0 fix (d6517429)"
    )


# ---------------------------------------------------------------------------
# The checker must BITE -- one case per shape it has to catch
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,label",
    [
        ("from common.config.overlay import applyConfigOverlay\n", "the exact US-530 P0 line"),
        ("from common import getLogger\n", "bare package, no submodule"),
        ("import common.config.overlay\n", "plain import"),
        ("import common\n", "plain import of the package itself"),
        ("from src.common.time.helper import utcIsoNow\n", "mirror-image src. prefix"),
        ("import src.common.time.helper\n", "mirror-image plain import"),
        (
            "from common.config.overlay import (\n    applyConfigOverlay,\n    readEffectiveValue,\n)\n",
            "parenthesised multi-name import",
        ),
        (
            "def loadLater():\n    from common.config.overlay import applyConfigOverlay\n    return applyConfigOverlay\n",
            "deferred import inside a function",
        ),
        (
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n    from common.analysis.types import ParameterStatistics\n",
            "import under if TYPE_CHECKING",
        ),
        (
            "try:\n    from common.config.overlay import applyConfigOverlay\nexcept ImportError:\n    applyConfigOverlay = None\n",
            "import inside try/except ImportError",
        ),
    ],
)
def test_checkerFlagsAbsoluteSelfImports(source, label):
    """Every shape an absolute self-import can take must be caught. The
    try/except case matters most: it converts a hard crash into a silent
    None, which is worse than the P0 it imitates."""
    assert findAbsoluteSelfImports(source), f"checker missed {label}: {source!r}"


# ---------------------------------------------------------------------------
# The checker must NOT bite -- the controls that keep it from being deleted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source,label",
    [
        ("from .overlay import applyConfigOverlay\n", "relative sibling import"),
        ("from ..errors.handler import RetryableError\n", "relative parent import"),
        ("from . import config\n", "relative bare import"),
        ("from pathlib import Path\n", "unrelated stdlib import"),
        ("import json\n", "unrelated plain import"),
        ("from src.server.db.models import Base\n", "other tier -- a different rule"),
        ("from commonwealth.tools import thing\n", "package that merely shares a prefix"),
        ("import common_utils\n", "module that merely shares a prefix"),
        ("# from common.config.overlay import applyConfigOverlay\n", "commented-out import"),
        (
            '"""Usage:\n    from common.config.validator import ConfigValidator\n"""\n',
            "docstring usage example",
        ),
        (
            'EXAMPLE = "from common.logging.setup import getLogger"\n',
            "the import shape inside a string literal",
        ),
    ],
)
def test_checkerIgnoresNonViolations(source, label):
    """False positives are how a lint gets deleted. The docstring and
    string-literal cases are not hypothetical -- src/common carries five real
    `Usage:` examples that a textual scan would flag on a clean tree."""
    assert findAbsoluteSelfImports(source) == [], (
        f"checker produced a false positive on {label}: {source!r}"
    )


def test_checkerIgnoresTheRealDocstringExamplesInSrcCommon():
    """The strongest control available: run the checker over the ACTUAL text of
    src/common/__init__.py, whose module docstring lists four absolute imports
    as caller-facing examples. If this ever fails, the checker has regressed to
    a textual scan."""
    initFile = COMMON_DIR / "__init__.py"
    source = initFile.read_text(encoding="utf-8")

    # Premise: the docstring examples really are still there. Without this the
    # test could pass because someone deleted them.
    assert source.count("from common.") >= 4, (
        "src/common/__init__.py no longer carries the Usage: docstring examples "
        "this control depends on -- re-point the control before trusting it"
    )
    assert findAbsoluteSelfImports(source, str(initFile)) == [], (
        "the checker flagged src/common/__init__.py's docstring examples as real imports"
    )


def test_checkerReportsLineNumbersAndStatements():
    """The failure message has to name the file:line and the offending
    statement, or whoever trips this lint cannot act on it."""
    source = "import json\n\n\nfrom common.config.overlay import applyConfigOverlay\n"
    violations = findAbsoluteSelfImports(source)
    assert violations == [(4, "from common.config.overlay import ...")], violations

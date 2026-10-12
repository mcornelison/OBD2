################################################################################
# File Name: test_render_advanced_tier_sample.py
# Purpose/Description: US-721 -- scripts/render_advanced_tier_sample.py RUNS the
#     way its own docstring says to run it. The script was lint-clean (US-706)
#     and still raised on import when invoked as documented: it put src/ on
#     sys.path but not the repo root, and both `src.common.*` (reached through
#     pi.alert.manager) and `tools.pm._paths` resolve only from the repo root.
#     tests/lint/test_make_lint_gate_is_green.py pins the script's import ORDER;
#     this file is the other half -- lint passing is not evidence a script runs.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-09-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-10    | Rex          | Initial -- US-721: run the documented Usage lines.
# ================================================================================
################################################################################

"""The documented Usage commands of render_advanced_tier_sample.py run and render."""

from __future__ import annotations

import ast
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("pygame", reason="the script renders through pygame")

REPO_ROOT = Path(__file__).resolve().parents[2]
RENDER_SCRIPT = REPO_ROOT / "scripts" / "render_advanced_tier_sample.py"
SCRIPT_INVOCATION = "python scripts/render_advanced_tier_sample.py"

# Where the script writes when no --out is given, relative to $FLEET_SHARE.
DEFAULT_OUT_UNDER_SHARE = Path("tuner") / "inbox" / "us165-gate2" / "advanced_tier_sample.png"

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# A render is ~1-2 s on this bench; the ceiling only stops a hung pygame init
# from hanging the suite.
RENDER_TIMEOUT_SECONDS = 120


def documentedUsageCommands() -> list[str]:
    """
    Extract the Usage command lines from the script's module docstring.

    Read from the docstring rather than re-typed here, so the test follows the
    documentation instead of a copy of it that can drift.

    Returns:
        Every docstring line that invokes the script, stripped.

    Raises:
        AssertionError: If the docstring documents no invocation at all.
    """
    docstring = ast.get_docstring(ast.parse(RENDER_SCRIPT.read_text(encoding="utf-8")))
    assert docstring, f"{RENDER_SCRIPT.name} has no module docstring"

    commands = [
        line.strip() for line in docstring.splitlines() if line.strip().startswith(SCRIPT_INVOCATION)
    ]
    assert commands, f"{RENDER_SCRIPT.name}'s docstring documents no Usage command"
    return commands


def defaultDestinationCommands() -> list[str]:
    """
    The documented commands that write to the default destination.

    The ``--out /tmp/screen.png`` line is excluded: on Windows that absolute path
    lands at the drive root, outside any scratch directory a test may write to.
    It shares the import block with the others, so it adds no import coverage.

    Returns:
        The documented commands carrying no ``--out``.
    """
    return [command for command in documentedUsageCommands() if "--out" not in command]


def test_documentedUsageCommands_includeTheBareInvocation() -> None:
    """
    Given: the script's docstring
    When: its Usage lines are extracted
    Then: the bare invocation is among them, and no --out-free line was lost

    Guards the harness: if extraction yielded nothing runnable, the render test
    below would parametrize over an empty list and pass on nothing.
    """
    commands = defaultDestinationCommands()

    assert SCRIPT_INVOCATION in commands, f"bare Usage line not found: {commands}"


@pytest.mark.parametrize("command", defaultDestinationCommands())
def test_documentedUsageCommand_fromRepoRoot_rendersAPng(command: str, tmp_path: Path) -> None:
    """
    Given: a documented Usage command, run from the repo root with no PYTHONPATH
           and $FLEET_SHARE pointed at a scratch directory
    When: it runs exactly as written, with `python` resolved to this interpreter
    Then: it exits 0 and writes a PNG at the script's default destination

    PYTHONPATH is removed on purpose: a developer shell that happens to carry the
    repo root would mask the defect, and the docstring does not ask for one.
    `python <script>` puts the SCRIPT's directory on sys.path, not the cwd, so
    running from the repo root does not put the root on the path by itself.
    """
    argv = shlex.split(command)
    argv[0] = sys.executable

    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    env["FLEET_SHARE"] = str(tmp_path)

    result = subprocess.run(
        argv,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=RENDER_TIMEOUT_SECONDS,
    )

    assert result.returncode == 0, (
        f"the documented command `{command}` does not run.\n"
        f"exit: {result.returncode}\n{result.stdout}{result.stderr}"
    )
    written = tmp_path / DEFAULT_OUT_UNDER_SHARE
    assert written.is_file(), f"`{command}` exited 0 but wrote no file at {written}"
    assert written.read_bytes().startswith(PNG_SIGNATURE), f"{written} is not a PNG"

################################################################################
# File Name: test_blank_cursor_theme.py
# Purpose/Description: US-652-e -- the labwc kiosk session runs on the
#                      eclipse-blank cursor theme: deploy/labwc/environment
#                      names it, deploy/make-blank-cursor-theme.py GENERATES it
#                      at deploy (one transparent Xcursor image, a symlink per
#                      system cursor name, no Inherits=), and deploy-pi.sh ships
#                      and runs the generator before the environment install.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-25
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-25    | Rex (US-652-e) | Initial implementation (Sprint 115).
# ================================================================================
################################################################################

"""Blank cursor theme tests (US-652-e).

Desk-only and Windows-runnable: the generator runs against tmp icons and
source-theme dirs (--icons-dir / --source-theme), deploy-pi.sh runs --dry-run
from an isolated temp copy. No ssh, no Pi, no root, no labwc.
"""

from __future__ import annotations

import ast
import importlib.util
import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_DIR = REPO_ROOT / "deploy"
DEPLOY_SCRIPT = DEPLOY_DIR / "deploy-pi.sh"
GENERATOR = DEPLOY_DIR / "make-blank-cursor-theme.py"
ENVIRONMENT = DEPLOY_DIR / "labwc" / "environment"

THEME = "eclipse-blank"
STEP = "step_install_blank_cursor_theme"
KIOSK_STEP = "step_install_kiosk_session"

# Xcursor(3): file magic and the image chunk type.
XCURSOR_MAGIC = b"Xcur"
XCURSOR_IMAGE_TYPE = 0xFFFD0002

# A fixture "system default theme": a few real Adwaita names, without 'default'
# so the always-present names are proven to be added, not merely copied.
FIXTURE_NAMES = ("left_ptr", "pointer", "text", "watch", "xterm")

needsBash = pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")


def _canSymlink(tmp: Path) -> bool:
    probe = tmp / "symlink-probe"
    try:
        os.symlink("target", probe)
    except (OSError, NotImplementedError):
        return False
    probe.unlink()
    return True


NO_SYMLINK_REASON = (
    "this filesystem cannot create symlinks (Windows without Developer Mode, "
    "WinError 1314): the generator ran with a recording linker instead"
)


def _loadGenerator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("make_blank_cursor_theme", GENERATOR)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sourceTheme(tmp: Path, names: tuple[str, ...] = FIXTURE_NAMES) -> Path:
    theme = tmp / "source" / "Adwaita"
    cursors = theme / "cursors"
    cursors.mkdir(parents=True)
    for name in names:
        (cursors / name).write_bytes(b"not a real cursor")
    return theme


def _recordingLinker(calls: list[tuple[str, str]]):
    """os.symlink stand-in for a filesystem that cannot symlink: a marker file."""

    def link(target: str, path: str) -> None:
        calls.append((target, os.path.basename(path).split(".tmp-")[0]))
        Path(path).write_text(f"-> {target}", encoding="utf-8")

    return link


def _generate(tmp: Path, sourceTheme: Path) -> tuple[Path, bool, list[tuple[str, str]]]:
    """Run the generator for real when symlinks work, else with a recording linker."""
    icons = tmp / "icons"
    icons.mkdir(exist_ok=True)
    gen = _loadGenerator()
    calls: list[tuple[str, str]] = []
    real = _canSymlink(tmp)
    argv = ["--icons-dir", str(icons), "--source-theme", str(sourceTheme)]
    if real:
        rc = gen.main(argv)
    else:
        rc = gen.main(argv, symlink=_recordingLinker(calls))
    assert rc == 0
    return icons / THEME, real, calls


def _snapshot(themeDir: Path) -> dict[str, bytes | str]:
    out: dict[str, bytes | str] = {}
    for p in sorted(themeDir.rglob("*")):
        rel = p.relative_to(themeDir).as_posix()
        if p.is_symlink():
            out[rel] = "link:" + os.readlink(p)
        elif p.is_file():
            out[rel] = p.read_bytes()
    return out


def _imagePixels(data: bytes) -> tuple[int, int, list[int]]:
    magic, headerSize, _version, ntoc = struct.unpack_from("<4sIII", data, 0)
    assert magic == XCURSOR_MAGIC
    assert ntoc == 1
    chunkType, _subtype, position = struct.unpack_from("<III", data, headerSize)
    assert chunkType == XCURSOR_IMAGE_TYPE
    (_hdr, ctype, _sub, _ver, width, height, _xhot, _yhot, _delay) = struct.unpack_from(
        "<IIIIIIIII", data, position
    )
    assert ctype == XCURSOR_IMAGE_TYPE
    pixelStart = position + 36
    pixels = list(struct.unpack_from(f"<{width * height}I", data, pixelStart))
    assert len(data) == pixelStart + 4 * width * height
    return width, height, pixels


# ----------------------------------------------------------------------------
# The environment file
# ----------------------------------------------------------------------------


def test_environmentFile_isExactlyTheOneLine():
    assert ENVIRONMENT.read_bytes() == b"XCURSOR_THEME=eclipse-blank\n"


# ----------------------------------------------------------------------------
# The generator
# ----------------------------------------------------------------------------


def test_generator_importsOnlyTheStdlib():
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "relative import in a stdlib-only script"
            roots.add((node.module or "").split(".")[0])
    roots.discard("__future__")
    assert roots, "the generator imports nothing?"
    notStdlib = sorted(r for r in roots if r not in sys.stdlib_module_names)
    assert not notStdlib, notStdlib


def test_generator_isAGeneratorNotACommittedBinary():
    """No Xcursor file is committed anywhere under deploy/ -- it is written at deploy."""
    for p in DEPLOY_DIR.rglob("*"):
        if p.is_file():
            with p.open("rb") as fh:
                assert fh.read(4) != XCURSOR_MAGIC, f"committed Xcursor binary: {p}"


def test_generatedImage_isXcursor_everyPixelTransparent(tmp_path: Path):
    themeDir, _real, _calls = _generate(tmp_path, _sourceTheme(tmp_path))
    images = [
        p for p in (themeDir / "cursors").iterdir()
        if not p.is_symlink() and p.read_bytes()[:4] == XCURSOR_MAGIC
    ]
    assert len(images) == 1, images
    width, height, pixels = _imagePixels(images[0].read_bytes())
    assert width > 0 and height > 0
    assert all(px >> 24 == 0 for px in pixels), "a pixel has non-zero alpha"


def test_indexTheme_hasNoInherits(tmp_path: Path):
    themeDir, _real, _calls = _generate(tmp_path, _sourceTheme(tmp_path))
    text = (themeDir / "index.theme").read_text(encoding="utf-8")
    assert "[Icon Theme]" in text
    assert "Inherits" not in text


def test_everySourceName_linksToTheOneImage_defaultAndLeftPtrIncluded(tmp_path: Path):
    themeDir, real, calls = _generate(tmp_path, _sourceTheme(tmp_path))
    cursors = themeDir / "cursors"
    expected = set(FIXTURE_NAMES) | {"default", "left_ptr"}
    imageName = _loadGenerator().IMAGE_NAME
    assert (cursors / imageName).read_bytes()[:4] == XCURSOR_MAGIC
    for name in expected:
        assert (cursors / name).exists(), f"no cursor entry for {name}"
    if not real:
        assert {n for _t, n in calls} == expected
        assert {t for t, _n in calls} == {imageName}
        pytest.skip(NO_SYMLINK_REASON)
    for name in expected:
        assert (cursors / name).is_symlink(), f"{name} is not a symlink"
        assert os.readlink(cursors / name) == imageName


def test_secondRun_isByteIdentical(tmp_path: Path):
    source = _sourceTheme(tmp_path)
    themeDir, _real, _calls = _generate(tmp_path, source)
    first = _snapshot(themeDir)
    _generate(tmp_path, source)
    assert _snapshot(themeDir) == first


def test_secondRun_reportsAlreadyCurrent(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    source = _sourceTheme(tmp_path)
    _themeDir, real, _calls = _generate(tmp_path, source)
    first = capsys.readouterr().out
    assert f"1 transparent image, {len(set(FIXTURE_NAMES) | {'default'})} symlinks" in first
    if not real:
        pytest.skip(NO_SYMLINK_REASON)
    _generate(tmp_path, source)
    assert "already current" in capsys.readouterr().out


def test_missingSourceCursors_warnsOnce_themeStillHasDefaultAndLeftPtr(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    missing = tmp_path / "no-such-theme"
    themeDir, _real, _calls = _generate(tmp_path, missing)
    err = capsys.readouterr().err
    warns = [ln for ln in err.splitlines() if ln.startswith("WARN")]
    assert len(warns) == 1, err
    assert "cursors" in warns[0]
    names = {p.name for p in (themeDir / "cursors").iterdir()}
    assert {"default", "left_ptr"} <= names


def test_unwritableIconsDir_exitsNonZeroNamingIt(tmp_path: Path):
    """A FILE where the icons dir should be: nothing can be written under it."""
    blocker = tmp_path / "icons"
    blocker.write_text("not a directory", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(GENERATOR), "--icons-dir", str(blocker),
         "--source-theme", str(_sourceTheme(tmp_path))],
        capture_output=True, text=True, encoding="utf-8", timeout=60,
    )
    assert result.returncode != 0
    assert str(blocker) in result.stderr, result.stderr
    assert result.stderr.startswith("ERROR"), result.stderr


# ----------------------------------------------------------------------------
# deploy-pi.sh: shipping, the step, its order
# ----------------------------------------------------------------------------


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _codeLines(text: str) -> list[str]:
    """Stripped non-blank, non-comment lines (a comment must never satisfy a guard)."""
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _stepBody(name: str) -> str:
    text = _deployText()
    start = text.index(f"{name}() {{")
    return text[start : text.index("\n}\n", start)]


def test_generatorShipsOnBothSyncPaths_byExactName():
    """Modelled on test_deploy_pi.py::test_us885a_deployLibShipsOnBothSyncPaths."""
    lines = _codeLines(_deployText())
    assert lines.count("--include=deploy/make-blank-cursor-theme.py \\") == 1
    assert not [ln for ln in lines if "--include=deploy/*.py" in ln], "never a deploy/*.py glob"
    tarLists = [ln for ln in lines if ln.startswith("./deploy/os-trim.manifest ")]
    assert len(tarLists) == 1, tarLists
    assert " ./deploy )" in tarLists[0], tarLists


def test_themeStep_runsTheGeneratorAsRootWithSystemPython():
    code = "\n".join(_codeLines(_stepBody(STEP)))
    assert "sudo /usr/bin/python3" in code
    assert "deploy/make-blank-cursor-theme.py" in code
    assert "|| true" not in code, "a failed generator must stop the deploy"


def test_themeStep_isModeIndependent():
    """Inert unless the eclipse labwc session names it: no mode file read here."""
    code = "\n".join(_codeLines(_stepBody(STEP)))
    assert "display-mode" not in code
    assert "kiosk_mode_resolver" not in code


def test_themeStep_isWiredBeforeTheEnvironmentInstall():
    """set -e: a failed generator halts the deploy before the environment lands."""
    text = _deployText()
    call = f"\n{STEP}\n"
    assert text.count(call) == 1, f"{STEP} must be called exactly once"
    assert text.index(call) < text.rindex(f"\n{KIOSK_STEP}\n")


def test_kioskSessionStep_installsTheEnvironmentFile():
    code = "\n".join(_codeLines(_stepBody(KIOSK_STEP)))
    assert "for f in rc.xml autostart environment; do" in code


def _isolatedDeploy(tmp_path: Path, *, withEnvironment: bool = True) -> subprocess.CompletedProcess:
    deployDir = tmp_path / "deploy"
    deployDir.mkdir()
    for name in ("deploy-pi.sh", "addresses.sh", "os-trim.manifest"):
        shutil.copy(DEPLOY_DIR / name, deployDir / name)
    shutil.copytree(DEPLOY_DIR / "labwc", deployDir / "labwc")
    if not withEnvironment:
        (deployDir / "labwc" / "environment").unlink()
    (deployDir / "deploy.conf").write_text(
        "PI_HOST=192.0.2.1\nPI_USER=nobody\nPI_PATH=/tmp/will-never-exist\nPI_PORT=22\n",
        encoding="utf-8",
        newline="\n",
    )
    return subprocess.run(
        ["bash", deployDir.joinpath("deploy-pi.sh").as_posix(), "--dry-run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        timeout=120,
    )


@needsBash
def test_deployDryRun_printsTheGeneratorRunThenTheEnvironmentInstall(tmp_path: Path):
    result = _isolatedDeploy(tmp_path)
    out = result.stdout
    assert result.returncode == 0, out[-2000:]
    lines = out.splitlines()
    gen = [i for i, ln in enumerate(lines)
           if ln.startswith("DRY-RUN") and "make-blank-cursor-theme.py" in ln]
    env = [i for i, ln in enumerate(lines)
           if ln.startswith("DRY-RUN") and "environment" in ln and "/etc/eclipse/labwc" in ln]
    assert len(gen) == 1, out[-3000:]
    assert "sudo /usr/bin/python3" in lines[gen[0]]
    assert env, out[-3000:]
    assert gen[0] < env[0]


@needsBash
def test_deployDryRun_missingEnvironment_failsLoudNamingThePath(tmp_path: Path):
    result = _isolatedDeploy(tmp_path, withEnvironment=False)
    out = result.stdout
    assert result.returncode == 12, out[-2000:]
    errors = [ln for ln in out.splitlines() if ln.startswith("ERROR: labwc config not found: ")]
    assert errors, out[-2000:]
    assert f"{tmp_path.name}/deploy/labwc/environment" in errors[0]

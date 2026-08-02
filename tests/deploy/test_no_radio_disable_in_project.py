################################################################################
# File Name: test_no_radio_disable_in_project.py
# Purpose/Description: US-513 prevention guard (BL-025 origin RCA). The RCA's
#                      central finding is a NEGATIVE one: no project code or
#                      deploy path can produce the persisted Bluetooth soft-block
#                      that killed capture from ~2026-07-03. Every radio verb the
#                      repo ships is restorative -- `bluetoothctl power on`,
#                      `rfkill unblock all`, `rfcomm bind/release`. Nothing
#                      blocks, powers down, or masks a radio.
#
#                      That finding exonerated the project, but it was a
#                      POINT-IN-TIME audit, and a point-in-time audit decays the
#                      moment someone adds a "just reset the adapter" line to a
#                      recovery path. This file converts it into a standing
#                      invariant so the exoneration stays true by construction.
#
#                      Scope note: US-512 already guards this at RUNTIME, but
#                      only for two helpers (resetRfcommBinding / ensureTrusted)
#                      and only for commands they actually emit. A new script, a
#                      new deploy step, or a new orchestrator path is invisible
#                      to that check. This one is repo-wide and static.
#
#                      Offline-safe: pure file reads. No SSH, no network, no root.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-08-02
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-02    | Rex          | Initial implementation (US-513 prevention guard)
# ================================================================================
################################################################################

"""No project-shipped file may disable a radio.

The 07-03 outage cost roughly four weeks of capture (including a wasted IRL
drive on 07-27) because a *soft-block* is invisible from inside the application:
every layer above it honestly reported "no adapter" while the fault sat one
level below the whole stack. The cheapest possible insurance against a repeat is
to never let the repo acquire the ability to cause one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

#: Directories that ship to a machine. `tests/` is deliberately excluded: test
#: files assert ON these strings (US-512's guards literally check
#: `"power off" not in line`), so scanning them would flag the very tests that
#: enforce the rule.
SCANNED_DIRS = ("src", "scripts", "deploy")

SCANNED_SUFFIXES = (".py", ".sh", ".service")

#: An explicit, greppable opt-out. Per the project's escape-hatch rule, a named
#: exemption on the offending line beats a quietly-loosened pattern -- if a real
#: need ever arrives, it should be visible in a grep, not buried in a regex.
EXEMPTION_MARKER = "radio-guard-exempt"

#: Separator between command tokens. Deliberately NOT plain ``\s+``: the Pi code
#: shells out through argv LISTS (`subprocess.run(["rfkill", "block", ...])`, the
#: form `bluetooth_helper` uses), so a whitespace-only separator would see every
#: shell example and miss every Python one -- the guard's own self-test caught
#: exactly that on the first run.
_SEP = r"[\"',\s]+"

#: (name, pattern, why-this-is-dangerous). Each pattern targets an INVOCATION,
#: not prose, because the same phrases appear constantly in the comments and
#: docstrings that explain this very outage.
FORBIDDEN_RADIO_COMMANDS: tuple[tuple[str, str, str], ...] = (
    (
        "rfkill block",
        rf"rfkill{_SEP}\bblock\b",
        "sets the soft-block that systemd-rfkill then PERSISTS across reboots -- "
        "the exact BL-025 mechanism",
    ),
    (
        "nmcli radio off",
        rf"nmcli{_SEP}radio(?:{_SEP}(?:wifi|all|wwan))?{_SEP}\boff\b",
        "NetworkManager persists radio-off in its own state file; on 2026-07-19 "
        "this stranded the Pi off-network across four reboots",
    ),
    (
        "hciconfig <dev> down",
        rf"hciconfig{_SEP}[\w:.-]+{_SEP}\bdown\b",
        "brings the HCI device down out from under bluetoothd, with no layer "
        "above able to report why the adapter vanished",
    ),
    (
        "systemctl stop/disable/mask bluetooth",
        rf"systemctl{_SEP}(?:stop|disable|mask){_SEP}bluetooth",
        "disables the stack the capture path depends on; `mask` in particular "
        "survives reboots and resists `enable`",
    ),
    (
        "bluetoothctl 'power off'",
        r"['\"]power\s+off['\"]|['\"]power['\"]\s*,\s*['\"]off['\"]",
        "powers the adapter down; the pairing driver must only ever send "
        "'power on' (scripts/pair_obdlink_driver.py)",
    ),
)


def _scannableFiles() -> list[Path]:
    """Every shipped source file under the scanned directories."""
    files: list[Path] = []
    for directory in SCANNED_DIRS:
        root = REPO_ROOT / directory
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
                continue
            if "__pycache__" in path.parts:
                continue
            files.append(path)
    return files


def _strippedLines(text: str) -> list[tuple[int, str]]:
    """Drop whole-line ``#`` comments, keeping 1-based line numbers.

    US-501's lesson, learned the hard way on the version-chip guard: a scanner
    that reads raw file text trips on the explanatory comment describing the
    thing it forbids. Every match this guard would otherwise report in
    `bluetooth_helper.py` / `obd_connection.py` is such a comment.
    """
    kept: list[tuple[int, str]] = []
    for lineNo, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("#"):
            continue
        kept.append((lineNo, line))
    return kept


def findRadioDisableViolations(text: str) -> list[tuple[int, str, str]]:
    """Return ``(lineNo, commandName, line)`` for each forbidden radio command.

    Args:
        text: Full source text of a shipped file.

    Returns:
        One entry per violating line; empty when the text is clean.
    """
    violations: list[tuple[int, str, str]] = []
    for lineNo, line in _strippedLines(text):
        if EXEMPTION_MARKER in line:
            continue
        for name, pattern, _why in FORBIDDEN_RADIO_COMMANDS:
            if re.search(pattern, line, re.IGNORECASE):
                violations.append((lineNo, name, line.strip()))
    return violations


# ----------------------------------------------------------------------------
# The invariant.
# ----------------------------------------------------------------------------


def test_noShippedFileDisablesARadio():
    """US-513: the repo must remain incapable of causing a BL-025 soft-block.

    This is the assertion that keeps the RCA's "project exonerated" conclusion
    true tomorrow. A radio the project turns off is a radio that can be saved
    OFF at shutdown and restored OFF at boot -- and the resulting outage is
    invisible from inside the application, which is what let 07-03 run for four
    weeks before anyone looked below the stack.
    """
    offenders: list[str] = []
    for path in _scannableFiles():
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineNo, name, line in findRadioDisableViolations(text):
            rel = path.relative_to(REPO_ROOT).as_posix()
            offenders.append(f"  {rel}:{lineNo}  [{name}]  {line}")

    assert not offenders, (
        "shipped code disables a radio -- this is the BL-025 (07-03 dead-capture) "
        "class of defect:\n"
        + "\n".join(offenders)
        + "\n\nEvery radio verb this project ships must be RESTORATIVE "
        "(`power on`, `rfkill unblock`, `rfcomm bind/release`). If a disable is "
        f"genuinely required, mark the line `{EXEMPTION_MARKER}` and say why."
    )


# ----------------------------------------------------------------------------
# ...and that the guard actually guards. A rotted regex passes forever.
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sample",
    [
        "    subprocess.run(['rfkill', 'block', 'bluetooth'])",
        "sudo rfkill block bluetooth",
        "sudo nmcli radio wifi off",
        "nmcli radio all off",
        "sudo hciconfig hci0 down",
        "sudo systemctl stop bluetooth",
        "sudo systemctl mask bluetooth.service",
        '    _send(child, "power off", promptTimeout)',
        "    _send(child, 'power off')",
        '    runner(["nmcli", "radio", "wifi", "off"])',
        '    runner(["hciconfig", "hci0", "down"])',
        '    runner(["systemctl", "stop", "bluetooth"])',
        '    child.sendline("power", "off")',
    ],
)
def test_guardDetectsEachForbiddenForm(sample: str):
    """Feed the scanner a known-bad line and prove it trips.

    Without this, a typo'd or over-narrowed pattern would leave
    `test_noShippedFileDisablesARadio` passing on an empty search forever --
    a guard that reports "clean" because it can no longer see anything.
    """
    assert findRadioDisableViolations(sample), (
        f"the guard failed to flag a known radio-disable form: {sample!r}"
    )


@pytest.mark.parametrize(
    "sample",
    [
        "        sudo rfkill unblock all",
        "ExecStart=/usr/sbin/rfkill unblock all",
        '    runner(["rfkill", "unblock", "all"])',
        "    bluetoothctl power on",
        '    _send(child, "power on", promptTimeout)',
        "sudo nmcli radio wifi on",
        "    sudo rfcomm release 0",
        "    sudo rfcomm bind 0 $MAC 1",
    ],
)
def test_guardPermitsEveryRestorativeRadioCommand(sample: str):
    """The repo's real radio verbs must all survive the guard.

    `rfkill unblock` is the sharp one: a naive `block` pattern matches the tail
    of `unblock` and would condemn `deploy-pi.sh` and the unblock unit itself --
    i.e. the guard would flag the FIX for the outage it exists to prevent.
    """
    assert findRadioDisableViolations(sample) == [], (
        f"the guard wrongly flagged a restorative command: {sample!r}"
    )


def test_guardIgnoresCommentaryAboutTheOutage():
    """The codebase is full of prose explaining these exact commands.

    `bluetooth_helper.py` and `obd_connection.py` both document why they refuse
    to run `bluetoothctl power off`. Flagging those would make the guard
    unusable and it would be deleted -- so the comment strip is load-bearing.
    """
    commentary = (
        "# The 07-03 killer was a persisted block; never run rfkill block here.\n"
        "#   hciconfig hci0 down / bluetoothctl power off are both forbidden.\n"
        "    # sudo nmcli radio wifi off  <- stranded the Pi on 07-19\n"
    )
    assert findRadioDisableViolations(commentary) == []


def test_guardHonoursAnExplicitExemption():
    """A named exemption is greppable; a loosened regex is not."""
    exempted = f"    runCommand('rfkill block bluetooth')  # {EXEMPTION_MARKER}: bench teardown only\n"
    assert findRadioDisableViolations(exempted) == []


def test_guardActuallyScansRealFiles():
    """A scanner pointed at nothing passes trivially (the US-494 shape)."""
    files = _scannableFiles()
    assert len(files) > 50, (
        f"the radio guard only found {len(files)} files to scan; SCANNED_DIRS is "
        "probably wrong, which would make the invariant vacuous"
    )
    names = {p.name for p in files}
    assert "bluetooth_helper.py" in names, (
        "the guard is not reaching src/pi/obdii/bluetooth_helper.py -- the single "
        "most likely file to acquire a radio-disable call"
    )

################################################################################
# File Name: test_rfkill_unblock_install.py
# Purpose/Description: BL-025 P0 hotfix gate (V0.29.22, CIO-directed via Atlas
#                      2026-07-31). `systemd-rfkill` restores a SAVED Bluetooth
#                      soft-block (/var/lib/systemd/rfkill/*:bluetooth = [1]) on
#                      EVERY boot, so BT comes up blocked, eclipse-obd cannot
#                      reach the OBDLink LX, and the Pi captures zero rows --
#                      the "dead since ~07-03" root cause. Atlas fixed it LIVE on
#                      the Pi with a boot-unblock oneshot; these tests pin the
#                      REPO-MANAGED half, so a `deploy-pi.sh --init` or a reflash
#                      re-installs it instead of silently going dark again.
#
#                      Three things are asserted, and the third is the one that
#                      has bitten this project repeatedly (US-494): the unit's
#                      CONTENT, the install step's SHAPE, and that the step is
#                      actually CALLED on a routine deploy -- proven by running
#                      the shipped `deploy-pi.sh --dry-run` and reading its own
#                      output, not by grepping for a function definition. A
#                      correct routine nobody calls is worth nothing.
#
#                      Offline-safe: static file reads, `bash -n`, and the
#                      script's own --dry-run (no SSH, no network, no root).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-07-31
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-31    | Rex          | Initial implementation (BL-025 rfkill deploy-bake)
# ================================================================================
################################################################################

"""Repo-managed-ness of the boot-time radio unblock (BL-025 P0 hotfix).

The live fix on the Pi is not the deliverable -- surviving a reflash is. Every
assertion here is about what the REPO ships, because that is the only copy a
`--init` deploy can restore.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from pi.ops import unit_manifest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SERVICE_FILE = REPO_ROOT / "deploy" / "eclipse-rfkill-unblock.service"
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"

UNIT_NAME = "eclipse-rfkill-unblock.service"
STEP_NAME = "step_install_rfkill_unblock"


def _bashAvailable() -> bool:
    """True if bash is on PATH (Windows git-bash, MSYS, Linux, mac)."""
    return shutil.which("bash") is not None


def _serviceText() -> str:
    assert SERVICE_FILE.is_file(), (
        f"{SERVICE_FILE.name} is missing from deploy/. The unblock exists only as "
        "a hand-installed unit on the Pi, so a reflash or `--init` loses it and "
        "Bluetooth goes dark again (BL-025)."
    )
    return SERVICE_FILE.read_text(encoding="utf-8")


def _extractDeployFunctionBody(funcName: str) -> str:
    """Return a ``name() {`` bash function body, sliced to the next top-level one."""
    scriptText = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    startMatch = re.search(rf"^{re.escape(funcName)}\(\) \{{", scriptText, re.MULTILINE)
    if not startMatch:
        return ""
    body = scriptText[startMatch.end():]
    endMatch = re.search(r"^[a-z_]+\(\) \{", body, re.MULTILINE)
    if endMatch:
        body = body[: endMatch.start()]
    return body


# ----------------------------------------------------------------------------
# The unit file itself -- content is the contract, since deploy ships it verbatim.
# ----------------------------------------------------------------------------


def test_rfkillUnblockUnit_existsInTheRepo():
    """The unit must be a repo artifact, not a Pi-local hand-install."""
    assert SERVICE_FILE.is_file()


def test_rfkillUnblockUnit_carriesTheProjectFileHeader():
    """Sibling deploy/*.service files open with the standards.md comment block."""
    text = _serviceText()
    assert text.lstrip().startswith("#"), (
        f"{UNIT_NAME} does not open with the project file-header comment block "
        "(specs/standards.md); every sibling deploy/*.service carries one."
    )
    assert "[Unit]" in text, f"{UNIT_NAME} has no [Unit] section"


def test_rfkillUnblockUnit_unblocksEveryRadioWithAnAbsolutePath():
    """`ExecStart=/usr/sbin/rfkill unblock all`.

    Absolute, because systemd runs units with a minimal PATH and `rfkill` lives
    in /usr/sbin -- a bare `rfkill` is the same class of silent no-op that made
    `i2cdetect` look like a broken bus on this Pi. `all` (not `bluetooth`)
    because the saved-block mechanism is per-radio and WiFi can acquire one the
    same way; unblocking one radio and leaving the sibling blocked would repeat
    this outage on the other interface.
    """
    text = _serviceText()
    assert re.search(r"^ExecStart=/usr/sbin/rfkill\s+unblock\s+all\s*$", text, re.MULTILINE), (
        f"{UNIT_NAME} does not ExecStart=/usr/sbin/rfkill unblock all"
    )


def test_rfkillUnblockUnit_isAOneshotThatStaysActive():
    """Type=oneshot + RemainAfterExit=yes -- the unit runs once and reads active.

    Without RemainAfterExit the unit falls back to `inactive (dead)` the instant
    it finishes, and `systemctl is-active` -- the operator's only check that the
    unblock ran this boot -- reports a healthy unit as failed-looking.
    """
    text = _serviceText()
    assert re.search(r"^Type=oneshot\s*$", text, re.MULTILINE), f"{UNIT_NAME} is not Type=oneshot"
    assert re.search(r"^RemainAfterExit=yes\s*$", text, re.MULTILINE), (
        f"{UNIT_NAME} is missing RemainAfterExit=yes; `systemctl is-active` would "
        "report `inactive` after a perfectly successful unblock"
    )


def test_rfkillUnblockUnit_runsAfterTheServiceThatRestoresTheStaleBlock():
    """`After=systemd-rfkill.service` -- the whole fix is an ORDERING fact.

    systemd-rfkill is what replays the saved `[1]` soft-block at boot. Unblocking
    BEFORE it runs means it simply re-blocks the radio afterwards and the Pi is
    dark again with a green-looking unit. This ordering IS the fix; everything
    else in the file is plumbing.
    """
    text = _serviceText()
    afterTokens: set[str] = set()
    for line in text.splitlines():
        match = re.match(r"^After=(.+)$", line)
        if match:
            afterTokens.update(match.group(1).split())
    assert "systemd-rfkill.service" in afterTokens, (
        f"{UNIT_NAME} does not order itself After=systemd-rfkill.service -- the "
        "saved soft-block would be restored AFTER the unblock and BT stays dark "
        "(BL-025 root cause)"
    )
    assert "bluetooth.service" in afterTokens, (
        f"{UNIT_NAME} does not order itself After=bluetooth.service (Atlas's "
        "verified-live unit does)"
    )


def _unitOrderingTokens(unitFileName: str, directive: str) -> set[str]:
    """Collect every token from a repeated ``After=``/``Before=`` directive.

    systemd merges repeated ordering directives rather than letting the last one
    win, so the honest read is the UNION of all of them -- reading only the first
    (or last) line would report a real ordering as absent.
    """
    path = REPO_ROOT / "deploy" / unitFileName
    assert path.is_file(), f"{unitFileName} is missing from deploy/"
    tokens: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(rf"^{directive}=(.+)$", line)
        if match:
            tokens.update(match.group(1).split())
    return tokens


#: Units that cannot do their job against a soft-blocked adapter. rfcomm-bind
#: binds /dev/rfcomm0 to the dongle; eclipse-obd opens it and polls the ECU.
RADIO_CONSUMER_UNITS = ("rfcomm-bind.service", "eclipse-obd.service")


@pytest.mark.parametrize("consumer", RADIO_CONSUMER_UNITS)
def test_rfkillUnblockUnit_ordersItselfBeforeTheUnitsThatNeedTheRadio(consumer: str):
    """US-513: the safety net must be ordered before the units it protects.

    `After=systemd-rfkill.service` fixes the PRODUCER half -- the unblock lands
    after the stale `[1]` is replayed. Nothing ordered the CONSUMER half: neither
    rfcomm-bind nor eclipse-obd declares any relationship to this unit, so systemd
    is free to start all three concurrently, and on the Pi (boot of 2026-07-31)
    rfcomm-bind and eclipse-rfkill-unblock both entered at 20:25:59 -- the same
    second. That race is invisible while no block is saved and silently decides
    capture on the one boot where a block IS saved: bind against a dark adapter,
    then a green `is-active` on both units.

    `Before=` (not `Wants=`) is deliberate: this orders the consumers if they are
    already part of the boot transaction, and must never PULL them in.
    """
    before = _unitOrderingTokens(UNIT_NAME, "Before")
    assert consumer in before, (
        f"{UNIT_NAME} does not declare Before={consumer}. The radio unblock can "
        f"therefore run concurrently with (or after) {consumer}, which needs an "
        "unblocked adapter -- the BL-025 failure with a green-looking unit."
    )


def test_radioConsumers_declareNoConflictingOrderBeforeTheUnblock():
    """Guard the other direction: no consumer may order itself BEFORE the unblock.

    A `Before=eclipse-rfkill-unblock.service` on a consumer would either fight the
    directive above or form an ordering cycle, which systemd resolves by silently
    DROPPING one edge -- turning the fix back into the race it replaced, with no
    error anyone would see.
    """
    for consumer in RADIO_CONSUMER_UNITS:
        assert UNIT_NAME not in _unitOrderingTokens(consumer, "Before"), (
            f"{consumer} declares Before={UNIT_NAME}, contradicting the unblock's "
            "own ordering and risking a silently-dropped ordering edge"
        )


def test_rfkillUnblockUnit_isWantedByMultiUserTarget():
    """[Install] WantedBy=multi-user.target -- `enable` has to have a target."""
    text = _serviceText()
    assert re.search(r"^WantedBy=multi-user\.target\s*$", text, re.MULTILINE), (
        f"{UNIT_NAME} has no WantedBy=multi-user.target; `systemctl enable` would "
        "have nothing to link and the unit would never run at boot"
    )


# ----------------------------------------------------------------------------
# The install step -- sync-if-changed, mirroring its siblings.
# ----------------------------------------------------------------------------


def test_deployPiSh_hasTheRfkillUnblockInstallStep():
    assert _extractDeployFunctionBody(STEP_NAME), (
        f"{STEP_NAME} not found in deploy-pi.sh -- the unit is in the repo but "
        "no deploy installs it"
    )


def test_deployPiSh_installsTheUnitVerbatimNotFromAHeredoc():
    """`install -m 644` from the synced deploy/ source, guarded by `cmp -s`.

    Verbatim install is what makes deploy/eclipse-rfkill-unblock.service the
    single point of change: editing the repo file is enough. A heredoc would
    fork the content and the repo copy would drift into decoration.
    """
    body = _extractDeployFunctionBody(STEP_NAME)
    assert UNIT_NAME in body, f"{STEP_NAME} never references {UNIT_NAME}"
    assert "install -m 644" in body, (
        f"{STEP_NAME} does not `install -m 644` the unit file verbatim"
    )
    assert "cmp -s" in body, (
        f"{STEP_NAME} has no `cmp -s` guard -- every deploy would rewrite the "
        "unit and daemon-reload for nothing (the sibling steps all guard)"
    )
    assert "<<" not in body, (
        f"{STEP_NAME} appears to template the unit via a heredoc; the content "
        "must come from deploy/{UNIT_NAME} so the repo file is the SSOT"
    )


def test_deployPiSh_reloadsAndEnablesTheUnit():
    """daemon-reload on change + `enable --now` (idempotent, self-healing)."""
    body = _extractDeployFunctionBody(STEP_NAME)
    assert "daemon-reload" in body, f"{STEP_NAME} never daemon-reloads after installing"
    assert re.search(r"systemctl enable --now\s+eclipse-rfkill-unblock", body), (
        f"{STEP_NAME} does not `systemctl enable --now` the unit; `--now` is what "
        "makes the radios unblocked on the deploy itself rather than one reboot later"
    )


def test_deployPiSh_neutralizesTheStaleSavedBlock():
    """Belt-and-suspenders: clear the SAVED block, not just the live one.

    The unit handles every boot from here on, but the very first deploy still
    has a stale `[1]` sitting in /var/lib/systemd/rfkill. Zeroing it closes the
    one-boot window between deploying and rebooting -- and it is the actual
    artifact the CIO would otherwise have to remember to delete by hand.
    """
    body = _extractDeployFunctionBody(STEP_NAME)
    assert "rfkill unblock all" in body, (
        f"{STEP_NAME} does not unblock the live radios during the deploy"
    )
    assert "/var/lib/systemd/rfkill" in body, (
        f"{STEP_NAME} does not neutralize the SAVED soft-block under "
        "/var/lib/systemd/rfkill -- the stale [1] survives until the next boot"
    )


def test_deployPiSh_rfkillStepIsPreviewableUnderDryRun():
    """The step must short-circuit before `remote` so --dry-run stays offline."""
    body = _extractDeployFunctionBody(STEP_NAME)
    assert re.search(r"if \$DRY_RUN; then", body), (
        f"{STEP_NAME} has no DRY_RUN branch; the offline smoke test would try to SSH"
    )


# ----------------------------------------------------------------------------
# ... and that it is actually CALLED. US-494's lesson: a correct routine nobody
# invokes is worth nothing, and no test of the routine can tell you it is unwired.
# ----------------------------------------------------------------------------


def test_deployPiSh_callsTheStepOnEveryDeployNotJustInit():
    """The call site must be top-level, not inside the `if $INIT` block.

    A radio soft-block can be re-saved at any shutdown, so the unblock has to be
    re-asserted by ROUTINE deploys -- same posture as step_reassert_obd_mac and
    step_enforce_eeprom_power_off_on_halt. Gating it behind --init would mean the
    only Pi that gets the fix is one being rebuilt from scratch.
    """
    scriptText = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    calls = re.findall(rf"^(\s*){re.escape(STEP_NAME)}\s*$", scriptText, re.MULTILINE)
    assert calls, f"{STEP_NAME} is defined but never called in the main deploy sequence"
    assert any(indent == "" for indent in calls), (
        f"every call to {STEP_NAME} is indented, i.e. nested inside a conditional "
        "block (`if $INIT`). It must run on every deploy."
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_dryRunActuallyRunsTheRfkillStep():
    """Run the SHIPPED script and read its own output -- the wiring proof.

    This is the assertion that would have caught US-494: it does not ask whether
    the function exists or whether some line mentions it, it asks whether a real
    routine deploy reaches it.
    """
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, f"dry-run failed: {result.stderr}"
    assert "rfkill" in result.stdout.lower(), (
        "a routine `deploy-pi.sh --dry-run` never reaches the rfkill-unblock step; "
        f"the fix would not ship. Output was:\n{result.stdout[-2000:]}"
    )
    assert UNIT_NAME in result.stdout, (
        f"the dry-run does not preview installing {UNIT_NAME}"
    )


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_bashSyntaxValid():
    """`bash -n deploy-pi.sh` must parse cleanly after the edit."""
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"bash -n failed (exit={result.returncode}):\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


# ----------------------------------------------------------------------------
# Manifest registration -- US-492's SSOT must know about a unit deploy installs.
# ----------------------------------------------------------------------------


def test_unitManifest_knowsTheRfkillUnblockUnit():
    """A deploy-installed unit missing from the manifest is exactly the drift
    US-492 built the manifest to prevent -- and this is the unit an operator
    debugging dead capture most needs `obdctl status` to show.
    """
    assert UNIT_NAME in unit_manifest.CANONICAL_UNITS, (
        f"{UNIT_NAME} is installed by deploy but absent from UNIT_MANIFEST; "
        "obdctl would never report the radio unblock's state"
    )


def test_unitManifest_ordersTheUnblockBeforeTheRfcommBind():
    """Start order is a dependency claim: unblock the radio, THEN bind rfcomm.

    Binding /dev/rfcomm0 while the adapter is soft-blocked is precisely the
    failure this hotfix exists to stop.
    """
    order = list(unit_manifest.START_ORDER)
    assert order.index(UNIT_NAME) < order.index("rfcomm-bind.service"), (
        "the manifest starts rfcomm-bind before the radio unblock"
    )


@pytest.mark.parametrize("consumer", RADIO_CONSUMER_UNITS)
def test_unitManifestOrdering_isBackedByARealSystemdDirective(consumer: str):
    """US-513 anti-drift: the manifest may not claim an order systemd does not implement.

    unit_manifest's own header states its ordering is "grounded in the units' own
    declarations, NOT invented" -- and lists exactly the declarations it relies on
    (`rfcomm-bind: Requires/After=bluetooth.service`, `eclipse-obd: After=network.
    target bluetooth.target`). NONE of those mention the unblock unit, so the
    manifest's unblock-first claim was the one ordering in the list with nothing
    behind it, and `test_unitManifest_ordersTheUnblockBeforeTheRfcommBind` passed
    on the strength of a hand-ordered Python tuple while the real boot raced.

    That is this project's recurring two-correct-halves shape (US-494/499/502/503/
    505): the manifest was right, the units were internally consistent, and nothing
    carried the claim across. `obdctl` orders its OWN sequential start/stop by this
    tuple, so the manifest is not decorative -- but it cannot order BOOT, and boot
    is when a restored soft-block actually bites. This test makes the tuple's claim
    falsifiable against the units it describes.
    """
    manifestOrder = list(unit_manifest.START_ORDER)
    assert manifestOrder.index(UNIT_NAME) < manifestOrder.index(consumer), (
        f"the manifest does not start {UNIT_NAME} before {consumer}"
    )

    unblockDeclaresBefore = consumer in _unitOrderingTokens(UNIT_NAME, "Before")
    consumerDeclaresAfter = UNIT_NAME in _unitOrderingTokens(consumer, "After")
    assert unblockDeclaresBefore or consumerDeclaresAfter, (
        f"unit_manifest.START_ORDER claims {UNIT_NAME} starts before {consumer}, "
        f"but NEITHER unit declares it: {UNIT_NAME} has no Before={consumer} and "
        f"{consumer} has no After={UNIT_NAME}. At boot systemd orders by the unit "
        "files alone, so the manifest's claim is unenforced and the two can race."
    )

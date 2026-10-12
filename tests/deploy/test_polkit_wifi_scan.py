################################################################################
# File Name: test_polkit_wifi_scan.py
# Purpose/Description: US-776-j2 -- the 52- polkit rule granting the powerwatch
#                      user (mcornelison) ONLY org.freedesktop.NetworkManager.
#                      wifi.scan, and its deploy-pi.sh install step.
#
#                      Without the grant the US-776-j1 key-off sweep
#                      (`nmcli dev wifi list --rescan yes`) is refused with
#                      "not authorized" and reads FAILED -> UNKNOWN on every
#                      key-off. The CIO approved the scan action and nothing
#                      else, so the load-bearing assertion is that exactly ONE
#                      action id appears anywhere in the rule file.
#
#                      Offline-safe: static file reads, `bash -n`, and the
#                      shipped script's own --dry-run (no SSH, no root).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-10-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-11    | Rex          | Initial implementation (US-776-j2)
# ================================================================================
################################################################################

"""The 52- WiFi-scan polkit rule and its deploy install step (US-776-j2)."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEPLOY_SCRIPT = REPO_ROOT / "deploy" / "deploy-pi.sh"
RULE_NAME = "52-eclipse-wifi-scan.rules"
RULE_FILE = REPO_ROOT / "deploy" / "polkit-rules" / RULE_NAME
SOURCE_PATH = f"deploy/polkit-rules/{RULE_NAME}"
TARGET_PATH = f"/etc/polkit-1/rules.d/{RULE_NAME}"
STEP_NAME = "step_install_polkit_wifi_scan"

SCAN_ACTION = "org.freedesktop.NetworkManager.wifi.scan"
POWERWATCH_USER = "mcornelison"

# Any polkit action id: a reverse-DNS name rooted at a vendor prefix.
_ACTION_ID = re.compile(r"\b(?:org|com|net|io)\.[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]+)+")


def _ruleText() -> str:
    return RULE_FILE.read_text(encoding="utf-8")


def _deployText() -> str:
    return DEPLOY_SCRIPT.read_text(encoding="utf-8")


def _stepBody(text: str, stepName: str) -> str:
    """Return the body of `<stepName>() { ... }` so a check stays scoped to it."""
    marker = f"{stepName}() {{"
    start = text.index(marker)
    end = text.index("\n}\n", start)
    return text[start:end]


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


# ---------------------------------------------------------------------------
# The rule file: the scan action, for the powerwatch user, and nothing else.
# ---------------------------------------------------------------------------


def test_wifiScanRule_namesExactlyOneActionId_theScanAction():
    """
    Given: the CIO approved org.freedesktop.NetworkManager.wifi.scan ONLY
    When: every action id anywhere in the rule file (code AND comments) is listed
    Then: there is exactly one distinct id and it is the scan action. A second id
        -- even one only in a comment -- is a widened grant to review, not ship.
    """
    found = set(_ACTION_ID.findall(_ruleText()))

    assert found == {SCAN_ACTION}, f"expected only {SCAN_ACTION}, found {sorted(found)}"


def test_wifiScanRule_grantsTheScanToThePowerwatchUserOnly():
    """
    Given: powerwatch runs as mcornelison
    When: the rule's single decision is read
    Then: it returns YES only when the action is the scan AND the subject is that
        user, in one condition
    """
    rule = _ruleText()

    assert rule.count("polkit.addRule(") == 1
    assert f'action.id == "{SCAN_ACTION}"' in rule
    assert f'subject.user == "{POWERWATCH_USER}"' in rule
    assert rule.count("polkit.Result.YES") == 1


def test_wifiScanRule_returnsNoDecisionForAnyOtherAction():
    """
    Given: 'returns no decision for any other action'
    When: the rule is read
    Then: it never returns NO / AUTH_* (that would override other rules for the
        same user) -- anything else falls through to the PolicyKit default
    """
    rule = _ruleText()

    for verdict in ("polkit.Result.NO", "AUTH_ADMIN", "AUTH_SELF", "NOT_HANDLED"):
        assert verdict not in rule, f"{verdict} would decide actions this rule must not touch"


# ---------------------------------------------------------------------------
# The install step: mirrors step_install_polkit_poweroff.
# ---------------------------------------------------------------------------


def test_deployPi_definesAndCallsTheWifiScanStep():
    """
    Given: a defined step nobody calls installs nothing
    When: deploy-pi.sh is read
    Then: the step is defined and called un-indented in the main sequence
    """
    text = _deployText()

    assert f"{STEP_NAME}()" in text
    calls = [ln for ln in text.splitlines() if ln == STEP_NAME]
    assert calls, f"{STEP_NAME} is defined but never called on a routine deploy"


def test_wifiScanStep_installsTheRuleIdempotentlyLikeThePoweroffStep():
    """
    Given: step_install_polkit_poweroff's sync-if-changed install
    When: the new step body is read
    Then: it installs the 52- source to the rules.d target 0644 only when
        `cmp -s` says the content differs
    """
    body = _stepBody(_deployText(), STEP_NAME)

    assert SOURCE_PATH in body
    assert TARGET_PATH in body
    assert "cmp -s" in body
    assert "install -m 644" in body


def test_wifiScanStep_isDryRunAware():
    """
    Given: --dry-run must change nothing
    When: the step body is read
    Then: it returns under $DRY_RUN before any remote call
    """
    body = _stepBody(_deployText(), STEP_NAME)
    dryRunIndex = body.index("$DRY_RUN")

    assert "DRY-RUN would install" in body
    assert body.index("return 0", dryRunIndex) < body.index("remote", dryRunIndex)


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_dryRunInstallsTheWifiScanRuleToRulesD():
    """
    Given: the shipped deploy-pi.sh
    When: it is run with --dry-run
    Then: its own output shows the 52- rule being installed to
        /etc/polkit-1/rules.d/ -- proof a routine deploy reaches the step
    """
    result = subprocess.run(
        ["bash", str(DEPLOY_SCRIPT), "--dry-run"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
        cwd=str(REPO_ROOT),
    )

    assert result.returncode == 0, f"dry-run failed: {result.stderr}"
    installLines = [
        ln
        for ln in result.stdout.splitlines()
        if ln.startswith("DRY-RUN would install") and SOURCE_PATH in ln
    ]
    assert installLines, (
        f"the dry-run never previews installing {RULE_NAME}. Output tail:\n"
        f"{result.stdout[-2000:]}"
    )
    assert installLines[0].endswith(f"-> {TARGET_PATH}")


@pytest.mark.skipif(not _bashAvailable(), reason="bash not available on PATH")
def test_deployPiSh_bashSyntaxValid():
    """`bash -n deploy-pi.sh` must parse cleanly after the edit."""
    result = subprocess.run(
        ["bash", "-n", str(DEPLOY_SCRIPT)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=10,
    )

    assert result.returncode == 0, result.stderr

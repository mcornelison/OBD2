################################################################################
# File Name: test_no_hardcoded_addresses.py
# Purpose/Description: B-044 standing-rule lint -- fail CI if infrastructure
#     addresses (IPs, hostnames, ports, MACs) appear as literals outside
#     allowed locations. Drives audit_config_literals module API.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-20
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-20    | Rex          | Initial implementation (US-201)
# ================================================================================
################################################################################

"""
B-044 standing rule enforcement: no hardcoded infrastructure addresses.

The audit logic scans the repository for literal IPs, hostnames, ports, and
MAC addresses that should instead live in config.json or be marked with an
inline `# b044-exempt: <reason>` pragma. Exempted paths (specs, docs,
offices, *.md, tool caches, the lint itself, canonical config files) are
skipped wholesale.

This test acts as the standing CI gate. Running it locally:
    pytest tests/lint/test_no_hardcoded_addresses.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_config_literals import (
    AddressFinding,
    auditRepository,
    scanLine,
)

REPO_ROOT = Path(__file__).parent.parent.parent


class TestScanLineContract:
    """Unit tests for scanLine() -- the per-line literal detector."""

    def test_scanLine_literalIpInCode_returnsFinding(self) -> None:
        findings = scanLine(
            path=Path("src/pi/sync/client.py"),
            lineNo=10,
            line='    baseUrl = "http://10.27.27.10:8000"',
        )
        assert len(findings) == 1
        assert findings[0].pattern == "ip"
        assert "10.27.27.10" in findings[0].snippet

    def test_scanLine_literalHostname_returnsFinding(self) -> None:
        findings = scanLine(
            path=Path("scripts/foo.sh"),
            lineNo=1,
            line='SERVER="chi-srv-01"',
        )
        assert len(findings) == 1
        assert findings[0].pattern == "hostname"

    def test_scanLine_literalMac_returnsFinding(self) -> None:
        findings = scanLine(
            path=Path("src/foo.py"),
            lineNo=1,
            line='MAC = "00:04:3E:85:0D:FB"',
        )
        assert len(findings) == 1
        assert findings[0].pattern == "mac"

    def test_scanLine_inlinePragma_skipsLine(self) -> None:
        findings = scanLine(
            path=Path("src/foo.py"),
            lineNo=1,
            line='default = "10.27.27.10"  # b044-exempt: validator default',
        )
        assert findings == []

    def test_scanLine_noLiteral_returnsEmpty(self) -> None:
        findings = scanLine(
            path=Path("src/foo.py"),
            lineNo=1,
            line='    return config.get("baseUrl")',
        )
        assert findings == []

    def test_scanLine_unrelatedIp_notFlagged(self) -> None:
        # Only the DeathStarWiFi 10.27.27.* subnet is monitored by B-044.
        findings = scanLine(
            path=Path("src/foo.py"),
            lineNo=1,
            line='    default_gateway = "192.168.1.1"',
        )
        assert findings == []

    def test_scanLine_macCaseInsensitive_detected(self) -> None:
        findings = scanLine(
            path=Path("src/foo.py"),
            lineNo=1,
            line='    mac = "00:04:3e:85:0d:fb"',
        )
        assert len(findings) == 1
        assert findings[0].pattern == "mac"


class TestAuditRepositoryExemptPaths:
    """Verify exempt paths are skipped."""

    def test_auditRepository_returnsListOfFindings(self) -> None:
        findings = auditRepository(REPO_ROOT)
        assert isinstance(findings, list)
        # Contract: every element is an AddressFinding
        for f in findings:
            assert isinstance(f, AddressFinding)

    def test_auditRepository_skipsSpecsDir(self) -> None:
        findings = auditRepository(REPO_ROOT)
        for f in findings:
            assert not str(f.path).replace("\\", "/").startswith("specs/"), (
                f"Found unexpected finding in specs/: {f}"
            )

    def test_auditRepository_skipsDocsDir(self) -> None:
        findings = auditRepository(REPO_ROOT)
        for f in findings:
            assert not str(f.path).replace("\\", "/").startswith("docs/"), (
                f"Found unexpected finding in docs/: {f}"
            )

    def test_auditRepository_skipsOfficesDir(self) -> None:
        findings = auditRepository(REPO_ROOT)
        for f in findings:
            assert not str(f.path).replace("\\", "/").startswith("offices/"), (
                f"Found unexpected finding in offices/: {f}"
            )

    def test_auditRepository_skipsMarkdownFiles(self) -> None:
        findings = auditRepository(REPO_ROOT)
        for f in findings:
            assert not str(f.path).lower().endswith(".md"), (
                f"Found unexpected finding in .md file: {f}"
            )

    def test_auditRepository_skipsCanonicalConfigJson(self) -> None:
        findings = auditRepository(REPO_ROOT)
        for f in findings:
            assert str(f.path).replace("\\", "/") != "config.json", (
                f"Found unexpected finding in config.json: {f}"
            )

    def test_auditRepository_skipsSelfFiles(self) -> None:
        """The audit module + its test must never flag themselves."""
        findings = auditRepository(REPO_ROOT)
        forbidden = {
            "scripts/audit_config_literals.py",
            "scripts/audit_config_literals.sh",
            "tests/lint/test_no_hardcoded_addresses.py",
        }
        for f in findings:
            p = str(f.path).replace("\\", "/")
            assert p not in forbidden, f"Audit module flagged itself: {f}"


class TestAuditRepositoryStandingRule:
    """Acceptance: zero findings in non-exempt files."""

    def test_auditRepository_cleanRepository_zeroFindings(self) -> None:
        """B-044 acceptance: zero infrastructure-IP/hostname/port/MAC literals
        in src/, scripts/, tests/, deploy/ outside of config files + inline
        exemptions. This is the standing CI gate.
        """
        findings = auditRepository(REPO_ROOT)
        if findings:
            report = "\n".join(
                f"  {f.path}:{f.lineNo} [{f.pattern}] {f.snippet}"
                for f in findings[:30]
            )
            more = f"\n  ... and {len(findings) - 30} more" if len(findings) > 30 else ""
            pytest.fail(
                f"B-044 violation: {len(findings)} hardcoded address(es) "
                f"found in non-exempt files. Fix by moving to config.json or "
                f"marking the line with '# b044-exempt: <reason>'.\n"
                f"{report}{more}"
            )


class TestAuditExtensibleExemptions:
    """The audit tool's exemption list must be extensible via argv."""

    def test_auditRepository_extraExempt_honored(self, tmp_path: Path) -> None:
        # Build a throwaway repo-like tree with a violating file
        badFile = tmp_path / "src" / "naughty.py"
        badFile.parent.mkdir(parents=True)
        badFile.write_text('HOST = "10.27.27.99"\n')

        # Without exemption, must flag
        base = auditRepository(tmp_path)
        assert any(str(f.path).endswith("naughty.py") for f in base)

        # With path-prefix exemption, must skip
        withExempt = auditRepository(tmp_path, extraExempt=["src/naughty.py"])
        assert not any(str(f.path).endswith("naughty.py") for f in withExempt)

################################################################################
# File Name: test_address_mirror_consistency.py
# Purpose/Description: A-15 standing-rule lint -- the infrastructure address is
#     held as a LITERAL in three sanctioned mirrors that B-044 deliberately
#     exempts (config.json, validator.py DEFAULTS, deploy/addresses.sh). B-044
#     guarantees no NEW stray literal appears; it does NOT verify the sanctioned
#     mirrors still agree with each other. This lint closes that exact hole: it
#     fails when the mirrors diverge (the failure mode that broke sync on the
#     2026-06-18 chi-srv-01 .10 -> .120 move). Drives audit_address_mirrors.
# Author: Atlas (Architect)
# Creation Date: 2026-06-18
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-18    | Atlas        | Initial implementation (A-15 mirror-drift gate)
# ================================================================================
################################################################################

"""
A-15 standing rule enforcement: the sanctioned address mirrors must agree.

The server/Pi addresses appear in three places that MUST move together:
    1. config.json            (the declared canonical source)
    2. validator.py DEFAULTS   (# b044-exempt: mirrors config.json)
    3. deploy/addresses.sh     (# b044-exempt: canonical bash-side mirror)

Plus config.json itself triplicates the server address (serverHost,
serverBaseUrl, companionService.baseUrl). B-044's audit exempts all of these,
so it cannot catch them drifting apart -- which is exactly what bit us. This
test is the standing gate. Run locally:
    pytest tests/lint/test_address_mirror_consistency.py -v
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.audit_address_mirrors import (
    MirrorMismatch,
    checkMirrorConsistency,
    compareMirrors,
    parseAddressesSh,
    parseConfigAddresses,
    parseValidatorDefaults,
)

REPO_ROOT = Path(__file__).parent.parent.parent


def _consistentFacts() -> tuple[dict, dict, dict]:
    """Return (config, addressesSh, validatorDefaults) that all agree."""
    config = {
        "serverHost": "10.27.27.120",
        "serverPort": "8000",
        "serverHostname": "chi-srv-01",
        "serverBaseUrl": "http://10.27.27.120:8000",
        "piHost": "10.27.27.28",
        "piHostname": "chi-eclipse-01",
        "companionBaseUrl": "http://10.27.27.120:8000",
    }
    addressesSh = {
        "SERVER_HOST": "10.27.27.120",
        "SERVER_PORT": "8000",
        "SERVER_HOSTNAME": "chi-srv-01",
        "PI_HOST": "10.27.27.28",
        "PI_HOSTNAME": "chi-eclipse-01",
    }
    validatorDefaults = {"companionBaseUrl": "http://10.27.27.120:8000"}
    return config, addressesSh, validatorDefaults


class TestCompareMirrorsCore:
    """Pure comparison core -- proves the mechanism catches divergence."""

    def test_compareMirrors_allAgree_returnsEmpty(self) -> None:
        config, sh, validator = _consistentFacts()
        assert compareMirrors(config, sh, validator) == []

    def test_compareMirrors_serverHostDivergesAcrossMirrors_returnsMismatch(self) -> None:
        # The exact 2026-06-18 failure: config moved to .120, addresses.sh
        # was left at .10.
        config, sh, validator = _consistentFacts()
        sh["SERVER_HOST"] = "10.27.27.10"
        mismatches = compareMirrors(config, sh, validator)
        assert any(m.fact == "server host" for m in mismatches)

    def test_compareMirrors_validatorBaseUrlDiverges_returnsMismatch(self) -> None:
        config, sh, validator = _consistentFacts()
        validator["companionBaseUrl"] = "http://10.27.27.10:8000"
        mismatches = compareMirrors(config, sh, validator)
        assert any("validator" in m.message.lower() for m in mismatches)

    def test_compareMirrors_intraConfigBaseUrlStale_returnsMismatch(self) -> None:
        # serverBaseUrl no longer matches host:port within config.json itself.
        config, sh, validator = _consistentFacts()
        config["serverBaseUrl"] = "http://10.27.27.10:8000"
        mismatches = compareMirrors(config, sh, validator)
        assert any(m.fact == "server base url" for m in mismatches)

    def test_compareMirrors_returnsMirrorMismatchInstances(self) -> None:
        config, sh, validator = _consistentFacts()
        sh["PI_HOST"] = "10.27.27.99"
        mismatches = compareMirrors(config, sh, validator)
        assert mismatches
        for m in mismatches:
            assert isinstance(m, MirrorMismatch)


class TestParsers:
    """Parsers read the real on-disk mirrors."""

    def test_parseConfigAddresses_realConfig_extractsServerHost(self) -> None:
        facts = parseConfigAddresses(REPO_ROOT / "config.json")
        assert facts["serverHost"] == "10.27.27.120"
        assert facts["companionBaseUrl"].startswith("http://")

    def test_parseAddressesSh_realFile_extractsDefaults(self) -> None:
        facts = parseAddressesSh(REPO_ROOT / "deploy" / "addresses.sh")
        assert facts["SERVER_HOST"] == "10.27.27.120"
        assert facts["PI_HOST"] == "10.27.27.28"

    def test_parseValidatorDefaults_realFile_extractsCompanionBaseUrl(self) -> None:
        facts = parseValidatorDefaults(
            REPO_ROOT / "src" / "common" / "config" / "validator.py"
        )
        assert facts["companionBaseUrl"] == "http://10.27.27.120:8000"


class TestStandingGate:
    """Acceptance: the live repo's mirrors are consistent."""

    def test_checkMirrorConsistency_realRepo_isConsistent(self) -> None:
        mismatches = checkMirrorConsistency(REPO_ROOT)
        if mismatches:
            report = "\n".join(f"  - {m.fact}: {m.message}" for m in mismatches)
            pytest.fail(
                f"A-15 violation: {len(mismatches)} address mirror(s) diverge.\n"
                f"The server/Pi address is held in config.json, validator.py "
                f"DEFAULTS, and deploy/addresses.sh -- they must move together.\n"
                f"{report}"
            )

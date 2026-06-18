################################################################################
# File Name: audit_address_mirrors.py
# Purpose/Description: A-15 standing-rule audit -- verify the sanctioned
#     infrastructure-address mirrors agree with each other. The server/Pi
#     address is held as a LITERAL in three places that B-044 deliberately
#     exempts: config.json (canonical source), src/common/config/validator.py
#     DEFAULTS, and deploy/addresses.sh. B-044 guarantees no NEW stray literal
#     appears in non-exempt source; it does NOTHING to verify these sanctioned
#     mirrors still match. That gap let the 2026-06-18 chi-srv-01 .10 -> .120
#     move ship with addresses.sh / validator left behind, breaking sync. This
#     module turns "remember to update all three" into a gate. Portable Python
#     (stdlib only); runs on Windows, Linux, and Pi. Backs the pytest lint gate
#     and a standalone CLI.
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
A-15 mirror-consistency audit.

The address SSOT was never single -- it is "documented duplication" across
three sanctioned mirrors that must move together:

    config.json            -- server.network.* + pi.network.* + companionService
    validator.py DEFAULTS  -- pi.companionService.baseUrl
    deploy/addresses.sh    -- SERVER_HOST / PI_HOST / ... defaults

plus config.json itself triplicates the server address (serverHost,
serverBaseUrl, companionService.baseUrl). This audit parses all three and
asserts every copy of each fact agrees. It does the one thing B-044's
literal-scan cannot: catch the mirrors diverging.

CLI:
    python scripts/audit_address_mirrors.py            # reports, exit 0 if consistent
    python scripts/audit_address_mirrors.py --verbose  # show every checked fact
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MirrorMismatch:
    """One fact that disagrees across (or within) the address mirrors."""

    fact: str
    message: str
    sources: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Parsers -- read the real on-disk mirrors.
# ---------------------------------------------------------------------------
def parseConfigAddresses(configPath: Path) -> dict[str, str]:
    """Extract address facts from config.json.

    Returns:
        Mapping with keys: serverHost, serverPort, serverHostname,
        serverBaseUrl, piHost, piHostname, companionBaseUrl. Missing keys
        resolve to '' so the comparator flags them rather than KeyError-ing.
    """
    data = json.loads(Path(configPath).read_text(encoding="utf-8"))
    server = data.get("server", {}).get("network", {})
    pi = data.get("pi", {}).get("network", {})
    companion = data.get("pi", {}).get("companionService", {})
    return {
        "serverHost": str(server.get("serverHost", "")),
        "serverPort": str(server.get("serverPort", "")),
        "serverHostname": str(server.get("serverHostname", "")),
        "serverBaseUrl": str(server.get("serverBaseUrl", "")),
        "piHost": str(pi.get("piHost", "")),
        "piHostname": str(pi.get("piHostname", "")),
        "companionBaseUrl": str(companion.get("baseUrl", "")),
    }


# Matches `NAME="${NAME:-default}"`. The default capture stops at the first
# '}', which is correct for the scalar defaults we compare (SERVER_HOST etc.)
# and harmlessly mangles the derived SERVER_BASE_URL (never read here).
_SH_DEFAULT = re.compile(r'^(?P<name>[A-Z_]+)="\$\{(?P=name):-(?P<val>[^}]*)\}"')


def parseAddressesSh(shPath: Path) -> dict[str, str]:
    """Extract `${VAR:-default}` scalar defaults from deploy/addresses.sh."""
    facts: dict[str, str] = {}
    for line in Path(shPath).read_text(encoding="utf-8").splitlines():
        match = _SH_DEFAULT.match(line.strip())
        if match:
            facts[match.group("name")] = match.group("val")
    return facts


_VALIDATOR_COMPANION = re.compile(
    r"""['"]pi\.companionService\.baseUrl['"]\s*:\s*['"]([^'"]+)['"]"""
)


def parseValidatorDefaults(validatorPath: Path) -> dict[str, str]:
    """Extract the address-bearing DEFAULTS entries from validator.py.

    Regex-parsed (not imported) to keep this module stdlib-only and free of
    the validator's import side effects -- matching the B-044 audit's posture.
    """
    text = Path(validatorPath).read_text(encoding="utf-8")
    match = _VALIDATOR_COMPANION.search(text)
    return {"companionBaseUrl": match.group(1) if match else ""}


# ---------------------------------------------------------------------------
# Comparison core -- pure, over already-parsed facts.
# ---------------------------------------------------------------------------
def compareMirrors(
    config: dict[str, str],
    addressesSh: dict[str, str],
    validatorDefaults: dict[str, str],
) -> list[MirrorMismatch]:
    """Return every fact that disagrees across (or within) the mirrors."""
    mismatches: list[MirrorMismatch] = []

    def cross(fact: str, cfgKey: str, shKey: str) -> None:
        cfgVal = config.get(cfgKey, "")
        shVal = addressesSh.get(shKey, "")
        if cfgVal != shVal:
            mismatches.append(
                MirrorMismatch(
                    fact=fact,
                    message=(
                        f"config.json {cfgKey} ({cfgVal!r}) != "
                        f"addresses.sh {shKey} ({shVal!r})"
                    ),
                    sources={"config.json": cfgVal, "addresses.sh": shVal},
                )
            )

    # config.json <-> addresses.sh
    cross("server host", "serverHost", "SERVER_HOST")
    cross("server port", "serverPort", "SERVER_PORT")
    cross("server hostname", "serverHostname", "SERVER_HOSTNAME")
    cross("pi host", "piHost", "PI_HOST")
    cross("pi hostname", "piHostname", "PI_HOSTNAME")

    # Intra-config coherence: the two derived base URLs must equal host:port.
    expectedBaseUrl = f"http://{config.get('serverHost', '')}:{config.get('serverPort', '')}"
    if config.get("serverBaseUrl", "") != expectedBaseUrl:
        mismatches.append(
            MirrorMismatch(
                fact="server base url",
                message=(
                    f"config.json serverBaseUrl ({config.get('serverBaseUrl', '')!r}) "
                    f"!= derived {expectedBaseUrl!r} (serverHost:serverPort)"
                ),
                sources={"serverBaseUrl": config.get("serverBaseUrl", "")},
            )
        )
    if config.get("companionBaseUrl", "") != expectedBaseUrl:
        mismatches.append(
            MirrorMismatch(
                fact="companion base url",
                message=(
                    f"config.json companionService.baseUrl "
                    f"({config.get('companionBaseUrl', '')!r}) != derived "
                    f"{expectedBaseUrl!r} (serverHost:serverPort)"
                ),
                sources={"companionBaseUrl": config.get("companionBaseUrl", "")},
            )
        )

    # validator.py DEFAULTS <-> config.json
    if validatorDefaults.get("companionBaseUrl", "") != config.get("companionBaseUrl", ""):
        mismatches.append(
            MirrorMismatch(
                fact="validator companion base url",
                message=(
                    f"validator.py DEFAULTS companionService.baseUrl "
                    f"({validatorDefaults.get('companionBaseUrl', '')!r}) != "
                    f"config.json ({config.get('companionBaseUrl', '')!r})"
                ),
                sources={
                    "validator.py": validatorDefaults.get("companionBaseUrl", ""),
                    "config.json": config.get("companionBaseUrl", ""),
                },
            )
        )

    return mismatches


def checkMirrorConsistency(repoRoot: Path) -> list[MirrorMismatch]:
    """Parse the three real mirrors under repoRoot and compare them."""
    repoRoot = Path(repoRoot)
    config = parseConfigAddresses(repoRoot / "config.json")
    addressesSh = parseAddressesSh(repoRoot / "deploy" / "addresses.sh")
    validatorDefaults = parseValidatorDefaults(
        repoRoot / "src" / "common" / "config" / "validator.py"
    )
    return compareMirrors(config, addressesSh, validatorDefaults)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A-15 address mirror-consistency audit")
    parser.add_argument("--verbose", action="store_true", help="show every checked mirror")
    parser.add_argument(
        "--repo-root",
        default=str(Path(__file__).parent.parent),
        help="repository root (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)
    repoRoot = Path(args.repo_root)

    if args.verbose:
        config = parseConfigAddresses(repoRoot / "config.json")
        print("config.json:", config)
        print("addresses.sh:", parseAddressesSh(repoRoot / "deploy" / "addresses.sh"))

    mismatches = checkMirrorConsistency(repoRoot)
    if not mismatches:
        print("A-15 OK: all address mirrors agree.")
        return 0
    print(f"A-15 VIOLATION: {len(mismatches)} mirror(s) diverge:")
    for m in mismatches:
        print(f"  - {m.fact}: {m.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())

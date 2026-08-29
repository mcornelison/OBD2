################################################################################
# File Name: test_grounded_knowledge_compass_status.py
# Purpose/Description: US-571 standing-rule lint -- specs/grounded-knowledge.md is
#     the PM Rule 7 shared surface, so its magnetic-heading entry is read by every
#     agent as current. US-565 made the AK09916 channel actually vary, which turns
#     the old "COMPASS IS FABRICATED" fact stale; but TD-087 records that the
#     heading is real and UNCALIBRATED, printed to a tenth of a degree it cannot
#     support. Two opposite ways to get this entry wrong, so both are pinned:
#       - deleting the caveat and calling the heading plainly "real" (TD-087 lost);
#       - re-asserting, in the present tense, that the channel is latched.
#     A bare "the word fabricated must not appear" check would be WRONG -- drives
#     <=41 genuinely do carry a fabricated heading and that history must survive.
#     So the rule is that every fabrication claim in the section is SCOPED to those
#     historical drives, never left standing as the channel's current state.
# Author: Rex (US-571)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-28    | Rex (US-571) | Initial -- section presence, uncalibrated caveat,
#               |              | scoped-history rule, no present-tense fabrication.
# ================================================================================
################################################################################

"""Lint: the shared grounded-knowledge compass entry stays honest in both directions.

Guards ``specs/grounded-knowledge.md`` only. The other surface US-571 corrected,
``$FLEET_SHARE/knowledge/memory/MEMORY.md``, lives on the fleet share, which is
not present on a clean checkout or a CI runner -- a test that read it would honest
-skip on exactly the machines that run this suite, so it is deliberately not
asserted here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
GROUNDED_KNOWLEDGE = REPO_ROOT / "specs" / "grounded-knowledge.md"

# The section's stable anchor. Prose below it may be rewritten freely; this line
# is what the lint navigates by.
SECTION_HEADING = "## Magnetic Heading"

# A fabrication claim left in the PRESENT tense -- the exact stale wording US-571
# removed, plus the shapes a future edit is most likely to re-introduce.
PRESENT_TENSE_FABRICATION = re.compile(
    r"(?i)(compass is fabricated"
    r"|heading\w*\s+is\s+not\s+a\s+reading"
    r"|heading\w*\s+is\s+(a\s+)?fabricat)"
)

# The channel's current state asserted as latched, rather than narrated as history.
PRESENT_TENSE_LATCH = re.compile(r"(?i)(magnetometer|channel|mag)\s+is\s+latched")

# TD-087's caveat: real measurement, not yet an accurate one.
CALIBRATION_CAVEAT = re.compile(r"(?i)uncalibrated|hard-iron")

# The historical boundary that must survive: drives <=41 were captured on the
# broken acquisition path and nothing retroactively fixes them.
HISTORICAL_DRIVE_BOUND = re.compile(r"(?:<=|≤)\s*41")


def _readSection() -> str:
    """
    Return the magnetic-heading section of grounded-knowledge.md.

    Returns:
        The section text, from its ``##`` heading up to the next ``##`` heading
        or end of file.

    Raises:
        AssertionError: If the section is absent entirely.
    """
    text = GROUNDED_KNOWLEDGE.read_text(encoding="utf-8")
    start = text.find(SECTION_HEADING)
    assert start != -1, (
        f"{GROUNDED_KNOWLEDGE.name} has no {SECTION_HEADING!r} section. This is the "
        f"PM Rule 7 shared surface; without the entry, agents fall back to the "
        f"pre-US-565 belief that the compass is fabricated."
    )

    rest = text[start + len(SECTION_HEADING) :]
    nextHeading = re.search(r"^## ", rest, re.MULTILINE)
    return SECTION_HEADING + (rest[: nextHeading.start()] if nextHeading else rest)


def test_groundedKnowledge_carriesTheMagneticHeadingSection() -> None:
    """
    Given: the shared grounded-knowledge surface
    When: it is read
    Then: it carries a magnetic-heading section naming US-565 as the fix

    An absent entry is not neutral. Agents that find nothing here go looking in
    shared memory and the architect's 2026-08-20 finding, both of which describe
    the pre-US-565 world.
    """
    section = _readSection()

    assert "US-565" in section, (
        "the magnetic-heading section does not name US-565. The acquisition fix is "
        "the whole reason the old fabricated-compass fact stopped being true."
    )


def test_groundedKnowledge_compassSection_keepsTheUncalibratedCaveat() -> None:
    """
    Given: the magnetic-heading section
    When: it is read
    Then: it still states the heading is uncalibrated

    TD-087: the measured field magnitude is ~90 uT against Earth's ~52 uT at this
    latitude -- a hard-iron offset about as large as the field being measured, so
    the bearing can be wrong by tens of degrees and the error is
    direction-dependent, meaning it does not average out. Replacing "fabricated"
    with an unqualified "real" would be a second wrong fact, not a correction.
    """
    section = _readSection()

    assert CALIBRATION_CAVEAT.search(section), (
        "the magnetic-heading section no longer carries the uncalibrated caveat. "
        "US-565 fixed ACQUISITION, not accuracy -- see TD-087."
    )


def test_groundedKnowledge_compassSection_statesThePrecisionDebt() -> None:
    """
    Given: the magnetic-heading section
    When: it is read
    Then: it names the tenth-of-a-degree render as unsupported precision

    ``imu_state_bridge._HEADING_DECIMALS = 1``, so the card prints e.g. ``43.7``.
    That is a precision claim the underlying measurement cannot support, and it is
    the specific debt TD-087 was filed to keep visible.
    """
    section = _readSection()

    assert re.search(r"(?i)0\.1\s*°|tenth of a degree", section), (
        "the magnetic-heading section no longer states the 0.1-degree precision "
        "debt (TD-087). A real measurement wearing more confidence than it earned "
        "is the milder cousin of the fabrication this entry replaced."
    )


def test_groundedKnowledge_compassSection_makesNoPresentTenseFabricationClaim() -> None:
    """
    Given: the magnetic-heading section
    When: every line is examined
    Then: no line asserts the channel is fabricated or latched RIGHT NOW

    The channel varies on the shipping code path: 90 s stationary on the bench gave
    mag_x 27 distinct values across 2,108 samples with DRDY set on 2,108 of 2,108
    reads, against 1 distinct across 20,000 on the old shadow path the same day.
    """
    section = _readSection()

    offenders = [
        line.strip()
        for line in section.splitlines()
        if PRESENT_TENSE_FABRICATION.search(line) or PRESENT_TENSE_LATCH.search(line)
    ]

    assert not offenders, (
        "the magnetic-heading section asserts the channel is currently "
        f"fabricated/latched: {offenders}. US-565 landed in V0.29.30."
    )


def test_groundedKnowledge_compassSection_keepsTheHistoricalDriveBoundary() -> None:
    """
    Given: the magnetic-heading section
    When: it is read
    Then: the drives-<=41 discard guidance survives

    Those drives were captured on the broken acquisition path and nothing
    retroactively fixes them. Deleting this along with the stale claim would
    silently re-admit 29,148 fabricated samples into Spool's analysis.
    """
    section = _readSection()

    assert HISTORICAL_DRIVE_BOUND.search(section), (
        "the drives-<=41 discard guidance is gone. That half of the old fact is "
        "still TRUE and is load-bearing for Spool's historical analysis."
    )


@pytest.mark.parametrize("claimWord", ["fabricat", "latch"])
def test_groundedKnowledge_compassSection_scopesEveryFabricationClaim(claimWord: str) -> None:
    """
    Given: the magnetic-heading section
    When: each line mentioning fabrication or latching is examined
    Then: that line also carries its historical scope

    This is the assertion that distinguishes a correction from an erasure. A bare
    "the word must not appear" rule would be wrong -- drives <=41 genuinely do
    carry a fabricated heading. The rule is that the claim is never left standing
    unscoped: each such line names the drive bound, a date/version, or marks itself
    as history.
    """
    section = _readSection()
    scope = re.compile(
        r"(?:<=|≤)\s*41|202\d-\d\d-\d\d|V0\.29|US-565|(?i:before|until|historic|was |were )"
    )

    offenders = [
        line.strip()
        for line in section.splitlines()
        if claimWord in line.lower() and not scope.search(line)
    ]

    assert not offenders, (
        f"unscoped {claimWord!r} claim(s) in the magnetic-heading section: "
        f"{offenders}. Say WHICH drives or WHEN -- an unscoped claim reads as the "
        f"channel's current state, which is what US-571 corrected."
    )

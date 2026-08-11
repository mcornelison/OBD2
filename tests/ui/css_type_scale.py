################################################################################
# File Name: css_type_scale.py
# Purpose/Description: US-539 shared helper -- resolve a `font-size` declaration
#   through the F-127 type scale. Before US-539 every size on the dashboard was a
#   bare `font-size: Npx`, so a test could read a magnitude straight out of a rule
#   body with one regex. The tokenization broke that, and two of the guards that
#   read sizes that way are SAFETY guards (the STOP takeover directive must be the
#   biggest thing on the panel; the DTC detail directive must outrank its base
#   copy). A refactor that leaves a safety guard silently unable to see its own
#   subject is worse than the drift it fixed, so the resolver lives here ONCE and
#   all three consumers share it rather than each re-deriving `var()` handling.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-08-11
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-11    | Ralph (Rex)  | Initial -- US-539 type-scale token resolver.
# ================================================================================
################################################################################

"""Resolve `font-size` declarations through the US-539 / F-127 type scale."""

from __future__ import annotations

import os
import re

_UI = os.path.join(os.path.dirname(__file__), "..", "..", "specs", "UI")
TOKENS_CSS = os.path.join(_UI, "tokens.css")
DASHBOARD_CSS = os.path.join(_UI, "dist", "dashboard-pi", "dashboard.css")

# The whole scale, largest first. The ORDER is load-bearing: two safety
# hierarchies (see the module docstring) are expressed as "a higher tier than",
# and `test_dashboard_type_scale.py` asserts the declared values descend in
# exactly this sequence.
SCALE_TOKENS = ("fs-hero", "fs-primary", "fs-secondary", "fs-label", "fs-meta")

# A bare px magnitude on a `font-size` -- the drift US-539 exists to remove.
# `(?<![-\w])` keeps a custom-property declaration (`--fs-hero: 40px`) from
# reading as a `font-size` declaration.
BARE_PX_FONT_SIZE = re.compile(r"(?<![-\w])font-size:\s*([0-9.]+)px")


def readCss(path: str) -> str:
    """Read a stylesheet as text.

    Args:
        path: absolute path to the stylesheet.

    Returns:
        The file contents.
    """
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def ruleBlock(css: str, selector: str) -> str:
    """The declaration body of the rule with exactly this selector.

    ANCHORED AT LINE START, which is the whole reason this is a function. A
    plain substring search for `.takeover-directive {` finds the STOP override
    `#dtc-takeover[data-severity="stop"] .takeover-directive {` first, because
    it is declared earlier in the sheet -- so a guard comparing the override
    against its base would silently compare the override against ITSELF and
    report a passing hierarchy that does not exist.

    Args:
        css: the full stylesheet.
        selector: the exact selector text, with or without a trailing ` {`.

    Returns:
        The rule body between the braces.

    Raises:
        AssertionError: when no rule with that selector is declared.
    """
    pattern = rf"^{re.escape(selector.rstrip(' {'))}\s*\{{([^}}]*)\}}"
    match = re.search(pattern, css, re.MULTILINE)
    assert match is not None, f"no rule declared for {selector}"
    return match.group(1)


def scaleValues(css: str) -> dict:
    """The declared px value of every type-scale token in a stylesheet.

    Args:
        css: stylesheet text (either the SSOT or the dist mirror).

    Returns:
        Mapping of token name (no leading `--`) to its integer px value. Tokens
        that are not declared are simply absent -- the caller decides whether an
        absence is a failure, because "missing" and "wrong" are different faults.
    """
    values = {}
    for name in SCALE_TOKENS:
        match = re.search(rf"^\s*--{re.escape(name)}:\s*([0-9.]+)px;", css, re.MULTILINE)
        if match is not None:
            values[name] = int(float(match.group(1)))
    return values


def resolveFontPx(css: str, block: str) -> int:
    """The effective px size of the `font-size` in one rule body.

    Handles both spellings so a guard keeps working across the US-539 refactor
    and cannot quietly start reporting "absent" for a size that is really there.

    Args:
        css: the full stylesheet, needed to resolve a `var(--fs-*)` reference
            against the `:root` scale.
        block: the rule body to read.

    Returns:
        The size in px; -1 when the rule declares no font-size, or declares a
        non-numeric one such as `inherit` (which is a deliberate declaration in
        `.detail-value`, not an absence -- see US-491).
    """
    varMatch = re.search(r"(?<![-\w])font-size:\s*var\(--([a-zA-Z0-9-]+)\)", block)
    if varMatch is not None:
        return scaleValues(css).get(varMatch.group(1), -1)
    pxMatch = BARE_PX_FONT_SIZE.search(block)
    return int(float(pxMatch.group(1))) if pxMatch is not None else -1

################################################################################
# File Name: test_dashboard_token_ssot.py
# Purpose/Description: US-484-a tests -- the shipped Pi dashboard renders against
#   the visual SSOT (specs/UI/tokens.css), not a forked local palette. This slice
#   reconciles the two tokens Atlas has already gated: the OK/MINOR green
#   (dist `--ok-green #2ECC71` -> SSOT `--green-ok #35C46A`, name AND value) and
#   `--text-primary` (#DDDDDD, tokenized 2026-07-25 under Rule-10). Both files are
#   parsed and compared -- a future drift in EITHER file re-reds these tests, which
#   is the point (the SSOT rule is only real if something enforces it).
#   The STOP/critical-red tier is deliberately NOT reconciled here -- that is the
#   safety half (US-484-b, Spool §6d multi-channel). A scope-fence test asserts the
#   STOP tier is still on the brand reds so this mechanical slice cannot silently
#   half-land the safety repoint.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-26
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-26    | Ralph (Rex)  | Initial -- US-484-a SSOT token reconciliation.
# ================================================================================
################################################################################

"""US-484-a tests for dashboard.css <-> specs/UI/tokens.css token reconciliation."""

import os
import re

_UI = os.path.join(os.path.dirname(__file__), "..", "..", "specs", "UI")
_TOKENS = os.path.join(_UI, "tokens.css")
_DIST = os.path.join(_UI, "dist", "dashboard-pi")
_CSS = os.path.join(_DIST, "dashboard.css")
_JS = os.path.join(_DIST, "carousel.js")


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _tokenValue(css: str, name: str) -> str:
    """Return the declared value of a custom property, uppercased + stripped.

    Matches only a real declaration (line-leading `--name:` ... `;`) so prose
    mentions of a token inside the SSOT's comment blocks are never picked up.
    """
    match = re.search(rf"^\s*--{re.escape(name)}:\s*([^;]+);", css, re.MULTILINE)
    assert match is not None, f"--{name} is not declared"
    return match.group(1).strip().upper()


def _declaredTokens(css: str) -> set:
    """Every custom property NAME declared in the file."""
    return set(re.findall(r"^\s*--([a-zA-Z0-9-]+):", css, re.MULTILINE))


# ---------------------------------------------------------------------------
# AC1 -- the green: name AND value come from the SSOT.
# ---------------------------------------------------------------------------


def test_dashboardCss_declaresSsotGreenName_notTheLocalFork():
    """The dist palette declares the SSOT's `--green-ok`; the forked
    `--ok-green` name is gone entirely (rename, not an alias)."""
    css = _read(_CSS)
    declared = _declaredTokens(css)
    assert "green-ok" in declared
    assert "ok-green" not in declared


def test_dashboardCss_greenValue_matchesSsot():
    """The green VALUE is read from the SSOT, so the two files cannot drift:
    #35C46A (Atlas A-8), never the old dist #2ECC71."""
    assert _tokenValue(_read(_CSS), "green-ok") == _tokenValue(_read(_TOKENS), "green-ok")
    assert _tokenValue(_read(_CSS), "green-ok") == "#35C46A"


def test_dashboardCss_noOkGreenReferencesRemain():
    """Every consumer rule binds `var(--green-ok)` -- a leftover
    `var(--ok-green)` would resolve to nothing and render the tier unstyled."""
    assert "--ok-green" not in _read(_CSS)


def test_carouselJs_minorTakeoverTier_bindsSsotGreenVar():
    """The JS side of the same token: the MINOR takeover's colorVar is the
    SSOT name (the CSS rename alone would leave this dangling)."""
    js = _read(_JS)
    assert "--ok-green" not in js
    assert '"--green-ok"' in js


# ---------------------------------------------------------------------------
# AC2 -- text-primary is the SSOT value (tokenized 2026-07-25, Rule-10).
# ---------------------------------------------------------------------------


def test_dashboardCss_textPrimary_matchesSsot():
    """`--text-primary` is no longer a dist invention -- it is now in the SSOT
    and the two declarations must agree on #DDDDDD."""
    assert _tokenValue(_read(_CSS), "text-primary") == _tokenValue(
        _read(_TOKENS), "text-primary"
    )
    assert _tokenValue(_read(_CSS), "text-primary") == "#DDDDDD"


def test_dashboardCss_neutralTextTier_matchesSsot():
    """The rest of the text tier was already aligned -- pin it so a future edit
    to either file cannot quietly re-fork the neutral ramp."""
    css, tokens = _read(_CSS), _read(_TOKENS)
    for name in ("text-secondary", "text-tertiary", "amber-warn"):
        assert _tokenValue(css, name) == _tokenValue(tokens, name), name


# ---------------------------------------------------------------------------
# AC3 -- no drifted literal survives the rename (including the rgba() form,
# which a name-only search misses).
# ---------------------------------------------------------------------------


def test_dashboardCss_noDriftedGreenLiteralRemains():
    """#2ECC71 in ANY notation -- hex or the rgba(46,204,113) spelling used by
    the trust badge -- is drift and must be gone."""
    css = _read(_CSS).upper()
    assert "2ECC71" not in css
    assert not re.search(r"RGBA\(\s*46\s*,\s*204\s*,\s*113", css)


def test_dashboardCss_greenAlphaTint_isTheSsotGreen():
    """The verified trust badge's translucent backdrop is the SSOT green at the
    same 18% alpha -- rgb(53,196,106) == #35C46A."""
    css = _read(_CSS)
    assert re.search(r"rgba\(\s*53\s*,\s*196\s*,\s*106\s*,\s*0\.18\s*\)", css)


def test_dashboardCss_textPrimaryLiteral_appearsOnceInRoot():
    """#DDDDDD is declared exactly once (the :root token) -- every consumer
    goes through var(--text-primary)."""
    assert len(re.findall(r"#DDDDDD", _read(_CSS), re.IGNORECASE)) == 1


# ---------------------------------------------------------------------------
# AC4 -- scope fence: the STOP/critical-red tier belongs to US-484-b.
# ---------------------------------------------------------------------------


def test_stopTier_isUntouchedByThisSlice():
    """US-484-a is the mechanical half. The DTC STOP surfaces must STILL be on
    the brand reds here -- repointing them onto --critical-red without Spool's
    multi-channel (area/motion/text/near-black/full-brightness) treatment would
    ship a weaker STOP than either design. US-484-b lands that as one change."""
    css = _read(_CSS)
    assert '#dtc-ribbon[data-level="stop"]    { background: var(--red-light);' in css
    assert '.dtc-chip[data-level="stop"]    { background: var(--red-light);' in css
    assert "--critical-red" not in css


def test_severityTiersBelowStop_keepTheirSsotColours():
    """WATCH stays amber and MINOR stays the SSOT green after the rename -- the
    severity ramp reads in the same order it did before this slice."""
    css = _read(_CSS)
    assert '#dtc-ribbon[data-level="watch"]   { background: var(--amber-warn);' in css
    assert '#dtc-ribbon[data-level="minor"]   { background: var(--green-ok);' in css

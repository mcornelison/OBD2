################################################################################
# File Name: test_topbar_chain_glyph.py
# Purpose/Description: US-894-a (spec specs/v030-system-page-design.md s4.2.1,
#   S-4/S8) -- the single BT glyph is replaced on every page by the three-layer
#   link chain BT -> ADAPTER -> ECU, read verbatim from system-status.link.
#   Closes US-713 (BT could not say `connecting`) and ARCH-061 (a silent ECU
#   read as "Bluetooth down").
#
#   What is pinned here:
#     - the per-dot looks (up green, connecting neutral, retrying non-member
#       --text-secondary, down non-member tertiary, null HOLLOW), resolved
#       through the shipped stylesheet as COLOURS, not only as tokens;
#     - the colour rule (s4.0): a dot is amber ONLY when its layer is a
#       verdict.members[].key -- swept over every layer-state combination the
#       REAL producer (buildSystemStatusState -> buildSystemVerdict) can emit;
#     - the chain ignores source.obd and obdLink;
#     - an unreadable / vanished system-status file is three hollow dots;
#     - the fit: a declared 3ch SVG (spec limit 3.5ch), relative units only;
#     - ONE cross-language guard per JS copy of a Python vocabulary (layers,
#       link states, member keys), read from the Python source of truth.
#
#   Skipped when node is not on PATH (a node-less CI box) -- the markup, CSS
#   and vocabulary-source checks always run.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-23    | Ralph (Rex)  | Initial -- US-894-a top-bar link chain.
# ================================================================================
################################################################################

"""US-894-a tests: the top bar shows the three-layer link chain."""

from __future__ import annotations

import itertools
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

from pi.splash import system_status_emitter as sse  # noqa: E402
from pi.splash.system_status_emitter import buildSystemStatusState  # noqa: E402

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests boot the shipped carousel.js",
)

PANEL = (480, 320)
_DASH = os.path.join(_REPO_ROOT, "src", "pi", "ui", "dashboard")
_CAROUSEL_JS = os.path.join(_DASH, "carousel.js")
_HTML = os.path.join(_DASH, "dashboard.html")
_CSS = os.path.join(_DASH, "dashboard.css")
_PROBE = os.path.join(os.path.dirname(__file__), "carousel_probe.js")

_NOW = "2026-10-23T07:30:00Z"

# The colour each look resolves to through the shipped cascade (spec s4.2).
GREEN = "var(--green-ok)"
AMBER = "var(--amber-warn)"
SECONDARY = "var(--text-secondary)"
TERTIARY = "var(--text-tertiary)"

HOLLOW3 = {"bt": "hollow", "adapter": "hollow", "ecu": "hollow"}

# Every value a layer's state can take on the wire (Atlas L1 + null).
_ALL_STATES = (sse.LINK_UP, sse.LINK_CONNECTING, sse.LINK_RETRYING, sse.LINK_DOWN, None)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _payload(
    bt: str | None,
    adapter: str | None,
    ecu: str | None,
    *,
    driveState: str = "idle",
    obdAvailable: bool = True,
) -> dict:
    """A system-status payload from the SHIPPED builder -- its verdict included."""
    link = {
        layer: {"state": state, "ts": _NOW if state else None, "lastOkTs": None}
        for layer, state in (("bt", bt), ("adapter", adapter), ("ecu", ecu))
    }
    return buildSystemStatusState(
        syncLastOkTs=_NOW,
        syncRows=10,
        syncPending=0,
        syncStale=False,
        powerSource="external",
        driveState=driveState,
        driveId=7 if driveState == "recording" else None,
        nowIso=_NOW,
        obdAvailable=obdAvailable,
        obdUnavailableReason=None if obdAvailable else "never connected",
        link=link,
    )


def _looks(payloads: list[Any]) -> list[dict]:
    """linkChainGlyph over many payloads in ONE node process (probe --map)."""
    proc = subprocess.run(
        [_NODE, _PROBE, "--map", "linkChainGlyph"],
        input=json.dumps([[p] for p in payloads]),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _look(payload: Any) -> dict:
    return _looks([payload])[0]


def _jsVocabulary() -> dict:
    """The JS copies of the provider vocabulary, as the shipped module exports them."""
    script = (
        "const c = require(process.argv[1]);"
        "console.log(JSON.stringify({layers: c.LINK_CHAIN_LAYERS,"
        " states: Object.keys(c.LINK_STATE_LOOK), members: c.LINK_MEMBER_LAYERS}));"
    )
    proc = subprocess.run(
        [_NODE, "-e", script, _CAROUSEL_JS],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _surface(routes: dict[str, Any], steps: list[dict[str, Any]] | None = None):
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _dots(surface) -> dict[str, tuple[str, str, str]]:
    """{layer: (data-state, resolved colour, resolved fill)} off the rendered bar."""
    chain = surface.pathById("glyph-bt")
    assert chain is not None, "no #glyph-bt in the rendered DOM"
    assert surface.rendered(chain), "#glyph-bt is in the DOM but not displayed"
    out = {}
    for path in surface.pathsByClass("chain-dot"):
        attrs = path[-1].get("attrs", {})
        colour = surface.winningDeclaration(path, "color")
        fill = surface.winningDeclaration(path, "fill")
        out[attrs.get("data-layer")] = (
            attrs.get("data-state"),
            colour[0] if colour else "",
            fill[0] if fill else "",
        )
    assert list(out) == ["bt", "adapter", "ecu"], f"chain dots read {list(out)}"
    return out


def _allText(node: dict) -> list[str]:
    """Every text node AND attribute value under ``node`` (titles say things too)."""
    out = [str(v) for v in node.get("attrs", {}).values()]
    for child in node.get("children", []):
        if "text" in child:
            out.append(child["text"])
        else:
            out.extend(_allText(child))
    return out


# ---------------------------------------------------------------------------
# Cross-language guards -- one per JS copy of a Python vocabulary.
# ---------------------------------------------------------------------------


@_needsNode
def test_theChainLayersAreTheProvidersLayers_inChainOrder():
    assert _jsVocabulary()["layers"] == list(sse.LINK_LAYERS)


@_needsNode
def test_theLinkStateTableKeysAreExactlyTheProvidersStates():
    """null is NOT a key: a layer with no table entry is hollow (not read)."""
    expected = {sse.LINK_UP, sse.LINK_CONNECTING, sse.LINK_RETRYING, sse.LINK_DOWN}
    assert set(_jsVocabulary()["states"]) == expected


@_needsNode
def test_theMemberLayersAreVerdictMemberKeysThatNameALayer():
    """Only bt and adapter can paint a dot amber (spec s4.1); the ECU is never a
    member. Each JS key must be a real member key AND a real layer."""
    members = _jsVocabulary()["members"]
    assert members == [sse.VERDICT_BT, sse.VERDICT_ADAPTER]
    for key in members:
        assert key in sse.VERDICT_MEMBER_ORDER
        assert key in sse.LINK_LAYERS


def test_thereIsOnlyOneLinkStateTableInTheRenderer():
    source = _read(_CAROUSEL_JS)
    assert len(re.findall(r"\bvar LINK_STATE_LOOK\s*=", source)) == 1
    assert len(re.findall(r"\bvar LINK_CHAIN_LAYERS\s*=", source)) == 1


def test_btGlyphStateIsRetired():
    """No definition, call or export survives (a comment may record the retirement)."""
    source = _read(_CAROUSEL_JS)
    assert not re.search(r"\bbtGlyphState\s*[(:]", source)


# ---------------------------------------------------------------------------
# The view: glyphs.bt = {bt, adapter, ecu}, through the REAL producer.
# ---------------------------------------------------------------------------


@_needsNode
def test_arch061_btUpAdapterUpEcuConnecting_isGreenGreenNeutral():
    payload = _payload("up", "up", "connecting")
    assert payload["verdict"]["issueCount"] == 0
    assert _look(payload) == {"bt": "ok", "adapter": "ok", "ecu": "neutral"}


@_needsNode
def test_systemStatusView_carriesTheChainAsGlyphsBt():
    """The story's own example: glyphs.bt {bt: 'ok', adapter: 'ok', ecu: 'neutral'}."""
    proc = subprocess.run(
        [_NODE, _PROBE, "systemStatusView", json.dumps(_payload("up", "up", "connecting"))],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert proc.returncode == 0, proc.stderr
    view = json.loads(proc.stdout)
    assert view["glyphs"]["bt"] == {"bt": "ok", "adapter": "ok", "ecu": "neutral"}


@_needsNode
def test_allNull_isThreeHollowDots():
    assert _look(_payload(None, None, None)) == HOLLOW3


@_needsNode
@pytest.mark.parametrize("payload", [None, "x", [], {}, {"link": None}, {"link": "x"}])
def test_anUnreadablePayload_isThreeHollowDots(payload):
    assert _look(payload) == HOLLOW3


@_needsNode
def test_ecuRetryingAfterKeyOffWithNoMember_isSecondary_neverAmber():
    payload = _payload("up", "up", "retrying")
    assert payload["verdict"]["members"] == []
    assert _look(payload)["ecu"] == "secondary"


@_needsNode
def test_btRetryingWithTheBtMember_paintsTheBtDotAmber():
    payload = _payload("retrying", None, None, driveState="recording")
    assert [m["key"] for m in payload["verdict"]["members"]] == ["bt"]
    assert _look(payload)["bt"] == "amber"


@_needsNode
def test_btRetryingWithNoMember_isSecondary_becauseAmberIsKeyedToTheMember():
    """Iris I2: the SAME state is amber or not by membership alone."""
    payload = _payload("retrying", None, None, driveState="idle")
    assert payload["verdict"]["members"] == []
    assert _look(payload)["bt"] == "secondary"


@_needsNode
def test_anAdapterDownWhileBtIsDown_isTertiary_btIsTheFault():
    payload = _payload("down", "down", None)
    assert [m["key"] for m in payload["verdict"]["members"]] == ["bt"]
    assert _look(payload) == {"bt": "amber", "adapter": "tertiary", "ecu": "hollow"}


@_needsNode
def test_anAdapterNotAnsweringWhileBtIsUp_paintsTheAdapterDotAmber():
    payload = _payload("up", "down", None)
    assert [m["key"] for m in payload["verdict"]["members"]] == ["adapter"]
    assert _look(payload) == {"bt": "ok", "adapter": "amber", "ecu": "hollow"}


@_needsNode
def test_aStateWordTheProviderHasNotPublished_isHollow_neverAColour():
    payload = _payload("up", "up", "up")
    payload["link"]["ecu"]["state"] = "someFutureState"
    assert _look(payload)["ecu"] == "hollow"


@_needsNode
def test_theChainIgnoresSourceObd():
    payload = _payload("up", "up", "up", obdAvailable=False)
    assert payload["source"]["obd"]["available"] is False
    assert _look(payload) == {"bt": "ok", "adapter": "ok", "ecu": "ok"}


@_needsNode
def test_aMalformedVerdictNamesNobody_soNoDotIsAmber():
    payload = _payload("down", None, None)
    payload["verdict"] = {"issueCount": 1, "members": "bt"}
    assert _look(payload)["bt"] == "tertiary"


@_needsNode
def test_theAmberSetEqualsTheMemberSet_overEveryStateTheProducerCanEmit():
    """Spec AC 7 at the top bar: across every layer-state combination and both
    drive states, a dot is amber IFF its layer is a verdict member."""
    cases = [
        (combo, drive)
        for combo in itertools.product(_ALL_STATES, repeat=3)
        for drive in ("idle", "recording")
    ]
    payloads = [_payload(*combo, driveState=drive) for combo, drive in cases]
    looks = _looks(payloads)
    assert len(looks) == len(cases) == 250
    for (combo, drive), payload, look in zip(cases, payloads, looks):
        members = {m["key"] for m in payload["verdict"]["members"]} & set(sse.LINK_LAYERS)
        amber = {layer for layer, value in look.items() if value == "amber"}
        assert amber == members, (combo, drive, look, payload["verdict"])
        for layer, state in zip(sse.LINK_LAYERS, combo):
            if layer in members:
                continue
            expected = {
                sse.LINK_UP: "ok",
                sse.LINK_CONNECTING: "neutral",
                sse.LINK_RETRYING: "secondary",
                sse.LINK_DOWN: "tertiary",
                None: "hollow",
            }[state]
            assert look[layer] == expected, (combo, drive, layer, look)


# ---------------------------------------------------------------------------
# The rendered top bar (validationCriteria 1 and 2).
# ---------------------------------------------------------------------------


@_needsNode
def test_validation1_arch061_rendersGreenGreenNeutral_andNoElementSaysBluetoothDown():
    surface = _surface({"/system-status": _payload("up", "up", "connecting")})
    dots = _dots(surface)
    assert dots["bt"][:2] == ("ok", GREEN)
    assert dots["adapter"][:2] == ("ok", GREEN)
    assert dots["ecu"][:2] == ("neutral", SECONDARY)
    everything = " ".join(_allText(surface.tree)).lower()
    assert "bluetooth down" not in everything


@_needsNode
def test_theChainIsInTheSharedTopBar_soItIsOnEveryPage():
    surface = _surface({"/system-status": _payload("up", "up", "connecting")})
    path = surface.pathById("glyph-bt")
    ids = [node.get("attrs", {}).get("id") for node in path]
    assert "topbar" in ids
    classes = " ".join((node.get("attrs", {}).get("class") or "") for node in path)
    assert "card" not in classes.split(), "the chain sits inside a page, not the bar"


@_needsNode
def test_validation2_systemStatusUnreadable_isThreeHollowRings():
    dots = _dots(_surface({}))
    for layer in ("bt", "adapter", "ecu"):
        assert dots[layer] == ("hollow", TERTIARY, "none"), (layer, dots)


@_needsNode
def test_aVanishedStateFileReturnsTheChainToHollow_noLingeringGreen():
    payload = _payload("up", "up", "up")
    gone = _dots(
        _surface(
            {"/system-status": payload},
            steps=[{"flush": 4}, {"setRoutes": {"/system-status": None}}, {"flush": 4}],
        )
    )
    assert {layer: v[0] for layer, v in gone.items()} == HOLLOW3


@_needsNode
def test_theStateFileIsKeptAndTheChainStaysGreen_control():
    payload = _payload("up", "up", "up")
    kept = _dots(
        _surface(
            {"/system-status": payload},
            steps=[{"flush": 4}, {"setRoutes": {"/system-status": payload}}, {"flush": 4}],
        )
    )
    assert {layer: v[:2] for layer, v in kept.items()} == {
        "bt": ("ok", GREEN),
        "adapter": ("ok", GREEN),
        "ecu": ("ok", GREEN),
    }


@_needsNode
def test_theStylesheetResolvesEveryLookToItsSpecColour():
    surface = _surface({"/system-status": _payload("up", "up", "up")})
    dot = surface.pathsByClass("chain-dot")[0]
    resolved = {}
    for look in ("ok", "neutral", "secondary", "tertiary", "amber", "hollow", "someFutureLook"):
        dot[-1]["attrs"]["data-state"] = look
        colour = surface.winningDeclaration(dot, "color")
        fill = surface.winningDeclaration(dot, "fill")
        resolved[look] = (colour[0] if colour else "", fill[0] if fill else "")
    assert resolved["ok"] == (GREEN, "currentcolor")
    assert resolved["neutral"] == (SECONDARY, "currentcolor")
    assert resolved["secondary"] == (SECONDARY, "currentcolor")
    assert resolved["tertiary"] == (TERTIARY, "currentcolor")
    assert resolved["amber"] == (AMBER, "currentcolor")
    assert resolved["hollow"] == (TERTIARY, "none")
    assert resolved["someFutureLook"][0] != AMBER
    assert [look for look, (c, _) in resolved.items() if c == AMBER] == ["amber"]
    assert [look for look, (c, _) in resolved.items() if c == GREEN] == ["ok"]


# ---------------------------------------------------------------------------
# Markup + fit (spec AC 11, 14).
# ---------------------------------------------------------------------------


def _chainMarkup() -> str:
    match = re.search(r'<span class="glyph" id="glyph-bt"[^>]*>(.*?)</span>', _read(_HTML), re.S)
    assert match is not None, "no #glyph-bt span in dashboard.html"
    return match.group(0)


def test_theSlotKeepsItsIdAndTitle_andHoldsOneSvgWithThreeDots():
    markup = _chainMarkup()
    assert 'title="Bluetooth"' in markup
    assert markup.count("<svg") == 1
    assert 'class="chain-mark"' in markup
    layers = re.findall(r'<circle class="chain-dot" data-layer="([a-z]+)" data-state="hollow"', markup)
    assert layers == ["bt", "adapter", "ecu"]
    assert ">BT<" not in markup, "the retired BT text glyph is back"


def test_theChainSvgUsesRelativeUnitsOnly():
    assert "px" not in _chainMarkup()
    css = _read(_CSS)
    rules = re.findall(r"^#glyph-bt [^{]*\{[^}]*\}", css, re.M)
    assert rules, "no #glyph-bt rules in dashboard.css"
    for rule in rules:
        assert not re.search(r"\d\s*px\b", rule), rule
        assert "#" not in rule.split("{", 1)[1], f"literal colour in {rule}"


def test_theChainIsDeclared3ch_withinTheSpecsLimitOf3point5ch():
    css = _read(_CSS)
    rule = re.search(r"^#glyph-bt \.chain-mark\s*\{([^}]*)\}", css, re.M)
    assert rule is not None
    width = re.search(r"(?<![-\w])width:\s*([\d.]+)ch;", rule.group(1))
    assert width is not None, "the chain declares no ch width"
    assert float(width.group(1)) == 3.0
    assert float(width.group(1)) <= 3.5

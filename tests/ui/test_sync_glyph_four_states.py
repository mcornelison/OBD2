################################################################################
# File Name: test_sync_glyph_four_states.py
# Purpose/Description: US-917-d (spec specs/v030-system-page-design.md s4.3.1,
#   AC 17; CIO 2026-10-27) -- the top-bar sync glyph in FOUR states, decided
#   top-down, first match wins:
#     1 `error`   a `sync` verdict member is present       --amber-warn
#     2 `busy`    sync.inProgress is true                   --blue-busy
#     3 `ok`      sync.lastOkTs is non-null                 --green-ok
#     4 `unknown` none of the above / no system-status      --text-tertiary
#   One case per AC 17 row, each on its generated sync-* fixture (the REAL
#   builder's inProgress, priorCustody, syncedThisBoot and sync member), plus
#   the DATA sentence's sync member span (S1/S2) and the source guards: the
#   page computes no case (no '120', no 'syncStaleThresholdSeconds', no
#   sync.stale).
#
#   Skipped when node is not on PATH.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-10-27
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-10-27    | Rex (US-917-d)| Initial -- the four-state sync glyph exit test.
# ================================================================================
################################################################################

"""US-917-d: the sync glyph is amber over blue over green over grey."""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
from datetime import UTC, datetime
from typing import Any

import pytest

sys.path.insert(0, os.path.dirname(__file__))
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

import render_harness as rh  # noqa: E402

_NODE = shutil.which("node")
_needsNode = pytest.mark.skipif(
    _NODE is None,
    reason="node not on PATH -- these tests run the shipped carousel.js",
)

PANEL = (480, 320)
_ZONE = "America/Chicago"
_FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "states", "system")
_NOW_MS = int(datetime(2026, 10, 22, 23, 10, tzinfo=UTC).timestamp() * 1000)
_UI = os.path.join(_REPO_ROOT, "src", "pi", "ui")
_CAROUSEL_JS = os.path.join(_UI, "dashboard", "carousel.js")

AMBER = "var(--amber-warn)"
BLUE = "var(--blue-busy)"
GREEN = "var(--green-ok)"
GREY = "var(--text-tertiary)"

# state -> (colour, title): spec s4.3.1's table and its `title` line.
_LOOK = {
    "error": (AMBER, "sync error"),
    "busy": (BLUE, "syncing"),
    "ok": (GREEN, "sync OK"),
    "unknown": (GREY, "sync not read"),
}

# AC 17, one fixture per row -> the glyph state it must paint.
_AC17 = {
    "sync-ok": "ok",
    "sync-busy": "busy",
    "sync-prior-unfinished": "error",
    "sync-prior-unfinished-count-unknown": "error",
    "sync-cut-off": "error",
    "sync-home-stuck": "error",
    "sync-busy-during-error": "error",
    "sync-driving-old": "ok",
    "sync-away-backlog": "ok",
    "sync-never": "unknown",
    "sync-custody-missing": "ok",
}


def _payloads(name: str) -> dict[str, Any]:
    with open(os.path.join(_FIXTURE_DIR, f"{name}.json"), encoding="utf-8") as fh:
        return json.load(fh)["payloads"]


def _surface(routes: dict[str, Any]):
    tree = rh.runDashboard(routes=routes, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    return rh.dashboardSurface(tree, viewport=PANEL)


def _fixtureSurface(name: str):
    return _surface({"/" + k: v for k, v in _payloads(name).items()})


def _glyph(surface) -> tuple[dict, str | None]:
    """#glyph-sync's attributes and its winning colour."""
    path = surface.pathById("glyph-sync")
    assert path is not None, "no #glyph-sync in the rendered DOM"
    declaration = surface.winningDeclaration(path, "color")
    return path[-1].get("attrs", {}), (declaration[0] if declaration else None)


def _text(node: dict) -> str:
    if "text" in node:
        return node["text"]
    return "".join(_text(c) for c in node.get("children", []))


def _syncParts(surface) -> list[dict]:
    """The DATA sentence's parts, in order, as {text, level, member}."""
    rows = [p for p in surface.pathsByClass("sys-row")
            if p[-1].get("attrs", {}).get("data-row") == "data"]
    assert len(rows) == 1, "no single DATA row"
    parts = []
    stack = [rows[0][-1]]
    while stack:
        node = stack.pop(0)
        attrs = node.get("attrs", {})
        if "sys-row-part" in (attrs.get("class") or "").split():
            parts.append({
                "text": _text(node), "level": attrs.get("data-level"),
                "member": attrs.get("data-member"),
            })
            continue
        stack[0:0] = [c for c in node.get("children", []) if "text" not in c]
    return parts


# ---------------------------------------------------------------------------
# AC 17: one case per row -- state, colour and title.
# ---------------------------------------------------------------------------


def test_theAc17SetIsEveryGeneratedSyncFixture():
    """Every AC 17 row has its generated fixture on disk (no vacuous case)."""
    onDisk = {f[:-5] for f in os.listdir(_FIXTURE_DIR) if f.endswith(".json")}
    assert set(_AC17) <= onDisk, sorted(set(_AC17) - onDisk)


@_needsNode
@pytest.mark.parametrize("name", sorted(_AC17))
def test_sync_glyph_four_states(name: str, monkeypatch):
    """
    Given: an AC 17 fixture from the real builder
    When: the shipped dashboard renders it
    Then: #glyph-sync paints the s4.3.1 state, its token and its title; the
          amber member marks are present exactly when the state is error.
    """
    monkeypatch.setenv("TZ", _ZONE)
    want = _AC17[name]
    members = [m["key"] for m in _payloads(name)["system-status"]["verdict"]["members"]]
    # The member, not the page, decides error (s4.3.1 row 1).
    assert ("sync" in members) == (want == "error"), (name, members)
    attrs, colour = _glyph(_fixtureSurface(name))
    assert attrs.get("data-state") == want, (name, attrs)
    assert colour == _LOOK[want][0], (name, colour)
    assert attrs.get("title") == _LOOK[want][1], (name, attrs)
    if want == "error":
        assert attrs.get("data-level") == "amber"
        assert attrs.get("data-member") == "sync"
    else:
        assert "data-level" not in attrs and "data-member" not in attrs, (name, attrs)


@_needsNode
def test_noSystemStatus_isUnknown(monkeypatch):
    """No /system-status at all -> unknown, grey, 'sync not read'."""
    monkeypatch.setenv("TZ", _ZONE)
    attrs, colour = _glyph(_surface({}))
    assert attrs.get("data-state") == "unknown"
    assert colour == GREY
    assert attrs.get("title") == "sync not read"


@_needsNode
def test_aCountedReadThenTheFileVanishes_resetsToUnknown(monkeypatch):
    """resetSystemGlyphs paints syncGlyphState(null): a dead emitter's error
    does not linger amber, and its member marks go with it."""
    monkeypatch.setenv("TZ", _ZONE)
    routes = {"/" + k: v for k, v in _payloads("sync-home-stuck").items()}
    steps = [{"flush": 4}, {"setRoutes": {"/system-status": None}}, {"flush": 4}]
    tree = rh.runDashboard(routes=routes, steps=steps, viewport=PANEL, nowMs=_NOW_MS)["tree"]
    attrs, colour = _glyph(rh.dashboardSurface(tree, viewport=PANEL))
    assert attrs.get("data-state") == "unknown"
    assert colour == GREY
    assert "data-level" not in attrs and "data-member" not in attrs


def test_theMarkupStartsUnknown():
    """Before the first read the glyph is the markup's: unknown, 'sync not read'."""
    with open(os.path.join(_UI, "dashboard", "dashboard.html"), encoding="utf-8") as fh:
        html = fh.read()
    m = re.search(r'<span[^>]*id="glyph-sync"[^>]*>', html)
    assert m is not None
    assert 'data-state="unknown"' in m.group(0)
    assert 'title="sync not read"' in m.group(0)


# ---------------------------------------------------------------------------
# The DATA sentence (System s4.3 :190): the member's reason, amber, first in
# the sync part, in its own span.
# ---------------------------------------------------------------------------


@_needsNode
@pytest.mark.parametrize("name, reason", [
    ("sync-prior-unfinished", "Last sync didn't finish · 1,240 rows kept"),
    ("sync-prior-unfinished-count-unknown", "Last sync didn't finish · row count unknown"),
    ("sync-cut-off", "Last stop was cut off · sync result unknown · 3,880 rows waiting"),
])
def test_theDataSentencePrintsTheSyncMemberFirstInTheSyncPart(name, reason, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    parts = _syncParts(_fixtureSurface(name))
    synced = [i for i, p in enumerate(parts) if p["member"] == "sync"]
    assert len(synced) == 1, parts
    i = synced[0]
    assert parts[i]["text"].lstrip(" ·") == reason
    assert parts[i]["level"] == "amber"
    # First in the sync part: the rows-waiting words follow it, neutral.
    assert "rows" in parts[i + 1]["text"] and parts[i + 1]["level"] == "secondary", parts
    for other in parts[i + 1:]:
        assert other["member"] is None and other["level"] != "amber", parts


@_needsNode
def test_cutOff_neverReadsTheOlderCustodyVerdict(monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    sentence = " ".join(p["text"] for p in _syncParts(_fixtureSurface("sync-cut-off")))
    assert "cut off" in sentence
    assert "rows kept" not in sentence and "1,240" not in sentence


@_needsNode
def test_s1_countsInTheVerdict(monkeypatch):
    """S1 is +1 on the verdict: sync-custody-missing (no member) reads ALL OK,
    sync-prior-unfinished reads 1 ISSUE."""
    monkeypatch.setenv("TZ", _ZONE)

    def verdict(name: str) -> str:
        paths = _fixtureSurface(name).pathsByClass("sys-verdict-text")
        return _text(paths[0][-1])

    assert verdict("sync-custody-missing") == "ALL OK"
    assert verdict("sync-prior-unfinished") == "1 ISSUE"


@_needsNode
@pytest.mark.parametrize("name", ["sync-ok", "sync-driving-old", "sync-away-backlog"])
def test_noMember_noAmberSyncPart(name, monkeypatch):
    monkeypatch.setenv("TZ", _ZONE)
    parts = _syncParts(_fixtureSurface(name))
    assert [p for p in parts if p["member"] == "sync" or p["level"] == "amber"] == []


# ---------------------------------------------------------------------------
# Source guards: one rule, the provider's facts only.
# ---------------------------------------------------------------------------


def _stripComments(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    return re.sub(r"(?m)(^|[^:\\])//.*$", r"\1", js)


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def test_carouselComputesNoCase_no120_noThresholdKey():
    code = _stripComments(_read(_CAROUSEL_JS))
    assert "syncStaleThresholdSeconds" not in code
    assert "120" not in code


def test_syncGlyphState_readsOnlyTheMembersAndTheSyncBlock_neverStale():
    code = _stripComments(_read(_CAROUSEL_JS))
    start = code.index("function syncGlyphState(")
    fn = code[start:code.index("\n  }", start)]
    assert "verdictMemberKeys(data)" in fn
    assert "inProgress" in fn and "lastOkTs" in fn
    assert "stale" not in fn
    # The order is the spec's: error, then busy, then ok, else unknown.
    order = [fn.index('"error"'), fn.index('"busy"'), fn.index('"ok"'), fn.index('"unknown"')]
    assert order == sorted(order), fn


def test_noNeutralOrAmberLookRemainsForTheSyncGlyph():
    code = _stripComments(_read(_CAROUSEL_JS))
    for line in code.splitlines():
        if "glyphEls.sync" in line or "syncGlyphState" in line:
            assert '"neutral"' not in line and '"amber"' not in line, line


def _token(css: str, name: str) -> str | None:
    m = re.search(rf"^\s*--{re.escape(name)}:\s*([^;]+);", css, re.MULTILINE)
    return m.group(1).strip().upper() if m else None


def test_blueBusyIsDeclaredInTheSsotAndMirrored():
    assert _token(_read(os.path.join(_UI, "tokens.css")), "blue-busy") == "#4FA8FF"
    assert _token(_read(os.path.join(_UI, "dashboard", "dashboard.css")), "blue-busy") == "#4FA8FF"

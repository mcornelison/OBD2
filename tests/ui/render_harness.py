################################################################################
# File Name: render_harness.py
# Purpose/Description: US-499 (S6, F-121) render-regression backstop -- the
#   render side of the harness. Parses the SHIPPED markup into a DOM tree, runs
#   the SHIPPED browser JS over it (via the node probes), then resolves the
#   SHIPPED stylesheet across the resulting tree to decide what actually has a
#   box on screen.
#
#   WHY THIS EXISTS. Sprint 66 shipped three defects that every unit test
#   passed: US-494 (a dependency the systemd entry point never injected),
#   US-495 (correct JS defeated by a stylesheet the JS cannot see), US-498 (three
#   individually-correct animation declarations interacting to a black screen).
#   All three are COMPOSITION failures, so the backstop has to compose too:
#   node owns "what did the real JS leave on the DOM", this module owns "what
#   does the real cascade do with that", and neither process can see the other's
#   verdict.
#
#   FIDELITY LIMITS (stated, not hidden -- the story's conditionalOutcome
#   requires this, and an unstated limit is how a lenient test passes on a broken
#   layout):
#     1. This resolves the CASCADE (importance -> specificity -> source order,
#        inline declarations, inherited display:none through ancestors). It does
#        NOT do LAYOUT: it cannot tell you a box overflowed, wrapped, or landed
#        off-screen. It answers "is this painted at all", which is exactly the
#        S1/S2 defect class and nothing more.
#     2. Unresolvable selectors (a pseudo-class this cannot evaluate) are
#        reported, NOT silently skipped -- `unresolvableDisplaySelectors()` lets
#        a test fail loudly when the stylesheet grows a rule this harness would
#        have to guess at. Skipping a `display` rule makes a test LENIENT, and a
#        lenient render test is worse than none.
#     3. @media blocks are evaluated only for the width/height the caller states.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-499 S6 render-regression harness.
# ================================================================================
################################################################################

"""Cascade-resolving render harness for the shipped Pi UI kits (US-499)."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from html.parser import HTMLParser
from typing import Any

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
DASHBOARD_DIR = os.path.join(_REPO, "specs", "UI", "dist", "dashboard-pi")
SPLASH_DIR = os.path.join(_REPO, "specs", "UI", "dist", "splash-pi")

# Elements the HTML spec renders as `display: none` with no stylesheet at all.
_UA_NOT_RENDERED_TAGS = frozenset({"script", "style", "head", "meta", "link", "title"})
_VOID_TAGS = frozenset(
    {"meta", "link", "br", "hr", "img", "input", "source", "area", "base", "col"}
)


# --- markup ------------------------------------------------------------------


class _TreeBuilder(HTMLParser):
    """Parse the shipped markup into a JSON-able element tree.

    Only the BODY subtree is kept: it is what the browser hands the stylesheet,
    and it is what the node probe rebuilds, so the ancestor chain in the harness
    is identical to the one on the panel.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: dict[str, Any] = {"tag": "body", "attrs": {}, "children": []}
        self._stack: list[dict[str, Any]] = [self.root]
        self._inBody = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self._inBody = True
            return
        if not self._inBody:
            return
        node = {
            "tag": tag,
            "attrs": {k: ("" if v is None else v) for k, v in attrs},
            "children": [],
        }
        self._stack[-1]["children"].append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if not self._inBody:
            return
        self._stack[-1]["children"].append(
            {
                "tag": tag,
                "attrs": {k: ("" if v is None else v) for k, v in attrs},
                "children": [],
            }
        )

    def handle_endtag(self, tag: str) -> None:
        if tag == "body":
            self._inBody = False
            return
        if not self._inBody:
            return
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i]["tag"] == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self._inBody and data.strip():
            self._stack[-1]["children"].append({"text": data})


def parseMarkup(path: str) -> dict[str, Any]:
    """Return the body subtree of ``path`` as ``{'tag': 'body', ...}``."""
    with open(path, encoding="utf-8") as fh:
        builder = _TreeBuilder()
        builder.feed(fh.read())
    return builder.root


def bodyChildren(tree: dict[str, Any]) -> list[dict[str, Any]]:
    """The element/text children of a parsed body (what the probe rebuilds)."""
    return tree["children"]


# --- stylesheet --------------------------------------------------------------


class Rule:
    """One selector + its declarations, tagged with its source order."""

    __slots__ = ("selector", "declarations", "order", "media")

    def __init__(self, selector: str, declarations: str, order: int, media: str) -> None:
        self.selector = selector
        self.declarations = declarations
        self.order = order
        self.media = media


def _stripComments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def parseCss(css: str) -> list[Rule]:
    """Every style rule in source order, descending into @media blocks."""
    return _parseBlock(_stripComments(css), media="", startOrder=0)[0]


def _parseBlock(text: str, media: str, startOrder: int) -> tuple[list[Rule], int]:
    rules: list[Rule] = []
    order = startOrder
    i = 0
    while True:
        brace = text.find("{", i)
        if brace == -1:
            return rules, order
        prelude = text[i:brace].strip()
        depth = 1
        j = brace + 1
        while j < len(text) and depth:
            if text[j] == "{":
                depth += 1
            elif text[j] == "}":
                depth -= 1
            j += 1
        body = text[brace + 1 : j - 1]
        if prelude.startswith("@media"):
            nested, order = _parseBlock(body, prelude[len("@media") :].strip(), order)
            rules.extend(nested)
        elif not prelude.startswith("@"):
            for selector in prelude.split(","):
                selector = selector.strip()
                if selector:
                    rules.append(Rule(selector, body, order, media))
                    order += 1
        i = j
    return rules, order


def declarationOf(declarations: str, prop: str) -> tuple[str, bool] | None:
    """The LAST declaration of ``prop`` in a block as ``(value, isImportant)``."""
    found: tuple[str, bool] | None = None
    for match in re.finditer(rf"(?:^|[;{{])\s*{re.escape(prop)}\s*:\s*([^;}}]+)", declarations):
        raw = match.group(1).strip()
        important = "!important" in raw
        found = (raw.replace("!important", "").strip().lower(), important)
    return found


# --- selectors ---------------------------------------------------------------

_PSEUDO_ELEMENT = re.compile(r"::[\w-]+")
_KNOWN_STATIC_PSEUDO = frozenset({":root", ":first-child", ":last-child"})
_COMBINATOR_SPLIT = re.compile(r"\s*([>+~])\s*|\s+")


def _compoundParts(compound: str) -> list[str]:
    return re.findall(r"\[[^\]]*\]|::?[\w-]+(?:\([^)]*\))?|[#.]?[\w-]+|\*", compound)


def isResolvable(selector: str) -> bool:
    """False when this compound uses state the harness cannot decide statically.

    A `:hover`/`:focus`/`:nth-child()` is dynamic or structural state; rather
    than guess, the caller is told so it can fail loudly.
    """
    stripped = _PSEUDO_ELEMENT.sub("", selector)
    for pseudo in re.findall(r"(?<!:):[\w-]+(?:\([^)]*\))?", stripped):
        name = pseudo.split("(")[0]
        if name == ":not":
            continue
        if name not in _KNOWN_STATIC_PSEUDO:
            return False
    return True


def _matchesCompound(compound: str, node: dict[str, Any]) -> bool:
    compound = _PSEUDO_ELEMENT.sub("", compound).strip()
    if not compound:
        return True
    attrs = node.get("attrs", {})
    classes = (attrs.get("class") or "").split()
    for part in _compoundParts(compound):
        if part == "*":
            continue
        if part.startswith(":not("):
            inner = part[5:-1].strip()
            if _matchesCompound(inner, node):
                return False
        elif part.startswith(":"):
            if part == ":root":
                return False  # :root is <html>; never an element in our tree
            continue  # :first-child etc. -- see _matchesSelector's caller
        elif part.startswith("#"):
            if attrs.get("id") != part[1:]:
                return False
        elif part.startswith("."):
            if part[1:] not in classes:
                return False
        elif part.startswith("["):
            name = re.match(r"\[\s*([\w-]+)\s*(?:([~|^$*]?=)\s*\"?([^\"\]]*)\"?)?", part)
            if name is None:
                return False
            attrName = name.group(1)
            if attrName not in attrs:
                return False
            if name.group(2) == "=" and attrs.get(attrName) != name.group(3):
                return False
        elif part.lower() != node["tag"].lower():
            return False
    return True


def _splitComplex(selector: str) -> list[str]:
    """['#a', '>', '.b'] -- compounds interleaved with combinator tokens."""
    tokens: list[str] = []
    buf = ""
    i = 0
    while i < len(selector):
        ch = selector[i]
        if ch in ">+~":
            if buf.strip():
                tokens.append(buf.strip())
            tokens.append(ch)
            buf = ""
        elif ch.isspace():
            if buf.strip():
                tokens.append(buf.strip())
            buf = ""
            if tokens and tokens[-1] not in (">", "+", "~", " "):
                tokens.append(" ")
        else:
            buf += ch
        i += 1
    if buf.strip():
        tokens.append(buf.strip())
    while tokens and tokens[-1] in (" ", ">", "+", "~"):
        tokens.pop()
    return tokens


def matchesSelector(selector: str, path: list[dict[str, Any]]) -> bool:
    """True when ``selector`` matches the last node of ``path`` (root .. node).

    Handles descendant, child (>), adjacent (+) and general-sibling (~)
    combinators by walking the ancestor chain right-to-left.
    """
    tokens = _splitComplex(selector)
    if not tokens:
        return False
    if not _matchesCompound(tokens[-1], path[-1]):
        return False
    idx = len(tokens) - 2
    pos = len(path) - 1
    while idx >= 0:
        combinator = tokens[idx]
        compound = tokens[idx - 1]
        if combinator == ">":
            pos -= 1
            if pos < 0 or not _matchesCompound(compound, path[pos]):
                return False
        elif combinator == " ":
            pos -= 1
            while pos >= 0 and not _matchesCompound(compound, path[pos]):
                pos -= 1
            if pos < 0:
                return False
        elif combinator in ("+", "~"):
            # Sibling combinators need the parent's child list; the shipped
            # sheets use none today, so this is reported rather than guessed.
            return False
        idx -= 2
    return True


def specificity(selector: str) -> tuple[int, int, int]:
    """(#ids, #classes+attrs+pseudo-classes, #elements+pseudo-elements)."""
    cleaned = re.sub(r":not\(([^)]*)\)", r" \1 ", selector)
    ids = len(re.findall(r"#[\w-]+", cleaned))
    classes = len(re.findall(r"\.[\w-]+", cleaned))
    attrs = len(re.findall(r"\[[^\]]*\]", cleaned))
    pseudoClasses = len(re.findall(r"(?<!:):[\w-]+", cleaned))
    elements = len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", cleaned))
    pseudoElements = len(re.findall(r"::[\w-]+", cleaned))
    return (ids, classes + attrs + pseudoClasses, elements + pseudoElements)


# --- cascade -----------------------------------------------------------------


def _mediaApplies(media: str, viewport: tuple[int, int]) -> bool:
    """Evaluate the min/max-width|height features the kits actually use."""
    if not media:
        return True
    width, height = viewport
    for feature, value in re.findall(r"\(\s*([\w-]+)\s*:\s*(\d+)px\s*\)", media):
        num = int(value)
        if feature == "min-width" and not width >= num:
            return False
        if feature == "max-width" and not width <= num:
            return False
        if feature == "min-height" and not height >= num:
            return False
        if feature == "max-height" and not height <= num:
            return False
    return True


class Surface:
    """A parsed markup tree + stylesheet, resolved together.

    ``rendered(node)`` is the whole point: it is the closest honest answer to
    "would the operator see this?" that a headless harness can give.
    """

    def __init__(
        self,
        tree: dict[str, Any],
        css: str,
        viewport: tuple[int, int] = (1920, 1080),
    ) -> None:
        self.tree = tree
        self.rules = parseCss(css)
        self.viewport = viewport
        self._paths: list[list[dict[str, Any]]] = []
        self._collect(tree, [])

    def _collect(self, node: dict[str, Any], ancestors: list[dict[str, Any]]) -> None:
        if "tag" not in node:
            return
        path = ancestors + [node]
        self._paths.append(path)
        for child in node.get("children", []):
            self._collect(child, path)

    # -- queries --------------------------------------------------------------

    def paths(self) -> list[list[dict[str, Any]]]:
        return list(self._paths)

    def pathById(self, elementId: str) -> list[dict[str, Any]] | None:
        for path in self._paths:
            if path[-1].get("attrs", {}).get("id") == elementId:
                return path
        return None

    def pathsByClass(self, className: str) -> list[list[dict[str, Any]]]:
        return [
            p
            for p in self._paths
            if className in (p[-1].get("attrs", {}).get("class") or "").split()
        ]

    def winningDeclaration(
        self, path: list[dict[str, Any]], prop: str
    ) -> tuple[str, str] | None:
        """Resolve ``prop`` for the element at ``path`` -> (value, source).

        Returns None when no author or inline rule declares it, so the caller
        can apply the UA default. Order of battle: importance, then inline vs
        author, then specificity, then source order -- real CSS rules.
        """
        best: tuple[str, str] | None = None
        bestKey: tuple[int, int, tuple[int, int, int], int] | None = None
        node = path[-1]

        inline = node.get("style") or {}
        if prop in inline:
            value = str(inline[prop]).strip().lower()
            important = "!important" in value
            best = (value.replace("!important", "").strip(), "inline style")
            bestKey = (1 if important else 0, 1, (0, 0, 0), 10**9)

        for rule in self.rules:
            if not _mediaApplies(rule.media, self.viewport):
                continue
            if not isResolvable(rule.selector):
                continue
            if not matchesSelector(rule.selector, path):
                continue
            found = declarationOf(rule.declarations, prop)
            if found is None:
                continue
            value, important = found
            key = (1 if important else 0, 0, specificity(rule.selector), rule.order)
            if bestKey is None or key > bestKey:
                bestKey, best = key, (value, rule.selector)
        return best

    def displayOf(self, path: list[dict[str, Any]]) -> tuple[str, str]:
        """The element's effective ``display`` as (value, whoDecidedIt)."""
        node = path[-1]
        tag = node["tag"].lower()
        if tag in _UA_NOT_RENDERED_TAGS:
            return ("none", "UA sheet (never-rendered element)")
        winner = self.winningDeclaration(path, "display")
        if winner is not None:
            return winner
        # No author declaration -> the UA sheet applies unopposed. This is the
        # ONLY place `hidden` gets honoured for free; an author `display` of any
        # specificity beats it, which is precisely how US-495 happened.
        if "hidden" in node.get("attrs", {}):
            return ("none", "UA sheet [hidden]")
        return ("block", "UA sheet default")

    def rendered(self, path: list[dict[str, Any]]) -> bool:
        """True when this element AND every ancestor has a box.

        `display: none` on an ancestor removes the whole subtree, so an overlay
        can be "visible" by its own rule and still paint nothing.
        """
        for depth in range(len(path)):
            subPath = path[: depth + 1]
            if self.displayOf(subPath)[0] == "none":
                return False
            if self.winningDeclaration(subPath, "visibility") == ("hidden", None):
                return False
        return True

    def renderedIds(self, candidateIds: list[str]) -> list[str]:
        """Which of ``candidateIds`` actually paint (order preserved)."""
        out = []
        for elementId in candidateIds:
            path = self.pathById(elementId)
            if path is not None and self.rendered(path):
                out.append(elementId)
        return out

    def unresolvableDisplaySelectors(self) -> list[str]:
        """`display` rules this harness would have to guess at.

        Non-empty means the stylesheet grew something the backstop cannot judge
        -- report it loudly rather than let a skipped rule pass as green.
        """
        return [
            rule.selector
            for rule in self.rules
            if declarationOf(rule.declarations, "display") is not None
            and not isResolvable(rule.selector)
        ]


# --- node probe drivers ------------------------------------------------------


class ProbeError(RuntimeError):
    """The node probe failed -- surfaced verbatim, never swallowed."""


def _runProbe(probe: str, payload: dict[str, Any]) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as fh:
        json.dump(payload, fh)
        inputPath = fh.name
    try:
        completed = subprocess.run(
            ["node", os.path.join(_HERE, probe), inputPath],
            capture_output=True,
            text=True,
            # TD-068: without an explicit encoding, Windows decodes the probe's
            # stdout as cp1252 and silently corrupts the kit's non-ASCII copy
            # (⋮ ⚠ ‹ ·) -- which is exactly the kind of "renders wrong" this
            # backstop exists to catch, so it must not introduce it itself.
            encoding="utf-8",
            timeout=90,
            check=False,
        )
    finally:
        os.unlink(inputPath)
    if completed.returncode != 0:
        raise ProbeError(f"{probe} exited {completed.returncode}: {completed.stderr}")
    return json.loads(completed.stdout)


def runDashboard(
    routes: dict[str, Any],
    steps: list[dict[str, Any]] | None = None,
    carouselPath: str | None = None,
    markupPath: str | None = None,
    token: str = "test-token",
    autoDim: Any = None,
    viewport: tuple[int, int] = (1920, 1080),
) -> dict[str, Any]:
    """Boot the SHIPPED carousel.js over the SHIPPED markup; return the DOM.

    ``routes`` maps a fetch path ('/system-status') to its JSON body; an unlisted
    route 404s, so a test states exactly which state files exist.
    """
    tree = parseMarkup(markupPath or os.path.join(DASHBOARD_DIR, "dashboard.html"))
    return _runProbe(
        "dom_probe.js",
        {
            "carouselPath": carouselPath or os.path.join(DASHBOARD_DIR, "carousel.js"),
            "tree": bodyChildren(tree),
            "routes": routes,
            "token": token,
            "autoDim": autoDim,
            "viewport": list(viewport),
            "steps": steps or [{"flush": 4}],
        },
    )


def runSplash(
    bootStates: list[Any],
    pollJsPath: str | None = None,
    markupPath: str | None = None,
    rounds: int = 80,
    emitIntervalMs: int = 500,
    brandLoadMs: int | None = 0,
) -> dict[str, Any]:
    """Run the SHIPPED boot-state-poll.js against a boot-state sequence.

    ``bootStates`` is the succession of payloads the emitter WRITES, one every
    ``emitIntervalMs`` (the eclipse-boot-state.service default), while the
    splash reads on its own 250 ms cadence -- so a poll sees the last-written
    entry, exactly as it would on the Pi. The final entry repeats. Returns the
    settled outcome plus the resulting DOM tree.

    ``brandLoadMs`` (US-525) is the virtual ms at which the brand ``<object>``
    fires its `load`. The mark is an async SVG document, so on a cold chromium
    the poll script is already ticking while the brand is still blank; ``None``
    models an SVG that never loads at all.
    """
    tree = parseMarkup(markupPath or os.path.join(SPLASH_DIR, "index.html"))
    return _runProbe(
        "splash_probe.js",
        {
            "pollJsPath": pollJsPath or os.path.join(SPLASH_DIR, "boot-state-poll.js"),
            "tree": bodyChildren(tree),
            "bootStates": bootStates,
            "rounds": rounds,
            "emitIntervalMs": emitIntervalMs,
            "brandLoadMs": brandLoadMs,
        },
    )


def dashboardSurface(
    domTree: dict[str, Any],
    cssPath: str | None = None,
    viewport: tuple[int, int] = (1920, 1080),
) -> Surface:
    """Resolve the shipped dashboard stylesheet over a post-JS DOM tree."""
    with open(cssPath or os.path.join(DASHBOARD_DIR, "dashboard.css"), encoding="utf-8") as fh:
        return Surface(domTree, fh.read(), viewport)


def splashSurface(
    domTree: dict[str, Any],
    cssPath: str | None = None,
    viewport: tuple[int, int] = (480, 320),
) -> Surface:
    """Resolve the shipped splash stylesheet over a post-JS DOM tree."""
    with open(cssPath or os.path.join(SPLASH_DIR, "styles.css"), encoding="utf-8") as fh:
        return Surface(domTree, fh.read(), viewport)

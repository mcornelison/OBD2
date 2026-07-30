################################################################################
# File Name: test_shutdown_splash_render.py
# Purpose/Description: US-498 (S5, F-103) render tests for the closeout
#   (grace-period) shutdown splash. The kit ships ONE shutdown-only override --
#   `animation-direction: reverse` on every class -- on the assumption that "the
#   keyframes are symmetric enough that reverse just works". They are not: the
#   boot timeline ends with a 6s-DELAYED fadeout, and `animation-fill-mode: both`
#   holds the reversed animation's FIRST RELEVANT keyframe during that delay,
#   which for `direction: reverse` is the `to` keyframe -- `opacity: 0`. The mark
#   is therefore INVISIBLE for the first 6 seconds of a 7s grace window
#   (pi.powerWatch.smoothingSec): the operator watches a black screen for the
#   whole shutdown and the animation only begins as the power cuts. That is the
#   trap Iris flagged, and it is what these tests measure.
#
#   These do not grep the stylesheet for a magic string. They RESOLVE the shipped
#   CSS -- cascade (source order + !important), comma-list animation shorthands,
#   fill-mode/direction/delay -- and sample the mark's effective opacity on a
#   clock, so the assertion is about what the operator SEES at second 1, 2, 3...
#   FIDELITY LIMIT (for US-499/S6): timing functions are treated as linear
#   between keyframe stops. Endpoints and the SIGN of a change are exact; a
#   mid-segment value can be off. Every assertion here is about zero-vs-nonzero
#   or an endpoint, which no easing in this kit can change (none overshoot).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-07-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-29    | Ralph (Rex)  | Initial -- US-498 closeout splash render.
# ================================================================================
################################################################################

"""US-498 render tests for the F-103 closeout (shutdown) splash animation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
KIT_DIR = REPO_ROOT / "specs" / "UI" / "dist" / "splash-pi"
CONFIG_PATH = REPO_ROOT / "config.json"

# The PRE_ROLL no-paint window shutdown-state-poll.js enforces before it reveals
# the stage (spec §6). Nothing before this instant is ever seen; everything from
# this instant on is (shutdown-state-poll.js PRE_ROLL_MS = 1000).
PRE_ROLL_S = 1.0

# Sample cadence for the "is anything on screen?" sweep -- finer than a human
# can perceive a gap, coarse enough to keep the test instant.
SAMPLE_STEP_S = 0.25


# ---------------------------------------------------------------------------
# A miniature CSS animation resolver (cascade + timeline), enough for this kit.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Anim:
    """One resolved animation on one element."""

    name: str
    durationS: float
    delayS: float
    fill: str
    direction: str

    @property
    def endS(self) -> float:
        """Wall-clock instant the animation's active period finishes."""
        return self.delayS + self.durationS


def _stripComments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _styleText(svgText: str) -> str:
    """Concatenate every <style> block in document order (CDATA unwrapped).

    Document order is the cascade's tie-breaker, so the shutdown-only override
    block MUST stay last -- concatenating preserves that.
    """
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", svgText, flags=re.DOTALL)
    joined = "\n".join(blocks)
    joined = joined.replace("<![CDATA[", "").replace("]]>", "")
    return _stripComments(joined)


def _topLevelBlocks(css: str) -> list[tuple[str, str]]:
    """Split CSS into ``(prelude, body)`` pairs, brace-depth aware (@keyframes)."""
    blocks: list[tuple[str, str]] = []
    i, n = 0, len(css)
    while i < n:
        open_ = css.find("{", i)
        if open_ == -1:
            break
        prelude = css[i:open_].strip()
        depth, k = 1, open_ + 1
        while k < n and depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        blocks.append((prelude, css[open_ + 1 : k - 1]))
        i = k
    return blocks


def _decls(body: str) -> list[tuple[str, str, bool]]:
    """Parse ``prop: value;`` declarations into ``(prop, value, important)``."""
    out: list[tuple[str, str, bool]] = []
    for chunk in body.split(";"):
        if ":" not in chunk:
            continue
        prop, _, value = chunk.partition(":")
        value = value.strip()
        important = "!important" in value
        value = value.replace("!important", "").strip()
        out.append((prop.strip(), value, important))
    return out


def _resolvedDecls(css: str, selector: str) -> dict[str, str]:
    """Resolve every declaration that applies to ``selector``.

    Every selector in this kit is a single class, so specificity is uniform and
    the cascade reduces to: an !important declaration beats a normal one, and
    otherwise the later source position wins.
    """
    normal: dict[str, str] = {}
    important: dict[str, str] = {}
    for prelude, body in _topLevelBlocks(css):
        if prelude.startswith("@"):
            continue
        if selector not in [s.strip() for s in prelude.split(",")]:
            continue
        for prop, value, isImportant in _decls(body):
            (important if isImportant else normal)[prop] = value
    return {**normal, **important}


def _customProps(css: str) -> dict[str, str]:
    """Collect the ``--name: value`` custom properties declared on :root/svg."""
    props: dict[str, str] = {}
    for prelude, body in _topLevelBlocks(css):
        if prelude.startswith("@") or "svg" not in prelude:
            continue
        for prop, value, _ in _decls(body):
            if prop.startswith("--"):
                props[prop] = value
    return props


def _commaList(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _seconds(value: str) -> float:
    text = value.strip()
    if text.endswith("ms"):
        return float(text[:-2]) / 1000.0
    return float(text.rstrip("s") or 0.0)


def _animations(css: str, selector: str) -> list[_Anim]:
    """Build the resolved animation list for ``selector`` (comma lists cycle)."""
    decls = _resolvedDecls(css, selector)
    names = _commaList(decls.get("animation-name", ""))
    if not names:
        return []
    durations = _commaList(decls.get("animation-duration", "0s"))
    delays = _commaList(decls.get("animation-delay", "0s"))
    fills = _commaList(decls.get("animation-fill-mode", "none"))
    directions = _commaList(decls.get("animation-direction", "normal"))
    return [
        _Anim(
            name=name,
            durationS=_seconds(durations[i % len(durations)]),
            delayS=_seconds(delays[i % len(delays)]),
            fill=fills[i % len(fills)],
            direction=directions[i % len(directions)],
        )
        for i, name in enumerate(names)
    ]


def _keyframeStops(css: str, name: str) -> list[tuple[float, dict[str, str]]]:
    """Return ``(progress, declarations)`` stops for ``@keyframes <name>``."""
    stops: list[tuple[float, dict[str, str]]] = []
    for prelude, body in _topLevelBlocks(css):
        if not prelude.startswith("@keyframes") or prelude.split()[-1] != name:
            continue
        for selectorText, stopBody in _topLevelBlocks(body):
            for marker in _commaList(selectorText):
                if marker == "from":
                    progress = 0.0
                elif marker == "to":
                    progress = 1.0
                else:
                    progress = float(marker.rstrip("%")) / 100.0
                stops.append(
                    (progress, {p: v for p, v, _ in _decls(stopBody)})
                )
    return sorted(stops, key=lambda s: s[0])


def _iterationProgress(anim: _Anim, t: float) -> float | None:
    """Where in its keyframes ``anim`` sits at wall-clock ``t`` (None = no effect).

    Implements the fill-mode rule that the shutdown override trips over: during
    the delay a ``backwards``/``both`` fill applies the FIRST RELEVANT keyframe,
    and for ``direction: reverse`` the first relevant keyframe is ``to`` (100%),
    not ``from``.
    """
    if t < anim.delayS:
        if anim.fill not in ("backwards", "both"):
            return None
        progress = 0.0
    elif t <= anim.endS:
        progress = (t - anim.delayS) / anim.durationS if anim.durationS else 1.0
    else:
        if anim.fill not in ("forwards", "both"):
            return None
        progress = 1.0
    return 1.0 - progress if anim.direction == "reverse" else progress


def _sample(stops: list[tuple[float, dict[str, str]]], prop: str, progress: float) -> float | None:
    """Linearly sample a numeric property across the keyframe stops."""
    points = [
        (p, _numeric(decls[prop]))
        for p, decls in stops
        if prop in decls and _numeric(decls[prop]) is not None
    ]
    if not points:
        return None
    if progress <= points[0][0]:
        return points[0][1]
    for (p0, v0), (p1, v1) in zip(points, points[1:], strict=False):
        if progress <= p1:
            span = p1 - p0
            return v0 if span == 0 else v0 + (v1 - v0) * (progress - p0) / span
    return points[-1][1]


def _numeric(value: str) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group()) if match else None


def valueAt(css: str, selector: str, prop: str, t: float, default: float) -> float:
    """Effective value of ``prop`` on ``selector`` at wall-clock ``t`` seconds."""
    for anim in _animations(css, selector):
        stops = _keyframeStops(css, anim.name)
        if not any(prop in decls for _, decls in stops):
            continue
        progress = _iterationProgress(anim, t)
        if progress is None:
            continue
        sampled = _sample(stops, prop, progress)
        if sampled is not None:
            return sampled
    return default


def brightnessAt(css: str, selector: str, t: float) -> float | None:
    """Effective ``filter: brightness(...)`` on ``selector``, custom props resolved."""
    customProps = _customProps(css)
    for anim in _animations(css, selector):
        stops = _keyframeStops(css, anim.name)
        resolved = [
            (
                p,
                {
                    prop: re.sub(
                        r"var\((--[\w-]+)\)",
                        lambda m: customProps.get(m.group(1), "0"),
                        value,
                    )
                    for prop, value in decls.items()
                },
            )
            for p, decls in stops
        ]
        if not any("filter" in decls for _, decls in resolved):
            continue
        progress = _iterationProgress(anim, t)
        if progress is None:
            continue
        return _sample(resolved, "filter", progress)
    return None


# ---------------------------------------------------------------------------
# Fixtures / grounded inputs
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def shutdownCss() -> str:
    return _styleText((KIT_DIR / "splash-shutdown.svg").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def bootCss() -> str:
    return _styleText((KIT_DIR / "splash.svg").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def graceWindowS() -> float:
    """The real grace window the closeout splash has to fill (config SSOT).

    pi.powerWatch.smoothingSec is the ShutdownSequencer's smoothing window --
    the span between "power lost" and the flush, i.e. exactly the span the
    operator is looking at the closeout splash. Read, never hardcoded, so a
    config change re-aims the test instead of silently invalidating it.
    """
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return float(config["pi"]["powerWatch"]["smoothingSec"])


ANIMATED_CLASSES = (".logo", ".dot", ".s-top", ".s-side")


# ---------------------------------------------------------------------------
# The blank-screen trap (the story's headline defect)
# ---------------------------------------------------------------------------


def test_shutdownSplash_markIsVisibleTheInstantTheStageIsRevealed(shutdownCss):
    """
    Given: shutdown-state-poll.js reveals the stage at PRE_ROLL (1s)
    When: the operator first sees the surface
    Then: the mark is at FULL opacity -- not mid-fade, not blank

    The reveal is a hard cut (visibility:hidden -> visible), so whatever the
    animation is doing at 1.0s is the first frame the operator gets. A closeout
    that is still fading IN at that instant reads as a boot, not a shutdown.
    """
    assert valueAt(shutdownCss, ".logo", "opacity", PRE_ROLL_S, default=1.0) == pytest.approx(1.0)


def test_shutdownSplash_neverGoesBlankDuringTheGraceWindow(shutdownCss, graceWindowS):
    """
    Given: the 7s grace window (pi.powerWatch.smoothingSec)
    When: sampled every 250ms from the PRE_ROLL reveal to the end of grace
    Then: the mark is never fully transparent

    This is the Iris-flagged trap measured directly. With only
    `animation-direction: reverse` and the boot's 6s fadeout delay intact, the
    `both` fill holds the reversed animation's `to` keyframe -- opacity 0 --
    for six of those seconds: a black screen for almost the entire shutdown.
    """
    blank = []
    t = PRE_ROLL_S
    while t <= graceWindowS + 1e-9:
        if valueAt(shutdownCss, ".logo", "opacity", t, default=1.0) <= 0.0:
            blank.append(round(t, 2))
        t += SAMPLE_STEP_S
    assert not blank, (
        "the closeout splash renders a BLANK screen at t="
        f"{blank}s of a {graceWindowS}s grace window"
    )


def test_shutdownSplash_animationCompletesInsideTheGraceWindow(shutdownCss, graceWindowS):
    """
    Given: the mark's animations and the real grace window
    Then: every animation finishes before the window does

    An animation still mid-flight when the flush begins gets cut off by the
    power drop -- the operator sees a frozen half-collapsed mark rather than a
    finished closeout. Sized against the config SSOT, not a literal.
    """
    for selector in ANIMATED_CLASSES:
        for anim in _animations(shutdownCss, selector):
            assert anim.endS <= graceWindowS, (
                f"{selector} '{anim.name}' ends at {anim.endS}s, past the "
                f"{graceWindowS}s grace window"
            )


# ---------------------------------------------------------------------------
# The reversal contract -- the shutdown IS the boot timeline played backwards
# ---------------------------------------------------------------------------


def test_shutdownSplash_everyAnimationRunsInReverse(shutdownCss):
    """
    Given: the shutdown-only override block
    Then: every animated class carries direction:reverse

    Half of the contract (the timing half is the next test). Pinned so a future
    edit cannot quietly drop a class back to the forward boot animation.
    """
    for selector in ANIMATED_CLASSES:
        for anim in _animations(shutdownCss, selector):
            assert anim.direction == "reverse", (
                f"{selector} '{anim.name}' plays FORWARD on the shutdown surface"
            )


def test_shutdownSplash_delaysMirrorTheBootTimeline(shutdownCss, bootCss):
    """
    Given: the boot timeline (splash.svg) is the source of truth for the motion
    Then: each shutdown delay is T - (bootDelay + bootDuration), T = boot total

    Reversing DIRECTION without reversing ORDER is the whole bug: the last thing
    to happen on boot must be the FIRST thing to happen on shutdown. Derived
    from the boot kit rather than asserted as literals, so re-timing the boot
    animation re-aims this test instead of leaving the closeout out of step.
    """
    bootAnims = {
        (selector, anim.name): anim
        for selector in ANIMATED_CLASSES
        for anim in _animations(bootCss, selector)
    }
    totalS = max(anim.endS for anim in bootAnims.values())

    for (selector, name), bootAnim in bootAnims.items():
        shutdownAnim = next(
            a for a in _animations(shutdownCss, selector) if a.name == name
        )
        assert shutdownAnim.delayS == pytest.approx(totalS - bootAnim.endS), (
            f"{selector} '{name}': shutdown delay {shutdownAnim.delayS}s should be "
            f"{totalS} - {bootAnim.endS} = {totalS - bootAnim.endS}s to mirror the boot"
        )


def test_shutdownSplash_dimsDownRatherThanUp(shutdownCss):
    """
    Given: the `light` keyframes ramp brightness UP across the boot
    Then: reversed, the ramp travels max -> low and its envelope only falls

    The name of the surface is 'reverse dim-down'. Note what this does NOT
    claim: the designed throb (a dip and its recovery) genuinely raises
    brightness sample-to-sample, and reversed it lands in the opening beat --
    so "never rises" would be a false claim about a deliberate motion. The
    honest invariant is the ENVELOPE: the closeout's second half is never
    brighter than its first, and it ends at the dimmest value in the kit.
    """
    lightAnim = next(a for a in _animations(shutdownCss, ".logo") if a.name == "light")
    brightMax = float(_customProps(shutdownCss)["--bright-max"])
    brightLow = float(_customProps(shutdownCss)["--bright-low"])

    assert brightnessAt(shutdownCss, ".logo", lightAnim.delayS) == pytest.approx(brightMax)
    assert brightnessAt(shutdownCss, ".logo", lightAnim.endS) == pytest.approx(brightLow)

    samples = []
    t = lightAnim.delayS
    while t <= lightAnim.endS + 1e-9:
        samples.append(brightnessAt(shutdownCss, ".logo", t))
        t += SAMPLE_STEP_S
    half = len(samples) // 2
    assert max(samples[half:]) <= max(samples[:half]), (
        "the closeout gets BRIGHTER as it ends -- that reads as a boot"
    )


# ---------------------------------------------------------------------------
# Control: the boot surface must NOT be re-timed by the shutdown fix
# ---------------------------------------------------------------------------


def test_bootSplash_stillFadesOutAtTheEnd(bootCss):
    """
    Given: the boot animation is untouched by this story
    Then: it still starts visible and fades to nothing at the hand-off

    The control. Both surfaces share splash.svg's keyframes, so a fix applied to
    the wrong file would land here as a boot that starts blank.
    """
    assert valueAt(bootCss, ".logo", "opacity", PRE_ROLL_S, default=1.0) == pytest.approx(1.0)
    assert valueAt(bootCss, ".logo", "opacity", 6.5, default=1.0) == pytest.approx(0.0)

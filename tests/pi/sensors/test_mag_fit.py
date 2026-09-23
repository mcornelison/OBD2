"""ARCH-027: tests for the magnetometer sphere fit.

The fit answers two different questions that a single stationary reading cannot:
the CENTRE of the fitted sphere is the hard-iron offset, and its RADIUS is the
true field strength. A single reading gives |Earth + offset|, which can sit above
or below Earth's field depending on the offset's direction.

🔴 The most important test here is `TestIllConditioned`. My A-30 gate failed
because I fitted a sphere to data from a car on flat ground, which samples a
horizontal CIRCLE. A circle has no vertical extent, the system is singular, and
any radius it returns is an artefact. The fit must REFUSE, not guess.
"""

from __future__ import annotations

import math

import pytest

from pi.sensors.mag_fit import axisRadii, ellipticity, sphereFit


def _spherePoints(
    center: tuple[float, float, float], radius: float, count: int = 200
) -> list[tuple[float, float, float]]:
    """Points spread over a full sphere by golden-angle spiral."""
    points: list[tuple[float, float, float]] = []
    goldenAngle = math.pi * (3.0 - math.sqrt(5.0))
    for i in range(count):
        z = 1.0 - (2.0 * i + 1.0) / count
        r = math.sqrt(max(0.0, 1.0 - z * z))
        theta = goldenAngle * i
        points.append(
            (
                center[0] + radius * r * math.cos(theta),
                center[1] + radius * r * math.sin(theta),
                center[2] + radius * z,
            )
        )
    return points


class TestSphereFit:
    def test_recoversCentreAndRadius_fromCleanData(self) -> None:
        fit = sphereFit(_spherePoints((10.0, -5.0, 3.0), 45.0))
        assert fit.center[0] == pytest.approx(10.0, abs=0.01)
        assert fit.center[1] == pytest.approx(-5.0, abs=0.01)
        assert fit.center[2] == pytest.approx(3.0, abs=0.01)
        assert fit.radius == pytest.approx(45.0, abs=0.01)

    def test_zeroOffsetSphere_recoversOrigin(self) -> None:
        fit = sphereFit(_spherePoints((0.0, 0.0, 0.0), 52.0))
        assert fit.radius == pytest.approx(52.0, abs=0.01)
        assert max(abs(c) for c in fit.center) < 0.01

    def test_residualIsSmallOnCleanData(self) -> None:
        fit = sphereFit(_spherePoints((2.0, 2.0, 2.0), 30.0))
        assert fit.residualRms < 0.01

    def test_survivesModerateNoise(self) -> None:
        """Real readings dither; the fit must not need clean data to be useful."""
        points = _spherePoints((16.0, -2.0, 5.0), 48.0, count=400)
        noisy = [
            (x + 0.3 * math.sin(i), y + 0.3 * math.cos(i), z + 0.3 * math.sin(2 * i))
            for i, (x, y, z) in enumerate(points)
        ]
        fit = sphereFit(noisy)
        assert fit.radius == pytest.approx(48.0, abs=0.5)
        assert fit.center[0] == pytest.approx(16.0, abs=0.5)

    def test_reportsSampleCount(self) -> None:
        fit = sphereFit(_spherePoints((0.0, 0.0, 0.0), 40.0, count=123))
        assert fit.samples == 123


class TestIllConditioned:
    """A fit that cannot be determined must say so, not return a number."""

    def test_flatCircle_refusesToFit(self) -> None:
        """This is the A-30 failure: a car on flat road samples a CIRCLE.

        The vertical component is constant, so the sphere's Z centre and its
        radius are not separately determined. Returning any radius here is how
        a gate ends up unsatisfiable by construction.
        """
        circle = [
            (40.0 * math.cos(t * math.tau / 100), 40.0 * math.sin(t * math.tau / 100), 12.0)
            for t in range(100)
        ]
        with pytest.raises(ValueError, match="span"):
            sphereFit(circle)

    def test_collinearPoints_refuseToFit(self) -> None:
        line = [(float(i), 2.0 * i, 3.0 * i) for i in range(50)]
        with pytest.raises(ValueError, match="span"):
            sphereFit(line)

    def test_tooFewPoints_refuseToFit(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            sphereFit([(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])

    def test_identicalPoints_refuseToFit(self) -> None:
        """A latched sensor returns the same triple forever. That is not a sphere."""
        with pytest.raises(ValueError, match="span"):
            sphereFit([(5.0, 5.0, 5.0)] * 100)


class TestAxisRadii:
    def test_sphereHasEqualAxisRadii(self) -> None:
        radii = axisRadii(_spherePoints((3.0, 3.0, 3.0), 40.0), center=(3.0, 3.0, 3.0))
        assert radii[0] == pytest.approx(radii[1], rel=0.05)
        assert radii[1] == pytest.approx(radii[2], rel=0.05)

    def test_squashedZ_showsSmallerZRadius(self) -> None:
        """Soft iron distorts the sphere into an ellipsoid; this detects that."""
        points = [(x, y, z * 0.5) for x, y, z in _spherePoints((0.0, 0.0, 0.0), 40.0)]
        radii = axisRadii(points, center=(0.0, 0.0, 0.0))
        assert radii[2] < radii[0] * 0.7


class TestEllipticity:
    def test_perfectSphereIsCloseToOne(self) -> None:
        assert ellipticity(_spherePoints((0.0, 0.0, 0.0), 40.0)) == pytest.approx(1.0, abs=0.1)

    def test_squashedSphereExceedsOne(self) -> None:
        points = [(x, y, z * 0.5) for x, y, z in _spherePoints((0.0, 0.0, 0.0), 40.0)]
        assert ellipticity(points) > 1.5

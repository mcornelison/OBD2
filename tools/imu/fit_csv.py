"""ARCH-027: fit a captured rotation CSV, and test whether the fit is trustworthy.

A single sphere fit over a whole capture always returns numbers. Whether those
numbers mean anything is a separate question, and this tool asks it the only way
that works: split the capture into segments, fit each independently, and see
whether they agree.

* **Centres agree across segments** => the hard-iron offset is a stable property
  of the sensor. It can be stored and subtracted.
* **Centres disagree** => the field the sensor saw was not constant during the
  capture, which happens when the sensor is TRANSLATED through a spatially
  varying field (near a car's steel) rather than rotated in place. The offset is
  then an artefact of where it was waved, and storing it would bake in nonsense.

This is the same out-of-sample discipline used on the test-ride heading data:
fit on one part, score on another. A calibration validated only on the data it
was fitted to is not validated.

Usage:
    python3 tools/imu/fit_csv.py path/to/capture.csv [--segments 4]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys

from pi.sensors.mag_fit import ellipticity, sphereFit

# Earth's total field at this latitude. A fitted radius far below this means
# field is being lost (soft iron, or a scale error), which an offset cannot fix.
EARTH_FIELD_UT = 52.0


def loadMagPoints(path: str) -> list[tuple[float, float, float]]:
    points: list[tuple[float, float, float]] = []
    with open(path, newline="") as handle:
        for row in csv.DictReader(handle):
            points.append(
                (float(row["mag_x_ut"]), float(row["mag_y_ut"]), float(row["mag_z_ut"]))
            )
    return points


def _fitSummary(points: list[tuple[float, float, float]]) -> dict[str, object]:
    try:
        fit = sphereFit(points)
    except ValueError as exc:
        return {"refused": str(exc), "samples": len(points)}
    return {
        "centerUt": [round(value, 2) for value in fit.center],
        "centerMagnitudeUt": round(math.sqrt(sum(v * v for v in fit.center)), 2),
        "radiusUt": round(fit.radius, 2),
        "residualRmsUt": round(fit.residualRms, 2),
        "samples": fit.samples,
    }


def _stability(fits: list[dict[str, object]], *, interleaved: bool) -> dict[str, object]:
    """Do independently fitted subsets agree on the centre?"""
    centres = [f["centerUt"] for f in fits if "centerUt" in f]
    if len(centres) < 2:
        return {"verdict": "unavailable", "why": "fewer than two subsets fitted"}
    spread = [
        round(max(c[axis] for c in centres) - min(c[axis] for c in centres), 2)  # type: ignore[index]
        for axis in range(3)
    ]
    worst = max(spread)
    verdict = "stable" if worst < 5.0 else "unstable"
    if interleaved:
        meaning = (
            "hard iron is a fixed property of the sensor; safe to store"
            if verdict == "stable"
            else "even with every subset covering the whole capture, the centre "
            "moves: the field itself was not constant. Do NOT store."
        )
    else:
        meaning = (
            "consecutive stretches agree"
            if verdict == "stable"
            else "consecutive stretches disagree. NOT conclusive on its own: a "
            "one-axis-at-a-time rotation guarantees this, because each stretch "
            "holds a different axis sweep and constrains different components. "
            "Read the interleaved verdict instead."
        )
    return {
        "verdict": verdict,
        "centreSpreadUt": spread,
        "worstAxisSpreadUt": worst,
        "interpretation": meaning,
    }


def analyse(points: list[tuple[float, float, float]], segments: int) -> dict[str, object]:
    """Fit the whole capture, then test the fit two independent ways.

    🔴 The two splits answer DIFFERENT questions, and using the wrong one is how
    a good calibration gets rejected:

    * **sequential** -- consecutive stretches of the capture. Detects the field
      changing over TIME (the sensor being carried through a varying field).
      Useless when the operator rotates one axis at a time, because each stretch
      then contains a different sweep and they must disagree.
    * **interleaved** -- every Nth sample. Every subset spans the WHOLE capture
      and contains all the axis sweeps, so the subsets differ only by noise.
      This is the one that says whether the offset is real.
    """
    overall = _fitSummary(points)
    size = len(points) // segments
    segmentFits = [
        _fitSummary(points[i * size : (i + 1) * size]) for i in range(segments)
    ]
    interleavedFits = [_fitSummary(points[i::segments]) for i in range(segments)]

    radii = [f["radiusUt"] for f in segmentFits if "radiusUt" in f]
    return {
        "overall": overall,
        "segments": segmentFits,
        "interleaved": interleavedFits,
        "stability": _stability(interleavedFits, interleaved=True),
        "stabilitySequential": _stability(segmentFits, interleaved=False),
        "radiusVsEarth": {
            "earthReferenceUt": EARTH_FIELD_UT,
            "segmentRadiiUt": radii,
            "note": (
                "a radius well below Earth's field means field is being LOST "
                "(soft iron or scale error), which subtracting an offset cannot fix"
            ),
        },
        "ellipticity": round(ellipticity(points), 3),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fit and validate a magnetometer capture")
    parser.add_argument("csv")
    parser.add_argument("--segments", type=int, default=4)
    args = parser.parse_args(argv)

    points = loadMagPoints(args.csv)
    print(json.dumps(analyse(points, args.segments), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

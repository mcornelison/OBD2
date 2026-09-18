################################################################################
# File Name: test_ak09916_axis_transform.py
# Purpose/Description: ARCH-033. The AK09916 magnetometer die does NOT share the
#     ICM-20948's accel/gyro axes. We applied no transform, so every heading
#     this project has ever published was computed from a magnetic vector in the
#     wrong frame.
#
# WHY THIS WAS MISSED FOR SO LONG (Atlas, 2026-09-18)
# --------------------------------------------------
# A-30 named this exact hypothesis on 2026-09-09 -- "the AK09916 does not share
# the accel/gyro frame... we apply no transform... latent from day one" -- and
# then recorded that THE DATA REFUTED IT. The data did refute it, because at the
# time the IMU sat on top of the stereo amplifier with a rotating field of
# ~14.7 uT on a ~4 uT noise floor (SNR ~1.2). The axis error could not express
# itself through that. A-30 even predicted the sequel: "It will surface the
# moment SNR is fixed and will look like the original fault returning."
#
# It did. With the IMU remounted on the dash, GPS course as independent truth,
# and two clean laps of the 2026-09-18 drive, a sweep of all 48 axis
# permutations scored (circular concentration R against GPS course):
#
#     identity  -- what shipped         R = 0.170 (lap 1)   0.357 (lap 3)
#     (+y,+x,-z) -- this transform      R = 0.861 (lap 1)   0.878 (lap 3)
#
# (+y,+x,-z) is the documented TDK orientation AND has determinant +1, i.e. it
# is a proper rotation -- which a difference in die orientation must physically
# be. A mirrored candidate scored identically on HEADING only because heading
# uses the horizontal projection; it would be wrong for any other consumer of
# the vector, so the rotation is what ships.
#
# ⚠️ AND IT IS NOT computeHeadingDeg. That function was suspected first and is
# CORRECT: atan2(+left, forward) is a clockwise bearing in a forward/left/up
# frame. Negating it broke four existing tests and was reverted. Nor is it the
# body frame: swapping IMU_BODY_FRAME B <-> identity leaves R unchanged at 0.170
# because a rotation cannot repair a frame error of this kind -- it only moves
# the offset.
#
# Author: Atlas (ARCH-033, CIO-directed)
# Creation Date: 2026-09-18
################################################################################
"""The AK09916's axes must be mapped into the ICM's frame, once, at the seam."""

from __future__ import annotations

import math

import pytest

from pi.sensors.ak09916_bypass import AK09916_TO_ICM_AXES, toIcmFrame


def _det(triples) -> float:
    """Determinant of the 3x3 built from (sourceIndex, sign) per output axis."""
    m = [[0.0] * 3 for _ in range(3)]
    for row, (src, sign) in enumerate(triples):
        m[row][src] = float(sign)
    return (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )


def test_transformIsTheDocumentedOrientation():
    """x<-ak_y, y<-ak_x, z<-(-ak_z)."""
    assert AK09916_TO_ICM_AXES == ((1, 1), (0, 1), (2, -1))


def test_transformIsAProperRotation():
    """🔴 Determinant MUST be +1.

    A die sitting in a different orientation inside one package is a ROTATION.
    A determinant of -1 would be a reflection -- physically unrealisable for a
    rigid part, and it would silently invert every handed quantity downstream
    rather than fail. `pitch_fusion._pitchRate` makes the same demand of
    IMU_BODY_FRAME for the same reason.
    """
    assert _det(AK09916_TO_ICM_AXES) == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ((1.0, 2.0, 3.0), (2.0, 1.0, -3.0)),
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0)),
        ((-5.5, 0.25, -7.0), (0.25, -5.5, 7.0)),
    ],
)
def test_toIcmFrame_mapsComponents(raw, expected):
    assert toIcmFrame(raw) == pytest.approx(expected)


def test_toIcmFrame_preservesMagnitude():
    """A rotation cannot change |B|. If it does, the map is not a rotation."""
    raw = (12.5, -30.25, 48.0)
    assert math.dist((0, 0, 0), toIcmFrame(raw)) == pytest.approx(math.dist((0, 0, 0), raw))


def test_toIcmFrame_isInvolutionFree_butSelfInverse():
    """Applying it twice returns the original.

    Not a requirement, but true of this particular map (swap + one negation),
    and asserting it pins the map: any future edit that changes the transform
    without changing this test would have to break it.
    """
    raw = (3.0, -4.0, 5.0)
    assert toIcmFrame(toIcmFrame(raw)) == pytest.approx(raw)


def test_toIcmFrame_rejectsShortVector():
    with pytest.raises((ValueError, IndexError, TypeError)):
        toIcmFrame((1.0, 2.0))


def test_headingFromRealDriveSamples_tracksGpsAfterTransform():
    """End-to-end sanity on REAL, VERIFIED samples from the 2026-09-18 drive.

    🔴 THE ASSERTION IS ABOUT CONSISTENCY, NOT ABSOLUTE ERROR, AND THAT IS THE
    POINT OF THE TICKET. This transform fixes whether the compass TRACKS. It
    does not, and cannot, fix the absolute offset -- that is IMU_BODY_FRAME,
    which is still set to _B for a mount that no longer exists (ARCH-034). On
    these four samples the residual after transforming is a CONSTANT ~+115 deg;
    a draft of this test asserted mean absolute error would fall, and it
    correctly failed.

    Untransformed the errors scatter (-69.6, +66.9, +21.7, -60.2); transformed
    they cluster (+134.4, +111.9, +72.7, +138.8). Scatter is a compass that does
    not know which way it is pointing. A constant offset is a compass that does,
    wearing the wrong frame.

    ⚠️ An earlier draft also INVENTED the GPS course for its samples. These four
    are extracted from the paired data -- real magnetometer and accelerometer
    readings with the GPS course measured within 0.5 s, all above 4.7 m/s, and
    spread across the compass so no single heading can carry the result.

    ⚠️ Four points are a SANITY check, not the statistical result. That is
    R 0.170 -> 0.861 over two independent laps, recorded in
    offices/architect/evidence/2026-09-18-heading-algorithm-comparison/.
    """
    from pi.sensors.imu_state_bridge import computeHeadingDeg

    # (rawMag uT, accel m/s^2 as the gravity reference, GPS course deg)
    samples = [
        ((10.95, -16.20, 58.20), (0.5746, 0.0000, 10.4315), 5.6),
        ((-20.25, -7.35, 56.40), (0.7374, 1.3192, 10.3908), 144.1),
        ((-20.85, -6.15, 53.70), (0.0096, 0.3160, 8.7269), 179.3),
        ((10.95, -16.20, 58.20), (-0.0407, 0.5602, 8.9064), 359.2),
    ]

    def signedErrors(useTransform):
        errs = []
        for raw, gravity, course in samples:
            vec = toIcmFrame(raw) if useTransform else raw
            h = computeHeadingDeg(gravity, vec)
            assert h is not None
            errs.append((h - course + 180.0) % 360.0 - 180.0)
        return errs

    def concentration(errs):
        """Circular R: 1.0 = every error identical, 0.0 = uniformly scattered."""
        sn = sum(math.sin(math.radians(e)) for e in errs) / len(errs)
        cs = sum(math.cos(math.radians(e)) for e in errs) / len(errs)
        return math.hypot(sn, cs)

    rawR = concentration(signedErrors(False))
    fixedR = concentration(signedErrors(True))
    assert fixedR > rawR + 0.2, (
        f"the transform did not make the heading error consistent: "
        f"R {rawR:.3f} -> {fixedR:.3f}. Tracking is what this ticket fixes; "
        f"the absolute offset is ARCH-034."
    )
    assert fixedR > 0.8, f"transformed heading still does not track (R={fixedR:.3f})"

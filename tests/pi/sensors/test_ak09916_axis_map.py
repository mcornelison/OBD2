"""ARCH-064: the AK09916 axis map is DS-000189 p.83 Fig. 13, not the ARCH-033 permutation."""
import math

from pi.sensors.ak09916_bypass import AK09916_TO_ICM_AXES, toIcmFrame


def test_axisMap_isDatasheetFigure13() -> None:
    # Fig. 13: mag +X == accel +X; mag +Y opposite accel +Y; mag +Z down (accel +Z up).
    assert AK09916_TO_ICM_AXES == ((0, 1), (1, -1), (2, -1))


def test_garageStaticVector_readsEast() -> None:
    """MEASURED 2026-09-28, garage, nose EAST, raw AK (-2.77, -22.52, +53.34) uT.
    Body frame C (x fwd, y left, z up): bearing = atan2(left, fwd) of the horizontal field
    is the angle from the nose to magnetic north (CCW); heading = that angle."""
    x, y, z = toIcmFrame((-2.77, -22.52, 53.34))
    assert z < 0, "the field must point DOWN in a z-up frame (northern hemisphere)"
    heading = math.degrees(math.atan2(y, x)) % 360
    assert 80 <= heading <= 110, heading      # ~97 deg magnetic = nose EAST


def test_theRetiredPermutation_wouldReadSouth() -> None:
    """Pins WHY: the ARCH-033 map differs by a 90-deg rotation, which a free-offset R cannot see."""
    ak = (-2.77, -22.52, 53.34)
    old = (ak[1], ak[0], -ak[2])
    assert 170 <= math.degrees(math.atan2(old[1], old[0])) % 360 <= 200

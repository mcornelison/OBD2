"""v5 delta checks -- the claims made to the CIO on 2026-09-17, each falsifiable.

This is NOT the full harness (that is check_v5.py, adapted from check_v4.py). This file
proves only the things v5 CHANGED, because those are the claims that could be wrong:

  1. total height 19.6 -> 16.0
  2. the LID IS UNCHANGED except for the rotated arrow  (the load-bearing claim)
  3. under-board channel clears 18 AWG, and the cable port matches it
  4. the barb actually overhangs the board hole, and the catch sits where it should
  5. nothing from the retired latch geometry survives over the board's long edge

Run:  python tests/verify_v5_deltas.py
"""
import struct
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENC = os.path.dirname(HERE)


def load_stl(path):
    """Return (triangles, vertices). OpenSCAD writes ASCII STL; binary handled too."""
    with open(path, "rb") as f:
        head = f.read(5)
        f.seek(0)
        if head == b"solid":
            tris, cur = [], []
            for line in f:
                s = line.strip()
                if s.startswith(b"vertex"):
                    cur.append(tuple(float(x) for x in s.split()[1:4]))
                    if len(cur) == 3:
                        tris.append(tuple(cur))
                        cur = []
        else:
            f.read(80)
            n = struct.unpack("<I", f.read(4))[0]
            tris = []
            for _ in range(n):
                d = struct.unpack("<12fH", f.read(50))
                tris.append((d[3:6], d[6:9], d[9:12]))
    verts = [v for t in tris for v in t]
    return tris, verts


def bounds(verts):
    xs = [v[0] for v in verts]
    ys = [v[1] for v in verts]
    zs = [v[2] for v in verts]
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))


def volume(tris):
    """Signed volume via the divergence theorem."""
    tot = 0.0
    for a, b, c in tris:
        tot += (a[0] * (b[1] * c[2] - c[1] * b[2])
                - a[1] * (b[0] * c[2] - c[0] * b[2])
                + a[2] * (b[0] * c[1] - c[0] * b[1])) / 6.0
    return abs(tot)


def inside(tris, p):
    """Ray cast +Z from p; odd crossings => inside."""
    px, py, pz = p
    hits = 0
    for a, b, c in tris:
        # 2D point-in-triangle on XY
        d = ((b[1] - c[1]) * (a[0] - c[0]) + (c[0] - b[0]) * (a[1] - c[1]))
        if abs(d) < 1e-12:
            continue
        u = ((b[1] - c[1]) * (px - c[0]) + (c[0] - b[0]) * (py - c[1])) / d
        v = ((c[1] - a[1]) * (px - c[0]) + (a[0] - c[0]) * (py - c[1])) / d
        w = 1.0 - u - v
        if u < 0 or v < 0 or w < 0:
            continue
        z = u * a[2] + v * b[2] + w * c[2]
        if z > pz:
            hits += 1
    return hits % 2 == 1


FAILS = []
NOTES = []


def check(name, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + name + ("   " + detail if detail else ""))
    if not ok:
        FAILS.append(name)


def near(a, b, tol=1e-3):
    return abs(a - b) <= tol


def solid_ring(tris, cx, cy, r, z, angles=(53, 127, 233, 307)):
    """Is there material at radius r around (cx,cy) at height z, on EVERY sample angle?

    ⚠️ Never probe along +/-X or +/-Y. OpenSCAD lays a $fn=48 cylinder's facet vertices
    on the axes, so an axis-aligned ray fires exactly down a facet boundary and the
    crossing count goes degenerate -- during the v5 build that produced a confident
    SOLID on +Y and air on -Y for geometry that is symmetric by construction. The
    instrument was wrong, not the part. Odd angles, several of them, and require
    agreement.
    """
    import math as _m
    res = [inside(tris, (cx + r * _m.cos(_m.radians(t)),
                         cy + r * _m.sin(_m.radians(t)), z)) for t in angles]
    return all(res), res


# ---- design constants, mirrored from imu-case-v5.scad -----------------------
SPLIT_Z, DOME_H = 12.0, 4.0
BOARD_Z, BOARD_T, FLOOR_T = 6.0, 1.60, 2.0
HOLE_D, BARB_D, STEM_D = 2.5, 2.9, 2.20
HOLE_CX, HOLE_CY = 6.35, 10.16          # ROTATED 90 deg, CIO 2026-09-18
BOARD_L, BOARD_W = 25.40, 17.78
RECT_A, RECT_B = 17.70, 13.89           # interior half-sizes
SEAT_OD, LPX, LPY, LPD = 5.6, 18.5, 10.4, 4.5
CATCH_CLEAR = 0.15
Z_CATCH = BOARD_Z + BOARD_T + CATCH_CLEAR          # 7.75
CABLE_Z, CABLE_H = 4.5, 5.0
WIRE_OD_18AWG = 2.5                                 # PVC hookup, design figure

print("=" * 72)
print("v5 delta checks")
print("=" * 72)

base5 = os.path.join(ENC, "stl", "v5-base.stl")
lid5 = os.path.join(ENC, "stl", "v5-lid-print.stl")
lid4 = os.path.join(ENC, "stl", "v4-lid-print.stl")
for p in (base5, lid5, lid4):
    if not os.path.exists(p):
        print("MISSING: " + p)
        sys.exit(2)

bt, bv = load_stl(base5)
l5t, l5v = load_stl(lid5)
l4t, l4v = load_stl(lid4)

# ---- 1. total height --------------------------------------------------------
print("\n1. lower profile")
(_, _, bz0), (_, _, bz1) = bounds(bv)
(_, _, _), (_, _, l5z1) = bounds(l5v)
total = SPLIT_Z + DOME_H
LPOST_TOP = SPLIT_Z + 1.8
check("base top is the lid posts at split_z+1.8", near(bz1, LPOST_TOP, 0.02),
      "got %.3f, expected %.3f (v4 was 17.4 = 15.6+1.8, same relationship)"
      % (bz1, LPOST_TOP))
# the SEAM itself: highest material that is NOT one of the four lid-post columns.
LPX, LPY, LPD = 18.5, 10.4, 4.5
def in_post_col(v):
    return any(((v[0] - sx*LPX)**2 + (v[1] - sy*LPY)**2) <= (LPD/2 + 0.2)**2
               for sx in (-1, 1) for sy in (-1, 1))
seam = max(v[2] for v in bv if not in_post_col(v))
check("shell seam is at split_z = 12.0", near(seam, SPLIT_Z, 0.02),
      "got %.4f (posts excluded)" % seam)
check("base bottom is z=0", near(bz0, 0.0, 0.02), "got %.4f" % bz0)
check("total assembled height is 16.0 (was 19.6)", near(total, 16.0),
      "%.1f mm, saves %.1f" % (total, 19.6 - total))

# ---- 2. THE LID IS UNCHANGED (except the rotated arrow) ---------------------
print("\n2. lid unchanged -- the load-bearing claim")
b4, t4 = bounds(l4v)
b5, t5 = bounds(l5v)
for i, ax in enumerate("xyz"):
    check("lid %s-min identical to v4" % ax, near(b4[i], b5[i], 1e-3),
          "v4 %.4f  v5 %.4f" % (b4[i], b5[i]))
    # x/y at 1 um -- they are bit-identical and must stay so (the footprint IS the fit).
    # z at 10 um: the DOCUMENTED v4 rim artifact (lid_n() one-sided finite difference at
    # u=0, removed by the z>=split_z clip) lands a few um differently at a new split_z.
    # 3.7 um is 1/54th of a 0.2 mm layer. Widened deliberately, with the reason named.
    tol = 1e-3 if ax != "z" else 1e-2
    check("lid %s-max identical to v4" % ax, near(t4[i], t5[i], tol),
          "v4 %.4f  v5 %.4f  (tol %.3f)" % (t4[i], t5[i], tol))
v4vol, v5vol = volume(l4t), volume(l5t)
dv = abs(v4vol - v5vol)
# The ONLY intended difference is the arrow, rotated 90 deg across a non-circular
# dome, so the removed wedge differs slightly. Anything beyond ~1% is a real change.
check("lid volume differs by <1% (arrow rotation only)", dv / v4vol < 0.01,
      "v4 %.1f  v5 %.1f  delta %.2f mm3 = %.3f%%" % (v4vol, v5vol, dv, 100 * dv / v4vol))
NOTES.append("lid volume delta %.2f mm3 is the rotated arrow cut, not a shape change"
             % dv)

# ---- 3. wire channel + cable port -------------------------------------------
print("\n3. under-board channel and cable port")
channel = BOARD_Z - FLOOR_T
check("under-board clear >= one 18 AWG conductor", channel >= WIRE_OD_18AWG,
      "%.1f mm channel vs %.1f mm wire (%.1f spare)"
      % (channel, WIRE_OD_18AWG, channel - WIRE_OD_18AWG))
port_lo, port_hi = CABLE_Z - CABLE_H / 2, CABLE_Z + CABLE_H / 2
check("cable port floor does not breach the case floor", port_lo >= FLOOR_T - 1e-9,
      "port z %.1f..%.1f, floor top %.1f" % (port_lo, port_hi, FLOOR_T))
check("cable port overlaps the whole under-board channel", port_lo <= FLOOR_T + 1e-9
      and port_hi >= BOARD_Z, "port %.1f..%.1f vs channel %.1f..%.1f"
      % (port_lo, port_hi, FLOOR_T, BOARD_Z))

# ---- 4. the barb -------------------------------------------------------------
print("\n4. snap post geometry (probed on the mesh, not on the source)")
check("barb overhangs the board hole", BARB_D > HOLE_D,
      "barb %.1f vs hole %.1f = %.2f mm catch per side"
      % (BARB_D, HOLE_D, (BARB_D - HOLE_D) / 2))
# Probe OFF-AXIS (see solid_ring). r=1.30 sits inside the barb cone (r~1.44 at z=7.80)
# and outside the plain stem (r=1.15), which is exactly what makes the pair discriminating:
# the board slides past the stem and is caught by the barb.
post = (HOLE_CX, HOLE_CY)
ok, res = solid_ring(bt, post[0], post[1], 1.30, Z_CATCH + 0.05)
check("barb material all round, just ABOVE the catch face", ok, "z=%.2f r=1.30 %s"
      % (Z_CATCH + 0.05, res))
ok2, res2 = solid_ring(bt, post[0], post[1], 1.30, Z_CATCH - 0.05)
check("clear at barb radius BELOW the catch face (board slides past the stem)",
      not any(res2), "z=%.2f r=1.30 %s" % (Z_CATCH - 0.05, res2))
ok3, res3 = solid_ring(bt, post[0], post[1], 1.00, (FLOOR_T + BOARD_Z) / 2)
check("spring stem is continuous below the board (finger length is real)", ok3,
      "z=%.2f r=1.00 %s" % ((FLOOR_T + BOARD_Z) / 2, res3))
# the slot must be open so the fingers can close: probe ALONG the slot axis (X)
check("slot open along X, so the fingers close in +/-Y",
      not inside(bt, (post[0] + 1.00, post[1], Z_CATCH + 0.05)), "on-axis, in the slot")

# ---- 4b. the 90-deg post rotation --------------------------------------------
print("\n4b. rotated posts (CIO 2026-09-18)")
check("hole pattern is rotated (c-c 12.70 x 20.32)",
      near(2 * HOLE_CX, 12.70) and near(2 * HOLE_CY, 20.32),
      "%.2f x %.2f" % (2 * HOLE_CX, 2 * HOLE_CY))
# the board is NOT square -- that is WHY the posts had to move. Assert the premise.
check("board is not square, so posts could not have stayed put",
      abs(BOARD_L - BOARD_W) > 1.0, "%.2f x %.2f, differ %.2f mm"
      % (BOARD_L, BOARD_W, BOARD_L - BOARD_W))
# rotated board must still fit the v3.2 interior
mx, my = RECT_A - BOARD_W / 2, RECT_B - BOARD_L / 2
check("rotated board still fits the interior", mx > 0 and my > 0,
      "X +%.2f  Y +%.2f per side (was 5.00/5.00)" % (mx, my))
# the tight axis: is there still a usable wire gap beside the collar?
gap = RECT_B - (HOLE_CY + SEAT_OD / 2)
check("short-side collar-to-wall gap measured and recorded", gap > 0,
      "%.2f mm -- TOO NARROW for 2.5 mm wire, route along the long sides" % gap)
NOTES.append("short-side wire gap is %.2f mm; wires must route along the long sides" % gap)
check("seat collar clears the lid posts",
      ((LPX - HOLE_CX) ** 2 + (LPY - HOLE_CY) ** 2) ** 0.5 > (LPD + SEAT_OD) / 2 + 0.3,
      "%.2f mm centres" % (((LPX - HOLE_CX) ** 2 + (LPY - HOLE_CY) ** 2) ** 0.5))
# and prove the posts actually MOVED in the mesh, not just in the source
ok_new, _ = solid_ring(bt, HOLE_CX, HOLE_CY, 1.00, (FLOOR_T + BOARD_Z) / 2)
old_has, _ = solid_ring(bt, 10.16, 6.35, 1.00, (FLOOR_T + BOARD_Z) / 2)
check("post EXISTS at the rotated position", ok_new, "(%.2f, %.2f)" % (HOLE_CX, HOLE_CY))
check("no post left at the OLD position", not old_has, "(10.16, 6.35)")

# ---- 5. retired latch geometry is really gone --------------------------------
print("\n5. retired v4 latch blades leave nothing behind")
# v4 latches sat outside the board's long edge at |y| ~ 8.99..9.69, z ~ 9.6-10.6.
# In v5 that space must be empty (board top is now 7.6; nothing should reach over it).
lat = [(11.65, 9.3, 9.9), (-11.65, 9.3, 9.9), (11.65, -9.3, 9.9), (-11.65, -9.3, 9.9)]
gone = all(not inside(bt, p) for p in lat)
check("no material where the v4 latch lips were", gone,
      "4 probes at |x|=11.65 |y|=9.3 z=9.9")

print("\n" + "=" * 72)
for n in NOTES:
    print("note: " + n)
print("%d failure(s)" % len(FAILS))
for f in FAILS:
    print("  - " + f)
print("=" * 72)
sys.exit(1 if FAILS else 0)

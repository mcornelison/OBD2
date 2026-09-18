"""IMU enclosure v4 verification (spec: specs/imu-case-v4-design.md §7).

Usage:  python tests/check_v4.py base-shell lid-shell base lid
Every check prints PASS/FAIL. Exit code 1 if anything failed.
"""
import pathlib
import sys

import numpy as np
import trimesh
from shapely.geometry import Polygon

ROOT = pathlib.Path(__file__).resolve().parents[1]
STL = ROOT / "stl"

# ---- spec numbers (independent copy on purpose: this is the oracle) ----
WALL = 2.0
FLOOR = 2.0
SPLIT = 15.6
DOME = 4.0
RECT_A, RECT_B = 17.70, 13.89
FOOT_X, FOOT_Y = 68.6, 58.4
SPLIT_X, SPLIT_Y = 52.6, 42.4
HOLES = [(sx * 10.16, sy * 6.35) for sx in (-1, 1) for sy in (-1, 1)]
BOARD_Z = 8.0
PIN_TOP = 10.6
LPOSTS = [(sx * 18.5, sy * 10.4) for sx in (-1, 1) for sy in (-1, 1)]
LPOST_TOP = 17.4
SOCKET_TOP = 2.0          # in lid print orientation (split plane -> z=0)
SKIN_MIN = 0.8
DIM_TOL = 0.4

FAILS = []


def check(name, cond, detail=""):
    print(("PASS  " if cond else "FAIL  ") + name + (f"   [{detail}]" if detail else ""))
    if not cond:
        FAILS.append(name)


def load(fname):
    path = STL / fname
    if not path.exists():
        check(f"{fname} exists", False, "render it first")
        return None
    return trimesh.load_mesh(path, process=True)


def solid_ok(m, fname):
    check(f"{fname} watertight", m.is_watertight)
    check(f"{fname} winding consistent", m.is_winding_consistent)
    check(f"{fname} positive volume", m.volume > 0, f"{m.volume:.1f} mm3")
    check(f"{fname} single body", len(m.split(only_watertight=False)) == 1)


def first_hit(m, origin, direction):
    locs, _, _ = m.ray.intersects_location([origin], [direction], multiple_hits=True)
    if len(locs) == 0:
        return None
    d = np.linalg.norm(locs - np.asarray(origin), axis=1)
    return float(d.min())


def wall_thickness(m, zmin, zmax):
    v = m.vertices
    n = m.vertex_normals
    sel = (v[:, 2] > zmin) & (v[:, 2] < zmax)
    origins = v[sel] - 0.01 * n[sel]
    dirs = -n[sel]
    locs, idx, _ = m.ray.intersects_location(origins, dirs, multiple_hits=True)
    best = np.full(len(origins), np.inf)
    dist = np.linalg.norm(locs - origins[idx], axis=1)
    np.minimum.at(best, idx, dist)
    best = best[np.isfinite(best)] + 0.01
    return best


def wall_thickness_detail(t):
    if t.size == 0:
        return "no samples"
    return f"n={t.size} min={t.min():.3f} max={t.max():.3f}"


def section_poly(m, z):
    sec = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        return []
    planar, _ = sec.to_2D(to_2D=np.eye(4))
    return planar.polygons_full


# ---------------------------------------------------------------- groups
def group_base_shell():
    m = load("v4-base-shell.stl")
    if m is None:
        return
    solid_ok(m, "base-shell")
    lo, hi = m.bounds
    ext = hi - lo
    check("base-shell lowest z = 0", abs(lo[2]) < 1e-3, f"{lo[2]:.4f}")
    check("base-shell top z = split", abs(hi[2] - SPLIT) < 0.02, f"{hi[2]:.3f}")
    check("base-shell footprint", abs(ext[0] - FOOT_X) < DIM_TOL and abs(ext[1] - FOOT_Y) < DIM_TOL,
          f"{ext[0]:.2f} x {ext[1]:.2f}")
    polys = section_poly(m, 0.05)
    check("flat bottom: one solid slice at z=0.05, no holes",
          len(polys) == 1 and len(polys[0].interiors) == 0, f"{len(polys)} polygon(s)")
    # v3.2 interior rectangle, expanded 0.45, must be clear of the shell at every height
    pts = []
    for z in np.arange(FLOOR + 0.1, SPLIT - 0.05, 0.5):
        for x in np.linspace(-RECT_A - 0.45, RECT_A + 0.45, 25):
            pts += [(x, RECT_B + 0.45, z), (x, -RECT_B - 0.45, z)]
        for y in np.linspace(-RECT_B - 0.45, RECT_B + 0.45, 19):
            pts += [(RECT_A + 0.45, y, z), (-RECT_A - 0.45, y, z)]
    inside = m.contains(np.array(pts))
    check("v3.2 interior fits with >= 0.45 mm margin", not inside.any(), f"{int(inside.sum())} intrusions")
    # RULING: sample band moved to FLOOR + 2.5 -> SPLIT - 0.2. Just above the floor the outer
    # wall is flared ~45 deg, so an inward ray from an outer vertex there crosses into the solid
    # floor and measures floor thickness, not wall thickness (false fail ~3.7 mm).
    t = wall_thickness(m, FLOOR + 2.5, SPLIT - 0.2)
    check("base wall 2.0 +/- 0.1 normal to surface",
          t.size > 0 and t.min() > WALL - 0.1 and t.max() < WALL + 0.1, wall_thickness_detail(t))


def group_lid_shell():
    m = load("v4-lid-shell.stl")
    b = load("v4-base-shell.stl")
    if m is None:
        return
    solid_ok(m, "lid-shell")
    lo, hi = m.bounds
    ext = hi - lo
    check("lid-shell sits on split plane", abs(lo[2] - SPLIT) < 0.02, f"{lo[2]:.3f}")
    check("lid-shell apex at 19.6", abs(hi[2] - (SPLIT + DOME)) < 0.02, f"{hi[2]:.3f}")
    check("lid-shell size at split", abs(ext[0] - SPLIT_X) < DIM_TOL and abs(ext[1] - SPLIT_Y) < DIM_TOL,
          f"{ext[0]:.2f} x {ext[1]:.2f}")
    t = wall_thickness(m, SPLIT + 0.3, SPLIT + DOME + 1)
    check("lid wall 2.0 +/- 0.1 normal to surface",
          t.size > 0 and t.min() > WALL - 0.1 and t.max() < WALL + 0.1, wall_thickness_detail(t))
    if b is not None:
        pl = section_poly(m, SPLIT + 0.02)
        pb = section_poly(b, SPLIT - 0.02)
        ok = len(pl) == 1 and len(pb) == 1 and abs(pl[0].area - pb[0].area) / pb[0].area < 0.01
        check("seam: lid rim ring matches base rim ring", ok,
              f"lid {pl[0].area if pl else 0:.1f} vs base {pb[0].area if pb else 0:.1f} mm2")


def group_base():
    m = load("v4-base.stl")
    s = load("v4-base-shell.stl")
    if m is None:
        return
    solid_ok(m, "base")
    lo, hi = m.bounds
    check("base lowest z = 0", abs(lo[2]) < 1e-3, f"{lo[2]:.4f}")
    check("base top = lid-post tops (17.4)", abs(hi[2] - LPOST_TOP) < 0.02, f"{hi[2]:.3f}")
    if s is not None:
        for z in (1.0, 12.0, 15.0):
            a = section_poly(m, z)
            b = section_poly(s, z)
            ea = max(Polygon(p.exterior).area for p in a) if a else 0
            eb = max(Polygon(p.exterior).area for p in b) if b else 0
            check(f"nothing breaks the outer skin at z={z}", eb > 0 and abs(ea - eb) / eb < 0.005,
                  f"{ea:.1f} vs {eb:.1f}")
    for hx, hy in HOLES:
        sx = np.sign(hx)
        z = first_hit(m, (hx + sx * 1.9, hy, 30.0), (0, 0, -1))
        check(f"shoulder at z=8.0 @({hx:+.2f},{hy:+.2f})", z is not None and abs((30.0 - z) - BOARD_Z) < 0.03,
              "none" if z is None else f"{30.0 - z:.3f}")
        z = first_hit(m, (hx, hy, 30.0), (0, 0, -1))
        check(f"pin tip at z=10.6 @({hx:+.2f},{hy:+.2f})", z is not None and abs((30.0 - z) - PIN_TOP) < 0.05,
              "none" if z is None else f"{30.0 - z:.3f}")
    probes_in, probes_out = [], []
    for sx in (-1, 1):
        for sy in (-1, 1):
            probes_in += [(sx * 11.65, sy * 8.7, 10.0), (sx * 11.65, sy * 9.3, 9.0)]
            probes_out += [(sx * 11.65, sy * 8.7, 9.3)]
    check("latch lip + blade present at all 4 corners", m.contains(np.array(probes_in)).all())
    check("space under each lip is clear for the board", not m.contains(np.array(probes_out)).any())
    grid = []
    for x in np.arange(-12.5, 12.51, 1.0):
        for y in np.arange(-8.7, 8.71, 0.87):
            if min(np.hypot(x - hx, y - hy) for hx, hy in HOLES) < 1.3:
                continue
            for z in (8.3, 9.0, 9.5):
                grid.append((x, y, z))
    hits = m.contains(np.array(grid))
    check("board volume clear (except pins)", not hits.any(), f"{int(hits.sum())} intrusions")
    hole = first_hit(m, (0.0, -60.0, 5.0), (0, 1, 0))
    check("cable exit open through -Y wall at z=5", hole is not None and hole > 30,
          "none" if hole is None else f"first hit {hole:.1f} mm in")


def group_lid():
    m = load("v4-lid-print.stl")
    if m is None:
        return
    solid_ok(m, "lid")
    lo, hi = m.bounds
    ext = hi - lo
    check("lid print: rim on bed (z=0)", abs(lo[2]) < 1e-3, f"{lo[2]:.4f}")
    check("lid print: height 4.0", abs(ext[2] - DOME) < 0.02, f"{ext[2]:.3f}")
    check("lid print: footprint", abs(ext[0] - SPLIT_X) < DIM_TOL and abs(ext[1] - SPLIT_Y) < DIM_TOL,
          f"{ext[0]:.2f} x {ext[1]:.2f}")
    for px, py in LPOSTS:
        d = first_hit(m, (px, py, -1.0), (0, 0, 1))
        top = None if d is None else d - 1.0
        check(f"socket top at 2.0 @({px:+.1f},{py:+.1f})", top is not None and abs(top - SOCKET_TOP) < 0.03,
              "none" if top is None else f"{top:.3f}")
        skins = []
        missing = 0
        for a in np.linspace(0, 2 * np.pi, 9)[:-1]:
            ox, oy = px + 2.2 * np.cos(a), py + 2.2 * np.sin(a)
            s = first_hit(m, (ox, oy, SOCKET_TOP + 0.01), (0, 0, 1))
            if s is None:
                missing += 1
            else:
                skins.append(s + 0.01)
        s0 = first_hit(m, (px, py, SOCKET_TOP + 0.01), (0, 0, 1))
        if s0 is None:
            missing += 1
        else:
            skins.append(s0 + 0.01)
        # a missing ray means no material at all above that point (worse than thin) -- it
        # must fail, not vanish into an np.inf that would make min(skins) >= SKIN_MIN vacuously true
        ok = missing == 0 and bool(skins) and min(skins) >= SKIN_MIN
        detail = f"{missing}/9 ray(s) hit nothing above the socket" if missing else f"min {min(skins):.2f}"
        check(f"skin above socket >= 0.8 @({px:+.1f},{py:+.1f})", ok, detail)


GROUPS = {"base-shell": group_base_shell, "lid-shell": group_lid_shell, "base": group_base, "lid": group_lid}

if __name__ == "__main__":
    names = sys.argv[1:] or list(GROUPS)
    for g in names:
        print(f"\n== {g} ==")
        GROUPS[g]()
    print(f"\n{len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)

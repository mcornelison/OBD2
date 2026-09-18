# IMU Enclosure v4 (dash-top flared pebble) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a parametric OpenSCAD model, verified STLs and (if the CLI cooperates) Bambu Studio slices for the v4 ICM-20948 enclosure: a flared-pebble shell with a uniform 2 mm wall, tapered-pin board posts, in-plane PLA latches on corner posts, and a press-fit domed lid.

**Architecture:** One new source file `case-imu-icm20948/imu-case-v4.scad`. The curved shell is built as `polyhedron`s from stacked rings of true 2D offsets of one superellipse (base) and a normal-offset roll+crown surface (lid). Features are ordinary CSG added to or cut from those shells. A Python/trimesh script renders nothing itself; it checks the STLs OpenSCAD writes against the spec's §7 rules. Shell-only parts (6, 7) exist purely as test oracles.

**Tech Stack:** OpenSCAD 2021.01 (`C:\Program Files\OpenSCAD\openscad.exe`), Python 3.13 + numpy 2.4 + trimesh 5.0 + shapely 2.1 (+ `rtree`, installed in Task 1), Bambu Studio CLI (`C:\Program Files\Bambu Studio\bambu-studio.exe`), git-bash.

**Spec:** `case-imu-icm20948/specs/imu-case-v4-design.md` — read it first; this plan argues from it.

## Global Constraints

- Frame: **+X = board long axis = car FORWARD**, +Y left, +Z up; Z=0 = outer bottom face; XY origin = centre of the interior.
- Board 25.40 × 17.78 × 1.60; hole centres (±10.16, ±6.35); `hole_d` default **2.5** (uncalibrated).
- v3.2 interior 35.40 × 27.78, z **2.0 → 15.6**; board underside z **8.0**; cable exit obround **11 × 5**, −Y, centre z **5.0**.
- Wall **2.0 mm normal to the surface**, everywhere; floor 2.0 solid; bottom **flat, no recess**; no mounting tabs.
- CIO proportions: **flare 8.00 · dome 4.00 · n 2.4**. Fit margin 0.5; foot band 0.8.
- Lid dome = roll (w 3.4, h 3.0) + crown (1.0). Split z 15.6. Overall 19.6.
- Latches on corner lid posts, flex in Y; lip 0.4 over the board, tip |x| 10.9–12.4.
- Lid posts Ø4.5 at (±18.5, ±10.4) to z 17.4; lid sockets Ø4.5 to split + 2.0; ≥ 0.8 mm skin above.
- Material PLA; printer Bambu Lab P2S, 0.4 nozzle.
- **Never overwrite an existing file.** Every output of this plan is a new path. v3.2 files (`imu-case.scad`, `stl/box.stl`, `stl/lid-print.stl`, `slicer/*`) are read-only.
- **No git.** This share is not version-controlled; there are no commit steps. Durability = the files themselves.
- Paths below are relative to `Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948/`. OpenSCAD alias used in commands:
  `SCAD="/c/Program Files/OpenSCAD/openscad.exe"`.

## File map

| File | Responsibility | Task |
|---|---|---|
| `tests/check_v4.py` | Verification oracle — spec §7 as executable checks, grouped | 1 |
| `imu-case-v4.scad` | Parameters, shell maths, shells, features, asserts, part dispatch | 2–5 |
| `stl/v4-base-shell.stl`, `stl/v4-lid-shell.stl` | Test oracles (parts 6, 7) | 2, 3 |
| `stl/v4-base.stl`, `stl/v4-lid-print.stl` | Print targets (parts 1, 4) | 4, 5 |
| `renders/v4_*.png` | Previews | 6 |
| `slicer/v4-base.3mf`, `slicer/v4-lid.3mf` | Bambu P2S slices (conditional) | 6 |
| spec §7 results + two A2AL notes | Record + hand-offs | 7 |

---

### Task 1: Verification harness

**Files:**
- Create: `tests/check_v4.py`

**Interfaces:**
- Consumes: STL files named in the File map (absent until later tasks).
- Produces: `python tests/check_v4.py <group> [<group> ...]`, groups `base-shell`, `lid-shell`, `base`, `lid`. Exit 0 iff every check in the named groups passes; prints one `PASS`/`FAIL` line per check. A missing STL for a named group is a `FAIL`.

- [ ] **Step 1: Install the ray-casting dependency**

trimesh's `contains` / `ray.intersects_location` need `rtree` when embree is absent.

Run: `python -m pip install rtree`
Then: `python -c "import rtree, trimesh; print('ok')"`
Expected: `ok`

- [ ] **Step 2: Write the harness**

Create `tests/check_v4.py`:

```python
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


def section_poly(m, z):
    sec = m.section(plane_origin=[0, 0, z], plane_normal=[0, 0, 1])
    if sec is None:
        return []
    planar, _ = sec.to_planar(to_2D=np.eye(4))
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
    t = wall_thickness(m, FLOOR + 0.2, SPLIT - 0.2)
    check("base wall 2.0 +/- 0.1 normal to surface", t.size > 0 and t.min() > 1.9 and t.max() < 2.1,
          f"n={t.size} min={t.min():.3f} max={t.max():.3f}")


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
    check("lid wall 2.0 +/- 0.1 normal to surface", t.size > 0 and t.min() > 1.9 and t.max() < 2.1,
          f"n={t.size} min={t.min():.3f} max={t.max():.3f}")
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
        for a in np.linspace(0, 2 * np.pi, 9)[:-1]:
            ox, oy = px + 2.2 * np.cos(a), py + 2.2 * np.sin(a)
            s = first_hit(m, (ox, oy, SOCKET_TOP + 0.01), (0, 0, 1))
            skins.append(np.inf if s is None else s + 0.01)
        s0 = first_hit(m, (px, py, SOCKET_TOP + 0.01), (0, 0, 1))
        skins.append(np.inf if s0 is None else s0 + 0.01)
        check(f"skin above socket >= 0.8 @({px:+.1f},{py:+.1f})", min(skins) >= SKIN_MIN, f"min {min(skins):.2f}")


GROUPS = {"base-shell": group_base_shell, "lid-shell": group_lid_shell, "base": group_base, "lid": group_lid}

if __name__ == "__main__":
    names = sys.argv[1:] or list(GROUPS)
    for g in names:
        print(f"\n== {g} ==")
        GROUPS[g]()
    print(f"\n{len(FAILS)} failure(s)")
    sys.exit(1 if FAILS else 0)
```

- [ ] **Step 3: Confirm the trimesh section API, then prove the harness fails with no geometry**

trimesh 5 renamed `Path3D.to_planar` → `to_2D`. Run:
`python -c "import trimesh; p=trimesh.creation.box().section([0,0,0],[0,0,1]); print(hasattr(p,'to_2D'), hasattr(p,'to_planar'))"`
If it prints `True False`, change `sec.to_planar(to_2D=np.eye(4))` in `section_poly` to `sec.to_2D(to_2D=np.eye(4))`.

Run: `cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948" && python tests/check_v4.py base-shell`
Expected: `FAIL  v4-base-shell.stl exists   [render it first]`, `1 failure(s)`, exit code 1.

---

### Task 2: Shell maths + base shell (part 6)

**Files:**
- Create: `imu-case-v4.scad`
- Create (rendered): `stl/v4-base-shell.stl`

**Interfaces:**
- Consumes: nothing.
- Produces (used by Tasks 3–5): parameters as named in Global Constraints; functions `se(t)`, `se_n(t)`, `off_pt(t, d)`, `ts()`, `flare_at(z)`, `flare_slope(z)`, `out_d(z)`, `in_d(z)`, `ring(d, z)`, `flat(l)`, `rev(f)`, `band(r0, r1, S)`, `fan_up(r, c, S)`, `fan_down(r, c, S)`, `fan_apex_out(r, c, S)`, `fan_apex_in(r, c, S)`, `se_val(x, y)`; module `base_shell()`; the line `// ===== part dispatch =====` that later tasks insert modules above.

Face-winding rule used everywhere: faces are **built right-hand-outward** (normal by right-hand rule points out of the solid), then every face is passed through `rev()` because OpenSCAD's `polyhedron` wants clockwise-from-outside. `band(r0, r1)` yields normal = tangent(CCW) × (ring r1 − ring r0).

- [ ] **Step 1: Write the file**

Create `imu-case-v4.scad`:

```openscad
// =========================================================================
// IMU Enclosure (#3) v4 — dash-top flared pebble
// Adafruit TDK InvenSense ICM-20948 9-DoF. Spec: specs/imu-case-v4-design.md
// Iris (UI/UX) 2026-09-16. v3.2 is unchanged in imu-case.scad.
//
// Render (git bash):
//   SCAD="/c/Program Files/OpenSCAD/openscad.exe"
//   "$SCAD" -o stl/v4-base.stl       -D part=1 imu-case-v4.scad
//   "$SCAD" -o stl/v4-lid-print.stl  -D part=4 imu-case-v4.scad
// Verify:  python tests/check_v4.py
//
// FRAME: +X = board long axis = car FORWARD (arrow on lid). +Y left. +Z up.
//        Z=0 outer bottom face. XY origin = centre of the interior.
// =========================================================================

part = 0;   // 0 assembly · 1 base · 2 lid in place · 3 section · 4 lid print
            // 5 lid lifted · 6 base shell only · 7 lid shell only

// ---- v3.2 facts: DO NOT MOVE -------------------------------------------
board_l = 25.40;  board_w = 17.78;  board_t = 1.60;
hole_cx = 10.16;  hole_cy = 6.35;          // hole centres (c-c 20.32 x 12.70)
hole_d  = 2.5;                             // NOT in the datasheet — CIO to caliper
rect_a  = 17.70;  rect_b  = 13.89;         // v3.2 interior half-sizes (35.40 x 27.78)
floor_t = 2.0;    split_z = 15.6;   board_z = 8.0;
cable_w = 11.0;   cable_h = 5.0;    cable_z = 5.0;

// ---- shell: CIO-tuned in the 3D mockup 2026-09-16 -----------------------
wall       = 2.0;   // normal to the surface, everywhere
fit_margin = 0.5;   // v3.2 rectangle corner clears the inner wall by this
foot_h     = 0.8;   // vertical band at the bed (no feather edge)
flare      = 8.0;
n_se       = 2.4;   // plan superellipse exponent
dome_h     = 4.0;
roll_h     = 3.0;   // edge roll rise   (min bend radius 2.65 > wall)
roll_w     = 3.4;   // edge roll inset
crown_h    = dome_h - roll_h;
seg = 96;  base_rings = 30;  roll_rings = 10;  crown_rings = 8;

// ---- posts / latches / lid fit ------------------------------------------
post_d    = 5.2;   pin_tip_d = 1.2;   pin_top_z = board_z + board_t + 1.0;
lpost_d   = 4.5;   lpost_x = 18.5;    lpost_y = 10.4;   lpost_top = split_z + 1.8;
latch_t   = 0.7;   latch_gap = 0.1;   latch_lip = 0.4;
latch_tip_x = 11.65;  latch_tip_len = 1.5;  latch_lead = 1.0;
boss_d    = 6.5;   lid_fit_d = 4.5;   socket_top = split_z + 2.0;  boss_grow = 1.0;
vent_w    = 1.3;   vent_len = 4.5;    vent_z = 7.5;
vent_ts   = [70, 90, 110, 9, -9, 171, 189];
arrow_depth = 0.6;
$fn = 48;

// ======================================================================
// maths
// ======================================================================
k_se = pow(2, 1/n_se);
Ai = (rect_a + fit_margin) * k_se;    // inner curve at the split: the
Bi = (rect_b + fit_margin) * k_se;    // rectangle corner + margin lies on it

function sgn(v)   = v < 0 ? -1 : 1;
function se(t)    = [Ai*sgn(cos(t))*pow(abs(cos(t)), 2/n_se),
                     Bi*sgn(sin(t))*pow(abs(sin(t)), 2/n_se)];
function unit2(v) = v / norm(v);
function se_n(t)  = let(d = se(t + 0.05) - se(t - 0.05)) unit2([d[1], -d[0]]);  // outward
function off_pt(t, d) = se(t) + d * se_n(t);                                      // true 2D offset
function se_val(x, y) = pow(abs(x)/Ai, n_se) + pow(abs(y)/Bi, n_se);
function ts() = [for (j = [0:seg-1]) j*360/seg];

function flare_at(z)    = let(u = (max(z, foot_h) - foot_h)/(split_z - foot_h)) flare*(1-u)*(1-u);
function flare_slope(z) = z < foot_h ? 0
                        : let(u = (z - foot_h)/(split_z - foot_h)) -2*flare*(1-u)/(split_z - foot_h);
function out_d(z) = wall + flare_at(z);
function in_d(z)  = out_d(z) - wall*sqrt(1 + pow(flare_slope(z), 2));
function ring(d, z) = [for (t = ts()) let(p = off_pt(t, d)) [p[0], p[1], z]];

// ---- polyhedron helpers (build right-hand-outward, rev() for OpenSCAD) ----
function flat(l) = [for (a = l) for (b = a) b];
function rev(f)  = [for (i = [len(f)-1:-1:0]) f[i]];
function band(r0, r1, S) = flat([for (j = [0:S-1])
    let(a = r0*S + j, b = r0*S + (j+1)%S, c = r1*S + (j+1)%S, d = r1*S + j) [[a, b, c], [a, c, d]]]);
function fan_up(r, c, S)       = [for (j = [0:S-1]) [c, r*S + j, r*S + (j+1)%S]];   // +z
function fan_down(r, c, S)     = [for (j = [0:S-1]) [c, r*S + (j+1)%S, r*S + j]];   // -z
function fan_apex_out(r, c, S) = [for (j = [0:S-1]) [r*S + j, r*S + (j+1)%S, c]];
function fan_apex_in(r, c, S)  = [for (j = [0:S-1]) [r*S + (j+1)%S, r*S + j, c]];

// ======================================================================
// design-rule asserts (render fails, it does not warn)
// ======================================================================
assert(hole_d - 0.2 > pin_tip_d, "pin taper inverted: hole_d too small");
assert(min([for (i = [0:60]) in_d(floor_t + (split_z - floor_t)*i/60)]) >= -1e-9,
       "inner wall intrudes on the v3.2 interior");
assert(max([for (a = [0:10:350]) se_val(lpost_x + (lpost_d/2 + 0.3)*cos(a),
                                        lpost_y + (lpost_d/2 + 0.3)*sin(a))]) < 1,
       "lid post within 0.3 mm of the wall");
assert(latch_tip_x - latch_tip_len/2 >= 10.9, "latch lip reaches the pin headers");
assert(latch_tip_x + latch_tip_len/2 <  board_l/2, "latch lip overhangs the board corner");
assert(pin_top_z < split_z, "pin reaches the lid");
assert(socket_top > lpost_top + 0.1, "post bottoms out in its socket");

// ======================================================================
// base shell (part 6) — outer rings up, rim annulus, inner rings down, floor, bottom
// ======================================================================
module base_shell() {
    S  = seg;
    zo = concat([0, foot_h], [for (i = [1:base_rings]) foot_h + (split_z - foot_h)*i/base_rings]);
    zi = [for (i = [0:base_rings]) split_z - (split_z - floor_t)*i/base_rings];
    Ro = len(zo);  Ri = len(zi);
    pts = concat(flat([for (z = zo) ring(out_d(z), z)]),
                 flat([for (z = zi) ring(in_d(z), z)]),
                 [[0, 0, 0], [0, 0, floor_t]]);
    bc = (Ro + Ri)*S;  fc = bc + 1;
    faces = concat(flat([for (r = [0:Ro-2]) band(r, r+1, S)]),
                   band(Ro-1, Ro, S),                               // rim annulus (+z)
                   flat([for (r = [Ro:Ro+Ri-2]) band(r, r+1, S)]),  // inner wall
                   fan_up(Ro+Ri-1, fc, S),                          // floor top
                   fan_down(0, bc, S));                             // flat bottom
    polyhedron(points = pts, faces = [for (f = faces) rev(f)], convexity = 6);
}

// ===== part dispatch =====
module board_ghost() {
    color("DarkSlateBlue") translate([-board_l/2, -board_w/2, board_z]) cube([board_l, board_w, board_t]);
}
if      (part == 1) base();
else if (part == 2) lid();
else if (part == 3) difference() {
    union() { base(); lid(); board_ghost(); }
    translate([-100, -200, -1]) cube([200, 200, 100]);   // keep y >= 0
}
else if (part == 4) translate([0, 0, -split_z]) lid();
else if (part == 5) { base(); %board_ghost(); translate([0, 0, 25]) lid(); }
else if (part == 6) base_shell();
else if (part == 7) lid_shell();
else { base(); %board_ghost(); color("DimGray", 0.6) lid(); }
```

- [ ] **Step 2: Render the base shell**

Run:
```bash
cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948"
SCAD="/c/Program Files/OpenSCAD/openscad.exe"
"$SCAD" -o stl/v4-base-shell.stl -D part=6 imu-case-v4.scad 2>&1 | tail -5
```
Expected: ends with `Simple: yes` and no `ERROR`/`Assertion` lines. If it reports `Simple: no` or CGAL complains about orientation, the winding is wrong — re-check `band`'s derivation in this task's Interfaces note before changing anything else.

- [ ] **Step 3: Verify**

Run: `python tests/check_v4.py base-shell`
Expected: all `PASS`, `0 failure(s)`; the footprint line reads ≈ `68.6 x 58.4`; wall min/max within 1.9–2.1.

If the wall check fails only by a few hundredths at the foot band boundary, raise `base_rings` to 40 and re-render — do **not** widen the test tolerance.

---

### Task 3: Lid shell (part 7) + seam

**Files:**
- Modify: `imu-case-v4.scad` — insert above `// ===== part dispatch =====`
- Create (rendered): `stl/v4-lid-shell.stl`

**Interfaces:**
- Consumes: Task 2 functions (`off_pt`, `ts`, `flat`, `band`, `fan_apex_out`, `fan_apex_in`, `rev`), params.
- Produces: `lid_us` (list), `lid_o(t, u)`, `lid_n(t, u)`, `lid_in(t, u, g)`, modules `lid_shell()`, `inner_space(g)`.

Meridian parameter `u`: 0 → 1 runs the edge roll (vertical at the rim → horizontal), 1 → 2 runs the crown (ρ = 2 − u, 1 → 0). Outer points are exact; inner points are the outer point minus `(wall − g)` along the unit surface normal from finite differences (`g = 0` is the real inner surface; `g > 0` grows it into the wall, used to clip bosses).

- [ ] **Step 1: Insert the lid maths and modules**

```openscad
// ======================================================================
// lid surface: edge roll (u 0..1) + crown (u 1..2)
// ======================================================================
lid_us = concat([for (i = [0:roll_rings]) i/roll_rings],
                [for (i = [1:crown_rings-1]) 1 + i/crown_rings]);

function lid_o(t, u) = u <= 1
    ? let(ph = 90*u, p = off_pt(t, wall - roll_w*(1 - cos(ph))))
        [p[0], p[1], split_z + roll_h*sin(ph)]
    : let(rho = 2 - u, p = off_pt(t, wall - roll_w))
        [rho*p[0], rho*p[1], split_z + roll_h + crown_h*pow(1 - rho*rho, 2)];
function unit3(v) = v / norm(v);
function lid_n(t, u) = let(du = 0.002, u0 = max(u - du, 0), u1 = min(u + du, 1.999),
                           a = lid_o(t + 0.2, u) - lid_o(t - 0.2, u),
                           b = lid_o(t, u1) - lid_o(t, u0))
                       unit3(cross(a, b));                       // outward
function lid_in(t, u, g) = lid_o(t, u) - (wall - g)*lid_n(t, u);

module lid_shell() {
    S = seg;  R = len(lid_us);
    pts = concat(flat([for (u = lid_us) [for (t = ts()) lid_o(t, u)]]),
                 flat([for (u = lid_us) [for (t = ts()) lid_in(t, u, 0)]]),
                 [[0, 0, split_z + dome_h], [0, 0, split_z + dome_h - wall]]);
    ao = 2*R*S;  ai = ao + 1;
    faces = concat(flat([for (r = [0:R-2]) band(r, r+1, S)]),       // outer surface
                   fan_apex_out(R-1, ao, S),
                   flat([for (r = [R:2*R-2]) band(r+1, r, S)]),     // inner surface (faces down/in)
                   fan_apex_in(2*R-1, ai, S),
                   band(R, 0, S));                                  // rim annulus (-z)
    polyhedron(points = pts, faces = [for (f = faces) rev(f)], convexity = 6);
}

// closed volume of the cavity (base + lid), grown g mm into the wall — for clipping only
module inner_space(g) {
    S  = seg;
    zb = [for (i = [0:base_rings]) floor_t + (split_z - floor_t)*i/base_rings];
    us = [for (u = lid_us) if (u > 0) u];
    N  = len(zb) + len(us);
    pts = concat(flat([for (z = zb) ring(in_d(z) + g, z)]),
                 flat([for (u = us) [for (t = ts()) lid_in(t, u, g)]]),
                 [[0, 0, floor_t], [0, 0, split_z + dome_h - (wall - g)]]);
    fc = N*S;  ap = fc + 1;
    faces = concat(flat([for (r = [0:N-2]) band(r, r+1, S)]),
                   fan_apex_out(N-1, ap, S),
                   fan_down(0, fc, S));
    polyhedron(points = pts, faces = [for (f = faces) rev(f)], convexity = 6);
}
```

- [ ] **Step 2: Render**

Run:
```bash
cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948"
SCAD="/c/Program Files/OpenSCAD/openscad.exe"
"$SCAD" -o stl/v4-lid-shell.stl -D part=7 imu-case-v4.scad 2>&1 | tail -5
```
Expected: `Simple: yes`, no errors.

- [ ] **Step 3: Verify**

Run: `python tests/check_v4.py base-shell lid-shell`
Expected: `0 failure(s)`. Apex at 19.6, size at split ≈ 52.6 × 42.4, lid wall 1.9–2.1, seam areas within 1 %.

---

### Task 4: Base features (part 1)

**Files:**
- Modify: `imu-case-v4.scad` — insert above `// ===== part dispatch =====`
- Create (rendered): `stl/v4-base.stl`

**Interfaces:**
- Consumes: `base_shell()`, `off_pt`, `se_n`, `out_d`, `in_d`, params.
- Produces: modules `base()`, `board_posts()`, `lid_posts()`, `latch_one()`, `latches()`, `wall_cut(t, z, w, h)`, `cable_cut()`, `vent_cuts()`.

- [ ] **Step 1: Run the base group to see it fail**

Run: `python tests/check_v4.py base`
Expected: `FAIL  v4-base.stl exists`.

- [ ] **Step 2: Insert the base feature modules**

```openscad
// ======================================================================
// base features
// ======================================================================
module board_posts() {                          // shoulder seats, taper guides
    for (sx = [-1, 1], sy = [-1, 1]) translate([sx*hole_cx, sy*hole_cy, 0]) {
        translate([0, 0, floor_t - 0.5]) cylinder(h = board_z - floor_t + 0.5, d = post_d);
        translate([0, 0, board_z - 0.01])
            cylinder(h = pin_top_z - board_z + 0.01, d1 = hole_d - 0.2, d2 = pin_tip_d);
    }
}

module lid_posts() {
    for (sx = [-1, 1], sy = [-1, 1]) translate([sx*lpost_x, sy*lpost_y, floor_t - 0.5])
        cylinder(h = lpost_top - floor_t + 0.5, d = lpost_d);
}

// one latch at the +X/+Y corner. Blade lies along X outside the board's long edge,
// flexes in Y (stress ALONG the layers). 45° underside from the post root = no supports.
module latch_one() {
    y0 = board_w/2 + latch_gap;   y1 = y0 + latch_t;
    x_in  = latch_tip_x - latch_tip_len/2;
    x_out = latch_tip_x + latch_tip_len/2;
    z_top   = board_z + board_t + latch_lead;
    z_catch = board_z + board_t + 0.05;
    // blade: XZ profile, extruded from y1 back to y0
    translate([0, y1, 0]) rotate([90, 0, 0]) linear_extrude(latch_t)
        polygon([[lpost_x, floor_t], [x_in, floor_t + (lpost_x - x_in)], [x_in, z_top], [lpost_x, z_top]]);
    // lip + lead-in: YZ profile, extruded along x_in..x_out
    translate([x_in, 0, 0]) rotate([90, 0, 90]) linear_extrude(x_out - x_in)
        polygon([[y0 + 0.2, z_catch], [board_w/2 - latch_lip, z_catch],
                 [board_w/2 - latch_lip, z_catch + 0.2], [y0, z_top], [y0 + 0.2, z_top]]);
}
module latches() {
    for (mx = [0, 1], my = [0, 1]) mirror([mx, 0, 0]) mirror([0, my, 0]) latch_one();
}

// stadium through the wall at plan angle t, height z, cut along the local plan normal.
// w = width along the wall, h = height.
module wall_cut(t, z, w, h) {
    dm = (out_d(z) + in_d(z))/2;
    p  = off_pt(t, dm);
    nn = se_n(t);
    translate([p[0], p[1], z]) rotate([0, 0, atan2(nn[1], nn[0])])
        hull() for (s = [-1, 1])
            if (w >= h) translate([0, s*(w - h)/2, 0]) rotate([0, 90, 0]) cylinder(h = 16, d = h, center = true);
            else        translate([0, 0, s*(h - w)/2]) rotate([0, 90, 0]) cylinder(h = 16, d = w, center = true);
}
module cable_cut() { wall_cut(270, cable_z, cable_w, cable_h); }
module vent_cuts() { for (t = vent_ts) wall_cut(t, vent_z, vent_w, vent_len); }

module base() {
    difference() {
        union() { base_shell(); board_posts(); lid_posts(); latches(); }
        cable_cut();
        vent_cuts();
    }
}
```

- [ ] **Step 3: Render (CGAL; allow several minutes)**

Run:
```bash
cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948"
SCAD="/c/Program Files/OpenSCAD/openscad.exe"
time "$SCAD" -o stl/v4-base.stl -D part=1 imu-case-v4.scad 2>&1 | tail -6
```
Expected: `Simple: yes`, no errors. (Use `run_in_background` if it passes ~10 min.)

- [ ] **Step 4: Verify**

Run: `python tests/check_v4.py base-shell base`
Expected: `0 failure(s)` — shoulders 8.0, pin tips 10.6, lips present, board volume clear, outer skin unbroken at z 1/12/15, cable exit open, top 17.4.

---

### Task 5: Lid features (parts 2, 4)

**Files:**
- Modify: `imu-case-v4.scad` — insert above `// ===== part dispatch =====`
- Create (rendered): `stl/v4-lid-print.stl`

**Interfaces:**
- Consumes: `lid_shell()`, `inner_space(g)`, params.
- Produces: modules `lid()`, `arrow_cut()`.

- [ ] **Step 1: Run the lid group to see it fail**

Run: `python tests/check_v4.py lid`
Expected: `FAIL  v4-lid-print.stl exists`.

- [ ] **Step 2: Insert the lid modules**

```openscad
// ======================================================================
// lid features
// ======================================================================
module arrow_cut() {                                          // FRONT = +X
    translate([0, 0, split_z + dome_h - arrow_depth - 0.15]) linear_extrude(arrow_depth + 1)
        polygon([[-6, -1.2], [1.5, -1.2], [1.5, -3.2], [6, 0], [1.5, 3.2], [1.5, 1.2], [-6, 1.2]]);
}

module lid() {
    difference() {
        union() {
            lid_shell();
            intersection() {                                  // socket bosses, fused into the wall,
                for (sx = [-1, 1], sy = [-1, 1])               // never through it
                    translate([sx*lpost_x, sy*lpost_y, split_z]) cylinder(h = dome_h, d = boss_d);
                inner_space(boss_grow);
            }
        }
        for (sx = [-1, 1], sy = [-1, 1])                      // press-fit sockets (blind)
            translate([sx*lpost_x, sy*lpost_y, split_z - 1]) cylinder(h = socket_top - split_z + 1, d = lid_fit_d);
        arrow_cut();
    }
}
```

- [ ] **Step 3: Render**

Run:
```bash
cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948"
SCAD="/c/Program Files/OpenSCAD/openscad.exe"
time "$SCAD" -o stl/v4-lid-print.stl -D part=4 imu-case-v4.scad 2>&1 | tail -6
```
Expected: `Simple: yes`, no errors.

- [ ] **Step 4: Verify everything**

Run: `python tests/check_v4.py`
Expected: all four groups, `0 failure(s)`. Socket tops at 2.0, skin ≥ 0.8 at every probe.

If the skin check fails, lower `socket_top` by the shortfall and `lpost_top` by the same amount (keeping `socket_top − lpost_top = 0.2`), re-render parts 1 and 4, re-run. Record the new engagement in spec §4.

---

### Task 6: Renders + Bambu Studio slices

**Files:**
- Create: `renders/v4_3q.png`, `renders/v4_side.png`, `renders/v4_section.png`, `renders/v4_lid-lifted.png`
- Create (conditional): `slicer/v4-base.3mf`, `slicer/v4-lid.3mf`

**Interfaces:**
- Consumes: parts 0, 3, 5 of `imu-case-v4.scad`; the two print STLs.
- Produces: preview images; slices or a stated reason there are none.

- [ ] **Step 1: Renders (OpenCSG preview — fast, coloured)**

Run:
```bash
cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948"
SCAD="/c/Program Files/OpenSCAD/openscad.exe"
"$SCAD" -o renders/v4_3q.png         --imgsize=1400,1000 --camera=0,0,9,55,0,215,190 --colorscheme=Tomorrow -D part=0 imu-case-v4.scad
"$SCAD" -o renders/v4_side.png       --imgsize=1400,700  --camera=0,0,9,90,0,180,170 --colorscheme=Tomorrow -D part=0 imu-case-v4.scad
"$SCAD" -o renders/v4_section.png    --imgsize=1400,1000 --camera=0,0,9,65,0,160,150 --colorscheme=Tomorrow -D part=3 imu-case-v4.scad
"$SCAD" -o renders/v4_lid-lifted.png --imgsize=1400,1000 --camera=0,0,20,55,0,215,230 --colorscheme=Tomorrow -D part=5 imu-case-v4.scad
ls -la renders/v4_*.png
```
Expected: four PNGs, each > 20 KB. Open each with the Read tool and confirm by eye: smooth flared shell, rolled lid edge, arrow on top, posts + latches visible in the section/lifted views.

- [ ] **Step 2: Try the Bambu Studio CLI slice**

Run:
```bash
cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948"
BBL="/c/Program Files/Bambu Studio/resources/profiles/BBL"
BS="/c/Program Files/Bambu Studio/bambu-studio.exe"
"$BS" --slice 0 --arrange 1 --orient 0 \
  --load-settings "$BBL/machine/Bambu Lab P2S 0.4 nozzle.json;$BBL/process/0.20mm Standard @BBL P2S.json" \
  --load-filaments "$BBL/filament/Bambu PLA Basic @BBL P2S.json" \
  --export-3mf slicer/v4-base.3mf stl/v4-base.stl > slicer/v4-base.cli.log 2>&1
echo "exit=$?"; tail -20 slicer/v4-base.cli.log; ls -la slicer/v4-base.3mf
```
Expected (success): exit 0 and `slicer/v4-base.3mf` exists with nonzero size.

- [ ] **Step 3: Branch on the result**

- **If Step 2 succeeded:** repeat it for the lid with `stl/v4-lid-print.stl` → `slicer/v4-lid.3mf` (log `slicer/v4-lid.cli.log`). Do not guess at a support flag: the lid 3mf is sliced without supports, and the hand-off tells the CIO to enable **tree supports** + **variable layer height** in the GUI before printing.
- **If Step 2 failed** (non-zero exit, missing 3mf, or a preset-inheritance error in the log): do **not** iterate on undocumented flags. Record the first error line from `slicer/v4-base.cli.log` and deliver STLs only, as the spec allows. The CIO opens the STLs in Bambu Studio with *P2S 0.4 · 0.20mm Standard · Bambu PLA Basic*, and for the lid enables **tree supports** + **variable layer height** (spec §4).

---

### Task 7: Record + hand-offs

**Files:**
- Modify: `specs/imu-case-v4-design.md` — append a `## 9. Build results` section
- Create: `../../tuner/inbox/2026-09-16-from-iris-imu-v4-enclosure-rebaseline.md`
- Create: `../../pm/inbox/2026-09-16-from-iris-imu-v4-built-and-printer-record-gap.md`

**Interfaces:**
- Consumes: the final `python tests/check_v4.py` output, STL bounds, Task 6 outcome.
- Produces: the record the next session and peers read.

- [ ] **Step 1: Capture the final numbers**

Run:
```bash
cd "Z:/O/OBD2v3/offices/uideveloper/case-imu-icm20948"
python tests/check_v4.py > specs/v4-check-output.txt 2>&1; echo "exit=$?"
python -c "import trimesh;[print(f, trimesh.load_mesh('stl/'+f).bounds.tolist()) for f in ('v4-base.stl','v4-lid-print.stl')]"
```
Expected: `exit=0`; bounds printed.

- [ ] **Step 2: Append §9 to the spec** (Edit tool, append at end of file — the file is new this session, so no backup is needed)

```markdown
## 9. Build results (2026-09-16)

- Verification: `python tests/check_v4.py` → **0 failures** (full log `specs/v4-check-output.txt`).
- Base `stl/v4-base.stl` bounds: <paste from Step 1>.
- Lid `stl/v4-lid-print.stl` bounds: <paste from Step 1>.
- Slices: <"slicer/v4-base.3mf + v4-lid.3mf (P2S 0.4, 0.20mm Standard, Bambu PLA Basic)" — OR — "none: Bambu CLI failed with <first error line>; STLs only">.
- Renders: `renders/v4_3q.png`, `v4_side.png`, `v4_section.png`, `v4_lid-lifted.png`.
- Still open: `hole_d` caliper; latch click + retention; lid press-fit; dash seating.
```

Replace every `<…>` with the real value before saving; a literal `<paste …>` left in the file is a failed step.

- [ ] **Step 3: A2AL to Spool (tuner inbox)**

```
from=Iris(UI/UX); to=Spool(Tuner); date=2026-09-16; topic=IMU enclosure v4 swap = IMU remount -> rebaseline; audience=agent; urgency=info

v4 IMU case built (flared pebble, dash-top centre, tape mount). Swap = physical REMOUNT of the ICM-20948.
- frame unchanged: FRONT arrow = +X = forward. board flat, shoulders at same z as v3.2.
- => first drive after swap = new IMU baseline; pitch fusion re-converges after ~5 stops (your 08-28 card). do NOT baseline across the swap.
- latched 1.07deg mount characterisation is for the v3.2 case/position; re-measure after.
CIO decides when to swap. no action until then.
```

- [ ] **Step 4: Note to Marcus (pm inbox)**

```
from=Iris(UI/UX); to=Marcus(PM); date=2026-09-16; topic=IMU enclosure v4 designed+built (office-only) + printer record gap; audience=agent; urgency=low

1. W-10 IMU enclosure v4 done in offices/uideveloper/case-imu-icm20948/ (spec specs/imu-case-v4-design.md, source imu-case-v4.scad, STLs stl/v4-*.stl). office files only; share has no git -> nothing to merge. CIO prints.
2. GAP (repo docs, not my lane): charter points to docs/3d-printing/ as printer/slicer SSOT -> path does NOT exist in C:\agents\OBD2v3\trunk. and CIO upgraded MK3S+ -> Bambu Lab P2S (2026-09-16); no fleet record says so. suggest a typed housekeeping story to restore/refresh the printer SSOT.
```

- [ ] **Step 5: Tell the CIO**

Report: test result, measured sizes, renders (show them), slices-or-STLs, the two planning-time spec changes (roll+crown lid edge; sockets bore up, 1.8 mm engagement), and the open `hole_d` caliper reading.

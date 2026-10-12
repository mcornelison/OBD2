// =========================================================================
// IMU Enclosure (#3) v5 — dash-top flared pebble
// Adafruit TDK InvenSense ICM-20948 9-DoF. Spec: specs/imu-case-v5-design.md
// Iris (UI/UX) 2026-09-17 (v4 2026-09-16 is unchanged in imu-case-v4.scad). v3.2 is unchanged in imu-case.scad.
//
// Render (git bash):
//   SCAD="/c/Program Files/OpenSCAD/openscad.exe"
//   "$SCAD" -o stl/v5-base.stl       -D part=1 imu-case-v5.scad
//   "$SCAD" -o stl/v5-lid-print.stl  -D part=4 imu-case-v5.scad
// Verify:  python tests/check_v5.py
//
// FRAME (CORRECTED v5, CIO 2026-09-17 — v4's comment was wrong about the car):
//   +X = board LONG axis = mounted ACROSS the car, driver<->passenger. NOT forward.
//   +Y = board SHORT axis = fore/aft.  -Y = the nose.  +Z = up.
// v4 read "+X = car FORWARD", which is 90 deg from how the case is actually mounted.
// The arrow is rotated to suit (arrow_rot); the CIO has ruled the axis question closed
// on the firmware side, so nothing downstream is changed here.
//        Z=0 outer bottom face. XY origin = centre of the interior.
// =========================================================================

part = 0;   // 0 assembly · 1 base · 2 lid in place · 3 section · 4 lid print
            // 5 lid lifted · 6 base shell only · 7 lid shell only

// ---- v3.2 facts: DO NOT MOVE -------------------------------------------
board_l = 25.40;  board_w = 17.78;  board_t = 1.60;
// ⚠️ ROTATED 90 deg, CIO 2026-09-18. The board is NOT square and neither is its hole
// pattern -- 25.40 x 17.78 mm (1.000" x 0.700") on 20.32 x 12.70 c-c (0.800" x 0.500"),
// both out by the same 7.62 mm -- so rotating the board REQUIRES rotating the posts.
// This is that swap. Each post moves 5.39 mm.
// Consequence: the board's long axis (+X, and the IMU's own +X) now runs FORE/AFT, so
// the sensor frame lines up with the car -- what v4's header wrongly claimed was already
// true. Interior clearance stops being symmetric: X +8.81 / Y +1.19 per side (was 5.00
// all round), so WIRES MUST ROUTE ALONG THE LONG SIDES -- the short-side gap between the
// seat collar and the wall is only 0.93 mm and will not take a 2.5 mm conductor.
hole_cx = 6.35;   hole_cy = 10.16;         // c-c 12.70 x 20.32 (was 20.32 x 12.70)
hole_d  = 2.5;                             // NOT in the datasheet — CIO to caliper
rect_a  = 17.70;  rect_b  = 13.89;         // v3.2 interior half-sizes (35.40 x 27.78)
// v5 (CIO 2026-09-17): lower profile. board_z 8.0 -> 6.0 (6.0 mm under the board was
// "tons of room"; 4.0 mm still clears one layer of 18 AWG at ~2.5 mm OD), and
// split_z 15.6 -> 12.0 shaves the dead space above. Total height 19.6 -> 16.0.
// The LID IS UNCHANGED BY CONSTRUCTION: flare_at() is normalised to split_z and is
// exactly 0 at the seam, so out_d(split_z) == wall for any height. Lowering split_z
// compresses the flare and steepens the sides; the seam outline and the footprint
// are identical. No compensation term is needed or present.
floor_t = 2.0;    split_z = 12.0;   board_z = 6.0;
comp_clear = split_z - (board_z + board_t);   // 4.4 — clear above the board.
                                              // PLACEHOLDER pending the CIO's caliper
                                              // of the tallest top-side component.
// cable port centre. Must keep its floor >= floor_t or the cut breaches the floor:
// cable_z - cable_h/2 = 4.5 - 2.5 = 2.0. Port spans z 2.0..7.0, matching the new
// under-board channel (z 2.0..6.0) so the wires do not have to climb to reach it.
cable_w = 11.0;   cable_h = 5.0;    cable_z = 4.5;

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
// ---- v5 board retention: SPLIT SNAP POSTS (CIO 2026-09-17) -------------------
// Replaces the v4 corner-post latch blades, which are RETIRED. The board now clicks
// onto all 4 posts and is released by pinching each finger pair inward.
//
// The seat and the spring are SEPARATE bodies, and that is the whole trick. A plain
// Ø5.2 post with a slot up the middle gives two 2.6 mm-thick half-posts -- far too
// stiff to flex, which is why a barb straight on the v4 pin stub would snap (2.6 mm
// of free length => ~7.7 % strain). Here a thin-walled COLLAR carries the board and a
// thin split STEM does the flexing, free over its whole length from the floor up.
seat_od   = 5.6;   seat_id  = 3.5;                 // collar: board rests on its top annulus
// 2.20. CIO has NO CALIPERS (2026-09-18) and reports past fits were fine -- true, but
// v4's pin was a TAPER, which self-centres and hides a small hole. This stem is STRAIGHT
// because it must be a spring, so it has no such forgiveness: too fat and the board will
// not go on at all. hole_d stays 2.5 per the CIO; the margin is bought here instead --
// 0.15 mm slop per side rather than 0.10, and a smaller stem only IMPROVES the barb grip
// if the holes turn out undersized.
stem_d    = hole_d - 0.3;                          // 2.20 — the pair before the slot
slot_w    = 0.8;                                   // must exceed 2*(insertion deflection)
barb_d    = 2.9;                                   // catch Ø: overhangs the Ø2.5 hole 0.2/side
barb_lead = 1.6;                                   // lead-in ramp above the catch face
catch_clear = 0.15;                                // Rule 2: >= one 0.2 mm layer
root_fillet = 0.6;                                 // stress concentration at the finger root
finger_root_z = floor_t;                           // 2.0 — free above the floor
z_catch   = board_z + board_t + catch_clear;       // 7.75
pin_top_z = z_catch + barb_lead;                   // 9.35 — must stay under the lid
// Strain check (Rule 1 formula, eps ~ 1.5*t*delta/L^2), t ~ 0.75 per finger after the
// slot, delta = (barb_d - hole_d)/2 = 0.20, L = z_catch - finger_root_z = 5.75:
//   eps ~ 1.5 * 0.75 * 0.20 / 5.75^2 = 0.68 %  -- well inside the 2 % few-cycle budget.
// ⚠️ BUT SEE THE RULE-1 CAVEAT IN THE SPEC: these are VERTICAL arms flexing SIDEWAYS,
// which loads the layer bonds, not the extrusion lines. The strain is low but the
// direction is the weak one. PETG (the keeper material) is where this is comfortable.
lpost_d   = 4.5;   lpost_x = 18.5;    lpost_y = 10.4;   lpost_top = split_z + 1.8;
arrow_rot = -90;   // v5: +X pointed driver-side; -90 deg about Z swings it to -Y = the
                   // nose. ONE NUMBER if the handedness is backwards (use +90).
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
assert(stem_d < hole_d, "spring stem does not fit the board hole");
assert(stem_d - 0.4 > 0.8, "barb lead-in tip too thin to print");
assert(root_fillet < z_catch - finger_root_z, "root fillet consumes the whole finger");
assert(min([for (i = [0:60]) in_d(floor_t + (split_z - floor_t)*i/60)]) >= -1e-9,
       "inner wall intrudes on the v3.2 interior");
assert(max([for (a = [0:10:350]) se_val(lpost_x + (lpost_d/2 + 0.3)*cos(a),
                                        lpost_y + (lpost_d/2 + 0.3)*sin(a))]) < 1,
       "lid post within 0.3 mm of the wall");
assert(seat_id > stem_d + 0.4, "seat collar bore fouls the spring stem");
assert(seat_od/2 < hole_cx && seat_od/2 < hole_cy, "seat collars overlap each other");
// Post-rotation guards (2026-09-18). These were a DEFERRED item on v4 ("true by
// construction"); rotating the posts is exactly the change that could quietly break
// them, so they are asserts now rather than an assumption.
assert(se_val(hole_cx + seat_od/2, hole_cy + seat_od/2) < 1,
       "seat collar has left the shell wall");
assert(pow(hole_cx + seat_od/2, 2) <= pow(rect_a, 2)
       && hole_cy + seat_od/2 <= rect_b,
       "seat collar breaks the v3.2 interior rectangle");
assert(norm([lpost_x - hole_cx, lpost_y - hole_cy]) > (lpost_d + seat_od)/2 + 0.3,
       "seat collar fouls a lid post");
assert(hole_cy + seat_od/2 < rect_b, "no wall gap left beside the collar");
assert(barb_d > hole_d, "barb does not overhang the board hole -- it would not catch");
assert(slot_w > (barb_d - hole_d), "slot cannot close far enough for the barb to enter");
assert(comp_clear > 0, "split_z is below the board top -- the lid would crush the board");
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

// ======================================================================
// base features
// ======================================================================
// v5 snap post: a thin-walled SEAT COLLAR (carries the board) plus a split STEM with a
// barb (holds it down). They do not touch, so the spring is thin over its full length.
module snap_post_one() {
    // 1. seat collar -- board lands on the annulus at z = board_z
    difference() {
        translate([0, 0, floor_t - 0.5]) cylinder(h = board_z - floor_t + 0.5, d = seat_od);
        translate([0, 0, floor_t - 0.6]) cylinder(h = board_z, d = seat_id);
    }
    // 2. stem + barb, then the slot that turns it into two fingers
    difference() {
        union() {
            translate([0, 0, finger_root_z - 0.01])
                cylinder(h = z_catch - finger_root_z + 0.01, d = stem_d);
            // fillet at the root: the highest-stress point, and the one a layer crack starts at
            translate([0, 0, finger_root_z - 0.01])
                cylinder(h = root_fillet, d1 = stem_d + 2*root_fillet, d2 = stem_d);
            // barb: flat catch face at z_catch, lead-in ramp above it
            translate([0, 0, z_catch]) cylinder(h = barb_lead, d1 = barb_d, d2 = stem_d - 0.4);
        }
        // the slot. Runs the full height so the fingers are free from the root up, and
        // is oriented along X so both fingers flex in +/-Y (identical on all four posts).
        translate([-stem_d, -slot_w/2, finger_root_z + root_fillet])
            cube([2*stem_d, slot_w, pin_top_z - finger_root_z]);
    }
}

module board_posts() {
    for (sx = [-1, 1], sy = [-1, 1])
        translate([sx*hole_cx, sy*hole_cy, 0]) snap_post_one();
}

module lid_posts() {
    for (sx = [-1, 1], sy = [-1, 1]) translate([sx*lpost_x, sy*lpost_y, floor_t - 0.5])
        cylinder(h = lpost_top - floor_t + 0.5, d = lpost_d);
}

// v5: the v4 corner latch blades are RETIRED. Board retention moved to the four
// snap posts (CIO 2026-09-17), so the corner posts are now purely lid sockets and
// nothing reaches over the board's long edge.

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
        union() { base_shell(); board_posts(); lid_posts(); }
        cable_cut();
        vent_cuts();
    }
}

// ======================================================================
// lid features
// ======================================================================
module arrow_cut() {                    // v5: rotated to -Y = the nose (arrow_rot)
    translate([0, 0, split_z + dome_h - arrow_depth - 0.15])
      rotate([0, 0, arrow_rot]) linear_extrude(arrow_depth + 1)
        polygon([[-6, -1.2], [1.5, -1.2], [1.5, -3.2], [6, 0], [1.5, 3.2], [1.5, 1.2], [-6, 1.2]]);
}

module lid() {
    intersection() {
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
        // clip: nothing exists below the split plane by design (lid meets the base edge-to-edge
        // at z=split_z, spec S4). lid_n()'s one-sided finite difference at its u=0 domain boundary
        // (inherited, Task 3) leaves a ~3.6 um numerical undershoot on the inner rim ring; this
        // exact half-space trim removes only that spurious sliver, never intended geometry.
        translate([-100, -100, split_z]) cube([200, 200, 100]);
    }
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

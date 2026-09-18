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
// lip underside above the board top: 0.15 lands the underside at z 9.75 -> prints on the
// 9.8 layer at 0.2 mm layer height; <=0.2 mm vertical play is the price of guaranteed engagement.
latch_catch_clear = 0.15;
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
assert(board_z + board_t + latch_catch_clear < board_z + board_t + latch_lead - 0.3,
       "latch lip has no lead-in height left");

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
    z_catch = board_z + board_t + latch_catch_clear;
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

// ======================================================================
// lid features
// ======================================================================
module arrow_cut() {                                          // FRONT = +X
    translate([0, 0, split_z + dome_h - arrow_depth - 0.15]) linear_extrude(arrow_depth + 1)
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

// =========================================================================
// IMU Enclosure (#3)  —  Adafruit TDK InvenSense ICM-20948 9-DoF IMU
// Flat box, 4 corner standoffs, friction-lip lid, wall vents, 4-5 wire exit, VHB base.
// Part of the Pi-5 black-box / EDR build. Spec: enclosure3/specs/imu-case-design.md
// Iris (UI/UX Designer)
//   v1  2026-06-17  — CIO interview design.
//   v2  2026-06-19  — CIO 1st-print fit-check: dropped lid SNAP rib + box groove
//                     (PLA too rigid to flex past the snap -> lid wouldn't seat);
//                     lid now a plain friction lip. Removed the unreadable lid TEXT
//                     label (arrow kept). Wire-exit "foot" clearance pending frame
//                     confirm. Top-of-lid smoothness = build-sheet, not model (note).
//
// Render (git bash; numeric part selector avoids CLI quote-mangling):
//   "/c/Program Files/OpenSCAD/openscad.exe" -o stl/box.stl -D part=1 imu-case.scad
//   "/c/Program Files/OpenSCAD/openscad.exe" -o stl/lid.stl -D part=2 imu-case.scad
//
// =========================================================================
// AUTHORITATIVE BOARD FACTS (ICM-20948 datasheet Fab Print, dims in INCHES)
//   Board overall : 1.00 x 0.70 in = 25.40 x 17.78 mm
//   Mount holes   : 4 corners, c-c 0.80 x 0.50 in (20.32 x 12.70 mm)
//   Hole inset    : 0.10 in (2.54 mm) from each edge; ~M2.5
//
// FRAME: +X = board long axis (25.40). +Y = short axis (17.78). +Z = up.
//        Z=0 = outer BOTTOM face (VHB). FRONT arrow on the lid points +X.
//        Wire exit on the -Y long wall; vents on +Y long wall + both short walls.
// =========================================================================

part = 0;   // 0 = assembly, 1 = box, 2 = lid, 3 = cross-section

// ---- Board facts --------------------------------------------------------
board_l    = 25.40;   // X
board_w    = 17.78;   // Y
board_t    = 1.60;
hole_inset = 2.54;    // holes 2.54 from each edge (-> c-c 20.32 x 12.70)
comp_h     = 4.0;     // approx tallest top-side part (STEMMA QT) for ghost/clearance

// ---- Geometry knobs -----------------------------------------------------
clr         = 5.0;    // board-to-wall clearance, all sides (CIO 2026-06-17: room for wires)
wall        = 2.0;    // side-wall thickness
bottom_wall = 2.0;    // floor thickness
standoff_h  = 3.0;    // board lift off the floor (under-board clearance + wiring)
comp_clear  = 6.0;    // open height above the board (connectors + soldered wires)
corner_r    = 2.0;

// ---- Fastening (M2.5 into printed posts) --------------------------------
post_r   = 2.6;
pilot_r  = 1.05;      // M2.5 self-tap pilot (Phi 2.1)
pilot_dz = 6.0;

// ---- Snap lid -----------------------------------------------------------
lid_top_t  = 2.0;     // lid top plate thickness
lid_lip_h  = 5.0;     // how far the lid lip reaches down into the box
lid_lip_t  = 1.5;     // lid lip wall thickness
lid_clear  = 0.3;     // locating-lip clearance, lip-to-inner-wall (per side).
                      //   lip now just ALIGNS the lid; the 2 screws retain it.
// snap_* params (v1 snap-fit) are now OBSOLETE — lid is screw-retained (v2).
snap_d     = 0.6;     // (unused)
snap_h     = 1.2;     // (unused)
snap_drop  = 2.5;     // (unused)

// ---- Lid retention screws (v2 — CIO: 2 small screws) --------------------
// 2 M2.5 self-tap screws at DIAGONAL corners (most clearance; clear of the
// board, vents, and cable slot). Box gets corner bosses; lid gets counterbored
// through-holes; the lip is pocketed locally so the boss can't hit it.
lid_scr_inset    = 4.2;   // screw-center inset from each outer wall (corner)
lid_scr_r        = 3.0;   // box boss radius
lid_scr_pilot    = 1.05;  // M2.5 self-tap pilot (Phi 2.1)
lid_scr_pilot_dz = 8.0;   // pilot depth down from the rim
lid_scr_shank_r  = 1.45;  // shank clearance through the lid (Phi 2.9 for M2.5)
lid_scr_head_r   = 2.6;   // counterbore for the head (M2.5 socket/pan)
lid_scr_head_dz  = 1.6;   // counterbore depth from the lid top

// ---- Vents (thin rounded-end vertical slots, like enclosure #2) ---------
vent_w   = 1.3;
vent_len = 4.5;
vent_z   = 4.5;       // center Z of wall vents (above floor)

// ---- Wire exit (4-5 wires, -Y long wall) --------------------------------
cable_w  = 7.0;
cable_h  = 5.0;       // taller so wires clear the board (CIO 2026-06-17)
cable_z  = 3.0;       // center Z above floor; lowered so the slot drops into the under-board gap

// ---- Bottom face --------------------------------------------------------
// FLAT (no VHB recess): full first-layer bed contact for reliable MK3S+
// adhesion. A recessed bottom only contacts on a thin lip-ring (~24% area) and
// releases mid-print. VHB tape sticks fine to a plain flat face.
// See knowledge/pattern-flat-base-and-print-orientation.md.

// ---- Derived ------------------------------------------------------------
x0 = wall + clr;                       // board origin (world) X
y0 = wall + clr;                       // board origin (world) Y
inner_x = board_l + 2*clr;
inner_y = board_w + 2*clr;
case_x  = inner_x + 2*wall;
case_y  = inner_y + 2*wall;
box_h   = standoff_h + board_t + comp_clear;   // floor -> box rim
rim_z   = bottom_wall + box_h;                 // world Z of the box rim
board_z = bottom_wall + standoff_h;            // world Z of the board underside
snap_z  = box_h - snap_drop;                   // snap band height above the floor

// hole positions (world)
hole_xy = [ for (sx = [hole_inset, board_l - hole_inset],
                 sy = [hole_inset, board_w - hole_inset]) [x0 + sx, y0 + sy] ];

// lid-screw positions (world) — 2 diagonal corners
lid_scr_xy = [ [lid_scr_inset, lid_scr_inset],
               [case_x - lid_scr_inset, case_y - lid_scr_inset] ];

$fn = 48;

// ======================================================================
// helpers
// ======================================================================
module rrect(x, y, r) {
    hull() {
        translate([r,   r  ]) circle(r);
        translate([x-r, r  ]) circle(r);
        translate([r,   y-r]) circle(r);
        translate([x-r, y-r]) circle(r);
    }
}

// vertical rounded-end vent slot, cut THROUGH a wall along Y (long walls)
module vent_slot_Y() {
    hull() for (s = [-1, 1])
        translate([0, 0, s*(vent_len - vent_w)/2])
            rotate([90, 0, 0]) cylinder(h = wall*3, r = vent_w/2, center = true);
}
// vertical rounded-end vent slot, cut THROUGH a wall along X (short walls)
module vent_slot_X() {
    hull() for (s = [-1, 1])
        translate([0, 0, s*(vent_len - vent_w)/2])
            rotate([0, 90, 0]) cylinder(h = wall*3, r = vent_w/2, center = true);
}

// 2D arrow pointing +X (for the lid FRONT marker)
module arrow2d(L = 10, shaft_w = 2.4, head_l = 4.5, head_w = 6.5) {
    union() {
        translate([0, -shaft_w/2]) square([L - head_l, shaft_w]);
        translate([L - head_l, 0]) polygon([[0, -head_w/2], [0, head_w/2], [head_l, 0]]);
    }
}

// ======================================================================
// board ghost (assembly view)
// ======================================================================
module board_ghost() {
    color("DarkSlateBlue")
        translate([x0, y0, board_z]) cube([board_l, board_w, board_t]);
    color("DimGray")
        translate([x0 + board_l*0.2, y0 + board_w*0.25, board_z + board_t])
            cube([board_l*0.6, board_w*0.5, comp_h]);
    color("Silver")
        for (h = hole_xy) translate([h[0], h[1], board_z + board_t]) cylinder(h = 1.6, r = 2.3);
}

// ======================================================================
// box (printable part 1)
// ======================================================================
module standoffs() {
    for (h = hole_xy) difference() {
        // sink 0.5 into the floor so the post fuses with it (no coincident face)
        translate([h[0], h[1], bottom_wall - 0.5]) cylinder(h = standoff_h + 0.5, r = post_r);
        translate([h[0], h[1], board_z - pilot_dz + 0.01]) cylinder(h = pilot_dz, r = pilot_r);
    }
}

// lid-retention corner bosses (rise floor -> rim; pilot for M2.5 self-tap)
module lid_screw_bosses() {
    for (p = lid_scr_xy) difference() {
        translate([p[0], p[1], bottom_wall - 0.5])
            cylinder(h = rim_z - (bottom_wall - 0.5), r = lid_scr_r);
        translate([p[0], p[1], rim_z - lid_scr_pilot_dz])
            cylinder(h = lid_scr_pilot_dz + 0.1, r = lid_scr_pilot);
    }
}

module box() {
    difference() {
        // outer blank
        linear_extrude(rim_z) rrect(case_x, case_y, corner_r);

        // cavity (open top)
        translate([wall, wall, bottom_wall])
            linear_extrude(box_h + 1) rrect(inner_x, inner_y, max(corner_r - wall, 0.6));

        // (v2) snap groove REMOVED — lid is now a plain friction lip (CIO: PLA too
        // rigid to flex past the snap rib, lid wouldn't seat). Lip fit = lid_clear.

        // wire exit slot (-Y long wall), rounded
        translate([case_x/2, wall/2, bottom_wall + cable_z]) rotate([90, 0, 0])
            hull() for (s = [-1, 1])
                translate([s*(cable_w - cable_h)/2, 0, 0])
                    cylinder(h = wall*3, r = cable_h/2, center = true);

        // vents: 3 on the +Y long wall
        for (i = [1:3])
            translate([case_x * i/4, case_y - wall/2, bottom_wall + vent_z]) vent_slot_Y();
        // vents: 2 on each short (X-end) wall
        for (j = [1:2]) {
            translate([wall/2,          case_y * j/3, bottom_wall + vent_z]) vent_slot_X();
            translate([case_x - wall/2, case_y * j/3, bottom_wall + vent_z]) vent_slot_X();
        }
        // bottom face is FLAT (VHB recess dropped — see param note)
    }
    standoffs();
    lid_screw_bosses();
}

// ======================================================================
// lid (printable part 2) — perimeter friction lip + FRONT arrow
//   (v2) snap rib removed; text label removed. Arrow kept as the orientation cue.
// ======================================================================
module lid() {
    // outer footprint of the lip (fits inside the box with clearance)
    lx = inner_x - 2*lid_clear;
    ly = inner_y - 2*lid_clear;
    difference() {
        union() {
            // top plate (rests on the box rim)
            difference() {
                translate([0, 0, rim_z]) linear_extrude(lid_top_t) rrect(case_x, case_y, corner_r);
                // debossed FRONT arrow (+X) — the only top marking (text removed: unreadable)
                translate([case_x/2 - 5, case_y/2, rim_z + lid_top_t - 0.6])
                    linear_extrude(1.0) arrow2d();
            }
            // locating lip ring hanging down into the box (retention = the 2 screws)
            translate([wall + lid_clear, wall + lid_clear, rim_z - lid_lip_h])
                linear_extrude(lid_lip_h)
                    difference() {
                        rrect(lx, ly, max(corner_r - wall - lid_clear, 0.6));
                        translate([lid_lip_t, lid_lip_t])
                            rrect(lx - 2*lid_lip_t, ly - 2*lid_lip_t, 0.6);
                    }
        }
        // lid-screw cuts: counterbored shank through the top + lip-clearance pocket
        for (p = lid_scr_xy) translate([p[0], p[1], 0]) {
            // shank through the full lid stack
            translate([0, 0, rim_z - lid_lip_h - 1])
                cylinder(h = lid_lip_h + lid_top_t + 2, r = lid_scr_shank_r);
            // head counterbore from the top down
            translate([0, 0, rim_z + lid_top_t - lid_scr_head_dz])
                cylinder(h = lid_scr_head_dz + 0.1, r = lid_scr_head_r);
            // lip-zone pocket so the box boss never collides with the lip
            translate([0, 0, rim_z - lid_lip_h - 0.1])
                cylinder(h = lid_lip_h + 0.1, r = lid_scr_r + 0.4);
        }
    }
}

// ======================================================================
// part dispatch
// ======================================================================
if (part == 1) {
    box();
} else if (part == 2) {
    lid();
} else if (part == 4) {
    // lid in PRINT orientation: top face flat on the bed, lip + snap rib pointing up
    // (so the solid top plate is the first layer -> no bridging, stable, smooth top).
    translate([0, case_y, rim_z + lid_top_t]) rotate([180, 0, 0]) lid();
} else if (part == 3) {
    // cross-section through the middle (keep X >= case_x/2, show cut face)
    difference() {
        union() {
            box(); lid();
            color("DarkSlateBlue") translate([x0, y0, board_z]) cube([board_l, board_w, board_t]);
        }
        translate([-200, -200, -200]) cube([200 + case_x/2, 400, 400]);
    }
} else {
    box();
    %board_ghost();
    color("LightCyan", 0.5) lid();
}

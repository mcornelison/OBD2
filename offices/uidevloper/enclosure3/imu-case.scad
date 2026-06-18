// =========================================================================
// IMU Enclosure (#3)  —  Adafruit TDK InvenSense ICM-20948 9-DoF IMU
// Flat box, 4 corner standoffs, snap-on lid, wall vents, 4-5 wire exit, VHB base.
// Part of the Pi-5 black-box / EDR build. Spec: enclosure3/specs/imu-case-design.md
// Iris (UI/UX Designer)
//   v1  2026-06-17  — CIO interview design.
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
lid_clear  = 0.3;     // fit clearance, lip-to-inner-wall (per side)
snap_d     = 0.6;     // snap rib/groove depth
snap_h     = 1.2;     // snap rib/groove height
snap_drop  = 2.5;     // snap band below the rim

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

module box() {
    difference() {
        // outer blank
        linear_extrude(rim_z) rrect(case_x, case_y, corner_r);

        // cavity (open top)
        translate([wall, wall, bottom_wall])
            linear_extrude(box_h + 1) rrect(inner_x, inner_y, max(corner_r - wall, 0.6));

        // snap groove around the inner wall perimeter (inner hole shrunk 0.1/side
        // so the cut overlaps the cavity void -> no coincident face -> manifold)
        translate([0, 0, bottom_wall + snap_z]) linear_extrude(snap_h)
            difference() {
                translate([wall - snap_d, wall - snap_d])
                    rrect(inner_x + 2*snap_d, inner_y + 2*snap_d, max(corner_r - wall + snap_d, 0.6));
                translate([wall + 0.1, wall + 0.1]) rrect(inner_x - 0.2, inner_y - 0.2, max(corner_r - wall, 0.6));
            }

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
}

// ======================================================================
// lid (printable part 2) — perimeter lip + snap rib + FRONT arrow
// ======================================================================
module lid() {
    // outer footprint of the lip (fits inside the box with clearance)
    lx = inner_x - 2*lid_clear;
    ly = inner_y - 2*lid_clear;
    union() {
        // top plate (rests on the box rim)
        difference() {
            translate([0, 0, rim_z]) linear_extrude(lid_top_t) rrect(case_x, case_y, corner_r);
            // debossed FRONT arrow (+X), upper area
            translate([case_x/2 - 5, case_y/2 + 6, rim_z + lid_top_t - 0.6])
                linear_extrude(1.0) arrow2d();
            // debossed part-number label, lower area
            translate([case_x/2, case_y/2 - 6, rim_z + lid_top_t - 0.6])
                linear_extrude(1.0)
                    text("ICM-20948", size = 4.5, halign = "center", valign = "center",
                         font = "Liberation Sans:style=Bold");
        }
        // lip ring hanging down into the box
        translate([wall + lid_clear, wall + lid_clear, rim_z - lid_lip_h])
            linear_extrude(lid_lip_h)
                difference() {
                    rrect(lx, ly, max(corner_r - wall - lid_clear, 0.6));
                    translate([lid_lip_t, lid_lip_t])
                        rrect(lx - 2*lid_lip_t, ly - 2*lid_lip_t, 0.6);
                }
        // snap rib on the lip outer face (clicks into the box groove)
        translate([0, 0, bottom_wall + snap_z]) linear_extrude(snap_h)
            difference() {
                translate([wall + lid_clear - snap_d, wall + lid_clear - snap_d])
                    rrect(lx + 2*snap_d, ly + 2*snap_d, max(corner_r - wall - lid_clear + snap_d, 0.6));
                translate([wall + lid_clear, wall + lid_clear]) rrect(lx, ly, max(corner_r - wall - lid_clear, 0.6));
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

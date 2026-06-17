// =========================================================================
// Light Sensor Enclosure  —  Adafruit TSL2591 lux-sensor breakout (#1980)
// Dash-mounted ambient-light sensor for Pi display auto-dim (black-box/EDR).
// Spec: enclosure2/specs/light-sensor-case-design.md
// Iris (UI/UX Designer)
//   v1  2026-06-16  — CIO interview design (one-piece, 15deg internal tilt,
//                     slide-in diffuser plate, passenger-side cable exit).
//
// Render (git bash; numeric part selector avoids CLI quote-mangling):
//   "/c/Program Files/OpenSCAD/openscad.exe" -o stl/shell.stl            -D part=1 light-sensor-case.scad
//   "/c/Program Files/OpenSCAD/openscad.exe" -o stl/diffuser-template.stl -D part=2 light-sensor-case.scad
//
// =========================================================================
// AUTHORITATIVE BOARD FACTS (Adafruit #1980 datasheet p.22, dims in INCHES)
//   Board overall : 0.75 x 0.65 in  = 19.05 x 16.51 mm
//   Mount holes   : Phi 0.10 in (2.54 mm, ~M2.5), c-c 0.55 in (13.97 mm)
//   Hole inset    : 0.10 in (2.54 mm) from each side; ~0.10 in from mount edge
//   Header        : 6-pin 0.1in along one long edge (Vin 3vo GND SDA SCL Int)
//
// FRAME:
//   +X = board long axis (19.05). Header runs along the LOW-Y long edge.
//   +Y = board short axis (16.51). Y=0 (local) = header edge = LOW side.
//                                  high Y = mount-hole edge = HIGH side (tilted up).
//   +Z = up.  Z=0 = outer BOTTOM face (the VHB dash face).
//   Board tilts +15deg about X, pivoting at the header (low-Y) edge.
//   Cable exits the LOW-Y wall (header edge) -> faces passenger side.
//   Diffuser plate slides in along +X from the X=0 short end; back-stop at far X.
// =========================================================================

part = 0;   // 0 = assembly view, 1 = shell (printable), 2 = diffuser plate template

// ---- Board facts --------------------------------------------------------
board_w      = 19.05;   // X long edge
board_h      = 16.51;   // Y short edge
board_t      = 1.60;    // PCB thickness (typ)
comp_h       = 1.50;    // approx component stack on top face (chip/caps) for ghost
hole_dx      = 13.97;   // mount-hole c-c (X)
hole_inset_x = (board_w - hole_dx) / 2;   // 2.54 from each side edge
hole_inset_y = 2.54;    // from the high-Y (mount) edge

// ---- Geometry knobs -----------------------------------------------------
tilt        = 15;       // board tilt (deg)
clr         = 0.75;     // board-to-wall clearance, each side
wall        = 2.0;      // side-wall thickness
bottom_wall = 2.0;      // floor thickness
cable_clr   = 2.5;      // space under header edge (solder joints + wires)
air_gap     = 1.5;      // board top -> diffuser underside
corner_r    = 1.5;      // outer corner radius

// ---- Diffuser slide cover ----------------------------------------------
lid_thickness = 1.0;    // <-- PLATE THICKNESS PARAM (retune to chosen material)
lid_clear     = 0.3;    // groove clearance (slide fit)
groove_depth  = 1.2;    // how far each plate edge sits into the long walls
top_lip       = 1.5;    // wall material above the diffuser (capture + recess look)

// ---- Fastening ----------------------------------------------------------
post_r   = 2.6;         // standoff boss outer radius
pilot_r  = 1.05;        // M2.5 self-tap pilot (Phi 2.1)
pilot_dz = 6.0;         // pilot depth into post (along board normal)

// ---- Cable exit (passenger side, low-Y wall) ----------------------------
cable_w  = 7.0;         // rounded slot width  (4-5 small wires)
cable_h  = 3.5;         // rounded slot height

// ---- VHB recess (bottom) ------------------------------------------------
vhb_lip    = 1.5;       // perimeter lip width around the recess
vhb_recess = 0.5;       // recess depth

// ---- Derived ------------------------------------------------------------
header_rest_z = bottom_wall + cable_clr;          // Z of board bottom at header edge
x0 = wall + clr;                                  // board local origin X (world)
y0 = wall + clr;                                  // board local origin Y (world)
inner_x = board_w + 2*clr;
inner_y = board_h + 2*clr;
case_x  = inner_x + 2*wall;
case_y  = inner_y + 2*wall;

diffuser_floor = board_t + air_gap;               // board-local Z, plate underside
diffuser_roof  = diffuser_floor + lid_thickness + lid_clear;
case_top_local = diffuser_roof + top_lip;         // board-local Z of the tilted rim
raw_h = 22;                                        // tall blank; trimmed by tilt plane

$fn = 48;

// ======================================================================
// helpers
// ======================================================================

// Put children into board-local space (origin at header-edge X=0 corner,
// board lying in +X/+Y, tilted +tilt about X, pivot at the header edge).
module on_board() {
    translate([x0, y0, header_rest_z]) rotate([tilt, 0, 0]) children();
}

// rounded rectangle (2D), corner radius r
module rrect(x, y, r) {
    hull() {
        translate([r,   r  ]) circle(r);
        translate([x-r, r  ]) circle(r);
        translate([r,   y-r]) circle(r);
        translate([x-r, y-r]) circle(r);
    }
}

// ======================================================================
// board ghost (assembly view only)
// ======================================================================
module board_ghost() {
    color("DarkSlateBlue")
        on_board() cube([board_w, board_h, board_t]);
    // component stack (chip + caps) on top face
    color("DimGray")
        on_board() translate([board_w*0.25, board_h*0.30, board_t])
            cube([board_w*0.5, board_h*0.4, comp_h]);
    // screw heads at the mount holes
    color("Silver")
        for (sx = [hole_inset_x, board_w - hole_inset_x])
            on_board() translate([sx, board_h - hole_inset_y, board_t])
                cylinder(h = 1.6, r = 2.3);
}

// diffuser plate (template / ghost) in board-local space
module diffuser_plate() {
    // spans inner footprint; long edges sit groove_depth into each wall
    py0 = -clr - (groove_depth - 0.4);
    py1 = (board_h + clr) + (groove_depth - 0.4);
    on_board()
        translate([-clr, py0, diffuser_floor])
            cube([inner_x, py1 - py0, lid_thickness]);
}

// ======================================================================
// standoffs + ledge (printed, part of the shell)
// ======================================================================
module standoff(sx, sy) {
    // board-bottom height at this (local) point, in world Z
    bz = header_rest_z + sy * sin(tilt);
    difference() {
        // vertical post from floor up past the board-bottom plane
        translate([x0 + sx, y0 + sy*cos(tilt), bottom_wall])
            cylinder(h = (bz - bottom_wall) + 2, r = post_r);
        // trim top flush to the (tilted) board-bottom plane
        on_board() translate([-50, -50, 0]) cube([100, 100, 60]);
        // pilot hole, drilled along the board normal (tilted)
        on_board() translate([sx, sy, -pilot_dz]) cylinder(h = pilot_dz + 2, r = pilot_r);
    }
}

module standoffs() {
    for (sx = [hole_inset_x, board_w - hole_inset_x])
        standoff(sx, board_h - hole_inset_y);
}

module header_ledge() {
    // line support under the header (low-Y) edge, flush to board bottom at Y=0
    lw = 2.2;   // ledge width in Y
    intersection() {
        translate([x0, y0 - 0.1, bottom_wall])
            cube([board_w, lw, header_rest_z - bottom_wall + 2]);
        // trim its top to the board-bottom plane
        on_board() translate([-50, -50, -60]) cube([100, 100, 60]);
    }
}

// ======================================================================
// shell
// ======================================================================
module shell() {
    difference() {
        // ---- outer blank ----
        linear_extrude(raw_h) rrect(case_x, case_y, corner_r);

        // ---- interior cavity (open top) ----
        translate([wall, wall, bottom_wall])
            linear_extrude(raw_h)
                rrect(inner_x, inner_y, max(corner_r - wall, 0.6));

        // ---- trim the top to the tilted (board-parallel) rim plane ----
        on_board() translate([-50, -50, case_top_local]) cube([100, 100, 60]);

        // ---- diffuser grooves: low-Y long wall ----
        on_board() translate([-clr - wall - 3, -clr - groove_depth, diffuser_floor])
            cube([inner_x + clr + wall + 3, groove_depth, lid_thickness + lid_clear]);
        // ---- diffuser grooves: high-Y long wall ----
        on_board() translate([-clr - wall - 3, board_h + clr, diffuser_floor])
            cube([inner_x + clr + wall + 3, groove_depth, lid_thickness + lid_clear]);
        // ---- insertion mouth through the near (X=0) short wall ----
        on_board() translate([-clr - wall - 3, -clr - groove_depth - 0.5, diffuser_floor])
            cube([wall + 3.5, inner_y + 2*groove_depth + 1, lid_thickness + lid_clear]);

        // ---- cable exit slot (low-Y wall, passenger side), rounded ----
        translate([case_x/2, wall/2, bottom_wall + cable_h/2])
            rotate([90, 0, 0])
                hull() {
                    translate([-(cable_w-cable_h)/2, 0, 0]) cylinder(h = wall*3, r = cable_h/2, center = true);
                    translate([ (cable_w-cable_h)/2, 0, 0]) cylinder(h = wall*3, r = cable_h/2, center = true);
                }

        // ---- VHB recess on the bottom face ----
        translate([vhb_lip, vhb_lip, -0.01])
            linear_extrude(vhb_recess + 0.01)
                rrect(case_x - 2*vhb_lip, case_y - 2*vhb_lip, max(corner_r - vhb_lip, 0.4));
    }
    // standoffs + ledge live inside the cavity
    standoffs();
    header_ledge();
}

// ======================================================================
// part dispatch
// ======================================================================
if (part == 1) {
    shell();
} else if (part == 2) {
    // flat diffuser template, laid flat for printing / as a cut template
    translate([-clr, -clr - (groove_depth - 0.4), 0])
        cube([inner_x, (board_h + 2*clr) + 2*(groove_depth - 0.4), lid_thickness]);
} else {
    // assembly view
    shell();
    %board_ghost();
    color("LightCyan", 0.45) diffuser_plate();
}

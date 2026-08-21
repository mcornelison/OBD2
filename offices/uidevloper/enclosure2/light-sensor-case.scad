// =========================================================================
// Light Sensor Enclosure  —  Adafruit TSL2591 lux-sensor breakout (#1980)
// Dash-mounted ambient-light sensor for Pi display auto-dim (black-box/EDR).
// Spec: enclosure2/specs/light-sensor-case-design.md
// Iris (UI/UX Designer)
//   v1  2026-06-16  — CIO interview design (one-piece, 15deg internal tilt,
//                     slide-in diffuser plate, passenger-side cable exit).
//   v6.1 2026-06-19 — CIO 1st-print fit-check: header ledge (the "foot") sat in
//                     the cable path -> added a wire pass-through notch in the
//                     ledge aligned with the cable-exit slot. (Recess already flat.)
//   v6.2 2026-06-19 — CIO 2nd fit-check: +3mm board-to-wall clearance/side
//                     (clr 1.0->4.0); back insertion mouth now OPEN to the rim to
//                     kill the top_lip bridge that sagged/failed at ~95%.
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

part = 0;   // 0 = assembly, 1 = shell, 2 = diffuser template,
            // 3 = cross-section thru a standoff, 4 = cross-section thru middle (cable)

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
clr         = 4.0;      // board-to-wall clearance, each side (v6.2 CIO: +3mm/side
                        //   over the original 1.0 for more wiring/handling room)
wall        = 2.0;      // side-wall thickness
bottom_wall = 2.0;      // floor thickness
cable_clr   = 5.5;      // space under header edge (solder joints + wires).
                        //   v6.3 CIO 2026-06-26: +3mm (2.5->5.5) for more wire room.
                        //   This single value drives board height, so it raises the
                        //   standoffs, the header ledge ("lower support") AND the
                        //   exterior walls/rim 3mm together (all referenced off it).
air_gap     = 1.5;      // board top -> diffuser underside
corner_r    = 1.5;      // outer corner radius

// ---- Diffuser slide cover ----------------------------------------------
lid_thickness = 1.5;    // <-- PLATE THICKNESS PARAM (sized for 1.0-1.5mm sheet)
lid_clear     = 0.3;    // groove clearance (slide fit)
groove_depth  = 1.0;    // groove cut depth into the walls (skin left = wall - this = 1.0)
top_lip       = 1.5;    // wall material above the diffuser (capture + recess look)
front_skin    = 1.0;    // outer skin left on the FRONT wall under its groove

// ---- Fastening ----------------------------------------------------------
post_r   = 2.6;         // standoff boss outer radius
pilot_r  = 1.05;        // M2.5 self-tap pilot (Phi 2.1)
pilot_dz = 6.0;         // pilot depth into post (along board normal)

// ---- Cable exit (passenger side, low-Y wall) ----------------------------
cable_w  = 10.0;        // rounded slot width  (v6.3 CIO 2026-06-26: 7->10, +3mm wider)
cable_h  = 3.5;         // rounded slot height

// ---- Bottom face --------------------------------------------------------
// FLAT (no VHB recess): the whole footprint contacts the bed for adhesion,
// and VHB tape sticks fine to a plain flat face. The recess was dropped after
// it caused perimeter-only bed contact -> repeated print release. See
// knowledge/docs/3d-printing/design-flat-base-and-orientation.md.

// ---- Air vents (thin rounded-end vertical slots) ------------------------
vent_w      = 1.3;      // slot width (the thin dimension)
vent_len    = 4.5;      // slot length (vertical)
vent_z      = 5.5;      // center Z of tall-wall vents
vent_z_side = 5.0;      // center Z of angled-wall vents (kept below the side grooves)

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
raw_h = 25;                                        // tall blank; trimmed by tilt plane
                                                   //   (v6.3: 22->25 to clear the +3mm rim)

// Plate FRONT-edge seating (board-local Y) and its WORLD position. The front
// groove is built in world coords from these so the tilt can't shear it through
// the front wall's outer face.
pf_yl   = -0.2;                                            // plate front edge (board-local Y)
pf_y_in = y0 + pf_yl*cos(tilt) - diffuser_floor*sin(tilt); // most-interior (+Y) front-edge point
pf_z_lo = header_rest_z + pf_yl*sin(tilt) + diffuser_floor*cos(tilt);
pf_z_hi = header_rest_z + pf_yl*sin(tilt) + diffuser_roof*cos(tilt);

$fn = 48;

// ======================================================================
// helpers
// ======================================================================

// Put children into board-local space (origin at header-edge X=0 corner,
// board lying in +X/+Y, tilted +tilt about X, pivot at the header edge).
module on_board() {
    translate([x0, y0, header_rest_z]) rotate([tilt, 0, 0]) children();
}

// vertical rounded-end vent slot, cut THROUGH a wall along Y (for front/back walls)
module vent_slot_Y() {
    hull() for (s = [-1, 1])
        translate([0, 0, s * (vent_len - vent_w) / 2])
            rotate([90, 0, 0]) cylinder(h = wall * 3, r = vent_w / 2, center = true);
}

// vertical rounded-end vent slot, cut THROUGH a wall along X (for the angled walls)
module vent_slot_X() {
    hull() for (s = [-1, 1])
        translate([0, 0, s * (vent_len - vent_w) / 2])
            rotate([0, 90, 0]) cylinder(h = wall * 3, r = vent_w / 2, center = true);
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

// diffuser plate (ghost) in board-local space — resting downhill against the
// short (low-Y) wall, edges captured groove_depth into the two angled walls.
module diffuser_plate() {
    px0 = -clr - (groove_depth - 0.4);            // edges seat into L/R grooves
    px1 = (board_w + clr) + (groove_depth - 0.4);
    py0 = pf_yl;                                  // front edge seats into front groove
    py1 = (board_h + clr) - 0.3;                  // back edge near the mouth
    on_board()
        translate([px0, py0, diffuser_floor])
            cube([px1 - px0, py1 - py0, lid_thickness]);
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
    // line support under the header (low-Y) edge, flush to board bottom at Y=0.
    // v6.1 (CIO 1st-print fit-check): the ledge sits right inside the cable-exit
    // wall and blocked the wires. Cut a pass-through NOTCH aligned with the cable
    // slot so the header wires route straight out. The ledge still supports the
    // header edge on both sides of the notch.
    lw = 2.2;            // ledge width in Y
    notch_w = cable_w + 1.5;   // wire clearance through the ledge (matches cable slot + margin)
    difference() {
        intersection() {
            translate([x0, y0 - 0.1, bottom_wall])
                cube([board_w, lw, header_rest_z - bottom_wall + 2]);
            // trim its top to the board-bottom plane
            on_board() translate([-50, -50, -60]) cube([100, 100, 60]);
        }
        // wire pass-through notch, centered on the cable exit slot (full height)
        translate([case_x/2 - notch_w/2, y0 - 1.1, bottom_wall - 1])
            cube([notch_w, lw + 2, header_rest_z - bottom_wall + 4]);
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

        // ---- diffuser U-CHANNEL: BLIND interior grooves on LEFT, RIGHT and ----
        // FRONT walls; OPEN at the BACK (tall) wall = insertion mouth. The plate
        // slides in from the back, rides the two side grooves, and seats its front
        // edge into the front groove (gravity pulls it down-slope into the stop).
        // Groove depth < wall thickness, so all outer faces stay clean — the only
        // opening that breaks an outer face is the back mouth.
        // LEFT (X=0) wall groove — tilted, runs front->back. Depth is in X so the
        // tilt does NOT shear it; leaves (wall - groove_depth) outer skin.
        on_board() translate([-clr - groove_depth, -clr, diffuser_floor])
            cube([groove_depth, inner_y + groove_depth + wall + 2, lid_thickness + lid_clear]);
        // RIGHT (X=max) wall groove — tilted, runs front->back:
        on_board() translate([board_w + clr, -clr, diffuser_floor])
            cube([groove_depth, inner_y + groove_depth + wall + 2, lid_thickness + lid_clear]);
        // FRONT (low-Y / short) wall groove — WORLD-aligned horizontal recess in the
        // inner face at the plate's front-edge height, so the tilt can't shear it out
        // the front. Leaves front_skin of outer wall; the down-slope seating stop.
        translate([wall - groove_depth, front_skin, pf_z_lo - 0.4])
            cube([inner_x + 2*groove_depth, (pf_y_in + 0.3) - front_skin, (pf_z_hi + 0.4) - (pf_z_lo - 0.4)]);
        // BACK (tall) wall insertion mouth — OPEN ALL THE WAY TO THE RIM (v6.2).
        // Previously the wall continued above the mouth (the top_lip), which forced
        // a full-width unsupported BRIDGE across the mouth at the top — it sagged and
        // failed at ~95%. Removing that strip eliminates the bridge entirely (no
        // supports needed). The diffuser is still retained by the L/R side grooves +
        // the front-edge stop + gravity (it seats down-slope toward the front).
        on_board() translate([-clr - groove_depth, board_h + clr, diffuser_floor])
            cube([inner_x + 2*groove_depth, wall + 2, (case_top_local - diffuser_floor) + 6]);

        // ---- cable exit slot (low-Y wall, passenger side), rounded ----
        translate([case_x/2, wall/2, bottom_wall + cable_h/2])
            rotate([90, 0, 0])
                hull() {
                    translate([-(cable_w-cable_h)/2, 0, 0]) cylinder(h = wall*3, r = cable_h/2, center = true);
                    translate([ (cable_w-cable_h)/2, 0, 0]) cylinder(h = wall*3, r = cable_h/2, center = true);
                }

        // ---- bottom face is FLAT (VHB recess dropped — see param note) ----

        // ---- air vents: 3 vertical on the TALL (back) wall, evenly spaced in X ----
        for (i = [1:3])
            translate([case_x * i/4, case_y - wall/2, vent_z]) vent_slot_Y();
        // ---- air vents: 2 vertical on EACH angled (X-end) wall, evenly spaced in Y ----
        for (j = [1:2]) {
            translate([wall/2,          case_y * j/3, vent_z_side]) vent_slot_X();
            translate([case_x - wall/2, case_y * j/3, vent_z_side]) vent_slot_X();
        }
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
    // flat diffuser template (cut guide for the plastic sheet), laid flat.
    // width spans into both side grooves; length spans front edge -> mouth.
    cube([inner_x + 2*(groove_depth - 0.4), (board_h + clr - 0.3) - pf_yl, lid_thickness]);
} else if (part == 3 || part == 4) {
    // cross-section through the tilt. Keep the half with X >= section_x and show
    // the cut face. part 3 cuts through a screw standoff; part 4 through the middle.
    section_x = (part == 3) ? (x0 + hole_inset_x) : (case_x / 2);
    difference() {
        union() {
            shell();
            color("DarkSlateBlue") on_board() cube([board_w, board_h, board_t]);
            color("DimGray") on_board()
                translate([board_w*0.25, board_h*0.30, board_t]) cube([board_w*0.5, board_h*0.4, comp_h]);
            color("LightCyan") diffuser_plate();
        }
        translate([-200, -200, -200]) cube([200 + section_x, 400, 400]);
    }
} else {
    // assembly view
    shell();
    %board_ghost();
    color("LightCyan", 0.45) diffuser_plate();
}

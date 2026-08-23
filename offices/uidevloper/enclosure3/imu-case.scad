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
//   v3   2026-06-26  — standoff_h 3->6 (taller, walls/rim rise with it); cable_w 7->10.
//   v3.1 2026-07-31  — cable_w 10->11: wider wire exit so the wiring CONNECTOR fits
//                     through the opening (box-only re-slice; lid unchanged).
//   v3.2 2026-08-12  — CIO: 4 external MOUNTING TABS (screw the case to wood/plastic/
//                     metal), one at each corner, with COUNTERSUNK screw holes.
//                     Frame per CIO: tabs EXTEND on the SHORT sides (=the +/-X end
//                     walls, since +X is the board long axis) and are FLUSH with the
//                     long lengthwise sides (their outer Y edges sit on the +/-Y wall
//                     planes). So the footprint grows in X only: 39.40 -> 59.40.
//                     M3 / #6 through (3.4) + 90deg countersink to 7.0 (CIO choice:
//                     truly flush flat-head, not a counterbore). Tabs are COPLANAR
//                     WITH THE FLAT BOTTOM (z=0..tab_t) -- keeps the flat-base print
//                     rule AND adds bed contact (see knowledge/pattern-flat-base-...).
//                     Box-only change; lid untouched.
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
standoff_h  = 6.0;    // board lift off the floor (under-board clearance + wiring).
                      //   v3 CIO 2026-06-26: +3mm (3->6). box_h = standoff_h + board_t
                      //   + comp_clear, so this lifts the board 3mm AND raises the
                      //   walls/rim 3mm together (comp_clear above the board preserved).
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

// ---- Mounting tabs (v3.2 — CIO 2026-08-12) ------------------------------
// 4 external ears, one per corner, for screwing the case down to wood/plastic/
// metal. CIO frame: they EXTEND on the SHORT sides (the +/-X end walls) and are
// FLUSH with the LONG lengthwise sides -- so each tab's outer Y edge lies on the
// y=0 / y=case_y plane and the case gets no wider, only longer.
//
// The tabs sit at z = 0..tab_t, i.e. COPLANAR WITH THE FLAT BOTTOM. Two reasons:
// the case still sits flat against whatever it is screwed to (no rocking on a
// proud tab), and the extra footprint is free bed adhesion on a printer that has
// fought adhesion on this family of parts.
tab_len  = 10.0;   // how far the tab projects PAST the end wall (X)
tab_w    = 10.0;   // tab width along Y (sits in the corner, flush to the long wall)
tab_t    = 5.0;    // tab thickness (Z). Must leave land under the countersink --
                   //   see csk_depth below; 5.0 - 1.8 = 3.2mm of material remains.
tab_r    = 2.0;    // outer corner rounding (matches corner_r)
tab_ovl  = 3.0;    // how far the tab interpenetrates the case body, so the union
                   //   is a true merge and not two solids sharing a face (the v2
                   //   coincident-face manifold bug). Buried; > tab_r so the tab's
                   //   inner rounded corners never surface.

// ---- Mounting screws: M3 / #6, countersunk flush (CIO 2026-08-12) -------
// CIO picked COUNTERSINK over counterbore: nothing protrudes at all.
// 90deg included angle takes an M3 machine screw directly; a #6 wood screw (82deg)
// seats on the upper rim of the cone -- the standard, acceptable compromise for a
// hole meant to accept both.
mnt_scr_d   = 3.4;                          // through-hole (M3 clearance / #6 shank)
mnt_csk_d   = 7.0;                          // countersink diameter at the tab face
mnt_scr_off = 5.0;                          // hole center, out from the end-wall face
                                            //   (= 5.0 from the tab tip too: centered)
mnt_csk_depth = (mnt_csk_d - mnt_scr_d)/2;  // 90deg cone => depth == radial run = 1.8
// (tab_xy + mnt_scr_xy are DERIVED from case_x/case_y -- see the Derived section
//  below. They must be declared after those, not here.)

// ---- Vents (thin rounded-end vertical slots, like enclosure #2) ---------
vent_w   = 1.3;
vent_len = 4.5;
vent_z   = 4.5;       // center Z of wall vents (above floor)

// ---- Wire exit (4-5 wires, -Y long wall) --------------------------------
cable_w  = 11.0;      // v3.1 CIO 2026-07-31: 10->11, wider so the wiring CONNECTOR
                      //   (not just the wires) passes through the exit. Opening is now
                      //   11.0 wide x cable_h (5.0) tall obround. Box-only change.
cable_h  = 5.0;       // taller so wires clear the board (CIO 2026-06-17)
cable_z  = 3.0;       // center Z above floor; lowered so the slot drops into the under-board gap

// ---- Bottom face --------------------------------------------------------
// FLAT (no VHB recess): full first-layer bed contact for reliable MK3S+
// adhesion. A recessed bottom only contacts on a thin lip-ring (~24% area) and
// releases mid-print. VHB tape sticks fine to a plain flat face.
// See knowledge/docs/3d-printing/design-flat-base-and-orientation.md.

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

// (v3.2) mounting-tab footprints: [x-origin, y-origin] of each rounded rect,
// each of size (tab_len + tab_ovl) x tab_w. Outer Y edges land exactly on y=0 and
// y=case_y -> FLUSH with the long walls, as the CIO specified.
tab_xy = [ [-tab_len,          0             ],   // -X end, -Y corner
           [-tab_len,          case_y - tab_w],   // -X end, +Y corner
           [ case_x - tab_ovl, 0             ],   // +X end, -Y corner
           [ case_x - tab_ovl, case_y - tab_w] ]; // +X end, +Y corner

// (v3.2) mounting-screw centers (world XY): mnt_scr_off out from each end wall,
// centered across the tab width.
mnt_scr_xy = [ [-mnt_scr_off,          tab_w/2         ],
               [-mnt_scr_off,          case_y - tab_w/2],
               [ case_x + mnt_scr_off, tab_w/2         ],
               [ case_x + mnt_scr_off, case_y - tab_w/2] ];

// (v3.2) overall footprint incl. tabs — for the spec + slicer sanity check
mount_x = case_x + 2*tab_len;   // 39.40 -> 59.40
mount_y = case_y;               // unchanged: tabs are flush on the long sides

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

// (v3.2) the 4 mounting ears, as a positive solid. Unioned into the box blank
// BEFORE the cavity is subtracted, so any tab material that reaches into the
// interior is carved back out by the cavity cut rather than intruding.
module mount_tabs() {
    for (t = tab_xy)
        translate([t[0], t[1], 0])
            linear_extrude(tab_t) rrect(tab_len + tab_ovl, tab_w, tab_r);
}

// (v3.2) through-hole + 90deg countersink, cut from each tab.
module mount_screw_cuts() {
    for (p = mnt_scr_xy) translate([p[0], p[1], 0]) {
        // through-hole, over-long both ends for a clean cut
        translate([0, 0, -1]) cylinder(h = tab_t + 2, r = mnt_scr_d/2);
        // the cone: opens out to mnt_csk_d at the tab's top face
        translate([0, 0, tab_t - mnt_csk_depth])
            cylinder(h = mnt_csk_depth, r1 = mnt_scr_d/2, r2 = mnt_csk_d/2);
        // and clear everything above the face, so a proud head is never trapped
        translate([0, 0, tab_t]) cylinder(h = 2, r = mnt_csk_d/2);
    }
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
        // outer blank + (v3.2) the 4 corner mounting ears, merged as ONE positive
        // before any cutting -- so the cavity below trims tab material that reaches
        // inside, and the screw cuts land on real tab geometry.
        union() {
            linear_extrude(rim_z) rrect(case_x, case_y, corner_r);
            mount_tabs();
        }

        // (v3.2) countersunk mounting-screw holes
        mount_screw_cuts();

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
        // vents: 2 on each short (X-end) wall.
        //   v3.2: moved inboard from case_y*[1/3, 2/3] (= y 10.59 / 21.19) to
        //   case_y*[0.40, 0.60] (= y 12.71 / 19.07). Reason: the new corner mounting
        //   tabs occupy y 0..tab_w and case_y-tab_w..case_y and stand 5mm tall, while
        //   these vents span z 4.25..8.75 -- at the old spacing the vent cut clipped
        //   the tab's inner top corner by 0.06mm. Sub-resolution at a 0.4mm nozzle,
        //   so it would not have shown in this print, but it is a latent trap: any
        //   future tab_w increase turns it into a real notch in a load-bearing ear.
        //   CONSTRAINT to preserve: tab_w < case_y*0.40 - vent_w/2 (= 12.06).
        for (vy = [0.40, 0.60]) {
            translate([wall/2,          case_y * vy, bottom_wall + vent_z]) vent_slot_X();
            translate([case_x - wall/2, case_y * vy, bottom_wall + vent_z]) vent_slot_X();
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

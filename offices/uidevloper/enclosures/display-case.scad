// =========================================================================
// OBD2 Display Case for OSOYOO 3.5" HDMI Capacitive Touch Screen v3.0
// Model: 2024009100
// Spec: offices/uidevloper/enclosures/display-case-spec.md
// Iris (UI/UX Designer)
//   v1 prototype  2026-05-22
//   v2 rebuild    2026-05-28 (CIO fit-check)
//   v2.1 rebuild  2026-05-29 — driven by the OFFICIAL 2024009100 datasheet
//                 (datasheets/2024009100_hdmi_datasheet.pdf) per CIO.
//
// Render:
//   openscad -o stl/back_shell.stl  -D part=1 display-case.scad
//   openscad -o stl/front_shell.stl -D part=2 display-case.scad
//
// =========================================================================
// AUTHORITATIVE FACTS (OSOYOO 2024009100 datasheet — override all ruler reads)
//   Glass / front panel : 93.44 x 60.00 x 7.00 mm
//   Active display area  : 73.44 x 48.96 mm  (borders 10.0 long / 5.52 short)
//   PCB                  : 85.0 x 49.0 mm        <-- was mis-measured as 56 wide
//   Mounting thread      : M2.5,  holes Phi 3 mm
//   Mount pattern (TRAPEZOID, from the drawing):
//       top row    c-c 50 mm : 28.5 & 78.5 mm from left, 3.5 mm from top edge
//       bottom row c-c 58 mm : 23.6 & 81.6 mm from left, 3.5 mm from bottom edge
//   Connectors: micro-HDMI + brightness + power switch on the TOP long edge;
//               Type-C (power+touch) on the LEFT short edge.
//
// FRAME (datasheet landscape, viewed from the BACK):
//   model +X = long axis toward the OSOYOO logo (RIGHT short edge)
//   model  X = 0  -> LEFT short edge  (Type-C)         -> +6mm clearance here
//   model +Y = TOP long edge (HDMI / buttons / power)  -> +6mm clearance here
//   model  Y = 0  -> BOTTOM long edge
//   model  Z = 0  -> outer BACK face (front/bezel = +Z)
// =========================================================================

part = 0;   // 0 = assembly (with cues), 1 = back shell, 2 = front shell

// ---- Print / wall knobs -------------------------------------------------
wall_t      = 1.2;
bezel_width = 3.5;
corner_r    = 2.0;
print_tol   = 0.3;

// ---- #6 asymmetric clearance --------------------------------------------
clearance_top  = 6.0;   // +Y long edge  (micro-HDMI 90° head)
clearance_left = 6.0;   //  X=0 short edge (Type-C 90° head)

// ---- Display geometry (datasheet) ---------------------------------------
glass_x = 93.44;  // long axis (X)
glass_y = 60.00;  // short axis (Y)
glass_tol = 0.30;
glass_cutout_x = glass_x + 2*glass_tol;  // 94.04  FROZEN (v1 fit perfectly)
glass_cutout_y = glass_y + 2*glass_tol;  // 60.60  FROZEN

active_x = 73.44; // active display area (reference only)
active_y = 48.96;

pcb_x = 85.00;    // PCB long axis (X)
pcb_y = 56.00;    // PCB short axis (Y) -- datasheet "49mm" is the mount-hole
                  // vertical c-c (3.5 + 49 + 3.5 = 56), NOT the edge; CIO's 56 was right

// PCB registration behind the glass. Datasheet active area is centered on the
// glass and the v1 window fit with the PCB centered, so default = centered.
// If a fit-check shows a real offset, bump these (CIO gaps hinted ~+? right).
pcb_shift_x = 0.0;
pcb_shift_y = 0.0;

// ---- Mount holes (datasheet trapezoid; x from LEFT/X=0, y from BOTTOM/Y=0) -
mount_hole_dia = 3.0;
// RECTANGLE (verified from the datasheet: both rows share the same x; the
// "28.5/6.5/50" top chain dimensions the connectors, not the holes).
mh_left_x      = 23.6;   // left column (both rows)
mh_right_x     = 81.6;   // right column (both rows) -> horizontal c-c 58
mh_from_top    = 3.5;    // top row inset from +Y edge
mh_from_bottom = 3.5;    // bottom row inset from Y=0 edge -> vertical c-c 49

// ---- Standoff seats (CIO's own M2.5 x 11mm + 3mm HEX metal standoffs) ---
// Standoff = 11 mm hex body + 3 mm male stud. Per CIO the seat pocket is a
// plain ROUND cylinder, just big enough for the hex body to drop into and
// rest, with a through M2.5 clearance hole + flush countersink on the outside.
standoff_body_h   = 11.0;   // M2.5 x 11 hex body
standoff_stud_h   = 3.0;    // + 3 mm male stud (up through the PCB hole)
seat_pocket_d     = 7.5;    // ROUND pocket, generous fit for the hex body
seat_pocket_depth = 3.5;    // how deep the hex body seats
seat_cup_d        = seat_pocket_d + 3.0;  // outer cup (~10.5)
seat_cup_h        = 5.0;    // raised cup height above the floor
seat_screw_d      = 3.0;    // M2.5 screw clearance
seat_cs_d         = 5.2;    // countersink head dia (outside back face)
seat_cs_depth     = 1.6;    // countersink depth

// ---- #4 buttons (back face, near top-left per CIO) ----------------------
button_hole_dia  = 3.5;
button_from_left = [6.0, 16.0];  // centers from the LEFT (X=0) edge
button_from_top  = 3.0;          // "flush with top" — inset from +Y edge

// ---- Depth stack --------------------------------------------------------
pcb_thick   = 1.6;
glass_thick = 3.0;
pcb_back_z    = wall_t + seat_cup_h + (standoff_body_h - seat_pocket_depth);  // PCB on the hex body top
glass_front_z = pcb_back_z + pcb_thick + glass_thick;
back_shell_z  = glass_front_z;
front_shell_z = 3.0;
case_z        = back_shell_z + (front_shell_z - 1.8);

// ---- Case dimensions ----------------------------------------------------
base_case_x = glass_cutout_x + 2*(bezel_width + wall_t);
base_case_y = glass_cutout_y + 2*(bezel_width + wall_t);
case_x = base_case_x + clearance_left;   // extra on X=0 side
case_y = base_case_y + clearance_top;    // extra on +Y side

// ---- Frozen window placement (extra clearance on X=0 and +Y) ------------
window_origin_x = bezel_width + wall_t + clearance_left;  // push window +X
window_origin_y = bezel_width + wall_t;                   // extra falls on +Y
glass_cx = window_origin_x + glass_cutout_x/2;
glass_cy = window_origin_y + glass_cutout_y/2;

// ---- PCB + hole + button positions in case coords -----------------------
pcb_origin_x = glass_cx + pcb_shift_x - pcb_x/2;
pcb_origin_y = glass_cy + pcb_shift_y - pcb_y/2;

mh_y_top = pcb_origin_y + pcb_y - mh_from_top;     // +Y row
mh_y_bot = pcb_origin_y + mh_from_bottom;          // Y=0 row
mount_pts = [
    [pcb_origin_x + mh_left_x,  mh_y_top], [pcb_origin_x + mh_right_x, mh_y_top],
    [pcb_origin_x + mh_left_x,  mh_y_bot], [pcb_origin_x + mh_right_x, mh_y_bot]
];

button_y   = pcb_origin_y + pcb_y - button_from_top;   // near +Y edge (flush top)
button_pts = [ for (l = button_from_left) [pcb_origin_x + l, button_y] ];

// ---- Snap clips ---------------------------------------------------------
clip_width = 6.0; clip_thickness = 1.5; clip_height = 3.0;
clip_hook_proud = 0.6; clip_hook_height = 1.0;
clip_positions_long  = [case_x / 3, case_x * 2 / 3];   // pairs on long edges
clip_positions_short = [case_y / 2];                   // singles on short edges

// ---- Magnet disc (back face center) -------------------------------------
disc_diameter = 25.0;
disc_x = case_x / 2;
disc_y = case_y / 2;

// ---- #7 vents (filtered grid; solid at seats + disc) --------------------
vent_hole_d       = 3.5;
vent_pitch        = 7.0;
vent_margin       = 6.0;
vent_keepout_disc = disc_diameter/2 + 4.0;
vent_keepout_seat   = seat_cup_d/2 + 3.0;
vent_keepout_button = button_hole_dia/2 + 3.5;   // keep vents off the button holes

// ---- #5 cable exit (LEFT / X=0 wall, aligned with the Type-C port) -------
// CIO: Type-C is on the LEFT short edge, 6.4 mm from the TOP (+Y), 9 mm long.
usbc_from_top  = 6.4;
usbc_len       = 9.0;
cable_slot_len = usbc_len + 9.0;   // 18mm — connector + 90° head clearance
cable_slot_h   = 14.0;             // along Z (taller opening per CIO)
cable_slot_cy  = (pcb_origin_y + pcb_y) - usbc_from_top - usbc_len/2;  // centered on the Type-C
cable_slot_z0  = wall_t + 2.0;

// =========================================================================
// HELPERS
// =========================================================================
module rounded_rect(x, y, r) { offset(r=r) offset(r=-r) square([x, y]); }
module rounded_box(x, y, z, r) { linear_extrude(height = z) rounded_rect(x, y, r); }
function dist_to_nearest_seat(x, y)   = min([ for (p = mount_pts)  norm([x-p[0], y-p[1]]) ]);
function dist_to_nearest_button(x, y) = min([ for (b = button_pts) norm([x-b[0], y-b[1]]) ]);

// =========================================================================
// BACK SHELL  (Z=0 = outer back; cavity opens +Z)
// =========================================================================
module back_shell() {
    difference() {
        union() {
            difference() {
                rounded_box(case_x, case_y, back_shell_z, corner_r);
                translate([wall_t, wall_t, wall_t])
                    rounded_box(case_x - 2*wall_t, case_y - 2*wall_t,
                                back_shell_z - wall_t + 0.1, max(corner_r - wall_t, 0.5));
            }
            for (p = mount_pts)
                translate([p[0], p[1], wall_t]) cylinder(h = seat_cup_h, d = seat_cup_d, $fn = 32);
        }
        // #5 cable exit on the LEFT (X=0) wall, aligned with Type-C
        translate([-0.1, cable_slot_cy - cable_slot_len/2, cable_slot_z0])
            cube([wall_t + 0.2, cable_slot_len, cable_slot_h]);
        // standoff seat cuts
        for (p = mount_pts) translate([p[0], p[1], 0]) seat_cut();
        // #4 button holes (back face)
        for (b = button_pts)
            translate([b[0], b[1], -0.1]) cylinder(h = wall_t + 0.2, d = button_hole_dia + print_tol, $fn = 24);
        // #7 vents
        vents();
    }
    clips();
}

module seat_cut() {
    // round socket the hex standoff body drops into and rests, open to the cavity/top
    translate([0, 0, wall_t + seat_cup_h - seat_pocket_depth])
        cylinder(h = seat_pocket_depth + 0.1, d = seat_pocket_d, $fn = 32);
    // M2.5 screw clearance through the pocket floor + case floor
    translate([0, 0, -0.1])
        cylinder(h = wall_t + seat_cup_h - seat_pocket_depth + 0.2, d = seat_screw_d, $fn = 24);
    // flush countersink on the OUTSIDE back face
    translate([0, 0, -0.01])
        cylinder(h = seat_cs_depth, d1 = seat_cs_d, d2 = seat_screw_d, $fn = 24);
}

module vents() {
    for (vx = [vent_margin : vent_pitch : case_x - vent_margin])
        for (vy = [vent_margin : vent_pitch : case_y - vent_margin])
            if (norm([vx - disc_x, vy - disc_y]) > vent_keepout_disc
                && dist_to_nearest_seat(vx, vy) > vent_keepout_seat
                && dist_to_nearest_button(vx, vy) > vent_keepout_button)
                translate([vx, vy, -0.1]) cylinder(h = wall_t + 0.2, d = vent_hole_d, $fn = 16);
}

module clips() {
    for (x = clip_positions_long) {
        translate([x, 0, back_shell_z]) snap_clip_finger();
        translate([x, case_y, back_shell_z]) rotate([0, 0, 180]) snap_clip_finger();
    }
    for (y = clip_positions_short) {
        translate([0, y, back_shell_z]) rotate([0, 0, -90]) snap_clip_finger();
        translate([case_x, y, back_shell_z]) rotate([0, 0, 90]) snap_clip_finger();
    }
}

module snap_clip_finger() {
    translate([-clip_width/2, 0, 0]) {
        cube([clip_width, clip_thickness, clip_height]);
        translate([0, clip_thickness, clip_height - clip_hook_height])
            cube([clip_width, clip_hook_proud, clip_hook_height]);
    }
}

// =========================================================================
// FRONT SHELL  (window FROZEN)
// =========================================================================
module front_shell() {
    interlock_inset = wall_t + print_tol;
    difference() {
        union() {
            translate([0, 0, 1.8]) rounded_box(case_x, case_y, 1.2, corner_r);
            translate([interlock_inset, interlock_inset, 0])
                rounded_box(case_x - 2*interlock_inset, case_y - 2*interlock_inset,
                            1.8, max(corner_r - interlock_inset, 0.5));
        }
        translate([window_origin_x, window_origin_y, -0.1])
            cube([glass_cutout_x, glass_cutout_y, front_shell_z + 0.2]);
        for (x = clip_positions_long) {
            translate([x - (clip_width+print_tol)/2, 0, 0])
                cube([clip_width+print_tol, wall_t+print_tol+clip_hook_proud+0.5, clip_height+0.5]);
            translate([x - (clip_width+print_tol)/2, case_y - (wall_t+print_tol+clip_hook_proud+0.5), 0])
                cube([clip_width+print_tol, wall_t+print_tol+clip_hook_proud+0.5, clip_height+0.5]);
        }
        for (y = clip_positions_short) {
            translate([0, y - (clip_width+print_tol)/2, 0])
                cube([wall_t+print_tol+clip_hook_proud+0.5, clip_width+print_tol, clip_height+0.5]);
            translate([case_x - (wall_t+print_tol+clip_hook_proud+0.5), y - (clip_width+print_tol)/2, 0])
                cube([wall_t+print_tol+clip_hook_proud+0.5, clip_width+print_tol, clip_height+0.5]);
        }
    }
}

// =========================================================================
// ASSEMBLY VIEW (visualization + orientation cues)
// =========================================================================
module assembly_view() {
    back_shell();
    color("cyan", 0.5) translate([0, 0, back_shell_z]) front_shell();
    for (b = button_pts) color("orange") translate([b[0], b[1], 0]) cylinder(h = wall_t, d = button_hole_dia, $fn = 24);
}

// =========================================================================
if (part == 1)      back_shell();
else if (part == 2) front_shell();
else                assembly_view();

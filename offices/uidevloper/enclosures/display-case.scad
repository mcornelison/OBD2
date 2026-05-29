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
pcb_y = 49.00;    // PCB short axis (Y)  -- datasheet (corrects ruler 56)

// PCB registration behind the glass. Datasheet active area is centered on the
// glass and the v1 window fit with the PCB centered, so default = centered.
// If a fit-check shows a real offset, bump these (CIO gaps hinted ~+? right).
pcb_shift_x = 0.0;
pcb_shift_y = 0.0;

// ---- Mount holes (datasheet trapezoid; x from LEFT/X=0, y from BOTTOM/Y=0) -
mount_hole_dia = 3.0;
mh_top_left_x  = 28.5;   mh_top_right_x  = 78.5;   // top row c-c 50
mh_bot_left_x  = 23.6;   mh_bot_right_x  = 81.6;   // bottom row c-c 58
mh_from_top    = 3.5;    // top row inset from +Y edge
mh_from_bottom = 3.5;    // bottom row inset from Y=0 edge

// ---- Standoff seats (CIO's own 10 mm metal standoffs) -------------------
standoff_h    = 10.0;
mount_pad_h   = 2.0;
seat_pad_d    = 8.5;
seat_screw_d  = 3.0;   // M2.5 clearance
seat_cs_d     = 5.2;   // flush countersink head dia (outside back face)
seat_cs_depth = 1.6;
seat_reg_d    = 6.6;   // locating recess for standoff base
seat_reg_h    = 0.6;

// ---- #4 buttons (back face, near top-left per CIO) ----------------------
button_hole_dia  = 3.5;
button_from_left = [6.0, 16.0];  // centers from the LEFT (X=0) edge
button_from_top  = 3.0;          // "flush with top" — inset from +Y edge

// ---- Depth stack --------------------------------------------------------
pcb_thick   = 1.6;
glass_thick = 3.0;
pcb_back_z    = wall_t + mount_pad_h + standoff_h;       // 13.2
glass_front_z = pcb_back_z + pcb_thick + glass_thick;     // 17.8
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
    [pcb_origin_x + mh_top_left_x,  mh_y_top], [pcb_origin_x + mh_top_right_x, mh_y_top],
    [pcb_origin_x + mh_bot_left_x,  mh_y_bot], [pcb_origin_x + mh_bot_right_x, mh_y_bot]
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
vent_keepout_seat = seat_pad_d/2 + 3.0;

// ---- #5 cable exit (TOP / +Y wall, toward the connector cluster) --------
cable_slot_w  = 32.0;   // along X
cable_slot_h  = 14.0;   // along Z (taller opening per CIO)
cable_slot_cx = pcb_origin_x + 30;   // biased toward left/connectors
cable_slot_z0 = wall_t + 2.0;

// =========================================================================
// HELPERS
// =========================================================================
module rounded_rect(x, y, r) { offset(r=r) offset(r=-r) square([x, y]); }
module rounded_box(x, y, z, r) { linear_extrude(height = z) rounded_rect(x, y, r); }
function dist_to_nearest_seat(x, y) = min([ for (p = mount_pts) norm([x-p[0], y-p[1]]) ]);

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
                translate([p[0], p[1], wall_t]) cylinder(h = mount_pad_h, d = seat_pad_d, $fn = 32);
        }
        // #5 cable exit on the TOP (+Y) wall
        translate([cable_slot_cx - cable_slot_w/2, case_y - wall_t - 0.1, cable_slot_z0])
            cube([cable_slot_w, wall_t + 0.2, cable_slot_h]);
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
    translate([0, 0, -0.1]) cylinder(h = wall_t + mount_pad_h + 0.2, d = seat_screw_d, $fn = 24);
    translate([0, 0, -0.01]) cylinder(h = seat_cs_depth, d1 = seat_cs_d, d2 = seat_screw_d, $fn = 24);
    translate([0, 0, wall_t + mount_pad_h - seat_reg_h]) cylinder(h = seat_reg_h + 0.1, d = seat_reg_d, $fn = 32);
}

module vents() {
    for (vx = [vent_margin : vent_pitch : case_x - vent_margin])
        for (vy = [vent_margin : vent_pitch : case_y - vent_margin])
            if (norm([vx - disc_x, vy - disc_y]) > vent_keepout_disc
                && dist_to_nearest_seat(vx, vy) > vent_keepout_seat)
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
    // cues (not printed): red = TOP/+Y (HDMI side), green = LEFT/X=0 (Type-C side)
    color("red")   translate([case_x/2 - 6, case_y - 3, back_shell_z]) cube([12, 3, 4]);
    color("green") translate([0, case_y/2 - 6, back_shell_z]) cube([3, 12, 4]);
    for (p = mount_pts) color("yellow") translate([p[0], p[1], 0]) cylinder(h = wall_t + mount_pad_h, d = seat_pad_d, $fn = 32);
    for (b = button_pts) color("orange") translate([b[0], b[1], 0]) cylinder(h = wall_t, d = button_hole_dia, $fn = 24);
}

// =========================================================================
if (part == 1)      back_shell();
else if (part == 2) front_shell();
else                assembly_view();

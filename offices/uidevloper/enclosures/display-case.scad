// =========================================================================
// OBD2 Display Case for OSOYOO 3.5" HDMI Capacitive Touch Screen v3.0
// Model: 2024009100
// Spec: offices/uidevloper/enclosures/display-case-spec.md
// Iris (UI/UX Designer) — 2026-05-22 — v1 prototype
//
// Render parts from command line:
//   openscad -o stl/back_shell.stl   -D part=1 display-case.scad
//   openscad -o stl/front_shell.stl  -D part=2 display-case.scad
//   openscad -o stl/plunger.stl      -D part=3 display-case.scad
//
// Or load in OpenSCAD GUI, change `part` variable, F6 to render, F7 to export.
// =========================================================================

// ---- Render selector ---------------------------------------------------
// 0 = assembly view (visualization only)
// 1 = back shell (printable)
// 2 = front shell (printable)
// 3 = plunger     (printable, tiny)
part = 0;

// ---- Tuning knobs (the most likely things you'll adjust) ----------------
wall_t          = 1.2;   // 3 perimeters at 0.4 mm nozzle
bezel_width     = 3.5;   // visible bezel frame around glass (each side)
cable_channel_z = 3.0;   // cavity depth behind PCB for cable routing
corner_r        = 2.0;   // external corner fillet
print_tol       = 0.3;   // global slop for snap-fit pieces

// ---- Display dimensions (from OSOYOO datasheet, 2024009100) -------------
glass_x         = 93.44; // glass outer X (long axis, landscape)
glass_y         = 60.00; // glass outer Y (short axis)
glass_tol_band  = 0.3;   // datasheet ±0.3 mm
glass_cutout_x  = glass_x + glass_tol_band*2; // 94.04
glass_cutout_y  = glass_y + glass_tol_band*2; //  60.6

pcb_x           = 85.00; // PCB outer X
pcb_y           = 49.00; // PCB outer Y
display_total_z = 7.00;  // glass-face to component-back, datasheet

// Mounting hole positions on PCB
// Datasheet shows Φ3 mm holes near each corner: 3.5 mm clear from short edge,
// 3.4 mm clear from long edge to the OUTER edge of the hole.
// Hole CENTERS ≈ 5 mm from short edge, 4.9 mm from long edge.
mount_hole_dia   = 3.0;
mount_inset_x    = 4.9;  // hole center from PCB long edge
mount_inset_y    = 5.0;  // hole center from PCB short edge

// ---- Case dimensions (derived) ------------------------------------------
case_x = glass_cutout_x + (bezel_width + wall_t) * 2; // ~104.04
case_y = glass_cutout_y + (bezel_width + wall_t) * 2; //  ~70.6

front_shell_z = 3.0;  // bezel face (1.2) + interlock lip into back shell (1.8)
back_shell_z  = wall_t + display_total_z + cable_channel_z + front_shell_z - wall_t;
// back_shell_z = 1.2 + 7 + 3 + 1.8 = 13.0 (the front-shell lip nests into the back shell rim by 1.8)

case_z = back_shell_z + (front_shell_z - 1.8); // total external Z = back_shell_z + front shell BEZEL part only

// Display position inside cavity (centered)
display_origin_x = (case_x - glass_x) / 2;
display_origin_y = (case_y - glass_y) / 2;

// PCB origin within case (centered)
pcb_origin_x = (case_x - pcb_x) / 2;
pcb_origin_y = (case_y - pcb_y) / 2;

// Mount hole positions in case coords
hole_x1 = pcb_origin_x + mount_inset_x;
hole_x2 = pcb_origin_x + pcb_x - mount_inset_x;
hole_y1 = pcb_origin_y + mount_inset_y;
hole_y2 = pcb_origin_y + pcb_y - mount_inset_y;

// ---- PCB mount bosses ---------------------------------------------------
// Heat-set insert for M2.5 brass insert: ~3.5 mm hole diameter, ~5 mm depth typical
boss_outer_d  = 6.0;
boss_inner_d  = 3.5;
// Boss height must clear tallest back-of-PCB component (~4 mm HDMI port)
// At corners there are no components, so the boss can be shorter than the
// component clearance — but the PCB rests on the boss TOP, and components hang
// in the cavity. boss_h = cable_channel_z keeps the PCB flat against the cavity floor offset.
boss_h        = cable_channel_z;

// ---- Snap clips on back shell rim ---------------------------------------
clip_width       = 6.0;
clip_thickness   = 1.5;
clip_height      = 3.0;        // length of cantilever finger above rim
clip_hook_proud  = 0.6;        // how far the hook protrudes inward
clip_hook_height = 1.0;        // hook vertical thickness

// Clip positions: 6 total. 2 per long edge, 1 per short edge.
clip_positions_long  = [case_x * 0.30, case_x * 0.70];
clip_positions_short = [case_y * 0.50];

// ---- Vents (back face) --------------------------------------------------
vent_slot_w     = 2.0;
vent_slot_l     = 50.0;
vent_group_n    = 5;       // 5 slots per group
vent_spacing    = 3.0;     // gap between slots
disc_clearance  = 30.0;    // keep central 30 mm clear for the magnet disc

// ---- Cable exit slot (bottom edge of back shell) ------------------------
cable_slot_x = 25.0;
cable_slot_y = 4.0;
cable_slot_z_from_bottom = wall_t + 4.0; // sit it just above the cavity floor

// ---- Brightness button plunger ------------------------------------------
plunger_d            = 3.5;
plunger_travel       = 1.5;
plunger_outer_proud  = 1.5;
// Plunger is on the TOP edge of the back shell, positioned above where the
// brightness button sits on the PCB top edge. From datasheet: brightness
// button is in the top-middle area, roughly X ≈ pcb_origin_x + 50 mm
plunger_pos_x        = pcb_origin_x + 50;
plunger_flexure_t    = 0.8;
plunger_flexure_w    = 4.0;
plunger_flexure_len  = 12.0;

// ---- Magnet disc zone (back face) ---------------------------------------
disc_diameter = 25.0;
disc_x = case_x / 2;
disc_y = case_y / 2;

// =========================================================================
// HELPER MODULES
// =========================================================================

module rounded_rect(x, y, r) {
    offset(r=r) offset(r=-r) square([x, y], center=false);
}

module rounded_box(x, y, z, r) {
    linear_extrude(height = z) rounded_rect(x, y, r);
}

// =========================================================================
// BACK SHELL
// =========================================================================
// Z=0 is the OUTSIDE BACK face. Cavity opens upward (positive Z).
// Top of back-shell rim (where front shell meets) is at Z = back_shell_z.
//
module back_shell() {
    difference() {
        // ---- Outer solid block ----
        rounded_box(case_x, case_y, back_shell_z, corner_r);

        // ---- Inner cavity ----
        // Floor is at Z = wall_t. Cavity height = back_shell_z - wall_t.
        translate([wall_t, wall_t, wall_t])
            rounded_box(
                case_x - 2*wall_t,
                case_y - 2*wall_t,
                back_shell_z - wall_t + 0.1,
                max(corner_r - wall_t, 0.5)
            );

        // ---- Cable exit oval slot (bottom edge — Y=0 wall) ----
        translate([(case_x - cable_slot_x)/2, -0.1, cable_slot_z_from_bottom])
            cube([cable_slot_x, wall_t + 0.2, cable_slot_y]);

        // ---- Vent slots on the back face (Z=0 wall) ----
        // Two groups: above and below the central disc clearance zone.
        // Upper group (centered above the disc zone)
        for (i = [0:vent_group_n-1]) {
            x_pos = (case_x - vent_slot_l) / 2;
            y_pos = case_y/2 + disc_clearance/2
                    + i * (vent_slot_w + vent_spacing);
            translate([x_pos, y_pos, -0.1])
                cube([vent_slot_l, vent_slot_w, wall_t + 0.2]);
        }
        // Lower group
        for (i = [0:vent_group_n-1]) {
            x_pos = (case_x - vent_slot_l) / 2;
            y_pos = case_y/2 - disc_clearance/2
                    - vent_slot_w
                    - i * (vent_slot_w + vent_spacing);
            translate([x_pos, y_pos, -0.1])
                cube([vent_slot_l, vent_slot_w, wall_t + 0.2]);
        }

        // ---- Plunger pass-through hole (top edge — Y=case_y wall) ----
        translate([plunger_pos_x, case_y - wall_t - 0.1,
                   back_shell_z - wall_t - plunger_d/2])
            rotate([-90, 0, 0])
                cylinder(h = wall_t + 0.2,
                         d = plunger_d + print_tol,
                         $fn=24);
    }

    // ---- PCB mount bosses (with heat-set insert pre-hole) ----
    for (x = [hole_x1, hole_x2], y = [hole_y1, hole_y2]) {
        translate([x, y, wall_t])
            boss();
    }

    // ---- Snap clip cantilever fingers on top rim ----
    // Long edges (top + bottom, Y=0 and Y=case_y)
    for (x = clip_positions_long) {
        // Bottom edge (Y=0) — shaft sits at the wall, hook projects inward (+Y)
        translate([x - clip_width/2, 0, back_shell_z])
            snap_clip_finger();
        // Top edge (Y=case_y) — shaft at the wall, hook projects inward (-Y absolute)
        translate([x + clip_width/2, case_y, back_shell_z])
            rotate([0, 0, 180])
                snap_clip_finger();
    }
    // Short edges (X=0 and X=case_x)
    for (y = clip_positions_short) {
        // Left edge (X=0) — rotate so shaft lies along Y axis, hook projects +X inward
        translate([0, y - clip_width/2, back_shell_z])
            rotate([0, 0, -90])
                snap_clip_finger();
        // Right edge (X=case_x)
        translate([case_x, y + clip_width/2, back_shell_z])
            rotate([0, 0, 90])
                snap_clip_finger();
    }
}

module boss() {
    difference() {
        cylinder(h = boss_h, d = boss_outer_d, $fn=24);
        translate([0, 0, -0.1])
            cylinder(h = boss_h + 0.2, d = boss_inner_d, $fn=24);
    }
}

// Snap clip cantilever finger.
// Cantilever shaft sits at origin extending in +X, +Y, +Z.
// Hook is at top of shaft, projecting in +Y (toward case interior).
// Callers handle wall orientation via translate + rotate.
module snap_clip_finger() {
    // Cantilever shaft
    cube([clip_width, clip_thickness, clip_height]);
    // Hook at top of shaft, projecting +Y from the +Y face of the shaft
    translate([0, clip_thickness, clip_height - clip_hook_height])
        cube([clip_width, clip_hook_proud, clip_hook_height]);
}

// =========================================================================
// FRONT SHELL
// =========================================================================
// Front shell sits at Z = back_shell_z when assembled. Outermost surface
// (the bezel face) is at Z = back_shell_z + 1.2 mm in assembly view.
//
// Front shell anatomy from Z=0 (interlock bottom) to Z=front_shell_z (bezel outer):
//   Z=0   .. 1.8  : interlock lip (sits inside back-shell cavity rim)
//   Z=1.8 .. 3.0  : bezel face (visible from outside)
//
module front_shell() {
    // Pre-compute interlock inset to avoid assignments inside boolean blocks
    interlock_inset = wall_t + print_tol;
    difference() {
        union() {
            // Outer bezel face (Z=1.8 .. 3.0)
            translate([0, 0, 1.8])
                rounded_box(case_x, case_y, 1.2, corner_r);
            // Interlock lip (Z=0 .. 1.8) — slightly smaller than bezel to nest inside back-shell rim
            translate([interlock_inset, interlock_inset, 0])
                rounded_box(
                    case_x - 2*interlock_inset,
                    case_y - 2*interlock_inset,
                    1.8,
                    max(corner_r - interlock_inset, 0.5)
                );
        }
        // Glass window cutout (through both layers)
        translate([
            (case_x - glass_cutout_x)/2,
            (case_y - glass_cutout_y)/2,
            -0.1
        ])
            cube([glass_cutout_x, glass_cutout_y, front_shell_z + 0.2]);

        // Snap clip catch slots in the interlock lip
        // Long edges
        for (x = clip_positions_long) {
            translate([x - clip_width/2 - print_tol/2, 0, 0])
                cube([clip_width + print_tol,
                      wall_t + print_tol + clip_hook_proud + 0.5,
                      clip_height + 0.5]);
            translate([x - clip_width/2 - print_tol/2,
                       case_y - wall_t - print_tol - clip_hook_proud - 0.5, 0])
                cube([clip_width + print_tol,
                      wall_t + print_tol + clip_hook_proud + 0.5,
                      clip_height + 0.5]);
        }
        for (y = clip_positions_short) {
            translate([0, y - clip_width/2 - print_tol/2, 0])
                cube([wall_t + print_tol + clip_hook_proud + 0.5,
                      clip_width + print_tol,
                      clip_height + 0.5]);
            translate([case_x - wall_t - print_tol - clip_hook_proud - 0.5,
                       y - clip_width/2 - print_tol/2, 0])
                cube([wall_t + print_tol + clip_hook_proud + 0.5,
                      clip_width + print_tol,
                      clip_height + 0.5]);
        }
    }
}

// =========================================================================
// PLUNGER (separate small part)
// =========================================================================
// A printed cylinder with a thin cantilever flexure arm. After the plunger
// shaft passes through the case top-wall hole, the flexure rests against
// the interior side of the top wall (acting as a return spring).
//
module plunger() {
    // Plunger shaft
    total_h = wall_t + plunger_outer_proud + plunger_travel + 2;
    cylinder(h = total_h, d = plunger_d, $fn=32);

    // Cantilever flexure arm (perpendicular to plunger axis)
    translate([0, 0, total_h - plunger_flexure_t])
        cube([plunger_flexure_w, plunger_flexure_len, plunger_flexure_t],
             center = false);

    // Stop collar (prevents plunger from being pushed too far in)
    translate([0, 0, wall_t + plunger_outer_proud])
        cylinder(h = 1, d = plunger_d + 2, $fn=32);
}

// =========================================================================
// ASSEMBLY VIEW (for visualization, not for printing)
// =========================================================================
module assembly_view() {
    back_shell();
    color("cyan", 0.6)
        translate([0, 0, back_shell_z])
            front_shell();
    color("orange", 0.8)
        translate([plunger_pos_x, case_y - wall_t + 0.5,
                   back_shell_z - wall_t - plunger_d/2])
            rotate([90, 0, 0])
                plunger();
}

// =========================================================================
// RENDER
// =========================================================================
if (part == 1) {
    back_shell();
} else if (part == 2) {
    front_shell();
} else if (part == 3) {
    plunger();
} else {
    assembly_view();
}

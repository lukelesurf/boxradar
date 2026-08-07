// =====================================================================
//  CYD ADS-B RADAR — 30° wedge console enclosure
//  Board: ESP32-2432S028R "Cheap Yellow Display", dual-USB variant
//  Landscape, SD end = LEFT, USB end = RIGHT (internal cable pocket),
//  cable exits low through the rear panel.
//
//  Parts:  part = "assembly"    exploded-ish preview with ghost board
//                 "body"        wedge body, as-installed orientation
//                 "body_print"  wedge body, bezel face down (print this)
//                 "panel"       rear panel (prints flat as-is)
//                 "fit_test"    bezel face + bosses only — print FIRST
//
//  Hardware: 4x M3x6 self-tap (board -> bezel bosses)
//            4x M3x8 self-tap (panel -> corner bosses)
// =====================================================================

part       = "panel";
show_board = true;          // ghost board in assembly view
$fn = 48;

/* ---------------- board — VERIFY tagged values with calipers ------- */
board_w    = 86.5;
board_h    = 50.0;
board_t    = 1.6;
hole_d     = 3.2;
hole_inset = 4.0;   // VERIFY: mounting hole centre inset from corners
glass_lift = 4.0;    // VERIFY: glass surface height above PCB top
disp_w     = 69.5;   // VERIFY: display module (metal frame) outline, lateral
disp_h     = 50.5;   // VERIFY: module outline, along slant
disp_du    = 0;      // VERIFY: module centre offset from board centre (+ = toward USB)
disp_dv    = 0;      // VERIFY: module centre offset along slant
view_du = -3;   // aperture offset within the module — display active area
                // sits left-of-centre (3mm dead border on the right side)
view_dv = 0;    // same idea vertically, if it ever needs it
view_w     = 60.0;   // bezel opening (active area is 57.6 x 43.2)
view_h     = 45.0;
sd_dv      = 0;      // VERIFY: microSD position along left edge
comp_back  = 12;     // clearance behind PCB (ESP32 can, connectors)

/* ---------------- enclosure ---------------- */
tilt         = 30;    // back-tilt, degrees
wall         = 3.0;
lip          = 1.2;   // bezel overlap onto glass edge
glass_gap    = 0.3;   // air gap between lip underside and glass
clr          = 0.6;   // board fit clearance
usb_pocket   = 15;    // extra cavity width, USB side (plug + 90° bend)
D            = 55;    // overall depth front-toe to back
panel_t      = 2.5;
fit          = 0.25;  // panel fit clearance
boss_d       = 7;
pilot_d      = 2.6;   // M3 self-tap pilot
clear_d      = 3.4;   // M3 clearance
cable_slot_w = 10;
cable_slot_h = 12;
chin      = 10;   // foot height below the screen face
chin_rake = 15;   // chin leans back this many degrees.
                  // At tilt=30, rake >= 15 keeps the chin printable
                  // face-down (<= 45° overhang). Also looks less like a doorstop.

/* ---------------- derived ---------------- */
standoff_h = lip + glass_gap + glass_lift - wall;   // inner face -> PCB top
cav_slant  = board_h + 2*clr + 2;                   // cavity length along slant
int_w      = board_w + 2*clr + usb_pocket;          // cavity width
out_w      = int_w + 2*wall;                        // overall width
bcx        = wall + clr + board_w/2;                // board centre, global X
pcb_depth  = wall + standoff_h;                     // outer face -> PCB top
cable_x    = bcx + board_w/2 + 4 + cable_slot_w/2;  // rear slot centre
ldr_du = -(board_w/2 - hole_inset);        // same column as the left holes
ldr_dv = -(board_h/2 - hole_inset) + 7;    // ~9mm above hole centre — VERIFY
top_z = chin + cav_slant*cos(tilt) + 2*wall;
s_c   = (top_z - chin) / (2*cos(tilt));

assert(standoff_h >= 0.8,
  "standoff_h too small — thin the wall or check glass_lift");

/* ---------------- helpers ---------------- */
// extrude a 2D side profile (drawn as [depth, height]) along X
module extrude_x(l) { rotate([90,0,90]) linear_extrude(height=l) children(); }

// face frame: origin on OUTER bezel surface, +Z out of the face,
// fx = lateral (global X), fs = distance up the slant from the toe
module on_face(fx, fs) {
  translate([fx, fs*sin(tilt), chin + fs*cos(tilt)])
    rotate([90 - tilt, 0, 0]) children();
}
// same, relative to board centre
module on_board(u, v) { on_face(bcx + u, s_c + v) children(); }

/* ---------------- profiles ---------------- */
module prof_out() {
  polygon([[chin*tan(chin_rake), 0], [0, chin],
           [(top_z - chin)*tan(tilt), top_z], [D, top_z], [D, 0]]);
}
module prof_cav() {
  offset(delta = -wall)
    polygon([[chin*tan(chin_rake), 0], [0, chin],
             [(top_z - chin)*tan(tilt), top_z], [D + 20, top_z], [D + 20, 0]]);
}

/* ---------------- panel boss layout ---------------- */
pb = [[wall + 5,          wall + 5],
      [out_w - wall - 5,  wall + 5],
      [wall + 5,          top_z - wall - 5],
      [out_w - wall - 5,  top_z - wall - 5]];
pboss_len = 12;

/* ---------------- wedge body ---------------- */
module body() {
  difference() {
    union() {
      // shell = outline minus cavity, done FIRST so the bosses
      // added below survive (previously the cavity cut ate them)
      difference() {
        extrude_x(out_w) prof_out();
        translate([wall, 0, 0]) extrude_x(int_w) prof_cav();
      }
      // board standoff bosses on the inner bezel face
      for (sx = [-1,1], sy = [-1,1])
        on_board(sx*(board_w/2 - hole_inset), sy*(board_h/2 - hole_inset))
          translate([0,0, -wall - standoff_h])
            cylinder(h = standoff_h + 0.02, d = boss_d);
      // rear panel bosses — fattened so they fuse into the corner walls
      for (p = pb)
        translate([p[0], D - pboss_len, p[1]])
          rotate([-90,0,0]) cylinder(h = pboss_len, d = boss_d + 3);
    }

// view aperture
    on_board(disp_du + view_du, disp_dv + view_dv)
      cube([view_w, view_h, 4*wall], center = true);

    // display module pocket
    on_board(disp_du, disp_dv)
      translate([0,0, -lip - 7.5])
        cube([disp_w + 0.6, disp_h + 0.6, 15], center = true);

    // LDR light path + chamfer
    on_board(ldr_du, ldr_dv) {
      translate([0,0, -wall - 1]) cylinder(h = wall + 2, d = 3);
      translate([0,0, -1.2]) cylinder(h = 1.25, d1 = 3, d2 = 5.5);
    }

    // board screw pilots
    for (sx = [-1,1], sy = [-1,1])
      on_board(sx*(board_w/2 - hole_inset), sy*(board_h/2 - hole_inset))
        translate([0,0, -wall - standoff_h - 0.1])
          cylinder(h = standoff_h + wall - 1, d = pilot_d);

    // panel screw pilots
    for (p = pb)
      translate([p[0], D + 1, p[1]])
        rotate([90,0,0]) cylinder(h = pboss_len - 1, d = pilot_d);
  }
}

/* ---------------- rear panel ---------------- */
module panel() {
  px0 = wall + fit;  px1 = out_w - wall - fit;
  pz0 = wall + fit;  pz1 = top_z - wall - fit;
  difference() {
    translate([px0, D - panel_t, pz0])
      cube([px1 - px0, panel_t, pz1 - pz0]);
    // screw clearance
    for (p = pb)
      translate([p[0], D + 1, p[1]])
        rotate([90,0,0]) cylinder(h = panel_t + 2, d = clear_d);
    // cable exit notch, bottom edge, over the USB pocket
    translate([cable_x - cable_slot_w/2, D - panel_t - 1, pz0 - 0.1])
      cube([cable_slot_w, panel_t + 2, cable_slot_h]);
    // vents
    for (i = [0:5])
      translate([out_w/2 - 33 + i*12, D - panel_t - 1, top_z*0.55])
        cube([2.4, panel_t + 2, top_z*0.28]);
  }
}

/* ---------------- ghost board ---------------- */
module board_mock() {
  color("green", 0.4) on_board(0, 0)
    translate([0,0, -pcb_depth - board_t/2])
      cube([board_w, board_h, board_t], center = true);
  color("grey", 0.4) on_board(disp_du, disp_dv)
    translate([0,0, -pcb_depth + glass_lift/2])
      cube([disp_w, disp_h, glass_lift], center = true);
}

/* ---------------- part selection ---------------- */
if (part == "assembly") {
  body();
  color("orange", 0.7) panel();
  if (show_board) board_mock();
}
if (part == "body")       body();
if (part == "body_print") rotate([90 + tilt, 0, 0]) body();
if (part == "panel")      rotate([90, 0, 0]) translate([0, -D, 0]) panel();
if (part == "fit_test")
  rotate([90 + tilt, 0, 0]) intersection() {
    body();
    on_board(0, 0)
      translate([0,0, -(wall + standoff_h + 3)/2 + 0.5])
        cube([out_w*2, 200, wall + standoff_h + 4], center = true);
  }
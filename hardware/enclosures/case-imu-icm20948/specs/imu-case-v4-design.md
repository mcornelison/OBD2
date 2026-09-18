# IMU Enclosure (#3) — v4 Design: dash-top flared pebble

**Author:** Iris (UI/UX) · **Date:** 2026-09-16 · **Status:** DESIGN APPROVED (CIO, 3 sections) → spec review → build
**Supersedes the outer shell, fastening and lid of v3.2.** The board facts, board position and
interior clear space of v3.2 are unchanged and are the load-bearing constraint of this version.
v3.2 record: `imu-case-design.md` (left untouched). v3.2 source `imu-case.scad` is not modified;
v4 is a new file.

---

## 0. What changed and why (CIO brief, 2026-09-16)

| # | CIO ask | v4 answer |
|---|---|---|
| 1 | Replace board screws with simple posts + a small latch | Tapered-pin posts on a flat shoulder; latches moved to the corner lid posts (§3.2, CIO accepted) |
| 2 | Posts graduated thin→thick so the IMU seats perfectly | Taper **guides**, a flat shoulder **seats** at the v3.2 height (§3.1) |
| 3 | Corner posts for the lid; lid sockets replace screw holes | 4 corner posts + 4 lid bosses with press-fit sockets; no screws (§3.3, §4) |
| 4 | Ergonomic smooth shell that blends into the 1998 Eclipse dash | Flared pebble, CIO-tuned proportions (§2) |
| 5 | All walls the same thickness | 2.0 mm measured **normal to the surface** everywhere (§2.3) |
| 6 | Flat bottom, keep the cable hole | Flat, no recess (double-sided tape); cable exit identical to v3.2 (§2.4) |
| 7 | Interior must keep the same dimensions | v3.2 interior is a guaranteed **minimum** clear volume, asserted in code (§1) |
| — | Mounting tabs | **Removed** (tape mount) |
| — | Vents | Kept, restyled to follow the curve (§2.5) |

**Decisions the CIO made in the interview:** location = top of dash, centre · attach = double-sided
tape, no recess, tabs removed · lid hold = tight press-fit only (no crush ribs) · latch = pin +
edge hook · interior = v3.2 rectangle stays inside, shell may be roomier · filament = **PLA**
(re-confirmed after the P2S upgrade) · vents = keep, restyled · dash spot = flat across the full
~69 × 58 mm footprint · taper = guides, shoulder seats · shape = flared pebble · **no test coupon**
(small part; reprint if needed).

**Printer changed:** Bambu Lab **P2S** (enclosed, 0.4 mm nozzle, 256³ mm) replaces the MK3S+.
Slicer = Bambu Studio. The v3.2 PrusaSlicer profile and gcode stay as the v3.2 record only.

---

## 1. Fixed facts carried from v3.2 (must not move)

Frame: **+X = board long axis = car FORWARD**, +Y = left, +Z = up; Z=0 = outer bottom face.
v4 puts the origin at the **centre** of the interior in XY (v3.2 used a corner origin).

| Fact | Value |
|---|---|
| Board | 25.40 × 17.78 × 1.60 mm (ICM-20948 fab print, datasheet p.18) |
| Mount holes | 4 corners, c-c **20.32 × 12.70**, 2.54 from each edge → centres at (±10.16, ±6.35) |
| Hole Ø | **not in the datasheet** — parameter `hole_d`, default **2.5**, CIO to caliper |
| Board underside | **z = 8.0** (floor 2.0 + standoff 6.0) |
| Interior clear box | **35.40 × 27.78 mm**, z **2.0 → 15.6** (13.6 tall), centred on the board |
| Floor | 2.0 mm solid |
| Cable exit | obround **11 × 5 mm**, −Y wall, centred on X, centre z = **5.0** |
| Pin headers | a 0.1″ row along **both** long edges, between the corner holes |
| STEMMA QT | centred on **both** short edges |

**Interior guarantee (asserted):** at every z in [2.0, 15.6] the 35.40 × 27.78 rectangle lies
inside the inner wall with **≥ 0.5 mm** margin. That is the **shell** guarantee. Internal features
sit partly inside the rectangle's 5 mm clearance band, exactly as v3.2's own corner screw bosses
did: the corner lid posts overlap the rectangle's **corners** (they are centred in the extra oval
volume beyond it), and the latch blades run along the board's long edges. **Asserted:** nothing
enters the board's own footprint except the 0.4 mm latch lips and the tapered pins, and the
long-side clearance band stays clear between |x| < 11 (wire routing past the headers and to the
−Y cable exit).

---

## 2. Shell (Section 1)

### 2.1 CIO proportions (tuned live in the 3D mockup)

| Parameter | Value |
|---|---|
| `flare` — outward offset at the dash | **8.00 mm** |
| `dome_h` — lid rise above the split | **4.00 mm** |
| `n` — plan superellipse exponent | **2.4** |

### 2.2 Geometry

- **Plan** = superellipse `|x/A|^n + |y/B|^n = 1`. Inner at the split: A = (17.70 + 0.5)·2^(1/n),
  B = (13.89 + 0.5)·2^(1/n) → **A 24.29, B 19.21** (the rectangle corner + 0.5 lands exactly on it).
- **Base profile** (z 0 → 15.6): outer semi-axes = inner-at-split + 2.0 + f(z), with
  `f(z) = flare·(1−u)²`, `u = (z−0.8)/14.8`, and f constant below z = 0.8 (**0.8 mm vertical foot
  band**). f′ = 0 at the split, so the base wall is vertical where it meets the lid.
- **Split line** z = **15.6** (= v3.2 rim).
- **Lid dome** (outer) = **edge roll + crown**, total H = 4.0:
  - **roll** (quarter-ellipse): inset `3.4·(1−cos φ)` from the rim curve, rise `3.0·sin φ`,
    φ 0→90°. Starts vertical at the split (tangent-continuous with the base), ends horizontal.
  - **crown**: the ring left at the top of the roll is scaled by ρ 1→0 with rise
    `1.0·(1−ρ²)²` — zero slope where it meets the roll, apex at z = 19.6.
  - ⚠️ **Changed from the 3D mockup during planning (2026-09-16).** The mockup scaled the whole
    ring from the centre. Its tightest bend near the rim has a **~1.0 mm radius, smaller than the
    2.0 mm wall**, so a true 2 mm inner surface would fold through itself and the "same thickness
    everywhere" rule could not hold. The roll's tightest radius is **2.65 mm**, so it can. Same
    height, same footprint, visually near-identical (a soft rolled edge, nearly flat crowned top).

Expected (mockup maths, to be re-measured from the STL):

| | mm |
|---|---|
| Footprint on dash | **68.6 × 58.4** |
| At the split | 52.6 × 42.4 |
| Overall height | **19.6** |
| Flare angle at the foot | 47° from vertical |

The 47° flare is acceptable: the bottom 2 mm is solid floor and the foot band is vertical, so the
edge on the bed is ~2.9 mm of solid material, not a feather. (An earlier 40° "limit" was withdrawn.)

### 2.3 Uniform wall

- **2.0 mm normal to the surface.** Inner surface at height z is inset horizontally by
  `2.0·√(1+f′(z)²)`; the lid's inner dome uses the same rule on its own profile.
- Built as stacked superellipse rings joined into a `polyhedron` (base outer, base inner, lid outer,
  lid inner), not `minkowski` (too slow, and not normal-offset on a flare).
- **Asserted** by sampling ≥ 64 angles × ≥ 24 heights: normal thickness within 2.0 ± 0.05.

### 2.4 Bottom and cable exit

- **Flat, no recess**, full footprint on the bed; CIO mounts with double-sided tape.
- Cable exit: v3.2 obround 11 × 5 at z 5.0 on −Y, cut horizontally through the flared wall
  (tunnel is longer than 2 mm; that is expected).

### 2.5 Vents (restyled)

- **7 slots, same open area as v3.2** (1.3 × 4.5 mm obround each): 3 on the +Y flank at plan
  angles t = 70° / 90° / 110° (x ≈ +10 / 0 / −10), 2 on each end at t = ±9° and 180° ± 9°
  (y ≈ ±4). Centre z = **7.5**.
- Each slot is cut **horizontally along the local plan normal** of the curve at that point, so
  it follows the outline instead of being punched along a world axis.
- **Asserted:** no vent intersects a post, latch, or the cable exit.

### 2.6 Printing — base

Flat bottom on the bed, **no supports**. The wall's OUTER face leans inward and has no overhang;
the INNER face overhangs ~42–45° just above the floor, which still prints without support. Latch
undersides are 45°; the cable-exit top is an ~11 mm bridge (routine on the P2S).

---

## 3. Board posts, latches, lid posts (Section 2)

### 3.1 Board posts ×4 (at the hole centres)

| Part | Value |
|---|---|
| Post body | Ø **5.2**, from floor (fused 0.5 mm into it) to the **shoulder at z = 8.0** |
| Shoulder | flat, horizontal — **this is the seat datum**; all 4 identical |
| Tapered pin | base Ø **`hole_d − 0.2`** (2.3 default) at z 8.0 → tip Ø **1.2**, top at z **10.6** (1.0 above the board top) |

The taper centres the board as it drops; the board rests on the shoulders, so seat height does
not depend on the real hole diameter and the board cannot tilt.

### 3.2 Latches ×4 — on the corner lid posts (CIO-accepted change)

**Why not on the board posts:** a latch there must stand vertically and flex sideways, which puts
its bending stress **across** FDM layer lines — the weakest direction. PLA already failed this way
on this part (v1 lid snap rib, removed v2).

**Design:** a horizontal **blade** fused to the inboard side of each corner lid post, running in −X/+X
toward the board centre along the outside of the board's **long edge**, flexing in **Y** — stress
**along** the layers.

| Param | Default | Note |
|---|---|---|
| `latch_t` | **0.7** | blade thickness (Y) |
| `latch_len` | ≈ **5** | free length (post surface → wedge centre); derived from post position |
| `latch_gap` | **0.1** | blade inner face to board long edge |
| `latch_lip` | **0.4** | wedge overhang onto the board top |
| `latch_tip_x` | tip centred at \|x\| = **11.65**, 1.5 mm long (\|x\| 10.9–12.4) | lands on the corner mounting-hole copper ring |
| `latch_catch_clear` | **0.15** | lip underside 0.15 above the board top (z 8.0 + 1.6 + 0.15 = 9.75); prints on the next 0.2 mm layer; up to ~0.2 mm vertical play. Replaces a hardcoded 0.05, which was below one print layer and could leave the lip riding the board's edge with no downward hold. |
| underside | **45°** from the post root | self-supporting, no support material |
| wedge top | lead-in is **~34° from vertical** (steeper than the "45°" originally written) | prints fine; slightly higher push force to seat the board |

Peak PLA bending strain ≈ 1.5·t·δ/L² ≈ **2 %** — acceptable for a latch snapped a few times.

**Asserted clearances:** wedge lands at |x| ≥ 10.9 (clear of the header pins, which end at
|x| ≈ 7.6 plus pad) · no latch part lies in the STEMMA zone of the short edges · wedge top below
the lid (z ≤ 10.6 vs split 15.6).

**Release:** push the four blades outward (toothpick).

### 3.3 Corner lid posts ×4

- Ø **4.5**, centred in the extra oval volume just beyond each corner of the v3.2 rectangle
  (≈ (±18.5, ±10.4) — solved in code; the post overlaps the rectangle's corner, like v3.2's corner
  screw bosses), from the floor to z = **17.4** — i.e. **1.8 mm above the split**, rising into
  the lid.
- ⚠️ **Changed during planning (2026-09-16).** The approved text had the posts stop below the
  split and the lid's socket bosses **hang down** to z 11.8. Those bosses would sit **below the lid
  rim**, so the lid could not be printed rim-down — the only orientation that keeps the outside of
  the dome clean. The sockets now bore **up** into thickened lid corners instead.
- **Asserted:** each post is fully inside the inner wall at every z with ≥ 0.3 mm.

---

## 4. Lid (Section 3)

- Dome outer H = 4.0, inner H = 2.0 (2.0 mm wall normal to the surface).
- Meets the base **edge to edge** at z 15.6; outer surfaces tangent across the seam.
- **4 socket bosses** Ø 6.5 fill the lid cavity above each post, from the split plane up into
  the lid wall. They are **clipped to the lid's inner space grown 1.0 mm into the wall**, so they
  fuse with it and can never break through the outside.
- **Press-fit socket:** Ø **`lid_fit_d` = 4.5** (nominal = post Ø; the socket is line-on-line with
  the post — both Ø4.5), blind, top at split + **2.0** → **1.8 mm of engagement** (0.2 mm clearance
  above the post tip). **Asserted:** ≥ 0.8 mm of lid skin above every socket. CIO chose plain
  press-fit, no ribs. ⚠️ Engagement is shorter than the 3.4 mm first proposed (see §3.3).
  **Fit runs both directions, and TOO TIGHT is the more likely outcome:** FDM typically prints
  holes small and posts large, so a nominally line-on-line fit can land ~0.15–0.4 mm interference
  ×4 posts. **Do not force it** — socket skin is only ~0.82 mm at its thinnest (see §9). If tight:
  ream the 4 sockets with a 4.5–4.6 mm drill by hand, or reprint the lid with `lid_fit_d` 4.6–4.7.
  If loose: reprint with a smaller `lid_fit_d`. Next revision: a 0.3 mm chamfer on the post tops
  to ease first engagement.
- **FRONT arrow** (+X), debossed **0.6 mm** into the dome top.

### Printing — lid

Rim down on the plate. The inner ceiling is near-flat → **tree supports, inside only** (hidden
surface). Outer dome prints as top surface; use Bambu Studio **variable layer height** to soften
contour rings on the shallow dome.

---

## 5. Material and in-car notes

- **PLA** (CIO choice). ⚠️ Noted once: PLA softens at ~55–60 °C and a dark dash top in sun exceeds
  that; latches and press-fit may relax in summer. Reprint in PETG/ASA if it does — the design
  needs no change for that.
- **IMU re-baseline:** keep the FRONT arrow pointing forward (`forward:+x`). The first drive after
  the swap is the new IMU baseline; pitch fusion re-converges after ~5 stops. **Notify Spool.**

---

## 6. Deliverables

| File | Content |
|---|---|
| `imu-case-v4.scad` | parametric source. `part`: 0 assembly · 1 base · 2 lid (in place) · 3 cross-section · 4 lid print-orientation · 5 lid lifted · 6 base shell only · 7 lid shell only (6/7 are test oracles) |
| `tests/check_v4.py` | trimesh verification of §7 against the rendered STLs |
| `stl/v4-base.stl`, `stl/v4-lid-print.stl` | print targets (no in-place lid STL — that orientation is a known trap) |
| `slicer/v4-base.3mf`, `slicer/v4-lid.3mf` | Bambu Studio CLI slices for the P2S, PLA — **if** the CLI slices cleanly; otherwise STLs only, stated plainly |
| `renders/v4_{3q,side,section,lid-lifted}.png` | previews |

All v3.2 files untouched.

## 7. Verification (build fails, not warns)

1. Interior rectangle fits with ≥ 0.5 mm at every sampled z (§1).
2. Wall normal thickness 2.0 ± 0.05 at every sample (§2.3).
3. STL lowest Z = 0.000, and Z=0 vertices span the full footprint (flat base).
4. Shoulders at z 8.0 on the 20.32 × 12.70 pattern.
5. Posts inside the wall; bosses clear latches; latch wedges clear header pins and STEMMA zones.
6. Both STLs manifold (OpenSCAD `Simple: yes`).
7. Measured bounding boxes reported against §2.2 expectations.

## 8. Open (physical, after the first print)

- **`hole_d` caliper reading** (default 2.5).
- Latch click force / retention in PLA (`latch_t`, `latch_lip`).
- Lid press-fit tightness (`lid_fit_d`).
- Flat seating on the dash across the full footprint.

## 9. Build results (2026-09-17)

- Verification: `python tests/check_v4.py` → **0 failures** (full log `specs/v4-check-output.txt`).
- Base `stl/v4-base.stl` bounds: `[[-34.2941, -29.2083, 0.0], [34.2941, 29.2083, 17.4]]`.
- Lid `stl/v4-lid-print.stl` bounds: `[[-26.2941, -21.2083, -5.72205e-07], [26.2941, 21.2083, 3.98328]]`.
- Slices: ~~none — "the Bambu Studio CLI is a silent no-op on this PC"~~ **WRONG, corrected
  2026-09-17 (see "Slices" below).** The CLI works. The earlier failures came from how it was
  invoked from git-bash; a stray test slice made during review proved it could slice, and that stray
  predated the latch fix, so it was deleted.
- Renders: `renders/v4_3q.png`, `v4_side.png`, `v4_section.png`, `v4_lid-lifted.png`.
- **Accepted deviation:** `lid()` ends with an intersection against the half-space z ≥ split_z,
  trimming a 3.6 µm dip of the lid's inner rim ring below the split plane caused by a one-sided
  finite difference in `lid_n()` at u = 0. Below print resolution; no intended geometry removed
  (footprint, sockets, arrow verified). Follow-up if roll parameters ever change: replace the
  one-sided difference with an analytic/symmetric boundary tangent, because the clip would
  silently mask a larger error.
- **Measured:** base-shell wall 1.999–2.046 mm, lid wall 1.996–2.000 mm; seam rim areas
  295.9 = 295.9 mm²; socket skin min 0.88 mm (≥ 0.8); lid-socket engagement 1.8 mm as specified
  (no Step-4 adjustment was needed).
- **FRONT arrow points +X** (verified).
- Still open: `hole_d` caliper; latch click + retention; lid press-fit; dash seating.
- **Deferred minor items for the next revision:** code asserts for vent/post clearance (§2.5 says
  "asserted"; currently true by construction, ≥ 10.5 mm measured); the socket assert guards 0.1 mm
  not the 0.2 mm nominal clearance. (The lead-in angle wording was corrected in §3.2: ~34° from
  vertical; steeper than 45°, prints fine.)
- **Correction:** the socket-skin figure above is a **vertical-ray minimum of 0.88 mm**. The true
  minimum in any direction is **0.82 mm**, at the socket ceiling's outer edge (still ≥ the 0.8 mm
  spec floor).
- **Wall-sampling scope (documented, not a defect):** the base wall thickness check samples from
  z = 4.5 upward — below that, an inward ray from an outer vertex lands in the solid floor and
  measures floor thickness, not wall thickness (false fail). The lid rim band z 15.6–15.9 is not
  sampled either; it is closed analytically instead, because the inner rim ring there coincides
  with the base's own inner ring at the seam (verified equal areas, §9 seam measurement above).

### Final fix wave (2026-09-17)

- **Geometry:** `latch_catch_clear` raised **0.05 → 0.15 mm**, replacing the hardcoded lip-underside
  offset in `latch_one()` (`z_catch = board_z + board_t + latch_catch_clear`). Added a named
  parameter (with the other latch params) and a design-rule assert
  (`board_z + board_t + latch_catch_clear < board_z + board_t + latch_lead - 0.3`) so the lead-in
  above the catch stays meaningful. Reason: at 0.05 mm the lip underside sat below one 0.2 mm print
  layer and could print at or below the board top, riding the board's edge with no downward hold.
- Base re-rendered (`stl/v4-base.stl`, `Simple: yes`, ~42 s). Harness re-run:
  `python tests/check_v4.py` → **0 failure(s)**, all 4 groups (`base-shell`, `lid-shell`, `base`,
  `lid`), 55/55 PASS, exit 0 (full log `specs/v4-check-output.txt`).
- **Focused lip-underside probe** (appended to `specs/v4-check-output.txt`): for all 4 sign
  combinations of (x, y) at |x|=11.65, |y|=8.7 — point z=9.70 is **NOT inside** `stl/v4-base.stl`,
  point z=9.80 **IS inside** — confirming the lip underside moved to z 9.75
  (= board_z 8.0 + board_t 1.6 + latch_catch_clear 0.15), exactly as intended.
- **Section render re-shot from the correct side.** The prior `v4_section.png` looked at the uncut
  +Y exterior. Re-rendered `part=3` with `--camera=0,0,9,90,0,0,120 --render` (rotx=90 gives a
  level, face-on view down the Y axis rather than the 70°-elevated angle used before, which is what
  made the earlier attempt read as an intact exterior instead of a flat cut face; `--render` forces
  a full CGAL render instead of preview so cut surfaces render cleanly). The result clearly shows
  the wall/floor cross-section, both board posts with a tapered pin, both lid corner posts with
  their sockets, and the triangular latch blades between the posts.
- Stray 0-byte `slicer/v4-base.cli.log` deleted.

### Slices (2026-09-17, CIO-approved)

- Deleted two stray files in `case-imu-icm20948/`, `test4.3mf` and `result.json` (2026-09-16 23:59). They
  were a review-time test slice of the base from **before** the latch fix.
- **The CLI works when each argument is quoted and the program is launched natively from
  PowerShell (`Start-Process … -Wait`).** The git-bash invocation in plan Task 6 never produced a
  file, most likely because MSYS rewrote the `;`-joined `--load-settings` path list.
  Settings: `Bambu Lab P2S 0.4 nozzle` · `0.20mm Standard @BBL P2S` · `Bambu PLA Basic @BBL P2S`,
  plus `--slice 0 --arrange 1 --orient 0 --outputdir <dir> --export-3mf <name>`. Result `Success.`,
  return code 0, for both parts.
- `slicer/v4-base.3mf`: 87 layers, **~31 min**, 4.53 m filament (**≈13.5 g**). Arachne walls, no
  supports. Verified to be the latch-fixed base: volume 12848.0 mm³ equals the STL's, and the lip
  underside probe (9.70 clear / 9.80 solid, all 4 corners) passes on the 3mf mesh itself.
- `slicer/v4-lid.3mf`: 20 layers, **~11 min**, 1.35 m (**≈4 g**). Volume 3694.7 mm³ equals the STL's;
  rim on the bed (min z 0.0). **Sliced without supports**, on purpose.
- ⚠️ **Two known gaps in the CLI output. Fix them in the GUI before printing:**
  1. **Bed plate = Cool Plate, 35 °C** (the profile default). Select the plate actually installed
     (e.g. Textured PEI) so bed temperature and first-layer settings match.
  2. **Filament weight reads 0 g** because `filament_density` did not inherit from the base PLA
     profile. Temperatures did load (220 °C). The gram figures above are computed from length
     (1.75 mm PLA ≈ 2.98 g/m).
- **Lid in the GUI:** enable **tree supports**, **paint support blockers on the 4 sockets**, turn on
  a **brim**, apply **variable layer height**, then re-slice.

### Before you print (owner checklist)

1. Caliper one mounting hole; the pin base is Ø2.3, so a hole under ~2.3 mm (e.g. M2) stops the
   board seating — set `hole_d` and re-render the base.
2. Base in Bambu Studio: no supports; Arachne wall generator (the 0.7 mm latch blades are thinner
   than two 0.42 mm lines).
3. Lid in Bambu Studio: rim down, tree supports inside only, SUPPORT BLOCKERS painted on the 4
   sockets (a 4.5 mm bridge needs none; support left in a socket stops the lid seating), brim on,
   variable layer height for the dome.
4. Board install: press evenly near the board corners; ~25 N total to snap past all 4 latches.
   Removal: press both blades on one long side outward at the lead-in with a toothpick and tilt
   the board out.
5. Acceptance: all 4 latches click and the seated board does not rattle when the base is shaken.
   If it rattles, lower `latch_catch_clear` (e.g. 0.10) and reprint the base.
6. Lid: see §4 — tight is likelier than loose; don't force.
7. 🔴 **MATERIAL — TWO-STAGE, CIO 2026-09-17: print THIS revision in PLA as a FIT-TEST, then
   reprint the keeper in PETG.** The current slices (`slicer/v4-base.3mf`, `slicer/v4-lid.3mf`,
   `Bambu PLA Basic @BBL P2S`) are the **fit-test** slices. **Do not treat a successful PLA print
   as the finished case.**
   **Why the keeper is not PLA:** PLA softens ~55–60 °C and a dash in direct sun clears that. This
   part is **tape-mounted on the dash top** and retained by four **0.7 mm flexing latch blades**
   plus a **press-fit lid** — every creep-sensitive feature at once. 🔴 **And the failure is
   SILENT: this case IS the IMU's mount.** The mount is currently good at **1.07° true tilt
   (secured 2026-08-28; standing instruction — do NOT re-level, do NOT apply a manual pitch
   offset)**, and Spool is actively tracing a ~3.8° `pitchDeg` error to **gyro bias, explicitly
   not to the mounting**. A case that creeps in July changes the orientation calibration with no
   error, no log line and no symptom — it would present as a new sensor fault. PETG/ASA need **no
   design change**, only a filament profile and a re-slice.
   ⚠️ **What the PLA fit-test does and does not prove.** *Transfers to PETG:* `hole_d` / board
   seating, FRONT-arrow orientation, dash fit, whether the latches engage at all, and the
   support/blocker strategy. *Does NOT transfer:* **the press-fits themselves.** PETG shrinks
   differently and is markedly more elastic, and both critical fits here are already tight — the
   lid is "likelier TOO TIGHT than loose" (§4) and `latch_catch_clear` is **0.15 mm ≈ one 0.2 mm
   layer**. **Budget one dimensional tune on the keeper print, not zero**; re-run the item-5
   rattle acceptance in PETG rather than carrying the PLA result forward.
8. Keep the FRONT arrow pointing forward; first drive after the swap is the new IMU baseline
   (Spool notified).
9. Unverified: if the Adafruit board has rounded corners (~r 1.3), the lip overlap holds fully
   only over x ≈ 10.9–11.4, not the full 1.5 mm.

**Next-revision items:** post-top chamfer; vent/post clearance asserts; socket assert to 0.2;
`lid_n` symmetric boundary tangent (removes the z ≥ split clip); board-clear grid to y 8.89.

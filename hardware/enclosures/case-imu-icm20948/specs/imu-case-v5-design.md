# IMU Enclosure #3 — v5 design (lower profile + snap-post board retention)

Iris (UI/UX), 2026-09-17. Supersedes v4 (2026-09-16), which is **unchanged on disk**
(`imu-case-v4.scad`, `stl/v4-*.stl`, `slicer/v4-*.3mf`) exactly as v4 left v3.2 alone.

Source `imu-case-v5.scad` · checks `tests/verify_v5_deltas.py` · slice `slicer/slice-v5.ps1`.

---

## 0. Why v5 exists

The CIO printed v4 and fit-tested it. **It looked great**; four changes came back:

| # | CIO ask | Disposition |
|---|---|---|
| 1 | Rotate the lid arrow 90° | Done — arrow now points **−Y = the nose**. Cosmetic; CIO confirmed no axis remap. |
| 2 | Mounting pillars 3 mm taller | **NOT done, deliberately — the need dissolved.** See §1. |
| 3 | Lower overall profile, lid shape unchanged | Done — **19.6 → 16.0 mm**, lid provably identical. See §2. |
| 4 | Barb/hook on the *internal* posts so the board clicks in and can be released | Done — four split snap posts; v4's corner latch blades **retired**. See §3. |
| 5 | *(added 2026-09-18)* Rotate the board 90°, so rotate the posts | Done — hole pattern swapped to 12.70 × 20.32 c-c. See §3b. |

---

## 1. The +3 mm that wasn't needed

The CIO asked for 3 mm taller pillars and, in the same breath, for a lower overall case.
Those cancel: +3 mm of post and −3 mm of shell leaves **zero** clearance above the board.

Asking *why* dissolved it. The 3 mm was wanted **for snap-finger length** — and the
finger gets its length from slotting **down into the post body**, not from raising the
board. At the original height that is 0.83 % strain; the board never needed to move up.

⇒ **`board_z` went DOWN, 8.0 → 6.0**, which is what made the lower profile affordable.
The CIO's separate requirement — *18 AWG wires must run under the board and out the
port* — sets the floor: 6.0 mm of under-board space was "tons of room"; **4.0 mm still
clears a ~2.5 mm conductor with 1.5 mm spare.**

⚠️ **The cable port moved with the board.** `cable_z` 5.0 → **4.5**, so the port spans
z 2.0–7.0 against the new z 2.0–6.0 channel. Left at 5.0 the wires would have had to
climb to reach an exit that no longer lined up with the space they run in.

## 2. Lower profile — and why the lid is provably untouched

`split_z` **15.6 → 12.0**; `dome_h` unchanged at 4.0 ⇒ **total 19.6 → 16.0 mm**.

**The lid is unchanged BY CONSTRUCTION, not by care.** `flare_at(z)` is normalised to
`split_z` — `u = (z − foot_h)/(split_z − foot_h)`, value `flare·(1−u)²` — so it is
**exactly 0 at the seam** for any height, and `out_d(split_z) == wall` always. The seam
outline is therefore independent of `split_z`. Lowering the base compresses the flare
and steepens the sides; the seam and the footprint do not move.

*(I initially told the CIO this would need an explicit flare-compensation term. That was
wrong, and wrong in the cheap direction — the parameterisation already did it. Recorded
because the instinct to add a correction to something already self-correcting is how
parameters get double-applied.)*

Proven, not asserted — `tests/verify_v5_deltas.py` §2 compares the v5 lid against the
**v4 STL on disk**: x and y bounds **bit-identical** to 1 µm; z-max differs by **3.7 µm**
(1/54th of a 0.2 mm layer), which is the documented v4 rim artefact — `lid_n()`'s
one-sided finite difference at u = 0, trimmed by the `z ≥ split_z` clip — landing
fractionally differently at a new height. Volume differs **0.019 %**, the rotated arrow.

**Look tradeoff, stated to the CIO and accepted:** shorter base + same flare magnitude =
**steeper sides**. At 16 mm it reads as a squatter pebble.

## 3. Board retention — four split snap posts

v4's corner-post latch blades are **retired**; the corner posts are now purely lid
sockets and nothing reaches over the board's long edge (verified, §5 of the harness).

**The seat and the spring are separate bodies, and that is the whole design.**

| Body | Geometry | Job |
|---|---|---|
| Seat collar | Ø5.6 OD / Ø3.5 ID, z 1.5 → 6.0 | board rests on its top annulus |
| Spring stem | Ø2.3, split by a 0.8 mm slot along X, z 2.0 → 7.75, 0.6 mm root fillet | two fingers flexing in ±Y |
| Barb | Ø2.9 catch face at z 7.75, 1.6 mm lead-in ramp above | 0.20 mm hold per side over the Ø2.5 hole |

**Why not just slot the existing post:** a Ø5.2 post with a slot gives two **2.6 mm-thick**
half-posts — far too stiff to flex. A barb straight on v4's 2.6 mm pin stub is
**≈7.7 % strain** and snaps. That is the v1 snap-rib failure, quantified. Separating the
collar from the stem lets the spring stay thin over its whole length from the floor up.

Strain, by the rule's own formula `ε ≈ 1.5·t·δ/L²` with t ≈ 0.75, δ = 0.20, L = 5.75:
**0.68 %** — inside the 2 % few-cycle budget with ~3× margin.

### 🔴 The Rule-1 caveat — read this before printing in PLA

`knowledge/pattern-fdm-snap-latch-layer-rules.md` Rule 1: *a flexing latch must bend
ALONG the print layers, never across.* **These fingers break that rule.** They are
vertical arms flexing sideways, so the tensile stress runs up the arm, **across the layer
bonds** — the weak direction, and precisely the v1 failure mode.

It is unavoidable here: the CIO wants the barb on the board post, and the base must print
flat-bottom-down for adhesion (the whole enclosure-2/3 bed-adhesion saga). The post axis
is therefore Z, and nothing reorients it.

**What makes it acceptable rather than reckless:**
- strain is **0.68 %**, roughly a tenth of the failing case, giving ~24 MPa against PLA's
  ~30 MPa *interlayer* strength — a real margin, but **~1.25×, not 3×**;
- a **0.6 mm root fillet** at the highest-stress point, where a layer crack would start;
- **PETG is the keeper material** and has far better interlayer adhesion. This design is
  comfortable in PETG and marginal in PLA.

⚠️ **Consequence for the fit-test: a snapped finger on the PLA print is EXPECTED DATA,
not a design verdict.** Do not conclude the mechanism failed. Insert and remove the board
as few times as possible in PLA; judge retention on the PETG print.

**If it is too stiff or too loose:** `barb_d` is the one number. 2.9 gives 0.20 mm hold
per side; 2.8 halves it, 3.0 increases it. Strain scales linearly with the overhang.

## 3b. Posts rotated 90° (CIO 2026-09-18)

The CIO asked whether the board is square — i.e. whether rotating it needs the posts
moved. **It is not, and neither is the hole pattern:**

| | X | Y | Δ |
|---|---|---|---|
| Board | 25.40 mm (1.000″) | 17.78 mm (0.700″) | **7.62 mm** |
| Hole centres | 20.32 mm (0.800″) | 12.70 mm (0.500″) | **7.62 mm** |

⇒ `hole_cx`/`hole_cy` swapped to **6.35 / 10.16** (c-c **12.70 × 20.32**). Each post moves
**5.39 mm**. The board is a 1.000″ × 0.700″ Adafruit outline, so this was never going to
be a no-op.

**The lid did not change and was not re-rendered** — verified first: the `lid()` module
makes **zero** references to `hole_cx`, `hole_cy` or the post modules. `stl/v5-lid-print.stl`
from the pre-rotation build remains valid.

### What the rotation costs, and what it buys

**Clearance stops being symmetric — ✅ ACCEPTED BY THE CIO, 2026-09-18:** *"It is
acceptable that the 5 mm border has changed. That is totally fine and acceptable."* The
v3.2 interior was sized to give 5.00 mm all round; that symmetry is now deliberately
spent, not a defect to design back out. Rotated:

| | X per side | Y per side |
|---|---|---|
| Before | +5.00 | +5.00 |
| After | **+8.81** | **+1.19** |

⚠️ **The short-side wire gap is 0.93 mm** (collar outer edge y 12.96 against the interior
half-size 13.89) — **it will not take a 2.5 mm conductor.** *The 18 AWG wires must route
along the LONG sides.* This is now measured and reported by the harness rather than left
for someone to discover with a wire in hand.

⚠️ The Ø5.6 seat collar sits **0.26 mm proud of the board's short edge** (the rotated hole
is only 2.54 mm in from it). Not a collision — the collar is under the board — but the
board is supported at its lip on that axis. A smaller collar on those posts is the fix if
it matters; deliberately **not** done, because narrowing it also narrows the seat.

✅ Checked and clear: lid posts at 12.15 mm centres (needs 4.85); collar inside the shell
wall and inside the v3.2 interior rectangle.

**Four new asserts** guard all of this. They were a *deferred* item on v4 ("true by
construction") — and rotating the posts is precisely the change that could have broken
them quietly, which is the argument for promoting an assumption to an assert before you
disturb it, not after.

### The axis consequence — stated, not decided
The board's long axis, and therefore the IMU's own **+X**, now runs **fore/aft**, so the
sensor frame lines up with the car. That is what v4's header comment wrongly asserted was
already true. **This is a change to the part, not to the firmware**, and the CIO had
already ruled the downstream axis question closed; recorded here so the alignment is a
known fact rather than an accident.

### Wire exit — downgraded from blocker to assembly check (re-assessed 2026-09-18)
The cable port is at −Y and the rotation swings the board's connector edge 90°, so I
first raised this as a blocking question. **On the numbers it is not one**, and saying so
is more useful than leaving a caution standing:

- the wire is flexible, and it has **two** routes to the port — **over the board** (4.4 mm
  of `comp_clear`) or **along a long side** (8.81 mm). Either clears a 2.5 mm conductor
  comfortably, whichever edge the connector sits on;
- only the **short-side** route is closed (0.93 mm), and nothing forces the wire down it.

⇒ **Check it at assembly, not before printing.** The one case that would still bite is a
tall *rigid* plug body needing room on the short axis — which is the same unmeasured
quantity as `comp_clear` (§6.2), so one caliper reading answers both.

## 4. Arrow

`arrow_rot = -90` swings the FRONT arrow from +X to **−Y**. Confirmed against the render
by the CIO: the arrow points at the nose, **and the cable exits the same side**, so the
wire runs forward. One parameter if the handedness ever needs flipping (+90).

### Frame comment corrected
v4's header read `+X = board long axis = car FORWARD`. **That was wrong about the car.**
The case is mounted with the **long axis across the vehicle**, driver↔passenger; forward
is the short axis. v5's header states the real frame. ⚠️ **The CIO has ruled the
downstream axis question closed** — no note was filed to Spool or Atlas, and nothing in
the firmware was changed. Recorded here only so the next reader of this file is not
misled by a comment, as I was.

## 5. Build results (2026-09-17)

- `stl/v5-base.stl` — **`Simple: yes`** (manifold), 13,605 facets, z 0 → 13.8 (the lid
  posts; the shell seam is at 12.0 with the post columns excluded).
- `stl/v5-lid-print.stl` — **`Simple: yes`**, 6,758 facets, rim on the bed, z 0 → 3.987.
- `python tests/verify_v5_deltas.py` → **0 failures, 21 checks.**
- Renders `renders/v5_topdown.png`, `renders/v5_3q.png`.
- All design-rule asserts pass, including the **v3.2 interior guarantee** at the steeper
  wall angle, which was the risk in lowering `split_z`.

### Three harness bugs found and fixed (none were geometry faults)
Worth recording, because each one first looked like a broken part:
1. Asserted the base top was the seam. It is the **lid posts** (`split_z + 1.8`), exactly
   as in v4 (17.4 = 15.6 + 1.8). The seam is now measured with the post columns excluded.
2. Lid z-max tolerance of 1 µm flagged the **documented** 3.7 µm rim artefact. Widened to
   10 µm **with the reason named**; x/y stay at 1 µm, where they match exactly.
3. 🔴 **The probe lied.** Axis-aligned point-in-solid probes reported material at +Y and
   air at −Y on geometry that is symmetric by construction. OpenSCAD puts a `$fn=48`
   facet vertex exactly on the axes, so the ray fired down a facet boundary and the
   crossing count went degenerate. **The instrument was wrong, not the part** — this
   project's *"ask the instrument a question it can answer"* lesson in miniature. The
   harness now probes at 53/127/233/307° and requires agreement across all four.

### Slicing — NOT DONE, and the CLI is the reason
`slicer/slice-v5.ps1` is written, profile paths verified, and it is the reusable script
v4 never left behind (v4's invocation survived only as prose, so v5 had to rediscover
it). **It does not currently produce a file on this machine:** `--load-settings` with the
machine+process chain exits **−3** with no output, and slicing with no profile arguments
**segfaults** (`0xC0000005`). Three attempts, then stopped rather than grinding.

⚠️ **This costs less than it appears.** The CLI could never emit a print-ready file
anyway: the bed plate, the lid's tree supports, the socket blockers and the brim are all
GUI-only. Bambu Studio had to be opened regardless.

✅ **3MF files exist — but they are MODEL 3MFs, not sliced projects** (CIO asked for 3mf,
2026-09-18). `slicer/v5-base.3mf` and `slicer/v5-lid.3mf`, written by
`tests/stl_to_3mf.py`: correct millimetre units, open straight into Bambu Studio as
objects on the plate. 🔴 **They carry no profile, no supports, no layer count and no print
time.** v4's `slicer/v4-*.3mf` ARE sliced projects — **these are a different kind of file
with the same extension and must not be read as equivalent.** Vertex counts round-trip
exactly against OpenSCAD's own report (10,078 base / 4,408 lid).

## 6. Before you print

1. ✅ **RESOLVED 2026-09-18 — `hole_d` stays 2.5.** The CIO has **no calipers** and
   reports every past design fitted. True, but it does not transfer cleanly: **v4's pin
   was a TAPER**, which self-centres and hides an undersized hole. v5's stem is
   **straight**, because it must be a spring, so it is unforgiving — too fat and the
   board does not go on at all. Margin bought elsewhere instead: **`stem_d` is now
   `hole_d − 0.3` = 2.20** (was 2.30), doubling the slop to 0.15 mm per side. A thinner
   stem also *improves* barb grip if the holes are undersized. Strain drops to **0.64 %**.
2. ✅ **RESOLVED 2026-09-18 — `comp_clear` 4.4 mm stands; the CIO reports the tallest
   top-side component is 3–4 mm.** Measured off the lid mesh rather than assumed:
   **4.40 mm clear at the board edge, 6.14 mm over the centre** (the dome adds 1.74 mm).
   Worst case — a full 4 mm part sitting at the board's edge — still clears by 0.40 mm;
   anywhere near the middle it clears by 2.14 mm. **No geometry change, and the lower
   profile stands.**
3. Base: **no supports**, **Arachne** wall generator (the spring fingers are thinner than
   two 0.42 mm lines).
4. Lid: rim down, **tree supports inside only**, **blockers painted on the 4 sockets**,
   brim on, variable layer height for the dome.
5. Set the real **bed plate** — the profile default is Cool Plate 35 °C.
6. Board install: press evenly over the four posts until all four barbs click. Release by
   pinching each finger pair inward with a fingernail or toothpick and lifting.
7. 🔴 **PLA = fit-test only.** See §3 — judge the snap on PETG, and treat a broken PLA
   finger as expected.
8. Keep the arrow pointing at the nose. First drive after the swap is a new IMU baseline.

## 7. Open / next revision

- `hole_d` and `comp_clear` are both unmeasured (§6.1, §6.2).
- Slicer CLI unresolved — GUI for now.
- Full `check_v5.py` not yet adapted from `check_v4.py`; `verify_v5_deltas.py` covers only
  what v5 changed. The v4 harness's 55 invariants still apply and have not been re-run
  against v5 geometry.
- Rule 1 deserves an amendment for the case where the weak direction is unavoidable:
  acceptable at very low strain in a tough material, with the margin stated.

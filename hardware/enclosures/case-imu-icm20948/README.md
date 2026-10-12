# IMU case — Adafruit TDK InvenSense ICM-20948 9-DoF

Dash-top "flared pebble". Was `enclosure3/`.

**Current: v5** (`src/imu-case-v5.scad`) — **68.6 × 58.4 × 16.0 mm**, tape-mounted, flat
bottom. **v4 was printed by the CIO and fit-checked ("looked great"); v5 is v4 plus his four
changes and has NOT been printed yet.**

| Print this | |
|---|---|
| `stl/v5-base.stl` | no supports · **Arachne walls** |
| `stl/v5-lid-print.stl` | rim down · tree supports · **blockers on the 4 sockets** · brim |

Spec: [`specs/imu-case-v5-design.md`](specs/imu-case-v5-design.md). Verify:
`python tests/verify_v5_deltas.py` → **28 checks, 0 failures**.

## Versions kept here

| | Source | Geometry | Why kept |
|---|---|---|---|
| **v5** | `imu-case-v5.scad` | `v5-base`, `v5-lid-print` | current |
| **v4** | `imu-case-v4.scad` | `v4-base`, `v4-lid-print` | **the CIO printed it** |
| v3.2 | `imu-case.scad` | `box.stl`, `lid-print.stl` | prior printed design |

## v5 changes, from the v4 print

1. **Arrow → −Y (the nose).** Cosmetic; the CIO confirmed no axis remap.
2. **Lower profile, 19.6 → 16.0 mm.** The **lid is unchanged by construction** — `flare_at()`
   is normalised to `split_z` and is exactly 0 at the seam, so the seam outline is
   height-independent. Proven against the v4 STL: x/y bounds identical to 1 µm.
3. **Board sits LOWER, not higher.** The CIO asked for posts 3 mm *taller* — for snap-finger
   length. Slotting into the post body supplies that without raising anything, so `board_z`
   went 8.0 → **6.0**, gated by his real constraint: 18 AWG under the board (4.0 mm channel,
   1.5 mm spare). The cable port moved down with it.
4. **Four split snap posts; the v4 corner latch blades are retired.** Seat collar and spring
   stem are **separate bodies** — a slotted solid post gives 2.6 mm half-posts too stiff to
   flex. Board clicks on; release by pinching each finger pair inward.
5. **Posts rotated 90°** (2026-09-18). The board is **not square** — 25.40 × 17.78 mm on
   20.32 × 12.70 c-c — so rotating it forced the posts. Side effect: the IMU's **+X now runs
   fore/aft**, aligning the sensor frame with the car.

## 🔴 Read before printing

**The snap fingers flex ACROSS the print layers** — vertical arms bending sideways, which
loads the layer bonds rather than the extrusion lines. Unavoidable: the barb has to be on the
board post, and the base must print flat-bottom-down for adhesion.

Strain is **0.64 %**, about a tenth of the failing case (a barb on v4's 2.6 mm pin stub is
≈7.7 % and snaps — that is the v1 failure quantified). But against *interlayer* strength the
margin is **~1.25×, not 3×**.

⇒ **PETG is where this design is comfortable. PLA is a fit-test only, and a snapped finger on
a PLA print is expected data, not a verdict on the mechanism.** Insert and remove as little as
possible in PLA; judge retention on PETG. `barb_d` (2.9) is the single tuning number.

## Clearances (measured, not assumed)

| | |
|---|---|
| Under the board (18 AWG channel) | **4.0 mm** |
| Above the board, at the edge | **4.40 mm** |
| Above the board, over the centre | **6.14 mm** (the dome adds 1.74) |
| Interior, X per side | +8.81 mm |
| Interior, Y per side | **+1.19 mm** |

⚠️ After the post rotation the short-side gap between seat collar and wall is **0.93 mm** —
too narrow for a 2.5 mm conductor. **Route the wires along the LONG sides.** The asymmetry
was accepted by the CIO on 2026-09-18.

## Assumption still standing

`hole_d = 2.5 mm` is **not from the datasheet** and has never been measured — the CIO has no
calipers. v4's pin was a *taper*, which self-centres and hides an undersized hole; v5's stem
is *straight* because it must be a spring, so it is unforgiving. Margin was bought by
thinning the stem to `hole_d − 0.3` (2.20 mm) instead.

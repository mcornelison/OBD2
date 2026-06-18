---
name: pattern-tilted-feature-shear-in-vertical-walls
description: A board-parallel (tilted) groove cut into a VERTICAL wall gets sheared sideways by the tilt and can punch through the outer face; cut such features in world coords or clip them to the wall
metadata:
  type: pattern
---

Hit on the light-sensor case (enclosure #2 v5, 2026-06-17). The board is tilted 15°
inside a flat-bottomed box, so the diffuser sits in a tilted plane while the walls are
vertical (world Z). I cut the diffuser grooves "board-parallel" in board-local space.

**The bug:** for the LEFT/RIGHT walls the groove depth is along X — the 15° rotation
is about X, so X is unaffected and those grooves stayed blind/clean. But for the
**FRONT wall the groove depth is along Y — the same axis the tilt shears.** A
board-parallel slot at the diffuser height (~4 mm up) gets pushed *forward* by
`z·sin(tilt)` (~1 mm) and **broke through the outer face** of the short wall. The CIO
caught it on the STL: "the groove is on the outside, it needs to be interior."

**The rule:** when a part has a tilted internal plane but vertical exterior walls,
features on the walls perpendicular to the tilt axis (front/back) **cannot** be modeled
naively in the tilted frame — the shear moves them out of the wall.

**How to apply:**
- Cut features on the un-sheared walls (parallel to the tilt axis) in the tilted frame
  — fine.
- Cut features on the sheared walls (perpendicular to the tilt axis) in **world
  coordinates** at the computed height (use `sin`/`cos` of the tilt to find where the
  mating edge actually lands), OR clip the cut to the wall solid (intersect with a
  "leave-N-mm-skin" region) so the tilt can't push it through the outer face.
- General hygiene that also bit this session: avoid **coincident faces** in
  difference()/union() — a groove ring sharing the exact cavity-wall plane, or a
  standoff sitting coplanar on the floor, makes the result non-manifold. Shrink the
  inner cut ~0.1 mm to overlap the void, and sink posts ~0.5 mm into the floor.

Related: [[pattern-verify-feature-not-manifold-and-git-truth]],
[[pattern-hardware-measurement-frame-and-datasheet-authority]].

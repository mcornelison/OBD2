---
name: feedback-cio-measures-clearance-from-glass-edge
description: CIO measures enclosure clearances from the GLASS surface edge, not the PCB edge (2.3mm apart on the OSOYOO 3.5"). Confirm the datum before changing a gap.
metadata:
  type: feedback
---

# CIO measures clearances from the GLASS surface edge, not the PCB edge

On the display case (v2.6, 2026-06-03) the CIO ruler-measured the top clearance he
needs for the 90° micro-HDMI plug as **19 mm "from the top edge of the screen."**
"The screen" = the **glass surface edge**, which on the OSOYOO 3.5" sits **2.3 mm
outboard of the PCB edge** (glass cutout 60.6 mm overhangs the 56 mm PCB, centered).
So the same physical wall is 19 mm from his datum but 21.3 mm from the PCB edge.

**Why:** the CIO holds the assembled display and rests a ruler on the visible glass
panel — that's the edge he can actually see and touch. The PCB is hidden behind the
glass; he doesn't measure to it. My model, by contrast, naturally references the PCB
edge (where connectors mount). The two datums are always ~2.3 mm apart on this part.

**How to apply:**
- When the CIO gives an enclosure clearance, **default-assume the GLASS edge is his
  datum** unless he says otherwise.
- Before changing a `clearance_*` knob, confirm the datum (one `AskUserQuestion`
  with an arithmetic preview is cheap). A 2.3 mm error here is a whole wasted print.
- Translate explicitly in the model: glass-datum gap = `bezel_width (3.5) +
  clearance_top`; PCB-datum gap = `5.8 + clearance_top`. Put the datum in the
  comment so future-me doesn't re-confuse it.
- Err long (more connector room), never short.

See also: [[pattern-hardware-measurement-frame-and-datasheet-authority]] (Lesson 6 —
"the gap is wrong" = datum disagreement), [[reference-osoyoo-v3-display-dimensions]],
[[project-display-case-design-decisions]], [[feedback-cio-clarifying-questions-always-welcome]].

# Pattern: lock a shared frame + chase the datasheet, before geometry

**From:** display-case v2.1 session (2026-05-29). Several rounds were burned on
orientation confusion and ruler-vs-reality conflicts before the design closed.

## Lesson 1 — Agree the coordinate frame FIRST, anchored to a physical landmark

Edge-referenced measurements ("3 mm from the top", "6 mm from the left") are
**useless until "top/left" mean the same thing to both parties.** A CIO phone
photo can arrive rotated 90° from how the CIO is holding/measuring the part, so
my read of "the connectors are on the right" silently disagreed with his "on the
left," and I nearly put the asymmetric clearance on the wrong edges.

**Do this:** before accepting any edge-referenced numbers, pin the frame to an
**unambiguous silkscreen/landmark** both of us can see — e.g. "OSOYOO logo on
the right, '3.5 Inch LCD Display' text on the bottom, looking at the back."
Restate it back. Map that one frame to model axes in a comment block and never
re-derive it. Don't reason about left/right from connector positions in a
low-res photo — landmarks first.

## Lesson 2 — A real datasheet beats every ruler; ask for it early

Caliper/ruler reads are good; the manufacturer drawing is authority for raw
numbers. **Ask "is there a datasheet / model number?" at the start of any
hardware-fit task** instead of triangulating from photos and rulers.

(Cautionary note — see Lesson 5: having the datasheet is necessary but not
sufficient. I twice "corrected" the CIO's *correct* values from a wrong reading
of the datasheet's dimension SEMANTICS before getting it right.)

## Lesson 3 — Read a vectorized mechanical drawing by RENDERING a crop, not by parsing vectors

The page-1 dimensions were vectorized (no text layer), and `get_drawings()`
circle-detection drowned in component symbols. What worked: render the PDF
region at 6-11× with PyMuPDF and read the high-res PNG visually, then validate by
checking the dimension chains sum to the known overall (28.5+6.5+50 = 85 ✓).
(But summing-to-total only proves the chain is internally consistent — it does
NOT prove the chain measures what you think; see Lesson 5: that 28.5/6.5/50
chain dimensioned the CONNECTORS, not the mount holes.)

```python
import fitz
page = fitz.open("sheet.pdf")[0]
pix = page.get_pixmap(matrix=fitz.Matrix(6,6), clip=fitz.Rect(420,195,815,420))
pix.save("crop.png")   # then Read the PNG
```

## Lesson 4 — Render + show before the CIO prints

Asymmetric / mirror-able geometry makes an orientation error cost a whole print.
Always `openscad -o part.stl` (validates manifold: "Simple: yes") **and** render
a labeled image (orientation cue blocks for the key edges), then send it for a
visual sign-off before filament goes down. Cheap insurance.

## Lesson 5 — A datasheet number is useless until you know its SEMANTICS (edge? c-c? which feature?)

The hardest errors this session were NOT bad numbers — they were correct numbers
read with the wrong meaning. Twice I "corrected" the CIO's *right* values:

1. **Edge vs center-to-center.** The drawing's "49 mm" was the mount-hole vertical
   **center-to-center**, not the PCB edge. I read it as the edge and set the PCB
   short side to 49 — overriding the CIO's correct "56". (Truth: 3.5 + 49 + 3.5 = 56.)
2. **Which feature a dimension chain belongs to.** A "28.5 / 6.5 / 50" chain along
   the top edge dimensioned the *connectors*, and I read it as the top *hole row* —
   inventing a trapezoid when the holes are a clean rectangle (both rows share x).

**Why it matters:** a dimension that sums correctly and comes from the authoritative
datasheet still feels trustworthy while being applied to the wrong feature. The
CIO can SEE the physical part; when his lived measurement conflicts with my drawing
read, the conflict is usually MY interpretation, not his ruler.

**How to apply:**
- For every datasheet dimension, ask: edge length, or center-to-center, or
  feature-to-feature? Witness-line endpoints tell you — trace what each arrow
  actually touches (a hole center vs an edge vs a connector body).
- Before overriding a CIO-measured value, reconcile: if the datasheet "contradicts"
  him, first suspect you mis-read the semantics. Show him the specific witness lines.
- For hole patterns, confirm rectangle-vs-trapezoid by checking whether the two
  rows/columns share an axis (crop each column and compare), not by assuming the
  nearest dimension chain is the hole chain.

See also: `knowledge/pattern-openscad-cli-numeric-part-selector.md`,
`knowledge/feedback-cio-architectural-paths-belong-to-atlas.md`.

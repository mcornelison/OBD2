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

The whole short-axis math was broken by one ruler error (PCB "56 wide" vs the
datasheet's **49**). The instant the CIO supplied the official datasheet, every
conflict resolved and the "impossible" 50 mm-on-a-49 mm-board spacing revealed
the true **trapezoid** hole pattern. Caliper reads are good; the manufacturer
drawing is authority. **Ask "is there a datasheet / model number?" at the start
of any hardware-fit task** instead of triangulating from photos and rulers.

## Lesson 3 — Read a vectorized mechanical drawing by RENDERING a crop, not by parsing vectors

The page-1 dimensions were vectorized (no text layer), and `get_drawings()`
circle-detection drowned in component symbols. What worked: render the PDF
region at 6× with PyMuPDF and read the high-res PNG visually, then validate by
checking the dimension chains sum to the known overall (28.5+6.5+50 = 85 ✓).

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

See also: `knowledge/pattern-openscad-cli-numeric-part-selector.md`,
`knowledge/feedback-cio-architectural-paths-belong-to-atlas.md`.

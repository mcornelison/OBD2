# OSOYOO 3.5" HDMI Capacitive Touch (Model 2024009100) — Authoritative Facts

**Source of truth:** `2024009100_hdmi_datasheet.pdf` (this folder), supplied by CIO
2026-05-29 with the instruction "use this as your facts." Overrides all prior
ruler/caliper reads and any earlier datasheet-note approximations.

A second sheet, `3.5DSI_datasheet.pdf`, is a **different product** (DSI ribbon
variant, not HDMI) — kept for reference only; **not** our display.

---

## Display / front panel (glass)

| Fact | Value |
|------|-------|
| Glass outer (L × S × thick) | **93.44 × 60.00 × 7.00 mm** |
| Active display area | **73.44 × 48.96 mm** |
| Border, long sides | **10.00 mm** each |
| Border, short sides | **5.52 mm** each |
| Resolution | 480 × 320 |
| Viewing angle | 130° |

## PCB

| Fact | Value |
|------|-------|
| PCB outer (L × S) | **85.0 × 56.0 mm**  (CIO's "56 wide" was correct; the datasheet "49 mm" is the mount-hole vertical c-c, NOT the edge) |
| Thickness (est., not on sheet) | ~1.6 mm |
| Mounting thread | **M2.5** |
| Mount holes | **Ø3 mm**, 4×, **TRAPEZOID** pattern (below) |
| Standoffs (CIO's) | **M2.5 × 11 mm body + 3 mm male stud** |
| Type-C port | LEFT short edge: **6.4 mm from top, 9 mm long, 40.6 mm from bottom** (sums to 56 — confirms the 56 mm short edge) |

### Mount-hole pattern (TRAPEZOID — confirmed from the drawing's dimension chains)

Datasheet PCB frame: x measured from the LEFT edge along the 85 mm long axis;
y from the nearest long edge. Both dimension chains sum to 85 mm (validates scale).

| Hole | x from left | nearest-edge inset |
|------|-------------|--------------------|
| Top-left | **28.5 mm** | 3.5 mm from top long edge |
| Top-right | **78.5 mm** (top row c-c = **50 mm**) | 6.5 mm from right |
| Bottom-left | **23.6 mm** | 3.5 mm from bottom long edge |
| Bottom-right | **81.6 mm** (bottom row c-c = **58 mm**) | 3.4 mm from right |

**Vertical (short axis):** rows are **3.5 mm from the top edge and 3.5 mm from
the bottom edge**, vertical **c-c = 49 mm**. So PCB short edge = 3.5 + 49 + 3.5
= **56 mm** (the datasheet "49 mm" labels this c-c, not the edge — CIO confirmed).

CIO's calipers ("58 × 50", "3 from top", "3 from right") were correct — 58 and
50 are the two **horizontal row** spacings (bottom vs top), not long×short.
Overhang: short = 60 − 56 = ~4 mm, long = 93.44 − 85 = ~8.4 mm.

## Connectors (from datasheet page 2 photo + page 1 drawing)

| Connector | Edge |
|-----------|------|
| Micro-HDMI (display in) | TOP long edge |
| Brightness button | TOP long edge |
| Power switch | TOP long edge (left area) |
| **Type-C** (5 V power + touch) | **LEFT short edge** |
| FPC / touch ribbon | center, internal |

→ 90° cable-head clearance therefore belongs on the **top long edge (HDMI)**
and the **left short edge (Type-C)**.

## Electrical / environmental (reference)

- Power: 5 V; normal 200–230 mA, standby 70–90 mA, suspend 20 mA (switch off)
- Touch: 5-point capacitive, over Type-C
- Display port: standard Micro-HDMI
- Operating temp −20…+70 °C, storage −30…+80 °C
- Package 130 × 90 × 40 mm, weight 55 g

---

## Glass ↔ PCB registration (NOT fully specified by the sheet)

The sheet gives glass and PCB sizes but not their relative offset. The active
area is centered on the glass (symmetric borders). v1's window fit perfectly
with the PCB modeled centered, so the v2.1 model **centers the PCB behind the
glass** (`pcb_shift_x/y = 0`). CIO's gap reading (left 8 / right 2 mm) hinted at
a ~3 mm rightward shift; left as a one-line knob to bump if a fit-check shows
the screen off-window.

## Extraction tooling (this folder)

- `extract_holes.py` — dumps vector drawings (noisy; component symbols swamp the holes)
- `extract_text.py` — dimension text (page-1 dims are vectorized, no text layer)
- `crop_pcb.py` — renders the page-1 PCB drawing at 6× → `pcb_zoom.png` (this is
  how the trapezoid was read reliably)

Requires `pymupdf` (`pip install pymupdf`).

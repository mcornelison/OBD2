---
name: reference-osoyoo-v3-display-dimensions
description: OSOYOO 3.5" HDMI Capacitive Touch Screen v3.0 (Model 2024009100) — every dimension needed to enclose it. From the official datasheet.
metadata:
  type: reference
---

# OSOYOO 3.5" HDMI Capacitive Touch Screen v3.0

- **Model:** 2024009100
- **Datasheet:** https://osoyoo.com/picture/3.5hdmi_screen/2024009100/datasheet.pdf
- **Product page:** https://osoyoo.com/2024/11/25/osoyoo-3-5-inch-hdmi-capacitive-touch-screen-v3-0/
- **Source confirmed:** datasheet shared by CIO 2026-05-22

## Outer (touch-glass face)

| Dim | Value |
|---|---|
| Glass outer | **93.44 ± 0.3 mm × 60.00 ± 0.3 mm** |
| Active LCD | 73.44 × 48.96 mm (centered) |
| Margin, long side | 10.00 mm each side |
| Margin, short side | 5.52 mm each side |

## PCB

| Dim | Value |
|---|---|
| PCB outer | **85.0 ± 0.2 mm × 49.0 mm** |
| Glass overhang past PCB, long axis | (93.44 − 85.0) / 2 = 4.22 mm each side |
| Glass overhang past PCB, short axis | (60.0 − 49.0) / 2 = 5.5 mm each side |
| Total assembly Z (side profile) | 7.00 mm |

PCB sits recessed inside the glass envelope. Case front-face window cuts the GLASS outline (93.44 × 60), not the PCB outline.

## Mounting holes

- 4 holes, **Φ = 3 mm**, **M2.5 thread**, one near each PCB corner.
- Hole centers (from datasheet annotations):
  - 3.5 mm from short edge to hole outer-edge → center ≈ 5.0 mm from short edge
  - 3.4 mm from long edge to hole outer-edge → center ≈ 4.9 mm from long edge
- Inter-hole spacing along the long edge: **58 mm center-to-center** (23.6 + 58 + 3.4 = 85.0 ✓)
- Inter-hole spacing along the short edge: derivable from the 15.7/25.7/14.6 right-side stack — TODO verify with calipers when unit is in hand.

## Ports

| Port | Edge | Body height above PCB | Notes |
|---|---|---|---|
| **Micro-HDMI (Type D)** | TOP long edge (85 mm) | H = 4 mm | ~28.5 mm from one corner per datasheet annotation. Standard Micro-HDMI, plug-and-play, Pi 5 native. |
| **USB-C (Type-C)** | LEFT short edge (49 mm) | H = 3 mm | 5 V power + capacitive-touch data combined on a single USB cable. |
| Power slide switch | top-left area | H = 4 mm | "PWR" |
| Brightness button | top-middle | H ≈ 3 mm | Backlight dimming |
| 4-pin header | bottom edge | H = 2 mm | Probably touch/power test pads |

Key implication: **Micro-HDMI and USB-C are on PERPENDICULAR edges of the PCB.** Internal cable routing inside the case is asymmetric.

## Electrical / environmental

| | Value |
|---|---|
| Resolution | 480 × 320 (native, no scaling at this res) |
| Refresh rate | 60 Hz |
| Brightness | 300 cd/m², button-dimmable |
| Color gamut | 80% NTSC |
| Contrast | 500:1 |
| Viewing angle | 130° |
| Touch | 5-point capacitive |
| Power, normal (max brightness) | 5 V, 200–230 mA |
| Power, standby (no signal) | 5 V, 70–90 mA |
| Power, suspend (switch off) | 5 V, 20 mA |
| Operating temp | −20 to +70 °C — fits in-car |
| Storage temp | −30 to +80 °C |
| Weight (bare) | 55 g |
| Retail package | 130 × 90 × 40 mm |

## NOT this display (negative facts)

- **NOT Mini-HDMI (Type C).** "Mini" and "Micro" are different connectors. The Pi 5 also has Micro-HDMI, so a Micro-to-Micro cable is the matched solution.
- **Touch data shares the USB-C cable with power.** On the Pi 5 end, this terminates at a USB-A port (the only data-USB on Pi 5). So the cable is USB-C (display) → USB-A (Pi), unless touch is unused.
- **No I²C, no GPIO ribbon, no SPI.** This is the HDMI variant of the OSOYOO 3.5", entirely different from the GPIO/SPI sibling product.

## Case-design implications captured here for fast recall

- Front-face window cuts to GLASS outline 93.44 × 60, not PCB.
- 4 corner standoffs via Φ3 mm holes, M2.5 thread, ~3 mm tall to clear back-side components.
- Two ports on perpendicular edges → asymmetric internal routing to a unified bottom exit.
- Z assembly only 7 mm → thin front shell is feasible.
- Switch + brightness button are user-actuatable surfaces — if the case design wants these accessible, the back/side shell needs cutouts at those positions, otherwise they get sealed in.

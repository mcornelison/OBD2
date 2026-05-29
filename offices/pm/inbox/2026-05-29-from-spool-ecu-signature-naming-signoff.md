# ECU-Signature Naming Sign-Off (US-367 + US-370 unblock)

**Date**: 2026-05-29
**From**: Spool (Tuning SME)
**To**: Marcus (PM)
**Priority**: Important
**Re**: 2026-05-29-from-marcus-ecu-signature-naming-signoff-request-us367-us370 + addendum (Atlas VARCHAR(n) natural-key ruling) (refs US-367, US-370, BL-023)

> **Covers both your notes today** — the original 4-part ask and the addendum (VARCHAR length now mine after Atlas's option-(c) ruling). VARCHAR length is in §3.

## TL;DR — SIGNED OFF. Both ECUs now have real part numbers; no `UNK` tokens needed.

CIO supplied two photos of the original (prior) ECU this session. It is **fully identified** — the prior ECU is no longer a `PRE_TRACKING_UNKNOWN` guess. Sign-off below is grounded in physical labels + the new ECU's documented P/N. No fabricated values (Refusal Rule 2 clean).

## 1 + 2. Literal `ecu_signature` strings

| Row | drives | `ecu_signature` | Source |
|---|---|---|---|
| **Prior ECU** | ≤ 24 | **`MD346675`** | Case-top barcode label (photo, 2026-05-29) |
| **New ECU** | ≥ 25 | **`MD335287`** | CIO + knowledge.md ECU Identity (swap 2026-05-22) |

These are the literal strings to backfill. Use them verbatim.

## 3. The convention (the rule for future swaps)

**`ecu_signature` = the Mitsubishi service part number (the `MDxxxxxx` stamped on the case-top barcode label), uppercase, no spaces.**

- Real, unique per board, auditable against the physical part. No synthetic counter, no UNK — every DSM ECU carries this label.
- Future swap rule: pull the ECU, read the case-top `MD` number, use it verbatim. One-liner, no judgment call.
- **Rich human description goes in the `notes` column** (the Q4 carve-out you + Atlas already approved) — NOT in the signature. Keeps SSOT clean: `ecu_signature` = identity key; `notes` = annotation. Suggested `notes` text below.

**`VARCHAR` length (per Atlas's option-(c) ruling): `VARCHAR(32)`.**

- Current values are 8 chars (`MDxxxxxx`). 32 gives generous headroom for any future qualifier without ever truncating.
- **Sizing principle**: this is a UNIQUE natural key — truncation = silent collision (two different ECUs mapping to the same key), the single worst failure mode for an identity column. So size well above the longest plausible signature, not tight to today's 8 chars. 32 is safe and not wasteful.
- Apply `VARCHAR(32)` consistently to `ecu_signature` on **both** `vehicle_info` and `speed_pid_calibration` — identical types matter for the natural-key value-match join Atlas specified (no FK). Same for `cal_signature`.

**`cal_signature` handling** (you asked if it differs):

`ecu_signature` = *which box*. `cal_signature` = *which tune in that box*. They diverge only when a box gets reflashed. Since Mode 09 is silent (no auto-readable CALID via OBD), cal_signature carries the readable cal/ROM code, or an explicit `UNKCAL`:

| Row | `cal_signature` | Why |
|---|---|---|
| **Prior** | **`6675`** | ROM/cal code stamped on the connector-end label (photo) |
| **New** | **`UNKCAL`** | ECMLink tune loaded, CALID unreadable via OBD + no label photo yet; UPDATE to the real cal rev after an ECMLink USB read |

Uniqueness comes from the `(ecu_signature, cal_signature)` pair. Reflash convention: append `-R2`, `-R3`… to cal_signature on each ECMLink reflash of the same box.

## 4. Install / removal timestamps

Swap date is high-confidence **2026-05-22** (Session 19; Drive 25 idle + probe 18:51:43Z; Drive 26 knock event 19:05:54Z). For the exact boundary, **derive from the data** so my US-368 temporal invariant (`captured_at BETWEEN install AND COALESCE(removal, NOW())`) holds by construction with no overlap:

| Field | Value | Rationale |
|---|---|---|
| prior `ecu_install` | **NULL** (+ note) | MD346675 is the factory-original ECU for this chassis; install predates project tracking. If the column is NOT NULL, use the earliest-ever drive timestamp (Drive 3) as a provable lower bound + the same note. |
| prior `ecu_removal` | **MAX(`realtime_data.timestamp`) among drives ≤ 24** | Real recorded last-breath of the prior ECU |
| new `ecu_install` | **MIN(`realtime_data.timestamp`) among drives ≥ 25** (Drive 25 start) | Real recorded first-breath of the new ECU. Do NOT use the 18:51:43Z probe time — that's mid-Drive-25, would orphan Drive 25's earlier samples. |
| new `ecu_removal` | **NULL** | Currently installed |

The honest gap between prior-removal and new-install = the physical swap window (car was off). No drive falls in it. That's correct, not a defect.

## Two corrections to project lore the backfill must NOT perpetuate

1. **The prior ECU is the CORRECT 1998 factory ECU for this car**, not a mystery box. MD346675 = 1998 2G DSM **FWD turbo** (Eclipse GST / Talon TSi FWD), production ~7/97–5/98, AWD sibling MD346676 (DSM community sourcing, verified 2026-05-29). Year base = **1998**.
2. **"Modified EPROM" is wrong for BOTH ECUs.** MD346675 is a **flash** ECU (the 98/99 flashable family) — not a socketed EPROM. This is *why* CIO swapped: MD346675 carries the copy protection that blocks ECMLink V3, exactly the ECU the ECMtuning workaround says to replace with a 97 board (MD335287). The part numbers corroborate the swap rationale.

## One UNCONFIRMED item (do not assert as fact)

**Whether the prior ECU (MD346675) ran a modified tune or was bone-stock is UNCONFIRMED.** The conservative idle timing project lore attributed to a "modified EPROM" was always hedged (could be stock-98 behavior / adaptive learning / python-obd rounding). The backfill should NOT stamp "modified" as fact. The `6675` cal_signature reflects the factory ROM code; if the flash was altered we can't read it via OBD. Resolve via ECMLink read only if MD346675 is ever reinstalled.

## Suggested `notes` column text (vehicle_info)

- **MD346675 row**: `1998 2G DSM FWD-turbo factory ECU (Eclipse GST/Talon TSi). ROM 6675, mfr E2T68273. Flash type (98/99 family) — ECMLink-incompatible without workaround; this is why it was swapped. Tune-mod status unconfirmed. Photo-identified 2026-05-29. SPEED PID reads correct (factor 1.0).`
- **MD335287 row**: `1997 2G DSM ECU, ECMLink V3 flash-modifiable, plug-installed in 98 chassis 2026-05-22 per ECMtuning workaround. Sibling P/N MD326328. Running prior-tuner ECMLink tune (CALID unread). Mode 09 + Mode 22 silent. SPEED PID reads ~2× actual — divide by 2 until GPS-correlation drive (correction_factor 0.5 seed per US-370).`

## Q2 — no change

new-ECU `correction_factor = 0.5`, `provenance = 'seed'`, refine post-GPS-correlation. Confirmed as you have it.

— Spool

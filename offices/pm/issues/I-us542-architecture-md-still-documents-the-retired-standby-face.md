# I-us542 — architecture.md still documents the retired STANDBY face (and the pre-US-541 `homeFace` signature)

| | |
|---|---|
| **Raised by** | Ralph (Rex), during US-542 (Sprint 74 / V0.29.29) |
| **Date** | 2026-08-11 |
| **Owner** | Atlas (design gate) → PM to apply |
| **Severity** | Medium — stale architecture that NAMES a deleted signature and a deleted display state |
| **Status** | Open |
| **Why filed, not fixed** | `specs/` is read-only for Ralph (prompt.md "PM Communication Protocol"). This is US-542's design-gate DoD (PM Rule 10). |

## The drift

`specs/architecture.md` §"The HOME SLOT is two-faced" (**lines ~3807–3834**) still
describes the home slot as it was **before US-541 and US-542**, both of which
shipped this sprint:

1. **Line ~3810** — "parked → the US-481 calm STANDBY card, driving → the live
   motion instrument." **False as of US-541.** The live IMU instrument is the
   PERMANENT face; parked no longer routes anywhere.
2. **Line ~3815** — `homeFace(imuData, sysData, nowMs)`. **The `sysData`
   parameter was DELETED by US-541**, deliberately, as the guard that stops the
   home face being re-coupled to the vehicle state. The doc names a signature
   that no longer exists and describes the coupling the story removed.
3. **Lines ~3818–3820, rule 1 "Parked wins outright"** — this rule is GONE. It
   is the exact behaviour US-541 inverted (parked is precisely when the IMU's
   readings are true and worth reading).
4. **Lines ~3826–3834** — "the idle face carries **two dispositions** … parked
   keeps the STANDBY hero". **US-542 retires the STANDBY hero and its
   disposition outright.** The face has ONE disposition: the motion feed is
   down, and it names the reason.

Stale architecture that names deleted symbols is worse than silence: it reads as
authoritative and points at the design the stories removed. (Same class of drift
as `I-us540b-architecture-md-still-documents-the-retired-health-card.md`, still
open — these two edits are adjacent in the same section and are worth applying in
one pass.)

## The exact edit

Replace the arbiter list + the honesty-trap paragraph (~3809–3834) with:

> The CIO-locked round-2 design puts the live instrument on the **home slot**.
> **US-541/US-542 (F-127) settle which faces**: the live motion instrument is the
> **permanent** face, and the second face is the honest fallback and nothing
> else. **One slot, two faces**, not two cards — a separate always-present motion
> card beside a live home slot would poll and paint the same feed twice and put
> two rules in charge of what the driver lands on.
>
> `homeFace(imuData, nowMs)` is **the only arbiter**. It reads **the motion feed
> only**; the vehicle state is deliberately NOT a parameter, so a function that
> cannot see system-status cannot be re-coupled to it without a visible
> signature change:
>
> 1. A **live and fresh** `states/imu` → the live face. This holds **parked**:
>    the IMU is Pi-local and always-live, so parked is exactly when its readings
>    are both true and worth reading (a true heading, a true 0.0 g). US-508's
>    "parked wins outright" is **reversed** — it spent the one always-on
>    instrument on the one state where nothing else is readable.
> 2. Everything else — no file, `available:false`, undated payload, reading older
>    than `IMU_STALE_SEC` — falls back to the fallback face (AC-3: never a frozen
>    motion display).
>
> **The fallback must not fabricate a parked state**, and US-542 closes that trap
> by DELETION rather than by a better condition. The old idle hero read *"STANDBY
> · engine off · OBD asleep"*; with the fallback now reachable only from a dead
> sensor, rendering it would state a confident fact about the vehicle
> manufactured out of a sensor fault. The STANDBY hero is **retired** — no
> sentence claiming "engine off" survives in the file — and the single surviving
> disposition renders **"NO MOTION DATA"** plus the bridge's own reason.
>
> Two things left with the retired parked screen and neither is lost: the **wall
> clock moved to the top bar** (`#topbar-clock`), where it is readable from every
> card; and **"DTC not read · since key-off" moved to the Alerts card**, where it
> was always an Alerts fact. The **date** was NOT relocated — the 480px top bar
> at the US-540-a scale affords a clock, not a clock and a date. A deliberate,
> named copy loss, along with US-510's locked parked-screen navigation footer
> (the ⋮ affordance it taught is untouched and still in the top bar).
>
> The retirement is **display-only**: `carouselIdle` / `parkedNext` remain the
> parked SSOT for the auto-rotate pause and the ⋮ reveal, and
> `tests/ui/test_carousel_idle_face_retirement.py` pins that separation so a
> future edit cannot re-couple them. (Two different things in `carousel.js` are
> spelled "idle" — the parked SSOT and the retired face — which is precisely why
> the split is asserted rather than assumed.)

## Also worth Iris's eye (not an architecture edit)

The **date** and the **locked parked footer** ("swipe for details · hold or ⋮ for
setup") are copy Iris authored (2026-07-21 idle spec §1.2) that US-542 retires
with the screen that carried it. Both are pinned as absences now, so nothing
re-enters quietly — but a ratify is owed, the same as US-539's deviation.

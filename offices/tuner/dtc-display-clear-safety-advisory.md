# DTC Display + Clear-Code — Spool Safety Advisory

**Author**: Spool (Tuning SME)
**Date**: 2026-06-05
**Status**: Authoritative (CIO-ratified design fork 2026-06-05)
**Audience**: Iris (mockups), Atlas (architecture), Ralph (build), Marcus (PM tracking)
**Triggered by**: CIO check-engine light ON both legs of the (aborted) drive-27 run; new use case for the Pi display.

> SSOT for the engine-safety semantics of the on-screen DTC viewer + clear-code feature. Iris/Atlas/Ralph build against this; the severity tiers + clear-gate preconditions are mine and are non-negotiable on engine-protection grounds.

---

## 1. What we already have (don't rebuild)

| Piece | Where | Status |
|---|---|---|
| Mode 03 (stored) + Mode 07 (pending) retrieval | `src/pi/obdii/dtc_client.py` | built |
| MIL rising-edge → DTC re-fetch | `src/pi/obdii/mil_edge.py` | built |
| 30s during-drive Mode 03 cadence + drive-end Mode 07 | `src/pi/obdii/dtc_logger.py` | built |
| `dtc_log` capture table (code, description, status, drive_id, timestamps) | `src/pi/obdii/dtc_log_schema.py` | built |
| **Pi→server `dtc_log` mirror (sync)** | US-238, `src/server/...` | built — "report to server" is HALF DONE |
| `dtc_freeze_frame` server infra | US-368 | built (Pi-side Mode 02 capture support UNCONFIRMED on this ECU) |
| **Clear-DTC (Mode 04) path** | — | **DOES NOT EXIST.** Net-new. `cleared` status enum reserved, never wired. |

**Description gap (mandates the static table):** `dtc_client._asCode` pulls descriptions from python-obd's built-in `DTC_MAP`, which returns an **empty string for Mitsubishi P1xxx codes** — by design (never fabricate). The ECMLink ECU (drives ≥25) is exactly the setup that throws P1xxx. Without a static table, a DSM-specific code renders on screen as a bare `P1xxx` with no text.

### ⚠️ HARD REQUIREMENT — KOEO (key-on / engine-off) capture (CIO 2026-06-05)
The natural use case for a DTC viewer is *"pull up, key on, why is my light on?"* — **key-on, engine NOT running, no drive.** But every current capture path (`logSessionStartDtcs`, `maybePeriodicMode03`, `logDriveEndDtcs`) is gated behind an **active drive** — `DriveDetector._startDrive` only fires on **RPM > `driveStartRpmThreshold` for a sustained duration** (`src/pi/obdii/drive/detector.py`). KOEO = RPM 0 = no drive = **nothing captured**. So the viewer would show nothing until the car was actually driven, which is backwards for a diagnostic screen.

**Requirement:** the DTC viewer must have a **key-on capture path independent of DriveDetector** — a Mode 03 (+ Mode 02 freeze-frame) read that fires on connection/key-on with RPM 0, writing `dtc_log` rows with `drive_id = NULL` (the schema already permits NULL drive_id for exactly this "no drive context" case). This is a capture-architecture change for Atlas/Ralph, not just a display concern.

---

## 2. Static lookup DB — sizing verdict: NOT crazy big, go static

Bundle a static `code → short → long → severity → clear_eligible` table with the Pi image.

| Set | Count | Source |
|---|---|---|
| Generic SAE (P0/P2/P34xx + generic B/C/U) | ~2,000–3,000 | sourceable wholesale (standardized) |
| DSM-specific P1xxx (4G63-relevant) | ~30–50 | **Spool-curated from DSM sources (follow-up)** |

Full table lands **< ~2 MB JSON** — trivial for a Pi 5 (GB storage, GB+ RAM), loads fully into memory, **needs no network at display time** (works key-on-engine-off, works WiFi-down). The `severity` + `clear_eligible` columns are SME-owned (§3). short/long generic descriptions are sourced.

**Follow-up I own:** curate the DSM P1xxx subset with severity tags from authoritative DSM sources (factory service manual, ECMtuning wiki, DSMtuners consensus). I will NOT fabricate P1xxx meanings — empty until grounded.

---

## 3. Severity taxonomy — engine-protection first (turbo 4G63)

Three tiers. This drives BOTH the display color/messaging AND the clear-gate.

| Tier | Examples (generic; confident) | Display behavior | Clearable? |
|---|---|---|---|
| 🔴 **STOP** | Misfire **P0300–P0304**; knock/detonation-related; lean-at-load **P0171 under boost**; overheat-linked; oil-pressure; cam/crank correlation; **P0325 knock-sensor circuit** (loses the ECU's knock safety net) | "Reduce load / pull over." Prominent red. **No clear button at all.** | **Never** |
| 🟡 **WATCH** | Moderate fuel-trim; single O2/HO2S circuit (P0130–P0167); **P0401 EGR flow**; **P0420 cat efficiency**; intermittent sensor | Log, report, "drive gently, get it diagnosed." Amber. | No |
| 🟢 **MINOR** | Evap / gas cap (**P0440 / P0442 / P0455**); non-powertrain body/comfort | Log, report. "Likely <X>; safe to clear once logged." | **Yes — conditionally (§4)** |

**Turbo rule of thumb behind the 🔴 list:** a misfire *under boost* is detonation, and detonation on a 4G63 cracks ringlands and melts the #4 piston. A misfire code on a turbo motor is never "just a misfire." That's why P030x is hard-STOP, no clear, pull-over messaging.

---

## 4. Clear-code design — the OBD-II reality + the safety gate

### 4a. The correction everyone must internalize: Mode 04 is all-or-nothing
**There is no per-code clear in OBD-II.** Mode 04 wipes *every* stored code, *every* pending code, the **freeze-frame data**, AND resets **all emissions readiness monitors** in one shot. A "clear this minor code" button is really a "wipe the entire DTC memory" button.

**Consequence — clear is gated on the HIGHEST-severity stored code, not the one on screen.** If a 🟢 gas-cap and a 🔴 misfire are both set, clearing the gas cap also erases the misfire + its freeze frame. So:

> **Clear button is enabled ONLY when EVERY currently-stored code is 🟢 MINOR.** Any 🟡/🔴 present → disabled.

### 4b. CIO-ratified UX (2026-06-05): **Gated single-button**
One clear button. Enabled iff (all true):
1. Every stored code is 🟢 MINOR, **and**
2. Code(s) **+ freeze frame** captured to `dtc_log` / `dtc_freeze_frame`, **and**
3. **Server has ACKed the sync** (no ack → disabled).

Disabled the instant anything 🟡/🔴 is present. (Rejected alternatives: always-on-with-warning; post-drive-only.)

### 4c. Log-before-clear is a HARD precondition (CIO: "must log + report everything")
Never issue Mode 04 until §4b.2 + §4b.3 are satisfied. **Freeze frame is the crown jewel** — the sensor snapshot at the exact instant the code set (RPM, load, coolant, trims, timing). Clearing destroys it forever. Capture it *first*. We have the server infra (US-368); add the Pi-side capture + a **sync-ack gate**.

### 4d. Post-clear guards
- **Re-read (Mode 03) immediately after clear** — confirm it cleared, and catch an instant re-set.
- **Refuse a 2nd clear** of any code that re-set within the same session. A code that keeps coming back is a *hard fault*; repeatedly clearing it ("chasing the light") is how a real problem gets driven into a dead engine while the dash stays dark.
- **Readiness-monitor consequence:** clearing resets emissions monitors, which then need a full drive-cycle to re-run. If CIO ever needs an emissions/inspection pass, clearing right before = "not ready" fail. Surface this in the confirm copy.

---

## 5. DSM caveats — live-probe results (2026-06-05 KOEO read, MD326328)

**CONFIRMED via direct KOEO Mode 02/03/07 read 2026-06-05:**
- **Mode 02 (FREEZE_DTC) is UNSUPPORTED on this ECU** (returned null). The "freeze-frame-before-clear" gate (§4c) therefore has **no freeze frame to capture** — it falls back to **code + full `realtime_data` snapshot + server-sync ack**. This is now a confirmed design constraint, not a maybe.
- **Mode 07 (pending) returned empty** (not null) on this read — supported, just no pending codes.
- First real code read: **P0443** (EVAP purge control valve circuit) — 🟢 MINOR, python-obd HAS the description (renders without the static table). Good first display test case.

### Remaining caveats:
- 2G DSM is pre-full-OBD2. Mode 07 (pending) can be silent — already probed/cached.
- **Mode 02 freeze-frame support on this ECU is UNCONFIRMED.** Probe on the next session. If silent, the log-before-clear gate falls back to code + full `realtime_data` context instead of a true freeze frame.
- The ECMLink ECU may throw P1xxx python-obd can't name → reinforces §2 static table.

---

## 6. Suggested-fix field + internet enrichment (CIO ask 2026-06-05)

Add a **`suggested_fix`** to the lookup table, plus provenance so we never display an unverified fix as gospel (Principle 2 — Data Over Opinion). Schema delta:

| Column | Values | Notes |
|---|---|---|
| `suggested_fix` | TEXT | the fix text shown on screen |
| `fix_provenance` | `spool-validated` / `sourced` / `auto-unverified` / `none` | drives the display trust badge |
| `fix_source` | URL / citation | where it came from |
| `fix_confidence` | high / med / low | |

### 6a. Where the lookup happens — SERVER, post-drive. NOT in-car, NOT live.
On a **miss** (code absent, or no fix yet), the **server (chi-srv-01)** does the enrichment after the drive: web lookup of authoritative DSM sources (DSMtuners / ECMtuning / repair DB) ± Ollama (`llama3.1:8b`) summarization → writes `suggested_fix` + `fix_provenance='auto-unverified'` + `fix_source` → **syncs back to the Pi** on next sync. The Pi displays it tagged "unverified."

**Why not in-car/live:** ISO 9141-2 + the car has no reliable internet; the display must never block on a network call and must stay fully offline-capable. The server is the analytics authority (3-tier architecture) and already has Ollama + internet. Pi stays a consumer of synced facts.

### 6b. Safety gate — severity OVERRIDES an auto-fetched fix
An auto-fetched fix is **never** displayed as authoritative, and for dangerous codes it is **overridden, not shown raw**:
- 🔴 **STOP** / 🟡 **WATCH**: the severity directive wins. A generic internet "replace spark plugs" for a turbo **P0301** is *actively dangerous* — on a boosted 4G63 that misfire is far more likely detonation / a cracked ringland than a tired plug. These codes show **"STOP / diagnose — do not just swap parts"** regardless of what the web says, until I validate a real fix.
- 🟢 **MINOR** only: the auto-fetched fix may be the primary on-screen suggestion (still badged "unverified").

### 6c. Trust badge + promotion path
Display distinguishes `spool-validated` (✓ verified) from `auto-unverified` ("community suggestion, unverified"). Promotion: `auto-unverified` → Spool review → `spool-validated`. I own that review queue for any code above MINOR.

---

## 7. Open follow-ups (Spool)
1. Curate the DSM P1xxx severity/description **+ suggested_fix** subset (grounded; no fabrication).
2. Confirm Mode 02 freeze-frame support on MD326328 via live probe.
3. Live-read the actual drive-27 check-engine code → classify stop/watch/minor + clear-eligibility (DO NOT clear before reading).
4. Own the `auto-unverified → spool-validated` fix review queue for all 🔴/🟡 codes.

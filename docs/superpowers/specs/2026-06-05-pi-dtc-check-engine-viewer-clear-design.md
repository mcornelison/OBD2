# Pi DTC / Check-Engine Viewer + Gated Clear-Code — Design Spec v1.2

| Field | Value |
|---|---|
| Feature | **DTC / Check-Engine viewer** (on-Pi display) + **gated Clear-Code (Mode 04)** |
| Surfaces | Full-screen **takeover alert** (new code) + **Alerts card** (Card 5 of the touch carousel) + per-code **detail view** + **Clear flow** |
| Author | Iris (UI/UX Designer) |
| Date | 2026-06-05 (v1); 2026-06-05 (v1.1 — folded Spool's live results + 2 SME refinements); 2026-06-19 (v1.2 — folded Atlas gate conditions C-2/C-3 + Spool's DSM P1xxx table) |
| Status | **GROOM-READY (pending) — Atlas design-gate = CONDITIONAL PASS (2026-06-05 report + 2026-06-19 unified-alert ruling, no BLOCK); v1.2 folds the 3 build-gating conditions (C-1 sequencing, C-2 KOEO read, C-3 Mode 02 fallback) + Spool's P1xxx SSOT. Near-term line (F-103 → carousel shell → cards → DTC Card 5) GREEN-LIT by Atlas → Marcus on the fold. Argus acceptance still advisory-open (non-blocking).** |
| Target sprint | V0.28+ |
| Depends on | **F-092/F-097 carousel shell** (`docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md`) — this is its **Card 5 (Alerts+DTC)**, previously named-but-deferred — and transitively **F-103 splash** (shared chromium kiosk + `eclipse-states-http`). |
| Engine-safety SSOT | **`offices/tuner/dtc-display-clear-safety-advisory.md`** (Spool, CIO-ratified 2026-06-05) — severity tiers, clear-gate preconditions, suggested-fix provenance + severity override. **Non-negotiable on engine-protection grounds; this spec renders against it, it does not redefine it.** |

## 0. Provenance & Decisions (CIO brainstorm 2026-06-05)

Triggered by the CIO's check-engine light coming on during both legs of the (aborted) drive-27 run — a new, real use case for the Pi display. Designed live via the superpowers visual companion (HTML mockups, one decision per screen). Decisions ratified this session:

| # | Decision | Rationale |
|---|----------|-----------|
| D-1 | **Attention model = full-screen takeover** on a new code (CIO chose Option B over passive-card and hybrid) | The CIO wants a check-engine event to be impossible to miss. The takeover is the entry point; the Alerts card is its persistent home. |
| D-2 | **The takeover is severity-styled** — same skeleton, but color + directive + dismiss behavior change per Spool tier | A 🔴 misfire and a 🟢 gas-cap cannot get the identical screen — that is the alarm-fatigue trap and it would violate Spool's "pull over" vs "drive gently" messaging. Severity always wins. |
| D-3 | **Frequency rules** kill alarm fatigue: takeover fires only on a **new** code (MIL rising-edge), not on every boot of a known code; **one** takeover at a time (highest-severity = hero, others fold into "+N more"); **escalation re-fires**; after Acknowledge/Dismiss a persistent **ribbon** carries the alert on every card | Honest + proportional. Reuses the F-103 I-10b/F-7 alarm-fatigue guard at the dashboard layer. |
| D-4 | **Alerts card layout = Hero + list** (CIO chose Option A over a uniform list) | Worst code gets a prominent block with its directive; remaining codes are compact tappable rows. Eye goes straight to what matters; scales to 4–5 codes. |
| D-5 | **Code detail view** = fixed skeleton (hero · status · freeze-frame · suggested-fix · log/sync), with a **severity-gated fix area** and a **3-state trust badge** | Renders Spool's §6 suggested-fix semantics: 🔴/🟡 replace the fix with a "diagnose, don't swap parts" directive; only 🟢 MINOR shows a real fix, always badged by provenance. |
| D-6 | **Clear = one gated button** on the list (Mode 04 is all-or-nothing) with 3 states + hard confirm + post-clear re-read + refuse-2nd-clear | Renders Spool's §4 safety gate verbatim in spirit. There is no per-code clear in OBD-II, so the gate keys off the **highest-severity stored code**, not the one on screen. |

### 0.1 Changelog — v1.1 (Spool confirm + live results, 2026-06-05)

Spool reviewed v1 (`inbox/2026-06-05-from-spool-dtc-viewer-confirm-plus-live-results.md`): **S-1..S-4 confirmed correct, "ship it"**, and endorsed two of this spec's calls as improvements on his advisory (the §3 "gate re-enforced at the action path, not trusted from the button state" and the §5.4 "fix slot replaced, not hidden"). Folded:

- **Mode 02 freeze-frame CONFIRMED UNSUPPORTED on MD326328** (live KOEO probe). The §5.4 realtime_data fallback is now the **default** rendering for this ECU, not a contingency. Resolves the §11 open question + narrows Atlas A-4.
- **Live-validated end-to-end:** first real code **P0443** (EVAP purge-valve circuit, 🟢 MINOR; python-obd has the description, no static table needed) was read KOEO → logged (`dtc_log`, timestamped, syncing) → cleared (Mode 04) → re-read empty. The log→clear→confirm flow + "read before clear" are proven. Mechanics reference: `specs/examples/dtc_read_and_clear_koeo.py`.
- **R-1 condition-dependent severity** (S-1 nuance): some codes aren't one fixed tier — e.g. **P0171** (lean) is 🟡 at idle/cruise but 🔴 under boost/load. With Mode 02 dead there's no freeze-LOAD to auto-escalate from, so Spool's table classifies these **conservatively 🟡 with a "🔴 if set under load — verify" caveat**. The detail view + chip must support a **severity that carries a caveat line**, not just a flat chip (§4, §5.4).
- **R-2 ribbon red distinguishability** (S-2): the §5.2 ribbon rides on normal cards where brand-red elements live, so the ribbon's STOP-red must stay visually distinct from brand-red (use the brighter alert `--red-light` + a leading ⚠ glyph / subtle pulse) or the alarm reads as decoration (§5.2).

### 0.2 Changelog — v1.2 (Atlas gate conditions + Spool P1xxx table, 2026-06-19)

Atlas's design-gate landed as **CONDITIONAL PASS** (`offices/architect/reports/2026-06-05-dtc-and-dashboard-design-gate.md` + the 2026-06-19 unified-alert ruling `…/2026-06-19-iris-unified-alert-gate-ruling.md`) — **design sound, not a redraw**, with 3 cross-cutting conditions that gate the *build*, not the design. The near-term line (F-103 → carousel shell → cards → DTC Card 5) is **green-lit**; both alert-layer deltas (DELTA-1/DELTA-2) stay **out of this spec's near-term contract** (they're EDR-epic items). v1.2 folds:

- **C-1 (sequencing, hard):** unchanged — this spec is **Card 5** and depends on F-103 (kiosk + `eclipse-states-http`) + the F-092/F-097 carousel shell landing first. Already stated in the header "Depends on" + §8; no card may assume the kiosk/state-server already exist (Atlas: nothing in `src/` yet).
- **C-2 (DTC-A9, hard) — NEW capture path:** every existing capture path is gated behind DriveDetector (RPM > threshold), so a **KOEO** read (key-on, engine-off, RPM 0) captures **nothing** — the viewer would be blank exactly at "why's my light on?". Added a **key-on Mode 03(+07) read independent of DriveDetector**, writing `dtc_log` rows with **`drive_id = NULL`** (`dtc_log` already permits NULL — Atlas-verified). See §2 (gap), §8 (new unit), §10 A-9, §M-1 (US-A). This is the path the live P0443 read already exercised (`specs/examples/dtc_read_and_clear_koeo.py`).
- **C-3 (Mode 02) — CLOSED:** Mode 02 freeze-frame is **confirmed unsupported** on MD326328 (Spool live KOEO probe). The realtime_data fallback is already the **default** render (§5.4) and A-4 is RESOLVED; this changelog records C-3 satisfied — no "UNCONFIRMED" caveat remains anywhere in the spec.
- **Spool's DSM P1xxx severity table DELIVERED** (`offices/tuner/dsm-p1xxx-severity-table.md`) — the static-table P1xxx subset is no longer "owed". Folded: 7 engine-relevant P1xxx all **🟡 WATCH, none clearable**; **4 condition-dependent** (P1103/P1104/P1105/P1300 → escalate 🔴 under overboost / lean-at-load / knock → render the `severityCaveat`, exactly the R-1 mechanism); **5 auto-trans-only P1xxx** (P1715/1750/1751/1791/1795) are **N/A on the manual F5M33** → a quiet **"N/A this vehicle"** disposition, never a scary alert (new render case, §4 + §5.3). See §2, §4, §5.3, S-1/S-4.

## 1. Executive Summary

A check-engine / DTC surface for the OSOYOO 3.5″ 480×320 touch dashboard. When a **new** diagnostic trouble code sets (MIL rising-edge), a **full-screen takeover** appears, styled by Spool's severity tier (🔴 STOP / 🟡 WATCH / 🟢 MINOR) — red "pull over" for a misfire, calm green "safe to clear once logged" for a gas-cap. After Acknowledge/Dismiss the alert persists as a slim **ribbon** on every carousel card until the code clears. The **Alerts card** (Card 5) is the home: a **hero + list** of all stored/pending codes, worst-first, tappable into a **detail view** (code · long description · freeze-frame snapshot · suggested-fix · log/sync state). The **suggested-fix** area is **severity-gated** — only MINOR codes show an actual fix, always carrying a **trust badge** (✓ verified by Spool / 👥 community-unverified / ⏳ not fetched offline). **Clearing codes** is a single, all-or-nothing **Mode 04** button on the list, gated so it is enabled **only when every stored code is MINOR and has been captured + server-sync-acked**; it requires a hard confirm (warns about freeze-frame loss + readiness-monitor reset), re-reads to prove the clear, and refuses a second clear of any code that re-sets in the session ("don't chase the light"). The Pi is a **pure consumer** of a new `dtc` state file; it never decides severity, never fabricates a description or fix, and never blocks on a network call.

## 2. Context & Motivation

### What exists today (don't rebuild — Spool advisory §1)
| Piece | Where | Status |
|---|---|---|
| Mode 03 (stored) + Mode 07 (pending) retrieval | `src/pi/obdii/dtc_client.py` | built |
| MIL rising-edge → DTC re-fetch | `src/pi/obdii/mil_edge.py` | built |
| During-drive Mode 03 cadence + drive-end Mode 07 | `src/pi/obdii/dtc_logger.py` | built |
| `dtc_log` capture table | `src/pi/obdii/dtc_log_schema.py` | built |
| Pi→server `dtc_log` mirror (sync) | US-238 | built ("report to server" half done) |
| `dtc_freeze_frame` server infra | US-368 | built (**Pi-side Mode 02 capture CONFIRMED UNSUPPORTED on MD326328** — live KOEO probe 2026-06-05; detail view falls back to realtime_data context by default) |
| **Clear-DTC (Mode 04)** | — | **DOES NOT EXIST — net-new** (but the read→log→clear→re-read flow is live-validated against P0443 via `specs/examples/dtc_read_and_clear_koeo.py`) |
| **Key-on (KOEO) DTC read** independent of DriveDetector | — | **DOES NOT EXIST — net-new (C-2 / DTC-A9)**, see below |

> **The KOEO capture gap (C-2 / DTC-A9, Atlas gate — hard).** Every capture path above fires *during a drive* — `dtc_logger` runs its Mode 03 cadence + drive-end Mode 07 only while DriveDetector reports RPM above its threshold. At **key-on / engine-off** (RPM 0) DriveDetector never arms, so **nothing is captured** — the viewer would be blank at the exact moment the human walks up to a lit MIL and asks "why's my light on?". This spec therefore mandates a **key-on Mode 03(+07) read that does not depend on DriveDetector**, persisting `dtc_log` rows with **`drive_id = NULL`** (the column already permits NULL — Atlas-verified). It is the same read the live P0443 validation already exercised KOEO (`specs/examples/dtc_read_and_clear_koeo.py`); this makes it a first-class, always-available path, not a drive-only side effect. Ownership/trigger is load-bearing → Atlas A-9 (§10); the read itself is Spool-grounded and uses the existing `dtc_client`.

### Why now
The CIO's MIL is on (drive-27). He needs to *see* the code(s), understand severity, and — for harmless codes — clear them safely once logged. The carousel dashboard already reserved this as **Card 5 (Alerts+DTC)**; this pulls it forward.

### Description & fix gaps (mandate Spool's static table)
`dtc_client._asCode` pulls descriptions from python-obd's `DTC_MAP`, which returns an **empty string for Mitsubishi P1xxx** — exactly the codes the ECMLink ECU (drives ≥25) throws. The display must therefore handle "code, no description yet" gracefully, and a bundled static `code → short → long → severity → clear_eligible → suggested_fix` table is the source. **The Pi never fabricates a description, severity, or fix.**

**The DSM P1xxx subset is now DELIVERED** (`offices/tuner/dsm-p1xxx-severity-table.md`, Spool, 2026-06-05 — grounded in troublecodes.net's 95-Eclipse-Turbo / 96–98 list, severity/clearable/fix Spool-validated). Folded shape the display renders:
- **7 engine-relevant P1xxx** — P1103/P1104 (boost-control), P1105 (fuel-pressure), P1300 (timing), P1400 (EGR/MDP), P1500 (charging/alternator FR), P1600 (comms) — **all 🟡 WATCH, none clearable** (circuit/system faults return until fixed → the Clear button stays disabled, §6).
- **4 are condition-dependent** — P1103/P1104/P1105/P1300 base 🟡, escalate to 🔴 under **overboost / lean-at-load / knock** → render the **`severityCaveat`** line (the R-1 mechanism, §4 / §5.4), never flattened to a bare chip.
- **5 are auto-trans-only** — P1715/P1750/P1751/P1791/P1795 **cannot set on the manual F5M33**; if one ever appears it signals a misread / wrong-vehicle data, not a real fault → a quiet **"N/A this vehicle"** disposition (§4 / §5.3), not an alert/takeover.
- **No 🟢 clearable P1xxx** — the clearable codes on this car are generic EVAP (P0440/P0442/P0455, e.g. the P0443 already cleared), which carry their own python-obd descriptions.

The table is the *factory* meaning; the loaded ECMLink tune may suppress/alter EGR (P1400) and boost-control behavior. The Pi still never fabricates — an uncurated code renders "No description yet".

### Out of scope (named, deferred)
| Item | Why |
|---|---|
| The static lookup table contents (SAE wholesale + DSM P1xxx curation) | Spool owns (advisory §2, §7.1); this spec consumes it |
| Server-side internet enrichment of `suggested_fix` (web + Ollama) | Server feature (advisory §6a); Pi only displays the synced result |
| 1080p HDMI variant; on-screen keyboard | Carousel-shell scope; 480×320 only |
| Mode 06 / live test results | Not requested |

## 3. System Overview & Data Flow

The Pi display is a **consumer** of a new `dtc` state file, mirroring the F-103 / F-092 pattern. One direction of data flow.

```
 MIL rising-edge ─► dtc_logger/dtc_client (Mode 03/07[/02])
                         │ writes
                         ▼
   /var/run/eclipse-obd/states/dtc   ◄─ enriched fields (severity, suggested_fix,
                         │                provenance) merged from the synced static
                         │                table + server enrichment
                         ▼
   eclipse-states-http (read-only)  ──fetch ~1s──►  dashboard kiosk
                                                      │ takeover on new code
                                                      │ Alerts card + detail
                                                      ▼
   Clear request ──► privileged Mode-04 action path ──► dtc_client.clear()
                       (gate re-checked server-side/service-side, NOT trusted from UI)
```

### Key contracts
1. The display **never decides severity / clear-eligibility / fix text**. It renders what the `dtc` state reports (severity + `clear_eligible` + `suggested_fix` + `fix_provenance` all originate from Spool's table / server enrichment).
2. The display **never fabricates**. Missing description → "no description yet". Missing fix → "looking into it / not available offline". Never invent.
3. **Clear is never issued from the UI alone.** The UI requests a clear; the gate (all-MINOR + logged + server-acked) is **re-enforced at the action path**, not trusted from the button's enabled state. (Defense-in-depth, matching the F-092 service-control privilege pattern.)
4. The display **never blocks on the network**. Fix enrichment arrives via sync; the viewer is fully functional offline / WiFi-down / key-on-engine-off.

## 4. Severity Taxonomy (Spool SSOT — advisory §3, rendered)

| Tier | Color token | Takeover directive | Dismiss | Clear path |
|---|---|---|---|---|
| 🔴 **STOP** (misfire P0300–04, knock, lean-at-load, overheat, oil-pressure, P0325) | `--red` `#E60012` | "REDUCE LOAD · PULL OVER" | **Acknowledge only** → ribbon (no "dismiss & forget") | **Never** |
| 🟡 **WATCH** (fuel-trim, O2 circuit, P0401 EGR, P0420 cat) | `--amber-warn` `#FFC400` | "DRIVE GENTLY · GET DIAGNOSED" | Dismiss → ribbon | No |
| 🟢 **MINOR** (evap/gas-cap P0440/0442/0455, body) | `--green-ok` `#35C46A` *(NEW token, §7)* | "SAFE TO CLEAR ONCE LOGGED" | Dismiss → ribbon | **Yes — gated (§6)** |

The severity value is **read from the `dtc` state**, classified upstream from Spool's table. The display maps tier → color + directive + behavior; it does not classify.

**Condition-dependent severity (R-1).** A few codes aren't a single fixed tier — e.g. **P0171** (lean) is 🟡 at idle/cruise but 🔴 under boost/load. With Mode 02 dead on this ECU there is no freeze-LOAD to auto-escalate from, so Spool's table classifies these **conservatively 🟡 with a caveat** (`severityCaveat: "🔴 if set under load — verify"`). The display must render a tier chip that can **carry a caveat line** beneath it (takeover hero + detail), not just a flat chip. The caveat never silently upgrades the tier — it warns the human to check the conditions.

**"N/A this vehicle" disposition (Spool P1xxx table).** Five auto-transmission P1xxx (P1715/P1750/P1751/P1791/P1795) **cannot set on the manual F5M33**. If one is ever reported, it is a misread / wrong-vehicle signal, not a real fault. The display gives such a code a **fourth, quiet disposition** — a neutral `N/A` chip + "not applicable to this vehicle" — and it **never triggers a takeover or a ribbon**. This keeps a spurious code from masquerading as an engine alert (honest-instrument: don't alarm on a fault the car physically can't have). The `severity:"na"` value is read from the `dtc` state (classified upstream from Spool's table); the display does not decide applicability.

## 5. Surfaces — Visual Spec

Visual SSOT = F-103 tokens (mono type; `--text-secondary #888`, `--text-tertiary #666`; brand reds; `--amber-warn #FFC400`). One **new** token: `--green-ok #35C46A` for the MINOR / OK / "linked" state (§7 — needs adding to `specs/UI/`). No web fonts.

### 5.1 Takeover alert (D-1, D-2)
Full-bleed overlay above the dashboard, fired on a new code. Skeleton: icon · "CHECK ENGINE" · severity chip + hero code + short desc · directive line · "+N more codes" (if >1) · action buttons.
- 🔴 STOP: red radial bg, ⚠, pull-over directive, **[VIEW DETAIL ›] [Acknowledge]** (no plain dismiss).
- 🟡 WATCH: amber bg, ⚠, drive-gently directive, **[VIEW DETAIL ›] [Dismiss]**.
- 🟢 MINOR: dark-green bg, ⓘ, safe-to-clear directive, **[VIEW DETAIL ›] [Dismiss]**.
- Highest-severity code is the hero; others count into "+N more".

### 5.2 Frequency rules (D-3)
- Fires on a **new** code only (MIL rising-edge / a code not previously present). A re-known code at boot → **ribbon**, not a takeover.
- **One** takeover at a time.
- **Escalation re-fires**: a WATCH→STOP escalation, or a new STOP, re-triggers even after an earlier dismiss.
- After Acknowledge/Dismiss → persistent **ribbon** (red/amber) under the top bar on every carousel card: `⚠ CHECK ENGINE · <hero code> <desc> · tap ›`. Ribbon clears when the code is gone (or cleared, for MINOR).
- **Ribbon red ≠ brand red (R-2).** Unlike the full-bleed takeover, the ribbon rides on normal cards where brand-red chrome may live. The ribbon's STOP state must stay visually distinct from any brand-red — use the brighter alert `--red-light #F61D2D` (not brand `--red`), a leading ⚠ glyph, and/or a subtle slow pulse, so it reads as an alarm and never as decoration.

### 5.3 Alerts card — hero + list (D-4)
Card 5 of the carousel. Top bar (shared) + card body:
```
CHECK ENGINE                          3 stored · 1 pending
┌────────────────────────────────────────────────┐
│ [STOP]  P0301      Cylinder 1 misfire            │  ← hero block (worst code)
│         REDUCE LOAD · PULL OVER                   │
└────────────────────────────────────────────────┘
[WATCH] P0420  Catalyst efficiency low           ›    ← compact tappable rows
[WATCH] P1300  Ignition timing  ⚠🔴 if knock     ›    ← P1xxx w/ severityCaveat (Spool table)
[MINOR] P0442  Evap small leak                   ›
[ ?  ]  P16xx  No description yet          PEND  ›    ← graceful no-desc (uncurated code)
[ N/A ] P1750  Not applicable (A/T code)         ›    ← auto-trans P1xxx on a manual → quiet, no alert
────────────────────────────────────────────────
              🔒 CLEAR CODES                          ← single gated button (§6)
        unavailable — a STOP code is present
```
- Worst code = hero with its directive; remaining codes = compact rows (chip · code · short desc · status · `›`), sorted worst-first.
- A code with no description shows a neutral `?` chip + "No description yet" (never blank, never fabricated).
- A condition-dependent P1xxx (Spool table) shows its base 🟡 chip + an inline `severityCaveat` hint (e.g. `⚠🔴 if knock`); full caveat in detail (§5.4).
- An auto-trans P1xxx on this manual car shows the quiet **`N/A` chip** ("not applicable to this vehicle") and **sorts last**; it is informational only — no takeover, no ribbon (§4).
- Row tap → detail (§5.4). Clear button → §6.

### 5.4 Code detail view (D-5)
Fixed skeleton (scrolls on the panel): **‹ Back · code** | hero (chip + code + short desc) | severity directive band (🔴/🟡) | status meta (`STORED/PENDING · set <age> · Drive N · MIL on/off`) | **freeze-frame** grid | **suggested-fix** area | log/sync footer.

- **Freeze frame** ("crown jewel", advisory §4c) — sensor snapshot at the instant the code set: RPM, LOAD, COOLANT, STFT, LTFT, TIMING (+ boost where available). On STOP, load/RPM rendered hot. **On MD326328 (current ECU) Mode 02 is CONFIRMED unsupported** (live probe 2026-06-05), so the **default** rendering is the honest `realtime_data`-context fallback labeled "no freeze frame captured (this ECU) — showing context at fault time". A true freeze-frame grid renders only if a future ECU supports Mode 02. Never blank, never implied-but-empty.
- **Suggested-fix area — severity-gated (advisory §6b):**
  - 🔴 STOP / 🟡 WATCH → fix slot **replaced** by a directive band: "⚠ STOP — diagnose, don't just swap parts" + Spool's reasoning. The area is designed to be *replaced*, not merely hidden, so a dangerous code never shows a casual internet fix.
  - 🟢 MINOR → shows the actual `suggested_fix` text + a **trust badge**.
- **Trust badge — 3 states (advisory §6c):**
  - `spool-validated` → **✓ Verified · Spool** (green-tinted).
  - `auto-unverified` / `sourced` → **👥 Community · unverified** (dashed, muted — reads visibly less authoritative).
  - `none` / not-yet-synced → **⏳ Looking into it** ("not available offline — arrives on next sync"). No live net in the car (advisory §6a).
- **Log/sync footer** — `✓ logged · ✓ synced to server [· clear-eligible]`. This is the capture-before-clear precondition made visible; it drives the Clear gate.
- **No clear button on the detail view** — clear is global (all-or-nothing), so it lives only on the list. This structurally reinforces "no per-code clear".

## 6. Clear Flow (D-6 — Spool advisory §4, rendered)

One button on the Alerts list. **Mode 04 wipes ALL stored + pending codes, the freeze-frame, and resets readiness monitors** — so the gate keys off the **highest-severity stored code**, not the one on screen.

### 6.1 Button states
1. **Disabled — severity**: any 🟡/🔴 stored → `🔒 CLEAR CODES — unavailable, a STOP/WATCH code is present`.
2. **Disabled — not captured/synced**: all MINOR but log+server-ack not yet complete → `🔒 CLEAR CODES — waiting for server sync` (capture-before-clear, advisory §4c).
3. **Enabled**: every stored code MINOR **and** logged **and** server-acked → active `CLEAR CODES` (green-outline).

### 6.2 Confirm (hard gate)
Modal: **"Clear all codes?"** — "Wipes **every** stored + pending code, **erases the freeze-frame**, and **resets emissions readiness monitors** (a full drive cycle is needed before an inspection will pass). Can't be undone." Buttons: **[Cancel]** (easy default) · **[Clear all]** (deliberate).

### 6.3 Post-clear (advisory §4d)
- **Always re-read (Mode 03)** immediately → prove the clear ("0 stored, 0 pending, MIL off"), don't just report "command sent".
- **Re-set detection**: if any code returns immediately → show ⚠ "<code> returned — a code that comes back is a real fault; clearing again won't fix it" and **lock Clear for the session** ("don't chase the light"). Refuse a 2nd clear of any code that re-set this session.

### 6.4 Gate enforcement (load-bearing → Atlas)
The button's enabled state is UI convenience only. The **actual Mode 04 issuance re-checks the gate** at the privileged action path (all-MINOR + logged + server-acked). A tampered/stale UI must not be able to force a clear. The clear request reaches `dtc_client.clear()` (net-new) via the same privileged-action pattern the F-092 System Setup menu uses (polkit/privileged helper; kiosk stays unprivileged).

## 7. Visual Tokens — delta

| Token | Value | Use | Status |
|---|---|---|---|
| `--green-ok` | `#35C46A` | MINOR tier, OK/linked/verified states | **NEW — propose adding to `specs/UI/` SSOT** (W-3). Routes through Atlas as the SSOT-pattern owner. |
| `--red`/`--red-light`/`--red-dark` | `#E60012`/`#F61D2D`/`#BF000F` | STOP tier | exists (F-103) |
| `--amber-warn`/`--amber-soft` | `#FFC400`/`#FFC40033` | WATCH tier | exists (F-103) |

Severity chips: STOP = red bg/white text; WATCH = amber bg/black text; MINOR = green bg/black text; no-desc = neutral `#2a2f37` bg/muted text; **N/A (auto-trans P1xxx on this manual car) = same neutral `#2a2f37` bg/muted text, labeled `N/A`** — deliberately *un*-alarming. No new token needed (reuses the neutral no-desc treatment).

## 8. Integration / Architecture

### New + changed units
| Unit / file | Status | Purpose |
|---|---|---|
| DTC views (takeover + Alerts card + detail) in the dashboard kiosk | NEW (HTML/JS) | Card 5 of the carousel + the takeover overlay |
| **Key-on (KOEO) Mode 03(+07) read** independent of DriveDetector | **NET-NEW (C-2 / DTC-A9)** | reads stored+pending codes at key-on/engine-off (RPM 0) where DriveDetector never arms; persists `dtc_log` with **`drive_id = NULL`**, then feeds the `dtc` emitter. Uses the existing `dtc_client`; trigger/ownership → Atlas A-9. Closes the "blank at key-on" gap. |
| `dtc` state emitter → `/var/run/eclipse-obd/states/dtc` | NEW | publishes current codes + severity + suggested_fix + provenance + freeze-frame + log/sync status for the UI to read |
| `eclipse-states-http` | EXTEND | serve the new `dtc` endpoint read-only (already extended to full runtime in F-092) |
| Pi-side **Mode 02 freeze-frame capture** | **DEFERRED** (not needed for MD326328) | Mode 02 confirmed unsupported on the current ECU → detail view uses the realtime_data fallback by default. Build the capture path only when/if a Mode-02-capable ECU appears. |
| **Clear-DTC (Mode 04)** path: `dtc_client.clear()` + privileged action endpoint + server-side gate re-check | **NET-NEW (load-bearing)** | the only writer; gate enforced here, not in UI |
| Static lookup table loader (severity/desc/`clear_eligible`/`suggested_fix`/provenance), synced | NEW (consumes Spool's table) | merge into the `dtc` state so the UI reads enriched codes |
| Sync-ack signal (capture-before-clear) | NEW | surface "server has acked this code's sync" to gate the Clear button |

### `dtc` state file shape (proposed; Atlas ratifies paths/schema/ownership)
```json
{
  "mil": true,
  "codes": [
    { "code":"P0301", "status":"stored", "severity":"stop",
      "short":"Cylinder 1 misfire", "long":"…",
      "setAtTs":"2026-06-05T19:40:00Z", "driveId":27,
      "freezeFrame": {"rpm":4250,"loadPct":92,"coolantC":88,"stftPct":3,"ltftPct":7,"timingDeg":11,"source":"mode02"},
      "suggestedFix": null, "fixProvenance":"none",
      "logged": true, "syncAcked": true, "clearEligible": false },
    { "code":"P0442", "status":"stored", "severity":"minor",
      "short":"Evap small leak", "long":"…",
      "suggestedFix":"Check/tighten fuel cap; if it returns inspect EVAP hoses & purge valve.",
      "fixProvenance":"auto-unverified", "fixSource":"https://…",
      "logged": true, "syncAcked": true, "clearEligible": true }
  ],
  "newSinceTs": "2026-06-05T19:40:00Z",   // drives the takeover (new vs known)
  "clearGate": { "enabled": false, "reason":"stop_present" },  // severity_present | sync_pending | ok
  "sessionResetLock": ["P0442"],          // codes that re-set this session → refuse 2nd clear
  "ts": "2026-06-05T19:42:00Z"
}
```

Field notes (Atlas ratifies the schema):
- `severity` ∈ `stop | watch | minor | na | unknown`. `na` = an auto-trans P1xxx reported on this manual car (quiet disposition, no takeover/ribbon — §4); `unknown` = uncurated code, "No description yet". Classified upstream from Spool's table; the display never decides it.
- `severityCaveat` (optional, string) — present on condition-dependent codes (P1103/04/05/P1300, P0171…); the display renders it as a caveat line under the chip and **never** uses it to silently upgrade the tier (R-1, §4).
- `driveId` is **nullable** — a KOEO read (C-2) writes `drive_id = NULL` (no drive in progress). The display shows "key-on read" rather than "Drive N" when null.

### Touch
Reuses the F-092 carousel touch enablement; takeover buttons + list rows ≥40×40px tap targets.

## 9. Acceptance Criteria (Argus patterns: single-boolean, evidence-survival, failure-mode enumeration)

### Synthetic (CI-runnable, fixture-driven)
| # | Criterion | Evidence |
|---|---|---|
| S-1 | Takeover renders per severity from fixture (`severity:stop/watch/minor`) → correct color + directive + dismiss controls (STOP has no plain dismiss) | DOM test ×3 |
| S-2 | Takeover fires only when `newSinceTs` indicates a new code; a known-code fixture → no takeover, ribbon present | fixture test (both) |
| S-3 | Alerts card: hero = highest-severity code; rows sorted worst-first; a no-description code shows `?` + "No description yet", never blank | DOM test |
| S-4 | Detail: 🔴/🟡 fix area shows the diagnose directive and **no** raw fix text even if `suggestedFix` is non-null; 🟢 shows the fix + correct trust badge per `fixProvenance` (verified/community/offline) | fixture test (all branches) |
| S-5 | Missing freeze frame → "no freeze frame captured" / realtime fallback, labeled; never blank or fabricated | fixture test |
| S-6 | Clear button state matches `clearGate`: `stop_present`/`watch_present`→disabled+reason; `sync_pending`→disabled+reason; `ok`→enabled | DOM test ×3 |
| S-7 | Confirm dialog text includes freeze-frame-erase + readiness-reset warnings | DOM test |
| S-8 | A code in `sessionResetLock` → Clear stays locked with "don't chase the light"; UI offers no 2nd clear | fixture test |
| S-9 | Malformed/empty `dtc` JSON → "unavailable", no crash | fixture test |
| S-10 | Action path rejects a Clear when the gate fails server-side even if the UI requests it (gate not trusted from UI) | unit test of the Mode-04 path |
| S-11 | **C-2 KOEO read**: with DriveDetector inactive (RPM 0), a key-on read still captures stored+pending codes and writes `dtc_log` rows with `drive_id = NULL`; the detail view shows "key-on read" (not "Drive N") for a null `driveId` | unit test (read path) + DOM test (detail) |
| S-12 | **Auto-trans P1xxx** fixture (`severity:"na"`, e.g. P1750) → renders the quiet `N/A` chip, sorts last, and triggers **no** takeover and **no** ribbon | fixture test (takeover/ribbon both absent) |
| S-13 | **Condition-dependent P1xxx** fixture with `severityCaveat` (e.g. P1300 `🔴 if knock`) → base 🟡 chip renders with the caveat line; tier is **not** auto-upgraded to 🔴 | DOM test |

### IRL (drive-27 code is live — do NOT clear before reading; advisory §7.3)
| # | Criterion | Evidence |
|---|---|---|
| I-1 | Drive-27's real stored code renders on the Alerts card with the correct severity classification (Spool-confirmed) | photo + `cat dtc` + Spool sign-off |
| I-2 | Tapping the code opens detail with freeze-frame (or honest fallback if Mode 02 silent on MD326328) | photo + Mode 02 probe result |
| I-3 | A P1xxx with no table entry renders "No description yet" (not blank) | photo |
| I-4 | If the code is 🔴/🟡 → no clear button enabled; detail shows the diagnose directive, no raw internet fix | photo |
| I-5 | Capture-before-clear: a MINOR code is logged + server-acked before the Clear button enables | `dtc_log` + server row + screenshot |
| I-6 | (When a clearable MINOR exists) Clear → confirm → Mode 04 issued → re-read shows cleared + MIL off; freeze frame preserved server-side | recording + `dtc_freeze_frame` row |
| I-7 | Re-set case: if a cleared code returns immediately, Clear locks for the session | recording |
| I-8 | **C-2 KOEO**: at key-on / engine-off (no drive), the lit MIL's code(s) appear on the Alerts card within a few seconds — the "why's my light on?" path is *not* blank; `dtc_log` row has `drive_id = NULL` | photo + `cat dtc` + `dtc_log` row |

### Failure modes (must NOT happen)
| F | Failure | Detection |
|---|---|---|
| F-1 | A dangerous code (🔴/🟡) shows a casual "swap part X" internet fix | S-4, I-4 |
| F-2 | Clear enabled while any 🟡/🔴 is stored, or before capture+sync-ack | S-6, I-4, I-5 |
| F-3 | Clear issued from a tampered/stale UI without the server-side gate passing | S-10 |
| F-4 | Freeze frame destroyed by a clear without being captured first | I-5, I-6 |
| F-5 | A blank/fabricated description, severity, or fix shown (no-desc not handled, or invented data) | S-3, S-5, I-3 |
| F-6 | Takeover on every boot of a known code (alarm fatigue) | S-2 |
| F-7 | 2nd clear offered for a code that re-set ("chasing the light") | S-8, I-7 |
| F-8 | UI blocks waiting on a network fix lookup | code review (display reads synced state only) |
| F-9 | Viewer blank at key-on because capture is DriveDetector-gated (the C-2 gap) | S-11, I-8 |
| F-10 | An auto-trans P1xxx fires a scary takeover/ribbon on this manual car (should be quiet N/A) | S-12 |

## 10. Routing Surface

### Atlas (design-gate, Rule 10) — load-bearing
| # | Item | Verdict |
|---|---|---|
| A-1 | **Clear-DTC (Mode 04) path** — net-new writer to the vehicle; who issues it, privilege path (polkit/helper, F-092 precedent), and **server-side/service-side gate re-check** so a clear can't be forced from the UI | PENDING |
| A-2 | `dtc` state emitter — ownership, path, schema (`/var/run/eclipse-obd/states/dtc`); merge of live codes + synced static table + server enrichment | PENDING |
| A-3 | Extend `eclipse-states-http` with the read-only `dtc` endpoint | PENDING |
| A-4 | ~~Pi-side Mode 02 freeze-frame capture on MD326328~~ — **RESOLVED**: Mode 02 confirmed unsupported (Spool live probe 2026-06-05). Capture path deferred; realtime_data fallback is the default render. Atlas only blesses the fallback contract. | RESOLVED — confirm fallback |
| A-5 | **Capture-before-clear sync-ack signal** — where "server acked this code" originates + how the gate reads it | PENDING |
| A-6 | Takeover lifecycle over the kiosk (auto-surface overlay vs carousel; escalation re-fire; ribbon) | PENDING |
| A-7 | `suggested_fix` server-side enrichment + sync into the `dtc` state (web + Ollama; advisory §6a) — server architecture | PENDING |
| A-8 | **NEW token `--green-ok #35C46A`** into `specs/UI/` SSOT (Atlas owns the SSOT-design-pattern; W-3) | CONDITIONAL PASS — add once to `specs/UI/` (Rule-10 DoD in-sprint) |
| A-9 | **NEW (C-2 / DTC-A9, hard) — key-on Mode 03(+07) read** independent of DriveDetector, `drive_id = NULL`. Ownership/trigger: which unit fires the KOEO read + when (key-on edge), reusing `dtc_client`; `dtc_log` NULL-`drive_id` confirmed allowed | RAISED by Atlas (gate condition) — folded; **ownership/trigger PENDING Atlas** |
| A-* | **Standing conditions (Atlas):** C-1 F-103 first (kiosk/state-server unbuilt); DTC-A1 clear-gate re-checked at the action path against `dtc_log` + sync-ack (never trust the UI button); DTC-A1 uses the **I-036 polkit precedent** (no new privileged helper); Rule-10 DoD = emitter + Mode-04 path + `--green-ok` land with `architecture.md` + `specs/UI/` updates in-sprint | NOTED |

### Spool (semantics — he owns these; this spec renders them)
| # | Item |
|---|---|
| S-1 | Severity classification per code (the `severity` value in the `dtc` state) — incl. DSM P1xxx subset (advisory §7.1) — **DELIVERED 2026-06-05** (`offices/tuner/dsm-p1xxx-severity-table.md`): 7 engine P1xxx 🟡/non-clearable, 4 condition-dependent, 5 auto-trans N/A. Folded (§2/§4/§5.3) |
| S-2 | `clear_eligible` + the clear-gate thresholds (all-MINOR; capture+sync-ack) — confirm rendered correctly |
| S-3 | `suggested_fix` + `fix_provenance` values + the severity-override copy ("diagnose, don't swap parts") — **DELIVERED** in the P1xxx table (per-code Spool fix text, `fix_provenance = spool-validated`) |
| S-4 | ~~Live drive-27 code classification + Mode 02 probe~~ — **DONE** (2026-06-05): first code P0443 = 🟢 MINOR, read→log→clear→re-read live-validated; Mode 02 confirmed unsupported. ~~Remaining: DSM P1xxx severity + `suggested_fix` subset~~ — **also DELIVERED 2026-06-05** (S-1/S-3). Spool's P1xxx plate is clear. |

### Argus (advisory)
| # | Item |
|---|---|
| Q-1 | §10 acceptance criteria sign-off |
| Q-2 | IRL drill methodology — using the **real, already-set** drive-27 code (do NOT induce/clear before reading); how to evidence the clear path without a convenient clearable code |
| Q-3 | Evidence capture for the takeover + visual/severity criteria |

### Marcus (PM — sprint scoping)
| # | Item |
|---|---|
| M-1 | Proposed split: **US-A** key-on (KOEO) Mode 03(+07) read (C-2/DTC-A9, `drive_id=NULL`) + `dtc` emitter + state-server endpoint + static-table loader/sync (incl. Spool's P1xxx table) · **US-B** takeover + ribbon (severity-styled, frequency rules) · **US-C** Alerts card (hero+list) + detail view (freeze-frame + severity-gated fix + trust badge + **condition-dependent `severityCaveat`** + **auto-trans `N/A`** quiet disposition) · **US-D** Clear-DTC Mode 04 path + gate + confirm + re-read + session-lock (load-bearing — pairs with Atlas A-1) · **US-E** detail-view realtime_data fallback render (Mode 02 unsupported on current ECU — no capture path; lands with US-C) |
| M-2 | **Depends on** the F-092/F-097 carousel shell (Card 5 slot) + F-103 kiosk/state-server — sequence after/with them |
| M-3 | Rule-10 DoD: the emitter + Mode 04 path + token land matching `specs/architecture.md` + `specs/UI/` updates in-sprint (A-1/A-2/A-8) |

## 11. Open Questions
- ~~Mode 02 support on MD326328~~ — **RESOLVED 2026-06-05**: confirmed unsupported (Spool live probe). Detail view uses the realtime_data context fallback as the default; no capture path built for this ECU.
- **Takeover dismissal on STOP while driving** — "Acknowledge" drops to ribbon; confirm there's no scenario where STOP must stay full-screen (vs. always allowing the driver to clear the view to see the road). Current design favors driver control (ribbon persists).
- **Clear of mixed pending+stored** — Mode 04 wipes pending too; confirm the gate copy makes that clear (covered in confirm text; flag if more emphasis wanted).

## 12. Routing Plan
```
Iris (this spec) → CIO review
   → A2AL Atlas (design-gate A-1..A-8, load-bearing — Clear path is the heavy item)
   → A2AL Spool (semantics S-1..S-4; ack his two advisories)
   → A2AL Argus (advisory Q-1..Q-3)
   → on Atlas sign-off: A2AL Marcus (groom-ready, story split M-1)
```

---
*End of spec v1.2. Atlas design-gate = CONDITIONAL PASS (no BLOCK); v1.2 folds C-1/C-2/C-3 + Spool's P1xxx SSOT. Near-term line green-lit by Atlas → groom-ready to Marcus (DELTA-1/DELTA-2 alert-layer items held out as EDR-epic scope). Argus acceptance advisory-open (non-blocking).*

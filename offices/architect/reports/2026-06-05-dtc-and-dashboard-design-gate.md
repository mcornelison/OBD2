# Atlas Design-Gate (Rule 10) — F-092/F-097 Touch Carousel + DTC Viewer/Clear (combined)

**Gate by:** Atlas (Architect) · **Date:** 2026-06-05 · **Requested by:** Iris (UI/UX)
**Specs gated:**
- `docs/superpowers/specs/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md` (v1.1)
- `docs/superpowers/specs/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md` (v1)
**Engine-safety SSOT (rendered against, not re-litigated):** `offices/tuner/dtc-display-clear-safety-advisory.md` (Spool, CIO-ratified)

## Disposition

**CONDITIONAL PASS — both designs, sequenced.** The architecture is sound: both are pure
consumers of state files, never decide system state, never fabricate, and put the two
writers (service-control, Mode-04 clear) behind a re-checked privileged path. I'm signing
off the *design*, gated by **three cross-cutting conditions** (below) that must be cleared
before/within the build. Two of them are hard prerequisites, not nitpicks.

This is **not a BLOCK** — the designs don't need redrawing. But "build now as if the
foundation exists" is not available, because it doesn't (C-1).

---

## Verification ledger (checked against real systems, not the spec narrative)

| Claim | Verdict | Evidence |
|---|---|---|
| dtc_client / mil_edge / dtc_logger / dtc_log_schema built | ✅ exist | `src/pi/obdii/*` |
| `dtc_client.clear()` / Mode 04 exists | ✅ **does NOT** (net-new) | grep = 0 in `dtc_client.py` |
| status_display.py / dashboard_layout.py (pygame) built | ✅ exist | `src/pi/hardware/*` |
| **F-103 `eclipse-states-http` + kiosk built** | 🔴 **NOT built — spec only** | no `states-http`/`HEALTHY_YIELD` in `src/`/`deploy/`; only `docs/.../2026-05-26-b103-splash-animation-design.md` + `offices/pm/backlog/F-103-*` |
| I-036 polkit precedent | ✅ real | `deploy/polkit-rules/50-eclipse-obd-poweroff.rules` |
| DriveDetector gates capture on RPM>threshold (KOEO claim) | ✅ confirmed | `detector.py` `DEFAULT_DRIVE_START_RPM_THRESHOLD`, "drive started when RPM > threshold" |
| `dtc_log` permits NULL drive_id (KOEO capture) | ✅ schema-ready | `dtc_log_schema.py` "drive_id INTEGER NULL … Nullable because a Mode 03 probe may happen before _startDrive" |
| Mode 02 freeze-frame on MD326328 | ✅ **confirmed UNSUPPORTED** | Spool advisory §5 (direct KOEO read 2026-06-05, returned null) |

---

## Cross-cutting conditions (clear these before build)

### C-1 — F-103 is the foundation and it is unbuilt. Sequence it first. (BLOCKING PREREQUISITE)
Both specs depend on F-103's chromium kiosk + `eclipse-states-http` localhost state-server +
the `HEALTHY_YIELD` hand-off + the token SSOT. **None of it exists in code yet** — F-103 is a
gated *design* (I signed it 2026-05-26) that was never sprinted. The dependency chain is:

```
F-103 (kiosk + eclipse-states-http + tokens)   ← unbuilt
   └─► F-092/F-097 carousel shell (US-A)        ← this gate
         └─► DTC Card 5 + takeover               ← this gate
```

**Ruling:** F-103 must land first (or as the first story of this line). The carousel-shell
story (dashboard US-A) should either *be* F-103's first hardware build or explicitly carry the
kiosk + state-server creation. Do not scope the cards or the DTC surface as if the kiosk/state-
server are present. This is a sequencing fact, not a design defect — surfacing it so Marcus
doesn't groom a sprint whose first card assumes an absent runtime.

### C-2 — KOEO (key-on / engine-off) capture path is REQUIRED and under-scoped. (BLOCKING for DTC)
The DTC viewer's primary use case is *"pull up, key on, why is my light on?"* — RPM 0, no drive.
But **every** current capture path is gated behind `DriveDetector._startDrive` (RPM>threshold),
so KOEO captures **nothing** — the viewer would be blank exactly when it's needed. Spool flagged
this as a HARD requirement (advisory §1); the DTC spec's A-items under-weight it (it's capture
architecture, my lane, not a display concern).

**Ruling:** add a **key-on Mode 03(+07) read independent of DriveDetector**, firing on
connection/key-on at RPM 0, writing `dtc_log` with `drive_id = NULL` (schema already permits it —
verified). This is a new capture trigger in the DTC capture service and must be in scope (fold
into DTC US-A "emitter + capture", or a dedicated story). Without it the feature does not meet
its own primary use case. Tracking as **gate item DTC-A9** below.

### C-3 — Mode 02 freeze-frame is confirmed unsupported; build the fallback, fix the stale caveat.
Spool's 2026-06-05 KOEO probe **confirms Mode 02 returns null on MD326328**. So DTC A-4 is not
"verify Mode 02" — it's "Mode 02 is out; the capture-before-clear snapshot and the detail
'freeze frame' section use the **`realtime_data` context fallback**, honestly labeled 'no freeze
frame captured on this ECU'." **Do not build a Mode 02 capture path** (it would be dead code).
The server `dtc_freeze_frame` infra (US-368) stays for a future ECU but the Pi capture is
realtime_data-context. **Spec fix:** the DTC spec §5 "Remaining caveats" still says Mode 02
"UNCONFIRMED — probe next session"; that contradicts §5's own confirmed result — update to
CONFIRMED-unsupported so a future reader doesn't re-chase it.

---

## Dashboard (F-092/F-097) — A-1..A-8 verdicts

| # | Item | Verdict | Ruling |
|---|---|---|---|
| A-1 | Splash→dashboard hand-off | ✅ PASS (per C-1) | Hand-off must be **systemd unit ordering / kiosk-swap**, not JS `window.close()` alone (fragile in kiosk). The dashboard kiosk unit starts `After=` the splash reaches `HEALTHY_YIELD`; the splash signals completion via a state-file transition the dashboard unit waits on. Gated on F-103 existing. |
| A-2 | Extend `eclipse-states-http` boot→full-runtime | ✅ PASS | Sound; read-only contract preserved. The service stays single-owner, stdlib, 127.0.0.1. **Rule-10 DoD:** the lifetime change + new endpoints land with a `specs/architecture.md` update in-sprint. |
| A-3 | Two emitters: paths/schemas/**ownership** | ✅ PASS w/ condition | Paths `/var/run/eclipse-obd/states/{system-status,battery-health}` approved. **Ownership = the service that already owns the data — do NOT spawn new daemons:** `battery-health` written by the power-watch process (owns MAX17048/VCELL); `system-status` written by the OBD orchestrator/sync (owns BT-link + sync state). Each emitter is an SSOT writer-seam: it stamps its own freshness/`ts`; the UI must never *infer* staleness, only render the emitter's flag. |
| A-4 | Supersede pygame `status_display.py` — parity-gated sunset | ✅ PASS w/ condition | No hard cut. Republish the pygame data via the emitters first; cut over in **one** commit gated by a parity check. **Must preserve the US-264 PowerCardFields honest-instrument rule: VCELL authoritative + largest, SOC smallest + `(uncalibrated)`.** No window where both surfaces run (failure F-4). Pygame sunset is a *later* story than US-A, after parity is proven. |
| A-5 | Touch enablement in chromium kiosk | ✅ PASS | Low risk; OSOYOO capacitive over USB reaches chromium natively. Verify at build; not architecturally load-bearing. |
| A-6 | `draining` boolean vs ShutdownSequencer | ✅ PASS w/ condition (joint Spool) | **The honesty hinge.** `draining=true` may render the failsafe ladder ONLY when: wall/ignition power is lost **AND** the ShutdownSequencer (F-7) is NOT executing a normal prompt key-off shutdown **AND** the pack is actually depleting. A normal ~10–12s key-off shutdown must NOT trip the ladder (the D-2 dishonest-instrument trap). Predicate emitted by power-watch (it owns sequencer state); Spool sets the depletion threshold. This ties to my open sequencer items — I'll co-author the predicate. |
| A-7 | Service-control privilege path | ✅ PASS — **use polkit, not a helper daemon** | Build on the verified I-036 polkit precedent: **scoped polkit rules per unit**, not a new privileged helper (less attack surface, proven pattern). Install-fixed allow-list (`eclipse-obd`/`eclipse-sync` start/stop/restart; `eclipse-powerwatch` **restart-only**; `eclipse-dashboard` stop=Exit). **Enforce `eclipse-powerwatch` no-stop at the polkit-rule layer too**, not just a disabled UI button (defense-in-depth — failure F-7/F-9). Kiosk stays unprivileged; any unit off the list is rejected by the rule, not the UI. |
| A-8 | Exit/Close-UI lifecycle | ✅ PASS | Kiosk = systemd unit `WantedBy=graphical.target`; Exit = stop the unit via the same scoped polkit; auto-relaunch on reboot. Confirm-and-return contract holds. |

---

## DTC Viewer + Clear (Card 5) — A-1..A-8 + A-9 verdicts

| # | Item | Verdict | Ruling |
|---|---|---|---|
| A-1 | **Clear-DTC (Mode 04) path** — the heavy item | ✅ PASS w/ hard condition | Net-new `dtc_client.clear()`, issued **only** via the scoped-polkit privileged action path (same family as dashboard A-7 / I-036), kiosk never issues OBD directly. **The gate (all-stored-MINOR + logged + server-sync-acked) is RE-CHECKED at the action path against authoritative state (`dtc_log` + sync-ack), independent of the UI's button state.** A tampered/stale UI must not force a clear (failure F-3). Capture-before-clear is mandatory but, per C-3, "capture" = code + `realtime_data` snapshot + sync-ack (no Mode 02). Post-clear Mode-03 re-read + session re-set lock as specified. |
| A-2 | `dtc` state emitter — path/schema/ownership | ✅ PASS | `/var/run/eclipse-obd/states/dtc`, owned by the DTC capture service (the thing doing Mode 03/07 + the KOEO read C-2). Merges live codes + synced static table + server enrichment. Never fabricates: missing desc/fix → null, UI renders "no description yet" / "looking into it". Schema (§8) approved. |
| A-3 | Extend `eclipse-states-http` with `dtc` endpoint | ✅ PASS | Trivial read-only extension of dashboard A-2; gated on F-103 + dashboard state-server existing. |
| A-4 | Pi-side Mode 02 freeze-frame capture | ✅ **RESOLVED → realtime_data fallback** (see C-3) | Mode 02 confirmed unsupported. Do NOT build a Mode 02 capture. Detail "freeze frame" + capture-before-clear use the labeled `realtime_data` snapshot. Honest "no freeze frame on this ECU". |
| A-5 | Capture-before-clear sync-ack signal | ✅ PASS w/ condition | The ack must be a **server-confirmed receipt** of the code's `dtc_log` row (US-238 mirror), surfaced per-code as `syncAcked` — NOT a Pi-side optimistic "I sent it" flag. The clear gate (and its action-path re-check) reads this. |
| A-6 | Takeover lifecycle over the kiosk | ✅ PASS | Takeover is a UI overlay layer over the carousel (not a separate kiosk), fired by the emitter's `newSinceTs` (MIL rising-edge). Escalation re-fire + persistent ribbon as specified; reuses the F-103 alarm-fatigue guard. |
| A-7 | `suggested_fix` server enrichment + sync | ✅ PASS | Server-side (chi-srv-01 web + Ollama), post-drive, per advisory §6a — never live/in-car; Pi displays synced result by provenance badge. **Severity-override (STOP/WATCH → diagnose-directive, never a raw fix) enforced in the display mapping; emitter should not surface a raw fix for non-MINOR codes.** Matches 3-tier (server = analytics authority). |
| A-8 | NEW token `--green-ok #35C46A` → `specs/UI/` SSOT | ✅ PASS | I own the SSOT pattern: add `--green-ok #35C46A` once to `specs/UI/` tokens; both specs consume it (no per-spec copy). |
| **A-9** | **KOEO capture path (NEW — from C-2)** | ⚠️ **REQUIRED, add to scope** | Key-on Mode 03(+07) read independent of DriveDetector, `drive_id=NULL`. Primary-use-case blocker if omitted. See C-2. |

---

## Sequencing recommendation (to Marcus, on CIO's nod)

1. **F-103** (kiosk + `eclipse-states-http` + token SSOT + `HEALTHY_YIELD` signal) — the unbuilt foundation. **First.**
2. **Dashboard US-A** carousel shell (rides on / completes the F-103 kiosk + state-server extension).
3. **Dashboard US-B/US-C** System Status + Battery Health cards + their two emitters (+ Spool semantics, A-6 predicate).
4. **Dashboard US-E** System Setup menu + polkit service-control (A-7/A-8).
5. **Dashboard US-D** pygame sunset (parity-gated, after US-B/C reach parity).
6. **DTC US-A..US-E** Card 5: emitter + **KOEO capture (A-9)** + takeover + Alerts/detail + **Mode-04 clear path (A-1)**. Last, because it's Card 5 on the settled carousel and carries the only vehicle writer.

**Rule-10 DoD (both):** state-server extension, emitters, the Mode-04 path, and the `--green-ok`
token each land with matching `specs/architecture.md` (+ `specs/UI/`) updates **in the same
sprint** — not a follow-up.

---

## Bottom line for Iris
Both designs PASS the gate — they're honest-instrument, consumer-only, and put the writers behind
a re-checked privileged path. Three things gate the *build*, not the design: **(C-1)** F-103 must
be built first (it's still just a spec); **(C-2)** add the KOEO capture path (DTC-A9) or the
viewer is blank at key-on; **(C-3)** Mode 02 is confirmed dead on this ECU — build the
realtime_data fallback and fix the stale caveat. Open to pushback on any ruling on its merits.

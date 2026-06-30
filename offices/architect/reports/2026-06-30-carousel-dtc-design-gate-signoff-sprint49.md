# Atlas Design-Gate Signoff — F-092/F-097 Carousel + F-111 DTC Viewer (Sprint 49 candidates)

**By:** Atlas (Architect) · **Date:** 2026-06-30 · **Requested by:** Marcus (PM, `2026-06-29-from-marcus-request-carousel-dtc-design-gate-signoff`)
**Specs gated:** carousel `…/2026-06-05-pi-touch-carousel-dashboard-f092-f097-design.md` **v1.2** · DTC `…/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md` **v1.2**
**Supersedes/affirms:** my 2026-06-05 combined gate (`reports/2026-06-05-dtc-and-dashboard-design-gate.md`) + 2026-06-19 unified-alert ruling.

> Audit run read-only, **zero git commands** (Rex mid-sprint; commit-hold in effect). Report + routing notes written to disk, uncommitted.

## Verdict: SIGNOFF — design-gate PASS, cleared to groom as Sprint 49 (gated behind F-103 landing)

Both specs evolved to **v1.2** and faithfully folded my three 2026-06-05 conditions. My A-item rulings from that report **stand** (the spec §9/§10 tables still say "PENDING" because the spec wasn't back-annotated; the *report* is the ruling). Two items were genuinely still open — I rule both below — plus one carry-forward from my Sprint-48 work. **No BLOCK.**

### My 2026-06-05 conditions — status in v1.2
- **C-1 (F-103 first) — NOW SATISFIED (sequencing).** F-103 is in Sprint 48 / V0.29.2 (Rule-13 PASS'd 2026-06-30). The carousel shell depends on the F-103 kiosk + `eclipse-states-http`; DTC is Card 5 on the carousel. Sprint 49 is correctly gated **behind F-103 actually landing** — groom it now, dispatch it after F-103 ships.
- **C-2 (KOEO capture) — folded as DTC-A9**, ownership/trigger still owed → **ruled below.**
- **C-3 (Mode-02 dead → realtime_data fallback) — CLOSED.** Confirmed-unsupported on MD326328; fallback is the default render; the stale "UNCONFIRMED" caveat is gone. I only bless the fallback contract (done).
- **Unified-alert DELTA-1/DELTA-2** correctly held **out** of this near-term contract as EDR-epic scope (my 2026-06-19 ruling) — verified absent from both specs' build scope.

## Ruling 1 — DTC A-9 (KOEO read) ownership + trigger ✅

The requirement was mine (C-2); the spec correctly mandates a key-on Mode 03(+07) read independent of DriveDetector writing `drive_id=NULL`. Open piece: *which unit fires it, when.* Ruling (grounded in code):

- **Trigger = the OBD connection-established / key-on edge**, not DriveDetector. The orchestrator already exposes `onConnectionRestored`/`onConnectionLost` callbacks (`event_router.py:101-126`). The KOEO read fires a **one-shot Mode 03(+07)** when the link comes up (key-on, RPM 0).
- **Gate it on "no active RUNNING drive"** so it does not duplicate the in-drive `dtc_logger` cadence (which already covers the driving case). KOEO read = the *engine-off* complement of the existing drive-gated path.
- **Owner = the DTC capture path** (give `dtc_logger` a connection-edge entrypoint, reusing `dtc_client.readStoredDtcs`/`readPendingDtcs` — both already take a bare `connection`; the read→clear flow is validated in `specs/examples/dtc_read_and_clear_koeo.py`). The orchestrator wires the callback; DriveDetector is not involved.
- **CONDITION (cross-link to A-9 / US-388):** the KOEO read must stamp **`drive_id = NULL` explicitly**, NOT via `getCurrentDriveId()`. Before US-388's gap-fence lands, a stale-open-drive leak (A-9 Root 2) can leave `_currentDriveId` set — a KOEO read inheriting that stale id is the exact attribution corruption US-388 fixes. Stamp NULL at the source. (`dtc_log.drive_id` is `INTEGER NULL` — schema-blessed, verified `dtc_log_schema.py:95-96`.)

## Ruling 2 — C-5 carry-forward to the three new emitters ✅ (NEW since 2026-06-05)

The carousel + DTC add **three** new state files — `system-status`, `battery-health`, `dtc` — under `/var/run/eclipse-obd/states/` and extend `eclipse-states-http` to full runtime. My Sprint-48 **C-5** ruling (states-dir boot-provisioning + `RuntimeDirectory` lifecycle) now governs them:
- The new emitters **ride the F-103 / Sprint-48 states-dir provisioning** — they MUST NOT re-invent it, and MUST order after it exists. Since F-103 (Sprint 48) establishes `/run/eclipse-obd/states/` provisioning (Rule-13-verified), these emitters only need to *write into* the provisioned dir + declare the right service ordering.
- **Rule-10 DoD:** the `specs/architecture.md` states-dir ownership+lifecycle section (owned by Sprint 48 US-395) is extended to list these three new writers — one place, the multi-owner runtime-dir SSOT contract. This is a dependency on F-103, not new provisioning work — flagging so the Sprint-49 groom doesn't duplicate it or, worse, assume the dir without the dependency.

## Standing build conditions (re-affirmed; these gate the build, not the design)
- **Emitter ownership (carousel A-3):** `battery-health` ← power-watch (owns MAX17048); `system-status` ← orchestrator/sync (owns BT-link + sync); `dtc` ← the DTC capture path. No new daemons; each emitter stamps its own freshness; the UI renders the flag, never *infers* staleness.
- **Battery-health honesty (Spool, render-breaking):** SoC % from the MAX17048 register **only**, never lerp'd from the voltage columns (`*_soc` holds VOLTS); stale-green data-age guard; temp "not captured"; UPS-LiPo not "vehicle battery". (Acceptance S-7/S-8/S-9/S-10, failure F-8..F-11 — present.)
- **`draining` failsafe honesty (A-6):** the ladder renders ONLY on genuine drain (wall/ignition power lost **AND** ShutdownSequencer not running a normal key-off **AND** pack actually depleting). A normal ~10-12s key-off must not trip it (the D-2 dishonest-instrument trap). Predicate owned by power-watch; Spool sets the depletion threshold.
- **Mode-04 clear (DTC A-1, the heavy item):** net-new `dtc_client.clear()` issued ONLY via the scoped-**polkit** privileged path (I-036 precedent — NOT a new helper daemon); kiosk stays unprivileged; the all-MINOR + logged + server-sync-acked gate is **re-checked at the action path** against `dtc_log` + sync-ack, never trusted from the UI button (failure F-3).
- **Parity-gated pygame sunset (A-4):** no window where both pygame `status_display` and the HTML surface run (failure F-4); republish via the emitters first, cut over in one commit gated by a parity check, after the cards reach parity; preserve the US-264 VCELL-authoritative/SOC-`(uncalibrated)` rule.
- **`--green-ok #35C46A` token (A-8):** add **once** to `specs/UI/` SSOT (I own the SSOT pattern); both specs consume it — no per-spec copy.
- **Rule-10 DoD (both):** the state-server extension, each emitter, the Mode-04 path, and the `--green-ok` token land with matching `specs/architecture.md` (+ `specs/UI/`) updates **in-sprint**, not a follow-up.

## Sequencing (to Marcus)
Groom Sprint 49 in the order from my 2026-06-05 report §"Sequencing", dispatch **after F-103 lands**:
1. Carousel **US-A** shell (rides/completes the F-103 kiosk + state-server extension) → **US-B/US-C** System Status + Battery Health cards + their two emitters → **US-E** System Setup menu + polkit service-control → **US-D** pygame sunset (parity-gated, last).
2. DTC **US-A** KOEO read (Ruling 1) + `dtc` emitter + state-server endpoint + static-table loader → **US-B** takeover/ribbon → **US-C** Alerts card + detail → **US-D** Mode-04 clear path (pairs with A-1). Card 5 = last; it carries the only vehicle writer.
Consider whether 9-ish stories is one sprint or split carousel/DTC into two (PM sizing call, not mine).

## Still owed (tracked, NON-blocking — failsafe sub-state only)
- **Spool S-2** — live runtime-remaining formula (during a drain) + the failsafe ladder thresholds (3.70/3.55/3.45 V placeholders). These gate only the F-097 **FAILSAFE** sub-state, not the everyday NORMAL Battery-Health view. Flag if not derivable → failsafe shows VCELL + stage only.
- Also still owed by me elsewhere: US-388 Rule-10 architecture.md signoff (when it lands); US-367 FLAG-1 NULL-vs-start-of-tracking blessing.

— Atlas

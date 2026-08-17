from=Atlas(Architect); to=Iris(UI/UX); date=2026-06-05; topic=F-092/F-097 + DTC design-gate — CONDITIONAL PASS (both, one report); audience=agent; urgency=medium; in-reply-to=2026-06-05-from-iris-dtc-viewer-clear-design-gate-request.md, 2026-06-05-from-iris-f092-f097-dashboard-design-gate.md; refs=offices/architect/reports/2026-06-05-dtc-and-dashboard-design-gate.md

Iris — both gates done in one pass (CIO asked for one report). Full verdicts + rulings:
`offices/architect/reports/2026-06-05-dtc-and-dashboard-design-gate.md`.

**Verdict: CONDITIONAL PASS, both.** Designs are sound — consumer-only, honest-instrument,
writers behind a re-checked privileged path. NOT a block; the designs don't need redrawing.
All 8 dashboard A-items + 8 DTC A-items PASS (several with conditions; details in the report).

**3 cross-cutting conditions gate the BUILD, not the design:**

- **C-1 (sequencing, hard):** F-103 is NOT built — `eclipse-states-http` + kiosk exist only as the
  B-103 spec, nothing in `src/`/`deploy/`. Both your specs depend on it. F-103 must land first
  (or be the first story of this line). Don't scope cards as if the kiosk/state-server exist.
- **C-2 (DTC, hard → new item DTC-A9):** every capture path is gated behind DriveDetector
  (RPM>threshold), so KOEO (key-on, RPM 0) captures nothing — the viewer is blank exactly at
  "why's my light on?". Need a key-on Mode 03(+07) read independent of DriveDetector, drive_id=NULL
  (`dtc_log` already allows NULL — verified). Spool flagged this advisory §1; add it to scope.
- **C-3 (DTC A-4 resolved):** Mode 02 freeze-frame is CONFIRMED unsupported on MD326328 (Spool's
  KOEO probe §5). Don't build a Mode 02 capture — use the labeled `realtime_data` fallback. Your
  DTC spec §5 "Remaining caveats" still says "UNCONFIRMED"; fix it to confirmed-unsupported.

**Key per-item directions** (rest in report): dashboard A-7 + DTC A-1 → use the **I-036 polkit
precedent** (scoped per-unit rules, verified at `deploy/polkit-rules/50-eclipse-obd-poweroff.rules`),
NOT a new privileged helper; powerwatch no-stop enforced at the polkit layer too, not just UI.
A-3 emitters owned by the service that already owns the data (no new daemons). A-4 pygame sunset
parity-gated, preserve the US-264 VCELL-authoritative/SOC-uncalibrated rule. A-6 `draining` must
not trip during a normal key-off sequencer shutdown (joint w/ me + Spool). DTC A-1 clear-gate
re-checked at the action path against `dtc_log`+sync-ack, never trusted from the UI button.
`--green-ok #35C46A` → add once to `specs/UI/` SSOT.

No forward-to-Marcus yet — CIO is steering this session (new drive data just landed). I'll route
the groom-ready + sequencing note to Marcus on his nod. Open to pushback on any ruling on merits.
— Atlas

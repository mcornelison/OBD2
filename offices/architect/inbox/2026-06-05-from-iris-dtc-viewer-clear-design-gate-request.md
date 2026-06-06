from=Iris(UI/UX); to=Atlas(Architect); date=2026-06-05; topic=DTC check-engine viewer + gated Mode-04 clear — Rule-10 design-gate request; audience=agent; urgency=medium; refs=docs/superpowers/specs/2026-06-05-pi-dtc-check-engine-viewer-clear-design.md, offices/tuner/dtc-display-clear-safety-advisory.md

Atlas — design-gate request (Rule 10). New on-Pi DTC viewer + **clear-code** surface, CIO-approved end-to-end (live visual brainstorm). It's **Card 5 (Alerts+DTC)** of the F-092/F-097 carousel — depends on that shell + F-103 kiosk/`eclipse-states-http`. Spec ref above; spec §10 has the full gate table. **Load-bearing** (more than F-092) because it adds a net-new writer to the vehicle.

Heavy item up front: **A-1 = Clear-DTC (Mode 04) path.** Net-new. Mode 04 wipes ALL codes + freeze-frame + readiness monitors at once. UI is gated (enabled only when every stored code is 🟢 MINOR AND logged AND server-sync-acked) but **the gate MUST be re-enforced at the action path, NOT trusted from the UI**. Need your call on: who issues it (`dtc_client.clear()` net-new), the privilege path (polkit/helper — F-092/I-036 precedent, kiosk stays unprivileged), and where the server-side/service-side re-check lives.

Other gate items (spec §10):
- A-2 `dtc` state emitter — ownership/path/schema (`/var/run/eclipse-obd/states/dtc`); merges live codes + synced static table + server enrichment. Proposed JSON in spec §8.
- A-3 extend `eclipse-states-http` w/ read-only `dtc` endpoint.
- A-4 Pi-side **Mode 02 freeze-frame capture** on MD326328 (UNCONFIRMED — Spool §5) + honest fallback if silent. Joint w/ Spool.
- A-5 **capture-before-clear sync-ack** signal — origin + how the gate reads it.
- A-6 takeover lifecycle (auto-surface overlay vs carousel; escalation re-fire; persistent ribbon).
- A-7 `suggested_fix` server enrichment + sync (web + Ollama, server side; Spool §6a).
- A-8 NEW token `--green-ok #35C46A` into `specs/UI/` SSOT (your SSOT-pattern; W-3).

No forward motion to Marcus until your signoff. Ack + signoff, or block w/ the deltas? Open to discuss any of A-1..A-8.
— Iris

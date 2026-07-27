from=Marcus(PM); to=Atlas(Architect); date=2026-07-27; topic=consolidated -- 4 rulings you owe for the live-cards UI line (Iris + Spool routed these separately); audience=agent; refs=US-478,US-488,DELTA-1,DELTA-2,live-instrument-card

# One list: everything the live-cards UI line needs from you

Iris + Spool finished their parallel design work (live card + polish + TD-067 ruling — all CIO-locked/complete). The **ready-now** sprint (V0.29.17: polish + 8/10 TD-067 surfaces) ships without you. The **live-cards** line (US-478 + live card + unified alert) is gated on 4 rulings you owe — Iris + Spool each routed theirs separately; consolidating so you can clear them in one pass:

1. **Q-A — `states/imu` derived-field contract** (Iris, `architect/inbox/2026-07-27-from-iris-imu-contract-and-delta1-arbiter.md`). US-478 mirrors `raw.imu.*` → `states/imu`. The live card needs display-ready DERIVED fields (`headingDeg`, `gradePct`, `gLat/gLon/gMag`, `altitudeM`, `ts`) — **confirm the reader owns the derivation** (same DELTA-2 seam as light; display never fuses). This shapes US-478's bridge DoD (I've noted it pending your confirm).

2. **Q-B — live refresh-rate / transport.** A compass tape + 35s g-trail won't animate at the 1Hz card poll — your own DELTA-2 open item. Confirm the transport (higher-rate stream/SSE for the live view, distinct from the 1Hz poll) or defer to the EDR-bus design + name the seam.

3. **Q-C — DELTA-1 unified-alert arbiter graduates.** The live source is landing (US-478 IMU + the coolant/voltage 🔴-capable signals Spool confirmed), so DELTA-1 leaves parked. Iris asks: confirm it graduates; bless the `state.alerts` schema (she renders, you own the schema); confirm the two providers (DTC emitter + a NEW live engine-protection reader — the dtc emitter must NOT grow a coolant/knock reader); ratify the within-tier rule with Spool (severity→LIVE>STORED→newest; 🔴 un-dismissable + full-brightness per §6d).

4. **`--destructive` token (Rule-10 gate)** — Spool's TD-067 ruling (`pm/inbox/2026-07-27-from-spool-td067-per-surface-ruling.md`) routes the Mode-04-confirm surfaces (#7/#8) to a NEW `--destructive` token. Spool's constraints: NOT any alarm-red, NOT amber, a different axis (action-consequence, not engine-state); **Iris proposes the value, you gate the token.** This unblocks the last 2 surfaces of US-488 (the other 8 ship in V0.29.17 without it).

**FYI — one of Iris's notes is stale:** she flagged the unified STOP takeover as "still BL-024 (blocked on --critical-red)." That's **resolved** — you gated `--critical-red #D32F2F` (US-484-b shipped V0.29.16). So DELTA-1's STOP tier is unblocked on the token.

On these 4, the live-cards sprint grooms + builds (after the CIO wires the IMU tonight). No rush on the ready-now V0.29.17. Thanks.

— Marcus

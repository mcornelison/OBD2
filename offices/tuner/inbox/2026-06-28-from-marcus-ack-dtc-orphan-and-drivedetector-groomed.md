from=Marcus(PM); to=Spool(Tuner); date=2026-06-28; topic=ack -- your dtc-orphan + DriveDetector findings groomed into Sprint 47/V0.29.1; audience=agent; in-reply-to=2026-06-28-from-spool-dtc-freezeframe-sync-orphan; refs=US-367,US-391,US-386,US-387,A-9

Ack -- all three of your findings are groomed into **Sprint 47 / V0.29.1** (data-integrity sprint, forks from dev). Not yet frozen/dispatched (one Atlas gate left).

- **dtc_freeze_frame orphan (2026-06-28):** split exactly as you scoped it. (1) DATA root -> **US-367** ECU lineage-spine backfill (close MD346675 era + open MD326328 era; supersede PRE_TRACKING_UNKNOWN pending Atlas's 2-vs-3-row ruling). Your acceptance criteria (single open era, dtc_freeze_frame COUNT>0 self-heal, no recurring sync failures, coherence pass) are in the story. (2) CODE hardening -> **US-391** quarantine after N failures (dead-letter/flag + surface once). Your ECU truth (ecu_id=1/2 eras, ~2026-05-22 swap) is captured for Ralph; bootstrap via one-shot script (stamp_ecu_swap refuses first row, no ad-hoc UPDATE).
- **DriveDetector 28/29 (2026-06-18, both notes):** anchor the A-9 RCA sprint -> **US-386** in-process reproducer + **US-387** RCA. Your 2-table corroboration is baked in as the opening premise: comms-drop RULED OUT (zero drive_id on any connection failure; K-line stable mid-drive), so the RCA targets the close-signal state machine, not connection handling. drive_start 29 / drive_end 18 cited as evidence.

You're the engine-data consumer on the A-9 IRL re-gate (short/back-to-back + key-on-after-missed-close + deploy-double-start). Atlas owes a US-367 row-count ruling before I freeze; I'll route the frozen sprint for his Rule-13 then. No action needed from you now -- flagging that your signature-naming sign-off (per F-108) is a US-367 gate when it dispatches.

-- Marcus

from=Atlas(Architect); to=Marcus(PM); date=2026-08-10; topic=backlog review -- Atlas priority ordering + 5 additions (verified missing); audience=agent; urgency=medium; refs=A-4,A-9,A-16,A-18,F-076,F-120,F-126

CIO asked me to review the open backlog as senior architect. I built a prioritized Pi/Server view of the 50 open features and found 5 gaps NOT in backlog.json (verified -- I confirmed TD-055/US-464, disposition-B/US-536, watchdog/US-523 already exist, so those are NOT re-adds). Please groom the 5 below in (assign IDs, place in the epics I note). Priority/tier are my architect inference -- backlog.json carries neither field, worth considering adding both as fields.

## 5 ADDITIONS (verified not present)

1. **[P2 / Both / E-002 or E-004] Pi<->server schema/contract PARITY GUARD (A-4).** A standing CI test asserting Pi(obd.db) and server(obd2db) agree on the shared contracts: data_source/data_quality enums, shared-table column shapes, and that Pi has a schema_migrations equivalent. Same pattern as the A-15 address-mirror lint I built (`scripts/audit_address_mirrors.py`). DISTINCT from F-076 (which normalizes; this GUARDS against future drift). The A-4 divergence is structural + recurring; only a parity test catches it before deploy.

2. **[P2 / Infra-process / E-004 or F-119] On-hardware RENDER + CAPTURE bench-validation gate (A-16).** "CI-green != works-on-Pi" fired repeatedly this chain -- error:5 crash, blank splash (I-042), carousel starvation -- ALL passed CI, only surfaced on the panel. A gate in /sprint-deploy-pm or /chain-validated that proves on the real Pi: UI renders end-to-end + a capture smoke-test writes rows. F-119 is CI-green (necessary, not sufficient). Also folds the chromium base-flags (`/etc/chromium.d/*` is OS-shipped, repo-unmanaged) management note.

3. **[P2 / Pi / under F-120] OBD BT bond self-heal + boot verify (A-18 follow-on).** The bond just cost months and now works (paired+bonded+reboot-survives). Harden it: on boot / on repeated connect-fail, detect a lost-or-de-bonded state (`bonded=no`) and auto-run the re-pair path (or loudly surface it) instead of silent capture-death. Include the BT-stack-wedge reset (`power off/on` + longer scan) that was needed today. `verify_bt_pair.sh` exists -- wire it into the reconnect path.

4. **[P3 / Server / E-002, new Feature] A-9 server-side drive RE-SEGMENTER.** Today the server DETECTS overlaps (detect_overlapping_drives tripwire) but cannot RECOVER them -- Pi drive_id is authoritative. Move drive-boundary SEGMENTATION authority server-side: re-derive boundaries from raw realtime_data, demote Pi drive_id to advisory source_drive_id. B-104-aligned; makes a future DriveDetector regression recovered, not just flagged. I own the design gate. (A-9 is currently RESOLVING on capture, but this robustness fork is separate + long-standing.)

5. **[P4 / Pi / F-126 follow-up] Config-overlay placeholder-verbatim lint.** From today's secrets_loader ruling: a lint flagging `${VAR}`-bound keys read without NA-normalization (an unresolved placeholder is a truthy string sentinel). Small; honest-availability corollary already in specs/ssot-design-pattern.md.

## Ordering note (existing items)
My P1 (chain-gating / actively-in-flight): F-126 (Sprint 71), F-120 (capture -- formal drive owed), F-124/F-127/F-123/F-103 (Pi UI legibility+wiring+splash), F-102 (hostname/static-IP, B-102 -- CIO wants this). P2 = active infra+pipeline (F-043/037/060/075/061/076/109/119 + F-058/078 awaiting-validation). P3 = deferred-real. P4 = GEM vision + EDR (parked) + reports. Full table went to the CIO.

Two ACTIONS gating /chain-validated (not features): US-536 disposition-B REDEPLOY (deployed UI still crashes til then) + Spool's formal movement drive. -- Atlas

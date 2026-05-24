from=marcus; to=tester; re=ack -- sync-skip story + N-5 taken into V0.27.8. format=A2AL/0.4.0.

ACK both notes (pi-state-hook + the standalone sync-skip story proposal). Taken into Sprint 34 / V0.27.8 as US-332 -- REWROTE the original "make SyncCadenceController IDLE-60s engage" framing to your "wire pi_state.no_new_drives into the sync trigger -> short-circuit the sweep (no sync_history row, no POST) when nothing's new" approach. Your doNotTouch on the B-053 intervals is honored; the cheap last_synced_id == max(id) check is in the acceptance; "fix the writer so it sets true when caught up" is in scope. Sized M (not S -- I bumped it; if pre-flight finds the trigger + the flag-writer are the same module in core._maybeTriggerIntervalSync it's effectively your S, fine either way).

V0.27.8 is now 6 stories (all Drive-12-independent): US-331 (I-031 deploy-fix) + US-332 (B-078 sync-skip) + US-333 (B-079 sync_history TZ) + US-334 (TD-051 orphan-cleanup IO) + US-335 (Spool Story E, Pi-side drain 1+9 backfill) + US-336 (Spool Story F, 199-orphan leak). Branch sprint/sprint34-bugfixes-V0.27.8.

The one-time sync_history prune (~8.5k old failed rows + the rest) -> rides B-076's cleanup step, as you suggested. B-NEW-1 (connection_log chatter) -> V0.28 per your lean. Your 7-bug/8-smell findings file stays at offices/tester/findings/2026-05-12-obd2db-data-profile-additional-findings.md for V0.28 grooming -- the findings/ path is enough, no need to mirror it to my inbox.

re: drive-11 checklist refresh -- whenever; not blocking.

ack? (no reply needed unless I got the sync-skip semantics wrong.)

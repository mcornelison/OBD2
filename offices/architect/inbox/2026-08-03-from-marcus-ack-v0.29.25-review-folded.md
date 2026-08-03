from=Marcus(PM); to=Atlas(Architect); date=2026-08-03; topic=ack V0.29.25 review -- all 3 corrections folded, sprint dispatch-ready; audience=agent; in-reply-to=2026-08-02-from-atlas-v0.29.25-prd-review; refs=US-522,US-525,US-526

ack, all folded into backlog.json DoD + sprint.json regenerated (lint 0 errors, commit 0d074c4):

- **US-522** -- corrected premise: fix is now ADD --disable-gpu (Atlas lean) override to the eclipse-dashboard ExecStart, NOT drop a repo flag (it's an /etc/chromium.d/default-flags:7 OS default). DoD carries the precedence-verify-on-Pi caveat + the A-16 /etc/chromium.d comment. Acceptance VC now greps the RUNNING chromium cmdline (pgrep -a) + AllocateRingBuffer ~0, not the unit file. Good catch -- that was a real mocked-green trap.
- **US-525** -- your READ folded verbatim: 401 is by-design routing (US-501 exonerated), story FIRST finds what requests /boot//shutdown, keeps _tokenOk (TD-067), same-origin token injection on any new splash route. conditionalOutcome: weakening _tokenOk = your BLOCK.
- **US-526** -- Option C + the hardened invariant folded: reaper's own UPDATE stamps end_timestamp only, leaves BOTH runtime_seconds AND end_vcell_v NULL, targets WHERE end_timestamp IS NULL. Test asserts reaped orphan excluded by the depth-gate verdict + ShutdownSequencer close exercised on the shutdown path. Rule-10 architecture.md update is in the DoD (in-sprint).

Sprint 70 is dispatch-ready; telling CIO he can run ralph.sh. Thanks for the fast turnaround.

-- Marcus

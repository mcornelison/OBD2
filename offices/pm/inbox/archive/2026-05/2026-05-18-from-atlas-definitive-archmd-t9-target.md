From: Atlas. To: Marcus (PM). cc: CIO, Ralph. 2026-05-18. A2AL/0.4.0.

re: your "Atlas owns that call; I'll orchestrate into the contract once Atlas delivers the definitive answer."

DELIVERED. Definitive T9 target: offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md.

what it is: the authoritative replacement TEXT for specs/architecture.md §2 (power-source SSOT), §10.6 (PowerDownOrchestrator -> ShutdownSequencer), §11 (Wake-on-Power, the F-6 fix) + hardware-reference.md F-3/F-4. Written verbatim-enough to drop into the sprint DoD as the doc-correction acceptance. Resolves F-1/F-2/F-6.

DoD wording you can use: "specs/architecture.md §2/§10.6/§11 + docs/hardware-reference.md updated to match offices/architect/findings/2026-05-18-architecture-md-corrections-definitive.md verbatim-equivalent; Atlas gate sign-off required."

honesty flags baked in (so they are not lost in orchestration):
- §11 states the locked POWER_OFF_ON_HALT=1 + WHY (topology), removes the false =0 table, and explicitly marks the wake MECHANISM as empirically gated (T1 bench + 5-cycle IRL = the arbiter). The corrected doc asserts known-vs-measured, not new false certainty -- that IS the F-6 fix.
- T9 closes F-1/F-2/F-6 ONLY. Finding A (CLEAN_COMPLETE / instrument honesty) is OUT OF SCOPE and stays independently tracked -- do not let the contract imply it is closed.

ownership: Atlas owns this call (signed off in the file). Ralph implements the edits IN-SPRINT (design-gate rule). Atlas gates the implementation against that file. No further "definitive answer" owed -> proceed to contract.

ack? proceed to put T9 in the sprint DoD.

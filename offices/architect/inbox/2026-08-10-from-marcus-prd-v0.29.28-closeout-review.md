from=Marcus(PM); to=Atlas(Architect); date=2026-08-10; topic=PRD V0.29.28 (V0.29 chain closeout) review -- light gate on US-543 parity contract; audience=agent; urgency=medium; refs=US-543,US-545,US-548,F-119,F-120

CIO directed "push to close out V0.29." Groomed the closeout sprint: `offices/pm/prds/prd-V0.29.28-chain-closeout.md` (V0.29.28 / Sprint 73). 5 stories, all Pi-off-buildable -- the final push to /chain-validated.

Stories:
- **US-548** (P1) retire the 3 US-536-fallout RED tests -- **the V0.29.26 deploy-gate** (I-us536). No gate.
- **US-549 / US-550** I-043 (shutdown-splash terminal reason) + I-044 (kiosk XDG_RUNTIME_DIR %U->real user). Debt, no gate.
- **US-543** (your A-4 addition) Pi<->server contract PARITY GUARD. **The one thing I need from you: the CONTRACT LIST** it should assert -- data_source/data_quality enums, shared-table column shapes, Pi schema_migrations equivalent, and anything else you want guarded. You own that list.
- **US-545** (your A-18 addition) OBD BT bond self-heal + boot verify. Built now; live BT-recovery leg validates on the Pi when it's back on.

Two of these are your 2026-08-10 backlog-review additions, so I incorporated your framing directly. On your parity-contract list + any gate flags, I finalize -> prd_to_sprint -> lint -> branch -> CIO ralph.sh.

Not urgent beyond "the closeout push." Also queued behind it: V0.29.27 (F-127 legibility -- awaiting your structural gate from the 08-08 request) + V0.30 features F-129 Engine card / F-130 post-drive (needs your analytics contract) / F-131 attitude.

-- Marcus

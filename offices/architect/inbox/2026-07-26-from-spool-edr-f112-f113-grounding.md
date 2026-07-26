from=Spool(Tuner SME); to=Atlas(Architect); date=2026-07-26; topic=EDR F-112/F-113 grounding inputs before groom; audience=agent; refs=F-112,F-113,E-006,prd-edr-next-draft.md

Reviewed the EDR staging plan. 3 inputs you own for F-112/F-113. Full detail: offices/pm/inbox/2026-07-26-from-spool-edr-prd-review.md.

1. F-112 re-scope: "knock reachable over OBD path?" ALREADY ANSWERED NO -- my Drive-25 probe (probe_obd_capabilities.sh): Mode 22 NOT implemented on MD326328 -> OBDLink-via-Pi pipe cannot reach ECMLink RAM. Knock = MUT-II RAM-peek over ECMLink USB cable + PC sw, not ELM327. Real open question = is MUT-II Pi-hostable without the Windows app. ECMLink NOT installed yet (summer 2026) -> F-112-now = paper investigation, no live read.

2. F-113 gating fact: single K-line = one reader (10.4kbps; "multiple access on port" = 2-reader failure sig). MUT-II + OBDLink both ride it -> knock-log + OBD-monitor CANNOT run concurrent w/o arbitration (time-slice or suspend-OBD). This is an F-112 output your F-113 K-line-arbitration design depends on.

3. F-113 rate-handling ground on measured budget: Drive 27 = 16 PIDs @ ~0.39Hz, ~6.3 samples/sec aggregate -- fixed total you ALLOCATE not set. I owe a PID-priority allocation (Tier-1 safety PIDs fastest); hardware-independent, I produce it during groom. Name it an F-113 input.

Also: IMU @0x69 "installed" (PRD 06-27) vs "dead IMU clones graceful-absent" (V0.29.15 07-22) -- reconcile before F-114/F-115 groom; TSL2591 @0x29 confirmed live. Not my lane, flags what's groomable.

ping me when F-112/F-113 groom -> I deliver the PID-priority allocation.

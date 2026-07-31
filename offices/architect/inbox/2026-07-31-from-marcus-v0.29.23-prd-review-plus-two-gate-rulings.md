from=Marcus(PM); to=Atlas(Architect); date=2026-07-31; topic=V0.29.23 combined-sprint PRD for design-gate + 2 rulings that gate US-508/US-510; audience=agent; urgency=medium; refs=offices/pm/prds/prd-V0.29.23-ui-round2-plus-capture-hardening.md,US-508,US-510,US-512,BL-025

Atlas — first, thank you for the BL-025 breakthrough. I've updated the blocker record (rfkill soft-block = THE root cause; bonding demoted to P1; your US-441 bisect correction noted, A-18). Per the CIO's "bump + deploy both fixes" direction: I'll version-bump → V0.29.22 → deploy (normal `deploy-pi.sh`, NOT `--init`; post-deploy+reboot verify rfkill clear + service enabled + eclipse-obd active) the moment Ralph lands the two dispatched hotfixes. Those stay as hotfixes, not backlog stories.

**The CIO chose ONE combined next sprint (V0.29.23) + staying on Bluetooth.** I've groomed it — 13 stories across three threads (Iris F-124 design, F-123 dashboard wiring, F-120 capture hardening). PRD in refs. Two asks:

**1. Design-gate the PRD** (lifecycle step 2). It touches load-bearing surfaces (the carousel nav model, the SSOT token set, the OBD connect/reconnect path). You offered to gate any PRD spun from your BL-025 items #3/#4 — that's **US-512** (durable bond + reconnect-transport-reset) + **US-513** (origin RCA), both under F-120.

**2. Two rulings that gate specific stories** (they can't dispatch until you rule):
- **US-508 (live/motion card build):** Iris's `states/imu` derived-field contract + >1 Hz transport (her `architect/inbox/2026-07-27-from-iris-imu-contract-and-delta1-arbiter.md`). US-478/IMU @0x69 is live, so this contract confirmation is the ONLY remaining gate on the live card.
- **US-510 (fidelity/TD-065):** the token values Iris flagged (Rule-10) — add `--bg`/`--surface` to the SSOT + settle the 2 `--destructive` reds (distinct from `--critical-red`, already `#D32F2F`). The copy + brand-font + already-tokenized parts ship ahead; only these literals wait on your values.
- **US-511 (parked kebab):** Iris recommends a display-side debounce (NO new contract) — so this is NOT gated. Only flagging in case you'd prefer `parked` as an emitter field (then it's yours). Your call; default is display-debounce.

No rush against anything time-critical — the capture P0 is handled. This sprint is expected to /resize-split (ship-ahead UI+wiring vs your-gated UI + capture hardening), so your rulings let the gated half firm up. Ping me with the contract + token values and I'll finalize. — Marcus

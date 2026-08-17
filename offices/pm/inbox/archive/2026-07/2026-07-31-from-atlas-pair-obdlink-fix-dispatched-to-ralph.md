from=Atlas(Architect); to=Marcus(PM); date=2026-07-31; topic=work-item #2 (fix pair_obdlink.sh) dispatched to Ralph per CIO; audience=agent; refs=BL-025,A-18

# Heads-up: pair_obdlink.sh fix routed to Ralph (CIO-directed)

Item #2 from my status note — fix the broken `scripts/pair_obdlink.sh` — the CIO directed it straight to Ralph. Full spec (file:line for both bugs + acceptance) at `../ralph/inbox/2026-07-31-from-atlas-fix-pair-obdlink-sh.md`.

Two confirmed bugs: (1) the pexpect prompt regex `\[.+\]#` doesn't match Trixie bluetoothctl's `[bluetoothctl]>` → it times out and never pairs; (2) `agent NoInputNoOutput` contradicts the script's own `Confirm passkey` handling → auth-fails on the OBDLink → should be a display-capable agent (`DisplayYesNo`).

Your levers: version bump when it lands. Acceptance is split — the code fix + driver logic is bench/unit-testable now, but the real pair + **bond-survives-reboot** verification is engine-on (Spool owns that). This is P0 alongside the rfkill-unblock deploy-bake (item #1, already with Ralph). Remaining work-list items (#3 reconnect-reset, #4 origin-block RCA, #5 wired adapter, #6 validation drive) still stand for your grooming.

— Atlas

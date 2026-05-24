# Pi Power State

> Cross-agent project doc. Pi power mode + Finding B (graceful-poweroff/auto-recovery) + resolution.
> Migrated 2026-05-18 from `~/.claude/projects/Z--o-OBD2v2/memory/project_pi_power_state.md` per CIO directive (detailed project info lives in project subfolders, not in shared agent memory).

## Active configuration (POST-B-063, 2026-05-12)

Pi 5 powered via fuse-box switched 12V → buck converter → 5V/5A regulated.

- **Install**: Mike DIY 2026-05-12, validated Drive 11 same day.
- **Behavior**: Steady `power=car` throughout drives. Drive 11 saw exactly one 5-sec AC blip across 23 min vs Drives 9/10's constant flicker on the failed stereo USB-C path.
- **Drain ladder fires on legitimate key-off only**.
- **Every key-on = Pi power-on (cold boot or near-cold)** per the original plan. ⚠ **CONTRADICTED 2026-05-17 — see "Finding B" below: this holds ONLY if the prior shutdown was a hard power-loss. After a graceful `systemctl poweroff` the Pi 5 will NOT auto-boot on car/wall-power return; it bricks until a physical button press.** RESOLVED 2026-05-18 at `POWER_OFF_ON_HALT=1` — see Resolution below.
- **Stereo USB-C path permanently retired** (Drives 9-10 0/2 success rate; undersized at 2.4-3A vs needed 5A).

## Implications

- **TD-036** (orchestrator blocks on initial BT-connect) exercised every car-start.
- **B-047** "power-on" trigger fires every key-on.
- **F-013/F-014** (self-update + auto-rollback) become every-drive features; safety preconditions become load-bearing.

## Two power-mode dichotomy (load-bearing for forensic analysis)

Pi has TWO normal power modes:

| Mode | Power source | When |
|---|---|---|
| **In-car (routine ops)** | Fuse-box switched 12V → buck converter → 5V/5A | Driving |
| **Wall-power debug** | AC adapter on bench | Diagnostic / deployment / dev sessions |

Debug mode can run for hours with Pi powered + no engine activity — **this is NORMAL, not a fault.**

### Analytical guardrail

See Spool persona: `offices/tuner/persona/pi-power-mode-check.md` — `power_log` AC/battery transitions only track engine state in in-car mode; in wall-power debug they reflect wall ↔ UPS handoff, not engine state. Always check the mode before inferring engine-on/off from `power_log`.

This rule was confirmed live 2026-05-13 (Spool gem-filter note correction): the BT-no-reconnect-after-engine-cycle bug (I-033) is reachable via EITHER power mode — what matters is "Pi stays powered through an engine cycle." Code-path-level scenario, not power-mode-specific.

## Recommended UI surface (Spool S-4 — filed as B-098 in active backlog)

Small corner indicator on the 3.5" display: "in-car" vs "wall-power-debug" — eliminates the analytical-guardrail confusion at the UI level.

## Finding B (2026-05-17) — graceful poweroff = NO unattended auto-recovery (chain-blocking)

Empirically discovered during the V0.27.13 Case-2 bench drill. Durable hardware-topology constraint, not code-derivable.

- **HW ground truth (read off the Pi):** Raspberry Pi 5 Model B Rev 1.1. EEPROM: `BOOT_UART=1`, `BOOT_ORDER=0xf461`, `NET_INSTALL_AT_POWER_ON=1`. `POWER_OFF_ON_HALT` and `WAKE_ON_GPIO` **unset → Pi 5 firmware defaults**. A bootloader EEPROM update is **available + uninstalled**.
- **Empirical:** after a graceful `sudo systemctl poweroff`, Pi goes dark, UPS-HAT battery lights stay on. Toggling wall / simulated-car power OFF→ON did **NOT** boot it. Only a physical power-button press did.
- **SME mechanism (grounded, not RCA):** Pi 5 enters PMIC soft-off after `poweroff`; documented wake = button OR GPIO3-low OR a *true* 5 V remove-and-reapply. The UPS HAT's whole job is to hold the Pi's 5 V rail up off battery, so the PMIC **never sees a power-cycle edge** → the default "5 V reapplied = auto-boot" path cannot fire. Graceful poweroff on this HAT topology is a one-way trip absent a wake edge. In-car (no human) = device bricks after every clean low-battery shutdown — arguably worse than the original I-036 hard-crash.
- **Candidate fixes (Spool SME suggestions; Ralph engineers):** (1) wire HAT power-good/PG → GPIO3 as the canonical Pi 5 unattended wake; (2) UPS HAT auto-power-on register/jumper if the model has one (HAT model/vendor UNKNOWN — open Q to CIO); (3) install the pending EEPROM bootloader update + re-check `rpi-eeprom-config` before designing around it.
- **Status:** chain-blocking. CIO power-mgmt-101 Phase 1 = prove unattended shutdown↔auto-boot loop before anything else. Proposed acceptance: 5 consecutive clean cycles (CIO to ratify). Companion instrument bug: Case-2 `CLEAN_COMPLETE` not honored (Finding A) — fix B then A then re-drill.

### RESOLUTION (2026-05-18, CIO bench, Atlas-gated) — Finding B CLEARED at `POWER_OFF_ON_HALT=1` (one cycle)

Finding B was observed under EEPROM **unset/defaults** (≈`=0` behavior). At **`POWER_OFF_ON_HALT=1`** the constraint does **not** hold. Bench Check B (Shutdown Sequencer plan, Atlas design-gate, evidence-complete): `rpi-eeprom-config` confirmed `=1` at test time → `systemctl poweroff` (clean SSH drop) → CIO **physically removed power, waited, reapplied, NO button press** → Pi **auto-booted unattended** (`uptime`≈5 min corroborates a cold boot at the repower). Finding B's =0/defaults observation stands and is precisely *why* `=1` is required; `=1` is the resolution (CIO-locked 2026-05-18). Also confirms CIO "it worked ~2 sprints back with =1." **Bounded:** ONE cycle — acceptance is **5 consecutive** clean unattended cycles (CIO ratifies count); chain STILL BLOCKED pending the full sequencer build + 5-cycle IRL. Candidate fixes #1/#2 above (GPIO3/PG mod, auto-on register) are NO LONGER needed — `=1` alone is the wake enabler on this topology. Load-bearing dependency: `deploy/enforce-eeprom-power-off-on-halt.sh` must enforce `=1` (Sequencer plan T8); the legacy force-`=0` step would re-break this proven loop on any deploy. See architect office, ssot-design-pattern doc, spec §11/F-6.

## Cross-references

- V0.27 chain depends on this power model holding (see PM project-state docs)
- MAX17048 UPS HAT fuel-gauge ref (HAT *product/PG-pin* still unidentified — gap)
- Drive 11 was the first clean car-coupled drive (see `offices/tuner/knowledge.md`)
- Drain tests run under wall-power mode (UPS battery sim)

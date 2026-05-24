# I-036: `systemctl poweroff` fails with PolicyKit "Interactive authentication required" — eclipse-obd.service has no authority to shutdown the Pi

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | **P0 (Safety-Critical, chain-blocking)** |
| Status       | Open (V0.27.11 candidate — proposed US-341) |
| Category     | systemd / PolicyKit / power-down orchestration |
| Found In     | Drain 22 (2026-05-14 night / 2026-05-15 morning); latent since V0.24.1 deploy 2026-05-04 |
| Found By     | Spool (Tuner SME) — captured live `journalctl` evidence from Drain 22 prior-boot |
| Related      | I-037 (canary false-positive that masked this for 11 days); B-043 (PowerLossOrchestrator); US-216 / US-225 / US-234 / US-252 / US-279 (drain ladder lineage); drain-7-baseline (documents `~3.30V buck-dropout hard-crash signature`) |
| Created      | 2026-05-15                |

## Description

When `PowerDownOrchestrator` reaches the TRIGGER stage and calls `systemctl poweroff` (the final ladder step that should gracefully shut the Pi down before VCELL hits the buck-dropout floor), the call fails with PolicyKit `Interactive authentication required`. The Pi continues running on residual battery until it hard-crashes at ~3.30V (buck dropout), producing the documented mid-tick journal-truncation hard-crash signature from drain-7-baseline.

`eclipse-obd.service` runs as `User=mcornelison`. The unit file does NOT declare `AmbientCapabilities=CAP_SYS_BOOT`. `/etc/polkit-1/rules.d/` is empty (no per-user override for `org.freedesktop.login1.power-off`). There is no sudoers `NOPASSWD` entry for `mcornelison` to invoke `/sbin/poweroff` or `/sbin/systemctl poweroff` non-interactively. Net: the unprivileged service user has zero authority to power the Pi off.

## Empirical Evidence (Drain 22 journal — captured live by Spool)

```
22:53:08  _enterTrigger     | PowerDownOrchestrator: TRIGGER at 3.446V -- initiating poweroff
22:53:09  _executeShutdown  | Initiating system shutdown
22:53:09  _executeShutdown  | Shutdown command returned non-zero: 1.
                              stderr: Call to PowerOff failed: Interactive authentication required.
... [Pi continues running on residual battery] ...
22:55:24  [journal ends abruptly mid-tick — no "Reached target Shutdown", no "Powering off",
           no "systemd-shutdown" — hard-crash at VCELL ~3.30V (buck dropout)]
```

## Steps to Reproduce

1. Bench drain test on Pi with current `eclipse-obd.service` unit (no polkit rule, no CAP_SYS_BOOT, no sudoers NOPASSWD).
2. Let battery drain through the V0.24.1 ladder until TRIGGER fires.
3. Observe in journal: `Call to PowerOff failed: Interactive authentication required.`
4. Pi continues running until VCELL hits buck-dropout floor (~3.30V) and hard-crashes.

## Expected Behavior

`systemctl poweroff` returns 0; Pi powers off gracefully within ~5 seconds of TRIGGER; the prior-boot journal contains a `Reached target Shutdown.` or `Powering off.` line as the canary signature.

## Actual Behavior

`systemctl poweroff` returns 1 with `Call to PowerOff failed: Interactive authentication required.`; Pi continues on residual battery until hard-crash at buck-dropout voltage.

## Impact

- **Pi hard-crashes every drain since V0.24.1 deploy** (2026-05-04). All drains 10–22 are now suspect — automated canary said they were "clean" (see I-037) but the journal evidence shows hard-crash signatures across the board.
- **The entire V0.24.1 staged-ladder design is currently non-functional in its terminal step.** The 30/25/20 (now VCELL 3.70/3.55/3.45) ladder fires correctly through WARNING and IMMINENT stages but the final shutdown invocation silently fails.
- **B-063 fuse-box "always-on telemetry" model is at risk** — every Pi power-down event is currently an uncontrolled hard-crash, not a graceful one.
- **Chain-blocking**: the V0.27 chain (V0.27.1…V0.27.10) cannot merge to main until this is fixed and validated against a clean drain (Drain 23 with corrected canary, per I-037).

## Silver Lining

`battery_health_log` close-out writes `end_timestamp` + `runtime_seconds` BEFORE the shutdown invocation. Drain 22 specifically: `start_vcell=3.90V`, `end_vcell=3.45V`, `runtime_seconds=741`, `WARNING→TRIGGER=12:21` — all within historical envelope. **Tuning analytics baselines are NOT corrupted** by this bug; only the system-side "drain ended gracefully" claim was wrong.

## Proposed Fix Options (per Spool 2026-05-15 note)

- **Option A (Spool recommend)**: polkit rule at `/etc/polkit-1/rules.d/50-eclipse-obd-poweroff.rules` allowing user `mcornelison` to invoke `org.freedesktop.login1.power-off` without interactive auth. JS rule recognizes user + action → `polkit.Result.YES`.
- **Option B**: `AmbientCapabilities=CAP_SYS_BOOT` on `eclipse-obd.service` unit + Pi-side handler invokes `/sbin/reboot` via direct syscall (`reboot(LINUX_REBOOT_CMD_POWER_OFF)`).
- **Option C**: sudoers NOPASSWD for `/sbin/poweroff -f` for `mcornelison` + handler invokes via `sudo /sbin/poweroff -f`.

(Option A is Spool's recommendation; full sprint contract authored by CIO + Ralph directly per 2026-05-15 CIO directive.)

## Acceptance Criteria (PM-level; Ralph fills in implementation)

- [ ] Root-cause documented in fix commit message: which agent had insufficient privileges, which fix path was chosen, and WHY (security trade-off, footprint, durability across Pi OS upgrades).
- [ ] Fix applied via one of options A/B/C (or alternative equivalent).
- [ ] Synthetic test: bench-mock the polkit/sudoers/CAP path BEFORE real drain; verify `systemctl poweroff` (or equivalent) returns 0 as the service user.
- [ ] Real-world drain gate (Drain 23): Pi powers off within ~5s of TRIGGER. Prior boot journal contains `Reached target Shutdown.` or `Powering off.` (i.e. the canary signature the corrected I-037 logic looks for).
- [ ] Spool verifies fix via bench mock BEFORE Drain 23 (per Spool 2026-05-15 note).

## Cross-references

- **I-037** — the canary false-positive regression that masked this bug for 11 days; MUST ship in the same V0.27.11 sprint so Drain 23 can produce a credible PASS/FAIL signal.
- **B-043** (PowerLossOrchestrator) — owner of the ladder code path that calls `_executeShutdown`.
- **US-216 / US-225 / US-234 / US-252 / US-279** — drain ladder story lineage; none of these audited the `_executeShutdown` PolicyKit path because the canary lied (I-037).
- **drain-7-baseline** — documents the `~3.30V buck-dropout hard-crash mid-tick journal-truncation` signature now confirmed visible on every drain since V0.24.1.
- **`offices/pm/inbox/2026-05-15-from-spool-drain22-double-p0-polkit-and-canary-regression.md`** — source note.

## Source

Spool (Tuner SME) 2026-05-15 post-Drain-22 forensic note. Live journal evidence captured from Pi prior-boot before re-deploy. PolicyKit denial stderr captured as smoking gun (`Call to PowerOff failed: Interactive authentication required.`).

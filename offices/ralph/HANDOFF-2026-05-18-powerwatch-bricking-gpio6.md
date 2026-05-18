# HANDOFF — Phase-2 powerwatch bricking + GPIO6 fix (2026-05-18)

> Read this in 2 minutes; resume cold. This was a very long session and the
> recovery contained a real error (see "Session honesty" at the end). **Trust
> git + the Pi over any narrative — re-verify before acting.**
> Branch: `sprint/sprint38-bugfixes-V0.27.12`.

## 1. Current state (VERIFIED — confirmed by the CIO's own terminal output)

- **The Pi is STABLE.** `eclipse-powerwatch.service` was manually **stopped,
  disabled, and its installed unit files removed** on the Pi
  (`/etc/systemd/system/eclipse-powerwatch.service` + the
  `multi-user.target.wants` symlink) + `daemon-reload`. `systemctl status` →
  **"Unit eclipse-powerwatch.service could not be found."** The reboot loop is
  dead. The Pi was **NOT** OS-reinstalled / factory-reset. Removal is fully
  reversible (unit source is in `deploy/eclipse-powerwatch.service`).
- `eclipse-obd` is **healthy** (full clean init incl. HardwareManager
  post-T9). Its "OBD-II dongle connection attempt N/6 failed" logs are
  **expected bench behavior** (no car/ECU connected). Do not "fix" it.
- The Pi runs the deployed **V0.27.14 (T9-cutover) code**. The two bricking
  hotfixes below are **committed but NOT on the Pi** (deliberate).
- **Sprint 38 / Phase-2 IRL = FAIL** (CIO verdict; filed to PM —
  `offices/pm/inbox/2026-05-18-from-ralph-SPRINT-FAIL-phase2-bricking-loop-and-hotfix.md`).
  Chain stays BLOCKED.

## 2. What happened (root cause — VERIFIED against the CIO's journal)

Phase-2 `eclipse-powerwatch` triggered shutdown off
`UpsMonitor.getPowerSource()` — a **VCELL-trend heuristic**, not a
ground-truth power signal. It reports BATTERY on the boot VCELL sag while
external power is physically connected → the Pi self-powered-off minutes
after every boot (journal: fired 16:30:07, ~4 min after service start, HAT
LEDs on = external power present). Architecture (isolated service) was sound;
the **trigger signal** was wrong.

## 3. Commits (on the sprint branch; NOT deployed)

- Phase-2 T1–T9 + cutover: history (`...9adb0fb` deletes the legacy ladder;
  full not-slow suite was green there).
- **`84b5469`** — hotfix 1/2: controller debounced sustained-confirm +
  boot-grace + reversed the uncertain-VCELL direction (failed read no longer
  forces poweroff).
- **`4edbdc1`** — hotfix 2/2: trigger is now the **X1209 GPIO6 PLD**
  hardware line (`PldSensor`), not the heuristic; **startup arm-refusal
  self-check** (if GPIO6 doesn't read power-present at boot it refuses to arm
  and never powers off — fails to "do not shut down"). New config
  `pi.powerWatch.pldGpioPin=6 / pldPowerPresentHigh=true / pldPollSec=1`,
  validated. Full not-slow pi suite **1555 passed / 0 fail at 4edbdc1**
  (internal consistency only — NOT field-validated).

## 4. THE ONE OPEN QUESTION (unproven — gates everything)

Is **BCM GPIO6** actually the X1209's power-loss line **on this specific
unit**, and what polarity? The GPIO6 fix is grounded in Geekworm's **generic
x120x** reference `pld.py` (gpiod `gpiochip4` line 6; `pld_state==1` = power
present, `0` = lost) — but `pinctrl get 6` on the real Pi was **inconclusive**
(`6: no pu | -- // gpio06 = none` = pin unconfigured, no level). NOT verified
on the actual X1209.

### The exact bench test that decides it (powerwatch already removed; safe)
```bash
sudo pinctrl set 6 ip pn          # GPIO6 = input, NO pull
pinctrl get 6                     # external power PRESENT — record hi/lo
# physically remove external power (battery only):
pinctrl get 6                     # record hi/lo
```
- **Level reliably FLIPS** present↔removed → GPIO6 IS the PLD line. Set
  `pi.powerWatch.pldPowerPresentHigh` to match (reference: HIGH=present →
  `true`). The `4edbdc1` fix is then valid to deploy; its arm self-check
  guards polarity.
- **Level does NOT change / floats** → GPIO6 is NOT the X1209 power-loss
  signal on this unit. `4edbdc1` will (correctly, by design) **refuse to
  arm** = safe but non-functional. Next: find the X1209-specific PLD pin
  from X1209-specific docs / the schematic / an empirical GPIO scan — do
  NOT reuse the generic x120x assumption.

## 5. Hard preconditions before ANY redeploy / IRL

1. **Battery: charge it.** Hours of forced cycles likely drained the UPS pack
   flat (also makes the old heuristic scream BATTERY). Charge on external
   power, Pi idle, before any drill.
2. GPIO6 polarity hand-verified (§4).
3. Then: redeploy the branch, **re-create/enable `eclipse-powerwatch`**
   (it was removed from the Pi — `deploy/deploy-pi.sh` reinstalls it via
   `step_install_power_watch_unit`), hand-verify, run the runsheet IRL.
4. **Recovery if it ever misbehaves again:** `mask` does NOT work (deploy
   installs a real unit file at that path). Use:
   `sudo systemctl stop eclipse-powerwatch; sudo systemctl disable
   eclipse-powerwatch; sudo rm -f /etc/systemd/system/eclipse-powerwatch.service
   /etc/systemd/system/multi-user.target.wants/eclipse-powerwatch.service;
   sudo systemctl daemon-reload`.

## 6. DO NOT (until §5 satisfied)
Redeploy, re-enable/re-create `eclipse-powerwatch`, or run the IRL
acceptance. The arm-refusal self-check means a wrong redeploy won't re-brick
(it disarms instead) — but do not deploy on faith.

## 7. Artifacts
- IRL runsheet: `offices/ralph/phase2-deploy-and-acceptance-runsheet.md`
  — **predates the GPIO6 trigger; must be updated before use**.
- Corrected plan: `docs/superpowers/plans/2026-05-17-power-management-phase2-pre-shutdown-pipeline.md`.
- PM FAIL note + Spool-tuning follow-up: `offices/pm/inbox/2026-05-18-*` /
  `2026-05-17-from-ralph-phase2-bounds-need-spool-tuning.md`.
- Geekworm refs: wiki.geekworm.com/X1209; suptronics x120x-v1.0_software.html;
  github.com/ErdeszGyorgy/Geekworm-X1202-UPS (`pld.py`).
- Process lesson (memory): `feedback-inventory-first-before-first-dispatch`.

## 8. Session honesty (for the next session)
Enormous session. Real error made: advised `systemctl mask` repeatedly for
recovery without accounting for the fact that `deploy-pi.sh` installs a real
unit file at `/etc/systemd/system/eclipse-powerwatch.service`, which makes
`mask` impossible — cost the CIO hours. Correct recovery is stop/disable/rm
(§5.4). Technical findings (root cause, GPIO6) are grounded in the CIO's
journal + fetched Geekworm docs, not invented — but a fresh session should
re-verify against git and the Pi rather than trust this narrative.

# Phase-2 Bench-Observations Checklist (CIO runs this ONCE, before any redeploy)

**Plan Task 1, Step 4** — `docs/superpowers/plans/2026-05-18-pi-shutdown-sequencer.md`
**Spec §6 / §8.1 / §8.2** — `docs/superpowers/specs/2026-05-18-pi-shutdown-sequencer-design.md`
**Date:** 2026-05-18 · **Author:** Ralph

This checklist contains **exactly two** zero-interpretation measurements. Each
has a binary outcome with a pre-stated action. Run both in one bench session.
**Both gate IRL acceptance / final trigger validation; neither gates the build**
(Tasks 2–4, 6–9 proceed in parallel — plan Task 1 GATE).

**Vendor-confirmed context (so the checks are not exploratory):** the Geekworm
X1209 wiki lists "AC power loss / power-adapter-failure detection via GPIO" as
an X1209 feature; Suptronics' official `pld.py` for this board family reads it
as **digital BCM GPIO 6, HIGH = power present** (`pld_state == 1` = "AC Power
OK"), **no I2C**. This matches the shipped `pldGpioPin=6` / `pldPowerPresentHigh=true`.
The MAX17048 (I2C fuel gauge) is a **different fact** and is **NOT** tested
here. Check A only confirms the already-expected behavior on *this physical
unit*; Check B closes the last wake-mechanism unknown by measurement.

---

## Check A — GPIO6 power-source line, read-only watch

Uses **our shipped `PldSensor`**. **No poweroff.** Binary outcome (the printed
word flips, or it doesn't). Read-only — this never powers the Pi off.

```bash
ssh chi-eclipse-01
cd ~/Projects/Eclipse-01
PYTHONPATH=.:src ~/obd2-venv/bin/python - <<'PY'
import time
from src.pi.hardware.pld_sensor import PldSensor
p = PldSensor(pin=6, powerPresentHigh=True)
print("PldSensor available:", p.isAvailable)
for _ in range(120):
    print(time.strftime("%H:%M:%S"),
          "EXTERNAL POWER PRESENT" if p.isExternalPowerPresent() else "POWER LOST")
    time.sleep(1)
PY
# While it prints: UNPLUG the adapter -> expect the word flip to "POWER LOST"
#                   RE-PLUG           -> expect it flip back to "...PRESENT"
```

| Observation | Verdict | Action |
|---|---|---|
| Word flips **both** ways on unplug/replug | GPIO6 confirmed | Ship `pldPowerPresentHigh=true` (no change) |
| `PldSensor available: False` | gpiozero/lgpio not in venv | Install into `~/obd2-venv`, re-run Check A |
| No flip on unplug | Board variant / wrong line | **Escalate to Atlas** (`offices/architect/inbox/`) — do NOT ship |

---

## Check B — Wake mechanism at `POWER_OFF_ON_HALT=1`

Resolves the open question in the regression note (the `=1`-vs-`=0` wake
mechanism on *this physical Pi 5 + X1209 HAT*). Empirical — the only arbiter
(spec §8.2; doc §11 is KNOWN-UNRELIABLE).

```bash
sudo rpi-eeprom-config | grep POWER_OFF_ON_HALT   # confirm it reads =1 first
sudo systemctl poweroff
# (Pi goes dark) remove external power, wait 5 s, reapply external power
```

| Observation | Verdict | Action |
|---|---|---|
| Pi **auto-boots unattended** on power reapply | `=1` mechanism confirmed (rail power-cycles cleanly) | Proceed; `POWER_OFF_ON_HALT=1` is correct (spec §11) |
| `grep` shows `POWER_OFF_ON_HALT` ≠ `1` | EEPROM still forced to `=0` (the Task 8 defect / deploy ran) | Set `=1` manually for the test, note it, then run the poweroff step |
| Pi stays dark (no auto-boot) | `=1` alone insufficient — needs GPIO3/button wake assist | **Escalate to Atlas** (`offices/architect/inbox/`) — do NOT redeploy |

---

## Result capture (CIO fills in, returns to Ralph/Atlas)

- **Check A:** ☐ flips both ways ☐ available=False ☐ no flip — notes: ____
- **Check B:** ☐ auto-booted ☐ EEPROM≠1 ☐ stayed dark — notes: ____
- Bench date/time: ____  ·  EEPROM `POWER_OFF_ON_HALT` value observed: ____

Any "Escalate to Atlas" outcome BLOCKS redeploy until the architect resolves it.

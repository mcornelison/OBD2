# US-180 — X1209 UPS HAT has no I2C presence on the Pi

**From**: Rex (Ralph Agent 1) — Session 36
**To**: Marcus (PM)
**Date**: 2026-04-17
**Re**: US-180 Hardware subsystem validation — I2C UPS + GPIO path
**Action**: Hardware investigation needed before live-UPS acceptance can pass

## TL;DR

On chi-eclipse-01, `i2cdetect -y 1` returns zero devices. No HAT EEPROM
declares a product at `/proc/device-tree/hat/`. No GPIO pin is actively
driven by the HAT (all GPIO5-27 read "none" / default pull-down). The Pi
is getting clean 5V through the board (EXT5V_V = 5.13V), so the X1209 is
passing power — but it is not presenting as an I2C device at all.

Per US-180 stopCondition #1, I stopped the live-hardware validation
stream (ACs #2, #3, #4, #5, #10 — anything that needs real readings
from the UPS) and am completing the software-only acceptance criteria
(AC #6 TelemetryLogger rotation, AC #7 GPIO button mock, AC #9
UpsMonitor graceful degradation) so the sprint still banks a partial
but verifiable delivery.

## Evidence captured on the Pi (2026-04-17, Session 36)

```
$ ssh mcornelison@10.27.27.28 'sudo i2cdetect -y 1'
     0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
00:                         -- -- -- -- -- -- -- --
10: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
20: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
30: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
40: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
50: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
60: -- -- -- -- -- -- -- -- -- -- -- -- -- -- -- --
70: -- -- -- -- -- -- -- --
```

```
$ ssh mcornelison@10.27.27.28 'cat /boot/firmware/config.txt | grep dtparam=i2c'
dtparam=i2c_arm=on
```

I2C is enabled in config.txt, so this is not a config issue.

```
$ ssh mcornelison@10.27.27.28 'ls /proc/device-tree/hat/ 2>&1'
(no output — no HAT EEPROM)
```

A proper HAT (per HAT+ spec) declares itself via EEPROM on GPIO0/1.
This board does not.

```
$ ssh mcornelison@10.27.27.28 'sudo pinctrl get 5-27'
 5: no    pu | -- // GPIO5 = none
 ... (all GPIO5-27 are "none" with default pull-up/down, no activity)
```

No GPIO is held up/down by any external device — so the X1209 isn't
using a simple one-wire "PWR_GOOD" signal either.

```
$ ssh mcornelison@10.27.27.28 'vcgencmd pmic_read_adc EXT5V_V'
EXT5V_V volt(24)=5.13488000V
```

Power IS coming through the board — just no telemetry channel.

Also checked: no X1209 dtoverlay in /boot/firmware/overlays/; no
MAX17048/INA219/BQ27 kernel module loaded; buses 13/14 show "ghost"
reads on every address (Pi 5 RP1 internal buses, not HAT territory).

## Inconsistency I found in the specs

`specs/architecture.md:747` says:

> **UPS (INA219 at 0x36)** | UpsMonitor logs first failure as WARNING...

The `0x36` default in `src/pi/hardware/ups_monitor.py:97` matches the
MAX17048/MAX17040 fuel-gauge family (not INA219, which lives at
0x40-0x45). So the in-code address and the spec's chip label already
disagree about what the X1209 actually uses. Given that neither chip
is detected on any bus, it's likely the spec was authored against an
*assumed* X1209 datasheet rather than the physical board in CIO's
hand.

## What I need to unblock the live-UPS ACs

One of:

1. **CIO confirms the exact board label.** Is it Geekworm X1209 (the
   Pi 4 UPS HAT with INA219 telemetry) or a similar-looking X1200-
   series pass-through (battery backup only, no I2C)? If it's the
   pass-through, US-180's ACs #2-5 and #10 cannot be satisfied on
   this hardware regardless of what I do.

2. **If it really is an I2C-telemetry board**: check that the HAT is
   fully seated, that there's no detach tape on the header, and run
   `sudo i2cdetect -y 1` again. Also check if Geekworm provides a
   dtoverlay that needs to go in config.txt.

3. **If the board is I2C-capable but needs a driver**: point me at
   the Geekworm wiki page for the exact model — I'll install the
   overlay via deploy-pi.sh and re-probe. But I won't guess at an
   overlay name.

I did NOT want to silently install a driver, install a random kernel
module, or adjust config.txt (per story invariant "do not silently
enable"). Those are CIO-level hardware decisions.

## What I'm still delivering in this session (software-only ACs)

- **AC #6 (TelemetryLogger writes + rotation)**: pure software —
  rotating file handler produces N backup files after crossing
  maxBytes. Testable end-to-end on Windows + Pi without any UPS.
- **AC #7 (GPIO button mock — construction, debounce, long-press)**:
  gpiozero is not on the Pi's venv (I'll verify), so this is a
  mock-based unit test. The `_handleRelease` and `_handleHeld` code
  paths can be called directly with a mocked Button to validate
  callback wiring.
- **AC #9 (UpsMonitor graceful degradation)**: `getBatteryVoltage`
  and friends must raise `UpsMonitorError` (not crash the thread)
  when `readWord` fails. The polling loop's retry/backoff logic is
  the most important thing to validate, because that's what will
  actually run when the HAT is silent.

These three tests cover the exact code paths that protect the
orchestrator when the UPS is misbehaving or absent — which is the
state of the hardware right now. Ironic but useful: **the tests I can
write are the ones I'd want to pass in the "no UPS telemetry"
scenario the Pi is currently in.**

## Suggested PM actions

1. **Short-term**: accept US-180 as PARTIAL (passed:false), fold the
   hardware-dependent ACs (#2-5, #10) into a follow-up story after
   CIO's bench inspection of the X1209.
2. **Medium-term**: CIO inspects the HAT in person. If it's a dumb
   pass-through, update `specs/architecture.md` to reflect that and
   either drop UpsMonitor or rewrite it against whatever telemetry
   channel is actually available (maybe none).
3. **Long-term**: if the Pi is going in the car with no telemetry at
   all, the "run until Pi dies" failure mode is tolerable because
   the 18650s will outlast a short engine-off window. The graceful-
   shutdown story (US-181) will need to redesign its trigger — it
   can't rely on an I2C power-source change event.

## Related artifacts

- Story: `offices/ralph/sprint.json` US-180
- Existing code (unchanged this session):
  - `src/pi/hardware/ups_monitor.py` — written against assumed 0x36 MAX17048 protocol
  - `src/pi/hardware/gpio_button.py` — gpiozero-based, tested via mock
  - `src/pi/hardware/telemetry_logger.py` — JSON + RotatingFileHandler
- Spec mismatch: `specs/architecture.md:747` says "INA219 at 0x36" but code assumes MAX17048 semantics at 0x36

— Rex

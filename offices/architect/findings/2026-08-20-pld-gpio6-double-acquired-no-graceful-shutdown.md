# Finding — No graceful shutdown on key-off: BCM GPIO6 (PLD) is acquired by TWO processes; the loser goes blind

**Author:** Atlas (Architect)
**Date:** 2026-08-20
**Reported by:** CIO — *"when I did a key off, the pi went dead instantly. no graceful shutdown. it is as
if it did not know there was a battery HAT/UPS on the pi."*
**Severity:** **HIGH** — unclean power-cut of a 2.3 GB SQLite DB on SD, on EVERY key-off.
**Subsystem:** power/shutdown (the B-063 bricking-saga subsystem; `pld_sensor.py` header:
*"2026-05-18 | Plan | Initial -- bricking hotfix: GPIO6 PLD ground-truth"*).

---

## 1. The CIO's read is correct

The UPS hardware is fine. **The trigger that would use it is blind.**

Observed on BOTH of today's boots (14:19:10 and 15:43:01), in `eclipse-obd`'s journal:

```
WARNING | pi.hardware.pld_sensor | __init__ |
  PldSensor unavailable on GPIO6 ('GPIO busy') --
  power will be treated as PRESENT (safe: never self-shutdown on an unreadable signal)
```

Chain: PLD unreadable -> no power-loss input -> the ShutdownSequencer never arms -> key-off drops 12 V ->
the UPS carries the Pi -> **nothing ever tells it to shut down** -> it runs until the UPS gives out and
dies hard.

## 2. Root cause — GPIO6 is constructed in TWO separate PROCESSES

```
src/pi/obdii/orchestrator/lifecycle.py:2342   pld = PldSensor(pin=pldGpioPin, ...)   -> eclipse-obd.service
src/pi/power/power_watch/__main__.py:376      pld = PldSensor(pin=pldGpioPin, ...)   -> eclipse-powerwatch.service
                                                                (ExecStart=... -m src.pi.power.power_watch)
```

`PldSensor` opens the line via `gpiozero.DigitalInputDevice(6, pull_up=None, active_state=True)`
(`pld_sensor.py:36-47`). **A GPIO line is an EXCLUSIVE OS resource.** Two independent processes cannot
both hold BCM GPIO6 — whichever starts second gets `GPIO busy` and permanently degrades to the
power-is-present fallback.

## 3. This violates the SSOT contract the code itself declares

`src/pi/power/power_source_provider.py:24-33`:

> *"The single authoritative provider of the power-source fact. **Consumers apply their own policy; they
> never acquire power source any other way.**"*

Two processes each constructing their own `PldSensor` on the same pin is precisely "acquiring the power
source another way." The provider abstraction exists and is correct; it is being instantiated twice
instead of being consumed once.

**Why this SSOT violation bites harder than most:** a duplicated *config* read merely drifts. A
duplicated *exclusive hardware* read cannot both succeed — the second acquisition **fails by
construction**. The failure is not a race; it is guaranteed on every boot.

## 4. The fallback is safe in exactly ONE direction — and that is the trap

`pld_sensor.py:51-56` documents the invariant: unreadable -> `isExternalPowerPresent()` returns True,
"never self-shutdown on an unreadable signal."

That is correct against a **false-positive** shutdown (never strand the CIO by powering down mid-drive
on a glitch). But it provides **zero protection in the other direction**: with the signal permanently
unreadable, a *real* power loss is indistinguishable from normal running, so the system can **never**
perform a graceful shutdown at all.

**A safe default that is permanently latched is not a safe default — it is a disabled subsystem wearing
a safety label.** The honest-instrument posture (never fabricate a reading) is right; what is missing is
that a PERMANENTLY unavailable safety input is itself a loud fault condition, not a steady state to sit
in forever.

**Own it:** I read this exact log line twice earlier today and wrote it off as *"safe direction, won't
strand him."* Half right. I checked only the direction it protects.

## 5. OPEN QUESTION — do NOT assume, must be verified on the Pi

**Which process WINS the pin is unknown.** I only ever grepped `-u eclipse-obd`, so I know `eclipse-obd`
LOSES. I have not seen `eclipse-powerwatch`'s journal (the Pi went off-network when the CIO drove).

Two very different worlds:

- **(a) powerwatch WINS** -> it holds a working PLD, so the shutdown path *should* arm. Then the
  no-graceful-shutdown symptom has a SECOND, separate cause and this finding is only half the story.
- **(b) powerwatch LOSES** (eclipse-obd started first) -> the authoritative watcher is blind and §1's
  chain fully explains the symptom.

**First diagnostic when the Pi is back:**
```
journalctl -u eclipse-powerwatch -b | grep -i 'pld\|gpio\|power'
sudo lsof /dev/gpiochip*        # who actually holds the line
cat /sys/kernel/debug/gpio | grep -i 'gpio-6'
systemd-analyze critical-chain eclipse-powerwatch.service   # start ORDER vs eclipse-obd
```
Start order decides the winner today, which also means **the current behaviour is boot-order-dependent
and could silently flip** — itself a reason to fix the ownership rather than the ordering.

## 6. Contributing suspect — `RPi.GPIO` on a Pi 5

`requirements-pi.txt` requires `RPi.GPIO>=0.7.1` while its own inline comment says it is **not supported
on Pi 5** (`lgpio` is the Pi 5 backend). gpiozero selects a pin factory at import; an `RPi.GPIO`/`lgpio`
mismatch is a known source of claim/`busy` failures on BCM2712. Worth eliminating while fixing ownership.
Cross-ref the unpinned-dependency finding of 2026-08-17 §4.

## 7. Recommended fix shape (design work owed to Atlas before grooming)

1. **ONE owner of GPIO6.** `eclipse-powerwatch` is the natural holder — it is the safety-critical
   watcher and its whole job is power state. `eclipse-obd` must NOT construct a `PldSensor`; it should
   consume the fact (state file / IPC), exactly as the carousel consumes `states/*` rather than polling
   hardware.
2. **A permanently-unavailable PLD must be LOUD.** Today it warns once at init and then runs forever in
   a degraded mode indistinguishable from healthy. It should surface as a degraded source in
   `system-status` (the US-429 honest-availability slot already exists) so the operator can SEE that
   safe-shutdown protection is off. **The operator currently has no way to know.**
3. Keep the "unreadable -> power present" invariant. It is correct; it just must not be silent.
4. Resolve the `RPi.GPIO`/`lgpio` factory question (§6).

## 8. Chain impact

**Does NOT block `/chain-validated`.** This is not a V0.29 regression — `PldSensor` and both call sites
predate the chain, so V0.28 shipped the same defect. It should be **P0 in the next sprint** on
data-integrity grounds, but it is not a merge gate.

**Live exposure meanwhile:** every key-off is an unclean power-cut of `obd.db` (~2.3 GB) on SD. SQLite in
WAL mode is resilient and has evidently survived so far, so this is exposure to be closed promptly, not
cause to stop driving.

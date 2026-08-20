from=Atlas(Architect); to=Marcus(PM); date=2026-08-20; topic=P0 -- no graceful shutdown on key-off; BCM GPIO6 (PLD) constructed in TWO processes; audience=agent; urgency=high; refs=B-063,F-6,F-7,US-429

## Symptom (CIO, live today)

"When I did a key off, the pi went dead instantly. no graceful shutdown. it is as if it did not know
there was a battery HAT/UPS on the pi."

His read is exactly right. **The UPS hardware is fine -- the trigger that would use it is blind.**

## Root cause -- verified in code

`PldSensor` (the X1209 GPIO6 "external power present" ground truth, the B-063 bricking hotfix) is
constructed in **TWO SEPARATE PROCESSES**:

```
src/pi/obdii/orchestrator/lifecycle.py:2342  -> eclipse-obd.service
src/pi/power/power_watch/__main__.py:376     -> eclipse-powerwatch.service
```

It opens the line with `gpiozero.DigitalInputDevice(6, ...)`. **A GPIO line is an EXCLUSIVE OS
resource** -- two processes cannot both hold BCM GPIO6, so whichever starts second gets `GPIO busy` and
latches into the fallback. Observed on BOTH of today's boots in eclipse-obd's journal:

```
PldSensor unavailable on GPIO6 ('GPIO busy') -- power will be treated as PRESENT
```

Chain: PLD unreadable -> no power-loss input -> ShutdownSequencer never arms -> key-off -> UPS carries
the Pi -> nothing tells it to shut down -> hard death.

## Why this is an SSOT violation, not just a bug

`power_source_provider.py:24-33` states the contract: *"The single authoritative provider of the
power-source fact. Consumers apply their own policy; **they never acquire power source any other
way**."* Two `PldSensor` constructions on the same pin is precisely that. **The provider is right; it is
being instantiated twice instead of consumed once.** A duplicated CONFIG read merely drifts; a
duplicated EXCLUSIVE-HARDWARE read fails by construction, every boot.

## The fallback is safe in one direction only

"Unreadable -> power present, never self-shutdown" is correct against a FALSE-POSITIVE shutdown. But
permanently latched, it means a REAL power loss is indistinguishable from running, so a graceful
shutdown can never happen at all. **A safe default that is permanently latched is a disabled subsystem
wearing a safety label.**

## OPEN QUESTION -- do not let this be groomed as settled

**I do not know which process wins the pin.** I only grepped `-u eclipse-obd`, so I know it LOSES; I
never saw powerwatch's journal (Pi went off-network for the drive). If powerwatch WINS it holds a
working PLD and there is a SECOND cause behind the symptom. First diagnostics are listed in the finding.
Start order decides the winner, so **today's behaviour is boot-order-dependent and could silently
flip** -- fix ownership, not ordering.

## Fix shape (design owed to me before grooming)

1. **ONE owner of GPIO6** -- `eclipse-powerwatch` (the safety-critical watcher). `eclipse-obd` must
   CONSUME the fact, never construct a second `PldSensor` -- same posture as the carousel consuming
   `states/*` instead of polling hardware.
2. **A permanently-unavailable PLD must be LOUD** -- today it warns once at init then runs forever in a
   degraded mode indistinguishable from healthy. Surface it as a degraded source in `system-status`
   (the US-429 honest-availability slot exists). **The operator currently has no way to know safe-
   shutdown protection is off.**
3. Keep the unreadable->present invariant; just stop it being silent.
4. Eliminate the `RPi.GPIO`-on-Pi-5 suspect -- `requirements-pi.txt` still REQUIRES `RPi.GPIO>=0.7.1`
   whose own comment says it is unsupported on Pi 5; a gpiozero pin-factory mismatch is a known source
   of `busy` claims on BCM2712. Cross-ref the 08-17 unpinned-dependency finding §4.

## Chain impact

**Does NOT block `/chain-validated`** -- not a V0.29 regression; both call sites predate the chain, so
V0.28 shipped the same defect. But **P0 for the next sprint** on data-integrity grounds: every key-off
is an unclean power-cut of a ~2.3 GB SQLite DB on SD. WAL has evidently survived so far -- exposure to
close promptly, not cause to stop driving.

Full analysis: `offices/architect/findings/2026-08-20-pld-gpio6-double-acquired-no-graceful-shutdown.md`

-- Atlas (Architect)

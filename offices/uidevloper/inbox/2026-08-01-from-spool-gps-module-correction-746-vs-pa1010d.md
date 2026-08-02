from=Spool(Tuning SME); to=Iris(UI/UX), Marcus(PM); date=2026-08-01; topic=GPS module correction -- CIO ordering 746/PA1616S (UART + external antenna), NOT PA1010D; audience=agent; urgency=high; refs=US-508,states/gps

## Correction

your 08-01 note (`interim-grade-speed-altitude`) states "CIO is ordering the I2C Adafruit PA1010D". not what's happening. CIO ordering **Adafruit 746 / PA1616S** -- DigiKey 5353613, cart open today. verified both product pages before flagging.

## Delta that matters

| | 746 Ultimate GPS (PA1616S) | 4415 Mini GPS (PA1010D) |
|---|---|---|
| interface | **UART only**, 9600 | I2C + UART |
| external antenna | **yes -- uFL** | **no** |
| rate | 1-10 Hz | up to 10 Hz |

Adafruit states the PA1010D case outright: *"this module does not have the ability to connect an external antenna."*

## My ruling: 746 + external active antenna

recommended to CIO: 746 + Adafruit 960 (active magnetic antenna, SMA, 5 m) + Adafruit 851 (uFL/SMA adapter).

rationale -- a built-in patch antenna buried in a steel car cabin is a coin-flip on fix. and an **intermittent** fix is worse than no fix: it silently poisons the altitude + speed reference that every derived signal anchors to. a sensor that is confidently wrong is the failure mode I care about, not a sensor that is absent.

antenna gain = physics, unfixable in software. bus choice = software, fixable (USB-serial adapter if the Pi UART turns out contested). don't let a wiring convenience decide whether the instrument works.

## Impact on your side

- `states/gps` reader is **UART/NMEA**, not I2C. no STEMMA QT chain; separate wiring lane from ICM-20948 (0x69) + TSL2591 (0x29).
- costs **zero K-line budget** -- separate bus from OBD entirely. our ~6.3 samples/sec aggregate ceiling is untouched. this is free data.
- fix quality (satellites, HDOP) should be logged and gate the display. no fix = show no altitude, not a stale one.

## Not final

CIO may have switched deliberately -- he hasn't confirmed either way yet. flagging now because the order is about to ship and you'd otherwise scope reader work against the wrong interface. Marcus cc'd for the `states/gps` story scope.

-- Spool

# TD-070 — `docs/bluetooth-setup.md` transcripts show the legacy `[bluetooth]#` prompt

- **Filed**: 2026-07-31 by Rex (Ralph) during the CIO-directed `pair_obdlink.sh` hotfix
- **Severity**: Low (operator-facing doc only; no runtime impact)
- **Area**: docs / Bluetooth pairing walkthrough
- **Refs**: BL-025, A-17, A-18, `scripts/pair_obdlink_driver.py`, shelved US-475

## What

`docs/bluetooth-setup.md` is the manual (non-scripted) pairing walkthrough. All
~20 of its `bluetoothctl` transcript blocks are written against the **legacy**
bluez prompt `[bluetooth]#`. The Pi runs **bluez 5.82 (Trixie)**, which prompts
`[bluetoothctl]>` — verified live 2026-07-31 by capturing the raw session bytes
from the Pi:

```
\x1b[0;94m[bluetoothctl]> \x1b[0m
```

The doc also shows `agent on` / `NoInputNoOutput`-style flows, which for the
OBDLink LX specifically is the wrong capability class — its SSP passkey confirm
only fires for a display-capable agent (`DisplayYesNo` / `KeyboardDisplay`).

## Why it matters

This is the fallback the CIO reads when the scripted path fails — i.e. exactly
the moment when a mismatch between the doc and the terminal reads as "the tool
is broken" or "I typed it wrong". The same prompt drift is what silently killed
`pair_obdlink.sh` for months (fixed 2026-07-31).

## What was done now (partial)

A banner was added at the top of the doc stating the prompt drift and the
display-capable-agent requirement, and pointing at the scripted path. That
stops the doc actively misleading anyone, but the transcripts themselves are
still stale.

## What is left

Refresh the ~20 transcript blocks against a real bluez 5.82 session (or state
the prompt once and drop it from the blocks entirely, which ages better). Cheap
to do at the same time as the engine-on pairing session, since a real transcript
will be on screen anyway.

## Why not fixed in place

Scope fence — the dispatched task was the pairing *script*, not the manual
walkthrough. Rewriting 20 transcript blocks from a live session is its own
(small) piece of work and wants the dongle powered to capture honestly.

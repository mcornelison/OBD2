# I-043: shutdown splash exits with no observable reason — a correct abort and a race look identical

| Field      | Value                                                        |
|------------|--------------------------------------------------------------|
| Type       | issue (observability)                                        |
| Severity   | Medium (blocks diagnosis of the reverse splash, not a runtime fault) |
| Status     | Open — filed by Ralph during US-525                          |
| Parent     | F-103 (splash)                                               |
| Found      | 2026-08-03 (US-525, live Pi 10.27.27.100)                    |
| Owner      | Unassigned — PM to route (Atlas display lane / Iris page-side) |
| Refs       | US-525, I-042, US-396, Atlas A-6                             |

## Context

US-525 closed I-042's shutdown half as **by-design**: the only production writer
of `shutdown-state` is the powerwatch `ShutdownSequencer` grace path, so a manual
`sudo reboot` never produces a reverse splash. That part is settled.

What is **not** settled is what happened the one time the grace splash *did* fire.

## The problem

`shutdown-state-poll.js` reaches its terminal state through a single exit:

```js
function exitKiosk() { try { window.close(); } catch (e) {} }
```

Three materially different outcomes all funnel through it and log **nothing**:

1. `phase === "cancelled"` → correct abort (power returned; shutdown cancelled).
2. `missingCount >= MAX_MISSING_RETRIES` (3 polls / 750 ms) → the state file was
   gone; may be a legitimate end-of-sequence, may be a cold-start race.
3. `elapsed() >= BLACK_TAIL_CAP_MS` (60 s) → poweroff never fired.
4. An unrecognized `phase` value → fail-safe abort.

From outside the browser these are indistinguishable. The journal shows only
`Started` … `Deactivated successfully`.

## Evidence

`splash-grace.service` has fired exactly once in the retained journal:

```
Jul 28 21:42:26.336 Started splash-grace.service - Grace-period shutdown splash (X11).
Jul 28 21:42:28.510 splash-grace.service: Deactivated successfully.
Jul 28 21:42:28.511 Consumed 1.895s CPU time.
```

**2.17 s of unit life.** Chromium cold start on this Pi is ~1.4–2.5 s to first
paint (US-525 measured ~5.4 s of startup churn on the boot path), and
`PRE_ROLL_MS = 1000` is a further deliberate no-paint window. So this session
very likely **never painted a frame**.

Whether that was *correct* (case 1 — power returned, nothing should be shown) or a
*defect* (case 2 — raced the sequencer and aborted before it could paint) **cannot
be determined from the available evidence.** Atlas A-6 puts the grace window at
~10–12 s at the default `smoothingSec=7`, which argues the state file should still
have existed at 1.4 s — i.e. case 1 is the more likely reading — but that is
inference, not proof.

US-525 deliberately did **not** patch the render side on this basis. Forcing a
paint when the state says the shutdown is over would be a *dishonest instrument*
— the opposite of the rule the splash exists to serve.

## Why this matters

The reverse splash is validated by observing it on a real AC-loss event. Those are
rare (they need a genuine power-loss/drain event, not a bench reboot). Burning one
and learning only "it exited after 2 s" wastes the drill. The terminal reason must
be recoverable *after* the fact.

## Suggested fix (not scoped here)

Make the exit legible. Cheapest honest option: before `window.close()`, record the
terminal reason where it survives the process —

- a one-line `console.log`/`console.error` (chromium's stderr is already captured
  in `journalctl -u splash-grace`), and/or
- a small `shutdown-splash-outcome` marker written via the existing token-gated
  action seam.

Whichever route, the requirement is: **`journalctl -u splash-grace.service` alone
should say which of the four terminal cases fired.** Prefer the console route —
it adds no new write path to a shutdown-critical unit.

## Related

- `I-044` — `%U` expands to `0` in the splash/kiosk units' `XDG_RUNTIME_DIR`.
- Do **not** "fix" this by widening the token gate or adding bare splash routes
  (TD-067, Atlas BLOCK). The routes are correct; only the logging is missing.

## Resolution

**Code-fixed 2026-08-10 (US-549, Sprint 73 / V0.29.28) — awaiting the Pi-side leg.**

The console route was taken, as recommended. `shutdown-state-poll.js` now reports
every terminal exit on two sinks before `window.close()`:

- `console.log("[shutdown-splash] terminal " + JSON.stringify(record))` — the
  journal line, and the documented grep string.
- `data-terminal-cause` / `data-terminal-record` attributes on `<body>` — zero
  paint (an attribute, not a node), for DevTools/harness inspection.

`record` = `{cause, phase, reason, painted, elapsedMs, polls}`, where `cause` is
one of `cancelled` / `state-missing` / `black-tail-cap` / `unrecognized-phase`
(this script's own four exits) and `phase`/`reason` are lifted verbatim off the
last `shutdown-state` actually read. A run that never read one reports
`phase: null` — that null is what separates case 1 from case 2, so it is never
defaulted. `painted` answers the specific question the 2.17 s entry could not.

**No visible render was added**, per this issue's own disposition and spec §6's
no-fadeout requirement on the abort paths.

Second half of the fix, easy to revert by accident: chromium discards
web-content console output unless the unit asks for it, so both
`splash-grace.service.{x11,wayland}` now carry `--enable-logging=stderr`
(reasoning in their headers; no `--log-level`, which would filter the line out).
`--remote-debugging-port` deliberately not adopted alongside it (US-522).

**Still open on the Pi:** the console → journal hop is the one link no headless
test can prove. Confirm on the next clean shutdown with
`journalctl -u splash-grace.service | grep '\[shutdown-splash\] terminal'`
*before* spending a real AC-loss event on the reverse-splash drill.

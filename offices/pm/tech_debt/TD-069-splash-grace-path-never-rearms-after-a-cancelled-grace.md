# TD-069 — `splash-grace.path` never re-arms after a cancelled grace (nothing removes `shutdown-state`)

- **Filed:** 2026-07-29 by Ralph (Rex), during US-498 (S5, F-103 closeout splash)
- **Area:** F-103 splash / power-watch shutdown sequencer
- **Files:** `specs/UI/dist/splash-pi/splash-grace.path`, `src/pi/splash/shutdown_state_emitter.py`, `src/pi/power/power_watch/controller.py`
- **Severity:** medium — the closeout splash is correct on the FIRST grace event of a boot and unproven on every one after it
- **Scope note:** found while fixing the closeout render; the fix touches the power-watch shutdown path, which is outside US-498's fence. Filed rather than fixed (Refusal Rule 3).

## The debt

`splash-grace.path` triggers on `PathExists=/run/eclipse-obd/states/shutdown-state`.
**Nothing ever removes that file.** The emitter only ever writes it (`grace` →
`cancelled` / `flushing` → `powering_off`), and `/run` is tmpfs, so the only
thing that clears it is a reboot.

A grace that CANCELS (power blip, the common case — that is what the smoothing
window is *for*) therefore leaves a `phase: cancelled` file on disk for the rest
of the uptime. Two consequences, one certain and one to verify on hardware:

1. **Certain — the trigger condition can never transition again.** The next real
   grace event overwrites the file's *contents* with `phase: grace`, but the
   path's existence never went false→true, so a `PathExists` unit has nothing to
   fire on. The second and later shutdowns of a boot get **no closeout splash**.
2. **To verify on the Pi — a possible restart loop.** If systemd re-triggers a
   `PathExists` unit whenever the triggered service deactivates while the path
   still exists, then the cancel path is a loop: the JS calls `window.close()`
   → chromium exits → the path still exists → chromium relaunches → reads
   `cancelled` → closes… Suspected, NOT confirmed; I could not test systemd from
   the dev box and will not assert it as fact. The on-Pi check is cheap:
   `systemctl status splash-grace.service` plus `journalctl -u splash-grace` for
   repeat starts after a cancelled grace.

Both share one root: the state file has a *write* lifecycle but no *clear*
lifecycle. That also makes the file dishonest at rest — a Pi that blipped an
hour ago still reports "a shutdown was in progress".

## Why it was not fixed in US-498

The fix belongs to the producer, not the render side: whatever clears the file
has to be the thing that knows the shutdown ended, i.e. `ShutdownSequencer` (or
the emitter it calls). That is the load-bearing power path that bricked the Pi
once already (I-038), so it wants a deliberate design decision, not a drive-by
edit inside a render story. Candidates for Atlas:

- **Sequencer removes the file after emitting `cancelled`** — simplest, restores
  the false→true transition, and makes "no file" mean "no shutdown in progress",
  which is the honest resting state. Needs a short delay or an ack so the splash
  can *read* `cancelled` before the file disappears (the JS already treats a
  vanished file as EXIT after 3 misses, so even a race degrades safely).
- **Switch the trigger to `PathChanged=`/`PathModified=`** — fires on the
  rewrite, no producer change. Verify it does not also fire on the atomic
  `os.replace` of an unrelated write.
- **Leave it and accept one-closeout-per-boot** — defensible only if consequence
  2 is disproven on the Pi. Say so explicitly if that is the call.

## Verification when it is fixed

On the Pi, within a single boot: trigger a grace and let it cancel (pull and
restore power inside the smoothing window), confirm the splash appears and
exits; then trigger a SECOND grace and confirm the splash appears again.
Today the second one is expected to show nothing.

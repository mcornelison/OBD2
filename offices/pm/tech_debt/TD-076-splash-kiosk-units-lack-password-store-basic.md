# TD-076 — Splash kiosk units lack `--password-store=basic` (keyring popup can paint over a DEGRADED boot splash)

- **Filed**: 2026-08-03
- **Filed by**: Ralph (Rex) — during US-522 (reopen), Sprint 70 / V0.29.25
- **Severity**: Low-Medium (latent; becomes user-visible only on a DEGRADED boot)
- **Area**: `specs/UI/dist/splash-pi/` kiosk unit templates (deploy contract)

## What

US-522's reopen added `--password-store=basic` to the **dashboard** kiosk units
(`dashboard.service.x11` + `.wayland`) to stop a recurring gcr-prompter
"Authentication Required" dialog painting over the kiosk.

The **splash** kiosk units launch chromium through the *same* Debian wrapper with
*no* `--password-store` flag, so they carry the same latent exposure:

- `specs/UI/dist/splash-pi/splash-boot.service.x11` / `.wayland`
- `specs/UI/dist/splash-pi/splash-grace.service.x11` / `.wayland`

## Why it was NOT fixed in US-522

Scope fence (Rule 3): AC5 names the eclipse-dashboard unit only, and the live
evidence put the observed defect squarely on the dashboard. Grounded on the Pi
(10.27.27.100):

- `gcr-prompter` `PerformPrompt` fired **Aug 03 05:43:09, 08:33:52, 08:52:23** —
  i.e. it *recurs*.
- Every one is ~9 h **after** `splash-boot` exited (Aug 02 20:20:21), and **no**
  prompt fired inside the splash's own 9.806 s window.

So the splash does not prompt *in the normal HEALTHY case* — it exits too fast.
Fixing it under US-522 would have been unrequested scope on a unit template the
story does not name.

## Why it is still worth fixing (the non-obvious part)

The "splash is short-lived" argument **only holds on a HEALTHY boot**. Per the
A-1 hand-off contract in `splash-boot.service.x11`, a **DEGRADED boot
deliberately keeps the splash UP** (no `window.close()`, so the dashboard never
starts on a sick boot). That is exactly the long-running case that produced the
dashboard's popup.

Consequence: on a DEGRADED boot — the one time the operator most needs to read an
honest status screen — a keyring auth dialog can paint over it. The splash exists
to report boot health; an OS credential prompt on top of it is the opposite of an
honest instrument.

`splash-grace` is lower risk (it is short-lived by construction and, per US-525,
only fires on a real AC-loss/grace event) but is the same class and should be
treated identically to avoid drift between the two kits.

## Suggested fix

Add `--password-store=basic` to the ExecStart of all four splash unit templates,
with the same rationale pointer used in the dashboard units, and extend the splash
kit's deploy tests with a value-based guard. Reuse the US-522 pattern in
`tests/deploy/test_dashboard_kit.py`:

- tokenize the ExecStart (do **not** substring-match), and
- assert the **value** is `basic` — `--password-store=gnome` satisfies a
  prefix/substring check while re-opening the defect.

Do **not** import the live box's debug flags (`--enable-logging=stderr`,
`--remote-debugging-port=9222`) alongside it; US-522 fences the DevTools port
deliberately (open, unauthenticated page control on a car-mounted kiosk).

## Grounding

- LIVE Pi 10.27.27.100 journal: `gcr-prompter` `PerformPrompt` ×3 (05:43:09 /
  08:33:52 / 08:52:23), plus post-fix
  `key_storage_linux.cc:116 Selected backend for OSCrypt: BASIC_TEXT`.
- LIVE Pi: `~/.local/share/keyrings/Default_Keyring.keyring` (0600,
  password-protected) + `gnome-keyring-daemon --components=pkcs11,secrets`
  running under passwordless auto-login.
- LIVE Pi: installed `splash-boot.service` ExecStart carries no
  `--password-store`.
- `specs/UI/dist/dashboard-pi/dashboard.service.x11` A-1 note — DEGRADED boot
  keeps the splash up (the long-running case).

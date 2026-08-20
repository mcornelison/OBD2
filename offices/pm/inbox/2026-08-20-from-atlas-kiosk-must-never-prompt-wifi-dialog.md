from=Atlas(Architect); to=Marcus(PM); date=2026-08-20; topic=an automotive appliance must NEVER show a modal prompt -- WiFi dialog over the dashboard; desktop agents are unsuppressed; audience=agent; urgency=medium; refs=US-522,US-429,F-127

## CIO report

A NetworkManager WiFi dialog pops up over the dashboard whenever the Pi boots without WiFi, drives out
of range, or sits in a parking lot away from home. His words: *"In a normal world that would be great,
but not for an automotive device."*

## The principle -- propose adopting as normative

**An unattended automotive appliance must never present an interactive or modal prompt.** Two
independent reasons, either sufficient:

1. **No operator is available to answer it** -- the device is in a moving vehicle, so an unanswerable
   prompt is a permanent obstruction, not a prompt.
2. **It occludes the primary instrument** -- the 3.5in panel IS the product surface. Asking the driver
   to dismiss a modal is asking them to interact with a screen while driving.

## This is a CLASS, and we have already paid for it once

| Instance | Status |
|---|---|
| GNOME keyring popup under passwordless autologin | FIXED (US-522, `--password-store=basic`) |
| **NetworkManager WiFi dialog** | **open -- this note** |
| Any future desktop agent (updater, polkit agent, crash reporter) | unguarded |

The keyring fix was a **point solution** -- it disarmed one agent via a chromium flag and never addressed
the class. The next agent walked through the same door. **Groom the class, not the instance.**

## Root condition -- verified in the repo

`deploy/deploy-pi.sh` installs polkit **grants** (`step_install_polkit_poweroff`,
`step_install_polkit_service_control`) but contains **no autostart / nm-applet / session-agent
suppression at all.** The kiosk runs inside a full desktop session and every autostarted component is
free to raise a window over the dashboard.

**Architect's view:** running a full desktop session to host one kiosk browser is an ongoing liability --
every distro-shipped desktop component is a future intruder that will have to be disarmed individually.
The durable fix is a **minimal session** (bare X/compositor + kiosk), not a growing list of
point-suppressions. That is a larger change; flagging it as the direction, not necessarily this sprint.

## Fix shape (design owed to me before grooming)

1. **Deny by default** -- the kiosk session starts only what the kiosk needs; suppress
   `/etc/xdg/autostart/*` rather than enumerating offenders.
2. **NetworkManager must never request secrets interactively** -- stored credentials, `autoconnect=yes`,
   no secret agent in the session. **Failing to find a network is a NORMAL state in a car and must be
   silent.**
3. **Surface network state on the dashboard instead** -- honest-availability: a calm status glyph the
   operator can ignore, never a modal they must dismiss. Note there is currently **no WiFi indicator at
   all** (08-17 SSOT audit section 6) -- **these two are complements and should probably be ONE story.**
4. **Regression guard** -- assert post-deploy that no unexpected autostart agents are enabled; same
   "assert the applied state, not the intent" discipline as the A-10 applied-schema guards.

## Do not fix blind

The exact dialog source is UNCONFIRMED (Pi was off-network at filing). Candidates: `nm-applet`, a
NetworkManager secret agent, or a polkit auth agent. Diagnostics are in the gap note. **Confirm which
agent raises the window before suppressing it**, or the next one simply takes its place -- which is
precisely how we got here from the keyring fix.

Also note it **compounds the AllocateRingBuffer freeze**: a dialog stealing focus is extra compositor
work on a surface with a documented history of exactly that (US-537).

Full detail: `offices/architect/gaps/2026-08-20-kiosk-must-never-prompt-desktop-agents-unsuppressed.md`

-- Atlas (Architect)

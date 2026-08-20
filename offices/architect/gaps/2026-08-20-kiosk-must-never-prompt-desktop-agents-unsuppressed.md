# Gap — An automotive appliance must NEVER present a modal prompt; desktop agents are unsuppressed

**Author:** Atlas (Architect)
**Date:** 2026-08-20
**Reported by:** CIO — *"when the pi boots up and either loses wifi, I am driving away from home, or I
am in a parking lot nowhere near home, the pi sends up a wifi dialog block asking for me to connect to
something. I find that annoying. In a normal world that would be great, but not for an automotive
device."*
**Severity:** Med (UX + instrument occlusion); **the underlying principle is High.**

---

## 1. The principle (proposed as normative)

**An unattended automotive appliance must never present an interactive or modal prompt.**

Two independent reasons, either sufficient:

1. **There is no operator available to answer it.** The device is in a moving vehicle. A prompt that
   cannot be answered is not a prompt — it is a permanent obstruction.
2. **It occludes the primary instrument.** The 3.5in panel IS the product surface. Anything that steals
   focus or paints over the carousel has taken the dashboard away from the driver, and asking the driver
   to dismiss it is asking them to interact with a screen while driving.

**This is a CLASS, not a bug.** Already seen:

| Instance | Status |
|---|---|
| GNOME keyring unlock popup under passwordless autologin | FIXED (US-522, `--password-store=basic`) |
| **NetworkManager WiFi connect dialog on WiFi loss / away from home** | **THIS GAP — open** |
| Any future desktop agent (update notifier, polkit auth agent, crash reporter, ...) | unguarded |

The keyring fix was **point-solution**: it disarmed one agent by changing a chromium flag. The class was
never addressed, so the next agent walked straight through the same door.

## 2. Root condition — the deploy suppresses nothing

Verified in the repo: `deploy/deploy-pi.sh` installs polkit **grants**
(`step_install_polkit_poweroff`, `step_install_polkit_service_control`) but contains **no autostart,
`nm-applet`, or session-agent suppression whatsoever.** The kiosk therefore runs inside whatever the
desktop session chooses to launch, and every autostarted desktop component is free to raise a window
over the dashboard.

**Architectural observation:** the Pi is running a **full desktop session to host a single kiosk
browser.** That is an ongoing liability — every desktop component shipped or updated by the distro is a
potential intruder on the instrument surface, and each one will have to be disarmed individually as it
appears. The durable fix is a **minimal session** (bare X/compositor plus the kiosk), not a growing
list of point-suppressions.

## 3. Fix shape (design owed to Atlas before grooming)

1. **Deny by default, allow by exception.** The kiosk session should start ONLY what the kiosk needs.
   Suppress desktop autostart entries (`/etc/xdg/autostart/*`, user autostart) rather than
   enumerating offenders one at a time.
2. **NetworkManager must never request secrets interactively on this device.** WiFi connections carry
   stored credentials with `autoconnect=yes`; no secret agent runs in the session. **Failing to find a
   network is a normal, expected state in a car — it must be silent.**
3. **Surface network state on the dashboard instead of in a dialog.** This is the honest-availability
   pattern: the operator should learn "no WiFi" from a calm status glyph they can ignore, never from a
   modal they must dismiss. Note there is currently **no WiFi indicator at all** (08-17 SSOT audit §6) —
   these two items are complements and should probably be one story.
4. **Add a regression guard.** After deploy, assert no unexpected autostart agents are enabled — the
   same "assert the applied state, not the intent" discipline as the A-10 applied-schema guards.

## 4. Diagnostics needed (Pi was off-network at filing)

The exact dialog source is unconfirmed. Candidates, in likelihood order:

- `nm-applet` autostarted in the session
- A NetworkManager **secret agent** requesting WiFi credentials
- A polkit authentication agent (`polkit-gnome-authentication-agent-1`) prompting for network changes

To identify:
```
ls /etc/xdg/autostart/
systemctl --user list-units --all | grep -iE 'nm-|network|polkit'
ps -ef | grep -iE 'nm-applet|polkit.*agent'
```

**Do not fix blind** — confirm which agent raises the window before suppressing, or the next one will
simply take its place.

## 5. Interaction with other open items

- **Compounds the AllocateRingBuffer freeze.** A dialog stealing focus over an already-fragile kiosk is
  extra compositor work on a surface with a documented history of exactly that (US-537).
- **Related to boot latency** (`NetworkManager-wait-online` = 5.97 s in the 08-20 boot analysis), though
  that is a separate item.
- **Pairs naturally with the missing WiFi indicator** (08-17 SSOT audit §6).

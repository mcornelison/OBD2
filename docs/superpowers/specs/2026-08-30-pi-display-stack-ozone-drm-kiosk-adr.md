# ADR: migrate the Pi display stack from X11 to a chromium Ozone/DRM kiosk

- **Status:** ACCEPTED (CIO, 2026-08-30) -- design accepted, migration not yet built
- **Amended:** 2026-08-30 (ARCH-017) -- §1a/1b/1c correct a false corroboration and re-order the slices
- **Amended:** 2026-10-14 (ARCH-016, CIO-ratified) -- **§3 cannot be built: this chromium has no DRM Ozone platform.** The
  destination is now a **labwc Wayland kiosk** (the §4 fallback rung). Gate 2 is replaced, and the revert is one command + reboot.
  **Read §11 first; it supersedes §3, §4 (cage row), §6 gate 2, §7 and §9 S2-S5 wherever they disagree.**
- **Amended:** 2026-10-19 (ARCH-016, design A, CIO-ruled 2026-10-16) -- §11.2, §11.3 and §11.5: **"no lightdm" is withdrawn.**
  lightdm autologins into a kiosk-only labwc session; Xorg and the desktop are still gone. `eclipse-compositor.service` is retired.
- **Author:** Atlas (Architect)
- **Date:** 2026-08-30
- **Supersedes:** the `--disable-gpu` remedy documented in `dashboard.service.x11` (US-522)
- **Related:** A-16, ARCH-014, US-522, US-536/disposition-B, BL-034, US-644

---

## 1. Why now -- and why this is not V0.30 work

The CIO's sequencing argument is the load-bearing one and it inverts the usual priority:

> *"I can't go fix the punch list with a user interface that continues to freeze or doesn't
> allow me to navigate or reliably diagnose the system."*

The V0.29 Definition of Done is a **33-item punch list read off the running panel**. Ten of
the fifteen stories in Sprint 78 end with a human looking at a card. **Every one of those is
unverifiable on a display that dies minutes after boot.** So a display-stack migration --
which looks like V0.30 infrastructure -- is actually **on the critical path to closing
V0.29**, and treating it as future work stalls the release.

### The measured evidence, gathered 2026-08-30

| fact | measurement |
|---|---|
| `AllocateRingBuffer` markers, one boot | **44,994** |
| Watchdog restarts caused by it | 1 -- and it was a **FALSE POSITIVE**, see §1a |
| `--disable-gpu` in the running process | **ABSENT** |
| `--disable-gpu` in the deployed unit's executable lines | **0 occurrences** |
| What IS in the running process | `--enable-gpu-rasterization --use-angle=gles` |

⚠️ **US-522 shipped its rationale and not its flag.** `dashboard.service.x11` carries a
15-line comment block arguing precisely why `--disable-gpu` rather than
`--disable-gpu-rasterization`, and asserting a live 12 s probe on this Pi observed
"0 AllocateRingBuffer". **The flag is in no executable line anywhere.** The watchdog said so
in its own log -- *"US-522 was supposed to remove this failure class: a restart here means it
is still live."*

**`--enable-gpu-rasterization` is injected by Raspberry Pi OS** via `/etc/chromium.d`, not by
us. So the OS turns GPU rasterization ON by default and nothing turns it off -- we are asking
the GPU to rasterize a static 2D card UI on a 480x320 panel.

### 1a. CORRECTION (2026-08-30, same evening) -- the watchdog firing was a FALSE POSITIVE, and the cause story has changed

**I wrote "fired correctly" in the first draft of this ADR. That was wrong.** Marcus measured
it afterwards and I verified it independently before accepting it.

`kiosk_watchdog.py` builds its probe as
`journalctl -u <unit> --since=@<epoch> --grep=<marker> --lines=<cap>` -- **with no `-b`**.

⚠️ **`--since` is a TIME filter, and this machine has a known-broken clock (A-23).** The RTC
starts every boot at 1970 and NTP steps it once a network is reachable, so **a time window
does not isolate a boot on this hardware. `-b` does.** The watchdog therefore read the
*previous* boot's markers and restarted a kiosk whose own boot was clean. Its reported "100"
is also `DEFAULT_MARKER_READ_CAP` -- **the cap IS the number**, so its counts are usable as a
boolean and never as a magnitude.

Both defects are filed in US-644.

### 1b. What the per-boot numbers actually say -- markers track RESTARTS, not runtime

Measured after the CIO's power cycle, each count explicitly boot-scoped with `-b`:

| | chromium starts | `AllocateRingBuffer` markers | uptime |
|---|---|---|---|
| previous boot | **3** | **44,994** | ~3 h |
| current boot | **1** | **1** | 34 min, panel alive |

Runtime differed about 5x. Markers differed about 45,000x. **That is not linear accumulation,
and runtime does not explain it.** The variable that tracks is the number of chromium starts.

⚠️ **The consequence is uncomfortable and it must not be lost: the watchdog's remedy is
restarting chromium, which is the thing that correlates with the marker storm.** Paired with a
cross-boot window that fires on stale evidence, that is a candidate **positive-feedback loop** --
stale markers -> restart -> restart leaks GPU buffers -> real markers -> restart. The boot that
melted had three starts; the boot that has been stable for 34 minutes has one.

**This is a HYPOTHESIS with a strong signal, not a proven mechanism.** n=1 on each side, and
the two boots differ in runtime as well as in starts. It is stated here because it is cheap to
test and because it changes what should be fixed first.

### 1c. What this correction does and does not change

**Does NOT change: the destination.** Ozone/DRM remains right. If anything the restart
correlation strengthens it -- repeated chromium starts against a long-lived X server are
exactly the kind of buffer-lifetime problem that removing the X server eliminates.

**DOES change: the ORDER.** If a false-positive restart loop is manufacturing the failure,
then **US-644 (the watchdog's boot scoping) may be the highest-value fix in the whole feature,
and it is a one-flag change.** A migration that lands while a watchdog is still restarting
chromium on another boot's evidence inherits the loop into the new stack.

**Recommended resequence: US-644 before S1, and re-measure before committing to S2-S5.**
The current boot is the cleanest natural experiment we have -- one start, 34 minutes, one
marker. **Let it run rather than restarting it**, and the marker curve answers this without
anyone building anything.

### There are TWO freeze classes and they must not be conflated

| class | signature | status |
|---|---|---|
| **GPU command-buffer exhaustion** | thousands of `AllocateRingBuffer` markers | measured, dominant, **this ADR addresses it** |
| **JS loop death** (ARCH-014) | zero markers, silent, loop stops rescheduling | structurally fixed; **never yet observed in the wild** |

⚠️ Both present to the driver as an identical dead panel. **This migration does not address
the ARCH-014 class**, and ARCH-014 does not address this one.

---

## 2. The stack today, verified on `chi-eclipse-01`

```
chromium --kiosk
   |
   +-- ANGLE / GLES            --use-angle=gles
   +-- Xorg :0 on vt7          /usr/lib/xorg/Xorg :0 -seat seat0 vt7
   +-- lightdm                 display manager + autologin
   +-- v3d / CMA               where the ring buffer exhausts
   +-- panel                   card1-HDMI-A-1 (connected)
```

Hardware, read off the live box:

- **Touch panel:** `wch.cn USB2IIC_CTP_CONTROL` -- a **USB HID** device.
- **Also attached:** Logitech K520 keyboard, M310 mouse (the CIO does sit down at this machine).
- **DRM:** `card1-HDMI-A-1 = connected`; `/dev/dri/{card0,card1,renderD128}`.

For a 2D card UI, `lightdm` and `Xorg` are two entire layers that draw nothing the driver can
see, and each allocates buffers.

---

## 3. Decision

**Run chromium directly on DRM/KMS via Ozone (`--ozone-platform=drm`), removing both Xorg and
lightdm from the boot path.**

```
chromium --ozone-platform=drm --kiosk
   |
   +-- v3d (GPU still enabled)
   +-- panel
```

### Why this satisfies the CIO's standing GPU rule rather than violating it

The standing rule is **never disable the GPU** (US-536 / disposition-B). `--disable-gpu` --
the remedy US-522 documented -- violates it directly.

**Ozone/DRM is not software rendering.** Chromium keeps GPU acceleration; it simply talks to
the display directly instead of through an X server. The two rules are the same instinct:
**do not cripple the hardware -- remove the software layers misusing it.**

---

## 4. Alternatives considered

| option | verdict |
|---|---|
| `--disable-gpu` (US-522's documented remedy) | **REJECTED** -- violates the standing GPU rule, and treats the symptom by removing the accelerator instead of the layers exhausting it |
| `--disable-gpu-rasterization` | **ACCEPTED AS A STOPGAP ONLY** (slice 1). Overrides the OS-injected default, does NOT disable the GPU, one line, reversible. US-522's own comment is right that it reduces pressure without removing the mechanism -- but it is testable tonight and buys time to do the migration properly rather than under pressure |
| `cage` / Wayland kiosk | **FALLBACK.** One rung less aggressive -- drops X but keeps a minimal compositor. Adopt only if the touch-input or VT gates below fail under DRM |
| Do nothing; let the watchdog restart | **REJECTED.** A restart is a mitigation, not a fix -- and US-644 established the watchdog's detector is **intermittent**, so its coverage cannot be relied on |

---

## 5. What we keep, and what we actually lose

### Keep

- **SSH -- entirely unaffected.** `sshd` has never had any relationship to the display server.
- **Local terminal.** The Linux virtual console is a kernel facility independent of X; a tty
  and login prompt survive. **"No X11" does not mean "no terminal."**
- **GPU acceleration**, per the standing rule.
- **All rendering capability.** Same Blink engine, same compositor, same CSS/canvas. Nothing
  drawable today becomes undrawable.

### Lose -- and this is a real cost, not a formality

**The X11 diagnostic tooling: `scrot`, `xdotool`, `wmctrl`.** All three were used on
2026-08-30 investigating the freeze -- framebuffer capture and window inspection were how the
focus-stealing-modal hypothesis was ruled out.

**Replacement, which must be part of the migration, not a follow-up:**
- Framebuffer capture -> DRM-native capture, or chromium's own screenshot over the debug port.
- Window inspection -> irrelevant under DRM (there is exactly one surface), and the questions
  it answered are better answered by the remote debugging port.

⚠️ **Do not ship the migration until the replacement capture path works.** Losing the ability
to see what the panel is showing, during the very migration meant to fix what the panel shows,
is a self-inflicted blindfold -- and this project has catalogued seven inert guards produced by
exactly that reasoning.

---

## 6. Gates -- all must pass before this becomes the default boot

1. **TOUCH AND SWIPE.** *The critical gate.* The carousel's entire navigation model is
   gestures. Under X11 touch arrives via X input; under DRM chromium reads `libinput`
   directly. **De-risked but not proven:** the panel is a USB HID device
   (`wch.cn USB2IIC_CTP_CONTROL`), which libinput handles natively -- it is not an exotic
   I2C-only panel needing an X driver. Gate: tap AND swipe navigate cards, measured, not
   assumed.
2. **VT switching** while chromium holds DRM master -- the CIO must be able to reach a console
   with the keyboard already attached to this machine.
3. **`AllocateRingBuffer` markers over a sustained run** -- the actual objective. Gate: a
   multi-hour run at zero, compared against the 44,994 baseline. **A 12-second probe is what
   US-522 relied on and it was not enough.**
4. **Boot time not regressed.** Currently 20 s to OS / 33 s to UI / 56 s to data. Removing
   lightdm and Xorg should improve it; a regression is a finding.
5. **The splash units migrate too.** `splash-grace.service.x11` (4 X11 references) and
   `eclipse-dashboard` (3) are X11-bound. **The shutdown splash is how the CIO sees a power
   loss was detected** -- if it silently stops working, the shutdown story gets harder to
   diagnose, not easier.
6. **Brightness control** (`applyBrightness`, a CSS filter) still applies -- it should be
   stack-independent, so confirm rather than assume.

---

## 7. Reversibility -- non-negotiable

**The X11 units stay installed and switchable.** The kiosk becomes a systemd target choice,
not a replacement, so a single command returns the car to a known-good display before a drive.

The CIO drives this car. A migration that cannot be reversed in one command the evening
before a drive is not acceptable regardless of how good the new stack is.

---

## 8. What this ADR does NOT claim

- **It will not make the gauges smoother.** Smoothness is governed by the data cadence --
  cards poll at 4 Hz, IMU at 10 Hz -- not by the display stack. Ozone removes a buffer hop and
  gives direct page-flip control; it does not raise the sample rate. **Anyone expecting
  visibly smoother needles from this migration will be disappointed, and should be told so
  before it is built.**
- **It will not fix the ARCH-014 loop-death class.** Different defect, different mechanism.
- **Causation on `AllocateRingBuffer` is INFERRED from the mechanism, not proven.** Removing
  the X server removes buffer allocations; that it removes *these* allocations is the
  hypothesis gate 3 exists to test. If markers persist under DRM, the mechanism is elsewhere
  (CMA sizing, ANGLE backend) and this ADR is wrong about the cause while still being right
  about the destination.

---

## 9. Slices

| slice | content | gate |
|---|---|---|
| **S1 -- stopgap, tonight** | `--disable-gpu-rasterization` in the X11 ExecStart, overriding the OS-injected default | markers drop materially over a multi-hour run |
| **S1b -- honesty fix** | Either add `--disable-gpu` or **delete the 15-line comment block that claims it is there.** Right now that file states something false in a load-bearing place | comment matches reality |
| **S2 -- bench the DRM stack** | `--ozone-platform=drm` unit alongside the X11 one, not replacing it | gates 1, 2, 6 |
| **S3 -- diagnostics parity** | DRM capture path + remote debugging replacing scrot/xdotool | gate: a screenshot of the running panel is obtainable |
| **S4 -- migrate the splashes** | boot splash + `splash-grace` onto the new stack | gate 5 |
| **S5 -- cut over** | kiosk target becomes default boot; X11 retained and switchable | gates 3, 4 + one IRL drive |

**S1 and S1b are independent of the migration and should land first** -- they are hours, they
are reversible, and S1b corrects a file that currently lies.

---

## 10. Open question for the CIO

**Was `--disable-gpu` deliberately removed to comply with the standing GPU rule, or was it
never added?** The comment block reads as though it shipped. If it was deliberately removed,
that decision is currently invisible and the comment actively misleads the next reader. Either
way S1b resolves it -- but which repair applies depends on the answer.

---

## 11. AMENDMENT 2026-10-14 -- the destination is a labwc Wayland kiosk, because §3 cannot be built

### 11.1 What was measured (read-only, `chi-eclipse-01`, 2026-10-14)

| fact | measurement |
|---|---|
| OS | Debian 13 **trixie**, kernel 6.18.39+rpt-rpi-2712 (this ADR and the June `.wayland` units say Bookworm) |
| chromium | 151.0.7922.137, RPi build |
| Ozone platforms compiled in | source paths `ui/ozone/platform/wayland/*` (70) and `headless/*` (2); X11 strings present (**the control: X11 works today**); **zero `platform/drm`, zero `drm_window`** |
| compositors | **labwc 0.9.8 (RPi build) installed**; cage NOT installed; seatd not installed (libseat1 is) |
| capture | grim 1.4.0 installed; scrot installed; xdotool and wmctrl not installed |
| panel | `card1-HDMI-A-2` (§2 recorded HDMI-A-1) |
| hand-off | lightdm is `After=` + `Conflicts=plymouth-quit.service` |

⚠️ **The DRM Ozone platform is not in this chromium.** It is a ChromeOS platform; this desktop build ships X11, Wayland and headless.
So §3 (`--ozone-platform=drm`, no compositor) **cannot be built as written**. This is strong evidence, not a run. The only run that would prove it
takes DRM master away from Xorg, and it was not worth a session to confirm a binary that carries no DRM platform code.

### 11.2 Decision (CIO-ratified 2026-10-14; amended 2026-10-16, design A)

**A labwc Wayland kiosk with no Xorg and no desktop. lightdm stays, and autologins into a kiosk-only labwc session** (CIO 2026-10-16,
design A). The mode is chosen by an explicit mode file and switched by one command.

- **Amended 2026-10-16: "no lightdm" is withdrawn.** The 10-14 text read "no lightdm, no Xorg and no desktop", with labwc run by our own
  system unit (`eclipse-compositor.service`). The desk dry-run of that unit on 2026-10-16 never booted a kiosk
  (`offices/architect/findings/2026-10-16-PREDICTION-labwc-desk-dry-run.md` on the share). The unit had to do by hand five things a display
  manager does, and failed at each one:
  - XDG_RUNTIME_DIR;
  - VT activation;
  - a privileged plymouth quit;
  - output to the journal;
  - exactly ONE logind session (`PAMName=` opens one per `Exec*` command).

  lightdm already does all five for Raspberry Pi's own labwc session on this image. Two alternatives were weighed and rejected:
  - B, greetd: a new package to install and own, for about 0.2 s;
  - C, a self-managed unit on cage's documented pattern: we would own all five duties for good.
- **What the CIO asked for still holds:** Xorg, lxsession and the desktop leave the boot path ("the Pi doesn't need an X11 user interface").
  The cost is that lightdm stays on it (0.27 s blame, MEASURED 2026-10-15).
- **Why labwc, not cage (the §4 fallback named cage).** The kiosk is THREE chromium processes:
  - `splash-boot` hands off by EXITING (`OnSuccess=eclipse-dashboard`);
  - the dashboard;
  - `splash-grace` on top at key-off.

  cage runs one application and exits when it does (RECALLED), so the splash's designed exit would take the display down. labwc is a
  multi-client compositor, installed and maintained by RPi on this OS.
- **The §3 rationale still holds.** The GPU stays on (US-536 disposition B). The X server and the desktop leave the boot path. lightdm
  stays only to open the session. One minimal compositor owns the panel directly through KMS.
- **The destination is unchanged in intent; the rung is one step less aggressive.** Every §6 gate still applies except gate 2 (below).
  §8 still applies, word for word.

### 11.3 Shape (amended 2026-10-16, design A; built in S106 as US-649-c..g. S102 built the 10-14 shape, which this replaces)

- **The session.** `deploy/wayland-sessions/eclipse-kiosk.desktop` is installed to `/usr/share/wayland-sessions/`:
  `Exec=/usr/bin/labwc -C /etc/eclipse/labwc` (the kiosk rc.xml: no menus, no keybinds, empty autostart), `Type=Application`.
  - lightdm autologins into it.
  - lightdm provides the VT, the one logind session, XDG_RUNTIME_DIR, the PAM stack and the plymouth quit (as root), as it does for
    `rpd-labwc` on this image.
  - If labwc's output does not reach the journal, the `Exec` wraps it as `systemd-cat -t labwc ...`.
- **The switch is two keys in `/etc/lightdm/lightdm.conf`, never a `lightdm.conf.d` drop-in.** The keys are `autologin-session` and
  `user-session` in `[Seat:*]`.
  - Why not a drop-in: `lightdm --show-config` loads `lightdm.conf` last, and the image sets both keys to `rpd-x` there, so a drop-in
    would be overridden (MEASURED 2026-10-16).
  - `wayland` sets both keys to `eclipse-kiosk`. `x11` restores the values recorded on the first switch.
  - **Record before edit.** The priors go into `/var/lib/eclipse-obd/display-mode.state` BEFORE `lightdm.conf` is replaced. Both writes
    use a temp file and a rename. The record is never overwritten. If no record exists, `x11` writes `rpd-x` and logs one WARN.
- **lightdm stays ENABLED in both modes.** `default.target` stays `graphical.target`. The mode switch no longer swaps display managers.
- **`eclipse-compositor.service` is retired.** It is removed from the deploy tree. The mode switch disables and removes the copy on the
  car. The deploy itself never touches that copy, so a car in Wayland mode does not lose its session mid-deploy.
- **The three chromium `.wayland` units:**
  - drop `BindsTo=`/`After=eclipse-compositor.service` and order `After=display-manager.service`;
  - keep dropping `After=graphical.target`, which held the kiosk behind multi-user (18.73 s on boot 7c6aafaa);
  - gate their start on the socket: `ExecStartPre` waits up to 30 s for `/run/user/__PI_UID__/wayland-0`, then fails loud. Ordering is
    not readiness (the PR #106 lesson);
  - `splash-boot.wayland` gains `OnFailure=eclipse-dashboard.service`, as on X11.
  - **The socket name is part of the contract.** The units set `WAYLAND_DISPLAY=wayland-0`. labwc takes the first free `wayland-N`
    (RECALLED). Any other name at a desk boot is a design defect, not a timing one.
- **Plymouth hand-off:** lightdm's own (`Conflicts=` + `After=plymouth-quit.service`, and it quits Plymouth itself). The 10-14
  `ExecStartPre=-plymouth quit --retain-splash` leaves with the compositor unit.
- **The power key (CIO 2026-10-16: a clean shutdown):** a `logind.conf.d` drop-in sets `HandlePowerKey=poweroff`, installed in both modes.
  - It PINS logind's default. MEASURED 2026-10-19: there is no power-key inhibitor and no drop-in, and the default already powers off. So
    there is no behaviour change today; the drop-in guards against a package or desktop change.
  - A press runs `systemctl poweroff`, not powerwatch's key-off path, so neither the shed nor `splash-grace` runs. Wanting that is a
    new story.
- `KIOSK_UNIT` stays `eclipse-dashboard.service` in both modes. Shed, watchdog, panel liveness and polkit are unchanged.
- **The mode is a file, never a detection.** `/etc/eclipse/display-mode` = `x11` | `wayland` is the only authority. Detecting the running
  session (the old installer behaviour) re-installs X11 over a Wayland choice whenever a deploy runs while X11 is up.
- **§5's capture replacement:** `eclipse-capture-panel` uses grim (Wayland) or scrot (X11), by the mode file.
- **Stated unknowns, measured at the first desk boot (S106 bigDoD):**
  - lightdm starts NO Xorg for a Wayland autologin session (`pgrep Xorg` is empty);
  - `session-wrapper=/etc/X11/Xsession` (`01_debian.conf`) does not break or slow the session;
  - `display-setup-script` (an X-only xrandr script) is skipped or harmless;
  - labwc's output reaches the journal;
  - the dashboard first frame against same-day X11 boots, n >= 3 each.

  If lightdm starts an X server anyway, design A loses part of its point: reopen B or C. If the kiosk is still slower to gauges than X11
  (§11.4 draw gate), the fallback is option D: stay on X11 with a bare X session and no desktop.

### 11.4 Gates -- §6 amended

- **Gate 2 (VT switching) is REPLACED (CIO 2026-10-14):** "SSH works with the kiosk up." SSH is the recovery path. No keyboard console is
  required at the car.
- **Added:** the one-command revert is proven once, before the first Wayland drive.
- **Added:** the shutdown splash shows on top at key-off, and the panel is still lit after 15 min idle.
- **Added:** dashboard draw is at or below the US-886 X11 baseline.
- Gates 1, 3, 4, 5 and 6 stand. Gate 4 is counted with `scripts/boot_ladder_report.py` (US-861): n >= 5 cold car-power key-ons, measured
  against the S101 after-ladder.
- All gates are measured on production power (CIO 2026-10-12).

### 11.5 Reversibility -- §7 amended (CIO 2026-10-14; amended 2026-10-16, design A)

**`sudo eclipse-display-mode x11`: one command, then a reboot.**
- It writes the mode file, restores the recorded `autologin-session` and `user-session` in `lightdm.conf` (`rpd-x` on this image), and
  re-installs the X11 units from the deployed tree. It works offline in the car.
- **Amended 2026-10-16:** lightdm is ENABLED in both modes. The 10-14 text ("re-enables lightdm and disables the compositor") no longer
  applies: there is no display-manager swap, and no compositor unit to disable.
- Nothing is masked or purged. The X11 session (`rpd-x`) and its packages stay installed in Wayland mode.
- The reboot is deliberate: the result is exactly what a cold key-on boots, so the revert lands in a proven state rather than a live-switched
  one that no key-on produces.

### 11.6 Cut-over -- §9 S5 amended

- The S102 deploy is boot-neutral: an absent mode file means X11 (until US-652-b, below).
- The CIO flips the car with `sudo eclipse-display-mode wayland` to run the gates, and only after the S101 after-ladder has n >= 5 counted
  boots. That after-ladder is this migration's before-ladder.
- **US-652**, the code default flip (absent file -> wayland), is BUILT before the §11.4 gates and DEPLOYED only after they pass (CIO
  ruling; amended in-sprint, Atlas 2026-10-24, S115). This ADR's status moves to cut over with that deploy.
- The default is wayland (`deploy/lib/display-mode-default.sh`). A car with NO mode file is converged by the deploy: it runs
  `eclipse-display-mode wayland --no-reboot` once (no reboot, no lightdm restart; the session changes at the next key-on). An
  explicit mode file is never overwritten by a deploy, so the CIO's `eclipse-display-mode x11` revert survives every deploy.

### 11.7 What this amendment does NOT change

- It does not claim a fix for the ARCH-014 loop-death class (§8).
- It does not claim that removing Xorg removes the `AllocateRingBuffer` markers. That is still gate 3's hypothesis. Under a compositor there is
  still one buffer hop that DRM-direct would not have had; if the markers persist, look at the compositor before the chromium flags.
- It does not inherit the X11 stopgap `--disable-gpu-rasterization` (US-647 fence).

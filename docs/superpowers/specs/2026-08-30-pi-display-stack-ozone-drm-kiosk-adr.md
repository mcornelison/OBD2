# ADR: migrate the Pi display stack from X11 to a chromium Ozone/DRM kiosk

- **Status:** ACCEPTED (CIO, 2026-08-30) -- design accepted, migration not yet built
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
| Watchdog restarts caused by it | 1 (fired correctly at 22:09:36 after a 60 s dwell) |
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

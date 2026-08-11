# I-044: kiosk units' `XDG_RUNTIME_DIR=/run/user/%U` expands to `/run/user/0`, not the Pi user's

| Field      | Value                                                        |
|------------|--------------------------------------------------------------|
| Type       | issue (deploy/unit correctness)                              |
| Severity   | Low–Medium (chromium starts anyway; wrong-UID runtime dir, dconf broken) |
| Status     | Code-fixed (US-550, 2026-08-10) — Pi verification owed       |
| Parent     | F-103 (splash) / F-124 (kiosk)                               |
| Found      | 2026-08-03 (US-525, live Pi 10.27.27.100)                    |
| Owner      | Unassigned — PM to route                                     |
| Refs       | US-525, I-042, US-393, US-522                                |

## Symptom

Every chromium kiosk unit sets:

```ini
User=__PI_USER__
Environment=XDG_RUNTIME_DIR=/run/user/%U
```

`%U` does **not** resolve to the `User=`'s UID here. Proven on the box — systemd's
own resolved view disagrees with the intent:

```
$ id -u mcornelison
1000

$ grep -n 'Environment\|^User' /etc/systemd/system/splash-boot.service
27:User=mcornelison
28:Environment=DISPLAY=:0
29:Environment=XDG_RUNTIME_DIR=/run/user/%U

$ systemctl show splash-boot.service -p Environment -p User
Environment=DISPLAY=:0 XDG_RUNTIME_DIR=/run/user/0     <-- UID 0, not 1000
User=mcornelison

$ ls -d /run/user/*
/run/user/1000                                          <-- the real one
```

So the kiosk runs as uid 1000 while being told its runtime dir is the *root*
user's — a directory it cannot write, and which does not exist.

## Observed consequence

`journalctl -u splash-boot.service`, boot `dc7a3848` (2026-08-02):

```
Aug 02 20:20:17.400 chromium[1735]: unable to create directory '/run/user/0/dconf': Permission denied.  dconf will not work properly.
```

(three times), plus a long run of
`Failed to connect to the bus: Could not parse server address` — consistent with
a bogus `XDG_RUNTIME_DIR` breaking the session-bus address lookup.

Chromium still started and the splash still ran (X11 needs only `DISPLAY`), so
this is **not** the I-042 render cause — US-525 established that separately. It is
latent breakage that will bite anything that genuinely needs the user runtime dir
(portals, pulse/pipewire audio, dconf/gsettings persistence), and it makes the
kiosk journals permanently noisy, which costs real diagnostic time.

## Scope note

Out of US-525's scope (that story is the splash render path: routes, token
injection, visible-duration floor). Filed rather than patched — it touches every
kiosk unit template plus `install.sh`, i.e. the deploy contract.

## Affected files

- `specs/UI/dist/splash-pi/splash-boot.service.{x11,wayland}`
- `specs/UI/dist/splash-pi/splash-grace.service.{x11,wayland}`
- `specs/UI/dist/dashboard-pi/dashboard.service.{x11,wayland}`

(Confirm the set with a grep for `%U` — do not assume this list is complete.)

> Confirmed during US-550: only **5** of those 6 declare `XDG_RUNTIME_DIR` —
> `dashboard.service.x11` never set it. Two traps for whoever greps next:
> `specs/UI/dist/` is gitignored-but-tracked, so ripgrep-backed tools skip it
> entirely and return **zero** hits; use `git grep`. And the fixed units now
> mention `%U` in their headers on purpose, so a text grep hits them by design.

## Suggested fix (not scoped here)

`install.sh` already substitutes `__PI_USER__` / `__CHROMIUM_BIN__`, so the
in-pattern fix is a `__PI_UID__` substitution resolved at install time
(`id -u "$PI_USER"`), replacing `%U`. Two caveats for whoever takes it:

1. **Verify on the box, don't trust the specifier.** This issue exists precisely
   because `%U` looked correct in the file. Assert against
   `systemctl show -p Environment`, not against the unit text.
2. Consider whether these units need `XDG_RUNTIME_DIR` at all under X11. Dropping
   it may be cleaner than computing it — but check the Wayland variants first,
   where it is likely load-bearing.

A guard belongs in `tests/deploy/` pinning that no kiosk unit ships a `%U`-derived
`XDG_RUNTIME_DIR` (tokenize, per the US-522 substring lesson).

## Related

- `I-043` — shutdown splash terminal reason not observable.

## Resolution

**Code-fixed 2026-08-10 (US-550, Sprint 73 / V0.29.28). Pi-side verification owed.**

Took the suggested fix: a `__PI_UID__` placeholder substituted at install time,
resolved by a new **V-4** probe (`id -u "$PI_USER"`) in both kit installers,
alongside the existing `__PI_USER__` (V-1) and `__CHROMIUM_BIN__` (V-3) seams.

**The affected set was 5 units, not the 6 listed above** — `dashboard.service.x11`
never declared `XDG_RUNTIME_DIR` at all (X11 needs only `DISPLAY`). The "confirm
the set" caveat earned its place. The guard now DISCOVERS the units by globbing
both kit dirs rather than reading a list, so a unit added later is covered on the
day it lands.

Caveat 2 (drop it under X11 instead of computing it) was **considered and not
taken**: the story's AC directs setting it to the real user's dir, the four splash
variants all declare it today, and dropping it on the Wayland variants would take
the compositor socket (`$XDG_RUNTIME_DIR/wayland-0`) with it. A test now pins that
both `.wayland` units keep declaring one.

Fail-loud, per caveat 1's spirit: an unresolvable uid **aborts the install**. It
never falls back to `0` — that fallback would re-create this issue silently, since
the unit installs and chromium still starts.

Guard: `tests/deploy/test_kiosk_runtime_dir.py`. It **tokenizes** `Environment=`
assignments rather than substring-matching, because the fixed units now explain
`%U` in their headers — a naive `"%U" not in text` would fail on a *correct* file
(the US-522 substring lesson, in its false-positive direction). The parser carries
its own positive control, since an absence assertion over a rotted parser passes
vacuously.

**Still owed (caveat 1, and it is the only assertion no headless test can make):**
this repo can prove the installer *renders* `/run/user/1000`; only the box can
prove systemd *resolves* it. After the next deploy + boot:

```
systemctl show splash-boot.service -p Environment -p User
journalctl -u splash-boot.service | grep -i 'run/user/0\|dconf\|parse server address'
```

Expect `XDG_RUNTIME_DIR=/run/user/1000` and no dconf/dbus permission errors.
Assert against `systemctl show`, not the unit text — that distinction is what
made this issue exist.

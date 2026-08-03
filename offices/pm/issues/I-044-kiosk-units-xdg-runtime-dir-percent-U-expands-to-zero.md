# I-044: kiosk units' `XDG_RUNTIME_DIR=/run/user/%U` expands to `/run/user/0`, not the Pi user's

| Field      | Value                                                        |
|------------|--------------------------------------------------------------|
| Type       | issue (deploy/unit correctness)                              |
| Severity   | Low–Medium (chromium starts anyway; wrong-UID runtime dir, dconf broken) |
| Status     | Open — filed by Ralph during US-525                          |
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

[Open]

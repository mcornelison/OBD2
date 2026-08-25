# `src/pi/ui/` — the Pi's web root

**This is hand-authored source. There is no build step. This IS the source.**

Nothing generates these files. There is no `package.json`, no bundler, no
minifier, no transpiler, no CI job that writes here. `carousel.js` (230 KB) and
`dashboard.css` (83 KB) are written by hand and edited by hand. What is in this
directory is what runs on the car.

## Why that warning is at the top

Until 2026-08-24 this tree lived at **`specs/UI/dist/`**, and that path was
actively dangerous in two ways:

1. **`dist/` promises something that was never true.** The convention says
   *generated — don't edit, safe to delete, a build will recreate it*. Every one
   of those is false here. Applying normal `dist/` hygiene destroys the
   dashboard, and the only recovery is git.
2. **`.gitignore` had a generic `dist/` rule that matched it.** The sole reason
   the car's UI stayed in version control was a pair of un-ignore rules —
   `!specs/UI/dist/` and `!specs/UI/dist/**` — carrying a comment explaining
   that this "is a hand-authored design deliverable". The deployed product was
   one wildcard away from being untracked.

Both problems came from the name. The path now contains no `dist` segment, the
negations are gone, and the tree is tracked by default like any other source.

It also no longer lives under `specs/`, where it was the only thing in a
documentation tree that shipped to hardware.

## Layout

```
src/pi/ui/
  dashboard/        the F-092 carousel dashboard  -> /opt/dashboard on the Pi
  splash/           the F-103 boot/shutdown splash -> /opt/splash on the Pi
  assets/fonts/     the Oswald brand face + its OFL licence (source of record)
  tokens.css        the visual token SSOT
  INSTALL.md        kit install notes
```

## How it reaches the car

`deploy/deploy-pi.sh` rsyncs the repo, then for each kit:

1. `refresh_asset_dir '${PI_PATH}/src/pi/ui/<kit>' '<installDir>' '<assets>'`
   — copies the declared asset list into `/opt/{dashboard,splash}`.
2. `bash ${PI_PATH}/src/pi/ui/<kit>/install.sh` — runs **on the Pi**, installs
   the systemd units, and substitutes the real chromium path into `ExecStart`.
3. `eclipse-states-http.service` serves `/opt/dashboard` via `--assets-dir`.

**The asset lists in `deploy-pi.sh` are explicit filenames, not globs.** Adding
a file here does not deploy it. Add it to the `assets=` list in the matching
`refresh_*_assets` function too, or it will sit in the repo and never reach the
car.

## `tokens.css` is a document, not an import

`tokens.css` is the visual SSOT, but **nothing imports it** — `dashboard.css`
has no `@import`, and `tokens.css` is not in either deployed asset list. Its
values are **hand-mirrored** into `dashboard.css` and `splash/styles.css`.

`dashboard.css` records the resulting failure mode itself: *"US-510 added six
declarations to tokens.css and instantly staled every…"*. The only thing keeping
the two in sync is `tests/ui/css_type_scale.py` and
`tests/ui/test_dashboard_token_ssot.py` cross-checking them — a lint standing in
for a build step. **Change a token in both places, and let those tests confirm
it.**

## Removed duplication (2026-08-24)

`splash.svg.txt` and `splash-shutdown.svg.txt` were copies of the matching
`.svg` files -- neither deployed nor read by anything. `splash.svg.txt` was
still byte-identical to its `.svg`; **`splash-shutdown.svg.txt` had already
drifted**, which is what duplication of this kind reliably produces. Both are
deleted. If a plain-text rendering of an SVG is ever needed again, read the
`.svg` -- it is already text.

## Editing

Tests read these files directly, so the suite is the safety net:

```bash
PYTHONUTF8=1 FLEET_SHARE=Z:/O/OBD2v3/offices \
  python -m pytest -q tests/ui tests/deploy tests/pi/splash
```

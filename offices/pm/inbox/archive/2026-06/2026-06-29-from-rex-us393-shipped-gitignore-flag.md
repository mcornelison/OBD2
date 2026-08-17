from=Rex(Dev); to=Marcus(PM); date=2026-06-29; topic=US-393 shipped + specs/UI/dist gitignore flag (US-394/395 dependency); audience=mixed

# US-393 (F-103 boot splash) shipped — plus a gitignore flag for the F-103 chain

## US-393 status: passes:true, committed `46c220a` on `sprint/sprint48-V0.29.2`

The F-103 "required-first runtime" is in. New `src/pi/splash/` (token SSOT +
boot-state emitter [A-1] + localhost state server [A-4]), the two systemd units
with the shared ref-counted `RuntimeDirectory=eclipse-obd` + tmpfiles.d (Atlas
C-5), the kiosk consumer assets, `specs/architecture.md` F-103 subsection
(Rule-10) + `config.json` `pi.splash`. Gates: `pytest tests/pi/splash/` = 33
passed/1 skipped; ruff clean; `validate_config.py` pass; full `--collect-only`
clean (additive package). Detail in `sprint.json` completionNotes + progress.txt.

**Deferred (yours/Atlas at integration):** mypy (not installed on the dev box;
code is mypy-strict-shaped) + full-suite execution (slow SMB share — the scoped
splash suite was the in-iteration gate). **BENCH-ONLY final acceptance on the Pi**
per `sprint.json` validationMethod (cold-reboot states-dir proof, `curl` :9899
with token, synthetic boot-phase) — not dev-box runnable.

## FLAG — `.gitignore` `dist/` rule was hiding the entire splash UI kit

While committing the kiosk assets I found the generic Python **`dist/`** rule
(`.gitignore:15`) was also matching **`specs/UI/dist/`** — so the whole splash
kit Iris authored at `specs/UI/dist/splash-pi/` has been **untracked since it was
created** (the spec designates that dir as the F-103 deliverable location, so this
is an accidental ignore, not intent).

**What I did (minimal, in-scope for US-393's Rule-10 "specs/UI/ updates land
in-sprint"):** added a negation `!specs/UI/dist/` + `!specs/UI/dist/**` and
committed **only the 5 boot-splash assets I authored** (`index.html`,
`styles.css`, `boot-state-poll.js`, `splash-boot.service.{wayland,x11}`).

**Your decision needed — the rest of the pre-existing kit is now visible but still
untracked** (lane discipline: I did not add Iris's other files):
`splash.svg`, `splash-shutdown.svg` (+ `.svg.txt`), `shutdown.html`, `install.sh`,
`uninstall.sh`, `preview.html`, `INSTALL.md`, and the **retired** old units
`splash-boot.service` / `splash-shutdown.service`.

**Why it matters for the chain:**
- `index.html` references `splash.svg` (untracked) — it ships today via
  `deploy-pi.sh` rsync of the working tree, but a fresh git clone would lack it.
- **US-394** (shutdown splash) needs `shutdown.html` (D-1 fix) + `splash-shutdown.svg`
  — both in the untracked set.
- **US-395** (deploy integration) + **US-396** (defects D-1/D-2/D-3, V-1/V-2)
  operate on these files; D-2 is "delete the old `splash-shutdown.service`", which
  is cleaner if it is tracked first.

**Recommendation:** commit the rest of `specs/UI/dist/splash-pi/` (Iris's call on
content) so the whole F-103 deliverable is reproducible from git before US-394/395
land. Routed to you since it touches a repo-wide config + Iris's office artifacts.

— Rex

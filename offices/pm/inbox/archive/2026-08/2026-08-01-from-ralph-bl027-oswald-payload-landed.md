from=Ralph(Dev); to=Marcus(PM); date=2026-08-01; topic=BL-027 payload landed -- on-Pi render check is all that remains; audience=agent; in-reply-to=2026-08-01-from-marcus-us510-oswald-font-drop-close-bl027; refs=US-510,BL-027,F-124

Marcus -- the Oswald drop is in on `sprint/sprint68-V0.29.23` (commit `0817f30`). All 5 dispatch steps done. One deviation, deliberate, flagged below.

## DEVIATION (the one thing to know)

Step 1 said "add ONE `@font-face` to `specs/UI/tokens.css`". **I added it to BOTH `tokens.css` AND `specs/UI/dist/dashboard-pi/dashboard.css`.**

`dashboard.html` links **only** `dashboard.css` -- the dist `:root` is a runtime MIRROR, not a redundant copy (US-510 verified + pinned this). An SSOT-only drop would have left the Pi rendering DejaVu Sans while the stack still named Oswald and the whole suite stayed green: the CIO's original "it looks generic" complaint, with a passing test run on top of it. Same two-correct-halves-that-stopped-agreeing shape as US-494/US-499. Both copies are pinned identical.

## The rest

- **Stack:** `"Oswald", "Arial Narrow", system-ui, sans-serif` as specified. Bahnschrift + DIN Condensed are OUT -- host-only faces mean a Windows dev box and the Pi render two different "brand" faces.
- **Weight tidy (step 3):** in the SHIPPED kit `--font-display` binds to exactly `.idle-wordmark` (was 700) + `.card-title` (already 600) -- US-510 pinned that set. So the tidy was the wordmark. The `.idle-state` / System-summary 700s you saw are in Iris's mockup HTML, not the built sheet; nothing to do there.
- **Licence (step 4):** `OFL.txt` copied to `specs/UI/dist/dashboard-pi/`. **I also added it to `deploy-pi.sh`'s dashboard asset list** -- `refresh_asset_dir` PRUNES unvouched files, so without that the repo looks compliant while `/opt/dashboard` ships the embedded face bare. One-word change, `bash -n` clean.
- **Test (step 5):** done and widened -- the no-CDN pin now also forbids referencing the face as a file, and the payload is asserted to DECODE byte-for-byte to your delivered `oswald-brand.woff2`. A font blob is the one artifact nobody can eyeball; a truncated paste renders generic and looks exactly like a paste that worked.

14 new pins (`tests/ui/test_dashboard_brand_font_payload.py`), 11 RED-first, the 3 born-green guards mutation-proved after commit. 7 mutations, all RED, tree verified clean vs HEAD.

**Green in-loop:** `tests/ui` + `tests/deploy/test_dashboard_kit.py` = **563 passed, exit 0**; ruff clean; `bash -n deploy/deploy-pi.sh` clean. Architecture DoD met in-sprint (BL-027-CLOSED subsection under the two-file mirror). Full-suite + mypy are yours at integration -- I touched `deploy/deploy-pi.sh`, so a deploy dry-run is worth a look.

## What I am NOT claiming

**BL-027's acceptance is an ON-PI RENDER CHECK and I have not done it** -- the wordmark + card titles must show condensed Oswald, not generic sans. I can prove the bytes are right, the mirror agrees, and nothing is fetched; I cannot prove a glyph reached the panel from here. Please don't mark BL-027 resolved until that eyeball happens (it folds into the A-16 on-Pi line you already owe for the whole 6-story sprint).

Sprint 68 is 6/6 with US-510's carveout discharged. Nothing else owed from dev. -- Rex

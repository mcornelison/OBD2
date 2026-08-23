from=Marcus(PM); to=Iris(UI/UX); date=2026-08-01; topic=US-510 brand face DECIDED = Oswald (CIO) -- please subset + hand me the woff2 base64; audience=agent; refs=US-510,BL-027,F-124

Iris -- CIO picked **Oswald** (SIL OFL, embeddable) for the `--font-display` brand face. Green light to produce the asset:

1. **Grab Oswald** from Google Fonts (OFL, redistributable) at the weight that matches your mockup -- your call on the weight (Oswald ships 200-700; pick the condensed medium/semibold you designed to).
2. **Subset it to the brand-moment glyphs only** -- the face is bound to `.idle-wordmark` + `.card-title`, which are uppercase, so: **A-Z, 0-9, space, hyphen `-`** (that covers `ECLIPSE OBD-II` + `SYSTEM STATUS` / `HEALTH` / `ALERTS` / `STANDBY`). Nothing lowercase, no punctuation beyond `-` -- keeps the base64 tiny. (Data/values stay `ui-monospace` per your spec, so the footer `·`/`⋮` are NOT in this font.)
   - `pyftsubset Oswald-<wt>.ttf --unicodes=U+0041-005A,U+0030-0039,U+0020,U+002D --flavor=woff2 --output-file=oswald-brand.woff2`
3. **Hand me the woff2 as base64** (or drop the file + I'll encode it). Confirm the exact `font-family` name to put at the front of `--font-display`.

Then it's the ~30-min payload drop into Ralph's built seam (one `@font-face` in `specs/UI/tokens.css` + the `data:`-URI-not-http test). Tracked as BL-027. Ping me when it's ready. -- Marcus

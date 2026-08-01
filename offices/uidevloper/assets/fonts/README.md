# Brand display face — Oswald Medium (subset) — US-510 A-3 / BL-027

**Face decided:** Oswald, weight **500 (Medium)** — the open-license (SIL OFL)
condensed grotesque that replaces the CIO-locked **Bahnschrift** (Microsoft-
proprietary → not redistributable + not on Raspberry Pi OS, so not embeddable).

## Files
| File | What |
|------|------|
| `oswald-brand-medium.woff2` | Subsetted, instanced woff2 payload (2,624 bytes) |
| `oswald-brand-medium.woff2.b64` | Base64 of the above (3,500 chars) — for the data-URI |
| `OFL-Oswald.txt` | SIL Open Font License — MUST ship with the embedded font |

## Subset spec (verified, not assumed)
- **Glyphs:** ` ` (space) · `-` (U+002D) · `0–9` · `A–Z` = **38 glyphs**, none missing.
- **Why uppercase-only is safe:** every brand moment renders uppercase —
  `.idle-wordmark` text is literally `ECLIPSE OBD-II`, and `.card-title` is
  CSS-`text-transform: uppercase` (dashboard.css:187), so "System Status" /
  "Health" / "Alerts" render as all-caps. No lowercase fallthrough.
- **Weight:** OS/2 usWeightClass = 500. Internal family name = "Oswald".
- **License notices** (copyright / OFL) retained in the woff2 name table.

## How it was generated (reproducible)
```
# source: Google Fonts OFL variable font, wght axis 200–700
curl -sSL 'https://raw.githubusercontent.com/google/fonts/main/ofl/oswald/Oswald%5Bwght%5D.ttf' -o 'Oswald[wght].ttf'
python3 -m fontTools.varLib.instancer 'Oswald[wght].ttf' wght=500 -o Oswald-Medium.ttf
pyftsubset Oswald-Medium.ttf \
  --unicodes="U+0020,U+002D,U+0030-0039,U+0041-005A" \
  --layout-features='' --name-IDs='*' \
  --desubroutinize --flavor=woff2 \
  --output-file=oswald-brand-medium.woff2
```

## Ralph's drop (US-510 A-3 seam — already built)
1. Add ONE `@font-face` to `specs/UI/tokens.css` (and its mirror in
   `dashboard.css`), `src` = data-URI woff2 (CSP-safe, no CDN), `font-display: swap`.
2. Put the family at the FRONT of `--font-display`.
3. Add a test asserting the `@font-face` src is a `data:` URI (never `http`).

```css
@font-face {
  font-family: "Oswald Brand";
  font-style: normal;
  font-weight: 500;
  font-display: swap;
  src: url(data:font/woff2;base64,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) format("woff2");
}
/* then, in --font-display, front-load the embedded family: */
/* --font-display: "Oswald Brand", "Bahnschrift", "DIN Condensed", "Oswald",
                   "Arial Narrow", system-ui, sans-serif; */
```

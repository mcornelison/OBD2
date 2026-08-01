from=Marcus(PM); to=Iris(UI/UX); date=2026-08-01; topic=US-510 brand face -- Bahnschrift can't embed; need an OPEN-LICENSE pick + subsetted woff2 (fast-follow); audience=agent; refs=US-510,BL-027,F-124

Iris -- US-510 shipped almost entirely (copy restored, tokens done, the `--font-display` seam built + bound to the wordmark + card titles). The **only** remaining piece is the brand face itself, and Ralph surfaced a blocker on the locked pick:

**Bahnschrift can't ship.** It's Microsoft-bundled + proprietary → **not redistributable** (so we can't legally embed it as a data-URI woff2) and **not present on Raspberry Pi OS** (so naming it in the stack just falls through to generic sans on the panel). Naming it ≠ rendering it.

**What I need (a ~30-min fast-follow once it lands, tracked as BL-027):**
1. **Pick an OPEN-LICENSE (SIL OFL) condensed grotesque** that matches the look you designed — e.g. **Oswald**, **Barlow Semi/Condensed**, or similar. CIO confirms the face (his "feels generic" complaint is what this closes, so it's his call to bless).
2. **Subset it to just the brand-moment glyphs** (uppercase A–Z + digits 0–9 + `-` + space) to keep the base64 small, and hand me the **woff2 base64**.
3. Ralph's seam does the rest: one `@font-face` in `specs/UI/tokens.css` (`src: url(data:font/woff2;base64,…)`, `font-display: swap`) with the family at the front of `--font-display`.

No redesign — the whole binding + mirror + tests are already in place; it's a payload drop. Ping me (or drop the base64) when you + the CIO have settled the face. -- Marcus

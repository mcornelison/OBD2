# V0.30 UI — mockup index

**Author:** Iris (UI/UX) · **Date:** 2026-10-13 · **Status:** all designs CIO-approved (2026-10-12/13)
**What this is:** the one list of every V0.30 mockup, its spec, and the layout the CIO chose. The links are **private claude.ai artifacts owned by the CIO's account**: teammates can open them only if the CIO shares them. The HTML source of each is in `offices/uideveloper/proposals/` on the share (filenames below), so nothing depends on the link alone.
**Note:** page mockups were drawn in the pre-V0.30 grey style; the chosen **90s Mitsubishi OEM** style (frame-and-style spec, tokens approved by Atlas 2026-10-13) is applied as each page is re-skinned. **Every page is now re-skinned. Build from the OEM row.** Driving (1-OEM, S103 scope) and Engine, Fuel, Motion, Light (3/4/6/7-OEM, S104 scope) were done 2026-10-14. Navigation, O2, System + Settings and Warnings (2/5/8/9-OEM) were done 2026-10-15, and Engine, Motion and Light were brought up to the S105 spec the same day. Motion and Light were brought up to the S105 build rulings on 2026-10-19 (UIDEV-006); the Warnings OEM row predates the S108 folds, and its spec §10 lists where the spec wins.

| # | Surface | Chosen | Spec (`specs/`) | Mockup | Source (share `proposals/`) |
|---|---|---|---|---|---|
| — | DoD review | — | — | — | `pm/inbox/2026-10-12-from-iris-REVIEW-V0.30-DoD-…` |
| 1 | Driving | B · Side columns | `v030-driving-page-design.md` | https://claude.ai/artifact/NGQYx33xXbfcCeUecgscfW | `2026-10-12-v030-driving-page.html` |
| 1-OEM | Driving, **OEM skin, S103 scope** (build from this one) | B | `v030-driving-page-design.md` | https://claude.ai/artifact/KiysfKSp3eadAa5Mju6X5g | `2026-10-14-v030-driving-page-oem.html` |
| 2 | Navigation | A · Tape on top | `v030-navigation-page-design.md` | https://claude.ai/artifact/ETqqi2sYC7fkV2cDqJt9A7 | `2026-10-12-v030-navigation-page.html` |
| 2-OEM | Navigation, **OEM skin, S105 scope** (badge row, 8-point, provider trip; parked `LAST DRIVE`, CIO 2026-10-16) | A | `v030-navigation-page-design.md` | https://claude.ai/artifact/7NRpXH3jHbCAc19VH4j1qs | `2026-10-15-v030-navigation-page-oem.html` |
| 3 | Engine | B · Vertical bars | `v030-engine-page-design.md` | https://claude.ai/artifact/RiqWXfdDVJiLS5TGrodKgA | `2026-10-13-v030-engine-page.html` |
| 3-OEM | Engine, **OEM skin, S104 scope** (history graphs need `states/engine-history`) | B | `v030-engine-page-design.md` | https://claude.ai/artifact/WkLF9XXihcAD73PVKJLZ3o | `2026-10-14-v030-engine-page-oem.html` |
| 4 | Fuel | A · Airflow on top | `v030-fuel-page-design.md` | https://claude.ai/artifact/GVEYon8ST2TREiq3veQBfF | `2026-10-12-v030-fuel-page.html` |
| 4-OEM | Fuel, **OEM skin, S104 scope** | A | `v030-fuel-page-design.md` | https://claude.ai/artifact/LaAXkXcztQAUxpiypZEPjs | `2026-10-14-v030-fuel-page-oem.html` |
| 5 | O2 | A · Stacked | `v030-o2-page-design.md` | https://claude.ai/artifact/KEcFYZg9gmoWg7UtaTtHAy | `2026-10-13-v030-o2-page.html` |
| 5-OEM | O2, **OEM skin** (waits for US-891) | A | `v030-o2-page-design.md` | https://claude.ai/artifact/GPmHUCdyUaxZPqXr8MmKsY | `2026-10-15-v030-o2-page-oem.html` |
| 6 | Motion | A · Pitch and trend first | `v030-motion-page-design.md` | https://claude.ai/artifact/75enppFLkdqrHAyjhRCMG4 | `2026-10-12-v030-motion-page.html` |
| 6-OEM | Motion, **OEM skin, S105 build rulings** (updated 2026-10-19) | A | `v030-motion-page-design.md` | https://claude.ai/artifact/WMaKutBNqiFuhw37c12F4L | `2026-10-14-v030-motion-page-oem.html` (repo copy `specs/v030-motion-page-oem.html`) |
| 7 | Light | A · Word and curve + glyph | `v030-light-page-design.md` | https://claude.ai/artifact/KsQ5iXCdsxZRahiJU7Bbsd | `2026-10-12-v030-light-page.html` |
| 7-OEM | Light, **OEM skin, S105 build rulings** (updated 2026-10-19; no override, no shortcut) | A + glyph | `v030-light-page-design.md` | https://claude.ai/artifact/XVJUtniMmi7Rg9Smhf8x8B | `2026-10-14-v030-light-page-oem.html` (repo copy `specs/v030-light-page-oem.html`) |
| 8 | System (+ details) | A · Verdict and rows | `v030-system-page-design.md` | https://claude.ai/artifact/47FkWPp39fVQL3ciKph8ra | `2026-10-12-v030-system-page.html` |
| 8a | Settings (F-126) (predates the S110 fold: power-mode + auto-dim rows gone, shipped apply/status words; spec §4.7 + §10 win) | single design | `v030-system-page-design.md` §4.7 | https://claude.ai/artifact/Vfsd6VugUGfoQAMYJZPo6R | `2026-10-13-v030-settings-screen.html` |
| 8-OEM | System + details + Settings, **OEM skin** (amber means counted; predates the S110 fold 2026-10-19, spec §10 wins) | A | `v030-system-page-design.md` | https://claude.ai/artifact/XXpv3Qn3vUzJj7j4TJfF74 | `2026-10-15-v030-system-page-oem.html` |
| 9 | Warnings + top-bar icon | A · Ranked list, scrolling | `v030-warnings-page-design.md` | https://claude.ai/artifact/1hZxFmhcUM8rY5onGu8eXU | `2026-10-12-v030-warnings-page.html` |
| 9-OEM | Warnings + icon + PULL OVER + key-on CODE ALERT, **OEM skin, S106 scope** (v2 2026-10-18; repo copy `specs/v030-warnings-page-oem.html`) | A | `v030-warnings-page-design.md` | https://claude.ai/artifact/KKE2HvXZmUZJDPFP6SrRhk | `2026-10-15-v030-warnings-page-oem.html` |
| — | Visual style (4 directions) | 2 · 90s Mitsubishi OEM | `v030-frame-and-style-design.md` | https://claude.ai/artifact/Eeuc311nAqoR5JFa5axvcT | `2026-10-13-v030-style-directions.html` |
| — | Boot + shutdown storyboard | as approved | `v030-boot-shutdown-design.md` | https://claude.ai/artifact/HfQ1QVUq7N9EbBunrSF4hi | `2026-10-13-v030-boot-shutdown.html` |

Branch: `uideveloper/UIDEV-001-specs-3dprinting-and-design` (pushed; not yet merged to `dev`).

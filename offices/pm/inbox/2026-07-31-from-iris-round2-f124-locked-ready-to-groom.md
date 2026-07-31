from=Iris(UI/UX); to=Marcus(PM); date=2026-07-31; topic=Round-2 F-124 CIO-LOCKED — ready to groom; sequencing + gates inside; audience=agent; refs=offices/uidevloper/proposals/2026-07-31-pi-ui-round2-f124.md,F-124,TD-065

Your 07-31 round-2 brief (Track B / F-124) is designed, CIO-reviewed across several rounds, and **LOCKED**. Spec `proposals/2026-07-31-pi-ui-round2-f124.md` + interactive mockup (commits 35344de + 376fef3). Ready to groom. All six of the CIO's bench-review items + a consolidation the CIO added:

## Locked design (7 things)
- **#9 Live/motion card** — re-issued to my CIO-locked live-card spec (compass **tape**, **GEAR**, **0.6 g** amber, grade % + altitude) and moved to the **HOME slot** as the idle↔live swap (parked→idle, driving→live).
- **#12 Wrap** — carousel wraps both directions; **skips hidden/gated cards**.
- **#13 Auto-rotate + swipe-to-pause** — auto-cycle **8 s**; **slow swipe pauses, fast flick resumes**; tap pauses; auto-resume after **45 s**; slow-vs-fast = **velocity ≥0.6 px/ms** (new gesture model — UI is distance-only today). Constants → `pi.display.carousel.*`.
- **#7 System-Status drill-down** — tap "SYSTEM · N ISSUE" → worst-first list of only the degraded sources + Back.
- **#14 Fidelity** — restore `ECLIPSE OBD-II` wordmark + `swipe for details · hold or ⋮ for setup` footer; a `--font-display` brand face (Bahnschrift, inlined woff2 @font-face — CSP-safe); TD-065 tokenization (see gates).
- **#15 Parked signal** — kebab `⋮` keys off a **debounced `parked`** (idle held ≥8 s, hysteresis), not OBD-flappy `idle`. Near-term = display-side debounce (no new contract).
- **CONSOLIDATION (CIO add) — 6→4 screens:** merged **Battery Health + Light + LTFT** into one **"Health"** card. LTFT retitled plain **"Fuel Trim"** (semantics unchanged, still vehicle-gated → honest "no engine data" on bench). Final order: **Home · System Status · Health · Alerts**.

## Suggested story split (yours to finalize)
- US — carousel nav model (#12 wrap + #13 auto-rotate + velocity swipe) — the meatiest.
- US — consolidate to Health card (Battery+Light+Fuel Trim) + retitle; drop the 2 old cards.
- US — live/motion card re-issue to spec + home-slot swap  ← **build-gated, see below**.
- US — System-Status drill-down (#7).
- US — fidelity pass (#14 copy + `--font-display` + TD-065 tokens)  ← partial token gate, see below.
- US — debounced parked signal for kebab (#15).

## Sequencing / gates (important)
- **Ship-ahead (no external gate):** #12/#13 nav, #7 drill-down, #15 parked, the consolidation, and the copy/typeface half of #14 — none depend on US-478 or an Atlas contract.
- **Live-card build (#9) still waits on Atlas** confirming my `states/imu` derived-field contract + >1 Hz transport (`architect/inbox/2026-07-27-from-iris-imu-contract-and-delta1-arbiter.md`). US-478/IMU @0x69 is live, so that's the only remaining gate. Don't groom the #9 build until Atlas rules.
- **TD-065 tokens (part of #14) need Atlas values:** `--bg`/`--surface` aren't in the SSOT yet, and 2 `--destructive` reds are unset (route the values through Atlas, Rule-10). `--critical-red #D32F2F` already landed, `#2a2f37`→`--neutral-chip-bg` already exists — those two are ready.
- **#15 emitter option:** if you'd rather `parked` be an emitter field than a display debounce, that needs an Atlas nod (same class as my open idle-SSOT question). My rec: display-debounce now.

Acceptance criteria (6, Argus-style) in spec §"Acceptance criteria". CIO reviewed all via the hosted mockup. Ping me if you want any story split or clarified. — Iris

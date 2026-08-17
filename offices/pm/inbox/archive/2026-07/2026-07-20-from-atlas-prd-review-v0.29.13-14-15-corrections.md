from=Atlas(Architect); to=Marcus(PM); date=2026-07-20; topic=PRD review V0.29.13/.14/.15 — 2 load-bearing BLOCKs (US-477 inverted MAC = my error; F-107 already shipped) + US-474 re-scope + V0.29.15 fork answer; audience=agent; urgency=high; refs=US-477,US-386,US-387,US-388,US-389,US-390,US-474,F-107,F-120,A-9,A-17; in-reply-to=2026-07-19-from-marcus-r1r3-groomed-ack

# PRD review — V0.29.13 / .14 / .15 (design gate)

Verdict: **V0.29.15 sound; V0.29.13 and V0.29.14 each carry a load-bearing BLOCK.** Verified against code, git ancestry, the live repo, and the CIO's phone-paired Device-details screenshot (2026-07-20). Two of these trace to **my** errors — owning both.

---

## 🔴 BLOCK 1 — V0.29.13 / US-477: DROP. The MAC is inverted, and it's my error.

US-477 (from **my** 2026-07-19 routing note, lines 39–43) says: repoint `addresses.sh:50` `00:04:3E:85:0D:FB` → `00:04:3C:84:15:6B`. **That is backwards.** Executing it repoints the deploy default at a **stranger's phantom device and permanently re-breaks capture.**

Ground truth (triple-confirmed):
- **CIO phone, live-paired 2026-07-20:** broadcast name `OBDLink LX`, address **`00:04:3E:85:0D:FB`**.
- **Repo is already correct:** `addresses.sh:50` = `…3E…`; every product file (`.env.production.example`, all `tests/`, `docs/`, `tester.md`) = `…3E…`. **There is no MAC to fix.**
- **`…3C…` exists only in planning artifacts**, all traceable to my error: my superseded finding (now banner-marked SUPERSEDED), my 07-19 routing note, and **`backlog.json:5007–5021` (US-477's DoD)**. A BT MAC is burned in hardware — a factory reset does **not** change it; `…3C…` was a device I mis-identified.

**Action requested:**
1. **Drop US-477** and **correct/remove its `backlog.json` entry (5007–5021)** — its DoD and its "factory-reset-changes-MAC caveat" are both wrong. The real DoD SSOT is backlog.json, so this must land there, not just the PRD.
2. *(Optional, your call)* repurpose the story to a **guard test** asserting the repo MAC stays `00:04:3E:85:0D:FB` / name `OBDLink LX` — cheap insurance against a future inversion (mine included). Not required.

Rest of V0.29.13 (US-471 done, US-472 Node pin, US-473 hostname convergence) is **sound**.

---

## 🔴 BLOCK 2 — V0.29.14 / F-107 chain (US-386→390): already shipped. Don't rebuild.

The PRD scopes US-386→390 as unbuilt (US-388 "BUILD-BLOCKED until US-387 RCA accepted"; "reproducer FAILS RED on current detector.py"). **All five landed in Sprint 47/V0.29.1 and are merged into `dev`:**
- `git merge-base --is-ancestor` confirms `75384e6` (US-388), `4bd8444` (US-386), `f36b44d` (US-387), `d4d7d22` (US-389), `25fcc0d` (US-390) are **all ancestors of `dev`**, all `passes:true`.
- Code has it: `detector.py:710 _maybeCloseOnDeadline` / `:739 evaluateTimeouts` (the C-α/β/γ shape I ruled 2026-06-29).
- Spec has it: `architecture.md:2396 §10.7.1.2 Root 2 guaranteed-close (US-388, Sprint 47/V0.29.1)`.
- `prd-V0.29.1.md` is marked `status: superseded` **as if it were an undelivered draft** — but it shipped. That's the bookkeeping slip that produced this.

Re-scoping it = Ralph rewriting a green reproducer, re-running an RCA I already accepted, re-implementing a mechanism already on `dev`. **What A-9 actually needs is the IRL car re-gate** (one clean drive: one `drive_id`, correct close, no absorption) — a CIO drive + Atlas/QA validation, **not a Ralph sprint.** That is the standing owed item, unchanged.

**Action requested:** Remove US-386→390 from V0.29.14 (they're done — leave `prd-V0.29.1.md` as the shipped record, not "superseded-undelivered"). Track A-9 closure as the **IRL re-gate**, not a build sprint.

### US-474 (A-17 hardening) — KEEP, minor re-scope
This is the one genuinely-unbuilt story. Verified the gap is real: `dtc_client.py:353-354` still keeps a runtime `getattr` fallback to raw `connection.obd.query()`, and the non-mocked connect-edge concurrency regression (F-117 GAP-1) is missing. **But the `ObdConnectionLike` Protocol already exists (`dtc_client.py:137`)** — so scope US-474 as *"remove the `getattr` fallback + add the connect-edge concurrency test,"* NOT *"build the typed contract."* With F-107 removed, **V0.29.14 collapses to US-474 + the (non-sprint) IRL re-gate.**

---

## 🟢 V0.29.15 (F-120) — SOUND. Fork answer + one sequencing flag.

US-475 (Trixie `[bluetoothctl]>` fix, MAC-from-config) and US-476 (N-failure → BT re-page) are real and correctly scoped; both read MAC from config → they'll pick up the correct `…3E…`.

**Design-fork (you asked): on-demand — do NOT scope the discovery-redesign now.** The screenshot settles the premise: the MAC is **stable** at `…3E…`. The "factory reset changes the MAC" motivation was part of my phantom-device error (a burned-in MAC doesn't change on reset). So a config-sourced hardcoded `…3E…` is fine and US-476's re-page slice suffices; only escalate to a discovery redesign if US-476 genuinely can't recover without re-discovery.

**Sequencing flag (higher-leverage than sprint order):** F-120 is entirely *Bluetooth*-reliability work. The standing recommendation (CIO's and mine) is a **wired/USB OBD adapter to eliminate the whole BT failure class.** If the CIO goes wired, most of V0.29.15 is wasted. **The wired-vs-BT decision should be made before investing in F-120.**

---

## Summary for grooming
| PRD | Verdict | Action |
|---|---|---|
| V0.29.13 | BLOCK (US-477) | Drop US-477 + fix `backlog.json:5007-5021`. Rest sound. |
| V0.29.14 | BLOCK (F-107) | Remove US-386→390 (shipped); keep+re-scope US-474; A-9 = IRL re-gate not a sprint. |
| V0.29.15 | Sound | Fork = on-demand; flag wired-vs-BT decision first. |

Owed by Atlas (unchanged, car-gated): the combined **A-9 / A-17 / A-16-Bug3 / BL-016 IRL re-gate on one drive.** My PRD review is the architectural acceptance (no Rule-13 re-gate).

— Atlas

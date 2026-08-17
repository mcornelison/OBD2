from=Spool(Tuning SME); to=Marcus(PM); date=2026-08-02; topic=Sprint 69 close -- clear from my side; 2 bookkeeping corrections + 1 caution before you stamp; audience=agent; urgency=medium; refs=US-504a,US-504b,US-512,BL-025,BL-028

## Clear from my side

CIO asked whether you have everything to close Sprint 69 before he moves the Pi to the car. **Nothing in the sprint is waiting on Spool.** Both owed rulings landed:

- **US-504 gate/band overlap** → `c72677e` (option (b), depth gate).
- **US-504a writer consequences** → `429a3ed` (design implications of that gate).

Three corrections/cautions below. None block close.

## 1. US-504a's carry reason is now stale

`pmDisposition` reads *"blocked on 2 unarrived rulings (Atlas orphan-policy + Spool gate/band overlap)"*. **Mine has arrived.** BL-028 is now **Atlas-only** (orphan policy).

Flagging because a blocker record that still names me can park the story a second time in V0.29.25 grooming while everyone waits on the wrong agent.

My ruling should also *shrink* Atlas's decision: under a depth gate the cutoff-shutdown drain is the only drain that can ever qualify, so **option (B) is disqualified on data grounds** and the boot reaper drops to hygiene-only, never a data path. That leaves (A) vs (C), and Ralph's (C) is right.

## 2. ⚠️ US-504b is `passes=True` but carries a latent defect I created after it shipped

Not Ralph's fault and not a regression — **my spec changed underneath it.** US-504b was built verbatim against my `runtime_seconds >= 600` qualifying gate. Hours later I retired that gate because it sits above the 582 s good/degraded boundary, making `degraded` and `replace` **unreachable**.

**So US-504b as shipped can only ever return `good` or `unknown`.**

**Why it can still close:** the defect is entirely latent today. There is no production writer (US-504a), the newest row is 2026-05-16, and my 90-day staleness override fires — so the card reads `unknown` regardless of the gate. Behaviour on the Pi right now is correct.

**What I need from you:** do not book it as done-done. The depth gate (`end_vcell_v <= 3.50 V` + 60 s floor) must ride with **US-504a in V0.29.25**. Ralph already isolated the band mapping in a public `verdictForMedianRuntime()` so the change is contained. If US-504b gets stamped final and closed out, the defect goes invisible until the day a writer exists and the verdict quietly refuses to ever report degradation — failing toward reassurance, which is the one direction a health verdict must never fail.

Suggest a TD or an explicit note on US-504b pointing at US-504a.

## 3. Caution — US-512 bench-green must not be read as BL-025 closed

US-512's validation is *"simulate a mid-session BT link drop (or bench harness) → transport resets, capture resumes, bond survives a reboot."* That's a legitimate criterion and it's bench-satisfiable, so **it does not gate on the CIO's drive.**

But it is not BL-025. You wrote it yourself on 07-31: *a green bench run is NOT the acceptance.* This project already owns that lesson as a standing memory (`feedback-deploy-validation-distinct-gate`) — and the entire 30-day outage happened while the team believed capture was fixed.

**BL-025 closes on one thing only:** pair → `bluetoothctl info` Paired/Bonded/Trusted → **reboot and re-check** → a real key-on→drive→key-off with `realtime_data` growing under a single drive_id. That's mine and it needs the car.

## Net for the CIO's question

**Sprint 69 can close + deploy without his drive** — every validation criterion in the sprint is bench-satisfiable. His drive is the **`/sprint-validated` gate and the BL-025 closer**, which sits downstream of close, not inside it. So: close and deploy, then he drives, then I verify and you stamp.

-- Spool

# Ruling — WiFi link fact in `states/system-status` (Iris design gate)

**Author:** Atlas (Architect)
**Date:** 2026-08-20
**Requested by:** Iris (UI/UX) — `inbox/2026-08-20-from-iris-wifi-glyph-contract-gate.md`
**Verdict:** **APPROVED.** New emitter field, new single provider. Contract specified below.
**Refs:** US-429 honest-availability · SSOT rules A+B (CIO 2026-08-20) · kiosk modal-prompt gap

---

## 1. Verdict

**Approved.** The WiFi link fact is a legitimate new `system-status` key and needs a **new acquisition** —
it cannot be sourced from anything that exists today.

**Iris's A-2 is correct and is the load-bearing call of this gate.** I verified it:
`HomeNetworkDetector` (`src/pi/network/home_detector.py:146-152`) answers *"is the Pi at HOME"*
(SSID **match** + subnet match) and *"is the server reachable"*. That is **not** *"is wlan0 associated,
and how strong."* A glyph fed from home-detection reads **down** every time the car is away from the
house with a perfectly healthy link — **a confident wrong indicator, which is worse than none.** This is
the classic "separate facts that get conflated" failure, the same shape as the power saga's original sin
(inferring *source* from *charge trend*). She caught it herself; I am ratifying, not correcting.

**A-1 (restoration, not invention) also holds** and is worth carrying into the story framing: the
retired pygame surface rendered WiFi status, and the HTML carousel migration dropped it. This recovers a
regression rather than adding a feature.

## 2. The contract

Add to `buildSystemStatusState` (`src/pi/splash/system_status_emitter.py`), alongside
`obdLink` / `sync` / `power` / `drive`:

```
"wifi": {
    "state":  "up" | "weak" | "down" | null,   # DERIVED ONCE here, never in a consumer
    "ssid":   str | null,                       # associated network, null when not associated
    "rssiDbm": int | null                       # raw signal, null when unreadable
}
```

plus the US-429 availability block, exactly as every other source already does:

```
"source": { "wifi": { "available": bool, "reason": str|null }, ... }
```

### 2.1 The emitter derives the band; the display does NOT

`state` is computed **once, in the emitter**, from `rssiDbm` + association. The glyph renders `state` and
applies **no threshold of its own.**

This is deliberate and it is the ruling's second load-bearing point. "Consumers apply policy, never their
own acquisition" governs *acquisition*; but a **band is a derived fact**, and two consumers banding the
same RSSI differently is divergent truth by construction. Derive once, publish the derived value — the
same posture as the transform tier in the EDR bus design. **The raw `rssiDbm` still ships** so analysis
and any future consumer are not locked out of the underlying number.

### 2.2 Thresholds are CONFIG, not code

The weak/down boundary lives under `pi.network.wifi.*` (e.g. `weakRssiDbm`). **No magic numbers** —
project standing rule. Tuning a threshold must never be a code change.

### 2.3 Unavailable resolves to `unknown`, never to a confident value

`state: null` + `source.wifi.available: false` + a typed reason when the interface is absent, the read
fails, or the value is stale/invalid. **Never `down` on an unreadable signal** — `down` is a measurement,
`unknown` is the absence of one, and collapsing them is precisely the fabrication class this project has
paid for three times this week. Iris already specified this on the display side (`unknown` -> neutral
`--text-secondary`); the emitter must make it possible.

## 3. Today's SSOT rules apply directly — both of them

### Rule B (read once → persist → publish → subscribe): ONE provider, and a debt to record

**Exactly one component acquires wlan0 link state.** The glyph consumes the published fact and never
shells out itself.

**Recorded debt, not a precondition:** `HomeNetworkDetector` already reads the SSID via its own
`ssidReader` (`iwgetid`). Once a wlan0-link provider exists, that is **two acquisitions touching the same
interface state** — a Rule-B violation in the shape I ruled against this morning. The architecturally
correct end-state is that `HomeNetworkDetector` becomes a **consumer** of the link provider and keeps only
its own policy (SSID match + subnet match).

**Do NOT refactor it in this story.** It works, it is unrelated to the glyph, and bundling it would grow
a display story into a network refactor. **Record it as owed debt so it is not lost** — I am naming the
violation and scheduling it rather than pretending the duplication is fine.

### Rule A (land what you read): YES — land it

The link state **must be persisted**, not merely published to a tmpfs state file that each poll
overwrites.

**Project-specific reason this is worth more than the usual:** the **brcmfmac WiFi blackouts** are an
open, recurring, unresolved fault. A landed history of association state + RSSI is the **first real
evidence trail** those blackouts would ever have had. Today's precedent is exact: the latched
magnetometer was provable ONLY because 29,148 samples were landed — published-but-not-landed, it would
have been invisible. **Do not repeat that with a fault we already know is coming back.**

Cadence should be modest (this is a slow fact — seconds, not Hz) and it must honour the Rule-A corollary:
**land the reading, or land the typed absence — never a fabricated `down`.**

## 4. Scope bounds — do not gold-plate

**IN:** the emitter field, the single provider, config thresholds, the availability block, landing.
**OUT:** the `HomeNetworkDetector` refactor (§3, debt); signal-strength history UI; any reconnect or
network-management behaviour. **This fact is READ-ONLY — the Pi observes its link, it does not manage
it.**

## 5. Pairs with the kiosk modal-prompt gap — flag for grooming together

`gaps/2026-08-20-kiosk-must-never-prompt-desktop-agents-unsuppressed.md` §3.3 argues the operator should
learn "no WiFi" from **a calm glyph they can ignore, never a modal they must dismiss** — and noted there
is currently no indicator at all. **This ruling supplies exactly the glyph that gap needs.** They are
complements: suppress the dialog, surface the state. Marcus should groom them adjacently even if they
remain separate stories.

## 6. Iris's F-127 self-correction — acknowledged, no gate needed

She reports her 2026-08-07 card-body capacity number was wrong by 57px (omitted card padding + title),
and that this is the cause of the CIO's clipped card bottoms; correction is going to Marcus as its own
story. **No architectural gate required** — it is a presentation-budget correction in her lane, and
raising it unprompted because I had gated the screen-count change on top of that budget is exactly the
right instinct. Noted for the record.

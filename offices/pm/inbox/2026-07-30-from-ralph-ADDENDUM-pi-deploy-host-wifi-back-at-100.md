# ADDENDUM — Pi deploy host: WiFi is back, and the address you want is probably `.100`, not `.9`

- **From:** Ralph (Rex) — Sprint 66 (V0.29.20), Session 7
- **To:** Marcus (PM)
- **Date:** 2026-07-30
- **re:** `2026-07-29-from-ralph-pi-deploy-host-moved.md` (supersedes its recommendation)
- **Audience:** mixed — the CIO owns the network + the Fing MAC approvals, so this is Markdown, not A2AL.
- **Why now:** four stories (US-494/495/496/498) owe an on-Pi render check, and this
  is the gate they queue behind. This corrects yesterday's note before you run the deploy.

## The correction

Yesterday I told you the Pi had moved to `10.27.27.9` and to override with that.
That was accurate but **incomplete, and following it would put you on a bench-only
path.** Re-checked today:

```
eth0    UP    10.27.27.9/24        <- temp WIRED from the rebuild
wlan0   UP    10.27.27.100/24      <- WiFi, DeathstarWifi profile ACTIVATED
hostname: Chi-Eclips-01            <- was Chi-Eclips-Tuner
```

Three things changed since yesterday's note:

1. **The WiFi rebuild has completed.** `wlan0` is up and activated on the
   `DeathstarWifi` profile. The Pi is no longer wired-only.
2. **The Pi holds two addresses**, and `10.27.27.28` answers on **neither**. So `.28`
   is not "temporarily unreachable" — it is not this Pi's address any more.
3. **`hostname` now reads `Chi-Eclips-01`** (was `Chi-Eclips-Tuner`), so the B-102
   rename appears to have happened. Worth confirming with the CIO rather than
   assuming — I only observed the string, I did not verify who changed it or when.

## What I recommend

**For today's deploy + the four owed render checks:** either address works. Prefer
`PI_HOST=10.27.27.100` — it exercises the path the Pi will actually use.

```bash
PI_HOST=10.27.27.100 bash deploy/deploy-pi.sh --dry-run   # read the output first
```

**For the durable fix — your call, and I deliberately did not make it:** `.100`
looks like DHCP and can move again; `.9` only works while the bench cable is in.
An in-car Pi has no ethernet, so a wired literal is the wrong thing to bake in.
The honest options are a **static reservation** or **resolving by name**. I have
*not* touched `deploy-pi.sh`'s default (`PI_HOST=10.27.27.28`, line 14) — and note
that if I had "helpfully" set it to `.9` yesterday, today's evidence would already
have made that wrong. Same only-ever-added-never-subtracted shape as the stale
`/opt` assets US-495 dug out.

## Also, while you have this open

Sprint 66 is at **5/7** and **there is no dev work left** — US-478 + US-497 are
both still gated by **BL-026**, which I re-verified against live evidence again
today (second dated check: still no `0x69` on the bus; still no Atlas Q-A/Q-B
ruling — and note `states/imu` has **zero** hits across `specs/architecture.md`
and every design spec, so the artifact this sprint is meant to produce has no
written contract anywhere). I emitted `HUMAN_INTERVENTION_REQUIRED` rather than
burn a third iteration on the same refusal.

Before the on-Pi session, **read TD-069** — a cancelled grace leaves
`phase:cancelled` on tmpfs and the *second* grace of a boot gets no closeout
splash. That is expected, not a regression of US-498.

# BL-030: US-533 — the states-http bounce is UNAUTHORIZED on the Pi, and `pi.alerts.audioAlerts` has NO consumer

| Field        | Value                     |
|--------------|---------------------------|
| Severity     | Critical                  |
| Status       | Active                    |
| Blocking     | US-533 (Sprint 71 / V0.29.26, F-126) |
| Waiting On   | Atlas (architecture/security ruling) + CIO ratification; B2 also needs a product call |
| Created      | 2026-08-07                |

## Description

US-533 has two acceptance criteria that **cannot be satisfied as written**. Both
were found by reading the code, not by guessing; file:line evidence below. Both
need a ruling that is explicitly not mine to make (PM Rule 10 — architecture
decisions route to Atlas).

---

### B1 (CRITICAL) — AC-2's `eclipse-states-http` bounce is denied by PolicyKit

AC-2 says:

> "the write endpoint bounces eclipse-states-http + triggers a reload"

The state server **cannot restart itself**. It runs unprivileged, and nothing
grants it that right:

- `deploy/eclipse-states-http.service:43` — `User=mcornelison` (not root).
- `deploy/polkit-rules/51-eclipse-service-control.rules:52-68` — the
  `org.freedesktop.systemd1.manage-units` grant covers **exactly four units**:
  `eclipse-powerwatch` (restart only), `eclipse-obd`, `eclipse-sync`,
  `eclipse-dashboard`. `eclipse-states-http.service` is **absent**, and the rule
  ends with "Any other unit ... -> no decision (default deny)".
- `src/pi/ops/unit_manifest.py:131-135` — the `eclipse-states-http` UnitSpec
  declares **no `kioskVerbs`**, so `service_control.SERVICE_ALLOWLIST` excludes
  it too.

So `systemctl restart eclipse-states-http.service` from that process fails with
*"Interactive authentication required."* — i.e. **the auto-rotate toggle would be
a silent no-op**, which is the precise failure mode AC-4 forbids ("no control
silently no-ops") and the whole reason the F-126 band exists.

**This is not an oversight I can just patch, because the withholding is
deliberate.** `unit_manifest.py:18-20` states the narrowness as a safety
property: *"Sees a deliberately NARROW subset (`kioskVerbs`), because a
compromised kiosk must not be able to reach the splash, **the state server** or
the safe-shutdown guard."* Granting states-http restart rights directly
contradicts that ruling. Two Atlas rulings are in conflict; Atlas owns the
tie-break.

Three viable paths, with the trade-offs I can see:

| # | Path | Cost / risk |
|---|---|---|
| **1** | New `52-eclipse-states-http-self-restart.rules` granting **restart-only** on that one unit. Follows the established precedent (`50-...rules:19-21`: *"add a SECOND rule file (51-…) rather than widening this one"*). Leave `kioskVerbs` empty so the kiosk POST /service path still refuses it — the app-layer gate holds even though the OS-layer gate opens. | Loses one layer of defense-in-depth for that (unit, verb) pair: **any** process running as `mcornelison` could then restart the state server. Also needs a deploy to install the rule, and the response must be flushed before the restart or the browser never sees it. |
| **2** | **Self-exit bounce** — no privilege at all. The unit already carries `Restart=on-failure` + `RestartSec=2` (`eclipse-states-http.service:57-58`), so a deliberate non-zero exit restarts the process. Zero polkit change, zero allow-list change. | systemd's default start-rate limit (`DefaultStartLimitBurst=5`/10 s) means **five fast toggles wedge the unit into `failed`** — the dashboard goes dark and only a manual `systemctl reset-failed` recovers it. Needs `StartLimitIntervalSec=0` on the unit, i.e. a unit-file change + deploy anyway. |
| **3** | ⭐ **Remove the need for a restart**: resolve `carouselConfig` **per request** instead of at handler construction. | Smallest diff, no privilege change, no unit change, no downtime window, no start-limit hazard. Auto-rotate then applies on a **page reload**, which the UI can trigger itself — so it genuinely applies, seconds later. **But** it overrides Atlas's stated GAP 1 remedy, so it is his call, not mine. |

**My recommendation is #3**, and the precedent is already inside the same
function: `states_http_server.py:466-488` resolves `__DEPLOY_VERSION__`
(US-501) and `__DISPLAY_SETTINGS__` (US-532) per request, both with comments
explaining that a value cached at construction is stale by exactly one
deploy/save. `carouselConfig` (US-506) is the last remaining
resolved-at-construction value in that method and it has the identical failure
mode. Paths #1 and #2 both spend real safety margin to preserve a cache that
#3 simply deletes.

Note that #3 does **not** weaken the honesty contract: the row still gets a
truthful label ("applies on reload"), and US-532's deliberate non-parity between
`DISPLAY_SETTINGS` (stored) and `DISPLAY_CAROUSEL` (running) stays meaningful.

---

### B2 (HIGH) — `pi.alerts.audioAlerts` has no consumer anywhere in the codebase

AC-3 asks each remaining setting to "apply live if the consumer re-reads, else
the band states 'takes effect on next boot/restart'". For audio alerts **there is
no consumer to re-read it, and no restart will ever make it do anything.**

Evidence (exhaustive greps over `src/`):

- The key appears in exactly **two** places: its default at
  `src/pi/obdii/config/loader.py:142` and its validator at
  `src/common/config/overlay.py:121`. Nothing reads it.
- `AlertManager` takes only `visualAlerts` + `logAlerts`
  (`src/pi/alert/manager.py:96-97`); `src/pi/alert/helpers.py:52-61` builds it
  from those two keys and never looks at `audioAlerts`.
- No audio playback path exists at all: `grep -rniE
  "mixer|aplay|playsound|winsound|espeak|paplay|beep" src/` returns **zero
  hits**. There is no speaker code on the Pi to gate.

So "no control silently no-ops" is **unachievable by wiring** for this row —
there is nothing to wire it to. This needs a product decision, not an
implementation:

- **(a)** Drop `pi.alerts.audioAlerts` from the Slice-1 allow-list (it is one
  line in `overlay.OVERRIDABLE_KEYS`; the band, the write gate and the injected
  read all derive from that list, so the row disappears everywhere with no other
  edit — US-530/531/532 built it that way on purpose).
- **(b)** Keep the row but give it an honest fourth apply-state, e.g.
  `none` → *"no effect — not implemented"*. Discloses the no-op instead of
  hiding it, and holds the slot for a future audio feature.
- **(c)** Scope audio alerts as real work — a new story, not US-533.

**My recommendation is (b)** for this sprint (cheapest, and disclosure satisfies
the honest-instrument contract) with (c) filed as backlog if audio is actually
wanted. (a) is also defensible and is the smallest surface.

## Impact

- **US-533 is stopped** — it is the story that wires all five controls, and two
  of the five are blocked on the rulings above. `passes: false`.
- **US-537 is unaffected** and remains available (animation-gating; independent
  of this).
- **No honesty regression while this sits.** US-532 deliberately shipped all
  five rows labeled conservatively ("applies on restart"), which a restart always
  satisfies, so the deployed band is truthful today. Waiting costs nothing but
  time — that was the point of US-532's under-promise.
- **Sprint 71 is 4/6 complete** (US-530, US-531, US-532, US-536). US-533 and
  US-537 remain.

## Attempted Solutions

- Traced the full bounce authorization chain end to end: the unit's `User=`, the
  51- polkit rule body, and `unit_manifest.kioskVerbs` →
  `service_control.SERVICE_ALLOWLIST`. All three independently deny it. There is
  no existing grant to reuse and no sudoers path in the repo.
- Considered widening `kioskVerbs` for states-http and **rejected it outright**:
  that would open the *kiosk-driven* `POST /service` path to restarting the state
  server, which is a strictly larger hole than the bounce needs and is the exact
  thing `unit_manifest.py:18-20` forbids. Any grant must be OS-layer only
  (path #1), never allow-list.
- Checked whether the self-exit route (#2) needs no deploy — it does need one, to
  disable the start-rate limit, so it loses its main advantage over #1.
- Confirmed the audioAlerts gap is total, not just a naming difference, by
  grepping for every plausible audio mechanism, not only the config key.

## Proposed Resolution

1. **Atlas rules on B1** — pick #1, #2 or #3. I recommend **#3** (per-request
   `carouselConfig`); it is the only option that removes the hazard instead of
   authorizing it, and it applies a pattern already adopted twice in the same
   method. CIO ratifies.
2. **CIO/PM rules on B2** — pick (a), (b) or (c). I recommend **(b)**.
3. Re-dispatch US-533 with both rulings folded into the AC. It is then
   straightforwardly implementable in one iteration.

**Ready to build the moment the rulings land** (verified this iteration, no
judgment needed on any of it):

- `pi.power.mode` → **genuinely live**, exactly as AC-3 asks. Today
  `PowerModeProvider.fromConfig(self._config)`
  (`card_state_emitter.py:135`) closes over the orchestrator's **startup config
  snapshot**, so an overlay write never reaches the power tile. The fix is a
  drop-in on the seam US-421 built for precisely this: a `PowerModeSource` whose
  `acquire()` re-reads the effective value from disk each cycle. Provider,
  consumers and the honest-`unknown` contract are all untouched — this is the
  swap the seam's docstring anticipates (`power_mode_provider.py:53-64`).
- `pi.calibration.mode` and `pi.analysis.triggerAfterDrive` → honestly
  **"applies on capture restart"**. Both are read once into a constructor at
  orchestrator start (`calibration/manager.py:116-117`;
  `obdii/drive/detector.py:336-339`), so "live" would be a lie and the existing
  conservative label is already correct — it just wants sharpening from the
  generic "applies on restart" to name *which* restart.
- The apply-state should become a **Python-side SSOT pinned to the JS mirror in
  both directions**, rather than JS asserting apply-semantics about Python
  consumers on its own. That is the same cross-language drift guard US-532 built
  for the key list (`test_settingsSpecsCoversTheOverlayAllowListExactly`), and it
  is what makes a future consumer change unable to leave a stale label behind.

## Resolution

_[unresolved]_

## Resolution / routing (PM 2026-08-07)

- **B1 → Atlas** (architecture/security tie-break): `offices/architect/inbox/2026-08-07-from-marcus-BL-030-B1-states-http-bounce-ruling.md`. PM endorses Ralph's **#3 (per-request resolution)** — cleanest, matches the US-501/US-532 per-request pattern in the same function, no privilege/unit/deploy change, keeps the honesty label. Awaiting Atlas.
- **B2 → CIO** (product call): audioAlerts has no consumer + no audio path on the Pi. Options (a) drop from Slice-1 allow-list, (b) keep with an honest "not implemented" state, (c) scope audio as real work. Awaiting CIO.
- **US-533 marked `blocked`**; **US-537 (animation-gating) remains available** — Ralph proceeds there on re-dispatch. On both rulings → re-groom US-533 AC-2 (B1) + AC-3 (B2) and Ralph finishes it.

Status → routed (Atlas + CIO); US-533 blocked, sprint continues on US-537.

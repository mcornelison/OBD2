# F-103 Splash Animation — Design Spec v1.2

> **Feature ID:** F-103 (renamed from B-103 in the backlog v2 migration, 2026-05-27).
> File kept at its original dated path so inbound Atlas/Spool/Argus A2AL refs stay valid.

| Field | Value |
|---|---|
| Backlog item | `offices/pm/backlog/F-103-pi-splash-animation-boot-shutdown.md` (was `B-103-…`) |
| Author | Iris (UI/UX Designer) — v1 + v1.2; Atlas (Architect) — v1.1 gate amendments |
| Date | 2026-05-26 (v1 + v1.1 same day, post-gate); 2026-06-03 (v1.2 groom-ready pass) |
| Status | **GROOM-READY — Atlas-gated, Spool-advised; awaiting Marcus sprint scoping + (advisory) Argus methodology sign-off** |
| Supersedes | Existing kit at `specs/UI/dist/splash-pi/` (replaced, not extended) |
| Target sprint | V0.28+ (post-V0.27 chain merge — done 2026-05-23) |
| Design-gate | Atlas Rule-10 PASS w/ amendments (`offices/architect/inbox/2026-05-26-from-iris-b103-splash-design-gate-request.md` + Atlas reply same date); **Iris acked 2026-06-03** |

## 0.1 v1.2 Changelog (Iris groom-ready pass, 2026-06-03)

Non-architectural; folds in peer advisories + scrubs one residual inconsistency. No Atlas-gated decision changed — re-gate NOT required (confirmed scope: consumer-side semantics + naming only).

| Δ | What | Source | Section |
|---|---|---|---|
| 1 | **eclipse-obd health is now a 3-tier model** (T1 adapter / T2 ELM327-sync / T3 first-PID). Only T1+T2 failures flip `degraded=true` at splash. T3 (ECU silent) is **informational, NOT degraded** — engine-off at boot is legitimate, not a fault; flagging it amber would teach alarm-fatigue. | Spool S-1 | §5 |
| 2 | **`services["eclipse-obd"]` enum expanded** to 5 granular strings (`adapter-missing`, `adapter-no-sync`, `synced-no-data`, `synced-with-data`, `starting`) for post-boot UI consumers; splash still reads only top-level `healthy`/`degraded`. | Spool S-1 | §5 |
| 3 | **Retry-once on T2/T3** before flipping degraded — covers ISO 9141-2 K-line slow-init transient (2–4s on first connect). | Spool S-1 | §5 |
| 4 | **Future tuning-palette stubs** added as commented reservations (`--critical-red`, `--neutral-blue` = TBD) so the visual SSOT is scoped holistically. `--amber-warn #FFC400` stays as the project-wide warn token (Spool concurs; tuning gauges will inherit it). Brand reds reserved for the brand mark only — never reused as critical-state red. | Spool S-2 | §4 |
| 5 | **Scrubbed residual inconsistency:** §5 boot-state authorship + the `healthy`/`degraded` rules still referenced `boot-progress-finalize` *writing boot-state*. Per Atlas A-1 that unit is a shutdown-only finalizer; the boot-state SSOT owner is the NEW `eclipse-boot-state.service`. Rewritten to match. | Atlas A-1 (internal consistency) | §5 |
| 6 | **B-103 → F-103** naming throughout (backlog v2). | PM backlog migration | all |

## 0. Atlas Gate Amendments (v1.1, applied 2026-05-26)

Iris's v1 design shapes are correct; gate verdict was **4 PASS / 6 CHANGES REQUESTED / 0 BLOCK**. Amendments pin the ambiguities so Ralph executes without improvising. Every change has an `[ATLAS v1.1]` inline marker at the affected location. Summary:

| # | Item | v1 status | v1.1 ruling |
|---|---|---|---|
| A-1 | Boot-state emitter ownership | "boot-progress-finalize or extension?" | NEW dedicated unit `eclipse-boot-state.service` (Type=simple, polls `systemctl is-active`). `boot-progress-finalize` is a SHUTDOWN finalizer (ExecStop-only); lifecycle mismatch rules out extension. |
| A-2 | Shutdown-state phase semantics | `phase: grace` ambiguous (smoothing-begun vs smoothing-confirmed?) | Pinned: `grace` = smoothing-begun (T=0, transient possible); `flushing` = smoothing-confirmed, pipeline tasks executing; `powering_off` = pre-`systemctl poweroff`; `cancelled` = smoothing failed. Same-sprint `specs/architecture.md` §10.6 update required (Rule 10). |
| A-3 | Path convention | `/run/eclipse/` proposed in v1 | CHANGED to `/var/run/eclipse-obd/states/` — matches existing project convention (verified at `src/pi/obdii/shutdown/command_types.py:40`, `deploy/deploy-pi.sh:737-775`, `deploy/drain-forensics.service:30-34`). Two conventions = future confusion. |
| A-4 | Chromium → state-file IPC | 3 options proposed | PICKED: **localhost HTTP server** (Iris's preference). Pinned constraints: bind 127.0.0.1 only, Python stdlib only (`http.server`), serves ONLY `/var/run/eclipse-obd/states/*` read-only, runs as same user as the emitters. Options 2+3 dropped from spec. |
| A-5 | 250 ms poll rate | proposed | PASS — 4Hz tmpfs read negligible on Pi 5 at boot. |
| A-6 | Sequencer grace floor | "7.5s minimum floor" — not pinned | Pinned via *invariant in module docstring*, not new config: splash 7.5s budget fits inside sequencer's 7s smoothing + ~3-5s pipeline = ~10-12s total time-to-poweroff at default `smoothingSec=7`. If `smoothingSec < 4`, splash animation may be killed mid-frame (acceptable failure mode: degraded UX, no data loss). Ownership of timing-coupling lives at sequencer docstring. |
| A-7 | `.path` activation | `PathExists=` | PASS. |
| A-8 | Splash service Type= | "simple or oneshot?" | **`Type=simple`** for both splash units. `oneshot` was D-2's contributor (old `splash-shutdown.service`). |
| A-9 | Deploy block-vs-warn | "WARN proposed, Atlas to confirm" | **WARN-not-BLOCK** confirmed. Deploy log MUST print `WARN: splash deploy failed, system functional` (no silent failure). |
| A-10 | SSOT alignment | requires audit | PASS. The two NEW SSOTs (boot-state, shutdown-state) are non-duplicative of existing emitters (verified by `grep` across `src/` + `deploy/`). Splash-as-consumer is clean SSOT pattern (see `specs/ssot-design-pattern.md`). |

**Defects D-1 (wrong SVG ref), D-2 (Conflicts= self-cancel), D-3 (X11/Wayland confusion):** All three verified against real code (`shutdown.html:27`; `splash-shutdown.service:5+25`; `splash-boot.service`'s Before=/DISPLAY=). v1 fix descriptions are correct + concrete enough for Ralph. PASS as written.

**§10 open design questions also pinned in v1.1:** (a) Wayland fallback if SSH-install: check `/run/user/<UID>/wayland-0` socket exists; if neither active session NOR socket, fail loudly. (b) boot-degraded + shutdown-state simultaneous: shutdown wins (priority over boot-state). (c) `version.txt` malformed: chip reads `V?.?.?`, no kiosk crash.

**Rule-10 same-sprint requirement:** the story implementing A-2 (shutdown-state emitter) MUST also update `specs/architecture.md` §10.6 (ShutdownSequencer section) in the same sprint — part of Definition of Done, not a follow-up. Marcus administers as sprint-contract DoD.

## 1. Executive Summary

A status-aware boot/shutdown splash for the OSOYOO 3.5" Pi display, replacing the existing static kit at `specs/UI/dist/splash-pi/`. The brand spine — a Mitsubishi-inspired 3-rhombus animation — is preserved. An honest-instrument layer consumes two SSOTs (`/var/run/eclipse-obd/states/boot-state` from a new `eclipse-boot-state.service` emitter, `/var/run/eclipse-obd/states/shutdown-state` from a new ShutdownSequencer emit hook) to escalate to a 2-state degraded surface when critical services fail. Boot timing is dynamic: minimum 2.5s, yield on healthy, hard cap 12s. Shutdown fires when ShutdownSequencer enters smoothing-begun phase (`phase=grace`): 1s pre-roll + 6.5s reverse animation + BLACK_TAIL until poweroff or 60s safety cap. The splash carries a top wordmark `ECLIPSE OBD-II` and a bottom version chip `V<x> · <sha>` read from `.deploy-version`. Three correctness defects in the existing kit are fixed in scope. Deploy folds into `deploy/deploy-pi.sh` so the version chip is perpetually accurate. **[ATLAS v1.1: path + emitter names pinned; see §0.]**

## 2. Context & Motivation

### What exists today

CIO authored a complete splash kit at `specs/UI/dist/splash-pi/`:
- `splash.svg` — 6.5s boot animation (bloom → 3× spin with staged brightness 0.25→1.00 → throb pulses → fade)
- `splash-shutdown.svg` — same SVG with `animation-direction: reverse`
- `index.html` / `shutdown.html` — chromium kiosk wrappers
- `splash-boot.service` / `splash-shutdown.service` — systemd units
- `install.sh` / `uninstall.sh` / `preview.html`

The choreography is good. The integration around it is not — three defects (§5) plus a deeper UX problem: the splash plays 6.5s of pretty animation regardless of whether services actually came up. It violates the project's honest-instrument principle (Atlas A-5; see also `[[ssot-design-pattern]]`).

### What this spec adds

- Honest-instrument behavior: phases driven by real boot/shutdown state, not a fixed timeline
- Two-state UX (healthy / degraded) with three reinforcing degradation channels (color + motion-stop + text)
- Shutdown trigger moved EARLIER — from `shutdown.target` (driver may have left) to ShutdownSequencer grace-period entry (driver still in seat)
- Identifying chrome — top wordmark + bottom version chip, addressing post-deploy "did the new version boot cleanly" verification
- Defect fixes for three correctness bugs in the existing kit
- Wayland/X11 dual install path
- Deploy-script integration so version chip never lies

### Out of scope (deferred to v2+)

| Item | Why deferred |
|---|---|
| Plymouth / fbi headless fallback | Production Pi has graphical.target; covered by Wayland/X11 install paths |
| Multi-display / HDMI 1080p variant | OSOYOO 480×320 is the target |
| Numeric progress bar | 2-state UX won — bar competes with brand mark |
| Per-service status checklist | Same — too much information at glance |
| Vehicle wordmark ("Eclipse GST" / "4G63") | Project brand only in v1 |
| First-boot vs normal-boot visual variant | Version chip carries the distinction |
| "SAFE TO DISCONNECT" freeze-frame text | Animation IS the message; black is the silence |
| Animation variants per shutdown reason | Sequencer reports `reason`; v1 treats all reasons identically |
| Touch interaction in production | Dev-only via env flag |
| Pi 3 / Pi 4 compatibility | Pi 5 is the production target |
| Plymouth-based earlyboot graphics (pre-systemd) | 1–2s black pre-systemd is acceptable |
| B-086 GEM-1 warnings-first carousel | Separate backlog item; runs during post-boot UI, not splash |

## 3. System Overview & Data Flow

The splash is a **consumer** of two existing SSOTs. It never owns state and never decides system condition.

### Boot splash data flow

```
systemd boot
    │
    ▼
┌──────────────────────────┐       ┌──────────────────────────┐
│ eclipse-boot-state.service│ writes │ /var/run/eclipse-obd/    │
│  [NEW emitter, Type=simple│──────►│  states/boot-state       │
│   polls `systemctl is-    │       │   {progress, services,   │
│   active` for crit set]   │       │    healthy, degraded}    │
└──────────────────────────┘       └────────────┬─────────────┘
                                                │ poll @ 250ms via
                                                │ localhost HTTP (A-4)
                                                ▼
                                    ┌──────────────────────────┐
                                    │  splash-boot.service     │
                                    │  (chromium kiosk +       │
                                    │   splash.svg + JS poll)  │
                                    └──────────────────────────┘
```

**[ATLAS v1.1 / A-1]** Emitter ownership pinned: a NEW dedicated unit `eclipse-boot-state.service` (Type=simple) owns this SSOT. The existing `boot-progress-finalize.service` is a SHUTDOWN finalizer (ExecStart=/bin/true, ExecStop=python -m boot_progress --finalize) — its lifecycle is "run once at shutdown to write CLEAN_COMPLETE rung," not "continuously emit live boot status." Extending it would mash two unrelated honest-instrument capabilities into one unit. Clean separation: each unit owns one job.

### Shutdown splash data flow

```
key-off detected
    │
    ▼
┌────────────────────────┐         ┌──────────────────────────┐
│ ShutdownSequencer       │ writes │ /var/run/eclipse-obd/    │
│  (existing, F-7 fixed)  ├────────►│  states/shutdown-state   │
│  + NEW phase-emit hook  │         │   {phase, t_grace,       │
│                         │         │    t_remaining}          │
└────────────────────────┘         └────────────┬─────────────┘
           │                                    │ .path inotify trigger
           │                                    ▼
           └──────────────────────►   splash-grace.service
                                    (chromium kiosk +
                                     splash-shutdown.svg)
```

**[ATLAS v1.1 / A-2]** Phase emit hook is a NEW capability on ShutdownSequencer. Rule-10 trigger: same-sprint update to `specs/architecture.md` §10.6 is part of the story's DoD. Constraints on the emit hook: (a) non-blocking write (best-effort, never blocks the state machine); (b) emission happens AFTER state transitions are decided, not before; (c) write failures logged but never block shutdown progress. The sequencer is the SSOT; splash is consumer.

### Key contracts

1. Splash **never polls hardware** (GPIO6, MAX17048, OBDLink). Those belong to power-watch + obd-stream. Splash reads only the boot-state / shutdown-state files those services author. One direction of data flow.
2. Splash **never decides system state**. It renders what the SSOTs say. If boot-state reports `degraded=true`, splash paints amber. If shutdown-state reports `phase=grace`, splash plays reverse animation.
3. Splash retires the original `splash-shutdown.service`. The replacement (`splash-grace.service`, triggered via `.path` unit watching the shutdown-state file) fires when the driver is still in seat, not after they have walked away.

### Architectural items deferred to Atlas (§9 routing surface, items A-1..A-10)

The path naming, file schemas, emitter ownership (extend existing services vs. new emitter), chromium → state-file access mechanism, polling-rate validation, sequencer min-grace floor contract, and SSOT-pattern alignment audit are all **architectural decisions outside Iris's lane**. This spec proposes shapes; Atlas ratifies.

## 4. Visual Specification

### Canvas

480×320 native, `preserveAspectRatio="xMidYMid meet"`. All coordinates in viewBox space. No canvas redesign — the existing geometry carries over.

### Layer layout

```
┌──────────────────────────────────────────────┐  y=0
│              ECLIPSE OBD-II                  │  y=18  wordmark
│                                              │
│                                              │
│                  ╱╲                          │
│                 ╱  ╲                         │
│              ◢       ◣                       │  y=160  center mark
│              ◥       ◤                         (existing 3-rhombus)
│                                              │
│                                              │
│             V0.27.19 · a4c68e7               │  y=302  version chip
└──────────────────────────────────────────────┘  y=320
```

### Typography

| Element | Font | Size | Weight | Color | Tracking | Case |
|---|---|---|---|---|---|---|
| Wordmark | `ui-monospace, Menlo, Consolas, monospace` | 14px | 500 | `#888888` | 0.12em | UPPER |
| Version chip | same | 10px | 400 | `#666666` | 0.06em | as-is |
| Degraded message | same | 11px | 500 | `#FFC400` | 0.06em | as-is |

Single font family. System mono only — no web fonts, no font CDN dependency. Rationale: instrument feel + reliable rendering at small sizes on the OSOYOO's narrow gamut.

### Color tokens (additions to existing kit)

```css
--text-secondary: #888888;   /* wordmark */
--text-tertiary:  #666666;   /* version chip */
--amber-warn:     #FFC400;   /* degraded escalation; project-wide warn token */
--amber-soft:     #FFC40033; /* 20% alpha amber for soft backdrops */

/* --- Future tuning-instrument reservations (Spool S-2; NOT used in splash v1) --- */
/* Stubs only — values TBD when tuning UI lands (V0.28+ B-076 downstream).        */
/* Declared here so the visual SSOT is scoped holistically, not retrofitted under  */
/* deadline pressure. Splash never renders these.                                  */
/* --critical-red:  TBD;   state-alarm red ("PULL OVER") — MUST be distinct from   */
/*                         the brand reds below (cooler/orange-shifted, ~#D32F2F). */
/* --neutral-blue:  TBD;   normal-state readouts (~#7B9CAE).                       */
```

Existing reds (`--red` `#E60012`, `--red-light` `#F61D2D`, `--red-dark` `#BF000F`) preserved — these are **brand identity** (the 3-rhombus mark). Per Spool S-2 they are reserved for the brand mark and MUST NOT be reused as a tuning "critical state" color: if the permanent brand mark is red AND a critical alarm is also red, the driver can't tell "brand" from "PULL OVER NOW." Critical-state red is a separate future token (Δ4 above).

### Center mark

3-rhombus geometry, gradient, and keyframes carry over from `splash.svg` unchanged. The choreography is good and is not being redesigned.

### Rendering mechanism for wordmark + version chip + degraded message

Text layers are rendered as **HTML elements in `index.html` / `shutdown.html`**, layered above the embedded SVG via absolute positioning. NOT as SVG `<text>` nodes inside the SVG file itself.

Rationale: the version chip's text content is data-bound to runtime (`version.txt`); the degraded message's text content is data-bound to `boot-state.degradedReason`. HTML overlay makes both bindings trivial via standard DOM manipulation. SVG `<text>` would require JS to reach into the SVG DOM (cross-document boundary when SVG is embedded via `<object>`).

The SVG file itself stays focused on the 3-rhombus animation — same file size, same caching behavior, same preview-in-browser flow.

### Degraded escalation (the honest-instrument layer)

When `boot-state.degraded === true`:

| Channel | Behavior |
|---|---|
| Color | 4px amber outer ring fades in (0.3s); version chip text shifts to amber |
| Motion | Center mark animation FREEZES at current frame (no spin, no throb) — visual silence is the alarm |
| Text | Failure line appears below mark at y=200: e.g. `ECLIPSE-OBD: failed to start` (one line, one cause) |
| Wordmark | Appends `⚠` glyph (single unicode char, stays in monospace stride) |

Three reinforcing channels — degradation is unambiguous even on a panel with poor color reproduction.

### Touch interaction

- Production: no touch handlers. Splash is mandatory.
- Dev: install-time env flag `SPLASH_TAP_TO_SKIP=1` enables a touch-anywhere skip. Not exposed in production install path.

### Boot motion timeline (healthy path)

```
T=0.0   black
T=0.0   center dot fade-in (0.6s)
T=0.2   wordmark fade-in 0→1 (0.6s)
T=0.3   top rhombus bloom (0.4s)
T=0.6   version chip fade-in 0→1 (0.6s)
T=0.7   side rhombi bloom (0.8s)
T=1.5   spin starts (3.0s)
T=1.5   brightness ramp 0.25 → 1.00 (4.5s)
T=2.5   ★ earliest yield-on-healthy point
T=4.5   spin done; throb pulses begin
T=6.0   fade-out (0.5s) — OR earlier if healthy yield fired
T=6.5   splash exit → post-boot UI (or 12s hard cap → DEGRADED)
```

### Shutdown motion timeline

```
T=0.0   sequencer enters grace; trigger fires; BLACK
T=1.0   pre-roll ends; reverse-animation begins
T=1.0   wordmark fade-in (same as boot)
T=1.0   side rhombi collapse first (reverse cascade)
T=1.4   top rhombus collapses
T=2.5   reverse-spin starts (3.0s)
T=2.5   brightness ramp 1.00 → 0.25
T=7.0   final dot fade-out
T=7.5   BLACK (animation done); wait for poweroff or 60s cap
```

Wordmark and version chip appear during shutdown too — same info, last visible state of the system.

## 5. Boot Splash Behavior

### State machine

```
          ┌─────┐  file appears + parse OK
          │INIT │ ──────────────────────────┐
          └──┬──┘                           │
             │ file missing > 12s           ▼
             │                       ┌──────────────┐
             │                       │PLAYING_NORMAL│
             │                       │ animation    │
             │                       │ runs as-is   │
             │                       └───┬───────┬──┘
             │                           │       │
             │   healthy=true            │       │  degraded=true
             │   AND elapsed ≥ 2.5s      │       │  OR elapsed > 12s
             │                           ▼       ▼
             │                  ┌──────────┐  ┌────────────┐
             │                  │HEALTHY_  │  │DEGRADED    │
             │                  │YIELD     │  │amber ring  │
             │                  │fade out  │  │mark freeze │
             │                  │handoff   │  │msg painted │
             │                  └────┬─────┘  └────────────┘
             │                       │              │
             ▼                       ▼              ▼
        DEGRADED                  EXITED         (persists until
        (special: "boot-                          system reboot)
         progress missing")
```

### Polling loop

```js
// inside index.html, in a <script> block
const POLL_MS = 250;
const MIN_PLAY_MS = 2500;
const HARD_CAP_MS = 12000;
const T_START = performance.now();

async function pollBootState() {
  try {
    const r = await fetch('/boot-state', {cache: 'no-store'});
    if (!r.ok) return null;
    return await r.json();
  } catch {
    return null;
  }
}
```

Final endpoint depends on Atlas's choice for chromium → state-file access (item A-4).

### `boot-state` schema (authored by `eclipse-boot-state.service` [Atlas A-1])

```json
{
  "progress": 0.73,
  "healthy": false,
  "degraded": false,
  "services": {
    "eclipse-powerwatch": "active",
    "eclipse-obd": "synced-no-data",
    "boot-progress-finalize": "inactive"
  },
  "degradedReason": null,
  "ts": "2026-05-26T19:42:33Z"
}
```

The SSOT owner is the NEW `eclipse-boot-state.service` (Type=simple, polls `systemctl is-active` for the critical set — Atlas A-1). The splash is a pure consumer: it reads only the top-level `healthy` / `degraded` booleans + `degradedReason`. The granular per-service strings (esp. `eclipse-obd`, below) exist for **post-boot UI** consumers, not the splash.

- **Critical services** (Spool S-1: set unchanged): `eclipse-powerwatch`, `eclipse-obd`, `boot-progress-finalize`. The set is a contract owned by the emitter (`eclipse-boot-state.service` [A-1]), not by the splash. Splash never decides what counts — it reads the boolean flags `healthy` / `degraded`.
- `healthy === true` only when ALL critical services report `"active"` (for `eclipse-obd`, "active" = T1+T2 passed per the tier model below) **AND** the boot-state emitter has completed its initial verdict pass (`progress` reaches `1.0`).
- `degraded === true` when any critical service reports `"failed"` (for `eclipse-obd`, only a T1 or T2 failure — see below) **after** the retry-once window, OR the emitter cannot reach a healthy verdict within 12s.
- `degradedReason` is a one-line, user-readable string; splash paints it verbatim below the mark.

> **Authorship note (v1.2 scrub):** earlier drafts attributed boot-state authorship to `boot-progress-finalize.service`. Per Atlas A-1 that unit is a **shutdown-only finalizer** (`ExecStart=/bin/true`, `ExecStop=python -m boot_progress --finalize`); it never emits live boot status. The boot-state SSOT owner is the NEW `eclipse-boot-state.service`. `boot-progress-finalize` remains in the *critical set* (its `active (exited)` state means "boot-progress instrument armed"), but it does not *write* boot-state.

#### `eclipse-obd` tiered health model [Spool S-1, v1.2]

`eclipse-obd` health is naturally tiered. **Only T1 + T2 failures flip the splash to `degraded`.** T3 (ECU silent) is reported for post-boot UI but does NOT degrade the splash — ECU silence at boot is usually legitimate (Pi cold-booted on UPS with engine off; keyed-acc but not cranked; ISO 9141-2 slow-init). Flagging it amber would teach the CIO to ignore amber — amber must mean *something is actually broken* or it loses signal value (alarm-fatigue principle, Spool's lane).

| Tier | Check | Detection | Splash verdict | `degradedReason` |
|---|---|---|---|---|
| T1 | adapter detected | `/dev/rfcomm0` exists OR BT scan sees MAC `00:04:3E:85:0D:FB` within 5s of boot | T1 fail → **DEGRADED** | `OBD adapter not detected` |
| T2 | ELM327 sync | `ATZ` returns `ELM327 v1.4b` within 3s of T1 pass | T2 fail (post-T1) → **DEGRADED** | `OBD adapter not responding` |
| T3 | first PID response | Mode 01 `0100` returns supported-PIDs mask within 5s of T2 pass | T3 fail → **NOT degraded at splash** | n/a (surfaced in post-boot UI) |

**Retry-once (Spool S-1):** on a T2 *or* T3 failure, the emitter retries once before flipping the verdict — covers the ISO 9141-2 K-line slow-init transient (occasionally needs 2–4s + a retry on first connection). Init-jitter must not trip a false-positive amber.

`services["eclipse-obd"]` carries the tier outcome as one of **5 granular strings** for post-boot consumers (splash ignores these, reads only top-level `healthy`/`degraded`):

| String | Meaning | Maps to splash |
|---|---|---|
| `"starting"` | initial state, checks in progress | (neither yet) |
| `"adapter-missing"` | T1 fail | `degraded=true` |
| `"adapter-no-sync"` | T1 pass, T2 fail | `degraded=true` |
| `"synced-no-data"` | T1+T2 pass, T3 fail (legitimate engine-off case) | `degraded=false` |
| `"synced-with-data"` | T1+T2+T3 pass; PIDs flowing | `healthy` contributor |

### Edge cases

| Case | Behavior |
|---|---|
| `boot-state` file never appears within 12s | DEGRADED; message: `boot-progress instrument not reporting` |
| File appears with malformed JSON | DEGRADED; message: `boot-state unreadable` |
| Service flips healthy → failed AFTER splash exited | Ignore — splash is gone; post-boot UI owns runtime state |
| Multiple services degraded | Show only the first one in `degradedReason` (one-line discipline; no listing) |
| `progress` field drifts backward | Render forward only — don't expose backward motion to user |

## 6. Shutdown Splash Behavior

### State machine

```
          ┌─────┐  shutdown-state file appears
          │INIT │ ──────────────────────────┐
          └─────┘                            │
                                             ▼
                                      ┌───────────┐  cancel check
                                      │PRE_ROLL   │ ────────────┐
                                      │1.0s BLACK │              │
                                      └─────┬─────┘              │
                                            │                    │
                                            ▼                    │
                                      ┌───────────┐  cancel check│
                                      │ANIMATING  │ ─────────────┤
                                      │6.5s rev-  │              │
                                      │animation  │              ▼
                                      └─────┬─────┘       ┌────────────┐
                                            │             │ABORT       │
                                            ▼             │kill chrome │
                                      ┌───────────┐       │immediate   │
                                      │BLACK_TAIL │       │no fadeout  │
                                      │wait for   │       └────────────┘
                                      │poweroff   │
                                      │(60s cap)  │
                                      └─────┬─────┘
                                            │
                                            ▼
                                      ┌───────────┐
                                      │EXIT       │
                                      │service    │
                                      │stops      │
                                      └───────────┘
```

### Trigger mechanism

```ini
# splash-grace.path
[Path]
PathExists=/var/run/eclipse-obd/states/shutdown-state
Unit=splash-grace.service

[Install]
WantedBy=multi-user.target
```

The `.path` unit is always armed; the moment the file appears, the service activates. ShutdownSequencer never directly references the splash unit name — clean decoupling.

### `shutdown-state` schema [ATLAS v1.1 / A-2: pinned]

```json
{
  "phase": "grace",
  "tGraceStartedAt": "2026-05-26T19:50:00Z",
  "tGraceTotalS": 7,
  "tRemainingS": 5,
  "reason": "ignition_off",
  "ts": "2026-05-26T19:50:02Z"
}
```

**Phase enum (pinned to sequencer code-path transitions):**

| `phase` | Sequencer state | When written | Splash response |
|---|---|---|---|
| `grace` | smoothing-begun (T=0 of smoothing window; sustained-loss not yet confirmed) | First `isOnBattery()=True` after boot-grace clears, *before* `smoothingSec` window elapses | TRIGGER splash; play PRE_ROLL+ANIMATING |
| `cancelled` | smoothing window failed (GPIO6 returned HIGH before `smoothingSec` elapsed) | On sustained-loss check failure | ABORT splash (kill chromium, no fadeout) |
| `flushing` | smoothing-confirmed; pipeline tasks executing (drain forensics, sync, etc.) | After `_isSustainedLost()` returns True, before pipeline invocation | CONTINUE splash (no state change) |
| `powering_off` | immediately before invoking `systemctl poweroff` | After pipeline tasks return | CONTINUE splash (enters BLACK_TAIL naturally) |

`reason` values: `ignition_off`, `battery_critical`, `scheduled`. v1 treats all reasons identically; splash never branches on `reason`.

Splash reads `phase`. Only `"grace"` triggers initial render; `"cancelled"` means abort. `tRemainingS` could feed a countdown UI in v2 but **v1 does not surface it** (animation IS the countdown).

### Phase-timing contract [ATLAS v1.1 / A-6: pinned]

The splash's 7.5s animation budget (1s PRE_ROLL + 6.5s ANIMATING) fits inside the sequencer's actual time-from-grace-entry-to-poweroff. With default `config.json` `pi.powerWatch.smoothingSec=7`, the timeline is:

- T=0.0: `phase=grace` written (smoothing begins, splash triggers)
- T=0.0 to T=7.0: smoothing window (7s default)
- T=7.0: `phase=flushing` written; pipeline tasks execute (drain forensics, sync — empirically ~3-5s in Sprint 39 Cycle-2/3 IRL drills)
- T=~10-12: `phase=powering_off` written; `systemctl poweroff` invoked

Splash's 7.5s ≤ ~10-12s sequencer total = comfortable fit at default config.

**Invariant for ShutdownSequencer module docstring (Ralph adds this in same sprint as A-2 emit hook):**

> ```
> Phase-emit timing contract with splash subsystem (F-103):
>   Splash plays a 7.5s animation budget triggered on phase=grace.
>   If config `smoothingSec` < 4, splash animation may be killed
>   mid-frame when poweroff fires before animation completes.
>   Acceptable failure mode: degraded UX, no data loss.
>   Default smoothingSec=7 provides ~10-12s total time-to-poweroff,
>   comfortably exceeding splash's 7.5s budget.
> ```

Ownership of the time-coupling lives at the sequencer's docstring; splash holds the invariant by trusting it. No new config key, no runtime coordination — clean unidirectional dependency (splash depends on sequencer's timing contract; sequencer does not know splash exists).

### Cancellation behavior

Splash polls `shutdown-state` every 250ms. If `phase` transitions away from `grace`:

| Cancellation timing | Behavior |
|---|---|
| During PRE_ROLL (T < 1.0s) | Splash never painted anything → kill chromium, no visible flicker |
| During ANIMATING (1.0s ≤ T < 7.5s) | Kill chromium immediately. Driver sees sudden black, then post-boot UI reappears. Acceptable (rare; explainable) |
| After BLACK_TAIL begins (T ≥ 7.5s) | Same — kill chromium. The black tail's purpose is gone |

The 1s pre-roll is the debounce window that protects against false-positive shutdowns (sequencer enters grace but cancels within ~500ms because of GPIO bounce or driver hesitation).

### BLACK_TAIL safety cap

If poweroff doesn't fire within 60s after animation ends, splash service exits and post-boot UI reappears. Rationale: sequencer may have crashed mid-grace; we don't want a black screen forever. 60s is generous — longer than any reasonable shutdown — so a healthy sequencer never trips it.

### Edge cases

| Case | Behavior |
|---|---|
| Splash service starts but `shutdown-state` file is gone (race) | Wait 250ms, retry; if 3 retries fail, EXIT silently |
| `phase` field unrecognized value | Treat as `"cancelled"` — fail safe |
| Multiple grace-period cycles in quick succession | Each one re-triggers splash — sequencer is the SSOT, splash just renders |
| Pi loses power mid-animation | Screen goes black with hardware. Animation didn't lie — system was indeed shutting down |

## 7. Defects in the Existing Kit (folded into scope)

### D-1 — `shutdown.html:27` loads wrong SVG (P0)

Current: `data="splash.svg"`. Fix: `data="splash-shutdown.svg"`. Today's "shutdown splash" would play the forward boot animation if it ran. Pure copy-paste regression.

### D-2 — `splash-shutdown.service` self-cancels (P0)

```ini
Conflicts=reboot.target halt.target poweroff.target
WantedBy=halt.target reboot.target shutdown.target
```

`Conflicts=X` means "if X starts, stop this unit." The moment shutdown begins, systemd cancels the splash. INSTALL.md's troubleshooting note "Shutdown splash doesn't appear" is the symptom.

Fix: **delete this unit entirely**. The replacement is `splash-grace.service` triggered by `splash-grace.path` (§6).

### D-3 — `splash-boot.service` X11/Wayland confusion (P0)

```ini
Before=getty.target multi-user.target graphical.target
Environment=DISPLAY=:0
```

Two compounding problems:
- `Before=graphical.target` means the unit fires *before* the desktop session brings up the display server. There's no `:0` to talk to yet.
- Bookworm uses Wayland (labwc/wayfire) by default. Chromium needs `--ozone-platform=wayland` and `WAYLAND_DISPLAY=wayland-0`, not X11's `DISPLAY=:0`.

Fix: rewrite the unit to be Wayland-aware AND defer until the display server is actually up.

```ini
[Unit]
Description=Animated boot splash (status-aware)
After=graphical.target
Wants=graphical.target

[Service]
Type=simple
User=__PI_USER__                      # placeholder; substituted by install.sh at install time (see V-1)
Environment=WAYLAND_DISPLAY=wayland-0
Environment=XDG_RUNTIME_DIR=/run/user/%U
ExecStart=/usr/bin/chromium-browser \
  --kiosk \
  --ozone-platform=wayland \
  --noerrdialogs --disable-infobars --hide-scrollbars \
  --autoplay-policy=no-user-gesture-required \
  --user-data-dir=/tmp/splash-chromium-boot \
  file:///opt/splash/index.html

# Splash exits via its own JS calling window.close() once state machine
# reaches HEALTHY_YIELD or DEGRADED. No hardcoded sleep/pkill.
```

Three changes: ordering (`After=`, not `Before=`), platform (Wayland-native), exit mechanism (JS-driven, not external pkill).

### V-1 — Verify Pi user identity (P1 — install-time check)

The original kit hardcodes `User=pi` + `XDG_RUNTIME_DIR=/run/user/1000`. Production Pi (`Chi-Eclips-Tuner`) may have a different user. The `install.sh` MUST:
- Detect the actual user that owns `/home/<user>` (single non-root user)
- Substitute into the unit file before installing
- Fail loudly if it can't determine a target user

### V-2 — Verify session manager on Pi (P1 — install-time check)

Before installing, `install.sh` MUST check `loginctl show-session $XDG_SESSION_ID -p Type` (or fallback heuristic if no active session) and pick the matching unit variant: Wayland or X11. If session type is unknown, fail loudly.

This means the deliverable ships **two unit templates** (`splash-boot.service.wayland`, `splash-boot.service.x11`) and `install.sh` picks one.

## 8. Integration Details

### Unit inventory [ATLAS v1.1 / A-8: Type= pinned]

| Unit | Status | Type= | Trigger | Purpose |
|---|---|---|---|---|
| `eclipse-boot-state.service` | NEW | `simple` | `WantedBy=multi-user.target` | Emits boot-state JSON @ 500ms by polling `systemctl is-active` for critical-services set [A-1] |
| `eclipse-states-http.service` | NEW | `simple` | `WantedBy=multi-user.target` | Localhost HTTP @ 127.0.0.1:9899 serving `/var/run/eclipse-obd/states/*` read-only [A-4] |
| `splash-boot.service.wayland` | NEW | `simple` | `WantedBy=graphical.target` | Boot splash, Bookworm/Wayland |
| `splash-boot.service.x11` | NEW | `simple` | `WantedBy=graphical.target` | Boot splash, X11 fallback |
| `splash-grace.service` | NEW | `simple` | activated by `.path` unit | Grace-period shutdown splash |
| `splash-grace.path` | NEW | n/a (`.path` unit) | `PathExists=/var/run/eclipse-obd/states/shutdown-state` | Inotify watcher → fires grace service |
| `splash-boot.service` (original) | **RETIRED** | — | — | Replaced by Wayland/X11 variants |
| `splash-shutdown.service` (original) | **RETIRED** | — | — | Replaced by `splash-grace` pair |

Installer picks **one** of the boot variants based on detected session type. **All splash + state-emit units are `Type=simple`** — `oneshot` was D-2's root contributor and is rejected for this subsystem.

### File layout on Pi

```
/opt/splash/
├── index.html              ← boot splash entry
├── shutdown.html           ← shutdown splash entry (D-1 fixed)
├── splash.svg              ← forward animation + wordmark/chip layers
├── splash-shutdown.svg     ← reverse animation + wordmark/chip layers
├── boot-state-poll.js      ← NEW (state machine, polling loop)
├── shutdown-state-poll.js  ← NEW
├── styles.css              ← NEW (text layer styles externalized)
└── version.txt             ← written at install/deploy time from .deploy-version

/etc/systemd/system/
├── splash-boot.service     ← one of the two variants (substituted)
├── splash-grace.service
└── splash-grace.path

/var/run/eclipse-obd/states/               ← tmpfs, ephemeral, populated at runtime
├── boot-state              ← written by eclipse-boot-state.service [A-1]
└── shutdown-state          ← written by ShutdownSequencer (NEW capability)
```

### Chromium → state-file access mechanism [ATLAS v1.1 / A-4: pinned]

Chromium kiosk cannot `fetch('file:///var/run/...')` cleanly (browser file-access policy). **Picked: tiny localhost HTTP server.**

New unit: `eclipse-states-http.service`, Type=simple, ExecStart runs a small Python script. Constraints (Ralph implements to these):

- **Bind 127.0.0.1 only.** Never 0.0.0.0. Localhost-only attack surface.
- **Python stdlib only** (`http.server.HTTPServer` + a small custom handler). No `flask`, no `aiohttp`, no new deps.
- **Serves ONLY `/var/run/eclipse-obd/states/*` read-only.** Any path traversal (`..`) or non-states/* path returns 404. Hard-coded base directory; not configurable at runtime.
- **Runs as the same user that owns `/var/run/eclipse-obd/`** (currently `mcornelison` per `deploy-pi.sh:775`). No privilege escalation.
- **Cache-control: `no-store`** on every response so chromium's 250ms polls always see fresh data.
- **Port: `127.0.0.1:9899`** (fixed; document in unit file + spec; not user-configurable to avoid drift).
- **Listen-failure semantics:** if port bind fails (already in use), service exits non-zero — chromium's fetch() then returns network error, splash's polling loop falls through to DEGRADED ("boot-progress instrument not reporting"). No silent green-when-broken.

Splash uses `fetch('http://127.0.0.1:9899/boot-state', {cache: 'no-store'})` and same pattern for `/shutdown-state`.

Alternatives considered + rejected: bind-mount with `--allow-file-access-from-files` (deprecated chromium flag; security smell), `--user-data-dir` whitelist (brittle, breaks across Chromium versions).

### Install flow (new `install.sh` responsibilities)

```
1. Detect Pi user        → owner of /home/* (single non-root user)
2. Detect session type   → loginctl show-session ... -p Type → wayland|x11
3. Pick unit variant     → splash-boot.service.{wayland,x11}
4. Substitute %USER, %UID → into picked variant before install
5. Read .deploy-version  → write to /opt/splash/version.txt
6. Copy assets to /opt/splash/  (install -m 0644 ...)
7. Install systemd units → /etc/systemd/system/*
8. systemctl daemon-reload
9. Enable: splash-boot, splash-grace.path
10. Idempotency check    → don't double-enable, don't dup files
```

### Uninstall flow

```sh
systemctl stop splash-boot splash-grace splash-shutdown 2>/dev/null || true
systemctl disable splash-boot splash-grace.path splash-shutdown 2>/dev/null || true
rm -f /etc/systemd/system/splash-{boot,grace,shutdown}.service
rm -f /etc/systemd/system/splash-grace.path
rm -rf /opt/splash
systemctl daemon-reload
```

### Deploy-pi.sh integration (per CIO decision: fold-in) [ATLAS v1.1 / A-9: pinned]

`deploy/deploy-pi.sh` gains a new phase that reconciles `/opt/splash/` on every deploy:

- Copy current kit from repo to `/opt/splash/`
- Re-substitute user + session type (in case Pi changed)
- Write current `.deploy-version` value to `/opt/splash/version.txt`
- `systemctl daemon-reload` if unit files changed
- `systemctl restart splash-boot.service eclipse-boot-state.service eclipse-states-http.service || true` (no-op while running; ensures next boot uses new unit — V0.27.16 lesson per Argus)
- **Failures WARN but do not BLOCK deploy.** Required log line on splash-phase failure: `WARN: splash deploy failed, system functional — see journalctl -u <failing-unit> for details`. Silent failure is rejected; the deploy log must be honest about partial success.

Rationale: version chip becomes a deploy-health indicator. A stale chip on next boot → broken deploy script. Splash is cosmetic, never safety-critical — so WARN is correct, but observability discipline (explicit log line) keeps the regression net intact (V0.27.16 lesson: stale `.deploy-version` semantics are how silent-deploy bugs hide).

## 9. Acceptance Criteria

Argus pattern: single-boolean pass/fail, evidence-survival, failure-mode enumeration.

### Synthetic (CI-runnable)

| # | Criterion | Evidence |
|---|---|---|
| S-1 | `shutdown.html` `<object>` element loads `splash-shutdown.svg` (D-1 fix) | grep verifies file content |
| S-2 | No `splash-*.service` file contains `Conflicts=` directive (D-2 fix) | grep verifies absence |
| S-3 | Boot splash unit's `Environment=` lines reference Wayland (`WAYLAND_DISPLAY`) when wayland variant; X11 (`DISPLAY=:0`) when x11 variant | grep per variant |
| S-4 | `install.sh --dry-run` reports the user + session-type it WOULD pick (no actual install) | stdout matches expected pattern |
| S-5 | `preview.html` opened in headless chromium renders without console errors for both SVGs | headless chrome log captured |

### IRL — boot splash, healthy path

| # | Criterion | Evidence |
|---|---|---|
| I-1 | Pi cold-boot → splash visible on OSOYOO display within ≤5s of boot-progress reaching graphical.target | photo from drill log + journalctl timestamp |
| I-2 | Splash plays through to splash exit (chromium PID for splash-boot exits, post-boot UI takes over) | `pgrep -f splash-chromium-boot` empty after T+12s |
| I-3 | Version chip text matches `cat .deploy-version` exactly (V<x> · <sha>) | screenshot + diff vs file |
| I-4 | Wordmark "ECLIPSE OBD-II" rendered top, monospace, centered | screenshot |
| I-5 | No visible flicker, no partial frames during bloom + spin + throb | drill log + screen recording |

### IRL — boot splash, degraded path

| # | Criterion | Evidence |
|---|---|---|
| I-6 | `sudo systemctl mask eclipse-obd.service` → reboot → splash escalates to DEGRADED within 12s | screenshot of amber ring + frozen mark |
| I-7 | Degraded message text matches `boot-state.degradedReason` field exactly | screenshot + `cat /var/run/eclipse-obd/states/boot-state` artifact |
| I-8 | Center mark FREEZES on degraded (no spin, no throb) | screen recording or 2-frame comparison |
| I-9 | Amber outer ring rendered with correct color (`#FFC400`) on production panel | screenshot |
| I-10 | Unmask + reboot → next boot returns to healthy path, no leftover amber | screenshot |
| I-10b | **Alarm-fatigue guard (Spool S-1):** boot with **engine OFF** (adapter present + synced, ECU silent = T3 fail) → splash shows **HEALTHY, NOT degraded** (no amber, mark animates normally); `boot-state.services["eclipse-obd"] == "synced-no-data"` | screenshot (no amber) + `cat …/boot-state` artifact showing `degraded:false` + `synced-no-data` |

### IRL — shutdown splash

| # | Criterion | Evidence |
|---|---|---|
| I-11 | Engine off + key off → sequencer enters grace → splash appears within ≤1.5s (1s pre-roll + activation budget) | sequencer journal + screen photo |
| I-12 | Reverse animation plays full 6.5s, then transitions to BLACK_TAIL | screen recording |
| I-13 | If grace ends mid-animation, splash terminates cleanly (no orphan chromium) | `pgrep -f splash-chromium-shutdown` empty post-poweroff |
| I-14 | Grace cancelled in first 1.0s → no visible paint on screen (PRE_ROLL safety) | drill log + recording |
| I-15 | BLACK_TAIL 60s cap engages if sequencer hangs (force-test by SIGSTOP mid-grace) | service auto-exits + journal entry |

### IRL — deploy integration

| # | Criterion | Evidence |
|---|---|---|
| I-16 | Fresh deploy → `/opt/splash/version.txt` content matches `.deploy-version` exactly | file diff in drill artifact |
| I-17 | Re-deploy is idempotent: no duplicated `.service` files, no stale `.path` entries | `ls -la /etc/systemd/system/splash-*` snapshot before + after |
| I-18 | `uninstall.sh` removes all units + files; `systemctl status splash-*` returns "not-found" | journal + ls snapshot |

### Failure-mode enumeration (each must NOT happen)

| F | Failure mode | Detection |
|---|---|---|
| F-1 | Splash claims healthy when a critical service is down (green-when-broken) | I-6 inverse |
| F-2 | Splash never appears at all on cold boot | I-1; `journalctl -u splash-boot.service -b` |
| F-3 | Splash persists past exit (chromium PID lingers, eats screen) | I-2 pgrep check |
| F-4 | Version chip stale relative to deploy | I-3 + I-16 combined |
| F-5 | Shutdown splash plays during shutdown.target instead of grace (old kit behavior leaked) | I-11 timing check |
| F-6 | Splash service races eclipse-powerwatch on boot (delays bring-up) | journalctl timing: powerwatch READY timestamp not >1s later than baseline |
| F-7 | **False-amber: splash shows degraded on a legitimate engine-off boot** (T3 fail misread as fault — the alarm-fatigue bug Spool S-1 guards against) | I-10b |

## 10. Routing Surface

### Atlas (design-gate, Rule 10) — **CLEARED 2026-05-26 [v1.1 amendments applied; see §0]**

| # | Item | Spec ref | Verdict |
|---|---|---|---|
| A-1 | Boot-state emitter ownership | §3, §5 | CHANGED → NEW `eclipse-boot-state.service` (Type=simple) |
| A-2 | Shutdown-state phase semantics | §3, §6 | PINNED → enum table; same-sprint `specs/architecture.md` §10.6 update required (Rule 10 DoD) |
| A-3 | tmpfs path convention | §3 | CHANGED → `/var/run/eclipse-obd/states/` (existing project convention) |
| A-4 | Chromium IPC | §5, §8 | PICKED → localhost HTTP @ 127.0.0.1:9899 via `eclipse-states-http.service` |
| A-5 | 250ms poll rate | §5 | PASS |
| A-6 | Sequencer timing contract | §6 | PINNED → docstring invariant on sequencer (default smoothingSec=7 → 7.5s fits); no new config key |
| A-7 | `.path` activation | §6, §8 | PASS — `PathExists=` |
| A-8 | Splash `Type=` | §8 | PICKED → `simple` for all NEW units |
| A-9 | Deploy block-vs-warn | §8 | PICKED → WARN-not-BLOCK + explicit log line |
| A-10 | SSOT alignment | §3 | PASS — splash is pure consumer; both NEW SSOTs verified non-duplicative |

### Spool (advisory) — **RESOLVED 2026-05-28, folded into v1.2**

| # | Item | Disposition |
|---|---|---|
| S-1 | What counts as "OBD degraded" semantically | **FOLDED (§5):** 3-tier model — T1/T2 fail = degraded; T3 (engine-off ECU silence) = informational, not degraded; retry-once on T2/T3; 5 granular `eclipse-obd` strings. |
| S-2 | Amber `#FFC400` alignment with future tuning palette | **FOLDED (§4):** `--amber-warn #FFC400` confirmed project-wide warn token (tuning gauges inherit); `--critical-red`/`--neutral-blue` reserved as commented stubs; brand reds never reused as critical-state red. |

### Argus (advisory) — **OPEN; re-pinged 2026-06-03 (non-blocking for grooming)**

| # | Item | Status |
|---|---|---|
| Q-1 | Acceptance criteria (§9) sign-off | Awaiting Argus — §9 authored to his patterns (single-boolean, evidence-survival, failure-mode enumeration); needs his confirm |
| Q-2 | IRL drill methodology for degraded path — how to safely induce "OBD failed" in-vehicle | Awaiting Argus — proposed: `systemctl mask eclipse-obd.service` (T1/T2 induction); T3 path = boot with engine off (must show NOT-degraded per S-1) |
| Q-3 | Evidence-capture for visual criteria — screen recording rig, photo timestamp protocol | Awaiting Argus |

### Marcus / PM (v1.2 GROOM-READY 2026-06-03 — Atlas-gated + Spool-folded; ready for story filing)

| # | Item |
|---|---|
| M-1 | Sprint scoping — proposed split (Iris's original, ratified by Atlas with one addition): **US-A** boot splash (incl. NEW `eclipse-boot-state.service` emitter [A-1] + NEW `eclipse-states-http.service` IPC [A-4]) · **US-B** shutdown splash (incl. NEW ShutdownSequencer phase-emit hook [A-2] + **Rule-10 same-sprint update to `specs/architecture.md` §10.6** as part of US-B DoD + sequencer module-docstring timing-contract invariant [A-6]) · **US-C** deploy integration (deploy-pi.sh fold-in + version.txt + WARN-not-BLOCK semantics [A-9]) · **US-D** defects (D-1, D-2, D-3, V-1, V-2) — may fold into US-A+US-B at PM discretion |
| M-1a | **Rule-10 DoD on US-B:** the story implementing the ShutdownSequencer phase-emit hook MUST also land the matching `specs/architecture.md` §10.6 update in the same sprint (not a follow-up). Atlas BLOCK if the sprint ships the hook without the spec update. Standard same-sprint DoD pattern per CIO 2026-05-18 + the Sprint 39 T9 precedent. |
| M-2 | Dependency check — B-076 server schema may overlap on tooling but no hard deps |
| M-3 | Atlas-bound items CLEARED (§0); Spool S-1/S-2 FOLDED (§0.1); spec at **v1.2 groom-ready**. Only open item = Argus advisory (Q-1/Q-2/Q-3) sign-off — non-blocking; can resolve during grooming or first sprint of F-103. |
| M-4 | Story IDs: M-1 split (US-A/B/C/D) maps to the "US-359-class" children Marcus planned. PM owns final ID assignment + `validationCriteria`/`definitionOfDone` per the validation-criteria-upfront contract; §9 acceptance criteria are the source material. |

### Open design questions [ATLAS v1.1: all pinned]

- **Wayland session detection in install.sh** — `loginctl show-session $XDG_SESSION_ID` requires an active session at install time. If install is run via SSH (non-interactive), session lookup may fail. **Pinned fallback:** check for `wayland-0` socket in `/run/user/<UID>/`; if neither an active session NOR the socket exists, `install.sh` exits non-zero with message `ERROR: cannot determine session type (no active loginctl session, no wayland-0 socket); aborting splash install`. Fail loudly, don't pick X11 by default — guessing wrong gives the D-3 class of bug.
- **boot-state healthy AND shutdown-state appearing simultaneously** — **Pinned:** shutdown wins. If `shutdown-state` file appears at any time, splash transitions to shutdown rendering (kill any in-flight boot splash chromium PID, start splash-grace render). Boot splash never resumes once shutdown has begun. Rationale: shutdown is the more recent + more user-relevant event; boot state is stale once shutdown begins.
- **`version.txt` malformed handling** — **Pinned:** chip renders the literal string `V?.?.?` (no SHA, no extras) and continues to render the rest of the splash normally. JS does not throw; no kiosk crash. Logged once to journal as `WARN: version.txt malformed or unreadable: <reason>` so a stale/broken deploy is visible without blocking boot.

## 11. Routing Plan (post-spec-commit)

```
Iris (spec author, this session)
   │
   ▼ commits spec to docs/superpowers/specs/2026-05-26-b103-splash-animation-design.md
   │
   ▼ files A2AL to Atlas (architect/inbox/) — design-gate review request (A-1..A-10)
   │
   ▼ files advisory A2ALs to Spool + Argus (their inboxes) — input requests, not blocking
   │
   │           ┌─ Atlas reviews A-1..A-10
   │           │  closes / amends / blocks per finding
   │           ▼
   │       Atlas sign-off OR Atlas-blocked
   │           │
   │           ▼ (if signed off)
   │       Iris files A2AL to Marcus (pm/inbox/) — ready for sprint scoping
   │           │
   │           ▼
   │       Marcus scopes into V0.28+ sprint (stories US-A..US-D, dependencies, sequencing)
   │           │
   │           ▼
   │       Ralph builds
   │           │
   │           ▼
   │       Argus IRL drills against §9 acceptance criteria
```

---

*End of spec. Draft A2AL letter to Atlas held by Iris until CIO approves spec for forwarding.*

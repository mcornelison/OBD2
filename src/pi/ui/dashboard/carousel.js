/* ============================================================================
 * File:    carousel.js
 * Purpose: US-399 carousel shell (F-092). Swipe-nav between cards + page dots +
 *          a persistent top bar, plus the honest-instrument availability poll
 *          that drives each card to `unavailable` when its state file is
 *          missing/malformed. The dashboard is a PURE CONSUMER of the state
 *          files (specs/ssot-design-pattern.md): it NEVER polls hardware. The
 *          per-card field rendering (System Status / Battery Health) is US-400 /
 *          US-401; this shell only decides card AVAILABILITY + carousel motion.
 *
 *          The pure carousel logic (clampIndex / nextIndex / swipeDirection /
 *          cardAvailability) is exported under module.exports so it can be unit
 *          tested in node with no DOM (S-2). The DOM wiring runs only in the
 *          browser (guarded on `typeof document`).
 * Author:  Ralph Agent (Rex)
 * Created: 2026-06-30 -- Sprint 49 US-399 (carousel shell)
 * ==========================================================================*/
(function (global) {
  "use strict";

  var POLL_MS = 250;          // 4 Hz tmpfs read (matches the splash cadence)
  var SWIPE_THRESHOLD_PX = 40; // min horizontal travel to count as a swipe

  // US-508 (F-124): the LIVE feed gets its own faster loop. Atlas's transport
  // ruling -- the states/imu bridge writes at ~10-15 Hz latest-wins and the live
  // card polls it at ~10 Hz off the existing states_http_server, which animates
  // the compass tape and the g-trail with NO new transport. Deliberately a
  // SECOND loop rather than raising POLL_MS: the shared tick reads six state
  // files, and 2.5x-ing all of them to animate one card would be six reads
  // nobody can see for every one they can.
  var IMU_POLL_MS = 100;

  // US-653 -- deadlines. ARCH-014 made a THROWN tick survivable; it did not make
  // a HUNG one survivable, and the hang is what was actually on the panel:
  // 7.4 h uptime, one chromium start, cumulative CPU flat at 35 s, panel frozen,
  // ZERO markers and ZERO captured exceptions with the ARCH-014 build live.
  //
  // A browser `fetch()` has NO default timeout, so an accepted-but-never-completed
  // request hangs its `await` forever -- and a HANG IS NOT AN ERROR, so `catch`
  // never runs, the tick never returns, and nothing ever books the next one.
  //
  // Two layers on purpose: the request deadline stops the known cause, the tick
  // deadline stops ANY non-settling body including causes we have not met yet.
  var FETCH_DEADLINE_MS = 2000;   // localhost states server answers in <1 ms
  var TICK_DEADLINE_MS = 10000;   // generous: a tick reads several state files

  // -------------------------------------------------------------------------
  // ARCH-014 -- loop resilience and error reporting.
  //
  // THE DEFECT. Both live loops rescheduled themselves on the LAST line of an
  // async body:
  //
  //     async function imuTick() {
  //       lastImu = await fetchState("imu");
  //       renderHome(Date.now());
  //       setTimeout(imuTick, IMU_POLL_MS);   // unreachable after a throw
  //     }
  //
  // Nothing awaited the returned promise, so a rejection became an UNHANDLED
  // PROMISE REJECTION -- silent by construction. ONE transient fetch failure,
  // or one throw inside renderHome, ended the loop permanently. Measured live
  // on the car 2026-08-30: reproducible ~38 s after data starts, renderer
  // cumulative CPU flat at 00:00:12 in state `Sl` while every state file kept
  // updating. The data tier was healthy; only the display was dead, it never
  // recovered, and touch did nothing either -- because a deterministic throw
  // in the render path kills the touch-driven redraw on the same code.
  //
  // THE RULE. A transient error costs ONE FRAME, never the session.
  //
  // Why not setInterval, which survives a throw for free? Because it STACKS --
  // a read slower than the period queues another before the first finishes,
  // which is exactly why US-508 chose setTimeout. This keeps the no-stack
  // property AND adds the survival property, rather than trading one for the
  // other.
  // -------------------------------------------------------------------------

  //: Message levels, mirroring the CIO's own `myPrint` utility (2026-08-30).
  //: LOG_ERROR is deliberately 0 and is NEVER gated -- see shouldLog.
  var LOG_ERROR = 0;
  var LOG_WARN = 1;
  var LOG_INFO = 2;
  var LOG_DEBUG = 3;

  //: Verbosity when nothing overrides it: errors only. Per-tick tracing is
  //: temporary by design and must not ship on.
  var DEFAULT_DEBUG_LEVEL = LOG_ERROR;

  function currentDebugLevel() {
    // Read at CALL time, not at load time, so the level can be raised on a
    // running panel from the console without a reload.
    var injected = global && global.DISPLAY_DEBUG_LEVEL;
    return typeof injected === "number" ? injected : DEFAULT_DEBUG_LEVEL;
  }

  function shouldLog(level, configuredLevel) {
    // An error is not a verbosity setting. The ABSENCE of error reporting is
    // what hid the freeze for weeks, so level 0 ignores the gate entirely --
    // including at configuredLevel 0. Making errors configurable would rebuild
    // exactly the blindness this change exists to remove.
    if (level === LOG_ERROR) return true;
    var configured =
      typeof configuredLevel === "number" ? configuredLevel : DEFAULT_DEBUG_LEVEL;
    return configured >= level;
  }

  function uiLog(level, message) {
    if (!shouldLog(level, currentDebugLevel())) return false;
    if (typeof console === "undefined") return false;
    // Marker prefixes follow the myPrint convention so a mixed log can be
    // scanned by eye: [!] critical, [W] warning, [+] info, [D] debug.
    var marker = ["[!]", "[W]", "[+]", "[D]"][level] || "[-]";
    var sink = level === LOG_ERROR && console.error ? console.error : console.log;
    sink.call(console, marker + " eclipse-ui " + message);
    return true;
  }

  // US-866 (Atlas 2026-10-16, CIO-directed): the FIRST FRAME this page draws,
  // as one console line. chromium runs with --enable-logging=stderr, so the line
  // lands in the journal with a boot-relative timestamp -- the only way to see
  // when the driver actually gets gauges, as opposed to when systemd STARTED
  // the unit. Two nested requestAnimationFrame callbacks: the second runs after
  // the first frame has been produced. Deliberately NOT routed through uiLog:
  // its level gate is off by default, and this is one line per page load.
  function reportFirstFrame(win, page) {
    if (!win || typeof win.requestAnimationFrame !== "function") return false;
    if (typeof console === "undefined" || typeof console.info !== "function") return false;
    win.requestAnimationFrame(function () {
      win.requestAnimationFrame(function () {
        var perf = win.performance;
        var sinceNav = perf && typeof perf.now === "function" ? Math.round(perf.now()) : -1;
        console.info("[kiosk] first-frame page=" + page + " sinceNavigationMs=" + sinceNav);
      });
    });
    return true;
  }

  function reportFetchAbort(name, err, log) {
    // US-655: US-653 shipped TWO deadlines and instrumented only ONE. The tick
    // deadline reports; the FETCH deadline aborted into a catch that returns
    // null -- indistinguishable from a 404, a parse failure, or a missing file.
    //
    // That silence is not cosmetic. It made Boot B UNINTERPRETABLE: 2 h 48 m
    // with zero log lines was equally consistent with "the fix is absorbing
    // hangs" and "no hang ever happened", and nothing on the box could separate
    // them. This branch is the difference between those two readings.
    //
    // ONLY a timeout is reported. An ordinary failure stays quiet, or every
    // missing state file becomes an error line and buries the signal.
    if (!err || err.name !== "TimeoutError") return false;
    log(
      LOG_ERROR,
      "fetchState(" +
        name +
        ") aborted after " +
        FETCH_DEADLINE_MS +
        "ms -- the request never completed"
    );
    return true;
  }

  function reportLoopError(name, err) {
    // The STACK is the whole point -- it names the file and the line, which is
    // the one thing no amount of reading this file from the outside settles.
    var detail = err && err.stack ? err.stack : String(err);
    return uiLog(LOG_ERROR, name + " threw: " + detail);
  }

  function makeResilientLoop(opts) {
    var name = opts.name;
    var delayMs = opts.delayMs;
    var body = opts.body;
    var schedule = opts.schedule;
    var report = opts.report;
    // Opt-in: omitting it preserves ARCH-014's exact behaviour for any caller
    // that does not ask for a deadline, so this cannot silently alter a loop
    // that was never at risk.
    var deadlineMs = opts.deadlineMs || 0;

    function run() {
      // EXACTLY-ONCE, across FOUR outcomes -- resolve, reject, synchronous throw,
      // and NEVER SETTLING. The fourth is the one that was on the panel (US-653)
      // and the one ARCH-014 could not see, because it only ever reacted to an
      // event and a hang produces none.
      //
      // The latch also keeps the rate honest: a body that throws synchronously
      // AND leaves a rejected promise, or one that returns AFTER its deadline
      // already fired, must still book exactly one tick. Two timers would double
      // the loop rate and turn a display stall into a CPU burn.
      var settled = false;
      function finish(err) {
        if (settled) return;
        settled = true;
        if (err) report(name, err);
        schedule(run, delayMs);
      }
      try {
        var result = body();
        if (result && typeof result.then === "function") {
          if (deadlineMs > 0) {
            // A hang emits nothing to react to, so the only way to survive it is
            // to stop waiting on our own schedule. Reported, never silently
            // recovered -- a silent recovery would hide the failure this exists
            // to surface, which is how the panel died unnoticed for seven hours.
            schedule(function () {
              finish(
                new Error(
                  name +
                    " exceeded its " +
                    deadlineMs +
                    "ms deadline -- the body never settled"
                )
              );
            }, deadlineMs);
          }
          return result.then(
            function () {
              finish(null);
            },
            function (err) {
              finish(err);
            }
          );
        }
        finish(null);
      } catch (err) {
        finish(err);
      }
      return undefined;
    }
    return run;
  }

  function installGlobalErrorReporting(win, report) {
    // Catches throws that happen OUTSIDE the two loops -- event handlers, the
    // touch path, anything. Returns false under node (no addEventListener) so
    // the unit tests can load this module unchanged.
    if (!win || typeof win.addEventListener !== "function") return false;
    win.addEventListener("error", function (ev) {
      var err = ev && ev.error ? ev.error : new Error(String(ev && ev.message));
      report("window.error", err);
    });
    win.addEventListener("unhandledrejection", function (ev) {
      var reason = ev && ev.reason;
      report(
        "unhandledrejection",
        reason instanceof Error ? reason : new Error(String(reason))
      );
    });
    return true;
  }

  // US-506 (F-124) carousel navigation model -- the GROUNDED DEFAULTS that
  // mirror config.json `pi.display.carousel.*` (the tuning SSOT). They are the
  // file:// preview / unconfigured fallback; the live values arrive at serve
  // time as window.DISPLAY_CAROUSEL, the same injection seam US-483-b built for
  // the auto-dim curve. Retuning the feel is a config change, not a code change.
  var CAROUSEL_DEFAULTS = {
    autoRotateS: 8,               // hands-off cycle period (CIO-locked, F-124)
    resumeIdleS: 45,              // a pause self-expires after this much quiet
    swipeMinPx: 40,               // deadzone -- below this it is a TAP, not a
                                  // swipe (mirrors SWIPE_THRESHOLD_PX)
    swipeFastVelocityPxPerMs: 0.6, // |v| at/above this = a FLICK
    swipeFastTravelFrac: 0.55,    // ...or travel this fraction of the card
    // US-511: the `parked` debounce. Asymmetric on purpose -- see parkedNext.
    parkedOnS: 8,                 // idle must be HELD this long to read parked
    parkedOffS: 3,                // ...and not-idle this long to give it back
  };

  // US-482 letterbox scaling: the UI is authored at a fixed STAGE_W x STAGE_H
  // design box (#stage) and uniformly scaled to fill the real panel (device
  // resolution varies -- the Pi outputs 1080p). LETTERBOX = a single uniform
  // scale of the EXACT 480x320 layout, centered, with black bars on the aspect
  // mismatch (CIO-locked 2026-07-21). No layout reflow -- scaled as one unit.
  var STAGE_W = 480;          // design-box width  (px) -- matches #stage in css
  var STAGE_H = 320;          // design-box height (px) -- matches #stage in css

  // -------------------------------------------------------------------------
  // Pure carousel logic -- no DOM, node-testable (S-2).
  // -------------------------------------------------------------------------

  function clampIndex(i, count) {
    if (count <= 0) return 0;
    if (i < 0) return 0;
    if (i >= count) return count - 1;
    return i;
  }

  // dir > 0 -> next card; dir < 0 -> previous; 0 -> stay, clamped at the ends.
  // SUPERSEDED FOR NAVIGATION by nextVisibleIndex (US-496 gave it visibility
  // awareness; US-506 gave it wrap). Kept as the count-only helper the deploy
  // kit's smoke test exercises -- it does NOT describe the shipped nav contract.
  function nextIndex(current, dir, count) {
    var step = dir > 0 ? 1 : dir < 0 ? -1 : 0;
    return clampIndex(current + step, count);
  }

  // dx = endX - startX. A swipe LEFT (dx < 0) advances to the NEXT card (+1);
  // a swipe RIGHT (dx > 0) goes to the PREVIOUS card (-1). Travel below the
  // threshold is a tap, not a swipe (0).
  function swipeDirection(dx, threshold) {
    var t = threshold == null ? SWIPE_THRESHOLD_PX : threshold;
    if (Math.abs(dx) < t) return 0;
    return dx < 0 ? 1 : -1;
  }

  // US-482 uniform letterbox scale for the fixed STAGE_W x STAGE_H design box in
  // a viewport of (w x h): the LARGEST scale that still fits BOTH axes, so the
  // whole 480x320 UI stays visible + centered with black bars on the mismatch.
  // A degenerate (<=0 / non-finite) viewport falls back to 1 -- a transient 0x0
  // layout pass must never collapse the UI to nothing.
  function computeStageScale(w, h) {
    if (!(w > 0) || !(h > 0)) return 1;
    return Math.min(w / STAGE_W, h / STAGE_H);
  }

  // Honest-instrument classifier: the shell decides only AVAILABILITY. A null
  // (missing file / HTTP error) or a non-object payload is `unavailable`; a
  // plain object is `available` (the per-card story renders its fields).
  function cardAvailability(raw) {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
      return "unavailable";
    }
    return "available";
  }

  // US-496 (S3) -- the honest whole-card message when a state file is ABSENT or
  // malformed. The shell used to write the bare word "unavailable" on every
  // card. Two cards need to say WHICH instrument is silent, because the wrong
  // reading of their silence is the dangerous one:
  //   dtc   -- silence means "the codes were never read". It must NEVER read as
  //            "No stored codes" (a fabricated clean read) and never as an
  //            alert: the F-6 no-phantom rule at card level.
  //   light -- silence means "the feed stopped", not "dark" (a fabricated 0 lux).
  //   imu   -- (US-497) silence means "the motion feed stopped", NOT "not
  //            moving". A motion instrument reading as stationary is the same
  //            fabrication as a fabricated 0 lux, and a more dangerous one: a
  //            still g-meter is exactly what a parked car looks like.
  // Cards not listed keep the shipped one-word fallback -- this story was not
  // scoped to restyle the ones it does not touch.
  // US-898-b1: the `dtc` entry retired with the dtc-driven ALERTS card. That
  // card now reads states/alerts and paints its own absence ('--' + 'no
  // warnings data', warningsPageView) -- it no longer passes through here.
  var NO_DATA_VIEWS = {
    light: { label: "AMBIENT", reason: "no data -- light feed absent" },
    imu: { label: "MOTION", reason: "no data -- IMU feed absent" },
  };

  function noDataView(name) {
    return Object.prototype.hasOwnProperty.call(NO_DATA_VIEWS, name)
      ? NO_DATA_VIEWS[name]
      : null;
  }

  // US-496 AC-3 -- reveal the vehicle-dependent card(s) ONLY on the positive
  // claim `source.obd.available === true`. Deliberately STRICTER than
  // sourceUnavailable(), which treats an absent `source` block as available for
  // pre-US-429 backward compatibility: that default is right for "should I gray
  // this tile?" and wrong for "should I reveal a vehicle card?". An absent or
  // unreadable system-status leaves "is a car plugged in?" genuinely UNKNOWN,
  // and an unknown must never be rendered as a state (US-492 / US-494) -- so
  // this fails closed to HIDDEN. Hidden, not gray: gray says "this instrument is
  // broken"; hidden says "this instrument does not apply right now", which is
  // the truth on a bench with no car.
  function vehicleConnected(sysData) {
    return (
      isObj(sysData) &&
      isObj(sysData.source) &&
      isObj(sysData.source.obd) &&
      sysData.source.obd.available === true
    );
  }

  // US-496 -- the visible-card geometry a gated card forces. `#track` is a flex
  // row of full-width cards, so a card removed by the [hidden] guard (US-495)
  // takes NO slot: the translateX step count, the page dots and the swipe must
  // all count VISIBLE cards or hiding one slides the carousel to a blank frame.
  // `hidden` is an array of per-card booleans read straight off the DOM
  // (`card.hidden`), so the geometry can never disagree with what is painted.

  // How many visible cards precede `index` -- i.e. its translateX step count.
  function visualPosition(index, hidden) {
    var pos = 0;
    for (var i = 0; i < index; i++) {
      if (!(hidden && hidden[i])) pos++;
    }
    return pos;
  }

  // The next VISIBLE index in `dir`, WRAPPING at the ends (US-506 AC-12 --
  // this replaces the shipped clamp). Two invariants, and the second is the
  // load-bearing one:
  //   1. Swiping past the last card lands on the first, and vice-versa. A kiosk
  //      the operator can dead-end in is worse than one that cycles.
  //   2. The wrap traverses only VISIBLE cards. A wrap that lands on a
  //      vehicle-gated card paints a blank frame the operator cannot swipe out
  //      of -- strictly worse than the clamp it replaces. Same rule the mid-row
  //      skip already enforced, now applied across the seam too.
  // The scan is bounded by hidden.length, so a row with one (or zero) visible
  // cards terminates on `current` instead of spinning: a wrap loop with no
  // visible target is the one way this rewrite could hang the kiosk.
  function nextVisibleIndex(current, dir, hidden) {
    var step = dir > 0 ? 1 : dir < 0 ? -1 : 0;
    if (step === 0) return current;
    var n = hidden.length;
    if (n <= 0) return current;
    for (var k = 1; k <= n; k++) {
      // Positive modulo: JS `%` keeps the sign of the dividend, so a backward
      // wrap past 0 needs the +n before the second reduction.
      var i = (((current + step * k) % n) + n) % n;
      if (!hidden[i]) return i;
    }
    return current;
  }

  // -------------------------------------------------------------------------
  // US-506 (F-124) -- auto-rotate + the velocity swipe model. Pure, node-
  // testable: every decision takes its clock reading as an argument so nothing
  // here reads a timer of its own.
  // -------------------------------------------------------------------------

  // US-541-a (Atlas Option-1, CIO-ratified 2026-08-11 -- resolves BL-031 /
  // I-us536): the keys for which 0 is a REAL VALUE the operator chose, not a
  // misconfiguration to be discarded. This is a PER-KEY opt-in, deliberately
  // not a blanket `>= 0`: for every other key 0 still means "unusable", which
  // is what keeps a permanent freeze inexpressible in config (a `resumeIdleS: 0`
  // must never reach shouldAutoResume and disable the self-unpause).
  //
  // autoRotateS earns it because 0/off vs >0/on is the SAME contract the GAP-3a
  // settings band already encodes end to end -- settingsWriteValue WRITES 0 for
  // off and shouldAutoAdvance/rotateProgress already READ 0 as never-advance.
  // The resolver was the one layer that disagreed, so the operator's Off toggle
  // and US-536's disposition-B freeze fix were both silent no-ops.
  //
  // A future key opts in HERE, one line, on its own argument. Do not widen the
  // guard below instead.
  var ZERO_IS_A_VALUE = { autoRotateS: true };

  // Resolve the injected carousel config over the grounded defaults. Only
  // well-typed, FINITE overrides win, and only if POSITIVE -- or exactly zero
  // on a key that opts in above. A malformed or absent global leaves every
  // default in place (never a zeroed config, which would silently read as a
  // dead feature).
  function resolveCarouselConfig(cfg) {
    var out = {};
    for (var k in CAROUSEL_DEFAULTS) {
      if (Object.prototype.hasOwnProperty.call(CAROUSEL_DEFAULTS, k)) {
        out[k] = CAROUSEL_DEFAULTS[k];
      }
    }
    if (cfg && typeof cfg === "object") {
      for (var key in CAROUSEL_DEFAULTS) {
        if (!Object.prototype.hasOwnProperty.call(CAROUSEL_DEFAULTS, key)) continue;
        if (!Object.prototype.hasOwnProperty.call(cfg, key)) continue;
        var v = cfg[key];
        // NaN and Infinity are rejected for EVERY key, opt-in or not: a NaN
        // period makes `sinceMs >= autoRotateS * 1000` permanently false, i.e.
        // the same silent freeze from a value nobody chose. Only a clean 0 is
        // admitted, and only where 0 was given a meaning.
        if (typeof v !== "number" || !isFinite(v)) continue;
        var zeroOk = Object.prototype.hasOwnProperty.call(ZERO_IS_A_VALUE, key);
        if (v > 0 || (v === 0 && zeroOk)) out[key] = v;
      }
    }
    return out;
  }

  // Should the unpaused carousel advance now? `sinceMs` is the time since the
  // last advance. A non-positive period DISABLES rotation rather than firing
  // every tick -- a carousel spinning at the poll rate is unusable and reads as
  // a hardware fault, so a misconfigured interval must fail to OFF.
  function shouldAutoAdvance(paused, sinceMs, autoRotateS) {
    if (paused) return false;
    if (!(typeof autoRotateS === "number" && autoRotateS > 0)) return false;
    if (!(typeof sinceMs === "number" && isFinite(sinceMs))) return false;
    return sinceMs >= autoRotateS * 1000;
  }

  // Time-to-next as a 0..1 fraction for the calm thin bar (AC-13: no countdown
  // NUMBER -- the bar is the whole readout). Clamped at 1 because the poll is a
  // 250 ms tick, not a real-time clock, so a late tick must not overfill the
  // track. Rotation disabled -> 0, an empty bar: a full bar would promise an
  // advance that is never coming.
  function rotateProgress(sinceMs, autoRotateS) {
    if (!(typeof autoRotateS === "number" && autoRotateS > 0)) return 0;
    if (!(typeof sinceMs === "number" && isFinite(sinceMs)) || sinceMs <= 0) return 0;
    return Math.min(1, sinceMs / (autoRotateS * 1000));
  }

  // Has a paused carousel been quiet long enough to resume? `idleMs` is the
  // time since the last interaction of ANY kind. This is the guard that stops a
  // pause becoming a freeze: the operator who taps once and walks away gets a
  // moving dashboard back rather than a screen stuck on one card forever.
  function shouldAutoResume(paused, idleMs, resumeIdleS) {
    if (!paused) return false;
    if (!(typeof resumeIdleS === "number" && resumeIdleS > 0)) return false;
    if (!(typeof idleMs === "number" && isFinite(idleMs))) return false;
    return idleMs >= resumeIdleS * 1000;
  }

  // US-506 AC-14 -- the VELOCITY swipe model. The shipped gesture was
  // DISTANCE-ONLY (swipeDirection), so it could not tell "I flicked past this"
  // from "I settled here", and every swipe fought the auto-rotate identically.
  //
  //   dx/dy   -- pointer travel (px). Vertical-dominant is ignored so a card
  //              body can still scroll (touch-action: pan-y).
  //   dtMs    -- pointer-down duration.
  //   widthPx -- the card width the travel fraction is measured against.
  //
  // Returns {dir, fast}: `dir` is the shipped direction contract (swipe LEFT
  // advances); `fast` tells the caller whether this was a FLICK (advance +
  // RESUME auto-rotate) or a SETTLE (advance one + PAUSE).
  //
  // Two honest-instrument guards on the derived quantities: an unmeasurable
  // duration (dt <= 0) or an unusable width (a transient 0x0 layout pass)
  // contributes NOTHING rather than a fabricated Infinity. Dividing by either
  // would manufacture a flick out of a measurement failure -- and `fast` is the
  // signal that RESUMES rotation under the operator's finger, so a fabricated
  // one is felt immediately.
  function swipeGesture(dx, dy, dtMs, widthPx, cfg) {
    var c = resolveCarouselConfig(cfg);
    var out = { dir: 0, fast: false };
    if (!(typeof dx === "number" && isFinite(dx))) return out;
    // Vertical gesture -> not a page turn at all.
    if (typeof dy === "number" && isFinite(dy) && Math.abs(dx) < Math.abs(dy)) {
      return out;
    }
    var travel = Math.abs(dx);
    // The deadzone survives the rewrite: distance is still required to count as
    // a swipe AT ALL, so a 5 px twitch cannot become a flick on velocity alone.
    if (travel < c.swipeMinPx) return out;
    out.dir = dx < 0 ? 1 : -1;
    var velocity =
      typeof dtMs === "number" && isFinite(dtMs) && dtMs > 0 ? travel / dtMs : 0;
    var frac =
      typeof widthPx === "number" && isFinite(widthPx) && widthPx > 0
        ? travel / widthPx
        : 0;
    // Either evidence is enough: a quick flick, OR a deliberate drag most of
    // the way across the card (slow, but unmistakably a page turn).
    out.fast =
      velocity >= c.swipeFastVelocityPxPerMs || frac >= c.swipeFastTravelFrac;
    return out;
  }

  // Where to land when the card the operator is ON just became hidden (the
  // vehicle unplugged mid-session): the nearest visible card, preferring the
  // EARLIER one -- the operator's "back", never a forward jump past cards they
  // have not seen. null when nothing is visible, so the caller holds its index
  // rather than clamping onto a hidden card 0.
  function nearestVisibleIndex(current, hidden) {
    for (var d = 0; d < hidden.length; d++) {
      var back = current - d;
      if (back >= 0 && !hidden[back]) return back;
      var fwd = current + d;
      if (fwd < hidden.length && !hidden[fwd]) return fwd;
    }
    return null;
  }

  // -------------------------------------------------------------------------
  // US-400 System Status card -- pure render logic, node-testable (S-3/I-3/
  // I-4/F-1). The card is a verbatim consumer of the `system-status` emitter
  // (Atlas A-3 schema): it maps the state to honest tiles + top-bar glyph
  // states. The cardinal honest-instrument rule (F-1): a level/glyph is ONLY
  // `ok` (green) when the underlying state is genuinely good -- a down /
  // reconnecting / stale / battery state is amber/down/neutral, never green.
  // -------------------------------------------------------------------------

  function isObj(x) {
    return x !== null && typeof x === "object" && !Array.isArray(x);
  }

  // US-429 honest-availability: read the one-truth-per-source availability fact
  // (`state.source.<x>`) the emitter wrote. An ABSENT source block is treated as
  // available (backward compatible with pre-US-429 states); only an explicit
  // `available: false` is unavailable. The reason (why) travels with it.
  function sourceUnavailable(data, name) {
    return (
      isObj(data) &&
      isObj(data.source) &&
      isObj(data.source[name]) &&
      data.source[name].available === false
    );
  }

  function sourceReason(data, name) {
    if (isObj(data) && isObj(data.source) && isObj(data.source[name])) {
      var r = data.source[name].reason;
      if (typeof r === "string" && r) return r;
    }
    return "unavailable";
  }

  // A typed-NA tile: value "NA", the reason as the detail, `unavailable` level.
  // NA is rendered text derived from a NULL+reason -- NEVER a numeric sentinel.
  function naTile(label, reason) {
    return { label: label, value: "NA", detail: reason, level: "unavailable" };
  }

  // -------------------------------------------------------------------------
  // US-700 (F-123) -- LOADING IS A THIRD STATE, and it was missing.
  //
  // THE DEFECT, found by the CIO misreading his own panel at boot exactly as it
  // was built to be misread: a tile whose payload had NOT ARRIVED YET rendered
  // `— / unavailable`, which is BYTE-IDENTICAL to what it renders when the
  // producer is dead. Both readings were honest and the tile was still useless,
  // because one string covering two opposite situations is evidence that cannot
  // do the job it is cited for -- the DISCRIMINATION variant of this project's
  // own anti-pattern. The operator cannot act on it.
  //
  // THREE STATES, THREE RENDERS:
  //   loading      -- nothing has arrived yet and the bound below is still open
  //   ready        -- a payload is in hand. Everything downstream is UNCHANGED,
  //                   including today's typed NA + reason for a payload that
  //                   arrived and is unusable. A known-broken feed keeps its
  //                   reason: "loading" must never dress a defect up as a
  //                   start-up, which would be the same lie in a nicer word.
  //   unavailable  -- no producer, or one that answered once and then died
  //
  // ⚠️ Deliberately NO spinner and NO animation. The panel is read at arm's
  // length in a moving car; a distinct WORD in the big slot is the fix, motion
  // is not.
  // -------------------------------------------------------------------------

  // THE BOUND. A tile that says LOADING forever is the same defect wearing a
  // nicer word, so the pre-fetch state EXPIRES into the honest `unavailable`.
  //
  // Grounded on the PRODUCER'S OWN CADENCE rather than taste: the card states
  // are written every DEFAULT_CARD_STATE_EMIT_INTERVAL = 2.0 s
  // (src/pi/obdii/orchestrator/types.py), so three consecutive missed
  // publications is no longer "still starting" -- it is a feed that is not
  // answering. It also expires INSIDE the boot surface's own 12 s hard cap
  // (config.json pi.splash.bootState.hardCapSeconds), so this panel reaches a
  // definite verdict before the screen that precedes it gives up on the same
  // services.
  var LOADING_GRACE_MS = 6000;

  function loadingGraceMs() {
    return LOADING_GRACE_MS;
  }

  // THE ONE PREDICATE. Every surface that can render a WHOLE state payload asks
  // this, so three states cannot drift into four readings of one fact.
  //
  // `waitedMs` is how long the panel has been asking for a payload that has
  // NEVER arrived, and it is NULL once one has. That null is what stops a feed
  // which answered and then DIED from falling back into "loading" and looking
  // like it is merely starting up -- the mid-drive failure would otherwise
  // acquire the reassuring word at the worst possible moment.
  function loadPhase(payload, waitedMs) {
    if (isObj(payload)) return "ready";
    if (
      typeof waitedMs === "number" &&
      isFinite(waitedMs) &&
      waitedMs >= 0 &&
      waitedMs < LOADING_GRACE_MS
    ) {
      return "loading";
    }
    // Includes a NEGATIVE wait: this Pi has no RTC battery and boots before
    // NTP, so a clock that steps backwards is a real event here. Nonsense
    // resolves to the honest state, never to the comfortable one.
    return "unavailable";
  }

  // The LOADING tile. The word lives in the VALUE slot because that is the slot
  // readable at arm's length -- putting the distinction in the small detail line
  // would leave the two states confusable at exactly the distance the panel is
  // read from, which is the whole defect.
  function loadingTile(label) {
    return {
      label: label,
      value: "LOADING",
      detail: "waiting for first read",
      level: "loading",
    };
  }

  // The waiting-room ledger: which feeds have EVER answered. Kept as a plain
  // object rather than a closure on purpose -- it is the one piece of state this
  // whole feature turns on, and a closure would have put it somewhere no test
  // can hand it a value or read one back.
  function feedObserved(seen, name, payload) {
    var next = isObj(seen) ? seen : {};
    // Only a real payload counts as ARRIVED. A null read (404 / abort /
    // malformed) leaves the feed in the waiting room -- were it to count, the
    // loading window would end on the first failed fetch, i.e. never fire.
    if (isObj(payload)) next[name] = true;
    return next;
  }

  function feedWaitedMs(seen, name, startedAtMs, nowMs) {
    // Null, not 0: a 0 would read as "just started waiting" and would put a dead
    // feed back into loading on every single tick.
    if (isObj(seen) && seen[name] === true) return null;
    if (typeof startedAtMs !== "number" || typeof nowMs !== "number") return null;
    return nowMs - startedAtMs;
  }

  // Power tile: running on battery (UPS backup) -> amber; external -> ok.
  function powerTile(p) {
    if (!isObj(p)) {
      return { label: "POWER", value: "—", detail: "unavailable", level: "unavailable" };
    }
    // US-668: the tile now renders the SENSED SOURCE as its value.
    //
    // It used to render the operator-declared MODE (CAR/WALL) as the value, with
    // the source only in the detail line. The CIO removed the mode on 2026-09-02
    // -- "if I can see the screen then the power is on, it doesn't matter if it
    // is car or wall, it is on" -- and he is right: the value slot was spending
    // the tile's most prominent characters on a fact the viewer already knew by
    // looking at the panel.
    //
    // What it says now is the fact the screen CANNOT tell you by being lit:
    // external power, or running down the UPS battery. During the 2026-08-31 UPS
    // test the panel stayed lit for the whole time the Pi ran on battery toward
    // a graceful poweroff -- BATTERY is exactly the state a viewer cannot infer.
    if (p.source === "battery") {
      return { label: "POWER", value: "BATTERY", detail: "on UPS", level: "amber" };
    }
    if (p.source === "external") {
      return { label: "POWER", value: "EXTERNAL", detail: "wall/car power", level: "ok" };
    }
    // Unresolved stays unavailable rather than guessing a source. US-628's typed
    // reason travels in `reasons.source`, not here.
    return { label: "POWER", value: "—", detail: "unavailable", level: "unavailable" };
  }

  // -------------------------------------------------------------------------
  // US-744 -- the PREVIOUS shutdown's verdict, rendered.
  //
  // US-728 computed this on every boot, published it at `priorShutdown`, and
  // nothing read it: a grep of src/pi/ui/ for the key returned zero. (US-744
  // also found the producer never passed it, so the car published null.)
  //
  // READ-ONLY. The verdict, its words and its caveat are the producer's; this
  // renders them. It classifies nothing -- two producers of one fact is the
  // SSOT defect, not the feature.
  //
  // LEVEL IS ALWAYS `neutral`, including UNGRACEFUL. The verdict is HISTORY:
  // it describes a shutdown that already happened, not a live fault. An amber
  // tile would hold the card at one issue for the whole session over
  // something no longer happening -- the crying-wolf failure the US-509 row
  // floor already refuses for DRIVE=IDLE.
  // -------------------------------------------------------------------------

  // The producer's verdict vocabulary -> the tile's words. An unrecognised
  // verdict is a typed absence, never a guess: a NEW producer state must not
  // be able to render as CLEAN here (the fabricated-green failure).
  var PRIOR_SHUTDOWN_WORDS = {
    clean: "CLEAN",
    ungraceful: "UNGRACEFUL",
    no_record: "NO RECORD",
  };

  function priorShutdownAbsent(reason) {
    return { label: "LAST STOP", value: "—", detail: reason, level: "neutral" };
  }

  function priorShutdownTile(ps, nowTs) {
    // No block at all: the producer could not read a startup_log row. That is
    // "not read", a DIFFERENT fact from the NO RECORD verdict below, and the
    // two must never collapse into one string.
    if (!isObj(ps)) return priorShutdownAbsent("not read (no startup_log row)");

    var word = Object.prototype.hasOwnProperty.call(PRIOR_SHUTDOWN_WORDS, ps.verdict)
      ? PRIOR_SHUTDOWN_WORDS[ps.verdict]
      : null;
    if (word == null) {
      return priorShutdownAbsent(
        ps.verdict == null
          ? "no verdict recorded"
          : "unrecognised verdict: " + String(ps.verdict)
      );
    }

    // AC3: the verdict carries the boot it describes. `notAfterTs` is the
    // recording boot's own stamp -- the only boot reference in the published
    // block -- rendered through the dashboard's existing age idiom, never a
    // second one.
    var age = agoText(nowTs, typeof ps.notAfterTs === "string" ? ps.notAfterTs : null);
    // The Pi has no RTC battery, so most of these stamps were written before
    // NTP settled (198 of 296 rows on the car). An age derived from one is
    // MARKED rather than silently trusted -- and rather than suppressed, which
    // would throw away the only boot reference there is.
    var detail = ps.dataQuality === "clock_unsynced" ? age + " (clock unsynced)" : age;
    return { label: "LAST STOP", value: word, detail: detail, level: "neutral" };
  }

  // Top-bar glyph states (bound to data-state CSS in dashboard.css).
  //
  // US-894-a (spec s4.2.1, closes US-713 + ARCH-061): the single BT glyph is
  // retired with btGlyphState. The slot holds the three-layer link chain, one
  // dot per layer, read VERBATIM from system-status.link -- never from obdLink,
  // and never forced by source.obd (S109 publishes link regardless). Copies of
  // the provider vocabulary (pi.splash.system_status_emitter LINK_LAYERS /
  // LINK_* / VERDICT_*), pinned equal by tests/ui/test_topbar_chain_glyph.py.
  var LINK_CHAIN_LAYERS = ["bt", "adapter", "ecu"];
  // The colour rule (s4.0): amber is keyed to a verdict MEMBER's layer, never to
  // a state, so no state maps to amber here. A key absent from this table --
  // null, or a word the provider has not published -- is a dot we did not
  // read: hollow, never the solid `down` look (ARCH-062).
  var LINK_STATE_LOOK = {
    up: "ok",
    connecting: "neutral",
    retrying: "secondary",
    down: "tertiary",
  };
  // The verdict member keys that name a chain layer (s4.1): only these two can
  // paint a dot amber. The ECU is never a member.
  var LINK_MEMBER_LAYERS = ["bt", "adapter"];

  // The verdict members' keys as a set. A malformed verdict names nobody, so it
  // paints no amber: an amber dot is a claim the provider has to have made.
  function verdictMemberKeys(data) {
    var keys = {};
    var verdict = isObj(data) ? data.verdict : null;
    var members = isObj(verdict) && Array.isArray(verdict.members) ? verdict.members : [];
    for (var i = 0; i < members.length; i++) {
      if (isObj(members[i]) && typeof members[i].key === "string") {
        keys[members[i].key] = true;
      }
    }
    return keys;
  }

  // One look per layer -> {bt, adapter, ecu}. The page applies no threshold:
  // a member's layer is amber whatever its state, everything else is the
  // lookup above.
  function linkChainGlyph(data) {
    var link = isObj(data) && isObj(data.link) ? data.link : {};
    var members = verdictMemberKeys(data);
    var looks = {};
    for (var i = 0; i < LINK_CHAIN_LAYERS.length; i++) {
      var layer = LINK_CHAIN_LAYERS[i];
      var block = link[layer];
      var state = isObj(block) ? block.state : null;
      if (LINK_MEMBER_LAYERS.indexOf(layer) !== -1 && members[layer] === true) {
        looks[layer] = "amber";
      } else if (typeof state === "string"
                 && Object.prototype.hasOwnProperty.call(LINK_STATE_LOOK, state)) {
        looks[layer] = LINK_STATE_LOOK[state];
      } else {
        looks[layer] = "hollow";
      }
    }
    return looks;
  }
  // US-894-c (spec s4.3, Iris I4, Atlas P9): the sync glyph is NEUTRAL. It
  // used to paint `sync.stale` amber with no verdict member behind it -- an
  // amber nobody counted, the s4.0 failure. Sync has no member until US-917,
  // and the glyph goes amber exactly while that member is present.
  function syncGlyphState(data) {
    return verdictMemberKeys(data).sync === true ? "amber" : "neutral";
  }
  // US-696 (CIO ruling 2026-09-09): there is NO `powerGlyphState`. The top-bar
  // lightning glyph was removed -- "if I can see the screen the power is on",
  // so restating it spent a slot in a band that has none to spare. The state
  // function went with its only consumer rather than lingering as residue.
  // The MEASUREMENT is untouched: `power.source` is still sensed and still
  // rendered by `powerTile` on the System Status card, which keeps its Power
  // row. Recorded here because the argument against removal is real and should
  // not have to be rediscovered: the glyph was the only on-screen signal during
  // a UPS ride-down. The CIO's call is that the automatic sequenced poweroff
  // makes that signal unactionable.

  // -------------------------------------------------------------------------
  // US-894-b (spec s3 layout A, s4.1, s4.2) -- the System page is a VERDICT
  // line plus one row per subsystem. It replaces the US-489 summary line and
  // the 2x2 tile grid. The verdict is the provider's (system-status.verdict,
  // S109): the page counts nothing, compares nothing, and composes no reason
  // text -- a member's reason is printed verbatim.
  // -------------------------------------------------------------------------

  // The one no-data mark (spec s4.4): two hyphens, never an em dash.
  var SYS_NO_DATA = "--";

  // s4.1: `ALL OK` when the provider counted nothing, `n ISSUE` / `n ISSUES`
  // otherwise. An absent or malformed verdict is `--`, never ALL OK: ALL OK is
  // the provider's claim that it looked.
  function systemVerdictView(data) {
    var verdict = isObj(data) ? data.verdict : null;
    var n = isObj(verdict) ? verdict.issueCount : null;
    if (typeof n !== "number" || !isFinite(n) || n < 0 || Math.floor(n) !== n) {
      return { text: SYS_NO_DATA, level: "unavailable" };
    }
    if (n === 0) return { text: "ALL OK", level: "ok" };
    return { text: n + (n === 1 ? " ISSUE" : " ISSUES"), level: "amber" };
  }

  // The OBD row's step labels, chain order (spec s3).
  var OBD_STEP_LABELS = { bt: "BT", adapter: "ADAPTER", ecu: "ECU" };

  // s4.2 sentence table (Iris I1): the FIRST layer that is not `up` speaks,
  // looked up by its state -- a lookup on a provider enum, never a comparison
  // (the LIGHT_REASON_TEXT pattern). `null` is the key for a layer not read;
  // a state word the provider has not published is no reading either. The
  // down / retrying words are fallbacks only: under S109 those states make a
  // verdict member, whose reason speaks instead (obdRowView).
  var OBD_LAYER_SENTENCE = {
    bt: {
      connecting: "Bluetooth trying to link (key off?)",
      down: "Bluetooth not linked",
      retrying: "Bluetooth retrying…",
      "null": "Bluetooth not read yet",
    },
    adapter: {
      connecting: "adapter connecting…",
      down: "adapter not answering",
      retrying: "adapter retrying…",
      "null": "adapter not read yet",
    },
    ecu: {
      connecting: "ECU not answering (key off?)",
      down: "ECU not answering (key off?)",
      retrying: "ECU not answering (key off?)",
      "null": "ECU not read yet",
    },
  };
  var OBD_ALL_UP_SENTENCE = "ECU answering";

  function linkLayerState(data, layer) {
    var link = isObj(data) && isObj(data.link) ? data.link : {};
    var block = link[layer];
    var state = isObj(block) ? block.state : null;
    return typeof state === "string"
      && Object.prototype.hasOwnProperty.call(LINK_STATE_LOOK, state) ? state : null;
  }

  // The reason of the first verdict member whose key is in `keys`, verbatim;
  // null when none of them is a member (or its reason is not a string).
  function verdictMemberReason(data, keys) {
    var verdict = isObj(data) ? data.verdict : null;
    var members = isObj(verdict) && Array.isArray(verdict.members) ? verdict.members : [];
    for (var i = 0; i < members.length; i++) {
      var m = members[i];
      if (isObj(m) && keys.indexOf(m.key) !== -1 && typeof m.reason === "string") {
        return m.reason;
      }
    }
    return null;
  }

  function obdWalkSentence(data) {
    for (var i = 0; i < LINK_CHAIN_LAYERS.length; i++) {
      var layer = LINK_CHAIN_LAYERS[i];
      var state = linkLayerState(data, layer);
      if (state === "up") continue;
      var words = OBD_LAYER_SENTENCE[layer];
      return state !== null && Object.prototype.hasOwnProperty.call(words, state)
        ? words[state] : words["null"];
    }
    return OBD_ALL_UP_SENTENCE;
  }

  // The OBD row (s4.2): one step look per layer -- the top-bar chain's looks
  // (linkChainGlyph, so the bar and the row cannot disagree), except that a
  // layer not read is DASHED here where the bar draws it hollow (AC 4: never
  // the solid `down` look). The sentence is a member's reason verbatim when
  // the row has one (amber, it is counted); otherwise the walk above (neutral).
  function obdRowView(data) {
    var looks = linkChainGlyph(data);
    var steps = [];
    for (var i = 0; i < LINK_CHAIN_LAYERS.length; i++) {
      var look = looks[LINK_CHAIN_LAYERS[i]];
      steps.push(look === "hollow" ? "dashed" : look);
    }
    var reason = verdictMemberReason(data, LINK_MEMBER_LAYERS);
    return {
      key: "obd",
      label: "OBD",
      steps: steps,
      sentence: reason !== null ? reason : obdWalkSentence(data),
      level: reason !== null ? "amber" : "secondary",
    };
  }

  // The OBD detail (s4.6, parked): per layer, THIS session only (ARCH-062) --
  // the state, since when (the layer's `ts`), and the last success
  // (`lastOkTs`, S109 publishes it per layer); `--` wherever the provider
  // published nothing, never a time from an earlier boot. No adapter MAC and
  // no retry count: neither has a publish field (Atlas A3), so neither line is
  // drawn.
  function obdDetailView(data) {
    var link = isObj(data) && isObj(data.link) ? data.link : {};
    var row = obdRowView(data);
    var layers = [];
    for (var i = 0; i < LINK_CHAIN_LAYERS.length; i++) {
      var layer = LINK_CHAIN_LAYERS[i];
      var block = isObj(link[layer]) ? link[layer] : {};
      var state = linkLayerState(data, layer);
      layers.push({
        layer: layer,
        label: OBD_STEP_LABELS[layer],
        look: row.steps[i],
        state: state === null ? SYS_NO_DATA : state,
        since: state !== null && typeof block.ts === "string"
          ? fmtStamp(block.ts) : SYS_NO_DATA,
        lastOk: state !== null && typeof block.lastOkTs === "string"
          ? fmtStamp(block.lastOkTs) : SYS_NO_DATA,
      });
    }
    return { head: "OBD", layers: layers, sentence: row.sentence, level: row.level };
  }

  // -------------------------------------------------------------------------
  // US-894-c (spec s4.3, s4.6; Atlas A4, Iris I3/W3) -- the DATA row: capture
  // and sync on one row, replacing the SYNC / DRIVE / CAPTURE tiles. The
  // capture word comes from states/capture-health, never from the drive
  // state; `stalled` comes from the `capture` verdict MEMBER alone (one source
  // per fact), so the row and the count can never disagree.
  // -------------------------------------------------------------------------

  // Copies of the provider's vocabulary (pi.obdii.capture_health STATE_* /
  // REASON_NEVER_WRITTEN / FEED_NAMES), pinned equal by
  // tests/ui/test_system_page_data_row.py.
  var CAPTURE_STATE_WORD = { ok: "recording", idle: "idle" };
  var CAPTURE_STATE_STALLED = "stalled";
  var CAPTURE_REASON_NEVER_WRITTEN = "never_written";
  // s4.6 feed order and labels (OBD, light, IMU, UPS).
  var CAPTURE_FEEDS = [["obd", "OBD"], ["light", "LIGHT"], ["imu", "IMU"], ["ups", "UPS"]];
  var CAPTURE_FEED_WORD = { ok: "writing", stalled: "stalled", idle: "idle" };
  var CAPTURE_MEMBER_KEY = "capture";
  // A4: the ECU states whose fact carries `ECU not answering`. A member-less
  // stall names that cause only from link.ecu; with the ECU up, or not read,
  // no cause is printed (on a cold boot it would be false).
  var DATA_ECU_SILENT_STATES = ["down", "retrying", "connecting"];

  // `n rows waiting`, `1 row waiting`; a `+` on the number itself when tables
  // were left out of the count (`1+ rows waiting` stays plural). Null is
  // `rows not read`, never 0.
  function rowsWaitingText(n, notCounted) {
    if (typeof n !== "number" || !isFinite(n) || n < 0) return "rows not read";
    var plus = Array.isArray(notCounted) && notCounted.length > 0 ? "+" : "";
    return fmtThousands(n) + plus + (n === 1 && plus === "" ? " row waiting" : " rows waiting");
  }

  // `n event rows` only when > 0; zero, null and junk print nothing.
  function eventRowsText(n) {
    if (typeof n !== "number" || !isFinite(n) || n <= 0) return null;
    return fmtThousands(n) + (n === 1 ? " event row" : " event rows");
  }

  function sameLocalDay(a, b) {
    return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth()
      && a.getDate() === b.getDate();
  }

  // s4.3 date rule (Iris I3, UIDEV-010), local time against the payload's own
  // `ts`: the same day -> the time (`6:42 PM`); the day before -> `yesterday`
  // with NO time (the time would not fit, and the ellipsis would cut it to a
  // wrong-looking stub); older -> `Oct 12`. A bare time is only ever today's,
  // so with no usable `now` the date form is used. Null -> `no sync on
  // record`; an unparseable stamp is `--`, never a raw string or 1970.
  function syncWhenText(lastOkTs, nowTs) {
    if (typeof lastOkTs !== "string") return "no sync on record";
    if (!ISO_INSTANT.test(lastOkTs)) return "synced " + SYS_NO_DATA;
    var d = new Date(lastOkTs);
    if (isNaN(d.getTime())) return "synced " + SYS_NO_DATA;
    var now = typeof nowTs === "string" && ISO_INSTANT.test(nowTs) ? new Date(nowTs) : null;
    if (now !== null && !isNaN(now.getTime())) {
      if (sameLocalDay(d, now)) return "synced " + fmtTimeOfDay(d, false);
      var yesterday = new Date(now.getTime());
      yesterday.setDate(yesterday.getDate() - 1);
      if (sameLocalDay(d, yesterday)) return "synced yesterday";
    }
    return "synced " + STAMP_MONTHS[d.getMonth()] + " " + two(d.getDate());
  }

  // The capture word and its look. s4.0: amber ONLY for the member.
  function dataCaptureWord(data, captureData) {
    if (verdictMemberReason(data, [CAPTURE_MEMBER_KEY]) !== null) {
      return { word: CAPTURE_STATE_STALLED, look: "amber", basis: "member" };
    }
    var cap = isObj(captureData) ? captureData : {};
    if (cap.state === CAPTURE_STATE_STALLED) {
      // W3: a top-level stall with no member never reads `stalled`.
      return {
        word: cap.reason === CAPTURE_REASON_NEVER_WRITTEN ? "no rows" : "stopped",
        look: "secondary",
        basis: cap.reason === CAPTURE_REASON_NEVER_WRITTEN ? "noRows" : "stopped",
      };
    }
    if (cap.state === "ok") return { word: CAPTURE_STATE_WORD.ok, look: "ok", basis: "recording" };
    if (cap.state === "idle") return { word: CAPTURE_STATE_WORD.idle, look: "secondary", basis: "idle" };
    return { word: SYS_NO_DATA, look: "tertiary", basis: "unread" };
  }

  // The sentence's first part: the member's reason verbatim, else the
  // capture state's words; null when a member-less stall has no cause to
  // name and no age to print.
  function dataCaptureSentence(data, captureData, capture) {
    if (capture.basis === "member") {
      return verdictMemberReason(data, [CAPTURE_MEMBER_KEY]);
    }
    if (capture.basis === "recording") return "all 4 feeds writing";
    if (capture.basis === "idle") return "not driving";
    if (capture.basis === "unread") return "capture not read yet";
    if (DATA_ECU_SILENT_STATES.indexOf(linkLayerState(data, "ecu")) !== -1) {
      return "ECU not answering";
    }
    if (capture.basis === "noRows") return "no row logged this session";
    var age = isObj(captureData) ? captureData.lastRowSecondsAgo : null;
    if (typeof age !== "number" || !isFinite(age)) return null;
    return "last row " + agoSecsText(Math.floor(age));
  }

  // The DATA row: value = the capture word (its own look) + ` · synced
  // <when>` (neutral); the sentence as parts, so only the member's reason
  // is amber and the rows waiting beside it stay neutral (s4.0).
  function dataRowView(data, captureData) {
    var sync = isObj(data) && isObj(data.sync) ? data.sync : {};
    var wifi = isObj(data) && isObj(data.wifi) ? data.wifi : {};
    var capture = dataCaptureWord(data, captureData);
    var parts = [];
    var first = dataCaptureSentence(data, captureData, capture);
    if (first !== null) {
      parts.push({ text: first, level: capture.basis === "member" ? "amber" : "secondary" });
    }
    // s4.3 (F-155): neutral, never counted; a null home is no word at all.
    if (wifi.home === false) parts.push({ text: "away from home", level: "secondary" });
    parts.push({ text: rowsWaitingText(sync.rowsWaiting, sync.notCounted), level: "secondary" });
    var events = eventRowsText(sync.edrRowsWaiting);
    if (events !== null) parts.push({ text: events, level: "secondary" });
    var texts = [];
    for (var i = 0; i < parts.length; i++) texts.push(parts[i].text);
    var tail = " · " + syncWhenText(sync.lastOkTs, isObj(data) ? data.ts : null);
    return {
      key: "data",
      label: "DATA",
      word: capture.word,
      look: capture.look,
      tail: tail,
      value: capture.word + tail,
      parts: parts,
      sentence: texts.join(" · "),
      level: capture.basis === "member" ? "amber" : "secondary",
    };
  }

  // The DATA detail (s4.6, parked): per feed its word and freshness age
  // (`lastSampleSecondsAgo` -- lastRowSecondsAgo is top-level only), then
  // sync: last data stored (full stamp), rows waiting, event rows, the
  // uncounted tables by name, and at home. A stalled feed is amber only while
  // the `capture` member exists (the member's amber sits on the feed).
  function dataDetailView(data, captureData) {
    var sync = isObj(data) && isObj(data.sync) ? data.sync : {};
    var wifi = isObj(data) && isObj(data.wifi) ? data.wifi : {};
    var feeds = isObj(captureData) && isObj(captureData.feeds) ? captureData.feeds : {};
    var member = verdictMemberReason(data, [CAPTURE_MEMBER_KEY]) !== null;
    var rows = [];
    for (var i = 0; i < CAPTURE_FEEDS.length; i++) {
      var name = CAPTURE_FEEDS[i][0];
      var feed = isObj(feeds[name]) ? feeds[name] : {};
      var known = typeof feed.state === "string"
        && Object.prototype.hasOwnProperty.call(CAPTURE_FEED_WORD, feed.state);
      var look = "tertiary";
      if (feed.state === "ok") look = "ok";
      else if (feed.state === CAPTURE_STATE_STALLED) look = member ? "amber" : "secondary";
      else if (feed.state === "idle") look = "secondary";
      var age = freshAgeText(feed.lastSampleSecondsAgo);
      rows.push({
        feed: name,
        label: CAPTURE_FEEDS[i][1],
        state: known ? CAPTURE_FEED_WORD[feed.state] : SYS_NO_DATA,
        look: look,
        age: age === null ? SYS_NO_DATA : age,
      });
    }
    var events = sync.edrRowsWaiting;
    var notCounted = Array.isArray(sync.notCounted) && sync.notCounted.length > 0
      ? "not counted: " + sync.notCounted.join(", ") : null;
    var row = dataRowView(data, captureData);
    return {
      head: "DATA",
      feeds: rows,
      lastStored: typeof sync.lastOkTs === "string" ? fmtStamp(sync.lastOkTs) : "no sync on record",
      rowsWaiting: typeof sync.rowsWaiting === "number" && isFinite(sync.rowsWaiting)
        && sync.rowsWaiting >= 0 ? fmtThousands(sync.rowsWaiting) : "rows not read",
      eventRows: typeof events === "number" && isFinite(events) && events >= 0
        ? fmtThousands(events) : SYS_NO_DATA,
      notCounted: notCounted,
      atHome: wifi.home === true ? "yes" : wifi.home === false ? "no" : "unknown",
      sentence: row.sentence,
      level: row.level,
    };
  }

  // -------------------------------------------------------------------------
  // US-894-b (Atlas B9 + A1 2026-10-22) -- THE parked fact for the System page.
  // ONE module-level accessor: `parked` is the tick's DEBOUNCED engineParked
  // (gear P/N held 8 s, US-511-b) and `gearKnown` the RAW `states/gear`
  // available === true -- the same fact clearButtonView(data, parked,
  // gearKnown) is handed. The tick is its ONLY writer (publishParked). Never
  // gearParked here: that is the raw per-tick predicate, and reading it would
  // skip the 8 s hold. Listeners fire on a change of EITHER value.
  // -------------------------------------------------------------------------
  var parkedFact = { parked: false, gearKnown: false };
  var parkedListeners = [];

  function currentParked() {
    return { parked: parkedFact.parked, gearKnown: parkedFact.gearKnown };
  }

  function onParkedChange(fn) {
    if (typeof fn === "function") parkedListeners.push(fn);
  }

  // Returns true when the fact changed (and the listeners fired). Only a
  // strict true is parked or known: anything else fails closed.
  function publishParked(parked, gearKnown) {
    var next = { parked: parked === true, gearKnown: gearKnown === true };
    if (next.parked === parkedFact.parked && next.gearKnown === parkedFact.gearKnown) {
      return false;
    }
    parkedFact = next;
    for (var i = 0; i < parkedListeners.length; i++) {
      parkedListeners[i](currentParked());
    }
    return true;
  }

  // -------------------------------------------------------------------------
  // US-509 (F-124) -- the drill-down behind the verdict line (US-894-b: the
  // summary line and the 2x2 grid it sat over are gone; the drill stays until
  // US-894-f retires it). The rows are a PRESENTATION of the view's tiles --
  // no second read, no re-derivation.
  // -------------------------------------------------------------------------

  // Severity rank over the tile-level vocabulary. Three buckets, not two:
  //   ok            -- genuinely good.
  //   neutral       -- nominal but inactive (DRIVE=IDLE: "not recording").
  //   unavailable   -- a known-UNKNOWN.
  //   amber / down  -- the worst rows, listed first.
  var SYS_LEVEL_RANK = { ok: 0, neutral: 1, unavailable: 2, amber: 3, down: 4 };

  // A level this mapper has not been taught resolves to `unavailable`, NEVER to
  // ok -- a future tile level must not be able to drop out of the list.
  function sysLevelRank(level) {
    return Object.prototype.hasOwnProperty.call(SYS_LEVEL_RANK, level)
      ? SYS_LEVEL_RANK[level]
      : SYS_LEVEL_RANK.unavailable;
  }

  // The listing floor. Deliberately `unavailable`, not `amber`:
  //   * `ok`      -- never listed. A green source in a fault list is a
  //                  FABRICATED fault.
  //   * `neutral` -- never listed either. DRIVE=IDLE is the only neutral this
  //                  card produces and it means "not recording", NOT "broken";
  //                  listing it would report a fault in the commonest state
  //                  there is (key on, no drive started) -- crying wolf.
  //   * `unavailable` and worse -- listed. Excluding known-unknowns would
  //                  make a tappable headline open an EMPTY overlay, which is
  //                  the exact dead end US-509 removed.
  var SYS_ROW_FLOOR = SYS_LEVEL_RANK.unavailable;

  // The typed absence for a source that publishes no age at all. No source
  // publishes a per-source age today (the OBD link's was always null and was
  // removed, US-876-a), so every row MUST say the age was not reported rather
  // than render "seen 0s ago" -- which would claim we had just seen a source we
  // never timed. Same fabrication as a zeroed altitude (US-508): an unmeasured
  // quantity is an absence, never a zero.
  var SYS_NO_AGE = "age not reported";

  // One source's freshness for its drill-down row: always the typed absence
  // until a provider publishes a real per-source age.
  function sysRowFreshness() {
    return SYS_NO_AGE;
  }

  // Worst-first rows, one per non-OK source. Ties keep the view's tile order
  // (US-894-b: SYS_TILE_ORDER went with the grid), so the list never
  // reshuffles between polls under the operator's eyes. Built by
  // walking the rank buckets top-down rather than sorting, which makes that
  // stability a property of the construction instead of the sort algorithm.
  function systemIssueRows(tiles, data) {
    var rows = [];
    if (!isObj(tiles)) return rows;
    var rank = SYS_LEVEL_RANK.down;
    for (; rank >= SYS_ROW_FLOOR; rank--) {
      var keys = Object.keys(tiles);
      for (var i = 0; i < keys.length; i++) {
        var key = keys[i];
        var tile = tiles[key];
        if (!isObj(tile) || sysLevelRank(tile.level) !== rank) continue;
        var freshness = sysRowFreshness();
        var detail = typeof tile.detail === "string" ? tile.detail : "";
        rows.push({
          key: key,
          label: tile.label,
          value: tile.value,
          // The row carries the TILE's level verbatim -- the chip and the grid
          // cell behind it are then incapable of disagreeing.
          level: tile.level,
          // The emitter's own words. The drill-down explains what the card
          // already said; it does not re-diagnose. Dropped when it only repeats
          // the freshness the row prints beside it.
          reason: detail === freshness ? "" : detail,
          freshness: freshness,
        });
      }
    }
    return rows;
  }

  // US-559: the SYNC counts moved off the tile (CIO 2026-08-20) and land here.
  // Reference facts, NOT faults -- so they are a section of their own rather
  // than a row in the issue list, where a healthy source would read as a
  // fabricated fault (the US-509 floor above still holds, untouched).
  //
  // Taken VERBATIM off the tile the grid renders. The overlay presents a fact
  // the card already computed; it never re-derives one, so the two cannot
  // disagree -- the same rule the issue rows follow.
  // US-744 adds the PREVIOUS shutdown's verdict here, and deliberately NOT as a
  // sixth grid tile: the card is held to a 4-fact ceiling (US-557 / Iris), which
  // a sixth tile breaks -- and the story forbids re-budgeting the band or
  // shrinking type to make room. It belongs in this section on its own merits
  // anyway: it is a REFERENCE FACT about a boot that already ended, not a live
  // source, so it is neither a fault (it would cry wolf all session) nor a
  // status tile (it describes the past, not now).
  function systemDiagnostics(tiles, data) {
    var diags = [];
    if (!isObj(tiles)) return diags;
    // US-894-c: the SYNC counts line is gone with syncTile and the retired
    // sync.rows / sync.pending; the DATA row and its detail carry the backlog.
    // Built from the payload the card was rendered from -- one read, so the
    // overlay can never contradict it. Listed on every REAL card, including
    // when the verdict is absent: the absence is itself the fact worth reading
    // ("not read"), and a row that vanishes when the producer goes dark is how
    // this verdict stayed invisible from US-728 until US-744 found it.
    //
    // Gated on the card having tiles at all, which keeps US-509's guarantee
    // intact: a drill built over NO card still has nothing behind it and stays
    // untappable. Pinning that gate open is the inert-guard shape its own test
    // (test_systemDrill_nothingBehindTheLine_isStillNotATapTarget) forbids.
    if (isObj(data) && Object.keys(tiles).length > 0) {
      var ps = priorShutdownTile(data.priorShutdown, data.ts);
      diags.push({
        key: "priorShutdown",
        label: ps.label,
        text: ps.value + " · " + ps.detail,
      });
    }
    return diags;
  }

  // The summary line is a tap target ONLY when something is behind it -- an
  // affordance that opens an empty list is a misleading control.
  //
  // US-559 widened WHAT counts as "something", and deliberately not the rule
  // itself: US-509 gated this on faults because faults were all the overlay
  // held. Now the counts live here too, so a healthy card is tappable. Left
  // gated on faults, a non-zero PENDING backlog on an otherwise-OK sync would
  // have been unreachable and "moved to the drill-down" would have meant
  // deleted. The gate still reads real content -- it is not pinned open.
  function systemDrill(tiles, data) {
    var rows = systemIssueRows(tiles, data);
    var diagnostics = systemDiagnostics(tiles, data);
    return {
      rows: rows,
      diagnostics: diagnostics,
      tappable: rows.length > 0 || diagnostics.length > 0,
    };
  }

  // -------------------------------------------------------------------------
  // US-894-d (spec s4.4, s4.6; Iris I5, W1; Atlas A6) -- the WIFI row, its
  // detail and the top-bar glyph, keyed on (wifi.state, source.wifi.reason).
  // The emitter derives `state` (ARCH-007); the page applies NO RSSI
  // threshold. Amber is the `wifi` verdict MEMBER's (s4.0): a failed read is
  // the one counted WiFi state, and `weak` is never amber.
  // -------------------------------------------------------------------------

  // Copies of the provider's vocabulary (pi.network.wifi_reader
  // WIFI_REASON_*, system_status_emitter REASON_WIFI_UNKNOWN / VERDICT_WIFI
  // and deriveWifiState's bands), pinned equal by
  // tests/ui/test_system_page_wifi_row.py. There is no `not_associated`
  // (Atlas A6): not associated is the reading `down`, reason null.
  var WIFI_REASON_NOT_READ = "not_read";
  var WIFI_REASON_NMCLI_ABSENT = "nmcli_absent";
  var WIFI_REASON_READ_FAILED = "read_failed";
  var WIFI_MEMBER_KEY = "wifi";
  var WIFI_STATE_DOWN = "down";
  // The two absences in words; read_failed speaks through its member.
  var WIFI_REASON_WORDS = {
    not_read: "not read yet",
    nmcli_absent: "no WiFi tool on this host",
  };
  // `up` only means above the weak band, so `good`, never `strong`.
  var WIFI_SIGNAL_WORD = { up: "good signal", weak: "weak signal" };
  var WIFI_STRENGTH_WORD = { up: "good", weak: "weak" };
  var WIFI_NO_LEVEL = "no signal level";

  function wifiReading(data) {
    var wifi = isObj(data) && isObj(data.wifi) ? data.wifi : {};
    var source = isObj(data) && isObj(data.source) && isObj(data.source.wifi)
      ? data.source.wifi : {};
    return {
      wifi: wifi,
      state: typeof wifi.state === "string" ? wifi.state : null,
      ssid: typeof wifi.ssid === "string" && wifi.ssid ? wifi.ssid : null,
      available: source.available === true,
      reason: typeof source.reason === "string" ? source.reason : null,
    };
  }

  // True when the link was read and wlan0 is on a network: a band (up /
  // weak), or W1's associated-with-no-level (available, state null). The page
  // tells that from an unread link by `available`, never by a missing ssid.
  function wifiLinked(r) {
    if (!r.available) return false;
    if (r.state === null) return r.wifi.state === null;
    return Object.prototype.hasOwnProperty.call(WIFI_SIGNAL_WORD, r.state);
  }

  // The home word (I5): home true -> `home` green; false -> `other network`;
  // null -> `connected` (never guessed either way).
  function wifiHomeWord(home) {
    if (home === true) return { word: "home", look: "ok" };
    if (home === false) return { word: "other network", look: "secondary" };
    return { word: "connected", look: "secondary" };
  }

  // The WIFI row (s4.4 table). A member's reason is printed verbatim.
  function wifiRowView(data) {
    var r = wifiReading(data);
    var isMember = verdictMemberKeys(data)[WIFI_MEMBER_KEY] === true;
    var word = SYS_NO_DATA;
    var look = "tertiary";
    var sentence = "";
    if (isMember || r.reason === WIFI_REASON_READ_FAILED) {
      // Amber only with the member: a verdict-absent file counted nothing.
      var member = verdictMemberReason(data, [WIFI_MEMBER_KEY]);
      word = "? not read";
      look = isMember ? "amber" : "secondary";
      sentence = member !== null ? member : "";
    } else if (wifiLinked(r)) {
      var home = wifiHomeWord(r.wifi.home);
      word = home.word;
      look = home.look;
      sentence = (r.ssid !== null ? r.ssid + " · " : "")
        + (r.state === null ? WIFI_NO_LEVEL : WIFI_SIGNAL_WORD[r.state]);
    } else if (r.available && r.state === WIFI_STATE_DOWN) {
      word = "down";
      sentence = "not connected";
    } else if (!r.available) {
      sentence = r.reason === WIFI_REASON_NMCLI_ABSENT
        ? WIFI_REASON_WORDS.nmcli_absent : WIFI_REASON_WORDS.not_read;
    }
    return {
      key: "wifi",
      label: "WIFI",
      word: word,
      look: look,
      tail: "",
      value: word,
      sentence: sentence,
      level: isMember ? "amber" : "secondary",
    };
  }

  // The WIFI detail (s4.6, parked): SSID, strength (word + dBm; `no signal
  // level` and no dBm when associated with no level), home yes / no /
  // unknown, `not connected to any network` for `down`, and the typed reason
  // in words. No IP: there is no field, so the line is not drawn (I5).
  function wifiDetailView(data) {
    var r = wifiReading(data);
    var row = wifiRowView(data);
    var member = verdictMemberReason(data, [WIFI_MEMBER_KEY]);
    var rssi = r.available && typeof r.wifi.rssiDbm === "number" && isFinite(r.wifi.rssiDbm)
      ? r.wifi.rssiDbm : null;
    var strength = SYS_NO_DATA;
    if (rssi !== null) {
      strength = (Object.prototype.hasOwnProperty.call(WIFI_STRENGTH_WORD, r.state)
        ? WIFI_STRENGTH_WORD[r.state] + " · " : "") + rssi + " dBm";
    } else if (wifiLinked(r) && r.state === null) {
      strength = WIFI_NO_LEVEL;
    }
    var reason = null;
    if (member !== null) {
      reason = member;
    } else if (r.reason !== null && !r.available
               && Object.prototype.hasOwnProperty.call(WIFI_REASON_WORDS, r.reason)) {
      reason = WIFI_REASON_WORDS[r.reason];
    } else if (r.reason === WIFI_REASON_READ_FAILED) {
      reason = SYS_NO_DATA;
    }
    var home = r.available ? r.wifi.home : null;
    return {
      head: "WIFI",
      state: { text: row.word, look: row.look },
      network: r.available && r.ssid !== null ? r.ssid : SYS_NO_DATA,
      strength: strength,
      link: r.available && r.state === WIFI_STATE_DOWN ? "not connected to any network" : null,
      home: home === true ? "yes" : home === false ? "no" : "unknown",
      reason: reason,
      reasonLevel: row.level,
    };
  }

  // ARCH-007 (Atlas ruling 2026-08-20 s2.1/s2.3) + US-894-d (s4.4). The
  // emitter has ALREADY derived the band; this maps it to a glyph state and
  // applies NO threshold of its own:
  //   `up` ok; `weak` neutral (a band on a working link, never amber);
  //   `down` the slashed glyph (a MEASUREMENT: we looked, no link);
  //   no reading -- not_read, nmcli_absent, associated with no level, or no
  //   payload -- `dim` arcs with NO slash (a slash claims down, lit arcs a
  //   level); read_failed amber, the one amber WiFi state.
  function wifiGlyphState(data) {
    var r = wifiReading(data);
    var member = verdictMemberKeys(data)[WIFI_MEMBER_KEY] === true;
    // Before the unread return: a failed read is also unavailable. Amber is
    // the member's (s4.0), so a failed read nothing counted stays dim.
    if (member || r.reason === WIFI_REASON_READ_FAILED) return member ? "amber" : "dim";
    if (!r.available) return "dim";
    if (r.state === "up") return "ok";
    if (r.state === "weak") return "neutral";
    if (r.state === WIFI_STATE_DOWN) return "down";
    return "dim";
  }

  // The full structured view consumed by the DOM renderer + the node tests.
  // Non-object payload -> null (the shell renders `unavailable`).

  // US-688: `captureData` is a SECOND state file (states/capture-health), read
  // on the same slow tick. It is a separate slot rather than a key inside
  // system-status because the two have different producers -- capture health is
  // the orchestrator's fact about ITSELF, not about a car source -- and the
  // gear tile already established this shape. Optional: a caller that passes
  // one argument gets no capture tile.
  //
  // US-894-b: the page is `verdict` + `rows` (spec s3 layout A); the OBD row
  // is the first row, and the rows not yet built are absent. The obdLink tile
  // is gone with the block it read (Atlas A2/P6). `tiles` now only feed the
  // drill-down behind the verdict until their rows land (US-894-c/e/f).
  //
  // US-894-c: the DATA row is the second row; the SYNC / DRIVE / CAPTURE
  // tiles and their drill rows are gone (the drill keeps POWER until US-894-e).
  // US-894-d: the WIFI row is the third.
  function systemStatusView(data, captureData) {
    if (!isObj(data)) return null;
    var tiles = {
      power: powerTile(data.power),
    };
    return {
      // s4.1: the provider's count, never the page's.
      verdict: systemVerdictView(data),
      rows: [obdRowView(data), dataRowView(data, captureData), wifiRowView(data)],
      // s4.6: the rows' details, from the SAME read.
      obdDetail: obdDetailView(data),
      dataDetail: dataDetailView(data, captureData),
      wifiDetail: wifiDetailView(data),
      // US-509: the drill-down behind the verdict -- one read of the state
      // file feeds the page AND the overlay.
      drill: systemDrill(tiles, data),
      tiles: tiles,
      glyphs: {
        // US-894-a: the link chain ignores source.obd (s4.2.1).
        bt: linkChainGlyph(data),
        // US-894-c (I4): neutral without a `sync` member.
        sync: syncGlyphState(data),
        wifi: wifiGlyphState(data),
      },
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  // -------------------------------------------------------------------------
  // US-401 Battery Health card -- pure render logic, node-testable (F-8/F-9/
  // F-10/F-11/F-2). The card is an HONEST consumer of the `battery-health`
  // emitter (Atlas A-3 schema) for the Pi UPS LiPo cell -- NEVER the car
  // battery (F-11). The two render-breaking traps are locked here:
  //   F-8  the SoC percent is shown ONLY when `soc` is a real number; a null
  //        soc omits the percent and shows volts -- a voltage is NEVER painted
  //        as a percent.
  //   F-9  a GOOD verdict ALWAYS carries "last health check · <date> (<age>)"
  //        (computed from ts - lastHealthCheckTs, both in the state file) so a
  //        month-old reading is never mistaken for live. The producer adds a
  //        second layer upstream: it forces `unknown` once the pack's counted
  //        monthly test is over 45 days old (ARCH-065; US-504 used 90 days).
  // The drain ladder DOM is present ONLY when `draining === true` (F-2 / A-6).
  // -------------------------------------------------------------------------

  var BATTERY_LABEL = "Pi UPS battery"; // F-11: never "vehicle/car battery".
  var MS_PER_DAY = 86400000;

  // US-504: ONE verdict vocabulary end-to-end -- the words Spool's producer
  // emits (pi/power/battery_health_verdict.py) are the words the card carries.
  // The earlier green/attn/low display tiers were a SECOND enum for the same
  // fact and are retired; an unrecognised value falls through to the honest
  // unavailable state rather than being guessed at.
  //
  // NEVER alarm-red, at any state INCLUDING `replace` (Spool, load-bearing):
  // the UPS carries the Pi through power loss to a clean shutdown, which needs
  // well under a minute against the ~12 we measure. `replace` means the
  // data-integrity margin thinned, NOT that anything on the car is at risk, so
  // this signal must never compete with coolant or a DTC-STOP on a driving
  // surface. `ok` is withheld from degraded/replace for the opposite reason --
  // it would claim health the data does not support. Neutral is the only tier
  // that neither alarms nor reassures.
  function healthLevel(h) {
    if (h === "good") return "ok";
    if (h === "degraded" || h === "replace") return "neutral";
    return "unavailable";
  }

  function healthValue(h) {
    if (h === "good") return "GOOD";
    if (h === "degraded") return "DEGRADED";
    if (h === "replace") return "REPLACE";
    return "—";
  }

  // US-736: WHY the verdict is unknown. US-632 publishes one of six machine
  // reasons in `reasons.health` (battery_health_verdict.UNKNOWN_REASONS); before
  // this table the card threw all six away and every one read as the same
  // em-dash. Keys are the producer's names VERBATIM, and a guard test holds
  // them equal to UNKNOWN_REASONS. ARCH-065 (2026-10-03) replaced the three
  // drain reasons with the monthly-test / sync ones.
  var BATTERY_HEALTH_REASON_TEXT = {
    no_database: "no battery log database",
    log_unreadable: "battery log unreadable",
    clock_unreadable: "clock unreadable",
    no_monthly_test: "no monthly battery test yet",
    monthly_test_stale: "monthly battery test overdue",
    too_few_syncs: "too few home syncs to judge",
  };

  // ARCH-065: a RESOLVED verdict says why it is what it is -- T (minutes to the
  // reserve floor) against J (the at-home job, seconds) -- or null when the
  // producer published no numbers. Never for an unknown verdict: a margin
  // beside "we cannot say" would be a second, contradictory account.
  function healthMarginText(data) {
    if (data.health !== "good" && data.health !== "degraded" && data.health !== "replace") return null;
    if (typeof data.timeToFloorS !== "number" || !isFinite(data.timeToFloorS)) return null;
    if (typeof data.jobAvgS !== "number" || !isFinite(data.jobAvgS)) return null;
    return Math.round(data.timeToFloorS / 60) + " min vs " + data.jobAvgS + " s job" +
      (data.provisional === true ? " (provisional)" : "");
  }

  // Words for an unknown verdict's reason, or null for a resolved verdict (a
  // reason explains an ABSENCE). The two fallbacks are typed and can never
  // equal a known string: a missing reason and an untaught one are different
  // facts, and neither may pass for "last drain test too old".
  function healthReasonText(data) {
    if (data.health !== "unknown") return null;
    var code = isObj(data.reasons) ? data.reasons.health : null;
    if (typeof code !== "string" || code === "") return "reason not reported";
    if (Object.prototype.hasOwnProperty.call(BATTERY_HEALTH_REASON_TEXT, code)) {
      return BATTERY_HEALTH_REASON_TEXT[code];
    }
    return "unrecognised reason (" + code + ")";
  }

  // The date portion (YYYY-MM-DD) of an ISO instant, or null.
  function isoDate(ts) {
    if (typeof ts !== "string") return null;
    var i = ts.indexOf("T");
    return i > 0 ? ts.slice(0, i) : ts;
  }

  // Whole-day age between two ISO instants (now - then). Null if either is not
  // parseable -- we never assert an age we cannot compute.
  function ageDays(nowTs, thenTs) {
    if (typeof nowTs !== "string" || typeof thenTs !== "string") return null;
    var now = Date.parse(nowTs);
    var then = Date.parse(thenTs);
    if (isNaN(now) || isNaN(then)) return null;
    return Math.floor((now - then) / MS_PER_DAY);
  }

  function ageText(days) {
    if (days == null) return "age unknown";
    if (days <= 0) return "today";
    if (days === 1) return "1 day ago";
    return days + " days ago";
  }

  // Relative age with SUB-DAY resolution (US-505). ageText above is day-grain,
  // which is right for a health-check date but throws the signal away for a
  // drive that ended 25 minutes ago ("today"). Rather than declare a second age
  // vocabulary for the same fact -- the cross-module enum-identity drift that
  // cost the 9-drain saga -- this extends the SAME one downward and hands off to
  // ageText at a day and beyond, so "1 day ago" / "3 days ago" have exactly one
  // definition on the whole surface.
  //
  // Null on either input, or an unparseable instant, is "age unknown": we never
  // assert an age we cannot compute, and never render NaN.
  function agoText(nowTs, thenTs) {
    if (typeof nowTs !== "string" || typeof thenTs !== "string") return "age unknown";
    var now = Date.parse(nowTs);
    var then = Date.parse(thenTs);
    if (isNaN(now) || isNaN(then)) return "age unknown";
    return agoSecsText(Math.floor((now - then) / 1000));
  }

  // agoText's words for an age already in whole seconds (US-894-c: the DATA
  // row's `last row <age>` is capture-health's lastRowSecondsAgo, an age, not
  // an instant). floor(secs / 86400) is ageDays' floor for the same span.
  function agoSecsText(secs) {
    // A FUTURE instant means clock skew, not a negative age. The Pi has no RTC
    // battery and boots before NTP settles, so a stamp ahead of `now` is a
    // routine transient -- "-5 min ago" would be a visible nonsense.
    if (secs < 60) return "just now";
    if (secs < 3600) return Math.floor(secs / 60) + " min ago";
    if (secs < 86400) return Math.floor(secs / 3600) + " h ago";
    return ageText(Math.floor(secs / 86400));
  }

  // The stale-green guard line (F-9). ALWAYS produced so a GREEN verdict can
  // never be shown without its data-age. A missing check -> "never".
  function healthCheckLine(d) {
    var date = isoDate(d.lastHealthCheckTs);
    if (date == null) {
      return { date: null, ageDays: null, label: "last health check · never" };
    }
    var age = ageDays(d.ts, d.lastHealthCheckTs);
    return {
      date: date,
      ageDays: age,
      label: "last health check · " + date + " (" + ageText(age) + ")",
    };
  }

  // VCELL tile -- authoritative volts, ALWAYS rendered in volts, never percent.
  function vcellTile(d) {
    if (typeof d.vcellV !== "number") {
      return { label: "CELL", value: "—", detail: "unavailable", level: "unavailable" };
    }
    return {
      label: "CELL",
      value: d.vcellV.toFixed(2) + " V",
      detail: BATTERY_LABEL,
      level: "neutral",
    };
  }

  // SoC tile (F-8) -- the percent renders ONLY when `soc` is a real number from
  // the MAX17048 register; null -> omit the percent (shown:false), the card
  // falls back to volts. A voltage is NEVER rendered as a percent.
  function socTile(d) {
    if (typeof d.soc !== "number") {
      return {
        label: "CHARGE",
        value: "—",
        detail: "% unavailable · see volts",
        level: "unavailable",
        shown: false,
      };
    }
    return {
      label: "CHARGE",
      value: d.soc + "%",
      detail: d.socCalibrated === true ? "register" : "(uncalibrated)",
      level: "neutral",
      shown: true,
    };
  }

  // US-504: the TEMP tile is REMOVED. The MAX17048 is a voltage-based fuel
  // gauge (VCELL/SOC/CRATE/MODE/VERSION/HIBRT/CONFIG/VALRT/VRESET/STATUS) with
  // no temperature register at all, so the tile had no source it could ever
  // read and rendered "not captured" on every row ever logged. The
  // `ambient_temp_c` COLUMN survives -- a future BMP390 carries a temperature
  // channel that legitimately fills it, and the tile comes back with it.

  // Failsafe ladder view (F-2 / A-6) -- present ONLY when draining is true. The
  // runtime minutes render ONLY when the power tier supplied a real number
  // (Spool S-2); otherwise the failsafe shows stage + volts, never a fabricated
  // estimate. draining:false -> null (the DOM renderer draws no ladder).
  function ladderView(d) {
    if (d.draining !== true) return null;
    var l = isObj(d.ladder) ? d.ladder : {};
    var rt = typeof l.runtimeRemainingS === "number" ? l.runtimeRemainingS : null;
    return {
      stage: typeof l.stage === "string" ? l.stage : "DRAINING",
      thresholds: isObj(l.thresholds) ? l.thresholds : null,
      runtimeRemainingS: rt,
    };
  }

  // The full structured view consumed by the DOM renderer + the node tests.
  // Non-object payload -> null (the shell renders `unavailable`).
  function batteryHealthView(data) {
    if (!isObj(data)) return null;
    // US-429: the UPS/MAX17048 is a single source -- when it is unavailable the
    // WHOLE card is a typed NA ("gauge unreadable"), never a blank or a stale
    // last-real cell reading.
    if (sourceUnavailable(data, "ups")) {
      return {
        label: BATTERY_LABEL,
        unavailable: true,
        reason: sourceReason(data, "ups"),
        ts: typeof data.ts === "string" ? data.ts : null,
      };
    }
    // US-736: the reason goes IN FRONT of the F-9 line, never in place of it.
    // ARCH-065: so does a resolved verdict's T-vs-J margin.
    var reason = healthReasonText(data);
    var margin = reason === null ? healthMarginText(data) : null;
    var checkLabel = healthCheckLine(data).label;
    return {
      label: BATTERY_LABEL,
      unavailable: false,
      health: {
        label: "HEALTH",
        value: healthValue(data.health),
        detail: reason !== null ? reason + " · " + checkLabel
              : margin !== null ? margin + " · " + checkLabel : checkLabel,
        level: healthLevel(data.health),
        reason: reason,
      },
      vcell: vcellTile(data),
      soc: socTile(data),
      healthCheck: healthCheckLine(data),
      ladder: ladderView(data),
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  // -------------------------------------------------------------------------
  // US-420 / US-661 LTFT Trend card -- pure render logic, node-testable (F-096).
  // Long-Term Fuel Trim is a MULTI-DRIVE signal. The `ltft-trend` emitter is the
  // SSOT that gates, aggregates and CLASSIFIES; this view only maps the verdict
  // -> a tile level + bar colours, it never classifies. Honest-instrument
  // (defense-in-depth): an insufficient trend is forced to a non-green headline
  // HERE too, so a mislabeled state can't paint a confident green off too little
  // data.
  //
  // US-661 MOVED THE HEADLINE OFF THE NEWEST DRIVE AND ONTO THE ROLLING MEDIAN.
  // It used to print `current.ltftAvg` -- one drive's mean -- which Spool's
  // TUNER-005 contract measured as carrying NO information: drive means spread
  // up to 3.72 pp between drives on the same day with nothing wrong, so
  // "anyone reading that for drift finds drift, every time". The median over 5
  // drives resolves to about +/-0.6 pp. `points` still carries the per-drive
  // bars (they are the shape of the window, not the verdict).
  // -------------------------------------------------------------------------

  // Signed percent to 2 dp (e.g. -6.25% / +2.10%); a non-number -> "--".
  function fmtLtftPct(n) {
    if (typeof n !== "number" || !isFinite(n)) return "--";
    return (n > 0 ? "+" : "") + n.toFixed(2) + "%";
  }

  var LTFT_TREND_TEXT = {
    improving: "trend: migrating toward 0",
    worsening: "trend: drifting from 0",
    stable: "trend: stable",
  };

  function ltftPointView(p) {
    return {
      driveId: typeof p.driveId === "number" ? p.driveId : null,
      value: fmtLtftPct(p.ltftAvg),
      level: typeof p.level === "string" ? p.level : "unavailable",
    };
  }

  function ltftTrendView(data) {
    if (!isObj(data)) return null;
    var pts = Array.isArray(data.points) ? data.points.filter(isObj) : [];
    var median =
      typeof data.median === "number" && isFinite(data.median) ? data.median : null;
    // Sufficient ONLY when the emitter says so, real points exist, AND a median
    // was actually computed. The median clause is the US-661 half: the headline
    // now RENDERS the median, so a payload claiming sufficiency without one
    // could otherwise paint "insufficient data" under a confident green level.
    var sufficient = data.sufficient === true && pts.length > 0 && median !== null;
    // The headline verdict: the emitter's level when sufficient, else forced to
    // `insufficient` (never inherits ok/green off too little data).
    var headLevel = sufficient
      ? (typeof data.level === "string" ? data.level : "unavailable")
      : "insufficient";
    var trendKey = typeof data.trend === "string" ? data.trend : null;
    var minDrives = typeof data.minDrives === "number" ? data.minDrives : 5;
    // The producer's own reason for the absence, when it has one. It
    // distinguishes "the engine has not warmed up yet" (permanent for roughly
    // one drive in four, and NOT a drive-count problem) from "we have not
    // driven enough yet" -- printing the drive-count text for a warming engine
    // would name the wrong cause.
    var reason =
      typeof data.reason === "string" && data.reason !== "" ? data.reason : null;
    var detail = sufficient
      ? (trendKey && LTFT_TREND_TEXT[trendKey] ? LTFT_TREND_TEXT[trendKey] : "")
      : (reason || "need " + minDrives + "+ drives (" + pts.length + " captured)");
    return {
      label: "LTFT (bank 1)",
      sufficient: sufficient,
      headline: {
        label: "LTFT · " + minDrives + "-drive median",
        value: sufficient ? fmtLtftPct(median) : "insufficient data",
        detail: detail,
        level: headLevel,
      },
      trend: trendKey,
      points: pts.map(ltftPointView),
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  // --- US-890-a Fuel card, the trend row (F-127) -----------------------------
  //
  // specs/v030-fuel-page-design.md s4.4. The Fuel card takes the Fuel Trim
  // card's slot and keeps its source: states/ltft-trend through the same
  // vehicle-gated source-card route, with `ltftTrendView`'s sufficiency rule.
  // What changes is the drawing:
  //   dots      EXACTLY the points the headline median uses (inMedian true).
  //             Closes US-730 by rule: no chart shows a window its headline
  //             does not use, so a 7-drive payload draws its newest 5;
  //   median    one flat solid line across those dots (the provider publishes
  //             ONE median, not a per-drive series);
  //   baseline  the epoch baseline, dashed;
  //   colour    the provider's `level` alone -- the dots never colour, and
  //             nothing here compares a trim with a number.
  // Insufficient -> the provider's reason, verbatim, and no chart (US-890-g:
  // after a reset that reason is the provider's own "ECU relearning"). The y
  // range is the drawn values' own extent: geometry, not a scale.
  var FUEL_TREND_LABEL = "FUEL TRIM TREND";
  var FUEL_TREND_W = 100;
  var FUEL_TREND_H = 30;
  var FUEL_TREND_INSET = 4;

  function finiteNumber(n) {
    return typeof n === "number" && isFinite(n);
  }

  function fuelTrendChart(dots, median, baseline) {
    var lo = median;
    var hi = median;
    for (var i = 0; i < dots.length; i++) {
      lo = Math.min(lo, dots[i].value);
      hi = Math.max(hi, dots[i].value);
    }
    if (baseline !== null) {
      lo = Math.min(lo, baseline);
      hi = Math.max(hi, baseline);
    }
    var span = FUEL_TREND_H - 2 * FUEL_TREND_INSET;
    var yOf = function (v) {
      return engineHistoryCoord(hi === lo ? FUEL_TREND_H / 2
        : FUEL_TREND_INSET + (hi - v) / (hi - lo) * span);
    };
    var out = [];
    for (var j = 0; j < dots.length; j++) {
      out.push({
        driveId: dots[j].driveId,
        x: engineHistoryCoord((j + 0.5) / dots.length * FUEL_TREND_W),
        y: yOf(dots[j].value),
      });
    }
    return {
      dots: out,
      median: { x1: out[0].x, x2: out[out.length - 1].x, y: yOf(median) },
      baseline: baseline === null ? null : { y: yOf(baseline) },
    };
  }

  function fuelTrendView(data) {
    var base = ltftTrendView(data);
    if (!base) return null;
    var pts = Array.isArray(data.points) ? data.points.filter(isObj) : [];
    var dots = [];
    for (var i = 0; i < pts.length; i++) {
      var p = pts[i];
      if (base.sufficient && p.inMedian === true && finiteNumber(p.ltftAvg)) {
        dots.push({ driveId: typeof p.driveId === "number" ? p.driveId : null, value: p.ltftAvg });
      }
    }
    return {
      label: FUEL_TREND_LABEL,
      sufficient: base.sufficient,
      level: base.headline.level,
      value: base.sufficient ? base.headline.value : null,
      reason: base.sufficient ? null : base.headline.detail,
      chart: dots.length
        ? fuelTrendChart(dots, data.median, finiteNumber(data.baseline) ? data.baseline : null)
        : null,
    };
  }

  // -------------------------------------------------------------------------
  // US-540-b SOURCE CARDS (F-127) -- Battery, Fuel Trim and Light, one card
  // each. These three were standalone cards, were merged into the US-507
  // "Health" card when the CIO called six screens too many, and are cards again
  // now: the US-540-a legibility scale changes the arithmetic that call was made
  // on. At secondary 26px a card affords roughly three facts, and Health was
  // carrying six -- a container of three unrelated readouts is precisely the
  // thing the scale cannot pay for, and a screen is the cheaper thing to spend.
  //
  // The VIEW layer is unchanged across both moves, which is the point: each card
  // consumes its OWN state file through the SAME view function it has used in
  // every arrangement, so every honest-instrument state travels with it
  // (battery F-9 stale-green guard, light null/stale individual graying,
  // fuel-trim insufficient-never-green).
  //
  // Two properties stay load-bearing:
  //
  //   INDEPENDENCE -- availability is resolved PER SOURCE. The merge had to
  //   fight for this (one card-level check would have blanked two live
  //   instruments from one real fault); split back out it is structural, and
  //   this table is what keeps it so rather than a card-level branch.
  //
  //   THE GATE SPEAKS INSTEAD OF HIDING -- fuel trim stays vehicle-gated, and
  //   keeps the US-507 wording rather than reverting to the pre-US-507 hide.
  //   US-540-b locks SIX cards, and a card that vanishes on a bench breaks the
  //   set exactly where the CIO reads the panel most days. The gate is
  //   evaluated BEFORE the data, and a gated card carries no view at all -- a
  //   stale ltft-trend file left on disk from the last drive is exactly the
  //   input that would otherwise let a bench paint a confident fuel trim for an
  //   engine that is not running.
  // -------------------------------------------------------------------------

  // The gated wording. Deliberately NOT the no-data vocabulary: "does not apply"
  // and "is broken" are different facts, and telling an operator with a running
  // engine that there is no engine is the worse of the two mistakes.
  var FUEL_TRIM_GATED_REASON = "no engine data";

  // The table IS the vocabulary (one place, so a retitle cannot land in the
  // markup and the renderer out of step). `noData` is the per-source fallback
  // for a source with no entry in NO_DATA_VIEWS -- a bare "unavailable" does not
  // say WHICH instrument went silent, and the card title is not a substitute
  // (it is still painted when the body is a typed NA).
  var SOURCE_CARDS = [
    {
      key: "battery-health", title: "Battery",
      noData: { label: "BATTERY", reason: "no data -- UPS feed absent" },
    },
    {
      key: "light", title: "Light",
      noData: { label: "AMBIENT", reason: "no data -- light feed absent" },
    },
    // US-890-a: the Fuel card. Its source is still ltft-trend, but it paints
    // only the card's trend row (`slot`): the airflow / loop / trim / MPG rows
    // above it are the card's own markup and never wait on this gate.
    {
      key: "ltft-trend", title: "Fuel", slot: ".fuel-trend",
      vehicleGated: true,
      noData: { label: FUEL_TREND_LABEL, reason: "no data -- trend not computed" },
    },
  ];

  function sourceCardSpecs() {
    return SOURCE_CARDS;
  }

  function sourceCardSpec(key) {
    for (var i = 0; i < SOURCE_CARDS.length; i++) {
      if (SOURCE_CARDS[i].key === key) return SOURCE_CARDS[i];
    }
    return null;
  }

  // Build the per-source view. Kept as a switch on the key rather than a
  // function reference in the table so the three signatures (which genuinely
  // differ -- only the light view needs the dim config, a clock and the STOP
  // test) stay explicit.
  //
  // US-893-b: the Light page paints its OWN absence ('--' + 'no light data' in
  // its own layout, the brightness it fell back to beside it), so its view is
  // built even with no payload; `absent` tells the shell the feed is missing.
  function sourceView(key, data, cfg, nowMs, alarmActive, settings) {
    if (key === "light") return lightPageView(data, cfg, nowMs, alarmActive, settings);
    if (cardAvailability(data) !== "available") return null;
    if (key === "battery-health") return batteryHealthView(data);
    if (key === "ltft-trend") return fuelTrendView(data);
    return null;
  }

  //
  // US-700: these cards are SIBLINGS of the idle face's BATTERY tile and share
  // its defect exactly -- "no data -- UPS feed absent" is a confident claim at
  // t=0. Fixing one and not the other would re-create the confusion one swipe
  // away, which is why the story's conditionalOutcome names the shared shape
  // rather than the three tiles it was reported on.
  function sourceCardView(spec, data, sysData, cfg, nowMs, waitedMs, alarmActive, settings) {
    var base = { key: spec.key, title: spec.title, label: spec.noData.label };
    // The gate is checked FIRST and short-circuits: a gated card must carry no
    // reading, not a suppressed one (nothing downstream can leak what was never
    // derived). US-700 keeps it first ON PURPOSE -- a gated card has no reading
    // to be waiting FOR, and "loading" on a bench with no car would promise data
    // that cannot arrive until an engine does.
    if (spec.vehicleGated && !vehicleConnected(sysData)) {
      base.gated = true;
      base.unavailable = false;
      base.loading = false;
      base.na = { label: spec.noData.label, reason: FUEL_TRIM_GATED_REASON };
      base.view = null;
      return base;
    }
    var view = sourceView(spec.key, data, cfg, nowMs, alarmActive, settings);
    base.gated = false;
    if (view === null || view.absent === true) {
      if (loadPhase(data, waitedMs) === "loading") {
        base.loading = true;
        base.unavailable = false;
        base.na = null;
        base.view = null;
        return base;
      }
      base.loading = false;
      base.unavailable = true;
      // Reuse the shipped whole-card wording where one exists (light), so the
      // silent-instrument phrasing lives in exactly one place.
      base.na = noDataView(spec.key) || spec.noData;
      // US-893-b: the Light page's own absent view (null for every other card).
      base.view = view;
      return base;
    }
    base.loading = false;
    base.unavailable = false;
    base.na = null;
    base.view = view;
    return base;
  }

  // -------------------------------------------------------------------------
  // US-403 System Setup menu -- pure, node-testable logic (D-6/D-7/A-7/A-8).
  // The menu is reachable by a deliberate ~5s long-press (a filling ring; an
  // early release cancels) OR the top-bar `⋮`. Service control is on an
  // INSTALL-FIXED allow-list that MIRRORS service_control.py + the 51- polkit
  // rule; `eclipse-powerwatch` (the safe-shutdown guard) is RESTART-ONLY. The
  // kiosk is unprivileged -- the action POST is authorized by polkit, and the
  // server re-checks this allow-list (defense-in-depth), so a UI bug can never
  // drive an off-list action.
  // -------------------------------------------------------------------------

  var LONG_PRESS_MS = 5000;     // sustained hold to open the menu (D-6)
  var LONG_PRESS_ARM_MS = 600;  // hold before the ring starts showing
  var LONG_PRESS_MOVE_PX = 10;  // movement above this = a swipe/scroll, cancel

  // Allow-list mirror (service_control.SERVICE_ALLOWLIST + the 51- polkit rule).
  var SERVICE_ALLOWLIST = {
    "eclipse-obd.service": ["start", "stop", "restart"],
    "eclipse-sync.service": ["start", "stop", "restart"],
    "eclipse-powerwatch.service": ["restart"],
    "eclipse-dashboard.service": ["stop", "restart"],
  };

  // The OBD-II service rows shown in the menu (D-6). powerwatch carries no Stop
  // (canStop:false) because stopping the safe-shutdown guard could leave the Pi
  // unprotected on key-off (D-7 / F-7 / I-10).
  function serviceMenuItems() {
    return [
      { unit: "eclipse-obd.service", label: "eclipse-obd", sub: "data capture",
        canStop: true, canRestart: true },
      { unit: "eclipse-sync.service", label: "eclipse-sync", sub: "server upload",
        canStop: true, canRestart: true },
      { unit: "eclipse-powerwatch.service", label: "eclipse-powerwatch",
        sub: "safe-shutdown guard", canStop: false, canRestart: true },
    ];
  }

  function uiIsAllowed(unit, verb) {
    var verbs = SERVICE_ALLOWLIST[unit];
    return !!verbs && verbs.indexOf(verb) !== -1;
  }

  // Consequential actions confirm before acting (Stop, and Exit which is a
  // dashboard Stop); Restart self-recovers and acts directly. No single tap
  // performs a consequential action (F-6: the menu itself is behind long-press).
  function requiresConfirm(verb) {
    return verb === "stop";
  }

  // Build a validated action request, or null if the UI allow-list forbids it
  // (the server re-checks regardless). Carries the confirm flag for the DOM.
  function actionRequest(unit, verb) {
    if (!uiIsAllowed(unit, verb)) return null;
    return { unit: unit, verb: verb, confirm: requiresConfirm(verb) };
  }

  // --- US-532 (F-126) Settings band ----------------------------------------
  //
  // Iris Option B (CIO 2026-08-03): the Slice-1 settings render as a band at
  // the TOP of this same setup-menu overlay, ABOVE the service rows -- safe
  // persistent preferences on top, destructive service/Exit below.
  //
  // The keys are the overlay's own FLAT dot-paths, verbatim: they are what the
  // state server injects them under (window.DISPLAY_SETTINGS) AND what POST
  // /settings takes as its body `key`. A prettified display key would need a
  // mapping table, and that table is precisely the thing that drifts from the
  // write gate's allow-list.
  // US-533: an apply-state is a CLAIM ABOUT A CONSUMER, and each of these has
  // now been wired and proven, so the conservative US-532 placeholder
  // ("applies on restart" on every row) is gone. Only states an actual consumer
  // earned appear here -- an unused entry is a label nobody has verified, and
  // the next story will reach for it as if someone had.
  // US-668 removed `live: "applies now"`. pi.power.mode was the ONLY row that
  // claimed it, and the claim rested on PowerModeProvider re-reading the effective
  // value every cycle. With that setting deleted, no consumer re-reads anything
  // per-cycle -- so keeping the label would leave a note with no row behind it,
  // which is exactly what test_noDeadApplyStatesAreLeftInTheMapping forbids: a
  // label nobody has checked against a consumer, waiting for the next story to
  // reach for it as though it had been.
  var SETTINGS_APPLY_NOTES = {
    reload: "applies on reload",
    "capture-restart": "applies on capture restart",
  };

  // AUTO-ROTATE is "reload", NOT "restart" -- and the difference is load-bearing.
  // Atlas's original GAP 1 remedy was an eclipse-states-http bounce, but that
  // unit runs User=mcornelison and polkit's manage-units grant deliberately
  // excludes the state server (BL-030 B1), so the bounce is DENIED on the Pi: a
  // "restart" label would have sent the operator to an action they cannot take,
  // and a self-restart attempt would have been a silent no-op. The CIO ratified
  // the alternative that deletes the constraint instead of authorising it
  // (2026-08-08): the server resolves pi.display.carousel PER REQUEST, so the
  // new period lands on the next page load -- which this band triggers itself.
  //
  // POWER MODE was removed by US-668 (CIO, 2026-09-02): "if I can see the
  // screen then the power is on, it doesn't matter if it is car or wall, it is
  // on." It was an operator-declared fact whose only consumer was the card that
  // displayed it back to the operator -- nothing branched on it. The SENSED
  // power source stays; that one the display cannot tell you by existing.
  //
  // CALIBRATION / AUTO-ANALYZE are "capture-restart": both are read ONCE into a
  // constructor at orchestrator start, so "live" would be a lie -- and the bare
  // "restart" US-532 shipped was true but useless, because the unit the operator
  // would reach for (states-http, the only one this band talks to) is the wrong
  // one. Name the service or the label does not help anybody.
  var SETTINGS_SPECS = [
    { key: "pi.display.carousel.autoRotateS", label: "Auto-rotate",
      kind: "seconds", apply: "reload" },
    { key: "pi.calibration.mode", label: "Calibration mode",
      kind: "bool", apply: "capture-restart" },
    { key: "pi.analysis.triggerAfterDrive", label: "Auto-analyze after drive",
      kind: "bool", apply: "capture-restart" },
  ];

  var SETTINGS_PENDING_NOTE = "saving…";

  // US-533 B1: how long the "saved" note stays on screen before the reload that
  // actually applies an auto-rotate change. Long enough that the operator sees
  // the save was accepted, short enough that the reload reads as part of the
  // same tap rather than as the panel spontaneously restarting.
  var SETTINGS_RELOAD_DELAY_MS = 700;

  function settingsPendingNote() {
    return SETTINGS_PENDING_NOTE;
  }

  function settingsSpecs() {
    var out = [];
    for (var i = 0; i < SETTINGS_SPECS.length; i++) {
      var spec = SETTINGS_SPECS[i];
      out.push({
        key: spec.key,
        label: spec.label,
        kind: spec.kind,
        apply: spec.apply,
        // Derived from one mapping, never written per row: a future `apply` flip
        // then cannot leave a stale note contradicting it.
        applyNote: SETTINGS_APPLY_NOTES[spec.apply],
      });
    }
    return out;
  }

  // Every apply-state the band DECLARES. Exported so a test can prove the set
  // matches the set the rows actually use -- a note with no row behind it has
  // never been checked against a consumer.
  function settingsApplyStates() {
    var out = [];
    for (var k in SETTINGS_APPLY_NOTES) {
      if (Object.prototype.hasOwnProperty.call(SETTINGS_APPLY_NOTES, k)) out.push(k);
    }
    return out;
  }

  // Does this save need the page reloaded to take effect? (US-533 B1.)
  //
  // True ONLY for an apply:"reload" row whose write actually SUCCEEDED. Both
  // halves matter: reloading after a rejected write would wipe the "couldn't
  // save" note off the screen and repaint the unchanged value, which reads as
  // success -- and reloading a row that applies live or on a service restart is
  // a disruption the operator did not ask for (it closes the menu and restarts
  // every poll). The argument is the settingsSaveResult OUTPUT, not the raw
  // response, so the same non-echo discipline that governs the repaint governs
  // this: a body that merely looks successful cannot trigger a reload.
  function settingsReloadNeeded(spec, res) {
    return !!spec && spec.apply === "reload" && settingsSaveResult(res).ok;
  }

  // The choices offered for one setting: a 2-choice segmented control, and
  // "unknown" is expressible as *no* choice selected, which is how an
  // unreadable setting shows itself instead of defaulting to a confident Off.
  //
  // US-421: the 3-choice CAR/WALL/UNKNOWN branch for kind "mode" is gone.
  // US-668 removed pi.power.mode from SETTINGS_SPECS, so no spec could reach
  // it -- a control nothing can produce, reading as live code. Every kind the
  // renderer branches on is now a kind the table declares, enforced as a set
  // relation by tests/ui/test_carousel_settings_kind_coverage.py.
  // The `spec` argument is kept: every call site passes one, and the control
  // shape is a property OF a spec -- a future kind that needs a different
  // control adds a branch here, and the coverage guard makes sure it is a kind
  // the table actually declares.
  function settingsChoices(spec) {
    return [
      { value: false, label: "Off" },
      { value: true, label: "On" },
    ];
  }

  // US-878-c (Atlas B13): one entry of the injected settings blob. The server
  // sends {found, value} per key, so a key that RESOLVED to null (overrideLevel
  // = auto) is told apart from one it could not resolve. Anything else -- no
  // blob, a missing key, a bare value, found not exactly true -- is not found.
  function settingsEntry(source, key) {
    var entry = isObj(source) ? source[key] : null;
    if (!isObj(entry) || entry.found !== true ||
        !Object.prototype.hasOwnProperty.call(entry, "value")) {
      return { found: false, value: null };
    }
    return { found: true, value: entry.value };
  }

  // Render one settings row from its EFFECTIVE value. `known:false` means the
  // server could not resolve a value -- rendered Unknown, never Off: "Off" is a
  // claim about stored state, and we were told there isn't one (honest
  // instrument). GAP 3a: auto-rotate is DERIVED from autoRotateS > 0; no
  // separate autoRotate bool exists on this side either.
  function settingsRowView(spec, value) {
    var kind = spec ? spec.kind : null;
    var known = false;
    var on = null;
    var display = "Unknown";
    if (kind === "seconds") {
      known = typeof value === "number" && isFinite(value);
      if (known) {
        on = value > 0;
        display = on ? "On" : "Off";
      }
    } else if (kind === "bool") {
      known = typeof value === "boolean";
      if (known) {
        on = value;
        display = on ? "On" : "Off";
      }
    }
    return {
      key: spec ? spec.key : null,
      label: spec ? spec.label : "",
      kind: kind,
      apply: spec ? spec.apply : null,
      applyNote: spec ? SETTINGS_APPLY_NOTES[spec.apply] : "",
      known: known,
      value: known ? value : null,
      on: on,
      display: display,
    };
  }

  // Is this choice the one currently stored? An unknown row selects NOTHING --
  // highlighting a choice would assert a stored value we do not have.
  function settingsChoiceActive(view, choiceValue) {
    if (!view || !view.known) return false;
    // US-421: the kind "mode" branch (and the always-null `mode` field it read)
    // went with the CAR/WALL control above.
    return view.on === choiceValue;
  }

  // The value to PERSIST for a chosen control state. GAP 3a: auto-rotate off
  // writes 0 and on writes the shipped interval, so both directions round-trip
  // through the one autoRotateS key. Booleans are coerced to REAL booleans --
  // the overlay's validator takes bool only, so a truthy string would 400.
  function settingsWriteValue(spec, desired) {
    if (!spec) return null;
    if (spec.kind === "seconds") {
      return desired ? CAROUSEL_DEFAULTS.autoRotateS : 0;
    }
    return !!desired;
  }

  // Read a POST /settings response HONESTLY (Iris §3). The value a row repaints
  // with comes from the server's RE-READ (`res.value`), NEVER from what was
  // requested -- an optimistic repaint would show an "on" the Pi never stored.
  // A body with no `value` at all (401, network failure, non-JSON) yields null,
  // i.e. Unknown, because we genuinely do not know what is stored.
  function settingsSaveResult(res) {
    var obj = !!res && typeof res === "object";
    var has =
      obj && Object.prototype.hasOwnProperty.call(res, "value");
    var ok = obj && res.ok === true;
    return {
      ok: ok,
      note: ok ? "saved" : "couldn't save",
      value: has ? res.value : null,
    };
  }

  // Long-press ring fill fraction 0..1 (clamped). holdMs defaults to the full
  // open threshold.
  function longPressProgress(elapsedMs, holdMs) {
    var hold = holdMs == null ? LONG_PRESS_MS : holdMs;
    if (hold <= 0) return 1;
    var p = elapsedMs / hold;
    if (p < 0) return 0;
    if (p > 1) return 1;
    return p;
  }

  function isLongPressComplete(elapsedMs, holdMs) {
    var hold = holdMs == null ? LONG_PRESS_MS : holdMs;
    return elapsedMs >= hold;
  }

  // Movement beyond the threshold means the gesture is a swipe/scroll, not a
  // press -> cancel the long-press.
  function exceedsMoveCancel(dx, dy, threshold) {
    var t = threshold == null ? LONG_PRESS_MOVE_PX : threshold;
    return Math.sqrt(dx * dx + dy * dy) > t;
  }

  // US-659 (CIO ruling 2026-08-31, punch-list H6) -- THE `⋮` VISIBILITY GATE
  // WAS REMOVED HERE. `menuAccess(parked)` used to live at this point and
  // returned `{tapVisible: parked === true, longPress: true}`; US-490 hid the
  // top-bar kebab whenever the vehicle did not read parked, US-511 debounced
  // the signal behind it, and the click handler read the rendered `hidden` flag
  // back as defence in depth.
  //
  // THE RULING: always show the menu. The 5s long-press was ALWAYS state-blind,
  // so the menu was reachable in every state the gate hid the glyph in -- the
  // glyph was not protecting the affordance, it was misreporting it. The
  // long-press is unchanged and is now the only gate on the menu.
  //
  // WHAT IS STILL TRUE, so nobody rebuilds this from the wrong premise: a
  // single tap now opens the MENU in every state, not an action. Every
  // consequential item inside it keeps its own confirm (`requiresConfirm`), and
  // Exit still routes through the confirming action.
  //
  // DO NOT RESTORE THIS unless a ruling replaces H6.
  // tests/ui/test_carousel_kebab_always_visible.py fails on the identifiers,
  // on any write to the button's `hidden` flag, and on the rendered cascade.
  //
  // `carouselIdle`, `parkedInit` and `parkedNext` all survive below: carouselIdle
  // still drives the idle home face, and the US-511 debounce was left intact
  // but UNWIRED (TD-us659). US-889-c is its next consumer: the Engine card's
  // CHECK ENGINE count line is a tap to the Alerts card only while parked.

  // -------------------------------------------------------------------------
  // US-511 (F-124) -- the DEBOUNCED `parked` signal behind the ⋮ affordance.
  //
  // US-490 keyed the kebab straight off the emitter's `idle` SSOT boolean, so
  // every brief OBD-availability blip took the button off the screen and put it
  // straight back. Flicker on a fixed affordance does not read as "the state
  // changed" -- it reads as a broken panel. This inserts a HYSTERESIS debounce
  // between the flag and the menu policy:
  //
  //   not parked -> parked      raw parked held TRUE  for >= parkedOnS  (8 s)
  //   parked -> not parked      raw parked held FALSE for >= parkedOffS (3 s)
  //
  // US-511-b: the raw input is now gearParked(states/gear) -- gear P or N --
  // not the `idle` flag (which means "never connected this boot" and so never
  // unlocked anything after the first connect). The reducer is unchanged.
  //
  // THE TWO THRESHOLDS DIFFER ON PURPOSE. Offering a single tap into a service
  // stop is a convenience and can afford to be slow; WITHDRAWING it once the
  // car is moving is the safety half, so it is the fast one. A symmetric
  // debounce would hold the ⋮ on screen for a full 8 s of driving.
  //
  // Display-side only, per the AC: no emitter field and no new contract -- this
  // debounces the `idle` the display already consumes. (Promoting `parked` to
  // an emitted fact is the same class of question as the open idle-SSOT one and
  // needs an Atlas nod; not taken here.)
  //
  // Pure and node-testable like the rest of the navigation model: the clock
  // arrives as an argument, so nothing here reads a timer of its own.
  // -------------------------------------------------------------------------

  // The fail-closed start. Nothing has been HELD yet, so "am I parked?" is
  // unanswered -- and the unanswered side of that question is the one that
  // hands out a tap into a service stop. Mirrors the button's hidden-in-markup
  // boot state, so the pre-first-poll window offers no tap path.
  function parkedInit() {
    return { parked: false, raw: false, sinceMs: null };
  }

  // US-511-b (Atlas B1, spec v030-system-page-design 4.7.2): the RAW parked
  // fact is the derived gear -- P or N -- and nothing else. The deriver's P
  // already means stopped (US-511-a: fresh RPM 0 AND fresh SPEED 0), so this
  // reads the one fact rather than computing a second one. It replaced
  // carouselIdle as the reducer's input: system-status `idle` means "never
  // connected this boot", so after the first connect nothing parked-only ever
  // unlocked (F2, confirmed on the car). Fails closed: no gear file, an
  // unreadable one, `available` not strictly true, or any other gear (an
  // engaged gear is a number) is NOT parked.
  function gearParked(gearData) {
    return (
      isObj(gearData) &&
      gearData.available === true &&
      (gearData.gear === "P" || gearData.gear === "N")
    );
  }

  // Advance the signal by one observation. `prev` is the last state,
  // `rawParked` gearParked() for THIS poll, `nowMs` the tick clock.
  function parkedNext(prev, rawParked, nowMs, cfg) {
    var state =
      isObj(prev) && typeof prev.parked === "boolean"
        ? { parked: prev.parked, raw: prev.raw === true, sinceMs: prev.sinceMs }
        : parkedInit();
    // Only a strict `true` is parked. gearParked already applies this rule
    // upstream; re-applying it means the reducer cannot be broken by a second
    // caller that hands it a raw payload field instead.
    var raw = rawParked === true;
    // A hold is a MEASURED duration. With no readable clock there is no
    // measurement, so return the state completely untouched -- including the
    // reading. Recording the reading without a timestamp would let the NEXT
    // real clock credit this run's elapsed time to a reading taken during the
    // previous one, which is a fabricated hold assembled from two halves.
    if (!(typeof nowMs === "number" && isFinite(nowMs))) return state;
    var anchored =
      typeof state.sinceMs === "number" && isFinite(state.sinceMs);
    var held = anchored ? nowMs - state.sinceMs : -1;
    // Start a fresh run when the reading CHANGED, when there is no anchor yet
    // (boot), or when the elapsed time came back negative -- an NTP step back
    // on a Pi with no RTC. RE-ANCHORING ON EVERY CHANGE IS WHAT MAKES THIS
    // HYSTERESIS RATHER THAN AN ACCUMULATOR: six 2 s blips must not add up to
    // one 3 s run, or the flicker this story removes just takes longer to
    // arrive. An impossible elapsed time is not a measurement either -- left in
    // place it strands the signal for the size of the step, which on the OFF
    // edge means the ⋮ stays up while the car drives away.
    if (raw !== state.raw || held < 0) {
      state.raw = raw;
      state.sinceMs = nowMs;
      return state;
    }
    // Each edge is gated on the READING as well as the clock, so a threshold
    // the clock happens to pass can never fire the WRONG transition: a car sat
    // idle in the driveway for two minutes must not un-park itself.
    var c = resolveCarouselConfig(cfg);
    if (raw && !state.parked && held >= c.parkedOnS * 1000) state.parked = true;
    else if (!raw && state.parked && held >= c.parkedOffS * 1000) state.parked = false;
    return state;
  }

  // -------------------------------------------------------------------------
  // US-481 idle home card (F-121) -> US-542 MOTION-FAULT FALLBACK (F-127).
  //
  // This was the calm PARKED view: a STANDBY hero over three borrowed facts.
  // US-541 made the live IMU the permanent home face, which removed the ONLY
  // route to that hero -- parked, the IMU is CORRECT (a true heading, a true
  // 0.0 g), so there is nothing for a "STANDBY / engine off" screen to say that
  // the live instrument does not say better. US-542 therefore RETIRES the
  // parked disposition rather than leaving it as copy nothing can reach.
  //
  // What survives is the ONE disposition US-508 added and US-541 made the whole
  // point of the face: the motion feed is DOWN and the operator is owed the
  // reason. It is not "idle" in the carouselIdle sense and never was -- the two
  // meanings of that word are why AC-4 pins them apart.
  //
  // TWO THINGS LEFT WITH THE PARKED SCREEN, and neither is lost:
  //   - the wall clock moved to the TOP BAR, where it is readable on every card
  //     instead of only the one the operator saw with the engine off;
  //   - "DTC not read · since key-off" moved to the ALERTS card. It was always
  //     an Alerts fact (absence of a READ is neither a clean all-clear nor a
  //     fault) and was only ever HERE because this happened to be the screen a
  //     parked operator was looking at.
  // The warnings icon and the STOP takeover still show over every card, so
  // retiring this screen cannot suppress a genuine fault (Iris AC-5 survives).
  // -------------------------------------------------------------------------

  // idle is the emitter's SSOT (system-status `idle` boolean, US-480-a / Atlas
  // idle-SSOT b). The display RENDERS the flag; it NEVER re-derives idle from
  // the drive-state string (the replaced display-derived pattern). Anything
  // other than an explicit `true` (absent key / malformed file / false) reads
  // NOT-idle -- fail closed to the live view, never guess a calm parked state.
  function carouselIdle(systemStatusData) {
    return isObj(systemStatusData) && systemStatusData.idle === true;
  }

  // US-901-b (F-162; SSOT specs/v030-frame-and-style-design.md s3.1) -- is the
  // glass showing the live car? Two producers answer: system-status.runMode
  // (live / simulate / replay) and obd-live.dataSource (US-874). EITHER saying
  // "not live" raises the marker: if the two disagree that is a fault, and the
  // panel still marks itself (Atlas S-3). Replay wins over SIM, because a replay
  // rides the --simulate seam (US-857). A value this page does not recognise is
  // NOT LIVE -- never blank, never hidden, because hiding it would present
  // unknown data as live.
  //
  // null is NOT READ (sprint constraint), so it makes no claim either way, the
  // same as an absent key. obd-live publishes dataSource null before any logger
  // has resolved a tag, which a live boot does -- marking it would flag the car.
  //
  // Returns null (no marker) or {text, tier}; tier names the font-size token,
  // and NOT LIVE takes the meta tier so it fits REPLAY's box.
  function notLiveMarker(systemStatusData, obdLiveData) {
    var runMode = isObj(systemStatusData) ? systemStatusData.runMode : undefined;
    var dataSource = isObj(obdLiveData) ? obdLiveData.dataSource : undefined;
    var runModeNotLive =
      runMode !== undefined && runMode !== null && runMode !== "live";
    var sourceNotLive =
      dataSource !== undefined && dataSource !== null && dataSource !== "real";
    if (!runModeNotLive && !sourceNotLive) return null;
    if (runMode === "replay" || dataSource === "replay") {
      return { text: "REPLAY", tier: "label" };
    }
    if (runMode === "simulate" || dataSource === "physics_sim") {
      return { text: "SIM", tier: "label" };
    }
    return { text: "NOT LIVE", tier: "meta" };
  }

  // US-898-a (F-127; specs/v030-warnings-page-design.md s4.2) -- the top-bar
  // warnings icon, from states/alerts.icon ALONE. The provider computes the
  // state; this maps it to Iris's look and compares no tier, count or reading.
  // A missing or unreadable payload is `--`, never the grey triangle: `none`
  // is the provider's claim that the codes were read and nothing is active,
  // and with no payload that claim is false (Iris S108 review). Only a STOP
  // pulses (her look table); `pulse` is the provider's flag, already false for
  // an acknowledged entry.
  var ALERT_ICON_TRIANGLE = "▲";
  var ALERT_ICON_COUNT_CAP = 99;
  var ALERT_ICON_FIXED = {
    none: "△",
    not_checked: "?",
  };
  var ALERT_ICON_MISSING = { state: "missing", text: "--", pulse: false };

  function alertIconView(alerts) {
    var icon = isObj(alerts) && isObj(alerts.icon) ? alerts.icon : null;
    if (!icon) return ALERT_ICON_MISSING;
    var state = icon.state;
    if (Object.prototype.hasOwnProperty.call(ALERT_ICON_FIXED, state)) {
      return { state: state, text: ALERT_ICON_FIXED[state], pulse: false };
    }
    if (state !== "watch" && state !== "stop") return ALERT_ICON_MISSING;
    var count = icon.count;
    var shown = typeof count === "number" && isFinite(count) && count >= 0
      ? String(Math.min(Math.floor(count), ALERT_ICON_COUNT_CAP))
      : "";
    return {
      state: state,
      text: ALERT_ICON_TRIANGLE + shown,
      pulse: state === "stop" && icon.pulse === true,
    };
  }

  // -------------------------------------------------------------------------
  // US-406 DTC Alerts card (Card 5) + detail -- pure, node-testable logic
  // (S-4/S-5/S-12/S-13/I-3). The card is a PURE CONSUMER of the `dtc` state:
  // the display maps a Spool-classified tier -> chip label + color + directive;
  // it NEVER classifies. Two render-safety invariants are locked in the pure
  // builders (the SSOT) so a buggy DOM layer can't violate them:
  //   F-1/S-4  the fix area for a 🔴/🟡 code is REPLACED by a "diagnose, don't
  //            swap parts" directive -- the raw `suggestedFix` is never rendered
  //            even when non-null (only a 🟢 MINOR code shows a real fix + badge).
  //   S-13     a `severityCaveat` renders as a caveat LINE beneath the base chip;
  //            it NEVER auto-upgrades the tier (the display reads `severity`
  //            verbatim). `na` (auto-trans on this manual car) is a quiet
  //            disposition -- an N/A chip that sorts LAST, never a hero (S-12).
  // -------------------------------------------------------------------------

  function dtcShort(code) {
    return (code.short && String(code.short).trim()) || "No description yet";
  }

  function dtcCaveat(code) {
    return (code.severityCaveat && String(code.severityCaveat).trim()) || null;
  }

  // -------------------------------------------------------------------------
  // US-898-b1 (F-127; specs/v030-warnings-page-design.md s3, s4.1, s4.6) -- the
  // ALERTS card, from states/alerts ALONE. The provider orders the entries,
  // picks every tier and writes every word (Spool verbatim); these map each
  // entry to one row IN THE ORDER GIVEN and compare no tier, rank or reading
  // (Iris G-6, rule 0). The dtc-driven body they replace -- a hero plus a
  // worst-first sort the page computed itself -- is retired with them.
  // -------------------------------------------------------------------------

  // Tier -> chip word. A lookup, never a ranking. An unrecognised tier reads
  // as UNRATED: "not rated" is the honest name for a tier the page cannot
  // place, and the row is never dropped (hiding an entry could hide a fault).
  var WARNING_CHIP = { stop: "STOP", watch: "WATCH", minor: "MINOR", unrated: "UNRATED" };
  var WARNING_CHIP_FALLBACK = "unrated";
  // Iris s4.3 (default wording; Iris may re-word): no readable payload.
  var WARNINGS_NO_DATA_TEXT = "no warnings data";
  var WARNINGS_NO_DATA_HEADER = "--";
  // The age column of an entry the provider still lists after it cleared.
  var WARNING_CLEARED_TEXT = "cleared";

  // US-898-b2 (Iris brief "Empty state"; Atlas ARCH-062: never claim "clear"
  // for a source that was not assessed). The words for a card with nothing
  // active -- Iris's, verbatim. Each clause is printed only when `sources`
  // says its source WAS assessed.
  var WARNINGS_NONE_HEADER = "NONE";
  var WARNINGS_NOT_CHECKED_HEADER = "NOT CHECKED";
  var WARNINGS_NONE_HEAD = "NO WARNINGS";
  var WARNINGS_NOT_CHECKED_MARK = "?";
  var WARNINGS_NOT_CHECKED_HEAD = "NOT CHECKED YET";
  var WARNINGS_NOT_CHECKED_TEXT =
    "Trouble codes haven't been read since key-on, so \"nothing found\" can't be claimed.";
  var WARNINGS_ENGINE_CLAUSE = " Engine checks clear.";
  // US-877-c (Iris 2026-10-19): one line per unassessed source, System first.
  var WARNINGS_SYSTEM_NOT_READ_TEXT = "System checks not read yet.";
  var WARNINGS_DATA_NOT_BUILT_TEXT = "Data checks are not built yet.";

  // A source is assessed only when the provider says exactly true; absent or
  // anything else is "not assessed" -- the direction that claims nothing.
  function warningSourceAssessed(sources, name) {
    return isObj(sources[name]) && sources[name].assessed === true;
  }

  // When the codes were read, in the panel's one 12-hour clock without AM/PM
  // (the fmtTimeOfDay split, as engineHistoryWindow). An unparseable instant
  // is '--', never a guessed one.
  function warningsReadClock(at) {
    var read = typeof at === "string" && ISO_INSTANT.test(at) ? new Date(Date.parse(at)) : null;
    return read ? fmtTimeOfDay(read, false).split(" ")[0] : DRIVING_NOT_READ;
  }

  // The header: 'n ACTIVE' (n = the active rows) plus when the codes were
  // read; a null checkedAtTs is "not read", never a time. With nothing active
  // it is NONE when the code read was assessed, else NOT CHECKED (tone
  // 'amber', no meta: there is no read to time).
  function warningsHeaderView(alerts, rows) {
    var active = 0;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].active) active++;
    }
    var sources = isObj(alerts.sources) ? alerts.sources : {};
    var code = isObj(sources.code) ? sources.code : {};
    var meta = code.checkedAtTs != null
      ? "codes read " + warningsReadClock(code.checkedAtTs)
      : "codes not read yet";
    if (active > 0) return { text: active + " ACTIVE", meta: meta, tone: null };
    if (!warningSourceAssessed(sources, "code")) {
      return { text: WARNINGS_NOT_CHECKED_HEADER, meta: "", tone: "amber" };
    }
    return { text: WARNINGS_NONE_HEADER, meta: meta, tone: null };
  }

  // The body of a card with nothing ACTIVE (cleared rows may still be listed
  // under it -- a row is never hidden). Code read assessed: 'NO WARNINGS', when
  // the codes were read (+ the engine clause only while engine is assessed),
  // then a not-read / not-built line for each of system and data while it is
  // not assessed. Not assessed:
  // '? NOT CHECKED YET' and why nothing can be claimed -- no other line, so the
  // card says nothing about any source. null while anything is active.
  function warningsQuietView(alerts, rows) {
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].active) return null;
    }
    var sources = isObj(alerts.sources) ? alerts.sources : {};
    if (!warningSourceAssessed(sources, "code")) {
      return {
        state: "not-checked",
        mark: WARNINGS_NOT_CHECKED_MARK,
        head: WARNINGS_NOT_CHECKED_HEAD,
        lines: [{ text: WARNINGS_NOT_CHECKED_TEXT, tone: "primary" }],
      };
    }
    var lines = [{
      text: "Codes read at " + warningsReadClock(sources.code.checkedAtTs) + "." +
        (warningSourceAssessed(sources, "engine") ? WARNINGS_ENGINE_CLAUSE : ""),
      tone: "primary",
    }];
    if (!warningSourceAssessed(sources, "system")) {
      lines.push({ text: WARNINGS_SYSTEM_NOT_READ_TEXT, tone: "secondary" });
    }
    if (!warningSourceAssessed(sources, "data")) {
      lines.push({ text: WARNINGS_DATA_NOT_BUILT_TEXT, tone: "secondary" });
    }
    return { state: "none", mark: null, head: WARNINGS_NONE_HEAD, lines: lines };
  }

  // US-898-b2 (Iris U9): '↓ n more below', n = the rows whose bottom edge lies
  // below the list's visible bottom. At runtime n comes from LAYOUT
  // (warningsBelowFromLayout); these are the no-layout fallback the harness
  // tests -- rows at their 48 px floor in the 270 px card body, minus the
  // header and cue heights measured by the caller. A partly visible row counts
  // as below, so 7 entries under a ~40 px header and ~20 px cue -> 3.
  var WARNINGS_BODY_PX = 270;   // 320 panel - 34 bar - 16 dots (Iris brief)
  var WARNINGS_ROW_FLOOR_PX = 48;
  // Where not even the header and cue can be measured, their line boxes from
  // dashboard.css: --fs-primary 34 px and --fs-meta 15 px at --warn-line 1.2.
  var WARNINGS_HEADER_EST_PX = 34 * 1.2;
  var WARNINGS_CUE_EST_PX = 15 * 1.2;

  function warningsMoreBelow(rowCount, headerPx, cuePx) {
    if (typeof rowCount !== "number" || !(rowCount > 0)) return 0;
    var visible = WARNINGS_BODY_PX - (Number(headerPx) || 0) - (Number(cuePx) || 0);
    var shown = Math.max(0, Math.floor(visible / WARNINGS_ROW_FLOOR_PX));
    return Math.max(0, rowCount - shown);
  }

  // The layout count: rows whose bottom lies below the visible bottom (within
  // half a pixel, so a row flush with the edge is not "below").
  function warningsBelowFromLayout(visibleBottom, rowBottoms) {
    var n = 0;
    for (var i = 0; i < rowBottoms.length; i++) {
      if (rowBottoms[i] > visibleBottom + 0.5) n++;
    }
    return n;
  }

  function warningsMoreText(n) {
    return n > 0 ? "↓ " + n + " more below" : "";
  }

  // The FRESHNESS clause of a stale row -- how old the reading on screen is.
  // The S105 M7 rule (Iris; spec s4.6), the Motion page's own: floor, clamped
  // at 0 (a future ts is clock skew, not a negative age), 'N s' with a space,
  // capped at '999+'. Only this clause; the age column is agoText (a duration).
  function warningStaleText(lastTs, nowMs) {
    var then = typeof lastTs === "string" ? Date.parse(lastTs) : NaN;
    if (isNaN(then) || typeof nowMs !== "number" || isNaN(nowMs)) {
      return "last reading age unknown";
    }
    var shown = Math.max(0, Math.floor((nowMs - then) / 1000));
    var text = shown > MOTION_AGE_CAP_SEC ? MOTION_AGE_CAP_SEC + "+" : String(shown);
    return "last reading " + text + " s ago";
  }

  // A reading through the S103 G1 helper by its OWN unit (coolant 'C' -> °F).
  // Not a number -> no value: a code row and the over-rev row (Atlas G3: its
  // peak lives in the provider's sentence) carry none. `round` is the entry's
  // own direction (US-897-d: the battery's, toward the breach), else null.
  function warningValueText(value, unit, round) {
    if (typeof value !== "number" || !isFinite(value)) return null;
    var shown = displayUnits(value, unit, round);
    return shown.unit ? shown.text + " " + shown.unit : shown.text;
  }

  // One row. Stale (an active entry with no fresh reading): the LAST value plus
  // its freshness clause -- stale never clears, and a blank would read as
  // "fine". Every row's age is agoText(now, firstSeenTs) unchanged (Iris
  // 2026-10-19); an inactive entry reads 'cleared' in that column. Only a CODE
  // row is a control (US-758; its tap is the code detail).
  function warningRowView(entry, nowTs) {
    var tier = Object.prototype.hasOwnProperty.call(WARNING_CHIP, entry.tier)
      ? entry.tier : WARNING_CHIP_FALLBACK;
    var active = entry.active !== false;
    var stale = active && entry.stale === true;
    var last = isObj(entry.last) ? entry.last : null;
    var key = typeof entry.key === "string" ? entry.key : null;
    // A stale last.value keeps the episode's direction (US-897-d).
    var round = typeof entry.round === "string" ? entry.round : null;
    return {
      id: typeof entry.id === "string" ? entry.id : "",
      source: typeof entry.source === "string" ? entry.source : "",
      key: key,
      tier: tier,
      chip: WARNING_CHIP[tier],
      title: typeof entry.title === "string" && entry.title ? entry.title : key || DRIVING_NOT_READ,
      value: stale
        ? (last ? warningValueText(last.value, entry.unit, round) : null)
        : warningValueText(entry.value, entry.unit, round),
      stale: stale ? warningStaleText(last ? last.ts : null, Date.parse(nowTs)) : null,
      sentence: typeof entry.sentence === "string" && entry.sentence ? entry.sentence : null,
      age: active ? agoText(nowTs, entry.firstSeenTs) : WARNING_CLEARED_TEXT,
      active: active,
      control: entry.source === "code",
    };
  }

  // The whole card. No readable payload (absent, unreadable, no entries list)
  // -> header '--' and 'no warnings data': never a list that implies a read.
  // Otherwise one row per entry, in entries[] order. `nowTs` is the tick's one
  // clock as an ISO instant.
  function warningsPageView(alerts, nowTs) {
    var entries = isObj(alerts) && Array.isArray(alerts.entries) ? alerts.entries : null;
    if (!entries) {
      return {
        missing: true,
        header: { text: WARNINGS_NO_DATA_HEADER, meta: "", tone: null },
        rows: [],
        empty: WARNINGS_NO_DATA_TEXT,
        quiet: null,
      };
    }
    var rows = [];
    for (var i = 0; i < entries.length; i++) {
      if (isObj(entries[i])) rows.push(warningRowView(entries[i], nowTs));
    }
    return {
      missing: false,
      header: warningsHeaderView(alerts, rows),
      rows: rows,
      empty: null,
      quiet: warningsQuietView(alerts, rows),
    };
  }

  // -------------------------------------------------------------------------
  // US-899-a1 (F-127; CIO R31, Iris brief s A + U7/U11, Atlas G4/Q10) -- the
  // live coolant STOP takeover, from states/alerts.takeover ALONE. The provider
  // decides that a takeover exists and writes every word on it, the directive
  // band included (no page literal: a page-side directive could only be a
  // fallback, which G4 retired). The surface carries no control; a tap anywhere
  // acknowledges it for this boot (alertsAckNext), which stops only the ICON
  // pulse -- the frame keeps pulsing while the takeover is up.
  // -------------------------------------------------------------------------

  // Tier -> the colour token of its frame/chip. ONE map: the takeover's STOP
  // reads it here and the code alert's frame (US-899-b) reads the same row.
  var TIER_COLOR_VAR = {
    stop: "--critical-red",
    watch: "--amber-warn",
    minor: "--green-ok",
    unrated: "--neutral-chip-bg",
  };

  function tierColorVar(tier) {
    return Object.prototype.hasOwnProperty.call(TIER_COLOR_VAR, tier) ? TIER_COLOR_VAR[tier] : null;
  }

  // An entry is acknowledged only when the provider's re-read says exactly
  // true for that id (the takeover itself carries no ack flag).
  function alertsEntryAcknowledged(alerts, id) {
    var entries = isObj(alerts) && Array.isArray(alerts.entries) ? alerts.entries : [];
    for (var i = 0; i < entries.length; i++) {
      if (isObj(entries[i]) && entries[i].id === id) return entries[i].acknowledged === true;
    }
    return false;
  }

  // The takeover, or null (no payload, or the provider published none). Stale
  // (Atlas Q10, the existing shape: value null + stale + last): last.value plus
  // its own 'last reading n s ago' line (the M7 rule, warningStaleText) -- stale
  // never clears. The age is agoText(now, firstSeenTs) unchanged. `nowTs` is the
  // tick's one clock as an ISO instant.
  function takeoverAlertView(alerts, nowTs) {
    var t = isObj(alerts) && isObj(alerts.takeover) ? alerts.takeover : null;
    if (!t) return null;
    var stale = t.stale === true;
    var last = isObj(t.last) ? t.last : null;
    return {
      id: typeof t.id === "string" ? t.id : "",
      directive: typeof t.directive === "string" && t.directive ? t.directive : null,
      title: typeof t.title === "string" && t.title ? t.title : null,
      value: stale
        ? (last ? warningValueText(last.value, t.unit) : null)
        : warningValueText(t.value, t.unit),
      stale: stale ? warningStaleText(last ? last.ts : null, Date.parse(nowTs)) : null,
      sentence: typeof t.sentence === "string" && t.sentence ? t.sentence : null,
      age: agoText(nowTs, t.firstSeenTs),
      colorVar: TIER_COLOR_VAR.stop,
      acknowledged: alertsEntryAcknowledged(alerts, t.id),
    };
  }

  // A real STOP takeover is up (drives the full-brightness short-circuit). Keyed on
  // the provider's takeover, never on a states/dtc level: the alarm the panel
  // holds at full is exactly the one it is drawing.
  function brightnessAlarmActive(alertsData) {
    return isObj(alertsData) && isObj(alertsData.takeover);
  }

  // --- the ack: the honest write (the fuelResetNext pattern) -----------------
  //
  // A tap POSTs /alerts-ack {ids: [id]} (Atlas Q26: the one shape). Only a
  // RE-READ of states/alerts showing that entry acknowledged:true settles it,
  // within pi.display.stale.alertsAckConfirmSec of the 200 (Atlas Q33); a 200 is
  // not the proof. Anything else -- a refusal (a 409, 503, 504 or any other), no
  // answer, or no matching re-read in the window -- shows "couldn't acknowledge"
  // for pi.display.stale.alertsAckNoticeSec, and the provider's pulse simply
  // continues. Both windows are injected as window.DISPLAY_STALE; there is NO
  // mirrored default here (no literal in this file), so without them the tap is
  // not offered (fail closed: an unbounded acknowledging state would lie).
  var ALERTS_ACK_FAILED_TEXT = "couldn't acknowledge";

  function isPositiveSec(v) {
    return typeof v === "number" && isFinite(v) && v > 0;
  }

  function resolvePositiveSec(injected, key) {
    var v = isObj(injected) ? injected[key] : null;
    return isPositiveSec(v) ? v : null;
  }

  function resolveAlertsAckConfirmSec(injected) {
    return resolvePositiveSec(injected, "alertsAckConfirmSec");
  }

  function resolveAlertsAckNoticeSec(injected) {
    return resolvePositiveSec(injected, "alertsAckNoticeSec");
  }

  function alertsAckBody(id) {
    return { ids: [id] };
  }

  // phase: idle | posting (tap -> the answer) | awaiting (200 -> the matching
  // re-read). `noticeFromMs` is when "couldn't acknowledge" went up, else null.
  function alertsAckInit() {
    return { phase: "idle", id: null, confirmFromMs: null, noticeFromMs: null };
  }

  function alertsAckFailed(s, nowMs) {
    s.phase = "idle";
    s.confirmFromMs = null;
    s.noticeFromMs = typeof nowMs === "number" ? nowMs : null;
    return s;
  }

  // Advance the ack by one event. Pure; the clock arrives on the event.
  //   {type: "tap", view, confirmSec, noticeSec}   the takeover was tapped
  //   {type: "answer", status, body, nowMs}        the POST answered
  //   {type: "failure", nowMs}                     the POST never answered
  //   {type: "read", alerts, nowMs, confirmSec, noticeSec}   one tick's read
  function alertsAckNext(prev, ev) {
    var s = isObj(prev) && typeof prev.phase === "string" ? {
      phase: prev.phase, id: prev.id, confirmFromMs: prev.confirmFromMs,
      noticeFromMs: prev.noticeFromMs,
    } : alertsAckInit();
    if (isObj(ev) && ev.type === "tap") {
      var view = isObj(ev.view) ? ev.view : null;
      if (s.phase === "idle" && view && view.id && view.acknowledged !== true &&
          isPositiveSec(ev.confirmSec) && isPositiveSec(ev.noticeSec)) {
        s.phase = "posting";
        s.id = view.id;
        s.noticeFromMs = null;
      }
      return s;
    }
    return ackFlowStep(s, ev, function (alerts) {
      return s.id !== null && alertsEntryAcknowledged(alerts, s.id);
    });
  }

  // The half of an honest ack that is not the tap, shared by the STOP takeover's ack
  // and the code alert's DISMISS (US-899-b): the POST's answer, no answer, and
  // the re-read. `settled(alerts)` is the ONE proof each surface accepts from a
  // re-read; nothing else -- not a 200 -- ever settles it. Mutates and returns `s`.
  function ackFlowStep(s, ev, settled) {
    var type = isObj(ev) ? ev.type : null;
    if (type === "answer") {
      if (s.phase !== "posting") return s;
      if (ev.status === 200 && isObj(ev.body) && ev.body.ok === true) {
        s.phase = "awaiting";
        s.confirmFromMs = ev.nowMs;
        return s;
      }
      return alertsAckFailed(s, ev.nowMs);
    }
    if (type === "failure") {
      return s.phase === "posting" ? alertsAckFailed(s, ev.nowMs) : s;
    }
    if (type !== "read") return s;
    var acked = settled(ev.alerts);
    if (s.phase === "awaiting") {
      if (acked) {
        s.phase = "idle";
        s.confirmFromMs = null;
      } else if (!(typeof ev.nowMs === "number" && typeof ev.confirmSec === "number" &&
                   ev.nowMs - s.confirmFromMs <= ev.confirmSec * 1000)) {
        return alertsAckFailed(s, ev.nowMs);
      }
    } else if (s.phase === "idle" && s.noticeFromMs !== null) {
      // An ack that landed after all (a 504, a late write): the read speaks.
      // Otherwise the notice holds for its window, then goes.
      if (acked || !(typeof ev.nowMs === "number" && typeof ev.noticeSec === "number" &&
                     ev.nowMs - s.noticeFromMs <= ev.noticeSec * 1000)) {
        s.noticeFromMs = null;
      }
    }
    return s;
  }

  function alertsAckNoticeText(state) {
    return isObj(state) && state.phase === "idle" && state.noticeFromMs !== null
      ? ALERTS_ACK_FAILED_TEXT : "";
  }

  // -------------------------------------------------------------------------
  // US-899-b (F-127; spec s4.4b, Iris brief s B + U5-U7, Atlas Q26/Q32) -- the
  // key-on TROUBLE CODES screen, from states/alerts.codeAlert ALONE. The
  // provider decides that it shows (each key-on; a boot-scoped ack) and its
  // tier; the page compares nothing. Drawn only while engineParked is parked
  // (US-511; it starts not-parked) and never under the STOP takeover. Not being drawn
  // is not a dismiss: only DISMISS posts, and only a re-read with codeAlert
  // null closes it.
  // -------------------------------------------------------------------------

  // Iris brief s B: up to 3 rows; the rest are named by count, never clipped.
  var CODE_ALERT_ROWS_MAX = 3;
  var CODE_DISMISS_FAILED_TEXT = "couldn't dismiss";

  // The drawn screen, or null: no payload, no codeAlert, no ids, a takeover up
  // (the STOP takeover wins), or `parked` not strictly true. Each row is the entry its
  // id names in entries[] (chip + title + sentence, warningRowView's words);
  // an id with no entry draws no row. `more` is '+n more on ALERTS' beyond 3.
  function codeAlertView(alerts, parked) {
    if (!isObj(alerts) || !isObj(alerts.codeAlert) || isObj(alerts.takeover)) return null;
    if (parked !== true) return null;
    var ids = Array.isArray(alerts.codeAlert.ids)
      ? alerts.codeAlert.ids.filter(function (id) { return typeof id === "string" && id; })
      : [];
    if (!ids.length) return null;
    var entries = Array.isArray(alerts.entries) ? alerts.entries : [];
    var rows = [];
    for (var i = 0; i < ids.length && i < CODE_ALERT_ROWS_MAX; i++) {
      for (var j = 0; j < entries.length; j++) {
        if (isObj(entries[j]) && entries[j].id === ids[i]) {
          var row = warningRowView(entries[j], null);
          rows.push({
            id: row.id, tier: row.tier, chip: row.chip, title: row.title, sentence: row.sentence,
          });
          break;
        }
      }
    }
    var more = ids.length - Math.min(ids.length, CODE_ALERT_ROWS_MAX);
    return {
      ids: ids,
      colorVar: tierColorVar(alerts.codeAlert.tier),
      rows: rows,
      more: more > 0 ? "+" + more + " more on ALERTS" : null,
    };
  }

  // DISMISS -> ONE POST /alerts-ack {ids: every codeAlert id} (Atlas Q26: one
  // shape, all-or-nothing).
  function codeDismissBody(ids) {
    return { ids: Array.isArray(ids) ? ids.slice() : [] };
  }

  // The alertsAckNext lifecycle, keyed on the ids: idle | posting | awaiting.
  function codeDismissInit() {
    return { phase: "idle", ids: null, confirmFromMs: null, noticeFromMs: null };
  }

  // Advance the dismiss by one event (the alertsAckNext events; a tap carries
  // the codeAlertView). Settled ONLY by a re-read whose codeAlert is null -- an
  // unreadable payload is not that proof.
  function codeDismissNext(prev, ev) {
    var s = isObj(prev) && typeof prev.phase === "string" ? {
      phase: prev.phase, ids: Array.isArray(prev.ids) ? prev.ids.slice() : null,
      confirmFromMs: prev.confirmFromMs, noticeFromMs: prev.noticeFromMs,
    } : codeDismissInit();
    if (isObj(ev) && ev.type === "tap") {
      var view = isObj(ev.view) ? ev.view : null;
      if (s.phase === "idle" && view && Array.isArray(view.ids) && view.ids.length &&
          isPositiveSec(ev.confirmSec) && isPositiveSec(ev.noticeSec)) {
        s.phase = "posting";
        s.ids = view.ids.slice();
        s.noticeFromMs = null;
      }
      return s;
    }
    return ackFlowStep(s, ev, function (alerts) {
      return s.ids !== null && isObj(alerts) && alerts.codeAlert === null;
    });
  }

  function codeDismissNoticeText(state) {
    return isObj(state) && state.phase === "idle" && state.noticeFromMs !== null
      ? CODE_DISMISS_FAILED_TEXT : "";
  }

  // 3-state trust badge (design §5.4). Verified (Spool) / community-unverified /
  // offline-not-yet-fetched. Any unrecognized/absent provenance -> offline (the
  // honest "no live net in the car" default), never a fabricated authority.
  function trustBadge(fixProvenance) {
    if (fixProvenance === "spool-validated") {
      return { kind: "verified", label: "✓ Verified · Spool" };
    }
    if (fixProvenance === "auto-unverified" || fixProvenance === "sourced") {
      return { kind: "community", label: "👥 Community · unverified" };
    }
    return { kind: "offline", label: "⏳ Looking into it" };
  }

  // Severity-gated fix area (S-4/F-1 -- the load-bearing safety invariant). A
  // 🔴/🟡 (or uncurated `unknown`) code's fix slot is REPLACED by a diagnose
  // directive; the raw `suggestedFix` is NEVER rendered for it, even when
  // non-null. Only a 🟢 MINOR code shows the actual fix + a trust badge. `na`
  // is not applicable. A missing MINOR fix is honest text, never fabricated.
  function fixArea(code) {
    var sev = code.severity;
    if (sev === "na") {
      return { mode: "na", text: "Not applicable to this vehicle", badge: null };
    }
    if (sev !== "minor") {
      var lead =
        sev === "stop"
          ? "⚠ STOP — diagnose, don't just swap parts"
          : sev === "watch"
            ? "⚠ WATCH — get it diagnosed, don't swap parts"
            : "Get it diagnosed before replacing parts";
      return { mode: "directive", text: lead, badge: null };
    }
    var fix = (code.suggestedFix && String(code.suggestedFix).trim()) || null;
    return {
      mode: "fix",
      text: fix || "No fix available offline — arrives on next sync.",
      badge: trustBadge(code.fixProvenance),
    };
  }

  // US-491: the heading on the fix card, per mode. AC2 wants every section
  // card labelled, and the label has to tell the same truth the body does --
  // heading a 🔴/🟡 diagnose directive "SUGGESTED FIX" would undo S-4 in the
  // label while the body still obeys it. An unrecognised mode falls back to the
  // neutral "NEXT STEP", never to "SUGGESTED FIX".
  var FIX_SECTION_LABEL = {
    fix: "SUGGESTED FIX",
    directive: "NEXT STEP",
    na: "APPLICABILITY",
  };

  function fixSectionLabel(mode) {
    return Object.prototype.hasOwnProperty.call(FIX_SECTION_LABEL, mode)
      ? FIX_SECTION_LABEL[mode]
      : FIX_SECTION_LABEL.directive;
  }

  // Freeze-frame view (S-5). Mode 02 is confirmed unsupported on the current
  // ECU (MD326328) -> the default is the labeled realtime-context fallback,
  // never blank. A grid renders only if a future Mode-02-capable ECU supplies
  // one (freezeFrame is a non-null object).
  function freezeFrameView(code) {
    var ff = isObj(code.freezeFrame) ? code.freezeFrame : null;
    if (!ff) {
      return {
        hasFrame: false,
        fallbackText: "no freeze frame captured (this ECU) — showing context at fault time",
        grid: null,
      };
    }
    return { hasFrame: true, fallbackText: null, grid: ff };
  }

  // Status meta line. A null `driveId` is a KOEO (key-on) read (US-404 A-9) --
  // shown as "key-on read", NEVER a fabricated "Drive N".
  function dtcStatusMeta(code) {
    var parts = [];
    parts.push(code.status === "pending" ? "PENDING" : "STORED");
    parts.push(code.driveId == null ? "key-on read" : "Drive " + code.driveId);
    return parts.join(" · ");
  }

  // US-898-c (Iris U4): the line a detail prints when the states/dtc read that
  // backs it failed -- the entry's own words still stand above it.
  var DETAIL_UNAVAILABLE_TEXT = "details unavailable";
  // A code entry's id is 'code:<code>:<tier>' (alerts_arbiter).
  var CODE_ENTRY_ID = /^code:([^:]+):[^:]+$/;

  // The code a states/alerts code entry names, parsed from its id; null for
  // any other id (an engine entry, a malformed one).
  function codeFromEntryId(id) {
    var m = typeof id === "string" ? CODE_ENTRY_ID.exec(id) : null;
    return m ? m[1] : null;
  }

  // The states/dtc record for one code, or null (no payload, an unread source
  // publishing codes:null, or a code the payload does not list).
  function dtcRecordFor(data, codeStr) {
    if (!isObj(data) || !Array.isArray(data.codes) || !codeStr) return null;
    for (var i = 0; i < data.codes.length; i++) {
      if (isObj(data.codes[i]) && data.codes[i].code === codeStr) return data.codes[i];
    }
    return null;
  }

  // The per-code detail view: (codeRecord, entry). The ENTRY is the provider's
  // (states/alerts) and supplies the code, the chip and the directive band;
  // the RECORD is that code's states/dtc row and supplies everything else.
  // No code entry -> null (nothing to open). The caveat is a line, never a
  // tier upgrade (S-13).
  //
  // US-898-c (Iris U4): the band is the entry's `sentence`, the provider's
  // words -- never a tier-table directive -- and the chip is the
  // entry's tier, `unrated` drawn with the existing `unknown` styling. With no
  // record (the read failed, or does not list the code) the view keeps the
  // entry's title, chip and sentence and says `details unavailable`: never a
  // cached record, never a tier-table directive.
  function codeDetailView(record, entry) {
    if (!isObj(entry) || entry.source !== "code") return null;
    var code = codeFromEntryId(entry.id);
    if (!code) return null;
    var tier = Object.prototype.hasOwnProperty.call(WARNING_CHIP, entry.tier)
      ? entry.tier : WARNING_CHIP_FALLBACK;
    var title = typeof entry.title === "string" && entry.title ? entry.title : code;
    var rec = isObj(record) && record.code === code ? record : null;
    return {
      code: code,
      chip: WARNING_CHIP[tier],
      level: tier === "unrated" ? "unknown" : tier,
      title: title,
      short: rec ? dtcShort(rec) : title,
      long: rec ? (rec.long && String(rec.long).trim()) || null : null,
      directive: typeof entry.sentence === "string" && entry.sentence ? entry.sentence : null,
      unavailable: rec ? null : DETAIL_UNAVAILABLE_TEXT,
      caveat: rec ? dtcCaveat(rec) : null,
      statusMeta: rec ? dtcStatusMeta(rec) : null,
      freezeFrame: rec ? freezeFrameView(rec) : null,
      fix: rec ? fixArea(rec) : null,
      logged: rec ? rec.logged === true : false,
      syncAcked: rec ? rec.syncAcked === true : false,
      clearEligible: rec ? rec.clearEligible === true : false,
      isNa: rec ? rec.severity === "na" : false,
    };
  }

  // -------------------------------------------------------------------------
  // US-407 -- DTC Clear (Mode-04) surface (F-111 / design §6).
  // -------------------------------------------------------------------------

  // Display-only reason -> label. The AUTHORITATIVE gate is re-checked server-
  // side (pi.splash.dtc_clear); this mirrors it so the button reads honestly.
  var CLEAR_REASON_LABEL = {
    ok: "CLEAR CODES",
    severity_present: "🔒 CLEAR CODES — a STOP/WATCH code is present",
    // US-753: an ungraded code is refused on principle; saying STOP/WATCH
    // there asserts a tier nobody determined.
    severity_unknown: "🔒 CLEAR CODES — severity could not be determined",
    sync_pending: "🔒 CLEAR CODES — waiting for server sync",
    session_locked: "🔒 CLEAR CODES — a cleared code returned; clearing again won't fix it",
    // US-919 (Iris 2026-10-20, verbatim): no Mode 07 answered, so the pending
    // set Mode 04 would also wipe was never read. One fact, no tier, no "yet".
    pending_not_read: "🔒 CLEAR CODES — pending codes haven’t been read",
    // US-511-b (Atlas B2; spec warnings :190-195, system 4.7.2 :326-328): the
    // lock is engineParked, now fed by the gear (P or N), so an idling car
    // in N unlocks it -- "engine off" was no longer what unlocks it.
    moving: "🔒 CLEAR CODES — stop to clear",
    // US-511-b: the gear itself is unknown (no states/gear, or `available` not
    // true), so "stop" would claim a fact nobody has.
    parked_unknown: "🔒 CLEAR CODES — gear unknown",
  };

  // Re-derive the clear gate from the raw codes (the display mirror of the
  // server-side dtc_clear.evaluateClearGate). Deliberately IGNORES any
  // precomputed clearGate.enabled -- the button never lies just because the
  // state's flag does. Mode 04 is all-or-nothing and wipes pending codes too,
  // so the gate keys off ALL stored and pending (non-na) codes, not the one on
  // screen (US-919, Atlas Q2/Q3); a code both stored and pending counts once.
  function clearGateRelevant(codes) {
    var candidates = codes.filter(function (c) {
      return (c.status === "stored" || c.status === "pending") && c.severity !== "na";
    });
    var storedCodes = {};
    candidates.forEach(function (c) {
      if (c.status === "stored") storedCodes[c.code] = true;
    });
    var seen = {};
    return candidates.filter(function (c) {
      if (seen[c.code] || (c.status !== "stored" && storedCodes[c.code])) return false;
      seen[c.code] = true;
      return true;
    });
  }

  function clearGateReason(data) {
    if (!isObj(data)) return "no_codes";
    var codes = Array.isArray(data.codes) ? data.codes.filter(isObj) : [];
    var relevant = clearGateRelevant(codes);
    if (relevant.length === 0) return "no_codes";
    if (relevant.some(function (c) {
      return c.severity === "stop" || c.severity === "watch";
    })) {
      return "severity_present";
    }
    if (relevant.some(function (c) { return c.severity !== "minor"; })) {
      return "severity_unknown";
    }
    // US-919 (Atlas Q4): after every permanent reason, before sync -- no
    // Mode 07 answered this session (null or absent).
    if (data.pendingCheckedAtTs === null || data.pendingCheckedAtTs === undefined) {
      return "pending_not_read";
    }
    if (relevant.some(function (c) { return !(c.logged && c.syncAcked); })) {
      return "sync_pending";
    }
    var lock = {};
    var raw = Array.isArray(data.sessionResetLock) ? data.sessionResetLock : [];
    for (var i = 0; i < raw.length; i++) lock[raw[i]] = true;
    if (relevant.some(function (c) { return lock[c.code]; })) {
      return "session_locked";
    }
    return "ok";
  }

  // The Clear button view. `no_codes` -> no button (nothing to clear). Otherwise
  // the button is visible; enabled only when the gate is `ok`, else disabled
  // with an honest reason label (S-6 / S-8).
  //
  // US-898-c: `parked` is engineParked.parked; only a strict true unlocks. It
  // is asked only when the gate is otherwise `ok`, so a permanent reason
  // (WATCH, STOP, UNRATED, sync, session lock) wins over `moving` -- a WATCH
  // code never implies that turning the engine off unlocks it.
  //
  // US-511-b (Atlas B2): `gearKnown` is whether the CURRENT raw states/gear is
  // available (strict true), not the debounced state -- so the word follows
  // the gear under the operator: an unknown gear says 'parked_unknown', a
  // known one that is not (yet) held parked says 'moving'.
  function clearButtonView(data, parked, gearKnown) {
    var reason = clearGateReason(data);
    if (reason === "no_codes") {
      return { visible: false, enabled: false, reason: reason, label: null };
    }
    if (reason === "ok" && parked !== true) {
      reason = gearKnown === true ? "moving" : "parked_unknown";
    }
    return {
      visible: true,
      enabled: reason === "ok",
      reason: reason,
      label: CLEAR_REASON_LABEL[reason] || CLEAR_REASON_LABEL.ok,
    };
  }

  // The hard-confirm copy (S-7 / design §6.2). Names the irreversible
  // consequences: every code wiped, the freeze-frame erased, readiness monitors
  // reset (a full drive cycle before an inspection will pass).
  function confirmClearText() {
    return {
      title: "Clear all codes?",
      body:
        "Wipes every stored + pending code, erases the freeze-frame, and resets " +
        "emissions readiness monitors (a full drive cycle is needed before an " +
        "inspection will pass). Can't be undone.",
      confirmLabel: "Clear all",
      cancelLabel: "Cancel",
    };
  }

  // The post-clear result message from the server's clear outcome (§6.3). The
  // re-read is the PROOF -- report "0 stored, 0 pending, MIL off", never a bare
  // "command sent". An instant re-set -> "don't chase the light" (I-7 / S-8).
  function postClearMessage(outcome) {
    if (!isObj(outcome)) return null;
    if (!outcome.issued) {
      return {
        level: "blocked",
        text: "Clear refused — " + (outcome.reason || "not allowed right now"),
      };
    }
    var reSet = Array.isArray(outcome.reSetCodes) ? outcome.reSetCodes : [];
    if (reSet.length > 0) {
      return {
        level: "reset",
        text:
          reSet.join(", ") +
          " returned — a code that comes back is a real fault; clearing again won't fix it",
      };
    }
    if (outcome.cleared) {
      return { level: "cleared", text: "Cleared — 0 stored, 0 pending, MIL off" };
    }
    return {
      level: "partial",
      text: "Clear issued, but codes remain — re-check the Alerts card",
    };
  }

  // -------------------------------------------------------------------------
  // US-483-b display-brightness consumer (F-121) -- pure, node-testable logic.
  // The dashboard is a PURE CONSUMER of the states/light file US-483-a writes;
  // it NEVER reads the sensor. US-893-a (Atlas ruling 3 / A7): the light bridge
  // is the ONE brightness applier -- it publishes brightnessLevel from the one
  // curve -- and the page APPLIES that level. The page holds no curve, no lux
  // thresholds and no floor. It keeps only what it must decide itself: whether
  // the file is fresh (luxStaleSec), what to show when it is not (the injected
  // defaultLevel, US-483-b; no new injection, Atlas G5), and the STOP override
  // (a real active STOP alert is FULL brightness, US-484-b).
  // -------------------------------------------------------------------------

  // Spool 6d ch.4 (US-484-b): "a red alarm is full brightness always,
  // independent of auto-dim -- only ambient content dims." Full IS the top of
  // the 0..1 range, so this is a definition, not a tunable: there is no config
  // key that may lower a live PULL-OVER alarm.
  var STOP_ALARM_LEVEL = 1.0;

  // The file:// preview / unconfigured fallback for the two keys the page reads
  // from the injected window.DISPLAY_AUTODIM. They MIRROR the validator DEFAULTS
  // (tests/test_display_autodim_floor_rule.py pins the parity).
  //
  // US-893-a: the curve keys left with the curve. The bridge resolves them from
  // config itself, so a page copy could only ever disagree with the level it
  // applies.
  //
  // US-595 -- alarmFloorLevel was retired here too. It was superseded by
  // STOP_ALARM_LEVEL above (US-484-b ch.4: a STOP goes to FULL). The merge below
  // iterates BRIGHTNESS_DEFAULTS rather than the injected object, so a deployed
  // config.json still carrying a retired key is ignored BY CONSTRUCTION. Do not
  // re-add one to restore compatibility -- there is nothing to be compatible with.
  var BRIGHTNESS_DEFAULTS = {
    defaultLevel: 0.70,   // applied when states/light is absent, stale or
                          // malformed. Applied UNCLAMPED: validate_config enforces
                          // defaultLevel >= minLevel (US-627), and a clamp here
                          // could only mask a config that failed that gate.
    luxStaleSec: 10,      // a states/light older than this -> fallback
  };

  // Resolve the injected config over the grounded defaults (only well-typed
  // overrides win). A malformed/absent global leaves every default in place.
  function resolveAutoDimConfig(cfg) {
    var out = {};
    for (var k in BRIGHTNESS_DEFAULTS) {
      if (Object.prototype.hasOwnProperty.call(BRIGHTNESS_DEFAULTS, k)) {
        out[k] = BRIGHTNESS_DEFAULTS[k];
      }
    }
    if (cfg && typeof cfg === "object") {
      for (var key in BRIGHTNESS_DEFAULTS) {
        if (!Object.prototype.hasOwnProperty.call(cfg, key)) continue;
        var v = cfg[key];
        if (typeof v === "number" && isFinite(v)) out[key] = v;
      }
    }
    return out;
  }

  // US-878-c: the fixed-brightness key, as the server injects it in the
  // settings blob (the overlay's flat dot-path).
  var OVERRIDE_LEVEL_KEY = "pi.display.autoDim.overrideLevel";

  // brightnessAlarmActive (the alarm input below) is US-899-a1's: it keys on the
  // states/alerts takeover, beside takeoverAlertView.

  // US-893-a (Atlas A7) -- THE ONE APPLIER. Every surface that needs the panel's
  // level (the screen frame, and from US-893-b the Light page's status line and
  // dot) reads this one return, so no two can disagree. In order:
  //
  //   1. alarmActive -> {1.0, 'alert'}. US-484-b / Spool 6d ch.4, the
  //      load-bearing safety short-circuit: while a real STOP is active the
  //      surface is FULL before anything else is read, so a dark cabin (or a dead
  //      light sensor) can never dim a PULL-OVER alarm. It SUPERSEDED the old
  //      alarmFloorLevel key outright, which is why US-595 could retire it.
  //   2. US-878-c (Atlas B4): pi.display.autoDim.overrideLevel found in the
  //      per-request settings blob and a finite number in [0, 1] -> {it,
  //      'fixed'}. A CONFIG fact, not a sensor one, so a fixed level survives a
  //      dead light sensor. The blob is its only carrier (no states/light key,
  //      no bridge timer). Outside [0, 1] it falls through, never clamped
  //      (US-627); null (auto) or not found falls through too.
  //   3. FRESH -> {data.brightnessLevel, data.brightnessMode}: the level the
  //      bridge published, applied as published ('auto', or 'default' when the
  //      bridge had no reading). FRESH = an object, not sourceUnavailable, a
  //      parseable ts no older than luxStaleSec, and a brightnessLevel that is a
  //      finite number in [0, 1].
  //   4. otherwise -> {injected defaultLevel, 'fallback'}.
  //
  // lux is NOT consulted: the bridge already turned it into the level. An
  // out-of-range brightnessLevel is fallback, NEVER clamped (US-627: never
  // silently repair -- a clamp would leave the operator believing a value that
  // never takes effect). The fallback defaultLevel is applied UNCLAMPED for the
  // same reason; validate_config enforces defaultLevel >= minLevel. A payload
  // with no brightnessLevel at all (an older producer) is fallback, not a throw.
  function appliedBrightness(lightData, injectedAutoDim, nowMs, alarmActive, settings) {
    if (alarmActive) return { level: STOP_ALARM_LEVEL, basis: "alert" };
    var override = settingsEntry(settings, OVERRIDE_LEVEL_KEY);
    if (override.found && typeof override.value === "number" && isFinite(override.value) &&
        override.value >= 0 && override.value <= 1) {
      return { level: override.value, basis: "fixed" };
    }
    var c = resolveAutoDimConfig(injectedAutoDim);
    var fallback = { level: c.defaultLevel, basis: "fallback" };
    if (!isObj(lightData) || sourceUnavailable(lightData, "light")) return fallback;
    var age = readAgeSec(lightData, nowMs);
    if (age === null || !(age <= c.luxStaleSec)) return fallback;
    var level = lightData.brightnessLevel;
    if (typeof level !== "number" || !isFinite(level) || level < 0 || level > 1) {
      return fallback;
    }
    return { level: level, basis: lightData.brightnessMode };
  }

  // The payload's read age in seconds, or null when it carries no parseable ts.
  // An UNDATED reading is the one most likely to be stale, so it can never be
  // rendered as current.
  function readAgeSec(data, nowMs) {
    if (!isObj(data) || typeof data.ts !== "string") return null;
    var t = Date.parse(data.ts);
    if (isNaN(t)) return null;
    return (nowMs - t) / 1000;
  }

  // -------------------------------------------------------------------------
  // US-893-b Light page (F-127; specs/v030-light-page-design.md layout A +
  // glyph, governed by the Atlas L1-L6 / Iris L1-L7 rulings of 2026-10-19).
  // A PURE CONSUMER of states/light. The word is the provider's lightBand, the
  // curve is the provider's points, and the dot's y and the status line are the
  // level the kiosk APPLIED (appliedBrightness, the one applier), so the page,
  // the screen and the bridge cannot disagree. The page derives no band and no
  // level from lux and holds no lux threshold: a dot OFF the line (stale
  // fallback, STOP full) is the truth, not a bug.
  // -------------------------------------------------------------------------

  // The provider's reasons.lux codes -> glass text (Atlas L1). One table, the
  // IMU_REASON_TEXT pattern; IRIS owns the words.
  var LIGHT_REASON_TEXT = {
    at_limit: "sensor at limit",
    no_reading: "no reading",
  };
  var LIGHT_NO_DATA_TEXT = "no light data";
  var LIGHT_NO_TIMESTAMP_TEXT = "no timestamp";
  var LIGHT_AT_LIMIT_TEXT = "at limit";
  var LIGHT_UNIT = "lux";  // the one unit word on the page, never 'lx' (Iris L6)

  // The three provider bands, each drawn by its own glyph (Iris L4).
  var LIGHT_BANDS = ["night", "dusk", "day"];

  // The curve graph (spec s3: 200 x 104). The plot's left pad holds the y
  // labels ('100%' is ~36 px in the mono at --fs-meta, Iris L5); the bottom pad
  // holds the x labels. The y domain sits CURVE_Y_HEADROOM under minLevel so
  // the flat floor does not lie on the x axis -- presentation headroom, not a
  // level (Iris L5).
  var LIGHT_CURVE_W = 200;
  var LIGHT_CURVE_H = 104;
  var LIGHT_CURVE_PAD_L = 40;
  var LIGHT_CURVE_PAD_R = 6;
  var LIGHT_CURVE_PAD_T = 8;
  var LIGHT_CURVE_PAD_B = 22;
  var LIGHT_CURVE_LABEL_DX = 3;   // an x label's gap from its dashed vertical
  var LIGHT_CURVE_LABEL_DY = 5;   // a y label's baseline under its level
  var LIGHT_CURVE_X_LABEL_RISE = 3; // the x labels' baseline above the bottom edge
  var CURVE_Y_HEADROOM = 0.25;

  // THE ONE LOG SITE in carousel.js (Atlas 2026-10-16 gate item 1, Iris L5): a
  // lux -> a pixel x on the log-lux axis, and nothing else. luxLo / luxHi are
  // the published curve's first and last lux. It never takes the log of a
  // value <= 0: a lux at or below luxLo (night reads ~0.35 lux, and 0 is a
  // reading) pins to the left edge, one at or above luxHi to the right edge. A
  // non-numeric lux, or an axis that cannot be logged, has no x (null).
  function luxAxisX(lux, luxLo, luxHi, widthPx) {
    if (!isNum(lux) || !isNum(luxLo) || !isNum(luxHi) || !isNum(widthPx)) return null;
    if (!(luxLo > 0) || !(luxHi > luxLo)) return null;
    if (lux <= luxLo) return 0;
    if (lux >= luxHi) return widthPx;
    return widthPx * (Math.log10(lux) - Math.log10(luxLo)) /
      (Math.log10(luxHi) - Math.log10(luxLo));
  }

  // A lux for the glass (Iris L6): under 10 one decimal, from 10 a whole number
  // with the fixed ',' separator. The format is chosen from the raw value.
  function fmtLuxValue(lux) {
    return lux < 10 ? lux.toFixed(1) : fmtThousands(Math.round(lux));
  }

  // An x-axis label: a whole config value prints bare ('3', '1,000'), anything
  // else as a lux (Iris L5).
  function fmtAxisLux(v) {
    return v === Math.floor(v) ? fmtThousands(v) : fmtLuxValue(v);
  }

  // The published lux reason, through the one table. lux null with no code (a
  // producer older than US-893-a) is the no_reading class (Atlas A3); an
  // unknown code paints as itself rather than as a guess.
  function lightLuxReason(data) {
    var reasons = isObj(data.reasons) ? data.reasons : {};
    var code = reasons.lux;
    if (typeof code !== "string" || !code) return LIGHT_REASON_TEXT.no_reading;
    return Object.prototype.hasOwnProperty.call(LIGHT_REASON_TEXT, code)
      ? LIGHT_REASON_TEXT[code]
      : code;
  }

  // One raw cell (X2): 'at limit' (amber) on its flag, a count with the ','
  // separator, or '--' (tertiary) for a null or failed count -- never a
  // floored 0 and never a subtraction.
  function lightCountCell(count, atLimit) {
    if (atLimit === true) return { value: LIGHT_AT_LIMIT_TEXT, tone: "warn" };
    if (isNum(count) && count >= 0) return { value: fmtThousands(count), tone: "plain" };
    return { value: "--", tone: "none" };
  }

  function lightRawView(data) {
    var lim = isObj(data) && isObj(data.atLimit) ? data.atLimit : {};
    var d = isObj(data) ? data : {};
    return {
      ir: lightCountCell(d.irCount, lim.ir),
      full: lightCountCell(d.fullCount, lim.full),
      // visible = full - ir, so it is derived from a clipped count when EITHER is.
      visible: lightCountCell(d.visibleCount, lim.ir === true || lim.full === true),
      range: {
        // The gain word exactly as published -- no multiplier, the page holds
        // no gain table (Iris L2).
        gain: typeof d.gain === "string" && d.gain ? d.gain : "--",
        ms: isNum(d.integrationMs) && d.integrationMs >= 0
          ? fmtThousands(d.integrationMs) + " ms"
          : "--",
      },
    };
  }

  // The status line, from the APPLIED basis and never from data.brightnessMode
  // (Atlas L4), so a stale file that says 'auto' can never show AUTO. Three
  // runs in the mockup's tiers -- the Michroma label, the mono level, the mono
  // qualifier -- which is the shape Iris measured the 412 px worst case in.
  function lightStatusView(applied) {
    var value = Math.round(applied.level * 100) + " %";
    var label = applied.basis === "auto" ? "BRIGHTNESS AUTO" : "BRIGHTNESS";
    var note = applied.basis === "auto" ? null
      : applied.basis === "alert" ? "(alert)"
      : applied.basis === "fixed" ? "(fixed in Settings)" : "(default, no reading)";
    return {
      label: label, value: value, note: note,
      text: label + " " + value + (note ? " " + note : ""),
    };
  }

  // The curve graph from states/light.curve alone. Every polyline vertex is a
  // published [lux, level]; the dot is (lux, the APPLIED level). Nothing is
  // interpolated along the line, and no level or band comes from lux. A
  // missing or malformed curve draws nothing (null) -- never a guessed one.
  function lightCurveView(curve, lux, appliedLevel) {
    if (!isObj(curve) || !Array.isArray(curve.points) || curve.points.length < 2) return null;
    var pts = curve.points;
    for (var i = 0; i < pts.length; i++) {
      if (!Array.isArray(pts[i]) || !isNum(pts[i][0]) || !isNum(pts[i][1])) return null;
    }
    var luxLo = pts[0][0];
    var luxHi = pts[pts.length - 1][0];
    if (luxAxisX(luxHi, luxLo, luxHi, 1) === null) return null;
    var plotW = LIGHT_CURVE_W - LIGHT_CURVE_PAD_L - LIGHT_CURVE_PAD_R;
    var plotH = LIGHT_CURVE_H - LIGHT_CURVE_PAD_T - LIGHT_CURVE_PAD_B;
    var minLevel = isNum(curve.minLevel) ? curve.minLevel : null;
    var yLo = minLevel === null ? 0 : Math.max(0, minLevel - CURVE_Y_HEADROOM);
    function px(v) {
      return Number(v.toFixed(1));
    }
    function x(l) {
      return px(LIGHT_CURVE_PAD_L + luxAxisX(l, luxLo, luxHi, plotW));
    }
    // A level outside the domain pins to its edge, the way luxAxisX pins lux.
    function y(level) {
      var f = (Math.min(Math.max(level, yLo), 1) - yLo) / (1 - yLo);
      return px(LIGHT_CURVE_PAD_T + plotH * (1 - f));
    }
    var line = [];
    for (var j = 0; j < pts.length; j++) line.push(x(pts[j][0]) + "," + y(pts[j][1]));
    var verticals = [];
    var ends = [
      { lux: curve.luxMin, label: null, anchor: "end", dx: -LIGHT_CURVE_LABEL_DX },
      { lux: curve.luxFull, label: " " + LIGHT_UNIT, anchor: "start", dx: LIGHT_CURVE_LABEL_DX },
    ];
    // The luxMin label sits left of its line and the luxFull label right of
    // its own, so the two never meet however close the verticals are.
    for (var k = 0; k < ends.length; k++) {
      var e = ends[k];
      if (!isNum(e.lux) || !(e.lux > 0)) continue;
      var vx = x(e.lux);
      verticals.push({
        x: vx, labelX: px(vx + e.dx), anchor: e.anchor,
        label: fmtAxisLux(e.lux) + (e.label || ""),
      });
    }
    var yLabels = [{ y: px(y(1) + LIGHT_CURVE_LABEL_DY), text: "100%" }];
    if (minLevel !== null && minLevel < 1) {
      yLabels.push({
        y: px(y(minLevel) + LIGHT_CURVE_LABEL_DY), text: Math.round(minLevel * 100) + "%",
      });
    }
    var dot = null;
    if (isNum(lux) && lux >= 0 && isNum(appliedLevel)) dot = { x: x(lux), y: y(appliedLevel) };
    return {
      points: line.join(" "),
      axis: {
        x0: LIGHT_CURVE_PAD_L, x1: LIGHT_CURVE_W - LIGHT_CURVE_PAD_R,
        yTop: y(1), yBottom: y(yLo),
      },
      verticals: verticals,
      yLabels: yLabels,
      labelY: LIGHT_CURVE_H - LIGHT_CURVE_X_LABEL_RISE,
      dot: dot,
    };
  }

  // The whole Light page. `alarmActive` is the same STOP test the panel
  // applier is called with, so the status and the dot read the level the
  // screen is actually at. Reasons are checked in Atlas L1 / Iris L1 order: no
  // payload, then no timestamp, then the provider's lux reason; a null
  // lightBand is '--' with no glyph. Stale (age > luxStaleSec, or undated)
  // dims the word tile, the curve and the raw row -- never the status, which
  // reports what the kiosk applied.
  function lightPageView(data, cfg, nowMs, alarmActive, settings) {
    var applied = appliedBrightness(data, cfg, nowMs, alarmActive, settings);
    var status = lightStatusView(applied);
    if (!isObj(data) || sourceUnavailable(data, "light")) {
      return {
        absent: true, stale: false,
        word: { text: "--", glyph: null },
        ambient: { value: "--", unit: "", none: true },
        reason: isObj(data) ? sourceReason(data, "light") : LIGHT_NO_DATA_TEXT,
        age: null,
        raw: lightRawView(null),
        curve: null,
        applied: applied,
        status: status,
      };
    }
    var c = resolveAutoDimConfig(cfg);
    var ageSec = readAgeSec(data, nowMs);
    var stale = ageSec === null || ageSec > c.luxStaleSec;
    var age = null;
    if (ageSec === null) age = { text: LIGHT_NO_TIMESTAMP_TEXT, tone: "none" };
    else if (stale) age = { text: Math.max(0, Math.floor(ageSec)) + " s", tone: "warn" };
    var lux = isNum(data.lux) && data.lux >= 0 ? data.lux : null;
    var band = LIGHT_BANDS.indexOf(data.lightBand) === -1 ? null : data.lightBand;
    return {
      absent: false,
      stale: stale,
      word: band === null
        ? { text: "--", glyph: null }
        : { text: band.toUpperCase(), glyph: band },
      ambient: lux === null
        ? { value: "--", unit: "", none: true }
        : { value: fmtLuxValue(lux), unit: LIGHT_UNIT, none: false },
      reason: lux === null ? lightLuxReason(data) : null,
      age: age,
      raw: lightRawView(data),
      curve: lightCurveView(data.curve, lux, applied.level),
      applied: applied,
      status: status,
    };
  }

  // -------------------------------------------------------------------------
  // US-497 IMU live-instrument card (S4-card, F-113) -- pure, node-testable.
  //
  // A PURE CONSUMER of the states/imu file US-478's bridge writes. The bridge
  // already resolved the one hard problem (an accelerometer cannot tell gravity
  // from acceleration; a single slow gravity estimate defines the level frame,
  // the pitch AND the heading tilt-compensation). This card MAPS and FORMATS
  // that contract -- it never fuses and never re-derives, because a second
  // derivation is a second chance for the compass and the grade to disagree
  // about which way is down (Atlas DELTA-2; specs/architecture.md 10.8.2).
  //
  // The failure mode that shapes this whole module: a LIVE GRAPHICAL INSTRUMENT
  // CAN FREEZE, and a text tile cannot. A gray "NA" reads as dead at a glance; a
  // g-dot frozen at 0.4 g reads exactly like a car holding a steady corner. So
  // staleness here blanks the INSTRUMENT (the idle fallback), it does not merely
  // gray a label -- AC-3, "never a frozen/zeroed live instrument".
  // -------------------------------------------------------------------------

  // Freshness window, in seconds. US-896-a (Atlas S105 Q3/G1) re-grounds it on
  // a MEASUREMENT: states/imu writes every 1.00-1.02 s at stateHz 1, its ts is
  // whole seconds and the kiosk polls every 100 ms, so a healthy file reads a
  // median 1.84 s / max 1.94 s old before it is replaced. The old 2.0 left
  // ~0.06 s of margin and would flash NO UPDATE on a healthy feed. 3.0 = three
  // readings at 1 Hz, ~1 s above the measured worst case. Measured parked on
  // wall power; NOT yet validated under drive load.
  //
  // ONE key for one provider: NAV's stale state and the Motion dim both read
  // resolveImuStaleSec(). Two keys would let NAV freeze while Motion shows live
  // on the same fact.
  //
  // US-882-c: the window is pi.display.stale.imuSec, injected per request as
  // window.DISPLAY_STALE.imuSec. This constant is only the MIRROR of the
  // validator default, used when the injection is absent or not a finite
  // positive number; tests/ui/test_carousel_imu_stale_config.py pins it equal to
  // the validator DEFAULTS value, so drift fails a test.
  var DEFAULT_IMU_STALE_SEC = 3.0;

  // Read at CALL time (the currentDebugLevel pattern): the injected value can
  // then be checked by a node probe that sets the global before calling.
  function resolveImuStaleSec(injected) {
    var v = isObj(injected) ? injected.imuSec : null;
    return typeof v === "number" && isFinite(v) && v > 0 ? v : DEFAULT_IMU_STALE_SEC;
  }

  // The bridge's per-field absence vocabulary, in words. This is a NAME map,
  // not a second set of facts: an unknown code passes straight through rather
  // than being swallowed into a generic word, because a reason the card has not
  // been taught is still information the operator can act on.
  var IMU_REASON_TEXT = {
    sensor_absent: "sensor not detected",
    no_mag_reading: "no compass reading",
    tilt_unresolved: "orientation unresolved",
    pitch_out_of_range: "pitch beyond range",
    // US-749: the fusion's plausibility guard withheld a pitch the accelerometer contradicts.
    gyro_implausible: "gyro implausible",
    no_source: "no source",
    // US-896-a (closes US-821's text): the AHRS has no heading YET. The NAV
    // badge is this text upper-cased, STARTING UP (spec s4.2).
    heading_unseeded: "starting up",
    // US-892-c (Atlas C2): the pitch fusion has not seeded YET -- the same
    // class of fact as heading_unseeded. The Motion GYRO cell reads it.
    pitch_unseeded: "starting up",
  };

  function imuReason(data, field) {
    var reasons = isObj(data) && isObj(data.reasons) ? data.reasons : {};
    var code = reasons[field];
    if (typeof code !== "string" || !code) return "unavailable";
    return Object.prototype.hasOwnProperty.call(IMU_REASON_TEXT, code)
      ? IMU_REASON_TEXT[code]
      : code;
  }

  // The compass tape: how many degrees are visible across the strip, and how
  // often a tick / a rose label lands. A label on every tick is unreadable at
  // this size, so minor ticks are unlabelled and the 8-point cardinals carry the
  // words.
  var COMPASS_TAPE_SPAN_DEG = 90;
  var COMPASS_TAPE_TICK_DEG = 15;
  var COMPASS_TAPE_LABEL_DEG = 45;

  var COMPASS_ROSE = [
    "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
    "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
  ];

  // The 16-point rose label for a bearing. The modulo on the INDEX is the
  // load-bearing part: 359 degrees rounds to index 16, which runs off the array
  // and would read `undefined` exactly as the vehicle points north.
  function headingCardinal(deg) {
    if (typeof deg !== "number" || !isFinite(deg)) return null;
    var d = ((deg % 360) + 360) % 360;
    return COMPASS_ROSE[Math.round(d / 22.5) % 16];
  }

  function normDeg(deg) {
    return ((deg % 360) + 360) % 360;
  }

  // US-508: the scrolling compass TAPE that replaces the built rotating needle
  // (CIO-locked: "I love the tape", frozen). A fixed caret marks the vehicle's
  // heading and the TAPE moves under it.
  //
  // The one property worth testing hardest is DIRECTION. A tape that scrolls the
  // wrong way is a perfectly plausible instrument that is exactly backwards, and
  // nothing about a screenshot reveals it -- only a human turning a car does.
  // The contract: a bearing CLOCKWISE of the current heading sits to the RIGHT
  // (positive offset), so turning right walks it toward the caret and the labels
  // travel right-to-left, exactly like a real tape compass.
  //
  // `offset` is -1..1 across the strip, so the renderer owns the pixels and this
  // function owns the geometry. Signed shortest-arc, so the tape does not tear
  // itself apart across north: at 350 degrees the window genuinely spans 305..35.
  //
  // US-896-a: `tickDeg` (optional) is the lattice step. The interim card omits
  // it and keeps its 15-degree ticks; the NAV tape passes 5 (spec s3).
  function compassTape(headingDeg, spanDeg, tickDeg) {
    var span = typeof spanDeg === "number" && isFinite(spanDeg) && spanDeg > 0
      ? spanDeg
      : COMPASS_TAPE_SPAN_DEG;
    var step = typeof tickDeg === "number" && isFinite(tickDeg) && tickDeg > 0
      ? tickDeg
      : COMPASS_TAPE_TICK_DEG;
    // A dead magnetometer renders NO tape. A tape frozen under the caret reads
    // as a confident heading in exactly the way the frozen needle did -- the
    // instrument must be absent, not stopped (US-497's rule, new geometry).
    if (typeof headingDeg !== "number" || !isFinite(headingDeg)) {
      return { available: false, headingDeg: null, spanDeg: span, ticks: [] };
    }
    var heading = normDeg(headingDeg);
    var half = span / 2;
    var ticks = [];
    // Walk the tick lattice (absolute bearings, not offsets from the heading) so
    // every tick keeps its own true bearing and its label cannot drift off it.
    var first = Math.ceil((heading - half) / step) * step;
    for (var deg = first; deg <= heading + half; deg += step) {
      var bearing = normDeg(deg);
      var delta = deg - heading;   // already the shortest arc by construction
      ticks.push({
        deg: bearing,
        offset: delta / half,
        label: bearing % COMPASS_TAPE_LABEL_DEG === 0
          ? COMPASS_ROSE[Math.round(bearing / 22.5) % 16]
          : null,
        major: bearing % COMPASS_TAPE_LABEL_DEG === 0,
      });
    }
    return { available: true, headingDeg: heading, spanDeg: span, ticks: ticks };
  }

  // -------------------------------------------------------------------------
  // US-896-a (F-160; specs/v030-navigation-page-design.md s3/s4.1/s4.2): the
  // NAV card's heading half -- the bearing tape, the digits, the 8-point point
  // and the five heading states. Pure; the renderer is in the browser block.
  // -------------------------------------------------------------------------

  // Spec s3: fine ticks every 5 degrees, minor every 15, major + letter every
  // 45 (COMPASS_TAPE_LABEL_DEG). The 90-degree window is COMPASS_TAPE_SPAN_DEG.
  var NAV_TAPE_FINE_DEG = 5;
  var NAV_TAPE_MINOR_DEG = 15;

  // CIO N-4 (spec s4.1): each new reading starts a 1 s ease-in-out glide.
  var NAV_GLIDE_MS = 1000;

  // R25 / N-12: the 8 compass points, N first so index 0 is north.
  var COMPASS_POINTS_8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];

  // The bridge's startup code (imu_state_bridge.REASON_HEADING_UNSEEDED): the
  // AHRS has no heading YET, which is not a dead sensor (spec s4.2).
  var REASON_HEADING_UNSEEDED = "heading_unseeded";

  // Spec s7 (OEM mockup rules): the band's text before the first reading.
  var NAV_WAITING_TEXT = "waiting for the first heading reading";
  // US-911 (Atlas X3; CIO 2026-10-19 chose Iris's wording): ONE text for "the
  // legacy engine publishes no headingCalibrated and no reason for it". Motion's
  // labelled COMPASS cell shows it as is; NAV's unlabelled badge note prefixes
  // 'calibration ' (so NAV still reads 'calibration not published').
  var CALIBRATION_ABSENT_TEXT = "not published";

  // The NEW 8-point function (R25). Half up: 22.5 -> NE, 337.5 -> N, because
  // the index 8 wraps to 0. headingCardinal (16-point) is deliberately left
  // alone: the interim card keeps it until US-892-b retires both.
  function compassPoint8(deg) {
    if (typeof deg !== "number" || !isFinite(deg)) return null;
    return COMPASS_POINTS_8[Math.floor(normDeg(deg) / 45 + 0.5) % 8];
  }

  // '247°', zero-padded to three digits. The modulo after the round keeps
  // 359.6 reading 000, never a 360 that is not a bearing.
  function fmtHeadingDigits(deg) {
    if (typeof deg !== "number" || !isFinite(deg)) return "---°";
    var n = Math.round(normDeg(deg)) % 360;
    return (n < 10 ? "00" : n < 100 ? "0" : "") + n + "°";
  }

  // Signed shortest arc from one bearing to another, in (-180, 180]:
  // 350 -> 10 is +20, never -340 (spec s4.1).
  function shortestArcDeg(fromDeg, toDeg) {
    var d = normDeg(toDeg - fromDeg);
    return d > 180 ? d - 360 : d;
  }

  // Quadratic ease-in-out on 0..1. Exactly 0.5 at the midpoint, so half the
  // glide is half the arc.
  function easeInOut(p) {
    return p < 0.5 ? 2 * p * p : 1 - 2 * (1 - p) * (1 - p);
  }

  // The glide: where the tape is drawn now. {fromDeg, toDeg, startMs}; a null
  // fromDeg means "drawn at toDeg" (a step: the first reading, a reduced-motion
  // panel, or a frozen tape).
  function navGlideInit() {
    return { fromDeg: null, toDeg: null, startMs: null };
  }

  function navDrawnDeg(glide, nowMs) {
    if (!isObj(glide) || glide.toDeg === null) return null;
    if (glide.fromDeg === null || glide.startMs === null) return glide.toDeg;
    var p = (nowMs - glide.startMs) / NAV_GLIDE_MS;
    if (!(p < 1)) return glide.toDeg;
    if (p < 0) p = 0;
    return normDeg(glide.fromDeg + shortestArcDeg(glide.fromDeg, glide.toDeg) * easeInOut(p));
  }

  // True while a glide is still moving the tape (the browser keeps painting
  // frames until it is false).
  function navGliding(glide, nowMs) {
    return isObj(glide) && glide.fromDeg !== null && glide.startMs !== null &&
      nowMs - glide.startMs < NAV_GLIDE_MS;
  }

  // A new reading starts a fresh glide FROM WHERE THE TAPE IS DRAWN NOW, so a
  // reading mid-glide never snaps. The same bearing again is not a new reading.
  // Reduced motion steps.
  function navGlideNext(glide, targetDeg, nowMs, reducedMotion) {
    var g = isObj(glide) ? glide : navGlideInit();
    if (typeof targetDeg !== "number" || !isFinite(targetDeg)) return g;
    var target = normDeg(targetDeg);
    if (g.toDeg === target) return g;
    var drawn = navDrawnDeg(g, nowMs);
    if (drawn === null || reducedMotion) return { fromDeg: null, toDeg: target, startMs: null };
    return { fromDeg: drawn, toDeg: target, startMs: nowMs };
  }

  // One paint's glide from the heading view: a dead sensor drops the bearing
  // (no tape, and the next reading steps rather than gliding from a bearing
  // the panel no longer has); a stale feed FREEZES the tape where it is drawn
  // (no glide); anything else glides to the reading.
  function navGlideStep(glide, view, nowMs, reducedMotion) {
    if (!isObj(view) || view.state === "dead") return navGlideInit();
    if (view.state === "stale") {
      var drawn = navDrawnDeg(glide, nowMs);
      return { fromDeg: null, toDeg: drawn !== null ? drawn : view.headingDeg, startMs: null };
    }
    return navGlideNext(glide, view.headingDeg, nowMs, reducedMotion);
  }

  // The five heading states, FIRST MATCH WINS (spec s4.2):
  //   dead        headingDeg null, reason not heading_unseeded -> no tape at all
  //   stale       ts age > imuSec (strict)  -> frozen tape, NO UPDATE n s
  //   unseeded    heading_unseeded          -> STARTING UP
  //   uncalibrated headingCalibrated false  -> tape normal, NOT CALIBRATED
  //   legacy      headingCalibrated absent  -> tape normal, "--" + reason
  //   trusted     otherwise                 -> no badge
  // No payload, and an undated one, are dead too: neither can show a bearing
  // as current (the "no read time" rule). A stale page freezes and
  // badges but does not dim -- the badge is its stale signal (spec s7).
  //
  // ONE ACQUISITION PATH: the bearing and its reason come from the RESOLVED
  // heading tile (imuHeadingTile), never a second read of the payload --
  // tests/ui/test_carousel_heading_bare_bearing_recorded_pass.py pins it.
  function navHeadingView(data, nowMs, staleSec) {
    if (!isObj(data)) return navDeadView("no motion feed");
    var resolved = imuHeadingTile(data);
    var unseeded = !resolved.available &&
      resolved.detail === IMU_REASON_TEXT[REASON_HEADING_UNSEEDED];
    if (!resolved.available && !unseeded) return navDeadView(resolved.detail);
    var age = readAgeSec(data, nowMs);
    if (age === null) return navDeadView("no read time");
    var heading = resolved.available ? resolved.deg : null;
    if (age > staleSec) {
      return navLiveView("stale", heading, "NO UPDATE " + Math.floor(age) + " s", null);
    }
    if (unseeded) {
      return navLiveView("unseeded", null, resolved.detail.toUpperCase(), null);
    }
    if (data.headingCalibrated === false) {
      return navLiveView("uncalibrated", heading, "NOT CALIBRATED", null);
    }
    if (data.headingCalibrated !== true) {
      var reasons = isObj(data.reasons) ? data.reasons : {};
      return navLiveView(
        "legacy", heading, "--",
        typeof reasons.headingCalibrated === "string" && reasons.headingCalibrated
          ? imuReason(data, "headingCalibrated")
          : "calibration " + CALIBRATION_ABSENT_TEXT
      );
    }
    return navLiveView("trusted", heading, null, null);
  }

  function navDeadView(reason) {
    return {
      state: "dead", tape: false, headingDeg: null,
      badge: null, badgeNote: null, reason: reason,
    };
  }

  function navLiveView(state, heading, badge, badgeNote) {
    return {
      state: state, tape: true, headingDeg: heading,
      badge: badge, badgeNote: badgeNote, reason: null,
    };
  }

  // The NAV tape's geometry: compassTape's lattice (same direction contract,
  // same 90-degree window) at 5-degree ticks, each tagged with its tier.
  function navTape(drawnDeg) {
    var tape = compassTape(drawnDeg, COMPASS_TAPE_SPAN_DEG, NAV_TAPE_FINE_DEG);
    for (var i = 0; i < tape.ticks.length; i++) {
      var t = tape.ticks[i];
      t.tier = t.major ? "major" : t.deg % NAV_TAPE_MINOR_DEG === 0 ? "minor" : "fine";
    }
    return tape;
  }

  // -------------------------------------------------------------------------
  // US-896-b (F-160; spec s4.3/s4.4/s4.5): the NAV card's bottom row -- GRADE
  // from states/imu, the trip from system-status's drive block. Pure; the
  // renderer is in the browser block. No speed on this page (CIO N-2).
  // -------------------------------------------------------------------------

  // Spec s4.4: the reason under '-- mi' when there is no window to show.
  var NAV_TRIP_NOT_MEASURED = "not measured";
  // A window with no elapsedSec (the provider could not span it): the null
  // says it was not read, on the glass.
  var NAV_ELAPSED_NOT_READ = "elapsed not read";

  // GRADE: the Motion grade tile's formatter (one decimal, signed, a true
  // minus), so the two pages can never print one reading two ways. The slope
  // glyph tilts with the sign of the PRINTED value, so '+0.0 %' lies flat
  // rather than claiming a climb the digits do not show. A missing or undated
  // feed is '--' + its reason, on the glass (the US-852 rule). Parked it stays
  // live (spec s4.5); a stale feed is frozen under the NO UPDATE badge.
  function navGradeView(data, nowMs) {
    if (!isObj(data)) return { value: "--", slope: null, reason: "no motion feed" };
    if (readAgeSec(data, nowMs) === null) {
      return { value: "--", slope: null, reason: "no read time" };
    }
    var tile = imuGradeTile(data);
    if (!tile.available) return { value: "--", slope: null, reason: tile.detail };
    var shown = Math.round(tile.pct * 10);
    return {
      value: tile.value,
      slope: shown > 0 ? "up" : shown < 0 ? "down" : "flat",
      reason: null,
    };
  }

  // h:mm from the provider's elapsedSec. NO time arithmetic on timestamps
  // (spec s4.4): a page-side now - sinceTs would count parked time as drive
  // time. Whole minutes, never rounded up past what has elapsed.
  function fmtElapsed(sec) {
    if (typeof sec !== "number" || !isFinite(sec) || sec < 0) return null;
    return Math.floor(sec / 3600) + ":" + two(Math.floor((sec % 3600) / 60));
  }

  // The trip label, precedence top wins (spec s4.4, Atlas B-1(b), CIO Q1):
  //   1. distanceKm or distancePartial null -> '-- mi' + 'not measured'
  //   2. distancePartial true   -> 'SINCE h:mm', parked OR recording
  //   3. drive.state known, not recording -> 'LAST DRIVE'
  //   4. otherwise               -> 'THIS DRIVE'
  // The page reads the provider's facts and compares no timestamps: parked is
  // never inferred from speed, elapsed or time, and a null drive.state does not
  // assert parked. Rule 1 owns the figures only; its label still follows the
  // state (rules 3/4), as it has no window to qualify. An unreadable
  // system-status arrives as null, which is rule 1; a stale one is painted as
  // published -- never extrapolated (Atlas Q2).
  //
  // 'SINCE' is a label (Michroma) and h:mm a READING (--font-mono): the
  // Michroma subset has no ':' (Iris UIDEV-004), so the two travel apart.
  // h:mm is the panel's one 12-hour clock without AM/PM, the Engine history
  // label's rule (engineHistoryWindow).
  function navTripView(sysData) {
    var d = isObj(sysData) && isObj(sysData.drive) ? sysData.drive : {};
    var state = typeof d.state === "string" && d.state ? d.state : null;
    var parked = state !== null && state !== "recording";
    var km = typeof d.distanceKm === "number" && isFinite(d.distanceKm) ? d.distanceKm : null;
    var partial = typeof d.distancePartial === "boolean" ? d.distancePartial : null;
    var stateLabel = parked ? "LAST DRIVE" : "THIS DRIVE";
    if (km === null || partial === null) {
      return {
        window: "not-measured", label: stateLabel, time: null,
        distance: "-- mi", elapsed: NAV_TRIP_NOT_MEASURED, measured: false,
      };
    }
    var elapsed = fmtElapsed(d.elapsedSec);
    var view = {
      window: parked ? "last" : "this", label: stateLabel, time: null,
      distance: (km / KM_PER_MILE).toFixed(1) + " mi",
      elapsed: elapsed === null ? NAV_ELAPSED_NOT_READ : elapsed + " elapsed",
      measured: true,
    };
    if (partial) {
      var since = typeof d.distanceSinceTs === "string" && ISO_INSTANT.test(d.distanceSinceTs)
        ? new Date(Date.parse(d.distanceSinceTs)) : null;
      view.window = "since";
      view.label = "SINCE";
      view.time = since ? fmtTimeOfDay(since, false).split(" ")[0] : DRIVING_NOT_READ;
    }
    return view;
  }

  // -------------------------------------------------------------------------
  // US-892-b (F-127; specs/v030-motion-page-design.md s3/s4, layout A): the
  // Motion card's top two bands -- PITCH, the 15-minute GRADE graph, and g now
  // plus this drive's peaks. Pure; the renderer is in the browser block.
  //
  // Motion reads the RAW states/imu (Atlas B3): the provider publishes at
  // 1 Hz and the page steps with it, no interpolation and no page smoothing.
  // The grade graph reads states/grade-history ONLY (intervalS / windowS, the
  // provider's keys -- Atlas B4); the page keeps no trend of its own. Peaks are
  // states/imu.peaks, reset by the PROVIDER at drive start (US-892-a).
  // -------------------------------------------------------------------------

  // The absence text for an empty or all-null history (Iris M3), drawn above
  // the dashed zero line -- never a flat line, which would claim level road.
  var MOTION_NO_GRADE_HISTORY = "no grade history yet";
  // The bridge's REASON_GYRO_IMPLAUSIBLE (imu_state_bridge.py), the one key
  // whose text IMU_REASON_TEXT already holds (Atlas B5).
  var REASON_GYRO_IMPLAUSIBLE = "gyro_implausible";
  // The labels while a g reading is null: no sign means no direction to name.
  var MOTION_LON_NONE_LABEL = "ACCEL BRAKE";
  var MOTION_LAT_NONE_LABEL = "CORNER";

  // Grade graph geometry, in the svg's user units (spec s3: 300 x 58). The
  // line spans PLOT_W, so the end label sits right of the newest point inside
  // the box (OEM mockup 2026-10-14, motion:graph).
  var MOTION_GRAPH_W = 300;
  var MOTION_GRAPH_H = 58;
  var MOTION_GRAPH_PLOT_W = 236;
  var MOTION_GRAPH_PAD = 4;
  var MOTION_GRAPH_LABEL_DX = 6;
  var MOTION_GRAPH_LABEL_DY = 5;
  var MOTION_GRAPH_DOT_R = 4;
  // The empty-history text sits this far above the zero line (mockup: 8).
  var MOTION_GRAPH_EMPTY_RISE = 8;
  // The vertical scale is symmetric about 0 and grows with the history, in
  // whole steps of 2 %, never under +/-4 % (mockup motion:graph) -- so a flat
  // road's 0.1 % wobble is not stretched into hills.
  var MOTION_GRAPH_MIN_RANGE_PCT = 4;
  var MOTION_GRAPH_RANGE_STEP_PCT = 2;

  function isNum(v) {
    return typeof v === "number" && isFinite(v);
  }

  // Signed with a TRUE minus, the sign taken from the ROUNDED value: a value
  // that rounds to zero has no sign (never '-0.0', Iris M3/M6).
  function fmtSignedFixed(v, decimals) {
    var text = Math.abs(v).toFixed(decimals);
    if (Number(text) === 0) return text;
    return (v > 0 ? "+" : "−") + text;
  }

  function motionPitchView(data) {
    if (!isObj(data)) {
      return { value: "--", unit: "", sub: "no motion feed", none: true, warn: false };
    }
    var p = data.pitchDeg;
    if (!isNum(p)) {
      var reasons = isObj(data.reasons) ? data.reasons : {};
      return {
        value: "--", unit: "", sub: imuReason(data, "pitchDeg"), none: true,
        // The gyro guard is the one pitch reason that is a WARNING (spec s4):
        // the attitude is known to be contradicted, not merely not yet known.
        warn: reasons.pitchDeg === REASON_GYRO_IMPLAUSIBLE,
      };
    }
    var value = fmtSignedFixed(p, 1);
    var shown = Number(Math.abs(p).toFixed(1));
    return {
      value: value, unit: "°",
      sub: shown === 0 ? "level" : p > 0 ? "nose up" : "nose down",
      none: false, warn: false,
    };
  }

  function fmtPeak(v) {
    return isNum(v) ? Math.abs(v).toFixed(2) : "--";
  }

  // One g cell. The word follows the sign of the ROUNDED reading (+ =
  // accelerating / right, the imu_state_bridge contract), so '0.00' is never
  // labelled BRAKE; the number is the magnitude. Numbers are never coloured:
  // no g band exists (spec s4).
  function motionGCell(data, field, posWord, negWord, noneWord, peakLine) {
    var g = isObj(data) ? data[field] : null;
    if (!isNum(g)) {
      return {
        label: noneWord, value: "--", unit: "", none: true,
        note: isObj(data) ? imuReason(data, field) : "no motion feed",
        peak: peakLine,
      };
    }
    var text = Math.abs(g).toFixed(2);
    return {
      label: g < 0 && Number(text) !== 0 ? negWord : posWord,
      value: text, unit: " g", none: false, note: null, peak: peakLine,
    };
  }

  // US-892-c: the IMU health block (spec s3/s4 M-7). Each cell READS
  // states/imu and judges nothing: COMPASS is the provider's headingCalibrated,
  // GYRO its pitch reason, TILT FIX its ZUPT bias and stop count, UPDATED the
  // age of its ts. A cell is {value, tone, sub}; tone is the status colour --
  // ok / warn for the status cells, plain for a value, none for '--' + reason
  // (Iris M5). Unknown is never green.
  var MOTION_NO_FEED_TEXT = "no motion feed";
  var MOTION_NO_TIMESTAMP_TEXT = "no timestamp";
  // stopCount 0 means the bias is NOT measured yet: 0.0 is not a reading
  // (imu_state_bridge buildImuState).
  var MOTION_NO_STOPS_TEXT = "no stops yet";
  // The same wording as COMPASS's absent cell, so it reads the one source text
  // (US-911: 'not published' is written once in the NAV and Motion code).
  var MOTION_TILT_ABSENT_TEXT = CALIBRATION_ABSENT_TEXT;
  // The UPDATED age stops counting here; the amber already says "long ago"
  // (Iris M7).
  var MOTION_AGE_CAP_SEC = 999;

  // A whole, non-negative count with a FIXED ',' separator. Never
  // toLocaleString: the kiosk's locale is not ours to assume (Iris L6, shared
  // with the Light page).
  function fmtThousands(n) {
    return String(Math.floor(n)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  // The S105 M7 freshness age as one helper (spec s4.5 I6): floor, clamped at
  // 0 (a future ts is clock skew), `N s ago` with a space, capped at `999+`.
  // Null when there is no age -- an undated reading shows no age. The Motion
  // UPDATED cell and the DATA detail's feeds both read it.
  function freshAgeText(ageSec) {
    if (typeof ageSec !== "number" || isNaN(ageSec)) return null;
    var shown = Math.max(0, Math.floor(ageSec));
    return (shown > MOTION_AGE_CAP_SEC ? MOTION_AGE_CAP_SEC + "+" : String(shown)) + " s ago";
  }

  function healthCell(value, tone, sub) {
    return { value: value, tone: tone, sub: sub === undefined ? null : sub };
  }

  // Floor for the shown number, clamped at 0 (a future ts reads '0 s ago');
  // the stale DECISION keeps the raw float, strict age > imuSec. An undated
  // payload has no age to show (Iris M7).
  function motionUpdatedCell(data, nowMs, staleSec) {
    var age = readAgeSec(data, nowMs);
    if (age === null) return healthCell("--", "none", MOTION_NO_TIMESTAMP_TEXT);
    return healthCell(freshAgeText(age), age > staleSec ? "warn" : "plain");
  }

  // Only a boolean is a verdict. Absent: the provider's own reason when it
  // publishes one, else 'not published' -- never 'not calibrated' (Atlas C1).
  function motionCompassCell(data) {
    if (data.headingCalibrated === true) return healthCell("calibrated", "ok");
    if (data.headingCalibrated === false) return healthCell("not calibrated", "warn");
    var reasons = isObj(data.reasons) ? data.reasons : {};
    return healthCell(
      "--", "none",
      typeof reasons.headingCalibrated === "string" && reasons.headingCalibrated
        ? imuReason(data, "headingCalibrated")
        : CALIBRATION_ABSENT_TEXT
    );
  }

  // The mount-tilt bias in degrees, 2 decimals, signed from the ROUNDED value,
  // with its provenance 'from N stops' (Iris M2/M6). A measurement, never
  // coloured.
  function motionTiltCell(data) {
    var n = data.stopCount;
    if (n === 0) return healthCell("--", "none", MOTION_NO_STOPS_TEXT);
    if (!isNum(n) || n < 0 || !isNum(data.biasRad)) {
      return healthCell("--", "none", MOTION_TILT_ABSENT_TEXT);
    }
    return healthCell(
      fmtSignedFixed(data.biasRad * 180 / Math.PI, 2) + "°", "plain",
      "from " + fmtThousands(n) + (n === 1 ? " stop" : " stops")
    );
  }

  // Atlas C2: 'plausible' ONLY when the guard ran and passed -- a published
  // finite pitch. A dead or unseeded IMU is '--' + its reason, never green.
  function motionGyroCell(data) {
    var reasons = isObj(data.reasons) ? data.reasons : {};
    if (reasons.pitchDeg === REASON_GYRO_IMPLAUSIBLE) return healthCell("implausible", "warn");
    if (isNum(data.pitchDeg)) return healthCell("plausible", "ok");
    return healthCell("--", "none", imuReason(data, "pitchDeg"));
  }

  function motionHealthView(data, nowMs, staleSec) {
    if (!isObj(data)) {
      var none = healthCell("--", "none", MOTION_NO_FEED_TEXT);
      return { updated: none, compass: none, tilt: none, gyro: none };
    }
    return {
      updated: motionUpdatedCell(data, nowMs, staleSec),
      compass: motionCompassCell(data),
      tilt: motionTiltCell(data),
      gyro: motionGyroCell(data),
    };
  }

  // The whole top of the Motion card. `waitedMs` is the US-700 wait for a
  // feed that has never answered: inside the bound the card reads LOADING
  // (Atlas Q-1), after it '--' + reason. Stale is the ONE IMU key shared with
  // NAV (resolveImuStaleSec), strict age > imuSec; an undated payload is stale
  // too (Iris M4). Stale dims the values; it never blanks them.
  function motionView(data, nowMs, staleSec, waitedMs) {
    if (loadPhase(data, waitedMs) === "loading") {
      return { loading: true, tile: loadingTile("MOTION"), stale: false };
    }
    var peaks = isObj(data) && isObj(data.peaks) ? data.peaks : {};
    var age = isObj(data) ? readAgeSec(data, nowMs) : null;
    return {
      loading: false,
      tile: null,
      stale: isObj(data) && (age === null || age > staleSec),
      pitch: motionPitchView(data),
      lon: motionGCell(
        data, "gLon", "ACCEL", "BRAKE", MOTION_LON_NONE_LABEL,
        "peak ▲" + fmtPeak(peaks.accelG) + " ▼" + fmtPeak(peaks.brakeG)
      ),
      lat: motionGCell(
        data, "gLat", "CORNER R", "CORNER L", MOTION_LAT_NONE_LABEL,
        "peak L" + fmtPeak(peaks.leftG) + " R" + fmtPeak(peaks.rightG)
      ),
      health: motionHealthView(data, nowMs, staleSec),
    };
  }

  // The 15-minute grade graph from states/grade-history alone. Points are on
  // the provider's grid, oldest first, newest at the right edge; a slot the
  // window has not filled yet is empty space on the left. A null point ENDS a
  // segment and the next real point starts a new one -- never a line drawn
  // across a gap (Iris M3). Line, end dot and end label share ONE scale, and
  // the label is the last non-null point.
  function motionGradeGraph(history) {
    var pts = isObj(history) && Array.isArray(history.points) ? history.points : [];
    var maxAbs = null;
    for (var i = 0; i < pts.length; i++) {
      var v = isObj(pts[i]) ? pts[i].gradePct : null;
      if (isNum(v)) maxAbs = Math.max(maxAbs === null ? 0 : maxAbs, Math.abs(v));
    }
    var midY = MOTION_GRAPH_H / 2;
    if (maxAbs === null) {
      return { empty: true, text: MOTION_NO_GRADE_HISTORY, zeroY: midY, segments: [], end: null };
    }
    var range = Math.max(
      MOTION_GRAPH_MIN_RANGE_PCT,
      Math.ceil(maxAbs / MOTION_GRAPH_RANGE_STEP_PCT) * MOTION_GRAPH_RANGE_STEP_PCT
    );
    var inner = MOTION_GRAPH_H - 2 * MOTION_GRAPH_PAD;
    function y(pct) {
      return MOTION_GRAPH_PAD + inner * (1 - (pct + range) / (2 * range));
    }
    var slots = isNum(history.windowS) && isNum(history.intervalS) && history.intervalS > 0
      ? Math.floor(history.windowS / history.intervalS) : pts.length;
    if (slots < pts.length) slots = pts.length;
    function x(idx) {
      if (slots <= 1) return MOTION_GRAPH_PLOT_W;
      return MOTION_GRAPH_PLOT_W * (slots - pts.length + idx) / (slots - 1);
    }
    var segments = [];
    var current = [];
    var end = null;
    for (var j = 0; j < pts.length; j++) {
      var g = isObj(pts[j]) ? pts[j].gradePct : null;
      if (!isNum(g)) {
        if (current.length) segments.push(current.join(" "));
        current = [];
        continue;
      }
      var px = Number(x(j).toFixed(1));
      var py = Number(y(g).toFixed(1));
      current.push(px + "," + py);
      end = { x: px, y: py, pct: g };
    }
    if (current.length) segments.push(current.join(" "));
    return {
      empty: false,
      text: null,
      zeroY: Number(y(0).toFixed(1)),
      rangePct: range,
      segments: segments,
      end: {
        x: end.x, y: end.y,
        labelX: MOTION_GRAPH_PLOT_W + MOTION_GRAPH_LABEL_DX,
        labelY: Number((end.y + MOTION_GRAPH_LABEL_DY).toFixed(1)),
        label: fmtSignedFixed(end.pct, 1) + "%",
      },
    };
  }

  // US-508: the GEAR glyph. Gear is NOT an IMU fact -- Atlas ruled it out of
  // states/imu explicitly, because it is Spool's OBD derivation from a SEPARATE
  // producer (F5M33 ratios + tyre circumference, debounced; validated against
  // drive 30). THAT PRODUCER DOES NOT EXIST YET, so this glyph follows the
  // ALTITUDE precedent Atlas already ruled for this same card: the field stays
  // in the contract so a real producer is zero-rework, and it resolves to an
  // honest typed-NA until one lands. It is never zeroed, never guessed, and the
  // reason is on the card so "no producer" is distinguishable from "ambiguous
  // right now" -- two different facts, exactly like gated vs no-data (US-507).
  //
  // Spool's semantics when a producer does land: "--" when ambiguous (speed
  // < 5 km/h, rpm < 900, ratio > 15% off the nearest gear), "N" rolling neutral,
  // >= 2 s debounce. NEVER a wrong number.
  var GEAR_UNKNOWN = "--";

  // US-687-a: the producer's reasons are MACHINE vocabulary. `below_threshold`
  // is a fine token in states/gear and in a test; it is not a phrase anyone
  // parses on a 3.5in panel at a glance, and it was what the tile showed at
  // every stoplight. THIS IS THE ONE PLACE they become driver English -- the
  // snake_case token keeps travelling in the state file unchanged, so nothing
  // downstream loses the exact reason.
  //
  // Nothing here is INVENTED: each phrase says only what its token says.
  // `no_band_match` becomes "no gear match" rather than "clutch in", because
  // clutch-in, coasting and mid-shift all land on that token and the producer
  // cannot tell them apart.
  var GEAR_REASON_TEXT = {
    engaged: "engaged",
    neutral: "neutral",
    park: "parked",
    no_data: "no reading",
    stale: "reading stale",
    not_calibrated: "not calibrated",
    below_threshold: "too slow to tell",
    no_band_match: "no gear match",
    ambiguous: "ambiguous",
    settling: "settling",
    // US-739, PM-ruled operator wording (not the developer's). Both are
    // EXPLICIT entries rather than left to the underscore fallback below:
    // "link down" / "settling park" would be the machine tokens with the
    // underscore taken out, and the fallback renders them underscore-free, so
    // the existing sweep would have passed while the driver read vocabulary
    // nobody chose. Both sit inside the <=16-character envelope the strings
    // above establish ("too slow to tell" is the longest, at 16).
    link_down: "no link",
    settling_park: "confirming park",
    // US-511-a: fresh RPM 0 while SPEED says the car is still moving -- a
    // stall while rolling, which used to read P. Iris's wording (UIDEV-012 I2,
    // system spec 4.7.2). Explicit because the fallback would render
    // "engine off rolling", 18 characters, past the 16-character envelope.
    engine_off_rolling: "engine off"
  };

  function gearReasonText(reason) {
    if (typeof reason !== "string" || !reason) return "no source";
    if (Object.prototype.hasOwnProperty.call(GEAR_REASON_TEXT, reason)) {
      return GEAR_REASON_TEXT[reason];
    }
    // A reason this renderer has never heard of must still not reach the driver
    // as raw machine vocabulary. A producer that grows a new token degrades to
    // readable words rather than to snake_case -- so the sweep holds for
    // reasons that do not exist yet, which is the only way it stays true.
    return reason.replace(/_/g, " ");
  }

  function gearView(gearData) {
    var reason = isObj(gearData) && typeof gearData.reason === "string" && gearData.reason
      ? gearReasonText(gearData.reason)
      : "no source";
    if (!isObj(gearData) || gearData.available !== true) {
      return {
        label: "GEAR", value: GEAR_UNKNOWN, detail: reason,
        level: "unavailable", available: false,
      };
    }
    var gear = gearData.gear;
    if (gear === "N") {
      return {
        label: "GEAR", value: "N", detail: "neutral",
        level: "neutral", available: true,
      };
    }
    // US-687-b. Unlike "N" -- which this function has handled since US-508 and
    // no producer emitted for a month -- "P" was handled NOWHERE, so a producer
    // emitting it fell through to the `--` below and the panel changed nothing.
    // The producer half and this branch therefore ship together.
    //
    // "parked" is what the driver reads, not what P PROVES. The producer emits
    // P when the OBD link is healthy and RPM has been unusable past the park
    // dwell -- so it means "the link is up and the engine is not reporting a
    // speed". This car is a manual with no Park detent and no PRNDL; the glyph
    // is the operator's word for switched-off, ruled by the CIO on the record
    // and sound only while gear stays display-only (US-693 enforces that).
    if (gear === "P") {
      return {
        label: "GEAR", value: "P", detail: "parked",
        level: "neutral", available: true,
      };
    }
    if (typeof gear === "number" && isFinite(gear) && gear > 0) {
      return {
        label: "GEAR", value: String(Math.round(gear)), detail: "engaged",
        level: "neutral", available: true,
      };
    }
    // Present but unresolved -- Spool's ambiguous case. Same glyph as no-source,
    // a different reason: the operator can tell a missing producer from a
    // producer that is honestly refusing to guess.
    return {
      label: "GEAR", value: GEAR_UNKNOWN, detail: reason,
      level: "unavailable", available: false,
    };
  }

  // --- US-888-a Driving card (F-140; specs/v030-driving-page-design.md) -----
  //
  // THE display-units helper -- the one place this page converts anything
  // (Atlas G1). It converts by the unit the PROVIDER published, never by an
  // assumption about the PID: 'C' -> deg F and 'km/h' -> mph (D-3, D-13); a
  // value already in the target unit passes through; an unknown or missing unit
  // renders the raw value with its own unit string. Assuming "temps are C" would
  // silently double-convert the day a provider or a replay emits 'F'. Display
  // only: bands are judged by the provider in the source unit and are never
  // re-judged here, so a rounding edge cannot flip a colour.
  var KM_PER_MILE = 1.609344;
  var DISPLAY_UNITS = {
    C: { unit: "°F", decimals: 0, convert: function (c) { return c * 9 / 5 + 32; } },
    F: { unit: "°F", decimals: 0, convert: null },
    "km/h": { unit: "mph", decimals: 0, convert: function (kmh) { return kmh / KM_PER_MILE; } },
    mph: { unit: "mph", decimals: 0, convert: null },
    // Volts keep one decimal so 14.0 -> 14.1 does not change the width.
    V: { unit: "V", decimals: 1, convert: null },
    // The RPM label already names the unit; "rpm" beside four digits would
    // not fit the 120 px column.
    rpm: { unit: "", decimals: 0, convert: null },
    // US-889-b: ONLY canonical keys (Atlas G1) -- what obd-live publishes after
    // US-888-b. The OBD library's unit names never reach this table (grep gate,
    // tests/ui/test_engine_page.py). Degrees print the glyph, never letters.
    "%": { unit: "%", decimals: 0, convert: null },
    deg: { unit: "°", decimals: 0, convert: null },
    "g/s": { unit: "g/s", decimals: 1, convert: null },
    count: { unit: "", decimals: 0, convert: null },
  };

  // US-897-d (Atlas RULED 2026-10-20): an optional `round` -- 'floor' or 'ceil',
  // the provider's direction TOWARD the breach -- applied as the FINAL step,
  // after convert, at the rule's decimals, so a converted unit can never round
  // back to the safe side. Any other value (null, absent) is toFixed, unchanged.
  // The provider publishes the raw reading; only this step rounds it.
  var ROUND_DIRECTIONS = { floor: Math.floor, ceil: Math.ceil };
  // Below this distance from a whole step the scaled value IS that step: a value
  // that arrives as 0.30000000000000004 (0.1 + 0.2) scales to 3.0000000000000004,
  // and a bare Math.ceil would show 0.4 (the trap the S107 _towardBreach
  // docstring named). Far under any real 1-dp difference (0.1 scales to 1) and
  // far over float error at these magnitudes.
  var ROUND_STEP_EPSILON = 1e-9;

  function roundToward(x, decimals, round) {
    var scale = Math.pow(10, decimals);
    var scaled = x * scale;
    var nearest = Math.round(scaled);
    var step = Math.abs(scaled - nearest) < ROUND_STEP_EPSILON ? nearest : round(scaled);
    return (step / scale).toFixed(decimals);
  }

  function displayUnits(value, unit, round) {
    var rule = typeof unit === "string" &&
      Object.prototype.hasOwnProperty.call(DISPLAY_UNITS, unit) ? DISPLAY_UNITS[unit] : null;
    if (!rule) {
      return { text: String(value), unit: typeof unit === "string" ? unit : "" };
    }
    var shown = rule.convert ? rule.convert(value) : value;
    var direction = typeof round === "string" &&
      Object.prototype.hasOwnProperty.call(ROUND_DIRECTIONS, round) ? ROUND_DIRECTIONS[round] : null;
    if (direction) {
      return { text: roundToward(shown, rule.decimals, direction), unit: rule.unit };
    }
    return { text: shown.toFixed(rule.decimals), unit: rule.unit };
  }

  // The readings layout B shows, by obd-live PID (spec s5; Atlas verified every
  // key on dev). Where each one sits is markup (`data-pid`), not this list.
  var DRIVING_PIDS = ["COOLANT_TEMP", "INTAKE_TEMP", "SPEED", "RPM", "BATTERY_V"];
  // Not read: the same glyph the gear uses, so "--" means one thing on the page.
  var DRIVING_NOT_READ = GEAR_UNKNOWN;

  // The provider's band name, or null. Only the three state names exist; any
  // other value is not a band this page may paint.
  function drivingBand(band) {
    if (!isObj(band)) return null;
    return band.band === "green" || band.band === "amber" || band.band === "red"
      ? band.band : null;
  }

  // A provider reason code as the glass prints it ("not_read" -> "not read").
  function drivingReasonText(code) {
    return typeof code === "string" && code ? code.replace(/_/g, " ") : "not read";
  }

  // "<n> s" since the reading's own ts -- clock arithmetic, not a threshold:
  // the PROVIDER decided it is stale (pi.display.stale.obdLiveSec).
  function drivingAgeText(ts, nowMs) {
    var t = typeof ts === "string" ? Date.parse(ts) : NaN;
    if (isNaN(t)) return "stale";
    return Math.max(0, Math.round((nowMs - t) / 1000)) + " s";
  }

  function drivingNotRead(reason) {
    return { text: DRIVING_NOT_READ, unit: "", band: null, stale: false, note: reason, noteKind: "reason" };
  }

  // One obd-live param -> what its slot paints (spec s4.3/s4.4):
  //   fresh value  -> converted value, provider band, no note (an unbanded value
  //                   is neutral with NO reason text -- no_band_defined and
  //                   amber_not_shipped are by design, not faults; Iris G-1/G-2);
  //   stale        -> last.value converted the same way, coloured by last.band,
  //                   dimmed, with its age -- never "--" while a number exists;
  //   not read     -> "--" + the provider's reason. Never 0, never a stale value.
  function drivingReading(param, nowMs) {
    if (!isObj(param)) return drivingNotRead("not read");
    if (param.stale === true) {
      var last = isObj(param.last) ? param.last : null;
      if (!last || typeof last.value !== "number" || !isFinite(last.value)) {
        return drivingNotRead(drivingReasonText(param.noBandReason));
      }
      var old = displayUnits(last.value, param.unit);
      return {
        text: old.text, unit: old.unit, band: drivingBand(last.band), stale: true,
        note: drivingAgeText(param.ts, nowMs), noteKind: "age",
      };
    }
    if (typeof param.value !== "number" || !isFinite(param.value)) {
      return drivingNotRead(drivingReasonText(param.noBandReason));
    }
    var shown = displayUnits(param.value, param.unit);
    return {
      text: shown.text, unit: shown.unit, band: drivingBand(param.band), stale: false,
      note: "", noteKind: "",
    };
  }

  // The Driving card's whole view from the two states it reads: states/obd-live
  // and states/gear (the ONE gear fetch the tick already makes). The page
  // computes no value and no band. The gear is gearView's glyph; between gears
  // it is "--" with no hint and no reason line (spec s4.2; the hint is US-904).
  function drivingView(obdLiveData, gearData, nowMs) {
    var params = isObj(obdLiveData) && isObj(obdLiveData.params) ? obdLiveData.params : null;
    var readings = {};
    for (var i = 0; i < DRIVING_PIDS.length; i++) {
      var pid = DRIVING_PIDS[i];
      readings[pid] = params ? drivingReading(params[pid], nowMs) : drivingNotRead("no source");
    }
    var gear = gearView(gearData);
    return {
      gear: { text: gear.value, measured: gear.available },
      readings: readings,
      // US-888-b: the stepped bar, from the same params.RPM as the number.
      rpmBar: rpmBarView(params ? params.RPM : null),
    };
  }

  // --- US-889-b Engine card, above the fold (F-127) -------------------------
  //
  // specs/v030-engine-page-design.md s3-s4: load, throttle and timing from
  // states/obd-live, each stepping at its own sample. The page judges nothing:
  // no value here carries a band (load at 100 % is expected on this turbo
  // engine and stays neutral -- a compound danger belongs to a provider).
  var ENGINE_PIDS = ["ENGINE_LOAD", "THROTTLE_POS", "TIMING_ADVANCE"];
  // The two vertical bars and their scale: 0-100 % of the bar's height. A
  // geometry bound, not a threshold -- it paints no colour.
  var ENGINE_BAR_PIDS = ["ENGINE_LOAD", "THROTTLE_POS"];
  var ENGINE_BAR_MAX_PCT = 100;

  function engineNotRead(reason) {
    return {
      value: null, text: DRIVING_NOT_READ, unit: "", stale: false,
      note: reason, noteKind: "reason",
    };
  }

  // SAE J1979 PID 0x0E is degrees relative to TDC, negative = retarded (Iris
  // G-2): >= 0 reads "n° BTDC", < 0 reads "|n|° ATDC" -- never "-4° BTDC". Only
  // a 'deg' reading may claim a crank position; any other unit renders raw.
  function engineTimingText(value, unit) {
    if (unit !== "deg") return displayUnits(value, unit);
    var shown = displayUnits(Math.abs(value), unit);
    return { text: shown.text, unit: shown.unit + (value < 0 ? " ATDC" : " BTDC") };
  }

  // One obd-live param -> its slot, the drivingReading rules without a band:
  // fresh -> the value; stale -> last.value with its age (dimmed by the sheet);
  // not read / absent -> "--" + the provider's reason. `value` is the number
  // shown, so the bar is drawn from the SAME sample as the digits.
  function engineReading(param, nowMs, format) {
    if (!isObj(param)) return engineNotRead("not read");
    var stale = param.stale === true;
    var source = stale ? (isObj(param.last) ? param.last.value : null) : param.value;
    if (typeof source !== "number" || !isFinite(source)) {
      return engineNotRead(drivingReasonText(param.noBandReason));
    }
    var shown = format(source, param.unit);
    return {
      value: source, text: shown.text, unit: shown.unit, stale: stale,
      note: stale ? drivingAgeText(param.ts, nowMs) : "",
      noteKind: stale ? "age" : "",
    };
  }

  // A bar's fill in % of its height, or null (nothing lit). Only a '%' reading
  // can fill a 0-100 % bar; clamped so a value past the scale pins the bar
  // rather than overflowing the card.
  function engineBar(reading, unit) {
    var fill = reading.value === null || unit !== "%" ? null
      : Math.max(0, Math.min(ENGINE_BAR_MAX_PCT, reading.value));
    return { fill: fill, stale: fill !== null && reading.stale };
  }

  // The Engine card's above-the-fold view from states/obd-live alone.
  function engineView(obdLiveData, nowMs) {
    var params = isObj(obdLiveData) && isObj(obdLiveData.params) ? obdLiveData.params : null;
    var readings = {};
    for (var i = 0; i < ENGINE_PIDS.length; i++) {
      var pid = ENGINE_PIDS[i];
      var format = pid === "TIMING_ADVANCE" ? engineTimingText : displayUnits;
      readings[pid] = params ? engineReading(params[pid], nowMs, format)
        : engineNotRead("no source");
    }
    var bars = {};
    for (var b = 0; b < ENGINE_BAR_PIDS.length; b++) {
      var barPid = ENGINE_BAR_PIDS[b];
      var param = params && isObj(params[barPid]) ? params[barPid] : null;
      bars[barPid] = engineBar(readings[barPid], param ? param.unit : null);
    }
    return { readings: readings, bars: bars };
  }

  // --- US-890-b Fuel card, airflow (F-127) -----------------------------------
  //
  // specs/v030-fuel-page-design.md s4.1 (Atlas S104 ruling 2): params.MAF at
  // --fs-hero, one decimal (displayUnits 'g/s'), over a bar from 0 to
  // params.MAF.scale.max -- the PROVIDER's max (pi.display.scale.mafMaxGs); the
  // page holds no number. Above the max the bar pins exactly full and the
  // digits stay unclamped: a full bar says "at least the scale max", never "the
  // sensor hit its limit" (nobody knows where it clips). Unbanded, so nothing
  // on the airflow element is ever amber or red. Fresh / stale / not read follow
  // engineReading: the bar draws the SAME sample as the digits.
  var FUEL_AIRFLOW_PID = "MAF";
  // The unit the scale max is published in; a reading in any other unit is not
  // on that scale and lights no bar.
  var FUEL_AIRFLOW_UNIT = "g/s";
  var FUEL_BAR_FULL_PCT = 100;

  // The bar's fill in % of its width, or null (no usable scale: nothing lit).
  function fuelAirflowFill(reading, param) {
    var max = isObj(param.scale) ? param.scale.max : null;
    if (reading.value === null || param.unit !== FUEL_AIRFLOW_UNIT ||
        typeof max !== "number" || !isFinite(max) || max <= 0) {
      return null;
    }
    return Math.max(0, Math.min(FUEL_BAR_FULL_PCT, reading.value / max * FUEL_BAR_FULL_PCT));
  }

  // The Fuel card's airflow view from states/obd-live alone.
  function fuelAirflowView(obdLiveData, nowMs) {
    var params = isObj(obdLiveData) && isObj(obdLiveData.params) ? obdLiveData.params : null;
    if (!params) return { reading: engineNotRead("no source"), bar: { fill: null, stale: false } };
    var param = params[FUEL_AIRFLOW_PID];
    var reading = engineReading(param, nowMs, displayUnits);
    var fill = isObj(param) ? fuelAirflowFill(reading, param) : null;
    return { reading: reading, bar: { fill: fill, stale: fill !== null && reading.stale } };
  }

  // --- US-890-c Fuel card, loop chip + total trim (F-127) -------------------
  //
  // specs/v030-fuel-page-design.md s4.2 (Atlas S104 total-trim ruling (b)): both
  // read ONLY states/obd-live `fuel` -- the provider decides which status codes
  // are closed loop and sums the trims, so the page holds no code set and does
  // no trim arithmetic. The chip is outlined and never coloured (open loop is
  // normal at cold start and full throttle); TOTAL TRIM is unbanded and neutral.
  var FUEL_LOOP_TEXT = { closed: "CLOSED LOOP", open: "OPEN LOOP" };
  var FUEL_LOOP_UNKNOWN = "loop unknown";
  // totalTrimNow.reason -> its text. open_loop keeps Iris's wording; stale has
  // no age and no last value (Iris G-7: a stale sum of two samples is not a
  // reading). Any other code shows raw, never blank.
  var FUEL_TRIM_REASON_TEXT = {
    not_read: "not read",
    stale: "stale",
    loop_unknown: FUEL_LOOP_UNKNOWN,
    open_loop: "not applied in open loop",
  };
  // The one reason whose "--" is dimmed: trims exist but are not being applied.
  var FUEL_TRIM_DIMMED_REASON = "open_loop";

  function fuelSideNote(text, note) {
    return { text: text, note: note, noteKind: note ? "reason" : "", dimmed: false };
  }

  // obd-live -> its `fuel` block, or a reason it has none.
  function fuelBlockOf(obdLiveData) {
    if (!isObj(obdLiveData)) return { fuel: null, missing: "no source" };
    if (!isObj(obdLiveData.fuel)) return { fuel: null, missing: "not published" };
    return { fuel: obdLiveData.fuel, missing: "" };
  }

  // The loop chip: CLOSED LOOP / OPEN LOOP, else "--" + why.
  function fuelLoopView(obdLiveData) {
    var block = fuelBlockOf(obdLiveData);
    if (!block.fuel) return fuelSideNote("--", block.missing);
    var text = Object.prototype.hasOwnProperty.call(FUEL_LOOP_TEXT, block.fuel.loop)
      ? FUEL_LOOP_TEXT[block.fuel.loop] : null;
    return text ? fuelSideNote(text, "") : fuelSideNote("--", FUEL_LOOP_UNKNOWN);
  }

  // Signed, ONE decimal, "%" (spec s3), from toFixed(1) -- never String(float),
  // never displayUnits. The sign follows the ROUNDED figure, so -0.04 reads
  // "+0.0 %", not "−0.0 %".
  function fmtTotalTrim(value) {
    var shown = Math.abs(value).toFixed(1);
    return (value < 0 && Number(shown) !== 0 ? "−" : "+") + shown + " %";
  }

  // TOTAL TRIM: the provider's totalTrimNow, else "--" + its reason's text.
  function fuelTotalTrimView(obdLiveData) {
    var block = fuelBlockOf(obdLiveData);
    var trim = block.fuel && isObj(block.fuel.totalTrimNow) ? block.fuel.totalTrimNow : null;
    if (!trim) return fuelSideNote("--", block.missing || "not published");
    if (trim.reason === null && typeof trim.value === "number" && isFinite(trim.value)) {
      return fuelSideNote(fmtTotalTrim(trim.value), "");
    }
    var reason = typeof trim.reason === "string" && trim.reason ? trim.reason : "not_read";
    var view = fuelSideNote("--", Object.prototype.hasOwnProperty.call(FUEL_TRIM_REASON_TEXT, reason)
      ? FUEL_TRIM_REASON_TEXT[reason] : reason);
    view.dimmed = reason === FUEL_TRIM_DIMMED_REASON;
    return view;
  }

  // --- US-890-d Fuel card, the MPG row (F-127) -------------------------------
  //
  // specs/v030-fuel-page-design.md s4.3/s4.6: THIS DRIVE and SINCE RESET read
  // states/fuel-economy ONLY -- the provider integrates distance and fuel and
  // divides; the page never touches MAF or speed. Every figure carries the
  // approximately sign (the estimate assumes stoichiometric burn); THIS DRIVE
  // and SINCE RESET show ONE decimal (spec s3 mockup). LAST 30 S (US-890-e)
  // reads fuel-economy.recent, the provider's ratio of sums over its window.
  var FUEL_MPG_APPROX = "≈";
  // s4.6: the ONE code -> text table for the MPG row. Every text is <= 16
  // characters (the row's fit rule); a code not in it shows raw, never blank.
  var FUEL_MPG_REASON_TEXT = {
    maf_untrusted: "MAF not fitted",
    maf_stale: "no MAF reading",
    maf_zero_running: "MAF reads zero",
    gaps: "too many gaps",
    too_short: "too short yet",
    no_fuel: "no fuel counted",
    too_few_samples: "too few samples",
  };
  var FUEL_MPG_NOT_STARTED = "not started";
  var FUEL_MPG_NEVER_RESET = "never reset";
  // sinceReset carries no reason field: a null mpg there is "too short yet",
  // and the page does not guess between the provider's other causes (s4.3).
  var FUEL_MPG_SINCE_RESET_NULL = "too_short";
  // thisDrive.mpg null with no code at all -- still a reason, never blank.
  var FUEL_MPG_NO_CODE = "no reason sent";
  // thisDrive.approximate (open-loop air over the provider's threshold). Open
  // loop is BOTH enrichment and decel fuel-cut, so the flag says only that --
  // never which way the estimate leans.
  var FUEL_MPG_OPEN_LOOP_FLAG = "open loop";
  // LAST 30 S is an integer and reads "99+" at >= 99 -- Spool's display rule
  // (pm/inbox 2026-10-14-from-spool-S104-...-MPG-last-30s-ratio-of-sums-null-
  // rules.md s2): decel coasts give big numbers, true direction, false
  // precision. No approximately sign: the label already says "last 30 s".
  var FUEL_MPG_LAST30_CAP = 99;
  var FUEL_MPG_LAST30_CAP_TEXT = "99+";
  // US-922: the unit after every MPG figure, painted into .fuel-unit as the
  // airflow's g/s (fuel spec s4.3, CIO 2026-10-22: "just text"). A figure is
  // noteKind "none"; every "--" (a reason, "not published", "resetting…")
  // carries no unit -- its note already says why there is no number.
  var FUEL_MPG_UNIT = "MPG";

  function fuelMpgSlot(text, note, noteKind) {
    var unit = noteKind === "none" ? FUEL_MPG_UNIT : "";
    return { text: text, note: note, noteKind: noteKind, flag: "", unit: unit };
  }

  function fuelMpgReasonText(code) {
    if (typeof code !== "string" || !code) return FUEL_MPG_NO_CODE;
    return Object.prototype.hasOwnProperty.call(FUEL_MPG_REASON_TEXT, code)
      ? FUEL_MPG_REASON_TEXT[code] : code;
  }

  // One decimal from toFixed(1), never String(float); null when not a figure.
  function fmtFuelMpg(mpg) {
    if (typeof mpg !== "number" || !isFinite(mpg)) return null;
    return FUEL_MPG_APPROX + mpg.toFixed(1);
  }

  // One MPG block (thisDrive / sinceReset) -> its slot. `absentNote` is what a
  // null block means; `nullCode` is the reason code for a null mpg.
  function fuelMpgBlockSlot(block, absentNote, nullCode) {
    if (block === null) return fuelMpgSlot("--", absentNote, "reason");
    if (!isObj(block)) return fuelMpgSlot("--", "not published", "unpublished");
    var figure = fmtFuelMpg(block.mpg);
    if (figure !== null) return fuelMpgSlot(figure, "", "none");
    return fuelMpgSlot("--", fuelMpgReasonText(nullCode), "reason");
  }

  // LAST 30 S from fuel-economy.recent: absent -> a provider without the
  // field; null -> no drive window yet (Iris G-5); a null mpg -> its reason.
  function fuelMpgLast30Slot(fuelEconomyData) {
    if (!Object.prototype.hasOwnProperty.call(fuelEconomyData, "recent")) {
      return fuelMpgSlot("--", "not published", "unpublished");
    }
    var recent = fuelEconomyData.recent;
    if (recent === null) return fuelMpgSlot("--", FUEL_MPG_NOT_STARTED, "reason");
    if (!isObj(recent)) return fuelMpgSlot("--", "not published", "unpublished");
    var mpg = recent.mpg;
    if (typeof mpg === "number" && isFinite(mpg)) {
      var text = mpg >= FUEL_MPG_LAST30_CAP
        ? FUEL_MPG_LAST30_CAP_TEXT : String(Math.round(mpg));
      return fuelMpgSlot(text, "", "none");
    }
    return fuelMpgSlot("--", fuelMpgReasonText(recent.mpgNullReason), "reason");
  }

  // The MPG row's view from states/fuel-economy alone.
  function fuelMpgView(fuelEconomyData) {
    if (!isObj(fuelEconomyData)) {
      return {
        last30: fuelMpgSlot("--", "not published", "unpublished"),
        thisDrive: fuelMpgSlot("--", "no source", "reason"),
        sinceReset: fuelMpgSlot("--", "no source", "reason"),
      };
    }
    var last30 = fuelMpgLast30Slot(fuelEconomyData);
    var drive = fuelEconomyData.thisDrive;
    var thisDrive = fuelMpgBlockSlot(
      drive, FUEL_MPG_NOT_STARTED, isObj(drive) ? drive.mpgNullReason : null
    );
    // The flag sits with a figure: a "--" already says why there is none.
    if (thisDrive.noteKind === "none" && drive.approximate === true) {
      thisDrive.flag = FUEL_MPG_OPEN_LOOP_FLAG;
    }
    var sinceReset = fuelMpgBlockSlot(
      fuelEconomyData.sinceReset, FUEL_MPG_NEVER_RESET, FUEL_MPG_SINCE_RESET_NULL
    );
    return { last30: last30, thisDrive: thisDrive, sinceReset: sinceReset };
  }

  // --- US-890-f the SINCE RESET reset (F-127, spec s4.3) ---------------------
  //
  // US-923: offered only while the PROVIDER's gate says so --
  // states/fuel-economy.resetAllowed.value === true (orchestrator
  // fuel_reset_gate, re-checked when the POST lands). The page computes no gate
  // of its own. Then: hold SINCE RESET ~2 s, confirm "Reset average MPG?", then a
  // token-gated POST /fuel-reset, then show the RE-READ stored value (F-126
  // honest write, never optimistic). The page never caches an "old value": the
  // slot always renders the LATEST states/fuel-economy read plus an outcome
  // line. The ONE time it masks the provider is "resetting…", from Yes until a
  // read whose sinceReset.resetAtTs equals the 200's resetAtTs, bounded by
  // pi.display.stale.fuelResetConfirmSec counted from the 200 (Atlas Q4/G3).
  //
  // Hold time: CIO F-6, "long-press the tile (~2 s)" (fuel spec s2).
  var FUEL_RESET_HOLD_MS = 2000;
  // Every outcome text is <= 16 characters, the MPG row's fit rule (s4.6).
  var FUEL_RESET_HINT = "hold to reset";
  var FUEL_RESET_RESETTING = "resetting…";
  // US-923: the two gate refusals keep the provider's code as their key (fuel
  // spec s4.3/s4.6, Iris UIDEV-012 I4): driving -> "slow to reset" (at 5 mph
  // the reset works, so not "park"/"stop"); speed_unknown -> "speed unknown".
  var FUEL_RESET_OUTCOME_TEXT = {
    driving: "slow to reset",
    speed_unknown: "speed unknown",
    failed: "couldn't reset",
    unconfirmed: "couldn't confirm",
  };
  // The refusals that come from the gate (fuel_reset_gate.resetAllowed's
  // reasons, via core.py _maybeServiceFuelResetRequest); every other 409
  // reason is a failed reset.
  var FUEL_RESET_GATE_REASONS = { driving: true, speed_unknown: true };

  // The gate as published: only a strict true offers the reset. false, null,
  // a missing block or an unreadable file all fail closed (spec s4.3).
  function fuelResetAllowed(fuelEconomyData) {
    var gate = isObj(fuelEconomyData) ? fuelEconomyData.resetAllowed : null;
    return isObj(gate) && gate.value === true;
  }

  // pi.display.stale.fuelResetConfirmSec, injected per request as
  // window.DISPLAY_STALE.fuelResetConfirmSec (the imuSec pattern). There is NO
  // mirrored default here, on purpose (no literal in this file): without a real
  // window "resetting…" would be unbounded, so an absent or invalid injection
  // returns null and the reset is simply not offered (fail closed).
  function resolveFuelResetConfirmSec(injected) {
    var v = isObj(injected) ? injected.fuelResetConfirmSec : null;
    return typeof v === "number" && isFinite(v) && v > 0 ? v : null;
  }

  function fuelSinceResetTs(fuelEconomyData) {
    var block = isObj(fuelEconomyData) ? fuelEconomyData.sinceReset : null;
    return isObj(block) && typeof block.resetAtTs === "string" ? block.resetAtTs : null;
  }

  // phase: idle | confirm | posting (Yes -> the answer) | awaiting (200 -> the
  // matching read). `outcome` is a FUEL_RESET_OUTCOME_TEXT key or null.
  // `baselineTs` is the resetAtTs on the read at Yes -- an identity, not a
  // value: a later read with a different one means a reset landed.
  function fuelResetInit() {
    return { phase: "idle", outcome: null, baselineTs: null, resetAtTs: null, confirmFromMs: null };
  }

  // A POST /fuel-reset answer -> the next state (states_http_server
  // _handleFuelReset: 200, 409, 503, 504, 401). Only a 200 that names its
  // resetAtTs can be confirmed by a read; a 504, a 200 without a stamp and any
  // status the server does not document leave the outcome UNKNOWN.
  function fuelResetAnswer(state, status, body, nowMs) {
    var b = isObj(body) ? body : {};
    if (status === 200 && b.ok === true && typeof b.resetAtTs === "string" && b.resetAtTs) {
      state.phase = "awaiting";
      state.resetAtTs = b.resetAtTs;
      state.confirmFromMs = nowMs;
      return state;
    }
    state.phase = "idle";
    var gateRefusal = status === 409 && typeof b.reason === "string" &&
      Object.prototype.hasOwnProperty.call(FUEL_RESET_GATE_REASONS, b.reason);
    if (gateRefusal) state.outcome = b.reason;
    else if (status === 409 || status === 503 || status === 401) state.outcome = "failed";
    else state.outcome = "unconfirmed";
    return state;
  }

  // Advance the reset by one event. Pure; the clock arrives on the event.
  // `allowed` is fuelResetAllowed(the latest read) -- the provider's gate.
  //   {type: "hold", allowed, confirmSec}     the 2 s hold completed
  //   {type: "no"}                            confirm -> No (changes nothing)
  //   {type: "yes", read}                     confirm -> Yes
  //   {type: "answer", status, body, nowMs}   the POST answered
  //   {type: "failure"}                       the POST never answered
  //   {type: "read", read, allowed, nowMs, confirmSec}   one tick's read
  function fuelResetNext(prev, ev) {
    var s = isObj(prev) && typeof prev.phase === "string" ? {
      phase: prev.phase, outcome: prev.outcome, baselineTs: prev.baselineTs,
      resetAtTs: prev.resetAtTs, confirmFromMs: prev.confirmFromMs,
    } : fuelResetInit();
    var type = isObj(ev) ? ev.type : null;
    if (type === "hold") {
      if (s.phase === "idle" && ev.allowed === true && typeof ev.confirmSec === "number") {
        s.phase = "confirm";
      }
      return s;
    }
    if (type === "no") {
      if (s.phase === "confirm") s.phase = "idle";
      return s;
    }
    if (type === "yes") {
      if (s.phase !== "confirm") return s;
      s.phase = "posting";
      s.outcome = null;
      s.baselineTs = fuelSinceResetTs(ev.read);
      s.resetAtTs = null;
      s.confirmFromMs = null;
      return s;
    }
    if (type === "answer") {
      if (s.phase !== "posting") return s;
      return fuelResetAnswer(s, ev.status, ev.body, ev.nowMs);
    }
    if (type === "failure") {
      // No answer at all: the server may or may not have acted.
      if (s.phase === "posting") {
        s.phase = "idle";
        s.outcome = "unconfirmed";
      }
      return s;
    }
    if (type !== "read") return s;
    var ts = fuelSinceResetTs(ev.read);
    if (s.phase === "confirm" && ev.allowed !== true) {
      // The gate closed under an open confirm (the car sped up): withdraw it.
      s.phase = "idle";
    } else if (s.phase === "awaiting") {
      if (ts !== null && ts === s.resetAtTs) {
        s.phase = "idle";
        s.outcome = null;
      } else if (!(typeof ev.nowMs === "number" && typeof ev.confirmSec === "number" &&
                   ev.nowMs - s.confirmFromMs <= ev.confirmSec * 1000)) {
        // Past the window, or no window to measure against.
        s.phase = "idle";
        s.outcome = "unconfirmed";
      }
    } else if (s.phase === "idle" && s.outcome !== null && ts !== null && ts !== s.baselineTs) {
      // A reset landed after all (a 504 or a late read): the read speaks.
      s.outcome = null;
    }
    return s;
  }

  // The MPG row with the reset applied to SINCE RESET, gated by the same read.
  function fuelMpgResetView(fuelEconomyData, resetState, confirmSec) {
    return fuelResetOverlay(
      fuelMpgView(fuelEconomyData), resetState, fuelResetAllowed(fuelEconomyData), confirmSec
    );
  }

  // Apply the reset to a fuelMpgView. `sinceReset.line` is the slot's outcome /
  // hint line; `reset` says whether the hold is live and the confirm is open.
  // `allowed` is fuelResetAllowed(read): the hint and the hold follow it alone.
  function fuelResetOverlay(view, resetState, allowed, confirmSec) {
    var s = isObj(resetState) && typeof resetState.phase === "string" ? resetState : fuelResetInit();
    var offered = allowed === true && typeof confirmSec === "number";
    var slot = view.sinceReset;
    slot.line = "";
    if (s.phase === "posting" || s.phase === "awaiting") {
      view.sinceReset = fuelMpgSlot("--", FUEL_RESET_RESETTING, "resetting");
      view.sinceReset.line = "";
    } else if (s.outcome !== null &&
               Object.prototype.hasOwnProperty.call(FUEL_RESET_OUTCOME_TEXT, s.outcome)) {
      slot.line = FUEL_RESET_OUTCOME_TEXT[s.outcome];
    } else if (offered) {
      slot.line = FUEL_RESET_HINT;
    }
    view.reset = {
      pressable: offered && s.phase === "idle",
      confirm: offered && s.phase === "confirm",
    };
    return view;
  }

  // --- US-889-c Engine card, the scroll half (F-127) -------------------------
  //
  // specs/v030-engine-page-design.md s3-s4, ACs 5-11: this drive's coolant,
  // intake-air and battery history from states/engine-history, then the RUN
  // TIME / CHECK ENGINE status row from states/obd-live. The history is the
  // provider's: one point per bucket {ts (the bucket's END), value (its last
  // fresh sample), band (the WORST band it held)}. The page plots the value as
  // a neutral stepped line and paints a span ONLY where a point's band is amber
  // or red -- it never compares a value with a number, so a line crossing an
  // edge with no band shows nothing (dwell-as-render-rule, Spool 08-21).
  var ENGINE_HISTORY_SERIES = [
    { pid: "COOLANT_TEMP", label: "COOLANT" },
    { pid: "INTAKE_TEMP", label: "INTAKE AIR" },
    { pid: "BATTERY_V", label: "BATTERY" },
  ];
  var ENGINE_HISTORY_ABSENT =
    "History not recorded yet. It starts with this drive's first readings.";
  // The chart's own coordinate box (viewBox 0 0 100 46) and the 4-unit inset
  // that keeps the line off the top and bottom edges -- the OEM mockup's graph
  // (proposals/2026-10-14-v030-engine-page-oem.html, h 46, inset 4). Geometry,
  // not a scale: the y range is the series' own extent.
  var ENGINE_HISTORY_W = 100;
  var ENGINE_HISTORY_H = 46;
  var ENGINE_HISTORY_INSET = 4;
  var ENGINE_SPAN_BANDS = { amber: true, red: true };

  function engineHistoryPoints(raw) {
    var out = [];
    if (!Array.isArray(raw)) return out;
    for (var i = 0; i < raw.length; i++) {
      var p = raw[i];
      var endMs = isObj(p) && typeof p.ts === "string" ? Date.parse(p.ts) : NaN;
      if (isNaN(endMs) || typeof p.value !== "number" || !isFinite(p.value)) continue;
      out.push({ endMs: endMs, value: p.value, band: ENGINE_SPAN_BANDS[p.band] ? p.band : null });
    }
    return out;
  }

  // The window label from engine-history ALONE (Atlas G3): partial false is
  // the whole drive; partial true names where coverage begins, in the panel's
  // local h:mm. The page compares no other provider's clock, so it never
  // decides for itself when the drive started.
  function engineHistoryWindow(data) {
    if (data.partial === false) return "THIS DRIVE";
    var since = typeof data.sinceTs === "string" && ISO_INSTANT.test(data.sinceTs)
      ? new Date(Date.parse(data.sinceTs)) : null;
    return "SINCE " + (since ? fmtTimeOfDay(since, false).split(" ")[0] : DRIVING_NOT_READ);
  }

  function engineHistoryCoord(n) {
    return Math.round(n * 10) / 10;
  }

  // One series -> its chart. Buckets that touch (this end == the next start)
  // join into one run; an omitted bucket opens a new run, so a gap is a gap and
  // never a bridge. Each run is a stepped line: flat across its bucket, a riser
  // at the boundary, no interpolation.
  function engineHistorySeries(entry, points, unit, x0, x1, intervalMs) {
    if (!points.length) {
      return { pid: entry.pid, label: entry.label, empty: true, segments: [], spans: [], end: null };
    }
    var lo = points[0].value;
    var hi = lo;
    for (var i = 1; i < points.length; i++) {
      lo = Math.min(lo, points[i].value);
      hi = Math.max(hi, points[i].value);
    }
    var span = ENGINE_HISTORY_H - 2 * ENGINE_HISTORY_INSET;
    var xOf = function (ms) {
      return engineHistoryCoord((ms - x0) / (x1 - x0) * ENGINE_HISTORY_W);
    };
    var yOf = function (v) {
      return engineHistoryCoord(hi === lo ? ENGINE_HISTORY_H / 2
        : ENGINE_HISTORY_INSET + (hi - v) / (hi - lo) * span);
    };
    var segments = [];
    var spans = [];
    var run = [];
    for (var j = 0; j < points.length; j++) {
      var p = points[j];
      var startMs = p.endMs - intervalMs;
      if (j > 0 && startMs !== points[j - 1].endMs) {
        segments.push(run.join(" "));
        run = [];
      }
      var y = yOf(p.value);
      run.push(xOf(startMs) + "," + y, xOf(p.endMs) + "," + y);
      if (p.band) {
        spans.push({ x: xOf(startMs), width: engineHistoryCoord(xOf(p.endMs) - xOf(startMs)), band: p.band });
      }
    }
    segments.push(run.join(" "));
    var last = displayUnits(points[points.length - 1].value, unit);
    return {
      pid: entry.pid, label: entry.label, empty: false, segments: segments, spans: spans,
      end: { text: last.text, unit: last.unit },
    };
  }

  // The scroll half's history from states/engine-history alone. `empty` means
  // no series holds a point (or there is no readable history): the card shows
  // the typed absence and NO chart. All three charts share one time axis, the
  // extent of the buckets themselves, so the graphs line up.
  function engineHistoryView(data) {
    var intervalSec = isObj(data) ? data.intervalSec : null;
    var empty = { empty: true, absence: ENGINE_HISTORY_ABSENT, window: "", series: [] };
    if (!isObj(data) || !isObj(data.series) || typeof intervalSec !== "number" ||
        !isFinite(intervalSec) || intervalSec <= 0) {
      return empty;
    }
    var intervalMs = intervalSec * 1000;
    var units = isObj(data.unit) ? data.unit : {};
    var bySeries = [];
    var x0 = Infinity;
    var x1 = -Infinity;
    for (var i = 0; i < ENGINE_HISTORY_SERIES.length; i++) {
      var pts = engineHistoryPoints(data.series[ENGINE_HISTORY_SERIES[i].pid]);
      bySeries.push(pts);
      if (pts.length) {
        x0 = Math.min(x0, pts[0].endMs - intervalMs);
        x1 = Math.max(x1, pts[pts.length - 1].endMs);
      }
    }
    if (x1 === -Infinity) return empty;
    var series = [];
    for (var k = 0; k < ENGINE_HISTORY_SERIES.length; k++) {
      var entry = ENGINE_HISTORY_SERIES[k];
      series.push(engineHistorySeries(entry, bySeries[k], units[entry.pid], x0, x1, intervalMs));
    }
    return { empty: false, absence: ENGINE_HISTORY_ABSENT, window: engineHistoryWindow(data), series: series };
  }

  // RUN TIME as h:mm from params.RUNTIME_SEC -- the ECU's engine run time,
  // NEVER the drive's duration (Atlas G4: two different facts).
  function engineRunTimeText(seconds) {
    var minutes = Math.floor(Math.max(0, seconds) / 60);
    return { text: Math.floor(minutes / 60) + ":" + two(minutes % 60), unit: "" };
  }

  // params.MIL_ON is read by VALUE (1 on, 0 off), never by its unit label.
  var ENGINE_MIL_TEXT = { 0: "OFF", 1: "ON" };

  function engineMilText(value) {
    return { text: ENGINE_MIL_TEXT[value], unit: "" };
  }

  // The status row from states/obd-live. CHECK ENGINE's count line ("n codes
  // ›", "1 code ›", "0 codes ›" for a pending code) exists only while the lamp is ON; it
  // is a tap to the Alerts card ONLY while parked (`parked`, the debounced
  // parkedNext signal) -- moving, the line carries no tap target.
  function engineStatusView(obdLiveData, parked, nowMs) {
    var params = isObj(obdLiveData) && isObj(obdLiveData.params) ? obdLiveData.params : null;
    var runTime = params ? engineReading(params.RUNTIME_SEC, nowMs, engineRunTimeText)
      : engineNotRead("no source");
    var mil = params ? engineReading(params.MIL_ON, nowMs, engineMilText)
      : engineNotRead("no source");
    if (mil.value !== null && !Object.prototype.hasOwnProperty.call(ENGINE_MIL_TEXT, mil.value)) {
      mil = engineNotRead("not read");
    }
    var codes = null;
    if (mil.value === 1) {
      var count = engineReading(params.DTC_COUNT, nowMs, displayUnits);
      var n = count.value === null ? DRIVING_NOT_READ : String(Math.round(count.value));
      // US-909: exactly one reads "1 code ›" (spec v030-engine-page-design.md
      // s3, the most common real MIL case); 0, n and "--" stay plural.
      codes = { text: n + (n === "1" ? " code ›" : " codes ›"), tap: parked === true };
    }
    return { runTime: runTime, mil: mil, codes: codes };
  }

  // --- US-888-b the RPM bar (spec s4.1, R30, R35) ----------------------------
  //
  // Geometry from the spec: 16 segments x 500 rpm. That is the bar's SCALE, not
  // a threshold -- where amber and red start is the provider's
  // params.RPM.scale {amberFrom, redFrom} (band_producer.rpmScale, the same
  // pi.bands.rpm keys the RPM band uses), so this file never names an edge.
  var RPM_BAR_SEGMENTS = 16;
  var RPM_BAR_SEGMENT_RPM = 500;

  // The provider's zone edges, or null. Both must be real numbers: half a
  // scale is no scale, and a bar with no scale paints no zone at all rather
  // than one this page made up.
  function rpmBarScale(scale) {
    if (!isObj(scale)) return null;
    var a = scale.amberFrom;
    var r = scale.redFrom;
    if (typeof a !== "number" || !isFinite(a) || typeof r !== "number" || !isFinite(r)) {
      return null;
    }
    return { amberFrom: a, redFrom: r };
  }

  // One params.RPM -> the bar. A pure map from ONE sample: the bar steps on
  // each real reading and paints nothing in between (no sweep, no
  // interpolation -- Spool 08-07: it fabricates values the ECU never sent).
  //   segment i      covers [i x 500, (i+1) x 500) and is ZONED by its lower
  //                  edge (R35): green below amberFrom, amber below redFrom,
  //                  red from redFrom;
  //   lit            once the sample reaches the segment's lower edge, so the
  //                  leading segment's zone is the sample's zone;
  //   stale          last.value, dimmed by the stylesheet; never a flash, which
  //                  would claim "over the redline NOW" from an old sample;
  //   not read       nothing lit.
  // `redline` (sample >= redFrom) arms the flash; the NUMBER's red is the
  // provider band (drivingView), never this comparison.
  function rpmBarView(param) {
    var p = isObj(param) ? param : null;
    var stale = !!p && p.stale === true;
    var source = stale ? (isObj(p.last) ? p.last.value : null) : (p ? p.value : null);
    var value = typeof source === "number" && isFinite(source) ? source : null;
    var scale = p ? rpmBarScale(p.scale) : null;
    var segments = [];
    var lit = 0;
    var zone = null;
    for (var i = 0; i < RPM_BAR_SEGMENTS; i++) {
      var lower = i * RPM_BAR_SEGMENT_RPM;
      var segZone = !scale ? "none"
        : lower >= scale.redFrom ? "red"
        : lower >= scale.amberFrom ? "amber" : "green";
      var on = value !== null && value >= lower;
      if (on) {
        lit++;
        zone = scale ? segZone : null;
      }
      segments.push({ zone: segZone, lit: on });
    }
    return {
      segments: segments,
      lit: lit,
      zone: zone,
      stale: value !== null && stale,
      redline: !stale && !!scale && value !== null && value >= scale.redFrom,
    };
  }

  function imuHeadingTile(data) {
    var deg = data.headingDeg;
    if (typeof deg !== "number" || !isFinite(deg)) {
      var na = naTile("HEADING", imuReason(data, "headingDeg"));
      na.deg = null;
      na.available = false;
      return na;
    }
    var d = normDeg(deg);
    return {
      label: "HEADING",
      value: Math.round(d) + "° " + headingCardinal(d),
      // NO DETAIL LINE. US-697, CIO 2026-09-09: removal, not rewording -- the
      // bearing and its cardinal are the whole tile.
      //
      // WHAT WAS HERE AND WHY IT WENT, recorded so it is not re-added by
      // someone re-deriving the original reasoning. The line read `magnetic`,
      // and it was NOT one of the uncalibrated hedges US-656's ruling bans: it
      // named the REFERENCE FRAME -- a bearing against magnetic north, no
      // declination in the contract -- which is a fact about the quantity, the
      // same class of statement as a unit. Its job was to stop a bearing a few
      // degrees off a paper map from being read as a broken compass. The CIO's
      // call is that at 480x320, read at arm's length, that is one more thing
      // to read. The frame itself is unchanged and still documented in
      // specs/architecture.md 10.8.2 and specs/grounded-knowledge.md.
      //
      // AND THE RATIONALE NO LONGER HELD ANYWAY: the compass IS broken today
      // (A-30 -- rotating field at ~28% of Earth's, heading uncorrelated with
      // rotation over 668 turns; US-695). The label was reassuring the operator
      // about a real defect, so removing it hides nothing it was successfully
      // communicating.
      //
      // EMPTY STRING, NOT AN ABSENT KEY. "" is the shipped convention for a
      // tile with nothing to say: every tile declares its whole shape. NOT
      // because a dropped key would paint a word -- `appendTile` assigns
      // `detail.textContent = tile.detail` unconditionally, and a browser
      // paints NOTHING for `undefined` there (measured, Chrome/Edge 152,
      // US-719). That is exactly why a dropped key would go unseen, on the
      // panel and in the render harness alike (US-726). `.tile-detail`
      // reserves no height, so the empty span costs no line box.
      detail: "",
      level: "neutral",
      deg: d,
      available: true,
    };
  }

  function imuGradeTile(data) {
    var pct = data.gradePct;
    if (typeof pct !== "number" || !isFinite(pct)) {
      var na = naTile("GRADE", imuReason(data, "gradePct"));
      na.available = false;
      return na;
    }
    return {
      label: "GRADE",
      value: (pct >= 0 ? "+" : "−") + Math.abs(pct).toFixed(1) + " %",
      detail: pct >= 0 ? "climbing" : "descending",
      // `neutral`, never `ok`: a road grade is a fact about the road, not a
      // health verdict. Nothing on this card is a pass/fail.
      level: "neutral",
      // US-508: the raw number, so the ~15-min trend samples the SAME value the
      // tile prints. Re-parsing the formatted string would let the sparkline and
      // the readout disagree the first time the format changes.
      pct: pct,
      available: true,
    };
  }

  // US-503 idle-card wall clock. PURE -- the caller supplies the Date, so this
  // formats a clock face without reading one (the tests stay deterministic and
  // it is node-testable; it previously lived in the browser-only block below,
  // where block-scoped function declarations put it out of reach of every test).
  //
  // A 12-hour AM/PM face is how the operator reads a dashboard at a glance.
  function two(n) { return (n < 10 ? "0" : "") + n; }

  // THE 12-hour rule for this whole surface -- written ONCE, on purpose.
  // US-503's note here used to warn that two formatters is how a 12-hour face
  // drifts back to 24-hour on one panel; US-559 is that warning coming true, so
  // the rule is now SHARED by the top-bar clock and the sync stamp rather than
  // copied into a second place.
  //
  // Mod-12 ALONE is wrong twice a day -- it renders both midnight and noon as
  // hour 0 -- so the 12 is restored explicitly. The padding is asymmetric on
  // purpose: a bare hour ("2:05 PM", never "02:05 PM"), a padded minute, and a
  // padded second on the surfaces that ask for one.
  function fmtTimeOfDay(d, withSeconds) {
    var h = d.getHours();
    var sec = withSeconds ? ":" + two(d.getSeconds()) : "";
    return (h % 12 || 12) + ":" + two(d.getMinutes()) + sec + " " + (h < 12 ? "AM" : "PM");
  }

  // US-503 top-bar / idle face. Seconds are deliberately absent: a ticking
  // seconds field on a glanceable clock is motion the driver has to ignore.
  function fmtClock(d) {
    return fmtTimeOfDay(d, false);
  }

  // US-559 (F-132 P-5). The sync stamp arrives as an ISO-8601 instant and used
  // to be pasted RAW onto the tile, so the panel carried TWO clocks -- the
  // top-bar face in local time, the sync stamp in UTC -- that can differ by
  // hours with no way to tell which one is lying. Formatting fixed the reading;
  // rendering it in LOCAL time (`fmtTimeOfDay` reads `getHours`) fixes the
  // contradiction. The day is padded so the stamp holds a FIXED width and the
  // tile does not reflow between the 9th and the 10th.
  var STAMP_MONTHS = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];

  // Only a ZONE-QUALIFIED ISO-8601 instant is formatted. The zone is not
  // pedantry: JS reads a zoneless timestamp as LOCAL, so a stamp the emitter
  // sends in UTC would render silently hours wrong -- re-creating the exact
  // contradiction this function exists to remove. And `new Date` is far too
  // willing: it reads "412" as the year 412 and would put a confident wrong
  // date on the one tile whose whole job is to report sync health. Anything
  // this pattern does not admit is handed back VERBATIM.
  var ISO_INSTANT = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})$/;

  function fmtStamp(ts) {
    // Echoed rather than formatted, never coerced through `new Date`: a
    // fabricated Jan 01 1970 is the green-when-broken failure here.
    if (typeof ts !== "string") return String(ts);
    if (!ISO_INSTANT.test(ts)) return ts;
    var d = new Date(ts);
    if (isNaN(d.getTime())) return ts;
    return (
      STAMP_MONTHS[d.getMonth()] + " " + two(d.getDate()) + ", " +
      d.getFullYear() + " " + fmtTimeOfDay(d, true)
    );
  }

  var api = {
    makeResilientLoop: makeResilientLoop,
    reportFetchAbort: reportFetchAbort,
    shouldLog: shouldLog,
    uiLog: uiLog,
    reportFirstFrame: reportFirstFrame,
    reportLoopError: reportLoopError,
    installGlobalErrorReporting: installGlobalErrorReporting,
    clampIndex: clampIndex,
    nextIndex: nextIndex,
    swipeDirection: swipeDirection,
    computeStageScale: computeStageScale,
    cardAvailability: cardAvailability,
    noDataView: noDataView,
    vehicleConnected: vehicleConnected,
    visualPosition: visualPosition,
    nextVisibleIndex: nextVisibleIndex,
    nearestVisibleIndex: nearestVisibleIndex,
    resolveCarouselConfig: resolveCarouselConfig,
    shouldAutoAdvance: shouldAutoAdvance,
    shouldAutoResume: shouldAutoResume,
    rotateProgress: rotateProgress,
    swipeGesture: swipeGesture,
    // US-893-b: the Light page.
    luxAxisX: luxAxisX,
    lightCurveView: lightCurveView,
    lightStatusView: lightStatusView,
    lightPageView: lightPageView,
    headingCardinal: headingCardinal,
    resolveImuStaleSec: resolveImuStaleSec,
    compassTape: compassTape,
    // US-896-a: the NAV card's heading half.
    compassPoint8: compassPoint8,
    fmtHeadingDigits: fmtHeadingDigits,
    shortestArcDeg: shortestArcDeg,
    navGlideInit: navGlideInit,
    navGlideNext: navGlideNext,
    navGlideStep: navGlideStep,
    navDrawnDeg: navDrawnDeg,
    navGliding: navGliding,
    navHeadingView: navHeadingView,
    navTape: navTape,
    // US-896-b: the NAV card's bottom row.
    navGradeView: navGradeView,
    navTripView: navTripView,
    fmtElapsed: fmtElapsed,
    // US-892-b: the Motion card's top two bands.
    motionView: motionView,
    motionGradeGraph: motionGradeGraph,
    gearView: gearView,
    gearReasonText: gearReasonText,
    displayUnits: displayUnits,
    drivingView: drivingView,
    engineView: engineView,
    engineHistoryView: engineHistoryView,
    engineStatusView: engineStatusView,
    rpmBarView: rpmBarView,
    sourceUnavailable: sourceUnavailable,
    sourceReason: sourceReason,
    naTile: naTile,
    // US-700: the three-state machinery. `loadingGraceMs` is exported as a
    // FUNCTION as well as a constant so the fixture probe -- which can only
    // call exports -- reads the shipped bound instead of re-typing it.
    loadPhase: loadPhase,
    loadingTile: loadingTile,
    loadingGraceMs: loadingGraceMs,
    feedObserved: feedObserved,
    feedWaitedMs: feedWaitedMs,
    LOADING_GRACE_MS: LOADING_GRACE_MS,
    powerTile: powerTile,
    linkChainGlyph: linkChainGlyph,
    LINK_CHAIN_LAYERS: LINK_CHAIN_LAYERS,
    LINK_STATE_LOOK: LINK_STATE_LOOK,
    LINK_MEMBER_LAYERS: LINK_MEMBER_LAYERS,
    syncGlyphState: syncGlyphState,
    systemVerdictView: systemVerdictView,
    obdRowView: obdRowView,
    obdDetailView: obdDetailView,
    OBD_LAYER_SENTENCE: OBD_LAYER_SENTENCE,
    OBD_ALL_UP_SENTENCE: OBD_ALL_UP_SENTENCE,
    currentParked: currentParked,
    onParkedChange: onParkedChange,
    publishParked: publishParked,
    sysRowFreshness: sysRowFreshness,
    systemIssueRows: systemIssueRows,
    systemDiagnostics: systemDiagnostics,
    systemDrill: systemDrill,
    systemStatusView: systemStatusView,
    dataRowView: dataRowView,
    dataDetailView: dataDetailView,
    wifiRowView: wifiRowView,
    wifiDetailView: wifiDetailView,
    wifiGlyphState: wifiGlyphState,
    syncWhenText: syncWhenText,
    freshAgeText: freshAgeText,
    CAPTURE_STATE_WORD: CAPTURE_STATE_WORD,
    CAPTURE_FEEDS: CAPTURE_FEEDS,
    CAPTURE_FEED_WORD: CAPTURE_FEED_WORD,
    priorShutdownTile: priorShutdownTile,
    healthCheckLine: healthCheckLine,
    vcellTile: vcellTile,
    socTile: socTile,
    ladderView: ladderView,
    batteryHealthView: batteryHealthView,
    fmtLtftPct: fmtLtftPct,
    ltftTrendView: ltftTrendView,
    fuelTrendView: fuelTrendView,
    fuelAirflowView: fuelAirflowView,
    fuelLoopView: fuelLoopView,
    fuelTotalTrimView: fuelTotalTrimView,
    fuelMpgView: fuelMpgView,
    FUEL_RESET_HOLD_MS: FUEL_RESET_HOLD_MS,
    resolveFuelResetConfirmSec: resolveFuelResetConfirmSec,
    fuelResetInit: fuelResetInit,
    fuelResetNext: fuelResetNext,
    fuelMpgResetView: fuelMpgResetView,
    fuelResetAllowed: fuelResetAllowed,
    sourceCardSpecs: sourceCardSpecs,
    sourceCardSpec: sourceCardSpec,
    sourceCardView: sourceCardView,
    serviceMenuItems: serviceMenuItems,
    settingsSpecs: settingsSpecs,
    settingsApplyStates: settingsApplyStates,
    settingsReloadNeeded: settingsReloadNeeded,
    settingsChoices: settingsChoices,
    settingsRowView: settingsRowView,
    settingsEntry: settingsEntry,
    settingsChoiceActive: settingsChoiceActive,
    settingsWriteValue: settingsWriteValue,
    settingsSaveResult: settingsSaveResult,
    settingsPendingNote: settingsPendingNote,
    requiresConfirm: requiresConfirm,
    actionRequest: actionRequest,
    longPressProgress: longPressProgress,
    isLongPressComplete: isLongPressComplete,
    exceedsMoveCancel: exceedsMoveCancel,
    parkedInit: parkedInit,
    parkedNext: parkedNext,
    gearParked: gearParked,
    appliedBrightness: appliedBrightness,
    brightnessAlarmActive: brightnessAlarmActive,
    resolveAutoDimConfig: resolveAutoDimConfig,
    fmtClock: fmtClock,
    fmtStamp: fmtStamp,
    carouselIdle: carouselIdle,
    notLiveMarker: notLiveMarker,
    alertIconView: alertIconView,
    agoText: agoText,
    warningsPageView: warningsPageView,
    warningRowView: warningRowView,
    warningStaleText: warningStaleText,
    warningsMoreBelow: warningsMoreBelow,
    warningsBelowFromLayout: warningsBelowFromLayout,
    warningsMoreText: warningsMoreText,
    tierColorVar: tierColorVar,
    takeoverAlertView: takeoverAlertView,
    resolveAlertsAckConfirmSec: resolveAlertsAckConfirmSec,
    resolveAlertsAckNoticeSec: resolveAlertsAckNoticeSec,
    alertsAckBody: alertsAckBody,
    alertsAckInit: alertsAckInit,
    alertsAckNext: alertsAckNext,
    alertsAckNoticeText: alertsAckNoticeText,
    codeAlertView: codeAlertView,
    codeDismissBody: codeDismissBody,
    codeDismissInit: codeDismissInit,
    codeDismissNext: codeDismissNext,
    codeDismissNoticeText: codeDismissNoticeText,
    trustBadge: trustBadge,
    fixArea: fixArea,
    fixSectionLabel: fixSectionLabel,
    freezeFrameView: freezeFrameView,
    codeDetailView: codeDetailView,
    codeFromEntryId: codeFromEntryId,
    dtcRecordFor: dtcRecordFor,
    clearGateReason: clearGateReason,
    clearButtonView: clearButtonView,
    confirmClearText: confirmClearText,
    postClearMessage: postClearMessage,
    POLL_MS: POLL_MS,
    IMU_POLL_MS: IMU_POLL_MS,
    COMPASS_TAPE_SPAN_DEG: COMPASS_TAPE_SPAN_DEG,
    NAV_GLIDE_MS: NAV_GLIDE_MS,
    SWIPE_THRESHOLD_PX: SWIPE_THRESHOLD_PX,
    CAROUSEL_DEFAULTS: CAROUSEL_DEFAULTS,
    STAGE_W: STAGE_W,
    STAGE_H: STAGE_H,
    LONG_PRESS_MS: LONG_PRESS_MS,
    LONG_PRESS_ARM_MS: LONG_PRESS_ARM_MS,
    LONG_PRESS_MOVE_PX: LONG_PRESS_MOVE_PX,
  };

  // -------------------------------------------------------------------------
  // DOM wiring -- browser only.
  // -------------------------------------------------------------------------

  if (typeof document !== "undefined") {
    var token = global.SPLASH_TOKEN || "";

    // US-483-b: the pi.display.autoDim section injected same-origin at serve
    // time (states_http_server substitutes the placeholder from config.json).
    // Since US-893-a the page reads only its defaultLevel and luxStaleSec. An
    // object -> use it; anything else (unsubstituted preview / null) -> the
    // built-in defaults kick in inside resolveAutoDimConfig.
    var displayAutoDim =
      global.DISPLAY_AUTODIM && typeof global.DISPLAY_AUTODIM === "object"
        ? global.DISPLAY_AUTODIM
        : null;

    // US-506: the carousel navigation config (pi.display.carousel), injected
    // the same way. Resolved ONCE here so every gesture and every tick reads
    // one object -- resolving per-event would let a mid-session config swap
    // change the feel halfway through a gesture.
    var carouselCfg = resolveCarouselConfig(
      global.DISPLAY_CAROUSEL && typeof global.DISPLAY_CAROUSEL === "object"
        ? global.DISPLAY_CAROUSEL
        : null
    );

    // US-532: the 5 Slice-1 settings at their EFFECTIVE values (US-530 shared
    // resolver), injected the same way and resolved by the server PER REQUEST --
    // so a reload after a save shows what was actually stored. Anything that is
    // not an object (unsubstituted preview / null when the server has no config)
    // -> every row renders Unknown, which is honest: without the injection we do
    // not know what is stored, and a display-side default would be a fabrication.
    var settingsSource =
      global.DISPLAY_SETTINGS && typeof global.DISPLAY_SETTINGS === "object"
        ? global.DISPLAY_SETTINGS
        : null;

    // Apply the computed 0..1 brightness as a CSS var on the screen frame (a
    // software dim -- the browser kiosk can't drive the panel backlight). Setting
    // a var (not style.filter) keeps the CSS the single owner of the filter rule.
    function applyBrightness(level) {
      var screenEl = document.getElementById("screen");
      if (screenEl) screenEl.style.setProperty("--display-brightness", String(level));
    }

    // --- US-400 System Status DOM render (browser only) ---------------------

    // Render one tile into a parent element (label + prominent value + detail).
    // The level drives the colour via [data-level] CSS -- a degraded tile is
    // never green (F-1). Built with textContent (no innerHTML) so emitter values
    // render verbatim, never as markup.
    // US-894-b: the US-489 `withDot` status dot went with the System grid,
    // its only caller.
    function appendTile(parent, tile) {
      var el = document.createElement("div");
      el.className = "tile";
      el.setAttribute("data-level", tile.level);
      var label = document.createElement("span");
      label.className = "tile-label";
      label.textContent = tile.label;
      var value = document.createElement("span");
      value.className = "tile-value";
      value.textContent = tile.value;
      var detail = document.createElement("span");
      detail.className = "tile-detail";
      detail.textContent = tile.detail;
      el.appendChild(label);
      el.appendChild(value);
      el.appendChild(detail);
      parent.appendChild(el);
    }

    // US-894-b (spec s3 layout A): the verdict line, then one row per
    // subsystem. Built with textContent (no innerHTML) so provider values --
    // a member's reason above all -- render verbatim, never as markup. Rows
    // are `.sys-row`, never `.tile`.
    function appendSysVerdict(body, verdict, tappable) {
      var line = document.createElement("div");
      line.className = "sys-verdict";
      line.setAttribute("data-level", verdict.level);
      var text = document.createElement("span");
      text.className = "sys-verdict-text";
      text.textContent = verdict.text;
      line.appendChild(text);
      if (tappable) {
        // s4.1 I9: the ` ›` only while the tap works (parked). A chevron that
        // leads nowhere is the US-758 failure.
        line.classList.add("sys-tappable");
        line.setAttribute("role", "button");
        line.setAttribute("tabindex", "0");
        var chevron = document.createElement("span");
        chevron.className = "sys-chevron";
        chevron.textContent = " ›";
        line.appendChild(chevron);
        line.onclick = function () { openSysDetail("drill"); };
      }
      body.appendChild(line);
    }

    // The OBD row's chain: three outlined steps joined by short rules, each
    // step's look on its own data-state (a null layer is `dashed`, AC 4).
    function appendObdChain(parent, steps) {
      var chain = document.createElement("span");
      chain.className = "obd-chain";
      for (var i = 0; i < LINK_CHAIN_LAYERS.length; i++) {
        var layer = LINK_CHAIN_LAYERS[i];
        if (i > 0) {
          var join = document.createElement("span");
          join.className = "obd-join";
          join.textContent = "━";
          chain.appendChild(join);
        }
        var step = document.createElement("span");
        step.className = "obd-step";
        step.setAttribute("data-layer", layer);
        step.setAttribute("data-state", steps[i]);
        step.textContent = OBD_STEP_LABELS[layer];
        chain.appendChild(step);
      }
      parent.appendChild(chain);
    }

    function appendSysRow(parent, row, tappable) {
      var el = document.createElement("div");
      el.className = "sys-row";
      el.setAttribute("data-row", row.key);
      el.setAttribute("data-level", row.level);
      var label = document.createElement("span");
      label.className = "sys-row-label";
      label.textContent = row.label;
      el.appendChild(label);
      var main = document.createElement("div");
      main.className = "sys-row-main";
      var value = document.createElement("div");
      value.className = "sys-row-value";
      if (row.steps) {
        appendObdChain(value, row.steps);
      } else {
        // US-894-c: a word in its own look, then a neutral tail.
        var word = document.createElement("span");
        word.className = "sys-row-word";
        word.setAttribute("data-state", row.look);
        word.textContent = row.word;
        value.appendChild(word);
        var tail = document.createElement("span");
        tail.className = "sys-row-tail";
        tail.textContent = row.tail;
        value.appendChild(tail);
      }
      main.appendChild(value);
      var sentence = document.createElement("span");
      sentence.className = "sys-row-sentence";
      if (row.parts) {
        // US-894-c: one span per part, each on its own level, so a member's
        // reason is amber and the counts beside it are not (s4.0). The ` · `
        // lives inside the span it introduces.
        for (var p = 0; p < row.parts.length; p++) {
          var part = document.createElement("span");
          part.className = "sys-row-part";
          part.setAttribute("data-level", row.parts[p].level);
          part.textContent = (p > 0 ? " · " : "") + row.parts[p].text;
          sentence.appendChild(part);
        }
      } else {
        sentence.textContent = row.sentence;
      }
      main.appendChild(sentence);
      el.appendChild(main);
      if (tappable) {
        el.classList.add("sys-tappable");
        el.setAttribute("role", "button");
        el.setAttribute("tabindex", "0");
        var chevron = document.createElement("span");
        chevron.className = "sys-chevron";
        chevron.textContent = "›";
        el.appendChild(chevron);
        el.onclick = function () { openSysDetail(row.key); };
      }
      parent.appendChild(el);
    }

    // The page body from a view. Taps are offered only while parked (the ONE
    // accessor, currentParked); not parked, nothing opens and no chevron shows.
    function renderSystemBody(card, view) {
      var body = card.querySelector(".card-body");
      if (!body) return;
      body.textContent = "";
      var parked = currentParked().parked === true;
      appendSysVerdict(body, view.verdict, parked && !!view.drill && view.drill.tappable);
      var rows = document.createElement("div");
      rows.className = "sys-rows";
      for (var i = 0; i < view.rows.length; i++) appendSysRow(rows, view.rows[i], parked);
      body.appendChild(rows);
    }

    function renderSystemStatusCard(card, view, glyphEls) {
      // US-509: the detail is fed by the SAME poll that paints the page, and
      // an OPEN overlay is repainted with it -- never frozen on the snapshot
      // that opened it.
      lastSysView = view;
      lastSysCard = card;
      if (sysDetailOpen()) renderSysDetail(view);
      renderSystemBody(card, view);
      paintLinkChain(glyphEls.bt, view.glyphs.bt);
      if (glyphEls.sync) glyphEls.sync.setAttribute("data-state", view.glyphs.sync);
      // ARCH-007: render the emitter's verdict. The display applies NO
      // threshold of its own (ruling s2.1) -- two rules for one fact disagree
      // the first time either moves.
      if (glyphEls.wifi) glyphEls.wifi.setAttribute("data-state", view.glyphs.wifi);
    }

    // s4.1: system-status unreadable -> the verdict is `--`, never ALL OK, and
    // no row claims a reading. The view is dropped so no tap can open a detail
    // built from a reading that is gone.
    function renderSystemUnavailable(card) {
      lastSysView = null;
      lastSysCard = card;
      var body = card.querySelector(".card-body");
      if (!body) return;
      body.textContent = "";
      appendSysVerdict(body, systemVerdictView(null), false);
    }

    // US-894-b: a parked edge repaints the page from the last view, so a tap
    // and its chevron appear (or go) on the edge, not a tick later.
    function repaintSystemOnParkedEdge() {
      if (lastSysCard && lastSysView) renderSystemBody(lastSysCard, lastSysView);
    }

    // --- US-509 System-Status detail overlay (browser only) -----------------

    // The most-recent page view, so a tap has content to show without a second
    // read of the state file. It is set by the renderer above, which means the
    // overlay is fed by exactly the same poll that painted the page.
    var lastSysView = null;
    var lastSysCard = null;
    // US-894-b: which detail #sys-detail shows -- "drill" (behind the verdict)
    // or a row's key ("obd"). Every detail renders in the one overlay (I8).
    var sysDetailKind = "drill";

    // Elements are looked up LAZILY rather than captured at init: this renderer
    // lives in the shared render scope (not the browser-only block below), and a
    // captured-at-load reference would be null under the node/file:// paths that
    // exercise this file without the full DOM.
    function renderSysDetail(view) {
      var bodyEl = document.getElementById("sys-detail-body");
      if (!bodyEl) return;
      bodyEl.textContent = "";
      // I8: the version chip shows only in the Pi detail. Until that detail
      // lands (US-894-e/f) the drill behind the verdict -- the line the Pi
      // detail will be opened from -- keeps it; a row's detail never shows it.
      var chip = document.getElementById("version-chip");
      if (chip) chip.hidden = sysDetailKind !== "drill";
      if (sysDetailKind === "obd") {
        renderObdDetail(bodyEl, view);
        return;
      }
      if (sysDetailKind === "data") {
        renderDataDetail(bodyEl, view);
        return;
      }
      if (sysDetailKind === "wifi") {
        renderWifiDetail(bodyEl, view);
        return;
      }
      var head = document.getElementById("sys-detail-head");
      // The head repeats the LINE THE OPERATOR TAPPED verbatim (the verdict).
      if (head) head.textContent = view && view.verdict ? view.verdict.text : "";
      var rows = view && view.drill ? view.drill.rows : [];
      if (!rows.length) {
        // Reachable while the overlay is OPEN and the last fault clears, and --
        // since US-559 -- the NORMAL state of a healthy card, which is now
        // reachable for its diagnostics. Saying so is the honest move; an empty
        // box reads as a broken overlay, and closing it would yank the surface
        // out from under the operator.
        var none = document.createElement("div");
        none.className = "sys-issue-none";
        none.textContent = "all sources OK";
        bodyEl.appendChild(none);
      }
      for (var i = 0; i < rows.length; i++) {
        var row = rows[i];
        var el = document.createElement("div");
        el.className = "detail-card sys-issue-row";
        // The row's level came straight off the tile.
        el.setAttribute("data-level", row.level);
        var rowHead = document.createElement("div");
        rowHead.className = "sys-issue-head";
        var label = document.createElement("span");
        label.className = "sys-issue-label";
        label.textContent = row.label;
        var chip2 = document.createElement("span");
        chip2.className = "sys-issue-chip";
        chip2.textContent = row.value;
        rowHead.appendChild(label);
        rowHead.appendChild(chip2);
        el.appendChild(rowHead);
        // Omitted when the view found it only repeated the freshness beside it.
        if (row.reason) {
          var reason = document.createElement("span");
          reason.className = "sys-issue-reason";
          reason.textContent = row.reason;
          el.appendChild(reason);
        }
        var fresh = document.createElement("span");
        fresh.className = "sys-issue-freshness";
        fresh.textContent = row.freshness;
        el.appendChild(fresh);
        bodyEl.appendChild(el);
      }
      renderSysDiagnostics(bodyEl, view && view.drill ? view.drill.diagnostics : []);
    }

    // s4.6 OBD detail: per layer its state, since when and last success, then
    // the row's sentence in full (the row ellipsizes it). A view that is gone
    // (the file went unreadable while open) shows every value as `--`.
    function renderObdDetail(bodyEl, view) {
      var detail = view && view.obdDetail ? view.obdDetail : obdDetailView(null);
      var head = document.getElementById("sys-detail-head");
      if (head) head.textContent = detail.head;
      for (var i = 0; i < detail.layers.length; i++) {
        var layer = detail.layers[i];
        var el = document.createElement("div");
        el.className = "detail-card obd-layer-row";
        el.setAttribute("data-layer", layer.layer);
        var rowHead = document.createElement("div");
        rowHead.className = "sys-issue-head";
        var label = document.createElement("span");
        label.className = "obd-step";
        label.setAttribute("data-state", layer.look);
        label.textContent = layer.label;
        var state = document.createElement("span");
        state.className = "obd-layer-state";
        state.textContent = layer.state;
        rowHead.appendChild(label);
        rowHead.appendChild(state);
        el.appendChild(rowHead);
        var since = document.createElement("span");
        since.className = "obd-layer-fact";
        since.textContent = "since " + layer.since;
        el.appendChild(since);
        var lastOk = document.createElement("span");
        lastOk.className = "obd-layer-fact";
        lastOk.textContent = "last success " + layer.lastOk;
        el.appendChild(lastOk);
        bodyEl.appendChild(el);
      }
      var sentence = document.createElement("div");
      sentence.className = "detail-card obd-detail-sentence";
      sentence.setAttribute("data-level", detail.level);
      sentence.textContent = detail.sentence;
      bodyEl.appendChild(sentence);
    }

    // s4.6 DATA detail: per feed its word (in its look) and freshness age,
    // then the sync facts, then the row's sentence in full. A view that is
    // gone shows every value unread.
    function appendDataFact(bodyEl, label, text, cls) {
      var el = document.createElement("div");
      el.className = "detail-card data-fact-row" + (cls ? " " + cls : "");
      var head = document.createElement("span");
      head.className = "sys-diag-label";
      head.textContent = label;
      var value = document.createElement("span");
      value.className = "sys-diag-text";
      value.textContent = text;
      el.appendChild(head);
      el.appendChild(value);
      bodyEl.appendChild(el);
      return el;
    }

    function renderDataDetail(bodyEl, view) {
      var detail = view && view.dataDetail ? view.dataDetail : dataDetailView(null);
      var head = document.getElementById("sys-detail-head");
      if (head) head.textContent = detail.head;
      for (var i = 0; i < detail.feeds.length; i++) {
        var feed = detail.feeds[i];
        var el = document.createElement("div");
        el.className = "detail-card data-feed-row";
        el.setAttribute("data-feed", feed.feed);
        var rowHead = document.createElement("div");
        rowHead.className = "sys-issue-head";
        var label = document.createElement("span");
        label.className = "sys-issue-label";
        label.textContent = feed.label;
        var state = document.createElement("span");
        state.className = "sys-row-word data-feed-state";
        state.setAttribute("data-state", feed.look);
        state.textContent = feed.state;
        rowHead.appendChild(label);
        rowHead.appendChild(state);
        el.appendChild(rowHead);
        var age = document.createElement("span");
        age.className = "obd-layer-fact";
        age.textContent = "last row " + feed.age;
        el.appendChild(age);
        bodyEl.appendChild(el);
      }
      appendDataFact(bodyEl, "LAST DATA STORED", detail.lastStored);
      appendDataFact(bodyEl, "ROWS WAITING", detail.rowsWaiting);
      appendDataFact(bodyEl, "EVENT ROWS WAITING", detail.eventRows);
      if (detail.notCounted !== null) appendDataFact(bodyEl, "NOT COUNTED", detail.notCounted);
      appendDataFact(bodyEl, "AT HOME", detail.atHome);
      var sentence = document.createElement("div");
      sentence.className = "detail-card obd-detail-sentence";
      sentence.setAttribute("data-level", detail.level);
      sentence.textContent = detail.sentence;
      bodyEl.appendChild(sentence);
    }

    // s4.6 WIFI detail (US-894-d): the state word in its look, then SSID,
    // strength, `not connected to any network` for `down`, home, and the
    // reason in words -- amber only as the `wifi` member's. No IP line.
    function renderWifiDetail(bodyEl, view) {
      var detail = view && view.wifiDetail ? view.wifiDetail : wifiDetailView(null);
      var head = document.getElementById("sys-detail-head");
      if (head) head.textContent = detail.head;
      var stateEl = appendDataFact(bodyEl, "STATE", "", "wifi-state-row");
      var word = stateEl.querySelector(".sys-diag-text");
      if (word) {
        word.className = "sys-diag-text sys-row-word";
        word.setAttribute("data-state", detail.state.look);
        word.textContent = detail.state.text;
      }
      appendDataFact(bodyEl, "NETWORK", detail.network);
      appendDataFact(bodyEl, "STRENGTH", detail.strength);
      if (detail.link !== null) appendDataFact(bodyEl, "LINK", detail.link);
      appendDataFact(bodyEl, "HOME NETWORK", detail.home);
      if (detail.reason !== null) {
        var reasonEl = appendDataFact(bodyEl, "REASON", detail.reason, "wifi-reason");
        reasonEl.setAttribute("data-level", detail.reasonLevel);
      }
    }

    // US-559: the reference facts, below the faults. Built with textContent (no
    // innerHTML) like every other row here, so emitter values render verbatim
    // and never as markup.
    function renderSysDiagnostics(bodyEl, diags) {
      if (!diags || !diags.length) return;
      for (var i = 0; i < diags.length; i++) {
        var el = document.createElement("div");
        el.className = "detail-card sys-diag-row";
        var label = document.createElement("span");
        label.className = "sys-diag-label";
        label.textContent = diags[i].label;
        var text = document.createElement("span");
        text.className = "sys-diag-text";
        text.textContent = diags[i].text;
        el.appendChild(label);
        el.appendChild(text);
        bodyEl.appendChild(el);
      }
    }

    function sysDetailOpen() {
      var el = document.getElementById("sys-detail");
      return !!el && el.hidden === false;
    }

    // Opens a detail ONLY while parked (Atlas B9: row and verdict taps), read
    // at tap time from the one accessor -- a stale listener left on a row
    // painted while parked cannot open it after the car moves off. The drill
    // is also gated on having something behind it.
    function openSysDetail(which) {
      var el = document.getElementById("sys-detail");
      if (!el || !lastSysView || currentParked().parked !== true) return;
      if (which === "drill" && !lastSysView.drill.tappable) return;
      sysDetailKind = which;
      renderSysDetail(lastSysView);
      el.hidden = false;
    }

    function closeSysDetail() {
      var el = document.getElementById("sys-detail");
      if (el) el.hidden = true;
    }

    // US-894-a: each `.chain-dot` in #glyph-bt carries its own data-state, keyed
    // by its data-layer. A dot the view has no look for falls to hollow rather
    // than keeping a previous paint (no stale-green).
    function paintLinkChain(chainEl, looks) {
      if (!chainEl) return;
      var dots = chainEl.querySelectorAll(".chain-dot");
      for (var i = 0; i < dots.length; i++) {
        var layer = dots[i].getAttribute("data-layer");
        var look = isObj(looks) && typeof looks[layer] === "string" ? looks[layer] : "hollow";
        dots[i].setAttribute("data-state", look);
      }
    }

    // Honest-instrument reset: a missing/malformed system-status file returns the
    // glyphs to neutral so a prior good read can't linger green (no stale-green).
    // US-894-a: the chain resets to three HOLLOW dots -- an unreadable file is
    // no reading of any layer (spec s4.2.1, AC 4).
    function resetSystemGlyphs(glyphEls) {
      paintLinkChain(glyphEls.bt, linkChainGlyph(null));
      if (glyphEls.sync) glyphEls.sync.setAttribute("data-state", "neutral");
      // US-894-d: no reading -> dim arcs, no slash (s4.4).
      if (glyphEls.wifi) glyphEls.wifi.setAttribute("data-state", wifiGlyphState(null));
    }

    // --- US-401 Battery Health DOM render (browser only) --------------------

    // Render the failsafe ladder block (F-2 / A-6) -- built ONLY when draining.
    // Minutes appear only when the power tier supplied a real runtimeRemainingS
    // (Spool S-2); otherwise stage + volts only, no fabricated estimate.
    function appendLadder(parent, ladder) {
      var box = document.createElement("div");
      box.className = "ladder";
      box.setAttribute("data-stage", ladder.stage);
      var banner = document.createElement("span");
      banner.className = "ladder-banner";
      banner.textContent = "DRAINING · " + ladder.stage;
      box.appendChild(banner);
      if (ladder.runtimeRemainingS != null) {
        var rt = document.createElement("span");
        rt.className = "ladder-runtime";
        rt.textContent = "~" + Math.round(ladder.runtimeRemainingS / 60) + " min to cutoff";
        box.appendChild(rt);
      }
      parent.appendChild(box);
    }

    // US-429: render a whole-card typed NA -- one "NA (<reason>)" tile, honest
    // (never a blank or a stale last-real card) when the card's source is down.
    function renderNaBody(body, label, reason) {
      body.textContent = "";
      appendTile(body, naTile(label, reason));
    }

    // US-700: the pre-fetch body. Same geometry as the typed NA above -- one
    // tile in the slot -- so the card does not JUMP when the real payload lands
    // a moment later. Only the words and the level differ, which is the whole
    // point: the operator reads a change of state, not a change of layout.
    function renderLoadingBody(body, label) {
      body.textContent = "";
      appendTile(body, loadingTile(label));
    }

    // US-888-a: paint `drivingView` into the Driving card's FIXED skeleton
    // (dashboard.html). Text and state attributes only -- the stylesheet maps
    // data-band / data-stale / data-note to tokens, so the colour on the glass
    // is decided by the provider's band and nothing in this function. A note
    // with nothing to say takes its box down with it.
    // US-888-b: the last MEASURED gear painted, so the glide fires on a real
    // change (3 -> 4, also through a "--" between them) and never on the first
    // gear, a repeat of the same gear, or "--".
    var drivingLastGear = null;
    function renderDrivingCard(card, view) {
      if (!card || !view) return;
      var gearEl = card.querySelector(".drv-gear");
      if (gearEl) {
        gearEl.textContent = view.gear.text;
        gearEl.setAttribute("data-measured", view.gear.measured ? "true" : "false");
        if (view.gear.measured) {
          if (drivingLastGear !== null && drivingLastGear !== view.gear.text) {
            // Alternate a/b: a NEW animation-name restarts the glide without a
            // forced reflow, so two quick shifts each get their own.
            gearEl.setAttribute(
              "data-glide", gearEl.getAttribute("data-glide") === "a" ? "b" : "a"
            );
          }
          drivingLastGear = view.gear.text;
        }
      }
      if (view.rpmBar) renderRpmBar(card.querySelector(".drv-rpm-bar"), view.rpmBar);
      var slots = card.querySelectorAll(".drv-reading");
      for (var s = 0; s < slots.length; s++) {
        var slot = slots[s];
        var reading = view.readings[slot.getAttribute("data-pid")];
        if (!reading) continue;
        slot.setAttribute("data-band", reading.band || "none");
        slot.setAttribute("data-stale", reading.stale ? "true" : "false");
        slot.setAttribute("data-note", reading.noteKind || "none");
        var valueEl = slot.querySelector(".drv-value");
        if (valueEl) valueEl.textContent = reading.text;
        var unitEl = slot.querySelector(".drv-unit");
        if (unitEl) unitEl.textContent = reading.unit;
        var noteEl = slot.querySelector(".drv-note");
        if (noteEl) {
          noteEl.textContent = reading.note;
          noteEl.hidden = !reading.note;
        }
      }
    }

    // US-889-b: paint `engineView` into the Engine card's FIXED skeleton
    // (dashboard.html). Text, state attributes and the bars' fill height only:
    // the stylesheet maps data-stale / data-note to tokens. The fill is a plain
    // height with no transition, so a bar steps from one sample to the next.
    function renderEngineCard(card, view) {
      if (!card || !view) return;
      var slots = card.querySelectorAll(".eng-reading");
      for (var s = 0; s < slots.length; s++) {
        var slot = slots[s];
        var reading = view.readings[slot.getAttribute("data-pid")];
        if (!reading) continue;
        slot.setAttribute("data-stale", reading.stale ? "true" : "false");
        slot.setAttribute("data-note", reading.noteKind || "none");
        var valueEl = slot.querySelector(".eng-value");
        if (valueEl) valueEl.textContent = reading.text;
        var unitEl = slot.querySelector(".eng-unit");
        if (unitEl) unitEl.textContent = reading.unit;
        var noteEl = slot.querySelector(".eng-note");
        if (noteEl) {
          noteEl.textContent = reading.note;
          noteEl.hidden = !reading.note;
        }
      }
      var cols = card.querySelectorAll(".eng-bar-col");
      for (var c = 0; c < cols.length; c++) {
        var bar = view.bars[cols[c].getAttribute("data-pid")];
        if (!bar) continue;
        cols[c].setAttribute("data-stale", bar.stale ? "true" : "false");
        var fill = cols[c].querySelector(".eng-bar-fill");
        if (fill) fill.style.setProperty("height", (bar.fill === null ? 0 : bar.fill) + "%");
      }
    }

    // US-890-b: paint `fuelAirflowView` into the Fuel card's AIRFLOW slot
    // (dashboard.html skeleton). Text, state attributes and the fill's width
    // only; the width has no transition, so the bar steps per reading.
    function renderFuelAirflow(card, view) {
      if (!card || !view) return;
      var slot = card.querySelector(".fuel-airflow");
      if (!slot) return;
      var reading = view.reading;
      slot.setAttribute("data-stale", reading.stale ? "true" : "false");
      slot.setAttribute("data-note", reading.noteKind || "none");
      var valueEl = slot.querySelector(".fuel-value");
      if (valueEl) valueEl.textContent = reading.text;
      var unitEl = slot.querySelector(".fuel-unit");
      if (unitEl) unitEl.textContent = reading.unit;
      var noteEl = slot.querySelector(".fuel-note");
      if (noteEl) {
        noteEl.textContent = reading.note;
        noteEl.hidden = !reading.note;
      }
      var bar = slot.querySelector(".fuel-bar");
      if (bar) bar.setAttribute("data-stale", view.bar.stale ? "true" : "false");
      var fill = slot.querySelector(".fuel-bar-fill");
      if (fill) fill.style.setProperty("width", (view.bar.fill === null ? 0 : view.bar.fill) + "%");
    }

    // US-890-c: paint `fuelLoopView` / `fuelTotalTrimView` into the LOOP and
    // TOTAL TRIM slots (dashboard.html skeleton). Text and state attributes
    // only; data-dimmed is the sheet's one hook for the open-loop "--".
    function renderFuelSideSlot(card, slotClass, view) {
      var slot = card.querySelector(slotClass);
      if (!slot) return;
      slot.setAttribute("data-note", view.noteKind || "none");
      slot.setAttribute("data-dimmed", view.dimmed ? "true" : "false");
      var valueEl = slot.querySelector(".fuel-value");
      if (valueEl) valueEl.textContent = view.text;
      var noteEl = slot.querySelector(".fuel-note");
      if (noteEl) {
        noteEl.textContent = view.note;
        noteEl.hidden = !view.note;
      }
    }

    function renderFuelLoopAndTrim(card, loopView, trimView) {
      if (!card || !loopView || !trimView) return;
      renderFuelSideSlot(card, ".fuel-loop", loopView);
      renderFuelSideSlot(card, ".fuel-total-trim", trimView);
    }

    // US-890-d: paint `fuelMpgView` into the three MPG slots (dashboard.html
    // skeleton), selected by class. The flag shows only when the view sets one.
    function renderFuelMpg(card, view) {
      if (!card || !view) return;
      var slots = [
        [".fuel-mpg-last30", view.last30],
        [".fuel-mpg-this-drive", view.thisDrive],
        [".fuel-mpg-since-reset", view.sinceReset],
      ];
      for (var i = 0; i < slots.length; i++) {
        var slot = card.querySelector(slots[i][0]);
        var slotView = slots[i][1];
        if (!slot || !slotView) continue;
        slot.setAttribute("data-note", slotView.noteKind || "none");
        var valueEl = slot.querySelector(".fuel-value");
        if (valueEl) valueEl.textContent = slotView.text;
        // US-922: the unit, as renderFuelAirflow paints g/s.
        var unitEl = slot.querySelector(".fuel-unit");
        if (unitEl) unitEl.textContent = slotView.unit || "";
        var flagEl = slot.querySelector(".fuel-flag");
        if (flagEl) {
          flagEl.textContent = slotView.flag;
          flagEl.hidden = !slotView.flag;
        }
        var noteEl = slot.querySelector(".fuel-note");
        if (noteEl) {
          noteEl.textContent = slotView.note;
          noteEl.hidden = !slotView.note;
        }
      }
      // US-890-f: SINCE RESET's hint / outcome line, whether the hold is live,
      // and the in-page confirm -- all from `fuelMpgResetView`.
      var since = card.querySelector(".fuel-mpg-since-reset");
      var reset = isObj(view.reset) ? view.reset : { pressable: false, confirm: false };
      if (since && view.sinceReset) {
        var lineEl = since.querySelector(".fuel-reset-line");
        if (lineEl) {
          lineEl.textContent = view.sinceReset.line || "";
          lineEl.hidden = !view.sinceReset.line;
        }
        since.setAttribute("data-pressable", reset.pressable ? "true" : "false");
      }
      var confirmEl = card.querySelector(".fuel-reset-confirm");
      if (confirmEl) confirmEl.hidden = !reset.confirm;
    }

    // US-889-c: one history chart. The spans go in first so the neutral line
    // draws over them; one polyline per run, so an omitted bucket leaves a
    // real break in the line.
    function buildEngineHistoryChart(series) {
      var svg = svgEl("svg", {
        class: "eng-hist-chart", viewBox: "0 0 " + ENGINE_HISTORY_W + " " + ENGINE_HISTORY_H,
        preserveAspectRatio: "none", "aria-hidden": "true",
      });
      for (var s = 0; s < series.spans.length; s++) {
        var span = series.spans[s];
        svg.appendChild(svgEl("rect", {
          class: "eng-hist-span", "data-band": span.band,
          x: span.x, y: 0, width: span.width, height: ENGINE_HISTORY_H,
        }));
      }
      for (var g = 0; g < series.segments.length; g++) {
        svg.appendChild(svgEl("polyline", { class: "eng-hist-line", points: series.segments[g] }));
      }
      return svg;
    }

    function engineTextEl(tag, cls, text) {
      var el = document.createElement(tag);
      el.className = cls;
      el.textContent = text;
      return el;
    }

    function buildEngineHistorySeries(series, windowText) {
      var box = document.createElement("div");
      box.className = "eng-hist";
      box.setAttribute("data-pid", series.pid);
      var head = document.createElement("div");
      head.className = "eng-hist-head";
      head.appendChild(engineTextEl("span", "eng-label", series.label));
      head.appendChild(engineTextEl("span", "eng-hist-window", "· " + windowText));
      box.appendChild(head);
      if (series.empty) {
        box.appendChild(engineTextEl("p", "eng-absence", ENGINE_HISTORY_ABSENT));
        return box;
      }
      var row = document.createElement("div");
      row.className = "eng-hist-row";
      row.appendChild(buildEngineHistoryChart(series));
      var end = document.createElement("span");
      end.className = "eng-hist-end";
      end.appendChild(engineTextEl("span", "eng-hist-value", series.end.text));
      end.appendChild(engineTextEl("span", "eng-hist-unit", series.end.unit));
      row.appendChild(end);
      box.appendChild(row);
      return box;
    }

    // US-889-c: paint the scroll half. The history changes at most once per
    // bucket (30 s) while the tick runs at 4 Hz, so the charts are rebuilt
    // only when the view itself changed; the status row is text and state
    // attributes on the fixed skeleton, like the readings above the fold.
    var engineHistoryKey = null;

    function renderEngineScroll(card, historyView, statusView) {
      if (!card) return;
      var host = card.querySelector(".eng-history");
      var key = JSON.stringify(historyView);
      if (host && key !== engineHistoryKey) {
        engineHistoryKey = key;
        host.textContent = "";
        if (historyView.empty) {
          host.appendChild(engineTextEl("p", "eng-absence", historyView.absence));
        } else {
          for (var i = 0; i < historyView.series.length; i++) {
            host.appendChild(buildEngineHistorySeries(historyView.series[i], historyView.window));
          }
        }
      }
      var tiles = card.querySelectorAll(".eng-stat");
      for (var t = 0; t < tiles.length; t++) {
        var pid = tiles[t].getAttribute("data-pid");
        var reading = pid === "RUNTIME_SEC" ? statusView.runTime
          : pid === "MIL_ON" ? statusView.mil : null;
        if (!reading) continue;
        tiles[t].setAttribute("data-stale", reading.stale ? "true" : "false");
        tiles[t].setAttribute("data-note", reading.noteKind || "none");
        var valueEl = tiles[t].querySelector(".eng-stat-value");
        if (valueEl) valueEl.textContent = reading.text;
        var noteEl = tiles[t].querySelector(".eng-note");
        if (noteEl) {
          noteEl.textContent = reading.note;
          noteEl.hidden = !reading.note;
        }
      }
      var codesEl = card.querySelector(".eng-codes");
      if (codesEl) {
        var codes = statusView.codes;
        codesEl.hidden = !codes;
        codesEl.textContent = codes ? codes.text : "";
        codesEl.setAttribute("data-tap", codes && codes.tap ? "true" : "false");
        if (codes && codes.tap) codesEl.setAttribute("role", "button");
        else codesEl.removeAttribute("role");
      }
    }

    // US-888-b: paint `rpmBarView` into `.drv-rpm-bar`. The segments are built
    // ONCE and then only their state attributes move, so a new sample is one
    // paint: the stylesheet maps data-lit / data-zone to tokens, data-stale to
    // the dim and data-redline (state-qualified, motion opt-in) to the flash.
    function renderRpmBar(bar, view) {
      if (!bar) return;
      var segs = bar.querySelectorAll(".drv-seg");
      if (segs.length !== view.segments.length) {
        bar.textContent = "";
        for (var n = 0; n < view.segments.length; n++) {
          var seg = document.createElement("span");
          seg.className = "drv-seg";
          bar.appendChild(seg);
        }
        segs = bar.querySelectorAll(".drv-seg");
      }
      for (var i = 0; i < segs.length; i++) {
        segs[i].setAttribute("data-zone", view.segments[i].zone);
        segs[i].setAttribute("data-lit", view.segments[i].lit ? "true" : "false");
      }
      bar.setAttribute("data-stale", view.stale ? "true" : "false");
      bar.setAttribute("data-redline", view.redline ? "true" : "false");
    }

    // US-507: the three merged renderers take a BODY element, not a card. They
    // used to reach for their own `.card-body`, which silently assumed one
    // source per card -- the assumption the Health card overturns. Taking the
    // slot as an argument is what lets three of them paint into one card.
    function renderBatteryHealthBody(body, view) {
      if (!body || !view) return;
      // US-429: UPS source unavailable -> the whole SECTION is a typed NA.
      if (view.unavailable) {
        renderNaBody(body, view.label, view.reason);
        return;
      }
      body.textContent = "";
      appendTile(body, view.health);
      appendTile(body, view.vcell);
      // F-8: render the percent tile only when a real SoC exists; a null soc
      // omits the percent (volts already shown above), never a voltage-as-%.
      if (view.soc.shown) appendTile(body, view.soc);
      // US-504: no TEMP tile -- the MAX17048 has no temperature register.
      // F-2 / A-6: the ladder DOM exists only when actually draining.
      if (view.ladder) appendLadder(body, view.ladder);
    }

    // --- SVG helpers + the US-892-b Motion card render (browser only) -------

    var SVG_NS = "http://www.w3.org/2000/svg";

    function svgEl(name, attrs) {
      var el = document.createElementNS(SVG_NS, name);
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k)) {
          el.setAttribute(k, String(attrs[k]));
        }
      }
      return el;
    }

    // One Motion value cell: label, value + unit, the sub-line / reason, the
    // peak line. data-none greys a '--'; data-warn colours the gyro reason.
    function paintMotionCell(cell, v, subCls) {
      if (!cell || !v) return;
      cell.setAttribute("data-none", v.none ? "true" : "false");
      if (v.warn !== undefined) cell.setAttribute("data-warn", v.warn ? "true" : "false");
      var label = cell.querySelector(".motion-label");
      if (label && v.label !== undefined) label.textContent = v.label;
      var value = cell.querySelector(".motion-value");
      if (value) value.textContent = v.value;
      var unit = cell.querySelector(".motion-unit");
      if (unit) unit.textContent = v.unit;
      var sub = cell.querySelector(subCls);
      if (sub) {
        var text = subCls === ".motion-sub" ? v.sub : v.note;
        sub.textContent = text || "";
        sub.hidden = !text;
      }
      var peak = cell.querySelector(".motion-peak");
      if (peak && v.peak !== undefined) peak.textContent = v.peak;
    }

    // The grade graph: rebuilt per paint from `motionGradeGraph` -- a handful
    // of nodes at the 1 Hz publish. One polyline per run of real points, so a
    // null point is a gap, never a line drawn across it.
    function paintMotionGraph(cell, graph) {
      if (!cell || !graph) return;
      var svg = cell.querySelector(".motion-graph");
      if (!svg) return;
      cell.setAttribute("data-empty", graph.empty ? "true" : "false");
      svg.textContent = "";
      svg.appendChild(svgEl("line", {
        class: "motion-graph-zero", x1: 0, y1: graph.zeroY,
        x2: MOTION_GRAPH_PLOT_W, y2: graph.zeroY,
      }));
      if (graph.empty) {
        var empty = svgEl("text", {
          class: "motion-graph-empty", x: 0,
          y: graph.zeroY - MOTION_GRAPH_EMPTY_RISE,
        });
        empty.textContent = graph.text;
        svg.appendChild(empty);
        return;
      }
      for (var i = 0; i < graph.segments.length; i++) {
        svg.appendChild(svgEl("polyline", {
          class: "motion-graph-line", points: graph.segments[i],
        }));
      }
      svg.appendChild(svgEl("circle", {
        class: "motion-graph-dot", cx: graph.end.x, cy: graph.end.y,
        r: MOTION_GRAPH_DOT_R,
      }));
      var label = svgEl("text", {
        class: "motion-graph-end", x: graph.end.labelX, y: graph.end.labelY,
      });
      label.textContent = graph.end.label;
      svg.appendChild(label);
    }

    // US-892-b: paint the Motion card from `motionView` + `motionGradeGraph`.
    // Before the first read the bands give way to US-700's LOADING tile; after
    // that every value carries its own '--' + reason. data-stale dims both
    // bands (the stylesheet), never blanks them.
    function renderMotionCard(card, view, graph) {
      if (!card || !view) return;
      var loading = card.querySelector(".motion-loading");
      var bands = card.querySelectorAll(".motion-band");
      if (loading) {
        loading.textContent = "";
        if (view.loading) appendTile(loading, view.tile);
        loading.hidden = !view.loading;
      }
      for (var b = 0; b < bands.length; b++) bands[b].hidden = view.loading;
      var health = card.querySelector(".motion-health");
      if (health) health.hidden = view.loading;
      card.setAttribute("data-stale", view.stale ? "true" : "false");
      if (view.loading) return;
      paintMotionCell(card.querySelector(".motion-pitch"), view.pitch, ".motion-sub");
      paintMotionCell(card.querySelector(".motion-lon"), view.lon, ".motion-note");
      paintMotionCell(card.querySelector(".motion-lat"), view.lat, ".motion-note");
      paintMotionGraph(card.querySelector(".motion-grade"), graph);
      renderMotionHealth(health, view.health);
    }

    // US-892-c: the health block. data-tone carries the status colour (the
    // stylesheet maps it to a token); the sub-line is the reason or, for TILT
    // FIX, the provenance. The block is not a .motion-band, so it never dims.
    function renderMotionHealth(block, health) {
      if (!block || !health) return;
      var cells = [
        [".motion-updated", health.updated], [".motion-compass", health.compass],
        [".motion-tilt", health.tilt], [".motion-gyro", health.gyro],
      ];
      for (var i = 0; i < cells.length; i++) {
        var cell = block.querySelector(cells[i][0]);
        var v = cells[i][1];
        if (!cell || !v) continue;
        cell.setAttribute("data-tone", v.tone);
        var value = cell.querySelector(".motion-hv");
        if (value) value.textContent = v.value;
        var sub = cell.querySelector(".motion-hsub");
        if (sub) {
          sub.textContent = v.sub || "";
          sub.hidden = !v.sub;
        }
      }
    }

    // --- US-893-b Light page DOM render (browser only) ----------------------

    // The three glyphs (Iris L4), copied from the OEM mockup unchanged and
    // stroked through the .glyph class -- never coloured. A null band has none.
    var LIGHT_GLYPH_SHAPES = {
      day: [
        ["circle", { cx: 17, cy: 17, r: 7 }],
        ["path", { d: "M17 2v5M17 27v5M2 17h5M27 17h5M6 6l3.5 3.5M24.5 24.5L28 28M6 28l3.5-3.5M24.5 9.5L28 6" }],
      ],
      night: [["path", { d: "M23 5a12 12 0 1 0 6 18A10 10 0 0 1 23 5z" }]],
      dusk: [["path", { d: "M4 24h26M9 24a8 8 0 0 1 16 0M17 8v4M7 13l3 3M27 13l-3 3" }]],
    };
    var LIGHT_DOT_R = 5;
    // [cell class, label] in grid order; RANGE carries a second, meta line.
    var LIGHT_RAW_CELLS = [
      ["light-ir", "IR"], ["light-full", "FULL"],
      ["light-visible", "VISIBLE"], ["light-range", "RANGE"],
    ];

    function lightEl(tag, cls, text) {
      var el = document.createElement(tag);
      el.className = cls;
      if (text !== undefined) el.textContent = text;
      return el;
    }

    // The page's skeleton, built into the card body. The US-700 loading tile
    // and the typed NA replace the body, so it is rebuilt after either.
    function buildLightPage(body) {
      body.textContent = "";
      var page = lightEl("div", "light-page");
      var top = lightEl("div", "light-top");
      var left = lightEl("div", "light-left");
      var tile = lightEl("div", "light-word-tile light-dimmable");
      var wordRow = lightEl("div", "light-word-row");
      wordRow.appendChild(svgEl("svg", {
        class: "glyph light-glyph", viewBox: "0 0 34 34", "aria-hidden": "true",
      }));
      wordRow.appendChild(lightEl("span", "light-word", "--"));
      tile.appendChild(wordRow);
      tile.appendChild(lightEl("span", "light-label", "AMBIENT"));
      var ambient = lightEl("span", "light-ambient");
      ambient.appendChild(lightEl("span", "light-ambient-value", "--"));
      ambient.appendChild(lightEl("span", "light-ambient-unit", ""));
      tile.appendChild(ambient);
      left.appendChild(tile);
      // Not dimmable: the reason and the age are the evidence of the state.
      var notes = lightEl("div", "light-notes");
      notes.appendChild(lightEl("span", "light-reason", ""));
      notes.appendChild(lightEl("span", "light-age", ""));
      left.appendChild(notes);
      top.appendChild(left);
      top.appendChild(svgEl("svg", {
        class: "light-curve light-dimmable",
        viewBox: "0 0 " + LIGHT_CURVE_W + " " + LIGHT_CURVE_H, "aria-hidden": "true",
      }));
      page.appendChild(top);
      var raw = lightEl("div", "light-raw light-dimmable");
      for (var i = 0; i < LIGHT_RAW_CELLS.length; i++) {
        var cell = lightEl("div", "light-cell " + LIGHT_RAW_CELLS[i][0]);
        cell.setAttribute("data-tone", "none");
        cell.appendChild(lightEl("span", "light-label", LIGHT_RAW_CELLS[i][1]));
        cell.appendChild(lightEl("span", "light-cv", "--"));
        if (LIGHT_RAW_CELLS[i][0] === "light-range") {
          cell.appendChild(lightEl("span", "light-cmeta", "--"));
        }
        raw.appendChild(cell);
      }
      page.appendChild(raw);
      var status = lightEl("div", "light-status");
      status.appendChild(lightEl("span", "light-status-label", "BRIGHTNESS"));
      status.appendChild(lightEl("span", "light-status-value", "--"));
      status.appendChild(lightEl("span", "light-status-note", ""));
      page.appendChild(status);
      body.appendChild(page);
      return page;
    }

    function paintLightGlyph(svg, band) {
      if (!svg) return;
      svg.textContent = "";
      var shapes = band ? LIGHT_GLYPH_SHAPES[band] : null;
      svg.hidden = !shapes;
      if (!shapes) return;
      for (var i = 0; i < shapes.length; i++) svg.appendChild(svgEl(shapes[i][0], shapes[i][1]));
    }

    function paintLightText(el, text) {
      if (!el) return;
      el.textContent = text || "";
      el.hidden = !text;
    }

    // The curve: rebuilt per paint from `lightCurveView` (axes, the dashed
    // curve ends and their labels, the published polyline, the dot). A missing
    // curve leaves the graph empty -- never a guessed line.
    function paintLightCurve(svg, curve) {
      if (!svg) return;
      svg.textContent = "";
      if (!curve) return;
      var a = curve.axis;
      svg.appendChild(svgEl("line", {
        class: "light-curve-axis", x1: a.x0, y1: a.yBottom, x2: a.x1, y2: a.yBottom,
      }));
      svg.appendChild(svgEl("line", {
        class: "light-curve-axis", x1: a.x0, y1: a.yTop, x2: a.x0, y2: a.yBottom,
      }));
      for (var i = 0; i < curve.yLabels.length; i++) {
        var yl = svgEl("text", { class: "light-curve-label", x: 0, y: curve.yLabels[i].y });
        yl.textContent = curve.yLabels[i].text;
        svg.appendChild(yl);
      }
      for (var j = 0; j < curve.verticals.length; j++) {
        var v = curve.verticals[j];
        svg.appendChild(svgEl("line", {
          class: "light-curve-end", x1: v.x, y1: a.yTop, x2: v.x, y2: a.yBottom,
        }));
        var xl = svgEl("text", {
          class: "light-curve-label", x: v.labelX, y: curve.labelY, "text-anchor": v.anchor,
        });
        xl.textContent = v.label;
        svg.appendChild(xl);
      }
      svg.appendChild(svgEl("polyline", { class: "light-curve-line", points: curve.points }));
      if (curve.dot) {
        svg.appendChild(svgEl("circle", {
          class: "light-curve-dot", cx: curve.dot.x, cy: curve.dot.y, r: LIGHT_DOT_R,
        }));
      }
    }

    // US-893-b: paint `lightPageView` into the Light card body. Text and
    // state attributes only -- data-stale dims the word tile, the curve and the
    // raw row (never the notes or the status); data-tone / data-none map to
    // tokens in the stylesheet.
    function renderLightBody(body, view) {
      if (!body || !view) return;
      var page = body.querySelector(".light-page") || buildLightPage(body);
      page.setAttribute("data-stale", view.stale ? "true" : "false");
      paintLightGlyph(page.querySelector(".light-glyph"), view.word.glyph);
      var word = page.querySelector(".light-word");
      word.textContent = view.word.text;
      word.setAttribute("data-none", view.word.glyph ? "false" : "true");
      var ambient = page.querySelector(".light-ambient");
      ambient.setAttribute("data-none", view.ambient.none ? "true" : "false");
      page.querySelector(".light-ambient-value").textContent = view.ambient.value;
      page.querySelector(".light-ambient-unit").textContent =
        view.ambient.unit ? " " + view.ambient.unit : "";
      paintLightText(page.querySelector(".light-reason"), view.reason);
      var age = page.querySelector(".light-age");
      paintLightText(age, view.age ? view.age.text : null);
      age.setAttribute("data-tone", view.age ? view.age.tone : "none");
      paintLightCurve(page.querySelector(".light-curve"), view.curve);
      var cells = { "light-ir": view.raw.ir, "light-full": view.raw.full, "light-visible": view.raw.visible };
      for (var i = 0; i < LIGHT_RAW_CELLS.length; i++) {
        var cls = LIGHT_RAW_CELLS[i][0];
        var cell = page.querySelector("." + cls);
        if (!cell) continue;
        if (cls === "light-range") {
          var noRange = view.raw.range.gain === "--" && view.raw.range.ms === "--";
          cell.setAttribute("data-tone", noRange ? "none" : "plain");
          cell.querySelector(".light-cv").textContent = view.raw.range.gain;
          cell.querySelector(".light-cmeta").textContent = view.raw.range.ms;
          continue;
        }
        cell.setAttribute("data-tone", cells[cls].tone);
        cell.querySelector(".light-cv").textContent = cells[cls].value;
      }
      page.querySelector(".light-status-label").textContent = view.status.label;
      page.querySelector(".light-status-value").textContent = view.status.value;
      paintLightText(page.querySelector(".light-status-note"), view.status.note);
    }

    // US-896-a: the NAV tape (spec s3) -- full width, the 90-degree window over
    // NAV_TAPE_W user units, so offset -1..1 maps edge to edge. Tick heights
    // and the letter baseline are the OEM mockup's (2026-10-15), measured from
    // the band's bottom edge. The hairline is drawn LAST so no tick covers it.
    var NAV_TAPE_W = 456;
    var NAV_TAPE_H = 70;
    var NAV_TICK_LEN = { major: 30, minor: 18, fine: 8 };
    var NAV_HAIRLINE_LEN = 34;
    var NAV_LABEL_Y = 28;

    function buildNavTape() {
      var svg = svgEl("svg", {
        class: "nav-tape", viewBox: "0 0 " + NAV_TAPE_W + " " + NAV_TAPE_H,
        "aria-hidden": "true",
      });
      svg.appendChild(svgEl("line", {
        class: "nav-tape-base", x1: 0, x2: NAV_TAPE_W,
        y1: NAV_TAPE_H - 0.5, y2: NAV_TAPE_H - 0.5,
      }));
      svg.appendChild(svgEl("g", { class: "nav-tape-ticks" }));
      svg.appendChild(svgEl("line", {
        class: "nav-tape-hairline", x1: NAV_TAPE_W / 2, x2: NAV_TAPE_W / 2,
        y1: NAV_TAPE_H - NAV_HAIRLINE_LEN, y2: NAV_TAPE_H,
      }));
      return svg;
    }

    function renderNavTape(svg, tape) {
      var group = svg.querySelector(".nav-tape-ticks");
      if (!group) return;
      group.textContent = "";
      if (!tape || !tape.available) return;
      for (var i = 0; i < tape.ticks.length; i++) {
        var t = tape.ticks[i];
        var x = (NAV_TAPE_W / 2 + t.offset * NAV_TAPE_W / 2).toFixed(1);
        group.appendChild(svgEl("line", {
          class: "nav-tick nav-tick-" + t.tier,
          x1: x, x2: x, y1: NAV_TAPE_H - NAV_TICK_LEN[t.tier], y2: NAV_TAPE_H,
        }));
        if (t.label) {
          var text = svgEl("text", {
            class: t.label === "N" ? "nav-tape-label nav-tape-north" : "nav-tape-label",
            x: x, y: NAV_LABEL_Y, "text-anchor": "middle",
          });
          text.textContent = t.label;
          group.appendChild(text);
        }
      }
    }

    // Paint the NAV heading half into its FIXED skeleton (dashboard.html). The
    // tape is BUILT only while there is a bearing to draw and REMOVED for a
    // dead sensor -- not hidden, not zero-opacity (spec AC 6). Digits and the
    // point follow the DRAWN bearing, so they always agree with the hairline.
    function renderNavCard(card, view, drawnDeg) {
      if (!card || !view) return;
      card.setAttribute("data-heading", view.state);
      var badge = card.querySelector(".nav-badge");
      if (badge) {
        badge.textContent = view.badge || "";
        badge.hidden = !view.badge;
      }
      var badgeNote = card.querySelector(".nav-badge-note");
      if (badgeNote) {
        badgeNote.textContent = view.badgeNote || "";
        badgeNote.hidden = !view.badgeNote;
      }
      var band = card.querySelector(".nav-band");
      if (!band) return;
      var tapeEl = band.querySelector(".nav-tape");
      var drawTape = view.tape && drawnDeg !== null;
      if (drawTape) {
        if (!tapeEl) {
          tapeEl = buildNavTape();
          band.appendChild(tapeEl);
        }
        renderNavTape(tapeEl, navTape(drawnDeg));
      } else if (tapeEl) {
        band.removeChild(tapeEl);
      }
      var blank = band.querySelector(".nav-blank");
      if (blank) {
        blank.hidden = drawTape;
        var head = blank.querySelector(".nav-blank-head");
        // NO HEADING only for a dead sensor; before the first reading the band
        // just says what it is waiting for (spec s7).
        if (head) head.hidden = view.tape;
        var why = blank.querySelector(".nav-blank-note");
        if (why) why.textContent = view.tape ? NAV_WAITING_TEXT : view.reason;
      }
      var digits = card.querySelector(".nav-digits");
      if (digits) {
        digits.textContent = fmtHeadingDigits(drawTape ? drawnDeg : null);
        digits.setAttribute("data-none", drawTape ? "false" : "true");
      }
      var point = card.querySelector(".nav-point");
      if (point) point.textContent = drawTape ? compassPoint8(drawnDeg) : "";
    }

    // US-896-b: the slope glyph's line in its 20 x 20 box, per sign. Up rises
    // to the right (climbing), down falls, flat is level.
    var NAV_SLOPE_LINE = {
      up: { y1: 18, y2: 2 },
      down: { y1: 2, y2: 18 },
      flat: { y1: 10, y2: 10 },
    };

    // Paint GRADE (spec s4.3): the value, the glyph tilted by its sign, and a
    // null's reason on the glass beneath the '--'.
    function renderNavGrade(card, view) {
      if (!card || !view) return;
      var cell = card.querySelector(".nav-grade");
      if (!cell) return;
      cell.setAttribute("data-slope", view.slope || "none");
      var value = cell.querySelector(".nav-grade-value");
      if (value) {
        value.textContent = view.value;
        value.setAttribute("data-none", view.slope ? "false" : "true");
      }
      var glyph = cell.querySelector(".nav-slope");
      if (glyph) {
        glyph.hidden = !view.slope;
        var line = glyph.querySelector(".nav-slope-line");
        var ends = view.slope ? NAV_SLOPE_LINE[view.slope] : null;
        if (line && ends) {
          line.setAttribute("y1", ends.y1);
          line.setAttribute("y2", ends.y2);
        }
      }
      var note = cell.querySelector(".nav-grade-note");
      if (note) {
        note.textContent = view.reason || "";
        note.hidden = !view.reason;
      }
    }

    // Paint the trip (spec s4.4): the label (SINCE + its mono h:mm when the
    // window is partial), the distance in miles and the elapsed h:mm, all as
    // navTripView resolved them from the provider.
    function renderNavTrip(card, view) {
      if (!card || !view) return;
      var cell = card.querySelector(".nav-trip");
      if (!cell) return;
      cell.setAttribute("data-window", view.window);
      var label = cell.querySelector(".nav-trip-label");
      if (label) label.textContent = view.label;
      var time = cell.querySelector(".nav-trip-time");
      if (time) {
        time.textContent = view.time || "";
        time.hidden = !view.time;
      }
      var distance = cell.querySelector(".nav-trip-distance");
      if (distance) {
        distance.textContent = view.distance;
        distance.setAttribute("data-none", view.measured ? "false" : "true");
      }
      var elapsed = cell.querySelector(".nav-trip-elapsed");
      if (elapsed) elapsed.textContent = view.elapsed;
    }

    // --- US-890-a Fuel card trend row DOM render (browser only) -------------

    // The chart: dashed baseline, the flat median line, then the dots on top.
    // Every stroke is non-scaling (CSS), so the stretched viewBox keeps a dot
    // round: each dot is a zero-length line drawn by its round cap.
    function buildFuelTrendChart(chart) {
      var svg = svgEl("svg", {
        class: "fuel-trend-chart", viewBox: "0 0 " + FUEL_TREND_W + " " + FUEL_TREND_H,
        preserveAspectRatio: "none", "aria-hidden": "true",
      });
      if (chart.baseline) {
        svg.appendChild(svgEl("line", {
          class: "fuel-trend-baseline", x1: 0, x2: FUEL_TREND_W,
          y1: chart.baseline.y, y2: chart.baseline.y,
        }));
      }
      svg.appendChild(svgEl("line", {
        class: "fuel-trend-median", x1: chart.median.x1, x2: chart.median.x2,
        y1: chart.median.y, y2: chart.median.y,
      }));
      for (var i = 0; i < chart.dots.length; i++) {
        var dot = chart.dots[i];
        svg.appendChild(svgEl("line", {
          class: "fuel-trend-dot", "data-drive": dot.driveId === null ? "" : dot.driveId,
          x1: dot.x, x2: dot.x, y1: dot.y, y2: dot.y,
        }));
      }
      return svg;
    }

    // `fuelTrendView` into the card's `.fuel-trend` slot. data-level is the
    // only colour input (the stylesheet maps it); textContent only.
    function renderFuelTrendBody(body, view) {
      if (!body || !view) return;
      body.textContent = "";
      var row = document.createElement("div");
      row.className = "fuel-trend-row";
      row.setAttribute("data-level", view.level);
      row.appendChild(engineTextEl("span", "fuel-label", view.label));
      if (view.sufficient) row.appendChild(engineTextEl("span", "fuel-trend-value", view.value));
      else row.appendChild(engineTextEl("span", "fuel-trend-reason", view.reason));
      if (view.chart) row.appendChild(buildFuelTrendChart(view.chart));
      body.appendChild(row);
    }

    // --- US-540-b source card DOM render (browser only) ---------------------

    // One source card. The gate + the fault BOTH render the shared typed-NA
    // tile, but they carry different words and are told apart in the DOM by
    // `data-gated` -- so the render backstop can prove a bench painted the GATE
    // rather than a fabricated trim, which is the one thing a pure-function
    // test can never see. The flag is written on EVERY paint, including the
    // ungated one: left write-only-when-true it would latch, and a card that
    // says "gated" after the engine started is a stale claim about the vehicle.
    function renderSourceCard(card, view) {
      if (!card || !view) return;
      // US-890-a: a source with a `slot` paints only that part of its card
      // (the Fuel card's trend row); every other source owns the whole body.
      var spec = sourceCardSpec(view.key);
      var body = card.querySelector(spec && spec.slot ? spec.slot : ".card-body");
      if (!body) return;
      card.setAttribute("data-gated", view.gated ? "true" : "false");
      // The typed NA is the card's whole body here, so the shipped
      // `.unavailable` italic-gray must not also apply -- the tile carries its
      // own honest styling and the two together read as a doubly-dead card.
      card.classList.toggle("unavailable", false);
      // US-700: checked BEFORE the NA branch. A card still inside its loading
      // bound has nothing to be typed-NA about yet.
      if (view.loading) {
        renderLoadingBody(body, view.label);
        return;
      }
      // US-893-b: an unavailable card WITH a view (the Light page's own
      // absence) paints that view; every other unavailable card is the NA.
      if (view.gated || (view.unavailable && !view.view)) {
        renderNaBody(body, view.na.label, view.na.reason);
        return;
      }
      if (view.key === "battery-health") renderBatteryHealthBody(body, view.view);
      else if (view.key === "light") renderLightBody(body, view.view);
      else if (view.key === "ltft-trend") renderFuelTrendBody(body, view.view);
    }

    // US-482 letterbox: uniformly scale the fixed 480x320 #stage design box to
    // fill the real panel. The transformed #stage becomes the containing block
    // for its fixed/absolute descendants, so the shipped layout inside it is
    // untouched -- only the outer scale changes. Idempotent + null-safe.
    function applyStageScale() {
      var stage = document.getElementById("stage");
      if (!stage) return;
      var scale = computeStageScale(window.innerWidth, window.innerHeight);
      stage.style.setProperty("--scale", String(scale));
    }

    // US-542 AC-1: the wall clock, moved off the retired parked face into the
    // PERSISTENT top bar. The clock was never a parked-state fact -- it was
    // only ever on that screen because that screen was what a parked operator
    // saw. In the bar it is readable from every card, including the live IMU
    // face that replaced the one it used to live on.
    //
    // It reuses `fmtClock` (US-503, pure + pinned) rather than formatting here:
    // two formatters is how the 12-hour face drifts back to 24-hour on one
    // surface while every test of the other stays green.
    //
    // BLOCK SCOPE, not setup's, and that is not a style choice: the 4 Hz tick
    // lives inside `startAvailabilityPoll`, which setup CALLS rather than
    // encloses -- a painter declared in setup is invisible from there, and the
    // first tick throws a ReferenceError that kills the whole poll loop.
    var clockEl = null;
    var lastClockText = null;
    function renderTopbarClock(now) {
      // Resolved lazily + cached: this block is evaluated before DOMContentLoaded
      // on the slow path, where an eager lookup would cache a permanent null.
      if (!clockEl) clockEl = document.getElementById("topbar-clock");
      if (!clockEl) return;
      var text = fmtClock(now);
      // Write only on a real change. The caller ticks at 4 Hz and the face moves
      // once a minute, so an unguarded write is ~240 pointless DOM mutations per
      // minute on the one surface that is ALWAYS painted -- and needless
      // always-on repaint work on this panel has a history (US-537: the
      // always-on compositor layer behind the US-522 freeze).
      if (text === lastClockText) return;
      lastClockText = text;
      clockEl.textContent = text;
    }

    // US-898-a: paint the warnings icon (alertIconView). Block scope, beside the
    // clock, for the clock's reason: the 4 Hz tick inside startAvailabilityPoll
    // calls it. Writes only on a change, like the clock. It never sets
    // `hidden`: the icon is the always-visible state (Iris U1).
    var warnIconEl = null;
    var lastWarnIconKey = null;
    function renderTopbarIcon(view) {
      if (!warnIconEl) warnIconEl = document.getElementById("glyph-warnings");
      if (!warnIconEl) return;
      var key = view.state + "|" + view.text + "|" + view.pulse;
      if (key === lastWarnIconKey) return;
      lastWarnIconKey = key;
      warnIconEl.textContent = view.text;
      warnIconEl.setAttribute("data-state", view.state);
      warnIconEl.setAttribute("data-pulse", view.pulse ? "true" : "false");
    }

    // US-901-b: paint the not-live marker and hide the clock under it. Block
    // scope, beside the clock, for the same reason the clock lives here: the
    // 4 Hz tick calls it from inside `startAvailabilityPoll`. Writes only on a
    // change, like the clock.
    var markerEl = null;
    var lastMarkerKey = null;
    function renderNotLiveMarker(marker) {
      if (!markerEl) markerEl = document.getElementById("not-live-marker");
      if (!clockEl) clockEl = document.getElementById("topbar-clock");
      if (!markerEl) return;
      var key = marker ? marker.text + "|" + marker.tier : "";
      if (key === lastMarkerKey) return;
      lastMarkerKey = key;
      markerEl.textContent = marker ? marker.text : "";
      markerEl.setAttribute("data-tier", marker ? marker.tier : "label");
      markerEl.hidden = !marker;
      if (clockEl) clockEl.classList.toggle("masked", !!marker);
    }

    var setup = function () {
      // Scale first, then wire re-scale on any viewport change (rotation /
      // resolution change / the panel reporting late at boot).
      applyStageScale();
      window.addEventListener("resize", applyStageScale);

      var track = document.getElementById("track");
      var dotsNav = document.getElementById("dots");
      // US-887-c: the top bar names the current page (frame spec s3.2).
      var pageNameEl = document.getElementById("page-name");
      var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));
      var count = cards.length;
      var current = 0;
      var glyphEls = {
        bt: document.getElementById("glyph-bt"),
        sync: document.getElementById("glyph-sync"),
        wifi: document.getElementById("glyph-wifi"),
      };

      // US-542: paint the top-bar clock once at boot so the slot is never blank
      // for the length of the first poll. The painter itself lives at block
      // scope -- see renderTopbarClock -- because the 4 Hz tick that keeps it
      // current runs inside startAvailabilityPoll, which is NOT nested here.
      renderTopbarClock(new Date());

      // Build one page dot per card (>=40px touch target via .tap-target CSS).
      var dots = [];
      for (var i = 0; i < count; i++) {
        var dot = document.createElement("button");
        dot.className = "dot tap-target";
        dot.setAttribute("aria-label", "card " + (i + 1));
        (function (idx) {
          dot.addEventListener("click", function () { goTo(idx); });
        })(i);
        dotsNav.appendChild(dot);
        dots.push(dot);
      }

      // US-496: the per-card visibility flags, read straight off the DOM so the
      // carousel geometry can never disagree with what is actually painted. A
      // vehicle-gated card is removed from the flex row by the US-495 [hidden]
      // guard, so it owns no slot and no page dot.
      function hiddenFlags() {
        var flags = [];
        for (var h = 0; h < cards.length; h++) flags.push(!!cards[h].hidden);
        return flags;
      }

      function render() {
        var flags = hiddenFlags();
        if (track) {
          var pos = visualPosition(current, flags);
          track.style.transform = "translateX(" + (-pos * 100) + "%)";
        }
        for (var d = 0; d < dots.length; d++) {
          // A hidden card owns no dot: a dot that navigates nowhere is the same
          // dead affordance as the card behind it.
          dots[d].hidden = flags[d];
          dots[d].classList.toggle("active", d === current);
        }
        // US-887-c: the bar's page name follows the SAME `current` the track
        // and the active dot read, so the three can never name different
        // pages. Read off the card's own `data-page-name` -- one registry, the
        // `.card` query, exactly as the dots are built from it.
        if (pageNameEl && cards[current]) {
          pageNameEl.textContent = cards[current].getAttribute("data-page-name") || "";
        }
      }

      function goTo(idx) {
        var target = clampIndex(idx, count);
        // Never navigate ONTO a hidden card -- that paints a blank frame the
        // operator cannot see their way out of.
        if (hiddenFlags()[target]) return;
        current = target;
        render();
      }

      function move(dir) {
        current = nextVisibleIndex(current, dir, hiddenFlags());
        render();
      }

      // US-496: the poll calls this after it flips a vehicle-gated card. If the
      // card the operator was ON just vanished (the vehicle unplugged), land on
      // the nearest visible one rather than holding a dead index.
      function onVisibilityChange() {
        var flags = hiddenFlags();
        if (flags[current]) {
          var near = nearestVisibleIndex(current, flags);
          if (near !== null) current = near;
        }
        render();
      }

      // --- US-506 (AC-13/AC-14/AC-15) auto-rotate + pause state -------------
      // The carousel is hands-off by default and pauses the moment the operator
      // engages, so it never moves under someone who is reading it -- and the
      // pause SELF-EXPIRES so it can never freeze forever.
      var paused = false;
      var lastAdvanceMs = Date.now();
      var lastInteractionMs = Date.now();
      var rotateBar = document.getElementById("rotate-progress");
      var rotateFill = document.getElementById("rotate-progress-fill");

      // One pause entry point. Every interaction routes here (a tap on a card, a
      // page dot, the kebab, any overlay button, a settle swipe, an arrow key),
      // because it is hung on `document` -- so an overlay added later cannot
      // forget to pause, which a per-overlay call site inevitably would.
      function pauseAutoRotate() {
        paused = true;
        lastInteractionMs = Date.now();
        renderRotateBar();
      }

      // Resume restarts the clock as well as clearing the flag: resuming into a
      // period that has already elapsed would snap to the next card instantly,
      // which reads as the flick having advanced TWO cards.
      function resumeAutoRotate() {
        paused = false;
        lastAdvanceMs = Date.now();
        lastInteractionMs = Date.now();
        renderRotateBar();
      }

      // The calm thin time-to-next bar (AC-13 -- a bar, never a countdown
      // number). A PAUSED carousel has no time-to-next, so the bar is REMOVED
      // rather than left frozen part-filled: a stalled progress bar is the same
      // fabrication as a frozen instrument -- it says "something is coming" when
      // nothing is. Absent elements are tolerated (file:// preview).
      function renderRotateBar() {
        if (!rotateBar) return;
        rotateBar.hidden = paused;
        if (paused || !rotateFill) return;
        var frac = rotateProgress(Date.now() - lastAdvanceMs, carouselCfg.autoRotateS);
        rotateFill.style.setProperty("--rotate-fill", String(frac));
      }

      // Redrawn on the shipped 4 Hz tick: over the 8 s default period that is 32
      // steps, which reads as smooth on a 480x320 panel without a second clock.
      function autoRotateTick() {
        if (shouldAutoResume(paused, Date.now() - lastInteractionMs, carouselCfg.resumeIdleS)) {
          resumeAutoRotate();
        }
        if (shouldAutoAdvance(paused, Date.now() - lastAdvanceMs, carouselCfg.autoRotateS)) {
          move(1);
          lastAdvanceMs = Date.now();
        }
        renderRotateBar();
      }

      // Pointer-driven swipe (covers touch + mouse on the kiosk). Vertical drag
      // is ignored (touch-action: pan-y) so the panel can still scroll a card.
      // US-506: pointer-down time is now recorded too -- the velocity model
      // needs the gesture DURATION, which the distance-only version discarded.
      var startX = null;
      var startY = null;
      var startMs = null;
      if (track) {
        track.addEventListener("pointerdown", function (e) {
          startX = e.clientX; startY = e.clientY; startMs = Date.now();
        });
        track.addEventListener("pointerup", function (e) {
          if (startX === null) return;
          var dx = e.clientX - startX;
          var dy = e.clientY - startY;
          var dt = Date.now() - startMs;
          startX = null; startY = null; startMs = null;
          // Measure the fraction against the REAL card box, not the design-box
          // constant: #stage is letterbox-scaled (US-482), so a hard-coded 480
          // would misread travel on any panel that is not 1:1.
          var width = track.getBoundingClientRect
            ? track.getBoundingClientRect().width
            : 0;
          var g = swipeGesture(dx, dy, dt, width, carouselCfg);
          if (g.dir === 0) return; // a tap or a vertical drag -- pointerdown
                                   // already paused; leave it paused.
          move(g.dir);
          // A FLICK says "keep going" -> resume. A SETTLE says "I want to look
          // at this one" -> stay paused. This is the whole point of the velocity
          // model: the distance-only swipe could not tell these apart.
          if (g.fast) resumeAutoRotate();
          else pauseAutoRotate();
        });
      }

      // Any pointer contact anywhere is an interaction: pause first, and let the
      // gesture handler above resume if it turns out to be a flick. Pausing on
      // DOWN (not up) means the carousel stops the instant a finger lands,
      // rather than advancing out from under a slow deliberate press.
      document.addEventListener("pointerdown", function () {
        pauseAutoRotate();
      });

      // Keyboard arrows (bench/dev affordance; harmless on a touch panel). An
      // arrow is a deliberate single-card move -- a settle, not a flick.
      document.addEventListener("keydown", function (e) {
        if (e.key === "ArrowLeft") { move(-1); pauseAutoRotate(); }
        else if (e.key === "ArrowRight") { move(1); pauseAutoRotate(); }
      });

      setInterval(autoRotateTick, POLL_MS);

      render();
      renderRotateBar();
      startAvailabilityPoll(cards, glyphEls, goTo, onVisibilityChange);
      setupMenu();
    };

    // --- US-403 System Setup menu DOM (browser only) -----------------------

    // POST an allow-listed action to the state server's /service-control route.
    // The kiosk is unprivileged; polkit authorizes the systemctl call and the
    // server re-checks the allow-list. Failures surface in the menu status line
    // (no console logging, never a fabricated success).
    function postAction(unit, verb, statusEl) {
      if (!actionRequest(unit, verb)) {
        if (statusEl) statusEl.textContent = unit + " " + verb + ": not permitted";
        return;
      }
      if (statusEl) statusEl.textContent = verb + " " + unit + " …";
      var headers = { "Content-Type": "application/json" };
      if (token) headers["X-Splash-Token"] = token;
      fetch("/service-control", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ unit: unit, verb: verb }),
      })
        .then(function (r) {
          return r.json().then(null, function () { return { ok: false }; });
        })
        .then(function (res) {
          if (!statusEl) return;
          statusEl.textContent = res.ok
            ? verb + " " + unit + " ok"
            : verb + " " + unit + " failed: " + (res.reason || res.error || "");
        })
        .then(null, function () {
          if (statusEl) statusEl.textContent = verb + " " + unit + " failed";
        });
    }

    // US-659: `applyMenuAccess` / `updateMenuAccess` / the `parkedSignal`
    // debounce state stood here and painted the `⋮` per tick. All removed with
    // the ruling -- the button now simply ships visible and stays visible. See
    // the note at the retired `menuAccess` above.

    function setupMenu() {
      var menu = document.getElementById("setup-menu");
      if (!menu) return;
      var menuBtn = document.getElementById("menu-btn");
      var closeBtn = document.getElementById("menu-close");
      var list = document.getElementById("svc-list");
      var settingsList = document.getElementById("settings-list");
      var statusEl = document.getElementById("menu-status");
      var exitBtn = document.getElementById("menu-exit");
      var ring = document.getElementById("longpress-ring");
      var confirmModal = document.getElementById("confirm-modal");
      var confirmText = document.getElementById("confirm-text");
      var confirmOk = document.getElementById("confirm-ok");
      var confirmCancel = document.getElementById("confirm-cancel");

      function hideConfirm() {
        if (confirmModal) confirmModal.hidden = true;
      }
      function openMenu() {
        buildList();
        // US-532: rebuilt on every open, not once at boot -- a save made in a
        // previous open must not leave a stale value sitting behind the ⋮.
        buildSettings();
        menu.hidden = false;
      }
      function closeMenu() {
        menu.hidden = true;
        hideConfirm();
      }
      // Consequential actions (Stop, Exit) require a confirm; ✕/Cancel always
      // returns control (the user is never trapped).
      function askConfirm(message, onYes) {
        if (!confirmModal) {
          onYes();
          return;
        }
        if (confirmText) confirmText.textContent = message;
        confirmModal.hidden = false;
        confirmOk.onclick = function () {
          hideConfirm();
          onYes();
        };
        confirmCancel.onclick = hideConfirm;
      }
      function doAction(unit, verb) {
        var req = actionRequest(unit, verb);
        if (!req) return;
        if (req.confirm) {
          askConfirm(verb + " " + unit + "?", function () {
            postAction(unit, verb, statusEl);
          });
        } else {
          postAction(unit, verb, statusEl);
        }
      }

      function buildList() {
        if (!list) return;
        list.textContent = "";
        var items = serviceMenuItems();
        for (var i = 0; i < items.length; i++) {
          (function (item) {
            var row = document.createElement("div");
            row.className = "svc-row";
            var nm = document.createElement("span");
            nm.className = "svc-name";
            nm.textContent = item.label + " · " + item.sub;
            row.appendChild(nm);

            var restart = document.createElement("button");
            restart.className = "svc-btn tap-target";
            restart.textContent = "Restart";
            restart.addEventListener("click", function () {
              doAction(item.unit, "restart");
            });
            row.appendChild(restart);

            var stop = document.createElement("button");
            stop.className = "svc-btn tap-target";
            stop.textContent = "Stop";
            // F-7 / D-7 / I-10: the safe-shutdown guard has no working Stop.
            if (!item.canStop) {
              stop.disabled = true;
              stop.title = "safe-shutdown guard — restart only";
            } else {
              stop.addEventListener("click", function () {
                doAction(item.unit, "stop");
              });
            }
            row.appendChild(stop);
            list.appendChild(row);
          })(items[i]);
        }
      }

      // --- US-532 (F-126) Settings band --------------------------------------

      // Persist ONE setting through the US-531 token-gated route -- the only
      // write path there is; the kiosk is sandboxed and cannot touch the
      // filesystem itself. `render` is the SAME closure that painted the row on
      // open, so the value shown after a save and the value shown after a page
      // reload can never come from different code.
      //
      // Deliberately NO confirm: these are non-destructive preferences, and
      // borrowing the service-control confirm would train the operator to
      // dismiss the modal that guards a service stop (Iris §4).
      function postSetting(spec, desired, render, currentValue) {
        // The pending paint keeps the value we already know is stored -- it must
        // not show the REQUESTED one, which is the optimistic success Iris ruled
        // out wearing a nicer label.
        render(currentValue, settingsPendingNote());
        var headers = { "Content-Type": "application/json" };
        if (token) headers["X-Splash-Token"] = token;
        fetch("/settings", {
          method: "POST",
          headers: headers,
          body: JSON.stringify({
            key: spec.key,
            value: settingsWriteValue(spec, desired),
          }),
        })
          .then(function (r) {
            return r.json().then(null, function () { return null; });
          })
          .then(function (res) {
            var out = settingsSaveResult(res);
            // Repaint FIRST, unconditionally: the operator must see the REAL
            // stored value even if the reload below is slow, blocked, or never
            // due -- the truth must not depend on the apply mechanism firing.
            render(out.value, out.note);
            // US-533 B1: the row said "applies on reload", so this is where the
            // band keeps that promise. The server resolves pi.display.carousel
            // per request, so the reloaded page picks the new period up with NO
            // eclipse-states-http restart (which polkit denies anyway).
            if (settingsReloadNeeded(spec, res)) {
              setTimeout(function () {
                location.reload();
              }, SETTINGS_RELOAD_DELAY_MS);
            }
          })
          .then(null, function () {
            // A rejected fetch tells us nothing about what is stored -> Unknown.
            render(null, settingsSaveResult(null).note);
          });
      }

      function buildSettings() {
        if (!settingsList) return;
        settingsList.textContent = "";
        var specs = settingsSpecs();
        for (var i = 0; i < specs.length; i++) {
          (function (spec) {
            var row = document.createElement("div");
            row.className = "set-row";
            var name = document.createElement("span");
            name.className = "set-name";
            name.textContent = spec.label;
            row.appendChild(name);
            var note = document.createElement("span");
            note.className = "set-apply";
            row.appendChild(note);
            var controls = document.createElement("div");
            controls.className = "set-controls";
            row.appendChild(controls);

            var choices = settingsChoices(spec);

            // The ONE paint path for this row. Built with textContent (no
            // innerHTML) so a config value can never become markup.
            function render(value, statusNote) {
              var view = settingsRowView(spec, value);
              note.textContent = statusNote
                ? view.applyNote + " · " + statusNote
                : view.applyNote;
              controls.textContent = "";
              for (var c = 0; c < choices.length; c++) {
                (function (choice) {
                  var btn = document.createElement("button");
                  btn.className = "set-btn tap-target";
                  btn.textContent = choice.label;
                  btn.setAttribute(
                    "aria-pressed",
                    String(settingsChoiceActive(view, choice.value))
                  );
                  btn.addEventListener("click", function () {
                    postSetting(spec, choice.value, render, view.value);
                  });
                  controls.appendChild(btn);
                })(choices[c]);
              }
            }

            // US-878-c: a not-found entry is null here, i.e. Unknown.
            render(settingsEntry(settingsSource, spec.key).value, "");
            settingsList.appendChild(row);
          })(specs[i]);
        }
      }

      if (menuBtn) {
        // US-659: the `if (menuBtn.hidden) return;` guard was US-490's defence
        // in depth for a gate that no longer exists. Kept, it would be a silent
        // restore point -- re-add `hidden` in the markup and the tap dies with
        // nothing else changing, which is the failure this ruling is about.
        menuBtn.addEventListener("click", openMenu);
      }
      if (closeBtn) closeBtn.addEventListener("click", closeMenu);
      if (exitBtn) {
        // Exit / Close UI (A-8): a dashboard stop -> drops to desktop; the
        // splash hand-off re-launches it on the next reboot.
        exitBtn.addEventListener("click", function () {
          doAction("eclipse-dashboard.service", "stop");
        });
      }

      // Long-press anywhere on the carousel opens the menu (D-6). A filling ring
      // gives feedback after the arm delay; movement or an early release cancels.
      //
      // US-747: the SAME hold on the open menu closes it -- a second way out
      // that does not depend on the ✕ (the one control is exactly what failed).
      //
      // US-747 root cause, and why each press OWNS its interval: this used to
      // keep the interval in `timer` alone. A second pointerdown before the
      // pointerup (a second finger, a palm) overwrote it, the first interval was
      // never cleared, and after the release nulled `pressStart` it read
      // `Date.now() - null` -- always past the hold -- and re-opened the menu on
      // every tick. ✕ closed it; the orphan opened it again 50 ms later.
      var carousel = document.getElementById("carousel");
      if (ring) {
        var pressStart = null;
        var pressX = 0;
        var pressY = 0;
        var timer = null;
        var armed = false;
        function clearPress() {
          pressStart = null;
          armed = false;
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
          ring.hidden = true;
          ring.style.setProperty("--fill", "0");
        }
        function startPress(e) {
          // A new contact restarts the hold rather than stacking a second one.
          clearPress();
          pressStart = Date.now();
          pressX = e.clientX;
          pressY = e.clientY;
          var id = setInterval(function () {
            // Belt and braces: an interval that is not the live press, or that
            // outlived it, stops itself instead of reading a null start.
            if (timer !== id || pressStart === null) {
              clearInterval(id);
              return;
            }
            var elapsed = Date.now() - pressStart;
            if (elapsed >= LONG_PRESS_ARM_MS && !armed) {
              armed = true;
              ring.hidden = false;
            }
            if (armed) {
              ring.style.setProperty("--fill", String(longPressProgress(elapsed)));
            }
            if (isLongPressComplete(elapsed)) {
              clearPress();
              if (menu.hidden) openMenu();
              else closeMenu();
            }
          }, 50);
          timer = id;
        }
        function movePress(e) {
          if (pressStart === null) return;
          if (exceedsMoveCancel(e.clientX - pressX, e.clientY - pressY)) clearPress();
        }
        if (carousel) {
          carousel.addEventListener("pointerdown", startPress);
          carousel.addEventListener("pointermove", movePress);
          carousel.addEventListener("pointerup", clearPress);
          carousel.addEventListener("pointercancel", clearPress);
        }
        menu.addEventListener("pointerdown", startPress);
        menu.addEventListener("pointermove", movePress);
        menu.addEventListener("pointerup", clearPress);
        menu.addEventListener("pointercancel", clearPress);
      }
    }

    // Honest-instrument poll: fetch each card's state file; missing/malformed ->
    // `unavailable` (never a crash, never green-when-broken). The shell sets the
    // availability class; the per-card renderer (US-400 system-status; US-401
    // battery-health) paints the fields on top when available.
    function startAvailabilityPoll(cards, glyphEls, goTo, onVisibilityChange) {
      async function fetchState(name) {
        try {
          var init = {
            cache: "no-store",
            headers: token ? { "X-Splash-Token": token } : {},
          };
          // US-653: bound the request. An abort THROWS, which the catch below
          // already turns into a null read -- so the tick completes honestly
          // instead of hanging. Guarded for absence so the module still loads
          // where AbortSignal.timeout is unavailable.
          if (typeof AbortSignal !== "undefined" && AbortSignal.timeout) {
            init.signal = AbortSignal.timeout(FETCH_DEADLINE_MS);
          }
          var r = await fetch("/" + name, init);
          if (!r.ok) return null;
          return await r.json();
        } catch (e) {
          // US-655: an abort is a HANG we survived -- say so. Everything else
          // stays a quiet null, exactly as before.
          reportFetchAbort(name, e, uiLog);
          return null;
        }
      }

      // US-899-a1 (Iris U12): the ONE token-gated POST behind every write on
      // this page -- /dtc-clear, /fuel-reset and /alerts-ack (postAction stays
      // the /service-control helper). It answers {status, body} and never
      // judges either: each caller keeps its own honest-write rule (confirm
      // from a RE-READ, or say it failed). A body that is not JSON is {}; no
      // answer at all rejects, which each caller turns into its own failure.
      function postWrite(path, body) {
        var init = {
          method: "POST",
          headers: { "X-Splash-Token": token, "Content-Type": "application/json" },
        };
        if (body !== undefined) init.body = JSON.stringify(body);
        return fetch(path, init).then(function (r) {
          return r.json().then(
            function (j) { return { status: r.status, body: j }; },
            function () { return { status: r.status, body: {} }; }
          );
        });
      }

      // --- US-899-a1 STOP takeover surface (browser only) --------------------
      // Its lines, the view last painted and the ack.
      var takeoverEl = document.getElementById("dtc-takeover");
      var tvDirective = document.getElementById("takeover-directive");
      var tvTitle = document.getElementById("takeover-title");
      var tvValue = document.getElementById("takeover-value");
      var tvStale = document.getElementById("takeover-stale");
      var tvSentence = document.getElementById("takeover-sentence");
      var tvAge = document.getElementById("takeover-age");
      var tvNotice = document.getElementById("takeover-notice");
      var takeoverAlert = null;
      var alertsAck = alertsAckInit();
      // --- US-899-b TROUBLE CODES surface (browser only) ---------------------
      // Its own container, the view last painted, the rows last built and the
      // DISMISS state.
      var codeAlertEl = document.getElementById("code-alert");
      var codeAlertRows = document.getElementById("code-alert-rows");
      var codeAlertMore = document.getElementById("code-alert-more");
      var codeAlertDismiss = document.getElementById("code-alert-dismiss");
      var codeAlertNotice = document.getElementById("code-alert-notice");
      var codeAlert = null;
      var codeAlertRowsPainted = null;
      var codeDismiss = codeDismissInit();

      // --- US-406 Alerts card (Card 5) + per-code detail (browser only) ------
      var detailEl = document.getElementById("dtc-detail");
      var detailBody = document.getElementById("detail-body");
      var detailBack = document.getElementById("detail-back");
      var detailCodeHead = document.getElementById("detail-code-head");
      // US-407 clear surface: the gated button + result line inside the detail,
      // and the dedicated hard-confirm modal.
      var clearBtn = document.getElementById("dtc-clear-btn");
      var clearZone = document.getElementById("dtc-clear-zone");
      var clearResult = document.getElementById("dtc-clear-result");
      var clearConfirm = document.getElementById("clear-confirm");
      var clearConfirmTitle = document.getElementById("clear-confirm-title");
      var clearConfirmText = document.getElementById("clear-confirm-text");
      var clearConfirmOk = document.getElementById("clear-confirm-ok");
      var clearConfirmCancel = document.getElementById("clear-confirm-cancel");
      // US-898-c: the latest states/alerts (the entries a row tap resolves
      // to), the entry the code detail is open on (null while closed) and the
      // detail body last painted (re-built only when what it says changed).
      var lastAlerts = null;
      var detailEntry = null;
      var detailPainted = null;
      // US-898-b1: the ALERTS card, found by its id (Iris U2) -- it no longer
      // carries data-state, so the generic per-card loop never reaches it.
      var alertsCard = document.getElementById("alerts-card");
      // The cached body of the last paint: the tick runs at 4 Hz and the list
      // is rebuilt only when what it says changed.
      var alertsCardPainted = null;
      // US-892-b: the Motion card (it replaced the interim Home card). Painted
      // from the raw states/imu on the ~10 Hz motion loop and from
      // states/grade-history, polled on the 4 Hz tick like the other states.
      var motionCard = document.getElementById("motion-card");
      var lastGradeHistory = null;
      // US-888-a: the Driving card is the LANDING card (R5, `data-landing`).
      // The engine-state edge below returns the carousel HERE; `lastIdle`
      // edge-triggers it so it fires only on a state CHANGE -- it never fights
      // a manual swipe while a state holds -- and its firing on the first tick
      // (lastIdle starts null) is what makes the landing card the card the
      // panel opens on.
      var drivingCard = document.getElementById("driving-card");
      // US-896-a: the NAV card, right after Driving. Its heading half reads the
      // raw states/imu on the ~10 Hz motion loop (the glide needs frames the
      // 4 Hz tick cannot give); `navGlide` is the drawn bearing's state.
      var navCard = document.getElementById("nav-card");
      var navGlide = navGlideInit();
      var navFramePending = false;
      // US-889-b: the Engine card, right after Driving; filled from the same
      // cached states/obd-live on the same tick.
      var engineCard = document.getElementById("engine-card");
      // US-890-b: the Fuel card's AIRFLOW row, from the same cached
      // states/obd-live on the same tick (the trend row is the source card's).
      var fuelCard = document.getElementById("fuel-card");
      // US-889-c: the CHECK ENGINE count line is a PARKED-ONLY tap to the
      // Alerts card. `engineParked` is the US-511 debounce (parkedNext, its
      // first consumer since TD-us659), advanced once per tick from the same
      // states/gear the Driving card reads (US-511-b); the render sets data-tap from
      // it, and the handler honours only what is on the glass right now.
      var engineParked = parkedInit();
      var engineCodes = document.getElementById("engine-codes");
      if (engineCodes) {
        engineCodes.addEventListener("click", function () {
          if (engineCodes.getAttribute("data-tap") === "true") openAlertsCard();
        });
      }
      // US-890-f: the SINCE RESET reset (spec s4.3). `fuelReset` is the
      // fuelResetNext state and `lastFuelEconomy` the LATEST states/fuel-economy
      // read; Yes and the POST's answer repaint from them between ticks, so
      // "resetting…" shows from Yes. US-923: the gate is the provider's
      // `resetAllowed` on that same read (fuelResetAllowed) -- never
      // engineParked, which stays the gate for Clear, the code-row tap and
      // Settings only.
      var fuelReset = fuelResetInit();
      var lastFuelEconomy = null;
      var fuelSinceResetEl = document.getElementById("fuel-since-reset");
      var fuelResetYes = document.getElementById("fuel-reset-yes");
      var fuelResetNo = document.getElementById("fuel-reset-no");
      function fuelConfirmSec() {
        return resolveFuelResetConfirmSec(global.DISPLAY_STALE);
      }
      function paintFuelMpg() {
        renderFuelMpg(
          fuelCard,
          fuelMpgResetView(lastFuelEconomy, fuelReset, fuelConfirmSec())
        );
      }
      if (fuelSinceResetEl) {
        // The menu long-press's shape (US-747): each press owns its interval.
        var fuelProgress = fuelSinceResetEl.querySelector(".fuel-reset-progress");
        var fuelHoldStart = null;
        var fuelHoldX = 0;
        var fuelHoldY = 0;
        var fuelHoldTimer = null;
        var fuelHoldClear = function () {
          fuelHoldStart = null;
          if (fuelHoldTimer) {
            clearInterval(fuelHoldTimer);
            fuelHoldTimer = null;
          }
          if (fuelProgress) {
            fuelProgress.hidden = true;
            fuelProgress.style.setProperty("--fill", "0");
          }
        };
        fuelSinceResetEl.addEventListener("pointerdown", function (e) {
          fuelHoldClear();
          // Moving, the slot carries no hold at all.
          if (fuelSinceResetEl.getAttribute("data-pressable") !== "true") return;
          fuelHoldStart = Date.now();
          fuelHoldX = e.clientX;
          fuelHoldY = e.clientY;
          var id = setInterval(function () {
            if (fuelHoldTimer !== id || fuelHoldStart === null) {
              clearInterval(id);
              return;
            }
            var elapsed = Date.now() - fuelHoldStart;
            if (fuelProgress) {
              fuelProgress.hidden = false;
              fuelProgress.style.setProperty(
                "--fill", String(longPressProgress(elapsed, FUEL_RESET_HOLD_MS))
              );
            }
            if (!isLongPressComplete(elapsed, FUEL_RESET_HOLD_MS)) return;
            fuelHoldClear();
            // Honour only what is on the glass right now: the gate may have
            // closed during the hold.
            if (fuelSinceResetEl.getAttribute("data-pressable") !== "true") return;
            fuelReset = fuelResetNext(fuelReset, {
              type: "hold", allowed: fuelResetAllowed(lastFuelEconomy),
              confirmSec: fuelConfirmSec(),
            });
            paintFuelMpg();
          }, 50);
          fuelHoldTimer = id;
        });
        fuelSinceResetEl.addEventListener("pointermove", function (e) {
          if (fuelHoldStart === null) return;
          if (exceedsMoveCancel(e.clientX - fuelHoldX, e.clientY - fuelHoldY)) fuelHoldClear();
        });
        fuelSinceResetEl.addEventListener("pointerup", fuelHoldClear);
        fuelSinceResetEl.addEventListener("pointercancel", fuelHoldClear);
        fuelSinceResetEl.addEventListener("pointerleave", fuelHoldClear);
      }
      if (fuelResetNo) {
        fuelResetNo.addEventListener("click", function () {
          fuelReset = fuelResetNext(fuelReset, { type: "no" });
          paintFuelMpg();
        });
      }
      if (fuelResetYes) {
        fuelResetYes.addEventListener("click", function () {
          if (fuelReset.phase !== "confirm") return;
          fuelReset = fuelResetNext(fuelReset, { type: "yes", read: lastFuelEconomy });
          // "resetting…" from Yes, not from the 200: the POST can take up to
          // pi.fuel.resetTimeoutSec and the states server stalls reads meanwhile.
          paintFuelMpg();
          // The shared token-gated POST (postWrite): status + JSON body. The
          // server's raw text goes to the log only, never to the glass.
          postWrite("/fuel-reset")
            .then(function (res) {
              var b = isObj(res.body) ? res.body : {};
              if (res.status !== 200) {
                uiLog(LOG_WARN, "fuel-reset " + res.status + ": " + (b.reason || b.error || ""));
              }
              fuelReset = fuelResetNext(fuelReset, {
                type: "answer", status: res.status, body: b, nowMs: Date.now(),
              });
              paintFuelMpg();
            })
            .then(null, function (e) {
              uiLog(LOG_WARN, "fuel-reset no answer: " + String(e));
              fuelReset = fuelResetNext(fuelReset, { type: "failure" });
              paintFuelMpg();
            });
        });
      }
      var landingIndex = -1;
      var lastIdle = null;
      // US-508: the live feed is polled on its OWN faster loop, so its payload
      // and the slow tick's payloads meet here rather than in one function's
      // arguments.
      // US-630: `lastGear` is no longer permanently null. Gear IS Spool's OBD
      // derivation from a separate producer (Atlas ruled it out of states/imu),
      // and that producer now exists: the orchestrator derives it from the
      // realtime SPEED/RPM against the measured drives-50/51 bands and publishes
      // states/gear. The slow tick assigns it below. With the producer dark
      // (`pi.gear.enabled` false) no such file exists, the fetch 404s, and this
      // stays null -- the pre-US-630 behaviour, unchanged.
      var lastImu = null;
      var lastGear = null;
      // US-700: the waiting room. `feedStartedMs` is when THIS PAGE started
      // asking, not when the producer started -- the panel cannot know the
      // latter, and claiming to would be the fabrication this story removes. So
      // a reload three hours into a dead feed shows LOADING for the bound and
      // then settles on `unavailable`, which is an honest account of what the
      // panel actually knows: it has not been answered yet.
      var feedStartedMs = Date.now();
      var feedSeen = {};
      // US-496: the vehicle-dependent cards, revealed only while a vehicle is
      // actually connected (they ship `hidden`, so the pre-first-poll unknown
      // shows no vehicle card).
      var gatedCards = [];
      // The ALERTS card's index -- the target of the warnings icon and the
      // CHECK ENGINE tap. US-898-b1
      // (Iris U2): found by the card's id, never by its position or data-state.
      var alertsCardIndex = -1;
      for (var ci = 0; ci < cards.length; ci++) {
        if (cards[ci].getAttribute("id") === "alerts-card") alertsCardIndex = ci;
        if (cards[ci].getAttribute("data-landing") !== null) landingIndex = ci;
        if (cards[ci].getAttribute("data-vehicle-gated") !== null) {
          gatedCards.push(cards[ci]);
        }
      }

      // US-898-a: tapping the warnings icon opens ALERTS -- allowed while moving
      // (Iris U1): it only navigates, which a swipe already does, so nothing
      // here reads the parked signal.
      var warnIconBtn = document.getElementById("glyph-warnings");
      if (warnIconBtn) {
        warnIconBtn.addEventListener("click", function () {
          if (alertsCardIndex >= 0) goTo(alertsCardIndex);
        });
      }

      // US-496 AC-3: reveal/hide the vehicle-dependent cards from the SAME
      // system-status the tick already fetched (no second read). `hidden` (not a
      // class) is deliberate: it is the property the US-495 guard removes from
      // the flex track AND the one hiddenFlags() reads back as the rendered
      // truth, so the gate and the paint can never disagree. The carousel is
      // re-laid-out only on a real CHANGE, so a steady state never fights a swipe.
      function applyVehicleGate(sysData) {
        var wantHidden = !vehicleConnected(sysData);
        var changed = false;
        for (var g = 0; g < gatedCards.length; g++) {
          if (gatedCards[g].hidden === wantHidden) continue;
          gatedCards[g].hidden = wantHidden;
          changed = true;
        }
        if (changed && typeof onVisibilityChange === "function") onVisibilityChange();
      }

      // US-898-c: the states/alerts entry with this exact id; null when the
      // latest payload has none.
      function alertsEntryFor(match) {
        var entries = isObj(lastAlerts) && Array.isArray(lastAlerts.entries)
          ? lastAlerts.entries : [];
        for (var i = 0; i < entries.length; i++) {
          if (isObj(entries[i]) && match(entries[i])) return entries[i];
        }
        return null;
      }
      function alertsEntryById(id) {
        return alertsEntryFor(function (e) { return e.id === id; });
      }
      function closeDetail() {
        if (detailEl) detailEl.hidden = true;
        detailEntry = null;
        detailPainted = null;
      }
      // Navigate the carousel to the Alerts card.
      function openAlertsCard() {
        if (alertsCardIndex >= 0 && typeof goTo === "function") goTo(alertsCardIndex);
      }

      function hideTakeover() {
        if (!takeoverEl) return;
        takeoverEl.hidden = true;
        // US-537: drop the severity WITH the surface. The STOP alarm pulse hangs
        // off [data-severity="stop"], so leaving the attribute behind left an
        // acknowledged takeover matching the alarm rule forever -- inert only
        // because the element had no box. The state attribute and the surface
        // go up and down together, so motion can never outlive the alert.
        takeoverEl.removeAttribute("data-severity");
      }
      // US-899-a1: one takeover line -- its text, and the line DOWN when it has
      // nothing to say (an empty painted line would still claim its gap).
      function fillTakeoverLine(el, text) {
        if (!el) return;
        el.textContent = text || "";
        el.hidden = !text;
      }

      // US-899-a1: paint takeoverAlertView into #dtc-takeover -- the ONLY writer
      // of its state and copy. null takes it down WITH its severity (the US-537
      // lockstep: the alarm pulse hangs off [data-severity="stop"]). The
      // surface holds no control (Iris U7): the whole of it is the ack tap.
      function renderAlertsTakeover(view, ackState) {
        takeoverAlert = view;
        if (!takeoverEl) return;
        if (!view) {
          hideTakeover();
          return;
        }
        takeoverEl.setAttribute("data-severity", "stop");
        fillTakeoverLine(tvDirective, view.directive);
        fillTakeoverLine(tvTitle, view.title);
        fillTakeoverLine(tvValue, view.value);
        fillTakeoverLine(tvStale, view.stale);
        fillTakeoverLine(tvSentence, view.sentence);
        fillTakeoverLine(tvAge, view.age);
        fillTakeoverLine(tvNotice, alertsAckNoticeText(ackState));
        takeoverEl.hidden = false;
      }

      function alertsAckWindows() {
        return {
          confirmSec: resolveAlertsAckConfirmSec(global.DISPLAY_STALE),
          noticeSec: resolveAlertsAckNoticeSec(global.DISPLAY_STALE),
        };
      }

      // A tap ANYWHERE on the takeover acknowledges it: ONE POST of its id. The
      // answer only moves the ack on; what settles it is the next re-read.
      if (takeoverEl) {
        takeoverEl.addEventListener("click", function () {
          if (takeoverEl.hidden || !takeoverAlert) return;
          var windows = alertsAckWindows();
          var before = alertsAck.phase;
          alertsAck = alertsAckNext(alertsAck, {
            type: "tap", view: takeoverAlert,
            confirmSec: windows.confirmSec, noticeSec: windows.noticeSec,
          });
          if (before === "posting" || alertsAck.phase !== "posting") return;
          renderAlertsTakeover(takeoverAlert, alertsAck);
          postWrite("/alerts-ack", alertsAckBody(alertsAck.id))
            .then(function (res) {
              if (res.status !== 200) {
                var b = isObj(res.body) ? res.body : {};
                uiLog(LOG_WARN, "alerts-ack " + res.status + ": " + (b.error || ""));
              }
              alertsAck = alertsAckNext(alertsAck, {
                type: "answer", status: res.status, body: res.body, nowMs: Date.now(),
              });
              renderAlertsTakeover(takeoverAlert, alertsAck);
            })
            .then(null, function (e) {
              uiLog(LOG_WARN, "alerts-ack no answer: " + String(e));
              alertsAck = alertsAckNext(alertsAck, { type: "failure", nowMs: Date.now() });
              renderAlertsTakeover(takeoverAlert, alertsAck);
            });
        });
      }

      // US-899-b: paint codeAlertView into #code-alert. null takes it down
      // (moving, the STOP takeover up, or no codeAlert) -- which posts nothing. The
      // frame is the provider tier's colour token; the rows are rebuilt only
      // when what they say changed.
      function renderCodeAlert(view, dismissState) {
        codeAlert = view;
        if (!codeAlertEl) return;
        if (!view) {
          codeAlertEl.hidden = true;
          return;
        }
        // An unknown tier sets "" (removes it): the CSS default frame stands.
        codeAlertEl.style.setProperty(
          "--code-alert-frame", view.colorVar ? "var(" + view.colorVar + ")" : ""
        );
        var rowsKey = JSON.stringify(view.rows);
        if (codeAlertRows && rowsKey !== codeAlertRowsPainted) {
          codeAlertRowsPainted = rowsKey;
          codeAlertRows.textContent = "";
          for (var i = 0; i < view.rows.length; i++) {
            var r = view.rows[i];
            var row = document.createElement("div");
            row.className = "code-alert-row";
            row.setAttribute("data-id", r.id);
            var chip = warnSpan("span", "code-alert-chip", r.chip);
            chip.setAttribute("data-tier", r.tier);
            row.appendChild(chip);
            row.appendChild(warnSpan("span", "code-alert-title", r.title));
            if (r.sentence) row.appendChild(warnSpan("span", "code-alert-sentence", r.sentence));
            codeAlertRows.appendChild(row);
          }
        }
        fillTakeoverLine(codeAlertMore, view.more);
        fillTakeoverLine(codeAlertNotice, codeDismissNoticeText(dismissState));
        codeAlertEl.hidden = false;
      }

      // DISMISS: ONE POST of every id. The answer only moves the dismiss on;
      // the screen closes on the re-read that shows codeAlert null.
      if (codeAlertDismiss) {
        codeAlertDismiss.addEventListener("click", function () {
          if (!codeAlertEl || codeAlertEl.hidden || !codeAlert) return;
          var windows = alertsAckWindows();
          var before = codeDismiss.phase;
          codeDismiss = codeDismissNext(codeDismiss, {
            type: "tap", view: codeAlert,
            confirmSec: windows.confirmSec, noticeSec: windows.noticeSec,
          });
          if (before === "posting" || codeDismiss.phase !== "posting") return;
          renderCodeAlert(codeAlert, codeDismiss);
          postWrite("/alerts-ack", codeDismissBody(codeDismiss.ids))
            .then(function (res) {
              if (res.status !== 200) {
                var b = isObj(res.body) ? res.body : {};
                uiLog(LOG_WARN, "alerts-ack (codes) " + res.status + ": " + (b.error || ""));
              }
              codeDismiss = codeDismissNext(codeDismiss, {
                type: "answer", status: res.status, body: res.body, nowMs: Date.now(),
              });
              renderCodeAlert(codeAlert, codeDismiss);
            })
            .then(null, function (e) {
              uiLog(LOG_WARN, "alerts-ack (codes) no answer: " + String(e));
              codeDismiss = codeDismissNext(codeDismiss, { type: "failure", nowMs: Date.now() });
              renderCodeAlert(codeAlert, codeDismiss);
            });
        });
      }

      // --- US-406 detail render (browser only) -------------------------------

      // A labeled line: a bold label + a plain value (textContent -> verbatim,
      // never markup). Returns the row element so callers can tag it.
      function detailLine(cls, label, value) {
        var row = document.createElement("div");
        row.className = cls;
        if (label) {
          var l = document.createElement("span");
          l.className = "detail-label";
          l.textContent = label;
          row.appendChild(l);
        }
        var v = document.createElement("span");
        v.className = "detail-value";
        v.textContent = value;
        row.appendChild(v);
        return row;
      }

      // Render the per-code detail body from codeDetailView(). Every branch is
      // honest: a 🔴/🟡 fix is a diagnose directive (never a raw fix); a missing
      // freeze-frame is the labeled realtime fallback; a caveat is a line, never
      // a tier upgrade.
      function renderDetailBody(view) {
        if (!detailBody) return;
        detailBody.textContent = "";
        if (detailCodeHead) detailCodeHead.textContent = view.code;

        // Hero: chip + code + short description.
        var hero = document.createElement("div");
        hero.className = "detail-hero";
        var chip = document.createElement("span");
        chip.className = "dtc-chip";
        chip.setAttribute("data-level", view.level);
        chip.textContent = view.chip;
        hero.appendChild(chip);
        var codeSpan = document.createElement("span");
        codeSpan.className = "detail-code";
        codeSpan.textContent = view.code;
        hero.appendChild(codeSpan);
        var shortSpan = document.createElement("span");
        shortSpan.className = "detail-short";
        shortSpan.textContent = view.short;
        hero.appendChild(shortSpan);
        detailBody.appendChild(hero);

        // Severity directive band (🔴/🟡 only). US-488: the band is TIER-DRIVEN
        // in CSS, so the row carries data-level from the SAME tier the chip
        // above uses -- a directive can never disagree with the chip beside it,
        // and an untagged row falls back to the neutral base rather than
        // inheriting a severity it does not have.
        if (view.directive) {
          var directiveRow = detailLine("detail-directive", "", view.directive);
          directiveRow.setAttribute("data-level", view.level);
          detailBody.appendChild(directiveRow);
        }
        // Condition-dependent caveat -- a LINE beneath the chip, never a tier
        // upgrade (S-13).
        if (view.caveat) {
          detailBody.appendChild(detailLine("detail-caveat", "", "⚠ " + view.caveat));
        }
        // US-898-c (Iris U4): no states/dtc record -- the entry's title, chip
        // and sentence above stand alone, and nothing below is drawn from a
        // cached record.
        if (view.unavailable) {
          detailBody.appendChild(detailLine("detail-unavailable", "", view.unavailable));
          return;
        }
        // Status meta (STORED/PENDING · key-on read | Drive N).
        detailBody.appendChild(detailLine("detail-meta", "", view.statusMeta));

        // Freeze-frame grid OR the labeled realtime fallback (S-5, never blank).
        // US-491: `detail-card` is the SHARED section shell (border + the one
        // spacing scale) -- three near-identical boxes drift the first time one
        // of them is edited, which is what "consistent rhythm" (AC3) is about.
        var ff = document.createElement("div");
        ff.className = "detail-card detail-freeze";
        var ffLabel = document.createElement("span");
        ffLabel.className = "detail-label";
        ffLabel.textContent = "FREEZE FRAME";
        ff.appendChild(ffLabel);
        if (view.freezeFrame.hasFrame) {
          var grid = view.freezeFrame.grid;
          for (var k in grid) {
            if (Object.prototype.hasOwnProperty.call(grid, k)) {
              ff.appendChild(detailLine("detail-ff-cell", k, String(grid[k])));
            }
          }
        } else {
          ff.appendChild(detailLine("detail-ff-fallback", "", view.freezeFrame.fallbackText));
        }
        detailBody.appendChild(ff);

        // Severity-gated fix (S-4/F-1): directive for 🔴/🟡, real fix + badge for
        // 🟢, N/A for na.
        var fixBox = document.createElement("div");
        fixBox.className = "detail-card detail-fix";
        fixBox.setAttribute("data-mode", view.fix.mode);
        // US-491: the heading is now UNCONDITIONAL -- it used to live inside the
        // `mode === "fix"` branch, so a 🔴/🟡 card rendered a bordered box with
        // no heading at all. The wording is mode-driven (fixSectionLabel), so a
        // diagnose directive is never mis-headed "SUGGESTED FIX" (S-4).
        var fixLabel = document.createElement("span");
        fixLabel.className = "detail-label";
        fixLabel.textContent = fixSectionLabel(view.fix.mode);
        fixBox.appendChild(fixLabel);
        if (view.fix.mode === "fix") {
          fixBox.appendChild(detailLine("detail-fix-text", "", view.fix.text));
          if (view.fix.badge) {
            var badge = document.createElement("span");
            badge.className = "dtc-trust-badge";
            badge.setAttribute("data-kind", view.fix.badge.kind);
            badge.textContent = view.fix.badge.label;
            fixBox.appendChild(badge);
          }
        } else {
          // directive / na -> the fix slot is REPLACED (never a raw fix).
          fixBox.appendChild(detailLine("dtc-fix-directive", "", view.fix.text));
        }
        detailBody.appendChild(fixBox);

        // Log/sync footer (the capture-before-clear precondition, made visible).
        var footer = detailLine(
          "detail-footer",
          "",
          (view.logged ? "✓ logged" : "· not yet logged") +
            " · " +
            (view.syncAcked ? "✓ synced to server" : "· sync pending")
        );
        detailBody.appendChild(footer);
      }

      // US-898-c (Iris U4 / G-7 exception): open the detail on a code ENTRY.
      // The one states/dtc read outside the provider path, scoped to this open
      // and the ticks while it stays open; it is what the clear gate keys off.
      async function openDetail(entry) {
        if (!detailEl || !codeDetailView(null, entry)) return;
        var dtcData = await fetchState("dtc");
        detailEntry = entry;
        detailPainted = null;
        if (clearResult) clearResult.textContent = "";
        paintCodeDetail(dtcData);
        detailEl.hidden = false;
      }

      // Paint the open detail from one states/dtc read (`dtcData`, null when
      // the read failed). That read is also what the clear gate keys off, so
      // the record on screen and the button agree; with no record there is no
      // clear to offer.
      function paintCodeDetail(dtcData) {
        var view = codeDetailView(
          dtcRecordFor(dtcData, codeFromEntryId(detailEntry.id)), detailEntry
        );
        if (!view) return;
        var painted = JSON.stringify(view);
        if (painted !== detailPainted) {
          detailPainted = painted;
          renderDetailBody(view);
        }
        renderClearButton(view.unavailable ? null : dtcData);
      }

      // The tick's half of the open detail: the entry's latest words (kept as
      // they were if the provider stopped listing it) and a fresh read.
      function refreshCodeDetail(dtcData) {
        if (!detailEntry || !detailEl || detailEl.hidden) return;
        detailEntry = alertsEntryById(detailEntry.id) || detailEntry;
        paintCodeDetail(dtcData);
      }

      // --- US-407 clear surface (browser only) -------------------------------

      // Reflect the (display-mirror) gate onto the Clear button. No button when
      // nothing is clearable; disabled + reason label otherwise; enabled only on
      // `ok` while parked. The server RE-CHECKS the gate on submit -- the button
      // never forces. US-898-c: re-gated on every tick the detail is open, so
      // the button follows the codes and engineParked under the operator.
      function renderClearButton(dtcData) {
        if (!clearBtn) return;
        var view = clearButtonView(
          dtcData, engineParked.parked, isObj(lastGear) && lastGear.available === true
        );
        // US-491: the zone is now a bordered, LABELLED card, so it must go with
        // the button -- an empty "CLEAR CODES" box on a nothing-to-clear detail
        // is a new visual regression. The GATE is untouched: visibility still
        // comes from clearButtonView(), and the server re-checks on submit.
        // US-898-c: a clear's result line lives in the zone, so the zone stays
        // while it has something to say (a cleared car has no codes left).
        if (clearZone) {
          clearZone.hidden = !view.visible && !(clearResult && clearResult.textContent);
        }
        if (!view.visible) {
          clearBtn.hidden = true;
          return;
        }
        clearBtn.hidden = false;
        clearBtn.textContent = view.label;
        clearBtn.disabled = !view.enabled;
        clearBtn.setAttribute("data-reason", view.reason);
      }

      function showClearResult(msg) {
        if (!clearResult || !msg) return;
        clearResult.textContent = msg.text;
        clearResult.setAttribute("data-level", msg.level);
      }

      function hideClearConfirm() {
        if (clearConfirm) clearConfirm.hidden = true;
      }

      function openClearConfirm() {
        if (!clearConfirm) return;
        var copy = confirmClearText();
        if (clearConfirmTitle) clearConfirmTitle.textContent = copy.title;
        if (clearConfirmText) clearConfirmText.textContent = copy.body;
        if (clearConfirmOk) clearConfirmOk.textContent = copy.confirmLabel;
        if (clearConfirmCancel) clearConfirmCancel.textContent = copy.cancelLabel;
        clearConfirm.hidden = false;
      }

      // POST the clear request. The gate is re-checked SERVER-SIDE from its own
      // `dtc` state (never this request) -- a 403 means the server refused. The
      // result reports the re-read proof (or the re-set), never "command sent".
      function submitClear() {
        hideClearConfirm();
        postWrite("/dtc-clear", { confirm: true })
          .then(function (res) {
            if (res.status === 200) {
              showClearResult(postClearMessage(res.body));
            } else {
              showClearResult({
                level: "blocked",
                text: "Clear refused — " + (res.body.reason || res.body.error || "not allowed"),
              });
            }
          })
          .then(null, function () {
            showClearResult({ level: "blocked", text: "Clear failed — no response" });
          });
      }

      if (clearBtn) {
        clearBtn.addEventListener("click", function () {
          if (!clearBtn.disabled) openClearConfirm();
        });
      }
      if (clearConfirmOk) clearConfirmOk.addEventListener("click", submitClear);
      if (clearConfirmCancel) {
        clearConfirmCancel.addEventListener("click", hideClearConfirm);
      }

      // --- US-898-b1 ALERTS card render (browser only) -----------------------

      function warnSpan(tag, cls, text) {
        var el = document.createElement(tag);
        el.className = cls;
        el.textContent = text;
        return el;
      }

      // Paint warningsPageView into #alerts-card. Rows go in view.rows order --
      // the provider's -- and nothing here compares a tier. A CODE row is a
      // real control (a button) that opens the code's detail while parked
      // (US-898-c, openDetail); an ENGINE row
      // and every sentence are plain text (US-758). `loading` is the US-700
      // bounded LOADING while the first states/alerts read is pending.
      function renderWarningsCard(card, view, loading) {
        var body = card ? card.querySelector(".card-body") : null;
        if (!body) return;
        card.classList.toggle("unavailable", view.missing && !loading);
        var painted = loading ? "loading" : JSON.stringify(view);
        if (painted === alertsCardPainted) {
          updateWarningsMore(body);
          return;
        }
        alertsCardPainted = painted;
        if (loading) {
          renderLoadingBody(body, card.getAttribute("data-page-name") || "");
          return;
        }
        body.textContent = "";
        var head = document.createElement("div");
        head.className = "warn-header";
        var count = warnSpan("span", "warn-count", view.header.text);
        if (view.header.tone) count.setAttribute("data-tone", view.header.tone);
        head.appendChild(count);
        if (view.header.meta) head.appendChild(warnSpan("span", "warn-meta", view.header.meta));
        body.appendChild(head);
        if (view.missing) {
          body.appendChild(warnSpan("div", "warn-empty", view.empty));
          return;
        }
        if (view.quiet) body.appendChild(warningsQuietBlock(view.quiet));
        if (!view.rows.length) return;
        var list = document.createElement("div");
        list.className = "warn-list";
        for (var i = 0; i < view.rows.length; i++) {
          (function (r) {
            var row = document.createElement(r.control ? "button" : "div");
            row.className = r.control ? "warn-row warn-row-code" : "warn-row";
            row.setAttribute("data-id", r.id);
            row.setAttribute("data-tier", r.tier);
            row.setAttribute("data-active", r.active ? "true" : "false");
            var chip = warnSpan("span", "warn-chip", r.chip);
            chip.setAttribute("data-tier", r.tier);
            chip.setAttribute("data-active", r.active ? "true" : "false");
            row.appendChild(chip);
            var main = document.createElement("span");
            main.className = "warn-main";
            var line = document.createElement("span");
            line.className = "warn-line";
            line.appendChild(warnSpan("span", "warn-title", r.title));
            if (r.value) line.appendChild(warnSpan("span", "warn-value", r.value));
            main.appendChild(line);
            if (r.stale) main.appendChild(warnSpan("span", "warn-stale", r.stale));
            if (r.sentence) main.appendChild(warnSpan("span", "warn-sentence", r.sentence));
            row.appendChild(main);
            row.appendChild(warnSpan("span", "warn-age", r.age));
            if (r.control) {
              // US-898-c: PARKED-ONLY (engineParked, the US-511 debounce, as
              // on the glass right now); while not parked the tap does nothing.
              row.addEventListener("click", function () {
                if (engineParked.parked !== true) return;
                var entry = alertsEntryById(r.id);
                if (entry) openDetail(entry);
              });
            }
            list.appendChild(row);
          })(view.rows[i]);
        }
        body.appendChild(list);
        // The cue line is always laid out under the list (empty while nothing
        // is below), so showing it never shrinks the list it is counting.
        body.appendChild(warnSpan("div", "warn-more", ""));
        list.addEventListener("scroll", function () { updateWarningsMore(body); });
        updateWarningsMore(body);
      }

      // US-898-b2: the empty / not-checked body. The '?' is its own --font-mono
      // span: Michroma carries only the upper-case words.
      function warningsQuietBlock(quiet) {
        var block = document.createElement("div");
        block.className = "warn-quiet";
        block.setAttribute("data-state", quiet.state);
        var headline = document.createElement("div");
        headline.className = "warn-quiet-head";
        if (quiet.mark) headline.appendChild(warnSpan("span", "warn-quiet-mark", quiet.mark + " "));
        headline.appendChild(warnSpan("span", "warn-quiet-word", quiet.head));
        block.appendChild(headline);
        for (var i = 0; i < quiet.lines.length; i++) {
          var line = warnSpan("div", "warn-quiet-line", quiet.lines[i].text);
          line.setAttribute("data-tone", quiet.lines[i].tone);
          block.appendChild(line);
        }
        return block;
      }

      // A laid-out element's height, or null where there is no layout (the
      // test harness, a card not yet laid out).
      function warnHeight(el) {
        if (!el || typeof el.getBoundingClientRect !== "function") return null;
        var h = el.getBoundingClientRect().height;
        return h > 0 ? h : null;
      }

      // Iris U9: count from LAYOUT -- the rows whose bottom is below the list's
      // visible bottom. No layout -> the 48 px-floor fallback, over the
      // measured header and cue heights (0 where even those are unmeasured).
      function updateWarningsMore(body) {
        var list = body.querySelector(".warn-list");
        var cue = body.querySelector(".warn-more");
        if (!list || !cue) return;
        var rows = list.querySelectorAll(".warn-row");
        var n;
        if (warnHeight(list) !== null) {
          var bottom = list.getBoundingClientRect().top + list.clientTop + list.clientHeight;
          var bottoms = [];
          for (var i = 0; i < rows.length; i++) bottoms.push(rows[i].getBoundingClientRect().bottom);
          n = warningsBelowFromLayout(bottom, bottoms);
        } else {
          n = warningsMoreBelow(
            rows.length,
            warnHeight(body.querySelector(".warn-header")) || WARNINGS_HEADER_EST_PX,
            warnHeight(cue) || WARNINGS_CUE_EST_PX
          );
        }
        var text = warningsMoreText(n);
        if (cue.textContent !== text) cue.textContent = text;
      }

      if (detailBack) detailBack.addEventListener("click", closeDetail);
      // US-509: the System-Status drill-down's Back, wired beside its sibling so
      // the two overlays' escape hatches live together. AC2 -- never traps.
      var sysDetailBack = document.getElementById("sys-detail-back");
      if (sysDetailBack) sysDetailBack.addEventListener("click", closeSysDetail);
      // US-894-b: the System page's taps follow the parked fact's edges.
      onParkedChange(repaintSystemOnParkedEdge);
      // US-892-b: paint the Motion card. Called from BOTH loops -- the ~10 Hz
      // motion poll (fresh states/imu) and the 4 Hz tick (fresh
      // states/grade-history) -- against one clock per paint.
      function renderMotion(nowMs) {
        if (!motionCard) return;
        renderMotionCard(
          motionCard,
          motionView(
            lastImu, nowMs, resolveImuStaleSec(global && global.DISPLAY_STALE),
            feedWaitedMs(feedSeen, "imu", feedStartedMs, nowMs)
          ),
          motionGradeGraph(lastGradeHistory)
        );
      }

      // Edge-triggered home navigation. US-508 RETARGETS it: US-481 sent the
      // operator to System Status when `idle` flipped false, because the home
      // card was a parked-only view and staying on it while driving would have
      // been useless. The home slot now BECOMES the live instrument, so
      // navigating away from it on engine start is exactly backwards -- both
      // edges now land on home, which is where the change is visible.
      // US-888-a RETARGETS it again, to the LANDING card (Driving, R5): an
      // engine start or stop is exactly when the driver's page is the one to
      // read, and the first tick's edge is what opens the panel there. The
      // name and the parked SSOT (carouselIdle) are unchanged.
      function updateHomeNav(sysData) {
        var idle = carouselIdle(sysData);
        if (idle === lastIdle) return; // edge-trigger only -- never trap a swipe
        if (landingIndex >= 0) goTo(landingIndex);
        lastIdle = idle;
      }

      async function tick() {
        var sysData = null; // shared by every surface (one fetch per tick)
        var lightData = null; // shared: the US-507 Health card + the auto-dim
        // US-496: ONE clock for the whole tick, so the Light card's freshness
        // verdict and the brightness the screen is actually set to are resolved
        // against the same instant -- the card can never contradict the surface.
        var nowMs = Date.now();
        // US-542: repaint the top-bar clock from the SAME tick clock everything
        // else on this pass is resolved against (US-496's one-clock rule), so
        // the time the operator reads and the freshness verdicts beside it can
        // never be resolved against two different instants.
        renderTopbarClock(new Date(nowMs));
        // US-507: ONE fetch per state name per tick, however many surfaces
        // consume it. states/light now feeds BOTH the Health card and the
        // auto-dim; fetching it twice could resolve the printed reading and the
        // brightness against two different samples. The cache also removes the
        // old "whichever card happened to fetch it" coupling -- the shared vars
        // are now assigned in exactly one place, so they are populated no matter
        // which surface asked first.
        var fetched = {};
        async function stateOnce(name) {
          if (Object.prototype.hasOwnProperty.call(fetched, name)) return fetched[name];
          var payload = await fetchState(name);
          fetched[name] = payload;
          // US-700: record the arrival HERE, where every state name funnels
          // through exactly once per tick. A ledger updated per-consumer would
          // be a ledger some consumer forgets to update.
          feedSeen = feedObserved(feedSeen, name, payload);
          if (name === "system-status") sysData = payload;
          else if (name === "light") lightData = payload;
          return payload;
        }
        for (var c = 0; c < cards.length; c++) {
          var card = cards[c];
          // US-496: a gated-off card is not rendered and not fetched. It is
          // display:none -- polling it 4x/s would be a read nobody can see.
          if (card.hidden) continue;
          var name = card.getAttribute("data-state");
          if (!name) continue;
          var data = await stateOnce(name);
          // US-540-b: the three source cards route through their OWN view,
          // deliberately BEFORE the generic availability path below. Two of
          // them (battery, light) would survive that path; fuel trim would not
          // -- its gate has to be evaluated before its data, and the generic
          // path reads the data first. One route for all three keeps the rule
          // "which card is this?" in exactly one place.
          var spec = sourceCardSpec(name);
          if (spec) {
            // The gate resolves against the SAME system-status the rest of the
            // tick uses (cached -- free when another card already read it), so
            // the fuel-trim gate can never disagree with the vehicle state the
            // top bar was rendered against.
            // US-893-b: the Light page's status line and dot read the SAME
            // applied level the panel is set to below -- same cached payloads,
            // same STOP test, same clock.
            renderSourceCard(
              card,
              sourceCardView(
                spec, data, await stateOnce("system-status"), displayAutoDim,
                nowMs, feedWaitedMs(feedSeen, name, feedStartedMs, nowMs),
                brightnessAlarmActive(await stateOnce("alerts")),
                settingsSource
              )
            );
            continue;
          }
          var avail = cardAvailability(data);
          // US-700: a card that has not been answered YET is not a dead card.
          // The `.unavailable` class is the whole-card gray, and applying it to
          // a loading card would paint the exact "this instrument is broken"
          // claim the body below is being careful not to make.
          var cardLoading =
            loadPhase(data, feedWaitedMs(feedSeen, name, feedStartedMs, nowMs))
            === "loading";
          card.classList.toggle(
            "unavailable", avail === "unavailable" && !cardLoading
          );
          if (avail === "unavailable") {
            var body = card.querySelector(".card-body");
            // US-496: a card with a bespoke no-data view NAMES the silent
            // instrument (`dtc` must never read as an all-clear); every other
            // card keeps the shipped one-word fallback.
            var nd = noDataView(name);
            if (body && cardLoading) {
              // The instrument's own name where one exists, else the card's
              // page name -- read off the DOM rather than a second table, so
              // the label on the tile cannot disagree with the name in the bar
              // (US-887-c: the card title row it used to read is retired).
              renderLoadingBody(
                body,
                nd ? nd.label : (card.getAttribute("data-page-name") || "")
              );
            } else if (body && nd) renderNaBody(body, nd.label, nd.reason);
            // US-894-b (s4.1): the System page's unavailable path is the
            // verdict `--`, never ALL OK.
            else if (body && name === "system-status") renderSystemUnavailable(card);
            else if (body) body.textContent = "unavailable";
            if (name === "system-status") resetSystemGlyphs(glyphEls);
            continue;
          }
          // available -> the per-card renderer owns the body.
          if (name === "system-status") {
            // US-688: the CAPTURE tile's fact lives in its own state file, so
            // it is fetched here rather than carried inside system-status --
            // different producer, different tier concern. `stateOnce` caches
            // per tick, so this costs one read however many surfaces ask.
            // A null (producer dark / 404 / fetch aborted) yields NO capture
            // tile, which is the pre-US-688 card -- never a fabricated `ok`.
            var captureData = await stateOnce("capture-health");
            renderSystemStatusCard(
              card, systemStatusView(data, captureData), glyphEls
            );
          }
          // US-508: the standalone Motion branch is GONE with the card it
          // served -- the live instrument is now a FACE of the home slot,
          // driven by its own faster poll below. Left in place it would have
          // been a branch no card could reach, which is not harmless: nothing
          // executes it, so nothing proves it still resolves (US-500).
          // US-507: the ltft-trend branch is GONE, not merely unreachable. It
          // still named `renderLtftTrendCard`, which this story renamed -- a
          // ReferenceError waiting on the day something re-declares a card with
          // that state. A branch no card can reach is not harmless: nothing
          // executes it, so nothing proves it still resolves.
        }
        // US-496 AC-3: reveal/hide the vehicle-dependent cards from the state
        // just read. An unavailable system-status leaves sysData null here, which
        // fails closed to hidden -- no vehicle card without a vehicle.
        applyVehicleGate(sysData);
        // US-901-b: the not-live marker, from the SAME system-status every
        // other surface on this tick read (cached) plus states/obd-live.
        renderNotLiveMarker(
          notLiveMarker(await stateOnce("system-status"), await stateOnce("obd-live"))
        );
        // US-898-a: the warnings icon is on every page, so states/alerts is read
        // on EVERY tick, unconditionally -- not only while ALERTS is showing.
        lastAlerts = await stateOnce("alerts");
        renderTopbarIcon(alertIconView(lastAlerts));
        // US-899-a1: the STOP takeover, from the SAME cached states/alerts
        // on this tick's one clock. The read first moves the ack on (a matching
        // re-read settles it; a lapsed window says so), then the surface paints.
        var ackWindows = alertsAckWindows();
        alertsAck = alertsAckNext(alertsAck, {
          type: "read", alerts: lastAlerts, nowMs: nowMs,
          confirmSec: ackWindows.confirmSec, noticeSec: ackWindows.noticeSec,
        });
        renderAlertsTakeover(
          takeoverAlertView(lastAlerts, new Date(nowMs).toISOString()), alertsAck
        );
        // US-898-b1: the ALERTS card, from the SAME cached states/alerts the
        // icon just read, on this tick's one clock. LOADING only while that
        // feed has never answered (US-700), keyed by the feed's name.
        renderWarningsCard(
          alertsCard,
          warningsPageView(await stateOnce("alerts"), new Date(nowMs).toISOString()),
          loadPhase(
            await stateOnce("alerts"), feedWaitedMs(feedSeen, "alerts", feedStartedMs, nowMs)
          ) === "loading"
        );
        // US-630: the derived gear. Read on THIS tick rather than the ~10 Hz
        // motion loop -- the producer debounces for >= 2 s before it will name a
        // gear, so a gear cannot change faster than the 4 Hz card tick can see
        // it, and polling it at 10 Hz would be 6 reads a second of a file that
        // had not moved. A missing/404 state leaves this null, which gearView
        // already renders as the honest "-- / no source": the tile falls back to
        // exactly the state it held before this story, never to a stale gear.
        lastGear = await stateOnce("gear");
        // US-888-a: the Driving card reads the SAME gear payload (one fetch,
        // test_carousel_gear_derived) and states/obd-live, already fetched for
        // the not-live marker above (cached), on this tick's one clock.
        renderDrivingCard(
          drivingCard, drivingView(await stateOnce("obd-live"), lastGear, nowMs)
        );
        renderEngineCard(engineCard, engineView(await stateOnce("obd-live"), nowMs));
        // US-889-c: the scroll half -- this drive's history from
        // states/engine-history alone, and the status row from the same cached
        // obd-live, its codes tap gated on the debounced parked signal.
        // US-511-b: fed from THIS tick's states/gear (lastGear, read above --
        // no second fetch), never from system-status idle.
        engineParked = parkedNext(engineParked, gearParked(lastGear), nowMs, carouselCfg);
        // US-894-b: the ONE write of the module's parked fact -- the debounced
        // value just advanced, and the RAW gear-known fact (Atlas B9 + A1).
        publishParked(engineParked.parked, isObj(lastGear) && lastGear.available === true);
        // US-899-b: the TROUBLE CODES screen, from the SAME cached states/alerts
        // the takeover painted from, against THIS tick's parked signal. The read
        // moves the dismiss on first (a codeAlert-null re-read settles it).
        codeDismiss = codeDismissNext(codeDismiss, {
          type: "read", alerts: lastAlerts, nowMs: nowMs,
          confirmSec: ackWindows.confirmSec, noticeSec: ackWindows.noticeSec,
        });
        renderCodeAlert(codeAlertView(lastAlerts, engineParked.parked), codeDismiss);
        // US-898-c: an open code detail re-reads states/dtc each tick -- the
        // only states/dtc read on the tick -- and re-gates its clear against
        // THIS tick's parked signal.
        if (detailEntry) refreshCodeDetail(await stateOnce("dtc"));
        renderEngineScroll(
          engineCard,
          engineHistoryView(await stateOnce("engine-history")),
          engineStatusView(await stateOnce("obd-live"), engineParked.parked, nowMs)
        );
        renderFuelAirflow(fuelCard, fuelAirflowView(await stateOnce("obd-live"), nowMs));
        // US-890-c: the loop chip and TOTAL TRIM from the same cached obd-live's
        // `fuel` block -- never from the raw status code or the trims.
        renderFuelLoopAndTrim(
          fuelCard,
          fuelLoopView(await stateOnce("obd-live")),
          fuelTotalTrimView(await stateOnce("obd-live"))
        );
        // US-890-d: the MPG row from states/fuel-economy alone. US-890-f: the
        // read also advances the reset (match / confirm window / a landed
        // reset), against that read's own gate (US-923) and this tick's one
        // clock.
        lastFuelEconomy = await stateOnce("fuel-economy");
        fuelReset = fuelResetNext(fuelReset, {
          type: "read", read: lastFuelEconomy, allowed: fuelResetAllowed(lastFuelEconomy),
          nowMs: nowMs, confirmSec: fuelConfirmSec(),
        });
        renderFuelMpg(fuelCard, fuelResetOverlay(
          fuelMpgView(await stateOnce("fuel-economy")),
          fuelReset, fuelResetAllowed(lastFuelEconomy), fuelConfirmSec()
        ));
        // US-896-b: the NAV trip from the SAME system-status every other
        // surface on this tick read (cached); the page does no time arithmetic.
        renderNavTrip(navCard, navTripView(await stateOnce("system-status")));
        // US-892-b: the grade graph's history, polled like the other states;
        // the motion values arrive on their own faster loop.
        lastGradeHistory = await stateOnce("grade-history");
        renderMotion(nowMs);
        updateHomeNav(sysData);
        // US-659: `updateMenuAccess(sysData, nowMs)` was called here to repaint
        // the ⋮ per tick against the debounced parked signal. Removed with the
        // gate -- the kebab's visibility is no longer a function of any state.
        // US-483-b / US-893-a: APPLY the level the light bridge published in
        // states/light (pure consumer -- never the sensor, never a curve). A
        // STOP takeover up (US-899-a1: states/alerts.takeover, the same cached
        // read the takeover painted from) holds it at full; an absent/stale feed holds the injected
        // defaultLevel (honest fallback). See appliedBrightness.
        // US-507: `stateOnce` is idempotent, so this REUSES the payload the
        // Health card's Light section already read and only performs a real
        // fetch if no surface consumed it -- the auto-dim keeps working even if
        // the section is ever removed from the markup, with no flag to forget.
        await stateOnce("light");
        applyBrightness(
          appliedBrightness(
            lightData,
            displayAutoDim,
            nowMs,
            brightnessAlarmActive(lastAlerts),
            settingsSource
          ).level
        );
      }

      // US-508 / Atlas transport ruling: the live feed gets its OWN ~10 Hz loop
      // off the same states_http_server (localhost, no-store). A compass tape
      // and a g-trail cannot animate at the 4 Hz card tick, and raising that
      // tick would re-read five other state files 2.5x for nothing. No new
      // transport: the bridge writes latest-wins at 10-15 Hz and this reads the
      // newest. setTimeout (not setInterval) so a slow read cannot stack.
      async function imuTick() {
        lastImu = await fetchState("imu");
        // US-700: the live feed does NOT go through `stateOnce` (it has its own
        // loop), so it books its own arrival. Missing this is how the motion
        // card would have sat at LOADING while every other tile moved on.
        feedSeen = feedObserved(feedSeen, "imu", lastImu);
        var nowMs = Date.now();
        renderMotion(nowMs);
        renderNav(nowMs);
      }

      // US-896-a: paint the NAV heading from the RAW states/imu (the provider's
      // value; the glide is the only motion between readings, spec s4.1). While
      // a glide is moving, the browser's frame clock repaints it so the tape
      // glides rather than stepping at the 100 ms poll; without
      // requestAnimationFrame the poll alone repaints it.
      function renderNav(nowMs) {
        if (!navCard) return;
        var view = navHeadingView(
          lastImu, nowMs, resolveImuStaleSec(global && global.DISPLAY_STALE)
        );
        navGlide = navGlideStep(navGlide, view, nowMs, prefersReducedMotion());
        renderNavCard(navCard, view, navDrawnDeg(navGlide, nowMs));
        // US-896-b: GRADE from the same states/imu read, on the same clock.
        renderNavGrade(navCard, navGradeView(lastImu, nowMs));
        if (navGliding(navGlide, nowMs) && !navFramePending &&
            typeof global.requestAnimationFrame === "function") {
          navFramePending = true;
          global.requestAnimationFrame(function () {
            navFramePending = false;
            renderNav(Date.now());
          });
        }
      }

      // prefers-reduced-motion => the tape STEPS to each reading (spec s4.1).
      // Read per paint, so a change to the OS setting applies at once.
      function prefersReducedMotion() {
        return typeof global.matchMedia === "function" &&
          global.matchMedia("(prefers-reduced-motion: reduce)").matches === true;
      }

      // ARCH-014: the loops are BUILT here rather than self-scheduling, so a
      // throw anywhere in a body costs one frame instead of the session.
      installGlobalErrorReporting(global, reportLoopError);
      var tickLoop = makeResilientLoop({
        name: "tick",
        delayMs: POLL_MS,
        deadlineMs: TICK_DEADLINE_MS,
        body: tick,
        schedule: setTimeout,
        report: reportLoopError,
      });
      var imuTickLoop = makeResilientLoop({
        name: "imuTick",
        delayMs: IMU_POLL_MS,
        deadlineMs: TICK_DEADLINE_MS,
        body: imuTick,
        schedule: setTimeout,
        report: reportLoopError,
      });
      tickLoop();
      imuTickLoop();
      reportFirstFrame(global, "dashboard");
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", setup);
    } else {
      setup();
    }
  }

  // -------------------------------------------------------------------------
  // Export (node unit tests) / attach (browser global).
  // -------------------------------------------------------------------------
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    global.Carousel = api;
  }
})(typeof window !== "undefined" ? window : globalThis);

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
  //: US-662 -- DISPLAY smoothing. The CIO, 2026-08-31, after reading the panel:
  //: "the heading is flickering plus or minus two or three degrees ... we need to
  //: add a 3-second smoothing function to some of these readings FOR DISPLAY
  //: PURPOSES ONLY."
  //:
  //: THE ARCHITECTURE IS IN HIS LAST FOUR WORDS. Smoothing is a VIEW concern.
  //: `lastImu` stays RAW, the state files stay RAW, the database stays RAW.
  //: Landing a smoothed number would write something no sensor ever reported --
  //: the ambient-temperature defect rebuilt.
  //:
  //: The window is in MILLISECONDS, not samples, so it behaves identically on
  //: the 4 Hz card tick and the 10 Hz live tick. A count-based window would
  //: smooth over 3 s on one loop and 0.4 s on the other.
  var SMOOTH_WINDOW_MS = 3000;

  //: Smoothed for display. Deliberately explicit and deliberately SHORT.
  //: ⚠️ Nothing alert-bearing, and never speed or rpm: smoothing buys steadiness
  //: with LATENCY -- a 3 s window shows a real event about 1.5 s late, which is
  //: correct for a glance instrument and disqualifying for anything that warns.
  var SMOOTHED_FIELDS = ["headingDeg", "gLat", "gLon", "gradePct"];

  //: Only a BEARING wraps. Grade and g are linear, and a circular mean applied
  //: to them would be cargo-culting the fix onto values it cannot help.
  var ANGULAR_FIELDS = ["headingDeg"];

  function makeSmoothWindow(windowMs) {
    var samples = [];
    return {
      push: function (value, atMs) {
        // A non-finite reading is not a sample. Pushing it would let an absent
        // value pull the mean, which is how a smoothed display invents data.
        if (typeof value !== "number" || !isFinite(value)) return false;
        samples.push({ v: value, t: atMs });
        return true;
      },
      values: function (nowMs) {
        var cutoff = nowMs - windowMs;
        var out = [];
        for (var i = 0; i < samples.length; i++) {
          if (samples[i].t > cutoff) out.push(samples[i].v);
        }
        return out;
      },
      prune: function (nowMs) {
        var cutoff = nowMs - windowMs;
        var kept = [];
        for (var i = 0; i < samples.length; i++) {
          if (samples[i].t > cutoff) kept.push(samples[i]);
        }
        samples = kept;
      },
    };
  }

  function linearMean(values) {
    if (!values || !values.length) return null;
    var sum = 0;
    var n = 0;
    for (var i = 0; i < values.length; i++) {
      if (typeof values[i] === "number" && isFinite(values[i])) {
        sum += values[i];
        n += 1;
      }
    }
    return n ? sum / n : null;
  }

  function circularMeanDeg(values) {
    // 🔴 A BEARING CANNOT BE AVERAGED ARITHMETICALLY. The mean of
    // 358, 359, 1, 2 is 180 -- the display would point SOUTH while the car
    // drives NORTH. Average unit vectors instead.
    //
    // This is the failure that passes every test which does not cross north,
    // which is most of them, so the wrap case is pinned explicitly in the tests.
    if (!values || !values.length) return null;
    var sumSin = 0;
    var sumCos = 0;
    var n = 0;
    for (var i = 0; i < values.length; i++) {
      var v = values[i];
      if (typeof v !== "number" || !isFinite(v)) continue;
      var rad = (v * Math.PI) / 180;
      sumSin += Math.sin(rad);
      sumCos += Math.cos(rad);
      n += 1;
    }
    if (!n) return null;
    var mean = (Math.atan2(sumSin / n, sumCos / n) * 180) / Math.PI;
    return (mean + 360) % 360;
  }

  var smoothWindows = {};

  function pushImuSamples(data, nowMs) {
    // Called where the READING ARRIVES, never at render -- so the window tracks
    // the sensor's cadence rather than the paint rate.
    if (!isObj(data)) return;
    for (var i = 0; i < SMOOTHED_FIELDS.length; i++) {
      var f = SMOOTHED_FIELDS[i];
      if (!smoothWindows[f]) smoothWindows[f] = makeSmoothWindow(SMOOTH_WINDOW_MS);
      smoothWindows[f].push(data[f], nowMs);
      smoothWindows[f].prune(nowMs);
    }
  }

  function smoothedImuView(data, nowMs) {
    // Returns a COPY. The caller's object is never mutated, so `lastImu` -- the
    // thing every other consumer reads -- stays raw.
    if (!isObj(data)) return data;
    var view = {};
    for (var k in data) {
      if (Object.prototype.hasOwnProperty.call(data, k)) view[k] = data[k];
    }
    for (var i = 0; i < SMOOTHED_FIELDS.length; i++) {
      var f = SMOOTHED_FIELDS[i];
      var raw = data[f];
      // ⚠️ An absent reading STAYS absent. Smoothing must never resurrect a
      // value from history when the live one is unavailable -- that would turn
      // an honest NA into a stale number, which is worse than the jitter.
      if (typeof raw !== "number" || !isFinite(raw)) {
        view[f] = raw;
        continue;
      }
      var w = smoothWindows[f];
      if (!w) continue;
      var vals = w.values(nowMs);
      var mean =
        ANGULAR_FIELDS.indexOf(f) >= 0 ? circularMeanDeg(vals) : linearMean(vals);
      if (mean !== null) view[f] = mean;
    }
    return view;
  }

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
  var NO_DATA_VIEWS = {
    dtc: { label: "ALERTS", reason: "no data -- codes not read" },
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

  function seenDetail(s) {
    return s == null ? "" : "seen " + s + "s ago";
  }

  // OBD link tile: linked -> ok; reconnecting -> amber (I-033 visibility, the
  // operator SEES the retry); down -> red; missing/unknown -> unavailable.
  function obdLinkTile(o) {
    if (!isObj(o)) {
      return { label: "OBD LINK", value: "—", detail: "unavailable", level: "unavailable" };
    }
    var seen = seenDetail(o.lastSeenS);
    if (o.state === "linked") {
      return { label: "OBD LINK", value: "LINKED", detail: seen, level: "ok" };
    }
    if (o.state === "reconnecting") {
      var d = "retry " + (o.retries == null ? 0 : o.retries);
      if (seen) d += " · " + seen;
      return { label: "OBD LINK", value: "RECONNECTING", detail: d, level: "amber" };
    }
    if (o.state === "down") {
      return { label: "OBD LINK", value: "DOWN", detail: seen || "no signal", level: "down" };
    }
    return { label: "OBD LINK", value: "—", detail: "unavailable", level: "unavailable" };
  }

  // Sync tile: stale-while-driving -> amber (I-4); otherwise ok. The emitter
  // owns the stale DECISION (no green-when-broken); the tile renders it.
  function syncTile(s) {
    if (!isObj(s)) {
      // No counts to carry: nothing was measured and nothing was even offered.
      // An em-dash pair here would invent a diagnostics line for a source that
      // never reported (the fabrication one layer up from US-564's zero).
      return {
        label: "SYNC", value: "—", detail: "unavailable",
        level: "unavailable", counts: "",
      };
    }
    // US-564: a null count renders as an em-dash, NEVER as 0. Both halves of this
    // had to change together -- the emitter stopped inventing `syncPending=0`
    // and this line stopped re-inventing it -- because either coercion alone
    // ships green and the panel still reads "0 pending", which is an all-clear
    // on whether the drive is backed up that nobody ever measured.
    var pending = s.pending == null ? "—" : s.pending;
    var counts = (s.rows == null ? "—" : s.rows) + " rows · " + pending + " pending";
    // US-559 (CIO placement call, 2026-08-20): the STAMP is what gets read at a
    // glance, so it takes the tile's one detail line to itself; the counts are
    // diagnostics you go looking for and move to the System drill-down. They are
    // still derived HERE, once, and the overlay merely presents `counts` -- a
    // drill-down that re-derived them could disagree with the card behind it.
    //
    // No "last " prefix: the tile is already labelled SYNC, and the prefix cost
    // characters on a band P-3 had just re-budgeted. `never` stays bare and
    // unformatted -- an absent sync is the one place a date would be the worst
    // possible fabrication.
    var last = s.lastOkTs == null ? "never" : fmtStamp(s.lastOkTs);
    if (s.stale === true) {
      // The stamp is MORE load-bearing on this branch, not less: it is the
      // answer to "how stale?".
      return { label: "SYNC", value: "STALE", detail: last, level: "amber", counts: counts };
    }
    return { label: "SYNC", value: "OK", detail: last, level: "ok", counts: counts };
  }

  // Power tile: running on battery (UPS backup) -> amber; external -> ok.
  function powerTile(p) {
    if (!isObj(p)) {
      return { label: "POWER", value: "—", detail: "unavailable", level: "unavailable" };
    }
    // Power-mode SSOT (US-421 / BL-014): honour car/wall exactly; anything
    // else -- absent, stale, invalid -- is `unknown`, never a confident CAR
    // (honest-instrument). `unknown` renders lowercase so a real known mode is
    // visibly the confident one (CAR/WALL).
    var mode = p.mode === "car" || p.mode === "wall" ? p.mode : "unknown";
    var modeBadge = mode === "unknown" ? "unknown" : mode.toUpperCase();
    if (p.source === "battery") {
      return { label: "POWER", value: "BATTERY", detail: mode + " · on UPS", level: "amber" };
    }
    if (p.source === "external") {
      return { label: "POWER", value: modeBadge, detail: "external", level: "ok" };
    }
    return { label: "POWER", value: "—", detail: "unavailable", level: "unavailable" };
  }

  // Drive tile: recording -> active (ok); idle -> neutral (no warning, no green).
  function driveTile(d) {
    if (!isObj(d)) {
      return { label: "DRIVE", value: "—", detail: "unavailable", level: "unavailable" };
    }
    if (d.state === "recording") {
      var id = d.driveId == null ? "?" : d.driveId;
      return { label: "DRIVE", value: "REC", detail: "drive " + id, level: "ok" };
    }
    if (d.state === "idle") {
      return { label: "DRIVE", value: "IDLE", detail: "not recording", level: "neutral" };
    }
    return { label: "DRIVE", value: "—", detail: "unavailable", level: "unavailable" };
  }

  // Top-bar glyph states (bound to data-state CSS in dashboard.css).
  function btGlyphState(o) {
    if (!isObj(o)) return "neutral";
    if (o.state === "linked") return "ok";
    if (o.state === "reconnecting") return "amber";
    if (o.state === "down") return "down";
    return "neutral";
  }
  function syncGlyphState(s) {
    if (!isObj(s)) return "neutral";
    return s.stale === true ? "amber" : "ok";
  }
  function powerGlyphState(p) {
    if (!isObj(p)) return "neutral";
    if (p.source === "battery") return "amber";
    if (p.source === "external") return "ok";
    return "neutral";
  }

  // -------------------------------------------------------------------------
  // US-489 (Iris polish P-1) -- the one-glance SUMMARY line. A lossy
  // compression of the four tiles, which makes it exactly the place a
  // "green when broken" lie would enter, so honest-instrument F-1 is restated
  // here at the CARD level: the line is `ok` ONLY when every source is
  // genuinely good. Presentation-only -- it reads the tiles the card already
  // renders, never a second read of the state.
  // -------------------------------------------------------------------------

  // Display order == grid order, so "the worst source" is always named in a
  // stable, predictable place.
  var SYS_TILE_ORDER = ["obdLink", "sync", "power", "drive"];

  // Severity rank over the tile-level vocabulary. Three buckets, not two:
  //   ok            -- genuinely good.
  //   neutral       -- nominal but inactive. DRIVE=IDLE is the only neutral
  //                    this card produces and it means "not recording", NOT
  //                    "broken"; counting it as a fault would make green
  //                    unreachable in the commonest state (key on, no drive
  //                    started), which is its own dishonesty -- crying wolf.
  //   unavailable   -- a known-UNKNOWN. Blocks green (never claim OK over a
  //                    source we cannot read) without raising an alarm.
  //   amber / down  -- the only ISSUES.
  var SYS_LEVEL_RANK = { ok: 0, neutral: 1, unavailable: 2, amber: 3, down: 4 };
  var SYS_ISSUE_RANK = SYS_LEVEL_RANK.amber;

  // A level this mapper has not been taught resolves to `unavailable`, NEVER to
  // ok -- a future tile level must not be able to paint the card green by
  // default.
  function sysLevelRank(level) {
    return Object.prototype.hasOwnProperty.call(SYS_LEVEL_RANK, level)
      ? SYS_LEVEL_RANK[level]
      : SYS_LEVEL_RANK.unavailable;
  }

  function sysNoStateSummary() {
    return {
      text: "SYSTEM · UNAVAILABLE",
      detail: "no system state",
      level: "unavailable",
      issues: 0,
    };
  }

  // Summarise the four rendered tiles. The ISSUE COUNT is the glanceable fact;
  // the worst source is NAMED in the detail so the line says what to look at
  // without the operator reading all four tiles.
  function systemSummary(tiles) {
    if (!isObj(tiles)) return sysNoStateSummary();
    var worst = null;
    var worstRank = -1;
    var issues = 0;
    var unknowns = 0;
    for (var i = 0; i < SYS_TILE_ORDER.length; i++) {
      var tile = tiles[SYS_TILE_ORDER[i]];
      if (!isObj(tile)) continue;
      var rank = sysLevelRank(tile.level);
      if (rank >= SYS_ISSUE_RANK) issues++;
      else if (rank === SYS_LEVEL_RANK.unavailable) unknowns++;
      if (rank > worstRank) {
        worstRank = rank;
        worst = tile;
      }
    }
    if (worst === null) return sysNoStateSummary();
    var named = worst.label + " · " + worst.value;
    if (issues > 0) {
      // `worst` carries the highest rank, so with any issue present it IS an
      // issue tile -- its level is amber/down and drives the headline hue.
      return {
        text: "SYSTEM · " + issues + (issues === 1 ? " ISSUE" : " ISSUES"),
        detail: named,
        level: worst.level,
        issues: issues,
      };
    }
    if (unknowns > 0) {
      return {
        text: "SYSTEM · " + unknowns + " UNAVAILABLE",
        detail: named,
        level: "unavailable",
        issues: 0,
      };
    }
    return { text: "SYSTEM · OK", detail: "", level: "ok", issues: 0 };
  }

  // -------------------------------------------------------------------------
  // US-509 (F-124) -- the drill-down behind the summary line. The headline is a
  // lossy compression of four tiles; without this it is a dead end that names a
  // count and nothing to act on. The rows are a PRESENTATION of the SAME tiles
  // the grid renders -- no second read, no re-derivation, so the overlay can
  // never contradict the card behind it.
  // -------------------------------------------------------------------------

  // The listing floor. Deliberately `unavailable`, not `amber`:
  //   * `ok`      -- never listed. A green source in a fault list is a
  //                  FABRICATED fault.
  //   * `neutral` -- never listed either. DRIVE=IDLE is the only neutral this
  //                  card produces and it means "not recording", NOT "broken";
  //                  listing it would report a fault in the commonest state
  //                  there is (key on, no drive started) -- crying wolf.
  //   * `unavailable` and worse -- listed. The summary reads "SYSTEM · N
  //                  UNAVAILABLE" in that state, so excluding known-unknowns
  //                  would make a tappable headline open an EMPTY overlay,
  //                  which is the exact dead end this story removes.
  var SYS_ROW_FLOOR = SYS_LEVEL_RANK.unavailable;

  // The typed absence for a source that publishes no age at all. Only the OBD
  // source emits `lastSeenS` today, so the other three MUST say the age was not
  // reported rather than render "seen 0s ago" -- which would claim we had just
  // seen a source we never timed. Same fabrication as a zeroed altitude
  // (US-508): an unmeasured quantity is an absence, never a zero.
  var SYS_NO_AGE = "age not reported";

  // Read one source's own freshness fact out of the SAME payload the tiles were
  // built from. A non-finite or negative age is not a reading.
  function sysRowFreshness(data, key) {
    if (isObj(data) && isObj(data[key])) {
      var s = data[key].lastSeenS;
      if (typeof s === "number" && isFinite(s) && s >= 0) return seenDetail(s);
    }
    return SYS_NO_AGE;
  }

  // Worst-first rows, one per non-OK source. Ties keep the 2x2 grid order, so
  // the list never reshuffles between polls under the operator's eyes. Built by
  // walking the rank buckets top-down rather than sorting, which makes that
  // stability a property of the construction instead of the sort algorithm.
  function systemIssueRows(tiles, data) {
    var rows = [];
    if (!isObj(tiles)) return rows;
    var rank = SYS_LEVEL_RANK.down;
    for (; rank >= SYS_ROW_FLOOR; rank--) {
      for (var i = 0; i < SYS_TILE_ORDER.length; i++) {
        var key = SYS_TILE_ORDER[i];
        var tile = tiles[key];
        if (!isObj(tile) || sysLevelRank(tile.level) !== rank) continue;
        var freshness = sysRowFreshness(data, key);
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
          // the freshness the row prints beside it (the DOWN OBD tile's detail
          // IS the seen-age string).
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
  function systemDiagnostics(tiles) {
    var diags = [];
    if (!isObj(tiles)) return diags;
    var sync = tiles.sync;
    if (isObj(sync) && typeof sync.counts === "string" && sync.counts !== "") {
      diags.push({ key: "sync", label: sync.label, text: sync.counts });
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
    var diagnostics = systemDiagnostics(tiles);
    return {
      rows: rows,
      diagnostics: diagnostics,
      tappable: rows.length > 0 || diagnostics.length > 0,
    };
  }

  // The full structured view consumed by the DOM renderer + the node tests.
  // Non-object payload -> null (the shell renders `unavailable`).
  // ARCH-007 (Atlas ruling 2026-08-20 s2.1/s2.3). The emitter has ALREADY
  // derived the band; this maps its verdict to a glyph state and applies NO
  // threshold of its own.
  //
  // The load-bearing line is the last one: an unreadable link renders NEUTRAL,
  // never amber. `down` is a MEASUREMENT -- we looked and there is no link.
  // Painting "no signal" when the truth is "we could not look" is a fabricated
  // reading, which is the defect class this contract exists to prevent.
  function wifiGlyphState(data) {
    var src = data && data.source && data.source.wifi;
    if (!src || src.available !== true) return "neutral";
    var wifi = data.wifi || {};
    if (wifi.state === "up") return "ok";
    if (wifi.state === "weak") return "amber";
    if (wifi.state === "down") return "down";
    return "neutral";   // available but ungradeable -- still not a claim
  }

  function systemStatusView(data) {
    if (!isObj(data)) return null;
    // US-429: the OBD source owns the OBD-link tile + glyph. When the source is
    // unavailable (car off / wall power), render a typed NA ("OBD: off") rather
    // than a fabricated or stale link state -- sync/power/drive are their own
    // sources and stay honest independently (one truth per SOURCE).
    var obdOff = sourceUnavailable(data, "obd");
    var obdTile = obdOff
      ? naTile("OBD LINK", sourceReason(data, "obd"))
      : obdLinkTile(data.obdLink);
    var tiles = {
      obdLink: obdTile,
      sync: syncTile(data.sync),
      power: powerTile(data.power),
      drive: driveTile(data.drive),
    };
    return {
      // US-489: derived from the SAME tiles rendered below, so the headline can
      // never contradict the grid it summarises.
      summary: systemSummary(tiles),
      // US-509: and so is the drill-down behind that headline -- one read of
      // the state file feeds the grid, the summary AND the overlay.
      drill: systemDrill(tiles, data),
      tiles: tiles,
      glyphs: {
        bt: obdOff ? "neutral" : btGlyphState(data.obdLink),
        sync: syncGlyphState(data.sync),
        power: powerGlyphState(data.power),
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
  //        month-old reading is never mistaken for live. US-504 added a second
  //        layer upstream: the producer itself forces `unknown` once the last
  //        qualifying check is over 90 days old.
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
    var secs = Math.floor((now - then) / 1000);
    // A FUTURE instant means clock skew, not a negative age. The Pi has no RTC
    // battery and boots before NTP settles, so a stamp ahead of `now` is a
    // routine transient -- "-5 min ago" would be a visible nonsense.
    if (secs < 60) return "just now";
    if (secs < 3600) return Math.floor(secs / 60) + " min ago";
    if (secs < 86400) return Math.floor(secs / 3600) + " h ago";
    return ageText(ageDays(nowTs, thenTs));
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
    return {
      label: BATTERY_LABEL,
      unavailable: false,
      health: {
        label: "HEALTH",
        value: healthValue(data.health),
        detail: healthCheckLine(data).label,
        level: healthLevel(data.health),
      },
      vcell: vcellTile(data),
      soc: socTile(data),
      healthCheck: healthCheckLine(data),
      ladder: ladderView(data),
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  // -------------------------------------------------------------------------
  // US-420 LTFT Trend card -- pure render logic, node-testable (F-096). Long-
  // Term Fuel Trim is a MULTI-DRIVE signal: a healthy tune migrates the trim
  // TOWARD 0, drift beyond +/-10% is a fault. The `ltft-trend` emitter is the
  // SSOT that CLASSIFIES the drift (ok/amber/down) + the insufficient guard;
  // this view only maps the verdict -> a tile level + bar colours, it never
  // classifies. Honest-instrument (defense-in-depth): an insufficient trend is
  // forced to a non-green headline HERE too, so a mislabeled state can't paint
  // a confident green off too little data.
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
    // Sufficient ONLY when the emitter says so AND real points exist.
    var sufficient = data.sufficient === true && pts.length > 0;
    var current = isObj(data.current) ? data.current : null;
    // The headline verdict: the emitter's level when sufficient, else forced to
    // `insufficient` (never inherits ok/green off too little data).
    var headLevel = sufficient
      ? (typeof data.level === "string" ? data.level : "unavailable")
      : "insufficient";
    var trendKey = typeof data.trend === "string" ? data.trend : null;
    var minDrives = typeof data.minDrives === "number" ? data.minDrives : 2;
    var detail = sufficient
      ? (trendKey && LTFT_TREND_TEXT[trendKey] ? LTFT_TREND_TEXT[trendKey] : "")
      : "need " + minDrives + "+ drives (" + pts.length + " captured)";
    return {
      label: "LTFT (bank 1)",
      sufficient: sufficient,
      headline: {
        label: "LTFT · current drift",
        value: sufficient && current ? fmtLtftPct(current.ltftAvg) : "insufficient data",
        detail: detail,
        level: headLevel,
      },
      trend: trendKey,
      points: pts.map(ltftPointView),
      ts: typeof data.ts === "string" ? data.ts : null,
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
    {
      key: "ltft-trend", title: "Fuel Trim",
      vehicleGated: true,
      noData: { label: "FUEL TRIM", reason: "no data -- trend not computed" },
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
  // differ -- only the light view needs the dim config + a clock) stay explicit.
  function sourceView(key, data, cfg, nowMs) {
    if (cardAvailability(data) !== "available") return null;
    if (key === "battery-health") return batteryHealthView(data);
    if (key === "light") return lightView(data, cfg, nowMs);
    if (key === "ltft-trend") return ltftTrendView(data);
    return null;
  }

  function sourceCardView(spec, data, sysData, cfg, nowMs) {
    var base = { key: spec.key, title: spec.title };
    // The gate is checked FIRST and short-circuits: a gated card must carry no
    // reading, not a suppressed one (nothing downstream can leak what was never
    // derived).
    if (spec.vehicleGated && !vehicleConnected(sysData)) {
      base.gated = true;
      base.unavailable = false;
      base.na = { label: spec.noData.label, reason: FUEL_TRIM_GATED_REASON };
      base.view = null;
      return base;
    }
    var view = sourceView(spec.key, data, cfg, nowMs);
    base.gated = false;
    if (view === null) {
      base.unavailable = true;
      // Reuse the shipped whole-card wording where one exists (light), so the
      // silent-instrument phrasing lives in exactly one place.
      base.na = noDataView(spec.key) || spec.noData;
      base.view = null;
      return base;
    }
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
  var SETTINGS_APPLY_NOTES = {
    live: "applies now",
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
  // POWER MODE is "live": the card-state emitter's PowerModeProvider re-reads
  // the effective key on every cycle (OverlayConfigPowerModeSource), so the
  // power tile follows within one emit interval.
  //
  // CALIBRATION / AUTO-ANALYZE are "capture-restart": both are read ONCE into a
  // constructor at orchestrator start, so "live" would be a lie -- and the bare
  // "restart" US-532 shipped was true but useless, because the unit the operator
  // would reach for (states-http, the only one this band talks to) is the wrong
  // one. Name the service or the label does not help anybody.
  var SETTINGS_SPECS = [
    { key: "pi.display.carousel.autoRotateS", label: "Auto-rotate",
      kind: "seconds", apply: "reload" },
    { key: "pi.power.mode", label: "Power mode", kind: "mode", apply: "live" },
    { key: "pi.calibration.mode", label: "Calibration mode",
      kind: "bool", apply: "capture-restart" },
    { key: "pi.analysis.triggerAfterDrive", label: "Auto-analyze after drive",
      kind: "bool", apply: "capture-restart" },
  ];

  // Mirrors common.config.overlay.POWER_MODES. `unknown` is a LEGAL stored value
  // (the honest "no deployment context"), not an error state -- which is why the
  // row view keeps it distinct from "we could not read a value at all".
  var SETTINGS_POWER_MODES = ["car", "wall", "unknown"];

  var SETTINGS_PENDING_NOTE = "saving…";

  // US-533 B1: how long the "saved" note stays on screen before the reload that
  // actually applies an auto-rotate change. Long enough that the operator sees
  // the save was accepted, short enough that the reload reads as part of the
  // same tap rather than as the panel spontaneously restarting.
  var SETTINGS_RELOAD_DELAY_MS = 700;

  function settingsModeChoices() {
    return SETTINGS_POWER_MODES.slice();
  }

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

  // The choices offered for one setting. A toggle is a 2-choice segmented
  // control and power mode a 3-choice one, so BOTH render through one mechanism
  // -- and "unknown" is expressible as *no* choice selected, which is how an
  // unreadable setting shows itself instead of defaulting to a confident Off.
  function settingsChoices(spec) {
    if (spec && spec.kind === "mode") {
      return [
        { value: "car", label: "CAR" },
        { value: "wall", label: "WALL" },
        { value: "unknown", label: "UNKNOWN" },
      ];
    }
    return [
      { value: false, label: "Off" },
      { value: true, label: "On" },
    ];
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
    var mode = null;
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
    } else if (kind === "mode") {
      known =
        typeof value === "string" && SETTINGS_POWER_MODES.indexOf(value) !== -1;
      if (known) {
        mode = value;
        display = value.toUpperCase();
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
      mode: mode,
      display: display,
    };
  }

  // Is this choice the one currently stored? An unknown row selects NOTHING --
  // highlighting a choice would assert a stored value we do not have.
  function settingsChoiceActive(view, choiceValue) {
    if (!view || !view.known) return false;
    if (view.kind === "mode") return view.mode === choiceValue;
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
    if (spec.kind === "mode") {
      return SETTINGS_POWER_MODES.indexOf(desired) !== -1 ? desired : "unknown";
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
  // still drives the idle home face, and the US-511 debounce is left intact but
  // is now UNWIRED (TD-us659 -- retire it or find its next consumer; that is a
  // design call, not a side effect of this deletion).

  // -------------------------------------------------------------------------
  // US-511 (F-124) -- the DEBOUNCED `parked` signal behind the ⋮ affordance.
  //
  // US-490 keyed the kebab straight off the emitter's `idle` SSOT boolean, so
  // every brief OBD-availability blip took the button off the screen and put it
  // straight back. Flicker on a fixed affordance does not read as "the state
  // changed" -- it reads as a broken panel. This inserts a HYSTERESIS debounce
  // between the flag and the menu policy:
  //
  //   not parked -> parked      idle held TRUE  for >= parkedOnS  (8 s)
  //   parked -> not parked      idle held FALSE for >= parkedOffS (3 s)
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

  // Advance the signal by one observation. `prev` is the last state, `rawIdle`
  // the emitter's flag for THIS poll, `nowMs` the tick clock.
  function parkedNext(prev, rawIdle, nowMs, cfg) {
    var state =
      isObj(prev) && typeof prev.parked === "boolean"
        ? { parked: prev.parked, raw: prev.raw === true, sinceMs: prev.sinceMs }
        : parkedInit();
    // Only a strict `true` is idle. carouselIdle already applies this rule
    // upstream; re-applying it means the reducer cannot be broken by a second
    // caller that hands it a raw payload field instead.
    var raw = rawIdle === true;
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
  // US-405 DTC takeover + ribbon -- pure, node-testable logic (S-1/S-2/R-2).
  // The display is a PURE CONSUMER of the `dtc` state (severity classified
  // upstream from Spool's table -- the Pi never decides it). The takeover fires
  // ONLY on a NEW code (`newSinceTs`), one at a time (highest severity = hero,
  // the rest fold into "+N more"); after Acknowledge/Dismiss a persistent ribbon
  // carries the alert on every card. `na` (auto-trans on this manual car) is a
  // quiet disposition -- never a takeover, never a ribbon (design §4/§5.2).
  // -------------------------------------------------------------------------

  // Severity ordering (worst-first). `na` is not an alert; `unknown` is a real
  // uncurated code (ranks below the classified tiers but still alerts honestly).
  var DTC_SEVERITY_RANK = { stop: 3, watch: 2, minor: 1, unknown: 0 };

  // Per-severity takeover styling. The display maps a tier -> color + directive
  // + dismiss behavior; it never classifies. US-484-b: STOP binds the STATE-
  // ALARM `--critical-red`, never a brand red -- if the brand mark and the
  // pull-over alarm are the same red the driver cannot tell them apart (Spool
  // 6d ch.2). The colour is only the 3rd reinforcement; dashboard.css carries
  // STOP by area + motion + text on a near-black field.
  // STOP has NO plain dismiss -- only
  // "Acknowledge" (which drops to the ribbon) so a misfire is never dismissed-
  // and-forgotten, yet the driver still keeps view control (design §5.1/D-3).
  // `unknown` (severity not curated) gets the honest middle: a "get diagnosed"
  // caution -- never a false "safe to clear" (green) nor a false "pull over".
  var TAKEOVER_STYLE = {
    stop: { colorVar: "--critical-red", icon: "⚠", directive: "REDUCE LOAD · PULL OVER",
            dismissLabel: "Acknowledge", plainDismiss: false },
    watch: { colorVar: "--amber-warn", icon: "⚠", directive: "DRIVE GENTLY · GET DIAGNOSED",
            dismissLabel: "Dismiss", plainDismiss: true },
    minor: { colorVar: "--green-ok", icon: "ⓘ", directive: "SAFE TO CLEAR ONCE LOGGED",
            dismissLabel: "Dismiss", plainDismiss: true },
    unknown: { colorVar: "--amber-warn", icon: "⚠", directive: "GET DIAGNOSED",
            dismissLabel: "Dismiss", plainDismiss: true },
  };

  function severityRank(sev) {
    return Object.prototype.hasOwnProperty.call(DTC_SEVERITY_RANK, sev)
      ? DTC_SEVERITY_RANK[sev]
      : -1;
  }

  // The alert-eligible codes, worst-first. `na` and any unrecognized severity
  // are dropped (they never alarm). Stable within a rank (input order kept).
  function alertableCodes(codes) {
    if (!Array.isArray(codes)) return [];
    var out = [];
    for (var i = 0; i < codes.length; i++) {
      var c = codes[i];
      if (isObj(c) && severityRank(c.severity) >= 0) out.push(c);
    }
    out.sort(function (a, b) { return severityRank(b.severity) - severityRank(a.severity); });
    return out;
  }

  // The takeover view for a NEW code, or null (no new code / no alertable code /
  // malformed). One takeover at a time: the worst code is the hero; the rest are
  // "+N more". Firing (vs a prior ack) is a stateful concern -> takeoverShouldShow.
  function takeoverView(data) {
    if (!isObj(data)) return null;
    // US-429 / Bug-3b: an unavailable DTC source (no read happened) NEVER fires
    // a takeover -- an absent source reads `unavailable`, not "no codes -> alert".
    if (sourceUnavailable(data, "dtc")) return null;
    if (data.newSinceTs == null) return null; // known code at boot -> ribbon only
    var alertable = alertableCodes(data.codes);
    if (alertable.length === 0) return null;   // no real fault (e.g. all `na`)
    var hero = alertable[0];
    var style = TAKEOVER_STYLE[hero.severity] || TAKEOVER_STYLE.unknown;
    return {
      newSinceTs: data.newSinceTs,
      severity: hero.severity,
      code: hero.code,
      short: (hero.short && String(hero.short).trim()) || "No description yet",
      directive: style.directive,
      colorVar: style.colorVar,
      icon: style.icon,
      dismissLabel: style.dismissLabel,
      plainDismiss: style.plainDismiss,
      moreCount: alertable.length - 1,
    };
  }

  // Edge-trigger: show the takeover only when its `newSinceTs` differs from the
  // last-acknowledged stamp. Same stamp -> already handled (no re-show); a newer
  // code changes the stamp -> re-fire (escalation, design D-3).
  function takeoverShouldShow(view, lastAckedTs) {
    return !!view && view.newSinceTs !== lastAckedTs;
  }

  // The persistent ribbon while ANY alert-eligible code is present (design §5.2).
  // Level = the hero severity (drives the color); `na`/empty -> null (no ribbon).
  function ribbonView(data) {
    if (!isObj(data)) return null;
    // US-429: an unavailable DTC source carries no active fault -> no ribbon.
    if (sourceUnavailable(data, "dtc")) return null;
    var alertable = alertableCodes(data.codes);
    if (alertable.length === 0) return null;
    var hero = alertable[0];
    var text = "CHECK ENGINE · " + hero.code;
    var desc = hero.short && String(hero.short).trim();
    if (desc) text += " " + desc;
    if (alertable.length > 1) text += " · +" + (alertable.length - 1) + " more";
    return { level: hero.severity, glyph: "⚠", text: text, code: hero.code };
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
  // The persistent ribbon/takeover still fire over every card, so retiring this
  // screen cannot suppress a genuine fault (Iris AC-5 survives the retirement).
  // -------------------------------------------------------------------------

  // idle is the emitter's SSOT (system-status `idle` boolean, US-480-a / Atlas
  // idle-SSOT b). The display RENDERS the flag; it NEVER re-derives idle from
  // the drive-state string (the replaced display-derived pattern). Anything
  // other than an explicit `true` (absent key / malformed file / false) reads
  // NOT-idle -- fail closed to the live view, never guess a calm parked state.
  function carouselIdle(systemStatusData) {
    return isObj(systemStatusData) && systemStatusData.idle === true;
  }

  // Last-drive summary fact (US-505). `drive.lastDrive` is the most recent
  // COMPLETED drive, produced Pi-locally from drive_summary -- a DIFFERENT fact
  // from `drive.driveId`, which is the ACTIVE drive and is null whenever nothing
  // is recording. Before that producer existed this tile had only driveId to
  // read, so it said "No recent drive" PERMANENTLY rather than until the next
  // drive: the absence was real, but it was the absence of a producer.
  //
  // Renders Iris's idle spec shape ("Drive 35 · 2 h ago") across the tile's
  // value + detail slots. Honest degradation is per-HALF: a drive whose start
  // timestamp is missing or unparseable still shows the drive and admits
  // "age unknown", because the drive genuinely happened and hiding it would lose
  // a real fact to protect a cosmetic one.
  function idleLastDriveFact(systemStatusData) {
    var label = "LAST DRIVE";
    if (!isObj(systemStatusData) || !isObj(systemStatusData.drive)) {
      return { label: label, value: "—", detail: "unavailable", level: "unavailable" };
    }
    var drive = systemStatusData.drive;
    if (drive.state === "recording") {
      var id = drive.driveId == null ? "?" : drive.driveId;
      return { label: label, value: "REC", detail: "drive " + id, level: "neutral" };
    }
    var last = drive.lastDrive;
    if (isObj(last) && last.driveId != null) {
      return {
        label: label,
        value: "Drive " + last.driveId,
        detail: agoText(systemStatusData.ts, last.startedAtTs),
        level: "neutral",
      };
    }
    // Legacy shape: an active driveId with no lastDrive block. Kept so a state
    // file written by an older Pi (or mid-deploy) still renders the id it has.
    if (drive.driveId != null) {
      return { label: label, value: "drive " + drive.driveId, detail: "last recorded", level: "neutral" };
    }
    return { label: label, value: "No recent drive", detail: "since key-off", level: "neutral" };
  }

  // Battery-with-age fact. The ONE line allowed to go green at idle -- and only
  // via the Spool verdict, always carrying its data-age (F-9 stale-green guard).
  // Reuses the battery-health view (single UPS source -> whole-card NA); prefers
  // SoC% but falls back to volts (a voltage is never rendered AS a percent).
  function idleBatteryFact(batteryData) {
    var label = "BATTERY";
    var view = batteryHealthView(batteryData);
    if (view === null) {
      return { label: label, value: "—", detail: "unavailable", level: "unavailable" };
    }
    if (view.unavailable) {
      return { label: label, value: "NA", detail: view.reason, level: "unavailable" };
    }
    var value = view.soc && view.soc.shown ? view.soc.value : view.vcell.value;
    return {
      label: label,
      value: value,
      detail: view.healthCheck.label,   // "last health check · <date> (<age>)"
      level: view.health.level,         // green ONLY on a `good` verdict (US-504)
    };
  }

  // The assembled fallback view consumed by the DOM renderer + the node tests.
  //
  // US-542: ONE disposition. The `motionless` ternary is gone with the STANDBY
  // hero it selected -- not because the branch was wrong, but because US-541
  // left it permanently false, and a condition that cannot be false is a claim
  // waiting to be made by accident. The hero now states the only fact this
  // screen exists to state: the motion instrument is down, and here is why.
  //
  // `dtcData` is GONE FROM THE SIGNATURE, and that is the guard, not a tidy-up
  // (the US-541 pattern). A view that cannot SEE the dtc payload cannot re-
  // borrow the Alerts fact that just moved off it; a future re-borrow has to
  // widen the signature first, which is a visible act rather than a line added
  // to a facts object.
  //
  // The footer stays a VIEW field rather than a renderer literal even now that
  // there is one of them: copy no test can reach is copy that drifts, which is
  // exactly what US-510 had to come back and repair on this very surface.
  function idleCardView(systemStatusData, batteryData, motionReason) {
    return {
      // US-510 A-1: the LOCKED wordmark, verbatim from Iris's idle spec
      // (2026-07-21-pi-idle-state-and-full-bleed.md §1.2). The build had
      // paraphrased it to "ECLIPSE"; nothing pinned it, which is exactly why it
      // drifted. It is BRANDING, not status, so it survives the retirement --
      // the LOCKED FOOTER did not: it was a parked-screen navigation hint, and
      // the screen it taught is gone. The ⋮ it named is still in the top bar.
      wordmark: "ECLIPSE OBD-II",
      hero: {
        title: "NO MOTION DATA",
        // Never fabricated: `homeFace` reaches this view only WITH a reason, so
        // the empty string here is an un-taken defensive floor, not a second
        // disposition wearing a default sentence.
        substate: typeof motionReason === "string" ? motionReason : "",
        level: "neutral",
      },
      footer: "live instrument resumes when the motion feed returns",
      // TWO facts, not three. `faults` left with the Alerts card (AC-2); what
      // remains is what a dead motion feed does not make unreadable.
      facts: {
        lastDrive: idleLastDriveFact(systemStatusData),
        battery: idleBatteryFact(batteryData),
      },
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

  // Tier -> display presentation (chip label + CSS level + hero/detail
  // directive). `unknown` = an uncurated code (no Spool entry) -> the honest
  // middle "GET DIAGNOSED", never a false "safe to clear" nor a false "pull
  // over". `na` = not applicable to this vehicle (quiet, unalarming).
  var DTC_TIER = {
    stop: { chip: "STOP", level: "stop", directive: "REDUCE LOAD · PULL OVER" },
    watch: { chip: "WATCH", level: "watch", directive: "DRIVE GENTLY · GET DIAGNOSED" },
    minor: { chip: "MINOR", level: "minor", directive: "SAFE TO CLEAR ONCE LOGGED" },
    unknown: { chip: "?", level: "unknown", directive: "GET DIAGNOSED" },
    na: { chip: "N/A", level: "na", directive: "not applicable to this vehicle" },
  };

  // List ordering for the Alerts card: worst-first, but `na` ALWAYS sorts last
  // (design §5.3) -- higher rank = higher in the list. An unrecognized severity
  // is treated as `unknown` (never dropped -- hiding a code could hide a fault).
  var DTC_LIST_RANK = { stop: 4, watch: 3, minor: 2, unknown: 1, na: 0 };

  function dtcTier(sev) {
    return Object.prototype.hasOwnProperty.call(DTC_TIER, sev)
      ? DTC_TIER[sev]
      : DTC_TIER.unknown;
  }

  function dtcListRank(sev) {
    return Object.prototype.hasOwnProperty.call(DTC_LIST_RANK, sev)
      ? DTC_LIST_RANK[sev]
      : DTC_LIST_RANK.unknown;
  }

  function dtcShort(code) {
    return (code.short && String(code.short).trim()) || "No description yet";
  }

  function dtcCaveat(code) {
    return (code.severityCaveat && String(code.severityCaveat).trim()) || null;
  }

  // All valid code objects sorted worst-first (na last). Stable within a rank
  // (input order preserved), so same-severity codes keep their capture order.
  function dtcListSorted(codes) {
    if (!Array.isArray(codes)) return [];
    var out = [];
    for (var i = 0; i < codes.length; i++) {
      if (isObj(codes[i])) out.push(codes[i]);
    }
    out.sort(function (a, b) { return dtcListRank(b.severity) - dtcListRank(a.severity); });
    return out;
  }

  // One compact list row (chip · code · short · caveat hint · status).
  function dtcRow(code) {
    var tier = dtcTier(code.severity);
    return {
      code: code.code,
      chip: tier.chip,
      level: tier.level,
      short: dtcShort(code),
      caveat: dtcCaveat(code),
      status: code.status === "pending" ? "PEND" : "STORED",
      isNa: code.severity === "na",
    };
  }

  // US-542 AC-2: the fact that MOVED here from the retired idle face. It was
  // always an Alerts fact -- "no read has happened" is a statement about the
  // codes, not about the parked screen that happened to be showing it -- and
  // the Alerts card could not otherwise say it: US-429 already refuses to print
  // "No stored codes" over an unread source, but a bare typed NA states only
  // that the instrument is silent, not that the silence dates from key-off.
  //
  // Level stays `unavailable`, NOT the idle face's `neutral`. On a card of
  // mixed tiles neutral read as "calm"; alone on the Alerts card it would read
  // as a completed read with nothing to report -- the exact false all-clear
  // US-429 exists to prevent. Grey is the whole dashboard's word for "no read".
  //
  // The emitter's own reason rides ALONGSIDE the moved line rather than being
  // replaced by it: "since key-off" is when, the reason is why, and dropping
  // either to make room for the other loses a real fact.
  function dtcNotReadTile(reason) {
    var why = reason == null ? "" : String(reason).trim();
    return {
      label: "ALERTS",
      value: "DTC not read",
      detail: why ? "since key-off · " + why : "since key-off",
      level: "unavailable",
    };
  }

  // The Alerts card view: hero (worst ALERT-eligible code + its directive; `na`
  // and unrecognized severities are never a hero) + the full list (worst-first,
  // na last) + stored/pending counts. Non-object payload -> null (the shell
  // renders `unavailable`). An empty `codes` array is a valid no-fault view.
  function alertsCardView(data) {
    if (!isObj(data)) return null;
    // US-429: an unavailable DTC source (no read happened) is a typed NA -- NOT
    // "No stored codes" (which would falsely imply a clean all-clear read).
    if (sourceUnavailable(data, "dtc")) {
      var why = sourceReason(data, "dtc");
      return { unavailable: true, reason: why, notRead: dtcNotReadTile(why) };
    }
    var codes = Array.isArray(data.codes) ? data.codes.filter(isObj) : [];
    var alertable = alertableCodes(codes); // drops na + unrecognized (never a hero)
    var hero = null;
    if (alertable.length > 0) {
      var h = alertable[0];
      var t = dtcTier(h.severity);
      hero = {
        code: h.code,
        chip: t.chip,
        level: t.level,
        short: dtcShort(h),
        directive: t.directive,
        caveat: dtcCaveat(h),
      };
    }
    var stored = 0;
    var pending = 0;
    for (var i = 0; i < codes.length; i++) {
      if (codes[i].status === "pending") pending++;
      else stored++;
    }
    return {
      hero: hero,
      rows: dtcListSorted(codes).map(dtcRow),
      storedCount: stored,
      pendingCount: pending,
      mil: data.mil === true,
    };
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

  // The per-code detail view. Non-object -> null. The caveat is a line, never a
  // tier upgrade (S-13).
  //
  // US-491 (polish P-3, directive-first): the band renders for EVERY actionable
  // tier, not just 🔴/🟡. The detail is the one screen the operator opens to ask
  // "what do I do", and the answer already existed in DTC_TIER for MINOR ("safe
  // to clear once logged") and for an uncurated `unknown` ("get diagnosed") --
  // the takeover has shown both since US-405 while the detail showed nothing.
  // A blank band on the screen dedicated to the question reads as "no action
  // needed", which is the dishonest answer on an uncurated code (F-1). `na` is
  // the one tier that stays blank: "not applicable to this vehicle" is a FACT,
  // not an instruction, it never alarms anywhere else in the system, and the
  // fix slot already states it.
  function codeDetailView(code) {
    if (!isObj(code)) return null;
    var tier = dtcTier(code.severity);
    return {
      code: code.code,
      chip: tier.chip,
      level: tier.level,
      short: dtcShort(code),
      long: (code.long && String(code.long).trim()) || null,
      directive: tier.level === "na" ? null : tier.directive,
      caveat: dtcCaveat(code),
      statusMeta: dtcStatusMeta(code),
      freezeFrame: freezeFrameView(code),
      fix: fixArea(code),
      logged: code.logged === true,
      syncAcked: code.syncAcked === true,
      clearEligible: code.clearEligible === true,
      isNa: code.severity === "na",
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
    sync_pending: "🔒 CLEAR CODES — waiting for server sync",
    session_locked: "🔒 CLEAR CODES — a cleared code returned; clearing again won't fix it",
  };

  // Re-derive the clear gate from the raw codes (the display mirror of the
  // server-side dtc_clear.evaluateClearGate). Deliberately IGNORES any
  // precomputed clearGate.enabled -- the button never lies just because the
  // state's flag does. Mode 04 is all-or-nothing, so the gate keys off ALL
  // stored (non-na) codes, not the one on screen.
  function clearGateReason(data) {
    if (!isObj(data)) return "no_codes";
    var codes = Array.isArray(data.codes) ? data.codes.filter(isObj) : [];
    var relevant = codes.filter(function (c) {
      return c.status === "stored" && c.severity !== "na";
    });
    if (relevant.length === 0) return "no_codes";
    if (relevant.some(function (c) { return c.severity !== "minor"; })) {
      return "severity_present";
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
  function clearButtonView(data) {
    var reason = clearGateReason(data);
    if (reason === "no_codes") {
      return { visible: false, enabled: false, reason: reason, label: null };
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
  // The dashboard is a PURE CONSUMER of the states/light file US-483-a writes
  // ({lux, ts}); it NEVER reads the sensor. The auto-dim curve values are
  // GROUNDED CONFIG PARAMETERS injected at serve time (window.DISPLAY_AUTODIM),
  // so tuning is a config change, not a code change (CIO 2026-07-22). These
  // built-in defaults are the file:// preview / unconfigured fallback and MIRROR
  // config.json pi.display.autoDim.* (the tuning SSOT). Honest-instrument: an
  // absent/stale/saturated (null) reading holds the fixed default -- never a
  // fabricated "auto" behavior; and a real active STOP alert is held at FULL
  // brightness regardless of lux (the load-bearing safety guard, US-484-b).
  // -------------------------------------------------------------------------

  // Spool 6d ch.4 (US-484-b): "a red alarm is full brightness always,
  // independent of auto-dim -- only ambient content dims." Full IS the top of
  // the 0..1 range, so this is a definition, not a tunable: there is no config
  // key that may lower a live PULL-OVER alarm.
  var STOP_ALARM_LEVEL = 1.0;

  var BRIGHTNESS_DEFAULTS = {
    luxMin: 3.0,          // lux <= this -> min (grounded: civil-twilight dark)
    luxFull: 1000.0,      // lux >= this -> full (grounded: overcast daylight)
    minLevel: 0.15,       // US-627 -- READ THE NAME CAREFULLY: this is the floor
                          // on the CURVE branch, NOT a floor on displayed
                          // brightness. The absent/stale-feed branch of
                          // brightnessLevel() returns defaultLevel UNCLAMPED and
                          // never consults this value.
    defaultLevel: 0.70,   // fixed fallback when the feed is absent/stale/
                          // saturated. Returned UNCLAMPED, so it must never sit
                          // below minLevel -- validate_config enforces
                          // defaultLevel >= minLevel (US-627); it is deliberately
                          // NOT clamped here.
    // US-595 -- alarmFloorLevel was HERE and is RETIRED. It was superseded by
    // STOP_ALARM_LEVEL above (US-484-b ch.4: a STOP goes to FULL), which left it
    // resolvable but unreachable -- a tunable that looked adjustable and changed
    // nothing. Removing it here is SAFE, and specifically because the merge
    // below iterates BRIGHTNESS_DEFAULTS rather than the injected object: a
    // deployed config.json still carrying the key is ignored BY CONSTRUCTION,
    // not by a rule anyone has to remember. Do not re-add it to restore
    // compatibility -- there is nothing to be compatible with.
    luxStaleSec: 10,      // a reading older than this -> fallback
    curve: "logarithmic", // perceptual mapping between luxMin..luxFull
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
        if (key === "curve") {
          if (typeof v === "string") out[key] = v;
        } else if (typeof v === "number" && isFinite(v)) {
          out[key] = v;
        }
      }
    }
    return out;
  }

  // The perceptual lux -> 0..1 mapping. Returns 0 at/below luxMin, 1 at/above
  // luxFull, and a curve value between. A degenerate range (luxFull <= luxMin)
  // or a non-positive luxMin under the log curve falls back to linear/full so it
  // can never divide by zero or take log of a non-positive number.
  function brightnessCurve(lux, luxMin, luxFull, curve) {
    if (typeof lux !== "number" || !isFinite(lux)) return 0;
    if (!(luxFull > luxMin)) return 1; // misconfigured range -> full, never div0
    if (lux <= luxMin) return 0;
    if (lux >= luxFull) return 1;
    if (curve !== "linear" && luxMin > 0 && lux > 0) {
      return (
        (Math.log(lux) - Math.log(luxMin)) /
        (Math.log(luxFull) - Math.log(luxMin))
      );
    }
    return (lux - luxMin) / (luxFull - luxMin);
  }

  // The fresh, finite lux from a states/light payload, or null (fall back). A
  // missing/malformed file, a null lux (honest saturation), a non-finite value,
  // or a reading older than luxStaleSec all read null -> the caller holds the
  // fixed default rather than trusting a frozen/absent value.
  function freshLux(lightData, luxStaleSec, nowMs) {
    if (!lightData || typeof lightData !== "object") return null;
    var lux = lightData.lux;
    if (typeof lux !== "number" || !isFinite(lux)) return null;
    // ARCH-010, defence in depth. A negative lux is a computation failure, not
    // a dark reading -- and it is FINITE, so isFinite() waved it through. It
    // then hit `lux <= luxMin -> 0` below and drove the panel to minLevel, so
    // the brighter the sun the dimmer the screen. The producer now publishes
    // null for this, but the consumer must not depend on that being deployed:
    // this slipped past three type checks once already.
    if (lux < 0) return null;
    var ts = lightData.ts;
    if (typeof ts !== "string") return null;
    var t = Date.parse(ts);
    if (isNaN(t)) return null;
    var ageSec = (nowMs - t) / 1000;
    if (!(ageSec <= luxStaleSec)) return null; // stale (or NaN age) -> fallback
    return lux;
  }

  // A real ACTIVE STOP alert is present (drives the alarm floor). Reuses the same
  // honest ribbon classifier the takeover/ribbon use: an unavailable DTC source
  // carries no active fault -> false; only a STOP-tier hero forces the floor (the
  // PULL-OVER alarm). A WATCH/MINOR alert is a real code but not the pull-over
  // alarm, so it does not force the legible floor (Iris AC-7 scope).
  function brightnessAlarmActive(dtcData) {
    var rv = ribbonView(dtcData);
    return !!rv && rv.level === "stop";
  }

  // The final 0..1 brightness: clamp(minLevel, curve(lux), 1.0) when the feed is
  // fresh, else the fixed default (honest fallback).
  //
  // US-484-b / Spool 6d ch.4 -- the load-bearing safety short-circuit: while a
  // real STOP is active the surface is FULL, before any ambient math runs. It
  // overrides the curve and the fixed default, so a dark cabin (or a dead light
  // sensor) can never dim a PULL-OVER alarm. It also SUPERSEDED the old
  // alarmFloorLevel config key outright -- full brightness is stronger than any
  // floor -- which is why US-595 could retire that key entirely.
  //
  // US-627 -- THE TWO BRANCHES ARE DELIBERATELY ASYMMETRIC, AND THAT IS WHY THE
  // FLOOR IS ENFORCED AT CONFIG TIME. The curve branch clamps to c.minLevel; the
  // lux === null branch returns c.defaultLevel UNCLAMPED. So c.minLevel bounds
  // the CURVE, never displayed brightness -- a defaultLevel beneath it would
  // render below the floor exactly when the light sensor has failed (FOUND
  // 2026-08-29: minLevel was raised 0.5 -> 0.75 for a dark garage while
  // defaultLevel sat at 0.70).
  //
  // The fix is a validator rule -- pi.display.autoDim.defaultLevel must be >=
  // minLevel, rejected loudly by validate_config. It is NOT clamped here ON
  // PURPOSE: clamping would silently repair a bad config and leave the operator
  // believing a value that never takes effect, which is the inert-guard shape
  // this project has catalogued repeatedly. A bad config must fail at the gate,
  // not be quietly corrected on the panel.
  function brightnessLevel(lightData, cfg, nowMs, alarmActive) {
    if (alarmActive) return STOP_ALARM_LEVEL;
    var c = resolveAutoDimConfig(cfg);
    var lux = freshLux(lightData, c.luxStaleSec, nowMs);
    var level;
    if (lux === null) {
      // absent/stale/saturated -> fixed default. Intentionally NOT floored to
      // c.minLevel: validate_config guarantees defaultLevel >= minLevel, so a
      // clamp here could only ever mask a config that failed that gate (US-627).
      level = c.defaultLevel;
    } else {
      var curved = brightnessCurve(lux, c.luxMin, c.luxFull, c.curve);
      level = Math.min(Math.max(curved, c.minLevel), 1.0);
    }
    return Math.min(Math.max(level, 0), 1);
  }

  // -------------------------------------------------------------------------
  // US-496 Light card (S3, F-121) -- pure, node-testable. The card is a PURE
  // CONSUMER of the SAME states/light file ({lux, ts}) that drives the auto-dim
  // above, so the number on the card can never disagree with the screen it
  // explains. The sensor knows exactly one thing, so the card shows exactly two
  // facts: the reading (with its age) and the auto-dim BAND it falls in. The
  // band is a NAME for the existing grounded luxMin/luxFull thresholds -- NOT a
  // third set of numbers that could drift away from the curve.
  //
  // Deliberately NOT shown: the resulting screen brightness. A live STOP alarm
  // holds the surface at FULL regardless of lux (US-484-b ch.4), so a
  // lux-derived brightness percent on this card would be a number that
  // disagrees with the actual screen exactly when it matters most.
  // -------------------------------------------------------------------------

  // Sub-10 lux keeps one decimal: near the dark end a whole-lux round merges
  // cabins that sit on opposite sides of the DARK boundary (luxMin 3.0).
  function fmtLux(lux) {
    return (lux < 10 ? lux.toFixed(1) : String(Math.round(lux))) + " lx";
  }

  function fmtAgeSec(ageSec) {
    return (ageSec < 10 ? ageSec.toFixed(1) : String(Math.round(ageSec))) + "s";
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

  // The auto-dim band this reading falls in, resolved against the SAME injected
  // config the curve uses (so an operator retuning pi.display.autoDim moves the
  // label and the dimming together).
  function luxBand(lux, cfg) {
    var c = resolveAutoDimConfig(cfg);
    if (lux <= c.luxMin) return "DARK";
    if (lux >= c.luxFull) return "DAYLIGHT";
    return "DIM";
  }

  function lightView(data, cfg, nowMs) {
    if (!isObj(data)) return null; // absent -> the shell renders the no-data view
    if (sourceUnavailable(data, "light")) {
      return { unavailable: true, reason: sourceReason(data, "light") };
    }
    var c = resolveAutoDimConfig(cfg);
    var age = readAgeSec(data, nowMs);
    var lux = freshLux(data, c.luxStaleSec, nowMs);
    if (lux === null) {
      // WHY there is no usable reading IS the value of the gray tile. The order
      // matters: "no reading arrived at all" is a different fault from "readings
      // stopped arriving", and the operator needs to know which.
      var reason =
        typeof data.lux !== "number" || !isFinite(data.lux)
          ? "no reading (saturated or unreadable)"
          : age === null
            ? "no read time"
            : "stale -- last read " + fmtAgeSec(age) + " ago";
      // Both fields gray INDIVIDUALLY (the card stays present -- always-present
      // is the contract) and the band grays WITH the reading because it is
      // derived from it: with no lux there is nothing to derive.
      return {
        unavailable: false,
        ambient: naTile("AMBIENT", reason),
        band: naTile("CONDITION", reason),
      };
    }
    return {
      unavailable: false,
      ambient: {
        label: "AMBIENT",
        value: fmtLux(lux),
        detail: "read " + fmtAgeSec(age) + " ago",
        level: "ok",
      },
      band: {
        label: "CONDITION",
        value: luxBand(lux, cfg),
        detail: "auto-dim band",
        // `neutral`, not `ok`: an ambient band is a fact about the cabin, not a
        // health verdict -- DARK is not a fault and DAYLIGHT is not a pass.
        level: "neutral",
      },
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

  // Freshness window, in seconds. RE-GROUNDED by US-508, and the re-grounding
  // is the point: the bridge now writes at pi.sensors.imu.stateHz = 10 Hz (Atlas
  // transport ruling), so 2.0 s is TWENTY missed writes, not the eight it was at
  // 4 Hz. It is deliberately NOT retightened in proportion. This feed now drives
  // the HOME slot, and a home card that flips to the idle face on a brief
  // scheduling stall is its own defect -- a flapping home slot. 2.0 s is still
  // far below the horizon at which a driver could mistake a stale g-vector for a
  // live one, and still MUCH tighter than the light card's 10 s (a 10 s old lux
  // is roughly true; a 10 s old g-vector is meaningless). Rex-derived; flagged
  // for Atlas/Spool against a real drive, same status as the bridge's tau.
  var IMU_STALE_SEC = 2.0;

  // Spool's advisory g threshold (Iris live-instrument spec, quoted verbatim in
  // the US-508 acceptance criteria). This is a DIFFERENT FACT from the ring's
  // full scale below, and conflating them is what the built card got wrong: it
  // only turned amber at the 1.0 g CLAMP, so a hard 0.8 g corner rendered
  // identically to a gentle one. Advisory, never an alarm -- alarms live on the
  // unified alert layer, not on this calm card.
  var G_AMBER_G = 0.6;

  // Outer ring of the g-meter, in g. A street-tired car tops out near 0.9 g
  // lateral, so a 1.0 g full scale frames real driving without compressing it
  // into the middle of the dial. Rex-derived DISPLAY scale (not a vehicle
  // limit) -- flagged for Spool, who owns vehicle dynamics.
  var G_FULL_SCALE = 1.0;

  // The g-trail window, in seconds (Iris live-instrument spec). US-508 moved the
  // live poll to 10 Hz, so this is now ~350 points rather than ~140 -- drawn as
  // ONE polyline, which is one `points` attribute write per paint however many
  // points it holds. As discrete nodes it would be 3500 elements/sec on a kiosk
  // Pi, which is exactly why it never was.
  var G_TRAIL_WINDOW_SEC = 35;

  // The bridge's per-field absence vocabulary, in words. This is a NAME map,
  // not a second set of facts: an unknown code passes straight through rather
  // than being swallowed into a generic word, because a reason the card has not
  // been taught is still information the operator can act on.
  var IMU_REASON_TEXT = {
    sensor_absent: "sensor not detected",
    no_mag_reading: "no compass reading",
    tilt_unresolved: "orientation unresolved",
    pitch_out_of_range: "pitch beyond range",
    no_source: "no source",
  };

  function imuReason(data, field) {
    var reasons = isObj(data) && isObj(data.reasons) ? data.reasons : {};
    var code = reasons[field];
    if (typeof code !== "string" || !code) return "unavailable";
    return Object.prototype.hasOwnProperty.call(IMU_REASON_TEXT, code)
      ? IMU_REASON_TEXT[code]
      : code;
  }

  // Place the g-dot in a unit box centred on the instrument. The SIGN CONTRACT
  // (specs/architecture.md 10.8.2) mapped to SCREEN coordinates, which is where
  // it is easy to invert an instrument in a way that still looks plausible:
  //   gLon + = accelerating -> the dot moves UP    -> y NEGATIVE (screen y runs down)
  //   gLon - = braking      -> the dot moves DOWN  -> y POSITIVE
  //   gLat + = RIGHT        -> the dot moves RIGHT -> x POSITIVE
  // Over-scale readings clamp to the ring along their OWN direction (never
  // per-axis, which would swing the dot to a corner and misreport which way the
  // car was loaded). The clamp cannot understate the event silently: the
  // numeric readout beside the meter always carries the true magnitude.
  function gDotPosition(gLat, gLon, fullScale) {
    var fs = typeof fullScale === "number" && isFinite(fullScale) && fullScale > 0
      ? fullScale
      : G_FULL_SCALE;
    if (typeof gLat !== "number" || !isFinite(gLat)) return null;
    if (typeof gLon !== "number" || !isFinite(gLon)) return null;
    var x = gLat / fs;
    var y = -gLon / fs;
    var r = Math.sqrt(x * x + y * y);
    if (r > 1) return { x: x / r, y: y / r, clamped: true };
    return { x: x, y: y, clamped: false };
  }

  // The g-trend sparkline window (Iris locked spec: a ~15-min moving trend) and
  // its decimation. At the 10 Hz live poll a 15-minute window is ~9000 raw
  // samples; one retained point per 5 s bucket is <=180, which is more than a
  // 480x320 sparkline can resolve anyway. Decimation is SAMPLING, not smoothing:
  // the retained value is a real reading, never an average that never happened.
  var GRADE_TREND_WINDOW_SEC = 900;
  var GRADE_TREND_BUCKET_MS = 5000;

  // The sparkline's FIXED vertical scale, in percent grade. Deliberately fixed
  // rather than autoscaled to the observed range: an autoscale stretches a flat
  // road's hundredth-of-a-percent wobble to full height and renders it as a
  // mountain range -- a fabricated terrain built out of real noise. A 10% grade
  // is already a very steep road (highway signs warn at 6%). Rex-derived DISPLAY
  // scale, flagged for Spool like G_FULL_SCALE.
  var GRADE_TREND_SCALE_PCT = 10;

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
  function compassTape(headingDeg, spanDeg) {
    var span = typeof spanDeg === "number" && isFinite(spanDeg) && spanDeg > 0
      ? spanDeg
      : COMPASS_TAPE_SPAN_DEG;
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
    var first = Math.ceil((heading - half) / COMPASS_TAPE_TICK_DEG) * COMPASS_TAPE_TICK_DEG;
    for (var deg = first; deg <= heading + half; deg += COMPASS_TAPE_TICK_DEG) {
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

  function gearView(gearData) {
    var reason = isObj(gearData) && typeof gearData.reason === "string" && gearData.reason
      ? gearData.reason
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

  // Spool's advisory band on the g magnitude. Neutral for an unreadable value:
  // an absent measurement must never paint a warning colour, which would be a
  // fabricated event manufactured out of a dead sensor.
  function gLevel(gMag) {
    if (typeof gMag !== "number" || !isFinite(gMag)) return "neutral";
    return Math.abs(gMag) >= G_AMBER_G ? "amber" : "neutral";
  }

  // Advance the ~15-min grade trend. Same shape as pushGTrail and for the same
  // reason: eviction runs even when there is NO new value, so a feed that stops
  // decays the sparkline to empty instead of freezing its last shape on screen.
  // Within a bucket the newest reading REPLACES the previous one (latest-wins),
  // so the retained point is always a real sample.
  function pushGradeTrend(trend, pct, nowMs, windowSec, bucketMs) {
    var w = (typeof windowSec === "number" && windowSec > 0
      ? windowSec
      : GRADE_TREND_WINDOW_SEC) * 1000;
    var bucket = typeof bucketMs === "number" && bucketMs > 0
      ? bucketMs
      : GRADE_TREND_BUCKET_MS;
    var src = Array.isArray(trend) ? trend : [];
    var out = [];
    for (var i = 0; i < src.length; i++) {
      if (isObj(src[i]) && nowMs - src[i].t <= w) out.push(src[i]);
    }
    if (typeof pct !== "number" || !isFinite(pct)) return out;
    var last = out.length ? out[out.length - 1] : null;
    if (last && Math.floor(last.t / bucket) === Math.floor(nowMs / bucket)) {
      out[out.length - 1] = { v: pct, t: nowMs };
    } else {
      out.push({ v: pct, t: nowMs });
    }
    return out;
  }

  // Sparkline geometry in a unit box: x 0..1 across the window, y -1..1 with
  // POSITIVE = climbing. Fixed scale + clamp (see GRADE_TREND_SCALE_PCT) -- a
  // clamped point still lands at the edge, so a very steep road reads as
  // pinned rather than vanishing off the card.
  function gradeTrendPoints(trend) {
    var src = Array.isArray(trend) ? trend : [];
    if (src.length === 0) return [];
    var first = src[0].t;
    var last = src[src.length - 1].t;
    var span = last - first;
    var out = [];
    for (var i = 0; i < src.length; i++) {
      var y = src[i].v / GRADE_TREND_SCALE_PCT;
      if (y > 1) y = 1;
      if (y < -1) y = -1;
      out.push({ x: span > 0 ? (src[i].t - first) / span : 1, y: y });
    }
    return out;
  }

  // Advance the client-side g-trail (Atlas Q-B: the animation is accumulated
  // from POLLED values, so eviction is this card's job). Pure: returns a new
  // array. Eviction runs even when there is NO new point, so a feed that stops
  // decays the trail to empty instead of freezing its last shape on screen.
  function pushGTrail(trail, point, nowMs, windowSec) {
    var w = (typeof windowSec === "number" && windowSec > 0
      ? windowSec
      : G_TRAIL_WINDOW_SEC) * 1000;
    var src = Array.isArray(trail) ? trail : [];
    var out = [];
    for (var i = 0; i < src.length; i++) {
      if (isObj(src[i]) && nowMs - src[i].t <= w) out.push(src[i]);
    }
    if (isObj(point) && typeof point.x === "number" && typeof point.y === "number") {
      out.push({ x: point.x, y: point.y, t: nowMs });
    }
    return out;
  }

  // ARCH-011 -- ONE decimal, not two. CIO 2026-08-29 from the driver's seat:
  // "I did see actual g force values, although 2 decimal places is not needed
  // and just noise."
  //
  // The measurement argument, stated honestly because it is narrower than it
  // first looks: Spool measured this accelerometer's SCALE error at +1.62%
  // (|g| = 9.9659 vs 9.80665, 3,224 samples at rest). A scale error is
  // PROPORTIONAL, so the second decimal is defensible below ~0.6 g and only
  // becomes unsupported above it:
  //
  //     0.10 g -> +/-0.0016 g   2nd decimal supported
  //     0.50 g -> +/-0.0081 g   2nd decimal supported
  //     1.00 g -> +/-0.0162 g   2nd decimal NOT supported
  //
  // So the digit is least trustworthy exactly when the reading matters most --
  // hard cornering and braking. Below that it is supported and meaningless: it
  // flickers continuously at cruise and carries nothing a driver can act on.
  //
  // One decimal is honest at every magnitude AND readable at a glance, which is
  // the only way this value is ever read.
  var _G_DECIMALS = 1;

  // US-645: the direction-label deadband, DERIVED from the decimals constant
  // above and never written out as a literal. Half of the last displayed place
  // is precisely the value at which `toFixed(_G_DECIMALS)` stops printing zero,
  // so the label's neutral band and the number's rounding band are the SAME
  // band by construction -- at one decimal, 0.05 g. See gAxisDetail.
  var G_LABEL_DEADBAND_G = 0.5 * Math.pow(10, -_G_DECIMALS);

  function fmtG(g) {
    return g.toFixed(_G_DECIMALS) + " g";
  }

  // Name the two components on the tile. This puts the SIGN CONTRACT on the
  // screen, where a mounted-backwards board becomes obvious to the operator
  // ("0.3 brake" while accelerating) instead of a silently mirrored dot.
  //
  // US-631 (A) -- THE LATERAL LABEL IS ABBREVIATED TO ONE CHARACTER, and that is
  // a defect fix, not a style preference. CIO 2026-08-31, from the driver's
  // seat: "they do bounce as the word right will wrap around cuz it's too long
  // to fit on the screen." Atlas photographed both states one minute apart --
  // the tile rendered FOUR lines with `right` and THREE with `left`.
  //
  // The mechanism, and why one character is the whole fix: `.tile-detail`
  // declares no `white-space: nowrap` and no `min-height`, and `.live-col` sets
  // `justify-content: center`. So a string ONE CHARACTER wider re-wraps, grows
  // the tile by a line box, and re-centres the entire column -- the bounce. The
  // lateral word was the ONLY varying-length token on this line: `left` is 4 and
  // `right` is 5, while `accel` and `brake` are both 5 and never moved anything.
  // At `L`/`R` the rendered length depends ONLY on the two magnitudes, so no
  // change of DIRECTION can change the line count.
  //
  // WHAT THIS DOES NOT FIX, stated so it is not mistaken for closed: the line
  // still WRAPS in a 108px column -- it is merely stable now. That is the width
  // reservation US-631 (B) asks for, it does not fit at any tier in the F-127
  // scale, and it is escalated to Iris as I-us631. Abbreviating further, or
  // collapsing L/R to a shared token, would buy width by DELETING the sign
  // contract above; the direction stays distinguishable.
  //
  // The words are spelled INLINE, not hoisted to constants, because the
  // US-631 width guard reads this function's body to learn what vocabulary the
  // tile actually ships. Moving them out of it leaves that tripwire green and
  // blind, which is the failure mode it exists to prevent.
  //
  // US-645 (F-138) -- THE DEADBAND. A bare sign test has no neutral, so at rest
  // the label reports the sign of the NOISE: Atlas measured ELEVEN longitudinal
  // sign flips in 17 seconds at idle, on noise of +/-0.015 g straddling zero.
  // The lateral label has the identical defect and nobody had noticed. Both
  // axes get the same mechanical fix -- one pattern applied twice, not two
  // behaviours.
  //
  // THE DEADBAND IS THE DISPLAY'S OWN ROUNDING THRESHOLD, DERIVED. At one
  // decimal anything under 0.05 g prints as `0.0`, so deriving the band from
  // _G_DECIMALS makes the word go neutral EXACTLY when the number reads zero:
  // the tile can never show a direction beside a 0.0, and a future change to
  // the decimals constant moves both together. A hardcoded 0.05 would be the
  // same number today and a silent lie the day that constant moves -- which is
  // this defect over again, one layer up.
  //
  // WHAT THE DEADBAND DOES NOT TOUCH, stated because it would be the tempting
  // over-reach: the NUMBER and the METER DOT are untouched. A deadband that
  // zeroed the reading would fabricate a stillness the accelerometer never
  // measured. Only the WORD goes neutral; 0.03 g still moves the dot.
  //
  // THE WIDTHS ARE THE CONSTRAINT, and they are stated here because US-631 (A)
  // bought the tile's constant height with exactly this property:
  //     lateral      `L` `R` `-`                     -- ALL 1 character
  //     longitudinal `accel` `brake` `coast` `still` -- ALL 5 characters
  // Every value a term can take is the same width as its siblings, so no state
  // change on either axis can change the rendered length, the line count, or
  // the tile's height. That is why the neutral is a dash and not `steady`, and
  // why the stopped state is `still` and not `stopped`: US-645's own acceptance
  // requires one character laterally and five longitudinally, and the six- and
  // seven-character spellings would have re-opened the bounce US-631 just shut
  // on the far axis. tests/ui/test_gforce_tile_width_budget.py sweeps it.
  //
  // `still` IS AN OBD CLAIM, NOT AN IMU ONE. gLon is ~0 at a 65 mph cruise just
  // as it is in a parking space, so "stopped" inferred from this instrument
  // alone would be a lie at speed. It is upgraded ONLY on a vehicle speed that
  // is TRULY zero, and an absent/unreadable speed degrades to `coast` -- true at
  // any speed, including zero. NO PRODUCER PUBLISHES SPEED TO THIS DASHBOARD
  // TODAY (I-us645), so `null` is what the browser passes and `still` is
  // currently unreachable on the panel. That is the honest state, not an
  // oversight: the branch is here so wiring a producer is zero-rework, exactly
  // the shape GEAR carried before US-630 landed its own.
  // NO NON-LABEL STRING LITERAL MAY APPEAR IN THIS BODY. The US-631 tripwire
  // reads every quoted word out of it and treats them all as tile vocabulary,
  // so a stray `typeof x === "number"` here lands `number` in the measured
  // width set and the guard starts sizing against a word that never renders.
  // The speed test is a STRICT equality for exactly that reason as well as its
  // own: `=== 0` alone refuses null, undefined, NaN and the string "0" (which
  // `==` would accept), so it needs no typeof to be safe.
  function gAxisDetail(gLat, gLon, speedKph) {
    var band = G_LABEL_DEADBAND_G;
    var stopped = speedKph === 0;
    var lat = Math.abs(gLat) < band ? "-" : (gLat >= 0 ? "R" : "L");
    var lon = Math.abs(gLon) < band
      ? (stopped ? "still" : "coast")
      : (gLon >= 0 ? "accel" : "brake");
    return (
      Math.abs(gLat).toFixed(_G_DECIMALS) + " " + lat +
      " · " +
      Math.abs(gLon).toFixed(_G_DECIMALS) + " " + lon
    );
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
      // MAGNETIC, not true -- no declination is in the contract, so a bearing a
      // few degrees off a map is expected, not a fault. Saying so on the tile
      // stops that from being read as a broken compass.
      detail: "magnetic",
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

  // `speedKph` is the OBD vehicle speed, and it is a PARAMETER rather than a
  // field read off `data` on purpose: it is not an IMU fact, and letting this
  // function reach into the states/imu payload for it would re-merge two
  // producers into one contract -- the same SSOT violation Atlas named when he
  // kept gear out of states/imu. Absent (the shipped case today) it is null and
  // the tile simply never claims `still`.
  function imuGTile(data, speedKph) {
    var dot = gDotPosition(data.gLat, data.gLon, G_FULL_SCALE);
    var mag = data.gMag;
    if (dot === null || typeof mag !== "number" || !isFinite(mag)) {
      var na = naTile("G-FORCE", imuReason(data, "gLat"));
      // NO DOT. An origin dot would render as a real, measured "no g" -- the
      // zeroed instrument AC-3 forbids. Absence must look like absence.
      na.dot = null;
      na.available = false;
      return na;
    }
    return {
      label: "G-FORCE",
      value: fmtG(mag),
      detail: gAxisDetail(data.gLat, data.gLon, speedKph),
      // US-508: amber from 0.6 g (Spool), which the built card did not do -- it
      // only coloured at the 1.0 g CLAMP, so a hard 0.8 g corner looked exactly
      // like a gentle one. The colour is a NUDGE beside the true magnitude,
      // never a replacement for it and never a takeover.
      level: gLevel(mag),
      dot: dot,
      available: true,
    };
  }

  // The whole-card view. Returns:
  //   null                     -- no state file; the SHELL owns the absent
  //                               message, so one place decides absence
  //   {idle:true, reason}      -- present but not renderable as a live
  //                               instrument (unwired / undated / stale)
  //   {idle:false, ...}        -- the live instrument
  function imuView(data, nowMs, speedKph) {
    if (!isObj(data)) return null;
    // The bridge's EXPLICIT availability claim. An unwired sensor writes
    // available:false (and that write bypasses the bridge's own rate limit, so
    // an unplug can never leave a live reading sitting here looking current).
    if (data.available !== true) {
      // The blanket reason the bridge stamps on every derived field.
      return { idle: true, reason: imuReason(data, "gLat") };
    }
    var age = readAgeSec(data, nowMs);
    if (age === null) return { idle: true, reason: "no read time" };
    if (age > IMU_STALE_SEC) {
      return { idle: true, reason: "stale -- last read " + fmtAgeSec(age) + " ago" };
    }
    return {
      idle: false,
      ageSec: age,
      fullScale: G_FULL_SCALE,
      g: imuGTile(data, speedKph),
      heading: imuHeadingTile(data),
      grade: imuGradeTile(data),
      // ALWAYS typed-NA (AC-2). The ICM-20948 has no barometer and a zeroed
      // altitude renders as sea level -- a confident lie. It never blocks the
      // card; a future BMP280/GPS fills it at the BRIDGE, not here.
      altitude: naTile("ALTITUDE", imuReason(data, "altitude")),
    };
  }

  // US-508: the whole LIVE face. imuView owns the states/imu contract; this adds
  // the two things that are NOT IMU facts -- the compass tape geometry (derived
  // from the heading the bridge already resolved, not from a second fusion) and
  // the gear glyph, whose producer is separate by Atlas's ruling. Returns the
  // same three shapes imuView does, so the caller has ONE thing to branch on.
  function liveCardView(imuData, gearData, nowMs, speedKph) {
    var view = imuView(imuData, nowMs, speedKph);
    if (view === null || view.idle) return view;
    view.tape = compassTape(
      view.heading.available ? view.heading.deg : null,
      COMPASS_TAPE_SPAN_DEG
    );
    // Gear is read from its OWN producer's payload, never from imuData -- even
    // if a states/imu file were to sprout a gear field, honouring it here would
    // quietly re-merge two producers into one fact (the SSOT violation Atlas
    // named when he kept gear out of the contract).
    view.gear = gearView(gearData);
    return view;
  }

  // US-508 HOME-SLOT SWAP: one slot, two faces. THIS FUNCTION IS THE ONLY PLACE
  // that decides which -- a second arbiter would put two rules in charge of one
  // fact, which is exactly why US-497 declined to build the swap at all.
  //
  // US-541 IMU-ALWAYS-ON (Atlas): the decision now reads THE MOTION FEED ONLY.
  // US-508 let `parked` win outright, which hid the one instrument that is
  // Pi-local and always-live at precisely the moment its readings are both true
  // and worth looking at -- parked, the IMU is CORRECT (real heading, a real
  // 0.0 g), not unavailable. The vehicle state is deliberately NOT a parameter:
  // a function that cannot see system-status cannot re-couple the home face to
  // it, so a future re-coupling has to widen the signature first, which is a
  // visible act rather than a condition slipped into the body. `carouselIdle`
  // keeps its OTHER consumers (the auto-rotate pause, the home nav edge).
  //
  // The idle face survives as the honest fallback and NOTHING ELSE: no file,
  // unwired sensor, undated payload or stale reading (AC-3 -- never a frozen
  // motion display). It therefore always carries a reason; there is no longer a
  // disposition where the fallback fires with nothing to say.
  function homeFace(imuData, nowMs) {
    var view = imuView(imuData, nowMs);
    if (view === null) {
      return { face: "idle", reason: "no motion feed" };
    }
    if (view.idle) {
      return { face: "idle", reason: view.reason };
    }
    return { face: "live", reason: null };
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
    makeSmoothWindow: makeSmoothWindow,
    circularMeanDeg: circularMeanDeg,
    linearMean: linearMean,
    smoothedImuView: smoothedImuView,
    reportFetchAbort: reportFetchAbort,
    shouldLog: shouldLog,
    uiLog: uiLog,
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
    luxBand: luxBand,
    lightView: lightView,
    gDotPosition: gDotPosition,
    // US-645: exported so the deadband can be swept densely across its own
    // boundary. gDotPosition and gLevel are already here for the same reason --
    // the per-axis rules on this tile are the parts worth measuring at 0.001 g,
    // and doing it through a whole card view would be 400 renders of furniture.
    gAxisDetail: gAxisDetail,
    headingCardinal: headingCardinal,
    pushGTrail: pushGTrail,
    imuView: imuView,
    compassTape: compassTape,
    gearView: gearView,
    gLevel: gLevel,
    pushGradeTrend: pushGradeTrend,
    gradeTrendPoints: gradeTrendPoints,
    liveCardView: liveCardView,
    homeFace: homeFace,
    sourceUnavailable: sourceUnavailable,
    sourceReason: sourceReason,
    naTile: naTile,
    obdLinkTile: obdLinkTile,
    syncTile: syncTile,
    powerTile: powerTile,
    driveTile: driveTile,
    btGlyphState: btGlyphState,
    syncGlyphState: syncGlyphState,
    powerGlyphState: powerGlyphState,
    systemSummary: systemSummary,
    sysRowFreshness: sysRowFreshness,
    systemIssueRows: systemIssueRows,
    systemDiagnostics: systemDiagnostics,
    systemDrill: systemDrill,
    systemStatusView: systemStatusView,
    healthCheckLine: healthCheckLine,
    vcellTile: vcellTile,
    socTile: socTile,
    ladderView: ladderView,
    batteryHealthView: batteryHealthView,
    fmtLtftPct: fmtLtftPct,
    ltftTrendView: ltftTrendView,
    sourceCardSpecs: sourceCardSpecs,
    sourceCardSpec: sourceCardSpec,
    sourceCardView: sourceCardView,
    serviceMenuItems: serviceMenuItems,
    settingsSpecs: settingsSpecs,
    settingsApplyStates: settingsApplyStates,
    settingsReloadNeeded: settingsReloadNeeded,
    settingsModeChoices: settingsModeChoices,
    settingsChoices: settingsChoices,
    settingsRowView: settingsRowView,
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
    alertableCodes: alertableCodes,
    takeoverView: takeoverView,
    takeoverShouldShow: takeoverShouldShow,
    ribbonView: ribbonView,
    dtcListSorted: dtcListSorted,
    brightnessCurve: brightnessCurve,
    brightnessLevel: brightnessLevel,
    brightnessAlarmActive: brightnessAlarmActive,
    resolveAutoDimConfig: resolveAutoDimConfig,
    fmtClock: fmtClock,
    fmtStamp: fmtStamp,
    carouselIdle: carouselIdle,
    agoText: agoText,
    idleLastDriveFact: idleLastDriveFact,
    idleBatteryFact: idleBatteryFact,
    dtcNotReadTile: dtcNotReadTile,
    idleCardView: idleCardView,
    dtcRow: dtcRow,
    alertsCardView: alertsCardView,
    trustBadge: trustBadge,
    fixArea: fixArea,
    fixSectionLabel: fixSectionLabel,
    freezeFrameView: freezeFrameView,
    codeDetailView: codeDetailView,
    clearGateReason: clearGateReason,
    clearButtonView: clearButtonView,
    confirmClearText: confirmClearText,
    postClearMessage: postClearMessage,
    POLL_MS: POLL_MS,
    IMU_POLL_MS: IMU_POLL_MS,
    G_AMBER_G: G_AMBER_G,
    GRADE_TREND_WINDOW_SEC: GRADE_TREND_WINDOW_SEC,
    GRADE_TREND_BUCKET_MS: GRADE_TREND_BUCKET_MS,
    COMPASS_TAPE_SPAN_DEG: COMPASS_TAPE_SPAN_DEG,
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

    // US-483-b: the auto-dim curve config injected same-origin at serve time
    // (states_http_server substitutes the placeholder from config.json). An
    // object -> use it; anything else (unsubstituted preview / null) -> the
    // built-in grounded defaults kick in inside resolveAutoDimConfig.
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
    // US-489: `withDot` prepends the per-tile status dot. It is OPT-IN because
    // appendTile is shared with the idle, battery and LTFT cards -- defaulting
    // it on would restyle three shipped cards from a story scoped to one.
    function appendTile(parent, tile, withDot) {
      var el = document.createElement("div");
      el.className = "tile";
      el.setAttribute("data-level", tile.level);
      var label = document.createElement("span");
      label.className = "tile-label";
      label.textContent = tile.label;
      if (withDot) {
        // The dot takes no level of its own -- it inherits the tile's
        // [data-level], so it can never disagree with the value beside it.
        var head = document.createElement("div");
        head.className = "tile-head";
        var dot = document.createElement("span");
        dot.className = "tile-dot";
        head.appendChild(dot);
        head.appendChild(label);
        el.appendChild(head);
      }
      var value = document.createElement("span");
      value.className = "tile-value";
      value.textContent = tile.value;
      var detail = document.createElement("span");
      detail.className = "tile-detail";
      detail.textContent = tile.detail;
      if (!withDot) el.appendChild(label);
      el.appendChild(value);
      el.appendChild(detail);
      parent.appendChild(el);
    }

    function renderSystemStatusCard(card, view, glyphEls) {
      // US-509: the drill-down is fed by the SAME poll that paints the card, and
      // an OPEN overlay is repainted with it. A drill-down left frozen on the
      // snapshot that opened it would keep printing "seen 42s ago" while the
      // age climbed -- the frozen-instrument fabrication this project names for
      // the g-dot and the rotate bar, in a third geometry.
      lastSysView = view;
      if (sysDetailOpen()) renderSysDetail(view);
      var body = card.querySelector(".card-body");
      if (body) {
        body.textContent = "";
        // US-489 P-1: the one-glance headline, then the 2x2 grid. Built with
        // textContent (no innerHTML) so emitter values render verbatim.
        var summary = document.createElement("div");
        summary.className = "sys-summary";
        summary.setAttribute("data-level", view.summary.level);
        var summaryText = document.createElement("span");
        summaryText.className = "sys-summary-text";
        summaryText.textContent = view.summary.text;
        summary.appendChild(summaryText);
        if (view.summary.detail) {
          var summaryDetail = document.createElement("span");
          summaryDetail.className = "sys-summary-detail";
          summaryDetail.textContent = view.summary.detail;
          summary.appendChild(summaryDetail);
        }
        // US-509: the headline becomes a control ONLY when there is something
        // behind it. An always-tappable summary that opens an empty list on a
        // healthy system is a misleading affordance -- it promises detail the
        // card does not have. The chevron is part of the same gate, so the
        // affordance and the behaviour can never disagree.
        if (view.drill && view.drill.tappable) {
          summary.classList.add("sys-summary-tappable");
          summary.setAttribute("role", "button");
          summary.setAttribute("tabindex", "0");
          var chevron = document.createElement("span");
          chevron.className = "sys-summary-chevron";
          chevron.textContent = "›";
          summary.appendChild(chevron);
          summary.onclick = function () { openSysDetail(); };
        }
        body.appendChild(summary);
        var grid = document.createElement("div");
        grid.className = "sys-grid";
        appendTile(grid, view.tiles.obdLink, true);
        appendTile(grid, view.tiles.sync, true);
        appendTile(grid, view.tiles.power, true);
        appendTile(grid, view.tiles.drive, true);
        body.appendChild(grid);
      }
      if (glyphEls.bt) glyphEls.bt.setAttribute("data-state", view.glyphs.bt);
      if (glyphEls.sync) glyphEls.sync.setAttribute("data-state", view.glyphs.sync);
      if (glyphEls.power) glyphEls.power.setAttribute("data-state", view.glyphs.power);
      // ARCH-007: render the emitter's verdict. The display applies NO
      // threshold of its own (ruling s2.1) -- two rules for one fact disagree
      // the first time either moves.
      if (glyphEls.wifi) glyphEls.wifi.setAttribute("data-state", view.glyphs.wifi);
    }

    // --- US-509 System-Status drill-down overlay (browser only) -------------

    // The most-recent card view, so a tap on the summary line has rows to show
    // without a second read of the state file. It is set by the renderer above,
    // which means the overlay is fed by exactly the same poll that painted the
    // card -- the two can never drift apart.
    var lastSysView = null;

    // Elements are looked up LAZILY rather than captured at init: this renderer
    // lives in the shared render scope (not the browser-only block below), and a
    // captured-at-load reference would be null under the node/file:// paths that
    // exercise this file without the full DOM.
    function renderSysDetail(view) {
      var bodyEl = document.getElementById("sys-detail-body");
      if (!bodyEl) return;
      bodyEl.textContent = "";
      var head = document.getElementById("sys-detail-head");
      // The head repeats the LINE THE OPERATOR TAPPED verbatim, rather than
      // recounting the rows into a second headline. A drill-down whose title
      // disagrees with the summary that opened it is its own small lie -- and
      // the counts genuinely differ (the summary counts ISSUES; the list also
      // carries known-unknowns).
      if (head) head.textContent = view && view.summary ? view.summary.text : "";
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
        // The row's level came straight off the tile, so the chip colour here
        // and the grid cell behind the overlay are incapable of disagreeing.
        el.setAttribute("data-level", row.level);
        var rowHead = document.createElement("div");
        rowHead.className = "sys-issue-head";
        var label = document.createElement("span");
        label.className = "sys-issue-label";
        label.textContent = row.label;
        var chip = document.createElement("span");
        chip.className = "sys-issue-chip";
        chip.textContent = row.value;
        rowHead.appendChild(label);
        rowHead.appendChild(chip);
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

    function openSysDetail() {
      var el = document.getElementById("sys-detail");
      // Guarded on `tappable` as well as the handler that called it, so a stale
      // listener left on a recovered card cannot open an empty overlay.
      if (!el || !lastSysView || !lastSysView.drill.tappable) return;
      renderSysDetail(lastSysView);
      el.hidden = false;
    }

    function closeSysDetail() {
      var el = document.getElementById("sys-detail");
      if (el) el.hidden = true;
    }

    // Honest-instrument reset: a missing/malformed system-status file returns the
    // glyphs to neutral so a prior good read can't linger green (no stale-green).
    function resetSystemGlyphs(glyphEls) {
      if (glyphEls.bt) glyphEls.bt.setAttribute("data-state", "neutral");
      if (glyphEls.sync) glyphEls.sync.setAttribute("data-state", "neutral");
      if (glyphEls.power) glyphEls.power.setAttribute("data-state", "neutral");
      if (glyphEls.wifi) glyphEls.wifi.setAttribute("data-state", "neutral");
    }

    // --- US-542 motion-fault fallback DOM render (browser only) -------------

    // US-542: `fmtDate` and its month/day tables are DELETED, not left for a
    // future caller. The parked header was their only consumer, and the date is
    // the one piece of that header this story does NOT relocate: the top bar is
    // 480px wide and already carries three glyphs, a version chip and the ⋮ at
    // the US-540-a scale, where a clock fits and a clock-plus-date does not. A
    // deliberate, named loss -- flagged for Iris in the story notes rather than
    // absorbed silently. (`fmtClock` stays: it moved to the pure section in
    // US-503 and now feeds the top bar, so there is still exactly ONE clock
    // formatter and it is still the one a test can reach.)

    // Render the fallback card from the assembled view. Built with textContent
    // (no innerHTML) so emitter values render verbatim, never as markup. The
    // fact tiles reuse the shared `.tile[data-level]` styling, so green is bound
    // to the SSOT token exactly once (US-484) -- this card holds no hex literal.
    // US-508: takes a BODY, not a card -- the same move US-507 made for the
    // three Health renderers, and for the same reason. Reaching for its own
    // `.card-body` assumed this renderer owned the whole card, which is the
    // assumption the two-faced home slot overturns.
    // US-542: the `now` parameter is GONE with the clock it fed. Same guard as
    // the `dtcData` drop above -- a renderer with no clock in its signature
    // cannot grow a second one behind the top bar's back.
    function renderIdleBody(body, view) {
      if (!body || !view) return;
      body.textContent = "";

      // Header: the wordmark. US-542 moved the CLOCK to the top bar, where it
      // is readable on every card rather than only on the one screen a parked
      // operator happened to be looking at -- and where it survives this face
      // being reachable only when the motion feed dies.
      var header = document.createElement("div");
      header.className = "idle-header";
      var wm = document.createElement("span");
      wm.className = "idle-wordmark";
      wm.textContent = view.wordmark;
      header.appendChild(wm);
      body.appendChild(header);

      // The NO MOTION DATA hero (neutral grey, never green) + the reason.
      var hero = document.createElement("div");
      hero.className = "idle-hero";
      hero.setAttribute("data-level", view.hero.level);
      var heroTitle = document.createElement("div");
      heroTitle.className = "idle-hero-title";
      heroTitle.textContent = view.hero.title;
      var heroSub = document.createElement("div");
      heroSub.className = "idle-hero-sub";
      heroSub.textContent = view.hero.substate;
      hero.appendChild(heroTitle);
      hero.appendChild(heroSub);
      body.appendChild(hero);

      // 2-fact summary strip: last-drive / battery-with-age. The faults tile
      // left with US-542 -- it is on the Alerts card, one swipe away, and the
      // ribbon still carries a REAL fault over this screen like any other.
      var strip = document.createElement("div");
      strip.className = "idle-facts";
      appendTile(strip, view.facts.lastDrive);
      appendTile(strip, view.facts.battery);
      body.appendChild(strip);

      // Footer: read from the VIEW rather than a literal here. Copy no test can
      // reach is copy that drifts from the spec -- which is precisely what
      // US-510 had to come back and restore on this surface.
      var footer = document.createElement("div");
      footer.className = "idle-footer";
      footer.textContent = view.footer;
      body.appendChild(footer);
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

    // --- US-496 Light card DOM render (browser only) ------------------------

    // Two tiles through the SHARED `.tile` component, which is already bound to
    // src/pi/ui/tokens.css -- the Light card introduces no palette of its own
    // (AC-4: a bespoke local colour is exactly the drift the SSOT prevents).
    function renderLightBody(body, view) {
      if (!body || !view) return;
      if (view.unavailable) {
        renderNaBody(body, "AMBIENT", view.reason);
        return;
      }
      body.textContent = "";
      appendTile(body, view.ambient);
      appendTile(body, view.band);
    }

    // --- US-497 IMU live-instrument DOM render (browser only) ---------------

    // The g-meter is ONE inline SVG, rebuilt only when its shape changes and
    // otherwise updated by ATTRIBUTE. At the US-508 10 Hz live poll a 350-point
    // trail rebuilt as discrete nodes would churn thousands of elements/sec on a
    // kiosk Pi; as a single <polyline> it is one `points` write per paint.
    var SVG_NS = "http://www.w3.org/2000/svg";
    var G_METER_R = 46;   // outer ring radius in the meter's own viewBox units
    var G_METER_C = 50;   // viewBox centre (the box is 100x100)

    function svgEl(name, attrs) {
      var el = document.createElementNS(SVG_NS, name);
      for (var k in attrs) {
        if (Object.prototype.hasOwnProperty.call(attrs, k)) {
          el.setAttribute(k, String(attrs[k]));
        }
      }
      return el;
    }

    // Build the static furniture once: the outer ring, the half-scale ring and
    // the cross-hairs. The rings are LABELLED by the full-scale constant, so a
    // change to G_FULL_SCALE cannot leave the dial claiming the old scale.
    function buildGMeter() {
      var svg = svgEl("svg", {
        class: "imu-meter",
        viewBox: "0 0 100 100",
        "aria-hidden": "true",
      });
      svg.appendChild(svgEl("circle", {
        class: "imu-ring", cx: G_METER_C, cy: G_METER_C, r: G_METER_R,
      }));
      svg.appendChild(svgEl("circle", {
        class: "imu-ring imu-ring-half",
        cx: G_METER_C, cy: G_METER_C, r: G_METER_R / 2,
      }));
      svg.appendChild(svgEl("line", {
        class: "imu-axis",
        x1: G_METER_C - G_METER_R, y1: G_METER_C,
        x2: G_METER_C + G_METER_R, y2: G_METER_C,
      }));
      svg.appendChild(svgEl("line", {
        class: "imu-axis",
        x1: G_METER_C, y1: G_METER_C - G_METER_R,
        x2: G_METER_C, y2: G_METER_C + G_METER_R,
      }));
      svg.appendChild(svgEl("polyline", { class: "imu-trail", points: "" }));
      svg.appendChild(svgEl("circle", { class: "imu-dot", cx: G_METER_C, cy: G_METER_C, r: 4 }));
      return svg;
    }

    function trailPoints(trail) {
      var parts = [];
      for (var i = 0; i < trail.length; i++) {
        parts.push(
          (G_METER_C + trail[i].x * G_METER_R).toFixed(1) + "," +
          (G_METER_C + trail[i].y * G_METER_R).toFixed(1)
        );
      }
      return parts.join(" ");
    }

    // US-508: the scrolling compass TAPE (CIO-locked; it replaces the built
    // rotating needle outright rather than sitting beside it -- two heading
    // instruments on one card can disagree, and the operator has no way to know
    // which one to believe).
    //
    // The CARET is static furniture: it marks the vehicle's own bearing and must
    // never move, because the whole readability of a tape comes from one fixed
    // reference with the world sliding past it. Only the tick group is rebuilt,
    // and at 7 ticks that is nothing next to the 140-point trail beside it.
    var TAPE_W = 100;          // tape viewBox width
    var TAPE_HALF = 48;        // usable half-width (leaves room for edge labels)

    function buildTape() {
      var svg = svgEl("svg", {
        class: "imu-tape", viewBox: "0 0 100 26", "aria-hidden": "true",
      });
      svg.appendChild(svgEl("g", { class: "imu-tape-ticks" }));
      svg.appendChild(svgEl("polygon", {
        class: "imu-caret", points: "50,0 46,6 54,6",
      }));
      return svg;
    }

    function renderTape(svg, tape) {
      var group = svg.querySelector(".imu-tape-ticks");
      if (!group) return;
      while (group.firstChild) group.removeChild(group.firstChild);
      // No bearing -> no ticks. An empty strip reads as an absent instrument;
      // ticks left frozen under the caret read as a confident heading, which is
      // the same fabrication the frozen needle made in a different shape.
      if (!tape || !tape.available) return;
      for (var i = 0; i < tape.ticks.length; i++) {
        var t = tape.ticks[i];
        var x = TAPE_W / 2 + t.offset * TAPE_HALF;
        group.appendChild(svgEl("line", {
          class: t.major ? "imu-tick imu-tick-major" : "imu-tick",
          x1: x.toFixed(1), y1: t.major ? 8 : 10,
          x2: x.toFixed(1), y2: 16,
        }));
        if (t.label) {
          var text = svgEl("text", {
            class: "imu-tape-label", x: x.toFixed(1), y: 25,
            "text-anchor": "middle",
          });
          text.textContent = t.label;
          group.appendChild(text);
        }
      }
    }

    // The ~15-min grade trend, as ONE polyline. y is flipped because screen y
    // runs down and the view's y is POSITIVE = climbing -- the same inversion
    // the g-dot makes, and the same place a sign error would hide.
    function trendPoints(points) {
      var parts = [];
      for (var i = 0; i < points.length; i++) {
        parts.push(
          (points[i].x * 100).toFixed(1) + "," +
          (10 - points[i].y * 9).toFixed(1)
        );
      }
      return parts.join(" ");
    }

    function buildTrend() {
      var svg = svgEl("svg", {
        class: "imu-trend", viewBox: "0 0 100 20", "aria-hidden": "true",
      });
      svg.appendChild(svgEl("line", {
        class: "imu-trend-zero", x1: 0, y1: 10, x2: 100, y2: 10,
      }));
      svg.appendChild(svgEl("polyline", { class: "imu-trend-line", points: "" }));
      return svg;
    }

    // US-508: the LIVE face, built to the CIO-locked layout -- compass tape and
    // heading down the left, the GEAR glyph in the middle, the g-meter on the
    // right, grade % + a prominent altitude + the ~15-min trend beneath.
    // Rebuilt only when the furniture is absent; every tick after that is an
    // attribute write, so a 10 Hz poll does not churn the DOM.
    function renderLiveBody(body, view, trail, trend) {
      if (!body || !view) return;
      var meter = body.querySelector(".imu-meter");
      if (!meter) {
        body.textContent = "";
        var wrap = document.createElement("div");
        wrap.className = "live-body";

        var left = document.createElement("div");
        left.className = "live-col live-heading";
        left.appendChild(buildTape());
        var headTile = document.createElement("div");
        headTile.className = "imu-tiles live-heading-tile";
        left.appendChild(headTile);
        var gradeBox = document.createElement("div");
        gradeBox.className = "imu-grade-box";
        gradeBox.appendChild(buildTrend());
        var gradeTiles = document.createElement("div");
        gradeTiles.className = "imu-tiles live-grade-tiles";
        gradeBox.appendChild(gradeTiles);
        left.appendChild(gradeBox);
        wrap.appendChild(left);

        var gearBox = document.createElement("div");
        gearBox.className = "live-col live-gear";
        var gearLabel = document.createElement("span");
        gearLabel.className = "imu-gear-label";
        gearLabel.textContent = "GEAR";
        var gearGlyph = document.createElement("span");
        gearGlyph.className = "imu-gear";
        var gearDetail = document.createElement("span");
        gearDetail.className = "imu-gear-detail";
        gearBox.appendChild(gearLabel);
        gearBox.appendChild(gearGlyph);
        gearBox.appendChild(gearDetail);
        wrap.appendChild(gearBox);

        var right = document.createElement("div");
        right.className = "live-col live-g";
        right.appendChild(buildGMeter());
        var gTiles = document.createElement("div");
        gTiles.className = "imu-tiles live-g-tiles";
        right.appendChild(gTiles);
        wrap.appendChild(right);

        body.appendChild(wrap);
        meter = body.querySelector(".imu-meter");
      }

      var dot = meter.querySelector(".imu-dot");
      var line = meter.querySelector(".imu-trail");
      // An unresolved g hides the dot + trail rather than parking them at the
      // origin, which would read as a measured "stationary".
      if (view.g.available && view.g.dot) {
        dot.removeAttribute("hidden");
        dot.setAttribute("cx", String(G_METER_C + view.g.dot.x * G_METER_R));
        dot.setAttribute("cy", String(G_METER_C + view.g.dot.y * G_METER_R));
        dot.setAttribute("data-clamped", view.g.dot.clamped ? "true" : "false");
        // US-508: Spool's 0.6 g advisory band, carried as the level the tile
        // already uses so the dot and its number can never disagree about
        // whether this was a hard corner.
        dot.setAttribute("data-level", view.g.level);
        line.setAttribute("points", trailPoints(trail || []));
        line.setAttribute("data-level", view.g.level);
      } else {
        dot.setAttribute("hidden", "hidden");
        line.setAttribute("points", "");
      }

      renderTape(body.querySelector(".imu-tape"), view.tape);

      var trendLine = body.querySelector(".imu-trend-line");
      if (trendLine) trendLine.setAttribute("points", trendPoints(gradeTrendPoints(trend || [])));

      var gearGlyphEl = body.querySelector(".imu-gear");
      var gearDetailEl = body.querySelector(".imu-gear-detail");
      if (gearGlyphEl) {
        gearGlyphEl.textContent = view.gear.value;
        gearGlyphEl.setAttribute("data-level", view.gear.level);
      }
      // The reason rides beside the glyph so "--" is never a bare shrug: the
      // operator can tell "no producer wired" from "the producer is refusing to
      // guess right now", which are different facts about the same dashes.
      if (gearDetailEl) gearDetailEl.textContent = view.gear.detail || "";

      var headBox = body.querySelector(".live-heading-tile");
      if (headBox) {
        headBox.textContent = "";
        appendTile(headBox, view.heading);
      }
      var gradeTileBox = body.querySelector(".live-grade-tiles");
      if (gradeTileBox) {
        gradeTileBox.textContent = "";
        appendTile(gradeTileBox, view.grade);
        // Altitude is PROMINENT per the locked spec and ALWAYS typed-NA today
        // (no barometer, no GPS -- Atlas's correction to the original design).
        // It sits in the grade box as a first-class readout rather than a
        // trailing tile, so when a source lands it is already in its place.
        appendTile(gradeTileBox, view.altitude);
      }
      var gTileBox = body.querySelector(".live-g-tiles");
      if (gTileBox) {
        gTileBox.textContent = "";
        appendTile(gTileBox, view.g);
      }
    }

    // US-508 HOME SLOT: paint whichever face `homeFace` chose. The two faces
    // REPLACE each other wholesale on a change -- leaving a stale <svg> under an
    // idle message is precisely the frozen instrument AC-3 forbids, and it is
    // the exact failure the swap makes possible for the first time.
    function renderHomeCard(card, face, liveView, idleView, trail, trend) {
      if (!card || !face) return;
      var body = card.querySelector(".card-body");
      if (!body) return;
      if (card.getAttribute("data-face") !== face.face) {
        card.setAttribute("data-face", face.face);
        body.textContent = "";
      }
      if (face.face === "live") {
        if (liveView && !liveView.idle) renderLiveBody(body, liveView, trail, trend);
        return;
      }
      if (idleView) renderIdleBody(body, idleView);
    }

    // --- US-420 LTFT Trend DOM render (browser only) ------------------------

    // Render the multi-drive bar row: one bar per drive, coloured by its own
    // drift level ([data-level] -> CSS), so a drive beyond +/-10% is visibly
    // not-green. Built with textContent (no innerHTML) -- verbatim, never markup.
    function appendLtftBars(parent, points) {
      var bars = document.createElement("div");
      bars.className = "ltft-bars";
      for (var i = 0; i < points.length; i++) {
        var p = points[i];
        var bar = document.createElement("div");
        bar.className = "ltft-bar";
        bar.setAttribute("data-level", p.level);
        var value = document.createElement("span");
        value.className = "ltft-bar-value";
        value.textContent = p.value;
        var drive = document.createElement("span");
        drive.className = "ltft-bar-drive";
        drive.textContent = p.driveId == null ? "—" : "#" + p.driveId;
        bar.appendChild(value);
        bar.appendChild(drive);
        bars.appendChild(bar);
      }
      parent.appendChild(bars);
    }

    function renderLtftTrendBody(body, view) {
      if (!body || !view) return;
      body.textContent = "";
      // The headline tile carries the verdict level (insufficient -> not green).
      appendTile(body, view.headline);
      // The per-drive bars render whenever any real point exists (0-1 points is
      // still shown honestly under an insufficient headline, never fabricated).
      if (view.points.length > 0) appendLtftBars(body, view.points);
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
      var body = card.querySelector(".card-body");
      if (!body) return;
      card.setAttribute("data-gated", view.gated ? "true" : "false");
      // The typed NA is the card's whole body here, so the shipped
      // `.unavailable` italic-gray must not also apply -- the tile carries its
      // own honest styling and the two together read as a doubly-dead card.
      card.classList.toggle("unavailable", false);
      if (view.gated || view.unavailable) {
        renderNaBody(body, view.na.label, view.na.reason);
        return;
      }
      if (view.key === "battery-health") renderBatteryHealthBody(body, view.view);
      else if (view.key === "light") renderLightBody(body, view.view);
      else if (view.key === "ltft-trend") renderLtftTrendBody(body, view.view);
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

    var setup = function () {
      // Scale first, then wire re-scale on any viewport change (rotation /
      // resolution change / the panel reporting late at boot).
      applyStageScale();
      window.addEventListener("resize", applyStageScale);

      var track = document.getElementById("track");
      var dotsNav = document.getElementById("dots");
      var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));
      var count = cards.length;
      var current = 0;
      var glyphEls = {
        bt: document.getElementById("glyph-bt"),
        sync: document.getElementById("glyph-sync"),
        power: document.getElementById("glyph-power"),
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

            render(settingsSource ? settingsSource[spec.key] : null, "");
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
      var carousel = document.getElementById("carousel");
      if (carousel && ring) {
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
        carousel.addEventListener("pointerdown", function (e) {
          pressStart = Date.now();
          pressX = e.clientX;
          pressY = e.clientY;
          timer = setInterval(function () {
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
              openMenu();
            }
          }, 50);
        });
        carousel.addEventListener("pointermove", function (e) {
          if (pressStart === null) return;
          if (exceedsMoveCancel(e.clientX - pressX, e.clientY - pressY)) clearPress();
        });
        carousel.addEventListener("pointerup", clearPress);
        carousel.addEventListener("pointercancel", clearPress);
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

      // --- US-405 DTC takeover + ribbon surfaces (browser only) --------------
      var ribbonEl = document.getElementById("dtc-ribbon");
      var takeoverEl = document.getElementById("dtc-takeover");
      var tvIcon = document.getElementById("takeover-icon");
      var tvChip = document.getElementById("takeover-chip");
      var tvCode = document.getElementById("takeover-code");
      var tvDesc = document.getElementById("takeover-desc");
      var tvDirective = document.getElementById("takeover-directive");
      var tvMore = document.getElementById("takeover-more");
      var tvDismiss = document.getElementById("takeover-dismiss");
      var tvDetail = document.getElementById("takeover-detail");
      // The last-acknowledged `newSinceTs` (edge-trigger). Acknowledge/Dismiss
      // records it so the same code never re-takes-over; a newer code (a
      // different stamp) re-fires (escalation, D-3).
      var dtcLastAckedTs = null;

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
      // The most-recent `dtc` state, so a ribbon/takeover "View detail" tap can
      // resolve a code string back to its full object.
      var lastDtc = null;
      // The Alerts card index, so a tap navigates the carousel to it.
      var dtcCardIndex = -1;
      // US-508 home slot: ONE element with two faces. `lastIdle` edge-triggers
      // the navigation so it fires only on a state CHANGE -- it never fights a
      // manual swipe while a state holds.
      var homeCard = document.getElementById("home-card");
      var homeIndex = -1;
      var lastIdle = null;
      // US-497 g-trail + US-508 grade trend: accumulated across polls from the
      // states/imu values (Atlas Q-B -- animate from the polled feed). They live
      // here, not on the card, so they are dropped with the poll rather than
      // outliving the feed that produced them.
      var gTrail = [];
      var gradeTrend = [];
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
      var lastSys = null;
      var lastBattery = null;
      var lastGear = null;
      // US-496: the vehicle-dependent cards, revealed only while a vehicle is
      // actually connected (they ship `hidden`, so the pre-first-poll unknown
      // shows no vehicle card).
      var gatedCards = [];
      for (var ci = 0; ci < cards.length; ci++) {
        var st = cards[ci].getAttribute("data-state");
        if (st === "dtc") dtcCardIndex = ci;
        if (cards[ci].getAttribute("data-idle-home") !== null) homeIndex = ci;
        if (cards[ci].getAttribute("data-vehicle-gated") !== null) {
          gatedCards.push(cards[ci]);
        }
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

      function findCode(codeStr) {
        if (!lastDtc || !Array.isArray(lastDtc.codes)) return null;
        for (var i = 0; i < lastDtc.codes.length; i++) {
          if (lastDtc.codes[i] && lastDtc.codes[i].code === codeStr) return lastDtc.codes[i];
        }
        return null;
      }
      function closeDetail() {
        if (detailEl) detailEl.hidden = true;
      }
      // Navigate the carousel to the Alerts card; optionally open a code detail.
      function openAlertsCard(codeStr) {
        if (dtcCardIndex >= 0 && typeof goTo === "function") goTo(dtcCardIndex);
        var codeObj = codeStr ? findCode(codeStr) : null;
        if (codeObj) openDetail(codeObj);
      }

      function hideTakeover() {
        if (!takeoverEl) return;
        takeoverEl.hidden = true;
        // US-537: drop the severity WITH the surface. The STOP alarm pulse hangs
        // off [data-severity="stop"], so leaving the attribute behind left an
        // acknowledged takeover matching the alarm rule forever -- inert only
        // because the element had no box. Same lockstep contract renderRibbon
        // already keeps with data-level: the state attribute and the surface go
        // up and down together, so motion can never outlive the alert.
        takeoverEl.removeAttribute("data-severity");
      }
      // Acknowledge/Dismiss -> record the stamp + drop to the ribbon (the ribbon
      // keeps carrying the alert). STOP has no plain dismiss, but Acknowledge is
      // still a drop-to-ribbon so the driver can always clear the view.
      function ackTakeover(view) {
        dtcLastAckedTs = view.newSinceTs;
        hideTakeover();
      }
      function showTakeover(view) {
        if (!takeoverEl) return;
        takeoverEl.setAttribute("data-severity", view.severity);
        if (tvIcon) tvIcon.textContent = view.icon;
        if (tvChip) tvChip.textContent = view.severity.toUpperCase();
        if (tvCode) tvCode.textContent = view.code;
        if (tvDesc) tvDesc.textContent = view.short;
        if (tvDirective) tvDirective.textContent = view.directive;
        if (tvMore) {
          if (view.moreCount > 0) {
            tvMore.textContent = "+" + view.moreCount + " more";
            tvMore.hidden = false;
          } else {
            tvMore.hidden = true;
          }
        }
        if (tvDismiss) {
          tvDismiss.textContent = view.dismissLabel;
          tvDismiss.onclick = function () { ackTakeover(view); };
        }
        // View detail (US-406): ack the takeover (drops it) + navigate to the
        // Alerts card and open the hero code's detail.
        if (tvDetail) {
          tvDetail.onclick = function () {
            ackTakeover(view);
            openAlertsCard(view.code);
          };
        }
        takeoverEl.hidden = false;
      }

      function renderRibbon(view) {
        if (!ribbonEl) return;
        if (!view) {
          ribbonEl.hidden = true;
          ribbonEl.removeAttribute("data-level");
          return;
        }
        ribbonEl.setAttribute("data-level", view.level);
        var glyph = ribbonEl.querySelector(".ribbon-glyph");
        var text = ribbonEl.querySelector(".ribbon-text");
        if (glyph) glyph.textContent = view.glyph;
        if (text) text.textContent = view.text;
        ribbonEl.hidden = false;
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

      function openDetail(codeObj) {
        var view = codeDetailView(codeObj);
        if (!view || !detailEl) return;
        renderDetailBody(view);
        renderClearButton();
        detailEl.hidden = false;
      }

      // --- US-407 clear surface (browser only) -------------------------------

      // Reflect the (display-mirror) gate onto the Clear button. No button when
      // nothing is clearable; disabled + reason label otherwise; enabled only on
      // `ok`. The server RE-CHECKS the gate on submit -- the button never forces.
      function renderClearButton() {
        if (!clearBtn) return;
        if (clearResult) clearResult.textContent = "";
        var view = clearButtonView(lastDtc);
        // US-491: the zone is now a bordered, LABELLED card, so it must go with
        // the button -- an empty "CLEAR CODES" box on a nothing-to-clear detail
        // is a new visual regression. The GATE is untouched: visibility still
        // comes from clearButtonView(), and the server re-checks on submit.
        if (clearZone) clearZone.hidden = !view.visible;
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
        fetch("/dtc-clear", {
          method: "POST",
          headers: { "X-Splash-Token": token, "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: true }),
        })
          .then(function (r) {
            return r.json().then(
              function (j) { return { status: r.status, body: j }; },
              function () { return { status: r.status, body: {} }; }
            );
          })
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

      // --- US-406 Alerts card render (browser only) --------------------------

      function renderAlertsCard(card, view) {
        var body = card.querySelector(".card-body");
        if (!body || !view) return;
        // US-429 / Bug-3b: DTC source unavailable -> a typed NA, NOT "No stored
        // codes" (a false all-clear) and NOT a mis-fired takeover.
        // US-542 AC-2: that NA now carries the line the retired idle face used
        // to hold -- "DTC not read · since key-off · <why>". Rendered from the
        // VIEW's tile, so the words are pinned by a pure test rather than
        // living as a renderer literal (`renderNaBody` composes "NA" here,
        // which would have swallowed the moved fact).
        if (view.unavailable) {
          body.textContent = "";
          appendTile(body, view.notRead);
          return;
        }
        body.textContent = "";

        // Header count line (stored · pending).
        var head = document.createElement("div");
        head.className = "dtc-count";
        head.textContent = view.storedCount + " stored · " + view.pendingCount + " pending";
        body.appendChild(head);

        // Hero block (worst code + its directive), when an alert-eligible code
        // exists (na-only / empty -> no hero).
        if (view.hero) {
          var heroEl = document.createElement("button");
          heroEl.className = "dtc-hero tap-target";
          heroEl.setAttribute("data-level", view.hero.level);
          var hChip = document.createElement("span");
          hChip.className = "dtc-chip";
          hChip.setAttribute("data-level", view.hero.level);
          hChip.textContent = view.hero.chip;
          heroEl.appendChild(hChip);
          var hCode = document.createElement("span");
          hCode.className = "dtc-hero-code";
          hCode.textContent = view.hero.code;
          heroEl.appendChild(hCode);
          var hShort = document.createElement("span");
          hShort.className = "dtc-hero-short";
          hShort.textContent = view.hero.short;
          heroEl.appendChild(hShort);
          var hDir = document.createElement("span");
          hDir.className = "dtc-hero-directive";
          hDir.textContent = view.hero.directive;
          heroEl.appendChild(hDir);
          (function (codeStr) {
            heroEl.addEventListener("click", function () { openAlertsCard(codeStr); });
          })(view.hero.code);
          body.appendChild(heroEl);
        } else if (view.rows.length === 0) {
          // No codes at all -> an honest all-clear (never a fabricated green).
          body.appendChild(detailLine("dtc-noalert", "", "No stored codes"));
        }

        // Compact tappable rows (worst-first, na last). Each opens the detail.
        for (var i = 0; i < view.rows.length; i++) {
          (function (r) {
            var row = document.createElement("button");
            row.className = "dtc-row tap-target";
            row.setAttribute("data-level", r.level);
            var rChip = document.createElement("span");
            rChip.className = "dtc-chip";
            rChip.setAttribute("data-level", r.level);
            rChip.textContent = r.chip;
            row.appendChild(rChip);
            var rCode = document.createElement("span");
            rCode.className = "dtc-row-code";
            rCode.textContent = r.code;
            row.appendChild(rCode);
            var rShort = document.createElement("span");
            rShort.className = "dtc-row-short";
            rShort.textContent = r.short + (r.caveat ? "  ⚠ " + r.caveat : "");
            row.appendChild(rShort);
            var rStatus = document.createElement("span");
            rStatus.className = "dtc-row-status";
            rStatus.textContent = r.status;
            row.appendChild(rStatus);
            row.addEventListener("click", function () { openDetail(findCode(r.code) || r); });
            body.appendChild(row);
          })(view.rows[i]);
        }
      }

      if (detailBack) detailBack.addEventListener("click", closeDetail);
      // US-509: the System-Status drill-down's Back, wired beside its sibling so
      // the two overlays' escape hatches live together. AC2 -- never traps.
      var sysDetailBack = document.getElementById("sys-detail-back");
      if (sysDetailBack) sysDetailBack.addEventListener("click", closeSysDetail);
      // The ribbon is tappable -> jump to the Alerts card + the hero detail.
      if (ribbonEl) {
        ribbonEl.addEventListener("click", function () {
          if (ribbonEl.hidden) return;
          var view = ribbonView(lastDtc);
          openAlertsCard(view ? view.code : null);
        });
      }

      // Apply the polled `dtc` state to the ribbon + takeover. A missing/malformed
      // `dtc` file -> no alert (honest: absence of the state = no active fault),
      // never a fabricated code.
      function updateDtcSurfaces(dtcData) {
        lastDtc = dtcData;
        renderRibbon(ribbonView(dtcData));
        var view = takeoverView(dtcData);
        if (view && takeoverShouldShow(view, dtcLastAckedTs)) {
          showTakeover(view);
        } else {
          hideTakeover();
        }
      }

      // US-508: paint the home slot. Called from BOTH loops -- the ~10 Hz live
      // poll (which supplies fresh motion) and the 4 Hz card tick (which
      // supplies fresh system/battery/dtc for the idle face) -- so whichever
      // fact changed, the slot repaints from ONE renderer against ONE face
      // decision. Two renderers racing for one slot is the defect a two-faced
      // card invites, and the reason `homeFace` is the only arbiter.
      function renderHome(nowMs) {
        if (!homeCard) return;
        // US-662: smooth for DISPLAY only. lastImu itself is untouched.
        var imuView = smoothedImuView(lastImu, nowMs);
        var face = homeFace(imuView, nowMs);
        if (face.face === "live") {
          // US-645: the fourth argument is the OBD vehicle speed, and it is
          // NULL because no producer publishes one to this dashboard -- the
          // realtime SPEED reading lives in the orchestrator and reaches no
          // state file the panel can fetch (I-us645). Null is the honest value,
          // not a placeholder: it is what stops the G-FORCE tile claiming
          // `still` at a 65 mph cruise, where gLon is ~0 too. The label
          // degrades to `coast`, which is true at any speed.
          // MERGE 2026-09-01 (US-671): the FIRST argument is US-662's SMOOTHED
          // `imuView`, not `lastImu`. Both sides of this conflict were fixes the
          // CIO had already accepted, and either one-sided resolution silently
          // reverts one of them: `lastImu` kills the 3-second smoothing he
          // confirmed by eye in the car, and dropping the 4th argument brings
          // back `still` at a 65 mph cruise. The union is the only correct
          // answer, which is why this call reads the way it does.
          var live = liveCardView(imuView, lastGear, nowMs, null);
          if (live && !live.idle) {
            // Advance both accumulators every paint. Eviction runs even with no
            // new point, so a feed that degrades mid-drive decays its history
            // instead of leaving a shape the vehicle is no longer making.
            gTrail = pushGTrail(
              gTrail,
              live.g.available ? live.g.dot : null,
              nowMs, G_TRAIL_WINDOW_SEC
            );
            gradeTrend = pushGradeTrend(
              gradeTrend,
              live.grade.available ? live.grade.pct : null,
              nowMs, GRADE_TREND_WINDOW_SEC, GRADE_TREND_BUCKET_MS
            );
            renderHomeCard(homeCard, face, live, null, gTrail, gradeTrend);
            return;
          }
        }
        // The idle face. RESET both accumulators: splicing a point from before
        // an outage onto one after it would draw a trail the vehicle never took
        // and a grade history it never climbed.
        gTrail = [];
        gradeTrend = [];
        // US-541: the reason is passed UNCONDITIONALLY. Under IMU-always-on the
        // idle face fires only because the motion feed died, so the hero must
        // always name the dead instrument. US-508 suppressed the reason when
        // parked so the calm STANDBY hero could show; leaving that ternary here
        // would hand a DEAD SENSOR the "engine off - OBD asleep" hero -- a
        // confident claim about the vehicle manufactured out of a sensor fault,
        // arriving through a condition that is now always false.
        // US-542: `lastDtc` is no longer handed to this view -- the faults tile
        // it fed is on the Alerts card now -- and neither is a Date: the clock
        // lives in the top bar, painted by its own tick.
        renderHomeCard(
          homeCard, face, null,
          idleCardView(lastSys, lastBattery, face.reason),
          null, null
        );
      }

      // Edge-triggered home navigation. US-508 RETARGETS it: US-481 sent the
      // operator to System Status when `idle` flipped false, because the home
      // card was a parked-only view and staying on it while driving would have
      // been useless. The home slot now BECOMES the live instrument, so
      // navigating away from it on engine start is exactly backwards -- both
      // edges now land on home, which is where the change is visible.
      function updateHomeNav(sysData) {
        var idle = carouselIdle(sysData);
        if (idle === lastIdle) return; // edge-trigger only -- never trap a swipe
        if (homeIndex >= 0) goTo(homeIndex);
        lastIdle = idle;
      }

      async function tick() {
        var dtcData = null; // fetched once (the Alerts card + ribbon/takeover share it)
        var sysData = null; // shared with the idle-home card (one fetch per tick)
        var batteryData = null;
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
          if (name === "dtc") dtcData = payload;
          else if (name === "system-status") sysData = payload;
          else if (name === "battery-health") batteryData = payload;
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
            // top bar and the idle-home card were rendered against.
            renderSourceCard(
              card,
              sourceCardView(
                spec, data, await stateOnce("system-status"), displayAutoDim, nowMs
              )
            );
            continue;
          }
          var avail = cardAvailability(data);
          card.classList.toggle("unavailable", avail === "unavailable");
          if (avail === "unavailable") {
            var body = card.querySelector(".card-body");
            // US-496: a card with a bespoke no-data view NAMES the silent
            // instrument (`dtc` must never read as an all-clear); every other
            // card keeps the shipped one-word fallback.
            var nd = noDataView(name);
            if (body && nd) renderNaBody(body, nd.label, nd.reason);
            else if (body) body.textContent = "unavailable";
            if (name === "system-status") resetSystemGlyphs(glyphEls);
            continue;
          }
          // available -> the per-card renderer owns the body.
          if (name === "system-status") {
            renderSystemStatusCard(card, systemStatusView(data), glyphEls);
          } else if (name === "dtc") {
            renderAlertsCard(card, alertsCardView(data));
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
        // US-405/US-406: drive the takeover + persistent ribbon from the same
        // `dtc` state the Alerts card rendered (one fetch per tick).
        updateDtcSurfaces(dtcData);
        // US-508: hand the slow-moving states to the home slot and repaint it,
        // then edge-trigger the home navigation. The live motion half arrives on
        // its own faster loop; this half keeps the IDLE face current so the slot
        // is already honest the instant the feed drops.
        lastSys = sysData;
        lastBattery = batteryData;
        // US-630: the derived gear. Read on THIS tick rather than the ~10 Hz
        // motion loop -- the producer debounces for >= 2 s before it will name a
        // gear, so a gear cannot change faster than the 4 Hz card tick can see
        // it, and polling it at 10 Hz would be 6 reads a second of a file that
        // had not moved. A missing/404 state leaves this null, which gearView
        // already renders as the honest "-- / no source": the tile falls back to
        // exactly the state it held before this story, never to a stale gear.
        lastGear = await stateOnce("gear");
        renderHome(nowMs);
        updateHomeNav(sysData);
        // US-659: `updateMenuAccess(sysData, nowMs)` was called here to repaint
        // the ⋮ per tick against the debounced parked signal. Removed with the
        // gate -- the kebab's visibility is no longer a function of any state.
        // US-483-b: drive the display brightness from the states/light feed
        // (pure consumer -- never the sensor). A real STOP holds it >= the alarm
        // floor; an absent/stale feed holds the fixed default (honest fallback).
        // US-507: `stateOnce` is idempotent, so this REUSES the payload the
        // Health card's Light section already read and only performs a real
        // fetch if no surface consumed it -- the auto-dim keeps working even if
        // the section is ever removed from the markup, with no flag to forget.
        await stateOnce("light");
        applyBrightness(
          brightnessLevel(
            lightData,
            displayAutoDim,
            nowMs,
            brightnessAlarmActive(dtcData)
          )
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
        pushImuSamples(lastImu, Date.now());
        renderHome(Date.now());
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

/* ============================================================================
 * File:    splash_probe.js
 * Purpose: US-499 (S6, F-121) render-regression backstop -- runs the SHIPPED
 *          boot-state-poll.js (F-103 splash) against the mini-DOM and reports
 *          whether the splash HANDED OFF to the dashboard or pinned/degraded.
 *
 *          This is the S1 half of the backstop. US-494's defect was NOT in the
 *          splash JS and NOT in computeBootState -- both were correct in
 *          isolation. It was that the payload the production wiring actually
 *          produced never reached healthy, so the handoff never fired and the
 *          Pi sat on "not ready (starting)" until reboot. The only place that
 *          shows up is END TO END: real emitter payload -> real poll JS ->
 *          did window.close() get called.
 *
 *          TIME IS VIRTUAL and advances POLL_MS per round, so minutes of
 *          driven clock cost milliseconds of wall clock. The page itself has
 *          no clock (US-869-d); time only indexes which boot-state was last
 *          written.
 *
 *          US-869-d: motion-gate.js is loaded BEFORE the poller, as index.html
 *          loads it, and getComputedStyle is stubbed from `computedStyles`
 *          ({elementId: {transitionDuration, animationName,
 *          animationDuration}}; an unlisted element computes 0s / none). Once
 *          the poller sets #splash-stage's opacity to 0 the probe dispatches
 *          `transitionend` on it -- unless `dispatchTransitionEnd` is false,
 *          modelling a browser that fires nothing because nothing animates.
 *
 *          US-785 (phase 0b): the page's three end events are modelled at
 *          given virtual ms -- DOMContentLoaded (`domContentLoadedMs`), the
 *          WARNING image's decode() resolving or, with `warningError`, failing
 *          (`warningDecodeMs`), and document.fonts.ready (`fontsReadyMs`); each
 *          defaults to 0. Events inside a poll round fire in time order, at
 *          their own virtual ms, so "the cross-fade starts at the last event"
 *          is measurable below POLL_MS. Once body.logo-up is set the probe
 *          dispatches the logo's `transitionend` -- unless
 *          `dispatchCrossFadeEnd` is false.
 *
 *          US-869-f (the spins): `computedStyles.logo` is what #logo computes
 *          WHILE a body.spin-N class is on (styles.css's `body.spin-N #logo`);
 *          with no spin class, or under `reducedMotion` (the media block),
 *          every element computes none / 0s. While a spin is live the probe is
 *          the browser's half: one rotation (`spinEventMs`, else the computed
 *          animationDuration) after a spin starts it dispatches #logo's
 *          `animationend` (spins 1 and 3) or one `animationiteration` per
 *          rotation (spin 2) -- unless `dispatchSpinEvents` is false.
 *          `spinEventMs` 0 dispatches at zero elapsed time.
 *
 *          US-869-g (the checklist): /capture-health and /system-status are
 *          served from `captureHealthStates` and `systemStatusStates`, each
 *          indexed by time exactly as `bootStates` is (the final entry repeats;
 *          a null entry, or an empty list, is a 404). Every state-file read is
 *          logged in `stateFetches` as {route, atMs, token}, so "one tick
 *          reads all three, with the token" is measurable.
 *
 *          Invoked as:  node splash_probe.js <inputJsonPath>
 *          Input:  {pollJsPath, motionGatePath, tree, bootStates,
 *                   captureHealthStates, systemStatusStates, rounds,
 *                   computedStyles, dispatchTransitionEnd, reducedMotion,
 *                   domContentLoadedMs, warningDecodeMs, warningError,
 *                   fontsReadyMs, dispatchCrossFadeEnd, dispatchSpinEvents,
 *                   spinEventMs}
 *          Output: {handoff, closeCalls, timeoutsQueued, degraded,
 *                   degradedMsg, polls, elapsedMs, crossFadeStartedAtMs,
 *                   crossFadeEndedAtMs, crossFadeEndDispatched,
 *                   warningDecodeCalls, spinLog, animationEvents,
 *                   fadeStartedAtMs, spinAtHandoff, animationLiveAtHandoff,
 *                   stateFetches, tree}
 * Author:  Ralph Agent (Rex)
 * Created: 2026-07-29 -- Sprint 66 US-499 (S6 render-regression backstop)
 * ==========================================================================*/
"use strict";

const fs = require("fs");
const path = require("path");
const dom = require(path.resolve(__dirname, "mini_dom.js"));

const POLL_MS = 250; // matches boot-state-poll.js -- one round is one poll

async function main() {
  const input = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));

  const doc = new dom.Document();
  const roots = Array.isArray(input.tree) ? input.tree : [input.tree];
  roots.forEach(function (spec) {
    dom.buildTree(doc, spec, doc.body);
  });

  const clock = new dom.Clock();
  let virtualMs = 0;
  let handoff = false;
  let handoffAtMs = null;
  let closeCalls = 0;
  let timeoutsQueued = 0;
  let polls = 0;

  // The state file is indexed by TIME, not by poll count: the emitter writes on
  // its own cadence (eclipse-boot-state.service --poll-ms, 500 by default) while
  // the splash reads at 250 ms, so a poll sees whatever was last WRITTEN. Two
  // independent cadences is the real system, and getting it wrong would decide
  // which emission a poll sees. The final entry repeats (a steady state); a
  // `null` entry models an unreadable file.
  // US-869-f: the spin the page is in, read off body.spin-N (0 = none).
  let spinAtHandoff = null;
  let animationLiveAtHandoff = null;
  function currentSpin() {
    for (let n = 1; n <= 3; n++) {
      if (doc.body.classList.contains("spin-" + n)) return n;
    }
    return 0;
  }
  function logoAnimationLive() {
    const logo = doc.getElementById("logo");
    if (!logo) return false;
    const cs = win.getComputedStyle(logo);
    return cs.animationName !== "none" && parseFloat(cs.animationDuration) > 0;
  }

  const states = input.bootStates || [];
  const emitIntervalMs = input.emitIntervalMs || 500;
  const computedStyles = input.computedStyles || {};
  const dispatchTransitionEnd = input.dispatchTransitionEnd !== false;
  let transitionEndDispatched = false;

  const win = {
    SPLASH_TOKEN: "test-token",
    performance: {
      now: function () {
        return virtualMs;
      },
    },
    close: function () {
      handoff = true;
      closeCalls += 1;
      if (handoffAtMs === null) {
        handoffAtMs = virtualMs;
        spinAtHandoff = currentSpin();
        animationLiveAtHandoff = logoAnimationLive();
      }
    },
    addEventListener: function () {},
    getComputedStyle: function (el) {
      const id = el && el.getAttribute ? el.getAttribute("id") : null;
      let entry = (id && computedStyles[id]) || {};
      // styles.css: #logo animates only under body.spin-N, and the
      // reduced-motion block turns every animation and transition off.
      if (id === "logo" && currentSpin() === 0) entry = {};
      if (input.reducedMotion) entry = {};
      return {
        transitionDuration: entry.transitionDuration || "0s",
        animationName: entry.animationName || "none",
        animationDuration: entry.animationDuration || "0s",
      };
    },
    matchMedia: function (query) {
      return { matches: !!input.reducedMotion && /prefers-reduced-motion/.test(query) };
    },
  };

  global.window = win;
  global.performance = win.performance;
  global.document = doc;
  // The last-written entry of a time-indexed sequence; null when none.
  function writtenAt(sequence) {
    if (!sequence || !sequence.length) return null;
    const idx = Math.min(Math.floor(virtualMs / emitIntervalMs), sequence.length - 1);
    const body = sequence[idx];
    return body === undefined ? null : body;
  }
  const stateRoutes = {
    "/boot-state": states,
    "/capture-health": input.captureHealthStates || [],
    "/system-status": input.systemStatusStates || [],
  };
  const stateFetches = [];
  global.fetch = function (url, options) {
    const route = String(url).split("?")[0];
    if (Object.prototype.hasOwnProperty.call(stateRoutes, route)) {
      if (route === "/boot-state") polls += 1;
      const headers = (options && options.headers) || {};
      stateFetches.push({ route: route, atMs: virtualMs, token: headers["X-Splash-Token"] || null });
      const body = writtenAt(stateRoutes[route]);
      if (body === null) {
        return Promise.resolve({ ok: false, status: 404 });
      }
      return Promise.resolve({
        ok: true,
        status: 200,
        json: function () {
          return Promise.resolve(body);
        },
      });
    }
    if (route === "version.txt") {
      return Promise.resolve({
        ok: true,
        status: 200,
        text: function () {
          return Promise.resolve(input.version || "V0.29.20");
        },
      });
    }
    return Promise.resolve({ ok: false, status: 404 });
  };
  global.setTimeout = function (fn) {
    timeoutsQueued += 1;
    return clock.setTimeout(fn);
  };
  global.clearTimeout = function (id) {
    return clock.clearTimeout(id);
  };

  // --- Phase 0b (US-785): the three end events, each a promise or an event the
  // probe settles at its own virtual ms. The scripts sit at the end of <body>,
  // so they run while the document is still "loading".
  doc.readyState = "loading";
  function deferred() {
    const d = {};
    d.promise = new Promise(function (resolve, reject) {
      d.resolve = resolve;
      d.reject = reject;
    });
    return d;
  }
  const decoded = deferred();
  const fontsReady = deferred();
  doc.fonts = { ready: fontsReady.promise };
  let warningDecodeCalls = 0;
  const warningImg = doc.getElementById("warning");
  if (warningImg) {
    warningImg.decode = function () {
      warningDecodeCalls += 1;
      return decoded.promise;
    };
  }
  const pageEvents = [
    {
      atMs: input.domContentLoadedMs || 0,
      fire: function () {
        doc.readyState = "interactive";
        doc.dispatch("DOMContentLoaded", { target: doc });
      },
    },
    {
      atMs: input.warningDecodeMs || 0,
      fire: function () {
        if (input.warningError) decoded.reject(new Error("EncodingError"));
        else decoded.resolve();
      },
    },
    {
      atMs: input.fontsReadyMs || 0,
      fire: function () {
        fontsReady.resolve(doc.fonts);
      },
    },
  ].sort(function (a, b) {
    return a.atMs - b.atMs;
  });
  // A rejection nobody awaits yet must not crash node before the page attaches.
  decoded.promise.catch(function () {});

  const dispatchCrossFadeEnd = input.dispatchCrossFadeEnd !== false;
  let crossFadeEndDispatched = false;
  let crossFadeStartedAtMs = null;
  let crossFadeEndedAtMs = null;

  if (input.motionGatePath) require(path.resolve(input.motionGatePath));
  require(path.resolve(input.pollJsPath));

  // The browser's half of the fade: once the stage's opacity is 0, a real
  // transition ends with a `transitionend` on the stage itself.
  function maybeEndTransition() {
    if (!dispatchTransitionEnd || transitionEndDispatched) return;
    const stage = doc.getElementById("splash-stage");
    if (!stage || stage.style.opacity !== "0") return;
    transitionEndDispatched = true;
    stage.dispatch("transitionend", { target: stage, propertyName: "opacity" });
  }

  // The browser's half of the cross-fade: body.logo-up starts the logo's
  // opacity transition, which ends with a `transitionend` on the logo itself.
  function maybeEndCrossFade() {
    const body = doc.body;
    if (crossFadeStartedAtMs === null && body.classList.contains("logo-up")) {
      crossFadeStartedAtMs = virtualMs;
    }
    if (dispatchCrossFadeEnd && !crossFadeEndDispatched && crossFadeStartedAtMs !== null) {
      const logo = doc.getElementById("mark");
      if (logo) {
        crossFadeEndDispatched = true;
        logo.dispatch("transitionend", { target: logo, propertyName: "opacity" });
      }
    }
    if (crossFadeEndedAtMs === null && body.classList.contains("phase-1")) {
      crossFadeEndedAtMs = virtualMs;
    }
  }

  // The browser's half of the spins (US-869-f). A spin is a new run each time
  // the body's spin class changes; while it is live, its events fall due one
  // rotation apart from the moment it started.
  const dispatchSpinEvents = input.dispatchSpinEvents !== false;
  const spinLog = [];
  const animationEvents = [];
  let spinRun = null;
  function rotationMs() {
    if (typeof input.spinEventMs === "number") return input.spinEventMs;
    const logo = doc.getElementById("logo");
    const raw = logo ? win.getComputedStyle(logo).animationDuration : "0s";
    const n = parseFloat(raw);
    return /ms$/.test(raw) ? n : n * 1000;
  }
  // Every spin the page STARTS is logged at the moment its class goes on --
  // including one that advances synchronously because no event will fire.
  const bodyClassAdd = doc.body.classList.add.bind(doc.body.classList);
  doc.body.classList.add = function (name) {
    bodyClassAdd(name);
    const m = /^spin-([123])$/.exec(name);
    if (!m) return;
    spinRun = { spin: Number(m[1]), startedAtMs: virtualMs, live: logoAnimationLive(), events: 0 };
    spinLog.push({ spin: spinRun.spin, atMs: virtualMs, live: spinRun.live });
  };
  function maybeAdvanceSpin() {
    const n = currentSpin();
    if (n === 0 || !spinRun || spinRun.spin !== n) return false;
    if (!dispatchSpinEvents || !spinRun.live || spinRun.done) return false;
    const due = spinRun.startedAtMs + (spinRun.events + 1) * rotationMs();
    if (virtualMs < due) return false;
    const logo = doc.getElementById("logo");
    const type = n === 2 ? "animationiteration" : "animationend";
    spinRun.events += 1;
    if (type === "animationend") spinRun.done = true;
    animationEvents.push({ type: type, spin: n, atMs: virtualMs });
    logo.dispatchAnimationEvent(type, "spin", (spinRun.events * rotationMs()) / 1000);
    return true;
  }

  let fadeStartedAtMs = null;
  async function settle() {
    await dom.drainMicrotasks();
    // Bounded: each pass lets at most one spin event land and the page answer
    // it, so a zero-length rotation cascades spin 1 -> 2 -> 3 -> fade at once.
    for (let pass = 0; pass < 16; pass++) {
      maybeEndCrossFade();
      const spun = maybeAdvanceSpin();
      const stage = doc.getElementById("splash-stage");
      if (fadeStartedAtMs === null && stage && stage.style.opacity === "0") {
        fadeStartedAtMs = virtualMs;
      }
      maybeEndTransition();
      await dom.drainMicrotasks();
      if (!spun && pass > 0) break;
    }
    maybeEndCrossFade();
  }

  // Fire every page event due before `limitMs`, each at its own virtual ms.
  async function fireEventsBefore(limitMs) {
    while (pageEvents.length && pageEvents[0].atMs < limitMs) {
      const ev = pageEvents.shift();
      virtualMs = Math.max(virtualMs, ev.atMs);
      ev.fire();
      await settle();
    }
  }

  for (let i = 0; i < (input.rounds || 80); i++) {
    const roundStartMs = virtualMs;
    await settle();
    clock.flushRound();
    await fireEventsBefore(roundStartMs + POLL_MS);
    virtualMs = roundStartMs + POLL_MS;
    if (handoff) break;
  }
  await settle();

  const msg = doc.getElementById("degraded-msg");
  process.stdout.write(
    JSON.stringify({
      handoff: handoff,
      handoffAtMs: handoffAtMs,
      closeCalls: closeCalls,
      timeoutsQueued: timeoutsQueued,
      transitionEndDispatched: transitionEndDispatched,
      degraded: doc.body.classList.contains("degraded"),
      degradedMsg: msg ? msg.textContent : "",
      polls: polls,
      elapsedMs: virtualMs,
      crossFadeStartedAtMs: crossFadeStartedAtMs,
      crossFadeEndedAtMs: crossFadeEndedAtMs,
      crossFadeEndDispatched: crossFadeEndDispatched,
      warningDecodeCalls: warningDecodeCalls,
      spinLog: spinLog,
      animationEvents: animationEvents,
      fadeStartedAtMs: fadeStartedAtMs,
      spinAtHandoff: spinAtHandoff,
      animationLiveAtHandoff: animationLiveAtHandoff,
      stateFetches: stateFetches,
      tree: dom.serialize(doc.body),
    })
  );
}

main().then(null, function (err) {
  process.stderr.write(String((err && err.stack) || err));
  process.exit(2);
});

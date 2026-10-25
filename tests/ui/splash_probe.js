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
 *          Invoked as:  node splash_probe.js <inputJsonPath>
 *          Input:  {pollJsPath, motionGatePath, tree, bootStates, rounds,
 *                   computedStyles, dispatchTransitionEnd, reducedMotion,
 *                   domContentLoadedMs, warningDecodeMs, warningError,
 *                   fontsReadyMs, dispatchCrossFadeEnd}
 *          Output: {handoff, closeCalls, timeoutsQueued, degraded,
 *                   degradedMsg, polls, elapsedMs, crossFadeStartedAtMs,
 *                   crossFadeEndedAtMs, crossFadeEndDispatched,
 *                   warningDecodeCalls, tree}
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
      if (handoffAtMs === null) handoffAtMs = virtualMs;
    },
    addEventListener: function () {},
    getComputedStyle: function (el) {
      const id = el && el.getAttribute ? el.getAttribute("id") : null;
      const entry = (id && computedStyles[id]) || {};
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
  global.fetch = function (url) {
    const route = String(url).split("?")[0];
    if (route === "/boot-state") {
      const idx = Math.min(Math.floor(virtualMs / emitIntervalMs), states.length - 1);
      polls += 1;
      const body = states.length ? states[idx] : null;
      if (body === null || body === undefined) {
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

  async function settle() {
    await dom.drainMicrotasks();
    maybeEndTransition();
    maybeEndCrossFade();
    await dom.drainMicrotasks();
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
      tree: dom.serialize(doc.body),
    })
  );
}

main().then(null, function (err) {
  process.stderr.write(String((err && err.stack) || err));
  process.exit(2);
});

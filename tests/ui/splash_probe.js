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
 *          TIME IS VIRTUAL and advances POLL_MS per round, so the shipped
 *          MIN_PLAY_MS (2.5s) and HARD_CAP_MS (12s) thresholds are exercised
 *          for real in milliseconds of wall clock. `performance.now` is the
 *          seam the shipped JS already reads.
 *
 *          Invoked as:  node splash_probe.js <inputJsonPath>
 *          Input:  {pollJsPath, tree, bootStates, rounds}
 *          Output: {handoff, degraded, degradedMsg, polls, elapsedMs, tree}
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
  let polls = 0;

  // The state file is indexed by TIME, not by poll count: the emitter writes on
  // its own cadence (eclipse-boot-state.service --poll-ms, 500 by default) while
  // the splash reads at 250 ms, so a poll sees whatever was last WRITTEN. Two
  // independent cadences is the real system, and getting it wrong would decide
  // which hard cap -- the emitter's or the splash's -- fires first. The final
  // entry repeats (a steady state); a `null` entry models an unreadable file.
  const states = input.bootStates || [];
  const emitIntervalMs = input.emitIntervalMs || 500;

  const win = {
    SPLASH_TOKEN: "test-token",
    performance: {
      now: function () {
        return virtualMs;
      },
    },
    close: function () {
      handoff = true;
    },
    addEventListener: function () {},
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
    return clock.setTimeout(fn);
  };
  global.clearTimeout = function (id) {
    return clock.clearTimeout(id);
  };

  require(path.resolve(input.pollJsPath));

  for (let i = 0; i < (input.rounds || 80); i++) {
    await dom.drainMicrotasks();
    clock.flushRound();
    virtualMs += POLL_MS;
    if (handoff) break;
  }
  await dom.drainMicrotasks();

  const msg = doc.getElementById("degraded-msg");
  process.stdout.write(
    JSON.stringify({
      handoff: handoff,
      degraded: doc.body.classList.contains("degraded"),
      degradedMsg: msg ? msg.textContent : "",
      polls: polls,
      elapsedMs: virtualMs,
      tree: dom.serialize(doc.body),
    })
  );
}

main().then(null, function (err) {
  process.stderr.write(String((err && err.stack) || err));
  process.exit(2);
});

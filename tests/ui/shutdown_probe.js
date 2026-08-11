/* ============================================================================
 * File:    shutdown_probe.js
 * Purpose: US-549 (I-043) terminal-reason backstop -- runs the SHIPPED
 *          shutdown-state-poll.js (F-103 closeout splash) against the mini-DOM
 *          and reports WHY it exited.
 *
 *          The boot splash already had splash_probe.js; the closeout splash had
 *          nothing, and that is not a coincidence -- the closeout's only
 *          observable was `window.close()`, which is the same event for all four
 *          of its terminal cases. I-043 is exactly that gap, so the probe's whole
 *          job is to surface the discriminator: the console line the script now
 *          writes and the `data-terminal-*` attributes it leaves on <body>.
 *
 *          `console` is CAPTURED, not silenced-then-guessed: the shipped script's
 *          journal line and this probe's `consoleLines` are the same bytes, so a
 *          test asserting the grep string is asserting what the operator types.
 *
 *          TIME IS VIRTUAL and advances POLL_MS per round, so the shipped
 *          PRE_ROLL_MS (1s) and BLACK_TAIL_CAP_MS (60s) thresholds are exercised
 *          for real in milliseconds of wall clock. `performance.now` is the seam
 *          the shipped JS already reads.
 *
 *          Invoked as:  node shutdown_probe.js <inputJsonPath>
 *          Input:  {pollJsPath, tree, shutdownStates, rounds, emitIntervalMs}
 *          Output: {closed, closedAtMs, terminalCause, terminalRecord,
 *                   consoleLines, painted, polls, elapsedMs, tree}
 * Author:  Ralph Agent (Rex)
 * Created: 2026-08-10 -- Sprint 73 US-549 (I-043 observable terminal reason)
 * ==========================================================================*/
"use strict";

const fs = require("fs");
const path = require("path");
const dom = require(path.resolve(__dirname, "mini_dom.js"));

const POLL_MS = 250; // matches shutdown-state-poll.js -- one round is one poll

async function main() {
  const input = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));

  const doc = new dom.Document();
  const roots = Array.isArray(input.tree) ? input.tree : [input.tree];
  roots.forEach(function (spec) {
    dom.buildTree(doc, spec, doc.body);
  });

  const clock = new dom.Clock();
  let virtualMs = 0;
  let closed = false;
  let closedAtMs = null;
  let polls = 0;

  // The state file is indexed by TIME, not by poll count: the sequencer emits on
  // its own transitions while the splash reads at 250 ms, so a poll sees whatever
  // was last WRITTEN. The final entry repeats (a steady state); a `null` entry
  // models the file being absent -- which is a DIFFERENT outcome from a
  // `cancelled` phase, and telling those two apart is the whole point of I-043.
  const states = input.shutdownStates || [];
  const emitIntervalMs = input.emitIntervalMs || 500;

  // Capture rather than suppress: these lines ARE the journal evidence.
  const consoleLines = [];
  const capture = function () {
    consoleLines.push(
      Array.prototype.slice
        .call(arguments)
        .map(function (a) {
          return typeof a === "string" ? a : String(a);
        })
        .join(" ")
    );
  };
  global.console = { log: capture, error: capture, warn: capture, info: capture };

  const win = {
    SPLASH_TOKEN: "test-token",
    performance: {
      now: function () {
        return virtualMs;
      },
    },
    close: function () {
      closed = true;
      if (closedAtMs === null) closedAtMs = virtualMs;
    },
    addEventListener: function () {},
  };

  global.window = win;
  global.performance = win.performance;
  global.document = doc;
  global.fetch = function (url) {
    const route = String(url).split("?")[0];
    if (route === "/shutdown-state") {
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
          return Promise.resolve(input.version || "V0.29.28");
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
    if (closed) break;
  }
  await dom.drainMicrotasks();

  const recordJson = doc.body.getAttribute("data-terminal-record");

  process.stdout.write(
    JSON.stringify({
      closed: closed,
      closedAtMs: closedAtMs,
      terminalCause: doc.body.getAttribute("data-terminal-cause"),
      terminalRecord: recordJson === null ? null : JSON.parse(recordJson),
      consoleLines: consoleLines,
      painted: doc.body.classList.contains("animating"),
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

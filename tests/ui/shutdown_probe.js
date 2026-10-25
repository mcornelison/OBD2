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
 *          TIME IS VIRTUAL and advances POLL_MS per round, so a long shutdown
 *          (US-870-a: a 120 s at-home drain) runs in milliseconds of wall clock.
 *          `performance.now` is the seam the shipped JS reads for its
 *          report-only elapsedMs.
 *
 *          US-870-a: a `shutdownStates` entry may also be a fetch OUTCOME rather
 *          than a payload -- {"__fetch": "throw"} rejects the fetch (a refused
 *          connection) and {"__status": n} answers HTTP n with no body; `null`
 *          stays the 404. `paintedOnPoll` is the poll whose read revealed the
 *          stage (null = never painted).
 *
 *          US-869-d: motion-gate.js (the ONE event-will-fire helper, Atlas G2)
 *          is loaded BEFORE the poller when `motionGatePath` is given, and
 *          getComputedStyle is stubbed from `computedStyles` ({elementId:
 *          {transitionDuration, animationName, animationDuration}}; an unlisted
 *          element computes 0s / none).
 *
 *          US-870-b: `progress` is the bar's fill (#bar-fill's inline width) and
 *          the label's two lines (#label-1 / #label-2) when the run ends;
 *          `progressLog` is every CHANGE of those three, in order, each with
 *          the virtual ms and poll count it was first seen at.
 *
 *          US-883-c: `progress.kept` is #bar-kept's inline {left, width} (the
 *          amber rows-kept stretch; nulls until drawn), and a change of it is
 *          a change of the frame.
 *
 *          Invoked as:  node shutdown_probe.js <inputJsonPath>
 *          Input:  {pollJsPath, motionGatePath, tree, shutdownStates, rounds,
 *                   emitIntervalMs, computedStyles, reducedMotion}
 *          Output: {closed, closedAtMs, terminalCause, terminalRecord,
 *                   consoleLines, painted, paintedOnPoll, stageVisibility,
 *                   polls, elapsedMs, progress, progressLog, tree}
 * Author:  Ralph Agent (Rex)
 * Created: 2026-08-10 -- Sprint 73 US-549 (I-043 observable terminal reason)
 * Updated: 2026-10-25 -- Sprint 114 US-870-b (progress + progressLog)
 * Updated: 2026-10-25 -- Sprint 114 US-883-c (progress.kept)
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
  const computedStyles = input.computedStyles || {};

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
    if (route === "/shutdown-state") {
      const idx = Math.min(Math.floor(virtualMs / emitIntervalMs), states.length - 1);
      polls += 1;
      const body = states.length ? states[idx] : null;
      if (body === null || body === undefined) {
        return Promise.resolve({ ok: false, status: 404 });
      }
      if (body.__fetch === "throw") {
        return Promise.reject(new TypeError("Failed to fetch"));
      }
      if (body.__status !== undefined) {
        return Promise.resolve({ ok: body.__status >= 200 && body.__status < 300, status: body.__status });
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

  if (input.motionGatePath) require(path.resolve(input.motionGatePath));
  require(path.resolve(input.pollJsPath));

  let paintedOnPoll = null;
  const notePaint = function () {
    if (paintedOnPoll === null && doc.body.classList.contains("animating")) paintedOnPoll = polls;
  };

  // US-870-b: the bar and its two-line label, read off the DOM after every
  // round. An entry is logged only when one of the three CHANGES, so the log is
  // the succession of frames the driver would see, in order.
  const textOf = function (id) {
    const el = doc.getElementById(id);
    return el ? el.textContent : null;
  };
  const readProgress = function () {
    const fill = doc.getElementById("bar-fill");
    const kept = doc.getElementById("bar-kept");
    return {
      fill: fill && fill.style ? fill.style.width || null : null,
      line1: textOf("label-1"),
      line2: textOf("label-2"),
      kept: {
        left: kept && kept.style ? kept.style.left || null : null,
        width: kept && kept.style ? kept.style.width || null : null,
      },
    };
  };
  const progressLog = [];
  const noteProgress = function () {
    const now = readProgress();
    const last = progressLog.length ? progressLog[progressLog.length - 1] : null;
    if (last && last.fill === now.fill && last.line1 === now.line1 && last.line2 === now.line2 &&
        last.kept.left === now.kept.left && last.kept.width === now.kept.width) return;
    progressLog.push({
      atMs: virtualMs, poll: polls, fill: now.fill, line1: now.line1, line2: now.line2, kept: now.kept,
    });
  };

  noteProgress();
  for (let i = 0; i < (input.rounds || 80); i++) {
    await dom.drainMicrotasks();
    notePaint();
    noteProgress();
    clock.flushRound();
    virtualMs += POLL_MS;
    if (closed) break;
  }
  await dom.drainMicrotasks();
  notePaint();
  noteProgress();

  const stage = doc.getElementById("splash-stage");
  const recordJson = doc.body.getAttribute("data-terminal-record");

  process.stdout.write(
    JSON.stringify({
      closed: closed,
      closedAtMs: closedAtMs,
      terminalCause: doc.body.getAttribute("data-terminal-cause"),
      terminalRecord: recordJson === null ? null : JSON.parse(recordJson),
      consoleLines: consoleLines,
      painted: doc.body.classList.contains("animating"),
      paintedOnPoll: paintedOnPoll,
      stageVisibility: stage && stage.style ? stage.style.visibility || null : null,
      polls: polls,
      elapsedMs: virtualMs,
      progress: readProgress(),
      progressLog: progressLog,
      tree: dom.serialize(doc.body),
    })
  );
}

main().then(null, function (err) {
  process.stderr.write(String((err && err.stack) || err));
  process.exit(2);
});

/* ============================================================================
 * File:    carousel_probe.js
 * Purpose: US-429 test harness. Loads the browser-only carousel.js under node
 *          (module.exports path) and evaluates ONE pure view/logic function
 *          against a fixture, printing the JSON result. Lets the pytest fixture
 *          suite exercise the honest-availability display logic with no DOM and
 *          no JS test framework. Invoked as:
 *              node carousel_probe.js <fnName> <fixtureJson>
 *
 *          US-645 adds a BATCH mode, because a 17-second sample sequence at
 *          10 Hz is 170 evaluations and 170 node startups is not a test:
 *              node carousel_probe.js --map <fnName>   [arg lists on stdin]
 *          stdin carries a JSON array of ARGUMENT LISTS; stdout carries a JSON
 *          array of results, one per list, in order. Reading from stdin rather
 *          than argv is deliberate -- a few hundred state payloads overrun the
 *          Windows command-line limit long before they overrun a pipe.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-07-02 -- Sprint 52 US-429 (carousel honest-availability)
 * Modified: 2026-09-01 -- US-645: --map batch mode (deadband sample sweeps).
 * ==========================================================================*/
"use strict";

const path = require("path");
const carousel = require(
  path.resolve(
    __dirname,
    "..",
    "..",
    "src",
    "pi",
    "ui",
    "dashboard",
    "carousel.js"
  )
);

// --map <fnName>: read a JSON array of argument lists from stdin, evaluate the
// function once per list, print a JSON array of results. Same normalisation of
// `undefined` as the single-shot path below, so a caller reads one shape.
if (process.argv[2] === "--map") {
  const mapped = carousel[process.argv[3]];
  if (typeof mapped !== "function") {
    process.stderr.write("no such carousel export: " + process.argv[3]);
    process.exit(2);
  }
  const stdin = require("fs").readFileSync(0, "utf-8");
  const results = JSON.parse(stdin).map(function (argList) {
    const out = mapped.apply(null, argList);
    return out === undefined ? null : out;
  });
  process.stdout.write(JSON.stringify(results));
  process.exit(0);
}

const fnName = process.argv[2];
// Variadic: every argv past the function name is one JSON-encoded positional
// argument (US-481 idleCardView takes 3 state fixtures). Backward compatible --
// the pre-existing single-fixture callers pass exactly one arg.
const args = process.argv.slice(3).map((a) => JSON.parse(a));
const fn = carousel[fnName];
if (typeof fn !== "function") {
  process.stderr.write("no such carousel export: " + fnName);
  process.exit(2);
}
const result = fn.apply(null, args);
// undefined is not valid JSON -- normalize to null so the caller reads it back.
process.stdout.write(JSON.stringify(result === undefined ? null : result));

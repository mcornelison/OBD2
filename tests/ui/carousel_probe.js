/* ============================================================================
 * File:    carousel_probe.js
 * Purpose: US-429 test harness. Loads the browser-only carousel.js under node
 *          (module.exports path) and evaluates ONE pure view/logic function
 *          against a fixture, printing the JSON result. Lets the pytest fixture
 *          suite exercise the honest-availability display logic with no DOM and
 *          no JS test framework. Invoked as:
 *              node carousel_probe.js <fnName> <fixtureJson>
 * Author:  Ralph Agent (Rex)
 * Created: 2026-07-02 -- Sprint 52 US-429 (carousel honest-availability)
 * ==========================================================================*/
"use strict";

const path = require("path");
const carousel = require(
  path.resolve(
    __dirname,
    "..",
    "..",
    "specs",
    "UI",
    "dist",
    "dashboard-pi",
    "carousel.js"
  )
);

const fnName = process.argv[2];
const fixture = JSON.parse(process.argv[3]);
const fn = carousel[fnName];
if (typeof fn !== "function") {
  process.stderr.write("no such carousel export: " + fnName);
  process.exit(2);
}
const result = fn(fixture);
// undefined is not valid JSON -- normalize to null so the caller reads it back.
process.stdout.write(JSON.stringify(result === undefined ? null : result));

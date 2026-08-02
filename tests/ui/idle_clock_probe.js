/* ============================================================================
 * File:    idle_clock_probe.js
 * Purpose: US-503 probe for the idle-card wall clock. Loads the shipped
 *          carousel.js under node and prints `fmtClock` for one LOCAL wall time.
 *
 *          A dedicated probe rather than carousel_probe.js because that one
 *          JSON-decodes its arguments, and JSON has no Date -- it would hand
 *          fmtClock a Number and the formatter would read NaN. Here the Date is
 *          built from local calendar COMPONENTS, so getHours()/getMinutes()
 *          return exactly the requested wall time in any timezone: the fixture
 *          is the clock face, not an instant, which is what a kiosk shows.
 *
 *          Invoked as:  node idle_clock_probe.js <hour24> <minute>
 *          Output: the formatted clock string on stdout.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-08-01 -- Sprint 69 US-503 (12-hour AM/PM idle clock)
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

if (typeof carousel.fmtClock !== "function") {
  process.stderr.write("carousel.js does not export fmtClock");
  process.exit(2);
}

const hour = Number(process.argv[2]);
const minute = Number(process.argv[3]);
// A fixed, arbitrary date -- only the time-of-day is under test.
process.stdout.write(carousel.fmtClock(new Date(2026, 7, 1, hour, minute, 30)));

/* ============================================================================
 * File:    boot-state-poll.js
 * Purpose: F-103 boot-splash state machine (spec §5). Polls the localhost state
 *          server for boot-state, drives the honest-instrument UX:
 *            INIT -> PLAYING_NORMAL -> HEALTHY_YIELD | DEGRADED.
 *          The splash is a pure CONSUMER -- it renders the emitter's
 *          healthy/degraded booleans, it never decides system condition.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-06-29 -- Sprint 48 US-393 (F-103 boot splash)
 * ==========================================================================*/
(function () {
  "use strict";

  var POLL_MS = 250;        // 4 Hz tmpfs read (Atlas A-5)
  var MIN_PLAY_MS = 2500;   // earliest yield-on-healthy point (spec §5)
  var HARD_CAP_MS = 12000;  // degrade if no healthy verdict by here
  var T_START = (window.performance && performance.now) ? performance.now() : Date.now();

  var token = window.SPLASH_TOKEN || "";
  var settled = false;      // true once HEALTHY_YIELD or DEGRADED is reached

  // US-525 (I-042): the floor above is a MINIMUM VISIBLE duration, so it must be
  // anchored to the brand actually being PAINTED -- not to this script parsing.
  // The mark is an <object type="image/svg+xml">, i.e. a separate async document:
  // on a cold chromium the poll loop is already ticking while the stage is still
  // blank, so anchoring at parse let the splash satisfy its own 2.5 s floor
  // having shown the brand for a fraction of it, then fade. Measured on the Pi
  // (boot dc7a3848, 2026-08-02): the unit lived 9.8 s but chromium burned the
  // first ~5.4 s on startup before the page existed at all.
  //
  // null => not painted yet (or never will be). Deliberately NOT initialised to
  // 0: a brand that never loads must fall back to the parse anchor, never hold
  // the hand-off open (see brandFloorMs).
  var brandReadyMs = null;

  function markBrandReady() {
    if (brandReadyMs === null) brandReadyMs = elapsed();
  }

  /**
   * Earliest elapsed() at which HEALTHY_YIELD may fire.
   *
   * Bounded by HARD_CAP_MS on purpose: a very slow brand must not be able to
   * push the hand-off arbitrarily late, and must not tip a HEALTHY boot into the
   * amber DEGRADED branch (which persists until reboot) -- that would be a
   * dishonest instrument reading caused purely by a slow asset.
   */
  function brandFloorMs() {
    if (brandReadyMs === null) return MIN_PLAY_MS;   // honest fallback
    var floor = brandReadyMs + MIN_PLAY_MS;
    return floor < HARD_CAP_MS ? floor : HARD_CAP_MS;
  }

  // Retry-once on a transient IPC failure before treating boot-state as missing
  // (covers a single dropped poll / server not-yet-listening race).
  var consecutiveFailures = 0;
  var MAX_TRANSIENT_FAILURES = 1;

  function elapsed() {
    var now = (window.performance && performance.now) ? performance.now() : Date.now();
    return now - T_START;
  }

  async function fetchBootState() {
    try {
      var r = await fetch("/boot-state", {
        cache: "no-store",
        headers: token ? { "X-Splash-Token": token } : {},
      });
      if (!r.ok) return null;
      return await r.json();
    } catch (e) {
      return null;
    }
  }

  async function loadVersionChip() {
    // version.txt is a public static asset (no token). Malformed -> 'V?.?.?'
    // (spec §10 pinned), no throw, no kiosk crash.
    try {
      var r = await fetch("version.txt", { cache: "no-store" });
      if (!r.ok) return;
      var txt = (await r.text()).trim();
      if (txt) document.getElementById("version-chip").textContent = txt;
    } catch (e) {
      /* leave the placeholder; do not crash the kiosk */
    }
  }

  function enterDegraded(reason) {
    if (settled) return;
    settled = true;
    document.body.classList.add("degraded");        // amber ring + chip + freeze
    document.getElementById("warn-glyph").textContent = " ⚠"; // wordmark glyph
    var msg = document.getElementById("degraded-msg");
    msg.textContent = reason || "boot-progress instrument not reporting";
    msg.hidden = false;
    // DEGRADED persists until system reboot -- no window.close().
  }

  function enterHealthyYield() {
    if (settled) return;
    settled = true;
    // Fade out + hand off to the post-boot UI. Chromium kiosk closes itself
    // (D-3: JS-driven exit, no external pkill).
    document.getElementById("splash-stage").style.transition = "opacity 0.5s";
    document.getElementById("splash-stage").style.opacity = "0";
    setTimeout(function () { try { window.close(); } catch (e) {} }, 600);
  }

  async function tick() {
    if (settled) return;
    var state = await fetchBootState();

    if (state === null) {
      consecutiveFailures += 1;
      // Only treat the boot-state as truly missing once the retry-once window
      // AND the hard cap have both elapsed (transient drops must not trip amber).
      if (consecutiveFailures > MAX_TRANSIENT_FAILURES && elapsed() > HARD_CAP_MS) {
        enterDegraded("boot-progress instrument not reporting");
        return;
      }
      schedule();
      return;
    }
    consecutiveFailures = 0;

    if (state.degraded === true) {
      enterDegraded(state.degradedReason);
      return;
    }
    if (state.healthy === true && elapsed() >= brandFloorMs()) {
      enterHealthyYield();
      return;
    }
    if (elapsed() > HARD_CAP_MS) {
      enterDegraded(state.degradedReason || "boot did not reach healthy state");
      return;
    }
    schedule();
  }

  function schedule() {
    setTimeout(tick, POLL_MS);
  }

  // Anchor the visible floor to the brand's own load event (US-525). If the
  // event already fired before this listener attached, brandReadyMs stays null
  // and brandFloorMs() degrades to the historical parse anchor -- the previous
  // behaviour, never a stall.
  (function watchBrand() {
    var mark = document.getElementById("mark");
    if (!mark) return;                  // no brand element -> parse anchor
    mark.addEventListener("load", markBrandReady);
    mark.addEventListener("error", markBrandReady);  // broken SVG: don't wait
  })();

  loadVersionChip();
  schedule();
})();

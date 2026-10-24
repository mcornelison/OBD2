/* ============================================================================
 * File:    boot-state-poll.js
 * Purpose: F-103 boot-splash state machine (spec §5). Polls the localhost state
 *          server for boot-state, drives the honest-instrument UX:
 *            INIT -> PLAYING_NORMAL -> HEALTHY_YIELD | DEGRADED.
 *          The splash is a pure CONSUMER -- it renders the emitter's
 *          healthy/degraded booleans, it never decides system condition.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-06-29 -- Sprint 48 US-393 (F-103 boot splash)
 * Updated: 2026-10-24 -- US-869-d: no clocks (CIO no-timer rule). Degraded
 *          comes only from the emitter's two events; a null boot-state is
 *          WAITING. The hand-off closes on the fade's transitionend, or at once
 *          when motionGate says that event will not fire (Atlas G2). The only
 *          setTimeout left is the POLL_MS tick.
 * ==========================================================================*/
(function () {
  "use strict";

  var POLL_MS = 250;        // 4 Hz tmpfs read (Atlas A-5)

  var token = window.SPLASH_TOKEN || "";
  var settled = false;      // true once HEALTHY_YIELD or DEGRADED is reached

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
    msg.textContent = reason || "";
    msg.hidden = false;
    // DEGRADED persists until system reboot -- no window.close().
  }

  var closed = false;

  function closeWindow() {
    if (closed) return;
    closed = true;
    try { window.close(); } catch (e) {}
  }

  function fadeWillEnd(stage) {
    var gate = window.motionGate;
    return !!(gate && typeof gate.willFire === "function" && gate.willFire(stage, "transition"));
  }

  function enterHealthyYield() {
    if (settled) return;
    settled = true;
    // Fade out + hand off to the post-boot UI. Chromium kiosk closes itself
    // (D-3: JS-driven exit, no external pkill) on the fade's OWN end event.
    var stage = document.getElementById("splash-stage");
    stage.style.transition = "opacity 0.5s";
    if (!fadeWillEnd(stage)) {
      // No transitionend will fire (styles missing, reduced motion, no
      // motion-gate): advance on the healthy verdict itself (Atlas G2).
      stage.style.opacity = "0";
      closeWindow();
      return;
    }
    stage.addEventListener("transitionend", function (ev) {
      if (ev && ev.target && ev.target !== stage) return;   // a child's transition
      closeWindow();
    });
    stage.style.opacity = "0";
  }

  async function tick() {
    if (settled) return;
    var state = await fetchBootState();

    // A null boot-state (404, refused, thrown) is WAITING: the emitter has not
    // written yet. Keep polling and paint nothing new -- only the emitter's two
    // events (a core unit failed, assets missing) ever degrade the splash.
    if (state === null) {
      schedule();
      return;
    }

    if (state.degraded === true) {
      enterDegraded(state.degradedReason);
      return;
    }
    if (state.healthy === true) {
      enterHealthyYield();
      return;
    }
    schedule();
  }

  function schedule() {
    setTimeout(tick, POLL_MS);
  }

  // US-866: the splash's first frame, one console line (same format as the
  // dashboard's reportFirstFrame in carousel.js). It reaches the journal only
  // where chromium runs with --enable-logging=stderr.
  if (typeof window.requestAnimationFrame === "function" && typeof console !== "undefined") {
    window.requestAnimationFrame(function () {
      window.requestAnimationFrame(function () {
        console.info("[kiosk] first-frame page=splash sinceNavigationMs=" +
          Math.round(window.performance.now()));
      });
    });
  }

  loadVersionChip();
  schedule();
})();

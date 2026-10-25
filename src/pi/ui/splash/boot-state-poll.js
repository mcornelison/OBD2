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
 * Updated: 2026-10-24 -- US-785: phase 0b. The page opens on the WARNING
 *          image; once DOMContentLoaded has fired, the image has decoded (or
 *          failed) and document.fonts.ready has resolved, body.logo-up
 *          cross-fades it to the logo, and the logo's transitionend sets
 *          body.phase-1 (spin 1 starts there, US-869-f). No timer, no hold;
 *          the hand-off never waits for the cross-fade.
 * Updated: 2026-10-24 -- US-869-f: the spins. phase-1 starts spin 1 (one
 *          rotation); its animationend starts spin 2 (loops); the first
 *          animationiteration after the healthy read starts spin 3 (one
 *          rotation); its animationend starts the fade. Every wait asks
 *          motionGate.willFire first and, on false, advances on the event
 *          that started it (reduced motion, styles missing). The rotation's
 *          length lives once, in styles.css (--t-spin); the hand-off now
 *          follows 0b, because spin 1 does.
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

  function willFire(el, kind) {
    var gate = window.motionGate;
    return !!(el && gate && typeof gate.willFire === "function" && gate.willFire(el, kind));
  }

  function transitionWillEnd(el) {
    return willFire(el, "transition");
  }

  // --- Phase 0b (US-785, Atlas C-Atlas-5) -----------------------------------
  // Three EVENTS end it; none of them is a clock. Each promise below settles
  // and never rejects, so a failure is a visual degrade, never a stall.

  function noop() {}

  function domContentLoaded() {
    return new Promise(function (resolve) {
      if (document.readyState !== "loading") {
        resolve();
        return;
      }
      document.addEventListener("DOMContentLoaded", function () { resolve(); });
    });
  }

  // decode() resolves once the image is decoded and rejects on an image
  // error; both end the wait. No decode() means nothing to wait on.
  function warningDecoded() {
    var img = document.getElementById("warning");
    if (!img || typeof img.decode !== "function") return Promise.resolve();
    try {
      return Promise.resolve(img.decode()).then(noop, noop);
    } catch (e) {
      return Promise.resolve();
    }
  }

  // The wordmark is Michroma (US-869-e): cross-fade onto a settled face.
  function fontsReady() {
    var fonts = document.fonts;
    if (!fonts || !fonts.ready || typeof fonts.ready.then !== "function") {
      return Promise.resolve();
    }
    return fonts.ready.then(noop, noop);
  }

  var crossFadeEnded = false;

  function endCrossFade() {
    if (crossFadeEnded) return;
    crossFadeEnded = true;
    document.body.classList.add("phase-1");
    enterSpin(1);
  }

  function startCrossFade() {
    var logo = document.getElementById("mark");
    // Atlas G2: ask before waiting. No transitionend will fire (styles
    // missing, reduced motion) -> the cross-fade ends on the 0b event itself.
    var willEnd = !!logo && transitionWillEnd(logo);
    if (willEnd) {
      logo.addEventListener("transitionend", function (ev) {
        if (ev && ev.target && ev.target !== logo) return;   // a child's transition
        endCrossFade();
      });
    }
    document.body.classList.add("logo-up");     // warning out, logo in (styles.css)
    if (!willEnd) endCrossFade();
  }

  // --- The spins (US-869-f, spec §1.1) --------------------------------------
  // spin 1 once -> spin 2 loops -> spin 3 once -> the fade. Each step is
  // started by the previous step's OWN event; the one rotation is --t-spin in
  // styles.css and nowhere here. `ready` is the healthy boot-state.

  var SPIN_CLASSES = ["spin-1", "spin-2", "spin-3"];
  var spin = 0;             // 0 = before spin 1; 4 = the fade has begun
  var spinLive = false;     // the current spin's animation event will fire
  var ready = false;
  var spinListening = false;

  function listenToTheLogo(logo) {
    if (spinListening) return;
    spinListening = true;
    logo.addEventListener("animationend", function (ev) {
      if (ev && ev.target && ev.target !== logo) return;
      if (spin === 1) enterSpin(2);
      else if (spin === 3) enterFade();
    });
    logo.addEventListener("animationiteration", function (ev) {
      if (ev && ev.target && ev.target !== logo) return;
      // Spin 2 finishes the rotation it is in: spin 3 starts on the
      // iteration boundary, never mid-turn, so the logo never snaps.
      if (spin === 2 && ready) enterSpin(3);
    });
  }

  function enterSpin(n) {
    spin = n;
    var logo = document.getElementById("logo");
    var body = document.body;
    SPIN_CLASSES.forEach(function (c) { body.classList.remove(c); });
    // Every spin is the same @keyframes spin, so the browser would carry the
    // finished animation on instead of starting a new one: read the style
    // once with no spin class, and the next class starts it from 0deg.
    if (logo && typeof window.getComputedStyle === "function") {
      void window.getComputedStyle(logo).animationName;
    }
    body.classList.add("spin-" + n);
    spinLive = willFire(logo, "animation");
    if (spinLive) {
      listenToTheLogo(logo);
      return;
    }
    // No animation event will fire (reduced motion, styles missing): the
    // step advances on the event that started it (Atlas G2, C-Atlas-6).
    if (n === 1) enterSpin(2);
    else if (n === 2 && ready) enterSpin(3);
    else if (n === 3) enterFade();
  }

  function enterFade() {
    if (spin === 4) return;
    spin = 4;
    // Fade out + hand off to the post-boot UI. Chromium kiosk closes itself
    // (D-3: JS-driven exit, no external pkill) on the fade's OWN end event.
    var stage = document.getElementById("splash-stage");
    stage.style.transition = "opacity var(--t-fade)";   // the length lives in styles.css
    if (!transitionWillEnd(stage)) {
      // No transitionend will fire (styles missing, reduced motion, no
      // motion-gate): advance on spin 3's end itself (Atlas G2).
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

  function enterHealthyYield() {
    if (settled) return;
    settled = true;
    ready = true;
    // The readiness event advances only a spin 2 with no animation event to
    // wait for; a live spin 2 turns on to its next animationiteration, and a
    // page still in 0b or spin 1 reaches spin 2 with `ready` already set.
    if (spin === 2 && !spinLive) enterSpin(3);
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
  Promise.all([domContentLoaded(), warningDecoded(), fontsReady()]).then(startCrossFade);
  schedule();
})();

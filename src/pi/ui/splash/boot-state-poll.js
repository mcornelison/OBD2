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
 * Updated: 2026-10-25 -- US-869-g: the four-feed checklist and gate R1. Each
 *          tick reads /boot-state, /capture-health and /system-status
 *          together. Spin 3 waits for healthy AND IMU, LIGHT and UPS FINISHED
 *          (ready or faulted, latched for this boot); OBD never holds it.
 *          healthy latches, and degraded is honoured only before the first
 *          healthy read (Atlas R3). A failed eclipse-obd finishes the three as
 *          fault (Atlas G1). Polling ends when the window closes.
 * ==========================================================================*/
(function () {
  "use strict";

  var POLL_MS = 250;        // 4 Hz tmpfs read (Atlas A-5)

  var token = window.SPLASH_TOKEN || "";
  var degraded = false;     // DEGRADED reached: a dead end, polling stops
  var healthy = false;      // latched on the first healthy read (Atlas R3)

  // --- Producer vocabulary (US-869-g) ---------------------------------------
  // Copies, never twins: tests/ui/test_boot_checklist.py pins each one to its
  // source, so a producer rename turns that suite red.
  // carousel.js CAPTURE_FEEDS, in its order (Iris C-Iris-5: one feed order on
  // every surface); as a set, capture_health.FEED_NAMES.
  var FEEDS = ["obd", "light", "imu", "ups"];
  var NOT_WAITED_FOR = "obd";                   // capture_health.FEED_OBD (R1)
  var STATE_FAULTED = "faulted";                // capture_health.STATE_FAULTED
  var REASON_SENSOR_ABSENT = "sensor_absent";   // FEED_REASON_SENSOR_ABSENT
  var REASON_READ_FAILED = "read_failed";       // FEED_REASON_READ_FAILED
  var LINK_UP = "up";                           // system_status_emitter.LINK_UP
  // system_status_emitter.LINK_LAYERS, chain order, with the spec §1.3 words.
  var LINK_WORDS = [
    ["bt", "waiting for Bluetooth"],
    ["adapter", "waiting for adapter"],
    ["ecu", "waiting for ECU"],
  ];
  // Atlas G1: boot_state_emitter INFORMATIONAL_SERVICES_DEFAULT, the only
  // producer of capture-health, and its terminal systemctl failure word.
  var OBD_SERVICE = "eclipse-obd";
  var SERVICE_FAILED = "failed";

  async function fetchState(route) {
    try {
      var r = await fetch(route, {
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
    if (degraded || healthy) return;    // Atlas R3: never after healthy
    degraded = true;
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
  // styles.css and nowhere here. `ready` is gate R1 met (US-869-g).

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

  function enterReady() {
    if (ready) return;
    ready = true;
    document.body.classList.add("r1-met");     // reduced motion: --bright-max
    // The readiness event advances only a spin 2 with no animation event to
    // wait for; a live spin 2 turns on to its next animationiteration, and a
    // page still in 0b or spin 1 reaches spin 2 with `ready` already set.
    if (spin === 2 && !spinLive) enterSpin(3);
  }

  // --- The checklist (US-869-g, spec §1.3) ----------------------------------
  // A row's WORD is the feed's current state; its STEP latches. The first
  // ready-or-fault read finishes the step for this boot, and nothing after
  // un-finishes it (Iris C-Iris-6).

  var finished = {};        // feed -> true once its step has finished
  var obdServiceFailed = false;

  function isObject(v) {
    return v !== null && typeof v === "object";
  }

  // OBD's cause is the first link layer that is not up (ARCH-061's chain);
  // an unread layer, or no system-status at all, is plain `waiting`.
  function linkWord(status) {
    var link = isObject(status) ? status.link : null;
    if (!isObject(link)) return "waiting";
    for (var i = 0; i < LINK_WORDS.length; i++) {
      var layer = link[LINK_WORDS[i][0]];
      var state = isObject(layer) ? layer.state : null;
      if (state === LINK_UP) continue;
      if (state === null || state === undefined) return "waiting";
      return LINK_WORDS[i][1];
    }
    return "waiting";
  }

  function faultWord(reason) {
    if (reason === REASON_SENSOR_ABSENT) return "sensor not found";
    if (reason === REASON_READ_FAILED) return "read failed";
    return "fault";
  }

  // -> {word, tone, finished}. tone is the row's colour class (styles.css).
  function feedRow(name, capture, status) {
    var isObd = name === NOT_WAITED_FOR;
    // Atlas G1: eclipse-obd failed for good -- nothing will ever publish these
    // feeds, so their steps finish as fault and the car reaches the dashboard.
    if (obdServiceFailed) {
      if (isObd) return { word: linkWord(status), tone: "w-wait", finished: false };
      return { word: "fault", tone: "w-warn", finished: true };
    }
    var feeds = isObject(capture) ? capture.feeds : null;
    var feed = isObject(feeds) ? feeds[name] : null;
    if (!isObject(feed)) return { word: "not read", tone: "w-unread", finished: false };
    if (feed.state === STATE_FAULTED) {
      return { word: faultWord(feed.reason), tone: "w-warn", finished: true };
    }
    if (feed.firstSampleTs !== null && feed.firstSampleTs !== undefined) {
      return { word: "ready", tone: "w-ok", finished: true };
    }
    return { word: isObd ? linkWord(status) : "waiting", tone: "w-wait", finished: false };
  }

  function renderChecklist(capture, status) {
    FEEDS.forEach(function (name) {
      var row = feedRow(name, capture, status);
      if (row.finished) finished[name] = true;
      var el = document.getElementById("feed-" + name);
      if (!el) return;
      el.textContent = row.word;
      el.className = "cl-word " + row.tone;
    });
  }

  function gateFeeds() {
    return FEEDS.filter(function (name) { return name !== NOT_WAITED_FOR; });
  }

  function anyGateFeedFinished() {
    return gateFeeds().some(function (name) { return finished[name] === true; });
  }

  // Gate R1: healthy AND IMU, LIGHT and UPS finished. OBD is never waited for.
  function r1Met() {
    return healthy && gateFeeds().every(function (name) { return finished[name] === true; });
  }

  async function tick() {
    if (degraded || closed) return;
    var reads = await Promise.all([
      fetchState("/boot-state"),
      fetchState("/capture-health"),
      fetchState("/system-status"),
    ]);
    var state = reads[0];

    // A null boot-state (404, refused, thrown) is WAITING: the emitter has not
    // written yet. Only the emitter's two events (a core unit failed, assets
    // missing) ever degrade the splash, and only before healthy (Atlas R3):
    // after it, boot-state is read for services['eclipse-obd'] alone.
    if (state !== null) {
      if (!healthy && state.degraded === true) {
        enterDegraded(state.degradedReason);
        return;
      }
      if (state.healthy === true) healthy = true;
      var services = isObject(state.services) ? state.services : {};
      obdServiceFailed = services[OBD_SERVICE] === SERVICE_FAILED;
    }

    renderChecklist(reads[1], reads[2]);
    if (anyGateFeedFinished()) document.body.classList.add("feed-finished");
    if (r1Met()) enterReady();
    if (!closed) schedule();
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

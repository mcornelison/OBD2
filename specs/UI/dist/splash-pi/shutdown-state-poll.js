/* ============================================================================
 * File:    shutdown-state-poll.js
 * Purpose: F-103 shutdown-splash state machine (spec §6). The splash-grace.path
 *          unit starts this page the instant /run/eclipse-obd/states/shutdown-
 *          state appears; this script polls that file (token-gated) at 250ms
 *          and renders the spec §6 phase contract:
 *            phase=grace        -> PRE_ROLL (1s debounce) then ANIMATING
 *            phase=flushing     -> CONTINUE (no visual change)
 *            phase=powering_off -> CONTINUE (BLACK_TAIL naturally)
 *            phase=cancelled    -> ABORT (kill kiosk, no fadeout)
 *            unrecognized phase -> treat as cancelled (fail safe)
 *          The splash is a pure CONSUMER -- ShutdownSequencer is the SSOT of
 *          shutdown phase; this script only renders what it reads.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-06-29 -- Sprint 48 US-396 (F-103 shutdown splash render side)
 * ==========================================================================*/
(function () {
  "use strict";

  var POLL_MS = 250;          // 4 Hz tmpfs read (spec §6, Atlas A-5)
  var PRE_ROLL_MS = 1000;     // debounce window -- no paint before this (§6)
  var BLACK_TAIL_CAP_MS = 60000; // safety: exit if poweroff never fires (§6)
  var MAX_MISSING_RETRIES = 3;   // file-gone race: retry 3x then EXIT silently

  var token = window.SPLASH_TOKEN || "";
  var T_START = (window.performance && performance.now) ? performance.now() : Date.now();

  var painted = false;        // becomes true once we leave PRE_ROLL
  var aborted = false;        // terminal: ABORT or EXIT reached
  var missingCount = 0;       // consecutive shutdown-state-not-found polls

  function elapsed() {
    var now = (window.performance && performance.now) ? performance.now() : Date.now();
    return now - T_START;
  }

  async function fetchShutdownState() {
    try {
      var r = await fetch("/shutdown-state", {
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
      /* leave placeholder; never crash the kiosk */
    }
  }

  function exitKiosk() {
    // D-3 lesson: JS-driven exit, no external pkill. window.close() ends the
    // grace render; the .path/.service pair re-arms for the next cycle.
    try { window.close(); } catch (e) {}
  }

  function abort() {
    if (aborted) return;
    aborted = true;
    // ABORT (cancelled / unrecognized phase): kill immediately, no fadeout.
    exitKiosk();
  }

  function beginAnimating() {
    if (painted || aborted) return;
    painted = true;
    // Reveal the stage (PRE_ROLL no-paint window has now cleared, §6).
    var stage = document.getElementById("splash-stage");
    if (stage) stage.style.visibility = "visible";
    document.body.classList.add("animating");
  }

  async function tick() {
    if (aborted) return;

    // BLACK_TAIL safety cap: if poweroff never fires, don't hang on a black
    // screen forever -- exit so the post-boot UI can reappear (§6).
    if (elapsed() >= BLACK_TAIL_CAP_MS) {
      abort();
      return;
    }

    var state = await fetchShutdownState();

    if (state === null) {
      // shutdown-state missing (race or removed): retry a few times, then EXIT.
      missingCount += 1;
      if (missingCount >= MAX_MISSING_RETRIES) {
        abort();
        return;
      }
      schedule();
      return;
    }
    missingCount = 0;

    var phase = state.phase;
    if (phase === "cancelled") {
      abort();
      return;
    }
    if (phase === "grace" || phase === "flushing" || phase === "powering_off") {
      // grace/flushing/powering_off all CONTINUE the render; only leave PRE_ROLL
      // (paint) once the 1s debounce has elapsed.
      if (elapsed() >= PRE_ROLL_MS) {
        beginAnimating();
      }
      schedule();
      return;
    }

    // Unrecognized phase value -> fail safe (treat as cancelled, §6 edge case).
    abort();
  }

  function schedule() {
    setTimeout(tick, POLL_MS);
  }

  loadVersionChip();
  schedule();
})();

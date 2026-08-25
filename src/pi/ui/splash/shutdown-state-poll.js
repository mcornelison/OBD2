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
 *
 *          US-549 (I-043): every one of the four terminal outcomes above used to
 *          funnel through one SILENT window.close(), so from outside the browser
 *          a correct abort (power returned) and a cold-start race (the state file
 *          was not there yet) were indistinguishable -- the journal showed only
 *          `Started` ... `Deactivated successfully`. The reverse splash is
 *          validated by watching a REAL AC-loss event, which is rare, so burning
 *          one and learning "it exited after 2s" wastes the drill. Every exit now
 *          reports WHY, and the report carries the sequencer's own phase+reason
 *          alongside this script's local cause. Nothing is defaulted: a run that
 *          never managed to read the state file reports phase/reason as null
 *          rather than inventing a plausible one (honest instrument).
 * Author:  Ralph Agent (Rex)
 * Created: 2026-06-29 -- Sprint 48 US-396 (F-103 shutdown splash render side)
 * Updated: 2026-08-10 -- Sprint 73 US-549 (I-043 observable terminal reason)
 * ==========================================================================*/
(function () {
  "use strict";

  var POLL_MS = 250;          // 4 Hz tmpfs read (spec §6, Atlas A-5)
  var PRE_ROLL_MS = 1000;     // debounce window -- no paint before this (§6)
  var BLACK_TAIL_CAP_MS = 60000; // safety: exit if poweroff never fires (§6)
  var MAX_MISSING_RETRIES = 3;   // file-gone race: retry 3x then EXIT silently

  // US-549 (I-043): the four terminal causes, as an enum rather than prose, so
  // the journal line is greppable and a test can assert the exact string the
  // operator will search for. These name why the SPLASH stopped -- distinct from
  // the sequencer's `phase`/`reason`, which name why the PI is going down. Both
  // travel together in the report; conflating them is how case 1 and case 2
  // became indistinguishable in the first place.
  var CAUSE_CANCELLED = "cancelled";                    // phase=cancelled: correct abort
  var CAUSE_STATE_MISSING = "state-missing";            // file gone for MAX_MISSING_RETRIES polls
  var CAUSE_BLACK_TAIL_CAP = "black-tail-cap";          // poweroff never fired
  var CAUSE_UNRECOGNIZED_PHASE = "unrecognized-phase";  // fail-safe abort
  var TERMINAL_LOG_PREFIX = "[shutdown-splash] terminal ";

  var token = window.SPLASH_TOKEN || "";
  var T_START = (window.performance && performance.now) ? performance.now() : Date.now();

  var painted = false;        // becomes true once we leave PRE_ROLL
  var aborted = false;        // terminal: ABORT or EXIT reached
  var missingCount = 0;       // consecutive shutdown-state-not-found polls
  var pollCount = 0;          // shutdown-state reads attempted (0 => never polled)
  var lastState = null;       // last shutdown-state payload actually READ (never faked)

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

  /**
   * US-549 (I-043): record WHY this splash reached its terminal state.
   *
   * Two independent sinks, because they fail independently:
   *   - console -> chromium stderr -> `journalctl -u splash-grace.service`. This
   *     is the one the issue asks for, and it is the only one that survives the
   *     process. It requires `--enable-logging=stderr` on the grace unit: without
   *     that flag chromium swallows console output entirely and this whole story
   *     would be an elaborate no-op. The unit and this function ship together.
   *   - a `data-terminal-*` attribute pair on <body>, which costs no paint (an
   *     attribute, not a node) and is what a DevTools/harness inspection reads.
   *
   * Deliberately NOT a visible render: the terminal states are `cancelled` (the
   * shutdown is OFF -- painting anything would be a lie) and three abort paths
   * that spec 6 requires to exit immediately with no fadeout. I-043 says so
   * outright: forcing a paint when the state says the shutdown is over is the
   * dishonest instrument this splash exists to avoid.
   */
  function reportTerminal(cause) {
    var record = {
      cause: cause,
      // The sequencer's own words, straight off the last state we READ. Null --
      // not "unknown", not a default -- when we never got one: that null is the
      // signal that separates a raced cold start from a real cancellation.
      phase: lastState && lastState.phase !== undefined ? lastState.phase : null,
      reason: lastState && lastState.reason !== undefined ? lastState.reason : null,
      painted: painted,
      elapsedMs: Math.round(elapsed()),
      polls: pollCount,
    };
    try {
      console.log(TERMINAL_LOG_PREFIX + JSON.stringify(record));
    } catch (e) {
      /* a logging failure must never keep the kiosk alive through a poweroff */
    }
    try {
      document.body.setAttribute("data-terminal-cause", cause);
      document.body.setAttribute("data-terminal-record", JSON.stringify(record));
    } catch (e) {
      /* ditto */
    }
    return record;
  }

  function abort(cause) {
    if (aborted) return;
    aborted = true;
    // ABORT (cancelled / unrecognized phase): kill immediately, no fadeout --
    // but never anonymously (US-549). Report BEFORE the close: window.close()
    // is the last thing this context does.
    reportTerminal(cause);
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
      abort(CAUSE_BLACK_TAIL_CAP);
      return;
    }

    pollCount += 1;
    var state = await fetchShutdownState();

    if (state === null) {
      // shutdown-state missing (race or removed): retry a few times, then EXIT.
      missingCount += 1;
      if (missingCount >= MAX_MISSING_RETRIES) {
        abort(CAUSE_STATE_MISSING);
        return;
      }
      schedule();
      return;
    }
    missingCount = 0;
    lastState = state;

    var phase = state.phase;
    if (phase === "cancelled") {
      abort(CAUSE_CANCELLED);
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
    // The offending value is not lost: `lastState` carries it into the report,
    // which is the difference between "the splash quit" and "the sequencer wrote
    // a phase this kit does not know about".
    abort(CAUSE_UNRECOGNIZED_PHASE);
  }

  function schedule() {
    setTimeout(tick, POLL_MS);
  }

  loadVersionChip();
  schedule();
})();

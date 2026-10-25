/* ============================================================================
 * File:    shutdown-state-poll.js
 * Purpose: F-103 shutdown-splash state machine (spec §6). The splash-grace.path
 *          unit starts this page the instant /run/eclipse-obd/states/shutdown-
 *          state appears; this script polls that file (token-gated) at 250ms
 *          and renders the phase contract:
 *            phase=grace        -> stay HIDDEN, keep polling (the dashboard
 *                                  stays up; a blip ends in cancelled)
 *            phase=flushing     -> PAINT on the first read (ANIMATING)
 *            phase=powering_off -> PAINT on the first read; die with the power
 *            phase=cancelled    -> ABORT (kill kiosk, no fadeout)
 *            unrecognized phase -> ABORT (fail safe)
 *            HTTP 404           -> ABORT state-missing on the FIRST one: the
 *                                  file is written atomically and never
 *                                  deleted, so a 404 means it was never written
 *            refused / thrown   -> HOLD: no exit, keep the last paint (the
 *                                  states server going away is power-off in
 *                                  progress)
 *          US-870-a: the page holds NO timer of its own. The sequencer's
 *          smoothing window (grace -> flushing | cancelled) is the one debounce
 *          (CIO 2026-10-23: keep it); the 1s pre-roll, the 60s cap and the
 *          three-miss count are gone. POLL_MS is the sampling cadence of a loop
 *          that READS state, never a wait (Atlas C-Atlas-8).
 *          US-870-b: on each flushing/powering_off read the progress bar and
 *          its two-line label are drawn from step{index, of, name} alone
 *          (fill = index / of, never less than already drawn; line 1 the
 *          §2.2 step word, line 2 `step <index> of <of>`).
 *          The splash is a pure CONSUMER -- ShutdownSequencer is the SSOT of
 *          shutdown phase; this script only renders what it reads.
 *
 *          US-549 (I-043): every terminal outcome used to
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
 * Updated: 2026-10-25 -- Sprint 114 US-870-a (paint on flushing, 404 vs
 *          refused, no timer)
 * Updated: 2026-10-25 -- Sprint 114 US-870-b (progress bar + step words)
 * ==========================================================================*/
(function () {
  "use strict";

  var POLL_MS = 250;          // 4 Hz tmpfs read (spec §6, Atlas A-5)

  // US-549 (I-043): the terminal causes, as an enum rather than prose, so
  // the journal line is greppable and a test can assert the exact string the
  // operator will search for. These name why the SPLASH stopped -- distinct from
  // the sequencer's `phase`/`reason`, which name why the PI is going down. Both
  // travel together in the report; conflating them is how case 1 and case 2
  // became indistinguishable in the first place.
  var CAUSE_CANCELLED = "cancelled";                    // phase=cancelled: correct abort
  var CAUSE_STATE_MISSING = "state-missing";            // HTTP 404: the file was never written
  var CAUSE_UNRECOGNIZED_PHASE = "unrecognized-phase";  // fail-safe abort
  var TERMINAL_LOG_PREFIX = "[shutdown-splash] terminal ";

  // US-870-a: fetchShutdownState's distinct results. A 404 and a refused
  // connection used to collapse into one `null`; they mean opposite things.
  var FETCH_STATE = "state";       // a readable payload
  var FETCH_MISSING = "missing";   // HTTP 404 -> exit state-missing
  var FETCH_HOLD = "hold";         // refused / thrown / any other failure -> hold

  // US-870-b: line 1 of the label, per step.name (spec §2.2, verbatim). The
  // keys are power_watch.ceremony's CEREMONY_ORDER plus STEP_MONTHLY_TEST_HOLD,
  // pinned by tests/ui/test_shutdown_progress_page.py. `drain` says
  // WORD_OTHER until US-883-c hands the drain's label to the sync words.
  var STEP_WORDS = {
    "shed": "closing the dashboard",
    "drain": "shutting down",
    "drain close": "saving the battery record",
    "custody": "recording what synced",
    "monthly_test_hold": "monthly battery test",
    "poweroff": "powering off",
  };
  var WORD_OTHER = "shutting down";          // any other name, or step{} absent
  var WORD_STEPS_NOT_READ = "steps not read"; // line 2 when step{} is absent

  var token = window.SPLASH_TOKEN || "";
  var T_START = (window.performance && performance.now) ? performance.now() : Date.now();

  var painted = false;        // becomes true on the first flushing/powering_off read
  var aborted = false;        // terminal: ABORT or EXIT reached
  var pollCount = 0;          // shutdown-state reads attempted (0 => never polled)
  var lastState = null;       // last shutdown-state payload actually READ (never faked)

  // US-870-b: the last REAL step values read (null until one is), and the
  // fraction already drawn. The bar only ever grows from what it has drawn.
  var stepIndex = null;
  var stepOf = null;
  var stepName = null;
  var drawnFraction = 0;

  // REPORT-ONLY (Atlas C-Atlas-7): read by reportTerminal for the US-549 record
  // and by nothing else -- no condition in this file may consult it.
  function elapsed() {
    var now = (window.performance && performance.now) ? performance.now() : Date.now();
    return now - T_START;
  }

  /**
   * US-870-a: read shutdown-state, telling a 404 apart from a refused connection.
   *
   * Returns {kind: FETCH_STATE, state} for a readable payload, {kind:
   * FETCH_MISSING} for an HTTP 404 (the file is written atomically and never
   * deleted, so it was never written: Atlas A-sd 2), and {kind: FETCH_HOLD} for
   * everything else -- a thrown fetch, a refused connection, another status, an
   * unparseable body. Only the 404 is evidence of anything; the rest is the
   * states server going away under a poweroff, which the page rides out with
   * its last paint.
   */
  async function fetchShutdownState() {
    var r;
    try {
      r = await fetch("/shutdown-state", {
        cache: "no-store",
        headers: token ? { "X-Splash-Token": token } : {},
      });
    } catch (e) {
      return { kind: FETCH_HOLD };
    }
    if (r.status === 404) return { kind: FETCH_MISSING };
    if (!r.ok) return { kind: FETCH_HOLD };
    try {
      return { kind: FETCH_STATE, state: await r.json() };
    } catch (e) {
      return { kind: FETCH_HOLD };
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
   * shutdown is OFF -- painting anything would be a lie) and two abort paths
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
      // REPORT-ONLY (Atlas C-Atlas-7): how long the page lived, for the
      // journal. It decides nothing.
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
    // ABORT (cancelled / 404 / unrecognized phase): kill immediately, no fadeout --
    // but never anonymously (US-549). Report BEFORE the close: window.close()
    // is the last thing this context does.
    reportTerminal(cause);
    exitKiosk();
  }

  function beginAnimating() {
    if (painted || aborted) return;
    painted = true;
    // Reveal the stage: the first flushing/powering_off read (US-870-a).
    var stage = document.getElementById("splash-stage");
    if (stage) stage.style.visibility = "visible";
    document.body.classList.add("animating");
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function isCount(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 1;
  }

  /**
   * US-870-b: draw the bar and the two-line label from shutdown-state step{}.
   *
   * The fill is index / of, a step counting when it is ENTERED (Iris
   * C-Iris-4). index and of are one reading -- an index is a position in THAT
   * of -- so the pair is taken only when both are whole counts >= 1 with
   * index <= of; otherwise the last real pair holds (spec §2.1). A step whose
   * index is behind the last one drawn is stale and changes nothing: index
   * never goes back. A recomputed `of` that would draw less holds the bar:
   * the page never draws less than it has already drawn. step{} absent ->
   * 'shutting down' / 'steps not read' and the bar holds (spec §2.2).
   */
  function renderStep(step) {
    if (!step || typeof step !== "object") {
      setText("label-1", WORD_OTHER);
      setText("label-2", WORD_STEPS_NOT_READ);
      return;
    }
    if (isCount(step.index) && stepIndex !== null && step.index < stepIndex) return;

    if (isCount(step.index) && isCount(step.of) && step.index <= step.of) {
      stepIndex = step.index;
      stepOf = step.of;
    }
    if (typeof step.name === "string") stepName = step.name;

    var words = STEP_WORDS.hasOwnProperty(stepName) ? STEP_WORDS[stepName] : WORD_OTHER;
    setText("label-1", words);
    if (stepIndex === null) {
      setText("label-2", WORD_STEPS_NOT_READ);
      return;
    }
    setText("label-2", "step " + stepIndex + " of " + stepOf);
    drawnFraction = Math.max(drawnFraction, stepIndex / stepOf);
    var fill = document.getElementById("bar-fill");
    if (fill) fill.style.width = drawnFraction * 100 + "%";
  }

  async function tick() {
    if (aborted) return;

    pollCount += 1;
    var result = await fetchShutdownState();

    if (result.kind === FETCH_MISSING) {
      // A 404 exits on the FIRST one: the file was never written (Atlas A-sd 2).
      abort(CAUSE_STATE_MISSING);
      return;
    }
    if (result.kind === FETCH_HOLD) {
      // Refused / thrown: power-off in progress. No exit; the last paint holds.
      schedule();
      return;
    }
    var state = result.state;
    lastState = state;

    var phase = state.phase;
    if (phase === "cancelled") {
      // Key back on: no words (spec §2.2) -- the dashboard is underneath.
      setText("label-1", "");
      setText("label-2", "");
      abort(CAUSE_CANCELLED);
      return;
    }
    if (phase === "grace") {
      // The sequencer's smoothing window: not yet a real power loss. Stay
      // hidden -- the dashboard is still up -- and keep reading.
      schedule();
      return;
    }
    if (phase === "flushing" || phase === "powering_off") {
      // The power loss is real: paint on this read (Atlas A-sd 1).
      beginAnimating();
      renderStep(state.step);
      schedule();
      return;
    }

    // Unrecognized phase value -> fail safe (Atlas A-sd 3).
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

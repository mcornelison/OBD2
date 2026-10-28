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
 *          US-883-c: at home (sync.state joining / syncing / ended) the bar is
 *          0-75 % the drain by confirmed / waitingAtKeyOff and 75-100 % the
 *          steps after it; during the drain the sync words (sync.state, then
 *          sync.outcome once ended) take over the label, and a sync that ended
 *          with rows kept draws them as an amber stretch below the 75 % marker.
 *          Away (sync.state away) and the VCELL fast path (sync null) stay
 *          index / of.
 *          US-870-c: the logo is page-driven. Painted, it reverse-spins at
 *          --bright-hi and loops; once the fill is 100 % its next
 *          animationiteration starts one dim spin (--bright-low), whose
 *          animationend starts the dim-down, whose animationend starts the
 *          stage fade; the page then stays black and dies with the power.
 *          Every wait asks motionGate.willFire first; false advances that part
 *          at once. cancelled exits at any point with no close-out.
 *          US-870-e (spec §2.1 / §5a, CIO 2026-10-27): the dim spin starts on
 *          the first reverse animationiteration where >= MIN_REVERSE_TURNS
 *          turns are complete AND the bar was SEEN full -- #bar-fill's
 *          transitionend at 100 % (the 100 % read itself when no transitionend
 *          will fire). Reaching black, by any path, POSTs
 *          /shutdown-splash-done exactly once (never after cancelled): the
 *          poweroff waits for it (US-870-d).
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
 * Updated: 2026-10-25 -- Sprint 114 US-883-c (the at-home sync part + words)
 * Updated: 2026-10-25 -- Sprint 114 US-870-c (the logo's spins + close-out)
 * Updated: 2026-10-27 -- Sprint 119 US-870-e (two turns, seen full, done once)
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
  // WORD_OTHER only while sync is null (the sync task has not started); once
  // a sync is read the sync words below take the drain's label (US-883-c).
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

  // US-883-c: the at-home bar (spec §2, Iris C-Iris-4). DRAIN_INDEX is the
  // 1-based position of "drain" in CEREMONY_ORDER (the guard pins it); 0-75 %
  // is the drain by sync, 75-100 % the steps after it, evenly.
  var DRAIN_INDEX = 2;
  var SYNC_PART = 0.75;

  // US-883-c: the label during the drain, per sync.state (spec §2.2,
  // verbatim). The keys are sync_with_server.SYNC_STATES, pinned by the guard.
  // A null line is filled in by renderSyncWords: syncing shows the counts,
  // ended the outcome words.
  var SYNC_STATE_WORDS = {
    "away": ["away from home", "not syncing"],
    "joining": ["joining home WiFi", ""],
    "syncing": ["syncing", null],
    "ended": [null, null],
  };
  var WORD_NOTHING_TO_SYNC = "nothing to sync";  // syncing with waitingAtKeyOff 0
  var WORD_SYNC_NOT_READ = "sync not read";      // sync{} absent or unreadable

  // US-883-c: line 1 once the sync has ended, per sync.outcome (spec §2.2,
  // verbatim). Every key is an OutcomeKind value (the guard pins it); any
  // other value says WORD_SYNC_ENDED. `interrupted` is provisional and never
  // published.
  var OUTCOME_WORDS = {
    "delivered": "synced",
    "stalled": "sync stalled",
    "at_home_server_down": "server not answering",
    "unknown_network": "home network not confirmed",
    "at_home_joining_timeout": "home WiFi not joined",
    "probe_misconfigured": "server check refused",
    "reserve_floor": "stopped at battery reserve",
  };
  var WORD_SYNC_ENDED = "sync ended";
  var WORD_ALL_CONFIRMED = "all rows confirmed";

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

  // US-883-c: at home once a joining / syncing / ended state is read -- the
  // path does not go back to away. The kept stretch, once drawn, stays.
  var atHome = false;
  var keptDrawn = false;

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
    enterLogoStep(STEP_SPIN);
  }

  // --- The logo (US-870-c, spec §2 Close-out) --------------------------------
  // reverse spin (loops while the bar is under 100 %) -> dim spin (once) ->
  // dim-down (once) -> the stage fade -> black. Each part is started by the
  // previous part's OWN event; every length lives in styles.css. The page then
  // stays black and dies with the power: no window.close() here.

  var STEP_NONE = 0;
  var STEP_SPIN = 1;       // body.spin-rev: --bright-hi, infinite
  var STEP_DIM = 2;        // body.spin-dim: --bright-low, one rotation
  var STEP_DIM_DOWN = 3;   // body.dim-down: one run
  var STEP_FADE = 4;       // the stage's opacity transition
  var STEP_BLACK = 5;      // body.black: the stage is at opacity 0
  var LOGO_CLASSES = ["spin-rev", "spin-dim", "dim-down"];

  // US-870-e: the reverse turns the logo must complete before the dim spin
  // (spec §2.1, CIO 2026-10-27: three turns minimum -- two reverse + the dim).
  var MIN_REVERSE_TURNS = 2;
  var SPLASH_DONE_ROUTE = "/shutdown-splash-done";   // states_http_server, US-870-d

  var logoStep = STEP_NONE;
  var logoLive = false;      // the current part's animation event will fire
  var full = false;          // the bar has been drawn to 100 %
  var seenFull = false;      // ... and its glide there has ended (US-870-e)
  var reverseTurns = 0;      // completed reverse turns: animationiteration count
  var doneSent = false;      // the done POST went (once, on black)
  var logoListening = false;

  function willFire(el, kind) {
    var gate = window.motionGate;
    return !!(el && gate && typeof gate.willFire === "function" && gate.willFire(el, kind));
  }

  function listenToTheLogo(logo) {
    if (logoListening) return;
    logoListening = true;
    logo.addEventListener("animationiteration", function (ev) {
      if (aborted || (ev && ev.target && ev.target !== logo)) return;
      if (logoStep !== STEP_SPIN) return;
      // The reverse spin finishes the rotation it is in: the dim spin starts
      // on an iteration boundary, never mid-turn, once enough turns are
      // complete and the bar has been seen full.
      reverseTurns += 1;
      if (reverseTurns >= MIN_REVERSE_TURNS && seenFull) enterLogoStep(STEP_DIM);
    });
    logo.addEventListener("animationend", function (ev) {
      if (aborted || (ev && ev.target && ev.target !== logo)) return;
      if (logoStep === STEP_DIM) enterLogoStep(STEP_DIM_DOWN);
      else if (logoStep === STEP_DIM_DOWN) enterFade();
    });
  }

  function enterLogoStep(step) {
    if (aborted) return;
    logoStep = step;
    var logo = document.getElementById("logo");
    var body = document.body;
    LOGO_CLASSES.forEach(function (c) { body.classList.remove(c); });
    // The two spins share @keyframes spin: read the style once with no class
    // on, so the next class starts a new run from its first keyframe.
    if (logo && typeof window.getComputedStyle === "function") {
      void window.getComputedStyle(logo).animationName;
    }
    body.classList.add(LOGO_CLASSES[step - 1]);
    logoLive = willFire(logo, "animation");
    if (logoLive) {
      listenToTheLogo(logo);
      return;
    }
    // No animation event will fire (reduced motion, styles missing): the part
    // advances on the read that started it (Atlas G2, C-Atlas-6). With no
    // turns to count, the bar seen full is the whole condition.
    if (step === STEP_SPIN && seenFull) enterLogoStep(STEP_DIM);
    else if (step === STEP_DIM) enterLogoStep(STEP_DIM_DOWN);
    else if (step === STEP_DIM_DOWN) enterFade();
  }

  // The single convergence of every black path (the stage's transitionend,
  // no transitionend, no stage), so the done signal lives here.
  function enterBlack() {
    if (logoStep === STEP_BLACK) return;
    logoStep = STEP_BLACK;
    document.body.classList.add("black");
    signalDone();
  }

  /**
   * US-870-e (Q3, Atlas S119): tell the sequencer the page is done, exactly
   * once and never after an abort (cancelled included). The poweroff waits on
   * this (US-870-d), bounded by its own ceiling; a failed POST is logged, and
   * the page stays black and dies with the power either way.
   */
  function signalDone() {
    if (doneSent || aborted) return;
    doneSent = true;
    try {
      fetch(SPLASH_DONE_ROUTE, {
        method: "POST",
        cache: "no-store",
        headers: token ? { "X-Splash-Token": token } : {},
        body: "",
      }).then(null, function (e) {
        console.log("[shutdown-splash] done POST failed: " + e);
      });
    } catch (e) {
      console.log("[shutdown-splash] done POST failed: " + e);
    }
  }

  function enterFade() {
    if (aborted || logoStep >= STEP_FADE) return;
    logoStep = STEP_FADE;
    var stage = document.getElementById("splash-stage");
    if (!stage) {
      enterBlack();
      return;
    }
    stage.style.transition = "opacity var(--t-fade)";   // the length lives in styles.css
    if (!willFire(stage, "transition")) {
      // No transitionend will fire: black on the dim-down's end itself.
      stage.style.opacity = "0";
      enterBlack();
      return;
    }
    stage.addEventListener("transitionend", function (ev) {
      if (ev && ev.target && ev.target !== stage) return;   // a child's transition
      enterBlack();
    });
    stage.style.opacity = "0";
  }

  // The 100 % read. The bar is SEEN full when its glide there ends: on
  // #bar-fill's transitionend, or on this read when none will fire.
  function noteFull() {
    if (full) return;
    full = true;
    var fill = document.getElementById("bar-fill");
    if (!willFire(fill, "transition")) {
      noteSeenFull();
      return;
    }
    fill.addEventListener("transitionend", function (ev) {
      if (aborted || (ev && ev.target && ev.target !== fill)) return;
      if (ev && ev.propertyName && ev.propertyName !== "width") return;
      noteSeenFull();
    });
  }

  // A live reverse spin turns on to its next animationiteration that has
  // enough turns; one with no event to wait for advances now.
  function noteSeenFull() {
    if (seenFull) return;
    seenFull = true;
    if (logoStep === STEP_SPIN && !logoLive) enterLogoStep(STEP_DIM);
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function isCount(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 1;
  }

  function isWhole(value) {
    return typeof value === "number" && isFinite(value) && Math.floor(value) === value && value >= 0;
  }

  // "1240" -> "1,240" (spec §2.2: comma thousands separators).
  function commas(n) {
    return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }

  /**
   * US-883-c: read shutdown-state.sync. null is its own answer -- the sync
   * task has not started, or the fast path never runs it. Absent, not an
   * object, or a state outside SYNC_STATE_WORDS is unreadable. The counts are
   * one reading, taken only as whole numbers with confirmed <= waitingAtKeyOff;
   * otherwise they are null and the bar holds.
   */
  function readSync(sync) {
    if (sync === null) return { kind: "none" };
    if (!sync || typeof sync !== "object" || !SYNC_STATE_WORDS.hasOwnProperty(sync.state)) {
      return { kind: "unread" };
    }
    var counts = null;
    if (isWhole(sync.waitingAtKeyOff) && isWhole(sync.confirmed) &&
        sync.confirmed <= sync.waitingAtKeyOff) {
      counts = { waiting: sync.waitingAtKeyOff, confirmed: sync.confirmed };
    }
    return {
      kind: "sync",
      state: sync.state,
      outcome: typeof sync.outcome === "string" ? sync.outcome : null,
      counts: counts,
    };
  }

  /**
   * US-883-c: the fraction this read asks for, or null to hold. Away and the
   * fast path: index / of. At home: before the drain 0; the drain itself
   * 75 % x confirmed / waitingAtKeyOff (75 % at once when nothing was owed,
   * and at ended, where the rows left are drawn amber instead); after it
   * 75 % + 25 % x (index - DRAIN_INDEX) / (of - DRAIN_INDEX). Joining, or
   * counts that are null, hold.
   */
  function targetFraction(read) {
    if (!atHome) return stepIndex / stepOf;
    if (stepIndex < DRAIN_INDEX) return 0;
    if (stepIndex > DRAIN_INDEX) {
      return SYNC_PART + (1 - SYNC_PART) * (stepIndex - DRAIN_INDEX) / (stepOf - DRAIN_INDEX);
    }
    if (read.kind !== "sync" || read.state === "joining" || read.counts === null) return null;
    if (read.state === "ended" || read.counts.waiting === 0) return SYNC_PART;
    return SYNC_PART * read.counts.confirmed / read.counts.waiting;
  }

  // US-883-c: a sync that ended with rows kept draws them as a length -- the
  // unfilled stretch of the sync part, ending at the 75 % marker, in amber.
  function drawKept(read) {
    if (keptDrawn || read.kind !== "sync" || read.state !== "ended" || read.counts === null) return;
    var kept = read.counts.waiting - read.counts.confirmed;
    if (kept <= 0) return;
    var el = document.getElementById("bar-kept");
    if (!el) return;
    var width = SYNC_PART * kept / read.counts.waiting * 100;
    el.style.left = SYNC_PART * 100 - width + "%";
    el.style.width = width + "%";
    keptDrawn = true;
  }

  // US-883-c: the label while the drain step runs (spec §2.2).
  function renderSyncWords(read) {
    if (read.kind === "unread") {
      setText("label-1", WORD_SYNC_NOT_READ);
      setText("label-2", "");
      return;
    }
    var words = SYNC_STATE_WORDS[read.state];
    var line1 = words[0];
    var line2 = words[1];
    var counts = read.counts;
    if (read.state === "syncing") {
      if (counts !== null && counts.waiting === 0) {
        line1 = WORD_NOTHING_TO_SYNC;
        line2 = "";
      } else {
        line2 = counts === null ? "" : commas(counts.confirmed) + " of " + commas(counts.waiting) + " rows";
      }
    } else if (read.state === "ended") {
      line1 = OUTCOME_WORDS.hasOwnProperty(read.outcome) ? OUTCOME_WORDS[read.outcome] : WORD_SYNC_ENDED;
      line2 = "";
      if (counts !== null && counts.waiting - counts.confirmed > 0) {
        line2 = commas(counts.waiting - counts.confirmed) + " rows kept";
      } else if (counts !== null && read.outcome === "delivered") {
        line2 = WORD_ALL_CONFIRMED;
      }
    }
    setText("label-1", line1);
    setText("label-2", line2);
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
   *
   * US-883-c: sync{} decides the path (away / at home) and, during the drain
   * step, the words; see targetFraction and renderSyncWords.
   */
  function renderStep(step, sync) {
    var read = readSync(sync);
    if (read.kind === "sync" && read.state !== "away") atHome = true;
    drawKept(read);

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

    if (stepName === "drain" && read.kind !== "none") {
      renderSyncWords(read);
    } else {
      setText("label-1", STEP_WORDS.hasOwnProperty(stepName) ? STEP_WORDS[stepName] : WORD_OTHER);
      setText("label-2", stepIndex === null ? WORD_STEPS_NOT_READ : "step " + stepIndex + " of " + stepOf);
    }
    if (stepIndex === null) return;

    var target = targetFraction(read);
    if (target === null) return;
    drawnFraction = Math.max(drawnFraction, target);
    var fill = document.getElementById("bar-fill");
    if (fill) fill.style.width = drawnFraction * 100 + "%";
    if (drawnFraction >= 1) noteFull();    // US-870-c: the close-out's start
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
      renderStep(state.step, state.sync);
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

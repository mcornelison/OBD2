/* ============================================================================
 * File:    stage-scale.js
 * Purpose: US-869-h -- the ONE letterbox for every kiosk page. The UI is authored
 *          at a fixed STAGE_W x STAGE_H design box (#stage) and uniformly scaled
 *          to fill the real panel (the car drives the OSOYOO panel at 1280x720,
 *          wlr-randr MEASURED). LETTERBOX = a single uniform scale of the EXACT
 *          480x320 layout, centred, black bars on the aspect mismatch (CIO-locked
 *          2026-07-21, US-482). No layout reflow -- the box is scaled as one unit.
 *
 *          Lifted out of the dashboard's carousel.js so the boot and shutdown
 *          splash pages use the same formula instead of a second copy. This is
 *          the only source; the deploy copies it into /opt/dashboard AND
 *          /opt/splash (cmp-verified), so neither kit carries its own copy.
 *
 *          The scale is set on load and on resize ONLY -- no timer (C-Atlas-8).
 *          In a browser the API is window.EclipseStageScale; under node (the
 *          desk tests) it is module.exports.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-10-26 -- Sprint 115 US-869-h (lifted from carousel.js, US-482)
 * ==========================================================================*/
(function (global) {
  "use strict";

  var STAGE_W = 480;          // design-box width  (px) -- matches #stage in css
  var STAGE_H = 320;          // design-box height (px) -- matches #stage in css

  // The LARGEST scale that still fits BOTH axes of a (w x h) viewport, so the
  // whole 480x320 UI stays visible + centred with black bars on the mismatch.
  // A degenerate (<=0 / non-finite) viewport falls back to 1 -- a transient 0x0
  // layout pass must never collapse the UI to nothing.
  function computeStageScale(w, h) {
    if (!(w > 0) || !(h > 0) || !isFinite(w) || !isFinite(h)) return 1;
    return Math.min(w / STAGE_W, h / STAGE_H);
  }

  // Write --scale on #stage from the live viewport. The transformed #stage
  // becomes the containing block for its absolute/fixed descendants, so the
  // layout inside it is untouched -- only the outer scale changes. Null-safe:
  // a page with no #stage is left alone.
  function applyStageScale(doc, win) {
    var stage = doc.getElementById("stage");
    if (!stage) return;
    var scale = computeStageScale(win.innerWidth, win.innerHeight);
    stage.style.setProperty("--scale", String(scale));
  }

  // The splash pages' one call: scale now, then again on every viewport change
  // (the panel reporting late at boot, a mode change). Load + resize, no timer.
  function bindStageScale(doc, win) {
    applyStageScale(doc, win);
    win.addEventListener("resize", function () {
      applyStageScale(doc, win);
    });
  }

  var api = {
    STAGE_W: STAGE_W,
    STAGE_H: STAGE_H,
    computeStageScale: computeStageScale,
    applyStageScale: applyStageScale,
    bindStageScale: bindStageScale,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    global.EclipseStageScale = api;
  }
})(typeof window !== "undefined" ? window : globalThis);

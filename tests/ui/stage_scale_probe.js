/* ============================================================================
 * File:    stage_scale_probe.js
 * Purpose: US-869-h render pin -- runs a splash page's letterbox scripts (the
 *          SHIPPED src/pi/ui/stage-scale.js and the page's own inline scripts,
 *          in document order) against the mini-DOM at a given viewport and
 *          prints the resulting element tree. render_harness.py then resolves
 *          styles.css over that tree and the test models the box.
 *
 *          Scripts run with vm.runInThisContext, i.e. as a browser runs a
 *          classic <script>: no `module`, so stage-scale.js takes its browser
 *          path and publishes window.EclipseStageScale. A script that throws is
 *          recorded and the next one still runs, as in a browser.
 *
 *          Timers are COUNTED, never run: the scale is set on load and resize
 *          only (C-Atlas-8), so any timer a letterbox script arms is a defect
 *          the test reports.
 *
 *          Invoked as:  node stage_scale_probe.js <inputJsonPath>
 *          Input:  {tree, viewport: [w, h], scripts: [{path} | {inline}],
 *                   resizeTo: [w, h] | null}
 *                  Viewport values are Number()-ed, so "NaN" / "Infinity"
 *                  reach the page as the non-finite numbers JSON cannot carry.
 *          Output: {tree, errors, timers, resizeListeners} on stdout
 * Author:  Ralph Agent (Rex)
 * Created: 2026-10-26 -- Sprint 115 US-869-h (splash letterbox)
 * ==========================================================================*/
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");
const dom = require(path.resolve(__dirname, "mini_dom.js"));

function main() {
  const input = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));

  const doc = new dom.Document();
  (input.tree || []).forEach(function (spec) {
    dom.buildTree(doc, spec, doc.body);
  });

  const win = {
    innerWidth: Number(input.viewport[0]),
    innerHeight: Number(input.viewport[1]),
    _listeners: {},
    addEventListener: function (type, fn) {
      (this._listeners[type] = this._listeners[type] || []).push(fn);
    },
  };

  let timers = 0;
  function countTimer() {
    timers += 1;
    return timers;
  }
  global.window = win;
  global.document = doc;
  global.setTimeout = countTimer;
  global.setInterval = countTimer;
  global.requestAnimationFrame = countTimer;

  const errors = [];
  (input.scripts || []).forEach(function (script, index) {
    const code =
      script.path !== undefined ? fs.readFileSync(script.path, "utf-8") : script.inline;
    try {
      vm.runInThisContext(code, { filename: script.path || "inline-" + index });
    } catch (e) {
      errors.push(String(e && e.stack ? e.stack : e));
    }
  });

  if (input.resizeTo) {
    win.innerWidth = Number(input.resizeTo[0]);
    win.innerHeight = Number(input.resizeTo[1]);
    (win._listeners.resize || []).forEach(function (fn) {
      fn({ type: "resize" });
    });
  }

  process.stdout.write(
    JSON.stringify({
      tree: dom.serialize(doc.body),
      errors: errors,
      timers: timers,
      resizeListeners: (win._listeners.resize || []).length,
    })
  );
}

main();

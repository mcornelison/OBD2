/* ============================================================================
 * File:    dom_probe.js
 * Purpose: US-499 (S6, F-121) render-regression backstop -- runs the SHIPPED
 *          dashboard carousel.js against the mini-DOM (mini_dom.js) and prints
 *          the resulting element tree as JSON.
 *
 *          This probe deliberately knows NOTHING about CSS. It answers exactly
 *          one question: "after the real browser JS has booted against the real
 *          markup and the given state files, what attributes are on the DOM?"
 *          render_harness.py then resolves the real stylesheet over that tree
 *          and decides what actually has a box. The US-495 defect lived in the
 *          gap between those two answers, so keeping them in separate processes
 *          is the point -- neither can quietly agree with the other.
 *
 *          Contrast with carousel_probe.js (US-429), which calls ONE exported
 *          pure function with a fixture. This probe exercises the DOM-wiring
 *          half of carousel.js -- the half that is invisible to every existing
 *          test, and the half that shipped the bug.
 *
 *          Invoked as:  node dom_probe.js <inputJsonPath>
 *          Input:  {carouselPath, tree, routes, token, autoDim, steps}
 *          Output: {tree, fetches} on stdout
 * Author:  Ralph Agent (Rex)
 * Created: 2026-07-29 -- Sprint 66 US-499 (S6 render-regression backstop)
 * ==========================================================================*/
"use strict";

const fs = require("fs");
const path = require("path");
const dom = require(path.resolve(__dirname, "mini_dom.js"));

async function main() {
  const input = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));

  const doc = new dom.Document();
  // The tree is the BODY's children, so the harness document has exactly the
  // ancestor chain the browser would (body > #screen > #stage > ...). An extra
  // wrapper element would silently change what a descendant/child selector
  // matches, which is the very thing under test.
  const roots = Array.isArray(input.tree) ? input.tree : [input.tree];
  roots.forEach(function (spec) {
    dom.buildTree(doc, spec, doc.body);
  });

  const clock = new dom.Clock();
  const fetches = [];

  const win = {
    innerWidth: input.viewport ? input.viewport[0] : 1920,
    innerHeight: input.viewport ? input.viewport[1] : 1080,
    SPLASH_TOKEN: input.token || "",
    DISPLAY_AUTODIM: input.autoDim === undefined ? "__DISPLAY_AUTODIM__" : input.autoDim,
    addEventListener: function (type, fn) {
      (this._listeners[type] = this._listeners[type] || []).push(fn);
    },
    _listeners: {},
  };

  // The shipped IIFE closes over `window` and reads document/fetch/timers off
  // the global scope, exactly as a browser provides them.
  global.window = win;
  global.document = doc;
  global.fetch = dom.makeFetch(input.routes || {}, fetches);
  global.setTimeout = function (fn) {
    return clock.setTimeout(fn);
  };
  global.clearTimeout = function (id) {
    return clock.clearTimeout(id);
  };
  global.setInterval = function (fn) {
    return clock.setInterval(fn);
  };
  global.clearInterval = function (id) {
    return clock.clearInterval(id);
  };

  // Loading the module IS the boot: readyState is "complete", so carousel.js
  // calls setup() during require, wiring the real DOM and starting the real
  // poll. Nothing in this harness calls setup() on its behalf.
  require(path.resolve(input.carouselPath));

  for (const step of input.steps || [{ flush: 4 }]) {
    if (step.flush) {
      for (let i = 0; i < step.flush; i++) {
        await dom.drainMicrotasks();
        clock.flushRound();
      }
      await dom.drainMicrotasks();
    }
    if (step.click) {
      const el = doc.getElementById(step.click);
      if (!el) throw new Error("no such element to click: #" + step.click);
      el.click();
      await dom.drainMicrotasks();
    }
    if (step.setRoutes) {
      Object.assign(input.routes, step.setRoutes);
    }
    if (step.key) {
      doc.dispatch("keydown", { key: step.key });
      await dom.drainMicrotasks();
    }
  }

  process.stdout.write(
    JSON.stringify({ tree: dom.serialize(doc.body), fetches: fetches })
  );
}

main().then(null, function (err) {
  process.stderr.write(String((err && err.stack) || err));
  process.exit(2);
});

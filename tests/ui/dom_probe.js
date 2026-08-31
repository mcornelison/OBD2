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
 *          Input:  {carouselPath, tree, routes, token, autoDim, nowMs, steps}
 *          Steps:  {flush} {click:<id>} {clickNth:{selector,index}}
 *                  {setRoutes} {key} {advanceMs}
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

  // US-641: an OPTIONAL virtual WALL clock, distinct from the `clock` above --
  // that one owns "which timer callbacks are due", this one owns "what time does
  // the page think it is". Absent (the default) nothing is patched and every
  // pre-existing probe run is byte-for-byte unchanged.
  //
  // WHY IT EXISTS: a freshness window can only be crossed two ways -- move the
  // reading's `ts` back, or move `now` forward. The first REWRITES the state
  // file, which models "the producer wrote an old reading". The behaviour the
  // panel actually has to survive is the other one: the producer STOPPED, so the
  // file is frozen byte-identical and the clock walks past it. Only this makes
  // that testable, and it is the difference between a cold boot that happens to
  // read stale and a live reading going stale UNDER the operator.
  //
  // Only Date.now() is patched, not the `Date` constructor: every freshness
  // verdict in carousel.js resolves from the tick's `nowMs = Date.now()`, so
  // this covers the path under test exactly while leaving `new Date()` (the
  // top-bar clock's boot paint) on real time.
  let virtualNowMs = null;
  if (typeof input.nowMs === "number" && isFinite(input.nowMs)) {
    virtualNowMs = input.nowMs;
    Date.now = function () {
      return virtualNowMs;
    };
  }

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
    // US-641: walk the virtual wall clock forward. Handled BEFORE {flush} so a
    // single {advanceMs, flush} step reads in the order it happens -- time
    // passes, THEN the panel repaints. Refuses rather than silently no-ops when
    // no virtual clock was installed: a staleness test whose clock never moved
    // would still pass on a cold-boot reading and prove nothing.
    if (typeof step.advanceMs === "number") {
      if (virtualNowMs === null) {
        throw new Error("advanceMs requires input.nowMs (no virtual clock installed)");
      }
      virtualNowMs += step.advanceMs;
    }
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
    // US-635: click the Nth element matching a selector. The page dots are
    // BUILT BY carousel.js and carry no id, so `step.click` (getElementById)
    // cannot reach them -- and the dot->card mapping is precisely what the dot
    // count alone cannot witness. Indexed over ALL matches, hidden included, so
    // a test can also dispatch at a dot the gate has taken away and prove the
    // navigation guard refuses it.
    if (step.clickNth) {
      const all = doc.querySelectorAll(step.clickNth.selector);
      const el = all[step.clickNth.index];
      if (!el) {
        throw new Error(
          "no " +
            step.clickNth.selector +
            "[" +
            step.clickNth.index +
            "] to click (" +
            all.length +
            " matched)"
        );
      }
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

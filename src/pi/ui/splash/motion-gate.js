/* ============================================================================
 * File:    motion-gate.js
 * Purpose: The ONE "will this event fire?" helper for the splash pages
 *          (Atlas G2, US-869-d). A page that advances on transitionend or
 *          animationend asks motionGate.willFire(el, kind) first; on false it
 *          advances on the readiness event directly (C-Atlas-6), with no timer.
 *
 *          Why it exists: Chromium fires NO transitionend / animationend when the
 *          computed duration is 0 or animation-name is none -- styles.css
 *          missing, a selector that no longer matches, or reduced motion. A page
 *          that waited for that event would wait forever. Never wait for an
 *          event that will not fire.
 *
 *          Loaded by index.html (and shutdown.html) BEFORE the page poller.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-10-24 -- Sprint 114 US-869-d (boot clocks retired)
 * ==========================================================================*/
(function (global) {
  "use strict";

  // A CSS <time> list ("0.5s, 200ms") has at least one entry above zero.
  function anyPositiveDuration(value) {
    if (typeof value !== "string" || value === "") return false;
    return value.split(",").some(function (part) {
      var t = part.trim();
      var n = parseFloat(t);
      return n > 0 && /m?s$/.test(t);
    });
  }

  // An animation-name list has at least one entry other than `none`.
  function anyAnimationName(value) {
    if (typeof value !== "string" || value === "") return false;
    return value.split(",").some(function (part) {
      var name = part.trim();
      return name !== "" && name !== "none";
    });
  }

  function prefersReducedMotion() {
    if (typeof global.matchMedia !== "function") return false;
    var mq = global.matchMedia("(prefers-reduced-motion: reduce)");
    return !!(mq && mq.matches);
  }

  /**
   * True only when `el`'s computed style will produce the `kind` end event.
   *
   * kind "transition": a transition-duration above 0.
   * kind "animation":  an animation-name other than none AND an
   *                    animation-duration above 0.
   * Always false under prefers-reduced-motion, for an unknown kind, or when the
   * computed style cannot be read -- a false here is never a stall.
   */
  function willFire(el, kind) {
    if (!el || typeof global.getComputedStyle !== "function") return false;
    if (prefersReducedMotion()) return false;
    var cs = global.getComputedStyle(el);
    if (!cs) return false;
    if (kind === "transition") return anyPositiveDuration(cs.transitionDuration);
    if (kind === "animation") {
      return anyAnimationName(cs.animationName) && anyPositiveDuration(cs.animationDuration);
    }
    return false;
  }

  global.motionGate = { willFire: willFire };
})(window);

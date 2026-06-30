/* ============================================================================
 * File:    carousel.js
 * Purpose: US-399 carousel shell (F-092). Swipe-nav between cards + page dots +
 *          a persistent top bar, plus the honest-instrument availability poll
 *          that drives each card to `unavailable` when its state file is
 *          missing/malformed. The dashboard is a PURE CONSUMER of the state
 *          files (specs/ssot-design-pattern.md): it NEVER polls hardware. The
 *          per-card field rendering (System Status / Battery Health) is US-400 /
 *          US-401; this shell only decides card AVAILABILITY + carousel motion.
 *
 *          The pure carousel logic (clampIndex / nextIndex / swipeDirection /
 *          cardAvailability) is exported under module.exports so it can be unit
 *          tested in node with no DOM (S-2). The DOM wiring runs only in the
 *          browser (guarded on `typeof document`).
 * Author:  Ralph Agent (Rex)
 * Created: 2026-06-30 -- Sprint 49 US-399 (carousel shell)
 * ==========================================================================*/
(function (global) {
  "use strict";

  var POLL_MS = 250;          // 4 Hz tmpfs read (matches the splash cadence)
  var SWIPE_THRESHOLD_PX = 40; // min horizontal travel to count as a swipe

  // -------------------------------------------------------------------------
  // Pure carousel logic -- no DOM, node-testable (S-2).
  // -------------------------------------------------------------------------

  function clampIndex(i, count) {
    if (count <= 0) return 0;
    if (i < 0) return 0;
    if (i >= count) return count - 1;
    return i;
  }

  // dir > 0 -> next card; dir < 0 -> previous; 0 -> stay. Clamped at the ends
  // (no wrap -- a kiosk that silently wraps past the last card is disorienting).
  function nextIndex(current, dir, count) {
    var step = dir > 0 ? 1 : dir < 0 ? -1 : 0;
    return clampIndex(current + step, count);
  }

  // dx = endX - startX. A swipe LEFT (dx < 0) advances to the NEXT card (+1);
  // a swipe RIGHT (dx > 0) goes to the PREVIOUS card (-1). Travel below the
  // threshold is a tap, not a swipe (0).
  function swipeDirection(dx, threshold) {
    var t = threshold == null ? SWIPE_THRESHOLD_PX : threshold;
    if (Math.abs(dx) < t) return 0;
    return dx < 0 ? 1 : -1;
  }

  // Honest-instrument classifier: the shell decides only AVAILABILITY. A null
  // (missing file / HTTP error) or a non-object payload is `unavailable`; a
  // plain object is `available` (the per-card story renders its fields).
  function cardAvailability(raw) {
    if (raw === null || typeof raw !== "object" || Array.isArray(raw)) {
      return "unavailable";
    }
    return "available";
  }

  // -------------------------------------------------------------------------
  // US-400 System Status card -- pure render logic, node-testable (S-3/I-3/
  // I-4/F-1). The card is a verbatim consumer of the `system-status` emitter
  // (Atlas A-3 schema): it maps the state to honest tiles + top-bar glyph
  // states. The cardinal honest-instrument rule (F-1): a level/glyph is ONLY
  // `ok` (green) when the underlying state is genuinely good -- a down /
  // reconnecting / stale / battery state is amber/down/neutral, never green.
  // -------------------------------------------------------------------------

  function isObj(x) {
    return x !== null && typeof x === "object" && !Array.isArray(x);
  }

  function seenDetail(s) {
    return s == null ? "" : "seen " + s + "s ago";
  }

  // OBD link tile: linked -> ok; reconnecting -> amber (I-033 visibility, the
  // operator SEES the retry); down -> red; missing/unknown -> unavailable.
  function obdLinkTile(o) {
    if (!isObj(o)) {
      return { label: "OBD LINK", value: "—", detail: "unavailable", level: "unavailable" };
    }
    var seen = seenDetail(o.lastSeenS);
    if (o.state === "linked") {
      return { label: "OBD LINK", value: "LINKED", detail: seen, level: "ok" };
    }
    if (o.state === "reconnecting") {
      var d = "retry " + (o.retries == null ? 0 : o.retries);
      if (seen) d += " · " + seen;
      return { label: "OBD LINK", value: "RECONNECTING", detail: d, level: "amber" };
    }
    if (o.state === "down") {
      return { label: "OBD LINK", value: "DOWN", detail: seen || "no signal", level: "down" };
    }
    return { label: "OBD LINK", value: "—", detail: "unavailable", level: "unavailable" };
  }

  // Sync tile: stale-while-driving -> amber (I-4); otherwise ok. The emitter
  // owns the stale DECISION (no green-when-broken); the tile renders it.
  function syncTile(s) {
    if (!isObj(s)) {
      return { label: "SYNC", value: "—", detail: "unavailable", level: "unavailable" };
    }
    var pending = s.pending == null ? 0 : s.pending;
    var detail = (s.rows == null ? 0 : s.rows) + " rows · " + pending + " pending";
    if (s.stale === true) {
      return { label: "SYNC", value: "STALE", detail: detail, level: "amber" };
    }
    var last = s.lastOkTs == null ? "never" : "last " + s.lastOkTs;
    return { label: "SYNC", value: "OK", detail: last + " · " + detail, level: "ok" };
  }

  // Power tile: running on battery (UPS backup) -> amber; external -> ok.
  function powerTile(p) {
    if (!isObj(p)) {
      return { label: "POWER", value: "—", detail: "unavailable", level: "unavailable" };
    }
    var mode = p.mode === "wall" ? "wall" : "car";
    if (p.source === "battery") {
      return { label: "POWER", value: "BATTERY", detail: mode + " · on UPS", level: "amber" };
    }
    if (p.source === "external") {
      return { label: "POWER", value: mode.toUpperCase(), detail: "external", level: "ok" };
    }
    return { label: "POWER", value: "—", detail: "unavailable", level: "unavailable" };
  }

  // Drive tile: recording -> active (ok); idle -> neutral (no warning, no green).
  function driveTile(d) {
    if (!isObj(d)) {
      return { label: "DRIVE", value: "—", detail: "unavailable", level: "unavailable" };
    }
    if (d.state === "recording") {
      var id = d.driveId == null ? "?" : d.driveId;
      return { label: "DRIVE", value: "REC", detail: "drive " + id, level: "ok" };
    }
    if (d.state === "idle") {
      return { label: "DRIVE", value: "IDLE", detail: "not recording", level: "neutral" };
    }
    return { label: "DRIVE", value: "—", detail: "unavailable", level: "unavailable" };
  }

  // Top-bar glyph states (bound to data-state CSS in dashboard.css).
  function btGlyphState(o) {
    if (!isObj(o)) return "neutral";
    if (o.state === "linked") return "ok";
    if (o.state === "reconnecting") return "amber";
    if (o.state === "down") return "down";
    return "neutral";
  }
  function syncGlyphState(s) {
    if (!isObj(s)) return "neutral";
    return s.stale === true ? "amber" : "ok";
  }
  function powerGlyphState(p) {
    if (!isObj(p)) return "neutral";
    if (p.source === "battery") return "amber";
    if (p.source === "external") return "ok";
    return "neutral";
  }

  // The full structured view consumed by the DOM renderer + the node tests.
  // Non-object payload -> null (the shell renders `unavailable`).
  function systemStatusView(data) {
    if (!isObj(data)) return null;
    return {
      tiles: {
        obdLink: obdLinkTile(data.obdLink),
        sync: syncTile(data.sync),
        power: powerTile(data.power),
        drive: driveTile(data.drive),
      },
      glyphs: {
        bt: btGlyphState(data.obdLink),
        sync: syncGlyphState(data.sync),
        power: powerGlyphState(data.power),
      },
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  var api = {
    clampIndex: clampIndex,
    nextIndex: nextIndex,
    swipeDirection: swipeDirection,
    cardAvailability: cardAvailability,
    obdLinkTile: obdLinkTile,
    syncTile: syncTile,
    powerTile: powerTile,
    driveTile: driveTile,
    btGlyphState: btGlyphState,
    syncGlyphState: syncGlyphState,
    powerGlyphState: powerGlyphState,
    systemStatusView: systemStatusView,
    POLL_MS: POLL_MS,
    SWIPE_THRESHOLD_PX: SWIPE_THRESHOLD_PX,
  };

  // -------------------------------------------------------------------------
  // DOM wiring -- browser only.
  // -------------------------------------------------------------------------

  if (typeof document !== "undefined") {
    var token = global.SPLASH_TOKEN || "";

    // --- US-400 System Status DOM render (browser only) ---------------------

    // Render one tile into a parent element (label + prominent value + detail).
    // The level drives the colour via [data-level] CSS -- a degraded tile is
    // never green (F-1). Built with textContent (no innerHTML) so emitter values
    // render verbatim, never as markup.
    function appendTile(parent, tile) {
      var el = document.createElement("div");
      el.className = "tile";
      el.setAttribute("data-level", tile.level);
      var label = document.createElement("span");
      label.className = "tile-label";
      label.textContent = tile.label;
      var value = document.createElement("span");
      value.className = "tile-value";
      value.textContent = tile.value;
      var detail = document.createElement("span");
      detail.className = "tile-detail";
      detail.textContent = tile.detail;
      el.appendChild(label);
      el.appendChild(value);
      el.appendChild(detail);
      parent.appendChild(el);
    }

    function renderSystemStatusCard(card, view, glyphEls) {
      var body = card.querySelector(".card-body");
      if (body) {
        body.textContent = "";
        appendTile(body, view.tiles.obdLink);
        appendTile(body, view.tiles.sync);
        appendTile(body, view.tiles.power);
        appendTile(body, view.tiles.drive);
      }
      if (glyphEls.bt) glyphEls.bt.setAttribute("data-state", view.glyphs.bt);
      if (glyphEls.sync) glyphEls.sync.setAttribute("data-state", view.glyphs.sync);
      if (glyphEls.power) glyphEls.power.setAttribute("data-state", view.glyphs.power);
    }

    // Honest-instrument reset: a missing/malformed system-status file returns the
    // glyphs to neutral so a prior good read can't linger green (no stale-green).
    function resetSystemGlyphs(glyphEls) {
      if (glyphEls.bt) glyphEls.bt.setAttribute("data-state", "neutral");
      if (glyphEls.sync) glyphEls.sync.setAttribute("data-state", "neutral");
      if (glyphEls.power) glyphEls.power.setAttribute("data-state", "neutral");
    }

    var setup = function () {
      var track = document.getElementById("track");
      var dotsNav = document.getElementById("dots");
      var cards = Array.prototype.slice.call(document.querySelectorAll(".card"));
      var count = cards.length;
      var current = 0;
      var glyphEls = {
        bt: document.getElementById("glyph-bt"),
        sync: document.getElementById("glyph-sync"),
        power: document.getElementById("glyph-power"),
      };

      // Build one page dot per card (>=40px touch target via .tap-target CSS).
      var dots = [];
      for (var i = 0; i < count; i++) {
        var dot = document.createElement("button");
        dot.className = "dot tap-target";
        dot.setAttribute("aria-label", "card " + (i + 1));
        (function (idx) {
          dot.addEventListener("click", function () { goTo(idx); });
        })(i);
        dotsNav.appendChild(dot);
        dots.push(dot);
      }

      function render() {
        if (track) track.style.transform = "translateX(" + (-current * 100) + "%)";
        for (var d = 0; d < dots.length; d++) {
          dots[d].classList.toggle("active", d === current);
        }
      }

      function goTo(idx) {
        current = clampIndex(idx, count);
        render();
      }

      function move(dir) {
        current = nextIndex(current, dir, count);
        render();
      }

      // Pointer-driven swipe (covers touch + mouse on the kiosk). Vertical drag
      // is ignored (touch-action: pan-y) so the panel can still scroll a card.
      var startX = null;
      var startY = null;
      if (track) {
        track.addEventListener("pointerdown", function (e) {
          startX = e.clientX; startY = e.clientY;
        });
        track.addEventListener("pointerup", function (e) {
          if (startX === null) return;
          var dx = e.clientX - startX;
          var dy = e.clientY - startY;
          startX = null; startY = null;
          if (Math.abs(dx) < Math.abs(dy)) return; // vertical gesture, ignore
          var dir = swipeDirection(dx, SWIPE_THRESHOLD_PX);
          if (dir !== 0) move(dir);
        });
      }

      // Keyboard arrows (bench/dev affordance; harmless on a touch panel).
      document.addEventListener("keydown", function (e) {
        if (e.key === "ArrowLeft") move(-1);
        else if (e.key === "ArrowRight") move(1);
      });

      render();
      startAvailabilityPoll(cards, glyphEls);
    };

    // Honest-instrument poll: fetch each card's state file; missing/malformed ->
    // `unavailable` (never a crash, never green-when-broken). The shell sets the
    // availability class; the per-card renderer (US-400 system-status; US-401
    // battery-health) paints the fields on top when available.
    function startAvailabilityPoll(cards, glyphEls) {
      async function fetchState(name) {
        try {
          var r = await fetch("/" + name, {
            cache: "no-store",
            headers: token ? { "X-Splash-Token": token } : {},
          });
          if (!r.ok) return null;
          return await r.json();
        } catch (e) {
          return null;
        }
      }

      async function tick() {
        for (var c = 0; c < cards.length; c++) {
          var card = cards[c];
          var name = card.getAttribute("data-state");
          if (!name) continue;
          var data = await fetchState(name);
          var avail = cardAvailability(data);
          card.classList.toggle("unavailable", avail === "unavailable");
          if (avail === "unavailable") {
            var body = card.querySelector(".card-body");
            if (body) body.textContent = "unavailable";
            if (name === "system-status") resetSystemGlyphs(glyphEls);
            continue;
          }
          // available -> the per-card renderer owns the body.
          if (name === "system-status") {
            renderSystemStatusCard(card, systemStatusView(data), glyphEls);
          }
          // battery-health -> US-401.
        }
        setTimeout(tick, POLL_MS);
      }
      tick();
    }

    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", setup);
    } else {
      setup();
    }
  }

  // -------------------------------------------------------------------------
  // Export (node unit tests) / attach (browser global).
  // -------------------------------------------------------------------------
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  } else {
    global.Carousel = api;
  }
})(typeof window !== "undefined" ? window : globalThis);

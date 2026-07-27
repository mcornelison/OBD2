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

  // US-482 letterbox scaling: the UI is authored at a fixed STAGE_W x STAGE_H
  // design box (#stage) and uniformly scaled to fill the real panel (device
  // resolution varies -- the Pi outputs 1080p). LETTERBOX = a single uniform
  // scale of the EXACT 480x320 layout, centered, with black bars on the aspect
  // mismatch (CIO-locked 2026-07-21). No layout reflow -- scaled as one unit.
  var STAGE_W = 480;          // design-box width  (px) -- matches #stage in css
  var STAGE_H = 320;          // design-box height (px) -- matches #stage in css

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

  // US-482 uniform letterbox scale for the fixed STAGE_W x STAGE_H design box in
  // a viewport of (w x h): the LARGEST scale that still fits BOTH axes, so the
  // whole 480x320 UI stays visible + centered with black bars on the mismatch.
  // A degenerate (<=0 / non-finite) viewport falls back to 1 -- a transient 0x0
  // layout pass must never collapse the UI to nothing.
  function computeStageScale(w, h) {
    if (!(w > 0) || !(h > 0)) return 1;
    return Math.min(w / STAGE_W, h / STAGE_H);
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

  // US-429 honest-availability: read the one-truth-per-source availability fact
  // (`state.source.<x>`) the emitter wrote. An ABSENT source block is treated as
  // available (backward compatible with pre-US-429 states); only an explicit
  // `available: false` is unavailable. The reason (why) travels with it.
  function sourceUnavailable(data, name) {
    return (
      isObj(data) &&
      isObj(data.source) &&
      isObj(data.source[name]) &&
      data.source[name].available === false
    );
  }

  function sourceReason(data, name) {
    if (isObj(data) && isObj(data.source) && isObj(data.source[name])) {
      var r = data.source[name].reason;
      if (typeof r === "string" && r) return r;
    }
    return "unavailable";
  }

  // A typed-NA tile: value "NA", the reason as the detail, `unavailable` level.
  // NA is rendered text derived from a NULL+reason -- NEVER a numeric sentinel.
  function naTile(label, reason) {
    return { label: label, value: "NA", detail: reason, level: "unavailable" };
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
    // Power-mode SSOT (US-421 / BL-014): honour car/wall exactly; anything
    // else -- absent, stale, invalid -- is `unknown`, never a confident CAR
    // (honest-instrument). `unknown` renders lowercase so a real known mode is
    // visibly the confident one (CAR/WALL).
    var mode = p.mode === "car" || p.mode === "wall" ? p.mode : "unknown";
    var modeBadge = mode === "unknown" ? "unknown" : mode.toUpperCase();
    if (p.source === "battery") {
      return { label: "POWER", value: "BATTERY", detail: mode + " · on UPS", level: "amber" };
    }
    if (p.source === "external") {
      return { label: "POWER", value: modeBadge, detail: "external", level: "ok" };
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

  // -------------------------------------------------------------------------
  // US-489 (Iris polish P-1) -- the one-glance SUMMARY line. A lossy
  // compression of the four tiles, which makes it exactly the place a
  // "green when broken" lie would enter, so honest-instrument F-1 is restated
  // here at the CARD level: the line is `ok` ONLY when every source is
  // genuinely good. Presentation-only -- it reads the tiles the card already
  // renders, never a second read of the state.
  // -------------------------------------------------------------------------

  // Display order == grid order, so "the worst source" is always named in a
  // stable, predictable place.
  var SYS_TILE_ORDER = ["obdLink", "sync", "power", "drive"];

  // Severity rank over the tile-level vocabulary. Three buckets, not two:
  //   ok            -- genuinely good.
  //   neutral       -- nominal but inactive. DRIVE=IDLE is the only neutral
  //                    this card produces and it means "not recording", NOT
  //                    "broken"; counting it as a fault would make green
  //                    unreachable in the commonest state (key on, no drive
  //                    started), which is its own dishonesty -- crying wolf.
  //   unavailable   -- a known-UNKNOWN. Blocks green (never claim OK over a
  //                    source we cannot read) without raising an alarm.
  //   amber / down  -- the only ISSUES.
  var SYS_LEVEL_RANK = { ok: 0, neutral: 1, unavailable: 2, amber: 3, down: 4 };
  var SYS_ISSUE_RANK = SYS_LEVEL_RANK.amber;

  // A level this mapper has not been taught resolves to `unavailable`, NEVER to
  // ok -- a future tile level must not be able to paint the card green by
  // default.
  function sysLevelRank(level) {
    return Object.prototype.hasOwnProperty.call(SYS_LEVEL_RANK, level)
      ? SYS_LEVEL_RANK[level]
      : SYS_LEVEL_RANK.unavailable;
  }

  function sysNoStateSummary() {
    return {
      text: "SYSTEM · UNAVAILABLE",
      detail: "no system state",
      level: "unavailable",
      issues: 0,
    };
  }

  // Summarise the four rendered tiles. The ISSUE COUNT is the glanceable fact;
  // the worst source is NAMED in the detail so the line says what to look at
  // without the operator reading all four tiles.
  function systemSummary(tiles) {
    if (!isObj(tiles)) return sysNoStateSummary();
    var worst = null;
    var worstRank = -1;
    var issues = 0;
    var unknowns = 0;
    for (var i = 0; i < SYS_TILE_ORDER.length; i++) {
      var tile = tiles[SYS_TILE_ORDER[i]];
      if (!isObj(tile)) continue;
      var rank = sysLevelRank(tile.level);
      if (rank >= SYS_ISSUE_RANK) issues++;
      else if (rank === SYS_LEVEL_RANK.unavailable) unknowns++;
      if (rank > worstRank) {
        worstRank = rank;
        worst = tile;
      }
    }
    if (worst === null) return sysNoStateSummary();
    var named = worst.label + " · " + worst.value;
    if (issues > 0) {
      // `worst` carries the highest rank, so with any issue present it IS an
      // issue tile -- its level is amber/down and drives the headline hue.
      return {
        text: "SYSTEM · " + issues + (issues === 1 ? " ISSUE" : " ISSUES"),
        detail: named,
        level: worst.level,
        issues: issues,
      };
    }
    if (unknowns > 0) {
      return {
        text: "SYSTEM · " + unknowns + " UNAVAILABLE",
        detail: named,
        level: "unavailable",
        issues: 0,
      };
    }
    return { text: "SYSTEM · OK", detail: "", level: "ok", issues: 0 };
  }

  // The full structured view consumed by the DOM renderer + the node tests.
  // Non-object payload -> null (the shell renders `unavailable`).
  function systemStatusView(data) {
    if (!isObj(data)) return null;
    // US-429: the OBD source owns the OBD-link tile + glyph. When the source is
    // unavailable (car off / wall power), render a typed NA ("OBD: off") rather
    // than a fabricated or stale link state -- sync/power/drive are their own
    // sources and stay honest independently (one truth per SOURCE).
    var obdOff = sourceUnavailable(data, "obd");
    var obdTile = obdOff
      ? naTile("OBD LINK", sourceReason(data, "obd"))
      : obdLinkTile(data.obdLink);
    var tiles = {
      obdLink: obdTile,
      sync: syncTile(data.sync),
      power: powerTile(data.power),
      drive: driveTile(data.drive),
    };
    return {
      // US-489: derived from the SAME tiles rendered below, so the headline can
      // never contradict the grid it summarises.
      summary: systemSummary(tiles),
      tiles: tiles,
      glyphs: {
        bt: obdOff ? "neutral" : btGlyphState(data.obdLink),
        sync: syncGlyphState(data.sync),
        power: powerGlyphState(data.power),
      },
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  // -------------------------------------------------------------------------
  // US-401 Battery Health card -- pure render logic, node-testable (F-8/F-9/
  // F-10/F-11/F-2). The card is an HONEST consumer of the `battery-health`
  // emitter (Atlas A-3 schema) for the Pi UPS LiPo cell -- NEVER the car
  // battery (F-11). The two render-breaking traps are locked here:
  //   F-8  the SoC percent is shown ONLY when `soc` is a real number; a null
  //        soc omits the percent and shows volts -- a voltage is NEVER painted
  //        as a percent.
  //   F-9  a GREEN verdict ALWAYS carries "last health check · <date> (<age>)"
  //        (computed from ts - lastHealthCheckTs, both in the state file) so a
  //        month-old reading is never mistaken for live.
  // The drain ladder DOM is present ONLY when `draining === true` (F-2 / A-6).
  // -------------------------------------------------------------------------

  var BATTERY_LABEL = "Pi UPS battery"; // F-11: never "vehicle/car battery".
  var MS_PER_DAY = 86400000;

  // Map a Spool health verdict tier -> a display level (the card never decides
  // severity; green -> ok, attn -> amber, low -> down, unknown -> unavailable).
  function healthLevel(h) {
    if (h === "green") return "ok";
    if (h === "attn") return "amber";
    if (h === "low") return "down";
    return "unavailable";
  }

  function healthValue(h) {
    if (h === "green") return "HEALTHY";
    if (h === "attn") return "ATTENTION";
    if (h === "low") return "LOW";
    return "—";
  }

  // The date portion (YYYY-MM-DD) of an ISO instant, or null.
  function isoDate(ts) {
    if (typeof ts !== "string") return null;
    var i = ts.indexOf("T");
    return i > 0 ? ts.slice(0, i) : ts;
  }

  // Whole-day age between two ISO instants (now - then). Null if either is not
  // parseable -- we never assert an age we cannot compute.
  function ageDays(nowTs, thenTs) {
    if (typeof nowTs !== "string" || typeof thenTs !== "string") return null;
    var now = Date.parse(nowTs);
    var then = Date.parse(thenTs);
    if (isNaN(now) || isNaN(then)) return null;
    return Math.floor((now - then) / MS_PER_DAY);
  }

  function ageText(days) {
    if (days == null) return "age unknown";
    if (days <= 0) return "today";
    if (days === 1) return "1 day ago";
    return days + " days ago";
  }

  // The stale-green guard line (F-9). ALWAYS produced so a GREEN verdict can
  // never be shown without its data-age. A missing check -> "never".
  function healthCheckLine(d) {
    var date = isoDate(d.lastHealthCheckTs);
    if (date == null) {
      return { date: null, ageDays: null, label: "last health check · never" };
    }
    var age = ageDays(d.ts, d.lastHealthCheckTs);
    return {
      date: date,
      ageDays: age,
      label: "last health check · " + date + " (" + ageText(age) + ")",
    };
  }

  // VCELL tile -- authoritative volts, ALWAYS rendered in volts, never percent.
  function vcellTile(d) {
    if (typeof d.vcellV !== "number") {
      return { label: "CELL", value: "—", detail: "unavailable", level: "unavailable" };
    }
    return {
      label: "CELL",
      value: d.vcellV.toFixed(2) + " V",
      detail: BATTERY_LABEL,
      level: "neutral",
    };
  }

  // SoC tile (F-8) -- the percent renders ONLY when `soc` is a real number from
  // the MAX17048 register; null -> omit the percent (shown:false), the card
  // falls back to volts. A voltage is NEVER rendered as a percent.
  function socTile(d) {
    if (typeof d.soc !== "number") {
      return {
        label: "CHARGE",
        value: "—",
        detail: "% unavailable · see volts",
        level: "unavailable",
        shown: false,
      };
    }
    return {
      label: "CHARGE",
      value: d.soc + "%",
      detail: d.socCalibrated === true ? "register" : "(uncalibrated)",
      level: "neutral",
      shown: true,
    };
  }

  // Temp tile (F-10) -- a null reading is "not captured", never a fabricated
  // number.
  function tempTile(d) {
    if (typeof d.ambientTempC !== "number") {
      return { label: "TEMP", value: "not captured", detail: "", level: "neutral" };
    }
    return { label: "TEMP", value: d.ambientTempC + " °C", detail: "", level: "neutral" };
  }

  // Failsafe ladder view (F-2 / A-6) -- present ONLY when draining is true. The
  // runtime minutes render ONLY when the power tier supplied a real number
  // (Spool S-2); otherwise the failsafe shows stage + volts, never a fabricated
  // estimate. draining:false -> null (the DOM renderer draws no ladder).
  function ladderView(d) {
    if (d.draining !== true) return null;
    var l = isObj(d.ladder) ? d.ladder : {};
    var rt = typeof l.runtimeRemainingS === "number" ? l.runtimeRemainingS : null;
    return {
      stage: typeof l.stage === "string" ? l.stage : "DRAINING",
      thresholds: isObj(l.thresholds) ? l.thresholds : null,
      runtimeRemainingS: rt,
    };
  }

  // The full structured view consumed by the DOM renderer + the node tests.
  // Non-object payload -> null (the shell renders `unavailable`).
  function batteryHealthView(data) {
    if (!isObj(data)) return null;
    // US-429: the UPS/MAX17048 is a single source -- when it is unavailable the
    // WHOLE card is a typed NA ("gauge unreadable"), never a blank or a stale
    // last-real cell reading.
    if (sourceUnavailable(data, "ups")) {
      return {
        label: BATTERY_LABEL,
        unavailable: true,
        reason: sourceReason(data, "ups"),
        ts: typeof data.ts === "string" ? data.ts : null,
      };
    }
    return {
      label: BATTERY_LABEL,
      unavailable: false,
      health: {
        label: "HEALTH",
        value: healthValue(data.health),
        detail: healthCheckLine(data).label,
        level: healthLevel(data.health),
      },
      vcell: vcellTile(data),
      soc: socTile(data),
      temp: tempTile(data),
      healthCheck: healthCheckLine(data),
      ladder: ladderView(data),
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  // -------------------------------------------------------------------------
  // US-420 LTFT Trend card -- pure render logic, node-testable (F-096). Long-
  // Term Fuel Trim is a MULTI-DRIVE signal: a healthy tune migrates the trim
  // TOWARD 0, drift beyond +/-10% is a fault. The `ltft-trend` emitter is the
  // SSOT that CLASSIFIES the drift (ok/amber/down) + the insufficient guard;
  // this view only maps the verdict -> a tile level + bar colours, it never
  // classifies. Honest-instrument (defense-in-depth): an insufficient trend is
  // forced to a non-green headline HERE too, so a mislabeled state can't paint
  // a confident green off too little data.
  // -------------------------------------------------------------------------

  // Signed percent to 2 dp (e.g. -6.25% / +2.10%); a non-number -> "--".
  function fmtLtftPct(n) {
    if (typeof n !== "number" || !isFinite(n)) return "--";
    return (n > 0 ? "+" : "") + n.toFixed(2) + "%";
  }

  var LTFT_TREND_TEXT = {
    improving: "trend: migrating toward 0",
    worsening: "trend: drifting from 0",
    stable: "trend: stable",
  };

  function ltftPointView(p) {
    return {
      driveId: typeof p.driveId === "number" ? p.driveId : null,
      value: fmtLtftPct(p.ltftAvg),
      level: typeof p.level === "string" ? p.level : "unavailable",
    };
  }

  function ltftTrendView(data) {
    if (!isObj(data)) return null;
    var pts = Array.isArray(data.points) ? data.points.filter(isObj) : [];
    // Sufficient ONLY when the emitter says so AND real points exist.
    var sufficient = data.sufficient === true && pts.length > 0;
    var current = isObj(data.current) ? data.current : null;
    // The headline verdict: the emitter's level when sufficient, else forced to
    // `insufficient` (never inherits ok/green off too little data).
    var headLevel = sufficient
      ? (typeof data.level === "string" ? data.level : "unavailable")
      : "insufficient";
    var trendKey = typeof data.trend === "string" ? data.trend : null;
    var minDrives = typeof data.minDrives === "number" ? data.minDrives : 2;
    var detail = sufficient
      ? (trendKey && LTFT_TREND_TEXT[trendKey] ? LTFT_TREND_TEXT[trendKey] : "")
      : "need " + minDrives + "+ drives (" + pts.length + " captured)";
    return {
      label: "LTFT (bank 1)",
      sufficient: sufficient,
      headline: {
        label: "LTFT · current drift",
        value: sufficient && current ? fmtLtftPct(current.ltftAvg) : "insufficient data",
        detail: detail,
        level: headLevel,
      },
      trend: trendKey,
      points: pts.map(ltftPointView),
      ts: typeof data.ts === "string" ? data.ts : null,
    };
  }

  // -------------------------------------------------------------------------
  // US-403 System Setup menu -- pure, node-testable logic (D-6/D-7/A-7/A-8).
  // The menu is reachable by a deliberate ~5s long-press (a filling ring; an
  // early release cancels) OR the top-bar `⋮`. Service control is on an
  // INSTALL-FIXED allow-list that MIRRORS service_control.py + the 51- polkit
  // rule; `eclipse-powerwatch` (the safe-shutdown guard) is RESTART-ONLY. The
  // kiosk is unprivileged -- the action POST is authorized by polkit, and the
  // server re-checks this allow-list (defense-in-depth), so a UI bug can never
  // drive an off-list action.
  // -------------------------------------------------------------------------

  var LONG_PRESS_MS = 5000;     // sustained hold to open the menu (D-6)
  var LONG_PRESS_ARM_MS = 600;  // hold before the ring starts showing
  var LONG_PRESS_MOVE_PX = 10;  // movement above this = a swipe/scroll, cancel

  // Allow-list mirror (service_control.SERVICE_ALLOWLIST + the 51- polkit rule).
  var SERVICE_ALLOWLIST = {
    "eclipse-obd.service": ["start", "stop", "restart"],
    "eclipse-sync.service": ["start", "stop", "restart"],
    "eclipse-powerwatch.service": ["restart"],
    "eclipse-dashboard.service": ["stop", "restart"],
  };

  // The OBD-II service rows shown in the menu (D-6). powerwatch carries no Stop
  // (canStop:false) because stopping the safe-shutdown guard could leave the Pi
  // unprotected on key-off (D-7 / F-7 / I-10).
  function serviceMenuItems() {
    return [
      { unit: "eclipse-obd.service", label: "eclipse-obd", sub: "data capture",
        canStop: true, canRestart: true },
      { unit: "eclipse-sync.service", label: "eclipse-sync", sub: "server upload",
        canStop: true, canRestart: true },
      { unit: "eclipse-powerwatch.service", label: "eclipse-powerwatch",
        sub: "safe-shutdown guard", canStop: false, canRestart: true },
    ];
  }

  function uiIsAllowed(unit, verb) {
    var verbs = SERVICE_ALLOWLIST[unit];
    return !!verbs && verbs.indexOf(verb) !== -1;
  }

  // Consequential actions confirm before acting (Stop, and Exit which is a
  // dashboard Stop); Restart self-recovers and acts directly. No single tap
  // performs a consequential action (F-6: the menu itself is behind long-press).
  function requiresConfirm(verb) {
    return verb === "stop";
  }

  // Build a validated action request, or null if the UI allow-list forbids it
  // (the server re-checks regardless). Carries the confirm flag for the DOM.
  function actionRequest(unit, verb) {
    if (!uiIsAllowed(unit, verb)) return null;
    return { unit: unit, verb: verb, confirm: requiresConfirm(verb) };
  }

  // Long-press ring fill fraction 0..1 (clamped). holdMs defaults to the full
  // open threshold.
  function longPressProgress(elapsedMs, holdMs) {
    var hold = holdMs == null ? LONG_PRESS_MS : holdMs;
    if (hold <= 0) return 1;
    var p = elapsedMs / hold;
    if (p < 0) return 0;
    if (p > 1) return 1;
    return p;
  }

  function isLongPressComplete(elapsedMs, holdMs) {
    var hold = holdMs == null ? LONG_PRESS_MS : holdMs;
    return elapsedMs >= hold;
  }

  // Movement beyond the threshold means the gesture is a swipe/scroll, not a
  // press -> cancel the long-press.
  function exceedsMoveCancel(dx, dy, threshold) {
    var t = threshold == null ? LONG_PRESS_MOVE_PX : threshold;
    return Math.sqrt(dx * dx + dy * dy) > t;
  }

  // US-490 context-aware menu access (Iris P-2, CIO-locked Option C). The two
  // paths into the menu carry DIFFERENT intent, so they get different rules:
  //
  //   tapVisible -- the top-bar `⋮` is a SINGLE tap away from a service stop /
  //     Exit UI, so it is offered only while the emitter says parked. Hidden
  //     while driving, and hidden whenever "am I driving?" is UNREADABLE:
  //     carouselIdle already fails closed to not-idle, so an absent, malformed
  //     or idle-less payload hides the affordance rather than guessing a calm
  //     parked state. (Reads the `idle` SSOT boolean -- never re-derived from
  //     the drive-state string; Atlas idle-SSOT b.)
  //   longPress -- the ~5s hold is the DELIBERATE override and is state-blind
  //     on purpose. It is what makes hiding the `⋮` safe: fail-closed can never
  //     strand the operator, and driving is the state where they may most need
  //     to stop a misbehaving service.
  //
  // `carouselIdle` is declared further down this IIFE (with the idle-card
  // logic it belongs to) -- function declarations hoist, so this policy stays
  // next to the menu it governs.
  function menuAccess(systemStatusData) {
    return {
      tapVisible: carouselIdle(systemStatusData),
      longPress: true,
    };
  }

  // -------------------------------------------------------------------------
  // US-405 DTC takeover + ribbon -- pure, node-testable logic (S-1/S-2/R-2).
  // The display is a PURE CONSUMER of the `dtc` state (severity classified
  // upstream from Spool's table -- the Pi never decides it). The takeover fires
  // ONLY on a NEW code (`newSinceTs`), one at a time (highest severity = hero,
  // the rest fold into "+N more"); after Acknowledge/Dismiss a persistent ribbon
  // carries the alert on every card. `na` (auto-trans on this manual car) is a
  // quiet disposition -- never a takeover, never a ribbon (design §4/§5.2).
  // -------------------------------------------------------------------------

  // Severity ordering (worst-first). `na` is not an alert; `unknown` is a real
  // uncurated code (ranks below the classified tiers but still alerts honestly).
  var DTC_SEVERITY_RANK = { stop: 3, watch: 2, minor: 1, unknown: 0 };

  // Per-severity takeover styling. The display maps a tier -> color + directive
  // + dismiss behavior; it never classifies. US-484-b: STOP binds the STATE-
  // ALARM `--critical-red`, never a brand red -- if the brand mark and the
  // pull-over alarm are the same red the driver cannot tell them apart (Spool
  // 6d ch.2). The colour is only the 3rd reinforcement; dashboard.css carries
  // STOP by area + motion + text on a near-black field.
  // STOP has NO plain dismiss -- only
  // "Acknowledge" (which drops to the ribbon) so a misfire is never dismissed-
  // and-forgotten, yet the driver still keeps view control (design §5.1/D-3).
  // `unknown` (severity not curated) gets the honest middle: a "get diagnosed"
  // caution -- never a false "safe to clear" (green) nor a false "pull over".
  var TAKEOVER_STYLE = {
    stop: { colorVar: "--critical-red", icon: "⚠", directive: "REDUCE LOAD · PULL OVER",
            dismissLabel: "Acknowledge", plainDismiss: false },
    watch: { colorVar: "--amber-warn", icon: "⚠", directive: "DRIVE GENTLY · GET DIAGNOSED",
            dismissLabel: "Dismiss", plainDismiss: true },
    minor: { colorVar: "--green-ok", icon: "ⓘ", directive: "SAFE TO CLEAR ONCE LOGGED",
            dismissLabel: "Dismiss", plainDismiss: true },
    unknown: { colorVar: "--amber-warn", icon: "⚠", directive: "GET DIAGNOSED",
            dismissLabel: "Dismiss", plainDismiss: true },
  };

  function severityRank(sev) {
    return Object.prototype.hasOwnProperty.call(DTC_SEVERITY_RANK, sev)
      ? DTC_SEVERITY_RANK[sev]
      : -1;
  }

  // The alert-eligible codes, worst-first. `na` and any unrecognized severity
  // are dropped (they never alarm). Stable within a rank (input order kept).
  function alertableCodes(codes) {
    if (!Array.isArray(codes)) return [];
    var out = [];
    for (var i = 0; i < codes.length; i++) {
      var c = codes[i];
      if (isObj(c) && severityRank(c.severity) >= 0) out.push(c);
    }
    out.sort(function (a, b) { return severityRank(b.severity) - severityRank(a.severity); });
    return out;
  }

  // The takeover view for a NEW code, or null (no new code / no alertable code /
  // malformed). One takeover at a time: the worst code is the hero; the rest are
  // "+N more". Firing (vs a prior ack) is a stateful concern -> takeoverShouldShow.
  function takeoverView(data) {
    if (!isObj(data)) return null;
    // US-429 / Bug-3b: an unavailable DTC source (no read happened) NEVER fires
    // a takeover -- an absent source reads `unavailable`, not "no codes -> alert".
    if (sourceUnavailable(data, "dtc")) return null;
    if (data.newSinceTs == null) return null; // known code at boot -> ribbon only
    var alertable = alertableCodes(data.codes);
    if (alertable.length === 0) return null;   // no real fault (e.g. all `na`)
    var hero = alertable[0];
    var style = TAKEOVER_STYLE[hero.severity] || TAKEOVER_STYLE.unknown;
    return {
      newSinceTs: data.newSinceTs,
      severity: hero.severity,
      code: hero.code,
      short: (hero.short && String(hero.short).trim()) || "No description yet",
      directive: style.directive,
      colorVar: style.colorVar,
      icon: style.icon,
      dismissLabel: style.dismissLabel,
      plainDismiss: style.plainDismiss,
      moreCount: alertable.length - 1,
    };
  }

  // Edge-trigger: show the takeover only when its `newSinceTs` differs from the
  // last-acknowledged stamp. Same stamp -> already handled (no re-show); a newer
  // code changes the stamp -> re-fire (escalation, design D-3).
  function takeoverShouldShow(view, lastAckedTs) {
    return !!view && view.newSinceTs !== lastAckedTs;
  }

  // The persistent ribbon while ANY alert-eligible code is present (design §5.2).
  // Level = the hero severity (drives the color); `na`/empty -> null (no ribbon).
  function ribbonView(data) {
    if (!isObj(data)) return null;
    // US-429: an unavailable DTC source carries no active fault -> no ribbon.
    if (sourceUnavailable(data, "dtc")) return null;
    var alertable = alertableCodes(data.codes);
    if (alertable.length === 0) return null;
    var hero = alertable[0];
    var text = "CHECK ENGINE · " + hero.code;
    var desc = hero.short && String(hero.short).trim();
    if (desc) text += " " + desc;
    if (alertable.length > 1) text += " · +" + (alertable.length - 1) + " more";
    return { level: hero.severity, glyph: "⚠", text: text, code: hero.code };
  }

  // -------------------------------------------------------------------------
  // US-481 idle-state home card (F-121) -- pure, node-testable logic. The calm,
  // honest PARKED view: engine off / OBD asleep. It is a PURE CONSUMER of the
  // SAME three state files the live cards read (system-status / battery-health /
  // dtc) -- it fabricates nothing. Honest-instrument (Iris spec 1.3), locked in
  // the pure builders so a buggy DOM layer can't violate them:
  //   - NO green "OK" at idle EXCEPT the battery line (and that line always
  //     carries its data-age, F-9) -- the STANDBY hero is always neutral.
  //   - NO amber/red at idle UNLESS a REAL stored STOP/WATCH code exists; a
  //     MINOR/unknown code and a clean read stay neutral.
  //   - absence != clean and != fault: an unread DTC source is "DTC not read
  //     since key-off", never "No codes" (a false all-clear) and never a phantom
  //     Check Engine. The persistent ribbon/takeover still fire on top of this
  //     card, so idle never SUPPRESSES a genuine fault (Iris AC-5).
  // -------------------------------------------------------------------------

  // idle is the emitter's SSOT (system-status `idle` boolean, US-480-a / Atlas
  // idle-SSOT b). The display RENDERS the flag; it NEVER re-derives idle from
  // the drive-state string (the replaced display-derived pattern). Anything
  // other than an explicit `true` (absent key / malformed file / false) reads
  // NOT-idle -- fail closed to the live view, never guess a calm parked state.
  function carouselIdle(systemStatusData) {
    return isObj(systemStatusData) && systemStatusData.idle === true;
  }

  // Last-drive summary fact. Honest degradation: the parked emitter writes
  // driveId:null when idle, and there is no last-drive-summary state file yet,
  // so with no drive reference the fact reads "No recent drive" -- absence, not
  // a fabricated last trip. A real driveId (or an active recording) renders it.
  function idleLastDriveFact(systemStatusData) {
    var label = "LAST DRIVE";
    if (!isObj(systemStatusData) || !isObj(systemStatusData.drive)) {
      return { label: label, value: "—", detail: "unavailable", level: "unavailable" };
    }
    var drive = systemStatusData.drive;
    if (drive.state === "recording") {
      var id = drive.driveId == null ? "?" : drive.driveId;
      return { label: label, value: "REC", detail: "drive " + id, level: "neutral" };
    }
    if (drive.driveId != null) {
      return { label: label, value: "drive " + drive.driveId, detail: "last recorded", level: "neutral" };
    }
    return { label: label, value: "No recent drive", detail: "since key-off", level: "neutral" };
  }

  // Battery-with-age fact. The ONE line allowed to go green at idle -- and only
  // via the Spool verdict, always carrying its data-age (F-9 stale-green guard).
  // Reuses the battery-health view (single UPS source -> whole-card NA); prefers
  // SoC% but falls back to volts (a voltage is never rendered AS a percent).
  function idleBatteryFact(batteryData) {
    var label = "BATTERY";
    var view = batteryHealthView(batteryData);
    if (view === null) {
      return { label: label, value: "—", detail: "unavailable", level: "unavailable" };
    }
    if (view.unavailable) {
      return { label: label, value: "NA", detail: view.reason, level: "unavailable" };
    }
    var value = view.soc && view.soc.shown ? view.soc.value : view.vcell.value;
    return {
      label: label,
      value: value,
      detail: view.healthCheck.label,   // "last health check · <date> (<age>)"
      level: view.health.level,         // green ONLY when the Spool verdict is green
    };
  }

  // Honest-faults fact. An unavailable DTC source (no key-on read) -> "DTC not
  // read · since key-off" NEUTRAL. A real STOP/WATCH stored code surfaces at its
  // tier (down/amber); a MINOR/unknown code stays neutral (never amber/red at
  // idle); a clean read is "No stored codes" NEUTRAL (never green). Reuses the
  // same alertableCodes classifier the ribbon/takeover use (Spool severity).
  function idleFaultsFact(dtcData) {
    var label = "FAULTS";
    if (!isObj(dtcData) || sourceUnavailable(dtcData, "dtc")) {
      return { label: label, value: "DTC not read", detail: "since key-off", level: "neutral" };
    }
    var alertable = alertableCodes(dtcData.codes);
    if (alertable.length === 0) {
      return { label: label, value: "No stored codes", detail: "key-on read", level: "neutral" };
    }
    var hero = alertable[0];
    var level = hero.severity === "stop" ? "down"
      : hero.severity === "watch" ? "amber"
      : "neutral"; // minor/unknown are real but never amber/red at idle
    var more = alertable.length > 1 ? " · +" + (alertable.length - 1) + " more" : "";
    var desc = (hero.short && String(hero.short).trim()) || "";
    return { label: label, value: hero.code, detail: desc + more, level: level };
  }

  // The assembled idle card view consumed by the DOM renderer + the node tests.
  // The STANDBY hero is ALWAYS neutral (never a green "OK" backdrop). The header
  // wordmark + live clock/date and the footer are DOM-only presentation.
  function idleCardView(systemStatusData, batteryData, dtcData) {
    return {
      wordmark: "ECLIPSE",
      hero: { title: "STANDBY", substate: "engine off · OBD asleep", level: "neutral" },
      facts: {
        lastDrive: idleLastDriveFact(systemStatusData),
        battery: idleBatteryFact(batteryData),
        faults: idleFaultsFact(dtcData),
      },
    };
  }

  // -------------------------------------------------------------------------
  // US-406 DTC Alerts card (Card 5) + detail -- pure, node-testable logic
  // (S-4/S-5/S-12/S-13/I-3). The card is a PURE CONSUMER of the `dtc` state:
  // the display maps a Spool-classified tier -> chip label + color + directive;
  // it NEVER classifies. Two render-safety invariants are locked in the pure
  // builders (the SSOT) so a buggy DOM layer can't violate them:
  //   F-1/S-4  the fix area for a 🔴/🟡 code is REPLACED by a "diagnose, don't
  //            swap parts" directive -- the raw `suggestedFix` is never rendered
  //            even when non-null (only a 🟢 MINOR code shows a real fix + badge).
  //   S-13     a `severityCaveat` renders as a caveat LINE beneath the base chip;
  //            it NEVER auto-upgrades the tier (the display reads `severity`
  //            verbatim). `na` (auto-trans on this manual car) is a quiet
  //            disposition -- an N/A chip that sorts LAST, never a hero (S-12).
  // -------------------------------------------------------------------------

  // Tier -> display presentation (chip label + CSS level + hero/detail
  // directive). `unknown` = an uncurated code (no Spool entry) -> the honest
  // middle "GET DIAGNOSED", never a false "safe to clear" nor a false "pull
  // over". `na` = not applicable to this vehicle (quiet, unalarming).
  var DTC_TIER = {
    stop: { chip: "STOP", level: "stop", directive: "REDUCE LOAD · PULL OVER" },
    watch: { chip: "WATCH", level: "watch", directive: "DRIVE GENTLY · GET DIAGNOSED" },
    minor: { chip: "MINOR", level: "minor", directive: "SAFE TO CLEAR ONCE LOGGED" },
    unknown: { chip: "?", level: "unknown", directive: "GET DIAGNOSED" },
    na: { chip: "N/A", level: "na", directive: "not applicable to this vehicle" },
  };

  // List ordering for the Alerts card: worst-first, but `na` ALWAYS sorts last
  // (design §5.3) -- higher rank = higher in the list. An unrecognized severity
  // is treated as `unknown` (never dropped -- hiding a code could hide a fault).
  var DTC_LIST_RANK = { stop: 4, watch: 3, minor: 2, unknown: 1, na: 0 };

  function dtcTier(sev) {
    return Object.prototype.hasOwnProperty.call(DTC_TIER, sev)
      ? DTC_TIER[sev]
      : DTC_TIER.unknown;
  }

  function dtcListRank(sev) {
    return Object.prototype.hasOwnProperty.call(DTC_LIST_RANK, sev)
      ? DTC_LIST_RANK[sev]
      : DTC_LIST_RANK.unknown;
  }

  function dtcShort(code) {
    return (code.short && String(code.short).trim()) || "No description yet";
  }

  function dtcCaveat(code) {
    return (code.severityCaveat && String(code.severityCaveat).trim()) || null;
  }

  // All valid code objects sorted worst-first (na last). Stable within a rank
  // (input order preserved), so same-severity codes keep their capture order.
  function dtcListSorted(codes) {
    if (!Array.isArray(codes)) return [];
    var out = [];
    for (var i = 0; i < codes.length; i++) {
      if (isObj(codes[i])) out.push(codes[i]);
    }
    out.sort(function (a, b) { return dtcListRank(b.severity) - dtcListRank(a.severity); });
    return out;
  }

  // One compact list row (chip · code · short · caveat hint · status).
  function dtcRow(code) {
    var tier = dtcTier(code.severity);
    return {
      code: code.code,
      chip: tier.chip,
      level: tier.level,
      short: dtcShort(code),
      caveat: dtcCaveat(code),
      status: code.status === "pending" ? "PEND" : "STORED",
      isNa: code.severity === "na",
    };
  }

  // The Alerts card view: hero (worst ALERT-eligible code + its directive; `na`
  // and unrecognized severities are never a hero) + the full list (worst-first,
  // na last) + stored/pending counts. Non-object payload -> null (the shell
  // renders `unavailable`). An empty `codes` array is a valid no-fault view.
  function alertsCardView(data) {
    if (!isObj(data)) return null;
    // US-429: an unavailable DTC source (no read happened) is a typed NA -- NOT
    // "No stored codes" (which would falsely imply a clean all-clear read).
    if (sourceUnavailable(data, "dtc")) {
      return { unavailable: true, reason: sourceReason(data, "dtc") };
    }
    var codes = Array.isArray(data.codes) ? data.codes.filter(isObj) : [];
    var alertable = alertableCodes(codes); // drops na + unrecognized (never a hero)
    var hero = null;
    if (alertable.length > 0) {
      var h = alertable[0];
      var t = dtcTier(h.severity);
      hero = {
        code: h.code,
        chip: t.chip,
        level: t.level,
        short: dtcShort(h),
        directive: t.directive,
        caveat: dtcCaveat(h),
      };
    }
    var stored = 0;
    var pending = 0;
    for (var i = 0; i < codes.length; i++) {
      if (codes[i].status === "pending") pending++;
      else stored++;
    }
    return {
      hero: hero,
      rows: dtcListSorted(codes).map(dtcRow),
      storedCount: stored,
      pendingCount: pending,
      mil: data.mil === true,
    };
  }

  // 3-state trust badge (design §5.4). Verified (Spool) / community-unverified /
  // offline-not-yet-fetched. Any unrecognized/absent provenance -> offline (the
  // honest "no live net in the car" default), never a fabricated authority.
  function trustBadge(fixProvenance) {
    if (fixProvenance === "spool-validated") {
      return { kind: "verified", label: "✓ Verified · Spool" };
    }
    if (fixProvenance === "auto-unverified" || fixProvenance === "sourced") {
      return { kind: "community", label: "👥 Community · unverified" };
    }
    return { kind: "offline", label: "⏳ Looking into it" };
  }

  // Severity-gated fix area (S-4/F-1 -- the load-bearing safety invariant). A
  // 🔴/🟡 (or uncurated `unknown`) code's fix slot is REPLACED by a diagnose
  // directive; the raw `suggestedFix` is NEVER rendered for it, even when
  // non-null. Only a 🟢 MINOR code shows the actual fix + a trust badge. `na`
  // is not applicable. A missing MINOR fix is honest text, never fabricated.
  function fixArea(code) {
    var sev = code.severity;
    if (sev === "na") {
      return { mode: "na", text: "Not applicable to this vehicle", badge: null };
    }
    if (sev !== "minor") {
      var lead =
        sev === "stop"
          ? "⚠ STOP — diagnose, don't just swap parts"
          : sev === "watch"
            ? "⚠ WATCH — get it diagnosed, don't swap parts"
            : "Get it diagnosed before replacing parts";
      return { mode: "directive", text: lead, badge: null };
    }
    var fix = (code.suggestedFix && String(code.suggestedFix).trim()) || null;
    return {
      mode: "fix",
      text: fix || "No fix available offline — arrives on next sync.",
      badge: trustBadge(code.fixProvenance),
    };
  }

  // Freeze-frame view (S-5). Mode 02 is confirmed unsupported on the current
  // ECU (MD326328) -> the default is the labeled realtime-context fallback,
  // never blank. A grid renders only if a future Mode-02-capable ECU supplies
  // one (freezeFrame is a non-null object).
  function freezeFrameView(code) {
    var ff = isObj(code.freezeFrame) ? code.freezeFrame : null;
    if (!ff) {
      return {
        hasFrame: false,
        fallbackText: "no freeze frame captured (this ECU) — showing context at fault time",
        grid: null,
      };
    }
    return { hasFrame: true, fallbackText: null, grid: ff };
  }

  // Status meta line. A null `driveId` is a KOEO (key-on) read (US-404 A-9) --
  // shown as "key-on read", NEVER a fabricated "Drive N".
  function dtcStatusMeta(code) {
    var parts = [];
    parts.push(code.status === "pending" ? "PENDING" : "STORED");
    parts.push(code.driveId == null ? "key-on read" : "Drive " + code.driveId);
    return parts.join(" · ");
  }

  // The per-code detail view. Non-object -> null. The directive band renders
  // only for 🔴/🟡 (drives the "get diagnosed" message); the caveat is a line,
  // never a tier upgrade (S-13).
  function codeDetailView(code) {
    if (!isObj(code)) return null;
    var tier = dtcTier(code.severity);
    var isStopWatch = code.severity === "stop" || code.severity === "watch";
    return {
      code: code.code,
      chip: tier.chip,
      level: tier.level,
      short: dtcShort(code),
      long: (code.long && String(code.long).trim()) || null,
      directive: isStopWatch ? tier.directive : null,
      caveat: dtcCaveat(code),
      statusMeta: dtcStatusMeta(code),
      freezeFrame: freezeFrameView(code),
      fix: fixArea(code),
      logged: code.logged === true,
      syncAcked: code.syncAcked === true,
      clearEligible: code.clearEligible === true,
      isNa: code.severity === "na",
    };
  }

  // -------------------------------------------------------------------------
  // US-407 -- DTC Clear (Mode-04) surface (F-111 / design §6).
  // -------------------------------------------------------------------------

  // Display-only reason -> label. The AUTHORITATIVE gate is re-checked server-
  // side (pi.splash.dtc_clear); this mirrors it so the button reads honestly.
  var CLEAR_REASON_LABEL = {
    ok: "CLEAR CODES",
    severity_present: "🔒 CLEAR CODES — a STOP/WATCH code is present",
    sync_pending: "🔒 CLEAR CODES — waiting for server sync",
    session_locked: "🔒 CLEAR CODES — a cleared code returned; clearing again won't fix it",
  };

  // Re-derive the clear gate from the raw codes (the display mirror of the
  // server-side dtc_clear.evaluateClearGate). Deliberately IGNORES any
  // precomputed clearGate.enabled -- the button never lies just because the
  // state's flag does. Mode 04 is all-or-nothing, so the gate keys off ALL
  // stored (non-na) codes, not the one on screen.
  function clearGateReason(data) {
    if (!isObj(data)) return "no_codes";
    var codes = Array.isArray(data.codes) ? data.codes.filter(isObj) : [];
    var relevant = codes.filter(function (c) {
      return c.status === "stored" && c.severity !== "na";
    });
    if (relevant.length === 0) return "no_codes";
    if (relevant.some(function (c) { return c.severity !== "minor"; })) {
      return "severity_present";
    }
    if (relevant.some(function (c) { return !(c.logged && c.syncAcked); })) {
      return "sync_pending";
    }
    var lock = {};
    var raw = Array.isArray(data.sessionResetLock) ? data.sessionResetLock : [];
    for (var i = 0; i < raw.length; i++) lock[raw[i]] = true;
    if (relevant.some(function (c) { return lock[c.code]; })) {
      return "session_locked";
    }
    return "ok";
  }

  // The Clear button view. `no_codes` -> no button (nothing to clear). Otherwise
  // the button is visible; enabled only when the gate is `ok`, else disabled
  // with an honest reason label (S-6 / S-8).
  function clearButtonView(data) {
    var reason = clearGateReason(data);
    if (reason === "no_codes") {
      return { visible: false, enabled: false, reason: reason, label: null };
    }
    return {
      visible: true,
      enabled: reason === "ok",
      reason: reason,
      label: CLEAR_REASON_LABEL[reason] || CLEAR_REASON_LABEL.ok,
    };
  }

  // The hard-confirm copy (S-7 / design §6.2). Names the irreversible
  // consequences: every code wiped, the freeze-frame erased, readiness monitors
  // reset (a full drive cycle before an inspection will pass).
  function confirmClearText() {
    return {
      title: "Clear all codes?",
      body:
        "Wipes every stored + pending code, erases the freeze-frame, and resets " +
        "emissions readiness monitors (a full drive cycle is needed before an " +
        "inspection will pass). Can't be undone.",
      confirmLabel: "Clear all",
      cancelLabel: "Cancel",
    };
  }

  // The post-clear result message from the server's clear outcome (§6.3). The
  // re-read is the PROOF -- report "0 stored, 0 pending, MIL off", never a bare
  // "command sent". An instant re-set -> "don't chase the light" (I-7 / S-8).
  function postClearMessage(outcome) {
    if (!isObj(outcome)) return null;
    if (!outcome.issued) {
      return {
        level: "blocked",
        text: "Clear refused — " + (outcome.reason || "not allowed right now"),
      };
    }
    var reSet = Array.isArray(outcome.reSetCodes) ? outcome.reSetCodes : [];
    if (reSet.length > 0) {
      return {
        level: "reset",
        text:
          reSet.join(", ") +
          " returned — a code that comes back is a real fault; clearing again won't fix it",
      };
    }
    if (outcome.cleared) {
      return { level: "cleared", text: "Cleared — 0 stored, 0 pending, MIL off" };
    }
    return {
      level: "partial",
      text: "Clear issued, but codes remain — re-check the Alerts card",
    };
  }

  // -------------------------------------------------------------------------
  // US-483-b display-brightness consumer (F-121) -- pure, node-testable logic.
  // The dashboard is a PURE CONSUMER of the states/light file US-483-a writes
  // ({lux, ts}); it NEVER reads the sensor. The auto-dim curve values are
  // GROUNDED CONFIG PARAMETERS injected at serve time (window.DISPLAY_AUTODIM),
  // so tuning is a config change, not a code change (CIO 2026-07-22). These
  // built-in defaults are the file:// preview / unconfigured fallback and MIRROR
  // config.json pi.display.autoDim.* (the tuning SSOT). Honest-instrument: an
  // absent/stale/saturated (null) reading holds the fixed default -- never a
  // fabricated "auto" behavior; and a real active STOP alert is held at FULL
  // brightness regardless of lux (the load-bearing safety guard, US-484-b).
  // -------------------------------------------------------------------------

  // Spool 6d ch.4 (US-484-b): "a red alarm is full brightness always,
  // independent of auto-dim -- only ambient content dims." Full IS the top of
  // the 0..1 range, so this is a definition, not a tunable: there is no config
  // key that may lower a live PULL-OVER alarm.
  var STOP_ALARM_LEVEL = 1.0;

  var BRIGHTNESS_DEFAULTS = {
    luxMin: 3.0,          // lux <= this -> min (grounded: civil-twilight dark)
    luxFull: 1000.0,      // lux >= this -> full (grounded: overcast daylight)
    minLevel: 0.15,       // calm-screen dim floor (fraction 0..1)
    defaultLevel: 0.70,   // fixed fallback when the feed is absent/stale
    alarmFloorLevel: 0.40, // SUPERSEDED by STOP_ALARM_LEVEL (US-484-b ch.4):
                           // a STOP now goes to FULL, overriding this floor.
                           // Kept so an existing config.json that still carries
                           // pi.display.autoDim.alarmFloorLevel resolves cleanly
                           // (removal is a Spool/Atlas call -- see TD-066).
    luxStaleSec: 10,      // a reading older than this -> fallback
    curve: "logarithmic", // perceptual mapping between luxMin..luxFull
  };

  // Resolve the injected config over the grounded defaults (only well-typed
  // overrides win). A malformed/absent global leaves every default in place.
  function resolveAutoDimConfig(cfg) {
    var out = {};
    for (var k in BRIGHTNESS_DEFAULTS) {
      if (Object.prototype.hasOwnProperty.call(BRIGHTNESS_DEFAULTS, k)) {
        out[k] = BRIGHTNESS_DEFAULTS[k];
      }
    }
    if (cfg && typeof cfg === "object") {
      for (var key in BRIGHTNESS_DEFAULTS) {
        if (!Object.prototype.hasOwnProperty.call(cfg, key)) continue;
        var v = cfg[key];
        if (key === "curve") {
          if (typeof v === "string") out[key] = v;
        } else if (typeof v === "number" && isFinite(v)) {
          out[key] = v;
        }
      }
    }
    return out;
  }

  // The perceptual lux -> 0..1 mapping. Returns 0 at/below luxMin, 1 at/above
  // luxFull, and a curve value between. A degenerate range (luxFull <= luxMin)
  // or a non-positive luxMin under the log curve falls back to linear/full so it
  // can never divide by zero or take log of a non-positive number.
  function brightnessCurve(lux, luxMin, luxFull, curve) {
    if (typeof lux !== "number" || !isFinite(lux)) return 0;
    if (!(luxFull > luxMin)) return 1; // misconfigured range -> full, never div0
    if (lux <= luxMin) return 0;
    if (lux >= luxFull) return 1;
    if (curve !== "linear" && luxMin > 0 && lux > 0) {
      return (
        (Math.log(lux) - Math.log(luxMin)) /
        (Math.log(luxFull) - Math.log(luxMin))
      );
    }
    return (lux - luxMin) / (luxFull - luxMin);
  }

  // The fresh, finite lux from a states/light payload, or null (fall back). A
  // missing/malformed file, a null lux (honest saturation), a non-finite value,
  // or a reading older than luxStaleSec all read null -> the caller holds the
  // fixed default rather than trusting a frozen/absent value.
  function freshLux(lightData, luxStaleSec, nowMs) {
    if (!lightData || typeof lightData !== "object") return null;
    var lux = lightData.lux;
    if (typeof lux !== "number" || !isFinite(lux)) return null;
    var ts = lightData.ts;
    if (typeof ts !== "string") return null;
    var t = Date.parse(ts);
    if (isNaN(t)) return null;
    var ageSec = (nowMs - t) / 1000;
    if (!(ageSec <= luxStaleSec)) return null; // stale (or NaN age) -> fallback
    return lux;
  }

  // A real ACTIVE STOP alert is present (drives the alarm floor). Reuses the same
  // honest ribbon classifier the takeover/ribbon use: an unavailable DTC source
  // carries no active fault -> false; only a STOP-tier hero forces the floor (the
  // PULL-OVER alarm). A WATCH/MINOR alert is a real code but not the pull-over
  // alarm, so it does not force the legible floor (Iris AC-7 scope).
  function brightnessAlarmActive(dtcData) {
    var rv = ribbonView(dtcData);
    return !!rv && rv.level === "stop";
  }

  // The final 0..1 brightness: clamp(minLevel, curve(lux), 1.0) when the feed is
  // fresh, else the fixed default (honest fallback).
  //
  // US-484-b / Spool 6d ch.4 -- the load-bearing safety short-circuit: while a
  // real STOP is active the surface is FULL, before any ambient math runs. It
  // overrides the curve, the fixed default AND the alarmFloorLevel guard, so a
  // dark cabin (or a dead light sensor) can never dim a PULL-OVER alarm.
  function brightnessLevel(lightData, cfg, nowMs, alarmActive) {
    if (alarmActive) return STOP_ALARM_LEVEL;
    var c = resolveAutoDimConfig(cfg);
    var lux = freshLux(lightData, c.luxStaleSec, nowMs);
    var level;
    if (lux === null) {
      level = c.defaultLevel; // absent/stale/saturated -> fixed default
    } else {
      var curved = brightnessCurve(lux, c.luxMin, c.luxFull, c.curve);
      level = Math.min(Math.max(curved, c.minLevel), 1.0);
    }
    return Math.min(Math.max(level, 0), 1);
  }

  var api = {
    clampIndex: clampIndex,
    nextIndex: nextIndex,
    swipeDirection: swipeDirection,
    computeStageScale: computeStageScale,
    cardAvailability: cardAvailability,
    sourceUnavailable: sourceUnavailable,
    sourceReason: sourceReason,
    naTile: naTile,
    obdLinkTile: obdLinkTile,
    syncTile: syncTile,
    powerTile: powerTile,
    driveTile: driveTile,
    btGlyphState: btGlyphState,
    syncGlyphState: syncGlyphState,
    powerGlyphState: powerGlyphState,
    systemSummary: systemSummary,
    systemStatusView: systemStatusView,
    healthCheckLine: healthCheckLine,
    vcellTile: vcellTile,
    socTile: socTile,
    tempTile: tempTile,
    ladderView: ladderView,
    batteryHealthView: batteryHealthView,
    fmtLtftPct: fmtLtftPct,
    ltftTrendView: ltftTrendView,
    serviceMenuItems: serviceMenuItems,
    requiresConfirm: requiresConfirm,
    actionRequest: actionRequest,
    longPressProgress: longPressProgress,
    isLongPressComplete: isLongPressComplete,
    exceedsMoveCancel: exceedsMoveCancel,
    menuAccess: menuAccess,
    alertableCodes: alertableCodes,
    takeoverView: takeoverView,
    takeoverShouldShow: takeoverShouldShow,
    ribbonView: ribbonView,
    dtcListSorted: dtcListSorted,
    brightnessCurve: brightnessCurve,
    brightnessLevel: brightnessLevel,
    brightnessAlarmActive: brightnessAlarmActive,
    resolveAutoDimConfig: resolveAutoDimConfig,
    carouselIdle: carouselIdle,
    idleLastDriveFact: idleLastDriveFact,
    idleBatteryFact: idleBatteryFact,
    idleFaultsFact: idleFaultsFact,
    idleCardView: idleCardView,
    dtcRow: dtcRow,
    alertsCardView: alertsCardView,
    trustBadge: trustBadge,
    fixArea: fixArea,
    freezeFrameView: freezeFrameView,
    codeDetailView: codeDetailView,
    clearGateReason: clearGateReason,
    clearButtonView: clearButtonView,
    confirmClearText: confirmClearText,
    postClearMessage: postClearMessage,
    POLL_MS: POLL_MS,
    SWIPE_THRESHOLD_PX: SWIPE_THRESHOLD_PX,
    STAGE_W: STAGE_W,
    STAGE_H: STAGE_H,
    LONG_PRESS_MS: LONG_PRESS_MS,
    LONG_PRESS_ARM_MS: LONG_PRESS_ARM_MS,
    LONG_PRESS_MOVE_PX: LONG_PRESS_MOVE_PX,
  };

  // -------------------------------------------------------------------------
  // DOM wiring -- browser only.
  // -------------------------------------------------------------------------

  if (typeof document !== "undefined") {
    var token = global.SPLASH_TOKEN || "";

    // US-483-b: the auto-dim curve config injected same-origin at serve time
    // (states_http_server substitutes the placeholder from config.json). An
    // object -> use it; anything else (unsubstituted preview / null) -> the
    // built-in grounded defaults kick in inside resolveAutoDimConfig.
    var displayAutoDim =
      global.DISPLAY_AUTODIM && typeof global.DISPLAY_AUTODIM === "object"
        ? global.DISPLAY_AUTODIM
        : null;

    // Apply the computed 0..1 brightness as a CSS var on the screen frame (a
    // software dim -- the browser kiosk can't drive the panel backlight). Setting
    // a var (not style.filter) keeps the CSS the single owner of the filter rule.
    function applyBrightness(level) {
      var screenEl = document.getElementById("screen");
      if (screenEl) screenEl.style.setProperty("--display-brightness", String(level));
    }

    // --- US-400 System Status DOM render (browser only) ---------------------

    // Render one tile into a parent element (label + prominent value + detail).
    // The level drives the colour via [data-level] CSS -- a degraded tile is
    // never green (F-1). Built with textContent (no innerHTML) so emitter values
    // render verbatim, never as markup.
    // US-489: `withDot` prepends the per-tile status dot. It is OPT-IN because
    // appendTile is shared with the idle, battery and LTFT cards -- defaulting
    // it on would restyle three shipped cards from a story scoped to one.
    function appendTile(parent, tile, withDot) {
      var el = document.createElement("div");
      el.className = "tile";
      el.setAttribute("data-level", tile.level);
      var label = document.createElement("span");
      label.className = "tile-label";
      label.textContent = tile.label;
      if (withDot) {
        // The dot takes no level of its own -- it inherits the tile's
        // [data-level], so it can never disagree with the value beside it.
        var head = document.createElement("div");
        head.className = "tile-head";
        var dot = document.createElement("span");
        dot.className = "tile-dot";
        head.appendChild(dot);
        head.appendChild(label);
        el.appendChild(head);
      }
      var value = document.createElement("span");
      value.className = "tile-value";
      value.textContent = tile.value;
      var detail = document.createElement("span");
      detail.className = "tile-detail";
      detail.textContent = tile.detail;
      if (!withDot) el.appendChild(label);
      el.appendChild(value);
      el.appendChild(detail);
      parent.appendChild(el);
    }

    function renderSystemStatusCard(card, view, glyphEls) {
      var body = card.querySelector(".card-body");
      if (body) {
        body.textContent = "";
        // US-489 P-1: the one-glance headline, then the 2x2 grid. Built with
        // textContent (no innerHTML) so emitter values render verbatim.
        var summary = document.createElement("div");
        summary.className = "sys-summary";
        summary.setAttribute("data-level", view.summary.level);
        var summaryText = document.createElement("span");
        summaryText.className = "sys-summary-text";
        summaryText.textContent = view.summary.text;
        summary.appendChild(summaryText);
        if (view.summary.detail) {
          var summaryDetail = document.createElement("span");
          summaryDetail.className = "sys-summary-detail";
          summaryDetail.textContent = view.summary.detail;
          summary.appendChild(summaryDetail);
        }
        body.appendChild(summary);
        var grid = document.createElement("div");
        grid.className = "sys-grid";
        appendTile(grid, view.tiles.obdLink, true);
        appendTile(grid, view.tiles.sync, true);
        appendTile(grid, view.tiles.power, true);
        appendTile(grid, view.tiles.drive, true);
        body.appendChild(grid);
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

    // --- US-481 idle-state home card DOM render (browser only) --------------

    // Local wall-clock formatters for the parked header. Local (not UTC) is the
    // right zone for a kiosk showing the driver the time; the pure view logic
    // stays clock-free (deterministic tests), so these live in the DOM layer.
    function two(n) { return (n < 10 ? "0" : "") + n; }
    var IDLE_DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    var IDLE_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    function fmtClock(d) { return two(d.getHours()) + ":" + two(d.getMinutes()); }
    function fmtDate(d) {
      return IDLE_DAYS[d.getDay()] + " " + d.getDate() + " " + IDLE_MONTHS[d.getMonth()];
    }

    // Render the idle card from the assembled view. Built with textContent (no
    // innerHTML) so emitter values render verbatim, never as markup. The 3 fact
    // tiles reuse the shared `.tile[data-level]` styling, so green is bound to
    // the SSOT token exactly once (US-484) -- the idle card holds no hex literal.
    function renderIdleCard(card, view, now) {
      var body = card.querySelector(".card-body");
      if (!body) return;
      body.textContent = "";

      // Header: wordmark + live clock + date (Iris 1.2).
      var header = document.createElement("div");
      header.className = "idle-header";
      var wm = document.createElement("span");
      wm.className = "idle-wordmark";
      wm.textContent = view.wordmark;
      var clock = document.createElement("span");
      clock.className = "idle-clock";
      clock.textContent = fmtClock(now);
      var date = document.createElement("span");
      date.className = "idle-date";
      date.textContent = fmtDate(now);
      header.appendChild(wm);
      header.appendChild(clock);
      header.appendChild(date);
      body.appendChild(header);

      // STANDBY hero (neutral grey, never green) + substate.
      var hero = document.createElement("div");
      hero.className = "idle-hero";
      hero.setAttribute("data-level", view.hero.level);
      var heroTitle = document.createElement("div");
      heroTitle.className = "idle-hero-title";
      heroTitle.textContent = view.hero.title;
      var heroSub = document.createElement("div");
      heroSub.className = "idle-hero-sub";
      heroSub.textContent = view.hero.substate;
      hero.appendChild(heroTitle);
      hero.appendChild(heroSub);
      body.appendChild(hero);

      // 3-fact summary strip: last-drive / battery-with-age / honest-faults.
      var strip = document.createElement("div");
      strip.className = "idle-facts";
      appendTile(strip, view.facts.lastDrive);
      appendTile(strip, view.facts.battery);
      appendTile(strip, view.facts.faults);
      body.appendChild(strip);

      // Footer: a calm reassurance that data resumes on engine start (the
      // carousel auto-advances off idle the moment OBD wakes -- honest).
      var footer = document.createElement("div");
      footer.className = "idle-footer";
      footer.textContent = "monitoring resumes on engine start";
      body.appendChild(footer);
    }

    // --- US-401 Battery Health DOM render (browser only) --------------------

    // Render the failsafe ladder block (F-2 / A-6) -- built ONLY when draining.
    // Minutes appear only when the power tier supplied a real runtimeRemainingS
    // (Spool S-2); otherwise stage + volts only, no fabricated estimate.
    function appendLadder(parent, ladder) {
      var box = document.createElement("div");
      box.className = "ladder";
      box.setAttribute("data-stage", ladder.stage);
      var banner = document.createElement("span");
      banner.className = "ladder-banner";
      banner.textContent = "DRAINING · " + ladder.stage;
      box.appendChild(banner);
      if (ladder.runtimeRemainingS != null) {
        var rt = document.createElement("span");
        rt.className = "ladder-runtime";
        rt.textContent = "~" + Math.round(ladder.runtimeRemainingS / 60) + " min to cutoff";
        box.appendChild(rt);
      }
      parent.appendChild(box);
    }

    // US-429: render a whole-card typed NA -- one "NA (<reason>)" tile, honest
    // (never a blank or a stale last-real card) when the card's source is down.
    function renderNaBody(body, label, reason) {
      body.textContent = "";
      appendTile(body, naTile(label, reason));
    }

    function renderBatteryHealthCard(card, view) {
      var body = card.querySelector(".card-body");
      if (!body) return;
      // US-429: UPS source unavailable -> the whole card is a typed NA.
      if (view.unavailable) {
        renderNaBody(body, view.label, view.reason);
        return;
      }
      body.textContent = "";
      appendTile(body, view.health);
      appendTile(body, view.vcell);
      // F-8: render the percent tile only when a real SoC exists; a null soc
      // omits the percent (volts already shown above), never a voltage-as-%.
      if (view.soc.shown) appendTile(body, view.soc);
      appendTile(body, view.temp);
      // F-2 / A-6: the ladder DOM exists only when actually draining.
      if (view.ladder) appendLadder(body, view.ladder);
    }

    // --- US-420 LTFT Trend DOM render (browser only) ------------------------

    // Render the multi-drive bar row: one bar per drive, coloured by its own
    // drift level ([data-level] -> CSS), so a drive beyond +/-10% is visibly
    // not-green. Built with textContent (no innerHTML) -- verbatim, never markup.
    function appendLtftBars(parent, points) {
      var bars = document.createElement("div");
      bars.className = "ltft-bars";
      for (var i = 0; i < points.length; i++) {
        var p = points[i];
        var bar = document.createElement("div");
        bar.className = "ltft-bar";
        bar.setAttribute("data-level", p.level);
        var value = document.createElement("span");
        value.className = "ltft-bar-value";
        value.textContent = p.value;
        var drive = document.createElement("span");
        drive.className = "ltft-bar-drive";
        drive.textContent = p.driveId == null ? "—" : "#" + p.driveId;
        bar.appendChild(value);
        bar.appendChild(drive);
        bars.appendChild(bar);
      }
      parent.appendChild(bars);
    }

    function renderLtftTrendCard(card, view) {
      var body = card.querySelector(".card-body");
      if (!body) return;
      body.textContent = "";
      // The headline tile carries the verdict level (insufficient -> not green).
      appendTile(body, view.headline);
      // The per-drive bars render whenever any real point exists (0-1 points is
      // still shown honestly under an insufficient headline, never fabricated).
      if (view.points.length > 0) appendLtftBars(body, view.points);
    }

    // US-482 letterbox: uniformly scale the fixed 480x320 #stage design box to
    // fill the real panel. The transformed #stage becomes the containing block
    // for its fixed/absolute descendants, so the shipped layout inside it is
    // untouched -- only the outer scale changes. Idempotent + null-safe.
    function applyStageScale() {
      var stage = document.getElementById("stage");
      if (!stage) return;
      var scale = computeStageScale(window.innerWidth, window.innerHeight);
      stage.style.setProperty("--scale", String(scale));
    }

    var setup = function () {
      // Scale first, then wire re-scale on any viewport change (rotation /
      // resolution change / the panel reporting late at boot).
      applyStageScale();
      window.addEventListener("resize", applyStageScale);

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
      startAvailabilityPoll(cards, glyphEls, goTo);
      setupMenu();
    };

    // --- US-403 System Setup menu DOM (browser only) -----------------------

    // POST an allow-listed action to the state server's /service-control route.
    // The kiosk is unprivileged; polkit authorizes the systemctl call and the
    // server re-checks the allow-list. Failures surface in the menu status line
    // (no console logging, never a fabricated success).
    function postAction(unit, verb, statusEl) {
      if (!actionRequest(unit, verb)) {
        if (statusEl) statusEl.textContent = unit + " " + verb + ": not permitted";
        return;
      }
      if (statusEl) statusEl.textContent = verb + " " + unit + " …";
      var headers = { "Content-Type": "application/json" };
      if (token) headers["X-Splash-Token"] = token;
      fetch("/service-control", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ unit: unit, verb: verb }),
      })
        .then(function (r) {
          return r.json().then(null, function () { return { ok: false }; });
        })
        .then(function (res) {
          if (!statusEl) return;
          statusEl.textContent = res.ok
            ? verb + " " + unit + " ok"
            : verb + " " + unit + " failed: " + (res.reason || res.error || "");
        })
        .then(null, function () {
          if (statusEl) statusEl.textContent = verb + " " + unit + " failed";
        });
    }

    // --- US-490 context-aware `⋮` affordance (browser only) ----------------
    // `hidden` (not a class) is deliberate: it is the property the tap handler
    // reads back as the rendered truth, so the gate and the paint can never
    // disagree. The button ships hidden in the markup, so the pre-first-poll
    // window -- when "am I driving?" is genuinely unknown -- offers no tap path.
    function applyMenuAccess(btn, access) {
      if (!btn) return;
      btn.hidden = !access.tapVisible;
    }

    function updateMenuAccess(sysData) {
      applyMenuAccess(document.getElementById("menu-btn"), menuAccess(sysData));
    }

    function setupMenu() {
      var menu = document.getElementById("setup-menu");
      if (!menu) return;
      var menuBtn = document.getElementById("menu-btn");
      var closeBtn = document.getElementById("menu-close");
      var list = document.getElementById("svc-list");
      var statusEl = document.getElementById("menu-status");
      var exitBtn = document.getElementById("menu-exit");
      var ring = document.getElementById("longpress-ring");
      var confirmModal = document.getElementById("confirm-modal");
      var confirmText = document.getElementById("confirm-text");
      var confirmOk = document.getElementById("confirm-ok");
      var confirmCancel = document.getElementById("confirm-cancel");

      function hideConfirm() {
        if (confirmModal) confirmModal.hidden = true;
      }
      function openMenu() {
        buildList();
        menu.hidden = false;
      }
      function closeMenu() {
        menu.hidden = true;
        hideConfirm();
      }
      // Consequential actions (Stop, Exit) require a confirm; ✕/Cancel always
      // returns control (the user is never trapped).
      function askConfirm(message, onYes) {
        if (!confirmModal) {
          onYes();
          return;
        }
        if (confirmText) confirmText.textContent = message;
        confirmModal.hidden = false;
        confirmOk.onclick = function () {
          hideConfirm();
          onYes();
        };
        confirmCancel.onclick = hideConfirm;
      }
      function doAction(unit, verb) {
        var req = actionRequest(unit, verb);
        if (!req) return;
        if (req.confirm) {
          askConfirm(verb + " " + unit + "?", function () {
            postAction(unit, verb, statusEl);
          });
        } else {
          postAction(unit, verb, statusEl);
        }
      }

      function buildList() {
        if (!list) return;
        list.textContent = "";
        var items = serviceMenuItems();
        for (var i = 0; i < items.length; i++) {
          (function (item) {
            var row = document.createElement("div");
            row.className = "svc-row";
            var nm = document.createElement("span");
            nm.className = "svc-name";
            nm.textContent = item.label + " · " + item.sub;
            row.appendChild(nm);

            var restart = document.createElement("button");
            restart.className = "svc-btn tap-target";
            restart.textContent = "Restart";
            restart.addEventListener("click", function () {
              doAction(item.unit, "restart");
            });
            row.appendChild(restart);

            var stop = document.createElement("button");
            stop.className = "svc-btn tap-target";
            stop.textContent = "Stop";
            // F-7 / D-7 / I-10: the safe-shutdown guard has no working Stop.
            if (!item.canStop) {
              stop.disabled = true;
              stop.title = "safe-shutdown guard — restart only";
            } else {
              stop.addEventListener("click", function () {
                doAction(item.unit, "stop");
              });
            }
            row.appendChild(stop);
            list.appendChild(row);
          })(items[i]);
        }
      }

      if (menuBtn) {
        menuBtn.addEventListener("click", function () {
          // Defence in depth (US-490 AC-4): the button is display:none while
          // driving, but a CSS regression must not quietly re-open a one-tap
          // path into a service stop. `hidden` is the rendered truth.
          if (menuBtn.hidden) return;
          openMenu();
        });
      }
      if (closeBtn) closeBtn.addEventListener("click", closeMenu);
      if (exitBtn) {
        // Exit / Close UI (A-8): a dashboard stop -> drops to desktop; the
        // splash hand-off re-launches it on the next reboot.
        exitBtn.addEventListener("click", function () {
          doAction("eclipse-dashboard.service", "stop");
        });
      }

      // Long-press anywhere on the carousel opens the menu (D-6). A filling ring
      // gives feedback after the arm delay; movement or an early release cancels.
      var carousel = document.getElementById("carousel");
      if (carousel && ring) {
        var pressStart = null;
        var pressX = 0;
        var pressY = 0;
        var timer = null;
        var armed = false;
        function clearPress() {
          pressStart = null;
          armed = false;
          if (timer) {
            clearInterval(timer);
            timer = null;
          }
          ring.hidden = true;
          ring.style.setProperty("--fill", "0");
        }
        carousel.addEventListener("pointerdown", function (e) {
          pressStart = Date.now();
          pressX = e.clientX;
          pressY = e.clientY;
          timer = setInterval(function () {
            var elapsed = Date.now() - pressStart;
            if (elapsed >= LONG_PRESS_ARM_MS && !armed) {
              armed = true;
              ring.hidden = false;
            }
            if (armed) {
              ring.style.setProperty("--fill", String(longPressProgress(elapsed)));
            }
            if (isLongPressComplete(elapsed)) {
              clearPress();
              openMenu();
            }
          }, 50);
        });
        carousel.addEventListener("pointermove", function (e) {
          if (pressStart === null) return;
          if (exceedsMoveCancel(e.clientX - pressX, e.clientY - pressY)) clearPress();
        });
        carousel.addEventListener("pointerup", clearPress);
        carousel.addEventListener("pointercancel", clearPress);
      }
    }

    // Honest-instrument poll: fetch each card's state file; missing/malformed ->
    // `unavailable` (never a crash, never green-when-broken). The shell sets the
    // availability class; the per-card renderer (US-400 system-status; US-401
    // battery-health) paints the fields on top when available.
    function startAvailabilityPoll(cards, glyphEls, goTo) {
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

      // --- US-405 DTC takeover + ribbon surfaces (browser only) --------------
      var ribbonEl = document.getElementById("dtc-ribbon");
      var takeoverEl = document.getElementById("dtc-takeover");
      var tvIcon = document.getElementById("takeover-icon");
      var tvChip = document.getElementById("takeover-chip");
      var tvCode = document.getElementById("takeover-code");
      var tvDesc = document.getElementById("takeover-desc");
      var tvDirective = document.getElementById("takeover-directive");
      var tvMore = document.getElementById("takeover-more");
      var tvDismiss = document.getElementById("takeover-dismiss");
      var tvDetail = document.getElementById("takeover-detail");
      // The last-acknowledged `newSinceTs` (edge-trigger). Acknowledge/Dismiss
      // records it so the same code never re-takes-over; a newer code (a
      // different stamp) re-fires (escalation, D-3).
      var dtcLastAckedTs = null;

      // --- US-406 Alerts card (Card 5) + per-code detail (browser only) ------
      var detailEl = document.getElementById("dtc-detail");
      var detailBody = document.getElementById("detail-body");
      var detailBack = document.getElementById("detail-back");
      var detailCodeHead = document.getElementById("detail-code-head");
      // US-407 clear surface: the gated button + result line inside the detail,
      // and the dedicated hard-confirm modal.
      var clearBtn = document.getElementById("dtc-clear-btn");
      var clearResult = document.getElementById("dtc-clear-result");
      var clearConfirm = document.getElementById("clear-confirm");
      var clearConfirmTitle = document.getElementById("clear-confirm-title");
      var clearConfirmText = document.getElementById("clear-confirm-text");
      var clearConfirmOk = document.getElementById("clear-confirm-ok");
      var clearConfirmCancel = document.getElementById("clear-confirm-cancel");
      // The most-recent `dtc` state, so a ribbon/takeover "View detail" tap can
      // resolve a code string back to its full object.
      var lastDtc = null;
      // The Alerts card index, so a tap navigates the carousel to it.
      var dtcCardIndex = -1;
      // US-481 idle-home: the idle card element + its index (the HOME slot while
      // parked) and the System-Status index (where we auto-advance the moment
      // idle flips false). `lastIdle` edge-triggers the navigation so it fires
      // only on a state CHANGE -- it never fights a manual swipe while idle holds.
      var idleCard = document.getElementById("idle-card");
      var idleIndex = -1;
      var sysIndex = -1;
      var lastIdle = null;
      for (var ci = 0; ci < cards.length; ci++) {
        var st = cards[ci].getAttribute("data-state");
        if (st === "dtc") dtcCardIndex = ci;
        else if (st === "system-status") sysIndex = ci;
        if (cards[ci].getAttribute("data-idle-home") !== null) idleIndex = ci;
      }

      function findCode(codeStr) {
        if (!lastDtc || !Array.isArray(lastDtc.codes)) return null;
        for (var i = 0; i < lastDtc.codes.length; i++) {
          if (lastDtc.codes[i] && lastDtc.codes[i].code === codeStr) return lastDtc.codes[i];
        }
        return null;
      }
      function closeDetail() {
        if (detailEl) detailEl.hidden = true;
      }
      // Navigate the carousel to the Alerts card; optionally open a code detail.
      function openAlertsCard(codeStr) {
        if (dtcCardIndex >= 0 && typeof goTo === "function") goTo(dtcCardIndex);
        var codeObj = codeStr ? findCode(codeStr) : null;
        if (codeObj) openDetail(codeObj);
      }

      function hideTakeover() {
        if (takeoverEl) takeoverEl.hidden = true;
      }
      // Acknowledge/Dismiss -> record the stamp + drop to the ribbon (the ribbon
      // keeps carrying the alert). STOP has no plain dismiss, but Acknowledge is
      // still a drop-to-ribbon so the driver can always clear the view.
      function ackTakeover(view) {
        dtcLastAckedTs = view.newSinceTs;
        hideTakeover();
      }
      function showTakeover(view) {
        if (!takeoverEl) return;
        takeoverEl.setAttribute("data-severity", view.severity);
        if (tvIcon) tvIcon.textContent = view.icon;
        if (tvChip) tvChip.textContent = view.severity.toUpperCase();
        if (tvCode) tvCode.textContent = view.code;
        if (tvDesc) tvDesc.textContent = view.short;
        if (tvDirective) tvDirective.textContent = view.directive;
        if (tvMore) {
          if (view.moreCount > 0) {
            tvMore.textContent = "+" + view.moreCount + " more";
            tvMore.hidden = false;
          } else {
            tvMore.hidden = true;
          }
        }
        if (tvDismiss) {
          tvDismiss.textContent = view.dismissLabel;
          tvDismiss.onclick = function () { ackTakeover(view); };
        }
        // View detail (US-406): ack the takeover (drops it) + navigate to the
        // Alerts card and open the hero code's detail.
        if (tvDetail) {
          tvDetail.onclick = function () {
            ackTakeover(view);
            openAlertsCard(view.code);
          };
        }
        takeoverEl.hidden = false;
      }

      function renderRibbon(view) {
        if (!ribbonEl) return;
        if (!view) {
          ribbonEl.hidden = true;
          ribbonEl.removeAttribute("data-level");
          return;
        }
        ribbonEl.setAttribute("data-level", view.level);
        var glyph = ribbonEl.querySelector(".ribbon-glyph");
        var text = ribbonEl.querySelector(".ribbon-text");
        if (glyph) glyph.textContent = view.glyph;
        if (text) text.textContent = view.text;
        ribbonEl.hidden = false;
      }

      // --- US-406 detail render (browser only) -------------------------------

      // A labeled line: a bold label + a plain value (textContent -> verbatim,
      // never markup). Returns the row element so callers can tag it.
      function detailLine(cls, label, value) {
        var row = document.createElement("div");
        row.className = cls;
        if (label) {
          var l = document.createElement("span");
          l.className = "detail-label";
          l.textContent = label;
          row.appendChild(l);
        }
        var v = document.createElement("span");
        v.className = "detail-value";
        v.textContent = value;
        row.appendChild(v);
        return row;
      }

      // Render the per-code detail body from codeDetailView(). Every branch is
      // honest: a 🔴/🟡 fix is a diagnose directive (never a raw fix); a missing
      // freeze-frame is the labeled realtime fallback; a caveat is a line, never
      // a tier upgrade.
      function renderDetailBody(view) {
        if (!detailBody) return;
        detailBody.textContent = "";
        if (detailCodeHead) detailCodeHead.textContent = view.code;

        // Hero: chip + code + short description.
        var hero = document.createElement("div");
        hero.className = "detail-hero";
        var chip = document.createElement("span");
        chip.className = "dtc-chip";
        chip.setAttribute("data-level", view.level);
        chip.textContent = view.chip;
        hero.appendChild(chip);
        var codeSpan = document.createElement("span");
        codeSpan.className = "detail-code";
        codeSpan.textContent = view.code;
        hero.appendChild(codeSpan);
        var shortSpan = document.createElement("span");
        shortSpan.className = "detail-short";
        shortSpan.textContent = view.short;
        hero.appendChild(shortSpan);
        detailBody.appendChild(hero);

        // Severity directive band (🔴/🟡 only). US-488: the band is TIER-DRIVEN
        // in CSS, so the row carries data-level from the SAME tier the chip
        // above uses -- a directive can never disagree with the chip beside it,
        // and an untagged row falls back to the neutral base rather than
        // inheriting a severity it does not have.
        if (view.directive) {
          var directiveRow = detailLine("detail-directive", "", view.directive);
          directiveRow.setAttribute("data-level", view.level);
          detailBody.appendChild(directiveRow);
        }
        // Condition-dependent caveat -- a LINE beneath the chip, never a tier
        // upgrade (S-13).
        if (view.caveat) {
          detailBody.appendChild(detailLine("detail-caveat", "", "⚠ " + view.caveat));
        }
        // Status meta (STORED/PENDING · key-on read | Drive N).
        detailBody.appendChild(detailLine("detail-meta", "", view.statusMeta));

        // Freeze-frame grid OR the labeled realtime fallback (S-5, never blank).
        var ff = document.createElement("div");
        ff.className = "detail-freeze";
        var ffLabel = document.createElement("span");
        ffLabel.className = "detail-label";
        ffLabel.textContent = "FREEZE FRAME";
        ff.appendChild(ffLabel);
        if (view.freezeFrame.hasFrame) {
          var grid = view.freezeFrame.grid;
          for (var k in grid) {
            if (Object.prototype.hasOwnProperty.call(grid, k)) {
              ff.appendChild(detailLine("detail-ff-cell", k, String(grid[k])));
            }
          }
        } else {
          ff.appendChild(detailLine("detail-ff-fallback", "", view.freezeFrame.fallbackText));
        }
        detailBody.appendChild(ff);

        // Severity-gated fix (S-4/F-1): directive for 🔴/🟡, real fix + badge for
        // 🟢, N/A for na.
        var fixBox = document.createElement("div");
        fixBox.className = "detail-fix";
        fixBox.setAttribute("data-mode", view.fix.mode);
        if (view.fix.mode === "fix") {
          var fixLabel = document.createElement("span");
          fixLabel.className = "detail-label";
          fixLabel.textContent = "SUGGESTED FIX";
          fixBox.appendChild(fixLabel);
          fixBox.appendChild(detailLine("detail-fix-text", "", view.fix.text));
          if (view.fix.badge) {
            var badge = document.createElement("span");
            badge.className = "dtc-trust-badge";
            badge.setAttribute("data-kind", view.fix.badge.kind);
            badge.textContent = view.fix.badge.label;
            fixBox.appendChild(badge);
          }
        } else {
          // directive / na -> the fix slot is REPLACED (never a raw fix).
          fixBox.appendChild(detailLine("dtc-fix-directive", "", view.fix.text));
        }
        detailBody.appendChild(fixBox);

        // Log/sync footer (the capture-before-clear precondition, made visible).
        var footer = detailLine(
          "detail-footer",
          "",
          (view.logged ? "✓ logged" : "· not yet logged") +
            " · " +
            (view.syncAcked ? "✓ synced to server" : "· sync pending")
        );
        detailBody.appendChild(footer);
      }

      function openDetail(codeObj) {
        var view = codeDetailView(codeObj);
        if (!view || !detailEl) return;
        renderDetailBody(view);
        renderClearButton();
        detailEl.hidden = false;
      }

      // --- US-407 clear surface (browser only) -------------------------------

      // Reflect the (display-mirror) gate onto the Clear button. No button when
      // nothing is clearable; disabled + reason label otherwise; enabled only on
      // `ok`. The server RE-CHECKS the gate on submit -- the button never forces.
      function renderClearButton() {
        if (!clearBtn) return;
        if (clearResult) clearResult.textContent = "";
        var view = clearButtonView(lastDtc);
        if (!view.visible) {
          clearBtn.hidden = true;
          return;
        }
        clearBtn.hidden = false;
        clearBtn.textContent = view.label;
        clearBtn.disabled = !view.enabled;
        clearBtn.setAttribute("data-reason", view.reason);
      }

      function showClearResult(msg) {
        if (!clearResult || !msg) return;
        clearResult.textContent = msg.text;
        clearResult.setAttribute("data-level", msg.level);
      }

      function hideClearConfirm() {
        if (clearConfirm) clearConfirm.hidden = true;
      }

      function openClearConfirm() {
        if (!clearConfirm) return;
        var copy = confirmClearText();
        if (clearConfirmTitle) clearConfirmTitle.textContent = copy.title;
        if (clearConfirmText) clearConfirmText.textContent = copy.body;
        if (clearConfirmOk) clearConfirmOk.textContent = copy.confirmLabel;
        if (clearConfirmCancel) clearConfirmCancel.textContent = copy.cancelLabel;
        clearConfirm.hidden = false;
      }

      // POST the clear request. The gate is re-checked SERVER-SIDE from its own
      // `dtc` state (never this request) -- a 403 means the server refused. The
      // result reports the re-read proof (or the re-set), never "command sent".
      function submitClear() {
        hideClearConfirm();
        fetch("/dtc-clear", {
          method: "POST",
          headers: { "X-Splash-Token": token, "Content-Type": "application/json" },
          body: JSON.stringify({ confirm: true }),
        })
          .then(function (r) {
            return r.json().then(
              function (j) { return { status: r.status, body: j }; },
              function () { return { status: r.status, body: {} }; }
            );
          })
          .then(function (res) {
            if (res.status === 200) {
              showClearResult(postClearMessage(res.body));
            } else {
              showClearResult({
                level: "blocked",
                text: "Clear refused — " + (res.body.reason || res.body.error || "not allowed"),
              });
            }
          })
          .then(null, function () {
            showClearResult({ level: "blocked", text: "Clear failed — no response" });
          });
      }

      if (clearBtn) {
        clearBtn.addEventListener("click", function () {
          if (!clearBtn.disabled) openClearConfirm();
        });
      }
      if (clearConfirmOk) clearConfirmOk.addEventListener("click", submitClear);
      if (clearConfirmCancel) {
        clearConfirmCancel.addEventListener("click", hideClearConfirm);
      }

      // --- US-406 Alerts card render (browser only) --------------------------

      function renderAlertsCard(card, view) {
        var body = card.querySelector(".card-body");
        if (!body || !view) return;
        // US-429 / Bug-3b: DTC source unavailable -> a typed NA, NOT "No stored
        // codes" (a false all-clear) and NOT a mis-fired takeover.
        if (view.unavailable) {
          renderNaBody(body, "ALERTS", view.reason);
          return;
        }
        body.textContent = "";

        // Header count line (stored · pending).
        var head = document.createElement("div");
        head.className = "dtc-count";
        head.textContent = view.storedCount + " stored · " + view.pendingCount + " pending";
        body.appendChild(head);

        // Hero block (worst code + its directive), when an alert-eligible code
        // exists (na-only / empty -> no hero).
        if (view.hero) {
          var heroEl = document.createElement("button");
          heroEl.className = "dtc-hero tap-target";
          heroEl.setAttribute("data-level", view.hero.level);
          var hChip = document.createElement("span");
          hChip.className = "dtc-chip";
          hChip.setAttribute("data-level", view.hero.level);
          hChip.textContent = view.hero.chip;
          heroEl.appendChild(hChip);
          var hCode = document.createElement("span");
          hCode.className = "dtc-hero-code";
          hCode.textContent = view.hero.code;
          heroEl.appendChild(hCode);
          var hShort = document.createElement("span");
          hShort.className = "dtc-hero-short";
          hShort.textContent = view.hero.short;
          heroEl.appendChild(hShort);
          var hDir = document.createElement("span");
          hDir.className = "dtc-hero-directive";
          hDir.textContent = view.hero.directive;
          heroEl.appendChild(hDir);
          (function (codeStr) {
            heroEl.addEventListener("click", function () { openAlertsCard(codeStr); });
          })(view.hero.code);
          body.appendChild(heroEl);
        } else if (view.rows.length === 0) {
          // No codes at all -> an honest all-clear (never a fabricated green).
          body.appendChild(detailLine("dtc-noalert", "", "No stored codes"));
        }

        // Compact tappable rows (worst-first, na last). Each opens the detail.
        for (var i = 0; i < view.rows.length; i++) {
          (function (r) {
            var row = document.createElement("button");
            row.className = "dtc-row tap-target";
            row.setAttribute("data-level", r.level);
            var rChip = document.createElement("span");
            rChip.className = "dtc-chip";
            rChip.setAttribute("data-level", r.level);
            rChip.textContent = r.chip;
            row.appendChild(rChip);
            var rCode = document.createElement("span");
            rCode.className = "dtc-row-code";
            rCode.textContent = r.code;
            row.appendChild(rCode);
            var rShort = document.createElement("span");
            rShort.className = "dtc-row-short";
            rShort.textContent = r.short + (r.caveat ? "  ⚠ " + r.caveat : "");
            row.appendChild(rShort);
            var rStatus = document.createElement("span");
            rStatus.className = "dtc-row-status";
            rStatus.textContent = r.status;
            row.appendChild(rStatus);
            row.addEventListener("click", function () { openDetail(findCode(r.code) || r); });
            body.appendChild(row);
          })(view.rows[i]);
        }
      }

      if (detailBack) detailBack.addEventListener("click", closeDetail);
      // The ribbon is tappable -> jump to the Alerts card + the hero detail.
      if (ribbonEl) {
        ribbonEl.addEventListener("click", function () {
          if (ribbonEl.hidden) return;
          var view = ribbonView(lastDtc);
          openAlertsCard(view ? view.code : null);
        });
      }

      // Apply the polled `dtc` state to the ribbon + takeover. A missing/malformed
      // `dtc` file -> no alert (honest: absence of the state = no active fault),
      // never a fabricated code.
      function updateDtcSurfaces(dtcData) {
        lastDtc = dtcData;
        renderRibbon(ribbonView(dtcData));
        var view = takeoverView(dtcData);
        if (view && takeoverShouldShow(view, dtcLastAckedTs)) {
          showTakeover(view);
        } else {
          hideTakeover();
        }
      }

      // US-481: render the idle card content from the states the tick already
      // fetched, then edge-trigger the home/auto-advance. The idle card ALWAYS
      // renders honest content (so it's ready when parked); navigation only
      // fires when `idle` changes -- to the idle card when idle becomes true,
      // to System Status when it flips false (Iris AC-4). The ribbon/takeover
      // are separate overlays that fire on TOP of any card, so surfacing the
      // calm idle card never suppresses a real fault (AC-5).
      function updateIdleHome(sysData, batteryData, dtcData) {
        if (idleCard) {
          renderIdleCard(idleCard, idleCardView(sysData, batteryData, dtcData), new Date());
        }
        var idle = carouselIdle(sysData);
        if (idle === lastIdle) return; // edge-trigger only -- never trap a swipe
        if (idle) {
          if (idleIndex >= 0) goTo(idleIndex);
        } else if (sysIndex >= 0) {
          goTo(sysIndex);
        }
        lastIdle = idle;
      }

      async function tick() {
        var dtcData = null; // fetched once (the Alerts card + ribbon/takeover share it)
        var sysData = null; // shared with the idle-home card (one fetch per tick)
        var batteryData = null;
        for (var c = 0; c < cards.length; c++) {
          var card = cards[c];
          var name = card.getAttribute("data-state");
          if (!name) continue;
          var data = await fetchState(name);
          if (name === "dtc") dtcData = data;
          else if (name === "system-status") sysData = data;
          else if (name === "battery-health") batteryData = data;
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
          } else if (name === "battery-health") {
            var bv = batteryHealthView(data);
            if (bv) renderBatteryHealthCard(card, bv);
          } else if (name === "dtc") {
            renderAlertsCard(card, alertsCardView(data));
          } else if (name === "ltft-trend") {
            var lv = ltftTrendView(data);
            if (lv) renderLtftTrendCard(card, lv);
          }
        }
        // US-405/US-406: drive the takeover + persistent ribbon from the same
        // `dtc` state the Alerts card rendered (one fetch per tick).
        updateDtcSurfaces(dtcData);
        // US-481: render the idle-home card + edge-trigger home/auto-advance
        // from the same fetched states (no extra fetch, no second OBD touch).
        updateIdleHome(sysData, batteryData, dtcData);
        // US-490: track the parked/live context every tick from the SAME fetched
        // state (no extra fetch). An unavailable system-status leaves sysData
        // null here, which fails closed to a hidden ⋮ -- long-press still opens.
        updateMenuAccess(sysData);
        // US-483-b: drive the display brightness from the states/light feed
        // (pure consumer -- never the sensor). A real STOP holds it >= the alarm
        // floor; an absent/stale feed holds the fixed default (honest fallback).
        var lightData = await fetchState("light");
        applyBrightness(
          brightnessLevel(
            lightData,
            displayAutoDim,
            Date.now(),
            brightnessAlarmActive(dtcData)
          )
        );
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

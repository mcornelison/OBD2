/**
 * File:    touch_swipe_probe.mjs
 * Purpose: US-746 -- drive the SHIPPED dashboard in a REAL Chromium with REAL
 *          touch input and report where each gesture ends up.
 *
 *          Why a real engine, when mini_dom already boots carousel.js: the
 *          regression lived in the CSS cascade's touch-action, which decides
 *          whether the BROWSER claims a drag as a pan (-> pointercancel, no
 *          pointerup). mini_dom has no touch-action and delivers any pointerup
 *          it is handed, so every harness test stayed green through it. CDP
 *          Input.dispatchTouchEvent runs through the renderer's touch-action
 *          filter and gesture detector, which is the layer that failed.
 *
 *          Input:  JSON file path argv[2]:
 *                  {html, chrome, scenarios:[{css?, selector, kind, dx, dy, ms}]}
 *                  kind: "touch" (drag) | "tap"
 *          Output: {version, results:[{index0, index1, counts, startTouchAction}]}
 *                  on stdout. A browser that will not start exits non-zero.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-09-14 -- Sprint 86 US-746
 */
import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const input = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const PORT = 9300 + Math.floor(Math.random() * 600);
const PROFILE = fs.mkdtempSync(path.join(os.tmpdir(), "us746-"));
const BOOT_SETTLE_MS = 1200;   // carousel.js builds the dots after load
const GESTURE_SETTLE_MS = 400; // > the 0.25 s #track transition
const MOVE_STEPS = 12;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const chrome = spawn(input.chrome, [
  "--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${PROFILE}`,
  "--window-size=480,320", "--no-first-run", "--allow-file-access-from-files", "about:blank",
]);

function finish(code, payload) {
  if (payload) process.stdout.write(JSON.stringify(payload));
  try { chrome.kill(); } catch {}
  try { fs.rmSync(PROFILE, { recursive: true, force: true }); } catch {}
  process.exit(code);
}

async function pageSocketUrl() {
  for (let i = 0; i < 150; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(100);
  }
  throw new Error("chrome did not expose a page target");
}

let ws;
let seq = 0;
const pending = new Map();
const eventWaiters = [];

function send(method, params = {}) {
  return new Promise((res, rej) => {
    const id = ++seq;
    pending.set(id, { res, rej });
    ws.send(JSON.stringify({ id, method, params }));
  });
}

async function evaluate(expression) {
  const out = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  return out.result.value;
}

const INSTRUMENT = `(() => {
  window.__us746 = {};
  ["pointerdown", "pointerup", "pointercancel"].forEach((t) =>
    window.addEventListener(t, () => { window.__us746[t] = (window.__us746[t] || 0) + 1; }, true));
  return true;
})()`;
const ACTIVE_INDEX = `[...document.querySelectorAll("#dots .dot")].findIndex((d) => d.classList.contains("active"))`;
const startPoint = (selector) => `(() => {
  const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find((e) => {
    const r = e.getBoundingClientRect(); return r.width > 0 && r.left >= -1 && r.left < 470; });
  if (!el) return null;
  const r = el.getBoundingClientRect();
  return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + Math.min(r.height / 2, 40)),
           touchAction: getComputedStyle(el).touchAction };
})()`;

async function load(css) {
  const loaded = new Promise((resolve) => {
    eventWaiters.push(function wait(m) {
      if (m.method === "Page.loadEventFired") resolve();
      else eventWaiters.push(wait);
    });
  });
  await send("Page.navigate", { url: pathToFileURL(input.html).href });
  await loaded;
  await sleep(BOOT_SETTLE_MS);
  if (css) {
    await evaluate(`(() => { const s = document.createElement("style");
      s.textContent = ${JSON.stringify(css)}; document.head.appendChild(s); return true; })()`);
  }
  await evaluate(INSTRUMENT);
}

async function touchDrag(x, y, dx, dy, ms, steps) {
  await send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y, id: 1 }] });
  for (let i = 1; i <= steps; i++) {
    await sleep(ms / steps);
    await send("Input.dispatchTouchEvent", {
      type: "touchMove",
      touchPoints: [{ x: Math.round(x + (dx * i) / steps), y: Math.round(y + (dy * i) / steps), id: 1 }],
    });
  }
  await send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
}

try {
  ws = new WebSocket(await pageSocketUrl());
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  ws.addEventListener("message", (m) => {
    const msg = JSON.parse(m.data);
    if (msg.id && pending.has(msg.id)) {
      const { res, rej } = pending.get(msg.id);
      pending.delete(msg.id);
      if (msg.error) rej(new Error(JSON.stringify(msg.error)));
      else res(msg.result);
    } else if (msg.method) {
      for (const w of eventWaiters.splice(0)) w(msg);
    }
  });
  await send("Page.enable");
  await send("Runtime.enable");
  await send("Emulation.setDeviceMetricsOverride", { width: 480, height: 320, deviceScaleFactor: 1, mobile: false });
  await send("Emulation.setTouchEmulationEnabled", { enabled: true, maxTouchPoints: 5 });

  const results = [];
  for (const s of input.scenarios) {
    await load(s.css);
    const start = await evaluate(startPoint(s.selector));
    if (!start) throw new Error("no on-screen element matches " + s.selector);
    const index0 = await evaluate(ACTIVE_INDEX);
    if (s.kind === "tap") await touchDrag(start.x, start.y, 0, 0, 40, 1);
    else await touchDrag(start.x, start.y, s.dx, s.dy, s.ms, MOVE_STEPS);
    await sleep(GESTURE_SETTLE_MS);
    results.push({
      dots: await evaluate(`document.querySelectorAll("#dots .dot").length`),
      index0,
      index1: await evaluate(ACTIVE_INDEX),
      counts: await evaluate("window.__us746"),
      startTouchAction: start.touchAction,
    });
  }
  const version = (await send("Browser.getVersion")).product;
  finish(0, { version, results });
} catch (err) {
  process.stderr.write(String(err && err.stack ? err.stack : err));
  finish(2, null);
}

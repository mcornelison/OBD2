/* ============================================================================
 * File:    mini_dom.js
 * Purpose: US-499 (S6, F-121) render-regression backstop -- the DOM object
 *          model the SHIPPED browser JS runs against under node.
 *
 *          There is no jsdom in this repo and no npm install on the Pi/dev
 *          path, so this is the "closest faithful harness" the story's
 *          conditionalOutcome allows. It implements ONLY the DOM surface the
 *          shipped kits actually touch (enumerated from carousel.js +
 *          boot-state-poll.js, not guessed): textContent, appendChild,
 *          setAttribute/getAttribute/removeAttribute, addEventListener,
 *          querySelector(All), classList, style.setProperty, and the
 *          hidden/className/id/disabled/title/onclick IDL properties.
 *
 *          THE LOAD-BEARING BEHAVIOUR is IDL-to-content-attribute REFLECTION:
 *          `el.hidden = true` must show up as the `hidden` ATTRIBUTE, because
 *          the attribute is what the CSS cascade selects on. US-495's defect
 *          lived exactly in that seam -- the JS set the property correctly and
 *          the stylesheet ignored it -- so a harness that stored `hidden` as a
 *          private flag would reproduce the bug's blind spot instead of
 *          catching it.
 *
 *          The tree goes IN as JSON (parsed from the shipped markup by
 *          render_harness.py) and comes OUT as JSON after the real JS has run.
 *          This module makes no rendering decisions whatsoever -- it does not
 *          know what `display` is. Python owns the cascade. Neither half can
 *          launder the other's verdict.
 *
 *          Timers are VIRTUAL: setTimeout/setInterval queue into rounds the
 *          driver flushes a bounded number of times, so a self-rescheduling
 *          poll loop (carousel.js `tick`) terminates instead of hanging.
 * Author:  Ralph Agent (Rex)
 * Created: 2026-07-29 -- Sprint 66 US-499 (S6 render-regression backstop)
 * Updated: 2026-08-31 -- US-638: createElementNS, so the LIVE home face renders
 *          instead of throwing. Additive; no existing behaviour changed.
 * ==========================================================================*/
"use strict";

// --- selector matching (compound simple selectors only; see FIDELITY LIMIT) --
// querySelector in the shipped kits is only ever called with a single class or
// tag (".card-body", ".ribbon-text", ...). Anything richer returns no match
// rather than a wrong match -- an honest miss, never a fabricated hit.
function matchesCompound(el, selector) {
  var parts = selector.trim().match(/\[[^\]]*\]|[#.]?[\w-]+/g);
  if (!parts) return false;
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i];
    if (p[0] === "#") {
      if (el.getAttribute("id") !== p.slice(1)) return false;
    } else if (p[0] === ".") {
      if (!el.classList.contains(p.slice(1))) return false;
    } else if (p[0] === "[") {
      var name = /\[\s*([\w-]+)/.exec(p);
      if (!name || !el.hasAttribute(name[1])) return false;
    } else if (p.toLowerCase() !== el.tagName.toLowerCase()) {
      return false;
    }
  }
  return true;
}

function reflectBoolean(proto, prop) {
  Object.defineProperty(proto, prop, {
    get: function () {
      return this.hasAttribute(prop);
    },
    set: function (value) {
      if (value) this.setAttribute(prop, "");
      else this.removeAttribute(prop);
    },
  });
}

function reflectString(proto, prop, attrName) {
  Object.defineProperty(proto, prop, {
    get: function () {
      return this.getAttribute(attrName) || "";
    },
    set: function (value) {
      this.setAttribute(attrName, String(value));
    },
  });
}

function ClassList(el) {
  this._el = el;
}
ClassList.prototype._read = function () {
  var raw = this._el.getAttribute("class") || "";
  return raw.split(/\s+/).filter(Boolean);
};
ClassList.prototype._write = function (list) {
  this._el.setAttribute("class", list.join(" "));
};
ClassList.prototype.contains = function (name) {
  return this._read().indexOf(name) !== -1;
};
ClassList.prototype.add = function (name) {
  var list = this._read();
  if (list.indexOf(name) === -1) list.push(name);
  this._write(list);
};
ClassList.prototype.remove = function (name) {
  this._write(
    this._read().filter(function (c) {
      return c !== name;
    })
  );
};
ClassList.prototype.toggle = function (name, force) {
  var want = force === undefined ? !this.contains(name) : !!force;
  if (want) this.add(name);
  else this.remove(name);
  return want;
};

// Inline style. Real CSS wins/loses against inline declarations by IMPORTANCE,
// so the cascade in render_harness.py needs these verbatim -- they are kept as
// a plain property bag and serialized out with the element.
function Style() {
  this._props = {};
}
Style.prototype.setProperty = function (name, value) {
  this._props[name] = String(value);
};
Style.prototype.getPropertyValue = function (name) {
  return this._props[name] || "";
};
["transform", "opacity", "transition", "display", "visibility", "width"].forEach(
  function (prop) {
    Object.defineProperty(Style.prototype, prop, {
      get: function () {
        return this._props[prop] || "";
      },
      set: function (value) {
        this._props[prop] = String(value);
      },
    });
  }
);

function TextNode(text) {
  this.nodeType = 3;
  this.text = text;
  this.parentNode = null;
}

function Element(tagName, doc) {
  this.nodeType = 1;
  this.tagName = tagName;
  this.ownerDocument = doc;
  this.attributes = {};
  this.childNodes = [];
  this.parentNode = null;
  this.classList = new ClassList(this);
  this.style = new Style();
  this._listeners = {};
  this.onclick = null;
}

Element.prototype.hasAttribute = function (name) {
  return Object.prototype.hasOwnProperty.call(this.attributes, name);
};
Element.prototype.getAttribute = function (name) {
  return this.hasAttribute(name) ? this.attributes[name] : null;
};
Element.prototype.setAttribute = function (name, value) {
  var hadId = name === "id";
  this.attributes[name] = value === undefined ? "" : String(value);
  if (hadId && this.ownerDocument) this.ownerDocument._index(this);
};
Element.prototype.removeAttribute = function (name) {
  delete this.attributes[name];
};

Element.prototype.appendChild = function (child) {
  if (child.parentNode) child.parentNode.removeChild(child);
  child.parentNode = this;
  this.childNodes.push(child);
  if (this.ownerDocument && child.nodeType === 1) {
    this.ownerDocument._indexTree(child);
  }
  return child;
};
Element.prototype.removeChild = function (child) {
  var i = this.childNodes.indexOf(child);
  if (i !== -1) this.childNodes.splice(i, 1);
  child.parentNode = null;
  return child;
};

Object.defineProperty(Element.prototype, "children", {
  get: function () {
    return this.childNodes.filter(function (n) {
      return n.nodeType === 1;
    });
  },
});

Object.defineProperty(Element.prototype, "textContent", {
  get: function () {
    return this.childNodes
      .map(function (n) {
        return n.nodeType === 3 ? n.text : n.textContent;
      })
      .join("");
  },
  set: function (value) {
    this.childNodes = [];
    if (value !== "" && value != null) this.appendChild(new TextNode(String(value)));
  },
});

reflectBoolean(Element.prototype, "hidden");
reflectBoolean(Element.prototype, "disabled");
reflectString(Element.prototype, "className", "class");
reflectString(Element.prototype, "id", "id");
reflectString(Element.prototype, "title", "title");

Element.prototype._walk = function (visit) {
  for (var i = 0; i < this.childNodes.length; i++) {
    var child = this.childNodes[i];
    if (child.nodeType !== 1) continue;
    visit(child);
    child._walk(visit);
  }
};
Element.prototype.querySelectorAll = function (selector) {
  var found = [];
  this._walk(function (el) {
    if (matchesCompound(el, selector)) found.push(el);
  });
  return found;
};
Element.prototype.querySelector = function (selector) {
  return this.querySelectorAll(selector)[0] || null;
};

Element.prototype.addEventListener = function (type, fn) {
  (this._listeners[type] = this._listeners[type] || []).push(fn);
};
Element.prototype.dispatch = function (type, event) {
  var ev = event || {};
  ev.type = type;
  var list = (this._listeners[type] || []).slice();
  for (var i = 0; i < list.length; i++) list[i].call(this, ev);
  if (type === "click" && typeof this.onclick === "function") this.onclick(ev);
};
Element.prototype.click = function () {
  this.dispatch("click", {});
};

// --- document -----------------------------------------------------------
function Document() {
  this._byId = {};
  this.readyState = "complete";
  this._listeners = {};
  this.documentElement = new Element("html", this);
  this.body = new Element("body", this);
  this.documentElement.appendChild(this.body);
}
Document.prototype._index = function (el) {
  var id = el.getAttribute("id");
  if (id) this._byId[id] = el;
};
Document.prototype._indexTree = function (el) {
  this._index(el);
  var self = this;
  el._walk(function (child) {
    self._index(child);
  });
};
Document.prototype.createElement = function (tagName) {
  return new Element(tagName, this);
};
// US-638. An SVG element differs from an HTML one only in the namespace it
// carries, and nothing downstream of this harness resolves namespaced CSS -- so
// it is an ordinary Element that REMEMBERS its namespace.
//
// WHY IT IS NOT OPTIONAL. `svgEl` (carousel.js) is the FIRST call
// `renderLiveBody` makes, so without this the LIVE home face does not merely
// render imperfectly, it THROWS -- and the crash leaves an empty card body.
// Every "X is not on the live face" assertion would then pass by way of the
// harness failing, which is the lenient-test failure render_harness.py's own
// header warns about. Measured before adding it: the live face rendered NOTHING
// at all, and a characterisation test for a real finding was reading that
// emptiness as evidence.
Document.prototype.createElementNS = function (namespaceURI, tagName) {
  var el = new Element(tagName, this);
  el.namespaceURI = namespaceURI;
  return el;
};
Document.prototype.getElementById = function (id) {
  return this._byId[id] || null;
};
Document.prototype.querySelector = function (selector) {
  return this.documentElement.querySelector(selector);
};
Document.prototype.querySelectorAll = function (selector) {
  return this.documentElement.querySelectorAll(selector);
};
Document.prototype.addEventListener = Element.prototype.addEventListener;
Document.prototype.dispatch = Element.prototype.dispatch;

// Build the element tree from the JSON render_harness.py parsed out of the
// SHIPPED markup. `hidden` etc. arrive as real attributes, exactly as the
// browser would have them after parsing the same file.
function buildTree(doc, spec, parent) {
  if (spec.text !== undefined) {
    parent.appendChild(new TextNode(spec.text));
    return;
  }
  var el = doc.createElement(spec.tag);
  Object.keys(spec.attrs || {}).forEach(function (name) {
    el.setAttribute(name, spec.attrs[name] === null ? "" : spec.attrs[name]);
  });
  parent.appendChild(el);
  (spec.children || []).forEach(function (child) {
    buildTree(doc, child, el);
  });
}

function serialize(node) {
  if (node.nodeType === 3) return { text: node.text };
  var out = {
    tag: node.tagName,
    attrs: Object.assign({}, node.attributes),
    children: node.childNodes.map(serialize),
  };
  var inline = node.style._props;
  if (Object.keys(inline).length) out.style = Object.assign({}, inline);
  return out;
}

// --- virtual clock ------------------------------------------------------
// Rounds, not a real clock: flushRound() fires exactly the callbacks queued so
// far. A self-rescheduling poll (carousel.js `tick`) therefore advances one
// iteration per round and the driver stays in control of when it stops.
function Clock() {
  this._queue = [];
  this._nextId = 1;
  this._intervals = {};
}
Clock.prototype.setTimeout = function (fn) {
  var id = this._nextId++;
  this._queue.push({ id: id, fn: fn });
  return id;
};
Clock.prototype.clearTimeout = function (id) {
  this._queue = this._queue.filter(function (t) {
    return t.id !== id;
  });
};
Clock.prototype.setInterval = function (fn) {
  var id = this._nextId++;
  this._intervals[id] = fn;
  return id;
};
Clock.prototype.clearInterval = function (id) {
  delete this._intervals[id];
};
Clock.prototype.flushRound = function () {
  var due = this._queue;
  this._queue = [];
  for (var i = 0; i < due.length; i++) due[i].fn();
  var self = this;
  Object.keys(this._intervals).forEach(function (id) {
    self._intervals[id]();
  });
};

// Let every pending promise continuation run. The shipped polls are `async`
// and await fetch, so the DOM writes land in microtasks, not in the timer
// callback itself -- draining is what makes the snapshot truthful.
async function drainMicrotasks(cycles) {
  for (var i = 0; i < (cycles || 8); i++) {
    await new Promise(function (resolve) {
      setImmediate(resolve);
    });
  }
}

// A fetch that answers ONLY from a fixture map: an unlisted route 404s rather
// than resolving to something plausible. A test must state every state file it
// wants to exist; nothing is invented on its behalf.
function makeFetch(routes, log) {
  return function (url, options) {
    if (log) log.push({ url: url, method: (options && options.method) || "GET" });
    var key = String(url).split("?")[0];
    if (!Object.prototype.hasOwnProperty.call(routes, key)) {
      return Promise.resolve({ ok: false, status: 404, json: notJson, text: notText });
    }
    var body = routes[key];
    if (body === null) {
      return Promise.resolve({ ok: false, status: 404, json: notJson, text: notText });
    }
    return Promise.resolve({
      ok: true,
      status: 200,
      json: function () {
        return Promise.resolve(body);
      },
      text: function () {
        return Promise.resolve(typeof body === "string" ? body : JSON.stringify(body));
      },
    });
  };
}
function notJson() {
  return Promise.reject(new Error("no body"));
}
function notText() {
  return Promise.reject(new Error("no body"));
}

module.exports = {
  Document: Document,
  Element: Element,
  Clock: Clock,
  buildTree: buildTree,
  serialize: serialize,
  drainMicrotasks: drainMicrotasks,
  makeFetch: makeFetch,
};

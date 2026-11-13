/* The mock OS: one state object, one way to change it, and a snapshot of what is on screen.

   Python drives this page over CDP (typesafe_computer_use/mockos/desktop.py). It loads a task's
   starting state with `load`, reads the state back with `dump` for the task's check, and reads the
   screen with `hold`/`release` around each screenshot. Everything the apps do goes through
   `dispatch`, which appends to `state.log`, so a failed check can be read back from the log.

   Determinism: the clock is the seed's and never the real one; randomness is a seeded generator;
   every delay goes through `after`, which draws from that generator. Two loads of one seed, driven
   the same way, give the same screens. */
"use strict";

const MockOS = (function () {
  const { h } = Kit;
  const DISPLAY = { w: 1440, h: 900 };
  const BAR_H = 40; // models.MENU_BAR_PT: the loop leaves this strip out of change detection
  const OFFSCREEN_Y = -4200; // where a control scrolled out of its pane is parked, as Chromium parks one
  const apps = {}; // name -> {pid, frame, title(state), render(state), key(state, event), reduce(state, action), initial()}
  const parts = {}; // scope -> {reduce(state, action), initial()}: every app, and every fake site in the browser

  let state = null;
  let random = null;
  let latency = "typical";
  let held = false;
  let deferred = [];
  let timers = [];
  let scrollTo = null; // an element key to bring into view on the next render, once
  let rendering = false; // a field removed by a render blurs, and that blur is no user's
  const ids = new WeakMap();
  const byId = new Map();
  let nextId = 1;
  let snapshots = 0;

  // ----- determinism ------------------------------------------------------------------------

  function generator(seed) {
    // mulberry32: small, fast, and the same in every browser
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // A delay an app takes before showing what an action did, in ms, from the pass's latency
  // profile: none at all, the typical spread, or a slow page's spinner.
  function delay(low, high, slow) {
    if (latency === "instant") return 0;
    const ms = low + random() * (high - low);
    return Math.round(latency === "slow" && slow ? ms * 6 : ms);
  }

  // The only timer an app may use. A callback that comes due while a snapshot holds the
  // scheduler waits for the release, so the pixels, the text and the controls of one snapshot
  // all describe the same instant.
  function after(ms, fn) {
    if (ms <= 0) {
      fn();
      return;
    }
    const id = setTimeout(() => {
      timers = timers.filter((t) => t !== id);
      if (held) deferred.push(fn);
      else fn();
    }, ms);
    timers.push(id);
  }

  // ----- state ------------------------------------------------------------------------------

  function load(seed, options) {
    for (const id of timers) clearTimeout(id);
    timers = [];
    deferred = [];
    held = false;
    state = JSON.parse(JSON.stringify(seed));
    state.running = state.running || [state.front];
    state.clipboard = state.clipboard || "";
    state.overlay = null;
    state.log = [];
    for (const [scope, part] of Object.entries(parts)) if (part.initial && !(scope in state)) state[scope] = part.initial();
    random = generator(state.rng || 1);
    latency = (options && options.latency) || "typical";
    scrollTo = null;
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
    render();
    return true;
  }

  function dump() {
    return JSON.parse(JSON.stringify(state));
  }

  function dispatch(action) {
    state.log.push(JSON.parse(JSON.stringify(action)));
    if (action.picked) state.overlay = null; // an item picked from a menu closes the menu
    const [scope] = action.type.split(".");
    if (scope === "os") reduce(action);
    else if (parts[scope] && parts[scope].reduce) parts[scope].reduce(state, action);
    render();
  }

  function reduce(action) {
    if (action.type === "os.launch") {
      if (!state.running.includes(action.app)) state.running.push(action.app);
      state.front = action.app;
      state.overlay = null;
    } else if (action.type === "os.menu") {
      state.overlay = { kind: "menu", x: action.x, y: action.y, w: action.w, items: action.items };
    } else if (action.type === "os.close") {
      state.overlay = null;
    }
  }

  function launch(app) {
    if (!apps[app]) return false;
    dispatch({ type: "os.launch", app });
    return true;
  }

  // A menu the page draws, below `anchor`, of items {label, checked, action}. Picking one
  // dispatches its action; a click anywhere else closes it, as on a Mac, without acting.
  function openMenu(anchor, items) {
    const r = anchor.getBoundingClientRect();
    dispatch({ type: "os.menu", x: Math.round(r.left), y: Math.round(r.bottom + 4), w: Math.round(r.width), items });
  }

  // A context menu at the point a right click landed.
  function openMenuAt(x, y, items) {
    dispatch({ type: "os.menu", x: Math.round(x), y: Math.round(y), w: 0, items });
  }

  // ----- dragging -----------------------------------------------------------------------------
  // A drag is a press on an element made with `Kit.draggable`, a move, and a release over an
  // element made with `Kit.dropTarget`: the drop's action is dispatched with the drag's payload.
  // It is built from mouse events, which CDP's input events raise; HTML5 drag and drop is not.

  let dragging = null;

  function startDrag(event, payload) {
    if (event.button !== 0) return;
    dragging = { payload, x: event.clientX, y: event.clientY, moved: false };
  }

  function onMouseMove(event) {
    if (dragging && Math.hypot(event.clientX - dragging.x, event.clientY - dragging.y) > 6) dragging.moved = true;
  }

  function onMouseUp(event) {
    const drag = dragging;
    dragging = null;
    if (!drag || !drag.moved) return;
    const target = paintedAt(event.clientX, event.clientY);
    const drop = target && target.closest("[data-drop]");
    if (drop) dispatch({ ...JSON.parse(drop.dataset.drop), ...drag.payload });
  }

  function reveal(key) {
    scrollTo = key;
  }

  // ----- drawing ----------------------------------------------------------------------------

  function render() {
    const root = document.getElementById("desktop");
    const active = document.activeElement;
    const focusKey = active && active.dataset ? active.dataset.key : null;
    const selection = focusKey && typeof active.selectionStart === "number" ? [active.selectionStart, active.selectionEnd] : null;
    const scrolls = {};
    for (const el of root.querySelectorAll("[data-key]")) if (el.scrollTop) scrolls[el.dataset.key] = el.scrollTop;

    rendering = true;
    try {
      root.replaceChildren(bar(), ...windows(), dock(), ...overlay());
    } finally {
      rendering = false;
    }

    for (const [key, top] of Object.entries(scrolls)) {
      const el = keyed(key);
      if (el) el.scrollTop = top;
    }
    if (focusKey) {
      let el = keyed(focusKey);
      // The focused text field is kept, not rebuilt: it stays the element the loop holds a
      // reference to, so a value set through accessibility reads back from the same element.
      if (el && el !== active && (active.tagName === "INPUT" || active.tagName === "TEXTAREA") && el.tagName === active.tagName) {
        if (active.value !== el.value) active.value = el.value;
        el.replaceWith(active);
        el = active;
      }
      if (el) {
        el.focus({ preventScroll: true });
        if (selection && el.setSelectionRange) el.setSelectionRange(selection[0], selection[1]);
      }
    }
    // A field that appears to be typed into at once, as a name being edited does, takes the focus once.
    const wants = root.querySelector("[data-autofocus]");
    if (wants && document.activeElement !== wants && !wants.dataset.focused) {
      wants.focus({ preventScroll: true });
      if (wants.select) wants.select();
    }
    if (wants) wants.dataset.focused = "1";
    if (scrollTo) {
      const el = keyed(scrollTo);
      scrollTo = null;
      if (el) el.scrollIntoView({ block: "center" });
    }
  }

  function keyed(key) {
    return document.querySelector(`[data-key="${CSS.escape(key)}"]`);
  }

  function bar() {
    return h(
      "div",
      { class: "bar" },
      h("span", { class: "mark" }, "◆"),
      h("span", { class: "front" }, state.front),
      h("span", { class: "clock" }, clockText(state.clock)),
    );
  }

  function clockText(iso) {
    const [day, time] = iso.split("T");
    const d = new Date(`${day}T00:00:00Z`);
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${days[d.getUTCDay()]} ${months[d.getUTCMonth()]} ${d.getUTCDate()}  ${time.slice(0, 5)}`;
  }

  function windows() {
    const order = state.running.filter((name) => name !== state.front && apps[name]).concat(apps[state.front] ? [state.front] : []);
    return order.map((name) => {
      const app = apps[name];
      const [x, y, w, hgt] = app.frame;
      return h(
        "div",
        {
          class: name === state.front ? "window" : "window back",
          "data-app": name,
          role: "window",
          "aria-label": app.title(state),
          style: `left:${x}px;top:${y}px;width:${w}px;height:${hgt}px`,
          onmousedown: name === state.front ? null : () => launch(name),
        },
        h(
          "div",
          { class: "titlebar" },
          h("div", { class: "lights", "aria-hidden": "true" }, h("span"), h("span"), h("span")),
          h("span", { class: "title" }, app.title(state)),
        ),
        app.render(state),
      );
    });
  }

  function dock() {
    return h(
      "div",
      { class: "dock" },
      Object.keys(apps).map((name) =>
        h("div", { class: state.running.includes(name) ? "tile running" : "tile", title: null, onclick: () => launch(name) }, name.slice(0, 2)),
      ),
    );
  }

  function overlay() {
    const o = state.overlay;
    if (!o || o.kind !== "menu") return [];
    const close = () => dispatch({ type: "os.close" });
    return [
      h("div", { class: "backdrop", "data-see-through": "", onclick: close }),
      h(
        "div",
        { class: "menu", role: "menu", "aria-label": "", style: `left:${o.x}px;top:${o.y}px;min-width:${Math.max(160, o.w)}px` },
        o.items.map((item) =>
          h(
            "div",
            {
              class: item.disabled ? "mi disabled" : "mi",
              role: "menuitem",
              "aria-label": item.label,
              "aria-disabled": item.disabled ? "true" : null,
              onclick: Kit.own(() => (item.disabled ? null : dispatch({ ...item.action, picked: true }))),
            },
            h("span", { class: "check" }, item.checked ? "✓" : ""),
            h("span", {}, item.label),
          ),
        ),
      ),
    ];
  }

  // ----- the keyboard -----------------------------------------------------------------------

  function onKey(event) {
    if (state.overlay) {
      if (event.key === "Escape") {
        event.preventDefault();
        dispatch({ type: "os.close" });
      }
      return;
    }
    const app = apps[state.front];
    if (app && app.key) app.key(state, event);
  }

  // ----- the snapshot -----------------------------------------------------------------------

  function idOf(el) {
    let id = ids.get(el);
    if (!id) {
      id = nextId++;
      ids.set(el, id);
      byId.set(id, el);
    }
    return id;
  }

  function element(id) {
    const el = byId.get(id);
    return el && el.isConnected ? el : null;
  }

  const ROLES = {
    button: "AXButton",
    link: "AXLink",
    checkbox: "AXCheckBox",
    switch: "AXCheckBox",
    radio: "AXRadioButton",
    radiogroup: "AXRadioGroup",
    textbox: "AXTextField",
    searchbox: "AXSearchField",
    tab: "AXTab",
    tablist: "AXTabGroup",
    menuitem: "AXMenuItem",
    row: "AXRow",
    cell: "AXCell",
    list: "AXList",
    slider: "AXSlider",
    img: "AXImage",
    group: "AXGroup",
    dialog: "AXSheet",
    window: "AXWindow",
    // An open menu is walked like any group. A closed one would be AXMenu, which the walk skips.
    menu: "AXGroup",
  };
  const PRESSABLE = new Set(["AXButton", "AXLink", "AXCheckBox", "AXRadioButton", "AXTab", "AXMenuItem", "AXRow", "AXCell", "AXPopUpButton"]);
  const LABELLED_BY_TEXT = new Set(["AXButton", "AXLink", "AXTab", "AXMenuItem", "AXRadioButton"]);

  function axRole(el) {
    const role = el.getAttribute("role");
    if (el.tagName === "INPUT" && el.type === "password") return "AXSecureTextField";
    if (el.tagName === "TEXTAREA") return "AXTextArea";
    if (role === "button" && el.hasAttribute("aria-haspopup")) return "AXPopUpButton";
    if (role) return ROLES[role] || null;
    if (el.tagName === "BUTTON") return "AXButton";
    if (el.tagName === "A" && el.hasAttribute("href")) return "AXLink";
    if (el.tagName === "INPUT") return "AXTextField";
    return null;
  }

  function squash(text) {
    return text.replace(/\s+/g, " ").trim();
  }

  function axLabel(el, role) {
    const label = el.getAttribute("aria-label");
    if (label !== null) return squash(label);
    return LABELLED_BY_TEXT.has(role) ? squash(el.textContent || "") : "";
  }

  function hidden(el) {
    if (el.getAttribute("aria-hidden") === "true") return true;
    const style = getComputedStyle(el);
    return style.display === "none" || style.visibility === "hidden";
  }

  function intersect(a, b) {
    const x1 = Math.max(a.x1, b.x1), y1 = Math.max(a.y1, b.y1), x2 = Math.min(a.x2, b.x2), y2 = Math.min(a.y2, b.y2);
    return { x1, y1, x2, y2, empty: x2 <= x1 || y2 <= y1 };
  }

  function box(rect) {
    return { x1: rect.left, y1: rect.top, x2: rect.right, y2: rect.bottom };
  }

  function clipped(el, clip) {
    const style = getComputedStyle(el);
    if (style.overflowX === "visible" && style.overflowY === "visible") return clip;
    return intersect(clip, box(el.getBoundingClientRect()));
  }

  function round(v) {
    return Math.round(v * 10) / 10;
  }

  // Where a control is, in screen points: its box cut to the panes that scroll it, or parked off
  // the display when it is scrolled out of them altogether.
  function frameOf(rect, clip) {
    if (rect.width <= 0 || rect.height <= 0) return [round(rect.left), round(rect.top), 0, 0];
    const seen = intersect(clip, box(rect));
    if (seen.empty) return [round(rect.left), OFFSCREEN_Y, round(rect.width), round(rect.height)];
    return [round(seen.x1), round(seen.y1), round(seen.x2 - seen.x1), round(seen.y2 - seen.y1)];
  }

  // The front window, and the menu over it, as a tree of {id, role, label, frame, press, children}.
  // An element with no role is no node: its children stand in its place.
  function tree(el, clip) {
    if (hidden(el)) return [];
    const role = axRole(el);
    const inner = clipped(el, clip);
    const children = [];
    for (const child of el.childNodes) {
      if (child.nodeType === Node.TEXT_NODE) {
        const text = squash(child.data);
        if (!text || el.tagName === "TEXTAREA") continue;
        const range = document.createRange();
        range.selectNodeContents(child);
        children.push({ id: 0, role: "AXStaticText", label: text, frame: frameOf(range.getBoundingClientRect(), inner), press: false, children: [] });
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        children.push(...tree(child, inner));
      }
    }
    if (!role) return children;
    return [
      {
        id: idOf(el),
        role,
        label: axLabel(el, role),
        frame: frameOf(el.getBoundingClientRect(), clip),
        press: PRESSABLE.has(role),
        children,
      },
    ];
  }

  // What is painted at a point, past the layers that only catch clicks.
  function paintedAt(x, y) {
    for (const el of document.elementsFromPoint(x, y)) if (!el.hasAttribute("data-see-through")) return el;
    return null;
  }

  function visibleAt(owner, x1, y1, x2, y2) {
    const hit = paintedAt((x1 + x2) / 2, (y1 + y2) / 2);
    return hit !== null && (hit === owner || owner.contains(hit) || hit.contains(owner));
  }

  // Every rendered line of text with its box: one entry per line of each text node, the value or
  // placeholder of a text field at the field, dots for a password, nothing for an icon. A line
  // something else paints over, or one scrolled out of its pane, is left out.
  function lines() {
    const out = [];
    const display = { x1: 0, y1: 0, x2: DISPLAY.w, y2: DISPLAY.h };
    const range = document.createRange();

    function keep(text, x1, y1, x2, y2, clip, owner) {
      const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2;
      if (!text || cx < clip.x1 || cx >= clip.x2 || cy < clip.y1 || cy >= clip.y2) return;
      if (!visibleAt(owner, x1, y1, x2, y2)) return;
      out.push([text, 1.0, [round(x1), round(y1), round(x2), round(y2)]]);
    }

    const pen = document.createElement("canvas").getContext("2d");
    const width = (text, style) => {
      pen.font = style.font;
      return pen.measureText(text).width;
    };

    function field(el, clip) {
      const r = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      const left = r.left + parseFloat(style.paddingLeft) + parseFloat(style.borderLeftWidth);
      const value = el.value || el.placeholder || "";
      const shown = el.type === "password" && el.value ? "•".repeat(el.value.length) : value;
      const lh = parseFloat(style.lineHeight) || 18;
      if (el.tagName !== "TEXTAREA") {
        const top = r.top + (r.height - lh) / 2;
        keep(squash(shown), left, top, Math.min(r.right, left + width(shown, style)), top + lh, intersect(clip, box(r)), el);
        return;
      }
      const top = r.top + parseFloat(style.paddingTop) + parseFloat(style.borderTopWidth) - el.scrollTop;
      shown.split("\n").forEach((line, i) => {
        const y = top + i * lh;
        keep(squash(line), left, y, Math.min(r.right, left + width(line, style)), y + lh, intersect(clip, box(r)), el);
      });
    }

    function textNode(node, clip) {
      const data = node.data;
      const words = /\S+/g;
      let line = null;
      let m;
      const flush = () => {
        if (line) keep(squash(data.slice(line.start, line.end)), line.x1, line.y1, line.x2, line.y2, clip, node.parentElement);
        line = null;
      };
      while ((m = words.exec(data))) {
        range.setStart(node, m.index);
        range.setEnd(node, m.index + m[0].length);
        const r = range.getClientRects()[0];
        if (!r || r.width <= 0) continue;
        if (line && Math.abs(r.top - line.y1) < 3 && r.left >= line.x2 - 1) {
          line.end = m.index + m[0].length;
          line.x2 = r.right;
          line.y2 = Math.max(line.y2, r.bottom);
        } else {
          flush();
          line = { start: m.index, end: m.index + m[0].length, x1: r.left, y1: r.top, x2: r.right, y2: r.bottom };
        }
      }
      flush();
    }

    function walk(el, clip) {
      if (hidden(el)) return;
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        field(el, clip);
        return;
      }
      const inner = clipped(el, clip);
      if (inner.empty) return;
      for (const child of el.childNodes) {
        if (child.nodeType === Node.TEXT_NODE) textNode(child, inner);
        else if (child.nodeType === Node.ELEMENT_NODE) walk(child, inner);
      }
    }

    walk(document.getElementById("desktop"), display);
    return out;
  }

  function focus() {
    const el = document.activeElement;
    if (!el || (el.tagName !== "INPUT" && el.tagName !== "TEXTAREA")) return null;
    const r = el.getBoundingClientRect();
    const secret = el.type === "password";
    return {
      id: idOf(el),
      role: axRole(el),
      label: el.getAttribute("aria-label") || "",
      placeholder: el.placeholder || "",
      value: secret ? "" : el.value,
      frame: [round(r.left), round(r.top), round(r.width), round(r.height)],
      caret: secret ? null : el.selectionStart,
      selected: secret ? "" : el.value.slice(el.selectionStart, el.selectionEnd),
    };
  }

  function snapshot() {
    for (const [id, el] of byId) if (!el.isConnected) byId.delete(id);
    snapshots += 1;
    const front = state.front;
    const app = apps[front];
    const display = { x1: 0, y1: 0, x2: DISPLAY.w, y2: DISPLAY.h };
    const win = document.querySelector(`.window[data-app="${CSS.escape(front)}"]`);
    const menus = [...document.querySelectorAll("#desktop > .menu")];
    const chromium = apps.Chromium;
    const browser = chromium && state.running.includes("Chromium") && chromium.tabs ? chromium.tabs(state) : null;
    const children = [win, ...menus].filter(Boolean).flatMap((el) => tree(el, display));
    return {
      id: snapshots,
      app: front,
      pid: app ? app.pid : 0,
      window: app ? app.frame : null,
      // the browser's active tab and its tabs, whichever app is in front, as AppleScript answers on a Mac
      url: browser ? browser.url : null,
      tabs: browser ? browser.tabs : [],
      focus: focus(),
      tree: { id: 0, role: "AXApplication", label: front, frame: null, press: false, children },
      lines: lines(),
    };
  }

  function hold() {
    held = true;
    return snapshot();
  }

  function release() {
    held = false;
    const due = deferred;
    deferred = [];
    for (const fn of due) fn();
    return true;
  }

  // ----- what the adapter does through accessibility ----------------------------------------

  const ax = {
    press(id) {
      const el = element(id);
      if (!el) return false;
      // Under a sheet, a window's controls take no press, as a Mac's are disabled under one.
      const modal = el.closest(".window") && el.closest(".window").querySelector("[data-modal]");
      if (modal && !modal.contains(el)) return false;
      // A text field takes a press as the focus, as a click on it would give it.
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") el.focus();
      el.click();
      return true;
    },
    focus(id) {
      const el = element(id);
      if (!el || !el.focus) return false;
      el.focus();
      return document.activeElement === el;
    },
    setValue(id, text) {
      const el = element(id);
      if (!el || !("value" in el) || el.type === "password") return false;
      el.focus();
      el.value = text;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return true;
    },
    value(id) {
      const el = element(id);
      if (!el) return null;
      return "value" in el && el.tagName !== "DIV" ? el.value : squash(el.textContent || "");
    },
  };

  function clearField() {
    const el = document.activeElement;
    if (!el || !("value" in el) || el.tagName === "DIV") return false;
    el.value = "";
    el.dispatchEvent(new Event("input", { bubbles: true }));
    return true;
  }

  // An app's actions are named after it: "settings.open" goes to Settings' own `reduce`.
  function register(name, app) {
    apps[name] = { ...app, scope: name.toLowerCase() };
    parts[name.toLowerCase()] = app;
  }

  // A part with state and actions of its own that is no app: a fake site in the browser.
  function part(scope, definition) {
    parts[scope] = definition;
  }

  function boot() {
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("mousemove", onMouseMove, true);
    document.addEventListener("mouseup", onMouseUp, true);
    // The page is ready to load a task once every app has registered.
    MockOS.ready = true;
  }

  return {
    ready: false,
    DISPLAY,
    BAR_H,
    register,
    part,
    boot,
    openMenuAt,
    startDrag,
    load,
    dump,
    dispatch,
    after,
    delay,
    hold,
    release,
    snapshot,
    launch,
    openMenu,
    reveal,
    render,
    clearField,
    ax,
    apps: () => Object.keys(apps),
    browser: null,
    get state() {
      return state;
    },
    get rendering() {
      return rendering;
    },
  };
})();

/* Chromium, the mock browser: tabs, Back, an address field, and the fake sites drawn below them.

   Outline, in the builder's words: a tab strip (one tab per page, each with a close box), a
   toolbar (Back, Reload, the address field), and the page. Following a link shows a progress bar
   and an empty page for a moment, then the page, as a real browser repaints at once and fills in.

   Nothing is fetched. A site is drawn by the page itself, picked by its host name (see sites.js),
   and any other address shows a page that says it is not part of the mock OS. The browser's state
   is `state.chromium`; each site keeps its own (`state.shop`, ...), which a task's check reads. */
"use strict";

const Sites = (function () {
  const sites = {}; // host -> {title(state, url), render(state, url, go), slow(state, url), reduce, initial}
  return {
    add(host, scope, site) {
      sites[host] = { ...site, scope };
      MockOS.part(scope, site);
    },
    get(host) {
      return sites[host] || null;
    },
    // A link on a page: a press through accessibility and a click both follow it.
    link(label, href, go, extra) {
      return Kit.h("a", { role: "link", class: "link", ...(extra || {}), onclick: Kit.own((e) => go(href)) }, label);
    },
  };
})();

(function () {
  const { h, own } = Kit;
  const BLANK = "about:newtab";

  function parse(url) {
    try {
      return new URL(url);
    } catch (e) {
      return null;
    }
  }

  function siteOf(url) {
    const u = parse(url);
    return u ? Sites.get(u.host) : null;
  }

  function titleOf(state, tab) {
    if (tab.url === BLANK) return "New Tab";
    if (tab.loading) return parse(tab.url) ? parse(tab.url).host : tab.url;
    const site = siteOf(tab.url);
    return site ? site.title(state, parse(tab.url)) : "Not part of the mock OS";
  }

  function active(c) {
    return c.tabs[c.active];
  }

  // A typed address may leave out the scheme, as one typed into a real address bar may.
  function address(text) {
    const t = text.trim();
    if (!t) return null;
    if (/^https?:\/\//.test(t)) return t;
    if (/^[a-z0-9.-]+\.[a-z]{2,}(\/.*)?$/i.test(t)) return `https://${t}`;
    return `https://search.mockos.example/?q=${encodeURIComponent(t)}`;
  }

  function navigate(state, tab, url, push) {
    const c = state.chromium;
    if (push && tab.url !== BLANK) tab.back.push(tab.url);
    tab.url = url;
    tab.loading = true;
    c.editing = null;
    finish(state, tab, url);
  }

  function finish(state, tab, url) {
    const site = siteOf(url);
    const slow = site && site.slow && site.slow(state, parse(url));
    const ms = slow ? MockOS.delay(2000, 2700, true) : MockOS.delay(150, 550);
    MockOS.after(ms, () => MockOS.dispatch({ type: "chromium.loaded", tab: tab.id, url }));
  }

  function reduce(state, action) {
    const c = state.chromium;
    const t = action.type;
    if (t === "chromium.go") {
      const url = address(action.url);
      if (url) navigate(state, active(c), url, true);
    } else if (t === "chromium.open") {
      // from outside, as `open location` opens a page: a new tab, unless the front one is empty
      const url = address(action.url);
      if (!url) return;
      if (active(c).url !== BLANK) {
        c.tabs.push({ id: c.next++, url: BLANK, back: [], loading: false });
        c.active = c.tabs.length - 1;
      }
      navigate(state, active(c), url, true);
    } else if (t === "chromium.loaded") {
      const tab = c.tabs.find((x) => x.id === action.tab);
      if (tab && tab.url === action.url) tab.loading = false;
    } else if (t === "chromium.back") {
      const tab = active(c);
      const to = tab.back.pop();
      if (to) navigate(state, tab, to, false);
    } else if (t === "chromium.reload") {
      navigate(state, active(c), active(c).url, false);
    } else if (t === "chromium.show") {
      const i = c.tabs.findIndex((x) => x.id === action.tab);
      if (i >= 0) c.active = i;
      c.editing = null;
    } else if (t === "chromium.close") {
      const i = c.tabs.findIndex((x) => x.id === action.tab);
      if (i < 0) return;
      c.tabs.splice(i, 1);
      if (!c.tabs.length) c.tabs.push({ id: c.next++, url: BLANK, back: [], loading: false });
      c.active = Math.min(c.active, c.tabs.length - 1);
    } else if (t === "chromium.newTab") {
      c.tabs.push({ id: c.next++, url: BLANK, back: [], loading: false });
      c.active = c.tabs.length - 1;
      c.editing = "";
    } else if (t === "chromium.edit") {
      c.editing = action.text;
    }
  }

  function page(state, tab) {
    const go = (href) => MockOS.dispatch({ type: "chromium.go", url: new URL(href, tab.url).href });
    if (tab.url === BLANK) return h("div", { class: "newtab" }, h("div", { class: "newtab-mark" }, "New Tab"));
    if (tab.loading) return null;
    const site = siteOf(tab.url);
    if (!site)
      return h(
        "div",
        { class: "site notmock" },
        h("h1", {}, "This site is not part of the mock OS"),
        h("p", {}, `${parse(tab.url) ? parse(tab.url).host : tab.url} cannot be reached from here. The mock OS has three sites:`),
        ["https://shop.mockos.example/", "https://tickets.mockos.example/", "https://wiki.mockos.example/"].map((u) => h("p", {}, Sites.link(u, u, go))),
      );
    return site.render(state, parse(tab.url), go);
  }

  function render(state) {
    const c = state.chromium;
    const tab = active(c);
    const shown = c.editing !== null && c.editing !== undefined ? c.editing : tab.url === BLANK ? "" : tab.url;
    return h(
      "div",
      { class: "window-body chromium", style: "flex-direction:column" },
      h(
        "div",
        { class: "tabstrip", role: "tablist", "aria-label": "Tabs" },
        c.tabs.map((x, i) =>
          h(
            "div",
            { class: i === c.active ? "tab on" : "tab", role: "tab", "aria-selected": i === c.active ? "true" : "false", "aria-label": titleOf(state, x), onclick: own(() => MockOS.dispatch({ type: "chromium.show", tab: x.id })) },
            h("span", { class: "tab-title" }, titleOf(state, x)),
            h("span", { class: "tab-close", role: "button", "aria-label": "Close tab", onclick: own(() => MockOS.dispatch({ type: "chromium.close", tab: x.id })) }, "×"),
          ),
        ),
        h("div", { class: "btn newtab-btn", role: "button", "aria-label": "New tab", onclick: own(() => MockOS.dispatch({ type: "chromium.newTab" })) }, "+"),
      ),
      h(
        "div",
        { class: "toolbar" },
        h("div", { class: "btn tool", role: "button", "aria-label": "Back", onclick: own(() => MockOS.dispatch({ type: "chromium.back" })) }, "←"),
        h("div", { class: "btn tool", role: "button", "aria-label": "Reload", onclick: own(() => MockOS.dispatch({ type: "chromium.reload" })) }, "↻"),
        h(
          "div",
          { class: "omnibox" },
          Kit.textField({
            label: "Address and search bar",
            placeholder: "Search or type a web address",
            value: shown,
            key: "chromium-address",
            onInput: (text) => MockOS.dispatch({ type: "chromium.edit", text }),
            onKey: (e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                MockOS.dispatch({ type: "chromium.go", url: e.target.value });
                e.target.blur();
              } else if (e.key === "Escape") {
                e.preventDefault();
                MockOS.dispatch({ type: "chromium.edit", text: null });
              }
            },
          }),
        ),
      ),
      h("div", { class: tab.loading ? "progress on" : "progress" }),
      h("div", { class: "page", key: `page-${tab.id}-${tab.url}`, style: "position:relative" }, page(state, tab)),
    );
  }

  function key(state, event) {
    const command = event.metaKey || event.ctrlKey;
    if (!command) return;
    const k = event.key.toLowerCase();
    if (event.key === "[" || (event.altKey && event.key === "ArrowLeft")) MockOS.dispatch({ type: "chromium.back" });
    else if (k === "l") {
      const field = document.querySelector('[data-key="chromium-address"]');
      if (field) {
        field.focus();
        field.select();
      }
    } else if (k === "t") MockOS.dispatch({ type: "chromium.newTab" });
    else if (k === "w") MockOS.dispatch({ type: "chromium.close", tab: active(state.chromium).id });
    else if (k === "r") MockOS.dispatch({ type: "chromium.reload" });
    else return;
    event.preventDefault();
  }

  MockOS.register("Chromium", {
    pid: 4110,
    frame: [110, 50, 1220, 800],
    title: (state) => titleOf(state, active(state.chromium)),
    initial: () => ({ tabs: [{ id: 1, url: BLANK, back: [], loading: false }], active: 0, next: 2, editing: null }),
    render,
    key,
    reduce,
    resume: (state) => {
      for (const tab of state.chromium.tabs) if (tab.loading) finish(state, tab, tab.url);
    },
    // what the adapter reports as the browser's URL and tabs, as AppleScript reads a real browser's
    tabs: (state) => {
      const c = state.chromium;
      return { url: active(c).url === BLANK ? null : active(c).url, tabs: c.tabs.filter((x) => x.url !== BLANK).map((x) => [titleOf(state, x), x.url]) };
    },
  });

  MockOS.browser = {
    open(url) {
      MockOS.launch("Chromium");
      MockOS.dispatch({ type: "chromium.open", url });
      return true;
    },
    show(url) {
      const c = MockOS.state.chromium;
      const tab = c.tabs.find((x) => x.url === url);
      if (!tab) return false;
      MockOS.launch("Chromium");
      MockOS.dispatch({ type: "chromium.show", tab: tab.id });
      return true;
    },
  };
})();

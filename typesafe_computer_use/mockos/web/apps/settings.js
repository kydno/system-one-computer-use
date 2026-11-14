/* Settings: panes in a sidebar, each a list of grouped rows with a switch, a popup menu, a radio
   group, a value, or a button. A search field finds a row by its label or its pane's name.

   Outline, in the builder's words: a sidebar (search field, then one row per pane) and a detail
   area (the pane's title, then its groups of rows). Opening a pane takes a moment, during which
   the detail area is empty, as a real settings window redraws. A row's control is on its right.

   The content is the seed's (`state.settings.panes`), so a task's template decides every name and
   value, and a check reads the values back from the state. */
"use strict";

(function () {
  const { h, own } = Kit;

  function settings(state) {
    return state.settings;
  }

  function paneOf(s, id) {
    return s.panes.find((p) => p.id === id) || s.panes[0];
  }

  function rowOf(s, id) {
    for (const pane of s.panes) for (const group of pane.groups) for (const row of group.rows) if (row.id === id) return row;
    return null;
  }

  function matches(s) {
    const q = s.query.trim().toLowerCase();
    if (!q) return [];
    const out = [];
    for (const pane of s.panes) {
      if (pane.name.toLowerCase().includes(q)) out.push({ pane, row: null });
      for (const group of pane.groups)
        for (const row of group.rows) if (row.label.toLowerCase().includes(q)) out.push({ pane, row });
    }
    return out;
  }

  function reduce(state, action) {
    const s = settings(state);
    if (action.type === "settings.open" || action.type === "settings.reveal") {
      s.loading = action.pane;
      s.highlight = null;
      const done = { type: "settings.opened", pane: action.pane, row: action.row || null };
      MockOS.after(MockOS.delay(120, 420), () => MockOS.dispatch(done));
    } else if (action.type === "settings.opened") {
      if (s.loading !== action.pane) return; // another pane was asked for since
      s.loading = null;
      s.pane = action.pane;
      if (action.row) {
        s.query = "";
        s.highlight = action.row;
        MockOS.reveal(`row-${action.row}`);
      }
    } else if (action.type === "settings.set") {
      const row = rowOf(s, action.row);
      if (!row) return;
      if ("on" in action) row.on = action.on;
      if ("value" in action) row.value = action.value;
    } else if (action.type === "settings.query") {
      s.query = action.text;
    } else if (action.type === "settings.press") {
      const row = rowOf(s, action.row);
      if (!row) return;
      s.sheet = row.sheet === "reset" ? { kind: "reset" } : { kind: "style", row: row.id, value: row.value };
    } else if (action.type === "settings.style") {
      if (s.sheet) s.sheet.value = action.value;
    } else if (action.type === "settings.done") {
      const sheet = s.sheet;
      s.sheet = null;
      if (sheet && sheet.kind === "style") rowOf(s, sheet.row).value = sheet.value;
      if (sheet && sheet.kind === "reset" && action.confirm) s.resets += 1;
    } else if (action.type === "settings.cancel") {
      s.sheet = null;
    }
  }

  function control(row) {
    const set = (change) => MockOS.dispatch({ type: "settings.set", row: row.id, ...change });
    const key = `ctl-${row.id}`;
    if (row.kind === "switch") return Kit.toggle({ label: row.label, on: row.on, key, onToggle: () => set({ on: !row.on }) });
    if (row.kind === "popup")
      return Kit.popup({
        label: row.label,
        value: row.value,
        key,
        onOpen: (anchor) =>
          MockOS.openMenu(
            anchor,
            row.options.map((option) => ({
              label: option,
              checked: option === row.value,
              action: { type: "settings.set", row: row.id, value: option },
            })),
          ),
      });
    if (row.kind === "radio") return Kit.radios({ label: row.label, options: row.options, value: row.value, key, onPick: (value) => set({ value }) });
    if (row.kind === "value") return h("span", { class: "value" }, row.value);
    if (row.kind === "button" && row.sheet === "style")
      return h("div", { class: "inline" }, h("span", { class: "value" }, row.value), Kit.button({ label: row.button, key, onPress: () => MockOS.dispatch({ type: "settings.press", row: row.id }) }));
    if (row.kind === "button")
      return Kit.button({ label: row.button, key, onPress: () => MockOS.dispatch({ type: "settings.press", row: row.id }) });
    return null;
  }

  function pane(s) {
    const p = paneOf(s, s.pane);
    return [
      h("h2", {}, p.name),
      p.groups.map((group) => [
        group.title ? h("div", { class: "group-title" }, group.title) : null,
        h(
          "div",
          { class: "group" },
          group.rows.map((row) =>
            h(
              "div",
              { class: row.id === s.highlight ? "srow highlight" : "srow", key: `row-${row.id}` },
              h("div", { class: "what" }, h("div", {}, row.label), row.note ? h("div", { class: "note" }, row.note) : null),
              control(row),
            ),
          ),
        ),
      ]),
    ];
  }

  function results(s) {
    const found = matches(s);
    if (!found.length) return h("div", { class: "empty" }, "No Results");
    return h(
      "div",
      { role: "list", "aria-label": "Search results" },
      found.map(({ pane, row }) =>
        h(
          "div",
          {
            class: "result",
            role: "row",
            onclick: own(() => MockOS.dispatch({ type: "settings.reveal", pane: pane.id, row: row ? row.id : null })),
          },
          h("div", {}, row ? row.label : pane.name),
          h("div", { class: "where" }, row ? pane.name : "Settings pane"),
        ),
      ),
    );
  }

  function render(state) {
    const s = settings(state);
    const query = s.query.trim();
    return h(
      "div",
      { class: "window-body settings" },
      h(
        "div",
        { class: "sidebar" },
        Kit.textField({
          label: "Search",
          placeholder: "Search",
          value: s.query,
          key: "settings-search",
          search: true,
          onInput: (text) => MockOS.dispatch({ type: "settings.query", text }),
          onKey: (event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              const first = matches(s)[0];
              if (first) MockOS.dispatch({ type: "settings.reveal", pane: first.pane.id, row: first.row ? first.row.id : null });
            } else if (event.key === "Escape") {
              event.preventDefault();
              MockOS.dispatch({ type: "settings.query", text: "" });
            }
          },
        }),
        h(
          "div",
          { class: "panes", role: "list", "aria-label": "Panes", key: "settings-panes" },
          s.panes.map((p) =>
            h(
              "div",
              {
                class: "pane-row",
                role: "row",
                "aria-selected": !query && p.id === (s.loading || s.pane) ? "true" : "false",
                onclick: own(() => MockOS.dispatch({ type: "settings.open", pane: p.id })),
              },
              h("span", { class: "icon", style: `background:${p.color}`, "aria-hidden": "true" }, p.icon),
              h("span", {}, p.name),
            ),
          ),
        ),
      ),
      h("div", { class: "main", key: "settings-main" }, query ? results(s) : s.loading ? null : pane(s)),
      sheet(s),
    );
  }

  function sheet(s) {
    const d = s.sheet;
    if (!d) return null;
    const cancel = Kit.button({ label: "Cancel", onPress: () => MockOS.dispatch({ type: "settings.cancel" }) });
    if (d.kind === "reset")
      return Kit.sheet({
        title: "Reset all settings?",
        body: h("div", { class: "sheet-text" }, "Every setting returns to how it came. This cannot be undone."),
        buttons: [cancel, Kit.button({ label: "Reset", primary: true, onPress: () => MockOS.dispatch({ type: "settings.done", confirm: true }) })],
      });
    const row = rowOf(s, d.row);
    return Kit.sheet({
      title: `${row.label} notifications`,
      body: [
        h("div", { class: "form-label" }, "Alert style"),
        Kit.radios({ label: "Alert style", options: ["None", "Banners", "Alerts"], value: d.value, onPick: (value) => MockOS.dispatch({ type: "settings.style", value }) }),
      ],
      buttons: [cancel, Kit.button({ label: "Done", primary: true, onPress: () => MockOS.dispatch({ type: "settings.done" }) })],
    });
  }

  function key(state, event) {
    const command = event.metaKey || event.ctrlKey;
    if (command && event.key.toLowerCase() === "f") {
      event.preventDefault();
      const field = document.querySelector('[data-key="settings-search"]');
      if (field) field.focus();
    }
  }

  MockOS.register("Settings", {
    pid: 4101,
    frame: [180, 60, 1080, 768],
    title: (state) => (state.settings.query.trim() ? "Settings" : paneOf(state.settings, state.settings.loading || state.settings.pane).name),
    render,
    key,
    reduce,
  });
})();

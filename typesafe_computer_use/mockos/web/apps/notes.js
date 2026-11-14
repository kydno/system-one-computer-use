/* Notes: a list of notes and one text area.

   Outline, in the builder's words: a toolbar (New Note, Delete, and a search field), the list of
   notes, newest first (each with its first line as the title, a date, and the start of the next
   line), and the open note's whole text in one text area. A note's first line is its title.

   Notes are the seed's (`state.notes.notes`), each {id, body, updated}. */
"use strict";

(function () {
  const { h, own } = Kit;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const title = (n) => n.body.split("\n")[0].trim() || "New Note";
  const snippet = (n) => (n.body.split("\n").slice(1).find((l) => l.trim()) || "No additional text").slice(0, 60);
  const when = (stamp) => {
    const [, m, d] = stamp.slice(0, 10).split("-").map(Number);
    return `${d} ${MONTHS[m - 1]}`;
  };

  function shown(s) {
    const q = s.query.trim().toLowerCase();
    const list = q ? s.notes.filter((n) => n.body.toLowerCase().includes(q)) : s.notes;
    return [...list].sort((a, b) => (a.updated < b.updated ? 1 : a.updated > b.updated ? -1 : 0));
  }

  function reduce(state, action) {
    const s = state.notes;
    const t = action.type;
    if (t !== "notes.new") s.fresh = null;
    if (t === "notes.open") s.selected = action.id;
    else if (t === "notes.new") {
      const id = `n${s.next || s.notes.length + 1}`;
      s.next = (s.next || s.notes.length + 1) + 1;
      s.notes.push({ id, body: "", updated: state.clock.replace("T", " ") });
      s.selected = id;
      s.query = "";
      s.fresh = id; // a new note takes the keyboard at once, as a real one does
    } else if (t === "notes.edit") {
      const n = s.notes.find((x) => x.id === action.id);
      if (n) {
        n.body = action.body;
        n.updated = state.clock.replace("T", " ");
      }
    } else if (t === "notes.delete") {
      s.notes = s.notes.filter((x) => x.id !== s.selected);
      s.selected = shown(s).length ? shown(s)[0].id : null;
    } else if (t === "notes.query") s.query = action.text;
  }

  function render(state) {
    const s = state.notes;
    const open = s.notes.find((n) => n.id === s.selected);
    const list = shown(s);
    return h(
      "div",
      { class: "window-body notes", style: "flex-direction:column" },
      h(
        "div",
        { class: "toolbar" },
        h("div", { class: "btn tool", role: "button", "aria-label": "New Note", onclick: own(() => MockOS.dispatch({ type: "notes.new" })) }, "New Note"),
        h("div", { class: open ? "btn tool" : "btn tool disabled", role: "button", "aria-label": "Delete", onclick: own(() => open && MockOS.dispatch({ type: "notes.delete" })) }, "Delete"),
        h("div", { class: "spacer" }),
        h("div", { class: "tsearch" }, Kit.textField({ label: "Search", placeholder: "Search", value: s.query, key: "notes-search", search: true, onInput: (text) => MockOS.dispatch({ type: "notes.query", text }) })),
      ),
      h(
        "div",
        { class: "window-body" },
        h(
          "div",
          { class: "nlist", role: "list", "aria-label": "Notes", key: "notes-list" },
          list.map((n) =>
            h(
              "div",
              { class: n.id === s.selected ? "nrow selected" : "nrow", role: "row", "aria-selected": n.id === s.selected ? "true" : "false", onclick: own(() => MockOS.dispatch({ type: "notes.open", id: n.id })) },
              h("div", { class: "ntitle" }, title(n)),
              h("div", { class: "nmeta" }, h("span", {}, when(n.updated)), h("span", { class: "muted" }, snippet(n))),
            ),
          ),
          list.length ? null : h("div", { class: "empty" }, s.query.trim() ? "No Results" : "No Notes"),
        ),
        h(
          "div",
          { class: "neditor" },
          open
            ? Kit.textArea({ label: "Note", value: open.body, key: `note-${open.id}`, rows: 24, autofocus: s.fresh === open.id, onInput: (body) => MockOS.dispatch({ type: "notes.edit", id: open.id, body }) })
            : h("div", { class: "empty" }, "No Note Selected"),
        ),
      ),
    );
  }

  MockOS.register("Notes", {
    pid: 4105,
    frame: [200, 58, 1060, 770],
    title: () => "Notes",
    initial: () => ({ selected: null, query: "", notes: [] }),
    render,
    reduce,
    key: (state, event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") {
        event.preventDefault();
        MockOS.dispatch({ type: "notes.new" });
      }
    },
  });
})();

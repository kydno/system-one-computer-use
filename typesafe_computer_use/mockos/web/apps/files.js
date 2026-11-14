/* Files: folders and files in a sidebar and a list, as a file manager shows them.

   Outline, in the builder's words: a toolbar (Back, Open, New Folder, Rename, Move to, Move to
   Trash, and a search field), a sidebar of places (Home, Desktop, Documents, Downloads, Trash), a
   path line, and a list with sortable columns (Name, Date Modified, Size, Kind). A click selects a
   row, a double click opens it, a right click opens its menu, and a row dragged onto a folder moves
   there. Renaming edits the name in place; the Trash asks first; "Move to" asks where.

   The state is a flat map of paths (`state.files.entries`): "/Home/Documents/plan.txt" is a file
   in Documents. A task's check reads where each path ended up. */
"use strict";

(function () {
  const { h, own } = Kit;
  const PLACES = ["/Home", "/Home/Desktop", "/Home/Documents", "/Home/Downloads", "/Trash"];

  const name = (path) => path.slice(path.lastIndexOf("/") + 1);
  const parent = (path) => path.slice(0, path.lastIndexOf("/")) || "/";
  const isFolder = (f, path) => f.entries[path] && f.entries[path].kind === "folder";

  function children(f, folder) {
    return Object.keys(f.entries).filter((p) => parent(p) === folder);
  }

  function descendants(f, folder) {
    return Object.keys(f.entries).filter((p) => p.startsWith(folder + "/"));
  }

  function size(bytes) {
    if (bytes === undefined || bytes === null) return "--";
    if (bytes < 1000) return `${bytes} bytes`;
    if (bytes < 1e6) return `${Math.round(bytes / 1000)} KB`;
    if (bytes < 1e9) return `${(bytes / 1e6).toFixed(1)} MB`;
    return `${(bytes / 1e9).toFixed(2)} GB`;
  }

  function when(stamp) {
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    const [day, time] = stamp.split(" ");
    const [y, m, d] = day.split("-").map(Number);
    return `${d} ${months[m - 1]} ${y} at ${time}`;
  }

  function kind(f, path) {
    const entry = f.entries[path];
    if (entry.kind === "folder") return "Folder";
    const ext = name(path).includes(".") ? name(path).split(".").pop().toLowerCase() : "";
    return { pdf: "PDF document", txt: "Plain text", md: "Markdown", png: "PNG image", jpg: "JPEG image", csv: "CSV document", zip: "ZIP archive", docx: "Word document", xlsx: "Spreadsheet", key: "Presentation", mp3: "MP3 audio" }[ext] || "Document";
  }

  // Move `path` (and everything under it, for a folder) to `to/<name>`. A name taken there is refused.
  function move(f, path, to) {
    const target = `${to}/${name(path)}`;
    if (target === path || f.entries[target] || to === path || to.startsWith(path + "/")) return false;
    for (const p of [path, ...descendants(f, path)]) {
      const moved = target + p.slice(path.length);
      f.entries[moved] = f.entries[p];
      delete f.entries[p];
    }
    return target;
  }

  function freshName(f, folder, base) {
    let n = 1;
    let candidate = base;
    while (f.entries[`${folder}/${candidate}`]) candidate = `${base} ${++n}`;
    return candidate;
  }

  function reduce(state, action) {
    const f = state.files;
    const t = action.type;
    if (t === "files.go") {
      if (!isFolder(f, action.path) || action.path === f.cwd) return;
      f.back.push(f.cwd);
      f.loading = action.path;
      f.selected = null;
      f.query = "";
      MockOS.after(MockOS.delay(60, 260), () => MockOS.dispatch({ type: "files.shown", path: action.path }));
    } else if (t === "files.shown") {
      if (f.loading !== action.path) return;
      f.loading = null;
      f.cwd = action.path;
    } else if (t === "files.back") {
      const to = f.back.pop();
      if (to) {
        f.cwd = to;
        f.selected = null;
        f.query = "";
      }
    } else if (t === "files.select") {
      f.selected = action.path;
      if (f.renaming && f.renaming !== action.path) f.renaming = null;
    } else if (t === "files.open") {
      const path = action.path || f.selected;
      if (!path || !f.entries[path]) return;
      if (isFolder(f, path)) return MockOS.dispatch({ type: "files.go", path });
      f.opened.push(path);
    } else if (t === "files.sort") {
      f.sort = { key: action.key, desc: f.sort.key === action.key ? !f.sort.desc : false };
    } else if (t === "files.query") {
      f.query = action.text;
    } else if (t === "files.newFolder") {
      if (f.cwd === "/Trash") return;
      const path = `${f.cwd}/${freshName(f, f.cwd, "untitled folder")}`;
      f.entries[path] = { kind: "folder", modified: state.clock.replace("T", " ") };
      f.selected = path;
      f.renaming = path;
    } else if (t === "files.startRename") {
      const path = action.path || f.selected;
      if (path && f.entries[path] && parent(path) !== "/Trash") {
        f.selected = path;
        f.renaming = path;
      }
    } else if (t === "files.rename") {
      const from = action.from;
      f.renaming = null;
      const clean = (action.name || "").trim();
      if (!f.entries[from] || !clean || clean.includes("/") || clean === name(from)) return;
      const to = `${parent(from)}/${clean}`;
      if (f.entries[to]) return;
      for (const p of [from, ...descendants(f, from)]) {
        f.entries[to + p.slice(from.length)] = f.entries[p];
        delete f.entries[p];
      }
      f.selected = to;
    } else if (t === "files.cancelRename") {
      f.renaming = null;
    } else if (t === "files.askTrash") {
      const path = action.path || f.selected;
      if (path && f.entries[path] && parent(path) !== "/Trash") f.dialog = { kind: "trash", path };
    } else if (t === "files.trash") {
      const path = f.dialog && f.dialog.path;
      f.dialog = null;
      if (!path) return;
      const where = parent(path);
      const moved = move(f, path, "/Trash");
      if (moved) {
        f.entries[moved].from = where;
        f.selected = null;
      }
    } else if (t === "files.putBack") {
      const path = action.path || f.selected;
      const entry = f.entries[path];
      if (!entry || parent(path) !== "/Trash" || !entry.from) return;
      const from = entry.from;
      const moved = move(f, path, from);
      if (moved) delete f.entries[moved].from;
    } else if (t === "files.askMove") {
      const path = action.path || f.selected;
      if (path && f.entries[path]) f.dialog = { kind: "move", path, to: null };
    } else if (t === "files.pick") {
      if (f.dialog) f.dialog.to = action.to;
    } else if (t === "files.move") {
      // from a drag (`from` and `to`) or from the dialog
      const path = action.from || (f.dialog && f.dialog.path);
      const to = action.to || (f.dialog && f.dialog.to);
      if (!action.from) f.dialog = null;
      if (!path || !to || !isFolder(f, to)) return;
      const moved = move(f, path, to);
      if (moved) f.selected = null;
    } else if (t === "files.cancel") {
      f.dialog = null;
    }
  }

  function sorted(f, paths) {
    const { key, desc } = f.sort;
    const value = (p) => (key === "size" ? f.entries[p].size || 0 : key === "modified" ? f.entries[p].modified : key === "kind" ? kind(f, p) : name(p).toLowerCase());
    const out = [...paths].sort((a, b) => (value(a) < value(b) ? -1 : value(a) > value(b) ? 1 : name(a).localeCompare(name(b))));
    return desc ? out.reverse() : out;
  }

  function menuFor(f, path) {
    if (parent(path) === "/Trash") return [{ label: "Put Back", action: { type: "files.putBack", path } }];
    return [
      { label: "Open", action: { type: "files.open", path } },
      { label: "Rename", action: { type: "files.startRename", path } },
      { label: "Move to…", action: { type: "files.askMove", path } },
      { label: "Move to Trash", action: { type: "files.askTrash", path } },
    ];
  }

  function row(f, path, searching) {
    const folder = isFolder(f, path);
    const entry = f.entries[path];
    const renaming = f.renaming === path;
    const label = renaming
      ? Kit.textField({
          label: "Name",
          value: name(path),
          key: "files-rename",
          autofocus: true,
          cls: "rename",
          onKey: (e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              MockOS.dispatch({ type: "files.rename", from: path, name: e.target.value });
            } else if (e.key === "Escape") {
              e.preventDefault();
              MockOS.dispatch({ type: "files.cancelRename" });
            }
          },
          onBlur: (value) => MockOS.dispatch({ type: "files.rename", from: path, name: value }),
        })
      : h("span", {}, name(path));
    return h(
      "div",
      {
        class: f.selected === path ? "frow selected" : "frow",
        role: "row",
        "aria-selected": f.selected === path ? "true" : "false",
        onclick: own(() => MockOS.dispatch({ type: "files.select", path })),
        ondblclick: own(() => MockOS.dispatch({ type: "files.open", path })),
        ...Kit.contextMenu(() => menuFor(f, path)),
        ...(renaming ? {} : Kit.draggable({ from: path })),
        ...(folder ? Kit.dropTarget({ type: "files.move", to: path }) : {}),
      },
      h("div", { class: "fname" }, h("span", { class: folder ? "ficon folder" : "ficon", "aria-hidden": "true" }, folder ? "▸" : "≡"), label),
      h("div", { class: "fdate" }, when(entry.modified)),
      h("div", { class: "fsize" }, folder ? "--" : size(entry.size)),
      h("div", { class: "fkind" }, searching ? parent(path).replace("/Home", "Home") : kind(f, path)),
    );
  }

  function dialog(f) {
    const d = f.dialog;
    if (!d) return null;
    if (d.kind === "trash")
      return Kit.sheet({
        title: `Move “${name(d.path)}” to the Trash?`,
        body: h("div", { class: "sheet-text" }, "You can put it back from the Trash later."),
        buttons: [
          Kit.button({ label: "Cancel", onPress: () => MockOS.dispatch({ type: "files.cancel" }) }),
          Kit.button({ label: "Move to Trash", primary: true, onPress: () => MockOS.dispatch({ type: "files.trash" }) }),
        ],
      });
    const folders = Object.keys(f.entries)
      .filter((p) => isFolder(f, p) && p !== "/Trash" && !p.startsWith("/Trash/") && p !== d.path && !p.startsWith(d.path + "/") && p !== parent(d.path))
      .sort();
    return Kit.sheet({
      title: `Move “${name(d.path)}” to:`,
      body: h(
        "div",
        { class: "picker", role: "list", "aria-label": "Folders" },
        folders.map((p) =>
          h(
            "div",
            { class: d.to === p ? "frow selected" : "frow", role: "row", "aria-selected": d.to === p ? "true" : "false", onclick: own(() => MockOS.dispatch({ type: "files.pick", to: p })) },
            h("span", {}, p.replace("/Home", "Home").split("/").join(" › ")),
          ),
        ),
      ),
      buttons: [
        Kit.button({ label: "Cancel", onPress: () => MockOS.dispatch({ type: "files.cancel" }) }),
        Kit.button({ label: "Move", primary: true, onPress: () => MockOS.dispatch({ type: "files.move" }) }),
      ],
    });
  }

  function render(state) {
    const f = state.files;
    const query = f.query.trim().toLowerCase();
    const shown = f.loading
      ? []
      : query
        ? Object.keys(f.entries).filter((p) => p.startsWith("/Home/") && name(p).toLowerCase().includes(query))
        : children(f, f.cwd);
    const header = (key, label) =>
      h(
        "div",
        { class: `fh f${key}`, role: "button", "aria-label": label, onclick: own(() => MockOS.dispatch({ type: "files.sort", key })) },
        label + (f.sort.key === key ? (f.sort.desc ? " ▾" : " ▴") : ""),
      );
    const tool = (label, type, disabled) =>
      h("div", { class: disabled ? "btn tool disabled" : "btn tool", role: "button", "aria-label": label, "aria-disabled": disabled ? "true" : null, onclick: own(() => !disabled && MockOS.dispatch({ type })) }, label);
    const none = !f.selected;
    return h(
      "div",
      { class: "window-body files", style: "flex-direction:column" },
      h(
        "div",
        { class: "toolbar" },
        h("div", { class: "btn tool", role: "button", "aria-label": "Back", onclick: own(() => MockOS.dispatch({ type: "files.back" })) }, "‹"),
        tool("Open", "files.open", none),
        tool("New Folder", "files.newFolder", f.cwd === "/Trash"),
        tool("Rename", "files.startRename", none),
        tool("Move to…", "files.askMove", none),
        tool("Move to Trash", "files.askTrash", none),
        h("div", { class: "spacer" }),
        h(
          "div",
          { class: "tsearch" },
          Kit.textField({ label: "Search", placeholder: "Search", value: f.query, key: "files-search", search: true, onInput: (text) => MockOS.dispatch({ type: "files.query", text }) }),
        ),
      ),
      h(
        "div",
        { class: "window-body" },
        h(
          "div",
          { class: "sidebar", role: "list", "aria-label": "Places" },
          h("div", { class: "side-title" }, "Places"),
          PLACES.map((p) =>
            h(
              "div",
              {
                class: !query && f.cwd === p ? "place selected" : "place",
                role: "row",
                "aria-selected": !query && f.cwd === p ? "true" : "false",
                onclick: own(() => MockOS.dispatch({ type: "files.go", path: p })),
                ...Kit.dropTarget({ type: "files.move", to: p }),
              },
              h("span", { class: "ficon folder", "aria-hidden": "true" }, p === "/Trash" ? "⌫" : "▸"),
              h("span", {}, name(p)),
            ),
          ),
        ),
        h(
          "div",
          { class: "flist" },
          h("div", { class: "pathline" }, query ? `Searching Home for “${f.query.trim()}”` : f.cwd.slice(1).split("/").join(" › ")),
          h("div", { class: "fheader" }, header("name", "Name"), header("modified", "Date Modified"), header("size", "Size"), header("kind", query ? "Where" : "Kind")),
          h(
            "div",
            { class: "frows", role: "list", "aria-label": "Files", key: "files-rows" },
            sorted(f, shown).map((p) => row(f, p, !!query)),
            !f.loading && !shown.length ? h("div", { class: "empty" }, query ? "No Results" : "This folder is empty") : null,
          ),
          f.opened.length ? h("div", { class: "status" }, `Opened “${name(f.opened[f.opened.length - 1])}”`) : null,
        ),
      ),
      dialog(f),
    );
  }

  function key(state, event) {
    const f = state.files;
    const command = event.metaKey || event.ctrlKey;
    if (event.target && (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA")) return;
    if (f.dialog) {
      if (event.key === "Escape") MockOS.dispatch({ type: "files.cancel" });
      else if (event.key === "Enter") MockOS.dispatch({ type: f.dialog.kind === "trash" ? "files.trash" : "files.move" });
      return;
    }
    if (command && event.key === "[") MockOS.dispatch({ type: "files.back" });
    else if (command && event.key.toLowerCase() === "o") MockOS.dispatch({ type: "files.open" });
    else if (command && event.key === "Backspace") MockOS.dispatch({ type: "files.askTrash" });
    else if (event.key === "Enter" && f.selected) MockOS.dispatch({ type: "files.startRename" });
    else return;
    event.preventDefault();
  }

  MockOS.register("Files", {
    pid: 4102,
    frame: [170, 56, 1100, 772],
    title: (state) => (state.files.query.trim() ? "Searching Home" : name(state.files.loading || state.files.cwd)),
    initial: () => ({ cwd: "/Home", sort: { key: "name", desc: false }, selected: null, renaming: null, dialog: null, query: "", opened: [], back: [], loading: null, entries: Object.fromEntries(PLACES.map((p) => [p, { kind: "folder", modified: "2026-01-02 09:00" }])) }),
    render,
    key,
    reduce,
  });
})();

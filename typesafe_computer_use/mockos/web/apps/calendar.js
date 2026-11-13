/* Calendar: a month grid and the list of the chosen day, and a sheet to make or change an event.

   Outline, in the builder's words: a toolbar (Previous month, Next month, Today, New Event), the
   month as a grid of days with each day's events on it, and on the right the chosen day's events in
   order. An event opens in a sheet with its title, a date picker, a start time, and Save or Delete.
   The date picker is drawn by the page, a month of day buttons, not the browser's own.

   Events are the seed's (`state.calendar.events`), each {id, title, date, start}; an hour long. */
"use strict";

(function () {
  const { h, own } = Kit;
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];
  const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const LONG_DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
  const TIMES = [];
  for (let hour = 7; hour <= 20; hour++) for (const m of ["00", "30"]) TIMES.push(`${String(hour).padStart(2, "0")}:${m}`);

  const parse = (iso) => new Date(`${iso}T00:00:00Z`);
  const iso = (d) => d.toISOString().slice(0, 10);
  const long = (day) => {
    const d = parse(day);
    return `${LONG_DAYS[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
  };
  const short = (day) => {
    const d = parse(day);
    return `${MONTHS[d.getUTCMonth()].slice(0, 3)} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
  };

  function grid(month) {
    // the weeks of `month` ("2026-06"), Monday first, padded with the days around it
    const first = parse(`${month}-01`);
    const start = new Date(first);
    start.setUTCDate(1 - ((first.getUTCDay() + 6) % 7));
    const days = [];
    for (let i = 0; i < 42; i++) {
      const d = new Date(start);
      d.setUTCDate(start.getUTCDate() + i);
      days.push(iso(d));
    }
    return days;
  }

  function shift(month, by) {
    const d = parse(`${month}-01`);
    d.setUTCMonth(d.getUTCMonth() + by);
    return iso(d).slice(0, 7);
  }

  function reduce(state, action) {
    const s = state.calendar;
    const t = action.type;
    if (t === "calendar.month") s.month = shift(s.month, action.by);
    else if (t === "calendar.today") {
      s.selected = state.clock.slice(0, 10);
      s.month = s.selected.slice(0, 7);
    } else if (t === "calendar.day") {
      s.selected = action.day;
      if (action.day.slice(0, 7) !== s.month) s.month = action.day.slice(0, 7);
    } else if (t === "calendar.new") {
      s.editor = { id: null, title: "", date: s.selected, start: "09:00", picker: null };
    } else if (t === "calendar.edit") {
      const e = s.events.find((x) => x.id === action.id);
      if (e) s.editor = { id: e.id, title: e.title, date: e.date, start: e.start, picker: null };
    } else if (t === "calendar.field") {
      if (s.editor) s.editor[action.field] = action.value;
    } else if (t === "calendar.picker") {
      if (s.editor) s.editor.picker = s.editor.picker ? null : s.editor.date.slice(0, 7);
    } else if (t === "calendar.pickerMonth") {
      if (s.editor && s.editor.picker) s.editor.picker = shift(s.editor.picker, action.by);
    } else if (t === "calendar.pick") {
      if (s.editor) {
        s.editor.date = action.day;
        s.editor.picker = null;
      }
    } else if (t === "calendar.time") {
      if (s.editor) s.editor.start = action.value;
    } else if (t === "calendar.save") {
      const e = s.editor;
      if (!e) return;
      if (!e.title.trim()) {
        e.error = "Give the event a title.";
        return;
      }
      if (e.id) Object.assign(s.events.find((x) => x.id === e.id), { title: e.title.trim(), date: e.date, start: e.start });
      else s.events.push({ id: `ev${s.events.length + 1}`, title: e.title.trim(), date: e.date, start: e.start });
      s.selected = e.date;
      s.month = e.date.slice(0, 7);
      s.editor = null;
    } else if (t === "calendar.delete") {
      if (s.editor && s.editor.id) s.events = s.events.filter((x) => x.id !== s.editor.id);
      s.editor = null;
    } else if (t === "calendar.cancel") s.editor = null;
  }

  function editor(state) {
    const s = state.calendar;
    const e = s.editor;
    if (!e) return null;
    const picker = e.picker
      ? h(
          "div",
          { class: "picker-month" },
          h(
            "div",
            { class: "inline" },
            h("div", { class: "btn mini", role: "button", "aria-label": "Previous month", onclick: own(() => MockOS.dispatch({ type: "calendar.pickerMonth", by: -1 })) }, "‹"),
            h("b", {}, `${MONTHS[Number(e.picker.slice(5)) - 1]} ${e.picker.slice(0, 4)}`),
            h("div", { class: "btn mini", role: "button", "aria-label": "Next month", onclick: own(() => MockOS.dispatch({ type: "calendar.pickerMonth", by: 1 })) }, "›"),
          ),
          h(
            "div",
            { class: "pgrid" },
            DAYS.map((d) => h("span", { class: "muted" }, d.slice(0, 2))),
            grid(e.picker).map((day) =>
              day.slice(0, 7) === e.picker
                ? h("div", { class: day === e.date ? "pday on" : "pday", role: "button", "aria-label": long(day), onclick: own(() => MockOS.dispatch({ type: "calendar.pick", day })) }, String(Number(day.slice(8))))
                : h("span"),
            ),
          ),
        )
      : null;
    return Kit.sheet({
      title: e.id ? "Edit Event" : "New Event",
      body: [
        h("label", { class: "form-label" }, "Title"),
        Kit.textField({ label: "Title", placeholder: "New Event", value: e.title, key: "calendar-title", onInput: (value) => MockOS.dispatch({ type: "calendar.field", field: "title", value }) }),
        h("label", { class: "form-label" }, "Date"),
        h("div", { class: "popup", role: "button", "aria-haspopup": "dialog", "aria-label": "Date", onclick: own(() => MockOS.dispatch({ type: "calendar.picker" })) }, h("span", {}, short(e.date)), h("span", { class: "chev" }, "⌄")),
        picker,
        h("label", { class: "form-label" }, "Starts"),
        Kit.popup({
          label: "Starts",
          value: e.start,
          onOpen: (anchor) => MockOS.openMenu(anchor, TIMES.map((time) => ({ label: time, checked: time === e.start, action: { type: "calendar.time", value: time } }))),
        }),
        e.error ? h("div", { class: "error" }, e.error) : null,
      ],
      buttons: [
        e.id ? Kit.button({ label: "Delete", onPress: () => MockOS.dispatch({ type: "calendar.delete" }) }) : null,
        Kit.button({ label: "Cancel", onPress: () => MockOS.dispatch({ type: "calendar.cancel" }) }),
        Kit.button({ label: "Save", primary: true, onPress: () => MockOS.dispatch({ type: "calendar.save" }) }),
      ],
    });
  }

  function render(state) {
    const s = state.calendar;
    const today = state.clock.slice(0, 10);
    const byDay = (day) => s.events.filter((e) => e.date === day).sort((a, b) => (a.start < b.start ? -1 : 1));
    return h(
      "div",
      { class: "window-body calendar", style: "flex-direction:column;position:relative" },
      h(
        "div",
        { class: "toolbar" },
        h("div", { class: "btn tool", role: "button", "aria-label": "Previous month", onclick: own(() => MockOS.dispatch({ type: "calendar.month", by: -1 })) }, "‹"),
        h("div", { class: "btn tool", role: "button", "aria-label": "Next month", onclick: own(() => MockOS.dispatch({ type: "calendar.month", by: 1 })) }, "›"),
        h("div", { class: "btn tool", role: "button", "aria-label": "Today", onclick: own(() => MockOS.dispatch({ type: "calendar.today" })) }, "Today"),
        h("h2", { class: "month-title" }, `${MONTHS[Number(s.month.slice(5)) - 1]} ${s.month.slice(0, 4)}`),
        h("div", { class: "spacer" }),
        h("div", { class: "btn tool", role: "button", "aria-label": "New Event", onclick: own(() => MockOS.dispatch({ type: "calendar.new" })) }, "New Event"),
      ),
      h(
        "div",
        { class: "window-body" },
        h(
          "div",
          { class: "cgrid" },
          DAYS.map((d) => h("div", { class: "chead" }, d)),
          grid(s.month).map((day) =>
            h(
              "div",
              {
                class: ["cday", day.slice(0, 7) === s.month ? "" : "other", day === s.selected ? "on" : "", day === today ? "today" : ""].join(" "),
                role: "cell",
                "aria-label": long(day),
                onclick: own(() => MockOS.dispatch({ type: "calendar.day", day })),
              },
              h("div", { class: "cnum" }, String(Number(day.slice(8)))),
              byDay(day).map((e) => h("div", { class: "chip", role: "button", "aria-label": e.title, onclick: own(() => MockOS.dispatch({ type: "calendar.edit", id: e.id })) }, `${e.start} ${e.title}`)),
            ),
          ),
        ),
        h(
          "div",
          { class: "cday-list" },
          h("h3", {}, long(s.selected)),
          byDay(s.selected).length
            ? byDay(s.selected).map((e) => h("div", { class: "cevent", role: "row", onclick: own(() => MockOS.dispatch({ type: "calendar.edit", id: e.id })) }, h("span", { class: "muted" }, e.start), h("span", {}, e.title)))
            : h("div", { class: "muted" }, "No events"),
        ),
      ),
      editor(state),
    );
  }

  MockOS.register("Calendar", {
    pid: 4104,
    frame: [140, 52, 1160, 784],
    title: (state) => "Calendar",
    initial: () => ({ month: "2026-01", selected: "2026-01-01", events: [], editor: null }),
    render,
    reduce,
    key: (state, event) => {
      const s = state.calendar;
      if (event.target && (event.target.tagName === "INPUT" || event.target.tagName === "TEXTAREA")) {
        if (s.editor && event.key === "Enter") {
          event.preventDefault();
          MockOS.dispatch({ type: "calendar.save" });
        }
        return;
      }
      if (s.editor && event.key === "Escape") MockOS.dispatch({ type: "calendar.cancel" });
      else if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n") MockOS.dispatch({ type: "calendar.new" });
    },
  });
})();

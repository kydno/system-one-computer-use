/* Mail: mailboxes, a message list, a reading pane, and a sheet to write a message in.

   Outline, in the builder's words: a toolbar (New Message, Reply, and a search field), a sidebar of
   mailboxes (Inbox, Flagged, Sent, Archive), the list of the mailbox's messages (sender, subject,
   date, with a Flag and an Archive button on every row), and the message that is open. Writing a
   message opens a sheet with To, Subject and the body, and Send.

   Messages are the seed's (`state.mail.messages`); a sent one lands in Sent, for a check to read. */
"use strict";

(function () {
  const { h, own } = Kit;
  const BOXES = ["Inbox", "Flagged", "Sent", "Archive"];
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function when(stamp) {
    const [day, time] = stamp.split(" ");
    const [, m, d] = day.split("-").map(Number);
    return `${d} ${MONTHS[m - 1]} ${time}`;
  }

  function inBox(m, box) {
    return box === "Flagged" ? m.flagged && m.mailbox !== "Sent" : m.mailbox === box;
  }

  function listed(s) {
    const q = s.query.trim().toLowerCase();
    const pool = q ? s.messages.filter((m) => m.mailbox !== "Sent" || s.mailbox === "Sent") : s.messages.filter((m) => inBox(m, s.mailbox));
    const found = q ? pool.filter((m) => `${m.from} ${m.subject} ${m.body}`.toLowerCase().includes(q)) : pool;
    return [...found].sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0));
  }

  function reduce(state, action) {
    const s = state.mail;
    const t = action.type;
    const msg = (id) => s.messages.find((m) => m.id === id);
    if (t === "mail.box") {
      s.mailbox = action.box;
      s.selected = null;
      s.query = "";
    } else if (t === "mail.open") {
      s.selected = action.id;
      const m = msg(action.id);
      if (m) m.read = true;
    } else if (t === "mail.flag") {
      const m = msg(action.id);
      if (m) m.flagged = !m.flagged;
    } else if (t === "mail.archive") {
      const m = msg(action.id);
      if (m && m.mailbox !== "Sent") m.mailbox = "Archive";
      if (s.selected === action.id) s.selected = null;
    } else if (t === "mail.query") {
      s.query = action.text;
    } else if (t === "mail.compose") {
      s.compose = { to: "", subject: "", body: "", replyTo: null };
    } else if (t === "mail.reply") {
      const m = msg(s.selected);
      if (m) s.compose = { to: m.address, subject: m.subject.startsWith("Re: ") ? m.subject : `Re: ${m.subject}`, body: "", replyTo: m.id };
    } else if (t === "mail.field") {
      if (s.compose) s.compose[action.field] = action.value;
    } else if (t === "mail.send") {
      const c = s.compose;
      if (!c) return;
      if (!c.to.includes("@")) {
        c.error = "Add an address to send to.";
        return;
      }
      s.messages.push({ id: `sent${s.messages.length + 1}`, mailbox: "Sent", from: "Me", address: c.to, to: c.to, subject: c.subject, body: c.body, date: state.clock.replace("T", " "), flagged: false, read: true, replyTo: c.replyTo });
      s.compose = null;
    } else if (t === "mail.cancel") {
      s.compose = null;
    }
  }

  function compose(s) {
    const c = s.compose;
    if (!c) return null;
    const field = (name, label) => [h("label", { class: "form-label" }, label), Kit.textField({ label, placeholder: label, value: c[name], key: `mail-${name}`, onInput: (value) => MockOS.dispatch({ type: "mail.field", field: name, value }) })];
    return Kit.sheet({
      title: c.replyTo ? "Reply" : "New Message",
      body: [
        field("to", "To"),
        field("subject", "Subject"),
        h("label", { class: "form-label" }, "Message"),
        Kit.textArea({ label: "Message body", value: c.body, key: "mail-body", rows: 7, onInput: (value) => MockOS.dispatch({ type: "mail.field", field: "body", value }) }),
        c.error ? h("div", { class: "error" }, c.error) : null,
      ],
      buttons: [Kit.button({ label: "Cancel", onPress: () => MockOS.dispatch({ type: "mail.cancel" }) }), Kit.button({ label: "Send", primary: true, onPress: () => MockOS.dispatch({ type: "mail.send" }) })],
    });
  }

  function render(state) {
    const s = state.mail;
    const open = s.messages.find((m) => m.id === s.selected);
    const unread = (box) => s.messages.filter((m) => inBox(m, box) && !m.read).length;
    return h(
      "div",
      { class: "window-body mail", style: "flex-direction:column;position:relative" },
      h(
        "div",
        { class: "toolbar" },
        h("div", { class: "btn tool", role: "button", "aria-label": "New Message", onclick: own(() => MockOS.dispatch({ type: "mail.compose" })) }, "New Message"),
        h("div", { class: open ? "btn tool" : "btn tool disabled", role: "button", "aria-label": "Reply", onclick: own(() => open && MockOS.dispatch({ type: "mail.reply" })) }, "Reply"),
        h("div", { class: "spacer" }),
        h("div", { class: "tsearch" }, Kit.textField({ label: "Search", placeholder: "Search", value: s.query, key: "mail-search", search: true, onInput: (text) => MockOS.dispatch({ type: "mail.query", text }) })),
      ),
      h(
        "div",
        { class: "window-body" },
        h(
          "div",
          { class: "sidebar boxes", role: "list", "aria-label": "Mailboxes" },
          h("div", { class: "side-title" }, "Mailboxes"),
          BOXES.map((box) =>
            h(
              "div",
              { class: !s.query.trim() && s.mailbox === box ? "place selected" : "place", role: "row", "aria-selected": s.mailbox === box ? "true" : "false", onclick: own(() => MockOS.dispatch({ type: "mail.box", box })) },
              h("span", {}, box),
              unread(box) ? h("span", { class: "count" }, String(unread(box))) : null,
            ),
          ),
        ),
        h(
          "div",
          { class: "mlist", role: "list", "aria-label": "Messages", key: "mail-list" },
          listed(s).map((m) =>
            h(
              "div",
              { class: (m.id === s.selected ? "mrow selected" : "mrow") + (m.read ? "" : " unread"), role: "row", "aria-selected": m.id === s.selected ? "true" : "false", onclick: own(() => MockOS.dispatch({ type: "mail.open", id: m.id })) },
              h("div", { class: "mtop" }, h("span", { class: "mfrom" }, m.mailbox === "Sent" ? `To: ${m.to}` : m.from), h("span", { class: "mdate" }, when(m.date))),
              h("div", { class: "msubject" }, m.subject),
              h(
                "div",
                { class: "mactions" },
                h("div", { class: m.flagged ? "btn mini on" : "btn mini", role: "button", "aria-label": m.flagged ? "Unflag" : "Flag", onclick: own(() => MockOS.dispatch({ type: "mail.flag", id: m.id })) }, m.flagged ? "Unflag" : "Flag"),
                m.mailbox !== "Sent" && m.mailbox !== "Archive" ? h("div", { class: "btn mini", role: "button", "aria-label": "Archive", onclick: own(() => MockOS.dispatch({ type: "mail.archive", id: m.id })) }, "Archive") : null,
              ),
            ),
          ),
          listed(s).length ? null : h("div", { class: "empty" }, s.query.trim() ? "No Results" : "No Messages"),
        ),
        h(
          "div",
          { class: "mread", key: "mail-read" },
          open
            ? [h("h2", {}, open.subject), h("div", { class: "muted" }, `From: ${open.from} <${open.address}>`), h("div", { class: "muted" }, when(open.date)), h("div", { class: "mbody" }, open.body.split("\n").map((line) => h("p", {}, line)))]
            : h("div", { class: "empty" }, "No Message Selected"),
        ),
      ),
      compose(s),
    );
  }

  MockOS.register("Mail", {
    pid: 4103,
    frame: [150, 54, 1140, 776],
    title: (state) => (state.mail.query.trim() ? "Search results" : `${state.mail.mailbox} – ${state.mail.messages.filter((m) => inBox(m, state.mail.mailbox)).length} messages`),
    initial: () => ({ mailbox: "Inbox", selected: null, query: "", compose: null, messages: [] }),
    render,
    reduce,
    key: (state, event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "n" && !state.mail.compose) {
        event.preventDefault();
        MockOS.dispatch({ type: "mail.compose" });
      }
    },
  });
})();

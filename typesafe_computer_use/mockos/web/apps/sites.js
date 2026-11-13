/* The fake sites the mock browser shows, each picked by its host name, under the reserved
   .example domain, which can never be a real site:

   - shop.mockos.example: a catalogue, a search, a cart, a checkout form, a newsletter sign-up.
     It may show a cookie banner over the bottom of the page, and its Checkout button answers only
     to pointer events, as some web controls do, so a press through accessibility does nothing.
   - tickets.mockos.example: events with dates and prices, ticket tiers, a checkout. Its listing
     may load slowly.
   - wiki.mockos.example: long articles, a search, and links that may lead nowhere.

   Each site's content is the seed's (`state.shop`, `state.tickets`, `state.wiki`), and what a
   visitor does there is kept there, for a task's check to read. */
"use strict";

(function () {
  const { h, own } = Kit;
  const money = (cents) => `$${(cents / 100).toFixed(2)}`;
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  const day = (iso) => {
    const d = new Date(`${iso}T00:00:00Z`);
    return `${DAYS[d.getUTCDay()]}, ${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`;
  };

  // ----- the shop -------------------------------------------------------------------------------

  function shopReduce(state, action) {
    const s = state.shop;
    const t = action.type;
    if (t === "shop.add") {
      const line = s.cart.find((l) => l.id === action.id);
      if (line) line.qty += 1;
      else s.cart.push({ id: action.id, qty: 1 });
      s.notice = `Added ${s.products.find((p) => p.id === action.id).name} to your cart`;
    } else if (t === "shop.remove") {
      s.cart = s.cart.filter((l) => l.id !== action.id);
      s.notice = null;
    } else if (t === "shop.cookies") {
      s.banner = false;
      s.cookies = action.choice;
    } else if (t === "shop.field") {
      s.form[action.field] = action.value;
    } else if (t === "shop.order") {
      const missing = ["name", "street", "city", "postcode"].filter((f) => !(s.form[f] || "").trim());
      if (missing.length || !s.cart.length) {
        s.error = missing.length ? "Please fill in every field." : "Your cart is empty.";
        return;
      }
      s.orders.push({ lines: s.cart, ...s.form });
      s.cart = [];
      s.form = { name: "", street: "", city: "", postcode: "" };
      s.error = null;
      MockOS.dispatch({ type: "chromium.go", url: "https://shop.mockos.example/done" });
    } else if (t === "shop.email") {
      s.email = action.value;
    } else if (t === "shop.signup") {
      const email = (s.email || "").trim();
      if (email.includes("@")) {
        s.newsletter.push(email);
        s.email = "";
        s.notice = "Thanks for signing up";
      } else s.notice = "Please enter an email address";
    } else if (t === "shop.query") {
      s.query = action.value;
    }
  }

  function shopRender(state, url, go) {
    const s = state.shop;
    const path = url.pathname;
    const count = s.cart.reduce((n, l) => n + l.qty, 0);
    const header = h(
      "div",
      { class: "site-head" },
      Sites.link(s.name, "/", go, { class: "link brand" }),
      h(
        "div",
        { class: "site-search" },
        Kit.textField({
          label: "Search products",
          placeholder: "Search products",
          value: s.query,
          key: "shop-search",
          onInput: (value) => MockOS.dispatch({ type: "shop.query", value }),
          onKey: (e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              go(`/search?q=${encodeURIComponent(e.target.value)}`);
            }
          },
        }),
        Kit.button({ label: "Search", onPress: () => go(`/search?q=${encodeURIComponent(s.query)}`) }),
      ),
      Sites.link(`Cart (${count})`, "/cart", go),
    );
    const rows = (products) =>
      h(
        "div",
        { class: "plist" },
        products.map((p) =>
          h(
            "div",
            { class: "prow" },
            Sites.link(p.name, `/product/${p.id}`, go),
            h("span", { class: "muted" }, p.category),
            h("span", { class: "price" }, money(p.price)),
            Kit.button({ label: "Add to cart", onPress: () => MockOS.dispatch({ type: "shop.add", id: p.id }) }),
          ),
        ),
      );
    let body;
    if (path === "/" || path === "") {
      body = [
        h("h1", {}, "This week's range"),
        rows(s.products),
        h(
          "div",
          { class: "signup" },
          h("h2", {}, "Newsletter"),
          h("p", {}, "Offers and new arrivals, once a month."),
          h(
            "div",
            { class: "inline" },
            Kit.textField({ label: "Email address", placeholder: "Email address", value: s.email, key: "shop-email", onInput: (value) => MockOS.dispatch({ type: "shop.email", value }) }),
            Kit.button({ label: "Sign up", onPress: () => MockOS.dispatch({ type: "shop.signup" }) }),
          ),
        ),
      ];
    } else if (path === "/search") {
      const q = (url.searchParams.get("q") || "").trim().toLowerCase();
      const found = s.products.filter((p) => q && (p.name.toLowerCase().includes(q) || p.category.toLowerCase().includes(q)));
      body = [h("h1", {}, `Results for “${url.searchParams.get("q") || ""}”`), found.length ? rows(found) : h("p", {}, "No products match.")];
    } else if (path.startsWith("/product/")) {
      const p = s.products.find((x) => x.id === path.slice(9));
      body = p
        ? [h("h1", {}, p.name), h("p", { class: "price big" }, money(p.price)), h("p", {}, p.blurb), Kit.button({ label: "Add to cart", primary: true, onPress: () => MockOS.dispatch({ type: "shop.add", id: p.id }) })]
        : [h("h1", {}, "Product not found")];
    } else if (path === "/cart") {
      const total = s.cart.reduce((n, l) => n + l.qty * s.products.find((p) => p.id === l.id).price, 0);
      body = [
        h("h1", {}, "Your cart"),
        s.cart.length
          ? h(
              "div",
              { class: "plist" },
              s.cart.map((l) => {
                const p = s.products.find((x) => x.id === l.id);
                return h("div", { class: "prow" }, h("span", {}, p.name), h("span", { class: "muted" }, `× ${l.qty}`), h("span", { class: "price" }, money(p.price * l.qty)), Kit.button({ label: "Remove", onPress: () => MockOS.dispatch({ type: "shop.remove", id: l.id }) }));
              }),
            )
          : h("p", {}, "Your cart is empty."),
        h("p", { class: "total" }, `Total ${money(total)}`),
        s.cart.length ? Kit.button({ label: "Checkout", primary: true, pointerOnly: s.pointerOnly, onPress: () => go("/checkout") }) : null,
      ];
    } else if (path === "/checkout") {
      const field = (name, label) => [
        h("label", { class: "form-label" }, label),
        Kit.textField({ label, placeholder: label, value: s.form[name], key: `shop-${name}`, onInput: (value) => MockOS.dispatch({ type: "shop.field", field: name, value }) }),
      ];
      body = [
        h("h1", {}, "Checkout"),
        h("div", { class: "form" }, field("name", "Full name"), field("street", "Street address"), field("city", "City"), field("postcode", "Postcode")),
        s.error ? h("p", { class: "error" }, s.error) : null,
        Kit.button({ label: "Place order", primary: true, onPress: () => MockOS.dispatch({ type: "shop.order" }) }),
      ];
    } else if (path === "/done") {
      body = [h("h1", {}, "Order placed"), h("p", {}, `Thank you. Order ${s.orders.length} is on its way.`), Sites.link("Continue shopping", "/", go)];
    } else body = [h("h1", {}, "Page not found")];
    return h(
      "div",
      { class: "site shop" },
      header,
      s.notice ? h("div", { class: "notice" }, s.notice) : null,
      h("div", { class: "site-body" }, body),
      s.banner
        ? h(
            "div",
            { class: "cookie-banner" },
            h("div", {}, h("b", {}, "We value your privacy. "), "We use cookies to remember your cart and to measure visits."),
            h("div", { class: "inline" }, Kit.button({ label: "Reject", onPress: () => MockOS.dispatch({ type: "shop.cookies", choice: "rejected" }) }), Kit.button({ label: "Accept all", primary: true, onPress: () => MockOS.dispatch({ type: "shop.cookies", choice: "accepted" }) })),
          )
        : null,
    );
  }

  Sites.add("shop.mockos.example", "shop", {
    title: (state, url) => (url.pathname.startsWith("/product/") ? `${(state.shop.products.find((p) => p.id === url.pathname.slice(9)) || { name: "Product" }).name} – ${state.shop.name}` : state.shop.name),
    render: shopRender,
    reduce: shopReduce,
    initial: () => ({ name: "Corner Shop", products: [], cart: [], orders: [], newsletter: [], banner: false, pointerOnly: true, form: { name: "", street: "", city: "", postcode: "" }, email: "", query: "", notice: null, error: null }),
  });

  // ----- tickets --------------------------------------------------------------------------------

  function ticketsRender(state, url, go) {
    const s = state.tickets;
    const path = url.pathname;
    const head = h("div", { class: "site-head" }, Sites.link("Stagefront Tickets", "/", go, { class: "link brand" }), h("span", { class: "muted" }, "Live music, theatre and talks"));
    let body;
    if (path === "/" || path === "") {
      const events = [...s.events].sort((a, b) => a.name.localeCompare(b.name)); // A to Z, so the soonest takes reading the dates
      body = [
        h("h1", {}, "Upcoming events"),
        h(
          "div",
          { class: "plist" },
          events.map((e) => h("div", { class: "prow" }, Sites.link(e.name, `/event/${e.id}`, go), h("span", {}, day(e.date)), h("span", { class: "muted" }, e.venue), h("span", { class: "price" }, `from ${money(Math.min(...e.tiers.map((t) => t.price)))}`))),
        ),
      ];
    } else if (path.startsWith("/event/")) {
      const e = s.events.find((x) => x.id === path.slice(7));
      body = e
        ? [
            h("h1", {}, e.name),
            h("p", {}, `${day(e.date)} · ${e.venue}`),
            h(
              "div",
              { class: "plist" },
              e.tiers.map((t) =>
                h("div", { class: "prow" }, h("span", {}, t.name), h("span", { class: "price" }, money(t.price)), Kit.button({ label: "Select", onPress: () => { MockOS.dispatch({ type: "tickets.select", event: e.id, tier: t.name }); go(`/checkout?event=${e.id}`); } })),
              ),
            ),
          ]
        : [h("h1", {}, "Event not found")];
    } else if (path === "/checkout") {
      const sel = s.selected;
      const e = sel && s.events.find((x) => x.id === sel.event);
      body = e
        ? [h("h1", {}, "Checkout"), h("p", {}, `${e.name} · ${day(e.date)}`), h("p", {}, `${sel.tier} · ${money(e.tiers.find((t) => t.name === sel.tier).price)}`), h("p", { class: "muted" }, "Payment is not part of the mock OS.")]
        : [h("h1", {}, "Nothing selected")];
    } else body = [h("h1", {}, "Page not found")];
    return h("div", { class: "site tickets" }, head, h("div", { class: "site-body" }, body));
  }

  Sites.add("tickets.mockos.example", "tickets", {
    title: (state, url) => (url.pathname.startsWith("/event/") ? `${(state.tickets.events.find((e) => e.id === url.pathname.slice(7)) || { name: "Event" }).name} – Stagefront` : url.pathname === "/checkout" ? "Checkout – Stagefront" : "Stagefront Tickets"),
    render: ticketsRender,
    slow: (state, url) => state.tickets.slow && (url.pathname === "/" || url.pathname === ""),
    reduce: (state, action) => {
      if (action.type === "tickets.select") state.tickets.selected = { event: action.event, tier: action.tier };
    },
    initial: () => ({ events: [], slow: false, selected: null }),
  });

  // ----- the wiki -------------------------------------------------------------------------------

  function wikiRender(state, url, go) {
    const s = state.wiki;
    const path = url.pathname;
    const head = h(
      "div",
      { class: "site-head" },
      Sites.link("Mockipedia", "/", go, { class: "link brand" }),
      h(
        "div",
        { class: "site-search" },
        Kit.textField({
          label: "Search Mockipedia",
          placeholder: "Search Mockipedia",
          value: s.query,
          key: "wiki-search",
          onInput: (value) => MockOS.dispatch({ type: "wiki.query", value }),
          onKey: (e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              go(`/search?q=${encodeURIComponent(e.target.value)}`);
            }
          },
        }),
      ),
    );
    let body;
    if (path === "/" || path === "") {
      body = [h("h1", {}, "Welcome to Mockipedia"), h("p", {}, "Featured articles:"), h("ul", {}, s.featured.map((f) => h("li", {}, Sites.link(f.label, `/wiki/${f.slug}`, go))))];
    } else if (path === "/search") {
      const q = (url.searchParams.get("q") || "").trim().toLowerCase();
      const found = Object.entries(s.articles).filter(([, a]) => q && a.title.toLowerCase().includes(q));
      body = [h("h1", {}, `Search results for “${url.searchParams.get("q") || ""}”`), found.length ? h("ul", {}, found.map(([slug, a]) => h("li", {}, Sites.link(a.title, `/wiki/${slug}`, go)))) : h("p", {}, "There were no results.")];
    } else if (path.startsWith("/wiki/")) {
      const a = s.articles[path.slice(6)];
      body = a
        ? [h("h1", {}, a.title), a.paras.map((p) => h("p", {}, p)), a.links.length ? [h("h2", {}, "See also"), h("ul", {}, a.links.map((l) => h("li", {}, Sites.link(l.label, `/wiki/${l.slug}`, go))))] : null]
        : [h("h1", {}, "Page not found"), h("p", {}, "There is no article at this address. It may have been moved or deleted."), Sites.link("Back to the main page", "/", go)];
    } else body = [h("h1", {}, "Page not found")];
    return h("div", { class: "site wiki" }, head, h("div", { class: "site-body" }, body));
  }

  Sites.add("wiki.mockos.example", "wiki", {
    title: (state, url) => (url.pathname.startsWith("/wiki/") ? `${(state.wiki.articles[url.pathname.slice(6)] || { title: "Not found" }).title} – Mockipedia` : "Mockipedia"),
    render: wikiRender,
    reduce: (state, action) => {
      if (action.type === "wiki.query") state.wiki.query = action.value;
    },
    initial: () => ({ articles: {}, featured: [], query: "" }),
  });

  // An address that is no site: a search. The mock has no search engine; it says so.
  Sites.add("search.mockos.example", "search", {
    title: () => "Search",
    render: (state, url, go) =>
      h("div", { class: "site" }, h("div", { class: "site-body" }, h("h1", {}, "Search is not part of the mock OS"), h("p", {}, `You searched for “${url.searchParams.get("q") || ""}”. Try one of these sites:`), ["https://shop.mockos.example/", "https://tickets.mockos.example/", "https://wiki.mockos.example/"].map((u) => h("p", {}, Sites.link(u, u, go))))),
  });
})();

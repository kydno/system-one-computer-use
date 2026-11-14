"""Tasks in the mock browser, and the content of its three sites.

Every product, event and article is made up for the mock. The sites live under the reserved
.example domain, so no address here can ever be a real site.
"""

from __future__ import annotations

import random
from datetime import date, timedelta

from . import MIDDLE, MOCK_EMAIL, Task, desktop, rng, says, template

SHOP = "https://shop.mockos.example"
TICKETS = "https://tickets.mockos.example"
WIKI = "https://wiki.mockos.example"
BLANK = "about:newtab"

PRODUCTS = (
    ("Linen tea towel", "Kitchen", "Woven linen, washed soft."),
    ("Enamel mug", "Kitchen", "Holds 350 ml, chips less than you would think."),
    ("Bamboo chopping board", "Kitchen", "Light, firm, and kind to knives."),
    ("Cast iron skillet", "Kitchen", "Seasoned and ready, 26 cm."),
    ("Wool throw", "Home", "Lambswool, 130 by 170 cm."),
    ("Ceramic plant pot", "Home", "With a saucer, for a plant up to 20 cm."),
    ("Desk lamp", "Home", "Warm light, a weighted base, a long cord."),
    ("Canvas tote bag", "Bags", "Carries a week of groceries."),
    ("Rain jacket", "Clothing", "Packs into its own pocket."),
    ("Merino socks", "Clothing", "Two pairs, mid weight."),
    ("Notebook, dotted", "Stationery", "A5, 160 pages, lies flat."),
    ("Fountain pen", "Stationery", "Fine nib, takes standard cartridges."),
)
KETTLES = (
    ("Steel kettle", "Kitchen", "1.7 litres, quiet to boil."),
    ("Glass kettle", "Kitchen", "Watch it boil, 1.5 litres."),
    ("Travel kettle", "Kitchen", "Folds flat, 0.6 litres."),
)

EVENTS = (
    ("Harbour Lights Orchestra", "Quay Hall"),
    ("The Paper Boats", "Old Market Rooms"),
    ("An Evening of Short Plays", "Little Theatre"),
    ("Jazz on the Terrace", "Riverside Pavilion"),
    ("Mira Solis Quartet", "Quay Hall"),
    ("Science of Sleep: a talk", "Civic Library"),
    ("Folk Night", "The Lantern"),
    ("Comedy Late", "Little Theatre"),
)
TIERS = (("Standing", (1800, 3200)), ("Seated", (3300, 5400)), ("Front rows", (5500, 9000)))

ARTICLES = {
    "old-mill": ("The Old Mill", "architect", ("Ada Brennan", "Tomas Kerr", "Lena Vos")),
    "harbour-lighthouse": ("Harbour Lighthouse", "year", ("1851", "1864", "1879", "1892")),
    "north-bridge": ("North Bridge", "length", ("212 metres", "184 metres", "247 metres")),
    "clock-tower": ("The Clock Tower", "bells", ("six bells", "eight bells", "five bells")),
}
FILLER = (
    "The town grew around the river crossing, and much of what stands today replaced timber buildings lost in the great fire.",
    "Records from the period are thin, and local histories disagree on the order of events in the early years.",
    "A restoration in the last century replaced the roof and most of the windows while keeping the original stonework.",
    "Visitors can reach the site on foot from the station in about twenty minutes, following the towpath.",
    "The surrounding streets keep their medieval plan, though few of the houses are older than two hundred years.",
    "A small museum nearby keeps drawings, letters and a model built by students of the technical college.",
    "During the war the building served as a store, and the marks of shelving can still be seen on the walls.",
    "Guided tours run in summer, and the upper floors are opened to the public on two weekends a year.",
)
FACT = {
    "architect": "The building was designed by {value}, whose drawings survive in the town archive.",
    "year": "The present tower was first lit in {value}, after nine years of work on the foundations.",
    "length": "The bridge is {value} long, with five arches of unequal span.",
    "bells": "The tower holds {value}, cast in two batches at the foundry across the river.",
}


def money(cents: int) -> str:
    return f"${cents // 100}.{cents % 100:02d}"


def day(d: date) -> str:
    return f"{d.strftime('%a')}, {d.strftime('%b')} {d.day}, {d.year}"


def shop_content(r: random.Random, kettles: bool = False) -> dict:
    pool = list(PRODUCTS)
    r.shuffle(pool)
    chosen = pool[:8]
    if kettles:
        chosen[2:2] = list(KETTLES)
        chosen = chosen[:10]
    products = [
        {"id": f"p{n + 1}", "name": name, "category": category, "blurb": blurb, "price": r.randrange(500, 9000, 25)}
        for n, (name, category, blurb) in enumerate(chosen)
    ]
    return {
        "name": "Corner Shop",
        "products": products,
        "cart": [],
        "orders": [],
        "newsletter": [],
        "banner": False,
        "pointerOnly": True,
        "form": {"name": "", "street": "", "city": "", "postcode": ""},
        "email": "",
        "query": "",
        "notice": None,
        "error": None,
    }


def tickets_content(r: random.Random, today: date) -> dict:
    events = []
    pool = list(EVENTS)
    r.shuffle(pool)
    offsets = r.sample(range(2, 60), k=6)
    for n, ((name, venue), offset) in enumerate(zip(pool[:6], offsets, strict=True)):
        tiers = [{"name": tier, "price": r.randrange(low, high, 50)} for tier, (low, high) in TIERS]
        events.append(
            {
                "id": f"e{n + 1}",
                "name": name,
                "venue": venue,
                "date": (today + timedelta(days=offset)).isoformat(),
                "tiers": tiers,
            }
        )
    return {"events": events, "slow": False, "selected": None}


def wiki_content(r: random.Random) -> dict:
    articles = {}
    facts = {}
    for slug, (title, kind, values) in ARTICLES.items():
        value = r.choice(values)
        facts[slug] = value
        paras = [r.choice(FILLER) + " " + r.choice(FILLER) for _ in range(16)]
        paras[12] = FACT[kind].format(value=value) + " " + r.choice(FILLER)
        links = [{"label": ARTICLES[other][0], "slug": other} for other in ARTICLES if other != slug][:2]
        articles[slug] = {"title": title, "paras": paras, "links": links}
    featured = [{"label": a["title"], "slug": slug} for slug, a in articles.items()]
    return {"articles": articles, "featured": featured, "query": "", "facts": facts}


def browser(*urls: str, active: int = 0, loading: bool = False) -> dict:
    tabs = [{"id": n + 1, "url": url, "back": [], "loading": loading and n == active} for n, url in enumerate(urls or (BLANK,))]
    return {"tabs": tabs, "active": active, "next": len(tabs) + 1, "editing": None}


def today_of(seed: dict) -> date:
    return date.fromisoformat(seed["clock"][:10])


def web_seed(r: random.Random, chromium: dict | None, front: str = "Chromium", **given) -> dict:
    """A desktop with the browser running (when `chromium` is given) and the sites' content."""
    seed = desktop(r, front, running=["Chromium"] if chromium is not None else (), **given)
    if chromium is not None:
        seed["chromium"] = chromium
    return seed


def active_url(final: dict) -> str | None:
    c = final.get("chromium")
    if not c:
        return None
    return c["tabs"][c["active"]]["url"]


def row_of(product: dict) -> tuple[str, str, str]:
    """A product's Add to cart button, told apart from the others by the product's name on its row."""
    return ("Add to cart", "button", product["name"])


# ----- the shop --------------------------------------------------------------------------------


@template("shop/add-to-cart", 2)
def add_to_cart(seed: int) -> Task:
    name = "shop/add-to-cart"
    r = rng(name, seed)
    shop = shop_content(r)
    product = r.choice(shop["products"][:5])
    s = web_seed(r, browser(f"{SHOP}/"), shop=shop)

    def check(final: dict, answer: str | None) -> bool:
        return final["shop"]["cart"] == [{"id": product["id"], "qty": 1}] and not final["shop"]["orders"]

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Put one {product['name'].lower()} in my cart on the Corner Shop site.",
        seed=s,
        check=check,
        oracle=(("click_item", row_of(product)),),
        tags=("click_item", "web", "repeated"),
    )


@template("shop/search", 2)
def search(seed: int) -> Task:
    name = "shop/search"
    r = rng(name, seed)
    shop = shop_content(r)
    product = r.choice(shop["products"])
    s = web_seed(r, browser(f"{SHOP}/"), shop=shop)
    word = product["name"].split(",")[0].split()[-1].lower()

    def check(final: dict, answer: str | None) -> bool:
        return active_url(final) == f"{SHOP}/product/{product['id']}" and not final["shop"]["cart"]

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Search the Corner Shop for “{word}” and open the page of the {product['name'].lower()}.",
        seed=s,
        check=check,
        oracle=(
            ("click_item", ("Search products", "field")),
            ("type_text", None),
            ("press_enter", None),
            ("click_item", (product["name"], "link")),
        ),
        writes=(word,),
        tags=("type_text", "web"),
    )


@template("shop/cheapest", 3)
def cheapest(seed: int) -> Task:
    name = "shop/cheapest"
    r = rng(name, seed)
    shop = shop_content(r, kettles=True)
    kettles = [p for p in shop["products"] if p["name"].endswith("kettle")]
    best = min(kettles, key=lambda p: p["price"])
    s = web_seed(r, browser(f"{SHOP}/"), shop=shop)

    def check(final: dict, answer: str | None) -> bool:
        return final["shop"]["cart"] == [{"id": best["id"], "qty": 1}] and active_url(final) == f"{SHOP}/checkout"

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal="On the Corner Shop, put the cheapest kettle in my cart and go to checkout.",
        seed=s,
        check=check,
        oracle=(("click_item", row_of(best)), ("click_item", ("Cart (1)", "link")), ("click_item", ("Checkout", "button"))),
        tags=("compare", "repeated", "web", "pointer"),
    )


@template("shop/banner", 3)
def banner(seed: int) -> Task:
    name = "shop/banner"
    r = rng(name, seed)
    shop = shop_content(r)
    shop["banner"] = True
    product = shop["products"][-1]  # the row the banner covers
    s = web_seed(r, browser(f"{SHOP}/"), shop=shop)

    def check(final: dict, answer: str | None) -> bool:
        return final["shop"]["cart"] == [{"id": product["id"], "qty": 1}]

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Add the {product['name'].lower()} to my cart on the Corner Shop.",
        seed=s,
        check=check,
        # The banner covers the row's button: the loop sees no ink there and drops it from the items,
        # and does not offer it off screen either, since the other rows' buttons carry its label. So
        # the way through is to close the banner first.
        oracle=(("click_item", ("Reject", "button")), ("click_item", row_of(product))),
        tags=("banner", "web"),
    )


@template("shop/pointer-only", 3)
def pointer_only(seed: int) -> Task:
    name = "shop/pointer-only"
    r = rng(name, seed)
    shop = shop_content(r)
    shop["cart"] = [{"id": shop["products"][0]["id"], "qty": 1}]
    s = web_seed(r, browser(f"{SHOP}/cart"), shop=shop)

    def check(final: dict, answer: str | None) -> bool:
        return active_url(final) == f"{SHOP}/checkout"

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal="Go on to checkout from my Corner Shop cart.",
        seed=s,
        check=check,
        oracle=(("click_item", ("Checkout", "button")),),
        tags=("pointer", "web"),
    )


@template("shop/form", 3)
def form(seed: int) -> Task:
    name = "shop/form"
    r = rng(name, seed)
    shop = shop_content(r)
    shop["cart"] = [{"id": shop["products"][1]["id"], "qty": 1}]
    who = r.choice(("Robin Hale", "Noor Patel", "Ari Lund", "Sam Okafor"))
    street = r.choice(("14 Mill Lane", "3 Orchard Row", "27 Station Road"))
    city = r.choice(("Bristol", "Leeds", "Norwich", "Exeter"))
    postcode = r.choice(("BS1 4DJ", "LS2 7EW", "NR3 1AB", "EX4 3PT"))
    s = web_seed(r, browser(f"{SHOP}/checkout"), shop=shop)

    def check(final: dict, answer: str | None) -> bool:
        orders = final["shop"]["orders"]
        return len(orders) == 1 and (orders[0]["name"], orders[0]["street"], orders[0]["city"], orders[0]["postcode"]) == (
            who,
            street,
            city,
            postcode,
        )

    steps = []
    for label in ("Full name", "Street address", "City", "Postcode"):
        steps += [("click_item", (label, "field")), ("type_text", None)]
    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Place my Corner Shop order: shipping to {who}, {street}, {city}, {postcode}.",
        seed=s,
        check=check,
        oracle=(*steps, ("click_item", ("Place order", "button"))),
        writes=(who, street, city, postcode),
        tags=("type_text", "form", "web"),
    )


@template("shop/newsletter", 2)
def newsletter(seed: int) -> Task:
    name = "shop/newsletter"
    r = rng(name, seed)
    shop = shop_content(r)
    s = web_seed(r, browser(f"{SHOP}/"), shop=shop)

    def check(final: dict, answer: str | None) -> bool:
        return final["shop"]["newsletter"] == [MOCK_EMAIL]

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal="Sign me up for the Corner Shop newsletter with my email.",
        seed=s,
        check=check,
        oracle=(
            ("scroll_down", MIDDLE),
            ("click_item", ("Email address", "field")),
            ("type_email", None),
            ("click_item", ("Sign up", "button")),
        ),
        tags=("type_email", "scroll", "web"),
    )


# ----- tickets ---------------------------------------------------------------------------------


@template("tickets/next-event", 3)
def next_event(seed: int) -> Task:
    name = "tickets/next-event"
    r = rng(name, seed)
    s = web_seed(r, browser(f"{TICKETS}/"))
    s["tickets"] = tickets_content(r, today_of(s))
    soonest = min(s["tickets"]["events"], key=lambda e: e["date"])
    tier = min(soonest["tiers"], key=lambda t: t["price"])

    def check(final: dict, answer: str | None) -> bool:
        return final["tickets"]["selected"] == {"event": soonest["id"], "tier": tier["name"]} and active_url(final).startswith(
            f"{TICKETS}/checkout"
        )

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal="On Stagefront Tickets, get to checkout for the cheapest ticket to the next upcoming event.",
        seed=s,
        check=check,
        oracle=(("click_item", (soonest["name"], "link")), ("click_item", ("Select", "button", tier["name"]))),
        tags=("dates", "compare", "web"),
    )


@template("tickets/slow", 3)
def slow(seed: int) -> Task:
    name = "tickets/slow"
    r = rng(name, seed)
    s = web_seed(r, browser(f"{TICKETS}/", loading=True))
    s["tickets"] = tickets_content(r, today_of(s))
    s["tickets"]["slow"] = True
    event = r.choice(s["tickets"]["events"])

    def check(final: dict, answer: str | None) -> bool:
        return active_url(final) == f"{TICKETS}/event/{event['id']}"

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Open the Stagefront page for {event['name']}.",
        seed=s,
        check=check,
        oracle=(("wait", None), ("click_item", (event["name"], "link"))),
        tags=("wait", "web"),
    )


@template("tickets/price", 3)
def price(seed: int) -> Task:
    name = "tickets/price"
    r = rng(name, seed)
    s = web_seed(r, browser(f"{TICKETS}/"))
    s["tickets"] = tickets_content(r, today_of(s))
    event = r.choice(s["tickets"]["events"])
    cost = money(min(t["price"] for t in event["tiers"]))

    def check(final: dict, answer: str | None) -> bool:
        return says(answer, cost) and final["tickets"]["selected"] is None

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"What does the cheapest ticket to {event['name']} cost on Stagefront?",
        seed=s,
        check=check,
        oracle=(("click_item", (event["name"], "link")),),
        tags=("answer", "web"),
        read_only=True,
    )


# ----- the wiki --------------------------------------------------------------------------------


@template("wiki/fact", 2)
def fact(seed: int) -> Task:
    name = "wiki/fact"
    r = rng(name, seed)
    wiki = wiki_content(r)
    slug = r.choice(list(ARTICLES))
    title, kind, _ = ARTICLES[slug]
    value = wiki["facts"][slug]
    question = {
        "architect": f"who designed {title.removeprefix('The ')}",
        "year": f"in what year {title} was first lit",
        "length": f"how long {title} is",
        "bells": f"how many bells {title} holds",
    }[kind]
    s = web_seed(r, browser(f"{WIKI}/wiki/{slug}"), wiki=wiki)

    def check(final: dict, answer: str | None) -> bool:
        return says(answer, value)

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Using the Mockipedia article that is open, tell me {question}.",
        seed=s,
        check=check,
        oracle=(("scroll_down", MIDDLE), ("scroll_down", MIDDLE)),
        tags=("answer", "scroll", "web"),
        read_only=True,
    )


@template("wiki/dead-link", 3)
def dead_link(seed: int) -> Task:
    name = "wiki/dead-link"
    r = rng(name, seed)
    wiki = wiki_content(r)
    slug = r.choice(list(ARTICLES))
    title = ARTICLES[slug][0]
    # The first link that names the article leads to a page that is gone.
    wiki["featured"].insert(0, {"label": f"{title} (history)", "slug": f"{slug}-history"})
    s = web_seed(r, browser(f"{WIKI}/"), wiki=wiki)

    def check(final: dict, answer: str | None) -> bool:
        return active_url(final) == f"{WIKI}/wiki/{slug}"

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Open the Mockipedia article on {title}.",
        seed=s,
        check=check,
        oracle=(("click_item", (f"{title} (history)", "link")), ("go_back", None), ("click_item", (title, "link"))),
        tags=("go_back", "web"),
    )


# ----- the browser -----------------------------------------------------------------------------


@template("browser/by-address", 2)
def by_address(seed: int) -> Task:
    name = "browser/by-address"
    r = rng(name, seed)
    s = web_seed(r, None, front="Files")
    s["tickets"] = tickets_content(r, today_of(s))
    event = r.choice(s["tickets"]["events"])

    def check(final: dict, answer: str | None) -> bool:
        return active_url(final) == f"{TICKETS}/event/{event['id']}"

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Go to tickets.mockos.example and open the page for {event['name']}.",
        seed=s,
        check=check,
        oracle=(("use_browser", "other"), ("click_item", (event["name"], "link"))),
        url=f"{TICKETS}/",
        tags=("use_browser", "web"),
    )


@template("browser/tab", 3)
def tab(seed: int) -> Task:
    name = "browser/tab"
    r = rng(name, seed)
    wiki = wiki_content(r)
    slug = r.choice(list(ARTICLES))
    title = ARTICLES[slug][0]
    s = web_seed(r, browser(f"{SHOP}/", f"{WIKI}/wiki/{slug}", f"{TICKETS}/"), wiki=wiki)

    def check(final: dict, answer: str | None) -> bool:
        c = final["chromium"]
        return active_url(final) == f"{WIKI}/wiki/{slug}" and len(c["tabs"]) == 3

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Go back to the tab with the Mockipedia article on {title}.",
        seed=s,
        check=check,
        oracle=(("click_item", (f"{title} \u2013 Mockipedia", "tab")),),
        tags=("tabs", "web"),
    )

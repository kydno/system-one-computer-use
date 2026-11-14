"""Tasks that cross apps, or that the writer has to settle: a question for the user, a hand-back.

Tier 4: read on one screen and act on another, open an app on the way, or stop and ask.
"""

from __future__ import annotations

from datetime import timedelta

from . import Task, desktop, rng, says, template
from .files import SEP
from .office import long_day, today_of
from .settings import rows_of
from .web import SHOP, TICKETS, browser, money, tickets_content


def ensure_events(s: dict, *names: str) -> None:
    """Put these events in the listing, in place of others, so a task can name them."""
    from .web import EVENTS

    events = s["tickets"]["events"]
    for n, name in enumerate(names):
        if not any(e["name"] == name for e in events):
            venue = next(v for e, v in EVENTS if e == name)
            events[n]["name"], events[n]["venue"] = name, venue


@template("cross/mail-to-calendar", 4)
def mail_to_calendar(seed: int) -> Task:
    name = "cross/mail-to-calendar"
    r = rng(name, seed)
    s = desktop(r, "Mail")
    today = today_of(s)
    day = today + timedelta(days=r.randint(2, 9))
    if day.month != today.month:
        day = today + timedelta(days=1)
    when = r.choice(("10:00", "14:30", "16:00"))
    sender = s["mail"]["messages"][0]
    sender.update(
        mailbox="Inbox",
        subject="Can we meet next week?",
        body=f"Hi,\nCould we meet on {day.strftime('%A')}, {day.strftime('%B')} {day.day} at {when} to go over the plans?\nBest,\n{sender['from'].split()[0]}",
        date=f"{today.isoformat()} 08:12",
        read=False,
    )
    before = len(s["calendar"]["events"])
    title = f"Meeting with {sender['from'].split()[0]}"

    def check(final: dict, answer: str | None) -> bool:
        events = final["calendar"]["events"]
        new = [e for e in events if (e["date"], e["start"]) == (day.isoformat(), when)]
        return len(events) == before + 1 and len(new) == 1

    return Task(
        id=f"{name}@{seed}",
        tier=4,
        goal=f"{sender['from'].split()[0]} emailed to ask for a meeting. Put it in my calendar.",
        seed=s,
        check=check,
        oracle=(
            ("click_item", (sender["from"], "cell")),
            ("open_app", "Calendar"),
            ("click_item", ("New Event", "button")),
            ("click_item", ("Title", "field")),
            ("type_text", None),
            ("click_item", ("Date", "popup")),
            ("click_item", (long_day(day.isoformat()), "button")),
            ("click_item", ("Starts", "popup")),
            ("click_item", (when, "menu item")),
            ("click_item", ("Save", "button")),
        ),
        writes=(title,),
        tags=("open_app", "type_text", "dates", "cross"),
    )


@template("cross/price-to-note", 4)
def price_to_note(seed: int) -> Task:
    name = "cross/price-to-note"
    r = rng(name, seed)
    s = desktop(r, "Notes", running=["Chromium"])
    s["chromium"] = browser(f"{SHOP}/")
    product = r.choice(s["shop"]["products"][:6])
    price = money(product["price"])
    before = len(s["notes"]["notes"])

    def check(final: dict, answer: str | None) -> bool:
        notes = final["notes"]["notes"]
        return len(notes) == before + 1 and any(says(n["body"], price) for n in notes)

    return Task(
        id=f"{name}@{seed}",
        tier=4,
        goal=f"Look up the price of the {product['name'].lower()} on the Corner Shop and write it down in a new note.",
        seed=s,
        check=check,
        oracle=(
            ("use_browser", "none"),
            ("open_app", "Notes"),
            ("click_item", ("New Note", "button")),
            ("type_text", None),
        ),
        writes=(f"{product['name']}\n{price}",),
        tags=("use_browser", "open_app", "type_text", "cross"),
    )


@template("cross/note-to-files", 4)
def note_to_files(seed: int) -> Task:
    name = "cross/note-to-files"
    r = rng(name, seed)
    s = desktop(r, "Notes")
    f = s["files"]
    f["cwd"] = "/Home/Downloads"
    path = r.choice(sorted(p for p, e in f["entries"].items() if p.startswith("/Home/Downloads/") and e["kind"] == "file"))
    file = path.rsplit("/", 1)[1]
    folder = r.choice(("Receipts", "Travel"))
    note = s["notes"]["notes"][0]
    note.update(body=f"To file\nMove {file} from Downloads into Documents{SEP}{folder}", updated=f"{s['clock'][:10]} 07:58")
    s["notes"]["selected"] = note["id"]
    to = f"/Home/Documents/{folder}/{file}"

    def check(final: dict, answer: str | None) -> bool:
        entries = final["files"]["entries"]
        return to in entries and path not in entries

    return Task(
        id=f"{name}@{seed}",
        tier=4,
        goal="Do what my “To file” note says.",
        seed=s,
        check=check,
        oracle=(
            ("open_app", "Files"),
            ("click_item", (file, "cell")),
            ("click_item", ("Move to…", "button")),
            ("click_item", (SEP.join(("Home", "Documents", folder)), "cell")),
            ("click_item", ("Move", "button")),
        ),
        tags=("open_app", "dialog", "cross"),
    )


@template("cross/ask", 4)
def ask(seed: int) -> Task:
    """A goal that leaves a choice open: the writer asks, and the scripted user answers."""
    name = "cross/ask"
    r = rng(name, seed)
    s = desktop(r, "Chromium", running=["Chromium"])
    s["chromium"] = browser(f"{TICKETS}/")
    s["tickets"] = tickets_content(r, today_of(s))
    ensure_events(s, "Harbour Lights Orchestra", "Mira Solis Quartet")
    chosen = r.choice(("Harbour Lights Orchestra", "Mira Solis Quartet"))
    event = next(e for e in s["tickets"]["events"] if e["name"] == chosen)

    def check(final: dict, answer: str | None) -> bool:
        return final["tickets"]["selected"] == {"event": event["id"], "tier": "Standing"}

    return Task(
        id=f"{name}@{seed}",
        tier=4,
        goal="Get me to checkout for a standing ticket to the Quay Hall concert on Stagefront.",
        seed=s,
        check=check,
        oracle=(("none", None), ("click_item", (chosen, "link")), ("click_item", ("Select", "button", "Standing"))),
        actions=2,
        reviews=(
            {"question": "Two concerts are at Quay Hall: Harbour Lights Orchestra and Mira Solis Quartet. Which one?"},
            {"focus": f"Open the '{chosen}' event"},
        ),
        replies=(f"The {chosen} one.",),
        tags=("question", "writer", "web"),
    )


@template("cross/two-good-moves", 4)
def two_good_moves(seed: int) -> Task:
    """Two first moves are both right: the classifier is unsure, and the writer's focus settles it."""
    name = "cross/two-good-moves"
    r = rng(name, seed)
    s = desktop(r, "Settings")
    settings = s["settings"]
    display = next(p for p in settings["panes"] if p["name"] == "Display")
    settings["pane"] = display["id"]
    rows = rows_of(settings)
    rows["night-light"]["on"] = False
    rows["night-light-schedule"]["value"] = "Sunset to sunrise"

    def check(final: dict, answer: str | None) -> bool:
        got = rows_of(final["settings"])
        return got["night-light"]["on"] is True and got["night-light-schedule"]["value"] == "Custom"

    return Task(
        id=f"{name}@{seed}",
        tier=4,
        goal="Turn on Night light and give it a custom schedule.",
        seed=s,
        check=check,
        oracle=(
            ("click_item", ("Night light", "checkbox"), 0.3),
            ("click_item", ("Night light", "checkbox")),
            ("click_item", ("Night light schedule", "popup")),
            ("click_item", ("Custom", "menu item")),
        ),
        actions=3,
        reviews=({"focus": "Turn on the 'Night light' switch first, then set its schedule"},),
        tags=("low confidence", "writer"),
    )

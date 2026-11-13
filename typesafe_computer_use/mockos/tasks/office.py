"""Mail, Calendar and Notes tasks, and the messages, events and notes they start with.

Every name, address and message is made up for the mock; the addresses are under .example.
"""

from __future__ import annotations

import copy
import random
from datetime import date, timedelta

from . import Task, desktop, rng, says, template

PEOPLE = (
    ("Priya Raman", "priya.raman@harbourworks.example"),
    ("Jonas Weber", "jonas.weber@northfield.example"),
    ("Ines Duarte", "ines@duarte-design.example"),
    ("Kofi Mensah", "kofi.mensah@quaylabs.example"),
    ("Hana Sato", "hana.sato@riverside.example"),
    ("Lucas Moreau", "lucas.moreau@atelier.example"),
    ("Freya Lind", "freya.lind@lindco.example"),
    ("Omar Haddad", "omar@haddad-partners.example"),
)
TOPICS = (
    ("Invoice for March", "Please find the March invoice attached. Payment is due within 30 days."),
    ("Garden club schedule", "The garden club meets every second Thursday. Bring gloves and a trowel."),
    ("Your parcel is on its way", "Your parcel left the depot this morning and should arrive in two days."),
    ("Quarterly numbers", "The draft of the quarterly numbers is ready for a first look."),
    ("Kitchen renovation quote", "Here is the quote for the kitchen work we discussed on site."),
    ("Book club: next title", "We settled on a novel about a lighthouse keeper for next month."),
    ("Car service reminder", "Your car is due for its annual service. Reply to book a slot."),
    ("Photos from the weekend", "A few photos from the hike, the view from the ridge was worth it."),
    ("Team lunch on Friday", "Shall we try the new place by the river for the team lunch?"),
    ("Updated floor plan", "The architect sent an updated floor plan with the larger window."),
)
EVENT_TITLES = (
    "Dentist",
    "Team stand-up",
    "Yoga class",
    "Call with the bank",
    "Piano lesson",
    "Lunch with Ines",
    "Project review",
    "Haircut",
    "School pickup",
    "Gym",
)
NOTE_BODIES = (
    "Groceries\nOat milk\nLemons\nRice\nCoffee beans",
    "Gift ideas\nA good pen for Dad\nPlant for Hana\nBoard game for the twins",
    "Trip packing\nPassport\nChargers\nRain jacket\nWalking shoes",
    "Books to read\nThe lighthouse novel\nA history of bridges\nSomething light for the train",
    "Wifi at the cabin\nNetwork: Pinecone\nThe code is on the fridge",
    "Paint for the hallway\nColour: Harbour Grey\nTwo litres, satin finish",
    "Questions for the landlord\nWhen is the boiler serviced?\nCan we hang shelves?",
    "Recipe: lentil soup\nOnion, carrot, celery\nRed lentils\nCumin and lemon",
)


def stamp(d: date, r: random.Random) -> str:
    return f"{d.isoformat()} {r.randint(7, 20):02d}:{r.choice((0, 5, 15, 22, 30, 41, 50)):02d}"


def mail_content(r: random.Random, today: date) -> dict:
    messages = []
    people = list(PEOPLE)
    topics = list(TOPICS)
    r.shuffle(people)
    r.shuffle(topics)
    for n, ((who, address), (subject, body)) in enumerate(zip(people * 2, topics, strict=False)):
        mailbox = "Archive" if n >= 8 else "Inbox"
        messages.append(
            {
                "id": f"m{n + 1}",
                "mailbox": mailbox,
                "from": who,
                "address": address,
                "to": "me@mockos.example",
                "subject": subject,
                "body": f"Hi,\n{body}\nBest,\n{who.split()[0]}",
                "date": stamp(today - timedelta(days=r.randint(0, 20)), r),
                "flagged": False,
                "read": r.random() < 0.6,
            }
        )
    return {"mailbox": "Inbox", "selected": None, "query": "", "compose": None, "messages": messages}


def calendar_content(r: random.Random, today: date) -> dict:
    events = []
    for n in range(9):
        d = today + timedelta(days=r.randint(-10, 18))
        events.append(
            {
                "id": f"ev{n + 1}",
                "title": r.choice(EVENT_TITLES),
                "date": d.isoformat(),
                "start": f"{r.randint(8, 17):02d}:{r.choice(('00', '30'))}",
            }
        )
    return {"month": today.isoformat()[:7], "selected": today.isoformat(), "events": events, "editor": None}


def notes_content(r: random.Random, today: date) -> dict:
    bodies = list(NOTE_BODIES)
    r.shuffle(bodies)
    notes = [
        {"id": f"n{n + 1}", "body": body, "updated": stamp(today - timedelta(days=r.randint(1, 40)), r)}
        for n, body in enumerate(bodies[:6])
    ]
    latest = max(notes, key=lambda n: n["updated"])
    return {"selected": latest["id"], "query": "", "notes": notes, "next": len(notes) + 1}


def today_of(seed: dict) -> date:
    return date.fromisoformat(seed["clock"][:10])


def inbox(seed: dict) -> list[dict]:
    return sorted((m for m in seed["mail"]["messages"] if m["mailbox"] == "Inbox"), key=lambda m: m["date"], reverse=True)


def sent(final: dict) -> list[dict]:
    return [m for m in final["mail"]["messages"] if m["mailbox"] == "Sent"]


def long_day(d: str) -> str:
    x = date.fromisoformat(d)
    return f"{x.strftime('%A')}, {x.strftime('%B')} {x.day}, {x.year}"


# ----- Mail ------------------------------------------------------------------------------------


@template("mail/who-sent", 1)
def who_sent(seed: int) -> Task:
    name = "mail/who-sent"
    r = rng(name, seed)
    s = desktop(r, "Mail")
    m = r.choice(inbox(s)[:6])

    def check(final: dict, answer: str | None) -> bool:
        return says(answer, m["from"].split()[0])

    return Task(
        id=f"{name}@{seed}",
        tier=1,
        goal=f"Who sent me the email about “{m['subject'].lower()}”?",
        seed=s,
        check=check,
        oracle=(),
        tags=("answer",),
        read_only=True,
    )


@template("mail/flag", 2)
def flag(seed: int) -> Task:
    name = "mail/flag"
    r = rng(name, seed)
    s = desktop(r, "Mail")
    m = r.choice(inbox(s)[:6])
    start = copy.deepcopy(s["mail"]["messages"])

    def check(final: dict, answer: str | None) -> bool:
        got = {x["id"]: x["flagged"] for x in final["mail"]["messages"]}
        return got == {x["id"]: x["id"] == m["id"] for x in start}

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Flag the email from {m['from']}.",
        seed=s,
        check=check,
        oracle=(("click_item", ("Flag", "button", None, m["from"])),),
        tags=("repeated",),
    )


@template("mail/search", 2)
def search(seed: int) -> Task:
    name = "mail/search"
    r = rng(name, seed)
    s = desktop(r, "Mail")
    m = r.choice([x for x in s["mail"]["messages"] if x["mailbox"] == "Archive"])
    word = m["subject"].split()[-1]

    def check(final: dict, answer: str | None) -> bool:
        return final["mail"]["selected"] == m["id"]

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Find and open the email about “{m['subject'].lower()}”. Search for “{word.lower()}”.",
        seed=s,
        check=check,
        oracle=(("click_item", ("Search", "field")), ("type_text", None), ("click_item", (m["from"], "cell"))),
        writes=(word.lower(),),
        tags=("type_text", "search"),
    )


@template("mail/reply", 3)
def reply(seed: int) -> Task:
    name = "mail/reply"
    r = rng(name, seed)
    s = desktop(r, "Mail")
    m = r.choice(inbox(s)[:6])
    line = r.choice(("Thanks, that works for me.", "Got it, I will look this week.", "Thank you, see you then."))

    def check(final: dict, answer: str | None) -> bool:
        out = sent(final)
        return len(out) == 1 and out[0]["to"] == m["address"] and out[0]["replyTo"] == m["id"] and says(out[0]["body"], line)

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Reply to {m['from']}'s email about “{m['subject'].lower()}” with: {line}",
        seed=s,
        check=check,
        oracle=(
            ("click_item", (m["from"], "cell")),
            ("click_item", ("Reply", "button")),
            ("click_item", ("Message body", "field")),
            ("type_text", None),
            ("click_item", ("Send", "button")),
        ),
        writes=(line,),
        tags=("type_text", "writer", "dialog"),
    )


@template("mail/compose", 3)
def compose(seed: int) -> Task:
    name = "mail/compose"
    r = rng(name, seed)
    s = desktop(r, "Mail")
    _, address = r.choice(PEOPLE)
    subject = r.choice(("Saturday plans", "Spare keys", "The plant cuttings"))
    body = r.choice(
        ("Are you free on Saturday morning?", "I left the spare keys with the neighbour.", "The cuttings are ready to pick up.")
    )

    def check(final: dict, answer: str | None) -> bool:
        out = sent(final)
        return len(out) == 1 and out[0]["to"] == address and out[0]["subject"] == subject and says(out[0]["body"], body)

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Email {address} with the subject “{subject}” saying: {body}",
        seed=s,
        check=check,
        oracle=(
            ("click_item", ("New Message", "button")),
            ("click_item", ("To", "field")),
            ("type_text", None),
            ("click_item", ("Subject", "field")),
            ("type_text", None),
            ("click_item", ("Message body", "field")),
            ("type_text", None),
            ("click_item", ("Send", "button")),
        ),
        writes=(address, subject, body),
        tags=("type_text", "form", "dialog"),
    )


# ----- Calendar --------------------------------------------------------------------------------


@template("calendar/whats-on", 2)
def whats_on(seed: int) -> Task:
    name = "calendar/whats-on"
    r = rng(name, seed)
    s = desktop(r, "Calendar")
    today = today_of(s)
    e = r.choice([x for x in s["calendar"]["events"] if x["date"] > today.isoformat()] or s["calendar"]["events"])
    same_day = [x for x in s["calendar"]["events"] if x["date"] == e["date"]]

    def check(final: dict, answer: str | None) -> bool:
        return all(says(answer, x["title"]) for x in same_day)

    d = date.fromisoformat(e["date"])
    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"What is in my calendar on {d.strftime('%A')} {d.strftime('%B')} {d.day}?",
        seed=s,
        check=check,
        oracle=(("click_item", (long_day(e["date"]), "cell")),),
        tags=("answer", "dates"),
        read_only=True,
    )


@template("calendar/create", 3)
def create(seed: int) -> Task:
    name = "calendar/create"
    r = rng(name, seed)
    s = desktop(r, "Calendar")
    today = today_of(s)
    day = today + timedelta(days=r.randint(2, 12))
    if day.month != today.month:
        day = today + timedelta(days=1)
    title = r.choice(("Plumber visit", "Coffee with Kofi", "Pick up glasses", "Swim lesson"))
    start = r.choice(("10:00", "14:30", "16:00"))
    before = len(s["calendar"]["events"])

    def check(final: dict, answer: str | None) -> bool:
        events = final["calendar"]["events"]
        new = [e for e in events if e["title"] == title]
        return len(events) == before + 1 and len(new) == 1 and (new[0]["date"], new[0]["start"]) == (day.isoformat(), start)

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Add “{title}” to my calendar on {day.strftime('%B')} {day.day} at {start}.",
        seed=s,
        check=check,
        oracle=(
            ("click_item", ("New Event", "button")),
            ("click_item", ("Title", "field")),
            ("type_text", None),
            ("click_item", ("Date", "popup")),
            ("click_item", (long_day(day.isoformat()), "button")),
            ("click_item", ("Starts", "popup")),
            ("click_item", (start, "menu item")),
            ("click_item", ("Save", "button")),
        ),
        writes=(title,),
        tags=("type_text", "dates", "dialog", "menu"),
    )


@template("calendar/move", 3)
def move(seed: int) -> Task:
    name = "calendar/move"
    r = rng(name, seed)
    s = desktop(r, "Calendar")
    today = today_of(s)
    events = s["calendar"]["events"]
    e = r.choice([x for x in events if x["date"][:7] == today.isoformat()[:7] and x["date"] != today.isoformat()] or events)
    e["title"] = "Car service"
    s["calendar"]["selected"] = e["date"]
    s["calendar"]["month"] = e["date"][:7]
    old = date.fromisoformat(e["date"])
    new = old + timedelta(days=1 if old.day < 27 else -1)
    start = copy.deepcopy(events)

    def check(final: dict, answer: str | None) -> bool:
        got = {x["id"]: (x["title"], x["date"], x["start"]) for x in final["calendar"]["events"]}
        want = {x["id"]: (x["title"], new.isoformat() if x["id"] == e["id"] else x["date"], x["start"]) for x in start}
        return got == want

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Move my car service to {new.strftime('%B')} {new.day}, same time.",
        seed=s,
        check=check,
        oracle=(
            ("click_item", (f"{e['start']} Car service", "button")),
            ("click_item", ("Date", "popup")),
            ("click_item", (long_day(new.isoformat()), "button")),
            ("click_item", ("Save", "button")),
        ),
        tags=("dates", "dialog"),
    )


# ----- Notes -----------------------------------------------------------------------------------


@template("notes/new", 2)
def new_note(seed: int) -> Task:
    name = "notes/new"
    r = rng(name, seed)
    s = desktop(r, "Notes")
    title = r.choice(("Plumber", "Birthday party", "Bike repair"))
    line = r.choice(("Call back on Monday", "Bring the blue folder", "Ask about the warranty"))
    before = len(s["notes"]["notes"])

    def check(final: dict, answer: str | None) -> bool:
        notes = final["notes"]["notes"]
        new = [n for n in notes if n["body"].strip().splitlines()[:1] == [title]]
        return len(notes) == before + 1 and len(new) == 1 and says(new[0]["body"], line)

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Make a new note titled “{title}” that says “{line}”.",
        seed=s,
        check=check,
        oracle=(("click_item", ("New Note", "button")), ("type_text", None)),
        writes=(f"{title}\n{line}",),
        tags=("type_text",),
    )


@template("notes/append", 3)
def append(seed: int) -> Task:
    name = "notes/append"
    r = rng(name, seed)
    s = desktop(r, "Notes")
    note = next(n for n in s["notes"]["notes"] if n["id"] == s["notes"]["selected"])
    title = note["body"].splitlines()[0]
    line = r.choice(("Batteries", "Ask Omar", "Check the receipt"))
    lines = note["body"].splitlines()

    def check(final: dict, answer: str | None) -> bool:
        body = next(n["body"] for n in final["notes"]["notes"] if n["id"] == note["id"]).splitlines()
        return line in [b.strip() for b in body] and all(x in body for x in lines) and len(body) == len(lines) + 1

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal=f"Add a line “{line}” to my “{title}” note, keeping what is there.",
        seed=s,
        check=check,
        oracle=(("click_item", ("Note", "field")), ("type_text", None)),
        writes=(line,),
        tags=("type_text", "editor"),
    )


@template("notes/find", 2)
def find(seed: int) -> Task:
    name = "notes/find"
    r = rng(name, seed)
    s = desktop(r, "Notes")
    note = r.choice(s["notes"]["notes"])
    lines = note["body"].splitlines()
    clue = lines[-1].split()[-1].strip(".,")
    title = lines[0]

    def check(final: dict, answer: str | None) -> bool:
        return says(answer, title)

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Which of my notes mentions “{clue.lower()}”?",
        seed=s,
        check=check,
        oracle=(("click_item", ("Search", "field")), ("type_text", None)),
        writes=(clue.lower(),),
        reviews=({"achieved": True, "answer": f"The note “{title}” mentions it."},),
        tags=("answer", "search", "type_text"),
        read_only=True,
    )

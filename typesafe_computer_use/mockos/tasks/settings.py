"""Settings tasks, and the content of the Settings app they start from.

The panes and rows are made up for the mock, in ordinary words. A seed shuffles which value each
row holds, so two seeds of one template are different screens with the same shape. Density is
provisional until the survey of the real app gives a profile (docs/mock-os-plan.md): about fifteen
panes in the sidebar and eight to fourteen rows a pane, near what a real settings window shows.
"""

from __future__ import annotations

import copy
import random

from . import Task, desktop, rng, says, template

# (pane name, icon letter, icon color, groups): each group is (title, rows), and each row is
# (label, kind, options or None, note or None). Every label is unique across the app, so a check
# and an oracle can name a row by its label alone.
SWITCH, POPUP, RADIO, VALUE, BUTTON = "switch", "popup", "radio", "value", "button"
CATALOGUE: tuple[tuple[str, str, str, tuple], ...] = (
    (
        "General",
        "G",
        "#8e8e93",
        (
            (
                "",
                (
                    ("Device name", VALUE, None, None),
                    ("Software version", VALUE, None, None),
                    ("Serial number", VALUE, None, None),
                ),
            ),
            (
                "Startup",
                (
                    ("Open last session at login", SWITCH, None, "Reopen the windows that were open at log out"),
                    ("Start-up sound", SWITCH, None, None),
                    ("Language", POPUP, ("English", "Deutsch", "Español", "Français", "Italiano", "Nederlands"), None),
                ),
            ),
            ("Reset", (("Reset all settings", BUTTON, ("Reset…", "reset"), "Return every setting to how it came"),)),
        ),
    ),
    (
        "Network",
        "N",
        "#2f6fdf",
        (
            (
                "",
                (
                    ("Wireless", SWITCH, None, None),
                    ("Ask to join new networks", SWITCH, None, "Known networks are joined on their own"),
                    ("Limit IP address tracking", SWITCH, None, None),
                ),
            ),
            (
                "Advanced",
                (
                    ("Proxy configuration", POPUP, ("None", "Automatic", "Manual"), None),
                    ("Network location", POPUP, ("Home", "Office", "Travel"), None),
                    ("Firewall", SWITCH, None, "Block incoming connections from unknown apps"),
                ),
            ),
        ),
    ),
    (
        "Sound",
        "S",
        "#e0457b",
        (
            (
                "Output",
                (
                    ("Output device", POPUP, ("Built-in Speakers", "Headphones", "Desk Monitor"), None),
                    ("Balance", RADIO, ("Left", "Centre", "Right"), None),
                    ("Mute when headphones are removed", SWITCH, None, None),
                ),
            ),
            (
                "Alerts",
                (
                    ("Alert sound", POPUP, ("Chime", "Pop", "Bell", "Click", "Drum"), None),
                    ("Play feedback when volume is changed", SWITCH, None, None),
                    ("Play sound on start-up", SWITCH, None, None),
                ),
            ),
        ),
    ),
    (
        "Display",
        "D",
        "#3a8ee6",
        (
            (
                "",
                (
                    ("Resolution", RADIO, ("Larger text", "Default", "More space"), None),
                    ("Automatically adjust brightness", SWITCH, None, None),
                    ("Refresh rate", POPUP, ("60 Hz", "75 Hz", "120 Hz"), None),
                ),
            ),
            (
                "Night light",
                (
                    ("Night light", SWITCH, None, "Warmer colors after sunset"),
                    ("Night light schedule", POPUP, ("Sunset to sunrise", "Custom", "Off"), None),
                    ("Colour profile", VALUE, None, None),
                ),
            ),
        ),
    ),
    (
        "Notifications",
        "!",
        "#e5484d",
        (
            (
                "",
                (
                    ("Show previews", RADIO, ("Always", "When unlocked", "Never"), None),
                    ("Allow notifications when the display is asleep", SWITCH, None, None),
                    ("Allow notifications when mirroring", SWITCH, None, None),
                    ("Group notifications by app", SWITCH, None, None),
                ),
            ),
            (
                "Summary",
                (
                    ("Daily summary", SWITCH, None, "Collect quieter notifications into one delivery"),
                    ("Summary time", POPUP, ("8:00", "12:00", "18:00", "21:00"), None),
                ),
            ),
            (
                "Apps",
                tuple((app, BUTTON, ("Options…", "style"), None) for app in ("Browser", "Calendar", "Files", "Mail", "Notes")),
            ),
        ),
    ),
    (
        "Appearance",
        "A",
        "#6e56cf",
        (
            (
                "",
                (
                    ("Theme", RADIO, ("Light", "Dark", "Auto"), None),
                    ("Accent colour", POPUP, ("Blue", "Purple", "Pink", "Orange", "Green", "Graphite"), None),
                    ("Sidebar icon size", POPUP, ("Small", "Medium", "Large"), None),
                    ("Show scroll bars", RADIO, ("While scrolling", "Always"), None),
                    ("Click in the scroll bar to", RADIO, ("Jump to the next page", "Jump to the spot clicked"), None),
                ),
            ),
        ),
    ),
    (
        "Keyboard",
        "K",
        "#5b6b7b",
        (
            (
                "",
                (
                    ("Key repeat rate", POPUP, ("Off", "Slow", "Normal", "Fast"), None),
                    ("Delay until repeat", POPUP, ("Long", "Normal", "Short"), None),
                    ("Adjust keyboard brightness in low light", SWITCH, None, None),
                    ("Use F1, F2, etc. keys as standard function keys", SWITCH, None, None),
                ),
            ),
            (
                "Text input",
                (
                    ("Correct spelling automatically", SWITCH, None, None),
                    ("Capitalise words automatically", SWITCH, None, None),
                    ("Add full stop with double-space", SWITCH, None, None),
                ),
            ),
        ),
    ),
    (
        "Mouse",
        "M",
        "#4a9c8c",
        (
            (
                "",
                (
                    ("Tracking speed", POPUP, ("Slow", "Medium", "Fast"), None),
                    ("Natural scrolling", SWITCH, None, "Content follows the movement of your fingers"),
                    ("Secondary click", POPUP, ("Click on right side", "Click on left side", "Off"), None),
                    ("Double-click speed", RADIO, ("Slow", "Normal", "Fast"), None),
                ),
            ),
        ),
    ),
    (
        "Battery",
        "B",
        "#34a853",
        (
            (
                "",
                (
                    ("Battery health", VALUE, None, None),
                    ("Low power mode", POPUP, ("Never", "Always", "Only on battery", "Only on adapter"), None),
                    ("Optimised charging", SWITCH, None, "Charge to full just before you usually unplug"),
                    ("Show battery percentage", SWITCH, None, None),
                ),
            ),
            (
                "Energy",
                (
                    ("Turn display off after", POPUP, ("2 minutes", "5 minutes", "10 minutes", "Never"), None),
                    ("Wake for network access", SWITCH, None, None),
                    ("Prevent automatic sleeping on adapter", SWITCH, None, None),
                ),
            ),
        ),
    ),
    (
        "Privacy",
        "P",
        "#2b70c9",
        (
            (
                "",
                (
                    ("Location services", SWITCH, None, None),
                    ("Share analytics", SWITCH, None, "Send anonymous diagnostics to help improve the system"),
                    ("Personalised ads", SWITCH, None, None),
                    (
                        "Require password after sleep",
                        POPUP,
                        ("Immediately", "After 1 minute", "After 5 minutes", "After 1 hour"),
                        None,
                    ),
                ),
            ),
            (
                "Security",
                (
                    ("Allow apps downloaded from", RADIO, ("App store", "App store and known developers"), None),
                    ("Disk encryption", VALUE, None, None),
                ),
            ),
        ),
    ),
    (
        "Accounts",
        "U",
        "#a06a3a",
        (
            (
                "",
                (
                    ("Signed in as", VALUE, None, None),
                    ("Automatic login", POPUP, ("Off", "On for this account"), None),
                    ("Show user list at login", SWITCH, None, None),
                    ("Guest user", SWITCH, None, None),
                ),
            ),
        ),
    ),
    (
        "Date & Time",
        "T",
        "#d97b29",
        (
            (
                "",
                (
                    ("Set time automatically", SWITCH, None, None),
                    ("Time zone", VALUE, None, None),
                    ("Time format", RADIO, ("12-hour", "24-hour"), None),
                    ("Show date in the top bar", SWITCH, None, None),
                    ("First day of week", POPUP, ("Monday", "Saturday", "Sunday"), None),
                ),
            ),
        ),
    ),
    (
        "Sharing",
        "H",
        "#3f8f5b",
        (
            (
                "",
                (
                    ("File sharing", SWITCH, None, None),
                    ("Screen sharing", SWITCH, None, None),
                    ("Printer sharing", SWITCH, None, None),
                    ("Remote login", SWITCH, None, None),
                    ("Media sharing", SWITCH, None, None),
                    ("Local hostname", VALUE, None, None),
                ),
            ),
        ),
    ),
    (
        "Accessibility",
        "X",
        "#1f7ae0",
        (
            (
                "Vision",
                (
                    ("Zoom", SWITCH, None, None),
                    ("Increase contrast", SWITCH, None, None),
                    ("Reduce transparency", SWITCH, None, None),
                    ("Pointer size", POPUP, ("Normal", "Large", "Larger"), None),
                ),
            ),
            (
                "Hearing",
                (
                    ("Flash the screen for alerts", SWITCH, None, None),
                    ("Play stereo audio as mono", SWITCH, None, None),
                    ("Captions style", POPUP, ("Default", "Classic", "Large text"), None),
                ),
            ),
            (
                "Motor",
                (
                    ("Sticky keys", SWITCH, None, None),
                    ("Slow keys", SWITCH, None, None),
                    ("Mouse keys", SWITCH, None, None),
                    ("Dwell control", SWITCH, None, None),
                    ("Spring-loading speed", RADIO, ("Short", "Medium", "Long"), None),
                    ("Head pointer", SWITCH, None, "Move the pointer by moving your head in front of the camera"),
                    ("Voice control", SWITCH, None, None),
                    ("Switch control", SWITCH, None, None),
                ),
            ),
        ),
    ),
    (
        "Storage",
        "D",
        "#7a7a80",
        (
            (
                "",
                (
                    ("Available", VALUE, None, None),
                    ("Empty bin automatically", SWITCH, None, "Remove items that have been in the bin for 30 days"),
                    ("Store files in the cloud", SWITCH, None, None),
                    ("Optimise storage", SWITCH, None, None),
                ),
            ),
        ),
    ),
    (
        "Updates",
        "↻",
        "#4361ee",
        (
            (
                "",
                (
                    ("Installed version", VALUE, None, None),
                    ("Check for updates automatically", SWITCH, None, None),
                    ("Download new updates when available", SWITCH, None, None),
                    ("Install security responses", SWITCH, None, None),
                    ("Update channel", RADIO, ("Stable", "Beta"), None),
                ),
            ),
        ),
    ),
)

# What a value row shows, drawn from per seed.
VALUES = {
    "Device name": ("Ash's Laptop", "Studio Desk", "Kestrel", "Workbench 3", "Juniper"),
    "Software version": ("14.2.1", "14.3", "15.0.2", "15.1"),
    "Serial number": ("C02XK7L4MD6T", "FVFH3Q9QQ6L4", "C1MZ8V2KJ1GJ", "DMPXR0A2KPHQ"),
    "Colour profile": ("Built-in Display", "Studio Wide", "sRGB Standard"),
    "Battery health": ("Normal", "92% capacity", "88% capacity", "Service recommended"),
    "Disk encryption": ("On", "Off", "Encrypting, 41% done"),
    "Signed in as": ("Robin Hale", "Noor Patel", "Ari Lund", "Sam Okafor"),
    "Time zone": ("Lisbon", "Toronto", "Auckland", "Nairobi", "Denver"),
    "Local hostname": ("kestrel.local", "studio-desk.local", "juniper.local"),
    "Available": ("212.4 GB of 494.4 GB", "61.0 GB of 245.1 GB", "1.2 TB of 1.9 TB"),
    "Installed version": ("14.2.1", "15.0.2", "15.1"),
}
STYLES = ("None", "Banners", "Alerts")  # an app's notification style, on the sheet its Options… button opens


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text.lower()).strip("-")


def content(r: random.Random) -> dict:
    """Every pane with every row, each row holding a value drawn from `r`."""
    panes = []
    for name, icon, color, groups in CATALOGUE:
        out_groups = []
        for title, rows in groups:
            out_rows = []
            for label, kind, options, note in rows:
                row: dict = {"id": _slug(label), "label": label, "kind": kind}
                if note:
                    row["note"] = note
                if kind == SWITCH:
                    row["on"] = r.random() < 0.5
                elif kind in (POPUP, RADIO):
                    row["options"] = list(options)
                    row["value"] = r.choice(options)
                elif kind == VALUE:
                    row["value"] = r.choice(VALUES[label])
                elif kind == BUTTON:
                    row["button"], row["sheet"] = options
                    if row["sheet"] == "style":
                        row["value"] = r.choice(STYLES)
                out_rows.append(row)
            out_groups.append({"title": title, "rows": out_rows})
        panes.append({"id": _slug(name), "name": name, "icon": icon, "color": color, "groups": out_groups})
    labels = [row["label"] for pane in panes for group in pane["groups"] for row in group["rows"]]
    assert len(labels) == len(set(labels)), "every row label is unique"
    return {"pane": panes[0]["id"], "query": "", "loading": None, "highlight": None, "sheet": None, "resets": 0, "panes": panes}


def seed_for(r: random.Random, settings: dict) -> dict:
    return desktop(r, "Settings", settings=settings)


def rows_of(settings: dict) -> dict[str, dict]:
    return {row["id"]: row for pane in settings["panes"] for group in pane["groups"] for row in group["rows"]}


def pane_of(settings: dict, row_id: str) -> dict:
    return next(p for p in settings["panes"] if any(row["id"] == row_id for g in p["groups"] for row in g["rows"]))


IN_VIEW = 9  # rows from the top of a pane that a fresh window shows whole, with their group titles


def in_view(pane: dict) -> list[dict]:
    """The rows of a pane that show without scrolling, by the provisional layout."""
    rows = [row for group in pane["groups"] for row in group["rows"]]
    return rows[:IN_VIEW]


def pick(
    r: random.Random, settings: dict, kind: str, *, visible: bool = True, panes: list[dict] | None = None
) -> tuple[dict, dict]:
    """A row of `kind` and its pane: one a fresh window shows whole when `visible`."""
    candidates = [
        (pane, row)
        for pane in panes or settings["panes"]
        for row in (in_view(pane) if visible else [each for group in pane["groups"] for each in group["rows"]])
        if row["kind"] == kind
    ]
    return r.choice(candidates)


def unchanged_but(final: dict, start: dict, *row_ids: str) -> bool:
    """Every row but these holds the value it started with: a wrong click changed nothing else."""
    before, after = rows_of(start), rows_of(final)
    keys = ("on", "value")
    return all(
        all(before[rid].get(k) == after[rid].get(k) for k in keys) for rid in before if rid not in row_ids and rid in after
    )


# ----- templates -------------------------------------------------------------------------------


@template("settings/toggle", 1)
def toggle(seed: int) -> Task:
    """Turn on a named switch that the open pane shows."""
    name = "settings/toggle"
    r = rng(name, seed)
    settings = content(r)
    pane, row = pick(r, settings, SWITCH)
    row["on"] = False
    settings["pane"] = pane["id"]
    start = copy.deepcopy(settings)

    def check(final: dict, answer: str | None) -> bool:
        s = final["settings"]
        return rows_of(s)[row["id"]]["on"] is True and unchanged_but(s, start, row["id"])

    return Task(
        id=f"{name}@{seed}",
        tier=1,
        goal=f"Turn on {row['label']} in Settings.",
        seed=seed_for(r, settings),
        check=check,
        oracle=(("click_item", (row["label"], "checkbox")),),
        tags=("click_item",),
    )


@template("settings/read-value", 1)
def read_value(seed: int) -> Task:
    """Say what a setting holds, read off the open pane."""
    name = "settings/read-value"
    r = rng(name, seed)
    settings = content(r)
    pane, row = pick(r, settings, r.choice((VALUE, POPUP)))
    settings["pane"] = pane["id"]
    start = copy.deepcopy(settings)
    value = row["value"]

    def check(final: dict, answer: str | None) -> bool:
        return says(answer, value) and unchanged_but(final["settings"], start)

    return Task(
        id=f"{name}@{seed}",
        tier=1,
        goal=f"What is {row['label']} set to in Settings?",
        seed=seed_for(r, settings),
        check=check,
        oracle=(),
        tags=("answer",),
        read_only=True,
    )


@template("settings/popup", 2)
def popup(seed: int) -> Task:
    """Pick a value in a popup menu the open pane shows."""
    name = "settings/popup"
    r = rng(name, seed)
    settings = content(r)
    pane, row = pick(r, settings, POPUP)
    settings["pane"] = pane["id"]
    start = copy.deepcopy(settings)
    wanted = r.choice([o for o in row["options"] if o != row["value"]])

    def check(final: dict, answer: str | None) -> bool:
        s = final["settings"]
        return rows_of(s)[row["id"]]["value"] == wanted and unchanged_but(s, start, row["id"])

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Set {row['label']} to {wanted} in Settings.",
        seed=seed_for(r, settings),
        check=check,
        oracle=(("click_item", (row["label"], "popup")), ("click_item", (wanted, "menu item"))),
        tags=("click_item", "menu"),
    )


@template("settings/radio", 2)
def radio(seed: int) -> Task:
    """Pick one option of a radio group the open pane shows."""
    name = "settings/radio"
    r = rng(name, seed)
    settings = content(r)
    pane, row = pick(r, settings, RADIO)
    settings["pane"] = pane["id"]
    start = copy.deepcopy(settings)
    wanted = r.choice([o for o in row["options"] if o != row["value"]])

    def check(final: dict, answer: str | None) -> bool:
        s = final["settings"]
        return rows_of(s)[row["id"]]["value"] == wanted and unchanged_but(s, start, row["id"])

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"In Settings, choose {wanted} for {row['label']}.",
        seed=seed_for(r, settings),
        check=check,
        oracle=(("click_item", (wanted, "radio", row["label"])),),
        tags=("click_item", "repeated"),
    )


@template("settings/search", 2)
def search(seed: int) -> Task:
    """Find a switch on another pane by searching for it, then turn it on."""
    name = "settings/search"
    r = rng(name, seed)
    settings = content(r)
    start_pane = settings["panes"][0]
    _, row = pick(r, settings, SWITCH, visible=False, panes=[p for p in settings["panes"] if p is not start_pane])
    row["on"] = False
    settings["pane"] = start_pane["id"]
    start = copy.deepcopy(settings)

    def check(final: dict, answer: str | None) -> bool:
        s = final["settings"]
        return rows_of(s)[row["id"]]["on"] is True and unchanged_but(s, start, row["id"])

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Search Settings for {row['label']} and turn it on.",
        seed=seed_for(r, settings),
        check=check,
        oracle=(
            ("click_item", ("Search", "field")),
            ("type_text", None),
            ("click_item", (row["label"], "cell")),
            ("click_item", (row["label"], "checkbox")),
        ),
        writes=(row["label"],),
        tags=("type_text", "search"),
    )


@template("settings/scroll", 2)
def scroll(seed: int) -> Task:
    """Turn on a switch at the bottom of a pane too long for the window."""
    name = "settings/scroll"
    r = rng(name, seed)
    settings = content(r)
    pane = next(p for p in settings["panes"] if p["name"] == "Accessibility")
    rows = [row for g in pane["groups"] for row in g["rows"]]
    row = r.choice([row for row in rows[-2:] if row["kind"] == SWITCH])  # wholly below the window's bottom edge
    row["on"] = False
    settings["pane"] = pane["id"]
    start = copy.deepcopy(settings)

    def check(final: dict, answer: str | None) -> bool:
        s = final["settings"]
        return rows_of(s)[row["id"]]["on"] is True and unchanged_but(s, start, row["id"])

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"Turn on {row['label']} in Settings.",
        seed=seed_for(r, settings),
        check=check,
        oracle=(("press_offscreen", row["label"]),),
        tags=("press_offscreen", "scroll"),
    )


@template("settings/nested", 2)
def nested(seed: int) -> Task:
    """Change one app's option, where every app's row carries the same Options… button."""
    name = "settings/nested"
    r = rng(name, seed)
    settings = content(r)
    pane = next(p for p in settings["panes"] if p["name"] == "Notifications")
    rows = [row for g in pane["groups"] for row in g["rows"] if row.get("sheet") == "style"]
    row = r.choice(rows)
    wanted = r.choice([s for s in STYLES if s != row["value"]])
    settings["pane"] = pane["id"]
    start = copy.deepcopy(settings)

    def check(final: dict, answer: str | None) -> bool:
        s = final["settings"]
        return rows_of(s)[row["id"]]["value"] == wanted and unchanged_but(s, start, row["id"])

    return Task(
        id=f"{name}@{seed}",
        tier=2,
        goal=f"In Settings, set the notification style for {row['label']} to {wanted}.",
        seed=seed_for(r, settings),
        check=check,
        oracle=(
            ("click_item", ("Options…", "button", row["label"])),
            ("click_item", (wanted, "radio")),
            ("click_item", ("Done", "button")),
        ),
        tags=("click_item", "repeated", "dialog"),
    )


@template("settings/reset-confirm", 3)
def reset_confirm(seed: int) -> Task:
    """Reset every setting, through a confirmation sheet."""
    name = "settings/reset-confirm"
    r = rng(name, seed)
    settings = content(r)
    start = copy.deepcopy(settings)

    def check(final: dict, answer: str | None) -> bool:
        s = final["settings"]
        return s["resets"] == 1 and unchanged_but(s, start)

    return Task(
        id=f"{name}@{seed}",
        tier=3,
        goal="Reset all settings in Settings.",
        seed=seed_for(r, settings),
        check=check,
        oracle=(
            ("scroll_down", ("Language", "popup")),
            ("click_item", ("Reset…", "button")),
            ("click_item", ("Reset", "button")),
        ),
        tags=("dialog", "scroll"),
    )

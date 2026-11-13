"""Files tasks, and the folders and files the Files app starts with.

The names are made up for the mock. A seed draws which files each folder holds, their sizes and
their dates, so every seed is a different home folder of the same shape: three places with a few
dozen files between them, and a project folder three levels down.
"""

from __future__ import annotations

import copy
import random

from . import Task, desktop, rng, says, template

FOLDERS = (
    "/Home",
    "/Home/Desktop",
    "/Home/Documents",
    "/Home/Downloads",
    "/Trash",
    "/Home/Documents/Projects",
    "/Home/Documents/Receipts",
    "/Home/Documents/Travel",
    "/Home/Documents/Taxes 2025",
    "/Home/Documents/Projects/Website",
    "/Home/Documents/Projects/Garden plan",
    "/Home/Documents/Projects/Website/assets",
)
POOLS = {
    "/Home/Desktop": ("screenshot 0412.png", "todo.txt", "boarding pass.pdf", "notes from call.txt", "sketch.png"),
    "/Home/Documents": (
        "budget 2026.xlsx",
        "cover letter.docx",
        "lease agreement.pdf",
        "reading list.md",
        "meeting minutes.docx",
        "recipes.md",
        "insurance policy.pdf",
        "car service log.csv",
        "quarterly review.key",
        "passport scan.pdf",
    ),
    "/Home/Downloads": (
        "invoice-4471.pdf",
        "setup-tool.zip",
        "podcast episode 12.mp3",
        "train tickets.pdf",
        "photo export.zip",
        "statement-march.pdf",
        "paint colours.png",
        "conference schedule.pdf",
        "font pack.zip",
        "warranty card.pdf",
    ),
    "/Home/Documents/Receipts": (
        "hardware store.pdf",
        "bike repair.pdf",
        "groceries week 9.pdf",
        "dentist.pdf",
        "laptop stand.pdf",
    ),
    "/Home/Documents/Travel": ("itinerary.docx", "hotel booking.pdf", "packing list.md", "museum tickets.pdf"),
    "/Home/Documents/Taxes 2025": ("return draft.pdf", "deductions.xlsx", "donation receipts.pdf"),
    "/Home/Documents/Projects": ("project ideas.md", "timeline.xlsx"),
    "/Home/Documents/Projects/Website": ("index draft.md", "copy edits.docx", "sitemap.csv"),
    "/Home/Documents/Projects/Garden plan": ("bed layout.png", "seed order.csv", "watering schedule.md"),
    "/Home/Documents/Projects/Website/assets": ("logo final.png", "hero banner.jpg", "brand colours.md", "favicon.png"),
    "/Trash": ("old resume.docx", "draft 1.txt", "blurry photo.jpg"),
}
TRASHED_FROM = "/Home/Documents"
SEP = " \u203a "  # between the folders of a path, as the Files app writes one


def size_text(n: int | None) -> str:
    """A size as the Files app shows it (files.js `size`)."""
    if n is None:
        return "--"
    if n < 1000:
        return f"{n} bytes"
    if n < 1_000_000:
        return f"{int(n / 1000 + 0.5)} KB"
    return f"{n / 1e6:.1f} MB"


def stamp(r: random.Random) -> str:
    return f"2025-{r.randint(1, 12):02d}-{r.randint(1, 28):02d} {r.randint(7, 21):02d}:{r.randint(0, 59):02d}"


def content(r: random.Random) -> dict:
    entries = {path: {"kind": "folder", "modified": stamp(r)} for path in FOLDERS}
    for folder, pool in POOLS.items():
        keep = pool if folder == "/Trash" or len(pool) <= 5 else r.sample(pool, k=r.randint(6, len(pool)))
        for name in keep:
            entry = {
                "kind": "file",
                "size": r.randint(2_000, 900_000) if r.random() < 0.8 else r.randint(1_200_000, 48_000_000),
                "modified": stamp(r),
            }
            if folder == "/Trash":
                entry["from"] = TRASHED_FROM
            entries[f"{folder}/{name}"] = entry
    return {
        "cwd": "/Home/Documents",
        "sort": {"key": "name", "desc": False},
        "selected": None,
        "renaming": None,
        "dialog": None,
        "query": "",
        "opened": [],
        "back": [],
        "loading": None,
        "entries": dict(sorted(entries.items())),
    }


def name(path: str) -> str:
    return path.rsplit("/", 1)[1]


def files_in(f: dict, folder: str) -> list[str]:
    return sorted(p for p, e in f["entries"].items() if p.rsplit("/", 1)[0] == folder and e["kind"] == "file")


def seed_for(r: random.Random, f: dict) -> dict:
    return desktop(r, "Files", files=f)


def same_entries(final: dict, start: dict, *, but: dict | None = None) -> bool:
    """The final map of paths is the start's, with `but` applied: {path: entry or None to drop}."""
    expected = copy.deepcopy(start["entries"])
    for path, entry in (but or {}).items():
        if entry is None:
            expected.pop(path, None)
        else:
            expected[path] = entry
    got = {
        p: {k: v for k, v in e.items() if k != "modified" or e["kind"] == "file"} for p, e in final["files"]["entries"].items()
    }
    want = {p: {k: v for k, v in e.items() if k != "modified" or e["kind"] == "file"} for p, e in expected.items()}
    return got == want


def at(path: str) -> tuple[str, str]:
    """A row of the list, as an oracle names it."""
    return (name(path), "cell")


# ----- templates -------------------------------------------------------------------------------


@template("files/open", 1)
def open_file(seed: int) -> Task:
    """Open a named file in the folder on screen."""
    title = "files/open"
    r = rng(title, seed)
    f = content(r)
    path = r.choice(files_in(f, f["cwd"]))
    start = copy.deepcopy(f)

    def check(final: dict, answer: str | None) -> bool:
        return path in final["files"]["opened"] and same_entries(final, start)

    return Task(
        id=f"{title}@{seed}",
        tier=1,
        goal=f"Open {name(path)} from my Documents folder.",
        seed=seed_for(r, f),
        check=check,
        oracle=(("click_item", at(path)), ("click_item", ("Open", "button"))),
        tags=("click_item",),
    )


@template("files/new-folder", 2)
def new_folder(seed: int) -> Task:
    """Make a folder with a given name where the window is."""
    title = "files/new-folder"
    r = rng(title, seed)
    f = content(r)
    wanted = r.choice(("Invoices", "Moving house", "Photos to sort", "Course notes", "Bank letters"))
    start = copy.deepcopy(f)
    path = f"{f['cwd']}/{wanted}"

    def check(final: dict, answer: str | None) -> bool:
        entries = final["files"]["entries"]
        return entries.get(path, {}).get("kind") == "folder" and same_entries(final, start, but={path: entries.get(path)})

    return Task(
        id=f"{title}@{seed}",
        tier=2,
        goal=f"Make a new folder called {wanted} in Documents.",
        seed=seed_for(r, f),
        check=check,
        oracle=(("click_item", ("New Folder", "button")), ("type_text", None), ("press_enter", None)),
        writes=(wanted,),
        tags=("type_text",),
    )


@template("files/rename", 2)
def rename(seed: int) -> Task:
    """Rename a file in the folder on screen."""
    title = "files/rename"
    r = rng(title, seed)
    f = content(r)
    path = r.choice(files_in(f, f["cwd"]))
    stem, dot, ext = name(path).rpartition(".")
    wanted = f"{stem} (old).{ext}" if dot else f"{name(path)} (old)"
    start = copy.deepcopy(f)
    to = f"{f['cwd']}/{wanted}"

    def check(final: dict, answer: str | None) -> bool:
        return same_entries(final, start, but={path: None, to: start["entries"][path]})

    return Task(
        id=f"{title}@{seed}",
        tier=2,
        goal=f"In Files, rename {name(path)} to {wanted}.",
        seed=seed_for(r, f),
        check=check,
        oracle=(("click_item", at(path)), ("click_item", ("Rename", "button")), ("type_text", None), ("press_enter", None)),
        writes=(wanted,),
        tags=("type_text",),
    )


@template("files/trash", 2)
def trash(seed: int) -> Task:
    """Move a file to the Trash, through the confirmation."""
    title = "files/trash"
    r = rng(title, seed)
    f = content(r)
    f["cwd"] = "/Home/Downloads"
    path = r.choice(files_in(f, f["cwd"]))
    start = copy.deepcopy(f)
    to = f"/Trash/{name(path)}"

    def check(final: dict, answer: str | None) -> bool:
        return same_entries(final, start, but={path: None, to: {**start["entries"][path], "from": "/Home/Downloads"}})

    return Task(
        id=f"{title}@{seed}",
        tier=2,
        goal=f"Delete {name(path)} from Downloads.",
        seed=seed_for(r, f),
        check=check,
        oracle=(
            ("click_item", at(path)),
            ("click_item", ("Move to Trash", "button")),
            ("click_item", ("Move to Trash", "button", "Cancel")),
        ),
        tags=("click_item", "dialog"),
    )


@template("files/move", 3)
def move_drag(seed: int) -> Task:
    """Move a file into a folder beside it, by dragging it there."""
    title = "files/move"
    r = rng(title, seed)
    f = content(r)
    path = r.choice(files_in(f, f["cwd"]))
    # Not "Taxes 2025": perception joins that row with its date line, which shares the token "2025",
    # and the row's item reads as the date. A real run meets it; the oracle names rows by their text.
    folder = r.choice(("/Home/Documents/Receipts", "/Home/Documents/Travel"))
    start = copy.deepcopy(f)
    to = f"{folder}/{name(path)}"

    def check(final: dict, answer: str | None) -> bool:
        return same_entries(final, start, but={path: None, to: start["entries"][path]})

    return Task(
        id=f"{title}@{seed}",
        tier=3,
        goal=f"Drag {name(path)} into the {name(folder)} folder.",
        seed=seed_for(r, f),
        check=check,
        oracle=(("drag_item", (at(path), at(folder))),),
        tags=("drag_item", "moves"),
    )


@template("files/move-to", 3)
def move_dialog(seed: int) -> Task:
    """Move a file into another folder, through the "Move to" dialog."""
    title = "files/move-to"
    r = rng(title, seed)
    f = content(r)
    f["cwd"] = "/Home/Downloads"
    path = r.choice(files_in(f, f["cwd"]))
    folder = r.choice(("/Home/Documents/Receipts", "/Home/Documents/Travel", "/Home/Documents/Taxes 2025"))
    start = copy.deepcopy(f)
    to = f"{folder}/{name(path)}"
    shown = SEP.join(folder.replace("/Home", "Home").split("/"))

    def check(final: dict, answer: str | None) -> bool:
        return same_entries(final, start, but={path: None, to: start["entries"][path]})

    return Task(
        id=f"{title}@{seed}",
        tier=3,
        goal=f"Move {name(path)} from Downloads into Documents{SEP}{name(folder)}.",
        seed=seed_for(r, f),
        check=check,
        oracle=(
            ("click_item", at(path)),
            ("click_item", ("Move to…", "button")),
            ("click_item", (shown, "cell")),
            ("click_item", ("Move", "button")),
        ),
        tags=("click_item", "dialog"),
    )


@template("files/find-nested", 3)
def find_nested(seed: int) -> Task:
    """Find a file three folders down and say its size."""
    title = "files/find-nested"
    r = rng(title, seed)
    f = content(r)
    path = r.choice(files_in(f, "/Home/Documents/Projects/Website/assets"))
    size = size_text(f["entries"][path]["size"])
    start = copy.deepcopy(f)

    def check(final: dict, answer: str | None) -> bool:
        return says(answer, size) and same_entries(final, start)

    steps = []
    for folder in ("/Home/Documents/Projects", "/Home/Documents/Projects/Website", "/Home/Documents/Projects/Website/assets"):
        steps += [("click_item", at(folder)), ("click_item", ("Open", "button"))]
    return Task(
        id=f"{title}@{seed}",
        tier=3,
        goal=f"How big is the file {name(path)}? It is somewhere in Documents{SEP}Projects.",
        seed=seed_for(r, f),
        check=check,
        oracle=tuple(steps),
        tags=("answer", "navigation"),
        read_only=True,
    )


@template("files/newest", 3)
def newest(seed: int) -> Task:
    """Say which file in a folder changed last."""
    title = "files/newest"
    r = rng(title, seed)
    f = content(r)
    f["cwd"] = "/Home/Downloads"
    paths = files_in(f, f["cwd"])
    latest = max(paths, key=lambda p: f["entries"][p]["modified"])
    start = copy.deepcopy(f)

    def check(final: dict, answer: str | None) -> bool:
        return says(answer, name(latest)) and same_entries(final, start)

    return Task(
        id=f"{title}@{seed}",
        tier=3,
        goal="Which file in my Downloads folder was changed most recently?",
        seed=seed_for(r, f),
        check=check,
        oracle=(("click_item", ("Date Modified", "button")),),
        reviews=({"achieved": True, "answer": f"{name(latest)} is the most recently changed file in Downloads."},),
        tags=("answer", "compare"),
        read_only=True,
    )


@template("files/restore-missing", 2)
def restore_missing(seed: int) -> Task:
    """Put back a file that is not in the Trash: nothing can be done, and the run should say so."""
    title = "files/restore-missing"
    r = rng(title, seed)
    f = content(r)
    missing = r.choice(("tax summary.pdf", "wedding photos.zip", "thesis final.docx"))
    start = copy.deepcopy(f)

    def check(final: dict, answer: str | None) -> bool:
        return same_entries(final, start)

    return Task(
        id=f"{title}@{seed}",
        tier=2,
        goal=f"Put {missing} back from the Trash.",
        seed=seed_for(r, f),
        check=check,
        oracle=(("click_item", ("Trash", "cell")),),
        reviews=({"answer": f"{missing} is not in the Trash, so there is nothing to put back."},),
        tags=("trap",),
        trap=True,
    )

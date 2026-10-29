"""`clicker --events`: the run as JSON lines on stdout, and the user's replies on stdin.

This is how a front end that is not a terminal drives a run, the menu bar app in `menubar/` first
among them. Each line on stdout is one object with an `event` key:

- `log`: one line of what the terminal would have printed, as `text`
- `run`: the run has started, with its `folder` and whether it may `act`
- `step`: step `step` is reading the screen
- `action`: the run did `text`; `actions` counts them so far
- `would`: a dry run would have done `text`, and stops there
- `focus`: the writer sent the classifier back to work on `focus`, having said `text`
- `question`: the writer asks the user `text`; the run waits for one line on stdin
- `answer`: the writer's answer, `text`, with whether the goal was `achieved`
- `end`: the run is over; the rest is `run.json`, with the run `folder`

The bytes a reply is read from belong to the front end, so nothing else in the run may read stdin.
"""

from __future__ import annotations

import json
import sys
from typing import TextIO


class Events:
    """Writes events to `out` as JSON lines, and reads the user's replies from `replies`."""

    def __init__(self, out: TextIO | None = None, replies: TextIO | None = None):
        self.out = out or sys.stdout
        self.replies = replies or sys.stdin

    def __call__(self, event: str, **fields: object) -> None:
        # One write per line, flushed at once: the front end reads as the run goes, through a pipe.
        self.out.write(json.dumps({"event": event, **fields}, default=str) + "\n")
        self.out.flush()

    def line(self, text: str = "") -> None:
        self("log", text=text)

    def ask(self, question: str) -> str:
        """Put the writer's question to the user. A closed stdin, or an empty line, declines to answer."""
        self("question", text=question)
        return self.replies.readline().rstrip("\r\n")

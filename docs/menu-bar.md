# Menu bar app

`menubar/` is a macOS menu bar front end for `clicker`. Click the icon, type a goal, press Enter,
and the run works in the app you were in. When it needs you, or when it is done, the panel comes
back with its question or its answer.

It is built from [Menu-Bar-Chat](https://github.com/kydno/Menu-Bar-Chat)'s panel: a borderless,
non-activating `NSPanel` under an `NSStatusItem`, which takes the keyboard without bringing its
own app to the front. For a chat bar that means you never leave the app you were typing in. For
computer use it means more:

- The app you were in stays frontmost, and the run works in the frontmost app. From a terminal,
  the terminal is in front and has to be cleared first, since its text is OCR input.
- Nothing of the front end is on screen while the run reads it: the panel closes before the
  first capture, and comes back only when the run is waiting on you or has ended.

## Build and start it

macOS 26 (the panel is Liquid Glass) and the Swift command line tools; Xcode is not needed.

```
uv sync
cp .env.example .env            # fill in the keys, as for clicker
menubar/Scripts/run.sh          # build SystemOne.app, then open it
```

`menubar/Scripts/build.sh` alone builds without opening. It writes this checkout's path into the
app, which runs `.venv/bin/clicker` from here, so `.env` and `runs/` are the same ones `clicker`
uses. To run it from another checkout:
`defaults write com.kydno.SystemOne projectRoot <path>`.
`menubar/Scripts/install-login-item.sh` starts it at every login, and
`uninstall-login-item.sh` undoes that.

The build signs the app with a self-signed identity, **System One Dev**, which it creates in the
login keychain the first time. A stable identity is what keeps macOS's permission grants across
rebuilds. Menu-Bar-Chat found that Screen Recording may still not attach to a certificate without
an Apple Team ID; if captures come back as wallpaper, build with
`CODESIGN_IDENTITY="Apple Development: ..."` (a free Apple ID provides one).

## Permissions

`clicker` runs as the app's child, so macOS asks on behalf of **System One**, not of your
terminal. In System Settings > Privacy & Security, give System One:

- **Accessibility**, or a run that drives the Mac stops before it starts and says so
- **Screen Recording**, or every capture is wallpaper
- **Automation** for your browser and System Events, when macOS asks the first time a run reads
  the browser's URL or the frontmost app

## Using it

| | |
|---|---|
| Click the icon | Opens the panel. Type a goal and press Enter. |
| The eye / pointer button | Dry run or drive. A dry run is `clicker`'s own default: one decision, shown and not carried out. Driving is `--act`. The right-click menu has the same switch, as **Drive the Mac**. |
| While it runs | The panel stays off the screen and the icon shows the step. Clicking it shows the goal, the step, the last action, and **Stop**. |
| Stop | Stops the run as Ctrl-C does in a terminal: it writes `run.json` and ends as `aborted`. Slamming the mouse into the top-left corner still works too. |
| A question | The panel opens with it. Type a reply and press Enter, and the panel leaves before the run reads the screen again. Escape, or the icon, declines, as an empty reply does in the terminal: the run ends with the answer it has. |
| The end | The panel shows the goal, every action, and the writer's answer or how the run ended, with the time and a button for the run folder. |
| Right click | Drive the Mac, Open Last Run Folder, Stop while a run is going, Quit. |

Quitting the app mid-run stops the run.

## How it talks to `clicker`

The app runs `clicker --events [--act] -- <goal>` in this checkout. With `--events`, everything
the terminal would print arrives as JSON lines on stdout, with the run's milestones between them,
and a question waits for one line on stdin. `typesafe_computer_use/events.py` documents every
event; `menubar/Sources/SystemOne/Core/AgentEvent.swift` reads them. Any other front end can
drive a run the same way.

| event | when |
|---|---|
| `log` | every line the terminal would have printed |
| `run` | the run started; its folder and whether it may act |
| `step` | a step began reading the screen |
| `action` | the run did something, in the words of its history |
| `would` | a dry run's decision, and the end of it |
| `focus` | the writer sent the classifier back to work on one thing |
| `question` | the writer asks the user; the reply is the next line on stdin |
| `answer` | the writer's answer, and whether the goal was achieved |
| `end` | the run is over: `run.json`'s summary, the folder, and the outcome in words |

## What came from Menu-Bar-Chat

Kept, nearly as they were: the non-activating panel, its placement under the status item, the
outside-click, Escape and resign-key closes, the open and close motion, the glass surface, the
chrome buttons, the Edit menu and paste handling, the status item's click routing, and the build
script that assembles and signs the bundle without Xcode.

Left out, because a run needs none of it: chat providers and the model catalog, Keychain keys
(the keys stay in `.env`), threads and history, attachments, the settings view and its size,
surface and position controls, and backdrop sampling.

## Not yet verified

The app has been compiled, in CI, and never run. The first thing to check is Menu-Bar-Chat's own
acceptance test, with a run in the middle: put the cursor mid-sentence in TextEdit, open the
panel, start a dry run, and see that TextEdit stays in front, the decision describes TextEdit's
window, and keystrokes still land in TextEdit after the panel closes. Then the same with **Drive
the Mac**, and a goal that makes the writer ask a question.

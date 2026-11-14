"""The mock OS: a fake desktop in a Chromium page that the real step loop drives, for cheap reactive evals.

`page.py` starts Chromium and loads the page (`web/`), `desktop.py` is the `Desktop` adapter over it,
`tasks/` holds the tasks with their checks and scripted solutions, and `passes.py` runs a set of
tasks into rows. `clicker-mock` (`cli.py`) is the command. See docs/mock-os.md.
"""

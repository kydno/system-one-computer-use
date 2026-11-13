"""A static page to step through a run: `replay.html` in the run folder, and `index.html` for a pass.

Built from the files `runner.run_step` already writes: `step-NNN.png` with the pick marked, and
`step-NNN-answers.json` with what was decided, how sure, and how long each phase took. One page,
arrow keys to step. Nothing is opened: the command prints the path, and opening a file on the
maintainer's Mac is theirs to do.
"""

from __future__ import annotations

import html
import json
import re
from pathlib import Path

STEP = re.compile(r"step-(\d{3})-answers\.json$")


def steps(folder: Path) -> list[dict]:
    """Each step of a run folder: its number, image, decision and timing."""
    out = []
    for path in sorted(folder.glob("step-*-answers.json")):
        match = STEP.search(path.name)
        if match is None:
            continue
        n = match.group(1)
        answers = json.loads(path.read_text(encoding="utf-8"))
        image = next((name for name in (f"step-{n}.png", f"step-{n}-raw.png") if (folder / name).is_file()), None)
        review = folder / f"step-{n}-review.json"
        out.append(
            {
                "step": int(n),
                "image": image,
                "app": answers.get("app"),
                "url": answers.get("url"),
                "chosen": answers.get("chosen"),
                "kind": answers.get("kind"),
                "confidence": answers.get("confidence"),
                "items": len(answers.get("items") or []),
                "offscreen": len(answers.get("offscreen_controls") or []),
                "timing": answers.get("timing") or {},
                "review": json.loads(review.read_text(encoding="utf-8")) if review.is_file() else None,
            }
        )
    return out


def _data(value) -> str:
    """JSON safe to put inside a <script> element."""
    return json.dumps(value).replace("<", "\\u003c")


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Replay: {title}</title>
<style>
body {{ font: 14px/1.4 system-ui, sans-serif; margin: 16px; background: #f4f4f6; color: #1d1d1f; }}
header {{ display: flex; gap: 16px; align-items: baseline; flex-wrap: wrap; }}
h1 {{ font-size: 18px; margin: 0; }}
.meta {{ color: #555; }}
main {{ display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 16px; margin-top: 12px; }}
img {{ width: 100%; border: 1px solid #bbb; background: #fff; }}
aside {{ background: #fff; border: 1px solid #ccc; border-radius: 8px; padding: 12px; overflow-wrap: anywhere; }}
.step {{ font-weight: bold; font-size: 16px; }}
table {{ border-collapse: collapse; width: 100%; }}
td {{ padding: 2px 4px; border-bottom: 1px solid #eee; vertical-align: top; }}
ol {{ padding-left: 20px; }}
li.on {{ font-weight: bold; }}
button {{ font: inherit; }}
</style></head>
<body>
<header><h1>{title}</h1><span class="meta">{meta}</span>
<span><button id="prev">&larr;</button> <button id="next">&rarr;</button> (arrow keys)</span></header>
<main><div><img id="shot" alt="the screen this step was decided on"></div>
<aside><div class="step" id="label"></div><table id="facts"></table>
<h3>History</h3><ol id="history"></ol></aside></main>
<script>
const STEPS = {steps};
const HISTORY = {history};
let at = 0;
function show(i) {{
  if (!STEPS.length) {{ document.getElementById("label").textContent = "no steps"; return; }}
  at = Math.max(0, Math.min(STEPS.length - 1, i));
  const s = STEPS[at];
  document.getElementById("shot").src = s.image || "";
  document.getElementById("label").textContent = `step ${{s.step}} of ${{STEPS.length}}`;
  const rows = [["app", s.app], ["url", s.url], ["chose", s.chosen], ["confidence", s.confidence == null ? "" : s.confidence.toFixed(2)],
    ["items", s.items], ["off-screen", s.offscreen],
    ...Object.entries(s.timing).filter(([k, v]) => typeof v === "number").map(([k, v]) => [k, v.toFixed ? v.toFixed(3) : v])];
  if (s.review) for (const r of s.review) rows.push(["writer", `${{r.achieved ? "achieved" : "not achieved"}}: ${{r.answer || r.text || ""}}${{r.focus ? " | focus: " + r.focus : ""}}`]);
  const table = document.getElementById("facts");
  table.replaceChildren(...rows.map(([k, v]) => {{ const tr = document.createElement("tr");
    for (const x of [k, v]) {{ const td = document.createElement("td"); td.textContent = x == null ? "" : String(x); tr.appendChild(td); }} return tr; }}));
  const ol = document.getElementById("history");
  ol.replaceChildren(...HISTORY.map((h, n) => {{ const li = document.createElement("li"); li.textContent = h; if (n === at) li.className = "on"; return li; }}));
}}
document.getElementById("prev").onclick = () => show(at - 1);
document.getElementById("next").onclick = () => show(at + 1);
document.addEventListener("keydown", (e) => {{ if (e.key === "ArrowLeft") show(at - 1); if (e.key === "ArrowRight") show(at + 1); }});
show(0);
</script></body></html>
"""


def write(folder: Path) -> Path:
    """Write `replay.html` into a run folder and return its path."""
    summary = {}
    run = folder / "run.json"
    if run.is_file():
        summary = json.loads(run.read_text(encoding="utf-8"))
    mock = folder / "mockos.json"
    score = json.loads(mock.read_text(encoding="utf-8")).get("score") if mock.is_file() else None
    meta = f"outcome: {summary.get('outcome')}" + (f", score {score}" if score is not None else "")
    page = PAGE.format(
        title=html.escape(str(summary.get("goal") or folder.name)),
        meta=html.escape(meta),
        steps=_data(steps(folder)),
        history=_data(summary.get("history") or []),
    )
    out = folder / "replay.html"
    out.write_text(page, encoding="utf-8")
    return out


def index(folder: Path, rows: list[dict]) -> Path:
    """Write `index.html` for a pass: each task with pass or fail, linking to its replay."""
    lines = []
    for r in rows:
        name = f"{r['task'].replace('/', '-')}-r{r['repeat']}"
        mark = "pass" if r["score"] else "FAIL"
        cost = f"${r['cost']:.4f}" if isinstance(r.get("cost"), int | float) else ""
        lines.append(
            f"<tr><td>{mark}</td><td><a href='{html.escape(name)}/replay.html'>{html.escape(r['task'])}</a> r{r['repeat']}</td>"
            f"<td>{html.escape(str(r.get('outcome')))}</td><td>{r.get('steps')} / {r.get('oracle_steps')}</td>"
            f"<td>{r.get('seconds')}</td><td>{cost}</td></tr>"
        )
    page = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Mock OS pass</title>"
        "<style>body{font:14px/1.4 system-ui,sans-serif;margin:16px}td,th{padding:3px 8px;border-bottom:1px solid #ddd;text-align:left}</style>"
        f"</head><body><h1>Pass {html.escape(folder.name)}</h1><table><tr><th></th><th>task</th><th>outcome</th>"
        f"<th>steps / oracle</th><th>seconds</th><th>cost as if live</th></tr>{''.join(lines)}</table></body></html>"
    )
    out = folder / "index.html"
    folder.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    return out

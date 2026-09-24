"""Wikiracing benchmark: start on one Wikipedia article, reach another using only links on the page.

Tasks follow Jev's e2e suite format (name/url/goal/maxSteps/expectUrl). Every step lets Laya
choose among all unvisited article links on the page, which can be hundreds.

    python wikirace.py              # all tasks
    python wikirace.py Espresso     # tasks whose name contains "Espresso"
"""

import json
import subprocess
import sys
import time
from urllib.parse import unquote

from laya_browser import AB, ask_daemon

TASKS = [  # first two are Jev's (jev-for-chrome scripts/e2e-tasks.json), the rest follow the same shape
    {"name": "Rubber duck -> Eiffel Tower", "url": "https://en.wikipedia.org/wiki/Rubber_duck", "goal": "Eiffel Tower", "maxSteps": 14},
    {"name": "Coffee -> Espresso", "url": "https://en.wikipedia.org/wiki/Coffee", "goal": "Espresso", "maxSteps": 8},
    {"name": "Rubber duck -> Albert Einstein", "url": "https://en.wikipedia.org/wiki/Rubber_duck", "goal": "Albert Einstein", "maxSteps": 14},
    {"name": "Banana -> Moon", "url": "https://en.wikipedia.org/wiki/Banana", "goal": "Moon", "maxSteps": 14},
    {"name": "Pizza -> Philosophy", "url": "https://en.wikipedia.org/wiki/Pizza", "goal": "Philosophy", "maxSteps": 14},
]

# article links in the body only: no namespaces (File:, Help:), no in-page anchors, first text wins
LINKS_JS = """[...new Map([...document.querySelectorAll('#mw-content-text a')]
  .filter(a => a.host === location.host && a.pathname.startsWith('/wiki/') && !a.pathname.includes(':') && !/disambiguation|^\/wiki\/List_of/i.test(a.pathname) && a.innerText.trim())
  .map(a => [decodeURI(a.pathname), a.innerText.trim().slice(0, 80)])).entries()]"""


AB_FLAGS = []  # global agent-browser flags, e.g. ["--session", "laya", "--headed"]
BANNER = None  # label shown on the page each step (for recordings)


def ab(*args):
    out = subprocess.run([AB, *AB_FLAGS, *args], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(out.stderr or out.stdout)
    return out.stdout.strip()


def title(href):
    return unquote(href.rsplit("/", 1)[-1]).replace("_", " ")


def decide_laya(here, goal, links):
    res = ask_daemon({
        "target": goal,
        "elements": [(h, "link", text) for h, text in links],
        "state": f"Wikiracing. Current Wikipedia article: {title(here)}. Target article: {goal}.",
        "ask": f"Which link leads to an article most closely related to {goal}?",
        "fuzzy": False,  # "Moon" must not shortcut to "Moonwalk": the model decides
    })
    if "error" in res:
        raise RuntimeError(res["error"])
    return res["ref"]


def banner(text):
    if BANNER:
        ab("eval", "document.body.insertAdjacentHTML('afterbegin', `<div style='position:fixed;top:0;left:0;right:0;"
           "z-index:99999;background:#111;color:#fff;font:bold 28px system-ui;padding:12px 18px'>" + BANNER + " · " + text + "</div>`)")


def race(task, decide=decide_laya):
    goal, goal_href = task["goal"], "/wiki/" + task["goal"].replace(" ", "_")
    ab("open", task["url"])
    here = unquote("/wiki/" + task["url"].rsplit("/wiki/", 1)[1])
    path, visited, decide_ms, t0 = [title(here)], {here}, [], time.perf_counter()
    banner(f"→ {goal} · step 0 · 0.0 s")
    for _ in range(task["maxSteps"]):
        links = [(h, t) for h, t in json.loads(ab("eval", LINKS_JS)) if h not in visited]
        if not links:
            break  # dead end
        t = time.perf_counter()
        if goal_href in dict(links):  # target linked directly: no decision needed
            nxt = goal_href
        else:
            nxt = decide(here, goal, links)
        decide_ms.append((time.perf_counter() - t) * 1000)
        print(f"  {len(links):4d} links  {decide_ms[-1]:6.1f} ms  -> {title(nxt)}", file=sys.stderr)
        ab("open", "https://en.wikipedia.org" + nxt)
        here = unquote("/wiki/" + ab("get", "url").rsplit("/wiki/", 1)[1].split("#")[0])  # follows redirects
        path.append(title(here))
        banner(f"→ {goal} · step {len(path) - 1} · {time.perf_counter() - t0:.1f} s")
        visited |= {nxt, here}
        if here.lower() == goal_href.lower():
            break
    return {
        "name": task["name"],
        "ok": here.lower() == goal_href.lower(),
        "steps": len(path) - 1,
        "seconds": round(time.perf_counter() - t0, 2),
        "decide_ms_avg": round(sum(decide_ms) / max(len(decide_ms), 1), 1),
        "decide_ms_max": round(max(decide_ms, default=0), 1),
        "path": " > ".join(path),
    }


def main():
    tasks = [t for t in TASKS if not sys.argv[1:] or sys.argv[1] in t["name"]]
    ask_daemon({"target": "warm", "elements": [("a", "link", "x"), ("b", "link", "y")]})  # exclude model load
    results = []
    for task in tasks:
        print(task["name"], file=sys.stderr)
        results.append(race(task))
    print("| task | ok | steps | total s | decide ms avg / max | path |\n|---|---|---:|---:|---:|---|")
    for r in results:
        print(f"| {r['name']} | {'✅' if r['ok'] else '❌'} | {r['steps']} | {r['seconds']} | "
              f"{r['decide_ms_avg']} / {r['decide_ms_max']} | {r['path']} |")
    print(f"\n{sum(r['ok'] for r in results)}/{len(results)} reached the target")


if __name__ == "__main__":
    main()

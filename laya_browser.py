"""laya-browser: agent-browser drop-in that resolves plain-English selectors locally with Laya-MLX.

Every command is forwarded to agent-browser unchanged. When a selector argument is plain
English ("the login link") instead of a @ref/CSS selector, the page snapshot is ranked by a
resident Laya model (~15 ms) and the best @ref is substituted, so there's no LLM round-trip.
"""

import json
import os
import re
import socket
import socketserver
import subprocess
import sys
import tempfile
import time

AB = os.environ.get("AGENT_BROWSER", "agent-browser")
MODEL = os.environ.get("LAYA_MODEL", "aac6fef/laya-mlx")
SOCK = os.path.join(tempfile.gettempdir(), f"laya-browser-{os.getuid()}.sock")
IDLE_EXIT = 1800  # daemon quits after 30 min without requests
CHUNK = 32  # options per Laya choice question (32 measured fastest/most accurate on a 150-link page)
SKIP_ROLES = {"cell", "row"}  # layout wrappers that duplicate their children's text

# command -> positions (in args after the command) that hold a selector
SELECTOR_ARGS = {
    **dict.fromkeys(
        "click dblclick type fill hover focus check uncheck select upload download "
        "scrollintoview highlight wait".split(),
        (0,),
    ),
    "drag": (0, 1),
    "is": (1,),
}
GET_SELECTOR = {"attr": 2, **dict.fromkeys("text html value count box styles".split(), 1)}

HTML_TAGS = set(
    "a abbr article aside audio b body button canvas code dialog div em footer form h1 h2 h3 "
    "h4 h5 h6 header i iframe img input label li main nav ol option p pre section select span "
    "strong summary table tbody td textarea th thead tr ul video".split()
)
CSS_SYNTAX = re.compile(r"^[#.\[/@*]|^\w+=|[=>~+\[\]#:()]")


def is_natural(arg):
    """True when arg reads as English rather than a ref, CSS/XPath/Playwright selector or number."""
    a = arg.strip()
    # ponytail: syntax heuristic; a lone tag name like "button" stays CSS. Force English with a leading "~".
    if a.startswith("~"):
        return True
    return bool(a) and not CSS_SYNTAX.search(a) and not a.isdigit() and a.lower() not in HTML_TAGS


# ---------------------------------------------------------------- daemon (holds the model)


def serve():
    import laya_mlx as laya

    agent = laya.load(MODEL, batch_size=64)
    rank(agent, "warm up", [("e0", "button", "OK"), ("e1", "link", "Home")])  # compile/first-use cost

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            req = json.loads(self.rfile.readline())
            try:
                resp = rank(agent, req["target"], req["elements"], req.get("state"), req.get("ask"), req.get("fuzzy", True))
            except Exception as e:  # keep the daemon alive on bad input
                resp = {"error": str(e)}
            self.wfile.write(json.dumps(resp).encode() + b"\n")

    if os.path.exists(SOCK):
        os.unlink(SOCK)
    with socketserver.UnixStreamServer(SOCK, Handler) as srv:
        srv.timeout = IDLE_EXIT
        timed_out = []
        srv.handle_timeout = lambda: timed_out.append(1)
        while not timed_out:
            srv.handle_request()
    os.unlink(SOCK)


def rank(agent, target, elements, state=None, ask=None, fuzzy=True):
    """Pick the element best matching target. elements: [(ref, role, name)]. state/ask override the prompt."""
    labels = {}
    for ref, role, name in elements:
        if role not in SKIP_ROLES:
            labels.setdefault(f'{role} "{name}"' if name else role, ref)  # duplicates keep first
    if not labels:
        raise ValueError("no candidate elements on the page")
    norm = lambda t: re.sub(r"[^a-z0-9]", "", t.lower())
    want = norm(target)
    names_raw = {label: label.partition('"')[2].lower() for label in labels}
    names = {label: norm(raw) for label, raw in names_raw.items()}
    # lexical fast path, no model; only taken when unambiguous
    words = set(re.findall(r"[a-z0-9]+", target.lower()))
    hits = (
        [label for label, n in names.items() if n == want]
        or [label for label, n in names.items() if fuzzy and len(want) >= 3 and want in n]
        # every word of the name appears in the target: "large pizza" -> radio "Large"
        or [label for label in labels if fuzzy and set(re.findall(r"[a-z0-9]+", names_raw[label])) <= words and names[label]]
    )
    if len(hits) == 1 or (hits and names[hits[0]] == want):
        return {"ref": labels[hits[0]], "label": hits[0], "confidence": 1.0}

    state = state or f"The user wants to: {target}"
    ask = ask or "Which interactive page element accomplishes the user's goal?"
    pool = list(labels)
    # tournament: all chunks go in one batched predict, winners race again until one remains
    while len(pool) > 1:
        chunks = [pool[i : i + CHUNK] for i in range(0, len(pool), CHUNK)]
        chunks = [c if len(c) > 1 else c + [c[0] + " "] for c in chunks]  # choice needs 2 options
        qs = {
            f"q{i}": {"type": "choice", "instructions": ask, "criteria": c}
            for i, c in enumerate(chunks)
        }
        ans = agent.predict(state, qs)["answers"]
        picks = [ans[f"q{i}"] for i in range(len(chunks))]
        pool = [p["choice"].rstrip() for p in picks]
        confidence = picks[0]["confidence"]
    label = pool[0]
    return {"ref": labels[label], "label": label, "confidence": confidence if len(labels) > 1 else 1.0}


# ---------------------------------------------------------------- client (stdlib only, fast)


def ask_daemon(req):
    for attempt in range(200):
        try:
            with socket.socket(socket.AF_UNIX) as s:
                s.connect(SOCK)
                s.sendall(json.dumps(req).encode() + b"\n")
                return json.loads(s.makefile().readline())
        except (FileNotFoundError, ConnectionRefusedError):
            if attempt == 0:
                subprocess.Popen(
                    [sys.executable, os.path.abspath(__file__), "--laya-daemon"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=open(SOCK + ".log", "w"),
                    start_new_session=True,
                )
            time.sleep(0.05)
    sys.exit(f"laya-browser: daemon did not start, see {SOCK}.log")


def resolve(target, global_flags):
    out = subprocess.run([AB, *global_flags, "snapshot", "-i", "--json"], capture_output=True, text=True)
    refs = json.loads(out.stdout or "{}").get("data", {}).get("refs")
    if not refs:
        sys.exit(f"laya-browser: could not snapshot page to resolve {target!r}: {out.stderr.strip()}")
    elements = [(ref, r.get("role", ""), r.get("name", "")) for ref, r in refs.items()]
    res = ask_daemon({"target": target.lstrip("~").strip(), "elements": elements})
    if "error" in res:
        sys.exit(f"laya-browser: {res['error']}")
    print(f"laya: {target!r} -> @{res['ref']} {res['label']} ({res['confidence']:.2f})", file=sys.stderr)
    return "@" + res["ref"]


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv == ["--laya-daemon"]:
        return serve()
    # first known command; anything before it is agent-browser global flags (--session, ...)
    i = next((i for i, a in enumerate(argv) if a in SELECTOR_ARGS or a == "get"), None)
    if i is not None:
        cmd, args = argv[i], argv[i + 1 :]
        if cmd == "get":
            positions = (GET_SELECTOR[args[0]],) if args and args[0] in GET_SELECTOR else ()
        else:
            positions = SELECTOR_ARGS[cmd]
        # ponytail: positions count raw args, so flags go after positionals (agent-browser's usual order)
        for p in positions:
            if p < len(args) and is_natural(args[p]) and not (cmd == "wait" and args[p].startswith("--")):
                args[p] = resolve(args[p], argv[:i])
        argv[i + 1 :] = args
    os.execvp(AB, [AB, *argv])


if __name__ == "__main__":
    main()

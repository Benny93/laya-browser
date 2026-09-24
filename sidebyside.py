"""Side-by-side video: agent-browser driven by a local LLM (Ollama) vs laya-browser, same wikirace.

    python sidebyside.py ["Rubber duck -> Albert Einstein"] [ollama-model]
Writes docs/sidebyside.mp4. Runs sequentially so the two models never share the GPU.
"""

import json
import re
import subprocess
import sys
import urllib.request

import wikirace
from wikirace import TASKS, race, title

LLM_WEBM, LAYA_WEBM = "recordings/llm.webm", "recordings/laya.webm"
LLM = sys.argv[2] if len(sys.argv) > 2 else "dengcao/Qwen3-30B-A3B:Q5_K_M"


def decide_llm(here, goal, links):
    """What an agent does with plain agent-browser: read the link list, answer with one number."""
    listing = "\n".join(f"{i}: {text}" for i, (_, text) in enumerate(links))
    prompt = (f"Wikiracing. You are on the Wikipedia article '{title(here)}' and must reach '{goal}' "
              f"by clicking links. Links on this page:\n{listing}\n\n"
              "Reply with only the number of the link that gets closest to the target.")
    req = urllib.request.Request("http://localhost:11434/api/generate", data=json.dumps(
        {"model": LLM, "prompt": prompt, "stream": False, "think": False, "options": {"num_ctx": 32768}}).encode())
    reply = json.loads(urllib.request.urlopen(req, timeout=600).read())["response"]
    n = int((re.findall(r"\d+", reply) or [0])[0])
    return links[min(n, len(links) - 1)][0]


def run(session, label, decide, task, video):
    wikirace.AB_FLAGS, wikirace.BANNER = ["--session", session, "--headed"], label
    wikirace.ab("set", "viewport", "960", "1080")
    wikirace.ab("record", "start", video, task["url"])
    result = race(task, decide)
    subprocess.run(["sleep", "2"])  # hold the final frame
    wikirace.ab("record", "stop")
    wikirace.ab("close")
    print(label, result, file=sys.stderr)
    return result


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "Rubber duck -> Albert Einstein"
    task = next(t for t in TASKS if t["name"] == name)
    run("llm", f"agent-browser + {LLM.split(':')[0].split('/')[-1]}", decide_llm, task, LLM_WEBM)
    # unload the LLM so it doesn't hold the GPU/unified memory while Laya runs
    urllib.request.urlopen(urllib.request.Request("http://localhost:11434/api/generate",
                                                  data=json.dumps({"model": LLM, "keep_alive": 0}).encode())).read()
    for n in (40, 250, 700):  # MLX specializes per input shape: warm realistic page sizes before recording
        wikirace.decide_laya("/wiki/X", "warm", [(f"/wiki/{i}", f"Some article title {i}") for i in range(n)])
    run("laya", "laya-browser", wikirace.decide_laya, task, LAYA_WEBM)
    # pad the shorter clip with its last frame so both run to the end, then stack horizontally
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", LLM_WEBM, "-i", LAYA_WEBM,
                    "-filter_complex", "[0:v]scale=960:-2,tpad=stop=-1:stop_mode=clone[a];"
                    "[1:v]scale=960:-2,tpad=stop=-1:stop_mode=clone[b];[a][b]hstack=shortest=0[v]",
                    "-map", "[v]", "-t", str(duration(LLM_WEBM, LAYA_WEBM)),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "docs/sidebyside.mp4"], check=True)
    print("wrote docs/sidebyside.mp4")


def duration(*videos):
    return max(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", v],
                                    capture_output=True, text=True).stdout or 0) for v in videos)


if __name__ == "__main__":
    main()

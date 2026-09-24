# laya-browser

Drop-in for [agent-browser](https://github.com/vercel-labs/agent-browser): same commands, same output. Any selector can also be plain English, and a local [Laya-MLX](https://github.com/mizorewww/laya-mlx) decision model resolves it to a `@ref` on-device. The agent skips the snapshot → read → pick-ref round-trip.

```bash
uv tool install --editable .        # needs agent-browser on PATH, Apple Silicon
laya-browser open https://news.ycombinator.com
laya-browser click "log in"          # laya: 'log in' -> @e110 link "login" (1.00)
laya-browser fill "customer name" Ada
laya-browser click @e3               # refs / CSS / text= pass straight through
laya-browser click "~button"         # leading ~ forces English for words that look like tags
```

A resident daemon holds the model. It starts on first use and exits after 30 minutes idle. An English target costs one `snapshot -i` plus an unambiguous text match (no model), or one batched Laya pass (~15 ms for ≤32 elements, more on huge pages). The pick is logged to stderr with its confidence.

Env: `LAYA_MODEL` (default `aac6fef/laya-mlx`), `AGENT_BROWSER` (binary path). Check: `python test_laya_browser.py`.

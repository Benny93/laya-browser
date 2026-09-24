# Wikiracing (python wikirace.py), local Laya only, 14-step limit

| Race | A: baseline | B: filter + hub prompt | C: filter only |
|---|---|---|---|
| Rubber duck → Eiffel Tower | ✅ 5 steps, 1.5 s | ❌ | ❌ |
| Coffee → Espresso | ✅ 1 step | ✅ 1 step | ✅ 1 step |
| Rubber duck → Albert Einstein | ❌ | ❌ | ✅ 5 steps, 6.9 s |
| Banana → Moon | ❌ | ❌ | ❌ |
| Pizza → Philosophy | ❌ | ✅ 7 steps, 6.5 s | ❌ |
| **Total** | **2/5** | **2/5** | **2/5** |

Filter: skip disambiguation and "List of" links. Hub prompt: "Which link is a broad hub article ... most likely to link to X?".
Each decision chooses among 50–730 links in one batched tournament of 32-link chunks.

"""Add hand-chosen Commons categories / search queries as extra-photo
candidates for one cave (BLUISH VOID CAVES tab), 2026-11-07. Same API,
licence and size filters as extras_candidates.py (imported from there).

usage: python3 -I extras_manual.py cands.json "Cave name" "Category:X" "search:query" ...
"""
import json, os, sys
sys.argv, args = [sys.argv[0], "/dev/null", "/dev/null"], sys.argv[1:]
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "extras_candidates.py")).read()
exec(src.split("caves = json.load")[0])   # helpers only (get, info, members)
out, name, specs = args[0], args[1], args[2:]
res = json.load(open(out)); titles = []
for s in specs:
    if s.startswith("search:"):
        d = get({"action": "query", "list": "search", "srsearch": s[7:], "srnamespace": 6, "srlimit": 40})
        titles += [x["title"] for x in d.get("query", {}).get("search", [])]
    elif s.startswith("File:"):
        titles.append(s)
    else:
        titles += members(s)
        for sub in members(s, "subcat", 30)[:8]: titles += members(sub, n=60)
seen = set(); uniq = [t for t in titles if not (t in seen or seen.add(t))]
c = info(uniq[:300])
res[name] = {"cats": specs, "cands": c}
json.dump(res, open(out, "w"), indent=1, ensure_ascii=False)
print(name, len(uniq), len(c))

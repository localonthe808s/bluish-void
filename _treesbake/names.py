"""Build latin_common.json: one common name per scientific name, voted across every baked city by tree count (NYC's own name wins
when NYC has the species), so a city that shipped only latin names still says "honeylocust", not "Gleditsia
triacanthos". Run after a first bake.py pass, then bake again.

  python3 -I _treesbake/names.py <outdir> trees/index.json > _treesbake/latin_common.json
"""
import glob, json, os, re, sys
from collections import Counter, defaultdict


def norm_latin(v):
    """'Platanus x acerifolia', 'Gleditsia triacanthos var. inermis', 'Malus Mill.' -> 'platanus acerifolia',
    'gleditsia triacanthos', 'malus': genus + species epithet, lowercase, hybrid sign and authors dropped"""
    w = [x for x in re.sub(r"[^a-z\s-]", " ", (v or "").lower()).split() if x not in ("x", "spp", "sp", "l", "mill", "var", "ssp", "cv")]
    return " ".join(w[:2])


votes = defaultdict(Counter)
for ix in glob.glob(os.path.join(sys.argv[1], '*', 'index.json')):
    sp = json.load(open(ix))['sp']
    w = Counter()        # a vote is one city (ties broken by trees): one city's misaligned column cannot name a species
    for t in glob.glob(os.path.join(os.path.dirname(ix), 't_*.json')):
        for q in json.load(open(t)):
            w[q[4]] += 1
    for i, (com, lat) in enumerate(sp):
        if com and lat and norm_latin(com) != norm_latin(lat) and not re.search(r'species|:|vacant|site|stump|unassigned|notes|\bvar\b|^jap |^nrwy|^mapl', com.lower()):
            votes[norm_latin(lat)][com] += 1e6 + w[i]
nyc = {}
for com, lat in sorted(json.load(open(sys.argv[2]))['sp'], key=lambda r: "'" in r[1]):   # the species before its cultivars
    if lat and com: nyc.setdefault(norm_latin(lat), com)
out = {}
for lat, c in sorted(votes.items()):
    out[lat] = nyc.get(lat) or c.most_common(1)[0][0]
for lat, com in nyc.items():
    out.setdefault(lat, com)
# a cultivar's trade name won the vote; say the species
out.update({'fraxinus velutina': 'velvet ash', 'prunus serrulata': 'Japanese flowering cherry', 'prunus yedoensis': 'Yoshino cherry',
            'gleditsia triacanthos': 'honeylocust', 'acer freemanii': 'Freeman maple', 'pyrus kawakamii': 'evergreen pear',
            'quercus ellipsoidea': 'northern pin oak', 'celtis occidentalis': 'common hackberry'})
json.dump(out, sys.stdout, indent=0, sort_keys=True, ensure_ascii=False)

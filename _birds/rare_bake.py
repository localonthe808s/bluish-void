#!/usr/bin/env python3
"""
RARE BIRDS ACROSS THE CONTINENT (2026-11-01). The RARE BIRDS tab's roster (BV_RARE in index.html, keep the two lists
in step) at the continent's scale: every spot each species was reported from in the United States and Canada over the
last 30 days, from eBird's regional species feed (the newest report per location). A live call is too big for the page
(Peregrine Falcon: 5,900 spots, 1.7 MB), so this bakes once a day to R2 birds/rare/<code>.json, which the BIRDS map draws
when it is zoomed out with that species picked.

    python3 _birds/rare_bake.py out            # writes out/rare/<code>.json + out/rare/index.json
    python3 _birds/rare_bake.py out --only perfal,snoowl1
"""
import datetime, json, os, sys, time, urllib.parse, urllib.request

KEY = os.environ.get('EBIRD_KEY') or '822u237ioa78'       # the page's own key (non-commercial, exposed on purpose)
REGIONS = ['US', 'CA']
BACK = 30
ROSTER = [
    ('perfal', 'Peregrine Falcon', 'raptor'), ('baleag', 'Bald Eagle', 'raptor'), ('goleag', 'Golden Eagle', 'raptor'),
    ('gyrfal', 'Gyrfalcon', 'raptor'), ('snoowl1', 'Snowy Owl', 'owl'), ('calcon', 'California Condor', 'raptor'),
    ('whocra', 'Whooping Crane', 'water'), ('grhowl', 'Great Horned Owl', 'owl'), ('brdowl', 'Barred Owl', 'owl'),
    ('easowl1', 'Eastern Screech-Owl', 'owl'), ('nswowl', 'Northern Saw-whet Owl', 'owl'), ('sheowl', 'Short-eared Owl', 'owl'),
    ('brnowl', 'Barn Owl', 'owl'), ('burowl', 'Burrowing Owl', 'owl'), ('osprey', 'Osprey', 'raptor'), ('merlin', 'Merlin', 'raptor'),
    ('amekes', 'American Kestrel', 'raptor'), ('norhar2', 'Northern Harrier', 'raptor'), ('swtkit', 'Swallow-tailed Kite', 'raptor'),
    ('sancra', 'Sandhill Crane', 'water'), ('truswa', 'Trumpeter Swan', 'water'), ('amwpel', 'American White Pelican', 'water'),
    ('rosspo1', 'Roseate Spoonbill', 'water'), ('magfri', 'Magnificent Frigatebird', 'water'), ('atlpuf', 'Atlantic Puffin', 'water'),
    ('razorb', 'Razorbill', 'water'), ('harduc', 'Harlequin Duck', 'water'), ('blkski', 'Black Skimmer', 'water'),
    ('comrav', 'Common Raven', 'song'), ('pilwoo', 'Pileated Woodpecker', 'song'), ('rehwoo', 'Red-headed Woodpecker', 'song'),
    ('greroa', 'Greater Roadrunner', 'song'), ('annhum', "Anna's Hummingbird", 'song'), ('paibun', 'Painted Bunting', 'song'),
    ('monpar', 'Monk Parakeet', 'song'), ('wiltur', 'Wild Turkey', 'song'),
]


def roster():
    """The page's BV_RARE is the one list; this copy is the fallback if index.html cannot be read (2026-11-01)."""
    import re
    try:
        html = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'index.html'), encoding='utf-8').read()
        blk = html[html.index('var BV_RARE = ['):]
        blk = blk[:blk.index('\n  ];')]
        rows = re.findall(r"\['(\w+)', '((?:[^'\\]|\\.)+)', '(?:[^'\\]|\\.)*', '(\w+)'\]", blk)
        rows = [(c, n.replace("\\'", "'").replace('\\u2019', '\u2019'), t) for c, n, t in rows]
        if len(rows) >= 30:
            print('roster: %d species read from index.html' % len(rows))
            return rows
        print('roster: index.html gave %d rows, using the fallback' % len(rows))
    except Exception as e:
        print('roster: fallback (%s)' % e)
    return ROSTER


def get(url, tries=3):
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers={'x-ebirdapitoken': KEY, 'User-Agent': 'bluishvoid-rare-bake'})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception as e:                        # a 429 or a hiccup: wait and try again
            print('  retry', k + 1, url[-60:], e)
            time.sleep(8 * (k + 1))
    return None


def bake(out, only=None):
    today = datetime.date.today()
    os.makedirs(os.path.join(out, 'rare'), exist_ok=True)
    index = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'back': BACK, 'regions': REGIONS, 'species': {}}
    for code, name, typ in roster():
        if only and code not in only:
            continue
        pts, seen, failed = [], set(), 0
        for reg in REGIONS:
            rows = get('https://api.ebird.org/v2/data/obs/%s/recent/%s?back=%d&includeProvisional=true' % (reg, code, BACK))
            if rows is None:
                failed += 1
                continue
            for o in rows:
                try:
                    lat, lng = float(o['lat']), float(o['lng'])
                except Exception:
                    continue
                if o.get('locationPrivate'):
                    continue
                day = str(o.get('obsDt') or '')[:10]
                try:
                    age = (today - datetime.date.fromisoformat(day)).days
                except Exception:
                    age = BACK
                k = (round(lat, 3), round(lng, 3))
                if k in seen:
                    continue
                seen.add(k)
                loc = str(o.get('locName') or '')
                loc = loc.split('--')[0].split(' (')[0][:40]
                pts.append([round(lat, 3), round(lng, 3), max(0, min(BACK, age)), int(o.get('howMany') or 1), loc])
        pts.sort(key=lambda p: (p[2], -p[3]))
        doc = {'code': code, 'name': name, 'type': typ, 'built': index['built'], 'back': BACK, 'n': len(pts),
               'today': sum(1 for p in pts if p[2] == 0), 'partial': failed > 0, 'pts': pts}
        with open(os.path.join(out, 'rare', code + '.json'), 'w') as fh:
            json.dump(doc, fh, separators=(',', ':'))
        index['species'][code] = {'name': name, 'type': typ, 'n': len(pts), 'today': doc['today'], 'partial': doc['partial']}
        print('%-8s %-24s %5d spots, %4d today%s' % (code, name, len(pts), doc['today'], '  (PARTIAL)' if failed else ''))
        time.sleep(0.6)
    with open(os.path.join(out, 'rare', 'index.json'), 'w') as fh:
        json.dump(index, fh, separators=(',', ':'))
    print('wrote', os.path.join(out, 'rare'))


if __name__ == '__main__':
    out = sys.argv[1] if len(sys.argv) > 1 else 'out'
    only = None
    if '--only' in sys.argv:
        only = set(sys.argv[sys.argv.index('--only') + 1].split(','))
    bake(out, only)

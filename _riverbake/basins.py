#!/usr/bin/env python3
"""WHERE EACH RIVER ENDS UP (user 2026-11-08, a map of US rivers colored by drainage: "could we color code the river map?" ->
"where it ends up", on WATER > RIVERS only).

GEOGLOWS v2's model table gives every TDX-Hydro reach its TerminalLink, the last reach its water passes through. Each terminal's
downstream end is classified once, then every reach of the EVERY RIVER extract (reaches_full.sqlite, which kept no reach ids) is
matched back to its TDX reach by place and drained area and tagged with column b:

  1 MISSISSIPPI   the terminal with the largest drained area ending on the Louisiana coast
  2 ATLANTIC      Atlantic, Caribbean, Labrador Sea and their bays
  3 GULF          the Gulf of Mexico (other than the Mississippi and Rio Grande)
  4 GREAT LAKES / ST. LAWRENCE   the St. Lawrence's terminal (the Great Lakes drain through it)
  5 HUDSON BAY    Hudson and James Bay, Hudson Strait, Foxe Basin, Ungava Bay
  6 PACIFIC       Pacific, Bering Sea, Gulf of Alaska, Gulf of California (other than the Colorado)
  7 COLORADO      the Colorado's terminal at the head of the Gulf of California
  8 RIO GRANDE    the Rio Grande's terminal at the Gulf near Brownsville
  9 ARCTIC        the Arctic Ocean, Beaufort Sea, Baffin Bay and the Arctic channels
 10 INLAND        terminals more than ~35 km from any named sea: basins that never reach the ocean (Great Basin, closed lakes)

Seas: Natural Earth 10m geography_marine_polys (public domain). Streams: NGA TDX-Hydro via GEOGLOWS v2 (CC BY-SA 4.0).
One region's streams file at a time (~400 MB each), deleted after use.

    python3 basins.py WORK            # WORK holds model.parquet, marine.geojson, reaches_full.sqlite
"""
import json, math, os, sqlite3, sys, time, urllib.request
import numpy as np, pandas as pd, shapely
from shapely import wkb
from shapely.geometry import shape, Point
from shapely.strtree import STRtree

VPUS = list(range(701, 719)) + list(range(801, 805))
BUCKET = 'https://geoglows-v2.s3-us-west-2.amazonaws.com/hydrography/vpu%3D{v}/streams_{v}.gpkg'
UA = {'User-Agent': 'bluishvoid.com river basin bake'}
R = 6378137.0
SEA = {
    9: ['Amundsen Gulf', 'Arctic Ocean', 'Baffin Bay', 'Bathurst Inlet', 'Beaufort Sea', 'Chukchi Sea', 'Cumberland Sound', 'Darnley Bay', 'Davis Strait',
        'Disko Bay', 'Eclipse Sound', 'Franklin Bay', 'Frobisher Bay', 'Goldsmith Channel', 'Gulf of Boothia', 'Hadley Bay', 'Hall Basin', 'Husky Lakes',
        'Jones Sound', 'Kane Basin', 'Kennedy Channel', 'Kotzebue Sound', 'Liddon Gulf', 'Lincoln Sea', "M'Clure Strait", 'Mackenzie Bay', 'Melville Bay',
        'Minto Inlet', 'Murchison Sound', 'Prince ALbert Sound', 'Prince of Wales Strait', 'Richard Collinson Inlet', 'Robeson Channel', 'Sherman Basin',
        'Smith Sound', 'The North Western Passages', 'Uummannaq Fjord', 'Viscount Melville Sound', 'Wynniatt Bay'],
    5: ['Hudson Bay', 'James Bay', 'Hudson Strait', 'Foxe Basin', 'Fury and Hecla Strait', 'Ungava Bay', 'Wager Bay'],
    6: ['Baird Inlet', 'Bering Sea', 'Bristol Bay', 'Columbia River', 'Cook Inlet', 'Cordova Bay', 'Dixon Entrance', 'Golfo de California', 'Golfo de Panamá',
        'Golfo de Tehuantepec', 'Gulf of Alaska', 'Hecate Strait', 'Monterey Bay', 'North Pacific Ocean', 'Norton Sound', 'Prince William Sound',
        'Queen Charlotte Sound', 'Queen Charlotte Strait', 'Salish Sea', 'San Francisco Bay', 'South Pacific Ocean'],
    3: ['Gulf of Mexico', 'Bahía de Campeche', 'Lake Pontchartrain', 'Boca Grande'],
}
NAME2 = {n: k for k, ns in SEA.items() for n in ns}   # anything else at sea: Atlantic (2)

def gpkg_geom(b):
    flags = b[3]; env = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[(flags >> 1) & 7]
    return wkb.loads(bytes(b[8 + env:]))

def unmerc(x, y):
    return math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)

def fetch(url, path):
    if os.path.exists(path): return
    for attempt in range(6):
        try:
            tmp = path + '.part'
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=180) as r, open(tmp, 'wb') as f:
                while True:
                    b = r.read(1 << 20)
                    if not b: break
                    f.write(b)
            os.replace(tmp, path); return
        except Exception as e:
            print('fetch retry', attempt, e, flush=True); time.sleep(20 * (attempt + 1))
    raise RuntimeError('could not fetch ' + url)

def main(work):
    seas = json.load(open(os.path.join(work, 'marine.geojson')))['features']
    SG = [shape(f['geometry']) for f in seas]; SN = [f['properties'].get('name') or '' for f in seas]; stree = STRtree(SG)
    m = pd.read_parquet(os.path.join(work, 'model.parquet'), columns=['LINKNO', 'TerminalLink', 'DSContArea', 'VPUCode'])
    m = m[m.VPUCode.isin(VPUS)]
    term = dict(zip(m.LINKNO.values, m.TerminalLink.values)); area = dict(zip(m.LINKNO.values, m.DSContArea.values))
    c = sqlite3.connect(os.path.join(work, 'reaches_full.sqlite'))
    cols = [r[1] for r in c.execute('pragma table_info(r)')]
    if 'b' not in cols: c.execute('alter table r add column b integer'); c.commit()
    c.execute('create table if not exists bdone(vpu integer primary key)')
    done = {v for (v,) in c.execute('select vpu from bdone')}
    unk = {}; pending = None
    for i, v in enumerate(VPUS):
        if v in done: continue
        t0 = time.time(); sp = os.path.join(work, 'streams_%d.gpkg' % v)
        if pending is not None: pending.join(); pending = None     # the prefetch of this region, if one ran
        fetch(BUCKET.format(v=v), sp)
        nxt = [u for u in VPUS[i + 1:] if u not in done][:1]
        if nxt:   # the next region downloads while this one is matched
            import threading; pending = threading.Thread(target=fetch, args=(BUCKET.format(v=nxt[0]), os.path.join(work, 'streams_%d.gpkg' % nxt[0])), daemon=True); pending.start()
        sc = sqlite3.connect(sp); st = sc.execute('select table_name from gpkg_contents').fetchone()[0]
        L, G, A = [], [], []
        for lk, b, a in sc.execute('select LINKNO, geom, DSContArea from "%s" where DSContArea >= 8e6' % st):
            g = gpkg_geom(b)
            if g is None or g.is_empty: continue
            L.append(int(lk)); G.append(g); A.append(int(round(a / 1e6)))
        sc.close()
        geom = dict(zip(L, G))
        # each terminal's group, from where its last reach ends
        tg = {}
        for t in set(term.get(lk, lk) for lk in L):
            g = geom.get(t)
            if g is None: tg[t] = 0; continue
            ln = g.geoms[-1] if g.geom_type.startswith('Multi') else g
            lo, la = unmerc(*ln.coords[-1]); p = Point(lo, la); ta = area.get(t, 0) / 1e6
            k = stree.nearest(p); d = SG[k].distance(p)
            if ta > 2e6 and la < 31.5 and -92 < lo < -88: grp = 1
            elif ta > 2e5 and abs(la - 25.95) < 0.7 and abs(lo + 97.15) < 0.7: grp = 8
            elif ta > 2e5 and abs(la - 31.8) < 1.2 and abs(lo + 114.8) < 1.2: grp = 7
            elif ta > 5e5 and 45 < la < 51.5 and -73 < lo < -58: grp = 4
            elif d > 0.35: grp = 10
            else:
                grp = NAME2.get(SN[k])
                if grp is None and not SN[k]:   # an unnamed sea polygon: judged by where it is (2026-11-08: Alaska's unnamed fjords had gone to the Atlantic)
                    grp = (9 if la > 66 else 6) if lo < -100 else 5 if (-96 < lo < -76 and 51 < la < 64) else 9 if la > 66 else 2
                if grp is None: grp = 2
                if SN[k] not in NAME2: unk[SN[k]] = unk.get(SN[k], 0) + 1
            tg[t] = grp
        grp_of = {lk: tg.get(term.get(lk, lk), 0) for lk in L}
        tree = STRtree(G)
        rows = c.execute('select id, a, g from r where vpu = ?', (v,)).fetchall(); upd = []; miss = 0
        for rid, a, gb in rows:
            g = wkb.loads(gb); p = g.interpolate(0.5, normalized=True)
            best = None
            for j in tree.query(p.buffer(60)):
                if abs(A[j] - a) <= max(1, a * 0.01):
                    d = G[j].distance(p)
                    if best is None or d < best[0]: best = (d, j)
            if best is None:
                j = tree.nearest(p); best = (G[j].distance(p), j); miss += 1
            upd.append((grp_of[L[best[1]]], rid))
        c.executemany('update r set b = ? where id = ?', upd); c.execute('insert into bdone values (?)', (v,)); c.commit()
        os.remove(sp)
        cnt = {}
        for b2, _ in upd: cnt[b2] = cnt.get(b2, 0) + 1
        print('vpu %d: %d reaches, %d matched by nearest only, groups %s, %.0f s' % (v, len(rows), miss, sorted(cnt.items()), time.time() - t0), flush=True)
    print('other sea names (counted as Atlantic):', unk, flush=True)

if __name__ == '__main__':
    main(sys.argv[1])

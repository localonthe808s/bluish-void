#!/usr/bin/env python3
"""Bake the clear-night hero's satellites: two-line elements for what can be SEEN from the ground at night.

Run by .github/workflows/sats-night.yml (daily) on three CelesTrak downloads (FORMAT=tle): stations, visual, starlink.
Writes two JSON files for R2 (cdn.bluishvoid.com/sats/...):
  core.json     -- the stations, the ~150 brightest objects, and the Starlinks that are bright for their class: fresh
                   launches still low and raising their orbits (mean motion > 15.6 rev/day -- the "trains") and the
                   direct-to-cell craft [DTC]. Small; every device loads it.
  starlink.json -- every other Starlink (~10k). Desktop only, loaded after core.
Each: {"baked": ms, "rows": [[name, line1, line2, group], ...]}. A catalogue number appears once (first group wins:
stations, visual, starlink). Data: U.S. Space Force catalogue via CelesTrak -- credit CelesTrak.
Usage: python3 sats_bake.py <dir with stations.tle visual.tle starlink.tle> <out dir>"""
import json, sys, time, os

src, out = sys.argv[1], sys.argv[2]
seen, core, rest = set(), [], []
for g in ['stations', 'visual', 'starlink']:
    L = [l.rstrip() for l in open(os.path.join(src, g + '.tle')) if l.strip()]
    for i in range(0, len(L) - 2, 3):
        n, a, b = L[i].strip(), L[i + 1], L[i + 2]
        if not (a.startswith('1 ') and b.startswith('2 ')): continue
        cat = a[2:7].strip()
        if cat in seen: continue
        seen.add(cat)
        row = [n, a, b, g]
        if g != 'starlink': core.append(row); continue
        nm = float(b[52:63])
        (core if (nm > 15.6 or '[DTC]' in n) else rest).append(row)
baked = int(time.time() * 1000)
os.makedirs(out, exist_ok=True)
for name, rows in [('core.json', core), ('starlink.json', rest)]:
    with open(os.path.join(out, name), 'w') as f: json.dump({'baked': baked, 'rows': rows}, f, separators=(',', ':'))
    print(name, len(rows), 'objects', os.path.getsize(os.path.join(out, name)), 'bytes')

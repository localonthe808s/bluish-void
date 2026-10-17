#!/usr/bin/env python3
"""LIVE TRANSIT FOR ANY PLACE (step 2 of one map engine, user 2026-10-16). The Mobility Database catalog
(files.mobilitydatabase.org/feeds_v2.csv) lists every public GTFS-realtime feed; kept here are the US, Canadian and Puerto
Rican VEHICLE POSITION feeds that need no key and answered a probe, each with its agency's service area (the bounding box
of the static GTFS it references) and whether it sends a CORS header (read straight from the page; the rest go through
proxy.bluishvoid.com, whose allowlist must carry their hosts -- see hosts.txt).

    python3 feeds.py catalog.csv probe.json OUT_DIR       -> OUT_DIR/feeds.json, OUT_DIR/hosts.txt
"""
import csv, json, sys, urllib.parse
def main(cat, probe, out):
    R = list(csv.DictReader(open(cat))); by = {r['id']: r for r in R}
    P = {p[0]: p for p in json.load(open(probe))}
    feeds, hosts = [], set()
    for r in R:
        if r['data_type'] != 'gtfs_rt' or r['id'] not in P: continue
        pid, st, cors, n = P[r['id']]
        if st != 200 or n <= 50: continue
        bb = None
        for ref in [r['static_reference']] + r['static_reference'].split('|'):
            s = by.get(ref.strip())
            if s and s['location.bounding_box.minimum_latitude']:
                bb = [round(float(s['location.bounding_box.minimum_longitude']), 3), round(float(s['location.bounding_box.minimum_latitude']), 3),
                      round(float(s['location.bounding_box.maximum_longitude']), 3), round(float(s['location.bounding_box.maximum_latitude']), 3)]
                break
        if not bb: continue
        if (bb[2] - bb[0]) > 12 or (bb[3] - bb[1]) > 10: continue          # a statewide box says nothing about where the buses are
        u = r['urls.direct_download']
        feeds.append({'id': r['id'], 'n': r['provider'].split(',')[0].strip()[:60], 'u': u, 'c': 1 if cors else 0, 'b': bb})
        if not cors: hosts.add(urllib.parse.urlparse(u).hostname)
    json.dump({'src': 'Mobility Database catalog (MobilityData), GTFS-realtime vehicle positions, keyless', 'f': feeds}, open(out + '/feeds.json', 'w'), separators=(',', ':'))
    open(out + '/hosts.txt', 'w').write('\n'.join(sorted(hosts)) + '\n')
    print(len(feeds), 'feeds,', sum(f['c'] for f in feeds), 'with CORS,', len(hosts), 'proxy hosts')
if __name__ == '__main__': main(*sys.argv[1:4])

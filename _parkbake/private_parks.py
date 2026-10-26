"""PRIVATE PARKS, LEFT UNCOLORED (2026-10-25, user: "these are residential and not public land in sunnyside gardens"): OSM ways and
relations tagged leisure park/garden/playground/... with access private/no/residents/customers, across the lower 48, fetched from
Overpass in 5-degree blocks. Written as the basemap's own feature ids (way id + 2^45, relation id + 3*2^45 per planetiler's
encoding; ways checked against our tiles) -> private_parks.json, a sorted id list the park fill skips."""
import json, subprocess, sys, time
EPS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
Q = '[out:json][timeout:180];(way["leisure"~"^(park|garden|playground|recreation_ground|village_green|common|dog_park)$"]["access"~"^(private|no|customers|residents)$"]({s},{w},{n},{e});relation["leisure"~"^(park|garden|playground|recreation_ground|village_green|common|dog_park)$"]["access"~"^(private|no|customers|residents)$"]({s},{w},{n},{e}););out ids;'
ids = set(); W2 = 2 ** 45
# --blocks LAT,LON ...: only those 5-degree blocks, each fetched as four 2.5-degree quarters (the two that timed out on 10-25 --
# 24,-115 and 44,-110 -- went through this way), merged into the list already in sys.argv[1]
BLK = [tuple(int(v) for v in b.split(',')) for b in sys.argv[sys.argv.index('--blocks') + 1:]] if '--blocks' in sys.argv else None
if BLK:
    try: ids = set(json.load(open(sys.argv[1])))
    except Exception: pass
    print('merging into', len(ids))
CELLS = [(la + dy, lo + dx, 2.5) for la, lo in BLK for dy in (0, 2.5) for dx in (0, 2.5)] if BLK else [(la, lo, 5) for la in range(24, 50, 5) for lo in range(-125, -66, 5)]
for lat, lon, sz in CELLS:
    if True:
        q = Q.format(s=lat, w=lon, n=min(50, lat + sz), e=min(-66, lon + sz))
        for k in range(6):
            try:
                d = subprocess.run(['curl', '-s', '-m', '240', '-A', 'bluishvoid.com map', '--data-urlencode', 'data=' + q, EPS[k % 2]], capture_output=True, check=True).stdout   # curl: this Python's SSL fails Overpass's handshake
                el = json.loads(d)['elements']; break
            except Exception as ex:
                print('  retry', lat, lon, ex, flush=True); time.sleep(20 + 20 * k); el = None
        if el is None: print('FAILED block', lat, lon, flush=True); continue
        for x in el: ids.add(x['id'] + (W2 if x['type'] == 'way' else 3 * W2))
        print(lat, lon, len(el), 'total', len(ids), flush=True)
        time.sleep(25)   # gentle: Overpass throttles a fast run
json.dump(sorted(ids), open(sys.argv[1], 'w'), separators=(',', ':'))
print('done', len(ids))

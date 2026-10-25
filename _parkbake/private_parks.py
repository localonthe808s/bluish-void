"""PRIVATE PARKS, LEFT UNCOLORED (2026-10-25, user: "these are residential and not public land in sunnyside gardens"): OSM ways and
relations tagged leisure park/garden/playground/... with access private/no/residents/customers, across the lower 48, fetched from
Overpass in 5-degree blocks. Written as the basemap's own feature ids (way id + 2^45, relation id + 3*2^45 per planetiler's
encoding; ways checked against our tiles) -> private_parks.json, a sorted id list the park fill skips."""
import json, subprocess, sys, time
EPS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter']
Q = '[out:json][timeout:180];(way["leisure"~"^(park|garden|playground|recreation_ground|village_green|common|dog_park)$"]["access"~"^(private|no|customers|residents)$"]({s},{w},{n},{e});relation["leisure"~"^(park|garden|playground|recreation_ground|village_green|common|dog_park)$"]["access"~"^(private|no|customers|residents)$"]({s},{w},{n},{e}););out ids;'
ids = set(); W2 = 2 ** 45
for lat in range(24, 50, 5):
    for lon in range(-125, -66, 5):
        q = Q.format(s=lat, w=lon, n=min(50, lat + 5), e=min(-66, lon + 5))
        for k in range(6):
            try:
                d = subprocess.run(['curl', '-s', '-m', '240', '-A', 'bluishvoid.com map', '--data-urlencode', 'data=' + q, EPS[k % 2]], capture_output=True, check=True).stdout   # curl: this Python's SSL fails Overpass's handshake
                el = json.loads(d)['elements']; break
            except Exception as ex:
                print('  retry', lat, lon, ex, flush=True); time.sleep(20 + 20 * k); el = None
        if el is None: print('FAILED block', lat, lon, flush=True); continue
        for x in el: ids.add(x['id'] + (W2 if x['type'] == 'way' else 3 * W2))
        print(lat, lon, len(el), 'total', len(ids), flush=True)
        time.sleep(3)
json.dump(sorted(ids), open(sys.argv[1], 'w'), separators=(',', ':'))
print('done', len(ids))

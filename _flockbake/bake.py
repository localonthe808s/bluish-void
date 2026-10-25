#!/usr/bin/env python3
"""YOU'RE FLOCKED (2026-10-25, user: "are you able to show tracked flock cameras on traffic?" -> "yes build it"): every
license-plate reader mapped in OpenStreetMap -- the crowdsourced map DeFlock (deflock.org) draws -- as one compact file the
TRAFFIC tab's switch loads. The query is DeFlock's own: man_made=surveillance + surveillance:type=ALPR. OSM data, ODbL
(credited as OPENSTREETMAP on the tab).

    flock/alpr_v1.json   {"at": unix, "n": count, "mf": [makers], "op": [operators],
                          "p": [lon*1e5, lat*1e5, dir (deg, -1 unknown), maker idx, operator idx (-1 none), ...] flat}

    python3 _flockbake/bake.py            # fetch + upload (aws cli + R2 env in CI; the local rclone remote r2: otherwise)
    python3 _flockbake/bake.py --dry      # fetch, write /tmp/flock_alpr_v1.json, no upload
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.parse, urllib.request

BUCKET = 'bluishvoid-bg'; KEY = 'flock/alpr_v1.json'
Q = '[out:json][timeout:250];node["man_made"="surveillance"]["surveillance:type"="ALPR"];out body;'
MIRRORS = ['https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter', 'https://overpass.private.coffee/api/interpreter']
CARD = {'N': 0, 'NNE': 22.5, 'NE': 45, 'ENE': 67.5, 'E': 90, 'ESE': 112.5, 'SE': 135, 'SSE': 157.5, 'S': 180, 'SSW': 202.5,
        'SW': 225, 'WSW': 247.5, 'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5}


def fetch():
    body = urllib.parse.urlencode({'data': Q}).encode()
    for attempt in range(3):
        for m in MIRRORS:
            try:
                r = urllib.request.urlopen(urllib.request.Request(m, data=body, headers={'User-Agent': 'bluishvoid.com flock bake'}), timeout=300)
                j = json.loads(r.read())
                if len(j.get('elements', [])) > 50000: return j['elements']        # a partial answer is worse than yesterday's file
                print('short answer from', m, len(j.get('elements', [])))
            except Exception as e:
                print('mirror failed', m, e)
        time.sleep(60)
    raise SystemExit('no complete answer from any Overpass mirror')


def direction(t):
    """the first facing of camera:direction / direction: degrees, a cardinal, or a range (its middle)"""
    v = (t.get('camera:direction') or t.get('direction') or '').strip().split(';')[0].strip().upper()
    if not v: return -1
    if v in CARD: return int(CARD[v])
    m = re.match(r'^(-?\d+(?:\.\d+)?)\s*-\s*(-?\d+(?:\.\d+)?)$', v)
    if m:
        a, b = float(m.group(1)) % 360, float(m.group(2)) % 360
        if b < a: b += 360
        return int(round((a + b) / 2)) % 360
    try: return int(round(float(v))) % 360
    except ValueError: return -1


def main():
    els = fetch()
    mf, op, mfi, opi, p = [], [], {}, {}, []
    for e in els:
        t = e.get('tags', {})
        maker = (t.get('manufacturer') or t.get('surveillance:manufacturer') or t.get('brand') or t.get('surveillance:brand') or '').strip()
        oper = (t.get('operator') or t.get('surveillance:operator') or '').strip()
        if maker not in mfi: mfi[maker] = len(mf); mf.append(maker)
        oi = -1
        if oper:
            if oper not in opi: opi[oper] = len(op); op.append(oper)
            oi = opi[oper]
        p += [round(e['lon'] * 1e5), round(e['lat'] * 1e5), direction(t), mfi[maker], oi]
    out = {'at': int(time.time()), 'n': len(els), 'mf': mf, 'op': op, 'p': p}
    path = os.path.join(tempfile.gettempdir(), 'flock_alpr_v1.json')
    json.dump(out, open(path, 'w'), separators=(',', ':'), ensure_ascii=False)
    print('cameras', len(els), 'makers', len(mf), 'operators', len(op), 'bytes', os.path.getsize(path))
    if '--dry' in sys.argv: return
    cache = 'public, max-age=3600'
    if os.environ.get('R2_ACCOUNT_ID'):
        subprocess.run(['aws', 's3', 'cp', path, 's3://%s/%s' % (BUCKET, KEY), '--content-type', 'application/json', '--cache-control', cache,
                        '--endpoint-url', 'https://%s.r2.cloudflarestorage.com' % os.environ['R2_ACCOUNT_ID'], '--only-show-errors'], check=True)
    else:
        subprocess.run(['rclone', 'copyto', path, 'r2:%s/%s' % (BUCKET, KEY), '--s3-no-check-bucket',
                        '--header-upload', 'Content-Type: application/json', '--header-upload', 'Cache-Control: ' + cache], check=True)
    print('uploaded', KEY)


if __name__ == '__main__':
    main()

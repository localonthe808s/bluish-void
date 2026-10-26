#!/usr/bin/env python3
"""YOU'RE FLOCKED (2026-10-25, user: "are you able to show tracked flock cameras on traffic?" -> "yes build it"): every
license-plate reader mapped in OpenStreetMap -- the crowdsourced map DeFlock (deflock.org) draws -- as one compact file the
TRAFFIC tab's switch loads. The query is DeFlock's own: man_made=surveillance + surveillance:type=ALPR. OSM data, ODbL
(credited as OPENSTREETMAP on the tab).

    flock/alpr_v2.json   {"at": unix, "n": count, "s": 6, "mf": [makers as tagged], "co": [companies], "op": [operators],
                          "p": [lon*1e5, lat*1e5, dir (deg, -1 unknown), maker idx, operator idx (-1 none), company idx, ...] flat}

THE COMPANY (2026-10-25, user: "what are the 'others' can we break that up to be specific? ... i want to be accurate"): the
maker tag is free text -- "Flock Safety", "Flock Group Inc.", "Flock Safety Inc", "Flock" are one company -- so each camera
also gets its company, folded by COMPANIES below (Vigilant and Avigilon are Motorola Solutions' brands). '' = not recorded.

    python3 _flockbake/bake.py            # fetch + upload (aws cli + R2 env in CI; the local rclone remote r2: otherwise)
    python3 _flockbake/bake.py --dry      # fetch, write /tmp/flock_alpr_v1.json, no upload
"""
import json, os, re, subprocess, sys, tempfile, time, urllib.parse, urllib.request

BUCKET = 'bluishvoid-bg'; KEY = 'flock/alpr_v2.json'
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


COMPANIES = [   # (pattern on the lowercased maker tag, company) -- first match wins
    (r'flock', 'Flock Safety'), (r'motorola|mortorola|vigilant|avigilon', 'Motorola Solutions'), (r'genetec', 'Genetec'),
    (r'\baxis\b', 'Axis Communications'), (r'leonardo|elsag', 'Leonardo'), (r'rekor', 'Rekor'), (r'\baxon\b', 'Axon'),
    (r'platesmart|cyclops', 'PlateSmart'), (r'neology', 'Neology'), (r'ubicquia', 'Ubicquia'), (r'\bekin\b', 'Ekin'),
    (r'hikvision', 'Hikvision'), (r'dahua', 'Dahua'), (r'verkada', 'Verkada'), (r'\brtx\b|raytheon', 'RTX'), (r'tattile', 'Tattile'),
    (r'jenoptik', 'Jenoptik'), (r'kapsch', 'Kapsch'), (r'insight', 'Insight LPR'), (r'packetalk|pacetalk', 'Packetalk'),
    (r'hanwha', 'Hanwha Vision'), (r'bosch', 'Bosch'), (r'uniview', 'Uniview'), (r'liveview', 'LiveView Technologies'),
    (r'secure technical', 'Secure Technical Solutions'), (r'ndi recognition', 'NDI Recognition Systems'), (r'redspeed', 'Redspeed'),
    (r'^mav\b', 'MAV Systems'), (r'transcore', 'TransCore'), (r'verra', 'Verra Mobility'), (r'skycop', 'SkyCop'), (r'costar', 'CoStar'),
    (r'^unknown$|^other$|^\?$', '')]


def company(maker):
    m = maker.strip().lower()
    for pat, co in COMPANIES:
        if re.search(pat, m): return co
    return maker.strip()


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
    mf, op, co, mfi, opi, coi, p = [], [], [], {}, {}, {}, []
    for e in els:
        t = e.get('tags', {})
        maker = (t.get('manufacturer') or t.get('surveillance:manufacturer') or t.get('brand') or t.get('surveillance:brand') or '').strip()
        oper = (t.get('operator') or t.get('surveillance:operator') or '').strip()
        if maker not in mfi: mfi[maker] = len(mf); mf.append(maker)
        oi = -1
        if oper:
            if oper not in opi: opi[oper] = len(op); op.append(oper)
            oi = opi[oper]
        c = company(maker)
        if c not in coi: coi[c] = len(co); co.append(c)
        p += [round(e['lon'] * 1e5), round(e['lat'] * 1e5), direction(t), mfi[maker], oi, coi[c]]
    out = {'at': int(time.time()), 'n': len(els), 's': 6, 'mf': mf, 'co': co, 'op': op, 'p': p}
    path = os.path.join(tempfile.gettempdir(), 'flock_alpr_v2.json')
    json.dump(out, open(path, 'w'), separators=(',', ':'), ensure_ascii=False)
    print('cameras', len(els), 'makers', len(mf), 'companies', len(co), 'operators', len(op), 'bytes', os.path.getsize(path))
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

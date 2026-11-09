#!/usr/bin/env python3
"""Colorado — DWR / CDSS geophysical-log wells with AQUIFER PICKS (Denver Basin: Dawson, Denver, Arapahoe, Laramie-Fox Hills
...): depth to top/base of each bedrock aquifer read off the borehole's geophysical log by DWR staff. Not a driller's lithology
(Colorado's well construction reports are scanned images in Laserfiche; the permit API carries no lithology).
API (keyless): https://dwr.state.co.us/Rest/GET/api/v2/groundwater/geophysicallogs/wells/?division=N  then
.../geoplogpicks/?wellId=ID per well (~5.4k sequential requests, cached per well). Depths in feet below ground.
A unit with both an UPPER and a LOWER pick (e.g. DAWSON + UPPER DAWSON + LOWER DAWSON) keeps only the sub-units; a pick with
no top depth takes top = base - thickness, else is dropped. Coordinates: mostly spotted from PLSS section lines/quarters."""
import json, os, re, sys, time, urllib.error, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'co')
API = 'https://dwr.state.co.us/Rest/GET/api/v2/groundwater/geophysicallogs/'
BOX = (36.8, 41.2, -109.2, -101.9)


BLOCKED = []  # CDSS answers 403 once an anonymous client has made ~1000 requests in a day: stop, keep the cache, rerun tomorrow


def get(u, path):
    if os.path.exists(path) and os.path.getsize(path) > 0: return open(path, 'rb').read()
    if BLOCKED: return None
    for a in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()
            open(path, 'wb').write(b); time.sleep(0.5); return b
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                BLOCKED.append(e.code); print('CDSS refused (%d); using cached picks only, rerun later to fill in' % e.code, file=sys.stderr); return None
            time.sleep(4 * (a + 1))
        except Exception:
            time.sleep(4 * (a + 1))
    return None


def js(b):
    if not b: return []
    try:
        return json.loads(b.decode('utf-8', 'replace')).get('ResultList') or []
    except ValueError:
        return []  # "returns zero records" plain-text reply


def wells():
    os.makedirs(os.path.join(CACHE, 'picks'), exist_ok=True)
    for d in (1, 2, 3, 4, 5, 6, 7):
        for r in js(get(API + 'wells/?format=json&pageSize=50000&division=%d' % d, os.path.join(CACHE, 'wells_div%d.json' % d))):
            if not r.get('aquiferPicks'): continue
            lat, lon = r.get('latitude'), r.get('longitude')
            if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
            wid = r['wellId']
            pk = js(get(API + 'geoplogpicks/?format=json&wellId=%d' % wid, os.path.join(CACHE, 'picks', '%d.json' % wid)))
            names = set((p.get('aquifer') or '').strip().upper() for p in pk)
            log = []
            for p in pk:
                a = (p.get('aquifer') or '').strip().upper()
                if not a: continue
                if ('UPPER ' + a) in names and ('LOWER ' + a) in names: continue
                top, bot, th = p.get('gLogTopDepth'), p.get('gLogBaseDepth'), p.get('gLogThickness')
                if top is None and bot is not None and th: top = bot - th
                if top is None or top < 0: continue
                log.append([round(float(top), 1), None if bot is None else round(float(bot), 1), (a.title() + ' (aquifer pick)')[:120]])
            if not log: continue
            log.sort(key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
            nm = (r.get('wellName') or '').strip()
            yr = (r.get('logDate') or '')[:4]
            yield {'id': 'co:%d' % wid, 'lat': float(lat), 'lon': float(lon), 'elev_ft': r.get('elevation'), 'depth_ft': r.get('wellDepth'),
                   'src': 'co', 'name': ('Permit ' + r['permit']) if r.get('permit') else None,
                   'date': yr if re.match(r'^(19|20)\d\d$', yr) else None, 'log': log, 'loc': r.get('locationAccuracy')}


if __name__ == '__main__':
    n = k = 0
    for w in wells(): n += 1; k += len(w['log'])
    print('wells', n, 'intervals', k)

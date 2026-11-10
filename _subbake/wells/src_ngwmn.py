#!/usr/bin/env python3
"""NGWMN (USGS National Ground-Water Monitoring Network): ~21,800 wells from USGS and state agencies; the driller's lithology log
per well from the NGWMN cache (GroundWaterML2 XML). Only wells with at least one described interval are kept (Long Island's
USGS wells, for one, list depth intervals with no words). Depths in feet; a log whose deepest interval is about the well depth
divided by 3.28 is taken as meters and converted. Public domain (USGS) / public records of the providing state agencies."""
import concurrent.futures as cf, html, json, os, re, time, urllib.error, urllib.request
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com wells bake)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'ngwmn')
WFS = 'https://www.usgs.gov/apps/ngwmn/geoserver/wfs?service=WFS&version=1.0.0&request=GetFeature&typeName=ngwmn:VW_GWDP_GEOSERVER&outputFormat=application/json'
LOG = 'https://www.usgs.gov/apps/ngwmn/ngwmn_cache/data/%s/%s/LOG'


SKIP_AGENCY = ('UNLCSD',)   # University of Nebraska-Lincoln CSD: never (user 2026-11-08: "dont use nebraskas for wells"; its licence forbids redistribution)
OFFLINE = os.environ.get('NGWMN_OFFLINE') == '1'   # cache only (2026-11-08: 12 threads got this machine's address blocked by www.usgs.gov's firewall)
WORKERS = int(os.environ.get('NGWMN_WORKERS', '2'))
PAUSE = float(os.environ.get('NGWMN_PAUSE', '0.6'))


def get(u, path, timeout=90):
    if os.path.exists(path) and os.path.getsize(path) > 0: return open(path, 'rb').read()
    if OFFLINE: return None
    time.sleep(PAUSE)
    for a in range(3):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=timeout).read()
            open(path, 'wb').write(b); return b
        except urllib.error.HTTPError as e:
            if e.code in (403, 429): raise SystemExit('NGWMN: blocked (%d), stopping; rerun later' % e.code)
            time.sleep(3 * (a + 1))
        except Exception:
            time.sleep(3 * (a + 1))
    return None


def parse(t):
    out = []
    for m in re.finditer(r'<gsml:MappedInterval.*?</gsml:MappedInterval>', t, re.S):
        g = m.group(0)
        pos = re.search(r'<gml:(?:posList|coordinates)[^>]*>(.*?)</gml:(?:posList|coordinates)>', g, re.S)
        if not pos: continue
        n = [float(x) for x in re.findall(r'-?\d+(?:\.\d+)?', pos.group(1))][:2]
        if len(n) < 2: continue
        d = re.search(r'<gml:description>(.*?)</gml:description>', g, re.S)
        txt = html.unescape(d.group(1)).strip() if d else ''
        if not txt:
            nm = [html.unescape(x).strip() for x in re.findall(r'<gml:name[^>]*>([^<]+)</gml:name>', g) if x.strip()]
            txt = ' '.join(nm[:2])
        out.append([n[0], n[1], re.sub(r'\s+', ' ', txt)[:120]])
    return out


def wells():
    os.makedirs(CACHE, exist_ok=True)
    sites = json.loads(get(WFS, os.path.join(CACHE, 'sites.json'), 300))['features']
    def one(f):
        p = f['properties']; a, s = p['AGENCY_CD'], p['SITE_NO']
        if a in SKIP_AGENCY: return None
        b = get(LOG % (a, s), os.path.join(CACHE, '%s_%s.xml' % (a, re.sub(r'\W', '_', s))))
        if not b: return None
        log = parse(b.decode('utf-8', 'replace'))
        if not any(x[2] for x in log): return None
        dep = p.get('WELL_DEPTH'); mx = max(x[1] for x in log)
        if p.get('WELL_DEPTH_UNITS_NM') == 'Meters' and dep: dep = dep * 3.28084
        if dep and mx > 0 and abs(dep / mx - 3.28084) < 0.15: log = [[x[0] * 3.28084, x[1] * 3.28084, x[2]] for x in log]
        alt = p.get('ALT_VA')
        if alt is not None and p.get('ALT_UNITS_NM') == 'Meters': alt *= 3.28084
        lat, lon = p.get('DEC_LAT_VA'), p.get('DEC_LONG_VA')
        if lat is None or lon is None: return None
        return {'id': 'ngwmn:' + p['MY_SITEID'], 'lat': lat, 'lon': lon, 'elev_ft': alt, 'depth_ft': dep or round(max(x[1] for x in log), 1), 'src': 'ngwmn',
                'name': p.get('SITE_NAME'), 'date': None, 'log': [[round(x[0], 1), round(x[1], 1), x[2]] for x in log],
                'aq': p.get('LOCAL_AQUIFER_NAME') or p.get('NAT_AQFR_DESC'), 'ag': p.get('AGENCY_NM')}
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for w in ex.map(one, sites):
            if w: yield w


if __name__ == '__main__':
    n = k = 0
    for w in wells():
        n += 1; k += len(w['log'])
        if n <= 3: print(json.dumps(w)[:300])
    print('wells', n, 'intervals', k)

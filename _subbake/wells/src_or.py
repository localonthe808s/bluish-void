#!/usr/bin/env python3
"""Oregon — OWRD Groundwater Information System (GWIS) sites: the ~10k wells OWRD has field-located and measured (current +
non-current groundwater-level observation wells), each with the driller's lithology as OWRD transcribed it.
Site lists (ArcGIS Online, OWRD): Current_Observation_Wells/FeatureServer/2 and
Noncurrent_Groundwater_Level_Observation_Wells/FeatureServer/3 ; lithology per well log id from OWRD's JSON web service
https://apps.wrd.state.or.us/apps/gw/gw_data_rws/api/{gw_logid}/gw_lithology/ (start_depth/end_depth feet,
lithology_description). One sequential request per site, cached. The ~500k other Oregon well reports are scanned PDFs only.
site_name / established_by (people) are never read; name = the OWRD well log id (e.g. MORR 63)."""
import json, os, re, time, urllib.parse, urllib.request
UA = {'User-Agent': 'bluishvoid-wells-bake/1.0 (+https://bluishvoid.com)'}
CACHE = os.path.join(os.environ.get('WELLS_CACHE', '/Users/vvvaa/.claude/jobs/9395741e/tmp/wells_cache'), 'or')
AGO = 'https://services.arcgis.com/uUvqNMGPm7axC2dD/arcgis/rest/services/'
LAYERS = ('Current_Observation_Wells/FeatureServer/2', 'Noncurrent_Groundwater_Level_Observation_Wells/FeatureServer/3')
LITH = 'https://apps.wrd.state.or.us/apps/gw/gw_data_rws/api/%s/gw_lithology/'
BOX = (41.8, 46.4, -124.8, -116.3)


def get(u, path, sleep=0.05):
    if os.path.exists(path) and os.path.getsize(path) > 0: return json.load(open(path))
    for a in range(4):
        try:
            b = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120).read()
            d = json.loads(b.decode('utf-8'))
            if isinstance(d, dict) and 'error' in d: raise ValueError(d['error'])
            tmp = path + '.part'; open(tmp, 'wb').write(b); os.replace(tmp, path); time.sleep(sleep); return d
        except Exception:
            time.sleep(4 * (a + 1))
    return None


def sites():
    os.makedirs(CACHE, exist_ok=True)
    for L in LAYERS:
        last, i = -1, 0
        while True:
            q = {'where': 'OBJECTID>%d' % last, 'outFields': 'OBJECTID,gw_logid,gw_wl_county_code,gw_wl_nbr,latitude_dec,longitude_dec,'
                 'lsd_elevation,max_depth,lat_long_source,site_horizontal_err,aquifer,public_viewable', 'orderByFields': 'OBJECTID',
                 'resultRecordCount': 2000, 'returnGeometry': 'false', 'f': 'json'}
            j = get(AGO + L + '/query?' + urllib.parse.urlencode(q), os.path.join(CACHE, '%s_p%03d.json' % (L.split('/')[0], i)), 0.2)
            fs = (j or {}).get('features') or []
            if not fs: break
            for f in fs: yield f['attributes']
            last = max(f['attributes']['OBJECTID'] for f in fs); i += 1


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def wells():
    os.makedirs(os.path.join(CACHE, 'lith'), exist_ok=True)
    seen = set()
    for a in sites():
        lid = (a.get('gw_logid') or '').strip()
        if not re.match(r'^[A-Z]{4}\d{7}$', lid) or lid in seen: continue
        lat, lon = a.get('latitude_dec'), a.get('longitude_dec')
        if lat is None or lon is None or not (BOX[0] <= lat <= BOX[1] and BOX[2] <= lon <= BOX[3]): continue
        seen.add(lid)
        j = get(LITH % lid, os.path.join(CACHE, 'lith', lid + '.json'))
        log = []
        for r in (j or {}).get('feature_list') or []:
            t = re.sub(r'\s+', ' ', r.get('lithology_description') or r.get('lithology') or '').strip()
            top = num(r.get('start_depth'))
            if not t or top is None: continue
            bot = num(r.get('end_depth'))
            log.append((round(top, 1), None if bot is None else round(bot, 1), t[:120]))
        if not log or all(x[2].lower() == 'unknown' for x in log): continue
        log = sorted(set(log), key=lambda x: (x[0], x[1] if x[1] is not None else 1e9))
        yield {'id': 'or:' + lid, 'lat': float(lat), 'lon': float(lon), 'elev_ft': num(a.get('lsd_elevation')),
               'depth_ft': num(a.get('max_depth')), 'src': 'or', 'name': '%s %s' % (a.get('gw_wl_county_code'), a.get('gw_wl_nbr')),
               'date': None, 'log': [list(x) for x in log], 'aq': a.get('aquifer'), 'loc': a.get('lat_long_source')}


if __name__ == '__main__':
    n = k = 0
    for w in wells(): n += 1; k += len(w['log'])
    print('wells', n, 'intervals', k)

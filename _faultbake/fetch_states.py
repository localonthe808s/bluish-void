"""State bedrock faults that beat the national compilation, as GeoJSON lines (WGS84) with our common properties.
   NJ: NJ Geological & Water Survey bedrock faults, 1:100,000 (NJDEP Features/Geology/MapServer/6).
   CT: Connecticut bedrock geology (Rodgers 1985, 1:125,000 digitized), the fault classes of its contacts layer."""
import json, sys, urllib.request, urllib.parse
UA = {'User-Agent': 'bluishvoid.com fault bake'}
def page(base, where, fields, off):
    q = urllib.parse.urlencode({'where': where, 'outFields': fields, 'outSR': 4326, 'f': 'geojson', 'resultOffset': off, 'resultRecordCount': 1000, 'returnGeometry': 'true'})
    return json.loads(urllib.request.urlopen(urllib.request.Request(base + '/query?' + q, headers=UA), timeout=120).read())
def all_(base, where, fields):
    out, off = [], 0
    while True:
        j = page(base, where, fields, off); f = j.get('features', [])
        out += f; off += len(f)
        if len(f) < 1000: return out
def kind(t):
    t = (t or '').lower()
    return 'thrust' if 'thrust' in t or 'reverse' in t else 'strike' if 'strike' in t or 'lateral' in t else 'normal' if 'normal' in t else 'fault'
feats = []
for f in all_('https://mapsdep.nj.gov/arcgis/rest/services/Features/Geology/MapServer/6', '1=1', 'LINACC,LINKIND,NAME'):
    p = f['properties']; a = (p.get('LINACC') or '').lower()
    feats.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {'k': kind(p.get('LINKIND')), 'u': 0 if a == 'known' else 1, 'n': p.get('NAME') or '', 's': 'NJGWS 1:100,000', 'r': 3}})
ct = all_('https://services1.arcgis.com/FjPcSmEFuDYlIdKC/arcgis/rest/services/Connecticut_Bedrock_Geology/FeatureServer/0', "DEFINITION LIKE '%ault%'", 'DEFINITION')
for f in ct:
    d = f['properties'].get('DEFINITION') or ''
    if 'Window' in d or 'Klippe' in d: continue
    feats.append({'type': 'Feature', 'geometry': f['geometry'], 'properties': {'k': kind(d), 'u': 1 if ('approx' in d.lower() or 'question' in d.lower()) else 0, 'n': '', 's': 'CT Bedrock Map (Rodgers 1985)', 'r': 3}})
json.dump({'type': 'FeatureCollection', 'features': feats}, open(sys.argv[1], 'w'))
print('states', len(feats), 'NJ+CT')

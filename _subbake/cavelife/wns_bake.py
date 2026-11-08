"""White-nose syndrome county spread -> under/wns_counties_v1.json

SOURCE (status per county):
  USGS National Wildlife Health Center, "WNS Detection Map" hosted feature layer
  (ArcGIS Online item 52d3a3a889e6406f852c0bb74f34dba0, USGS org; the layer behind the
  USGS web map "White-nose Syndrome occurence in U.S. Counties", item 3a579a4b61c8473ebed39bf002d72211)
  https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/WNS_Detection_Map/FeatureServer/0
  Data last edited 2023-04-17 (editingInfo.dataLastEditDate); latest release_date 2023-02-06;
  seasons 2005-06 .. 2021-22 (Schoharie NY suspect 2005-06). 655 counties (548 USA, 107 Canada).
  Licence: US federal government work (USGS) -> public domain; the web map carries a USGS
  "preliminary / provisional, subject to revision" disclaimer. Canadian rows are compiled by
  the WNS response partners (Canadian Wildlife Health Cooperative) inside the same layer.
  NOTE the layer has 'name'/'email' fields (submitter contact) -- never requested, never stored.
GEOMETRY:
  US: US Census Bureau cartographic boundary counties 1:20m, 2021 vintage
      (cb_2021_us_county_20m; 2021 keeps the 8 old Connecticut counties the source uses).
      Public domain. https://www2.census.gov/geo/tiger/GENZ2021/shp/cb_2021_us_county_20m.zip
  Canada: the source layer's own polygons (no FIPS), generalised server-side (maxAllowableOffset 0.01 deg).
OUTPUT props: fips (US 5-digit, null for Canada), n "County, State", y first season start year
  (any determination), ss first season "2006-07", s current status
  ('confirmed' = WNS Positive, 'suspected' = WNS Suspect, 'pd' = Pd Positive or Pd Presumed),
  pp 1 when Pd is only presumed, yc season start year it became WNS Positive (if later than y).
Run:  python3 -I wns_bake.py <source.geojson> <census_dir> <out.json>
Written 2026-11-07.
"""
import sys, json, re
sys.path.insert(0, '/Users/vvvaa/Library/Python/3.9/lib/python/site-packages')
import shapefile
from shapely.geometry import shape, mapping
from shapely import set_precision

src, cdir, out = sys.argv[1:4]
STATUS = {'WNS Positive': 'confirmed', 'WNS Suspect': 'suspected', 'Pd Positive': 'pd', 'Pd Presumed': 'pd'}
FIPS_ST = {'01':'Alabama','02':'Alaska','04':'Arizona','05':'Arkansas','06':'California','08':'Colorado','09':'Connecticut','10':'Delaware','11':'District of Columbia','12':'Florida','13':'Georgia','15':'Hawaii','16':'Idaho','17':'Illinois','18':'Indiana','19':'Iowa','20':'Kansas','21':'Kentucky','22':'Louisiana','23':'Maine','24':'Maryland','25':'Massachusetts','26':'Michigan','27':'Minnesota','28':'Mississippi','29':'Missouri','30':'Montana','31':'Nebraska','32':'Nevada','33':'New Hampshire','34':'New Jersey','35':'New Mexico','36':'New York','37':'North Carolina','38':'North Dakota','39':'Ohio','40':'Oklahoma','41':'Oregon','42':'Pennsylvania','44':'Rhode Island','45':'South Carolina','46':'South Dakota','47':'Tennessee','48':'Texas','49':'Utah','50':'Vermont','51':'Virginia','53':'Washington','54':'West Virginia','55':'Wisconsin','56':'Wyoming'}

def key(s):
    s = s.lower().replace('saint ', 'st ').replace('st. ', 'st ').replace('ste. ', 'ste ')
    s = re.sub(r'\b(county|parish|city and borough|borough)\b', '', s)
    return re.sub(r'[^a-z]', '', s)

r = shapefile.Reader(f'{cdir}/cb_2021_us_county_20m')
census = {}
for sr in r.iterShapeRecords():
    a = sr.record.as_dict()
    st = FIPS_ST.get(a['STATEFP'])
    if not st: continue
    nm = a['NAMELSAD'] if a['LSAD'] == '25' else a['NAME']   # independent cities keep "city"
    census.setdefault((st, key(a['NAME'])), []).append((a['GEOID'], nm, sr.shape.__geo_interface__, a['LSAD']))

def geom(g, tol):
    s = shape(g).buffer(0).simplify(tol, preserve_topology=True)
    s = set_precision(s, 0.0001)
    return mapping(s)

feats, miss = [], []
for f in json.load(open(src))['features']:
    p = f['properties']
    # determination_history is a malformed '{"[{\"determination\":..}]"}' string: regex it
    hist = [{'determination': a, 'status_season': b} for a, b in re.findall(
        r'determination\\?":\\?"([^"\\]+)\\?".*?status_season\\?":\\?"([0-9-]+)', p['determination_history'] or '')]
    seasons = sorted(h['status_season'] for h in hist) or [p['status_season']]
    first = min(seasons + [p['status_season']])
    y = int(first[:4])
    pos = [h['status_season'] for h in hist if h['determination'] == 'WNS Positive']
    props = {'fips': None, 'n': f"{p['county']}, {p['stateprov']}", 'y': y, 'ss': first,
             's': STATUS[p['determination']]}
    if p['determination'] == 'Pd Presumed': props['pp'] = 1
    if pos and int(min(pos)[:4]) > y: props['yc'] = int(min(pos)[:4])
    g = None
    if p['country'] == 'USA':
        c = census.get((p['stateprov'], key(p['county'])), [])
        if len(c) > 1:   # county vs independent city of same name (VA, MO): prefer the county
            c = [x for x in c if x[3] != '25'] or c
        if c:
            props['fips'] = c[0][0]; props['n'] = f"{c[0][1]}, {p['stateprov']}"
            g = geom(c[0][2], 0.005)
        else:
            miss.append(props['n'])
    if g is None:
        g = geom(f['geometry'], 0.005)
    feats.append({'type': 'Feature', 'properties': props, 'geometry': g})

feats.sort(key=lambda f: (f['properties']['y'], f['properties']['n']))
fc = {'type': 'FeatureCollection',
      'meta': {'title': 'White-nose syndrome: counties with WNS or the Pd fungus',
               'asof': '2023-04-17', 'seasons': '2005-06..2021-22', 'released_through': '2023-02-06',
               'source': 'USGS National Wildlife Health Center, WNS Detection Map (services.arcgis.com/v01gqwM5QqNysAAi WNS_Detection_Map)',
               'attribution': 'White-nose syndrome data: USGS National Wildlife Health Center and WNS partners (provisional); counties: US Census Bureau',
               'licence': 'public domain (US government work)',
               'y': 'start year of the winter season of first detection (2006 = winter 2006-07)'},
      'features': feats}
json.dump(fc, open(out, 'w'), separators=(',', ':'))
print('features', len(feats), 'unmatched US', miss)

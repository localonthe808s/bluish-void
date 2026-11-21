#!/usr/bin/env python3
"""SUPERFUND SITES, WITH WHAT IS IN THEM (user 2026-11-20: "improve the superfund data too").

EPA's map layer of the National Priorities List says where a site is and its status. What a reader wants is what is in the
ground there and what was done about it, and that lives in two spreadsheets EPA publishes from its Superfund database:
  Contaminant of Concern Data for Decision Documents by Media  (which chemicals, in groundwater / soil / sediment / ...)
  Remedy Component Data for Decision Documents by Media        (excavation, capping, pump-and-treat, monitoring ...)
Joined here by EPA ID to the list, with each site's mapped acreage and its own EPA page (the site-boundary layer) and
whether the land is back in use (EPA's "sites in reuse" layer).

The spreadsheets' addresses change each year; they are found through EPA's own index of Superfund reports.

Out: superfund_v1.json { built, n, sites: [{ la, lo, n, c, s, st: 'F'|'D'|'P', sc, li, bu, de, id, ac, fed, url, reuse,
                                              m: { g: [...], s: [...], d: [...], w: [...], o: [...] }, r: [...] }, ...] }
     m = contaminants by medium (groundwater, soil, sediment, surface water, other), most often named first, folded to the
     families a reader knows (FAMILY: 'Chlorinated solvents', 'PCBs', 'Pesticides' ...; metals keep their names); r = remedies in plain words.
Run: python3 _superfundbake/bake.py [out.json]     (no keys; a minute or two)
"""
import sys, os, io, re, json, time, zipfile, datetime, collections, urllib.request, urllib.parse
import xml.etree.ElementTree as ET

UA = {'User-Agent': 'Mozilla/5.0 (superfund-bake)'}
A = 'https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/'
INDEX = 'https://www3.epa.gov/semsjson/HQ_MasterCollection_11.json'
NS = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
MED = {'Groundwater': 'g', 'Soil': 's', 'Sediment': 'd', 'Surface Water': 'w'}


def get(url, tries=4, timeout=240):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except Exception as e:
            if 'SSL' in str(e):                      # an old local Python cannot shake hands with some EPA hosts; curl can
                import subprocess
                r = subprocess.run(['curl', '-s', '-L', '--fail', '-A', UA['User-Agent'], '--max-time', str(timeout), url], capture_output=True)
                if r.returncode == 0 and r.stdout:
                    return r.stdout
            if i == tries - 1:
                raise
            time.sleep(6 * (i + 1))


def layer(path, fields, where='1=1'):
    out, off = [], 0
    while True:
        q = urllib.parse.urlencode({'where': where, 'outFields': fields, 'returnGeometry': 'false', 'resultOffset': off, 'resultRecordCount': 2000, 'f': 'json'})
        F = json.loads(get(A + path + '/query?' + q)).get('features', [])
        out += [f['attributes'] for f in F]
        if len(F) < 2000:
            return out
        off += 2000


def sheet(raw):
    """rows of the first sheet of an .xlsx, read with the standard library"""
    z = zipfile.ZipFile(io.BytesIO(raw)); ss = []
    if 'xl/sharedStrings.xml' in z.namelist():
        for si in ET.parse(z.open('xl/sharedStrings.xml')).getroot().iter(NS + 'si'):
            ss.append(''.join(t.text or '' for t in si.iter(NS + 't')))
    f = sorted([n for n in z.namelist() if re.match(r'xl/worksheets/sheet\d+\.xml', n)])[0]
    for _, el in ET.iterparse(z.open(f)):
        if el.tag != NS + 'row':
            continue
        r = {}
        for c in el.iter(NS + 'c'):
            v = c.find(NS + 'v'); t = c.get('t')
            if t == 'inlineStr':
                val = ''.join(x.text or '' for x in c.iter(NS + 't'))
            elif v is None:
                continue
            else:
                val = ss[int(v.text)] if t == 's' else v.text
            n = 0
            for ch in re.match(r'[A-Z]+', c.get('r')).group(0):
                n = n * 26 + ord(ch) - 64
            r[n - 1] = val
        yield [r.get(i, '') for i in range(max(r) + 1)] if r else []
        el.clear()


def report(title_re):
    idx = json.loads(get(INDEX))['data']
    hit = [r for r in idx if re.search(title_re, r.get('title', ''))]
    if not hit:
        raise RuntimeError('report not in EPA index: ' + title_re)
    hit.sort(key=lambda r: datetime.datetime.strptime(r['date'], '%m/%d/%Y'), reverse=True)
    url = re.search(r"href='([^']+)'", hit[0]['title']).group(1)
    print('  ', re.sub(r'<[^>]+>', '', hit[0]['title'])[:90], '|', hit[0]['date'], flush=True)
    R = list(sheet(get(url, timeout=600)))
    h = next(i for i, r in enumerate(R) if 'EPA ID' in r)
    H = R[h]
    return [dict(zip(H, r)) for r in R[h + 1:] if len(r) >= len(H) - 1]


METALS = ('ARSENIC', 'LEAD', 'CHROMIUM', 'CADMIUM', 'MERCURY', 'ZINC', 'COPPER', 'NICKEL', 'MANGANESE', 'ANTIMONY', 'BARIUM', 'BERYLLIUM', 'SELENIUM', 'THALLIUM',
          'VANADIUM', 'COBALT', 'SILVER', 'ALUMINUM', 'IRON', 'MOLYBDENUM', 'TIN')
FAMILY = [  # a chemist's name -> the family a reader knows; first match wins
    (r'PERFLUORO|PFOA|PFOS|PFAS|FLUOROTELOMER', 'PFAS'),
    (r'AROCLOR|POLYCHLORINATED BIPHENYL|\bPCB', 'PCBs'),
    (r'DIOXIN|TCDD|FURAN|\bCDD\b|\bCDF\b', 'Dioxins'),
    (r'RADIUM|URANIUM|THORIUM|RADON|PLUTONIUM|CESIUM|STRONTIUM|TRITIUM|AMERICIUM|TECHNETIUM|RADIONUCLIDE|GROSS ALPHA|GROSS BETA|COBALT-60|IODINE-1', 'Radioactive material'),
    (r'ASBESTOS', 'Asbestos'), (r'CYANIDE', 'Cyanide'),
    (r'PENTACHLOROPHENOL|CREOSOTE', 'Wood-treating chemicals'),
    (r'ANTHRACENE|PYRENE|FLUORANTHENE|CHRYSENE|NAPHTHALENE|FLUORENE|ACENAPHTH|PHENANTHRENE|PERYLENE|^BENZO\(|POLYCYCLIC AROMATIC|\bPAH', 'PAHs (tar and soot chemicals)'),
    (r'DIELDRIN|ALDRIN|\bDDT|\bDDE|\bDDD|CHLORDANE|HEPTACHLOR|TOXAPHENE|LINDANE|ENDRIN|ENDOSULFAN|HEXACHLOROCYCLOHEXANE|\bBHC\b|PESTICIDE|ATRAZINE|MIREX|KEPONE|DICHLORODIPHENYL', 'Pesticides'),
    (r'TRICHLOROETHENE|TETRACHLOROETHENE|DICHLOROETHENE|VINYL CHLORIDE|CHLOROETHENE|TRICHLOROETHANE|DICHLOROETHANE|TETRACHLOROETHANE|CHLOROFORM|CARBON TETRACHLORIDE|METHYLENE CHLORIDE|DICHLOROMETHANE|CHLOROBENZENE|DICHLOROBENZENE|TRICHLOROBENZENE|DICHLOROPROPANE|CHLORINATED|\bTCE\b|\bPCE\b', 'Chlorinated solvents (TCE, PCE and kin)'),
    (r'^BENZENE|TOLUENE|ETHYLBENZENE|XYLENE|\bBTEX|PETROLEUM|GASOLINE|DIESEL|\bTPH\b|MTBE|METHYL TERT', 'Fuel chemicals (benzene, toluene and kin)'),
    (r'1,4-DIOXANE', '1,4-Dioxane'), (r'PERCHLORATE', 'Perchlorate'), (r'NITRATE|NITRITE|AMMONIA', 'Nitrates and ammonia'),
    (r'PHTHALATE', 'Phthalates (plasticizers)'), (r'PHENOL', 'Phenols'), (r'EXPLOSIVE|\bTNT\b|TRINITROTOLUENE|\bRDX\b|\bHMX\b|DINITROTOLUENE', 'Explosives'),
    (r'ACID|\bPH\b', 'Acids'), (r'VOC|VOLATILE ORGANIC', 'Volatile organic chemicals'), (r'METAL', 'Metals'),
]
REMEDY = {'Institutional Controls': 'Land-use restrictions', 'Monitoring': 'Monitoring', 'Excavation': 'Dug out', 'Disposal': 'Hauled away', 'Cap': 'Capped',
          'Containment': 'Contained on site', 'Extraction': 'Groundwater pumped out', 'Monitored Natural Attenuation': 'Left to break down, watched',
          'Treatment': 'Treated', 'Consolidate': 'Gathered and contained', 'Revegetation': 'Replanted', 'Pump and Treat': 'Groundwater pumped and treated',
          'Soil Vapor Extraction': 'Vapors drawn out of the soil', 'Solidification/Stabilization': 'Locked in place (solidified)', 'Dredging': 'Dredged',
          'Alternate Water Supply': 'New water supply for neighbors', 'Incineration': 'Burned', 'In Situ Chemical Oxidation': 'Treated in the ground',
          'Bioremediation': 'Broken down by microbes', 'Vertical Engineered Barrier': 'Underground wall', 'Permeable Reactive Barrier': 'Underground treatment wall',
          'Air Stripping': 'Groundwater pumped and treated', 'Carbon Adsorption': 'Filtered through carbon', 'Wetlands Replacement': 'Wetlands rebuilt',
          'Fencing': 'Fenced off', 'Thermal Treatment': 'Heated to drive chemicals out'}
SKIP_REMEDY = re.compile(r'^(No Action|No Further Action|ESD|Discharge|Other|Engineering Control|Drainage|Water Table|Stream Realignment|Source Control|Leachate Control)', re.I)


def family(name):
    u = name.upper()
    for m in METALS:
        if u == m or u.startswith(m + ' ') or u.startswith(m + ',') or u.startswith(m + '('):
            return m.capitalize()
    for rx, fam in FAMILY:
        if re.search(rx, u):
            return fam
    return name.capitalize() if len(name) <= 26 else None          # an unfamiliar long name helps nobody


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'superfund_v1.json')
    npl = layer(urllib.parse.quote('Superfund_National_Priorities_List_(NPL)_Sites_with_Status_Information') + '/FeatureServer/0',
                'Site_Name,Site_Score,Site_EPA_ID,SEMS_ID,State,City,Status,Longitude,Latitude,Listing_Date,Deletion_Date,Construction_Completion_Date')
    print(len(npl), 'sites on the list', flush=True)
    if len(npl) < 1500:
        print('TOO FEW: not writing'); sys.exit(1)
    bnd = layer('FAC_Superfund_Site_Boundaries_EPA_Public/FeatureServer/0', 'EPA_ID,GIS_AREA,URL_ALIAS_TXT,FEDERAL_FACILITY_DETER_CODE')
    acres, page, fed = collections.Counter(), {}, {}
    for b in bnd:
        acres[b['EPA_ID']] += b.get('GIS_AREA') or 0
        if b.get('URL_ALIAS_TXT'):
            page[b['EPA_ID']] = b['URL_ALIAS_TXT'].strip()
        if b.get('FEDERAL_FACILITY_DETER_CODE') == 'Y':
            fed[b['EPA_ID']] = 1
    reuse = {str(r.get('Site_ID') or '').lstrip('0') for r in layer('Superfund_Sites_In_Reuse/FeatureServer/0', 'Site_ID')}
    # EPA's site-wide human exposure indicator (Y under control, N not under control, U insufficient data), from Cleanups in My Community
    he = {}
    for r in layer('Cleanups_in_my_Community_Sites/FeatureServer/0', 'EPA_ID,SF_EI_HE_CODE', "SF_EI_HE_CODE<>''"):
        if r.get('EPA_ID') and r.get('SF_EI_HE_CODE') in ('Y', 'N', 'U'):
            he[r['EPA_ID']] = r['SF_EI_HE_CODE']
    coc = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    for r in report(r'Contaminant of Concern Data for Decision Documents by Media'):
        nm = family((r.get('Contaminant Name') or '').strip())
        if nm:
            coc[r['EPA ID']][MED.get(r.get('Media'), 'o')][nm] += 1
        if r.get('Federal Facility') == 'Y':
            fed[r['EPA ID']] = 1
    rem = collections.defaultdict(collections.Counter)
    for r in report(r'Remedy Component Data for Decision Documents by Media'):
        nm = re.sub(r'\s*\(.*', '', (r.get('Remedy Component') or '')).strip()
        nm = None if not nm or SKIP_REMEDY.match(nm) else REMEDY.get(nm, nm)
        if nm:
            rem[r['EPA ID']][nm] += 1
    sites = []
    for a in npl:
        try:
            la, lo = float(a['Latitude']), float(a['Longitude'])
        except (TypeError, ValueError):
            continue
        if not la:
            continue
        eid = a.get('Site_EPA_ID') or ''
        st = a.get('Status') or ''
        m = {k: [n for n, _ in c.most_common(6)] for k, c in coc.get(eid, {}).items()}
        rr = [n for n, _ in rem.get(eid, collections.Counter()).most_common(5)]
        s = {'la': round(la, 5), 'lo': round(lo, 5), 'n': (a.get('Site_Name') or '').strip(), 'c': (a.get('City') or '').strip(), 's': (a.get('State') or '').strip(),
             'st': 'D' if 'Deleted' in st else 'P' if 'Proposed' in st else 'F', 'sc': a.get('Site_Score'), 'li': a.get('Listing_Date') or '',
             'bu': a.get('Construction_Completion_Date') or '', 'de': a.get('Deletion_Date') or '', 'id': eid,
             'url': page.get(eid) or ('https://cumulis.epa.gov/supercpad/cursites/csitinfo.cfm?id=%07d' % int(a['SEMS_ID']) if a.get('SEMS_ID') else '')}
        if acres.get(eid):
            s['ac'] = round(acres[eid], 1 if acres[eid] < 100 else 0)
        if fed.get(eid):
            s['fed'] = 1
        if str(a.get('SEMS_ID') or '').lstrip('0') in reuse:
            s['reuse'] = 1
        if he.get(eid):
            s['he'] = he[eid]
        if m:
            s['m'] = m
        if rr:
            s['r'] = rr
        sites.append(s)
    json.dump({'built': datetime.date.today().isoformat(), 'n': len(sites), 'sites': sites}, open(out, 'w'), separators=(',', ':'))
    print('wrote', out, os.path.getsize(out) // 1024, 'KB |', len(sites), 'sites | with contaminants', sum(1 for s in sites if s.get('m')), '| with remedies',
          sum(1 for s in sites if s.get('r')), '| with acreage', sum(1 for s in sites if s.get('ac')), '| in reuse', sum(1 for s in sites if s.get('reuse')), '| federal', sum(1 for s in sites if s.get('fed')), '| exposure status', collections.Counter(s.get('he') for s in sites))


if __name__ == '__main__':
    main()

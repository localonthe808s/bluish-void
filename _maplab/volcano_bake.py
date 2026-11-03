#!/usr/bin/env python3
"""
VOLCANOES (2026-11-02): the GEOLOGY tab's third view, on the DEEP TIME globe. One daily file, R2 volcano/latest.json:
  * every Holocene volcano from the Smithsonian Global Volcanism Program (Volcanoes of the World, via its WFS): name,
    number, lat/lon, elevation, type, last eruption year, country, the GVP photo and its credit, the first sentences of
    the geological summary -- 1,214 points, the Ring of Fire drawn by themselves;
  * the big eruptions from the same database: every VEI 6 and 7 of the Holocene, every VEI 5 since 1500, and a curated
    list of the greats with a line each (VEI, the year, what it did), older ones (Toba, Yellowstone) added by hand;
  * this week: the Smithsonian / USGS Weekly Volcanic Activity Report (RSS, with coordinates), and the USGS alert levels
    for the United States (volcanoes.usgs.gov API).
Citation: Global Volcanism Program, Smithsonian Institution, Volcanoes of the World (https://volcano.si.edu); the data are
free to use with that credit. USGS material is public domain.

    python3 _maplab/volcano_bake.py out            # out/volcano/latest.json
"""
import html, json, os, re, sys, time, urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
UA = {'User-Agent': 'bluishvoid-volcano-bake (https://bluishvoid.com)'}
WFS = 'https://webservices.volcano.si.edu/geoserver/GVP-VOTW/ows?service=WFS&version=2.0.0&request=GetFeature&typeName=GVP-VOTW:%s&outputFormat=json'
RSS = 'https://volcano.si.edu/news/WeeklyVolcanoRSS.xml'
USGS = 'https://volcanoes.usgs.gov/vsc/api/volcanoApi/elevated'

# the greats: GVP volcano number (for the coordinates), year, VEI, a line. Negative years are BCE; 'ka' entries are older than the Holocene list
GREATS = [
    (None, 'Toba', 2.68, 98.83, -72000, 8, 'The largest eruption of the last two million years: 2,800 cubic kilometres of rock, a lake 100 km long in the caldera, ash across the Indian Ocean. A volcanic winter that may have thinned the human population.'),
    (None, 'Yellowstone', 44.43, -110.67, -640000, 8, 'The Lava Creek eruption, 1,000 cubic kilometres, ash over most of what is now the United States; the caldera is 70 km across and still breathes.'),
    (212040, 'Santorini (Thera)', 36.404, 25.396, -1610, 7, 'The Minoan eruption blew out the centre of the island; its tsunami and ash reached Crete and may have helped end the Minoan world.'),
    (211020, 'Vesuvius', 40.821, 14.426, 79, 5, 'Buried Pompeii and Herculaneum under ash and pyroclastic surges in two days; Pliny the Younger wrote the first eyewitness account of an eruption.'),
    (264030, 'Rinjani (Samalas)', -8.42, 116.47, 1257, 7, 'The largest eruption of the last 7,000 years, traced to Lombok only in 2013 from ice cores; a cold, wet year across Europe followed.'),
    (354020, 'Huaynaputina', -16.608, -70.85, 1600, 6, 'The biggest eruption in South America in recorded history; the summer that failed in Russia and the famine of 1601 to 1603.'),
    (373010, 'Laki', 64.42, -17.33, 1783, 4, 'An eight-month fissure eruption that poured out 14 cubic kilometres of lava and a sulfur haze over Europe; a fifth of Iceland died, and the following winter was one of the coldest on record.'),
    (264040, 'Tambora', -8.25, 118.0, 1815, 7, 'The largest eruption in recorded history: the mountain lost its top kilometre, 10,000 died outright and tens of thousands in the famine; 1816 was the Year Without a Summer.'),
    (262000, 'Krakatau', -6.102, 105.423, 1883, 6, 'The explosions were heard 4,800 km away; the tsunami killed 36,000 along the Sunda Strait; the sunsets were red for years.'),
    (360120, 'Pelee', 14.809, -61.165, 1902, 4, 'A pyroclastic flow destroyed Saint-Pierre, Martinique, in minutes: 28,000 dead, two survivors; the eruption that named the nuee ardente.'),
    (342030, 'Santa Maria', 14.757, -91.552, 1902, 6, 'Guatemala; one of the three largest eruptions of the 20th century, after a five-century silence.'),
    (312180, 'Novarupta (Katmai)', 58.27, -155.157, 1912, 6, 'The largest eruption of the 20th century, in remote Alaska; the Valley of Ten Thousand Smokes filled with ash 200 m deep.'),
    (321050, 'St. Helens', 46.2, -122.18, 1980, 5, 'The north face slid away in the largest landslide in recorded history and the lateral blast flattened 600 square kilometres of forest; 57 died.'),
    (273083, 'Pinatubo', 15.13, 120.35, 1991, 6, 'The second-largest eruption of the 20th century; 20 million tonnes of sulfur dioxide cooled the whole planet by half a degree for two years.'),
    (372020, 'Eyjafjallajokull', 63.63, -19.62, 2010, 4, 'A modest eruption under a glacier whose ash grounded European air travel for six days.'),
    (243040, "Hunga Tonga-Hunga Ha'apai", -20.536, -175.382, 2022, 5, 'The most powerful explosion ever recorded by instruments: a plume to 57 km, a shock wave that circled the planet several times, a tsunami across the Pacific.'),
]


def get(url, binary=False, tries=3):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                b = r.read()
                if binary:
                    return b
                # the weekly RSS declares ISO-8859-1 (its accents, "Geología", came through as U+FFFD when read as UTF-8)
                m = re.match(rb'<\?xml[^>]*encoding="([\w-]+)"', b[:200])
                enc = m.group(1).decode() if m else 'utf-8'
                try:
                    return b.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    return b.decode('utf-8', 'replace')
        except Exception as e:
            print('  retry', k + 1, url[:70], e); time.sleep(5 * (k + 1))
    return None


def whole(t, cap=900):
    # the report text cut at a sentence, never mid-word (the card shows whole sentences)
    t = re.sub(r'\s+', ' ', t or '').strip()
    if len(t) <= cap:
        return t
    s = t[:cap]; k = max(s.rfind('. '), s.rfind('.) '))
    return s[:k + 1] if k > cap * 0.35 else s.rsplit(' ', 1)[0] + '…'


def first_sentences(t, n=2, cap=320):
    t = re.sub(r'\s+', ' ', t or '').strip()
    parts = re.split(r'(?<=[.!?])\s+', t)
    s = ' '.join(parts[:n])
    return s if len(s) <= cap else s[:cap].rsplit(' ', 1)[0] + '…'


def main():
    os.makedirs(os.path.join(OUT, 'volcano'), exist_ok=True)
    doc = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'volcanoes': [], 'eruptions': [], 'greats': [], 'week': [], 'usgs': [],
           'sources': [['Smithsonian Global Volcanism Program, Volcanoes of the World', 'https://volcano.si.edu/'], ['Smithsonian / USGS Weekly Volcanic Activity Report', 'https://volcano.si.edu/reports_weekly.cfm'], ['USGS Volcano Hazards Program', 'https://volcanoes.usgs.gov/']]}
    # volcanoes
    j = json.loads(get(WFS % 'Smithsonian_VOTW_Holocene_Volcanoes'))
    byn = {}
    for f in j['features']:
        p = f['properties']; lon, lat = f['geometry']['coordinates']
        v = {'n': p['Volcano_Number'], 'name': p['Volcano_Name'], 'lat': round(lat, 3), 'lon': round(lon, 3), 'elev': p.get('Elevation'), 'type': p.get('Primary_Volcano_Type'),
             'last': p.get('Last_Eruption_Year'), 'country': p.get('Country'), 'region': p.get('Region'), 'setting': p.get('Tectonic_Setting'),
             'photo': p.get('Primary_Photo_Link'), 'credit': p.get('Primary_Photo_Credit'), 'sum': first_sentences(p.get('Geological_Summary'), 1, 220)}
        doc['volcanoes'].append(v); byn[v['n']] = v
    print(len(doc['volcanoes']), 'volcanoes')
    # eruptions
    j = json.loads(get(WFS % 'Smithsonian_VOTW_Holocene_Eruptions'))
    for f in j['features']:
        p = f['properties']; vei = p.get('ExplosivityIndexMax'); y = p.get('StartDateYear')
        if vei is None or y is None or p.get('Activity_Type') != 'Confirmed Eruption':
            continue
        if vei >= 6 or (vei >= 5 and y >= 1500) or (vei >= 4 and y >= 1950):
            doc['eruptions'].append({'n': p['Volcano_Number'], 'name': p['Volcano_Name'], 'y': y, 'vei': vei})
    doc['eruptions'].sort(key=lambda e: e['y'])
    print(len(doc['eruptions']), 'eruptions kept')
    # greats
    for n, name, lat, lon, y, vei, line in GREATS:
        v = byn.get(n) if n else None
        doc['greats'].append({'n': n, 'name': name, 'lat': v['lat'] if v else lat, 'lon': v['lon'] if v else lon, 'y': y, 'vei': vei, 'line': line, 'photo': v and v.get('photo'), 'credit': v and v.get('credit')})
    # this week
    x = get(RSS)
    if x:
        for it in re.findall(r'<item>(.*?)</item>', x, re.S):
            ti = re.search(r'<title>(.*?)</title>', it, re.S); pt = re.search(r'<georss:point>(.*?)</georss:point>', it); d = re.search(r'<description>(.*?)</description>', it, re.S); ln = re.search(r'<link>(.*?)</link>', it)
            if not (ti and pt):
                continue
            t = html.unescape(ti.group(1)).strip(); m = re.match(r'(.*?) \((.*?)\) - Report for (.*?) - (.*)$', t)
            la, lo = [float(q) for q in pt.group(1).split()]
            txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', html.unescape(d.group(1) if d else ''))).strip()
            txt = re.sub(r"(?<=\w)\?(?=s\b)", "\u2019", txt)          # the feed's own lost apostrophes ("Etna?s")
            doc['week'].append({'name': m.group(1) if m else t, 'country': m.group(2) if m else '', 'period': m.group(3) if m else '', 'status': m.group(4) if m else '', 'lat': la, 'lon': lo, 'text': whole(txt), 'url': ln.group(1).strip() if ln else ''})
    print(len(doc['week']), 'in the weekly report')
    # usgs alerts
    u = get(USGS)
    if u:
        for e in json.loads(u):
            doc['usgs'].append({'name': e.get('vName'), 'color': e.get('colorCode'), 'alert': e.get('alertLevel'), 'lat': e.get('lat'), 'lon': e.get('long'), 'text': (e.get('noticeSynopsis') or '')[:400], 'threat': e.get('nvewsThreat'), 'n': e.get('vnum')})
    print(len(doc['usgs']), 'US alerts')
    with open(os.path.join(OUT, 'volcano', 'latest.json'), 'w') as fh:
        json.dump(doc, fh, separators=(',', ':'), ensure_ascii=False)
    print('wrote', os.path.join(OUT, 'volcano', 'latest.json'), os.path.getsize(os.path.join(OUT, 'volcano', 'latest.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()

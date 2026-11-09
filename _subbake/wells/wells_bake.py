#!/usr/bin/env python3
"""WELLS: every water well (and other borehole) with a driller's lithology log we may show (user 2026-11-08: "is there public borehole
data we could visualize underground?" -> mockup -> "yes build it, add the state wells too").

Sources are the src_<code>.py adapters beside this file (NGWMN nationally, then each state that publishes machine-readable logs; see
SOURCES.md). Each yields {id, lat, lon, elev_ft, depth_ft, src, name, date, log: [[top_ft, bottom_ft, words]]}.

Out (R2 bluishvoid-bg, under/):
  wells_v1.pmtiles          the dots, layer 'w': i id, d depth ft, s source (tippecanoe, densest dropped at low zooms)
  wells/logs/<cx>_<cy>.json the logs by 0.1-degree cell (cx = floor((lon+180)*10), cy = floor((lat+90)*10)):
                            {id: [lat, lon, elev_ft, depth_ft, name, date, src, [[top, bottom, words], ...], aquifer, agency]}
  wells/manifest.json       per source: count, credit, licence, link

    python3 wells_bake.py OUTDIR [src codes...] [--upload]
"""
import importlib.util, json, math, os, subprocess, sys, glob, time
HERE = os.path.dirname(os.path.abspath(__file__))
# credit, licence note, link per source (shown on the well card and in the slice); see SOURCES.md for the terms quoted
CREDIT = {
    'ngwmn': ('USGS National Ground-Water Monitoring Network', 'public domain / state public records', 'https://www.usgs.gov/apps/ngwmn/'),
    'tx': ('Texas Water Development Board, Groundwater Database', 'public records', 'https://www.twdb.texas.gov/groundwater/data/gwdbrpt.asp'),
    'txsdr': ('Texas Water Development Board, Submitted Drillers Reports', 'public records', 'https://www.twdb.texas.gov/groundwater/data/drillersdb.asp'),
    'ca': ('California DWR, Well Completion Reports', 'public domain', 'https://data.cnra.ca.gov/dataset/well-completion-reports'),
    'mt': ('Montana Bureau of Mines and Geology, GWIC (via Montana DNRC)', 'public records', 'https://mbmggwic.mtech.edu/'),
    'wa': ('Washington Geological Survey, Subsurface database (DDS-11)', 'as is, cite DDS-11', 'https://dnr.wa.gov/node/118'),
    'ct': ('USGS, depth to bedrock from Connecticut Water Resources Bulletins', 'public domain', 'https://www.sciencebase.gov/'),
    'nyli': ('USGS, Long Island hydrogeologic framework (Finkelstein and others, 2024)', 'public domain', 'https://www.sciencebase.gov/'),
    'pa': ('Pennsylvania DCNR Geological Survey, PaGWIS', 'public records', 'https://www.dcnr.pa.gov/Geology/GeologicalDataAndInformation/PaGWIS/'),
    'in': ('Indiana DNR Division of Water, Water Well Record Database', 'public records', 'https://www.in.gov/dnr/water/'),
    'il': ('Illinois State Geological Survey, ILGeoTech borings', 'public records', 'https://isgs.illinois.edu/'),
    'mi': ('Michigan EGLE, Wellogic', 'public records', 'https://www.michigan.gov/egle'),
    'ks': ('Kansas Geological Survey, WWC5 water well records (KDHE)', 'as is', 'https://www.kgs.ku.edu/Magellan/WaterWell/'),
    'ksog': ('Kansas Geological Survey, oil and gas well formation tops', 'public records', 'https://www.kgs.ku.edu/Magellan/Qualified/'),
    'mn': ('Minnesota Geological Survey and Department of Health, County Well Index', 'public records', 'https://www.health.state.mn.us/communities/environment/water/mwi/'),
    'ia': ('Iowa Geological Survey, GeoSam', 'unrestricted use, credit IGS', 'https://geosam.iihr.uiowa.edu/'),
    'wi': ('Wisconsin Geological and Natural History Survey, wiscLITH', 'public records', 'https://wgnhs.wisc.edu/'),
    'or': ('Oregon Water Resources Department, GWIS', 'public records', 'https://apps.wrd.state.or.us/apps/gw/gw_info/gw_info_report/'),
}
SKIP = ('co', 'ma', 'ne')   # co: staff aquifer picks only, API blocks; ma: ~58 h of PDF parsing, held back; ne: never (user 2026-11-08: "dont use nebraskas for wells"; its licence forbids redistribution); adapter removed


def load(code):
    spec = importlib.util.spec_from_file_location('src_' + code, os.path.join(HERE, 'src_%s.py' % code))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def main(out, codes, up):
    os.makedirs(os.path.join(out, 'logs'), exist_ok=True)
    if not codes: codes = sorted(c for c in (os.path.basename(p)[4:-3] for p in glob.glob(os.path.join(HERE, 'src_*.py'))) if c not in SKIP)
    man, seen = {}, set()
    pts = open(os.path.join(out, 'points.ndjson'), 'w')
    # logs stream to 64 bucket files by cell key, then each bucket is split into its cells: memory stays flat (2.6M wells, 8 GB machine)
    NB = 64; bk = [open(os.path.join(out, 'b%02d.ndjson' % i), 'w') for i in range(NB)]
    for code in codes:
        m = load(code); n = 0; t0 = time.time()
        for w in m.wells():
            try: lat, lon = float(w['lat']), float(w['lon'])
            except Exception: continue
            if not (13 < lat < 72 and -180 < lon < -64) or not w.get('log'): continue   # the US and its territories; drops swapped coordinates (an Illinois NGWMN well at -88.4, 40.2)
            if w['id'] in seen: continue
            seen.add(w['id'])
            log = [[round(float(a), 1), round(float(b), 1), str(t or '')[:120]] for a, b, t in w['log'] if a is not None and b is not None]
            if not log: continue
            dep = w.get('depth_ft') or max(x[1] for x in log)
            k = '%d_%d' % (math.floor((lon + 180) * 10), math.floor((lat + 90) * 10))
            rec = [round(lat, 5), round(lon, 5), None if w.get('elev_ft') is None else round(float(w['elev_ft']), 1), round(float(dep), 1),
                   w.get('name'), w.get('date'), w['src'], log, w.get('aq'), w.get('ag')]
            bk[hash(k) % NB].write(json.dumps([k, w['id'], rec], separators=(',', ':')) + '\n')
            pts.write(json.dumps({'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [round(lon, 5), round(lat, 5)]},
                                  'properties': {'i': w['id'], 'd': int(round(float(dep))), 's': w['src']}}) + '\n')
            n += 1
        cr = CREDIT.get(code, (code.upper(), '', ''))
        man[code] = {'count': n, 'credit': cr[0], 'terms': cr[1], 'link': cr[2]}
        print(code, n, 'wells', round(time.time() - t0), 's', flush=True)
    pts.close(); ncell = 0
    for f in bk: f.close()
    for i in range(NB):
        cells = {}; bp = os.path.join(out, 'b%02d.ndjson' % i)
        for line in open(bp):
            k, wid, rec = json.loads(line); cells.setdefault(k, {})[wid] = rec
        for k, v in cells.items(): json.dump(v, open(os.path.join(out, 'logs', k + '.json'), 'w'), separators=(',', ':'))
        ncell += len(cells); os.remove(bp)
    json.dump({'built': int(time.time()), 'sources': man, 'cells': ncell}, open(os.path.join(out, 'manifest.json'), 'w'))
    pm = os.path.join(out, 'wells_v1.pmtiles')
    subprocess.run(['tippecanoe', '-o', pm, '-f', '-l', 'w', '-Z2', '-z12', '--drop-densest-as-needed', '--extend-zooms-if-still-dropping',
                    '-r1', '--maximum-tile-bytes=600000', os.path.join(out, 'points.ndjson')], check=True)
    print('cells', ncell, 'pmtiles', os.path.getsize(pm) // 1024, 'KB')
    if up:
        H = ['--s3-no-check-bucket', '--header-upload', 'Cache-Control: public, max-age=86400']
        subprocess.run(['rclone', 'copyto', pm, 'r2:bluishvoid-bg/under/wells_v1.pmtiles', '--header-upload', 'Content-Type: application/vnd.pmtiles'] + H, check=True)
        subprocess.run(['rclone', 'copy', os.path.join(out, 'logs'), 'r2:bluishvoid-bg/under/wells/logs', '--transfers', '32', '--header-upload', 'Content-Type: application/json'] + H, check=True)
        subprocess.run(['rclone', 'copyto', os.path.join(out, 'manifest.json'), 'r2:bluishvoid-bg/under/wells/manifest.json', '--header-upload', 'Content-Type: application/json'] + H, check=True)


if __name__ == '__main__':
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    main(a[0], a[1:], '--upload' in sys.argv)

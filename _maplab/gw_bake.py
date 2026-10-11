"""GRAVITATIONAL WAVES (2026-10-11): the public record of LIGO, Virgo and KAGRA, baked for the page.

Three things, all keyless and public:
  alerts   GraceDB's significant public alerts (category Production, label ADVOK, not RETRACTED): id, time, false-alarm
           rate, source classification (p_astro: BBH / BNS / NSBH / Terrestrial), HasNS / HasRemnant, the detectors, and
           the sky map (the parameter-estimation map if there is one, else the rapid BAYESTAR map) REHOSTED to R2 under
           gw/sky/<id>.png -- GraceDB sends no CORS header, and its pictures should not be hot-linked from a public page.
  catalog  GWOSC's confident catalogues (GWTC-1..GWTC-5): every merger with source-frame masses, the final mass,
           distance, SNR. Newest catalogue version wins per event.
  chirp    GW150914, the first detection: LIGO Hanford's whitened, band-passed strain and the best-fit waveform, from the
           discovery paper's published figure data (GWOSC, CC BY 4.0), cut to 0.25-0.46 s and decimated 2x.
Writes OUT/gw.json and OUT/sky/*.png. Daily is plenty between observing runs; hourly during one.
"""
import json, os, sys, time, urllib.parse, urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else '_gw_out'
os.makedirs(os.path.join(OUT, 'sky'), exist_ok=True)
UA = {'User-Agent': 'bluishvoid.com gravitational-wave bake (contact via site)'}
GDB = 'https://gracedb.ligo.org/api/'


def get(url, tries=3, timeout=90):
    for k in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r: return r.read()
        except Exception as e:
            if k == tries - 1: raise
            time.sleep(4)


def jget(url): return json.loads(get(url).decode('utf-8'))


# ---- alerts -------------------------------------------------------------------------------------------------------
q = urllib.parse.urlencode({'query': 'category: Production label: ADVOK', 'count': 400, 'format': 'json'})
sev = jget(GDB + 'superevents/?' + q)['superevents']
alerts = []
for e in sev:
    if 'RETRACTED' in e['labels']: continue
    sid = e['superevent_id']; p = e.get('preferred_event_data') or {}
    rec = {'id': sid, 't': e['created'][:19].replace(' ', 'T') + 'Z', 'far': e.get('far'), 'group': p.get('group'),
           'pipeline': p.get('pipeline'), 'ifos': p.get('instruments'), 'cls': None, 'hasNS': None, 'hasRemnant': None, 'sky': None}
    alerts.append(rec)
print('significant alerts', len(alerts))
# details for the newest 40: classification, em_bright, sky map
for rec in alerts[:40]:
    sid = rec['id']
    try: files = jget(GDB + 'superevents/%s/files/?format=json' % sid)
    except Exception as ex: print(' files failed', sid, ex); continue
    pa = [k for k in files if k.endswith('p_astro.json') and not k.endswith('.png')]
    if pa:
        try: rec['cls'] = {k: round(v, 4) for k, v in jget(files[pa[0]]).items()}
        except Exception: pass
    if 'em_bright.json' in files:
        try: eb = jget(files['em_bright.json']); rec['hasNS'] = eb.get('HasNS'); rec['hasRemnant'] = eb.get('HasRemnant')
        except Exception: pass
    for name in ('Bilby.png', 'bayestar.png', 'cwb.png', 'olib.png'):
        if name in files:
            try:
                png = get(files[name]); fn = os.path.join(OUT, 'sky', sid + '.png'); open(fn, 'wb').write(png)
                try:   # crop the matplotlib page to the Mollweide sky itself (its own text block is above it)
                    from PIL import Image; im = Image.open(fn); w, h = im.size
                    if (w, h) == (800, 600): im.crop((88, 138, 732, 468)).save(fn, optimize=True)
                except Exception: pass
                rec['sky'] = 'gw/sky/%s.png' % sid; rec['skyFrom'] = name.split('.')[0]
            except Exception as ex: print(' sky failed', sid, ex)
            break
    time.sleep(0.5)

# ---- catalog ------------------------------------------------------------------------------------------------------
allev = jget('https://gwosc.org/eventapi/json/allevents/')['events']
KEEP = ('GWTC-1-confident', 'GWTC-2.1-confident', 'GWTC-3-confident', 'GWTC-4.0', 'GWTC-4.1', 'GWTC-5.0')
best = {}
for key, v in allev.items():
    if v.get('catalog.shortName') not in KEEP or v.get('mass_1_source') is None or v.get('mass_2_source') is None: continue
    n = v['commonName']
    if n not in best or v['version'] >= best[n]['version'] or KEEP.index(v['catalog.shortName']) > KEEP.index(best[n]['catalog.shortName']): best[n] = v
cat = []
for n, v in sorted(best.items(), key=lambda kv: kv[1]['GPS']):
    r = lambda k: round(v[k], 2) if v.get(k) is not None else None
    cat.append([n, r('mass_1_source'), r('mass_2_source'), r('final_mass_source'), r('luminosity_distance'), r('network_matched_filter_snr'), round(v['GPS'], 1), v['catalog.shortName']])
print('catalog mergers with masses', len(cat))

# ---- the first chirp ----------------------------------------------------------------------------------------------
def col(url):
    t, y = [], []
    for ln in get(url).decode().splitlines():
        if ln.startswith('#') or not ln.strip(): continue
        a, b = ln.split()[:2]; a = float(a)
        if 0.25 <= a <= 0.46: t.append(round(a, 5)); y.append(round(float(b), 4))
    return t[::2], y[::2]
B = 'https://gwosc.org/s/events/GW150914/P150914/'
th, oh = col(B + 'fig1-observed-H.txt'); tw, wh = col(B + 'fig1-waveform-H.txt')
chirp = {'name': 'GW150914', 'date': '2015-09-14T09:50:45Z', 'site': 'LIGO HANFORD', 't': th, 'observed': oh, 'model': wh[:len(oh)],
         'units': 'strain x 1e21, whitened and band-passed 35-350 Hz', 'credit': 'LIGO Scientific Collaboration and Virgo, PRL 116, 061102 (2016); GWOSC, CC BY 4.0'}

latest = alerts[0]['t'] if alerts else None
out = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'latestAlert': latest, 'alerts': alerts[:40], 'nSignificant': len(alerts),
       'catalog': cat, 'chirp': chirp,
       'credit': 'LIGO/Virgo/KAGRA public alerts via GraceDB · GWOSC event catalogue (CC BY 4.0)'}
json.dump(out, open(os.path.join(OUT, 'gw.json'), 'w'), separators=(',', ':'))
print('gw.json', os.path.getsize(os.path.join(OUT, 'gw.json')), 'bytes; sky maps', len(os.listdir(os.path.join(OUT, 'sky'))), '; latest alert', latest)

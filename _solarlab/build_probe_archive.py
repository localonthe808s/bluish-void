#!/usr/bin/env python3
"""One-time archive bake: historic probe imagery for the SPACE tab.

Sets (all public-domain NASA mission data; credit recorded per image):
  cassini_finale  Cassini ISS frames 2017-09-13 .. 2017-09-15T10:32Z (OPUS)
  nh_pluto        New Horizons LORRI Pluto/Charon around the 2015-07-14 flyby (OPUS)
  mariner4        Mariner 4 Mars close-ups (NASA Images API)
  mariner10       Mariner 10 Mercury + Venus (NASA Images API)
  junocam         processed JunoCam Jupiter/Io/Ganymede (NASA Images API)
  venera_sites    Magellan radar views of the Venera landing sites (NASA Images API)

OPUS frames are scored before choosing: near-black / flat (calibration, dark) frames are
dropped by mean, spread and lit fraction; near-duplicates by an 8x8 average hash.
NASA Images items whose title/description reads as an illustration, diagram, chart,
animation or spacecraft photo are rejected by keyword.

Writes _solarlab/probes/<set>_NN.webp (long side 640 px, never upsampled, WebP q78,
stepped down to stay < 70 KB) and _solarlab/probes/probes.json.

Idempotent: a set already in probes.json whose files all exist is kept as-is
(pass --force to rebuild, or --force SET to rebuild one set). Scoring thumbnails are
cached in $TMPDIR/probe_bake_cache so a rerun does not refetch them.

usage: build_probe_archive.py [--force [SET ...]]
"""
import io, json, os, re, sys, tempfile, time, hashlib, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageFilter, ImageStat

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'probes'
MANIFEST = OUT / 'probes.json'
CACHE = Path(tempfile.gettempdir()) / 'probe_bake_cache'
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid-bake; +https://bluishvoid.com)'}
OPUS = 'https://opus.pds-rings.seti.org'
NASA = 'https://images-api.nasa.gov'
LONG_SIDE = 640
MAX_BYTES = 70 * 1024

CASSINI_CREDIT = 'NASA/JPL-Caltech/Space Science Institute'
NH_CREDIT = 'NASA/JHUAPL/SwRI'
JPL_CREDIT = 'NASA/JPL'

# Hand review of the contact sheet: ids never to use (blank, calibration, duplicate, not a photo).
EXCLUDE = {
    'PIA01685',   # Mariner 4: the picture shown is the 1999 MGS frame
    'PIA22115',   # Mariner 4: an MRO HiRISE frame
    'PIA14033',   # Mariner 4: hand-coloured number printout, not a photograph
    'nh-lorri-lor_0299179751', 'nh-lorri-lor_0299180427',  # LORRI: readout streaks
    'nh-lorri-lor_0299181458',  # LORRI: smeared to noise
    'co-iss-w1884007257',  # same view as the Saturn frame 99 s earlier
    'PIA02439',   # Mariner 10 Caloris: map with lat/lon axes and labels
}

BAD_WORDS = re.compile(r"\b(illustration|illustrated|artist'?s?|concept|animation|animated|diagram|"
                       r"chart|graph|graphic|rendering|rendered|simulat\w*|model|mockup|"
                       r"spacecraft (?:in|being|undergoing|at)|launch|patch|logo|poster|"
                       r"engineers?|technicians?|team|clean ?room|replica|video|movie)\b", re.I)

_last_req = [0.0]


def fetch(url, tries=5):
    """GET with a 0.3 s politeness gap and exponential backoff."""
    for i in range(tries):
        gap = time.time() - _last_req[0]
        if gap < 0.3:
            time.sleep(0.3 - gap)
        _last_req[0] = time.time()
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            wait = 1.5 * 2 ** i
            print('  retry %d (%s) in %.1fs: %s' % (i + 1, e, wait, url[:100]))
            time.sleep(wait)


def fetch_cached(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    p = CACHE / hashlib.sha1(url.encode()).hexdigest()
    if p.exists() and p.stat().st_size:
        return p.read_bytes()
    b = fetch(url)
    p.write_bytes(b)
    return b


def jget(url):
    return json.loads(fetch(url))


# ---------- image scoring ----------

def stats(im):
    g = im.convert('L')
    g.thumbnail((256, 256))
    st = ImageStat.Stat(g)
    mean, std = st.mean[0], st.stddev[0]
    px = list(g.getdata())
    lit = sum(1 for v in px if v > 30) / len(px)
    sat = sum(1 for v in px if v > 250) / len(px)
    edge = ImageStat.Stat(g.filter(ImageFilter.FIND_EDGES)).mean[0]
    a = g.resize((8, 8), Image.LANCZOS)
    ap = list(a.getdata())
    m = sum(ap) / 64.0
    ahash = sum(1 << i for i, v in enumerate(ap) if v > m)
    return {'mean': mean, 'std': std, 'lit': lit, 'sat': sat, 'edge': edge, 'ahash': ahash}


def usable(s):
    return s['mean'] > 10 and s['std'] > 10 and s['lit'] > 0.04 and s['mean'] < 240 and s['sat'] < 0.6


def ham(a, b):
    return bin(a ^ b).count('1')


def is_dup(s, picked, thr=8, target=None):
    return any(ham(s['ahash'], q['_s']['ahash']) <= thr for q in picked
               if target is None or q.get('target') == target)


def is_grey(im):
    if im.mode in ('L', 'LA', 'I', 'I;16', 'F', '1'):
        return True
    rgb = im.convert('RGB')
    rgb.thumbnail((128, 128))
    r, g, b = rgb.split()
    from PIL import ImageChops
    d1 = ImageStat.Stat(ImageChops.difference(r, g)).mean[0]
    d2 = ImageStat.Stat(ImageChops.difference(g, b)).mean[0]
    return d1 < 2 and d2 < 2


def save_webp(img_bytes, path):
    im = Image.open(io.BytesIO(img_bytes))
    im.load()
    grey = is_grey(im)
    im = im.convert('L' if grey else 'RGB')
    w, h = im.size
    if max(w, h) > LONG_SIDE:
        k = LONG_SIDE / max(w, h)
        im = im.resize((max(1, round(w * k)), max(1, round(h * k))), Image.LANCZOS)
    q = 78
    while True:
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=q, method=6)
        if buf.tell() <= MAX_BYTES or q <= 30:
            break
        q -= 6
    path.write_bytes(buf.getvalue())
    return im.size, buf.tell()


# ---------- OPUS ----------

def opus_rows(params, cols):
    rows, start = [], 1
    while True:
        q = dict(params, cols=','.join(cols), limit=1000, startobs=start)
        d = jget(OPUS + '/api/data.json?' + urllib.parse.urlencode(q))
        rows += [dict(zip(cols, r)) for r in d['page']]
        if len(d['page']) < 1000:
            return rows
        start += 1000


def opus_images(params, size):
    out, start = {}, 1
    while True:
        q = dict(params, limit=1000, startobs=start)
        d = jget(OPUS + '/api/images/%s.json?' % size + urllib.parse.urlencode(q))
        for r in d['data']:
            out[r['opus_id']] = r
        if len(d['data']) < 1000:
            return out
        start += 1000


def opus_candidates(params, cols):
    rows = opus_rows(params, cols)
    med = opus_images(params, 'med')
    full = opus_images(params, 'full')
    for r in rows:
        r['med'] = med.get(r['opusid'], {}).get('url')
        f = full.get(r['opusid'], {})
        r['full'] = f.get('url')
        r['fullw'] = f.get('width') or 0
    return [r for r in rows if r['med'] and r['full'] and r['opusid'] not in EXCLUDE]


def score_all(cands, label):
    print('  scoring %d %s frames' % (len(cands), label))
    for i, c in enumerate(cands):
        try:
            c['_s'] = stats(Image.open(io.BytesIO(fetch_cached(c['med']))))
        except Exception as e:
            print('  skip %s: %s' % (c['opusid'], e))
            c['_s'] = None
        if i and i % 50 == 0:
            print('    %d/%d' % (i, len(cands)))
    return [c for c in cands if c['_s'] and usable(c['_s'])]


def tsec(t):
    return datetime.fromisoformat(t[:19]).replace(tzinfo=timezone.utc).timestamp()


def pick_spread(pool, n, picked, min_gap, key):
    """Greedy best-first by key, with dedupe and a minimum time gap to earlier picks."""
    for c in sorted(pool, key=key, reverse=True):
        if len(picked) >= n:
            break
        if c in picked or is_dup(c['_s'], picked, 10, c['target']):
            continue
        if any(abs(tsec(c['time1']) - tsec(p['time1'])) < min_gap and c['target'] == p['target']
               for p in picked):
            continue
        picked.append(c)
    return picked


def build_cassini():
    cols = ['opusid', 'time1', 'target', 'camera', 'FILTER']
    params = {'instrument': 'Cassini ISS', 'timesec1': '2017-09-13T00:00:00',
              'timesec2': '2017-09-15T10:32:00'}
    good = score_all(opus_candidates(params, cols), 'Cassini')
    q = lambda c: c['_s']['std'] + 3 * c['_s']['edge'] + 20 * min(c['_s']['lit'], 0.5)
    good.sort(key=lambda c: c['time1'])
    picked = []
    # the very last usable frames first
    for c in reversed(good):
        if len(picked) >= 2:
            break
        if not is_dup(c['_s'], picked, 8, c['target']):
            picked.append(c)
    quota = {'Saturn': 6, 'Saturn Rings': 6, 'Enceladus': 4, 'Titan': 3}
    for tgt, n in quota.items():
        have = sum(1 for p in picked if p['target'] == tgt)
        sub = [c for c in good if c['target'] == tgt]
        extra = []
        pick_spread(sub, n - have, extra, 900, q)
        picked += [e for e in extra if not is_dup(e['_s'], picked, 10, e['target'])]
    if len(picked) < 20:
        pick_spread(good, 20, picked, 600, q)
    picked.sort(key=lambda c: c['time1'])
    out = []
    for c in picked:
        cam = 'ISS %s camera, %s filter' % (c['camera'], c['FILTER'])
        out.append(dict(_url=c['full'], title='%s, %s' % (c['target'], c['time1'][:16].replace('T', ' ') + ' UTC'),
                        date=c['time1'][:19] + 'Z', target=c['target'], instrument='Cassini ' + cam,
                        credit=CASSINI_CREDIT,
                        source_url=OPUS + '/#/view=detail&detail=' + c['opusid'],
                        nasa_id_or_opusid=c['opusid']))
    return out


def build_nh():
    cols = ['opusid', 'time1', 'target']
    good = []
    for tgt in ('Pluto', 'Charon'):
        params = {'mission': 'New Horizons', 'instrument': 'New Horizons LORRI', 'target': tgt,
                  'timesec1': '2015-07-13T00:00:00', 'timesec2': '2015-07-15T00:00:00'}
        cands = [c for c in opus_candidates(params, cols) if c['fullw'] >= 1000]
        good += score_all(cands, 'LORRI ' + tgt)
    ca = tsec('2015-07-14T11:49:00')
    # detail first, nudged toward closest approach
    q = lambda c: (c['_s']['std'] + 3 * c['_s']['edge']) * (1.0 + 0.3 * max(0, 1 - abs(tsec(c['time1']) - ca) / 86400))
    picked = []
    pick_spread([c for c in good if c['target'] == 'Charon'], 3, picked, 1800, q)
    pick_spread(good, 12, picked, 1200, q)
    picked.sort(key=lambda c: c['time1'])
    out = []
    for c in picked:
        out.append(dict(_url=c['full'], title='%s, %s' % (c['target'], c['time1'][:16].replace('T', ' ') + ' UTC'),
                        date=c['time1'][:19] + 'Z', target=c['target'], instrument='New Horizons LORRI',
                        credit=NH_CREDIT, source_url=OPUS + '/#/view=detail&detail=' + c['opusid'],
                        nasa_id_or_opusid=c['opusid']))
    return out


# ---------- NASA Images API ----------

def nasa_search(q, pages=2):
    items = []
    for p in range(1, pages + 1):
        d = jget(NASA + '/search?' + urllib.parse.urlencode({'q': q, 'media_type': 'image', 'page': p}))
        its = d['collection']['items']
        items += its
        if len(its) < 100:
            break
    return items


def nasa_asset(href):
    lst = jget(href)
    imgs = [u.replace('http://', 'https://') for u in lst if re.search(r'\.(jpe?g|png)$', u, re.I)]
    for tag in ('~large', '~orig', '~medium'):
        for u in imgs:
            if tag in u:
                return u
    return None


def build_nasa(queries, n, require, target_of, credit_of, instrument, reject=None, picked=None):
    seen, picked = {p['nasa_id_or_opusid'] for p in (picked or [])}, list(picked or [])
    for q in queries:
        for it in nasa_search(q):
            m = it['data'][0]
            nid = m['nasa_id']
            if nid in seen or nid in EXCLUDE:
                continue
            seen.add(nid)
            text = (m.get('title', '') + ' ' + m.get('description', '') + ' ' +
                    ' '.join(m.get('keywords') or []))
            if BAD_WORDS.search(m.get('title', '')) or BAD_WORDS.search(m.get('description', '')[:400]):
                continue
            if not require(m, text) or (reject and reject(m, text)):
                continue
            tgt = target_of(m, text)
            if not tgt:
                continue
            per = sum(1 for p in picked if p['target'] == tgt)
            if per >= n.get(tgt, 0):
                continue
            url = nasa_asset(it['href'])
            if not url:
                continue
            try:
                b = fetch_cached(url)
                s = stats(Image.open(io.BytesIO(b)))
            except Exception as e:
                print('  skip %s: %s' % (nid, e))
                continue
            if not usable(s) or is_dup(s, picked):
                continue
            picked.append(dict(_url=url, _s=s, title=m.get('title', '').strip(),
                               date=m.get('date_created', '')[:19] + 'Z' if m.get('date_created') else None,
                               target=tgt, instrument=instrument, credit=credit_of(m),
                               source_url='https://images.nasa.gov/details/' + urllib.parse.quote(nid),
                               nasa_id_or_opusid=nid))
            if len(picked) >= sum(n.values()):
                return picked
    return picked


def in_text(*ws):
    return lambda m, t: all(w.lower() in t.lower() for w in ws)


def build_mariner4():
    return build_nasa(['mariner 4 mars', 'mariner 4'], {'Mars': 4},
                      lambda m, t: re.search(r'mariner\s*(iv|4)\b', t, re.I) and 'mars' in t.lower(),
                      lambda m, t: 'Mars', lambda m: JPL_CREDIT, 'Mariner 4 TV camera')


def build_mariner10():
    def tgt(m, t):
        tt = m.get('title', '').lower()
        if 'mercury' in tt: return 'Mercury'
        if 'venus' in tt: return 'Venus'
        tl = t.lower()
        if 'mercury' in tl and 'venus' not in tl: return 'Mercury'
        if 'venus' in tl and 'mercury' not in tl: return 'Venus'
        return None
    req = lambda m, t: re.search(r'mariner\s*(x|10)\b', t, re.I)
    rej = lambda m, t: re.search(r'quadrangle|earth and moon|moon north pole', m.get('title', ''), re.I)
    qs = ['mariner 10 venus', 'mariner 10 mercury']
    got = build_nasa(qs, {'Mercury': 4, 'Venus': 4}, req, tgt, lambda m: JPL_CREDIT,
                     'Mariner 10 TV camera', reject=rej)
    # NASA Images holds only one Mariner 10 Venus picture: Mercury fills the rest of the 8
    nv = sum(1 for p in got if p['target'] == 'Venus')
    got = build_nasa(qs, {'Mercury': 8 - nv, 'Venus': nv}, req, tgt, lambda m: JPL_CREDIT,
                     'Mariner 10 TV camera', reject=rej, picked=got)
    return sorted(got, key=lambda p: (p['target'] != 'Mercury', p['nasa_id_or_opusid']))


def build_junocam():
    def tgt(m, t):
        tt = (m.get('title', '') + ' ' + ' '.join(m.get('keywords', []) or [])).lower()
        for k, v in (('ganymede', 'Ganymede'), (' io', 'Io'), ('io ', 'Io'), ('jupiter', 'Jupiter')):
            if k in ' ' + tt + ' ':
                return v
        return None
    def credit(m):
        s = (m.get('secondary_creator') or '').strip()
        return s or 'NASA/JPL-Caltech/SwRI/MSSS'
    # non-commercial licences are skipped so every frame here can be reused freely
    nc = lambda m, t: re.search(r'\bNC\b|non-?commercial', (m.get('secondary_creator') or '') + ' ' + t, re.I)
    return build_nasa(['junocam', 'junocam jupiter', 'junocam io', 'junocam ganymede'],
                      {'Jupiter': 5, 'Io': 2, 'Ganymede': 1},
                      lambda m, t: 'junocam' in t.lower(), tgt, credit, 'Juno JunoCam', reject=nc)


def build_venera():
    return build_nasa(['venera', 'venera landing site magellan'], {'Venus': 6},
                      lambda m, t: re.search(r'venera\s*\d+', m.get('title', ''), re.I) and 'magellan' in t.lower(),
                      lambda m, t: 'Venus', lambda m: JPL_CREDIT, 'Magellan synthetic aperture radar')


SETS = [('cassini_finale', 'cassini_finale', build_cassini),
        ('nh_pluto', 'nh_pluto', build_nh),
        ('mariner4', 'mariner4', build_mariner4),
        ('mariner10', 'mariner10', build_mariner10),
        ('junocam', 'junocam', build_junocam),
        ('venera_sites', 'venera_site', build_venera)]


def main():
    args = sys.argv[1:]
    force = '--force' in args
    only = [a for a in args if not a.startswith('--')]
    OUT.mkdir(parents=True, exist_ok=True)
    man = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {'sets': {}}
    for key, prefix, fn in SETS:
        have = man['sets'].get(key)
        rebuild = force and (not only or key in only)
        if have and not rebuild and all((OUT / e['file']).exists() for e in have):
            print('%s: kept %d (already baked)' % (key, len(have)))
            continue
        print('%s: building' % key)
        try:
            items = fn()
        except Exception as e:
            print('  FAILED: %s' % e)
            continue
        # files are rewritten from the (cached) sources so names always match the manifest
        for f in OUT.glob(prefix + '_*.webp'):
            f.unlink()
        entries = []
        for i, it in enumerate(items, 1):
            name = '%s_%02d.webp' % (prefix, i)
            path = OUT / name
            try:
                save_webp(fetch_cached(it['_url']), path)
            except Exception as e:
                print('  skip %s: %s' % (it['nasa_id_or_opusid'], e))
                continue
            e = {k: v for k, v in it.items() if not k.startswith('_')}
            entries.append(dict(file=name, **e))
        man['sets'][key] = entries
        print('  %s: %d images' % (key, len(entries)))
    man['built'] = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    man['sets'] = {k: man['sets'].get(k, []) for k, _, _ in SETS}
    MANIFEST.write_text(json.dumps({'built': man['built'], 'sets': man['sets']}, indent=1, ensure_ascii=False))
    tot = sum(f.stat().st_size for f in OUT.glob('*.webp'))
    print('\nSUMMARY')
    for k, v in man['sets'].items():
        print('  %-15s %3d' % (k, len(v)))
    print('  total %d files, %.1f KB' % (len(list(OUT.glob('*.webp'))), tot / 1024))


if __name__ == '__main__':
    main()

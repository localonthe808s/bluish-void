#!/usr/bin/env python3
"""Bake what the great observatories are doing, for the SPACE tab's OBSERVATORIES NOW
row and EARTH VIEW (user 2026-09-23: "build all of it").

None of these sources can be read by the page directly -- STScI's schedule files and
JPL Horizons send no CORS headers -- so a scheduled Action runs this and commits small
files the page reads from its own origin.

Writes:
  observatories.json        Webb's published observing schedule (the newest week), Roman's
                            range + NASA's Roman mission-blog posts,
                            what Hubble and Webb observed in the last ~2 days (NASA MAST),
                            Parker Solar Probe's distance/speed series + perihelia
  _solarlab/_roman.js       Roman's delivered trajectory, launch -> end of the current
                            Horizons solution (same schema the EARTH VIEW already reads)
  _solarlab/_l2craft.js     JWST (-170) and Euclid (-680) geocentric ecliptic positions,
                            6-hourly, a week back to four months ahead

Every source is US-government / public domain (NASA, STScI for NASA, JPL). MAST's own
quick-look JPEGs were tried and dropped: they are raw detector frames (noise, chip gaps,
stripes) and read as broken next to the event cards' renders.

usage: build_observatories.py
"""
import datetime as dt, json, math, re, sys, time, urllib.parse, urllib.request

# a sentence ends at . ! ? -- but not after an initial ("Vera C. Rubin") or an abbreviation ("U.S.")
SENT = re.compile(r'(?<![\s.][A-Z]\.)(?<!\bSt\.)(?<!\bDr\.)(?<=[.!?])\s+(?=[A-Z\u201c"(])')


def first_sentence(t, cap=480):
    return (SENT.split(t) or [''])[0][:cap]
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UA = {'User-Agent': 'bluishvoid-bake (+https://bluishvoid.com)'}
NOW = dt.datetime.now(dt.timezone.utc)


def get(url, data=None, timeout=120, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            return urllib.request.urlopen(req, timeout=timeout).read()
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(10 * (i + 1))


def ms(d): return int(d.timestamp() * 1000)


# ── JPL HORIZONS ─────────────────────────────────────────────────────────────
def horizons(cmd, center, start, stop, step):
    """[(datetime, x, y, z, vx, vy, vz)] ecliptic J2000, km and km/s; or raises with
    Horizons' own message (it names the end of a spacecraft's solution)."""
    p = {'format': 'json', 'COMMAND': "'%s'" % cmd, 'OBJ_DATA': 'NO', 'MAKE_EPHEM': 'YES',
         'EPHEM_TYPE': 'VECTORS', 'CENTER': "'%s'" % center, 'START_TIME': "'%s'" % start,
         'STOP_TIME': "'%s'" % stop, 'STEP_SIZE': "'%s'" % step, 'REF_PLANE': 'ECLIPTIC',
         'VEC_TABLE': '2', 'OUT_UNITS': 'KM-S', 'CSV_FORMAT': 'YES', 'TIME_TYPE': 'UT'}
    t = json.loads(get('https://ssd.jpl.nasa.gov/api/horizons.api?' + urllib.parse.urlencode(p)))['result']
    s, e = t.find('$$SOE'), t.find('$$EOE')
    if s < 0: raise RuntimeError(t[-600:])
    out = []
    for line in t[s + 5:e].strip().split('\n'):
        c = [x.strip() for x in line.split(',')]
        when = dt.datetime.strptime(c[1].replace('A.D. ', '')[:20], '%Y-%b-%d %H:%M:%S').replace(tzinfo=dt.timezone.utc)
        out.append((when,) + tuple(float(v) for v in c[2:8]))
    return out


def solution_end(cmd, center, start):
    """Horizons refuses past a spacecraft's delivered solution and says where it ends."""
    try:
        horizons(cmd, center, start, (NOW + dt.timedelta(days=400)).strftime('%Y-%m-%d'), '10d')
        return NOW + dt.timedelta(days=400)
    except RuntimeError as err:
        m = re.search(r'after A\.D\. (\d{4}-[A-Z]{3}-\d{2} \d{2}:\d{2})', str(err))
        if not m: raise
        return dt.datetime.strptime(m.group(1).title(), '%Y-%b-%d %H:%M').replace(tzinfo=dt.timezone.utc)


def lon_km(r):
    x, y = r[1], r[2]
    return [round(math.degrees(math.atan2(y, x)) % 360, 3), round(math.hypot(x, y), 1)]


def bake_roman():
    """Same schema as the 09-07 hand bake: hourly [ecliptic lon deg, in-plane range km]
    from the first whole hour after launch to the end of the current solution."""
    launch = dt.datetime(2026, 8, 30, 11, 26, 4, tzinfo=dt.timezone.utc)
    t0 = dt.datetime(2026, 8, 30, 12, 0, tzinfo=dt.timezone.utc)
    end = solution_end('-211', '500@399', t0.strftime('%Y-%m-%d %H:%M')) - dt.timedelta(hours=1)
    rows = horizons('-211', '500@399', t0.strftime('%Y-%m-%d %H:%M'), end.strftime('%Y-%m-%d %H:%M'), '1h')
    R = {'src': 'JPL Horizons, target -211, geocentric ecliptic vectors', 'launch': ms(launch),
         'built': NOW.strftime('%Y-%m-%d'), 'solution_end': ms(rows[-1][0]),
         't0': ms(rows[0][0]), 'step': 3600000, 'n': len(rows), 'p': [lon_km(r) for r in rows]}
    (ROOT / '_solarlab/_roman.js').write_text('window.ROMAN = ' + json.dumps(R, separators=(',', ':')) + ';\n')
    return len(rows), rows[-1][0]


def bake_l2():
    start = (NOW - dt.timedelta(days=7)).replace(minute=0, second=0, microsecond=0)
    stop = start + dt.timedelta(days=127)
    out = {'src': 'JPL Horizons, geocentric ecliptic vectors', 'built': NOW.strftime('%Y-%m-%d')}
    for key, cmd in (('jwst', '-170'), ('euclid', '-680')):
        rows = horizons(cmd, '500@399', start.strftime('%Y-%m-%d %H:%M'), stop.strftime('%Y-%m-%d %H:%M'), '6h')
        out[key] = {'t0': ms(rows[0][0]), 'step': 6 * 3600000, 'n': len(rows), 'p': [lon_km(r) for r in rows]}
    (ROOT / '_solarlab/_l2craft.js').write_text('window.L2CRAFT = ' + json.dumps(out, separators=(',', ':')) + ';\n')


def bake_parker():
    """Heliocentric distance (AU) and speed (km/s), 3-hourly, two days back to 150 ahead;
    perihelia are the local minima, refined to the hour."""
    AU = 149597870.7
    start = (NOW - dt.timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    rows = horizons('-96', '500@10', start.strftime('%Y-%m-%d %H:%M'),
                    (start + dt.timedelta(days=152)).strftime('%Y-%m-%d %H:%M'), '3h')
    ser = [[round(math.sqrt(r[1]**2 + r[2]**2 + r[3]**2) / AU, 5),
            round(math.sqrt(r[4]**2 + r[5]**2 + r[6]**2), 2)] for r in rows]
    peri = []
    for i in range(1, len(ser) - 1):
        if ser[i][0] < 0.2 and ser[i][0] <= ser[i - 1][0] and ser[i][0] < ser[i + 1][0]:
            c = rows[i][0]
            fine = horizons('-96', '500@10', (c - dt.timedelta(hours=4)).strftime('%Y-%m-%d %H:%M'),
                            (c + dt.timedelta(hours=4)).strftime('%Y-%m-%d %H:%M'), '10m')
            best = min(fine, key=lambda r: r[1]**2 + r[2]**2 + r[3]**2)
            peri.append({'t': ms(best[0]), 'au': round(math.sqrt(best[1]**2 + best[2]**2 + best[3]**2) / AU, 5),
                         'kms': round(math.sqrt(best[4]**2 + best[5]**2 + best[6]**2), 1)})
    return {'src': 'JPL Horizons, target -96, heliocentric', 't0': ms(rows[0][0]), 'step': 3 * 3600000,
            'n': len(ser), 's': ser, 'perihelia': peri}


# ── WEBB: STScI's published observing schedule ───────────────────────────────
SCHED_IDX = 'https://www.stsci.edu/jwst/science-execution/observing-schedules'


def bake_webb_schedule():
    idx = get(SCHED_IDX).decode('utf-8', 'replace')
    links = sorted(set(re.findall(r'href="([^"]*_documents/(\d{8})_report_\d{8}\.txt)"', idx)), key=lambda x: x[1])
    if not links: raise RuntimeError('no schedule links on the index page')
    href, week = links[-1]
    url = href if href.startswith('http') else 'https://www.stsci.edu' + href
    txt = get(url).decode('utf-8', 'replace').split('\n')
    hi = next(i for i, l in enumerate(txt) if l.startswith('VISIT ID'))
    dashes = txt[hi + 1]
    spans = [(m.start(), m.end()) for m in re.finditer(r'-+', dashes)]
    names = [txt[hi][a:b + 2].strip() for a, b in spans]
    rows = []
    for line in txt[hi + 2:]:
        if not line.strip(): continue
        f = {names[k]: line[a:(spans[k + 1][0] if k + 1 < len(spans) else len(line))].strip() for k, (a, b) in enumerate(spans)}
        vt, start = f.get('VISIT TYPE', ''), f.get('SCHEDULED START TIME', '')
        if not vt.startswith('PRIME') or not re.match(r'\d{4}-\d\d-\d\dT', start): continue
        d = re.match(r'(\d+)/(\d+):(\d+):(\d+)', f.get('DURATION', ''))
        dur = (int(d[1]) * 86400 + int(d[2]) * 3600 + int(d[3]) * 60 + int(d[4])) if d else 0
        t = dt.datetime.strptime(start, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=dt.timezone.utc)
        rows.append({'t': ms(t), 'dur': dur, 'inst': f.get('SCIENCE INSTRUMENT AND MODE', ''),
                     'target': f.get('TARGET NAME', ''), 'cat': f.get('CATEGORY', ''),
                     'kw': f.get('KEYWORDS', ''), 'visit': f.get('VISIT ID', '')})
    if len(rows) < 5: raise RuntimeError('schedule parsed to %d rows' % len(rows))
    rows.sort(key=lambda r: r['t'])
    return {'src': url, 'page': SCHED_IDX, 'week': week, 'start': rows[0]['t'],
            'end': max(r['t'] + r['dur'] * 1000 for r in rows), 'rows': rows}


# ── NASA MAST: what Hubble and Webb observed lately ──────────────────────────
def mast(coll, days=2):
    now_mjd = time.time() / 86400 + 40587
    req = {'service': 'Mast.Caom.Filtered', 'format': 'json', 'pagesize': 3000, 'page': 1,
           'params': {'columns': 'instrument_name,target_name,t_min,t_exptime,obs_id,jpegURL,dataRights,'
                                 'target_classification,obs_title,proposal_id,filters',
                      'filters': [{'paramName': 'obs_collection', 'values': [coll]},
                                  {'paramName': 'intentType', 'values': ['science']},
                                  {'paramName': 't_min', 'values': [{'min': now_mjd - days, 'max': now_mjd + 1}]}]}}
    j = json.loads(get('https://mast.stsci.edu/api/v0/invoke',
                       data=urllib.parse.urlencode({'request': json.dumps(req)}).encode(), timeout=180))
    if j.get('status') != 'COMPLETE': raise RuntimeError('MAST %s: %s' % (coll, j.get('msg')))
    return j['data']


def mjd_ms(m): return int((m - 40587) * 86400000)


def bake_mast(coll):
    rows = mast(coll)
    newest = {}
    for r in rows:                                  # one line per target: its latest visit
        k = r['target_name']
        if k not in newest or r['t_min'] > newest[k]['t_min']: newest[k] = r
    items = sorted(newest.values(), key=lambda r: -r['t_min'])[:14]
    out = []
    for r in items:
        it = {'target': r['target_name'], 'inst': r['instrument_name'], 't': mjd_ms(r['t_min']),
              'title': (r['obs_title'] or '').strip(), 'cls': r['target_classification'] or '',
              'prop': r['proposal_id'], 'public': r['dataRights'] == 'PUBLIC'}
        out.append(it)
    return {'n_obs': len(rows), 'n_targets': len(newest), 'newest': mjd_ms(max(r['t_min'] for r in rows)) if rows else None,
            'items': out}


# ── WHY: each programme's own abstract (user 2026-09-24: "could you add a reason/purpose") ──
# STScI publishes every Hubble and Webb programme as a PDF with an ABSTRACT section written by
# the proposers. The card quotes the sentence that states the aim, VERBATIM -- their words, not
# ours -- plus the category (GO = science, CAL = calibration, ...). Cached by programme id in
# observatories.json, so each PDF is fetched once. Results are not a thing we can show: these
# observations are hours old; findings come out in papers months or years later.
AIM_RX = re.compile(r'\b(we (?:propose|seek|will|aim|request|plan|use|intend)|this (?:program|proposal|project) (?:will|aims|is designed|seeks)|here we|our goal|the goal of|in order to|to (?:measure|determine|test|search|study|characteri[sz]e|map|constrain|monitor|detect|obtain|image|calibrate|track))', re.I)


def program_pdf(obs, pid):
    kind = 'jwst' if obs == 'JWST' else 'hst'
    return 'https://www.stsci.edu/%s-program-info/download/%s/pdf/%s/' % (kind, kind, pid)


def program_page(obs, pid):
    return ('https://www.stsci.edu/jwst/science-execution/program-information?id=%s' % pid if obs == 'JWST'
            else 'https://www.stsci.edu/hst-program-info/program/?program=%s' % pid)


def fetch_abstract(obs, pid):
    import io as _io
    from pypdf import PdfReader
    raw = get(program_pdf(obs, pid), timeout=60, tries=2)
    rd = PdfReader(_io.BytesIO(raw))
    pages = [(pg.extract_text() or '') for pg in rd.pages[:12]]
    t = '\n'.join(pages)
    cat = re.search(r'Proposal Category:\s*([A-Z/]+)', t)
    i = t.find('ABSTRACT')
    if i < 0: return {'cat': cat.group(1) if cat else '', 'aim': ''}
    # Some PDFs interleave the visit table with the abstract (HST 17734): keep prose lines only.
    TABLE = re.compile(r'\d{2}-[A-Z][a-z]{2}-\d{4}|^\s*\d{1,3} \(\d+\)|^\s*(?:(?:COS|STIS|WFC3|ACS|NICMOS|FGS|NIRCAM|NIRSPEC|MIRI|NIRISS)/\S+\s*)+$|^Visit|^with Visit|Proposal \d+ \(STScI|^\s*\d+\s*$|^Name Institution|\(PI\)|\(CoI\)', re.I)
    keep = []
    for ln in t[i + 8:].split('\n'):
        if re.match(r'\s*(?:OBSERVING DESCRIPTION|OBSERVATION SUMMARY|TARGETS|SCIENTIFIC JUSTIFICATION|Observing Description)\b', ln): break
        if TABLE.search(ln) or not ln.strip(): continue
        keep.append(ln.strip())
    body = re.sub(r'\s+', ' ', ' '.join(keep)).strip()
    sents = re.split(r'(?<=[.!?])\s+(?=[A-Z(])', body)
    aim = next((x for x in sents if AIM_RX.search(x)), sents[0] if sents else '')
    return {'cat': cat.group(1) if cat else '', 'aim': aim.strip()[:420]}


def attach_aims(out, prev):
    cache = dict(prev.get('aims') or {})
    want = []
    for key, obs in (('hubble_obs', 'HST'), ('webb_obs', 'JWST')):
        for it in (out.get(key) or {}).get('items', []):
            if it.get('prop'): want.append((obs, str(it['prop'])))
    for r in (out.get('webb') or {}).get('rows', []):
        m = re.match(r'(\d+):', r.get('visit', ''))
        if m and r['t'] + r['dur'] * 1000 > ms(NOW) - 86400000: want.append(('JWST', m.group(1)))
    fetched = 0
    for obs, pid in dict.fromkeys(want):
        k = obs + ':' + pid
        if k in cache or fetched >= 40: continue
        try:
            cache[k] = fetch_abstract(obs, pid); fetched += 1
        except Exception as e:
            print('  abstract failed', k, e)
        cache.setdefault(k, {'cat': '', 'aim': ''})
        cache[k]['page'] = program_page(obs, pid)
    for k in cache: cache[k].setdefault('page', program_page(*k.split(':')))
    out['aims'] = cache
    print('aims cached', len(cache), 'fetched', fetched)


# ── ROMAN: where it is and what the mission team says (user 2026-09-24: "add a 4th spot for roman updates") ──
ROMAN_BLOG = 'https://science.nasa.gov/blogs/roman/feed/'


def bake_roman_card():
    """Distance from Earth (true 3-D range, 6-hourly across the delivered solution) and the
    newest posts from NASA's Roman mission blog -- titles and the lead sentence verbatim."""
    import html as _h
    launch = dt.datetime(2026, 8, 30, 11, 26, 4, tzinfo=dt.timezone.utc)
    end = solution_end('-211', '500@399', '2026-08-30 12:00') - dt.timedelta(hours=1)
    start = max(launch + dt.timedelta(hours=1), NOW - dt.timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    out = {'launch': ms(launch), 'arrive_approx': ms(dt.datetime(2026, 11, 30, 11, 26, tzinfo=dt.timezone.utc)),
           'solution_end': ms(end), 'blog': 'https://science.nasa.gov/mission/roman-space-telescope/'}
    if start < end:
        rows = horizons('-211', '500@399', start.strftime('%Y-%m-%d %H:%M'), end.strftime('%Y-%m-%d %H:%M'), '6h')
        out['range'] = {'t0': ms(rows[0][0]), 'step': 6 * 3600000, 'n': len(rows),
                        'km': [round(math.sqrt(r[1]**2 + r[2]**2 + r[3]**2)) for r in rows],
                        'kms': [round(math.sqrt(r[4]**2 + r[5]**2 + r[6]**2), 3) for r in rows]}
    x = get(ROMAN_BLOG).decode('utf-8', 'replace')
    posts = []
    for it in re.findall(r'<item>(.*?)</item>', x, re.S)[:5]:
        g = lambda t: (re.search(r'<%s>(.*?)</%s>' % (t, t), it, re.S) or [None, ''])[1]
        desc = _h.unescape(re.sub(r'<[^>]+>', '', g('description').replace('<![CDATA[', '').replace(']]>', '')))
        desc = re.sub(r'\s+', ' ', desc).strip()
        lead = first_sentence(desc)
        try: when = ms(dt.datetime.strptime(g('pubDate').strip()[:25], '%a, %d %b %Y %H:%M:%S'))
        except Exception: when = None
        posts.append({'title': _h.unescape(re.sub(r'<[^>]+>', '', g('title'))).strip(), 'link': g('link').strip(),
                      't': when, 'lead': lead})
    if not posts: raise RuntimeError('no Roman blog posts parsed')
    out['posts'] = posts
    return out


# ── PHOTOS + NEWS per observatory (user 2026-09-24: "add a tab ... for their latest photos
#    and maybe another tab for latest news") ──────────────────────────────────────────────
# NASA's mission blogs (public domain; each post's own lead image) and ESA/Webb's image and
# release feeds (CC BY 4.0 -- the credit travels with every picture). Titles and lead
# sentences verbatim.
# Per-source credit and licence. ESA's own site (Euclid) is CC BY-SA 3.0 IGO; NOIRLab (Rubin) is
# CC BY 4.0 like ESA/Webb; NASA is public domain.
SRC = {'nasa':    {'from': 'NASA',     'credit': 'NASA',                  'lic': 'public domain'},
       'esa':     {'from': 'ESA/Webb', 'credit': 'ESA/Webb, NASA & CSA',  'lic': 'CC BY 4.0'},
       'esaint':  {'from': 'ESA',      'credit': 'ESA/Euclid/Euclid Consortium/NASA', 'lic': 'CC BY-SA 3.0 IGO'},
       'noirlab': {'from': 'NOIRLab',  'credit': 'NSF\u2013DOE Vera C. Rubin Observatory/NOIRLab/SLAC/AURA', 'lic': 'CC BY 4.0'}}
# NOIRLab's feeds cover all of its telescopes and its outreach: Rubin items only, and no event photos
RUBIN_ONLY = re.compile(r'\brubin\b', re.I)
NOT_RUBIN_SKY = re.compile(r'visitor|activit|colou?ring|workshop|panel|celebrat|graduat|recognition|career|student|school|outreach|construction|summit road|dome|mirror|camera|lsstcam', re.I)
EUCLID_FEED = 'https://www.esa.int/rssfeed/Science_Exploration/Space_Science/Euclid'
FEEDS = {
    'webb':   {'photos': [('esa', 'https://esawebb.org/images/feed/')],
               'news':   [('nasa', 'https://science.nasa.gov/blogs/webb/feed/'), ('esa', 'https://esawebb.org/news/feed/')]},
    'hubble': {'photos': [('nasa', 'https://science.nasa.gov/category/missions/hubble/feed/')],
               'news':   [('nasa', 'https://science.nasa.gov/category/missions/hubble/feed/')]},
    'roman':  {'photos': [('nasa', 'https://science.nasa.gov/blogs/roman/feed/')],
               'news':   [('nasa', 'https://science.nasa.gov/blogs/roman/feed/')]},
    'parker': {'photos': [('nasa', 'https://science.nasa.gov/blogs/parker-solar-probe/feed/')],
               'news':   [('nasa', 'https://science.nasa.gov/blogs/parker-solar-probe/feed/')]},
    # added 2026-09-24 (user: "add them"): Euclid, Rubin, SPHEREx, Chandra, Voyager
    'euclid':  {'photos': [('esaint', EUCLID_FEED)], 'news': [('esaint', EUCLID_FEED)]},
    'rubin':   {'photos': [('noirlab', 'https://noirlab.edu/public/images/feed/'), ('noirlab', 'https://noirlab.edu/public/news/feed/')],
                'news':   [('noirlab', 'https://noirlab.edu/public/news/feed/')]},
    'spherex': {'photos': [('nasa', 'https://science.nasa.gov/category/missions/spherex/feed/')],
                'news':   [('nasa', 'https://science.nasa.gov/category/missions/spherex/feed/')]},
    'chandra': {'photos': [('nasa', 'https://science.nasa.gov/category/missions/chandra/feed/')],
                'news':   [('nasa', 'https://science.nasa.gov/category/missions/chandra/feed/')]},
    # Voyager takes no new pictures (its cameras were switched off in 1990): news only
    'voyager': {'photos': [], 'news': [('nasa', 'https://science.nasa.gov/blogs/voyager/feed/')]},
}


def _items(url):
    import html as _h
    x = get(url).decode('utf-8', 'replace')
    out = []
    for it in re.findall(r'<item>(.*?)</item>', x, re.S)[:12]:
        g = lambda t: re.sub(r'^\s*<!\[CDATA\[(.*)\]\]>\s*$', r'\1', (re.search(r'<%s>(.*?)</%s>' % (t, t), it, re.S) or [None, ''])[1], flags=re.S)
        raw = g('description') + g('content:encoded')
        raw = raw.replace('<![CDATA[', '').replace(']]>', '')
        rawu = _h.unescape(raw)
        img = re.search(r'<img[^>]+src="([^"]+)"', raw) or re.search(r'<img[^>]+src="([^"]+)"', rawu)
        tag = re.search(r'<img[^>]*>', rawu)
        alt = re.search(r'alt="([^"]*)"', tag.group(0)) if tag else None
        enc = re.search(r'<enclosure[^>]+url="([^"]+)"', it)
        txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', rawu)).strip()
        lead = first_sentence(txt)
        cr = re.search(r'Credit[s]?:\s*([^\n<]{3,160}?)(?:\s{2,}|$|\[|\. )', txt)
        try:
            pd = g('pubDate').strip()
            when = ms(dt.datetime.strptime(pd[:25], '%a, %d %b %Y %H:%M:%S'))
            z = re.search(r'([+-])(\d\d)(\d\d)$', pd)          # ESA stamps +0200: honour the offset
            if z: when -= (1 if z.group(1) == '+' else -1) * (int(z.group(2)) * 60 + int(z.group(3))) * 60000
        except Exception: when = None
        out.append({'title': _h.unescape(re.sub(r'<[^>]+>', '', g('title'))).strip(), 'link': g('link').strip(), 't': when,
                    'lead': lead, 'img': (enc.group(1) if enc else (img.group(1) if img else '')), 'credit': cr.group(1).strip() if cr else '',
                    'alt': alt.group(1) if alt else '', 'desc': txt[:600]})
    return out


def _thumb(src, img):
    # animated GIFs ignore ?w= and run to 3-8 MB (measured 2026-09-24): never on a card
    if not img or re.search(r'\.gif(?:\?|$)', img, re.I): return ''
    # a post that only carries the agency logo has no photo to show
    if re.search(r'meatball|logo|insignia|nasa-worm', img, re.I): return ''
    if src == 'esa':
        m = re.search(r'/archives/images/[^/]+/([^/?]+)\.(?:jpg|png|tif)', img)
        return 'https://cdn.esawebb.org/archives/images/thumb300y/%s.jpg' % m.group(1) if m else img
    if src == 'noirlab':
        m = re.search(r'/archives/images/[^/]+/([^/?]+)\.(?:jpg|png|tif)', img)
        return 'https://storage.noirlab.edu/media/archives/images/thumb300y/%s.jpg' % m.group(1) if m else img
    if src == 'esaint': return img
    return re.sub(r'\?.*$', '', img).replace(' ', '%20') + '?w=640'


# ONLY DEEP SPACE AND DATA (user 2026-09-24: "dont show rockets and take offs, i only want deep
# space and data analysis / visuals"). Anything that reads as the mission rather than the sky is
# dropped; NASA's blog images must also name a science subject, because those blogs mix launch,
# hardware and team photos in with the science. ESA/Webb's image feed is science by construction.
NOT_SKY = re.compile(r'launch|rocket|falcon|booster|lift-?off|launch ?pad|clean ?room|technician|engineer|\bcrew\b|\bteam\b|'
                     r'ceremony|briefing|amendment|\broses\b|solicitation|funding|proposals? due|landing|install|assembl|integrat|deploy|antenna|visor|hardware|thermal protection|'
                     r'\btps\b|heat shield|fitting|spacecraft|mission control|logo|meatball|insignia|astronaut|facility|'
                     r'trajectory animation|mid-course|artist.s (?:concept|illustration|rendering) of (?:the )?(?:roman|parker|webb|hubble)', re.I)
IS_SKY = re.compile(r'galax|nebula|cluster|supernova|\bstars?\b|stellar|planet|exoplanet|\bmoons?\b|jupiter|saturn|uranus|neptune|'
                    r'comet|asteroid|kuiper|\bsun\b|solar wind|corona|\bcme\b|wispr|flare|spectr|light curve|\bdata\b|chart|graph|'
                    r'\bplot\b|\bmap\b|visuali|simulat|deep field|universe|cosmic|\bdust\b|black hole|quasar|lens|potm|infrared|'
                    r'x-ray|ultraviolet|protostar|disk|jet\b|remnant|dwarf|milky way|heliosphere|magnetic', re.I)


def _is_sky(src, it):
    if src == 'noirlab':
        blob = it.get('title', '') + ' ' + it.get('desc', '')
        if not RUBIN_ONLY.search(blob) or NOT_RUBIN_SKY.search(it.get('title', '') + ' ' + it.get('alt', '')): return False
    words = ' '.join([it.get('alt', ''), it.get('title', ''), it.get('img', ''), it.get('desc', '')[:300]])
    if NOT_SKY.search(it.get('alt', '') + ' ' + it.get('img', '') + ' ' + it.get('title', '')): return False
    # a NASA mission blog's illustrations are of the SPACECRAFT (e.g. Parker drawn against the Sun)
    if src == 'nasa' and re.search(r'illustrat|artist|concept|swingby|closeup|rendering', it.get('alt', '') + ' ' + it.get('img', ''), re.I): return False
    return src == 'esa' or bool(IS_SKY.search(words))


_HASH = {}


def _same_picture(th, kept):
    h = _HASH.get(th)
    return h is not None and any(_HASH.get(k) is not None and bin(h ^ _HASH[k]).count('1') <= 6 for k in kept)


def _looks_like_sky(th):
    """The picture itself: a text slide or banner is not the sky. Drops images wider than 3:1
    and near-white, colourless ones (measured on the "Hubble vs. Roman" quote card, 2026-09-24)."""
    try:
        import io as _io
        from PIL import Image, ImageStat
        im = Image.open(_io.BytesIO(get(th, timeout=40, tries=2))).convert('RGB')
        w, h = im.size
        if w > 3 * h or h > 3 * w: return False
        g = im.convert('L').resize((8, 8))
        px = list(g.getdata()); avg = sum(px) / 64
        _HASH[th] = sum(1 << i for i, v in enumerate(px) if v > avg)
        im.thumbnail((96, 96))
        st = ImageStat.Stat(im)
        mean = sum(st.mean) / 3
        spread = sum(st.stddev) / 3
        return not (mean > 200 and spread < 45)
    except Exception as e:
        print('  thumb check failed', th[:80], e)
        return True


def esa_lead(url):
    import html as _h
    x = get(url, timeout=40, tries=2).decode('utf-8', 'replace')
    for p in re.findall(r'<p[^>]*>(.*?)</p>', x, re.S):
        t = re.sub(r'\s+', ' ', _h.unescape(re.sub(r'<[^>]+>', '', p))).strip()
        if len(t) > 80:
            t = re.sub(r'^Video:\s*[\d:]+\s*', '', t)          # an ESA video page opens with its running time
            if len(t) < 60: continue
            return first_sentence(t)
    return ''


def bake_media():
    out = {}
    for key, f in FEEDS.items():
        photos, news, seen = [], [], set()
        for src, url in f['photos']:
            for it in _items(url):
                th = _thumb(src, it['img'])
                if not th or th in seen or it['title'] in seen or not _is_sky(src, it) or not _looks_like_sky(th): continue
                if _same_picture(th, [p['thumb'] for p in photos]): continue
                seen.add(th); seen.add(it['title'])      # ESA posts a release's image and its video under one title
                photos.append({'thumb': th, 'title': it['title'], 'link': it['link'], 't': it['t'],
                               'credit': it['credit'] or SRC[src]['credit'], 'lic': SRC[src]['lic']})
        for src, url in f['news']:
            for it in _items(url):
                if src == 'noirlab' and not RUBIN_ONLY.search(it['title'] + ' ' + it['desc']): continue
                news.append({'title': it['title'], 'link': it['link'], 't': it['t'], 'lead': it['lead'],
                             'from': SRC[src]['from'], 'src': src})
        news = sorted({n['link']: n for n in news}.values(), key=lambda n: -(n['t'] or 0))
        news = list({n['title']: n for n in reversed(news)}.values())[::-1][:5]   # one per title, the newest
        for n in news:                    # ESA's feed carries only a picture: the lead is the article's first paragraph
            n['lead'] = re.sub(r'^Video:\s*[\d:]+\s*', '', n['lead'])      # an ESA video item opens with its running time
            if n.pop('src', '') == 'esaint' and len(n['lead']) < 60:
                try: n['lead'] = esa_lead(n['link'])
                except Exception as e: print('  esa lead failed', n['link'][-60:], e)
        photos = sorted(photos, key=lambda n: -(n['t'] or 0))[:6]
        out[key] = {'photos': photos, 'news': news}
        print('  media', key, len(photos), 'photos', len(news), 'news')
    return out


# ── CHANDRA: the CXC short-term schedule (the week's plan, public, fixed-width) ────────────
CXO_SCHED = 'https://cxc.harvard.edu/target_lists/stscheds/'


def cxo_abstract(obsid):
    """Proposal title + the aim sentence of its abstract, from the Chandra Data Archive."""
    import html as _h
    x = get('https://cda.harvard.edu/srservices/propAbstract.do?obsid=%s' % obsid, timeout=40, tries=2).decode('latin-1')
    t = re.sub(r'\s+', ' ', _h.unescape(re.sub(r'<[^>]+>', ' ', x))).strip()
    title = re.search(r'Proposal Title:\s*(.+?)\s+Proposal Number:', t)
    pi = re.search(r'Principal Investigator:\s*(.+?)\s+Abstract:', t)
    ab = (re.search(r'Abstract:\s*(.+)$', t) or [None, ''])[1].strip()
    sents = re.split(r'(?<=[.!?])\s+(?=[A-Z(])', ab)
    aim = next((x for x in sents if AIM_RX.search(x)), sents[0] if sents else '')
    return {'title': title.group(1).strip() if title else '', 'pi': pi.group(1).strip() if pi else '', 'aim': aim.strip()[:420],
            'page': 'https://cda.harvard.edu/chaser/startViewer.do?menuItem=details&obsid=%s' % obsid}


def bake_chandra(prev):
    import html as _h
    x = get(CXO_SCHED).decode('latin-1')
    week = re.search(r'<H4[^>]*>\s*([A-Z]{3}\d{4}[A-Z]?)\s*</H4>', x, re.I)
    pre = re.search(r'<pre id="schedule">(.*?)(?:</pre>|<!--\s*END|<H4|$)', x, re.S | re.I)   # the page never closes its <pre>
    if not pre: raise RuntimeError('no schedule block')
    L = _h.unescape(re.sub(r'<[^>]+>', '', pre.group(1))).split('\n')
    hi = next(i for i, l in enumerate(L) if l.startswith('Seq #'))
    spans = [(m.start(), m.end()) for m in re.finditer(r'-+', L[hi + 1])]
    rows = []
    for ln in L[hi + 2:]:
        if not ln.strip(): continue
        c = [ln[a:(spans[k + 1][0] if k + 1 < len(spans) else len(ln))].strip() for k, (a, b) in enumerate(spans)]
        m = re.match(r'(\d{4}):(\d{3}):(\d\d):(\d\d):(\d\d)', c[5])
        if not m: continue
        t = dt.datetime(int(m[1]), 1, 1, int(m[3]), int(m[4]), int(m[5]), tzinfo=dt.timezone.utc) + dt.timedelta(days=int(m[2]) - 1)
        try: ks = float(c[6])
        except ValueError: ks = 0
        rows.append({'t': ms(t), 'ks': ks, 'target': c[4], 'obsid': c[2], 'si': c[7] if c[7] != '--' else '',
                     'grat': c[8] if c[8] not in ('--', 'NONE') else '', 'too': c[1] in ('TOO', 'DDT'), 'cal': c[4].startswith('CAL-')})
    if len(rows) < 5: raise RuntimeError('schedule parsed to %d rows' % len(rows))
    rows.sort(key=lambda r: r['t'])
    # abstracts for the science rows around now (cached by ObsID across bakes)
    cache = dict((prev.get('chandra') or {}).get('abs') or {})
    now = ms(NOW)
    near = [r for r in rows if not r['cal'] and r['t'] + r['ks'] * 1000 > now - 86400000][:8]
    for r in near:
        if r['obsid'] in cache: continue
        try: cache[r['obsid']] = cxo_abstract(r['obsid'])
        except Exception as e: print('  cxo abstract failed', r['obsid'], e)
    keep = {r['obsid'] for r in rows}
    return {'src': CXO_SCHED, 'week': week.group(1) if week else '', 'rows': rows,
            'abs': {k: v for k, v in cache.items() if k in keep}}


# ── VOYAGER 1 + 2: distance from Earth and Sun, daily, off JPL Horizons ─────────────────
def bake_voyager():
    start = (NOW - dt.timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    stop = start + dt.timedelta(days=62)
    out = {'src': 'JPL Horizons, targets -31 and -32'}
    for key, cmd in (('v1', '-31'), ('v2', '-32')):
        e = horizons(cmd, '500@399', start.strftime('%Y-%m-%d'), stop.strftime('%Y-%m-%d'), '1d')
        h = horizons(cmd, '500@10', start.strftime('%Y-%m-%d'), stop.strftime('%Y-%m-%d'), '1d')
        out[key] = {'t0': ms(e[0][0]), 'step': 86400000, 'n': len(e),
                    'earth_km': [round(math.sqrt(r[1]**2 + r[2]**2 + r[3]**2)) for r in e],
                    'sun_km': [round(math.sqrt(r[1]**2 + r[2]**2 + r[3]**2)) for r in h],
                    'kms': round(math.sqrt(h[0][4]**2 + h[0][5]**2 + h[0][6]**2), 2)}
    return out


# ── EUCLID: range from Earth (it sits in a halo round L2, like Webb) ────────────────────
def bake_euclid():
    start = (NOW - dt.timedelta(days=2)).replace(minute=0, second=0, microsecond=0)
    rows = horizons('-680', '500@399', start.strftime('%Y-%m-%d %H:%M'), (start + dt.timedelta(days=40)).strftime('%Y-%m-%d %H:%M'), '6h')
    return {'src': 'JPL Horizons, target -680', 'survey_start': ms(dt.datetime(2024, 2, 14, tzinfo=dt.timezone.utc)),
            'range': {'t0': ms(rows[0][0]), 'step': 6 * 3600000, 'n': len(rows),
                      'km': [round(math.sqrt(r[1]**2 + r[2]**2 + r[3]**2)) for r in rows]}}


# ── RUBIN: the survey clock, and the Fink broker's nightly alert tally when it is fresh ─
def bake_rubin():
    # "Its 10-year Legacy Survey of Space and Time (LSST) began earlier this year on 29 June 2026"
    # -- NOIRLab, Image of the Week iotw2638a
    out = {'lsst_start': ms(dt.datetime(2026, 6, 29, tzinfo=dt.timezone.utc)), 'site': {'lat': -30.2446, 'lon': -70.7494}}
    try:
        j = json.loads(_fink(NOW.year))
        last = max(j, key=lambda r: r['f:night'])
        night = dt.datetime.strptime(last['f:night'], '%Y%m%d').replace(tzinfo=dt.timezone.utc)
        out['fink'] = {'night': ms(night), 'alerts': int(last['f:alerts']), 'objects': int(last['f:objects']),
                       'visits': int(last['f:visits']), 'new': int(last.get('f:is_first') or 0)}
    except Exception as e:
        print('  fink failed', e)
    return out


def _fink(year):
    req = urllib.request.Request('https://api.lsst.fink-portal.org/api/v1/statistics', data=json.dumps({'date': str(year)}).encode(),
                                 headers=dict(UA, **{'Content-Type': 'application/json'}))
    return urllib.request.urlopen(req, timeout=120).read()


def main():
    prev = {}
    try: prev = json.loads((ROOT / 'observatories.json').read_text())
    except Exception: pass
    out = {'built': ms(NOW)}
    # each piece is independent: one source down keeps the last good copy of that piece
    for key, fn in (('webb', bake_webb_schedule), ('parker', bake_parker), ('roman_card', bake_roman_card), ('media', bake_media),
                    ('hubble_obs', lambda: bake_mast('HST')),
                    ('chandra', lambda: bake_chandra(prev)), ('voyager', bake_voyager),
                    ('euclid', bake_euclid), ('rubin', bake_rubin),
                    ('webb_obs', lambda: bake_mast('JWST'))):
        try:
            out[key] = fn(); print('ok', key)
        except Exception as e:
            print('FAILED', key, e)
            if key in prev: out[key] = prev[key]
    try: attach_aims(out, prev)
    except Exception as e:
        print('FAILED aims', e)
        if 'aims' in prev: out['aims'] = prev['aims']
    for label, fn in (('roman', bake_roman), ('l2', bake_l2)):
        try: print('ok', label, fn())
        except Exception as e: print('FAILED', label, e)
    (ROOT / 'observatories.json').write_text(json.dumps(out, separators=(',', ':')))
    print('wrote observatories.json', len(json.dumps(out)), 'bytes')


if __name__ == '__main__':
    main()

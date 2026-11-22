#!/usr/bin/env python3
"""RADIO (user 2026-11-21: "make sure those are legal to use this way, build the map view, do a global view").

The global layer: every station in Radio Browser (radio-browser.info, a community-run open directory) that has a map position,
a working HTTPS stream (its last check passed). UK LISTENERS are the line, not UK stations: the file answers 451 in the UK. The page plays each station's OWN stream URL in an
<audio> element: the listener's browser connects straight to the station, nothing is relayed, recorded or re-hosted (the
directory model). Out: OUT/stations_v1.json {built, n, src, rows: [[lat, lon, name, url, homepage, cc, place, tags, codec,
bitrate, votes, 0, '', licensee, city of license, campus, campus domain, 'tag' if the stream's own tag confirmed it, listening tier 0-3]]}
plus OUT/health_v1.json and OUT/health.md (the weekly stream check, see health()).
Run: python3 _radiobake/bake.py OUT
"""
import sys, os, re, json, math, socket, random, urllib.request, datetime

UA = {'User-Agent': 'BluishVoid/1.0'}
FALLBACK = ['de1.api.radio-browser.info', 'de2.api.radio-browser.info', 'fi1.api.radio-browser.info', 'nl1.api.radio-browser.info']


def servers():
    """Radio Browser asks clients to pick a server from the all.api.radio-browser.info DNS round robin"""
    hs = []
    try:
        for ip in {a[4][0] for a in socket.getaddrinfo('all.api.radio-browser.info', 443, proto=socket.IPPROTO_TCP)}:
            try:
                hs.append(socket.gethostbyaddr(ip)[0])
            except Exception:
                pass
    except Exception:
        pass
    hs = [h for h in hs if h.endswith('radio-browser.info')] or FALLBACK
    random.shuffle(hs)
    return hs


def get(path, timeout=180):
    err = None
    for h in servers():
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request('https://' + h + path, headers=UA), timeout=timeout)), h
        except Exception as e:
            err = e
    raise SystemExit('radio-browser unreachable: %s' % err)


FCC = 'https://transition.fcc.gov/fcc-bin/%sq?list=4&size=9&status=LIC'


def fcc():
    """WHO HOLDS THE LICENSE (user 2026-11-21: "can you name the college"): the FCC's public FM and AM lists (US government data),
    call sign -> [(city of license, state, licensee, lat, lon)]"""
    out = {}
    for band in ('fm', 'am'):
        fn = os.path.join(os.environ.get('FCC_DIR', ''), band + '.txt')   # curl fetches them (the FCC answers Python's client 403)
        try:
            txt = open(fn, encoding='latin-1').read() if os.environ.get('FCC_DIR') else urllib.request.urlopen(urllib.request.Request(FCC % band, headers={'User-Agent': 'Mozilla/5.0'}), timeout=600).read().decode('latin-1')
        except Exception as e:
            print('fcc', band, 'unreachable', e)
            continue
        for ln in txt.splitlines():
            f = [x.strip() for x in ln.split('|')]
            if len(f) < 28 or f[12] != 'US' or not f[1]:
                continue
            try:
                la = (int(f[20]) + int(f[21]) / 60 + float(f[22]) / 3600) * (-1 if f[19] == 'S' else 1)
                lo = (int(f[24]) + int(f[25]) / 60 + float(f[26]) / 3600) * (-1 if f[23] == 'W' else 1)
            except ValueError:
                continue
            call = re.sub(r'-(FM|LP|AM|TV)$', '', f[1])
            out.setdefault(call, []).append((f[10], f[11], f[27], la, lo, re.sub(r'\s*(MHz|kHz)\s*$', '', f[2]).strip()))   # + frequency, for fcc_fix
    print('fcc calls', len(out))
    return out


def km(a, b, c, d):
    p = math.pi / 180
    return 12742 * math.asin(math.sqrt(math.sin((c - a) * p / 2) ** 2 + math.cos(a * p) * math.cos(c * p) * math.sin((d - b) * p / 2) ** 2))


# GENRES (user 2026-11-21: "do not all stations have a genre?" -> "yes do 1 and 2"): 1) the volunteers' free tags are mapped onto one
# vocabulary -- place names, frequencies and filler ("music", "hits", "am") dropped, spellings merged ("80's", "80er", "1980s" -> 80S;
# "hiphop" -> HIP-HOP) -- up to three; 2) a station left with none gets the genres its NAME states ("Jazz FM", "Classic Rock 101"),
# and a school-held FCC license makes it COLLEGE RADIO. A station whose name names nothing keeps none (the card says LIVE RADIO).
G = [
    ('CLASSIC ROCK', r'classic rock'), ('ALTERNATIVE', r'alternative|alt rock'), ('INDIE', r'\bindie'), ('METAL', r'metal'), ('PUNK', r'\bpunk'),
    ('SMOOTH JAZZ', r'smooth jazz'), ('JAZZ', r'\bjazz'), ('BLUES', r'\bblues'), ('SOUL', r'\bsoul\b'), ('R&B', r'\br ?& ?b\b|\brnb\b|rhythm and blues'),
    ('FUNK', r'\bfunk\b'), ('DISCO', r'\bdisco\b'), ('HIP-HOP', r'hip[- ]?hop|\bphonk\b'), ('RAP', r'\brap\b'), ('REGGAETON', r'reggaeton'), ('REGGAE', r'\breggae\b'),
    ('DANCEHALL', r'dancehall'), ('DEEP HOUSE', r'deep house'), ('HOUSE', r'\bhouse\b'), ('TECHNO', r'\btechno'), ('TRANCE', r'\btrance\b'),
    ('DRUM AND BASS', r'drum ?(and|&|n) ?bass|\bdnb\b'), ('DUBSTEP', r'dubstep'), ('DUB', r'^dub$'), ('AMBIENT', r'\bambient'), ('CHILLOUT', r'chill'),
    ('LOUNGE', r'lounge'), ('DOWNTEMPO', r'downtempo'), ('EXPERIMENTAL', r'experimental|avant'), ('ELECTRONIC', r'electronic|electronica|\belectro\b|\bedm\b'),
    ('DANCE', r'\bdance\b|eurodance'), ('CLASSICAL', r'classical|klassik|cl[aá]sica\b|\bclasic\b|\bopera\b|baroque|symphon|classic fm|classic radio'), ('CLASSIC COUNTRY', r'classic country'),
    ('BLUEGRASS', r'bluegrass'), ('COUNTRY', r'\bcountry\b'), ('AMERICANA', r'americana'), ('FOLK', r'\bfolk'), ('WORLD', r'world music|\bworld\b'),
    ('AFROBEATS', r'afrobeat'), ('SALSA', r'\bsalsa\b'), ('CUMBIA', r'cumbia'), ('BACHATA', r'bachata'), ('MERENGUE', r'merengue'), ('BANDA', r'^banda$'),
    ('REGIONAL MEXICAN', r'regional mexican|grupera|norte[ñn]a'), ('SERTANEJO', r'sertanej'), ('MPB', r'^mpb$'), ('SAMBA', r'\bsamba\b'), ('SCHLAGER', r'schlager'),
    ('BOLLYWOOD', r'bollywood'), ('LATIN', r'\blatin|latino'), ('GOSPEL', r'gospel'), ('CATHOLIC', r'catholic|cat[oó]lic'),
    ('CHRISTIAN', r'christian|cristian|worship|praise|\bhymns?\b'), ('ISLAMIC', r'islam|quran'), ('OLDIES', r'oldies|golden'),
    ('TOP 40', r'top ?40|top hits|\bcharts?\b|contemporary hits|^chr$'), ('ADULT CONTEMPORARY', r'adult contemporary|\bac\b'), ('EASY LISTENING', r'easy listening|soft hits'),
    ('BIG BAND', r'big band|swing'), ('SOUNDTRACKS', r'soundtrack|film score'), ('INSTRUMENTAL', r'instrumental'), ('KIDS', r'\bkids\b|children'),
    ('CHRISTMAS', r'christmas|navidad'), ('COMEDY', r'comedy'), ('OLD TIME RADIO', r'old time radio|\botr\b'), ('NEWS', r'\bnews\b|noticias|nachrichten|informa'),
    ('TALK', r'\btalk\b|spoken'), ('SPORTS', r'sport|deportes|futebol|f[uú]tbol'), ('PUBLIC RADIO', r'\bnpr\b|public radio'),
    ('COMMUNITY RADIO', r'community'), ('COLLEGE RADIO', r'college|campus|student radio|university radio'), ('ECLECTIC', r'eclectic|ecl[eé]tica|variety|various|freeform'),
    ('ROCK', r'\brock\b'), ('POP', r'\bpop\b'), ('BALLADS', r'balada|ballad'), ('CLASSIC HITS', r'^classic hits$|^adult hits$'),
]
G = [(n, re.compile(p, re.I)) for n, p in G]
DEC = re.compile(r"^(?:19)?([5-9]0)(?:'?s|er)$|^(?:20)?(00|10|20)(?:'?s|er)$", re.I)


def genres(tags):
    out = []
    for t in [x.strip() for x in tags.split(',') if x.strip()]:
        m = DEC.match(t.replace(' ', ''))
        hit = (m.group(1) + 'S') if m and m.group(1) else ('20' + m.group(2) + 'S') if m else None
        if not hit:
            hit = next((n for n, rx in G if rx.search(t)), None)
        if hit and hit not in out:
            out.append(hit)
    return out[:3]


def name_genres(nm):
    nm = re.sub(r'little rock|rockford|rockland|rockville|rock hill|round rock|rocky', ' ', nm, flags=re.I)
    out = []
    for n, rx in G:
        if n in ('HITS', 'DUB', 'BANDA', 'MPB', 'WORLD', 'ADULT CONTEMPORARY', 'COMMUNITY RADIO', 'KIDS', 'GOSPEL') and n != 'GOSPEL':
            continue
        if rx.search(nm) and n not in out:
            out.append(n)
    m = re.search(r"\b(?:19)?([5-9]0)'?s\b", nm)
    if m and len(out) < 3:
        out.append(m.group(1) + 'S')
    return out[:2]


# ON CAMPUS (user 2026-11-21: "how could we confirm the location of these stations another way" -> "yes do 1 and 2").
# 1) The Department of Education's IPEDS directory (public domain: every US college, its campus coordinates and web address). A
#    school-held station moves to the campus of the school whose name matches its licensee -- at least half the licensee's
#    distinctive words in the campus name, the same state, within 80 km of where the station was -- nearest wins; the card names the
#    campus ("Keene State College", not "University System of New Hampshire"). No match (a school board, a far transmitter): it stays.
# 2) The stream's own name tag (icy-name / icy-url, read from the first response, no audio kept): it confirms a station when it
#    carries the call sign or the school's web domain; a tag naming a DIFFERENT licensed call sign drops a station we placed by call
#    sign alone, since the directory's name was then wrong.
IP_STOP = set('THE OF AND AT IN FOR ON UNIVERSITY COLLEGE COLLEGES BOARD TRUSTEES REGENTS GOVERNORS SUPERVISORS VISITORS RECTOR PRESIDENT FELLOWS SYSTEM INC CORPORATION FOUNDATION DISTRICT COMMONWEALTH HIGHER EDUCATION STUDENT STUDENTS BROADCASTING RADIO MAIN CAMPUS'.split())


def ipeds():
    y = datetime.date.today().year
    for yr in (y - 1, y - 2, y - 3):
        try:
            import zipfile, io, csv
            b = urllib.request.urlopen(urllib.request.Request('https://nces.ed.gov/ipeds/datacenter/data/HD%d.zip' % yr, headers={'User-Agent': 'Mozilla/5.0'}), timeout=120).read()
            z = zipfile.ZipFile(io.BytesIO(b)); n = [x for x in z.namelist() if x.lower().endswith('.csv')][0]
            rows = list(csv.DictReader(z.read(n).decode('latin-1').splitlines()))
            print('ipeds', yr, len(rows))
            return rows
        except Exception as e:
            print('ipeds', yr, 'unavailable', e)
    return []


def sig(t):
    return {w for w in re.findall(r'[A-Z0-9&]+', (t or '').upper().replace('-', ' ')) if w not in IP_STOP and len(w) > 2}


def campus(rows, SCH):
    I = ipeds()
    if not I:
        return
    by = {}
    for x in I:
        try:
            by.setdefault(x['STABBR'], []).append((sig(x['INSTNM']), float(x['LATITUDE']), float(x['LONGITUD']), x['INSTNM'], x.get('WEBADDR', ''), sig(x.get('CITY', ''))))
        except (ValueError, KeyError):
            pass
    moved = 0
    for r in rows:
        if r[5] != 'US' or not SCH.search(r[13] or '') or not r[14]:
            continue
        # every distinctive word of the licensee in the campus name, and the campus name adding nothing but its own city's words
        # (2026-11-21: half-overlap sent Texas State to Texas Lutheran and Wayne State to Wayne County CC)
        st, ls, fc = r[14][-2:], sig(r[13]), sig(r[14][:-4])
        if not ls:
            continue
        best = None
        for s_, la, lo, nm, web, ic in by.get(st, []):
            if not ls <= s_ or (s_ - ls - fc):   # only the station's OWN city of license may add words (WKNH Keene went to UNH Manchester)
                continue
            d = km(r[0], r[1], la, lo)
            if d <= 80 and (best is None or d < best[0]):
                best = (d, la, lo, nm, web)
        if best:
            r[0], r[1] = round(best[1], 4), round(best[2], 4)
            r[15], r[16] = best[3][:80], re.sub(r'^(https?://)?(www\.)?', '', (best[4] or '').lower()).split('/')[0]
            moved += 1
    print('campus: placed on campus', moved)


def icy_check(rows, SCH, F):
    import concurrent.futures as cf
    todo = [r for r in rows if r[5] == 'US' and SCH.search(r[13] or '')]
    def tag(u):
        try:
            q = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0', 'Icy-MetaData': '1', 'Range': 'bytes=0-1023'}), timeout=8)
            h = {k.lower(): v for k, v in q.headers.items()}; q.close()
            return ' '.join(h.get(k, '') for k in ('icy-name', 'icy-url', 'icy-description', 'ice-name')).upper()
        except Exception:
            return None
    with cf.ThreadPoolExecutor(16) as ex:
        T = list(ex.map(tag, [r[3] for r in todo]))
    ok = none = bad = 0; drop = set()
    for r, t in zip(todo, T):
        calls = {m.group(1) for m in CALL.finditer(r[2].upper())}
        doms = {d.upper() for d in (r[16], re.sub(r'^(https?://)?(www\.)?', '', r[4].lower()).split('/')[0]) if d}
        if not t or not t.strip():
            none += 1; r[17] = ''
            continue
        if any(c in t for c in calls) or any(d and d in t for d in doms):
            ok += 1; r[17] = 'tag'
            continue
        other = {m.group(1) for m in CALL.finditer(t)} & set(F)
        if other and not (other & calls) and r[6] == '':
            drop.add(id(r)); bad += 1
        else:
            none += 1; r[17] = ''
    rows[:] = [r for r in rows if id(r) not in drop]
    print('stream tags: confirmed', ok, '| no usable tag', none, '| contradicted and dropped', bad)


# STACKS (user 2026-11-21: "explain to me what a larger circle is" -> "do 3 and do the rest you cant fix as 1"). Many directory stations share
# one exact point (a city center, a host's address); their glows stack into one big circle. Where a REAL location exists, a stacked station
# moves to it: a US station with an FCC license goes to its licensed transmitter; a station whose own listing names a different town than
# the rest of its stack goes to that town (Natural Earth populated places, public domain, same country, exact name). The rest -- mostly one
# broadcaster's channels, which genuinely share a place -- stay, and the page draws each shared point once (1).
NE_PLACES = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_populated_places_simple.geojson'


def _norm(t):
    import unicodedata
    return ''.join(c for c in unicodedata.normalize('NFKD', (t or '').lower()) if not unicodedata.combining(c)).strip()


def relocate(rows, FPOS):
    import collections
    st = collections.defaultdict(list)
    for r in rows:
        st[(round(r[0], 3), round(r[1], 3))].append(r)
    stacks = [v for v in st.values() if len(v) > 1]
    try:
        P = json.load(urllib.request.urlopen(urllib.request.Request(NE_PLACES, headers={'User-Agent': 'BluishVoid/1.0'}), timeout=120))['features']
    except Exception as e:
        print('places unavailable', e); P = []
    places = collections.defaultdict(list)
    for f in P:
        q = f['properties']
        for nm in {q.get('name'), q.get('nameascii'), q.get('namealt')}:
            if nm:
                places[(_norm(nm), q.get('iso_a2'))].append((q['latitude'], q['longitude']))
    nf = nt = 0
    for v in stacks:
        common = collections.Counter(_norm(x[6]) for x in v).most_common(1)[0][0]
        for r in v:
            if r[15]:                                            # already on its campus
                continue
            if id(r) in FPOS:
                la, lo = FPOS[id(r)]
                if km(r[0], r[1], la, lo) > 3:
                    r[0], r[1] = round(la, 4), round(lo, 4); nf += 1
                continue
            town = _norm((r[6] or '').split(',')[0])
            if not town or town == common:
                continue
            hit = places.get((town, r[5])) or []
            if len(hit) == 1 and km(r[0], r[1], hit[0][0], hit[0][1]) > 3:
                r[0], r[1] = round(hit[0][0], 4), round(hit[0][1], 4); nt += 1
    left = collections.Counter((round(r[0], 3), round(r[1], 3)) for r in rows)
    print('stacks: moved to FCC transmitter', nf, '| to their named town', nt, '| still sharing a point', sum(c for c in left.values() if c > 1))


CALL = re.compile(r'\b([KW][A-Z]{2,3})(?:-?(?:FM|AM|LP|LPFM|HD\d?))?\b')


# HEALTH (user 2026-11-21: "do 2 ... 10"). Every week each kept stream is asked for its first few KB, as a listener's browser would (no
# audio kept). A station whose stream failed THIS week and LAST week is left off the map -- one bad week is forgiven (a station down for
# maintenance). If more than a quarter fail, the checker's own network is the likelier fault and nothing is dropped. OUR PICKS (in
# index.html) are checked too but never dropped: a dead pick is a ::warning:: in the run, with any working stream the directory lists
# under the same name. The run's summary also lists stations whose own stream address changed since last week.
# State: radio/health_v1.json on R2 {built, fails: {url: weeks in a row}, uuid: {station uuid: url}} (HEALTH_PREV = last week's copy).
CODE = {}
GENRE = {}   # the genre each stream announces about itself (icy-genre), read by the health check


def probe(u):
    try:
        # asked as a browser's <audio> asks: Shoutcast servers hand a browser their HTML status page at "/" -- Chrome then cannot play
        # it (checked 2026-11-21), so that counts as a failure, as it is for a listener
        q = urllib.request.urlopen(urllib.request.Request(u, headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0 Safari/537.36', 'Accept': '*/*', 'Range': 'bytes=0-'}), timeout=12)
        ct = (q.headers.get('Content-Type') or '').lower(); GENRE[u] = (q.headers.get('icy-genre') or q.headers.get('ice-genre') or '').strip()[:80]; b = q.read(2048); q.close()
        if re.search(r'\.m3u8(\?|$)', u) or 'mpegurl' in ct:
            return b.lstrip().startswith(b'#EXTM3U')
        return bool(b) and 'text/html' not in ct
    except urllib.error.HTTPError as e:
        CODE[u] = e.code; return False
    except Exception:
        return False


# NO ACCESS CODES (user 2026-11-21: a "Sign in to access this site" box from f100.fabricahost.com.br). Some listings saved a stream address
# with the host's short-lived access code in it (?zt=, ?rj-tok=, ?f=&tid=, ?token= ...); once it expires the server asks for a password.
# Our rule is the station's own PUBLIC stream, never a token. Where the host's public address hands every listener a fresh code itself
# (Zeno, Revma: checked 2026-11-21), that public address is used; where it does not (Fabricahost answers 401), the station is left off.
TOKQ = {'zt', 'zs', 'rj-tok', 'rj-ttl', 'token', 'tid', 'jwt', 'sig', 'signature', 'expires', 'hdnts', 'hdnea', 'policy', 'key-pair-id',
        'wmsauthsign', 'playsessionid', 'session-id', 'listenerid', 'access_token', 'auth'}


def tokens(rows):
    import urllib.parse as up
    fix = {}
    for r in rows:
        p = up.urlsplit(r[3]); q = up.parse_qsl(p.query, keep_blank_values=True)
        bad = {k for k, v in q if k.lower().split(';')[-1] in TOKQ or v.startswith('eyJ')}   # 'amp;rj-tok': an &amp; saved into the address
        if not bad:
            continue
        if 'tid' in {k.lower() for k in bad}:
            bad |= {k for k, v in q if k.lower() == 'f'}
        host = 'stream.zeno.fm' if re.fullmatch(r'stream-\d+\.(zeno\.fm|surfernetwork\.com)', p.hostname or '') else p.netloc
        fix[r[3]] = up.urlunsplit((p.scheme, host, p.path, up.urlencode([(k, v) for k, v in q if k not in bad]), ''))
    import concurrent.futures as cf
    with cf.ThreadPoolExecutor(32) as ex:
        ok = dict(zip(fix.values(), ex.map(probe, list(fix.values()))))
    kept = gone = 0; drop = set()
    for r in rows:
        if r[3] in fix:
            if ok.get(fix[r[3]]):
                r[3] = fix[r[3]]; kept += 1
            else:
                drop.add(id(r)); gone += 1
    rows[:] = [r for r in rows if id(r) not in drop]
    print('access codes: moved to the public address', kept, '| left off (no public address)', gone)


def picks():
    try:
        h = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'index.html'), encoding='utf-8').read()
        return json.loads(re.search(r'RAD\.PICKS = (\[\[.*?\]\]);', h).group(1))
    except Exception as e:
        print('picks unreadable', e); return []


def health(rows, META, out):
    import concurrent.futures as cf
    try:
        prev = json.load(open(os.environ.get('HEALTH_PREV', ''))) if os.environ.get('HEALTH_PREV') else {}
    except Exception:
        prev = {}
    pf, pu = prev.get('fails') or {}, prev.get('uuid') or {}
    P = picks()
    urls = sorted({r[3] for r in rows} | {p[3] for p in P})
    with cf.ThreadPoolExecutor(48) as ex:
        ok = dict(zip(urls, ex.map(probe, urls)))
    bad = [u for u in urls if not ok[u]]
    # a WEEK counts only when last week's check is 5+ days old: a second run the same day (2026-11-21: 484 stations dropped after two
    # runs 30 minutes apart) keeps the count it had instead of adding to it
    try:
        age = (datetime.datetime.utcnow() - datetime.datetime.strptime(prev.get('built', ''), '%Y-%m-%dT%H:%MZ')).days
    except ValueError:
        age = 99
    fails = {u: pf.get(u, 0) + 1 if age >= 5 else max(1, pf.get(u, 0)) for u in bad}
    rate = len(bad) / max(1, len(urls))
    sick = rate > .25
    # a stream that answers with a login request (401/407) is access-controlled, not public: off at once, whatever the weeks
    gone = [r for r in rows if (fails.get(r[3], 0) >= 2 and not sick) or CODE.get(r[3]) in (401, 407)]
    gid = {id(r) for r in gone}
    rows[:] = [r for r in rows if id(r) not in gid]
    uu = {META[id(r)][0]: r[3] for r in rows if id(r) in META and META[id(r)][0]}
    moved = [(u, pu[u], v) for u, v in uu.items() if u in pu and pu[u] != v]
    nm = {META[id(r)][0]: r[2] for r in rows if id(r) in META}
    deadp = [p for p in P if not ok.get(p[3], True)]
    L = ['## Radio health %s' % datetime.date.today().isoformat(), '',
         '- streams checked: **%d**, failed this week: **%d** (%.1f%%)%s' % (len(urls), len(bad), rate * 100, ' -- too many, so the checker is suspect and NOTHING was dropped' if sick else ''),
         '- left off the map (failed two weeks running): **%d**' % len(gone),
         '- stream address changed since last week: **%d**' % len(moved), '']
    if deadp:
        L += ['### OUR PICKS not answering', '']
        for p in deadp:
            alt = []
            try:
                S, _ = get('/json/stations/byname/' + urllib.request.quote(p[2]))
                alt = sorted({s['url_resolved'] for s in S if s.get('lastcheckok') == 1 and (s.get('url_resolved') or '').startswith('https://') and s['url_resolved'] != p[3]})[:3]
            except BaseException:
                pass
            L.append('- **%s** `%s` (%s week%s in a row)%s' % (p[2], p[3], fails.get(p[3], 1), '' if fails.get(p[3], 1) == 1 else 's', (' -- the directory lists: ' + ', '.join('`%s`' % a for a in alt)) if alt else ''))
            print('::warning::RADIO PICK NOT ANSWERING: %s %s%s' % (p[2], p[3], (' | directory has ' + ' '.join(alt)) if alt else ''))
        L.append('')
    if gone:
        L += ['### Left off the map', ''] + ['- %s (%s) `%s`' % (r[2], r[5], r[3]) for r in gone[:60]] + (['- ...and %d more' % (len(gone) - 60)] if len(gone) > 60 else []) + ['']
    if moved:
        L += ['### Stream address changed', ''] + ['- %s: `%s` -> `%s`' % (nm.get(u, u), a, b) for u, a, b in moved[:60]] + (['- ...and %d more' % (len(moved) - 60)] if len(moved) > 60 else []) + ['']
    open(os.path.join(out, 'health.md'), 'w').write('\n'.join(L))
    json.dump({'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'fails': fails, 'uuid': uu}, open(os.path.join(out, 'health_v1.json'), 'w'), separators=(',', ':'))
    print('health: checked', len(urls), '| failed', len(bad), '| dropped', len(gone), '| address changed', len(moved), '| picks down', len(deadp))


# WRONG COUNTRY (user 2026-11-21: "this is in south america but it says its playing in Australia ... theyre located in austria"): a
# volunteer's dot and country can disagree (Live Radio Tirol: AU, pinned in the Amazon). Each dot is tested against Natural Earth's
# country shapes (public domain). A dot on ANOTHER country's land, more than ~50 km from its own country (borders: Tijuana heard in San
# Diego) and not a territory of it (Reunion is France), is wrong in one of the two fields; the station's own web address decides: a
# domain of the country under the dot keeps the dot and takes that country, anything else leaves the station off the map.
NE_A0 = 'https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_admin_0_countries.geojson'
PARENT = {k: 'FR' for k in 'RE MQ GP GF YT TF PM NC PF WF BL MF'.split()}
PARENT.update({k: 'US' for k in 'UM PR GU VI AS MP'.split()})
PARENT.update({'VA': 'IT', 'SM': 'IT', 'PS': 'IL', 'IL': 'PS', 'XK': 'RS', 'AX': 'FI', 'GG': 'GB', 'JE': 'GB', 'IM': 'GB', 'GI': 'GB', 'HK': 'CN', 'MO': 'CN',
               'SJ': 'NO', 'BQ': 'NL', 'CW': 'NL', 'SX': 'NL', 'AW': 'NL', 'GL': 'DK', 'FO': 'DK'})
TLD = {'uk': 'GB'}


def countries(rows):
    try:
        G = json.load(urllib.request.urlopen(urllib.request.Request(NE_A0, headers={'User-Agent': 'BluishVoid/1.0'}), timeout=120))['features']
    except Exception as e:
        print('countries unavailable, check skipped', e); return
    C = []
    for f in G:
        p = f['properties']; iso = p.get('ISO_A2_EH') if p.get('ISO_A2_EH') not in (None, '-99') else p.get('ISO_A2')
        g = f['geometry']
        for poly in ([g['coordinates']] if g['type'] == 'Polygon' else g['coordinates']):
            xs = [c[0] for c in poly[0]]; ys = [c[1] for c in poly[0]]
            C.append((iso, (min(xs), min(ys), max(xs), max(ys)), poly))
    def inr(x, y, ring):
        c = False; j = len(ring) - 1
        for i in range(len(ring)):
            xi, yi = ring[i]; xj, yj = ring[j]
            if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                c = not c
            j = i
        return c
    def where(la, lo):
        for iso, b, poly in C:
            if b[0] <= lo <= b[2] and b[1] <= la <= b[3] and inr(lo, la, poly[0]) and not any(inr(lo, la, h) for h in poly[1:]):
                return iso
        return None
    global WHERE, LABEL
    WHERE = where; LABEL = {}
    for f in G:
        p = f['properties']; iso = p.get('ISO_A2_EH') if p.get('ISO_A2_EH') not in (None, '-99') else p.get('ISO_A2'); b = f.get('bbox') or None
        LABEL[iso] = (p.get('LABEL_Y'), p.get('LABEL_X'))
    fam = lambda c: {c, PARENT.get(c, c)}
    fixed = gone = 0; drop = set()
    for r in rows:
        cc = r[5]; w = where(r[0], r[1]) if cc else None
        if not w or w == '-99' or w in fam(cc) or cc in fam(w):
            continue
        near = False
        for dd in (.15, .3, .45):
            for k in range(8):
                a = k * math.pi / 4; q = where(r[0] + dd * math.sin(a), r[1] + dd * math.cos(a) / max(.2, math.cos(math.radians(r[0]))))
                if q and (q in fam(cc) or cc in fam(q)):
                    near = True; break
            if near:
                break
        if near:
            continue
        host = re.sub(r'^(https?://)?', '', (r[4] or '').lower()).split('/')[0].split(':')[0]
        tld = host.rsplit('.', 1)[-1] if '.' in host else ''
        if tld and TLD.get(tld, tld.upper()) in fam(w):
            r[5] = w; r[6] = ''; fixed += 1
        else:
            drop.add(id(r)); gone += 1
    rows[:] = [r for r in rows if id(r) not in drop]
    print('countries: dot on another country -> country corrected from its web address', fixed, '| left off the map', gone)


# ONE STREAM, ONE DOT: the same stream listed twice with only tracking or cache-busting extras (?ref=, ?nocache=, /link, a trailing ;)
# keeps the first (the most voted). Run AFTER the country check, so a misplaced copy cannot win over the right one.
JUNK_Q = {'ref', 'nocache', 'type', 'origem', 'aggregator', 'uid', '_', 't', 'ts', 'cb', 'source', 'from'}


def skey(u):
    import urllib.parse as up
    p = up.urlsplit(u.strip())
    q = [(k, v) for k, v in up.parse_qsl(p.query, keep_blank_values=True) if k.lower() not in JUNK_Q and not k.isdigit()]
    if re.fullmatch(r'\d+', p.query or ''):
        q = []
    path = re.sub(r'(/link|/;|;)?/*$', '', p.path)
    return (p.hostname or '').lower() + ':' + str(p.port or 443) + path + ('?' + up.urlencode(sorted(q)) if q else '')


def dedupe(rows):
    seen, out = set(), []
    for r in rows:
        k = skey(r[3])
        if k in seen and not r[11]:
            continue
        seen.add(k); out.append(r)
    print('same stream listed twice: dropped', len(rows) - len(out))
    rows[:] = out


WHERE = None
LABEL = {}


# PLACEMENT AUDIT (user 2026-11-21: "audit the dot locations and make sure theyre placed correctly ... fix their database data a bit").
# 1) A US station whose name carries a call sign AND that license's frequency or city of license, but whose dot is more than 150 km from
#    the licensed transmitter (KJYO 102.7 Oklahoma City sat in Ohio): it moves to the transmitter. Call signs are unique; the frequency or
#    city in the name guards against words that look like call signs ("WILD", "KISS").
def fcc_fix(rows, F, FPOS):
    n = 0
    for r in rows:
        if r[5] != 'US' or r[13]:
            continue
        nm = r[2].upper()
        for m in CALL.finditer(nm):
            hit = [c for c in F.get(m.group(1), []) if (c[5] and re.search(r'(?<![\d.])' + re.escape(c[5].rstrip('0').rstrip('.') if '.' in c[5] else c[5]) + r'(?![\d])', nm)) or (c[0] and c[0].upper() in nm)]
            if len({(c[0], c[2]) for c in hit}) == 1 and km(r[0], r[1], hit[0][3], hit[0][4]) > 150:   # one license (its main record first; boosters share city and holder)
                c = hit[0]; r[0], r[1] = round(c[3], 4), round(c[4], 4); r[13] = ' '.join(c[2].split())[:80]; r[14] = (c[0].title() + ', ' + c[1])[:50]; FPOS[id(r)] = (c[3], c[4]); n += 1
                break
    print('placement: US stations moved to their licensed transmitter', n)


# 2) A dot more than ~50 km out to sea, and 3) a dot on a larger country's center point (a "somewhere in Germany" placeholder): moved to a
#    town the station's name or listing names, in its own country (Natural Earth populated places, the largest of that name); a dot at
#    sea with no such town is left off. Tiny countries keep their center -- it is near enough.
def places_fix(rows):
    if not WHERE:
        print('placement: country shapes unavailable, skipped'); return
    try:
        P = json.load(urllib.request.urlopen(urllib.request.Request(NE_PLACES, headers={'User-Agent': 'BluishVoid/1.0'}), timeout=120))['features']
    except Exception as e:
        print('placement: places unavailable', e); return
    import collections
    pl = collections.defaultdict(list)
    for f in P:
        q = f['properties']
        for nm in {q.get('name'), q.get('nameascii')}:
            if nm and len(nm) >= 4:
                pl[(_norm(nm), q.get('iso_a2'))].append((q['latitude'], q['longitude'], q.get('pop_max') or 0))
    def town(r):
        best = None
        for w in set(re.findall(r'[^\W\d_]{4,}(?:[ -][^\W\d_]{3,})?', r[2] + ' ' + (r[6] or ''))) | set(re.findall(r'[^\W\d_]{4,}', r[2] + ' ' + (r[6] or ''))):
            for la, lo, pop in pl.get((_norm(w), r[5]), []):
                if pop >= 20000 and (best is None or pop > best[2]):
                    best = (la, lo, pop)
        return best
    def at_sea(la, lo):
        if WHERE(la, lo):
            return False
        for dd in (.1, .25, .5):
            for k in range(8):
                a = k * math.pi / 4
                if WHERE(la + dd * math.sin(a), lo + dd * math.cos(a) / max(.2, math.cos(math.radians(la)))):
                    return False
        return True
    # 4) NEAR-SHORE WATER (user 2026-11-21: Mo's Place Radio sat in Long Island Sound -> "fix the near-shore water dots"): a dot in the water
    #    but within ~50 km of land moves to the town its name or listing names, if that is within 60 km, else to the nearest land. A dot
    #    within ~3 km of the shore stays: the country shapes are coarse at the coast, and waterfront stations sit there rightly.
    def nearest_land(la, lo, cc):
        cl = max(.2, math.cos(math.radians(la))); own = {cc, PARENT.get(cc, cc)}
        for dd in (.03, .05, .08, .12, .18):                      # ~20 km at most: farther than that only to a town it names
            for k in range(16):
                a = k * math.pi / 8; y, x = la + dd * math.sin(a), lo + dd * math.cos(a) / cl
                w = WHERE(y, x)
                if w and (w in own or PARENT.get(w) in own):                    # its own country's land only: a small island the coarse
                    return y + .01 * math.sin(a), x + .01 * math.cos(a) / cl   # shapes leave out (Alderney) must not land in France
        return None
    sea = moved = cen = shore = 0; drop = set()
    for r in rows:
        if r[15] or r[13]:
            continue                                            # placed by campus or FCC already
        if not WHERE(r[0], r[1]) and not at_sea(r[0], r[1]):
            cl = max(.2, math.cos(math.radians(r[0])))
            if any(WHERE(r[0] + .025 * math.sin(k * math.pi / 8), r[1] + .025 * math.cos(k * math.pi / 8) / cl) for k in range(16)):
                continue                                        # within ~3 km of the shore: leave it
            t = town(r)
            p = (t[0], t[1]) if t and km(r[0], r[1], t[0], t[1]) <= 60 else nearest_land(r[0], r[1], r[5])
            if p:
                r[0], r[1] = round(p[0], 4), round(p[1], 4); shore += 1
            continue
        if at_sea(r[0], r[1]):
            t = town(r)
            if t:
                r[0], r[1] = round(t[0], 4), round(t[1], 4); moved += 1
            else:
                drop.add(id(r))
            sea += 1
            continue
        lb = LABEL.get(r[5])
        if lb and lb[0] is not None and km(r[0], r[1], lb[0], lb[1]) < 25 and r[5] not in SMALL:
            t = town(r)
            if t and km(r[0], r[1], t[0], t[1]) > 25:
                r[0], r[1] = round(t[0], 4), round(t[1], 4); cen += 1
    rows[:] = [r for r in rows if id(r) not in drop]
    print('placement: out at sea', sea, '(moved to their named town', moved, ', left off', len(drop), ') | near-shore water moved ashore', shore, '| country-center placeholders moved', cen)


SMALL = set('SG LU LI MC SM VA AD MT BH BB LC GD VC KN AG DM MU SC MV CV KY BM FO GI IM JE GG AW CW SX BQ TC VG VI AI MS BL MF PM WF TO WS NR TV KI MH FM PW BN QA KW CY JM TT HK MO PS'.split())


# PUBLIC BROADCASTERS BY WEB ADDRESS (2026-11-21): stations the directory lists with no position and no city, placed at their studios; only
# studio cities we are sure of
BROADCASTER_HQ = {
    '5fm.co.za': (-26.183, 28.006, 'Johannesburg'), 'metrofm.co.za': (-26.183, 28.006, 'Johannesburg'),
    'ukhozifm.co.za': (-29.858, 31.022, 'Durban'), 'lotusfm.co.za': (-29.858, 31.022, 'Durban'),
    'lesedifm.co.za': (-29.121, 26.214, 'Bloemfontein'), 'umhlobowenenefm.co.za': (-33.961, 25.602, 'Gqeberha'),
    'phalaphalafm.co.za': (-23.904, 29.469, 'Polokwane'),
    'ebc.et': (9.030, 38.740, 'Addis Ababa'), 'rm.co.mz': (-25.966, 32.573, 'Maputo'),
    # South America (2026-11-21: "review south america for more public radio")
    'radionacional.co': (4.635, -74.083, 'Bogotá'), 'radiouruguay.uy': (-34.906, -56.186, 'Montevideo'),
    'rnv.gob.ve': (10.501, -66.913, 'Caracas'), 'radiomundial.com.ve': (10.501, -66.913, 'Caracas'),
    'radionacional.com.ar': (-34.602, -58.378, 'Buenos Aires'),
}
# a public network's own streams with no town in the name: its headquarters (Radio Nacional Argentina's stream network)
STREAM_HQ = {'sa.mp3.icecast.magma.edge-access.net': (-34.602, -58.378, 'Buenos Aires', 'https://www.radionacional.com.ar/', r'nacional')}
# public networks name real local stations ("LRA 16 Radio Nacional La Quiaca"): their towns count down to 5,000 people
PUBNET = re.compile(r'radio nacional|\bLRA ?\d|\bL[TUV] ?\d+ radio nacional|\bRTS\b|\bKBC\b|\bZNBC\b|\bSABC\b|radio uruguay', re.I)
CNAME = {'MZ': 'Mocambique', 'MX': 'Mexico'}   # a small town that shares its country's name: 'Radio Mocambique' is national, not from Ilha de Mocambique


# NO TUNEIN (user 2026-11-21: "dont use any tunein links"): TuneIn's own channels and streams it serves are left off; a station's own stream
# carrying TuneIn's tag (?source=TuneIn, environment=tunein, aggregator=tunein -- it credits the listen to TuneIn) keeps only its plain
# address, if that plays, else it is left off; a TuneIn page given as a station's website is dropped from the card.
TI = re.compile(r'tunein|radiotime', re.I)


def no_tunein(rows):
    import urllib.parse as up
    drop, fix = set(), {}
    for r in rows:
        if TI.search(r[4] or ''):
            r[4] = ''
        p = up.urlsplit(r[3])
        if TI.search(p.hostname or '') or TI.search(p.path or '') or TI.search(r[2] or '') and not r[11]:   # TuneIn in the host, the path or the name
            drop.add(id(r)); continue
        if TI.search(p.query or ''):
            q = [(k, v) for k, v in up.parse_qsl(p.query, keep_blank_values=True) if not TI.search(k) and not TI.search(v)]
            fix[id(r)] = up.urlunsplit((p.scheme, p.netloc, p.path, up.urlencode(q), ''))
    import concurrent.futures as cf
    ids = list(fix); urls = [fix[i] for i in ids]
    with cf.ThreadPoolExecutor(24) as ex:
        ok = dict(zip(ids, ex.map(probe, urls)))
    kept = 0
    for r in rows:
        if id(r) in fix:
            if ok.get(id(r)):
                r[3] = fix[id(r)]; kept += 1
            else:
                drop.add(id(r))
    n0 = len(rows); rows[:] = [r for r in rows if id(r) not in drop]
    print('tunein: tag stripped and kept', kept, '| left off', n0 - len(rows))


EXTRA = [
    (-1.2803, 36.8167, 'KBC Radio Taifa', 'https://stream.zeno.fm/ud2u96xst5quv', 'https://www.kbc.co.ke/radio/', 'KE', 'Nairobi', 'public radio'),
    (-1.2803, 36.8167, 'KBC English Service', 'https://stream.zeno.fm/mhmwnyyst5quv', 'https://www.kbc.co.ke/radio/', 'KE', 'Nairobi', 'public radio,news'),
    (-15.404, 28.312, 'ZNBC Radio 1', 'https://eu6.fastcast4u.com/proxy/radio1?mp=/1', 'https://znbc.co.zm', 'ZM', 'Lusaka', 'public radio'),
    (-15.404, 28.312, 'ZNBC Radio 2', 'https://eu6.fastcast4u.com/proxy/radio2?mp=/1', 'https://znbc.co.zm', 'ZM', 'Lusaka', 'public radio'),
    (-15.404, 28.312, 'ZNBC Radio 4', 'https://eu6.fastcast4u.com/proxy/radio4?mp=/1', 'https://znbc.co.zm', 'ZM', 'Lusaka', 'public radio'),
    (-6.770, 39.248, 'TBC Taifa', 'https://a7.asurahosting.com/listen/tbc_taifa/radio.mp3', 'https://www.tbc.go.tz', 'TZ', 'Dar es Salaam', 'public radio'),
    (-6.770, 39.248, 'TBC Bongo FM', 'https://a7.asurahosting.com/listen/bongo_fm/radio.mp3', 'https://www.tbc.go.tz', 'TZ', 'Dar es Salaam', 'public radio,pop'),
    (9.030, 7.490, 'Radio Nigeria Kapital FM', 'https://cast4.asurahosting.com/proxy/radioni1/stream', 'https://radionigeria.gov.ng', 'NG', 'Abuja', 'public radio'),
    (36.813, 10.179, 'Radio Tunisienne Nationale', 'https://radio.radiotunisienne.tn/nationale', 'https://www.radiotunisienne.tn', 'TN', 'Tunis', 'public radio'),
    (36.813, 10.179, 'Radio Tunisienne RTCI', 'https://radio.radiotunisienne.tn/rtci', 'https://www.radiotunisienne.tn', 'TN', 'Tunis', 'public radio'),
]


def tiers(rows, META):
    """how much each station is listened to, as the directory counts it (clicks in the last day, plus votes), ranked into four faint
    dot sizes: 3 = top 3%, 2 = top 15%, 1 = top half, 0 = the rest"""
    sc = sorted(((math.log1p(META.get(id(r), ('', 0, 0))[1]) + .3 * math.log1p(META.get(id(r), ('', 0, 0))[2]), i) for i, r in enumerate(rows)), reverse=True)
    n = max(1, len(sc))
    for k, (_, i) in enumerate(sc):
        f = k / n
        rows[i].append(3 if f < .03 else 2 if f < .15 else 1 if f < .5 else 0)


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'out'
    os.makedirs(out, exist_ok=True)
    S, host = get('/json/stations/search?has_geo_info=true&is_https=true&hidebroken=true&limit=200000&order=votes&reverse=true')
    rows, seen, META = [], set(), {}
    for s in S:
        u = (s.get('url_resolved') or '').strip()
        try:
            la, lo = float(s.get('geo_lat')), float(s.get('geo_long'))
        except (TypeError, ValueError):
            continue
        if not u.startswith('https://') or s.get('lastcheckok') != 1 or not (-90 < la < 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
            continue
        # HLS streams are in since 2026-11-21: the page plays them through hls.js (Safari natively); they were the big national broadcasters
        if u in seen:
            continue
        seen.add(u)
        nm = ' '.join((s.get('name') or '').split())[:80]
        if not nm:
            continue
        tags = ','.join([t.strip() for t in (s.get('tags') or '').split(',') if t.strip()][:3])[:60]
        place = (s.get('state') or '').strip()[:40]
        hp = (s.get('homepage') or '').strip()
        hp = hp if hp.startswith('http') else ''
        rows.append([round(la, 3), round(lo, 3), nm, u, hp[:200], (s.get('countrycode') or '').upper(), place, tags,
                     (s.get('codec') or '').upper()[:6], int(s.get('bitrate') or 0), int(s.get('votes') or 0), 0, '', '', '', '', '', ''])
        META[id(rows[-1])] = (s.get('stationuuid') or '', int(s.get('clickcount') or 0), int(s.get('votes') or 0))
    # US stations whose name carries a call sign: the licensee and city of license, if the FCC's transmitter is within 150 km
    F, nf = fcc(), 0
    FPOS = {}
    for r in rows:
        if r[5] != 'US':
            continue
        best = None
        for m in CALL.finditer(r[2].upper()):
            for c in F.get(m.group(1), []):
                d = km(r[0], r[1], c[3], c[4])
                if d <= 150 and (best is None or d < best[0]):
                    best = (d, c)
        if best:
            c = best[1]; r[13] = ' '.join(c[2].split())[:80]; r[14] = (c[0].title() + ', ' + c[1])[:50]; nf += 1; FPOS[id(r)] = (c[3], c[4])
    print('fcc matched', nf)
    SCH = re.compile(r'COLLEGE|UNIVERSITY|INSTITUTE OF|SCHOOL|ACADEMY|SEMINARY|REGENTS')
    # COLLEGE STATIONS THE DIRECTORY NEVER PLACED (user 2026-11-21: "are there more college stations out there? like new paltz ny?" ->
    # "i only want playable ones right now"): US stations with a working HTTPS stream but no map position, whose name carries the call
    # sign of a school-held FCC license, are placed at that license's transmitter. Checks: the call sign must be in the name; the
    # license must be held by a school; if the directory gives a state it must be the license's state; one license per stream.
    ST = {'AL': 'alabama', 'AK': 'alaska', 'AZ': 'arizona', 'AR': 'arkansas', 'CA': 'california', 'CO': 'colorado', 'CT': 'connecticut', 'DE': 'delaware', 'DC': 'district of columbia', 'FL': 'florida', 'GA': 'georgia', 'HI': 'hawaii', 'ID': 'idaho', 'IL': 'illinois', 'IN': 'indiana', 'IA': 'iowa', 'KS': 'kansas', 'KY': 'kentucky', 'LA': 'louisiana', 'ME': 'maine', 'MD': 'maryland', 'MA': 'massachusetts', 'MI': 'michigan', 'MN': 'minnesota', 'MS': 'mississippi', 'MO': 'missouri', 'MT': 'montana', 'NE': 'nebraska', 'NV': 'nevada', 'NH': 'new hampshire', 'NJ': 'new jersey', 'NM': 'new mexico', 'NY': 'new york', 'NC': 'north carolina', 'ND': 'north dakota', 'OH': 'ohio', 'OK': 'oklahoma', 'OR': 'oregon', 'PA': 'pennsylvania', 'RI': 'rhode island', 'SC': 'south carolina', 'SD': 'south dakota', 'TN': 'tennessee', 'TX': 'texas', 'UT': 'utah', 'VT': 'vermont', 'VA': 'virginia', 'WA': 'washington', 'WV': 'west virginia', 'WI': 'wisconsin', 'WY': 'wyoming', 'PR': 'puerto rico'}
    added = 0
    if F:
        try:
            U, _ = get('/json/stations/search?countrycode=US&is_https=true&hidebroken=true&limit=100000')
        except SystemExit:
            U = []
        for s in U:
            u = (s.get('url_resolved') or '').strip()
            if s.get('geo_lat') is not None or not u.startswith('https://') or s.get('lastcheckok') != 1 or u in seen:
                continue
            nm = ' '.join((s.get('name') or '').split())[:80]
            st = (s.get('state') or '').strip().lower()
            cands = [c for m in CALL.finditer(nm.upper()) for c in F.get(m.group(1), []) if SCH.search(c[2])]
            if st:
                cands = [c for c in cands if ST.get(c[1]) == st or c[1].lower() == st]
            lic = {c[2] for c in cands}
            if len(lic) != 1:
                continue
            c = cands[0]
            seen.add(u)
            tags = ','.join([t.strip() for t in (s.get('tags') or '').split(',') if t.strip()][:3])[:60]
            hp = (s.get('homepage') or '').strip()
            rows.append([round(c[3], 3), round(c[4], 3), nm, u, hp[:200] if hp.startswith('http') else '', 'US', '', tags,
                         (s.get('codec') or '').upper()[:6], int(s.get('bitrate') or 0), int(s.get('votes') or 0), 0, '',
                         ' '.join(c[2].split())[:80], (c[0].title() + ', ' + c[1])[:50], '', '', ''])
            META[id(rows[-1])] = (s.get('stationuuid') or '', int(s.get('clickcount') or 0), int(s.get('votes') or 0))
            added += 1
    print('college stations placed from the FCC', added)
    # STATIONS THE DIRECTORY NEVER PLACED, BY THEIR CITY (user 2026-11-21: "theres no reachable radio in tokyo or seoul? radio garden has a lot
    # of pop from those cities"): a working HTTPS station with no map position whose listing's city ("Seoul", "Tokyo", "Kobe") is a Natural
    # Earth populated place in its own country goes to that place (the largest of the name). No city, no placement: a capital would be a
    # guess (every .fr station in Paris), and a foreign-hosted channel would land in the wrong country. Every later check still applies.
    N = []
    for attempt in range(2):                                     # the biggest request; a busy directory times out (2026-11-22: 0 placed)
        try:
            N, _ = get('/json/stations/search?is_https=true&hidebroken=true&has_geo_info=false&limit=100000', timeout=420); break
        except SystemExit as e:
            print('no-position stations: attempt', attempt + 1, 'failed', e)
            import time as _t; _t.sleep(60)
    import collections
    try:
        PP = json.load(urllib.request.urlopen(urllib.request.Request(NE_PLACES, headers={'User-Agent': 'BluishVoid/1.0'}), timeout=120))['features']
    except Exception as e:
        print('places unavailable', e); PP = []
    pidx = collections.defaultdict(list)
    for f in PP:
        q = f['properties']
        for nm0 in {q.get('name'), q.get('nameascii')}:
            if nm0 and len(nm0) >= 3:
                pidx[(_norm(nm0), q.get('iso_a2'))].append((q['latitude'], q['longitude'], q.get('pop_max') or 0, q.get('name') or nm0))
    byc = 0
    for s in N:
        u = (s.get('url_resolved') or '').strip(); cc = (s.get('countrycode') or '').upper()
        if s.get('geo_lat') is not None or not u.startswith('https://') or s.get('lastcheckok') != 1 or u in seen:
            continue
        city = (s.get('state') or '').split(',')[0].strip()
        hit = pidx.get((_norm(city), cc)) if city else None
        nm = ' '.join((s.get('name') or '').split())[:80]
        if not nm:
            continue
        # ... or (user 2026-11-21: "review the countries of africa for more public radio") the town its NAME gives ("Radio Cotonou", "Love FM
        # 107.3 Dakar": a whole word, a place of 50,000+ in its own country, never the country's own name), or a public broadcaster's
        # studio city by its web address (BROADCASTER_HQ)
        if not hit:
            cn = _norm(CNAME.get(cc, ''))
            for w in set(re.findall(r'[^\W\d_]+(?:[ -][^\W\d_]+)?', _norm(nm))) | set(re.findall(r'[^\W\d_]{4,}', _norm(nm))):
                if w == cn:
                    continue
                c2 = [t for t in pidx.get((w, cc), []) if t[2] >= (5000 if PUBNET.search(nm) else 50000)]
                if c2 and (not hit or max(c2, key=lambda t: t[2])[2] > max(hit, key=lambda t: t[2])[2]):
                    hit = c2
            if hit:
                city = max(hit, key=lambda t: t[2])[3] if len(max(hit, key=lambda t: t[2])) > 3 else city
        if not hit:
            hd = re.sub(r'^https?://(www\.)?', '', (s.get('homepage') or '').lower()).split('/')[0]
            if hd in BROADCASTER_HQ:
                b0 = BROADCASTER_HQ[hd]; hit = [(b0[0], b0[1], 1)]; city = b0[2]
            else:
                sh = re.sub(r'^https?://', '', u).split('/')[0].split(':')[0]
                if sh in STREAM_HQ and re.search(STREAM_HQ[sh][4], nm, re.I):
                    b0 = STREAM_HQ[sh]; hit = [(b0[0], b0[1], 1)]; city = b0[2]
        if not hit:
            continue
        la, lo = max(hit, key=lambda t: t[2])[:2]
        seen.add(u)
        tags = ','.join([t.strip() for t in (s.get('tags') or '').split(',') if t.strip()][:3])[:60]
        hp = (s.get('homepage') or '').strip()
        sh = re.sub(r'^https?://', '', u).split('/')[0].split(':')[0]
        if sh in STREAM_HQ and re.search(STREAM_HQ[sh][4], nm, re.I) and 'radioarg.net' in hp:
            hp = STREAM_HQ[sh][3]                                # the network's own site, not a third-party directory
        rows.append([round(la, 3), round(lo, 3), nm, u, hp[:200] if hp.startswith('http') else '', cc, city[:40], tags,
                     (s.get('codec') or '').upper()[:6], int(s.get('bitrate') or 0), int(s.get('votes') or 0), 0, '', '', '', '', '', ''])
        META[id(rows[-1])] = (s.get('stationuuid') or '', int(s.get('clickcount') or 0), int(s.get('votes') or 0))
        byc += 1
    print('placed by their listed city', byc)
    # PUBLIC BROADCASTERS THE DIRECTORY LACKS (user 2026-11-21: "review the countries of africa for more public radio"): each stream taken from
    # the broadcaster's own site or player, untokenized, probed 2026-11-21; placed at its headquarters. They take every later check like
    # any other station (health, tokens, duplicates), so one that goes dark drops by itself.
    ext = 0
    for la, lo, nm, u, hp, cc, place, tags in EXTRA:
        if u in seen:
            continue
        seen.add(u); rows.append([la, lo, nm, u, hp, cc, place, tags, 'MP3', 128, 0, 0, '', '', '', '', '', '']); META[id(rows[-1])] = ('', 0, 0); ext += 1
    print('public broadcasters added by hand', ext)
    no_tunein(rows)
    countries(rows)
    fcc_fix(rows, F, FPOS)
    places_fix(rows)
    tokens(rows)
    dedupe(rows)
    campus(rows, SCH)
    relocate(rows, FPOS)
    icy_check(rows, SCH, F)
    health(rows, META, out)
    tiers(rows, META)
    # GENRES FROM THE STREAM ITSELF (user 2026-11-21: "yeah do 1"): a station the directory left untagged takes the genre its own stream
    # announces (icy-genre, read by the weekly health check) -- "Pop / Rock", "Christian Contemporary" -- before its name is tried
    nn = nc = ni = 0
    for r in rows:
        g = genres(r[7])
        if not g:
            g = genres(re.sub(r'[/;|]+', ',', GENRE.get(r[3], ''))); ni += bool(g)
        if not g:
            g = name_genres(r[2]); nn += bool(g)
        if SCH.search(r[13] or '') and 'COLLEGE RADIO' not in g:
            g = (g + ['COLLEGE RADIO'])[:3]
        nc += not g
        r[7] = ','.join(g)
    print('genres: from the stream itself', ni, '| from names', nn, '| still none', nc)
    # LOCAL TIME AT THE STATION (user 2026-11-21: "do ... 4"): each row's time zone (timezonefinder, from the world's tz boundaries, offline),
    # as an index r[19] into meta['tz'] so the names are stored once; the card shows the station's clock
    TZ, tzi = [], {}
    try:
        from timezonefinder import TimezoneFinder
        tf = TimezoneFinder()
        for r in rows:
            z = tf.timezone_at(lat=r[0], lng=r[1]) or ''
            if z not in tzi:
                tzi[z] = len(TZ); TZ.append(z)
            r.append(tzi[z])
    except Exception as e:
        print('time zones unavailable', e)
    meta = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'n': len(rows), 'src': host, 'tz': TZ, 'rows': rows}
    json.dump(meta, open(os.path.join(out, 'stations_v1.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
    print('stations', len(S), '-> kept', len(rows), 'from', host, os.path.getsize(os.path.join(out, 'stations_v1.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()

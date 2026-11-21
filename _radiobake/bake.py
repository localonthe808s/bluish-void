#!/usr/bin/env python3
"""RADIO (user 2026-11-21: "make sure those are legal to use this way, build the map view, do a global view").

The global layer: every station in Radio Browser (radio-browser.info, a community-run open directory) that has a map position,
a working HTTPS stream (its last check passed). UK LISTENERS are the line, not UK stations: the file answers 451 in the UK. The page plays each station's OWN stream URL in an
<audio> element: the listener's browser connects straight to the station, nothing is relayed, recorded or re-hosted (the
directory model). Out: OUT/stations_v1.json {built, n, src, rows: [[lat, lon, name, url, homepage, cc, place, tags, codec,
bitrate, votes, 0, '', licensee, city of license, campus, campus domain, 'tag' if the stream's own tag confirmed it]]}.
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


def get(path):
    err = None
    for h in servers():
        try:
            return json.load(urllib.request.urlopen(urllib.request.Request('https://' + h + path, headers=UA), timeout=180)), h
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
            out.setdefault(call, []).append((f[10], f[11], f[27], la, lo))
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
    ('FUNK', r'\bfunk\b'), ('DISCO', r'\bdisco\b'), ('HIP-HOP', r'hip[- ]?hop'), ('RAP', r'\brap\b'), ('REGGAETON', r'reggaeton'), ('REGGAE', r'\breggae\b'),
    ('DANCEHALL', r'dancehall'), ('DEEP HOUSE', r'deep house'), ('HOUSE', r'\bhouse\b'), ('TECHNO', r'\btechno'), ('TRANCE', r'\btrance\b'),
    ('DRUM AND BASS', r'drum ?(and|&|n) ?bass|\bdnb\b'), ('DUBSTEP', r'dubstep'), ('DUB', r'^dub$'), ('AMBIENT', r'\bambient'), ('CHILLOUT', r'chill'),
    ('LOUNGE', r'lounge'), ('DOWNTEMPO', r'downtempo'), ('EXPERIMENTAL', r'experimental|avant'), ('ELECTRONIC', r'electronic|electronica|\belectro\b|\bedm\b'),
    ('DANCE', r'\bdance\b|eurodance'), ('CLASSICAL', r'classical|klassik|cl[aá]sica\b|\bopera\b|baroque|symphon|classic fm|classic radio'), ('CLASSIC COUNTRY', r'classic country'),
    ('BLUEGRASS', r'bluegrass'), ('COUNTRY', r'\bcountry\b'), ('AMERICANA', r'americana'), ('FOLK', r'\bfolk'), ('WORLD', r'world music|\bworld\b'),
    ('AFROBEATS', r'afrobeat'), ('SALSA', r'\bsalsa\b'), ('CUMBIA', r'cumbia'), ('BACHATA', r'bachata'), ('MERENGUE', r'merengue'), ('BANDA', r'^banda$'),
    ('REGIONAL MEXICAN', r'regional mexican|grupera|norte[ñn]a'), ('SERTANEJO', r'sertanej'), ('MPB', r'^mpb$'), ('SAMBA', r'\bsamba\b'), ('SCHLAGER', r'schlager'),
    ('BOLLYWOOD', r'bollywood'), ('LATIN', r'\blatin|latino'), ('GOSPEL', r'gospel'), ('CATHOLIC', r'catholic|cat[oó]lic'),
    ('CHRISTIAN', r'christian|cristian|worship|praise|\bhymns?\b'), ('ISLAMIC', r'islam|quran'), ('OLDIES', r'oldies|golden'),
    ('TOP 40', r'top ?40|top hits|\bcharts?\b|contemporary hits'), ('ADULT CONTEMPORARY', r'adult contemporary|\bac\b'), ('EASY LISTENING', r'easy listening|soft hits'),
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


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else 'out'
    os.makedirs(out, exist_ok=True)
    S, host = get('/json/stations/search?has_geo_info=true&is_https=true&hidebroken=true&limit=200000&order=votes&reverse=true')
    rows, seen = [], set()
    for s in S:
        u = (s.get('url_resolved') or '').strip()
        try:
            la, lo = float(s.get('geo_lat')), float(s.get('geo_long'))
        except (TypeError, ValueError):
            continue
        if not u.startswith('https://') or s.get('lastcheckok') != 1 or not (-90 < la < 90 and -180 <= lo <= 180) or (la == 0 and lo == 0):
            continue
        if s.get('hls') == 1:
            continue                                                # HLS needs a JS player, not <audio> everywhere
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
            if s.get('geo_lat') is not None or not u.startswith('https://') or s.get('lastcheckok') != 1 or s.get('hls') == 1 or u in seen:
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
            added += 1
    print('college stations placed from the FCC', added)
    campus(rows, SCH)
    relocate(rows, FPOS)
    icy_check(rows, SCH, F)
    nn = nc = 0
    for r in rows:
        g = genres(r[7])
        if not g:
            g = name_genres(r[2]); nn += bool(g)
        if SCH.search(r[13] or '') and 'COLLEGE RADIO' not in g:
            g = (g + ['COLLEGE RADIO'])[:3]
        nc += not g
        r[7] = ','.join(g)
    print('genres: from names', nn, '| still none', nc)
    meta = {'built': datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ'), 'n': len(rows), 'src': host, 'rows': rows}
    json.dump(meta, open(os.path.join(out, 'stations_v1.json'), 'w'), separators=(',', ':'), ensure_ascii=False)
    print('stations', len(S), '-> kept', len(rows), 'from', host, os.path.getsize(os.path.join(out, 'stations_v1.json')) // 1024, 'KB')


if __name__ == '__main__':
    main()

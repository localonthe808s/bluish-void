#!/usr/bin/env python3
"""THE COASTAL GATE: for any place in the US, with zero network requests, how far the open sea is, whether a marine
layer is an everyday thing there, and which NWS Surf Zone Forecast covers its beaches. Built for the national LOCAL map,
so that THE BASIN's MARINE LAYER and surf grammar only shows where the sea actually reaches.

DISTANCE. The OSM coastline counts every tidal creek as sea: it runs up the Hudson to Troy and around every marsh. So
the sea is rastered from it and OPENED with a 2 km disk; only water at least ~4 km wide all the way out from the ocean
stays sea. The Chesapeake, Delaware Bay, Long Island Sound, Puget Sound's main channel, Tampa Bay and Monterey Bay
count; SF Bay (behind the Golden Gate), the Hudson and New York's Upper Bay (behind the Narrows), Galveston Bay, the
North Carolina sounds and Lake Pontchartrain do not (their outer beaches do). The Great Lakes are not in the coastline
at all. Distances run to the edge of that open sea, on a 0.25-degree lattice of nodes within 110 km of it.

MARINE LAYER, from data. ERA5 hourly low cloud (Open-Meteo archive, 2025): the share f of local 4-9 AM hours, May-Jul,
with low cloud >= 60 %, at ERA5's 0.5-degree points on US land within 100 km of the open sea (every point west of
114 W, whole degrees elsewhere), each against an inland CONTROL found by walking uphill on the coast-distance field to
200 km inland. excess = f - f(control). Measured (f / control / excess):
    Santa Monica .44/.00/.44  LA downtown .49/.00/.49  Long Beach .66/.00/.66  Pasadena .24/.00/.24
    San Diego .80/.00/.80     San Francisco .65/.02/.63 Monterey .63/.01/.62  Eureka .27/.02/.25
    Astoria .74/.08/.66       Seattle .33/.01/.32       Portland OR .25/.16/.09
    NYC .27/.42/-.15  Rockaway .26/.42/-.16  Montauk .24/.34/-.10  Atlantic City .23/.35/-.12
    Boston .36/.35/.01  Portland ME .30/.30/.00  Outer Banks .08/.20/-.13  Charleston .05/.18/-.13
    Miami .08/.07/.02  Tampa .03/.05/-.02  Galveston .14/.28/-.15  Houston .19/.28/-.10
    Phoenix .00/.01/-.01  Denver .13/.01/.12 (not coastal)  Honolulu .03  Hilo .22
Across the samples the excess runs (10th/50th/90th percentile) -.00/.18/.47 on the Pacific side, -.09/-.02/.01 on the
Gulf and -.11/-.04/.05 on the Atlantic north of 31 N. The flag is excess >= .10 and f >= .15: Portland OR (.09) falls
just outside, Pasadena (.24) and Eureka (.25) well inside. Flagged nodes must also join the coast (see marine()).
  - The Atlantic does NOT pass. Its coast does get morning low cloud (f .23-.36 from NJ to Maine), but in ERA5 inland
    New York and Pennsylvania get as much or more (controls .30-.42), so there is no marine excess to measure at this
    resolution. Sea fog and backdoor stratus on the Northeast shore are real but episodic, not an every-morning layer.
  - The Gulf does NOT pass: South Texas morning stratus (f up to .35 at 28-29 N) is a low-level-jet deck that is
    thicker inland than on the beach. Gulf sea fog is a winter-spring event and was not sampled.
  - Hawaii is never flagged: its morning cloud is trade-wind cumulus banked on the windward slopes (Hilo .22, Honolulu
    .03), not a stratus layer under an inversion, and an island has no inland control.
Three months of one year is a short sample, but the Pacific numbers sit far above the threshold and the Atlantic ones are not
close to it either.

SURF. The NWS Surf Zone Forecast (SRF) offices and zones: api.weather.gov/products/types/SRF/locations names the offices
with a product in its short retention; the zone lists come from the IEM AFOS archive (last 40 products since Jun 1)
for every coastal office, because the Northeast stops for the winter. 24 CONUS + Hawaii offices issue it (plus SJU and
GUM, outside this lattice): AKQ BOX BRO CAR CHS CRP EKA GYX HFO ILM JAX LOX MFL MFR MHX MLB MOB MTR OKX PHI PQR SGX TAE
TBW. LWX, KEY, LIX, LCH, HGX, SEW and the Alaska offices issue none (no archive since 2022). Every UGC is a public
forecast zone (Z) found in zones/v2, except LOX's CAZ364 (LA County Beaches), retired from the zone file and drawn here
with today's CAZ366. Each zone gets a point on its own beach; each node names the nearest zone within 40 km.

OUTPUT. gate.js: LC_GATE (the lattice as one string, ~13 KB with the decoder) and lcCoast(lat, lon) -> null or
{ d, mar, srf: { ugc, wfo, la, lo } | null }; gate.json: the same nodes in the clear, the zone list and the place table.

    python3 marine_gate.py lines.shp ZONES_V2_DIR WORKDIR      # writes WORKDIR/gate.json and WORKDIR/gate.js

lines.shp is coastlines-split-4326 from osmdata.openstreetmap.de (ODbL); ZONES_V2_DIR holds the per-state zone outlines
of _zonebake/bake.py (the same files as cdn.bluishvoid.com/zones/v2). Every download is cached in WORKDIR, and the
Open-Meteo fetch is paced to its free limits (about 6,500 weighted calls, ~85 minutes); a rerun reuses the cache.
"""
import glob, json, math, os, pickle, re, sys, time, urllib.error, urllib.request
import numpy as np, shapefile, shapely
from scipy import ndimage as ndi
from scipy.spatial import cKDTree
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.strtree import STRtree

UA = {'User-Agent': 'bluishvoid coastal gate bake (bluishvoid.com)'}
EARTH = 6371.0
BOXES = {'conus': (-126.5, 23.0, -64.5, 51.0, 0.006), 'hi': (-161.5, 18.0, -153.5, 23.0, 0.003)}
OPEN_R_KM = 2.0            # water must be at least 2 x this wide, all the way from the open sea, to count as sea
G, X0, Y0 = 0.25, -161.0, 18.5
GATE_KM = 100.0
SRF_KM = 40.0
ERA5_YEAR = 2025
HOURS = range(4, 10)       # local 4:00-9:59 AM, the marine layer's hours
LOW_PCT = 60               # an hour counts when ERA5 low cloud cover is at least this
MONTHS = range(5, 8)       # May-Jul, both coasts
MAR_EXCESS = 0.10          # a marine layer needs 10 points more early-morning low cloud than the inland control...
MAR_SHARE = 0.15           # ...and low cloud on at least 15 % of those mornings
SRF_SKIP = ('SJU', 'GUM')  # outside the gate's lattice (CONUS + Hawaii)
SRF_CANDIDATES = ('CAR GYX BOX OKX PHI LWX AKQ MHX ILM CHS JAX MLB MFL KEY TBW TAE MOB LIX LCH HGX CRP BRO '
                  'SGX LOX MTR EKA MFR PQR SEW HFO AJK AFC AFG SJU GUM').split()
SRF_ALIAS = {'CAZ364': 'CAZ366'}   # LOX still heads LA County Beaches with the retired UGC; its outline is today's CAZ366
PLACES = {'Santa Monica': (-118.49, 34.02), 'LA downtown': (-118.24, 34.05), 'Long Beach': (-118.19, 33.77),
          'Pasadena': (-118.14, 34.15), 'San Diego': (-117.16, 32.72), 'San Francisco': (-122.42, 37.77),
          'Monterey': (-121.89, 36.60), 'Eureka': (-124.16, 40.80), 'Portland OR': (-122.68, 45.52),
          'Astoria': (-123.83, 46.19), 'Seattle': (-122.33, 47.61), 'NYC': (-73.99, 40.73), 'Montauk': (-71.95, 41.04),
          'Rockaway': (-73.82, 40.58), 'Atlantic City': (-74.42, 39.36), 'Boston': (-71.06, 42.36),
          'Portland ME': (-70.26, 43.66), 'Outer Banks': (-75.62, 35.91), 'Charleston': (-79.93, 32.78),
          'Miami': (-80.19, 25.76), 'Galveston': (-94.80, 29.30), 'Houston': (-95.37, 29.76), 'Tampa': (-82.46, 27.95),
          'Phoenix': (-112.07, 33.45), 'Denver': (-104.99, 39.74), 'Honolulu': (-157.86, 21.31), 'Hilo': (-155.09, 19.72)}

def log(*a): print(time.strftime('%H:%M:%S'), *a, flush=True)

def get(url, timeout=120):
    for a in range(5):
        try: return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout).read()
        except urllib.error.HTTPError as e:
            if e.code in (400, 404): raise
            log('HTTP', e.code, url[:120]); time.sleep(300 if e.code == 429 else 30)
        except Exception as e:
            log('retry', e); time.sleep(30)
    raise RuntimeError('gave up: ' + url)

def xyz(lon, lat):
    lo, la = np.radians(np.atleast_1d(lon)), np.radians(np.atleast_1d(lat))
    return np.column_stack([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

# ---------------------------------------------------------------- 1. the open sea, from the OSM coastline
def open_sea(shp, work):
    """Rasters the coastline (0.006 deg CONUS, 0.003 deg Hawaii), tells sea from land by the sea-on-the-LEFT rule (a
    seed 1.6 px either side of every segment; each connected region takes the majority), then OPENS the sea with a
    2 km disk and keeps only what is still joined to the edge of the box: water narrower than ~4 km anywhere between it
    and the ocean (rivers, the Hudson above the Narrows, SF Bay behind the Golden Gate, Galveston Bay behind Bolivar
    Roads, the NC sounds behind their inlets, Lake Pontchartrain) stops counting as sea. The Chesapeake, Delaware Bay,
    Long Island Sound, Puget Sound's main channel and Tampa Bay stay open. Returns the open-coast boundary points."""
    fn = os.path.join(work, 'opensea.pkl')
    if os.path.exists(fn): return pickle.load(open(fn, 'rb'))
    sf = shapefile.Reader(shp); res = {}
    for key, (W, S, E, N, px) in BOXES.items():
        nx = int(round((E - W) / px)); ny = int(round((N - S) / px))
        line = np.zeros((ny, nx), bool); sea_seeds, land_seeds = [], []
        for shp_ in sf.iterShapes(bbox=[W, S, E, N]):
            P = np.asarray(shp_.points, dtype=np.float64)
            if len(P) < 2: continue
            X = (P[:, 0] - W) / px; Y = (N - P[:, 1]) / px                       # col, row (row 0 = north)
            dx = np.diff(X); dy = np.diff(Y); L = np.hypot(dx, dy)
            n = np.maximum(1, np.ceil(L * 2.5)).astype(int)
            seg = np.repeat(np.arange(len(L)), n); off = np.arange(n.sum()) - np.repeat(np.cumsum(n) - n, n)
            f = off / np.repeat(n, n)
            xs = np.concatenate([X[seg] + dx[seg] * f, X[-1:]]); ys = np.concatenate([Y[seg] + dy[seg] * f, Y[-1:]])
            c = np.floor(xs).astype(int); r = np.floor(ys).astype(int)
            ok = (c >= 0) & (c < nx) & (r >= 0) & (r < ny); line[r[ok], c[ok]] = True
            m = L > 0.8
            if m.any():   # the left normal of travel, in row/col space (rows run south)
                mx = X[:-1][m] + dx[m] / 2; my = Y[:-1][m] + dy[m] / 2; ux = dx[m] / L[m]; uy = dy[m] / L[m]
                for sgn, store in ((1.6, sea_seeds), (-1.6, land_seeds)):
                    store.append(np.column_stack([np.floor(my - sgn * ux), np.floor(mx + sgn * uy)]).astype(int))
        lab, nl = ndi.label(~line)
        def votes(seeds):
            a = np.concatenate(seeds); a = a[(a[:, 0] >= 0) & (a[:, 0] < ny) & (a[:, 1] >= 0) & (a[:, 1] < nx)]
            return np.bincount(lab[a[:, 0], a[:, 1]], minlength=nl + 1)
        issea = votes(sea_seeds) > votes(land_seeds); issea[0] = False
        sea = issea[lab]; del lab
        samp = (px * 111.32, px * 111.32 * math.cos(math.radians((S + N) / 2)))
        core = ndi.distance_transform_edt(sea, sampling=samp) >= OPEN_R_KM
        opened = ndi.distance_transform_edt(~core, sampling=samp) <= OPEN_R_KM
        lab, nl = ndi.label(opened)
        keep = np.zeros(nl + 1, bool)
        if key == 'conus': keep[np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))] = True
        else: keep[:] = True                                                     # every opened water body is the Pacific
        keep[0] = False
        op = keep[lab]; del lab
        bnd = op & ~ndi.binary_erosion(op); bnd[0, :] = bnd[-1, :] = bnd[:, 0] = bnd[:, -1] = False
        r, c = np.nonzero(bnd)
        res[key] = dict(bound=np.column_stack([W + (c + 0.5) * px, N - (r + 0.5) * px]).astype(np.float32),
                        box=(W, S, E, N, px), shape=(ny, nx), opensea=np.packbits(op))
        log(key, 'sea px', int(sea.sum()), 'open-coast points', len(r))
    pickle.dump(res, open(fn, 'wb'))
    return res

class Coast:
    def __init__(self, R):
        self.R = R
        B = np.concatenate([R['conus']['bound'], R['hi']['bound']]).astype(np.float64)
        self.B = B; self.tree = cKDTree(xyz(B[:, 0], B[:, 1]))
        self.op = {k: np.unpackbits(R[k]['opensea'])[:R[k]['shape'][0] * R[k]['shape'][1]].reshape(R[k]['shape']) for k in R}
    def dist(self, lon, lat):
        d, _ = self.tree.query(xyz(lon, lat)); return 2 * EARTH * np.arcsin(np.clip(d / 2, 0, 1))
    def is_sea(self, lon, lat):
        lon = np.atleast_1d(lon); lat = np.atleast_1d(lat); out = np.zeros(len(lon), bool)
        for k in self.R:
            W, S, E, N, px = self.R[k]['box']
            m = (lon >= W) & (lon < E) & (lat >= S) & (lat < N)
            if m.any(): out[m] = self.op[k][((N - lat[m]) / px).astype(int), ((lon[m] - W) / px).astype(int)] > 0
        return out

# ---------------------------------------------------------------- 2. US land, from the baked forecast zones
def us_zones(zdir):
    skip = set('AK AS GU MP PR VI FM MH PW st'.split())
    polys = []
    for f in sorted(glob.glob(os.path.join(zdir, '*.json'))):
        if os.path.basename(f)[:2] in skip: continue
        for rings in json.load(open(f)).values():
            polys += [Polygon(r) for r in rings if len(r) >= 4]
    return STRtree(polys)

def lattice(coast, ztree, g, lat0):
    """nodes of a g-degree lattice within GATE_KM (+10) of the open coast; kept when inside a US zone, or (sea and
    neighbours across the border) within 35 km of one, so every coastal place has all four corners to interpolate"""
    LO, LA = np.meshgrid(np.arange(-161.0, -66.0 + 1e-9, g), np.arange(lat0, 50.5 + 1e-9, g)); LO = LO.ravel(); LA = LA.ravel()
    m = ((LO > -126) & (LO < -65) & (LA > 23.5)) | ((LO > -161) & (LO < -154) & (LA < 22.6) & (LA > 18.6))
    LO, LA = LO[m], LA[m]; d = coast.dist(LO, LA); m = d <= GATE_KM + 10; LO, LA, d = LO[m], LA[m], d[m]
    pts = shapely.points(LO, LA); inside = np.zeros(len(LO), bool)
    inside[np.unique(ztree.query(pts, predicate='intersects')[0])] = True
    nd = np.full(len(LO), np.inf); cand = np.nonzero(~inside)[0]
    j, dd = ztree.query_nearest(pts[cand], max_distance=0.6, return_distance=True)
    for a, b in zip(j[0], dd): nd[cand[a]] = min(nd[cand[a]], b * 111.0 * math.cos(math.radians(LA[cand[a]])))
    keep = inside | (nd <= 35)
    return dict(lon=LO[keep], lat=LA[keep], d=d[keep], sea=coast.is_sea(LO[keep], LA[keep]), inside=inside[keep])

# ---------------------------------------------------------------- 3. Surf Zone Forecasts
def srf_zones(zdir, work):
    """Which offices issue SRF, and for which zones. api.weather.gov only lists offices with a product in its short
    retention, and the Northeast offices stop for the winter (OKX's last of 2026 was Sep 27, PHI's Sep 30), so the zone
    lists come from the IEM AFOS archive: the last 40 SRF products of every coastal office since Jun 1, every UGC line
    expanded (CAZ362-364, NJZ014>026 style ranges)."""
    fn = os.path.join(work, 'srf_ugcs.json')
    if os.path.exists(fn): S = json.load(open(fn))
    else:
        live = json.loads(get('https://api.weather.gov/products/types/SRF/locations')).get('locations', {})
        S = {}
        for w in sorted(set(SRF_CANDIDATES) | set(live)):
            t = get('https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py?pil=SRF%s&limit=40&sdate=%d-06-01&fmt=text'
                    % (w, ERA5_YEAR + 1)).decode('utf-8', 'replace')
            u = sorted(ugc_lines(t))
            if u: S[w] = u
            time.sleep(1)
        json.dump(S, open(fn, 'w'), indent=0)
    Z, cache = [], {}
    R = None
    for w in sorted(S):
        if w in SRF_SKIP: continue
        for u in S[w]:
            g = SRF_ALIAS.get(u, u); st = g[:2]
            if st not in cache: cache[st] = json.load(open(os.path.join(zdir, st + '.json')))
            if g not in cache[st]: log('SRF zone without an outline', w, u); continue
            Z.append(dict(ugc=u, wfo=w, poly=MultiPolygon([Polygon(r) for r in cache[st][g] if len(r) >= 4]).buffer(0)))
    return Z

def ugc_lines(text):
    out = set(); lines = text.splitlines(); i = 0
    while i < len(lines):
        buf = lines[i].strip()
        if re.match(r'^[A-Z]{2}[CZ]\d{3}[->]', buf):
            while not re.search(r'-\d{6}-\s*$', buf) and i + 1 < len(lines): i += 1; buf += lines[i].strip()
            cur = None; prev = None; rng = False
            for p in re.split(r'([->])', re.sub(r'-\d{6}-\s*$', '', buf)):
                if p == '>': rng = True; continue
                m = re.match(r'^([A-Z]{2}[CZ])?(\d{3})$', p)
                if not m: continue
                cur = m.group(1) or cur; n = int(m.group(2))
                out.update('%s%03d' % (cur, k) for k in (range(prev + 1, n + 1) if rng and prev is not None else [n]))
                prev = n; rng = False
        i += 1
    return out

def srf_points(Z, coast):
    """each zone's point on its own beach: the open-coast point within ~3 km of the zone nearest the zone's centroid"""
    B = coast.B
    for z in Z:
        p = z['poly']; c = p.centroid; b = p.bounds; best = None
        m = (B[:, 0] > b[0] - .05) & (B[:, 0] < b[2] + .05) & (B[:, 1] > b[1] - .05) & (B[:, 1] < b[3] + .05)
        if m.any():
            pb = p.buffer(0.03); cc = B[m]; cc = cc[shapely.contains(pb, shapely.points(cc[:, 0], cc[:, 1]))]
            if len(cc): best = cc[np.argmin(np.hypot((cc[:, 0] - c.x) * math.cos(math.radians(c.y)), cc[:, 1] - c.y))]
        if best is None: rp = p.representative_point(); best = (rp.x, rp.y)
        z['lon'], z['lat'] = round(float(best[0]), 3), round(float(best[1]), 3)

# ---------------------------------------------------------------- 4. ERA5 low cloud
def era5(locs, work):
    """hourly cloud_cover_low, May-Jul, from the Open-Meteo archive (models=era5, timezone=auto so hours are local).
    25 locations a call; one location over 92 days weighs ~6.6 calls, so a call weighs ~165; calls are spaced 45 s
    apart (the archive shares its per-IP limit with api.open-meteo.com, which the live page uses). Every cached file
    in WORKDIR/era5 is read first and only missing locations are fetched."""
    d = os.path.join(work, 'era5'); os.makedirs(d, exist_ok=True); out = {}
    def read(fn):
        D = json.load(open(fn))
        for loc, r in zip(D['locs'], D['resp']):
            t = r['hourly']['time']
            out[tuple(loc)] = dict(mon=np.array([int(s[5:7]) for s in t]), hr=np.array([int(s[11:13]) for s in t]),
                                   v=np.array([np.nan if x is None else x for x in r['hourly']['cloud_cover_low']], float))
    for fn in sorted(glob.glob(os.path.join(d, '*.json'))): read(fn)
    need = [p for p in dict.fromkeys(locs) if p not in out]
    for k in range(0, len(need), 25):
        chunk = need[k:k + 25]; fn = os.path.join(d, 'g%s_%03d.json' % (time.strftime('%Y%m%d%H%M'), k // 25))
        u = ('https://archive-api.open-meteo.com/v1/archive?latitude=%s&longitude=%s&start_date=%d-05-01&end_date=%d-07-31'
             '&hourly=cloud_cover_low&models=era5&timezone=auto') % (','.join('%.2f' % p[1] for p in chunk),
             ','.join('%.2f' % p[0] for p in chunk), ERA5_YEAR, ERA5_YEAR)
        r = json.loads(get(u, 240)); r = r if isinstance(r, list) else [r]
        json.dump({'locs': chunk, 'resp': r}, open(fn, 'w')); read(fn); log('era5', fn)
        if k + 25 < len(need): time.sleep(45)
    return out

def share(rec, months, hours=HOURS, thr=LOW_PCT):
    m = np.isin(rec['mon'], list(months)) & np.isin(rec['hr'], list(hours)) & ~np.isnan(rec['v'])
    return float(np.mean(rec['v'][m] >= thr)) if m.any() else float('nan')

def control(coast, lon, lat):
    """the inland control: walk uphill on the coast-distance field (0.5 deg steps) to 200 km inland or a local max"""
    x, y = lon, lat
    for _ in range(40):
        here = coast.dist(x, y)[0]
        if here >= 200: break
        nb = [(x + a, y + b) for a in (-0.5, 0, 0.5) for b in (-0.5, 0, 0.5) if a or b]
        dd = coast.dist(np.array([p[0] for p in nb]), np.array([p[1] for p in nb])); k = int(np.argmax(dd))
        if dd[k] <= here: break
        x, y = nb[k]
    return (round(x, 2), round(y, 2))

# ---------------------------------------------------------------- 5. encode
ALPHA = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+/'

def nearest_srf(Z, lon, lat):
    srf = np.full(len(lon), -1)
    for i in range(len(lon)):
        best = (SRF_KM, -1); k = math.cos(math.radians(lat[i])); P = Point(lon[i], lat[i])
        for zi, z in enumerate(Z):
            b = z['poly'].bounds
            if lon[i] < b[0] - 0.6 or lon[i] > b[2] + 0.6 or lat[i] < b[1] - 0.45 or lat[i] > b[3] + 0.45: continue
            km = affinity.scale(z['poly'], xfact=k, yfact=1.0, origin=(lon[i], lat[i])).distance(P) * 111.2
            if km <= best[0]: best = (km, zi)
        srf[i] = best[1]
    return srf

def encode(nodes, mar, srf, Z):
    lon, lat = nodes['lon'], nodes['lat']; sd = np.where(nodes['sea'], -nodes['d'], nodes['d'])
    code = np.clip(np.round((sd + 8) / 4), 0, 27).astype(int) + 28 * mar.astype(int)
    row = np.round((lat - Y0) / G).astype(int); col = np.round((lon - X0) / G).astype(int)
    segs = []; cur = None
    for i in np.lexsort((col, row)):
        r, c, z = int(row[i]), int(col[i]), int(srf[i])
        zs = ([x for x in cur[3] if x >= 0] + ([z] if z >= 0 else [])) if cur else []
        if cur and cur[0] == r and cur[1] + len(cur[2]) == c and (not zs or max(zs) - min(zs) <= 63):
            cur[2].append(ALPHA[code[i]]); cur[3].append(z)
        else:
            if cur: segs.append(cur)
            cur = [r, c, [ALPHA[code[i]]], [z]]
    segs.append(cur)
    parts = []
    for r, c, ch, zz in segs:
        p = '%d:%d:%s' % (r, c, ''.join(ch))
        if any(x >= 0 for x in zz):
            base = min(x for x in zz if x >= 0)
            p += ':%d:%s' % (base, ''.join('.' if x < 0 else ALPHA[x - base] for x in zz).rstrip('.'))
        parts.append(p)
    wl = []
    for z in Z:
        if not wl or wl[-1][0] != z['wfo']: wl.append([z['wfo'], []])
        wl[-1][1].append('%s %.3f %.3f' % (z['ugc'], z['lon'], z['lat']))
    return JS_TEMPLATE % dict(g=G, x0=X0, y0=Y0, a=ALPHA, r=','.join(parts),
                              z='|'.join(w + ':' + ','.join(L) for w, L in wl)), len(segs)

JS_TEMPLATE = r'''/* COASTAL GATE (baked by _coastbake/marine_gate.py): for any US place, how far the open sea is, whether a
   marine layer is an everyday thing there, and which NWS Surf Zone Forecast covers its beaches. Zero requests.
   Nodes sit on a %(g)s-degree lattice (row = (lat - y0) / g, col = (lon - x0) / g), one alphabet character each:
   v %% 28 is the signed distance to the open coast, (v %% 28) * 4 - 8 km (negative = over open water, 100 = 100 km or
   more); v >= 28 means a marine layer is an everyday thing there. r holds "row:col:chars[:base:srf]" segments; the
   optional srf string runs parallel to chars and names, per node, the nearest Surf Zone Forecast zone within 40 km
   ('.' = none, else zone number base + alphabet index; trailing dots trimmed). z holds "WFO:UGC lon lat,..." per issuing
   office ('|' between offices) in the order the zone numbers count; lon lat is the zone's point on its own beach.
   Fetch https://api.weather.gov/products/types/SRF/locations/{WFO}, then the latest product, and read the segment
   headed by the zone's UGC (ranges like CAZ362-364 or NJZ014>026 included). */
var LC_GATE = {
  g: %(g)s, x0: %(x0)s, y0: %(y0)s,
  a: '%(a)s',
  r: '%(r)s',
  z: '%(z)s'
};
function lcGateDecode() {
  var G = LC_GATE, m, k, i, j, p, c;
  if (G.m) return G;
  G.m = {}; G.f = {}; G.zl = []; G.w = [];
  p = G.r.split(',');
  for (i = 0; i < p.length; i++) {
    k = p[i].split(':');
    m = (+k[0]) * 1000 + (+k[1]);
    for (j = 0; j < k[2].length; j++) G.m[m + j] = G.a.indexOf(k[2].charAt(j));
    if (k.length > 3) for (j = 0; j < k[4].length; j++) {
      c = k[4].charAt(j);
      if (c !== '.') G.f[m + j] = (+k[3]) + G.a.indexOf(c);
    }
  }
  p = G.z.split('|');
  for (i = 0; i < p.length; i++) {
    m = p[i].split(':'); G.w.push(m[0]); k = m[1].split(',');
    for (j = 0; j < k.length; j++) {
      c = k[j].split(' ');
      G.zl.push({ ugc: c[0], wfo: m[0], lo: +c[1], la: +c[2] });
    }
  }
  return G;
}
/* lcCoast(lat, lon) -> null when the open coast is 100 km or more away and no surf zone is near; otherwise
   { d: km to the open coast (0 on the water; bilinear between nodes), mar: bool, srf: { ugc, wfo, la, lo } | null } */
function lcCoast(lat, lon) {
  var G = lcGateDecode(), x = (lon - G.x0) / G.g, y = (lat - G.y0) / G.g;
  var c0 = Math.floor(x), r0 = Math.floor(y), fx = x - c0, fy = y - r0;
  var dr, dc, v, w, key, sw = 0, sd = 0, sm = 0, best = -1, bw = -1, z;
  for (dr = 0; dr < 2; dr++) for (dc = 0; dc < 2; dc++) {
    w = (dc ? fx : 1 - fx) * (dr ? fy : 1 - fy); key = (r0 + dr) * 1000 + c0 + dc;
    v = G.m[key]; sw += w;
    if (v === undefined) { sd += w * 100; continue; }
    sd += w * ((v %% 28) * 4 - 8);
    if (v >= 28) sm += w;
    if (G.f[key] !== undefined && w > bw) { bw = w; best = G.f[key]; }
  }
  sd = sw ? sd / sw : 100;
  z = best >= 0 ? G.zl[best] : null;
  if (sd >= 100 && !z) return null;
  return { d: Math.max(0, Math.round(sd)), mar: sd < 100 && sm >= 0.5 * sw, srf: z };
}
'''

# ---------------------------------------------------------------- main
def main(shp, zdir, work):
    os.makedirs(work, exist_ok=True)
    coast = Coast(open_sea(shp, work)); ztree = us_zones(zdir)
    nodes = lattice(coast, ztree, G, Y0)
    Z = srf_zones(zdir, work); srf_points(Z, coast)
    log('nodes', len(nodes['lon']), 'srf zones', len(Z))
    # samples: ERA5's own 0.5 deg grid points on US land within GATE_KM; every one west of 114 W (the narrow Pacific
    # band), every other one (whole degrees) elsewhere; plus each one's inland control and the named places
    s5 = lattice(coast, ztree, 0.5, 18.5)
    m = s5['inside'] & ~s5['sea'] & (s5['d'] <= GATE_KM)
    samples = [(round(float(a), 2), round(float(b), 2)) for a, b in zip(s5['lon'][m], s5['lat'][m])]
    samples = [p for p in samples if p[0] < -114 or (p[0] % 1 == 0 and p[1] % 1 == 0)]
    ctrl = {p: control(coast, *p) for p in samples if p[0] > -150}
    places = [tuple(v) for v in PLACES.values()]
    E = era5(samples + sorted(set(ctrl.values())) + places, work)
    mar, table = marine(E, samples, ctrl, nodes, places)
    srf = nearest_srf(Z, nodes['lon'], nodes['lat'])
    js, nseg = encode(nodes, mar, srf, Z)
    open(os.path.join(work, 'gate.js'), 'w').write(js)
    sd = np.where(nodes['sea'], -nodes['d'], nodes['d'])
    json.dump(dict(grid=dict(g=G, x0=X0, y0=Y0), method=dict(hours=list(HOURS), low_pct=LOW_PCT, months=list(MONTHS),
                   year=ERA5_YEAR, mar_excess=MAR_EXCESS, mar_share=MAR_SHARE, open_r_km=OPEN_R_KM, srf_km=SRF_KM),
                   nodes=[[round(float(a), 2), round(float(b), 2), round(float(c), 1), int(mm), int(z)]
                          for a, b, c, mm, z in zip(nodes['lon'], nodes['lat'], sd, mar, srf)],
                   srf=[[z['ugc'], z['wfo'], z['lon'], z['lat']] for z in Z], wfos=sorted(set(z['wfo'] for z in Z)),
                   places=table), open(os.path.join(work, 'gate.json'), 'w'))
    log('gate.js', len(js), 'bytes,', len(nodes['lon']), 'nodes,', nseg, 'segments,', int(mar.sum()), 'marine nodes,',
        int((srf >= 0).sum()), 'nodes with a surf zone')

def marine(E, samples, ctrl, nodes, places):
    """share f of local 4-9 AM hours (May-Jul) with ERA5 low cloud >= 60 %; excess = f minus the inland control's f.
    Interpolated to the gate nodes from the samples within 60 km (inverse distance, nearest three)."""
    rows = []
    for p in samples:
        if p not in E or ctrl.get(p) not in E: continue
        f = share(E[p], MONTHS); fc = share(E[ctrl[p]], MONTHS); rows.append((p[0], p[1], f, f - fc))
    S = np.array(rows)
    log('samples with a control', len(S))
    k = np.cos(np.radians(nodes['lat']))
    mar = np.zeros(len(nodes['lon']), bool)
    for i in range(len(mar)):
        if nodes['lon'][i] < -150: continue           # Hawaii: see the docstring
        dd = np.hypot((S[:, 0] - nodes['lon'][i]) * k[i], S[:, 1] - nodes['lat'][i]) * 111.2
        j = np.argsort(dd)[:3]; j = j[dd[j] <= 60]
        if not len(j): continue
        w = 1 / np.maximum(dd[j], 5) ** 2
        f = np.sum(w * S[j, 2]) / w.sum(); ex = np.sum(w * S[j, 3]) / w.sum()
        mar[i] = ex >= MAR_EXCESS and f >= MAR_SHARE and nodes['d'][i] <= GATE_KM
    # a marine layer comes off the sea: keep only flagged nodes joined (8-neighbour, on the lattice) to a flagged node
    # within 15 km of the open coast. This drops 18 nodes (17 in the Litchfield Hills and southern New Hampshire), where
    # high ground beat its control while the shore itself showed no excess
    rc = {(int(round((b - Y0) / G)), int(round((a - X0) / G))): i for i, (a, b) in enumerate(zip(nodes['lon'], nodes['lat']))}
    seen = set(i for i in np.nonzero(mar)[0] if nodes['d'][i] <= 15 or nodes['sea'][i]); stack = list(seen)
    while stack:
        i = stack.pop(); r0 = int(round((nodes['lat'][i] - Y0) / G)); c0 = int(round((nodes['lon'][i] - X0) / G))
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                j = rc.get((r0 + dr, c0 + dc))
                if j is not None and mar[j] and j not in seen: seen.add(j); stack.append(j)
    log('marine nodes', int(mar.sum()), 'joined to the coast', len(seen))
    keep = np.zeros(len(mar), bool); keep[list(seen)] = True; mar &= keep
    table = {}
    for name, (lo, la) in PLACES.items():
        dd = np.hypot((S[:, 0] - lo) * math.cos(math.radians(la)), S[:, 1] - la); n = S[np.argmin(dd)]
        f = share(E[(lo, la)], MONTHS) if (lo, la) in E else float('nan')
        table[name] = dict(f=round(f, 2), ctrl=round(float(n[2] - n[3]), 2), excess=round(f - float(n[2] - n[3]), 2))
    return mar, table

if __name__ == '__main__':
    main(*sys.argv[1:4])

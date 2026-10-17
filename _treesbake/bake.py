"""NATIONAL STREET TREES (2026-10-17): every McCoy et al. 2022 city inventory baked into THE CITY's NYC tree format.

Source: McCoy, D. et al. 2022, "A dataset of 5 million city trees from 63 US cities: species, location, nativity
status, health, and more", Dryad doi:10.5061/dryad.2jm63xsrf (CC0 1.0), Zenodo mirror records/6726506. One CSV per
city (see fetch.py). New York is skipped: THE CITY has its own 2015 census in /trees/ (_maplab/trees_bake.py).

Output, one directory per city slug, the exact NYC layout:
  <slug>/index.json  {"cell":0.01, "sp":[[common, latin], ...], "tiles":[key, ...], "n": count, "src": "...",
                       "city", "state", "year"}
  <slug>/t_<floor(lat/0.01)>_<floor(lon/0.01)>.json  [[tree_id, dlat, dlon, dbh_in, sp, hs, nbhd], ...]
        dlat/dlon = round((lat - tile south) * 1e5), round((lon - tile west) * 1e5)
        dbh_in = trunk diameter in whole inches (cm / 2.54), 0 unknown, capped 255
        sp = index into sp (-1 unidentified); hs 0 good 1 fair 2 poor 3 alive-no-health 4 dead 5 stump
        nbhd = index into nta.json's list, -1 when the tree has no neighborhood
        tree_id = the dataset's tree_ID number where it has one, else the row's 1-based position in the city CSV
  <slug>/nta.json  {"nta":[[code, name, "", live, denom, good_share, [top sp, ...]], ...], "median": live/denom,
                    "rank_unit": "..."}   (code = name; denom: see RANK below; empty list + rank_unit null when the
                    city has no neighborhood field)
  cities.json  [{slug, name, state, bbox:[w,s,e,n], n, year, nbhd, rank_unit, center:[lat, lon], key}, ...]

Which trees: rows with coordinates, not retired, and not location_type green_space (parks); built_environment and
no_info both kept, since most cities never coded the field and their inventories are street/right-of-way trees.
A few cities ship coordinates in a projected system or with stray points: anything more than 60 km from the
city's median point is dropped. Several geocoded their inventories and parked the trees they could not place on one
centroid (Minneapolis: 2,024 trees on a single point; Ontario, Sacramento, Stockton, Houston: tens of thousands in
such stacks): more than STACK trees at one exact coordinate are dropped and counted as "unlocated".

RANK: the NYC card ranks neighborhoods by street trees a census block, counting the blocks that hold a tree. No
US-wide block field exists here, so the denominator is the same idea on a grid: the number of 100 m x 100 m squares
(hectares) holding any of the neighborhood's inventoried trees. live/denom is "street trees a hectare". (A convex
hull was tried first and failed: mislabeled trees across town stretched Minneapolis's Kenwood to 3,000 ha.) The
page's existing filter (denom >= 30) keeps neighborhoods with 30 or more such hectares.

  python3 -I _treesbake/bake.py <csvdir> <outdir> [nyc_index.json]
"""
import csv, glob, json, math, os, re, sys
from collections import Counter

csv.field_size_limit(1 << 30)
src, out = sys.argv[1], sys.argv[2]
nyc_ix = sys.argv[3] if len(sys.argv) > 3 else None
CELL = 0.01
STACK = 25          # trees at one exact coordinate beyond which none of them count as located

def norm_latin(v):
    """'Platanus x acerifolia', 'Gleditsia triacanthos var. inermis', 'Malus Mill.' -> 'platanus acerifolia',
    'gleditsia triacanthos', 'malus': genus + species epithet, lowercase, hybrid sign and authors dropped"""
    w = [x for x in re.sub(r"[^a-z\s-]", " ", (v or "").lower()).split() if x not in ("x", "spp", "sp", "l", "mill", "var", "ssp", "cv")]
    return " ".join(w[:2])


# NYC's common names, by latin name, so the page's CW_TREE_SEASON (keyed by NYC's names) hits the same species
NYC_NAME = {}
if nyc_ix:
    for com, lat in sorted(json.load(open(nyc_ix))['sp'], key=lambda r: "'" in r[1]):   # the species before its cultivars
        if lat and com:
            NYC_NAME.setdefault(norm_latin(lat), com)
# one common name per latin name, voted across all cities (names.py); fills cities that shipped latin only
LATIN_COMMON = {}
_lc = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'latin_common.json')
if os.path.exists(_lc):
    LATIN_COMMON = json.load(open(_lc))
# the page's CW_TREE_SEASON is keyed by NYC's names: say a species the NYC way wherever it is the same tree
def _nk(c): return re.sub(r'[^a-z]', '', c.lower())
NYC_COMMON = {_nk(c): c for c in NYC_NAME.values()}
ALIAS = {'tuliptree': 'tulip-poplar', 'tuliptreeyellowpoplar': 'tulip-poplar', 'yellowpoplar': 'tulip-poplar',
         'londonplane': 'London planetree', 'londonplanetree': 'London planetree', 'japanesepagodatree': 'Sophora',
         'pagodatree': 'Sophora', 'scholartree': 'Sophora', 'bradfordpear': 'Callery pear', 'flowering pear': 'Callery pear',
         'floweringpear': 'Callery pear', 'pear': 'Callery pear', 'blacktupelo': 'blackgum', 'tupelo': 'blackgum',
         'katsura': 'katsura tree', 'katsuratree': 'katsura tree', 'kentuckycoffeetree': 'Kentucky coffeetree',
         'goldenraintree': 'golden raintree', 'goldenrain': 'golden raintree', 'redbud': 'eastern redbud',
         'crabapple': 'crab apple', 'floweringcrabapple': 'crab apple', 'americanbasswood': 'American linden',
         'basswood': 'American linden', 'redoak': 'northern red oak', 'thornlesshoneylocust': 'honeylocust',
         'honeylocust': 'honeylocust', 'sweetgum': 'sweetgum', 'americansweetgum': 'sweetgum',
         'maidenhairtree': 'ginkgo', 'zelkova': 'Japanese zelkova', 'japaneselilactree': 'Japanese tree lilac',
         'purpleleafplum': 'purple-leaf plum', 'cherryplum': 'purple-leaf plum', 'floweringplum': 'purple-leaf plum',
         'floweringcherry': 'cherry', 'lacebarkelm': 'Chinese elm', 'littleleaflinden': 'littleleaf linden',
         'smallleavedlime': 'littleleaf linden', 'amurmaackia': 'Amur maackia', 'downyserviceberry': 'serviceberry',
         'kousadogwood': 'kousa dogwood', 'crapemyrtle': 'crape myrtle', 'crepemyrtle': 'crape myrtle',
         'commoncrapemyrtle': 'crape myrtle', 'southernliveoak': 'live oak',
         'schumardsoak': 'Shumard oak', 'shumardsoak': 'Shumard oak', 'shumardoak': 'Shumard oak',
         'hybridstrawberrytree': 'strawberry tree', 'brazilianpeppertree': 'Brazilian pepper',
         'californiapeppertree': 'California pepper', 'kwanzanfloweringcherry': 'Japanese flowering cherry',
         'kwanzancherry': 'Japanese flowering cherry', 'ornamentalcherry': 'Japanese flowering cherry',
         'othermaple': 'maple', 'deciduousoak': 'oak', 'appleserviceberry': 'serviceberry',
         'applecrabapple': 'crab apple', 'cherryplumlaurel': 'cherry', 'scarletbottlebrush': 'bottlebrush',
         'oliveTree': 'olive', 'indianlaurelfigtree': 'Indian laurel fig', 'carrotwood': 'carrotwood', 'carrotwoodtree': 'carrotwood',
         'londonplanetreesycamore': 'London planetree', 'sycamorelondonplane': 'London planetree', 'japanesezelkova': 'Japanese zelkova',}
ALIAS = {_nk(k): v for k, v in ALIAS.items()}
def canon(com):
    k = _nk(com)
    return ALIAS.get(k) or NYC_COMMON.get(k) or com

# words that stay capitalized in a lowercased common name
PROPER = set('''American Amur Arizona Atlas Austrian Autumn Bald Bradford Bur California Callery Canary Carolina
Chinese Colorado Cornelian Deodar Douglas Eastern English European Freeman Fremont Himalayan
Indian Italian Japanese Jerusalem Kentucky Korean Kousa Lebanon London Lombardy Manchurian Mexican Mississippi
Mondell Monterey Moreton Norway Ohio Oregon Osage Persian Peruvian Russian Scotch Scots Shumard Siberian Southern
Texas Tatarian Turkish Washington Western Afghan Aleppo Allegheny Australian Brazilian Canadian Chilean Cuban
Florida Hollywood Japan Mediterranean Nuttall Oklahoma Queensland Sargent Schubert Bosnian Carpathian Crimean
Dawn Kwanzan Yoshino Okame Heritage Chanticleer Cleveland Aristocrat Princeton Valley Kanzan Leyland Hinoki
Sawara Formosa Brisbane Bailey Cootamundra Victorian Hong Kong'''.split())


def tidy_common(c):
    c = re.sub(r'\s+', ' ', (c or '').strip())
    if not c or c.upper() == 'NA':
        return ''
    if c.isupper() or c.islower(): c = c.capitalize() if c.isupper() else c
    w = c.split(' ')
    return ' '.join(x if (i > 0 and x in PROPER) or (i == 0 and x in PROPER) else x.lower() for i, x in enumerate(w))


# cities whose common-name column is inventory shorthand: name their trees from the latin alone
ABBREV = {'SiouxFalls'}


def junk(com):
    """what a common-name field says when the row is not an identifiable live tree:
    'skip' (an empty planting site, not a tree), 'stump', 'dead', 'unid' (a tree of unknown kind), or None"""
    c = com.lower()
    if re.search(r'vacant|planting site|\bsite\b|unsuitable|not exist|deleted|no tree|empty', c): return 'skip'
    if 'stump' in c: return 'stump'
    if re.fullmatch(r'dead( tree)?', c): return 'dead'
    if re.fullmatch(r'[\d\W]+', c): return 'unid'
    if re.fullmatch(r'(shrub|species|other( tree)?|unknown( tree)?|tree|unidentified|n/?a|none|unassigned|\(see notes\))', c): return 'unid'
    return None


def hs_of(cond):
    c = (cond or '').strip().lower()
    if c in ('excellent', 'very good', 'good'): return 0
    if c in ('fair',): return 1
    if c in ('poor', 'critical', 'dying', 'very poor'): return 2
    if c in ('dead', 'dead/dying'): return 4
    if c in ('stump',): return 5
    return 3


def cells_ha(pts, lat0):
    """the neighborhood's tree-holding ground: how many 100 m x 100 m squares (1 ha each) hold at least one of its
    trees. NYC's denominator is the census blocks that hold a street tree; this is that idea on a grid, and a
    mislabeled tree across town adds one hectare instead of stretching a hull over the city."""
    kx = math.cos(math.radians(lat0)) * 111320
    return len(set((math.floor(la * 110540 / 100), math.floor(lo * kx / 100)) for la, lo in pts))


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def year_of(v):
    """the 4-digit year in a date string of any layout; 1970 and 1899 are null epochs, not survey years"""
    m = re.search(r'(19[89]\d|20[012]\d)', v or '')
    y = int(m.group(1)) if m else None
    return y if y and y != 1970 and y <= 2022 else None


def nb_name(v):
    """'516 - powderhorn park' -> 'Powderhorn Park'; 'Squirrel hill south' -> 'Squirrel Hill South'"""
    v = re.sub(r'^\d+\s*-\s*', '', re.sub(r'\s+', ' ', v.strip()))
    return ' '.join(w.upper() if w.lower() in ('cbd', 'dtc', 'nw', 'ne', 'sw', 'se') else w if (w.isupper() and len(w) > 1) else '-'.join(x[:1].upper() + x[1:] for x in w.split('-')) for w in v.split(' '))


def slug_of(key):
    return re.sub(r'[^a-z0-9]', '', key.lower())


os.makedirs(out, exist_ok=True)
cities = []
for p in sorted(glob.glob(os.path.join(src, '*_Final_2022-06-18.csv'))):
    key = os.path.basename(p).split('_Final')[0]
    if key == 'NewYork':
        continue
    rows = []
    with open(p, newline='', encoding='utf-8', errors='replace') as f:
        for i, r in enumerate(csv.DictReader(f), 1):
            la, lo = num(r.get('latitude_coordinate')), num(r.get('longitude_coordinate'))
            if la is None or lo is None or not (15 < la < 72 and -170 < lo < -60):
                continue
            if (r.get('location_type') or '').strip() == 'green_space':
                continue
            if (r.get('retired_date') or 'NA').strip() not in ('', 'NA'):
                continue
            rows.append((i, la, lo, r))
    if len(rows) < 500:
        print('skip', key, len(rows), 'usable rows', file=sys.stderr)
        continue
    las = sorted(x[1] for x in rows); los = sorted(x[2] for x in rows)
    mla, mlo = las[len(las) // 2], los[len(los) // 2]
    kx = math.cos(math.radians(mla)) * 111.32
    rows = [x for x in rows if math.hypot((x[1] - mla) * 110.54, (x[2] - mlo) * kx) <= 60]
    # a geocoder's fallback: hundreds of trees on ONE exact coordinate (a street or zip centroid) are not located
    # trees, and on the card they would read as a phantom grove within 200 m. More than STACK at one point: dropped.
    pc = Counter((x[1], x[2]) for x in rows)
    unloc = sum(1 for x in rows if pc[(x[1], x[2])] > STACK)
    rows = [x for x in rows if pc[(x[1], x[2])] <= STACK]
    if len(rows) < 500:
        print('skip', key, len(rows), 'located rows,', unloc, 'unlocated', file=sys.stderr)
        continue
    names = Counter((x[3].get('city') or '').strip() for x in rows)
    states = Counter((x[3].get('state') or '').strip() for x in rows)
    metro = Counter((x[3].get('greater_metro') or '').strip() for x in rows).most_common(1)[0][0]
    # neighborhood: only when most trees carry one and there are at least 3 distinct
    nbc = Counter()
    for x in rows:
        v = (x[3].get('neighborhood') or '').strip()
        if v and v.upper() != 'NA':
            nbc[v] += 1
    has_nb = len(nbc) >= 3 and sum(nbc.values()) >= 0.5 * len(rows)
    yrs = sorted(y for y in (year_of(x[3].get('most_recent_observation')) for x in rows) if y)

    slug = slug_of(key)
    od = os.path.join(out, slug)
    os.makedirs(od, exist_ok=True)
    for old in glob.glob(os.path.join(od, 't_*.json')):
        os.remove(old)
    sp_ix, sp, sp_lat, tiles = {}, [], [], {}
    nb_ix, nb = {}, []     # name -> idx; [name, live, good, Counter sp, pts]
    for i, la, lo, r in rows:
        lat_n = re.sub(r'\s+', ' ', (r.get('scientific_name') or '').strip())
        if lat_n.upper() == 'NA' or lat_n.lower() in ('tree', 'unassigned', 'unknown', 'other', 'vacant'): lat_n = ''
        raw = tidy_common(r.get('common_name'))
        j = junk(raw) if raw else None
        if j == 'skip':
            continue
        hs = hs_of(r.get('condition'))
        if j == 'stump': hs = 5
        if j == 'dead': hs = 4
        if j:
            raw, lat_n = '', ''
        raw = re.sub(r'\s*(species|spp\.?|sp\.)$|:$', '', raw).strip()        # 'elm species', 'yew:' -> the genus
        nl = norm_latin(lat_n)
        if raw and nl and norm_latin(raw) == nl: raw = ''                          # the common field holds the latin
        if re.search(r'^nrwy |^mapl|^jap |\bvar\.?$', raw): raw = ''              # inventory abbreviations
        # a two-word latin names the species: say it the NYC way, else the cross-city vote; a genus keeps its own word
        if key in ABBREV: raw = ''                                                  # glued abbreviations ('maplfrman aut bl')
        com = (NYC_NAME.get(nl) or LATIN_COMMON.get(nl)) if ' ' in nl else None
        com = com or raw or NYC_NAME.get(nl) or LATIN_COMMON.get(nl) or lat_n
        com = canon(com) if com else ''
        if com:
            # one entry per species name, whatever spelling of the latin each row used
            if com not in sp_ix:
                sp_ix[com] = len(sp); sp.append([com, lat_n]); sp_lat.append(Counter())
            s = sp_ix[com]
            if lat_n: sp_lat[s][lat_n] += 1
        else:
            s = -1
        d = num(r.get('diameter_breast_height_CM'))
        dbh = int(round(d / 2.54)) if d and d > 0 else 0
        ni = -1
        if has_nb:
            v = (r.get('neighborhood') or '').strip()
            if v and v.upper() != 'NA' and v.lower() not in ('unassigned', 'unknown', 'none', 'other'):
                v = nb_name(v)
                if v not in nb_ix:
                    nb_ix[v] = len(nb); nb.append([v, 0, 0, Counter(), []])
                ni = nb_ix[v]
                N = nb[ni]
                N[4].append((la, lo))
                if hs <= 3:
                    N[1] += 1; N[2] += hs == 0
                    if s >= 0: N[3][s] += 1
        tid = num(r.get('tree_ID'))
        tid = int(tid) if tid is not None and tid > 0 else i
        ty, tx = math.floor(la / CELL), math.floor(lo / CELL)
        tiles.setdefault((ty, tx), []).append([tid, round((la - ty * CELL) * 1e5), round((lo - tx * CELL) * 1e5), min(dbh, 255), s, hs, ni])
    for s_, c_ in enumerate(sp_lat):
        if c_: sp[s_][1] = c_.most_common(1)[0][0]
    keys = []
    for (ty, tx), tr in tiles.items():
        k = '%d_%d' % (ty, tx); keys.append(k)
        with open(os.path.join(od, 't_' + k + '.json'), 'w') as f:
            json.dump(tr, f, separators=(',', ':'))
    year = (str(yrs[len(yrs) // 20]) if yrs[len(yrs) // 20] == yrs[-1 - len(yrs) // 20] else '%d-%d' % (yrs[len(yrs) // 20], yrs[-1 - len(yrs) // 20])) if yrs else None
    n = sum(len(v) for v in tiles.values())
    city_name = names.most_common(1)[0][0] if names else key
    if metro and names and names.most_common(1)[0][1] < 0.8 * len(rows):
        city_name = metro    # a metro file (Atlanta + Decatur, ...): name it by the metro
    city_name = {'DesMoines': 'Des Moines', 'Washington DC': 'Washington'}.get(city_name, city_name)
    state = states.most_common(1)[0][0]
    src_txt = '%s street tree inventory (%s), via McCoy et al. 2022, Dryad doi:10.5061/dryad.2jm63xsrf (CC0)' % (city_name, year or 'undated')
    with open(os.path.join(od, 'index.json'), 'w') as f:
        json.dump({'cell': CELL, 'sp': sp, 'tiles': sorted(keys), 'n': n, 'src': src_txt, 'city': city_name, 'state': state, 'year': year, 'unlocated': unloc}, f, separators=(',', ':'))
    RU = 'street trees a hectare: live trees over the 100 m grid squares (1 ha) that hold any of the neighborhood\'s inventoried trees'
    nrows = []
    for name, live, good, spc, pts in nb:
        ha = cells_ha(pts, mla)
        nrows.append([name, name, '', live, ha, round(good / live, 3) if live else 0, [k for k, _ in spc.most_common(3)]])
    per = sorted(r_[3] / r_[4] for r_ in nrows if r_[4] >= 30)
    with open(os.path.join(od, 'nta.json'), 'w') as f:
        json.dump({'nta': nrows, 'median': round(per[len(per) // 2], 2) if per else None, 'rank_unit': RU if has_nb else None}, f, separators=(',', ':'))
    lat_all = [x[1] for x in rows]; lon_all = [x[2] for x in rows]
    cities.append({'slug': slug, 'name': city_name, 'state': state,
                   'bbox': [round(min(lon_all), 4), round(min(lat_all), 4), round(max(lon_all), 4), round(max(lat_all), 4)],
                   'n': n, 'year': year, 'nbhd': has_nb, 'rank_unit': RU if has_nb else None,
                   'center': [round(mla, 4), round(mlo, 4)], 'key': key, 'unlocated': unloc})
    print('%-16s %-24s %-14s n=%7d unlocated=%6d tiles=%4d sp=%4d nbhd=%s(%d) year=%s' % (slug, city_name, state, n, unloc, len(keys), len(sp), has_nb, len(nb), year), flush=True)
with open(os.path.join(out, 'cities.json'), 'w') as f:
    json.dump(cities, f, separators=(',', ':'))
print(len(cities), 'cities', sum(c['n'] for c in cities), 'trees')

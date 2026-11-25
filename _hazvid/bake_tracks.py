"""45 YEARS OF STORMS on the map (user 2026-11-25: "do 2" -- draw the storms on the map instead of a video).
Every tropical storm 1980-2024 from IBTrACS v04r01 (cache/ibtracs.csv, see fetch.sh), reaching 34 kt, main tracks, synoptic 6-hour fixes.
Writes out/tracks_v1.json -> cdn hur/tracks_v1.json:
  { t0: '1980-01-01T00:00Z', step: 6, s: [[name, kind, peak_kt, start_step, [dlat, dlon, kt/5, dlat, dlon, kt/5, ...]], ...], y: {year: [hu, ty, cy]} }
kind 0 hurricane (North Atlantic, East/Central Pacific), 1 typhoon (West Pacific), 2 cyclone (everything else). lat/lon are tenths of a degree,
delta-coded from the previous fix (the first fix absolute); lon is unwrapped so a track never jumps 360 at the date line.
"""
import csv, json, os, datetime, collections
HERE = os.path.dirname(os.path.abspath(__file__)); C = os.path.join(HERE, 'cache'); OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
Y0, Y1 = 1980, 2024
T0 = datetime.datetime(1980, 1, 1)
r = csv.reader(open(os.path.join(C, 'ibtracs.csv'))); h = next(r); next(r)
I = {k: h.index(k) for k in ('SID', 'BASIN', 'NAME', 'ISO_TIME', 'LAT', 'LON', 'WMO_WIND', 'USA_WIND', 'TRACK_TYPE')}
S = collections.defaultdict(list); NM = {}
for row in r:
    if row[I['TRACK_TYPE']] != 'main': continue
    t = row[I['ISO_TIME']]
    if int(t[:4]) < Y0 or int(t[:4]) > Y1 + 1: continue
    dt = datetime.datetime.strptime(t, '%Y-%m-%d %H:%M:%S')
    if dt.minute or dt.hour % 6: continue
    try: la = float(row[I['LAT']]); lo = float(row[I['LON']])
    except ValueError: continue
    w = row[I['USA_WIND']].strip() or row[I['WMO_WIND']].strip(); kt = float(w) if w else 0.0
    sid = row[I['SID']]; S[sid].append((dt, la, lo, kt, row[I['BASIN']])); NM[sid] = row[I['NAME']].strip()
kindOf = lambda b: 0 if b in ('NA', 'EP') else 1 if b == 'WP' else 2
out, yr = [], collections.defaultdict(lambda: [0, 0, 0])
for sid, P in S.items():
    P.sort()
    if P[0][0].year < Y0 or P[0][0].year > Y1 or max(p[3] for p in P) < 34: continue
    k = kindOf(P[0][4]); st = int((P[0][0] - T0).total_seconds() // 21600)
    arr, pla, plo, pdeg, prev_step = [], None, None, None, st
    for dt, la, lo, kt in ((p[0], p[1], p[2], p[3]) for p in P):
        step = int((dt - T0).total_seconds() // 21600)
        while step > prev_step + 1 and arr:   # a gap in the fixes: repeat the last one so every entry is one step
            arr += [0, 0, arr[-1]]; prev_step += 1
        prev_step = step
        if pdeg is not None:
            while lo - pdeg > 180: lo -= 360
            while lo - pdeg < -180: lo += 360
        ila, ilo = round(la * 10), round(lo * 10)
        if pla is None: arr += [ila, ilo, round(kt / 5)]
        else: arr += [ila - pla, ilo - plo, round(kt / 5)]
        pla, plo, pdeg = ila, ilo, lo
    nm = NM[sid] if NM[sid] and NM[sid] not in ('NOT_NAMED', 'UNNAMED') else ''
    out.append([nm, k, int(max(p[3] for p in P)), st, arr]); yr[P[0][0].year][k] += 1
out.sort(key=lambda s: s[3])
json.dump({'t0': '1980-01-01T00:00Z', 'step': 6, 's': out, 'y': {str(y): yr[y] for y in range(Y0, Y1 + 1)}}, open(os.path.join(OUT, 'tracks_v1.json'), 'w'), separators=(',', ':'))
print(len(out), 'storms', os.path.getsize(os.path.join(OUT, 'tracks_v1.json')) // 1024, 'KB')

#!/usr/bin/env python3
"""
THE BAKE TRAIL, MEASURED -- nightly, from the per-bake rows the workflow appends
to R2 (cdn.bluishvoid.com/kalshi/trail/<key>_<date>.jsonl; see trail_row() in
kalshi_daily.py). Answers what the noon lock alone cannot (2026-09-07):

  * plan stability -- how often the bet at the first bake of the window is
    still the bet at 11 and at the noon lock, and when it changed;
  * fillable depth -- contracts on offer at the plan's rung through the window,
    the ceiling the strategy sizes against;
  * the floors' lead -- minutes by which the 5-minute sensor, the corroborated
    TWC maximum and the six-hour group reached the settled value before the
    hourly stream did.

Written to trail_study.json; the bake and the panel read it once it has days.
Days without a trail (before 2026-09-07, or R2 misses) are simply absent.
"""
import json, os, sys, statistics, urllib.request, datetime, collections
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, 'trail_study.json')
BASE = 'https://cdn.bluishvoid.com/kalshi/trail/'
from active import ACTIVE                                   # noqa: E402  the traded markets (2026-10-06)
KEYS = tuple(k for k in ('ny_high',) if k in ACTIVE)
# THE LOWS TOO (2026-11-13, user: "yes wire them in"): a low follows its high's city into the study
LOW_KEYS = tuple(k.replace('_high', '_low') for k in KEYS)
DAYS = 60
WIN = {'ny_high': (7, 13)}   # fallback windows; by_hour overrides when present


def fetch(key, day):
    u = BASE + '%s_%s.jsonl' % (key, day)
    try:
        req = urllib.request.Request(u + '?v=' + day, headers={'User-Agent': 'bluishvoid.com trail study'})
        txt = urllib.request.urlopen(req, timeout=40).read().decode('utf-8', 'replace')
    except Exception:
        return []
    rows = []
    for line in txt.splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return rows


def hour_of(r):
    try:
        return int(r['lt'].split(':')[0]) + int(r['lt'].split(':')[1]) / 60.0
    except Exception:
        return None


def settled(key):
    fn = os.path.join(ROOT, ('kalshi_low_%s.json' if key.endswith('_low') else 'kalshi_%s.json') % key.split('_')[0])
    try:
        return {h['date']: h for h in json.load(open(fn)).get('history', []) if h.get('actual') is not None}
    except Exception:
        return {}


def bet_id(b):
    return (b['dir'], b['label']) if b else None


def study(key):
    hist = settled(key)
    today = datetime.date.today()
    w0, w1 = WIN[key]
    days = []
    for i in range(1, DAYS + 1):
        d = (today - datetime.timedelta(days=i)).isoformat()
        rows = fetch(key, d)
        if not rows:
            continue
        rows.sort(key=lambda r: r['t'])
        H = hist.get(d) or {}
        first = next((r for r in rows if (hour_of(r) or 0) >= w0 and r.get('bet')), None)
        at11 = next((r for r in reversed(rows) if (hour_of(r) or 99) <= 11.1 and r.get('bet')), None)
        lock = (H.get('lock') or {}).get('bet')
        # depth at the plan's rung across the window
        depths = []
        for r in rows:
            h = hour_of(r)
            if h is None or h < w0 or h > w1 or not r.get('bet'):
                continue
            b = r['bet']
            for lad in r.get('ladder') or []:
                if lad[0] == b['label']:
                    depths.append(lad[2] if b['dir'] == 'for' else lad[4])
        # the floors' lead: first bake at which each floor had reached the settled
        # whole-degree value, against the hourly stream
        a = H.get('actual')
        lead = {}
        if a is not None:
            def first_at(fn):
                for r in rows:
                    v = fn(r.get('obs') or {})
                    if v is not None and v >= a - 0.5:
                        return hour_of(r)
                return None
            th = first_at(lambda o: o.get('hmax'))
            for name, fn in (('own5', lambda o: o.get('own5')), ('twc', lambda o: o.get('twc') if o.get('twc_corr') else None), ('six', lambda o: o.get('six'))):
                t2 = first_at(fn)
                if th is not None and t2 is not None:
                    lead[name] = round((th - t2) * 60)
        days.append({'date': d, 'bakes': len(rows),
                     'first': bet_id(first['bet']) if first else None, 'first_at': first['lt'] if first else None,
                     'at11': bet_id(at11['bet']) if at11 else None,
                     'lock': bet_id(lock) if lock else None,
                     'stable_11': (bet_id(first['bet']) == bet_id(at11['bet'])) if (first and at11) else None,
                     'stable_lock': (bet_id(first['bet']) == bet_id(lock)) if (first and lock) else None,
                     'depth_med': statistics.median(depths) if depths else None,
                     'depth_first': depths[0] if depths else None,
                     'lead_min': lead or None, 'hit': H.get('hit')})
    S = {'n_days': len(days), 'bakes_per_day': round(statistics.mean(x['bakes'] for x in days), 1) if days else None}
    s11 = [x['stable_11'] for x in days if x['stable_11'] is not None]
    sl = [x['stable_lock'] for x in days if x['stable_lock'] is not None]
    S['stable_to_11'] = [sum(s11), len(s11)]
    S['stable_to_lock'] = [sum(sl), len(sl)]
    dm = [x['depth_med'] for x in days if x['depth_med'] is not None]
    S['depth_contracts_median'] = statistics.median(dm) if dm else None
    for nm in ('own5', 'twc', 'six'):
        L = [x['lead_min'][nm] for x in days if x['lead_min'] and nm in x['lead_min']]
        if L:
            S['lead_' + nm] = {'n': len(L), 'median_min': statistics.median(L), 'led_n': sum(1 for v in L if v > 0)}
    return {'summary': S, 'days': days}


def plan_of(r):
    """The plan a low bake stood on: its bet, or the shadow bet its closed edge court kept."""
    return r.get('bet') or r.get('sbet')


def study_low(key, w0=6, w1=10, eve0=18):
    """THE LOW'S TRAIL. A low has two moments, so two stabilities:
      * the MORNING: the plan at the first bake from 6 AM against the plan locked at 8 AM (lock.bet or lock.shadow);
      * the EVENING BEFORE: tomorrow's pick at the first bake from 6 PM against the evening lock's pick (the trail rows
        carry tomorrow's bet only since 2026-11-13, so the pick is what can be followed back);
    and the floors' lead, mirrored: minutes by which the six-hour minimum and the climate report reached the settled
    low (within half a degree, from above) before the hourly stream did."""
    hist = settled(key)
    today = datetime.date.today()
    days = []
    cache = {}

    def rows_of(d):
        if d not in cache:
            rs = fetch(key, d)
            rs.sort(key=lambda r: r['t'])
            cache[d] = rs
        return cache[d]

    for i in range(1, DAYS + 1):
        dd = today - datetime.timedelta(days=i)
        d = dd.isoformat()
        rows = rows_of(d)
        H = hist.get(d) or {}
        lock = H.get('lock') or {}
        lock_plan = lock.get('bet') or lock.get('shadow')
        first = next((r for r in rows if (hour_of(r) or 0) >= w0 and plan_of(r)), None)
        depths = []
        for r in rows:
            h = hour_of(r)
            b = plan_of(r)
            if h is None or h < w0 or h > w1 or not b:
                continue
            for lad in r.get('ladder') or []:
                if lad[0] == b['label']:
                    depths.append(lad[2] if b['dir'] == 'for' else lad[4])
        # the evening before: yesterday's file, tomorrow's block
        prev = rows_of((dd - datetime.timedelta(days=1)).isoformat())
        efirst = next((r for r in prev if (hour_of(r) or 0) >= eve0 and (r.get('tom') or {}).get('pick')), None)
        eve_pick = (H.get('eve') or {}).get('pick')
        a = H.get('actual')
        lead = {}
        if a is not None and rows:
            def first_at(fn):
                for r in rows:
                    v = fn(r.get('obs') or {})
                    if v is not None and v <= a + 0.5:
                        return hour_of(r)
                return None
            th = first_at(lambda o: o.get('hourly'))
            for name, fn in (('six', lambda o: None if o.get('six_suspect') else o.get('six')), ('cli', lambda o: o.get('cli'))):
                t2 = first_at(fn)
                if th is not None and t2 is not None:
                    lead[name] = round((th - t2) * 60)
        if not rows and not prev:
            continue
        days.append({'date': d, 'bakes': len(rows),
                     'first': bet_id(plan_of(first)) if first else None, 'first_at': first['lt'] if first else None,
                     'lock': bet_id(lock_plan) if lock_plan else None,
                     'stable_lock': (bet_id(plan_of(first)) == bet_id(lock_plan)) if (first and lock_plan) else None,
                     'eve_first': (efirst['tom']['pick'] if efirst else None), 'eve_first_at': (efirst['lt'] if efirst else None),
                     'eve_lock': eve_pick,
                     'stable_eve': (efirst['tom']['pick'] == eve_pick) if (efirst and eve_pick) else None,
                     'depth_med': statistics.median(depths) if depths else None,
                     'lead_min': lead or None, 'hit': H.get('hit'), 'eve_hit': H.get('eve_hit')})
    S = {'n_days': len(days), 'bakes_per_day': round(statistics.mean(x['bakes'] for x in days), 1) if days else None}
    for nm in ('stable_lock', 'stable_eve'):
        v = [x[nm] for x in days if x[nm] is not None]
        S[nm.replace('stable_', 'stable_to_')] = [sum(v), len(v)]
    dm = [x['depth_med'] for x in days if x['depth_med'] is not None]
    S['depth_contracts_median'] = statistics.median(dm) if dm else None
    for nm in ('six', 'cli'):
        Ls = [x['lead_min'][nm] for x in days if x['lead_min'] and nm in x['lead_min']]
        if Ls:
            S['lead_' + nm] = {'n': len(Ls), 'median_min': statistics.median(Ls), 'led_n': sum(1 for v in Ls if v > 0)}
    return {'summary': S, 'days': days, 'kind': 'low'}


def main():
    doc = {'built': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'), 'source': BASE, 'cities': {}}
    for k in KEYS:
        doc['cities'][k] = study(k)
        s = doc['cities'][k]['summary']
        print('%s: %s days, %s bakes/day | first-window bet still the bet at 11: %s | at the noon lock: %s | depth median %s | leads %s' % (
            k, s['n_days'], s['bakes_per_day'], s['stable_to_11'], s['stable_to_lock'], s['depth_contracts_median'],
            {x: s[x] for x in s if x.startswith('lead_')}))
    for k in LOW_KEYS:
        doc['cities'][k] = study_low(k)
        s = doc['cities'][k]['summary']
        print('%s: %s days, %s bakes/day | 6 AM plan still the plan at the 8 AM lock: %s | 6 PM pick still the pick at the evening lock: %s | depth median %s | leads %s' % (
            k, s['n_days'], s['bakes_per_day'], s['stable_to_lock'], s['stable_to_eve'], s['depth_contracts_median'],
            {x: s[x] for x in s if x.startswith('lead_')}))
    json.dump(doc, open(OUT, 'w'), indent=1)
    print('wrote', OUT)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""THE SUNSET LOG (2026-09-26, audit: "make sure our method for scoring and predicting them is as accurate as possible").

A score nobody checks cannot be tuned. Twice a day this loads the LIVE site in a headless browser and asks the site's own
scorer (window._ghUnifiedScore via showGoldenInsight scoreOnly) for every sunrise and sunset in the next 5 days, so the log
holds exactly what visitors were shown, at every lead time, with the full breakdown (to refit the weights later).
Rows are appended to out/rows.jsonl; the workflow merges them into R2 sunset/log.jsonl.

The OUTCOME side (what the sky actually did) is a separate collector -- see sunset_truth.py when a source is chosen.

RAINBOWS TOO (user 2026-11-07, after a rainbow and a quick deep-orange sunset over New York the night before: "yes start logging the
rainbow and golden hour calls"). The same page load asks the site's own window.predictRainbows for every hour of the next 48: each
hour with any score is kept (score, type, direction, sun altitude, the top factors), plus a per-day summary with the two calls the
page shows -- the hour strip's RAINBOW badge (a run of hours >= 30) and the card's chance line (best >= 50). Rows go to
out/rainbow.jsonl; the workflow appends them to R2 sky/rainbow_log.jsonl.
"""
import json, os, sys, time, datetime
from playwright.sync_api import sync_playwright

SITE = os.environ.get('SITE', 'https://bluishvoid.com/')
OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
os.makedirs(OUT, exist_ok=True)

JS = r"""
() => {
  const d = window._dailyData; if (!d || !window.showGoldenInsight) return null;
  const rows = [], now = Date.now();
  for (let i = 0; i < d.sunset.length && i < 8; i++) {
    for (const am of [true, false]) {
      const ev = am ? d.sunrise[i] : d.sunset[i];
      const evMs = new Date(ev).getTime() - (locNowNaive().getTime() - now);   // naive local -> real instant
      if (evMs < now - 30 * 60000 || evMs > now + 5.5 * 864e5) continue;
      const r = window.showGoldenInsight(null, { scoreOnly: true, dayIdx: i, isAm: am });
      if (!r) continue;
      const sp = window._sunPathAt ? window._sunPathAt(new Date(ev).getTime(), am) : null;
      rows.push({ event: am ? 'sunrise' : 'sunset', local: ev, lead_h: Math.round((evMs - now) / 36e5 * 10) / 10,
                  score: r.score, label: r.label, sunBlocked: !!r.sunBlocked,
                  path: sp ? { block: Math.round(sp.block * 100) / 100, low: sp.low, mid: sp.mid, az: sp.az } : null,
                  parts: (r.bd || []).map(x => [x.l, x.v, x.m, x.n]) });
    }
  }
  return { loc: window.LOCATION ? { name: LOCATION.name, lat: LOCATION.lat, lon: LOCATION.lon } : null, rows };
}
"""

RB_JS = r"""
() => {
  const h = window._hourlyData || window._wxHourly, d = window._dailyData;
  if (!h || !h.time || !window.predictRainbows || !window.LOCATION) return null;
  const all = window.predictRainbows(h, d, LOCATION.lat, LOCATION.lon) || [];
  const now = Date.now(), off = (typeof locNowNaive === 'function') ? (locNowNaive().getTime() - now) : 0, hours = [], days = {};
  all.forEach(r => {
    const t = new Date(r.time).getTime() - off; if (t < now - 36e5 || t > now + 48 * 36e5) return;
    const day = String(r.time).slice(0, 10), sc = Math.round(r.score || 0);
    const D = days[day] || (days[day] = { day: day, best: 0, best_at: null, best_type: null, badge_hours: 0 });
    if (sc > D.best){ D.best = sc; D.best_at = r.time; D.best_type = r.type; }
    if (sc >= 30) D.badge_hours++;
    if (sc > 0) hours.push({ local: r.time, lead_h: Math.round((t - now) / 36e5 * 10) / 10, score: sc, type: r.type, dir: r.direction,
      sunAlt: r.sunAlt == null ? null : Math.round(r.sunAlt * 10) / 10, factors: (r.factors || []).slice(0, 4) });
  });
  Object.values(days).forEach(D => { D.badge = D.badge_hours > 0; D.card = D.best >= 50; });
  return { hours: hours, days: Object.values(days) };
}
"""

CITIES = {   # the site boots wherever bv_lastLoc_v4 says (the location-switch harness trick)
    'nyc': None,
    'la': {'lat': 34.0522, 'lon': -118.2437, 'name': 'Los Angeles', 'tz': 'America/Los_Angeles'},
}

def run(city):
    with sync_playwright() as p:
        b = p.chromium.launch(args=['--use-gl=swiftshader', '--enable-unsafe-swiftshader'])
        pg = b.new_page(viewport={'width': 1300, 'height': 900})
        if CITIES[city]:
            seed = dict(CITIES[city]); seed['savedAt'] = int(time.time() * 1000)
            pg.add_init_script("try{localStorage.setItem('bv_lastLoc_v4', %s)}catch(e){}" % json.dumps(json.dumps(seed)))
        pg.goto(SITE + '?log=%d' % int(time.time()), wait_until='domcontentloaded', timeout=90000)
        res = None
        for _ in range(24):                       # the forecast, NWS and light-path fetches settle in 10-40 s
            time.sleep(5)
            try:
                if pg.evaluate('!!window._sunPath && !!window._nwsSky && !!window._dailyData'):
                    time.sleep(3)                  # let the re-score those arrivals trigger finish
                    res = pg.evaluate(JS); break
                res = pg.evaluate(JS)
            except Exception as e:
                print('not ready:', e)
        rb = None
        try: rb = pg.evaluate(RB_JS)
        except Exception as e: print('rainbow read failed:', e)
        b.close()
    if rb:
        stamp0 = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')
        with open(os.path.join(OUT, 'rainbow.jsonl'), 'a') as f:
            f.write(json.dumps({'city': city, 'logged': stamp0, 'days': rb['days'], 'hours': rb['hours']}) + '\n')
        for D in rb['days']: print(city, 'rainbow', D['day'], 'best', D['best'], D['best_type'], 'at', D['best_at'], 'badge' if D['badge'] else '', 'card' if D['card'] else '')
    if not res or not res['rows']:
        print(city, 'no rows'); return 0
    stamp = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%MZ')
    with open(os.path.join(OUT, 'rows.jsonl'), 'a') as f:
        for r in res['rows']:
            r['logged'] = stamp; r['loc'] = res['loc']; r['city'] = city
            f.write(json.dumps(r) + '\n')
    for r in res['rows']:
        print(city, r['event'], r['local'], 'lead', r['lead_h'], 'h ->', r['score'], r['label'], 'path', r['path'] and r['path']['block'])
    return len(res['rows'])

def main():
    open(os.path.join(OUT, 'rows.jsonl'), 'w').close(); open(os.path.join(OUT, 'rainbow.jsonl'), 'w').close()
    n = sum(run(c) for c in CITIES)
    if not n: sys.exit(1)

if __name__ == '__main__':
    main()

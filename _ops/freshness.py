#!/usr/bin/env python3
"""FRESHNESS WATCH (2026-11-17). Every baked file the page reads has a clock on it here.

GitHub's own schedule drops runs: on 11-15..17 the "every 3 hours" bakes (dust cameras, volcano cameras, observatories) ran
two or three times a day, 7-12 hours apart, and nothing said so. A green run with an old file (reference: the Kalshi silent
bail) is invisible the same way. So this reads each file's Last-Modified on the CDN and

  - older than KICK hours: starts that file's workflow (unless one is already running or started within half that time);
  - older than ALARM hours: the run FAILS, which is the alert (GitHub mails a failed run).

A row with no workflow is watched only. Add a row for every new bake. Run by .github/workflows/freshness.yml.
Local dry run: python3 _ops/freshness.py --dry
"""
import email.utils, json, subprocess, sys, time, urllib.request

CDN = 'https://cdn.bluishvoid.com/'
# key on the CDN, workflow file, kick after (h), alarm after (h), months it runs (None = all year)
ROWS = [
    ('goes/video/WORLD/latest.json',  'goes-video.yml',     1,   3, None),   # every 10 min, started by the cron worker
    ('goes/video/WORLD/polar.json',   'polar.yml',          3,  12, None),   # hourly
    ('kalshi/live/kalshi_ny.json',    None,                 0,   3, None),   # the worker's own; watched, never started here
    ('hfr/latest.json',               'hfr.yml',            3,  12, None),   # hourly
    ('neutrino/icecube.json',         'neutrino.yml',       3,  12, None),   # hourly
    ('solar/suvi304.jpg',             'suvi-frame.yml',     3,  12, None),   # hourly
    ('earth/dust/cams.json',          'dust.yml',           5,  24, None),   # every 3 h
    ('volcano/cams_v1.json',          'volcano-cams.yml',   5,  24, None),   # every 3 h
    ('moon/current.jpg',              'moon-frame.yml',     6,  24, None),   # every 4 h
    ('lsr/recent.json',               'lsr.yml',            9,  30, None),   # every 6 h
    ('solar/helio/meta.json',         'helio.yml',          9,  72, None),   # every 6 h; JSOC goes out for a day at a time
    ('argo/latest.json',              'argo.yml',          30,  54, None),   # daily from here down
    ('earth/globe/epic.json',         'epic_globe.yml',    30,  78, None),   # EPIC itself skips days
    ('gw/gw.json',                    'gw.yml',            30,  54, None),
    ('enso/kelvin.json',              'kelvin.yml',        30,  54, None),
    ('sats/core.json',                'sats-night.yml',    30,  54, None),
    ('volcano/latest.json',           'volcano.yml',       30,  54, None),
    ('sunset/log.jsonl',              'sunset-log.yml',    30,  54, None),
    ('flock/alpr_v2.json',            'flock.yml',         30,  54, None),
    ('sargassum/latest.json',         'sargassum.yml',     30,  54, None),
    ('surf/latest.json',              'surf.yml',          30,  54, None),
    ('sea/tide_stations.json',        'currents.yml',      30,  54, None),
    ('snow/resorts_v1.json',          'snow.yml',          30,  54, None),
    ('mig/latest.json',               'migration.yml',     30,  54, None),   # runs every 30 min but rewrites this only for a new night or new frames
    ('birds/rare/index.json',         'birds-rare.yml',    30,  54, None),
    ('foliage/latest.json',           'foliage.yml',       30,  54, (9, 10, 11)),
    ('ocean/mbari_sightings_v1.json', 'mbari-sightings.yml', 192, 360, None),   # weekly
    ('under/mines_active_v1.json',    'mines.yml',        192, 360, None),   # weekly
]


def age_h(key):
    """Hours since the object was written, or None when it cannot be read. The query string steps past the edge's year-long copy."""
    for i in range(3):
        try:
            rq = urllib.request.Request(CDN + key + '?fresh=%d' % time.time(), method='HEAD', headers={'User-Agent': 'bluish-freshness'})
            lm = urllib.request.urlopen(rq, timeout=25).headers.get('Last-Modified')
            return (time.time() - email.utils.parsedate_to_datetime(lm).timestamp()) / 3600 if lm else None
        except Exception as e:
            err = e; time.sleep(3 + 5 * i)
    print('   could not read %s: %s' % (key, err)); return None


def last_run(wf):
    """(busy, hours since the newest run started); (False, None) when it cannot be told."""
    try:
        r = subprocess.run(['gh', 'run', 'list', '--workflow', wf, '--limit', '1', '--json', 'status,createdAt'], capture_output=True, text=True, timeout=60)
        j = json.loads(r.stdout or '[]')
        if not j: return False, None
        t = time.mktime(time.strptime(j[0]['createdAt'], '%Y-%m-%dT%H:%M:%SZ')) - time.timezone
        return j[0]['status'] != 'completed', (time.time() - t) / 3600
    except Exception as e:
        print('   gh run list %s: %s' % (wf, e)); return False, None


def main():
    dry = '--dry' in sys.argv; month = time.gmtime().tm_mon; bad = []; kicked = set()
    for key, wf, kick, alarm, months in ROWS:
        if months and month not in months: print('%-34s out of season' % key); continue
        a = age_h(key)
        if a is None: bad.append('%s unreadable' % key); continue
        note = ''
        if wf and a > kick and wf not in kicked:
            busy, since = last_run(wf)
            if busy: note = 'old; a run is already going'
            elif since is not None and since < max(1.0, kick / 2.0): note = 'old; a run started %.1f h ago' % since
            elif dry: note = 'old; WOULD START %s' % wf
            else:
                r = subprocess.run(['gh', 'workflow', 'run', wf], capture_output=True, text=True, timeout=60); kicked.add(wf)
                note = 'old; STARTED %s' % wf if r.returncode == 0 else 'old; could not start %s: %s' % (wf, (r.stderr or '').strip()[-160:])
        if a > alarm: bad.append('%s is %.1f h old (limit %d h)' % (key, a, alarm)); note = (note + ' ' if note else '') + '** ALARM **'
        print('%-34s %7.1f h  (start %3d, alarm %3d)  %s' % (key, a, kick, alarm, note))
    if bad:
        print('\nSTALE:'); [print('  ' + b) for b in bad]; sys.exit(0 if dry else 1)
    print('\nall fresh')


if __name__ == '__main__':
    main()

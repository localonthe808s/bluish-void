#!/usr/bin/env python3
"""THE SUNSET TRUTH (2026-09-26). What the western sky over New York actually did, to score the site's predictions against.

Started by the cron worker two minutes before sunset (dispatch lands in seconds; GitHub's own cron runs late). Photographs
the west-facing cameras in _maplab/sunset_cams.json at sunset +5/+10/+15/+20 min and measures, in each camera's sky box:
  glow  -- share of sky pixels that are saturated and warm (red / orange / pink / magenta): the colour a good sunset has
  sat   -- mean saturation of the sky
  lum   -- mean brightness (a black frame or a night sky is not a verdict)
The evening's verdict is the best glow across cameras and times (a sunset is judged by its peak). Frames of the peak are kept.
Out: out/truth.jsonl (one row) + out/frames/*.jpg; the workflow appends to R2 sunset/truth.jsonl.
"""
import json, os, sys, time, io, math, datetime, urllib.request
from PIL import Image

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
os.makedirs(os.path.join(OUT, 'frames'), exist_ok=True)
CAMS = json.load(open(os.path.join(os.path.dirname(__file__), 'sunset_cams.json')))
WINDY = os.environ.get('WINDY_KEY', '')

def nyc_sunset_utc(now):
    lat, lon, rad = 40.708, -73.969, math.pi / 180
    base = now - datetime.timedelta(hours=6)
    d0 = datetime.datetime(base.year, base.month, base.day, tzinfo=datetime.timezone.utc)
    n = (d0 - datetime.datetime(2000, 1, 1, 12, tzinfo=datetime.timezone.utc)).total_seconds() / 86400 + 0.5
    M = (357.5291 + 0.98560028 * n) % 360
    C = 1.9148 * math.sin(M * rad) + 0.02 * math.sin(2 * M * rad) + 0.0003 * math.sin(3 * M * rad)
    L = (M + C + 180 + 102.9372) % 360
    dec = math.asin(math.sin(L * rad) * math.sin(23.44 * rad))
    w = math.acos((math.sin(-0.833 * rad) - math.sin(lat * rad) * math.sin(dec)) / (math.cos(lat * rad) * math.cos(dec)))
    J0 = 2451545 + 0.0009 + (-lon) / 360 + round(n - lon / -360 - 0.0009 - (-lon) / 360)
    Js = J0 + 0.0053 * math.sin(M * rad) - 0.0069 * math.sin(2 * L * rad) + w / (2 * math.pi)
    return datetime.datetime.fromtimestamp((Js - 2440587.5) * 86400, datetime.timezone.utc)

def fetch_frame(cam):
    if cam['src'] == 'dot':
        url = 'https://webcams.nyctmc.org/api/cameras/%s/image' % cam['id']
        return urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'bluishvoid-sunset-truth'}), timeout=20).read()
    if cam['src'] == 'windy':
        if not WINDY: return None
        r = urllib.request.Request('https://api.windy.com/webcams/api/v3/webcams/%s?include=images' % cam['id'], headers={'x-windy-api-key': WINDY})
        u = json.load(urllib.request.urlopen(r, timeout=20))['images']['current']['preview']
        return urllib.request.urlopen(u, timeout=20).read()

def measure(jpg, box):
    im = Image.open(io.BytesIO(jpg)).convert('RGB')
    W, H = im.size
    sky = im.crop((int(box[0] * W), int(box[1] * H), int(box[2] * W), int(box[3] * H))).resize((80, 40))
    hsv = sky.convert('HSV'); px = list(hsv.getdata()); n = len(px)
    warm = sum(1 for h, s, v in px if s > 70 and v > 60 and (h < 38 or h > 215))   # PIL hue 0-255: red-orange-yellow, and magenta-pink
    sat = sum(s for h, s, v in px) / n / 255; lum = sum(v for h, s, v in px) / n / 255
    return {'glow': round(warm / n, 3), 'sat': round(sat, 3), 'lum': round(lum, 3)}, im

def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    ss = nyc_sunset_utc(now)
    best, shots = None, []
    for off in (5, 10, 15, 20):
        t = ss + datetime.timedelta(minutes=off)
        wait = (t - datetime.datetime.now(datetime.timezone.utc)).total_seconds()
        if wait > 0: time.sleep(wait)
        for cam in CAMS:
            try:
                jpg = fetch_frame(cam)
                if not jpg: continue
                m, im = measure(jpg, cam['sky'])
            except Exception as e:
                print('frame failed', cam['name'], e); continue
            m.update({'cam': cam['name'], 'min': off}); shots.append(m)
            print(off, cam['name'], m)
            if m['lum'] > 0.08 and (best is None or m['glow'] > best['glow']):
                best = dict(m); im.save(os.path.join(OUT, 'frames', 'peak.jpg'), quality=85)
    row = {'date': (ss - datetime.timedelta(hours=5)).strftime('%Y-%m-%d'), 'sunset_utc': ss.strftime('%Y-%m-%dT%H:%MZ'),
           'glow': best['glow'] if best else None, 'best': best, 'shots': shots}
    # a plain verdict for reading the log by eye; the number is what gets correlated
    g = row['glow']
    row['verdict'] = None if g is None else 'vivid' if g > 0.25 else 'colourful' if g > 0.1 else 'some colour' if g > 0.03 else 'grey'
    with open(os.path.join(OUT, 'truth.jsonl'), 'w') as f: f.write(json.dumps(row) + '\n')
    print(json.dumps({k: row[k] for k in ('date', 'sunset_utc', 'glow', 'verdict')}))

if __name__ == '__main__':
    main()

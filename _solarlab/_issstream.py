"""THE ISS LIVE STREAM, KEPT CURRENT (2026-11-22; user: "add the iss check").

NASA's ISS camera stream on YouTube ends and restarts under a new video id every few months; the one EARTH VIEW embedded
(awQzjn72bI0) ended 2026-10-22 and showed "This live stream recording is not available". This reads NASA's own /streams page
(so the owner is NASA by construction) and takes the entry whose thumbnail carries the LIVE badge and whose title names the
International Space Station and "Official NASA Stream", preferring the High-Definition one. Writes {vid, title, checked} to
<out>/iss_stream.json, or exits 3 (and writes nothing) when nothing qualifies -- the workflow then keeps the last good file,
and the page keeps its built-in id.

YouTube bot-checks GitHub's runners on WATCH pages (a stripped page with no playability), and through the Cloudflare proxy
too, so nothing here reads a watch page; the channel page has served the runner fine. If it ever 429s, the proxy is tried.

Run: python3 _issstream.py <out dir>
"""
import json, os, re, sys, time, urllib.parse, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9'}
PROXY = 'https://proxy.bluishvoid.com/?url='
PAGE = 'https://www.youtube.com/@NASA/streams'

def read(url, proxy=False):
    if proxy:
        url, h = PROXY + urllib.parse.quote(url, safe=''), dict(UA, Origin='https://bluishvoid.com')
    else:
        h = UA
    return urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40).read().decode('utf-8', 'replace')

def page_data():
    for proxy in (False, True):
        try:
            m = re.search(r'var ytInitialData = (\{.*?\});</script>', read(PAGE, proxy), re.S)
            if m: return json.loads(m.group(1))
            print('streams page had no data', '(proxy)' if proxy else '(direct)')
        except Exception as e:
            print('streams page unreadable', '(proxy)' if proxy else '(direct)', e)
    return None

def lockups(o):
    if isinstance(o, dict):
        if 'lockupViewModel' in o: yield o['lockupViewModel']
        for v in o.values(): yield from lockups(v)
    elif isinstance(o, list):
        for v in o: yield from lockups(v)

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(out, exist_ok=True)
    d = page_data()
    if not d: return 3
    best = []
    for r in lockups(d):
        vid, js = r.get('contentId') or '', json.dumps(r)
        t = re.search(r'"title": \{"content": "((?:[^"\\]|\\.)*)"', js)
        title = json.loads('"' + t.group(1) + '"') if t else ''
        live = 'THUMBNAIL_OVERLAY_BADGE_STYLE_LIVE' in js
        ok = live and re.fullmatch(r'[A-Za-z0-9_-]{11}', vid) and 'International Space Station' in title and 'Official NASA Stream' in title
        print(vid, 'LIVE' if live else '----', 'ok' if ok else '  ', title[:90])
        if ok: best.append((0 if 'High-Definition' in title else 1, vid, title))
    if not best:
        print('no live NASA ISS stream on the page; keeping the last one'); return 3
    _, vid, title = sorted(best)[0]
    json.dump({'vid': vid, 'title': title, 'checked': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, open(os.path.join(out, 'iss_stream.json'), 'w'))
    print('chose', vid, title)
    return 0

if __name__ == '__main__':
    sys.exit(main())

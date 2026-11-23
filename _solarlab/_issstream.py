"""THE ISS LIVE STREAM, KEPT CURRENT (2026-11-22; user: "add the iss check").

NASA's ISS camera stream on YouTube ends and restarts under a new video id every few months; the one EARTH VIEW embedded
(awQzjn72bI0) ended 2026-10-22 and showed "This live stream recording is not available". This finds the current one:
NASA's /streams page, the video titled "...International Space Station...", confirmed on its own watch page as LIVE NOW and
owned by the NASA channel. Writes {vid, title, checked} to <out>/iss_stream.json, or exits 3 (and writes nothing) when no
confirmed stream is found -- the workflow then keeps the last good file, and the page keeps its built-in id.

Run: python3 _issstream.py <out dir>
"""
import json, os, re, sys, time, urllib.request

UA = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',
      'Accept-Language': 'en-US,en;q=0.9'}

def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode('utf-8', 'replace')

def candidates():
    h = get('https://www.youtube.com/@NASA/streams')
    out = []
    for m in re.finditer(r'International Space Station', h):
        seg = h[max(0, m.start() - 3000):m.start()]
        ids = re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', seg)
        if ids and ids[-1] not in out: out.append(ids[-1])
    return out

def confirm(vid):
    h = get('https://www.youtube.com/watch?v=' + vid)
    live = '"isLiveNow":true' in h
    owner = re.search(r'"ownerChannelName":"([^"]+)"', h)
    title = re.search(r'"title":"([^"]*International Space Station[^"]*)"', h)
    ok = re.search(r'"playabilityStatus":\{"status":"OK"', h)
    return bool(live and ok and owner and owner.group(1) == 'NASA' and title), (title.group(1) if title else '')

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else '.'
    os.makedirs(out, exist_ok=True)
    for vid in candidates():
        good, title = confirm(vid)
        print(vid, good, title[:90])
        if good:
            json.dump({'vid': vid, 'title': title, 'checked': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, open(os.path.join(out, 'iss_stream.json'), 'w'))
            return 0
    print('no confirmed NASA ISS live stream found; keeping the last one')
    return 3

if __name__ == '__main__':
    sys.exit(main())

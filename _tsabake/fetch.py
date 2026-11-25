"""The newest 8 weekly TSA throughput PDFs from tsa.gov's FOIA reading room into _tsabake/pdf/ (already-held ones are kept, older ones
and their parsed rows are dropped, so parse.py only reads the new week and bake.py always sees exactly the latest 8).

    python3 _tsabake/fetch.py   (prints the weeks; exit 1 if fewer than 8 were found)
"""
import os, re, sys, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__)); PDF = os.path.join(HERE, 'pdf'); OUT = os.path.join(HERE, 'out')
os.makedirs(PDF, exist_ok=True); os.makedirs(OUT, exist_ok=True)
UA = {'User-Agent': 'Mozilla/5.0 (compatible; bluishvoid-bake)'}
MO = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']


def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=300).read()


html = get('https://www.tsa.gov/foia/readingroom').decode('utf-8', 'replace')
links = sorted(set(re.findall(r'/sites/default/files/foia-readingroom/tsa[^"\']*throughput[^"\']*\.pdf', html)))


def start(path):
    m = re.search(r'(' + '|'.join(MO) + r')-(\d{1,2})-(\d{4})', path)
    return (int(m.group(3)), MO.index(m.group(1)) + 1, int(m.group(2))) if m else None


links = sorted([l for l in links if start(l)], key=start, reverse=True)
seen, keep = set(), []
for l in links:               # one file per week (TSA sometimes posts a week twice under two names)
    if start(l) in seen: continue
    seen.add(start(l)); keep.append(l)
    if len(keep) == 8: break
names = [os.path.basename(l) for l in keep]
for l, n in zip(keep, names):
    p = os.path.join(PDF, n)
    if not os.path.exists(p) or os.path.getsize(p) < 100000:
        open(p, 'wb').write(get('https://www.tsa.gov' + l)); print('got', n, os.path.getsize(p) // 1024, 'KB')
    else: print('have', n)
for f in os.listdir(PDF):
    if f.endswith('.pdf') and f not in names: os.remove(os.path.join(PDF, f)); print('dropped', f)
for f in os.listdir(OUT):
    if f.startswith('rows_') and f[5:-5] + '.pdf' not in names: os.remove(os.path.join(OUT, f)); print('dropped', f)
sys.exit(0 if len(names) == 8 else 1)

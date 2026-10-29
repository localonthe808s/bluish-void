#!/usr/bin/env python3
"""WHY A TREE IS NOTABLE (user 2026-10-29: "For notable trees. can the popups explain why they're notable?"). notable_v1.json (Wikidata
CC0) knew only a one-line description ("tree in Eufaula, Alabama"). This adds 'w', the reason, to each tree:
  - with an English Wikipedia article: its opening sentences (the REST summary extract, CC BY-SA; the page credits Wikipedia), which
    nearly always say what the tree is famous for ("deeded ownership of itself", "survived the 1995 bombing");
  - otherwise a line from its Wikidata statements: what kind of tree it is when that is itself the story (a Moon tree, with what a
    Moon tree is), heritage listings, awards, events, what it is named after; and its article in another language as the link.
'ws' says where the reason came from ('wp' or 'wd'). Entries that are not trees (a grass, a forest, a cut disk) are dropped.
    python3 notable_why.py IN_JSON OUT_JSON"""
import json, re, sys, time, urllib.error, urllib.parse, urllib.request
UA = {'User-Agent': 'BLUISH-VOID-tree-bake/1.0 (https://bluishvoid.com)'}
def get(u):
    for k in range(4):
        try: return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
        except urllib.error.HTTPError as e:
            if e.code == 404: return None   # no such page: no retry
            err = e; time.sleep(2 + 3 * k)
        except Exception as e: err = e; time.sleep(2 + 3 * k)
    print('fail', u[:100], err, flush=True); return None
def sentences(t, cap=430):
    t = re.sub(r'\s+', ' ', t or '').strip(); out = ''
    for s in re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"“])', t):
        if out and len(out) + len(s) + 1 > cap: break
        out = (out + ' ' + s).strip()
    return out[:cap + 80]
GENERIC = {'Q10884', 'Q811534', 'Q2075301', 'Q1145976'}   # tree, remarkable tree, individual tree (generic "kind" claims say nothing)
NOT_TREE = {'Q11015': 'grass', 'Q4421': 'forest'}
def main(src, dst):
    J = json.load(open(src)); F = J['f']; ents = {}
    ids = [t['q'] for t in F]
    for i in range(0, len(ids), 50):
        r = get('https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=claims|sitelinks|labels&languages=en&ids=' + '|'.join(ids[i:i + 50]))
        if r: ents.update(r.get('entities', {}))
    ref = set()
    def vals(e, p): return [c['mainsnak'].get('datavalue', {}).get('value', {}).get('id') for c in e.get('claims', {}).get(p, []) if c['mainsnak'].get('datavalue')]
    for e in ents.values():
        for p in ('P31', 'P1435', 'P166', 'P793', 'P138'): ref.update(v for v in vals(e, p) if v)
    lab = {}; ref = sorted(ref)
    for i in range(0, len(ref), 50):
        r = get('https://www.wikidata.org/w/api.php?action=wbgetentities&format=json&props=labels|descriptions&languages=en&ids=' + '|'.join(ref[i:i + 50]))
        for k, v in (r or {}).get('entities', {}).items():
            lab[k] = ((v.get('labels', {}).get('en') or {}).get('value'), (v.get('descriptions', {}).get('en') or {}).get('value'))
    keep = []; nwp = nwd = 0
    for t in F:
        e = ents.get(t['q'], {}); kinds = [v for v in vals(e, 'P31') if v]
        if (any(k in NOT_TREE for k in kinds) and not any(k in GENERIC for k in kinds)) or re.search(r'\b(grass|national forest|disk)\b', t['n'], re.I): print('drop', t['n'], flush=True); continue
        w = ''
        en = e.get('sitelinks', {}).get('enwiki')   # an English article the first pull did not carry
        if en and not t.get('art', '').startswith('https://en.wikipedia.org/'): t['art'] = 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(en['title'].replace(' ', '_'))
        if not t.get('art', '').startswith('https://en.wikipedia.org/'):
            # an English article by the tree's own name -- taken only when the article's own coordinates are within 50 km of the tree
            r = get('https://en.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(t['n'].replace(' ', '_'), safe=''))
            c = (r or {}).get('coordinates')
            if r and r.get('type') == 'standard' and (r.get('title') or '').lower() == t['n'].lower() and c and abs(c['lat'] - t['la']) < .45 and abs(c['lon'] - t['lo']) < .6:
                t['art'] = r['content_urls']['desktop']['page']; print('found', t['n'], '->', r.get('title'), flush=True)
        if t.get('art', '').startswith('https://en.wikipedia.org/wiki/'):
            title = t['art'].rsplit('/wiki/', 1)[1]
            r = get('https://en.wikipedia.org/api/rest_v1/page/summary/' + urllib.parse.quote(urllib.parse.unquote(title), safe=''))
            c = (r or {}).get('coordinates')   # a redirect to a namesake elsewhere (Eufaula's tree -> Athens' article): not this tree
            far = c and (abs(c['lat'] - t['la']) > .45 or abs(c['lon'] - t['lo']) > .6)
            if far: print('far', t['n'], '->', r.get('title'), flush=True); t.pop('art', None)
            w = '' if far else sentences((r or {}).get('extract', ''))
            if w: t['ws'] = 'wp'; nwp += 1
        if not w:
            bits = []
            for k in kinds:
                if k in GENERIC or k not in lab or not lab[k][0] or not re.search(r'tree|oak|maple|elm|pine|cedar|redwood|sequoia|ceiba|cypress', lab[k][0], re.I): continue   # kinds of TREE only (not 'barricade')
                l, d = lab[k]; bits.append('A ' + l + (' (' + d + ')' if d else '') + '.')
            hz = [{'designated heritage property (part IV)': "a heritage property under Ontario's Heritage Act"}.get(lab[v][0], lab[v][0]) for v in vals(e, 'P1435') if v in lab and lab[v][0]]
            if hz: bits.append('Listed as ' + ', '.join(hz) + '.')
            aw = [lab[v][0] for v in vals(e, 'P166') if v in lab and lab[v][0]]
            if aw: bits.append('Recognized: ' + ', '.join(aw) + '.')
            ev = [lab[v][0] for v in vals(e, 'P793') if v in lab and lab[v][0]]
            if ev: bits.append('Part of: ' + ', '.join(ev) + '.')
            nm = [lab[v][0] for v in vals(e, 'P138') if v in lab and lab[v][0]]
            if nm: bits.append('Named after ' + ', '.join(nm) + '.')
            w = ' '.join(bits)
            if w: t['ws'] = 'wd'; nwd += 1
            if not t.get('art'):   # an article in another language is still the best link
                sl = e.get('sitelinks', {})
                for k in ('eswiki', 'frwiki', 'dewiki'):
                    if k in sl: t['art'] = 'https://%s.wikipedia.org/wiki/%s' % (k[:2], urllib.parse.quote(sl[k]['title'].replace(' ', '_'))); break
        if w: t['w'] = w
        keep.append(t); time.sleep(.15)
    J['f'] = keep; J['src_w'] = 'reasons: English Wikipedia summaries (CC BY-SA) and Wikidata statements (CC0)'
    json.dump(J, open(dst, 'w'), separators=(',', ':'), ensure_ascii=False)
    print(len(keep), 'trees;', nwp, 'from Wikipedia,', nwd, 'from Wikidata,', len(keep) - nwp - nwd, 'without a reason', flush=True)
if __name__ == '__main__': main(*sys.argv[1:3])

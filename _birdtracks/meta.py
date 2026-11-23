"""Fetch title / citation / DOI / license for every dataset (every source of every species) into cache/meta_v2.json.
(v1 wrote cache/meta.json keyed by species; v2 is keyed by source id: Movebank handle or 'zenodo:<record>'.)"""
import json, re, sys, time, urllib.request, urllib.parse, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bake import SPECIES, CACHE, src_id
UA = {'User-Agent': 'bluish-birdtracks/1.0'}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
B = 'https://datarepository.movebank.org/server/api'
LIC = {'cc-zero': ('Creative Commons Zero v1.0 Universal', 'https://creativecommons.org/publicdomain/zero/1.0/'),
       'cc-by-4.0': ('Creative Commons Attribution 4.0 International', 'https://creativecommons.org/licenses/by/4.0/')}
MB_OK = {'CC0 1.0 Universal', 'Attribution 4.0 International'}
mp = os.path.join(CACHE, 'meta_v2.json')
meta = json.load(open(mp)) if os.path.exists(mp) else {}
for sp in SPECIES:
    for src in sp['sources']:
        sid = src_id(src)
        if sid in meta:
            continue
        if 'handle' in src:
            d = get(B + '/discover/search/objects?' + urllib.parse.urlencode({'query': 'handle:"%s"' % src['handle'], 'dsoType': 'item'}))
            io = [o['_embedded']['indexableObject'] for o in d['_embedded']['searchResult']['_embedded']['objects']
                  if o['_embedded']['indexableObject']['handle'] == src['handle']][0]
            m = io['metadata']; g = lambda k: (m.get(k) or [{'value': ''}])[0]['value']
            assert g('dc.rights') in MB_OK, (sid, g('dc.rights'))   # CC0 / CC BY only
            doi = g('dc.identifier.doi').replace('doi:', '')
            cite = re.sub(r'<[^>]+>', '', g('mdr.citation.CSE')).strip()
            meta[sid] = dict(source=sid, dataset=io['name'], citation=cite, paper=g('dc.identifier.citation'),
                             doi_or_url='https://doi.org/' + doi if doi else g('dc.identifier.uri'),
                             landing=g('dc.identifier.uri'), license=g('dc.rights'), license_url=g('dc.rights.uri'),
                             repository='Movebank Data Repository')
        else:
            h = get('https://zenodo.org/api/records/' + src['zenodo']); m = h['metadata']
            names = [c['name'] for c in m['creators']]
            au = '; '.join(names[:6]) + (' et al.' if len(names) > 6 else '')
            lic = m.get('license', {}).get('id')
            licname, licurl = LIC[lic]   # KeyError = not CC0 / CC BY: refuse
            dryad = h['doi'].startswith('10.5061/dryad')   # Dryad package mirrored on Zenodo
            cite = '%s (%s). %s. %s. https://doi.org/%s' % (au, m['publication_date'][:4], m['title'], 'Dryad' if dryad else 'Zenodo', h['doi'])
            paper = ''
            for r in m.get('related_identifiers', []):
                if r.get('relation') in ('isSupplementTo', 'isCitedBy', 'isDescribedBy') and r.get('scheme') == 'doi':
                    paper = 'https://doi.org/' + r['identifier'].replace('https://doi.org/', ''); break
            inbo = 'INBO' in json.dumps(m.get('creators', [])) or 'LifeWatch' in m.get('description', '') or 'inbo' in json.dumps(m.get('communities', [])).lower()
            meta[sid] = dict(source=sid, dataset=m['title'], citation=cite, paper=paper, doi_or_url='https://doi.org/' + h['doi'],
                             landing='https://zenodo.org/records/' + src['zenodo'], license=licname + ' (' + lic + ')',
                             license_url=licurl, repository='Dryad (file copy on Zenodo)' if dryad else ('Zenodo (INBO)' if inbo else 'Zenodo'), version=m.get('version'))
            time.sleep(1.5)
        print(sp['key'], '|', sid, '|', meta[sid]['license'], '|', meta[sid]['doi_or_url'], flush=True)
        json.dump(meta, open(mp, 'w'), indent=1, ensure_ascii=False)
json.dump(meta, open(mp, 'w'), indent=1, ensure_ascii=False)

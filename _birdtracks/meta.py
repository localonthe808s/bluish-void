"""Fetch title / citation / DOI / license for every dataset into cache/meta.json."""
import json, re, sys, urllib.request, urllib.parse, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bake import SPECIES, CACHE
UA = {'User-Agent': 'bluish-birdtracks/1.0'}
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
B = 'https://datarepository.movebank.org/server/api'
meta = {}
for sp in SPECIES:
    if 'handle' in sp:
        d = get(B + '/discover/search/objects?' + urllib.parse.urlencode({'query': 'handle:"%s"' % sp['handle'], 'dsoType': 'item'}))
        io = [o['_embedded']['indexableObject'] for o in d['_embedded']['searchResult']['_embedded']['objects']
              if o['_embedded']['indexableObject']['handle'] == sp['handle']][0]
        m = io['metadata']; g = lambda k: (m.get(k) or [{'value': ''}])[0]['value']
        doi = g('dc.identifier.doi').replace('doi:', '')
        cite = re.sub(r'<[^>]+>', '', g('mdr.citation.CSE')).strip()
        meta[sp['key']] = dict(dataset=io['name'], citation=cite, paper=g('dc.identifier.citation'),
                               doi_or_url='https://doi.org/' + doi if doi else g('dc.identifier.uri'),
                               landing=g('dc.identifier.uri'), license=g('dc.rights'), license_url=g('dc.rights.uri'),
                               repository='Movebank Data Repository')
    else:
        h = get('https://zenodo.org/api/records/' + sp['zenodo']); m = h['metadata']
        names = [c['name'] for c in m['creators']]
        au = '; '.join(names[:6]) + (' et al.' if len(names) > 6 else '')
        lic = m.get('license', {}).get('id')
        licname = {'cc-zero': 'Creative Commons Zero v1.0 Universal', 'cc-by-4.0': 'Creative Commons Attribution 4.0 International'}[lic]
        licurl = {'cc-zero': 'https://creativecommons.org/publicdomain/zero/1.0/', 'cc-by-4.0': 'https://creativecommons.org/licenses/by/4.0/'}[lic]
        cite = '%s (%s). %s. Zenodo. https://doi.org/%s' % (au, m['publication_date'][:4], m['title'], h['doi'])
        meta[sp['key']] = dict(dataset=m['title'], citation=cite, paper='', doi_or_url='https://doi.org/' + h['doi'],
                               landing='https://zenodo.org/records/' + sp['zenodo'], license=licname + ' (' + lic + ')',
                               license_url=licurl, repository='Zenodo (INBO)', version=m.get('version'))
    print(sp['key'], '|', meta[sp['key']]['license'], '|', meta[sp['key']]['doi_or_url'])
json.dump(meta, open(os.path.join(CACHE, 'meta.json'), 'w'), indent=1, ensure_ascii=False)

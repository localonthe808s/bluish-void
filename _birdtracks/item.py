import json, sys, urllib.request
UA={'User-Agent':'bluish-birdtracks/1.0'}
B='https://datarepository.movebank.org/server/api'
def get(u): return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60))
def handle(h):
    d=get(B+'/pid/find?id=hdl:'+h) if False else None
    u=get(B+'/discover/search/objects?query=handle:%22'+h+'%22&dsoType=item')
    for o in u['_embedded']['searchResult']['_embedded']['objects']:
        io=o['_embedded']['indexableObject']
        if io['handle']==h: return io
for h in sys.argv[1:]:
    io=handle('10255/'+h if '/' not in h else h)
    if not io: print(h,'NOTFOUND'); continue
    m=io['metadata']
    g=lambda k:' | '.join(x['value'] for x in m.get(k,[]))
    print('#####',io['handle'],io['uuid'],io['name'])
    for k in sorted(m):
        if any(s in k for s in ['rights','citation','identifier','taxon','species','date.issued','coverage','extent','subject']):
            print('  ',k,':',g(k)[:300])
    bs=get(B+'/core/items/'+io['uuid']+'/bundles?embed=bitstreams')
    for b in bs['_embedded']['bundles']:
        if b['name']!='ORIGINAL': continue
        for f in b['_embedded']['bitstreams']['_embedded']['bitstreams']:
            print('   FILE',f['name'],f['sizeBytes'],f['_links']['content']['href'])

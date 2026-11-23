import json, sys, urllib.request, urllib.parse, os
UA={'User-Agent':'bluish-birdtracks/1.0'}
OUT='/Users/vvvaa/bluish-void/_birdtracks/cache/search'
def get(u):
    return json.load(urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60))
for q in sys.argv[1:]:
    u='https://datarepository.movebank.org/server/api/discover/search/objects?'+urllib.parse.urlencode({'query':q,'size':40,'dsoType':'item'})
    try: d=get(u)
    except Exception as e: print(q,'ERR',e); continue
    objs=d['_embedded']['searchResult']['_embedded']['objects']
    print('==',q,d['_embedded']['searchResult']['page']['totalElements'])
    for o in objs:
        io=o['_embedded']['indexableObject']; m=io['metadata']
        def g(k): return '; '.join(x['value'] for x in m.get(k,[]))
        json.dump(io,open(os.path.join(OUT,io['uuid']+'.json'),'w'))
        lic=g('dc.rights') or g('dc.rights.uri') or g('dc.rights.license')
        print(' ',io['handle'],'|',io['name'][:110],'|',lic[:60],'|',g('dc.date.issued')[:10])

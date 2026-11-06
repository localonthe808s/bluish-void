import math, os, urllib.request
from concurrent.futures import ThreadPoolExecutor
z=16
def t(lo,la): n=2**z; return int((lo+180)/360*n), int((1-math.log(math.tan(math.radians(la))+1/math.cos(math.radians(la)))/math.pi)/2*n)
x0,y0=t(-74.025,40.882); x1,y1=t(-73.905,40.698)
jobs=[(x,y) for x in range(x0,x1+1) for y in range(y0,y1+1)]
def get(xy):
    x,y=xy; p='t16/%d_%d.png'%(x,y)
    if os.path.exists(p): return 1
    try:
        b=urllib.request.urlopen(urllib.request.Request('https://mapwarper.net/maps/tile/36301/%d/%d/%d.png'%(z,x,y),headers={'User-Agent':'bluish-void bake'}),timeout=90).read()
        open(p,'wb').write(b); return 1
    except Exception: return 0
with ThreadPoolExecutor(8) as ex: ok=sum(ex.map(get,jobs))
print(ok,'of',len(jobs),'tiles', x0,y0,x1,y1)

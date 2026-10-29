import json, math, numpy as np
from PIL import Image
from scipy import ndimage as nd
from skimage.morphology import skeletonize
from shapely.geometry import LineString, Polygon, Point
from shapely.ops import unary_union
from shapely.strtree import STRtree
z=16; X0,Y0,X1,Y1=19292,24599,19314,24643
W=(X1-X0+1)*256; H=(Y1-Y0+1)*256
mos=np.zeros((H,W,3),np.uint8)
for x in range(X0,X1+1):
  for y in range(Y0,Y1+1):
    try: mos[(y-Y0)*256:(y-Y0+1)*256,(x-X0)*256:(x-X0+1)*256]=np.asarray(Image.open('t16/%d_%d.png'%(x,y)).convert('RGB'))
    except Exception: pass
a=mos.astype(np.int16); r,g,b=a[...,0],a[...,1],a[...,2]; lum=(r+g+b)/3
ink=(lum<100)&(g-r>=14)&(g>b+8)
water=(b>r+8)&(lum>90); ink&=~nd.binary_dilation(nd.binary_opening(water,iterations=2),iterations=30)
blank=(mos.sum(-1)==0); ink&=~nd.binary_dilation(blank,iterations=4)
ink=nd.binary_closing(ink,structure=np.ones((3,3)),iterations=2)
sk=skeletonize(ink)
print('skeleton px', int(sk.sum()))
# PRUNE THE TICKS: peel endpoints 14 times (the hachure and grass ticks are side branches a few px long); real courses lose ~25 m at each end
K=np.ones((3,3),np.uint8)
for it in range(14):
    nbc=nd.convolve(sk.astype(np.uint8),K,mode='constant')-1
    sk=sk&~((nbc<=1)&sk)
print('pruned px', int(sk.sum()))
# WHOLE COMPONENTS, LONGEST PATHS (a stream drawn with two banks skeletonizes to a ladder of loops; cutting at junctions shattered it):
# each component's longest path, then the longest remaining branches, each at least ~45 m
import networkx as nx
lab,n=nd.label(sk,structure=np.ones((3,3)))
objs=nd.find_objects(lab)
def lonlat(px,py):
    n2=2**z; X=X0+px/256; Y=Y0+py/256
    return X/n2*360-180, math.degrees(math.atan(math.sinh(math.pi*(1-2*Y/n2))))
paths=[]
for i,sl in enumerate(objs,1):
    m=lab[sl]==i
    if int(m.sum())<40: continue
    yy,xx=np.nonzero(m); pts=set(zip((xx+sl[1].start).tolist(),(yy+sl[0].start).tolist()))
    G=nx.Graph()
    for p in pts:
        for dx,dy in ((1,0),(0,1),(1,1),(1,-1)):
            q=(p[0]+dx,p[1]+dy)
            if q in pts: G.add_edge(p,q,weight=1.414 if dx and dy else 1)
    while G.number_of_nodes()>=25:
        src=next(iter(G.nodes)); dd=nx.single_source_dijkstra_path_length(G,src); a_=max(dd,key=dd.get)
        dd2,pp=nx.single_source_dijkstra(G,a_); b_=max(dd2,key=dd2.get)
        if dd2[b_]<25: break
        path=pp[b_]; paths.append([lonlat(px+.5,py+.5) for px,py in path])
        G.remove_nodes_from(path)
        G.remove_nodes_from([c for c in list(nx.connected_components(G)) for c in ([] if len(c)>=25 else c)])
        if G.number_of_nodes()<25: break
        G=G.subgraph(max(nx.connected_components(G),key=len)).copy() if nx.number_connected_components(G)==1 else G
print('segments', len(paths))
# join segments whose ends meet (within 6 px ~ 11 m) into courses
def d(a,b): return math.hypot((a[0]-b[0])*84280,(a[1]-b[1])*110540)
joined=True
while joined:
    joined=False
    for i in range(len(paths)):
        if not paths[i]: continue
        for j in range(len(paths)):
            if i==j or not paths[j]: continue
            A,B=paths[i],paths[j]
            for a_,b_,f in ((A[-1],B[0],lambda:A+B),(A[-1],B[-1],lambda:A+B[::-1]),(A[0],B[-1],lambda:B+A),(A[0],B[0],lambda:A[::-1]+B)):
                if d(a_,b_)<14: paths[i]=f(); paths[j]=None; joined=True; break
            if joined: break
        if joined: break
paths=[p for p in paths if p]
print('courses', len(paths))
# what we already have, and Manhattan
old=json.load(open('/Users/vvvaa/bluish-void/ghost-rivers.json'))
oldL=[]
for f in old['features']:
    if f['properties'].get('src')!='Viele 1865': continue
    g=f['geometry']; L=[g['coordinates']] if g['type']=='LineString' else g['coordinates']
    oldL+= [LineString(l) for l in L if len(l)>1]
tree=STRtree(oldL)
hi=json.load(open('/Users/vvvaa/bluish-void/city_boroughs.json'))['hi']
man=unary_union([Polygon(r).buffer(0) for bo in hi if bo['n']=='Manhattan' for r in bo['r'] if len(r)>3]).buffer(0.0006)
new=[]
for p in paths:
    def chaikin(c, k=3):
        for _ in range(k):
            o=[c[0]]
            for a_,b_ in zip(c[:-1],c[1:]): o+=[(a_[0]*.75+b_[0]*.25,a_[1]*.75+b_[1]*.25),(a_[0]*.25+b_[0]*.75,a_[1]*.25+b_[1]*.75)]
            o.append(c[-1]); c=o
        return c
    # smooth the bank-to-bank zigzag: a running mean over ~9 px, then Chaikin, then simplify ~4 m
    P=np.array(p); 
    if len(P)>9: P=np.vstack([P[:1], np.array([P[max(0,i-4):i+5].mean(0) for i in range(1,len(P)-1)]), P[-1:]])
    ls=LineString(chaikin([tuple(q) for q in P.tolist()])).simplify(0.00004)
    if ls.length*95000<120: continue                       # under ~120 m
    if not man.contains(Point(ls.interpolate(0.5,normalized=True))): continue
    # already traced? the share of its points within 35 m of an old course
    pts=[ls.interpolate(k/10,normalized=True) for k in range(11)]
    near=sum(1 for q in pts if any(oldL[o].distance(q)*95000<35 for o in tree.query(q.buffer(0.0005))))
    if near>=6: continue
    new.append({'type':'Feature','properties':{'src':'Viele 1865','line':1,'len_m':round(ls.length*95000)},'geometry':{'type':'LineString','coordinates':[[round(x,5),round(y,5)] for x,y in ls.coords]}})
# A COURSE, NOT A TANGLE: a stream runs somewhere -- its length is at most ~2.6x the span of its ends' box; and a stream is not one of
# a dozen courses packed into the same few blocks (downtown's dense lettering and the made ground there came through as knots)
def span(f):
    C=np.array(f['geometry']['coordinates']); return math.hypot((C[:,0].max()-C[:,0].min())*84280,(C[:,1].max()-C[:,1].min())*110540)
new=[f for f in new if f['properties']['len_m'] <= 3.6*max(span(f),1)]
cells={}
for fi,f in enumerate(new):
    for k in {(int(x/0.0025),int(y/0.0019)) for x,y in f['geometry']['coordinates']}: cells.setdefault(k,set()).add(fi)   # ~210 m cells: COURSES per cell
cells={k:len(v) for k,v in cells.items()}
def crowd(f):
    C=f['geometry']['coordinates']; return max(cells.get((int(x/0.0025),int(y/0.0019)),0) for x,y in C)
new=[f for f in new if crowd(f) <= 5]
# not the edge of a marsh we already fill: drop a course whose points lie mostly in (or within ~20 m of) the 1865 wet ground
mj=json.load(open('/Users/vvvaa/bluish-void/ghost-marsh.json'))
from shapely.geometry import shape as _sh
marsh=unary_union([_sh(f['geometry']).buffer(0.0002) for f in mj['features'] if f['properties'].get('src')=='Viele 1865'])
from shapely.prepared import prep
pm=prep(marsh)
new=[f for f in new if not (sum(pm.contains(Point(c)) for c in f['geometry']['coordinates'])/len(f['geometry']['coordinates']) >= 0.5 and f['properties']['len_m'] > 1.7*max(span(f),1))]   # a winding outline in the marsh, not a channel through it
print('new courses', len(new), 'km', round(sum(f['properties']['len_m'] for f in new)/1000,1))
json.dump({'type':'FeatureCollection','features':new}, open('viele_lines_new.json','w'))
np.save('ink_sk.npy', sk)
# debug render of the patch window
import math
from PIL import ImageDraw
def tpx(lo,la):
    n2=2**z; X=(lo+180)/360*n2; Y=(1-math.log(math.tan(math.radians(la))+1/math.cos(math.radians(la)))/math.pi)/2*n2
    return (X-X0)*256,(Y-Y0)*256
ax0,ay0=tpx(-73.975,40.778); ax1,ay1=tpx(-73.945,40.758)
crop=Image.fromarray(mos[int(ay0):int(ay1),int(ax0):int(ax1)]).copy(); dr=ImageDraw.Draw(crop)
skc=sk[int(ay0):int(ay1),int(ax0):int(ax1)]; arr=np.asarray(crop).copy(); arr[skc]=[255,255,0]; crop=Image.fromarray(arr); dr=ImageDraw.Draw(crop)
for p in paths: dr.line([(tpx(*q)[0]-ax0,tpx(*q)[1]-ay0) for q in p], fill=(255,0,255), width=3)
for o in oldL: dr.line([(tpx(*q)[0]-ax0,tpx(*q)[1]-ay0) for q in o.coords], fill=(255,0,0), width=2)
for f in new: dr.line([(tpx(*q)[0]-ax0,tpx(*q)[1]-ay0) for q in f['geometry']['coordinates']], fill=(0,255,255), width=4)
crop.save('/private/tmp/claude-501/-Users-vvvaa/bc981796-22cc-4e2c-8e03-4ebfe6721d3d/scratchpad/viele_dbg.png')

# overview of the whole island: new courses in cyan, old in red
sc=8; ov=Image.fromarray(mos[::sc,::sc]).copy(); d2=ImageDraw.Draw(ov)
for o in oldL: d2.line([(tpx(*q)[0]/sc,tpx(*q)[1]/sc) for q in o.coords], fill=(255,0,0), width=1)
for f in new: d2.line([(tpx(*q)[0]/sc,tpx(*q)[1]/sc) for q in f['geometry']['coordinates']], fill=(0,255,255), width=2)
ov.save('/private/tmp/claude-501/-Users-vvvaa/bc981796-22cc-4e2c-8e03-4ebfe6721d3d/scratchpad/viele_all.png'); print(ov.size)

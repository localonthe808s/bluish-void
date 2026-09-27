import pickle, json, math, io, urllib.request, concurrent.futures as cf, os
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import box, LineString, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep
R=6378137
X=lambda lon: lon*math.pi/180*R
Y=lambda lat: R*math.log(math.tan(math.pi/4+lat*math.pi/360))
LON=lambda x: x/R*180/math.pi
LAT=lambda y: (2*math.atan(math.exp(y/R))-math.pi/2)*180/math.pi
gs=pickle.load(open('cempolys.pkl','rb'))
C=json.load(open('/Users/vvvaa/bluish-void/city_cemeteries.json'))
cem=unary_union(gs); pc=prep(cem)
excl_lines=[LineString(g) for g in C['p']+C['d'] if len(g)>1]
tombs=[Polygon(g) for g in C['t'] if len(g)>=4]
TS=600.0/math.cos(math.radians(40.7))   # tile size in mercator m (~600 ground m)
PX=2000
tiles=set()
for P in gs:
    x0,y0,x1,y1=P.bounds; X0,Y0,X1,Y1=X(x0),Y(y0),X(x1),Y(y1)
    for i in range(int(X0//TS),int(X1//TS)+1):
        for j in range(int(Y0//TS),int(Y1//TS)+1):
            b=box(LON(i*TS),LAT(j*TS),LON((i+1)*TS),LAT((j+1)*TS))
            if pc.intersects(b): tiles.add((i,j))
tiles=sorted(tiles); print('tiles',len(tiles),flush=True)
def work(t):
    i,j=t; mx0,my0=i*TS,j*TS
    fn='ortho/%d_%d.jpg'%(i,j)
    if not os.path.exists(fn):
        url='https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer/export?bbox=%f,%f,%f,%f&bboxSR=3857&imageSR=3857&size=%d,%d&format=jpg&f=image'%(mx0,my0,mx0+TS,my0+TS,PX,PX)
        for k in range(3):
            try: open(fn,'wb').write(urllib.request.urlopen(url,timeout=120).read()); break
            except Exception as e: err=e
        else: return []
    im=np.asarray(Image.open(fn).convert('RGB')).astype(np.int16)
    L=im.mean(2); sat=im.max(2)-im.min(2)
    bg=ndimage.median_filter(L.astype(np.uint8),size=9).astype(np.int16)
    cand=(L>150)&(L-bg>35)&(sat<60)
    # mask: inside cemetery, off paths/drives/tombs
    m=Image.new('L',(PX,PX)); d=ImageDraw.Draw(m)
    tb=box(LON(mx0),LAT(my0),LON(mx0+TS),LAT(my0+TS))
    topx=lambda lon,lat: ((X(lon)-mx0)/TS*PX,(my0+TS-Y(lat))/TS*PX)
    g=cem.intersection(tb)
    for P in ([g] if g.geom_type=='Polygon' else [q for q in getattr(g,'geoms',[]) if q.geom_type=='Polygon']):
        d.polygon([topx(*c) for c in P.exterior.coords],fill=255)
        for h in P.interiors: d.polygon([topx(*c) for c in h.coords],fill=0)
    wpx=max(2,int(1.6/ (TS/PX*math.cos(math.radians(40.7)))))
    for ln in excl_lines:
        if ln.intersects(tb): d.line([topx(*c) for c in ln.coords],fill=0,width=wpx*2)
    for tp in tombs:
        if tp.intersects(tb): d.polygon([topx(*c) for c in tp.exterior.coords],fill=0,outline=0)
    M=np.asarray(m)>128
    cand&=M
    lab,n=ndimage.label(cand)
    if n==0: return []
    sizes=ndimage.sum(cand,lab,range(1,n+1)); cms=ndimage.center_of_mass(cand,lab,range(1,n+1))
    out=[]
    for (yy,xx),s in zip(cms,sizes):
        if 1<=s<=30:
            mxp=mx0+xx/PX*TS; myp=my0+TS-yy/PX*TS
            out.append((round(LON(mxp),6),round(LAT(myp),6)))
    return out
pts=[]
with cf.ThreadPoolExecutor(6) as ex:
    for k,r in enumerate(ex.map(work,tiles)):
        pts+=r
        if k%20==0: print(k,len(pts),flush=True)
json.dump(pts,open('stones.json','w'))
print('done',len(pts))

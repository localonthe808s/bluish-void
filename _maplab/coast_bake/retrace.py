import numpy as np, json, math
from scipy.ndimage import gaussian_filter
from lut2 import load
tiles=[load(f) for f in ('t_canyon.nc','t_south.nc','t_east.nc')]; MED=load('gmrt_med.nc')
sm=[]
for T in tiles+[MED]:
    z=np.where(np.isfinite(T[0]),T[0],0).astype(np.float32); sm.append((gaussian_filter(z,1.2),)+tuple(T[1:]))
def depth(lon,lat):
    for T in sm:
        z,LON0,LAT1,DLON,DLAT=T; ny,nx=z.shape
        fx=(lon-LON0)/DLON-0.5; fy=(LAT1-lat)/DLAT-0.5
        if 2<=fx<nx-3 and 2<=fy<ny-3:
            i,j=int(fx),int(fy); tx,ty=fx-i,fy-j
            return z[j,i]*(1-tx)*(1-ty)+z[j,i+1]*tx*(1-ty)+z[j+1,i]*(1-tx)*ty+z[j+1,i+1]*tx*ty
    return None
coarse=[(p['lon'],p['lat']) for p in json.load(open('canyon_trace2.json'))]
kx=lambda la: 111.32*math.cos(math.radians(la))
# smooth the coarse course and densify every 150 m
C=np.array(coarse); 
for _ in range(3): C[1:-1]=(C[:-2]+2*C[1:-1]+C[2:])/4
seg=[0.0]
for a,b in zip(C[:-1],C[1:]): seg.append(seg[-1]+math.hypot((b[0]-a[0])*kx(a[1]),(b[1]-a[1])*111.0))
L=seg[-1]; s=np.arange(0,L,0.15)
lon=np.interp(s,seg,C[:,0]); lat=np.interp(s,seg,C[:,1])
out=[]; prev=None
for k in range(len(s)):
    k0,k1=max(0,k-3),min(len(s)-1,k+3)
    tx=(lon[k1]-lon[k0])*kx(lat[k]); ty=(lat[k1]-lat[k0])*111.0; tl=math.hypot(tx,ty) or 1
    nx,ny=-ty/tl,tx/tl                       # across-channel unit (km)
    best=None
    for off in np.arange(-1.5,1.51,0.05):
        lo=lon[k]+nx*off/kx(lat[k]); la=lat[k]+ny*off/111.0
        if prev is not None and math.hypot((lo-prev[0])*kx(la),(la-prev[1])*111)>0.6: continue   # no jumping to a neighbour
        z=depth(lo,la)
        if z is None: continue
        sc=z+8*abs(off)
        if best is None or sc<best[0]: best=(sc,lo,la,z)
    if best: prev=(best[1],best[2]); out.append(prev+(best[3],))
P=np.array([[a,b] for a,b,_ in out])
for _ in range(2): P[1:-1]=(P[:-2]+2*P[1:-1]+P[2:])/4        # light smoothing: 150 m noise, not the meanders
def rdp(pts,eps):
    if len(pts)<3: return list(pts)
    a,b=pts[0],pts[-1]; dx,dy=(b[0]-a[0])*kx(a[1]),(b[1]-a[1])*111; Lb=math.hypot(dx,dy) or 1
    d=[abs(dy*(p[0]-a[0])*kx(a[1])-dx*(p[1]-a[1])*111)/Lb for p in pts[1:-1]]; i=int(np.argmax(d))
    if d[i]>eps: return rdp(pts[:i+2],eps)[:-1]+rdp(pts[i+1:],eps)
    return [pts[0],pts[-1]]
S=rdp([tuple(p) for p in P],0.04)       # 40 m tolerance
print('course %.0f km, %d thalweg points -> %d kept; head %.0f m end %.0f m'%(L,len(P),len(S),-out[0][2],-out[-1][2]))
json.dump([[round(a,4),round(b,4)] for a,b in S],open('canyon_refined.json','w'))

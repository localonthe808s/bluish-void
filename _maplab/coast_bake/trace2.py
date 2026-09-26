import numpy as np, math, json
from scipy.ndimage import uniform_filter, gaussian_filter
R=6378137.0; X0,Y0,X1,Y1=(-8682920,4028802,-7235766,5311971)
Z=np.load('coast3_Z2x.npy'); H2,W2=Z.shape; mpp=(X1-X0)/W2*math.cos(math.radians(38.5))
Zs=gaussian_filter(Z,1.0); inc=Zs-uniform_filter(Zs,int(8000/mpp))
def ij(lat,lon): return (Y1-R*math.log(math.tan(math.pi/4+lat*math.pi/360)))/(Y1-Y0)*H2, (lon*math.pi/180*R-X0)/(X1-X0)*W2
def ll(y,x):
    lon=(X0+x/W2*(X1-X0))/R*180/math.pi; Y=Y1-y/H2*(Y1-Y0); return (2*math.atan(math.exp(Y/R))-math.pi/2)*180/math.pi, lon
def walk(y,x,heading,sign,maxn=800):
    """follow the most incised line; sign=+1 walks down (floor may not climb much), -1 walks up"""
    step=1000/mpp; path=[]; weak=0
    for n in range(maxn):
        best=None
        for da in np.linspace(-1.5,1.5,45):
            a=heading+da; yy=y+math.sin(a)*step; xx=x+math.cos(a)*step
            if not (0<=yy<H2-1 and 0<=xx<W2-1): continue
            sc=inc[int(yy),int(xx)]+15*abs(da)
            if best is None or sc<best[0]: best=(sc,yy,xx,a)
        if best is None: break
        _,y2,x2,a2=best
        dz=Zs[int(y2),int(x2)]-Zs[int(y),int(x)]
        if sign>0 and dz>150: break
        if sign<0 and dz<-60: break
        heading=0.5*heading+0.5*a2; y,x=y2,x2; path.append((y,x))
        weak=weak+1 if inc[int(y),int(x)]>-30 else 0
        if weak>=18: path=path[:-18]; break
    return path
y,x=ij(39.439,-72.179)
down=walk(y,x,math.atan2(0.8,1.0),+1)          # down-slope: south-east, screen y grows south
up=walk(y,x,math.atan2(-0.8,-1.0),-1,200)       # up-slope: north-west
pts=list(reversed(up))+[(y,x)]+down
out=[dict(lat=round(ll(*p)[0],3),lon=round(ll(*p)[1],3),depth=int(-Zs[int(p[0]),int(p[1])]),cut=int(-inc[int(p[0]),int(p[1])])) for p in pts]
km=len(pts)-1
print('traced %d km: head %s' % (km, out[0]))
print('end   ', out[-1])
for q in out[::25]: print('  ',q)
json.dump(out,open('canyon_trace2.json','w'))

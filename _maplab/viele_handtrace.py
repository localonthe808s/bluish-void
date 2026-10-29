"""HAND-PLACED, INK-SNAPPED (2026-10-28): rough polylines read off the sheet by eye, densified every 6 px, each point pulled to the darkest
pixel within 6 px across the line, then smoothed. For the faint lines whose ink matches the street ruling (no automatic rule separates them)."""
import json, math, sys, numpy as np
from scipy import ndimage as nd
z=16; X0,Y0=19292,24599
def lonlat(px,py):
    n2=2**z; X=X0+px/256; Y=Y0+py/256
    return X/n2*360-180, math.degrees(math.atan(math.sinh(math.pi*(1-2*Y/n2))))
def trace(crop, ox, oy, rough):
    g=nd.gaussian_filter(crop.astype(float).mean(-1),1.2)
    P=[]
    for (a,b) in zip(rough[:-1],rough[1:]):
        n=max(2,int(math.hypot(b[0]-a[0],b[1]-a[1])/6))
        for k in range(n): P.append((a[0]+(b[0]-a[0])*k/n, a[1]+(b[1]-a[1])*k/n))
    P.append(rough[-1]); out=[]
    for i,(x,y) in enumerate(P):
        j=min(len(P)-1,i+1); h=max(0,i-1); tx,ty=P[j][0]-P[h][0],P[j][1]-P[h][1]; L=math.hypot(tx,ty) or 1; nx,ny=-ty/L,tx/L
        best=None
        for s in range(-6,7):
            qx,qy=int(round(x+nx*s)),int(round(y+ny*s))
            if 0<=qy<g.shape[0] and 0<=qx<g.shape[1]:
                v=g[qy,qx]+abs(s)*1.5
                if best is None or v<best[0]: best=(v,qx,qy)
        out.append((best[1],best[2]))
    A=np.array(out,float)
    if len(A)>5: A=np.vstack([A[:1],np.array([A[max(0,i-2):i+3].mean(0) for i in range(1,len(A)-1)]),A[-1:]])
    return [lonlat(x+ox+.5,y+oy+.5) for x,y in A]

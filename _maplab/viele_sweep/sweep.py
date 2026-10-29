import numpy as np, cv2, math, json, sys
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage as nd
Image.MAX_IMAGE_PIXELS=None
z=16; X0,Y0=19292,24599
C=np.load('poly.npy')
def D(x,y): x,y=np.asarray(x)/1e4,np.asarray(y)/1e4; return np.stack([np.ones_like(x),x,y,x*x,x*y,y*y,x**3,x*x*y,x*y*y,y**3],-1)
def r2m(x,y): d=D(x,y); return d@C[0], d@C[1]
def m2ll(px,py):
    n2=2**z; X=X0+np.asarray(px)/256; Y=Y0+np.asarray(py)/256
    return X/n2*360-180, np.degrees(np.arctan(np.sinh(np.pi*(1-2*Y/n2))))
def ll2m(lo,la):
    n2=2**z; X=(np.asarray(lo)+180)/360*n2; Y=(1-np.log(np.tan(np.radians(la))+1/np.cos(np.radians(la)))/np.pi)/2*n2
    return (X-X0)*256,(Y-Y0)*256
# inverse (mosaic px -> Rumsey px), fitted on a grid of the forward map
gx,gy=np.meshgrid(np.linspace(800,19400,80),np.linspace(600,5800,30)); mx,my=r2m(gx.ravel(),gy.ravel())
Ai=D(mx,my); Ci=np.stack([np.linalg.lstsq(Ai,gx.ravel(),rcond=None)[0],np.linalg.lstsq(Ai,gy.ravel(),rcond=None)[0]])
def m2r(px,py): d=D(px,py); return d@Ci[0], d@Ci[1]
R=None
def rum():
    global R
    if R is None: R=np.asarray(Image.open('rumsey_full.png').convert('RGB'))
    return R
def crops():
    out=[]
    for y0 in (1050,2450,3850):
        for x0 in range(900,18400,1900): out.append((x0,y0,2000,1500))
    return out
def render(k, extra=None):
    x0,y0,w,h=crops()[k]; im=Image.fromarray(rum()[y0:y0+h,x0:x0+w]).copy(); d=ImageDraw.Draw(im)
    for fn,col,wd in (('/Users/vvvaa/bluish-void/ghost-rivers.json',(255,0,0),3),):
        for f in json.load(open(fn))['features']:
            if f['properties'].get('src')!='Viele 1865': continue
            g=f['geometry']; LL=[g['coordinates']] if g['type']=='LineString' else g['coordinates']
            for l in LL:
                l=np.array(l); px,py=m2r(*ll2m(l[:,0],l[:,1])); pts=list(zip(px-x0,py-y0))
                if any(0<=a<w and 0<=b<h for a,b in pts): d.line(pts,fill=col,width=wd)
    if extra:
        for l in extra: d.line([(a-x0,b-y0) for a,b in l],fill=(0,255,255),width=4)
    for gx in range(0,w,200): d.line([(gx,0),(gx,h)],fill=(255,0,255),width=1); d.text((gx+3,3),str(gx),fill=(255,0,255))
    for gy in range(0,h,200): d.line([(0,gy),(w,gy)],fill=(255,0,255),width=1); d.text((3,gy+3),str(gy),fill=(255,0,255))
    im.reduce(1).resize((1400,1050)).save('/private/tmp/claude-501/-Users-vvvaa/bc981796-22cc-4e2c-8e03-4ebfe6721d3d/scratchpad/sw_%02d.jpg'%k,quality=88)
def snap(rough, x0, y0):
    A=rum(); P=[]
    for a,b in zip(rough[:-1],rough[1:]):
        n=max(2,int(math.hypot(b[0]-a[0],b[1]-a[1])/8))
        for t in range(n): P.append((a[0]+(b[0]-a[0])*t/n, a[1]+(b[1]-a[1])*t/n))
    P.append(rough[-1]); out=[]
    for i,(x,y) in enumerate(P):
        X,Y=x+x0,y+y0; j=min(len(P)-1,i+1); hh=max(0,i-1); tx,ty=P[j][0]-P[hh][0],P[j][1]-P[hh][1]; L=math.hypot(tx,ty) or 1; nx,ny=-ty/L,tx/L
        best=None
        for s in range(-9,10):
            qx,qy=int(round(X+nx*s)),int(round(Y+ny*s))
            v=A[max(0,qy-1):qy+2,max(0,qx-1):qx+2].mean()+abs(s)*1.6
            if best is None or v<best[0]: best=(v,qx,qy)
        out.append((best[1],best[2]))
    Q=np.array(out,float)
    if len(Q)>5: Q=np.vstack([Q[:1],np.array([Q[max(0,i-2):i+3].mean(0) for i in range(1,len(Q)-1)]),Q[-1:]])
    return Q
if __name__=='__main__':
    for k in map(int,sys.argv[1:]): render(k)
    print(len(crops()),'crops')

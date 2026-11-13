import numpy as np, sys
from PIL import Image, ImageDraw
from scipy import ndimage as ndi
img=Image.open('agn_mosaic.png').convert('RGB')
x0,y0,x1,y1=[int(v) for v in sys.argv[1:5]]
a=np.asarray(img.crop((x0,y0,x1,y1))).astype(float)
r,g,b=a[...,0],a[...,1],a[...,2]; L=(r+g+b)/3
sat=a.max(2)-a.min(2)
d=ndi.gaussian_filter(L,0.8)-ndi.gaussian_filter(L,4)
bg=ndi.gaussian_filter(L,8)
grass=(g>r+4)&(g>b+2)
lawn=ndi.uniform_filter(grass.astype(float),21)
TB=float(sys.argv[5]) if len(sys.argv)>5 else 22; TD=float(sys.argv[6]) if len(sys.argv)>6 else 20
bright=(d>TB)&(sat<70)
pale=((L>115)&(sat<45)).astype(float)
busy=ndi.uniform_filter(pale,15)   # drives, blossom: broad pale ground, not one small stone
dark=(d<-TD)&(L<70)&(bg>55)          # not inside a broad tree shadow
pts=[]
for m,kind in ((bright,'b'),(dark,'d')):
    lab,n=ndi.label(m); 
    if not n: continue
    sl=ndi.find_objects(lab); sizes=ndi.sum(m,lab,range(1,n+1)); cms=ndi.center_of_mass(m,lab,range(1,n+1))
    for k in range(n):
        s=sl[k]; h=s[0].stop-s[0].start; w=s[1].stop-s[1].start
        if 3<=sizes[k]<=60 and max(h,w)<=12:
            cy,cx=cms[k]
            if lawn[int(cy),int(cx)]>0.5 and busy[int(cy),int(cx)]<0.10: pts.append((cx,cy,kind))
# a bright face with its own dark shadow within 6 px NW is one stone
out=[]
for p in sorted(pts,key=lambda q:q[2]):
    if any((p[0]-q[0])**2+(p[1]-q[1])**2<36 for q in out): continue
    out.append(p)
np.save('agn_det2.npy',np.array([(x+x0,y+y0) for x,y,_ in out]))
S=4; c=img.crop((x0,y0,x1,y1)).resize(((x1-x0)*S,(y1-y0)*S),Image.LANCZOS); dr=ImageDraw.Draw(c)
for x,y,k in out: dr.ellipse([x*S-7,y*S-7,x*S+7,y*S+7],outline=(255,255,0) if k=='b' else (0,255,255),width=2)
c.save('agn_det2.png'); print(len(out))

import sys, numpy as np
from PIL import Image
from scipy import ndimage as nd
from skimage.morphology import skeletonize
def detect(a, GR=14, MINLEN=60):
    r,g,b=a[...,0],a[...,1],a[...,2]; lum=a.mean(-1)
    ink=(lum<100)&(g-r>=GR)&(g>b+8)
    # land of 1865: pale paper that is not the river's wave texture -- the shoreline band itself is dropped
    water=(b>r+8)&(lum>90)                                   # the blue river bands
    wv=nd.binary_dilation(nd.binary_opening(water,iterations=2),iterations=14)
    ink&=~wv
    ink=nd.binary_closing(ink,structure=np.ones((3,3)),iterations=2)
    sk=skeletonize(ink)
    lab,n=nd.label(sk,structure=np.ones((3,3)))
    objs=nd.find_objects(lab); keep=np.zeros(n+1,bool)
    for i,sl in enumerate(objs,1):
        m=lab[sl]==i; c=int(m.sum())
        if c<MINLEN: continue
        yy,xx=np.nonzero(m); P=np.stack([xx,yy],1).astype(float); P-=P.mean(0)
        ev=np.linalg.eigvalsh(np.cov(P.T))
        if np.sqrt(ev[0])<2.5 and c>0: continue               # a ruled line
        keep[i]=True
    return keep[lab]
if __name__=='__main__':
    a=np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(float)
    out=detect(a)
    vis=a.copy(); vis[nd.binary_dilation(out,iterations=2)]=[255,0,255]
    Image.fromarray(vis.astype(np.uint8)).save(sys.argv[2]); print(out.sum())

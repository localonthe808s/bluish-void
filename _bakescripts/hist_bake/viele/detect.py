import sys, numpy as np
from PIL import Image
from scipy import ndimage as nd
from skimage.morphology import skeletonize, remove_small_objects
def detect(a, TH=105, DEN=0.22, MINLEN=110):
    g=a.mean(-1)
    dark=g<TH
    dens=nd.uniform_filter(dark.astype(float),21)
    cand=dark&(dens<DEN)
    cand=nd.binary_closing(cand,structure=np.ones((3,3)),iterations=2)
    sk=skeletonize(cand)
    lab,n=nd.label(sk,structure=np.ones((3,3)))
    objs=nd.find_objects(lab); keep=np.zeros(n+1,bool)
    for i,sl in enumerate(objs,1):
        m=lab[sl]==i; c=m.sum()
        if c<MINLEN: continue
        yy,xx=np.nonzero(m); P=np.stack([xx,yy],1).astype(float); P-=P.mean(0)
        ev=np.linalg.eigvalsh(np.cov(P.T)); straight=np.sqrt(ev[0])<2.2   # thinner than ~2 px across its run: a ruled line
        ext=np.hypot(sl[0].stop-sl[0].start, sl[1].stop-sl[1].start)
        if straight: continue
        if c>3.2*ext: continue          # a tangle (lettering, hachure clump), not a course
        keep[i]=True
    return keep[lab]
if __name__=='__main__':
    a=np.asarray(Image.open(sys.argv[1]).convert('RGB')).astype(float)
    out=detect(a)
    vis=a.copy(); vis[nd.binary_dilation(out,iterations=2)]=[255,0,255]
    Image.fromarray(vis.astype(np.uint8)).save(sys.argv[2]); print(out.sum())

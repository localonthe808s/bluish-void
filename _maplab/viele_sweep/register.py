import numpy as np, cv2, math, json
from PIL import Image
Image.MAX_IMAGE_PIXELS=None
# the georeferenced Map Warper mosaic (z16 web mercator tiles)
z=16; X0,Y0,X1,Y1=19292,24599,19314,24643
W=(X1-X0+1)*256; H=(Y1-Y0+1)*256
mos=np.zeros((H,W,3),np.uint8)
for x in range(X0,X1+1):
  for y in range(Y0,Y1+1):
    mos[(y-Y0)*256:(y-Y0+1)*256,(x-X0)*256:(x-X0+1)*256]=np.asarray(Image.open('/Users/vvvaa/hist_bake/viele/t16/%d_%d.png'%(x,y)).convert('RGB'))
np.save('mos.npy',mos)
R=np.asarray(Image.open('rumsey_full.png').convert('L'))
S=0.25   # feature scale: Rumsey at 1/4 (~4.6 m/px), mosaic at 0.63/4 -> both ~4.6 m/px... mosaic is 1.81 m/px
Rs=cv2.resize(R,None,fx=S,fy=S,interpolation=cv2.INTER_AREA)
Ms=cv2.resize(cv2.cvtColor(mos,cv2.COLOR_RGB2GRAY),None,fx=S*1.81/1.15*0.63/0.63*1.15/1.81*1.81/1.15,fy=S*1.81/1.15,interpolation=cv2.INTER_AREA)
sm=S*1.81/1.15
cl=cv2.createCLAHE(2.0,(8,8)); Rs=cl.apply(Rs); Ms=cl.apply(Ms)
sift=cv2.SIFT_create(nfeatures=40000)
k1,d1=sift.detectAndCompute(Rs,None); k2,d2=sift.detectAndCompute(Ms,None)
print(len(k1),len(k2))
fl=cv2.FlannBasedMatcher(dict(algorithm=1,trees=5),dict(checks=64))
m=fl.knnMatch(d1,d2,k=2); good=[a for a,b in m if a.distance<0.75*b.distance]
p1=np.float32([k1[a.queryIdx].pt for a in good])/S; p2=np.float32([k2[a.trainIdx].pt for a in good])/sm
Hh,inl=cv2.findHomography(p1,p2,cv2.RANSAC,40)
inl=inl.ravel().astype(bool); print('matches',len(good),'homography inliers',inl.sum())
p1,p2=p1[inl],p2[inl]
# second-order polynomial Rumsey px -> mosaic px, refit with outlier rejection
def D(p): x,y=p[:,0]/1e4,p[:,1]/1e4; return np.stack([np.ones_like(x),x,y,x*x,x*y,y*y,x**3,x*x*y,x*y*y,y**3],1)
keep=np.ones(len(p1),bool)
for it in range(5):
    A=D(p1[keep]); cx=np.linalg.lstsq(A,p2[keep,0],rcond=None)[0]; cy=np.linalg.lstsq(A,p2[keep,1],rcond=None)[0]
    e=np.hypot(D(p1)@cx-p2[:,0], D(p1)@cy-p2[:,1]); keep=e<max(6,np.percentile(e[keep],90))
print('poly inliers',keep.sum(),'median err px %.1f (= %.1f m)'%(np.median(e[keep]),np.median(e[keep])*1.81),'p90 %.1f px'%np.percentile(e[keep],90))
np.save('poly.npy',np.stack([cx,cy]))

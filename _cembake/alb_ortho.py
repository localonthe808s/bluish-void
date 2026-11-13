import math, os, sys, time, urllib.request
OUT=sys.argv[1]; R=6378137
BB=[float(v) for v in sys.argv[2].split(',')] if len(sys.argv)>2 else [-73.7432,42.6977,-73.7227,42.7150]   # W,S,E,N (default: Albany Rural)
mx=lambda lon: math.radians(lon)*R; my=lambda lat: R*math.log(math.tan(math.pi/4+math.radians(lat)/2))
X0,X1=mx(BB[0]),mx(BB[2]); Y0,Y1=my(BB[1]),my(BB[3])
RES=0.25/math.cos(math.radians((BB[1]+BB[3])/2))   # 25 cm ground = this many mercator m
T=2000; tm=T*RES
nx=math.ceil((X1-X0)/tm); ny=math.ceil((Y1-Y0)/tm); print(nx,ny,'tiles', RES)
open(os.path.join(OUT,'grid.txt'),'w').write('%f %f %f %d %d %d\n'%(X0,Y1,RES,T,nx,ny))
for j in range(ny):
  for i in range(nx):
    p=os.path.join(OUT,'t_%d_%d.png'%(i,j))
    if os.path.exists(p) and os.path.getsize(p)>10000: continue
    bx0=X0+i*tm; by1=Y1-j*tm
    u='https://orthos.its.ny.gov/arcgis/rest/services/wms/Latest/MapServer/export?bbox=%f,%f,%f,%f&bboxSR=3857&imageSR=3857&size=%d,%d&format=png24&f=image'%(bx0,by1-tm,bx0+tm,by1,T,T)
    for a in range(3):
      try:
        d=urllib.request.urlopen(urllib.request.Request(u,headers={'User-Agent':'bluishvoid.com cemetery bake'}),timeout=120).read(); open(p,'wb').write(d); break
      except Exception as e: print('retry',i,j,e); time.sleep(5)
    time.sleep(1.0)
print('done')

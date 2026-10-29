import json, math, numpy as np, sys
sys.path.insert(0,'.')
from sweep import crops, snap, r2m, m2ll, render
from traces import T
F=[]; per={}
for k,lines in T.items():
    x0,y0,w,h=crops()[k]; per[k]=[]
    for L in lines:
        rough=[(x/0.7,y/0.7) for x,y in L]
        Q=snap(rough,x0,y0)                       # full-res Rumsey px
        per[k].append([(a,b) for a,b in Q])
        mx,my=r2m(Q[:,0],Q[:,1]); lo,la=m2ll(mx,my)
        c=[[round(float(a),6),round(float(b),6)] for a,b in zip(lo,la)]
        Lm=sum(math.hypot((c[i][0]-c[i-1][0])*84280,(c[i][1]-c[i-1][1])*110540) for i in range(1,len(c)))
        F.append({'type':'Feature','properties':{'src':'Viele 1865','boro':'Manhattan','len_m':round(Lm),'line':3},'geometry':{'type':'LineString','coordinates':c}})
json.dump({'type':'FeatureCollection','features':F},open('sweep_new.json','w'))
print(len(F),'streams', round(sum(f['properties']['len_m'] for f in F)/1000,1),'km')
for k,ls in per.items(): render(k, ls)

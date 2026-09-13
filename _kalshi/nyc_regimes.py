#!/usr/bin/env python3
"""NEW YORK REGIMES AND THE AFTERNOON TABLE (2026-09-13). Read-only research; writes
nothing the bake reads. Fetches its own inputs into _kalshi/_study/ (gitignored,
~4 MB, refetched when older than a day) and prints two studies:

  1. Bias schemes, walk-forward over ~615 archive days (six models, IEM daily max):
     EWMA hl 7 stays the best (MAE 0.988, within-1 58.6%). REJECTED here, do not
     retest: a level-conditioned bias (days with a similar forecast level, 1.032 /
     55.0%), its 50/50 blend with EWMA (noise), a wind-sector bias (1.334), and a
     wind-sector SPREAD (bucket Brier .2473 vs pooled .2466). Onshore days (forecast
     14h wind 120-220) are harder, within-1 54% vs 61%, but not by enough to score.
  2. The afternoon table: with the :51 report in hand, how much higher the official
     max ends up, by season and by whether the last hour was still rising. After
     1:51 PM 60% of days still climb a degree and 35% two; after 2:51 PM 46% / 20%
     in all seasons, 50% / 21% in summer, 29% / 13% in autumn.

    python3 _kalshi/nyc_regimes.py
"""
import os, sys, time, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, '_study'); os.makedirs(D, exist_ok=True)
END = time.strftime('%Y-%m-%d')
def fetch(name, url):
    p = os.path.join(D, name)
    if not os.path.exists(p) or time.time() - os.path.getmtime(p) > 86400:
        print('fetching', name, flush=True)
        urllib.request.urlretrieve(url, p)
    return p
M = 'ncep_hrrr_conus,ncep_nbm_conus,ecmwf_ifs025,gfs_seamless,icon_seamless,gem_seamless'
y, m, d = END.split('-')
fetch('nyc_arch.json', 'https://historical-forecast-api.open-meteo.com/v1/forecast?latitude=40.7789&longitude=-73.9692&start_date=2025-01-01&end_date=%s&hourly=temperature_2m,wind_direction_10m,wind_speed_10m,cloud_cover&temperature_unit=fahrenheit&wind_speed_unit=mph&timezone=America%%2FNew_York&models=%s' % (END, M))
fetch('nyc_daily.csv', 'https://mesonet.agron.iastate.edu/cgi-bin/request/daily.py?network=NY_ASOS&stations=NYC&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&format=comma' % (y, m, d))
fetch('nyc_hourly.csv', 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=NYC&data=tmpf,drct,sknt,skyc1&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&tz=America%%2FNew_York&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=3' % (y, m, d))
fetch('lga_hourly.csv', 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=LGA&data=tmpf&year1=2025&month1=1&day1=1&year2=%s&month2=%s&day2=%s&tz=America%%2FNew_York&format=onlycomma&latlon=no&elev=no&missing=M&trace=T&direct=no&report_type=3' % (y, m, d))
os.chdir(D)
print('=' * 30, 'BIAS SCHEMES AND REGIMES')
import json, csv, math, statistics as st, collections, datetime
M=['ncep_hrrr_conus','ncep_nbm_conus','ecmwf_ifs025','gfs_seamless','icon_seamless','gem_seamless']
A=json.load(open('nyc_arch.json'))['hourly']
T=A['time']
# per day per model: peak temp (hours 0-23), afternoon wind dir/speed at 14h, mean cloud 10-16h
day={}
for i,t in enumerate(T):
    d=t[:10]; h=int(t[11:13]); r=day.setdefault(d,{m:{'pk':-999,'wd':None,'ws':None,'cc':[]} for m in M})
    for m in M:
        v=A['temperature_2m_'+m][i]
        if v is not None and v>r[m]['pk']: r[m]['pk']=v
        if h==14: r[m]['wd']=A['wind_direction_10m_'+m][i]; r[m]['ws']=A['wind_speed_10m_'+m][i]
        if 10<=h<=16 and A['cloud_cover_'+m][i] is not None: r[m]['cc'].append(A['cloud_cover_'+m][i])
truth={}
for r in csv.DictReader(open('nyc_daily.csv')):
    v=r.get('max_temp_f')
    if v not in (None,'','M','None'): truth[r['day']]=float(v)
# hourly obs: max through 11:51, hour of max, stream max, afternoon wind
obs=collections.defaultdict(list)
for r in csv.DictReader(open('nyc_hourly.csv')):
    if r['tmpf'] in ('M',''): continue
    obs[r['valid'][:10]].append((int(r['valid'][11:13]), float(r['tmpf']), None if r['drct'] in ('M','') else float(r['drct']), None if r['sknt'] in ('M','') else float(r['sknt'])))
lga=collections.defaultdict(list)
for r in csv.DictReader(open('lga_hourly.csv')):
    if r['tmpf'] in ('M',''): continue
    lga[r['valid'][:10]].append(float(r['tmpf']))
days=sorted(d for d in day if d in truth and all(day[d][m]['pk']>-900 for m in M) and d>='2025-01-01')
print('days with full data', len(days), days[0], days[-1])
raw={d:{m:day[d][m]['pk'] for m in M} for d in days}
cons={d:st.mean(raw[d].values()) for d in days}
err={d:{m:raw[d][m]-truth[d] for m in M} for d in days}
def sector(wd):
    if wd is None: return 'na'
    return 'onshore' if 120<=wd<=220 else 'offshore'
wsec={d:sector(st.mean(x for x in (day[d][m]['wd'] for m in M) if x is not None)) for d in days}
idx={d:i for i,d in enumerate(days)}
def ewma(d,m,hl=7,win=90):
    i=idx[d]; num=den=0.0
    for j in range(max(0,i-win),i):
        w=0.5**((i-j)/hl); num+=w*err[days[j]][m]; den+=w
    return num/den if den else 0.0
def flat(d,m,k=30):
    i=idx[d]; xs=[err[days[j]][m] for j in range(max(0,i-k),i)]
    return st.mean(xs) if xs else 0.0
def level(d,m,win=150,tol=4.0,minn=10,hl=None):
    i=idx[d]; c=cons[d]; num=den=0.0; n=0
    for j in range(max(0,i-win),i):
        if abs(cons[days[j]]-c)<=tol:
            w=1.0 if hl is None else 0.5**((i-j)/hl)
            num+=w*err[days[j]][m]; den+=w; n+=1
    return (num/den) if n>=minn else ewma(d,m)
def wind(d,m,win=150,minn=10):
    i=idx[d]; s=wsec[d]; xs=[err[days[j]][m] for j in range(max(0,i-win),i) if wsec[days[j]]==s]
    return st.mean(xs) if len(xs)>=minn else ewma(d,m)
schemes={'raw':lambda d,m:0.0,'flat30':flat,'ewma7':ewma,'level':level,'level_hl30':lambda d,m:level(d,m,hl=30),'level_tol2':lambda d,m:level(d,m,tol=2.0),'wind':wind,
         'lvl+ewma':lambda d,m:0.5*(level(d,m)+ewma(d,m))}
start=days[60]
res={}
for name,f in schemes.items():
    rows=[]
    for d in days:
        if d<start: continue
        p=st.mean(raw[d][m]-f(d,m) for m in M); e=p-truth[d]; rows.append((d,e))
    res[name]=rows
def score(rows):
    e=[x for _,x in rows]; return len(e), st.mean(abs(x) for x in e), st.mean(1.0 for x in e if abs(x)<1.0)/len(e)*len(e)/len(e) if e else 0, st.mean(e)
print('%-11s %5s %6s %7s %6s | %s'%('scheme','n','MAE','within1','bias','halves MAE (old/new)  seasons MAE (DJF MAM JJA SON)'))
def seas(d): return {12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}[int(d[5:7])]
for name,rows in res.items():
    n=len(rows); e=[x for _,x in rows]; h=n//2
    w1=sum(1 for x in e if abs(x)<1.0)/n
    halves=(st.mean(abs(x) for _,x in rows[:h]), st.mean(abs(x) for _,x in rows[h:]))
    ss=[]
    for s in ['DJF','MAM','JJA','SON']:
        xs=[x for d,x in rows if seas(d)==s]; ss.append('%.2f'%st.mean(abs(x) for x in xs) if xs else '-')
    print('%-11s %5d %6.3f %7.1f%% %+6.2f | %.3f/%.3f   %s'%(name,n,st.mean(abs(x) for x in e),100*w1,st.mean(e),halves[0],halves[1],' '.join(ss)))
# descriptive: signed error of ewma7 by consensus tercile, by sector, by month
rows=dict(res['ewma7'])
cs=sorted(cons[d] for d in rows); t1,t2=cs[len(cs)//3],cs[2*len(cs)//3]
for lab,sel in [('cold tercile',lambda d:cons[d]<t1),('mid',lambda d:t1<=cons[d]<t2),('hot tercile',lambda d:cons[d]>=t2)]:
    xs=[rows[d] for d in rows if sel(d)]; print('  ewma7 signed err %-12s n=%3d mean %+.2f  within1 %.0f%%'%(lab,len(xs),st.mean(xs),100*sum(1 for x in xs if abs(x)<1)/len(xs)))
for s in ['onshore','offshore']:
    xs=[rows[d] for d in rows if wsec[d]==s]; print('  ewma7 signed err %-12s n=%3d mean %+.2f  within1 %.0f%%'%(s,len(xs),st.mean(xs),100*sum(1 for x in xs if abs(x)<1)/len(xs)))
bym=collections.defaultdict(list)
for d in rows: bym[d[:7]].append(rows[d])
print('  by month (ewma7): '+' '.join('%s %+.2f/%.0f%%'%(k[2:],st.mean(v),100*sum(1 for x in v if abs(x)<1)/len(v)) for k,v in sorted(bym.items())))
# tricks: hour of max, stream gap, LGA gap
hm=collections.defaultdict(list); gap=collections.defaultdict(list); lg=collections.defaultdict(list); aft=collections.defaultdict(int); cnt=collections.defaultdict(int)
for d in days:
    o=obs.get(d); 
    if not o: continue
    mx=max(o,key=lambda x:x[1]); hm[seas(d)].append(mx[0]); gap[seas(d)].append(truth[d]-mx[1])
    cnt[seas(d)]+=1
    if mx[0]>=14: aft[seas(d)]+=1
    if lga.get(d): lg[wsec[d]].append(max(lga[d])-max(x[1] for x in o))
for s in ['DJF','MAM','JJA','SON']:
    hs=sorted(hm[s]); g=gap[s]
    print('  %s hour of hourly max: median %d, 25/75 %d/%d; max at/after 2 PM %.0f%%; daily max - hourly max mean %+.2f (0: %.0f%%, >=2: %.0f%%)'%(s,hs[len(hs)//2],hs[len(hs)//4],hs[3*len(hs)//4],100*aft[s]/cnt[s],st.mean(g),100*sum(1 for x in g if x<0.5)/len(g),100*sum(1 for x in g if x>=1.5)/len(g)))
for s in ['onshore','offshore']:
    print('  LGA - NYC hourly max, %s: mean %+.2f n=%d'%(s,st.mean(lg[s]),len(lg[s])))

# ---- spread regime by forecast wind sector: is sigma different, and does a sector sigma score better walk-forward?
rows=res['ewma7']; E=dict(rows); D=[d for d,_ in rows]
import math
def sdof(xs): return st.pstdev(xs) if len(xs)>1 else None
for s in ['onshore','offshore']:
    xs=[E[d] for d in D if wsec[d]==s]; print('  residual sd %-8s %.3f (n=%d)  |err|>=2: %.0f%%'%(s,sdof(xs),len(xs),100*sum(1 for x in xs if abs(x)>=2)/len(xs)))
for se in ['DJF','MAM','JJA','SON']:
    print('   ',se,' '.join('%s %.2f(n=%d)'%(s,sdof([E[d] for d in D if wsec[d]==s and seas(d)==se]) or 0,len([1 for d in D if wsec[d]==s and seas(d)==se])) for s in ['onshore','offshore']))
# walk-forward: sigma from trailing 90 days pooled vs by sector (min 15) ; score = mean log-likelihood of truth in a 2F bucket centred on the rounded pred? use continuous NLL and Brier of the bucket [round(pred)-0.5, round(pred)+0.5]... use the 2-degree bucket containing pred (parity by pred): P(truth in bucket)
from math import erf, sqrt
def Phi(x): return 0.5*(1+erf(x/sqrt(2)))
def pbucket(pred,sd,truth):
    lo=math.floor(pred) if (math.floor(pred)%2==1) else math.floor(pred)-1  # odd-aligned 2F buckets (77-78, 79-80), a fixed convention
    a,b=lo-0.5,lo+1.5
    p=Phi((b-pred)/sd)-Phi((a-pred)/sd); hit=1.0 if a<truth<b else 0.0
    return p,hit
def run(sector_sd):
    nll=[];br=[];n=0
    for i,d in enumerate(D):
        if i<90: continue
        prev=D[max(0,i-90):i]
        pool=[E[x] for x in prev]; sd=sdof(pool) or 1.0
        if sector_sd:
            same=[E[x] for x in prev if wsec[x]==wsec[d]]
            if len(same)>=15: sd=sdof(same)
        pred=truth[d]+E[d]
        p,hit=pbucket(pred,sd,truth[d]); br.append((p-hit)**2); nll.append(-math.log(max(p if hit else 1-p,1e-6))); n+=1
    return n,st.mean(br),st.mean(nll)
print('  pooled sigma : n=%d bucket Brier %.4f  logloss %.4f'%run(False))
print('  sector sigma : n=%d bucket Brier %.4f  logloss %.4f'%run(True))

print('=' * 30, 'THE AFTERNOON TABLE')
truth={}
for r in csv.DictReader(open('nyc_daily.csv')):
    v=r.get('max_temp_f')
    if v not in (None,'','M','None'): truth[r['day']]=float(v)
obs=collections.defaultdict(dict)
for r in csv.DictReader(open('nyc_hourly.csv')):
    if r['tmpf'] in ('M',''): continue
    h=int(r['valid'][11:13]); mn=int(r['valid'][14:16])
    if 45<=mn<=59: obs[r['valid'][:10]][h]=float(r['tmpf'])   # the routine :51 report only
def seas(d): return {12:'DJF',1:'DJF',2:'DJF',3:'MAM',4:'MAM',5:'MAM',6:'JJA',7:'JJA',8:'JJA',9:'SON',10:'SON',11:'SON'}[int(d[5:7])]
days=[d for d in sorted(truth) if len(obs.get(d,{}))>=20]
print('days', len(days))
print('AFTER HOUR h (the :51 report in hand): how much higher does the official max end up?')
print('%-4s %-3s %5s | %6s %6s %6s | rising: %6s %6s | flat/falling: %6s %6s'%('seas','h','n','=0','>=1','>=2','n','>=1','n','>=1'))
for se in ['JJA','SON','MAM','DJF','ALL']:
    for h in [11,12,13,14,15,16]:
        g=[]; rise=[]; fall=[]
        for d in days:
            if se!='ALL' and seas(d)!=se: continue
            o=obs[d]
            if h not in o or (h-1) not in o: continue
            run=max(v for k,v in o.items() if k<=h); gap=truth[d]-run
            g.append(gap); (rise if o[h]>o[h-1] else fall).append(gap)
        f=lambda xs,t: (100.0*sum(1 for x in xs if x>=t)/len(xs)) if xs else float('nan')
        print('%-4s %-3d %5d | %5.0f%% %5.0f%% %5.0f%% | %6d %5.0f%% | %6d %5.0f%%'%(se,h,len(g),100.0*sum(1 for x in g if x<0.5)/len(g),f(g,0.5),f(g,1.5),len(rise),f(rise,0.5),len(fall),f(fall,0.5)))
    print()

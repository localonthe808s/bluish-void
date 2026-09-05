"""Score the ASOS 6-hourly max groups against Kalshi's exact settled value."""
import importlib.util, datetime, io, csv, re, json, statistics, collections, urllib.parse
from zoneinfo import ZoneInfo
spec=importlib.util.spec_from_file_location("kd","/Users/vvvaa/bluish-void/_kalshi/kalshi_daily.py")
kd=importlib.util.module_from_spec(spec); spec.loader.exec_module(kd)
today=datetime.date(2026,9,5); N=45
start=today-datetime.timedelta(days=N+1)

def settled_values(cfg):
    d=kd.get_json('https://api.elections.kalshi.com/trade-api/v2/markets'
                  '?series_ticker=%s&status=settled&limit=400'%cfg['series'])
    v={}
    for m in d.get('markets',[]):
        x=m.get('expiration_value')
        if x not in (None,''):
            try: v[m['event_ticker']]=float(x)
            except ValueError: pass
    out={}
    for i in range(1,N+2):
        day=today-datetime.timedelta(days=i)
        t=kd.event_ticker(cfg,day)
        if t in v: out[day.isoformat()]=v[t]
    return out

def six_groups(cfg):
    """-> {(utc_date, report_hour): degF} from the 1sTTT remark."""
    u=('https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=%s&data=metar'
       '&year1=%d&month1=%d&day1=%d&year2=%d&month2=%d&day2=%d&tz=UTC'
       '&format=onlycomma&missing=empty'
       %(cfg['station'],start.year,start.month,start.day,today.year,today.month,today.day+1))
    out={}
    for r in csv.DictReader(io.StringIO(kd.get(u,timeout=180).decode())):
        raw=r.get('metar') or ''
        m=re.search(r'\b1([01])(\d{3})\b', raw)
        if not m: continue
        ts=r['valid']                       # 'YYYY-MM-DD HH:MM' UTC
        c=(int(m.group(2))/10.0)*(-1 if m.group(1)=='1' else 1)
        key=(ts[:10], int(ts[11:13]))
        out[key]=max(out.get(key,-999.0), round(c*9/5+32,1))
    return out

def daily_from_groups(groups, cfg, day):
    """Max over every 6-hour window that lies ENTIRELY inside the local climate day."""
    z=ZoneInfo(cfg['tz']); h0=kd.climate_day_start(cfg, day)
    lo=datetime.datetime(day.year,day.month,day.day,h0,tzinfo=z)
    hi=datetime.datetime(day.year,day.month,day.day,23,59,tzinfo=z)+datetime.timedelta(minutes=1)
    if h0==1: hi=hi+datetime.timedelta(hours=1)      # climate day runs to 00:59 next
    best=None
    for (d_,h),v in groups.items():
        rep=datetime.datetime(*map(int,d_.split('-')),h,tzinfo=datetime.timezone.utc)
        # the group covers the six hours ENDING at the nominal synoptic hour
        end=rep.replace(minute=0)+ (datetime.timedelta(hours=1) if rep.minute>30 else datetime.timedelta(0))
        st=end-datetime.timedelta(hours=6)
        if st.astimezone(z)>=lo and end.astimezone(z)<=hi:
            best=v if best is None else max(best,v)
    return best

print("  %-14s %4s %8s %9s %8s   %s" % ("city","n","exact","within1","MAE","vs IEM daily"))
tot=collections.Counter(); allerr=[]
for cfg in kd.MARKETS:
    sv=settled_values(cfg); gr=six_groups(cfg)
    iem=kd.daily_series(cfg, start, today)
    e6=[]; ei=[]
    for k,s in sv.items():
        d=datetime.date(*map(int,k.split('-')))
        v=daily_from_groups(gr,cfg,d)
        if v is not None: e6.append(v-s)
        if iem.get(k) is not None: ei.append(iem[k]-s)
    if not e6: print("  %-14s no data"%cfg['city']); continue
    allerr+=e6
    ex=100*sum(1 for x in e6 if abs(x)<0.51)/len(e6)      # settles to whole degrees
    w1=100*sum(1 for x in e6 if abs(x)<=1.01)/len(e6)
    exi=100*sum(1 for x in ei if abs(x)<0.51)/len(ei) if ei else float('nan')
    print("  %-14s %4d %7.0f%% %8.0f%% %8.2f   IEM %.0f%% exact, MAE %.2f"
          %(cfg['city'],len(e6),ex,w1,statistics.mean(abs(x) for x in e6),
            exi, statistics.mean(abs(x) for x in ei) if ei else float('nan')))
    tot['n']+=len(e6); tot['ex']+=sum(1 for x in e6 if abs(x)<0.51)
print("\n  ALL: %d days, 6-hourly exact %.1f%%, MAE %.2f, mean err %+.2f"
      %(tot['n'],100*tot['ex']/tot['n'],statistics.mean(abs(x) for x in allerr),statistics.mean(allerr)))

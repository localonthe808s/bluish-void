import json,re,sys
L=json.load(open('caves_notable_v4.json'))
SHOW=['fact','t_note','rock','formed','visit_note','diff_note','tour','season','found_note','features','above_credit']
num=lambda x: float(x.replace(',','').replace('+',''))
def fmt(v):
    a=abs(v)
    if a>=1000: v=round(v,-1)
    elif a>=10: v=round(v)
    else: v=round(v,1)
    s='{:,}'.format(int(v)) if float(v).is_integer() else str(v)
    return s
def cf(c): return round(num(c)*9/5+32)
def conv(t):
    t=re.sub(r'(\d[\d.]*)-(\d[\d.]*) C warmer', lambda m:'%s-%s F warmer'%(fmt(num(m.group(1))*1.8),fmt(num(m.group(2))*1.8)), t)
    t=re.sub(r'(?:about |~)?([-+]?\d[\d.]*) C \((\d+) F\)', r'\2°F', t)
    t=re.sub(r'([-+]?\d[\d.]*)(?:\s*(-|to)\s*([-+]?\d[\d.]*))?\s*C\b(?! warmer)', lambda m: ('%d°F'%cf(m.group(1)) if not m.group(3) else '%d%s%d°F'%(cf(m.group(1)),' to ' if m.group(2)=='to' else '-',cf(m.group(3)))), t)
    t=re.sub(r'([\d.,]+) million cubic meters', lambda m:'%s million cubic feet'%fmt(num(m.group(1))*35.315), t)
    t=re.sub(r'([\d.,]+) cubic meters', lambda m:'%s cubic feet'%fmt(num(m.group(1))*35.315), t)
    def L_(m,f,u):
        a=m.group(1); b=m.group(3)
        if b: return '%s%s%s %s'%(fmt(num(a)*f),' to ' if m.group(2).strip()=='to' else '-' if m.group(2).strip()=='-' else ' x ',fmt(num(b)*f),u)
        return '%s %s'%(fmt(num(a)*f),u)
    t=re.sub(r'(\d[\d,.]*)(?:(\s*(?:-|to|x)\s*)(\d[\d,.]*))?\s*km\b', lambda m:L_(m,0.6214,'mi'), t)
    t=re.sub(r'(\d[\d,.]*)(?:(\s*(?:-|to)\s*)(\d[\d,.]*))?\s*m\b', lambda m:L_(m,3.281,'ft'), t)
    return t
FIX={('Hölloch','fact'):"Hell Hole, a limestone cave that floods fast after heavy rain; more than 3,000 ft deep as well as long.",
     ('Hranice Abyss','fact'):"The deepest known flooded pit cave: 519.5 m confirmed, 450 m of it underwater; how it formed, possibly by rising hot acidic water, is still debated."}
n=0
for c in L:
    for k in SHOW:
        if k not in c: continue
        if (c['n'],k) in FIX: c[k]=FIX[(c['n'],k)]
        v=c[k]; nv=[conv(x) for x in v] if isinstance(v,list) else conv(v)
        if nv!=v: n+=1; print(c['n'],'|',k,'|',json.dumps(nv,ensure_ascii=False)[:230])
        c[k]=nv
json.dump(L,open('caves_notable_v5.json','w'),ensure_ascii=False,separators=(',',':'))
print('changed',n)

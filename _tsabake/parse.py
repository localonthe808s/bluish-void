"""TSA checkpoint throughput, from the weekly FOIA reading-room PDFs (user 2026-11-25: "build the TSA estimates for when theyre not live").

Each PDF (~1,400 pages, tsa.gov/foia/readingroom, "TSA Throughput Data ...") lists every hour of a week: every airport's checkpoints and
the people screened there (Total Pax + Crew). pypdf's layout mode keeps the columns. Two traps, both from merged cells drawn CENTERED:
  - an airport's code sits in the MIDDLE of its checkpoints (on the middle checkpoint's line for an odd count, alone between the two
    middle ones for an even count), and blank lines separate the checkpoints -- so a code owns as many checkpoints below it as above;
  - the date and hour labels are centered on their whole group too (dozens of pages), so they cannot be carried down. Instead the airports
    run alphabetically within each hour and start again at the next: every restart is a new hour, counted from the week's first date.

    python3 _tsabake/parse.py pdf/*.pdf      -> _tsabake/out/rows_<week>.json  [[date 'YYYY-MM-DD', hour, airport, checkpoint, count], ...]
"""
import datetime, json, os, re, sys
from multiprocessing import Pool
from pypdf import PdfReader

HERE = os.path.dirname(os.path.abspath(__file__)); OUT = os.path.join(HERE, 'out'); os.makedirs(OUT, exist_ok=True)
RD = re.compile(r'(\d{1,2})/(\d{1,2})/(\d{4})'); RH = re.compile(r'\b(\d{2}):00\b'); RN = re.compile(r'(\d[\d,]*)\s*$')
MO = ['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december']


def cols(lines):
    for l in lines:
        if 'Checkpoint' in l and 'Airport' in l:
            return l.index('Airport'), l.index('City'), l.index('Checkpoint')
    return None


def items(page):
    """the page as ['code', CODE, shares_line] and ['cp', name, n] in reading order"""
    lines = page.extract_text(extraction_mode='layout').split('\n'); C = cols(lines)
    if not C: return []
    a0, c0, k0 = C; out = []; started = False
    for l in lines:
        if not started:
            started = 'Checkpoint' in l and 'Airport' in l
            continue
        if not l.strip(): continue
        hl = RH.search(l[:a0])
        if hl: out.append(['lab', int(hl.group(1))])   # an hour label (centered on its hour's group)
        cp = l[k0 - 4:] if len(l) > k0 - 4 else ''
        n = RN.search(cp); has_cp = bool(n and cp[:n.start()].strip())
        seg = RH.sub(' ', RD.sub(' ', l[:c0])).split()
        if seg and re.fullmatch(r'[A-Z]{1,3}', seg[0]):
            if len(seg) > 1: out.append(['code', seg[0], has_cp])
            else:   # a lone fragment continues the last code ("MD" / "W")
                for j in range(len(out) - 1, -1, -1):
                    if out[j][0] == 'code':
                        if len(out[j][1]) < 3: out[j][1] += seg[0]
                        break
        if has_cp: out.append(['cp', cp[:n.start()].strip(), int(n.group(1).replace(',', ''))])
        elif cp.strip() and not seg and out and out[-1][0] == 'cp': out[-1][1] += ' ' + cp.strip()   # a wrapped checkpoint name
    return out


def week(path):
    seq = []
    for p in PdfReader(path).pages: seq += items(p)
    rows, pend, cur, owe, mid, labs = [], [], None, 0, False, []
    for it in seq:
        if it[0] == 'lab': labs.append((len(rows) + len(pend), it[1])); continue
        if it[0] == 'code':
            cur = it[1]; rows += [[cur, c[1], c[2]] for c in pend]; owe = len(pend); pend = []; mid = it[2]; continue
        if mid: rows.append([cur, it[1], it[2]]); mid = False; continue   # the middle checkpoint, on the code's own line
        if owe > 0: rows.append([cur, it[1], it[2]]); owe -= 1; continue
        pend.append(it)
    m = re.search(r'(' + '|'.join(MO) + r')-(\d{1,2})-(\d{4})', os.path.basename(path))
    t0 = datetime.datetime(int(m.group(3)), MO.index(m.group(1)) + 1, int(m.group(2)))
    # groups: a step back in the alphabet starts a new one. A stray step (a misread code) splits an hour in two, so each group takes
    # the hour of the label inside it; an unlabeled group joins the labeled one before it when that one's hour is followed directly
    # by the next label's (a split), else it is the hour between them
    starts, last = [0], ''
    for i, (code, cp, c) in enumerate(rows):
        if code < last: starts.append(i)
        last = code
    G = [[starts[k], starts[k + 1] if k + 1 < len(starts) else len(rows), None] for k in range(len(starts))]
    gi = 0
    for pos, hh in labs:
        while gi + 1 < len(G) and G[gi + 1][0] <= pos: gi += 1
        if G[gi][2] is None: G[gi][2] = hh
    known = [k for k in range(len(G)) if G[k][2] is not None]
    for k in range(len(G)):
        if G[k][2] is not None: continue
        p = max([j for j in known if j < k], default=None); n = min([j for j in known if j > k], default=None)
        if p is None: G[k][2] = (G[n][2] - (n - k)) % 24 if n is not None else 0
        elif n is None: G[k][2] = (G[p][2] + (k - p)) % 24
        else:
            gap = (G[n][2] - G[p][2]) % 24
            G[k][2] = (G[p][2] + min(k - p, max(0, gap - 1)) ) % 24 if gap > 1 else G[p][2]
    out, day, prev = [], 0, None
    for s0, s1, hh in G:
        if prev is not None and hh < prev: day += 1
        prev = hh; t = t0 + datetime.timedelta(days=day, hours=hh)
        for code, cp, c in rows[s0:s1]: out.append([t.strftime('%Y-%m-%d'), t.hour, code, cp, c])
    h = len(set((r[0], r[1]) for r in out)) - 1
    name = os.path.basename(path).replace('.pdf', '')
    json.dump(out, open(os.path.join(OUT, 'rows_' + name + '.json'), 'w'), separators=(',', ':'))
    return name, len(out), h + 1, len(pend)


if __name__ == '__main__':
    todo = [p for p in sys.argv[1:] if not os.path.exists(os.path.join(OUT, 'rows_' + os.path.basename(p).replace('.pdf', '') + '.json'))]   # weeks already parsed are kept
    if not todo: print('every week already parsed'); sys.exit(0)
    sys.argv = sys.argv[:1] + todo
    with Pool(min(8, len(sys.argv) - 1)) as P:
        for name, n, hrs, left in P.imap_unordered(week, sys.argv[1:]): print(name, n, 'rows', hrs, 'hours', left, 'unassigned', flush=True)

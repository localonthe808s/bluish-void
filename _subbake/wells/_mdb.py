"""Minimal read-only Microsoft Access (Jet 4 .mdb / ACE .accdb) table reader, pure python stdlib.
Supports the common column types (bool, byte, int, long, money, single, double, datetime, text, memo, GUID).
Data pages come from the table's usage map (stale pages that still name the table are ignored); if the map
cannot be read, falls back to scanning for pages owned by the table definition.
Unencrypted databases only. Untrusted input: every offset is bounds-checked; malformed rows are skipped."""
import mmap, struct, datetime

PG = 4096


def _text(b):
    if len(b) >= 2 and b[0] == 0xFF and b[1] == 0xFE:  # Jet4 compressed unicode
        out = []; comp = True; i = 2; n = len(b)
        while i < n:
            if b[i] == 0:
                comp = not comp; i += 1; continue
            if comp:
                out.append(chr(b[i])); i += 1
            else:
                if i + 1 >= n: break
                out.append(chr(b[i] | (b[i + 1] << 8))); i += 2
        return ''.join(out)
    return bytes(b[:len(b) // 2 * 2]).decode('utf-16-le', 'replace')


class MDB(object):
    def __init__(self, path):
        self.f = open(path, 'rb')
        self.m = mmap.mmap(self.f.fileno(), 0, access=mmap.ACCESS_READ)
        self.npg = len(self.m) // PG
        self._owners = None
        self.tables = {}
        for r in self._rows(2):
            t, name, idv, flags = r.get('Type'), r.get('Name'), r.get('Id'), r.get('Flags')
            if t == 1 and name and idv is not None:
                self.tables[name] = (idv & 0xFFFFFF, flags or 0)

    def page(self, n):
        return self.m[n * PG:(n + 1) * PG]

    def owners(self):
        if self._owners is None:
            o = {}
            for n in range(1, self.npg):
                b = self.m[n * PG:n * PG + 8]
                if b[0] == 1 and b[1] == 1:
                    o.setdefault(struct.unpack_from('<I', b, 4)[0], []).append(n)
            self._owners = o
        return self._owners

    def tdef(self, pg):
        b = self.page(pg)
        if b[0] != 2: raise ValueError('not a table definition page: %d' % pg)
        buf = bytearray(b); nxt = struct.unpack_from('<I', b, 4)[0]; guard = 0
        while nxt and guard < 1000:
            p = self.page(nxt); buf += p[8:]; nxt = struct.unpack_from('<I', p, 4)[0]; guard += 1
        num_cols = struct.unpack_from('<H', buf, 45)[0]
        num_real_idx = struct.unpack_from('<I', buf, 51)[0]
        o = 63 + num_real_idx * 12
        cols = []
        for i in range(num_cols):
            c = buf[o:o + 25]; o += 25
            cols.append({'type': c[0], 'num': struct.unpack_from('<H', c, 5)[0], 'var': struct.unpack_from('<H', c, 7)[0],
                         'fixed': bool(c[15] & 0x01), 'foff': struct.unpack_from('<H', c, 21)[0], 'len': struct.unpack_from('<H', c, 23)[0]})
        for c in cols:
            ln = struct.unpack_from('<H', buf, o)[0]; o += 2
            c['name'] = _text(bytes(buf[o:o + ln])); o += ln
        return cols

    def _rowbytes(self, pg, rn, depth=0):
        b = self.page(pg)
        if b[0] != 1 or depth > 3: return None
        nrows = struct.unpack_from('<H', b, 12)[0]
        if rn >= nrows: return None
        offs = struct.unpack_from('<%dH' % nrows, b, 14)
        raw = offs[rn]
        start = raw & 0x1FFF
        end = PG
        for j in range(rn - 1, -1, -1):
            end = offs[j] & 0x1FFF
            break
        if raw & 0x8000 and not raw & 0x4000: return None
        if raw & 0x4000:  # overflow pointer
            ptr = struct.unpack_from('<I', b, start)[0]
            return self._rowbytes(ptr >> 8, ptr & 0xFF, depth + 1)
        if not (14 <= start < end <= PG): return None
        return b[start:end]

    def _lval(self, d):
        ln = struct.unpack_from('<I', d, 0)[0]; flag = ln >> 24; ln &= 0x3FFFFFFF
        if flag & 0x80: return d[12:12 + ln]
        ptr = struct.unpack_from('<I', d, 4)[0]
        if flag & 0x40:
            r = self._rowbytes(ptr >> 8, ptr & 0xFF)
            return (r or b'')[:ln]
        out = bytearray(); guard = 0
        while ptr and len(out) < ln and guard < 10000:
            r = self._rowbytes(ptr >> 8, ptr & 0xFF)
            if not r or len(r) < 4: break
            ptr = struct.unpack_from('<I', r, 0)[0]; out += r[4:]; guard += 1
        return bytes(out[:ln])

    def _val(self, c, d):
        t = c['type']
        try:
            if t == 2: return d[0]
            if t == 3: return struct.unpack_from('<h', d)[0]
            if t == 4: return struct.unpack_from('<i', d)[0]
            if t == 5: return struct.unpack_from('<q', d)[0] / 10000.0
            if t == 6: return struct.unpack_from('<f', d)[0]
            if t == 7: return struct.unpack_from('<d', d)[0]
            if t == 8:
                v = struct.unpack_from('<d', d)[0]
                try: return datetime.datetime(1899, 12, 30) + datetime.timedelta(days=v)
                except Exception: return None
            if t == 10: return _text(d)
            if t == 12: return _text(self._lval(d)) if len(d) >= 12 else None
            if t == 15: return bytes(d[:16]).hex()
            if t == 16:  # numeric: 1 byte precision? scale, sign, 16 byte int
                return None
            return bytes(d)
        except Exception:
            return None

    def _crack(self, cols, r):
        if len(r) < 2: return None
        ncols = struct.unpack_from('<H', r, 0)[0]
        nm = (ncols + 7) // 8; E = len(r)
        if E < nm + 4: return None
        mask = r[E - nm:E]
        nvar = struct.unpack_from('<H', r, E - nm - 2)[0]
        voffs = []
        for i in range(nvar + 1):
            p = E - nm - 4 - 2 * i
            if p < 2: return None
            voffs.append(struct.unpack_from('<H', r, p)[0])
        out = {}
        for c in cols:
            n = c['num']
            present = n < ncols and (mask[n // 8] >> (n % 8)) & 1
            if c['type'] == 1:
                out[c['name']] = bool(present); continue
            if not present or n >= ncols: out[c['name']] = None; continue
            if c['fixed']:
                s = 2 + c['foff']; d = r[s:s + c['len']]
                out[c['name']] = self._val(c, d) if len(d) == c['len'] else None
            else:
                v = c['var']
                if v >= nvar: out[c['name']] = None; continue
                a, b = voffs[v], voffs[v + 1]
                out[c['name']] = self._val(c, r[a:b]) if 0 <= a <= b <= E else None
        return out

    def usage(self, tdef_pg):
        """Pages listed in the table's 'used pages' usage map, or None if it cannot be read."""
        try:
            ptr = struct.unpack_from('<I', self.page(tdef_pg), 55)[0]
            r = self._rowbytes(ptr >> 8, ptr & 0xFF)
            if not r: return None
            out = []
            if r[0] == 0:
                start = struct.unpack_from('<I', r, 1)[0]
                for i, byte in enumerate(r[5:]):
                    for k in range(8):
                        if byte >> k & 1: out.append(start + i * 8 + k)
            elif r[0] == 1:
                per = (PG - 4) * 8
                for j in range((len(r) - 1) // 4):
                    mp = struct.unpack_from('<I', r, 1 + 4 * j)[0]
                    if not mp or mp >= self.npg: continue
                    b = self.page(mp)
                    for i, byte in enumerate(b[4:]):
                        if byte:
                            for k in range(8):
                                if byte >> k & 1: out.append(j * per + i * 8 + k)
            else:
                return None
            own = set(self.owners().get(tdef_pg, []))
            return [p for p in out if p in own]
        except Exception:
            return None

    def _rows(self, tdef_pg):
        cols = self.tdef(tdef_pg)
        pages = self.usage(tdef_pg)
        if pages is None: pages = self.owners().get(tdef_pg, [])
        for pg in pages:
            b = self.page(pg)
            nrows = struct.unpack_from('<H', b, 12)[0]
            if nrows > 2000: continue
            offs = struct.unpack_from('<%dH' % nrows, b, 14)
            for rn in range(nrows):
                raw = offs[rn]
                # 0x8000 deleted; 0x4000 = pointer to an overflow row that lives (and is read) on its own page
                if raw & 0xC000: continue
                r = self._rowbytes(pg, rn)
                if r is None: continue
                try: d = self._crack(cols, r)
                except Exception: d = None
                if d is not None: yield d

    def columns(self, table):
        return [c['name'] for c in self.tdef(self.tables[table][0])]

    def rows(self, table):
        return self._rows(self.tables[table][0])

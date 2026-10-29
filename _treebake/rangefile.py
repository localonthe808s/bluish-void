import io, urllib.request
class RangeFile(io.RawIOBase):
    """read-only file over HTTP Range requests, 4 MB blocks cached"""
    def __init__(self, url, block=4 << 20):
        self.url, self.block, self.pos, self.cache = url, block, 0, {}
        r = urllib.request.urlopen(urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'bluish-void bake'}), timeout=60)
        self.size = int(r.headers['Content-Length']); self.hits = 0
    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.pos
    def seek(self, off, whence=0):
        self.pos = off if whence == 0 else self.pos + off if whence == 1 else self.size + off; return self.pos
    def _blk(self, i):
        if i not in self.cache:
            a = i * self.block; b = min(self.size, a + self.block) - 1
            req = urllib.request.Request(self.url, headers={'Range': 'bytes=%d-%d' % (a, b), 'User-Agent': 'bluish-void bake'})
            self.cache[i] = urllib.request.urlopen(req, timeout=120).read(); self.hits += 1
            if len(self.cache) > 400: self.cache.pop(next(iter(self.cache)))
        return self.cache[i]
    def readinto(self, buf):
        n = len(buf); end = min(self.size, self.pos + n); out = bytearray()
        p = self.pos
        while p < end:
            i = p // self.block; blk = self._blk(i); o = p - i * self.block; take = blk[o:o + (end - p)]; out += take; p += len(take)
        buf[:len(out)] = out; self.pos = p; return len(out)

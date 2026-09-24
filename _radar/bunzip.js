/*
 * bunzip.js -- a small bzip2 decompressor for the browser (window.bvBunzip).
 *
 * Written from scratch for bluishvoid.com from the published description of
 * the bzip2 format (Burrows-Wheeler + MTF + Huffman, Julian Seward's bzip2).
 * No code was copied from any other implementation.
 *
 * Licence: public domain (CC0 1.0). Do what you like with it.
 *
 * API:  bvBunzip(u8)  -> Uint8Array   (handles concatenated streams; throws
 *       on corrupt input). CRCs are not verified (callers check sizes).
 */
(function (root) {
  'use strict';

  function Bits(u8, pos) {
    this.u8 = u8; this.pos = pos || 0; this.buf = 0; this.n = 0;
  }
  Bits.prototype.get = function (k) {          // k <= 24
    while (this.n < k) {
      if (this.pos >= this.u8.length) throw new Error('bunzip: unexpected end of data');
      this.buf = ((this.buf << 8) | this.u8[this.pos++]) >>> 0;
      this.n += 8;
    }
    this.n -= k;
    var v = (this.buf >>> this.n) & ((1 << k) - 1);
    this.buf &= (1 << this.n) - 1;
    return v;
  };
  Bits.prototype.bit = function () {
    if (this.n === 0) {
      if (this.pos >= this.u8.length) throw new Error('bunzip: unexpected end of data');
      this.buf = this.u8[this.pos++]; this.n = 8;
    }
    this.n--;
    var v = (this.buf >>> this.n) & 1;
    this.buf &= (1 << this.n) - 1;
    return v;
  };
  Bits.prototype.align = function () { this.n = 0; this.buf = 0; };

  // Growable output
  function Out(hint) { this.a = new Uint8Array(hint || 65536); this.len = 0; }
  Out.prototype.ensure = function (k) {
    if (this.len + k <= this.a.length) return;
    var sz = this.a.length * 2; while (sz < this.len + k) sz *= 2;
    var b = new Uint8Array(sz); b.set(this.a.subarray(0, this.len)); this.a = b;
  };

  var MAX_GROUPS = 6, MAX_ALPHA = 258, MAX_LEN = 20, G_SIZE = 50;

  // Build canonical Huffman decode tables for one group
  function makeTable(lens, alphaSize) {
    var minL = 32, maxL = 0, i, L;
    for (i = 0; i < alphaSize; i++) { if (lens[i] > maxL) maxL = lens[i]; if (lens[i] < minL) minL = lens[i]; }
    var perm = new Int32Array(alphaSize), p = 0;
    var limit = new Int32Array(MAX_LEN + 2), base = new Int32Array(MAX_LEN + 2);
    for (L = minL; L <= maxL; L++) for (i = 0; i < alphaSize; i++) if (lens[i] === L) perm[p++] = i;
    var code = 0, idx = 0;
    for (L = minL; L <= maxL; L++) {
      var cnt = 0;
      for (i = 0; i < alphaSize; i++) if (lens[i] === L) cnt++;
      base[L] = idx - code;               // perm index = code + base[L]
      code += cnt; idx += cnt;
      limit[L] = code - 1;                // last code of this length (-1 if none)
      code <<= 1;
    }
    return { minL: minL, maxL: maxL, perm: perm, limit: limit, base: base };
  }

  function decodeBlock(br, blockSize, out) {
    br.get(16); br.get(16);                       // block CRC (unchecked)
    if (br.bit()) throw new Error('bunzip: randomised blocks not supported');
    var origPtr = br.get(24);

    // symbol map
    var used16 = br.get(16), seqToUnseq = new Uint8Array(256), nInUse = 0, i, j;
    for (i = 0; i < 16; i++) if (used16 & (0x8000 >>> i)) {
      var w = br.get(16);
      for (j = 0; j < 16; j++) if (w & (0x8000 >>> j)) seqToUnseq[nInUse++] = i * 16 + j;
    }
    if (!nInUse) throw new Error('bunzip: empty symbol map');
    var alphaSize = nInUse + 2, EOB = nInUse + 1;

    var nGroups = br.get(3);
    if (nGroups < 2 || nGroups > MAX_GROUPS) throw new Error('bunzip: bad group count');
    var nSel = br.get(15);
    if (!nSel) throw new Error('bunzip: no selectors');
    var mtfG = [0, 1, 2, 3, 4, 5], selectors = new Uint8Array(nSel);
    for (i = 0; i < nSel; i++) {
      j = 0; while (br.bit()) { j++; if (j >= nGroups) throw new Error('bunzip: bad selector'); }
      var v = mtfG[j]; while (j > 0) { mtfG[j] = mtfG[j - 1]; j--; } mtfG[0] = v;
      selectors[i] = v;
    }

    var tables = [], lens = new Uint8Array(MAX_ALPHA);
    for (var g = 0; g < nGroups; g++) {
      var len = br.get(5);
      for (i = 0; i < alphaSize; i++) {
        for (;;) {
          if (len < 1 || len > MAX_LEN) throw new Error('bunzip: bad code length');
          if (!br.bit()) break;
          len += br.bit() ? -1 : 1;
        }
        lens[i] = len;
      }
      tables.push(makeTable(lens, alphaSize));
    }

    // Huffman + RUNA/RUNB + MTF -> tt (low 8 bits = byte)
    var tt = new Int32Array(blockSize), count = new Int32Array(256), n = 0;
    var mtf = new Uint8Array(256); for (i = 0; i < 256; i++) mtf[i] = i;
    var selIdx = 0, left = 0, t = null, run = 0, runW = 1, sym, uc;
    for (;;) {
      if (left === 0) {
        if (selIdx >= nSel) throw new Error('bunzip: selectors exhausted');
        t = tables[selectors[selIdx++]]; left = G_SIZE;
      }
      left--;
      var L2 = t.minL, c = br.get(L2);
      while (c > t.limit[L2]) { L2++; if (L2 > t.maxL) throw new Error('bunzip: bad code'); c = (c << 1) | br.bit(); }
      sym = t.perm[c + t.base[L2]];

      if (sym <= 1) {                            // RUNA / RUNB
        run += (sym + 1) * runW; runW <<= 1;
        if (run > blockSize) throw new Error('bunzip: run overflow');
        continue;
      }
      if (run) {
        uc = seqToUnseq[mtf[0]];
        if (n + run > blockSize) throw new Error('bunzip: block overflow');
        count[uc] += run;
        while (run--) tt[n++] = uc;
        run = 0; runW = 1;
      }
      if (sym === EOB) break;
      j = sym - 1; var m = mtf[j];
      while (j > 0) { mtf[j] = mtf[j - 1]; j--; } mtf[0] = m;
      uc = seqToUnseq[m];
      if (n >= blockSize) throw new Error('bunzip: block overflow');
      count[uc]++; tt[n++] = uc;
    }
    if (origPtr >= n) throw new Error('bunzip: bad origPtr');

    // inverse BWT
    var cf = new Int32Array(256), s = 0;
    for (i = 0; i < 256; i++) { cf[i] = s; s += count[i]; }
    for (i = 0; i < n; i++) { uc = tt[i] & 0xff; tt[cf[uc]++] |= (i << 8); }

    // walk + undo the initial RLE (4 equal bytes then a repeat count)
    out.ensure(n * 2);
    var pos = tt[origPtr] >>> 8, last = -1, same = 0, a;
    for (i = 0; i < n; i++) {
      a = tt[pos]; var b = a & 0xff; pos = a >>> 8;
      if (same === 4) {
        out.ensure(b);
        for (j = 0; j < b; j++) out.a[out.len++] = last;
        same = 0; last = -1;
        continue;
      }
      if (b === last) same++; else { same = 1; last = b; }
      out.ensure(1);
      out.a[out.len++] = b;
    }
  }

  function bunzip(u8) {
    if (!(u8 instanceof Uint8Array)) u8 = new Uint8Array(u8);
    var out = new Out(u8.length * 4), br = new Bits(u8, 0), streams = 0;
    while (br.pos < u8.length) {
      // stream header 'BZh1'..'BZh9' (byte aligned)
      if (br.pos + 4 > u8.length || u8[br.pos] !== 0x42 || u8[br.pos + 1] !== 0x5a || u8[br.pos + 2] !== 0x68) {
        if (streams) break;                        // trailing padding
        throw new Error('bunzip: not a bzip2 stream');
      }
      var lvl = u8[br.pos + 3] - 0x30;
      if (lvl < 1 || lvl > 9) throw new Error('bunzip: bad level');
      br.pos += 4; br.align();
      var blockSize = lvl * 100000;
      for (;;) {
        var h1 = br.get(24), h2 = br.get(24);
        if (h1 === 0x314159 && h2 === 0x265359) { decodeBlock(br, blockSize, out); continue; }
        if (h1 === 0x177245 && h2 === 0x385090) { br.get(16); br.get(16); br.align(); break; }
        throw new Error('bunzip: bad block magic');
      }
      streams++;
    }
    return out.a.slice(0, out.len);
  }

  root.bvBunzip = bunzip;
})(typeof window !== 'undefined' ? window : this);

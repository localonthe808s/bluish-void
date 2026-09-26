/* bvSkyGL -- the golden-hour / sky-art clouds on the GPU (2026-09-26, prototype).
   User: "i think we're learning something the cloud artworks for golden hour never could" ... "the cloud artworks in golden
   hour next". The SVG renderer (renderCloudsSVG, ~5,800 lines) draws each genus by hand; this composes the SAME classifier
   output (classifyClouds: [{genus, species, layer, cover}]) from bvCloudGL's two shapes -- the lobed tower and the anchor
   deck -- lit by the real sun: at golden hour it sits on the horizon, so undersides and the sun side catch fire.
   Sky units: W x H with y measured UP from the panel's bottom; `hz` is the horizon (the terrain's top edge).
   Seeded, so the same sky draws the same clouds every frame; `t` only drifts and boils them. */
(function(){
  function rng(seed){ var s = seed >>> 0 || 1; return function(){ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  /* the light, from the sun's altitude: golden (0..6 deg) low and warm from the right, blue hour pink-violet, night moonlit */
  function light(sa){
    if (sa > 12) return { d: [-0.5, 0.8], c: [1.04, 0.99, 0.93], s: [0.56, 0.58, 0.66], n: 0 };
    if (sa > 0){ var k = Math.min(1, sa / 12);
      return { d: [0.95 - 1.45 * k, -0.12 + 0.92 * k], c: [1.22 - 0.18 * k, 0.86 + 0.13 * k, 0.66 + 0.27 * k], s: [0.66 - 0.10 * k, 0.48 + 0.10 * k, 0.52 + 0.14 * k], n: 0 }; }   /* peach-cream lit, dusky rose shade */
    if (sa > -6){ var b = -sa / 6;                      /* blue hour: the light from below the horizon, pink fading to violet */
      return { d: [0.9, -0.35], c: [1.02 - 0.45 * b, 0.62 - 0.22 * b, 0.62 - 0.02 * b], s: [0.30 - 0.14 * b, 0.26 - 0.12 * b, 0.40 - 0.14 * b], n: 0.3 * b }; }
    return { d: [0.2, 0.9], c: [0.50, 0.54, 0.68], s: [0.08, 0.10, 0.16], n: 1 };
  }
  window.bvSkyGL = function(ctx, o){
    if (!window.bvCloudGL || !bvCloudGL.ok()) return false;
    var W = o.W || 220, H = o.H || 232, hz = o.hz == null ? 50 : o.hz, t = o.t || 0, L = light(o.sa == null ? 3 : o.sa);
    var base = { ns: o.ns || 0.5, W: W, H: H, ppu: o.ppu || 2.5, t: t, night: L.n, sunDir: L.d, sunCol: L.c, shdCol: L.s, ground: hz };
    var byLayer = { high: [], mid: [], low: [], deep: [] };
    (o.types || []).forEach(function(ty){ (byLayer[ty.layer] || byLayer.low).push(ty); });
    var OFF = [9000, 9001, -3, -2];   /* bands switched off -- never equal edges: smoothstep(e, e, x) is undefined and cut hard lines */
    var draw = function(extra){ bvCloudGL(ctx, Object.assign({}, base, extra)); };
    var cov = function(ty){ return Math.max(0, Math.min(100, ty.cover || 0)) / 100; };
    /* the renderer takes 48 anchors a call: a big field goes in several calls */
    var drawField = function(P, extra){ for (var q = 0; q < P.length; q += 48) draw(Object.assign({ puffs: P.slice(q, q + 48) }, extra)); };
    var sky = H - hz;
    /* rows in perspective: near rows high and big, far rows low and small, converging on the horizon */
    var rowsOf = function(R, c, yTop, yBot, rNear, rFar, gap, fill){
      var P = [], nR = 5 + Math.round(4 * c);
      for (var r = 0; r < nR; r++){ var f = r / (nR - 1), yy = yTop + (yBot - yTop) * Math.pow(f, 1.5), rr = rNear + (rFar - rNear) * f;
        for (var x = -rr + R() * rr * 2; x < W + rr; x += rr * gap * (0.8 + 0.5 * R())){ if (R() > fill) continue; P.push([x, yy + (R() - 0.5) * rr * 0.5, rr * (0.8 + 0.4 * R()), 0.75 + 0.25 * R()]); } }
      return P;
    };
    /* HIGH: ice. Cirrus / cirrostratus: long fibrous streaks; cirrocumulus: small grains in rows */
    byLayer.high.forEach(function(ty, i){
      var R = rng(101 + i * 17), c = cov(ty);
      if (ty.genus === 'Cirrocumulus'){
        drawField(rowsOf(R, c, H - 8, hz + sky * 0.62, 3.8, 1.8, 2.1, 0.35 + 0.55 * c), { band: OFF, dens: 0.85 });
      } else {
        var P = [], n = ty.genus === 'Cirrostratus' ? 30 : 14 + 30 * c;
        for (var j = 0; j < n; j++){ var yy = hz + sky * (0.55 + 0.42 * R()); P.push([R() * W, yy, (ty.genus === 'Cirrostratus' ? 22 : 12) + R() * 12, 0.55 + 0.35 * R()]); }
        drawField(P, { band: [0, 1, -3, -2], dens: ty.genus === 'Cirrostratus' ? 0.5 : 0.85 });
      }
    });
    /* MID: altocumulus -- big puffy patches in perspective rows (the site's rule); altostratus -- a smooth grey sheet */
    byLayer.mid.forEach(function(ty, i){
      var R = rng(211 + i * 29), c = cov(ty);
      if (ty.genus === 'Altostratus'){
        var P = []; for (var j = 0; j < 12; j++) P.push([j * W / 11, hz + sky * 0.55 + (R() - 0.5) * 10, 28, 0.55 + 0.4 * c]);
        draw({ puffs: P, lean: 9, band: OFF, dens: 0.5 + 0.45 * c });
      } else {
        /* each patch a CLUSTER of 3-5 round puffs, so it has lobes and a ragged outline -- one big anchor made a smooth pill */
        var seeds = rowsOf(R, c, hz + sky * 0.82, hz + sky * 0.30, 13, 4.5, 2.6, 0.3 + 0.65 * c), P3 = [];
        seeds.forEach(function(sd){ var n3 = 3 + Math.floor(R() * 3); for (var m = 0; m < n3; m++) P3.push([sd[0] + (R() - 0.5) * sd[2] * 1.6, sd[1] + (R() - 0.35) * sd[2] * 0.6, sd[2] * (0.45 + 0.25 * R()), sd[3]]); });
        drawField(P3, { band: OFF, dens: 1 });
      }
    });
    /* LOW and DEEP */
    byLayer.low.concat(byLayer.deep).forEach(function(ty, i){
      var R = rng(307 + i * 41), c = cov(ty), g = ty.genus;
      if (g === 'Cumulonimbus'){
        draw({ cx: W * 0.5, base: hz + 12, h: sky * 0.74, hw: 30, lean: 0.8, anvil: 1, anvR: 90, anvL: 44, rain: 0.9, band: OFF, dens: 1 });
        return;
      }
      if (g === 'Cumulus'){
        /* a field of cumulus in perspective: big near ones higher and to the sides, small far ones on the horizon */
        var nC = 4 + Math.round(10 * c), cells = [];
        for (var k = 0; k < nC; k++){ var f = R(), cx = R() * W, sz = 0.45 + 0.9 * (1 - f);
          cells.push({ cx: cx, base: hz + 4 + f * 0 + (1 - f) * sky * 0.18, hw: 9 + 14 * sz, h: (14 + 30 * c) * sz * (0.8 + 0.5 * R()), f: f }); }
        cells.sort(function(a, b){ return a.f < b.f ? 1 : -1; });        /* far ones first */
        cells.forEach(function(cc, k2){ draw({ cx: cc.cx, base: cc.base, h: Math.max(cc.h, cc.hw * 1.5), hw: cc.hw, lean: 0.2, anvil: 0, rain: 0, band: OFF, dens: 1, t: t + k2 * 13 }); });
        return;
      }
      /* decks: stratocumulus -- big rolls in rows; stratus smooth; nimbostratus smooth and dark */
      var smooth = g === 'Stratus' || g === 'Nimbostratus';
      if (smooth){
        var P2 = [], y = hz + (g === 'Nimbostratus' ? sky * 0.45 : sky * 0.22);
        for (var j2 = 0; j2 < 14; j2++) P2.push([j2 * W / 13, y + (R() - 0.5) * 8, 30, 0.8 + 0.2 * R()]);
        var ex = { puffs: P2, lean: 9, band: OFF, dens: 1 };
        if (g === 'Nimbostratus') ex.shdCol = [L.s[0] * 0.7, L.s[1] * 0.7, L.s[2] * 0.75];
        draw(ex);
      } else {
        drawField(rowsOf(R, c, hz + sky * 0.62, hz + sky * 0.10, 17, 7, 1.7, 0.45 + 0.55 * c), { band: OFF, dens: 1 });
      }
    });
    return true;
  };
})();

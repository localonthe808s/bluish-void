/* bvHeroGL -- the live-weather hero's CLOUDS on the GPU (2026-09-26, user: "update them all").
   The hero's SVG clouds (blurred ellipses under a fractal filter) are replaced by the renderer the front scenes and the
   golden-hour sky use: bvCloudGL's lit, textured decks and towers, and bvSky2 for fair-weather cumulus and fog. The SVG
   keeps what animates -- rain streaks, snow, sleet, hail, lightning -- drawn over this with _HERO_NOCLOUD set, so the
   drops still fall from the cloud base. Rendered once per scene (static), so it costs nothing per frame.
   Scene units: 393 across (a phone's width), y UP from the bottom; `base` is where the precipitation spawns. */
(function(){
  function rng(seed){ var s = seed >>> 0 || 1; return function(){ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  var OFF = [9000, 9001, -3, -2];
  /* per state: how dark the underside, how low and deep the deck, whether a tower rises through it */
  var LOOK = {
    'drizzle':    { shd: [.60, .64, .70], lit: [.96, .97, 1.0], rows: 3, rMul: .9,  strat: .8, scud: 4 },
    'rain':       { shd: [.46, .51, .59], lit: [.90, .92, .96], rows: 4, rMul: 1,   strat: .6, scud: 7 },
    'rain-heavy': { shd: [.34, .38, .46], lit: [.82, .85, .90], rows: 5, rMul: 1.1, strat: .3, scud: 10, tower: .75 },
    'freezing':   { shd: [.52, .57, .65], lit: [.92, .94, .98], rows: 4, rMul: .95, strat: .7, scud: 5 },
    'snow':       { shd: [.66, .70, .77], lit: [1.0, 1.0, 1.02], rows: 4, rMul: 1,  strat: .9, scud: 3 },
    'sleet':      { shd: [.56, .61, .69], lit: [.94, .95, .99], rows: 4, rMul: .95, strat: .7, scud: 5 },
    'storm':      { shd: [.28, .31, .39], lit: [.86, .88, .93], rows: 4, rMul: 1.1, strat: .2, scud: 9, tower: 1 },
    'storm-hail': { shd: [.26, .29, .37], lit: [.88, .89, .94], rows: 4, rMul: 1.15, strat: .15, scud: 9, tower: 1.12 },
    'overcast':   { shd: [.54, .58, .65], lit: [.93, .94, .97], rows: 6, rMul: 1.05, strat: 1, scud: 0, full: 1 }
  };
  /* where the main cloud's underside came out, px from the top of the box: the lowest row that is cloud across most of
     the middle third (the far clouds sit at the sides and are not counted) */
  function underside(ctx, o){
    var cw = ctx.canvas.width, ch = ctx.canvas.height, x0 = Math.floor(cw * 0.36), x1 = Math.ceil(cw * 0.64), d;
    try { d = ctx.getImageData(x0, 0, x1 - x0, ch).data; } catch (e){ return null; }
    var w = x1 - x0, stepX = Math.max(1, Math.floor(w / 60));
    var row = function(y){ var n = 0, m = 0; for (var x = 0; x < w; x += stepX){ m++; if (d[(y * w + x) * 4 + 3] > 150) n++; } return n / m; };
    var bot = null, top = null;
    for (var y = ch - 1; y >= 0; y -= 2) if (row(y) > 0.6){ bot = y / (o.dpr || 1); break; }
    if (bot == null) return null;
    /* and its crown: the highest row with any cloud in it, walking up from the underside (so a row of 0 is sky above) */
    top = 0; for (var y2 = Math.round(bot * (o.dpr || 1)); y2 >= 0; y2 -= 2) if (row(y2) < 0.04){ top = y2 / (o.dpr || 1); break; }
    return { bottom: bot, top: top }; }
  window.bvHeroGL = function(ctx, o){
    if (!window.bvCloudGL || !bvCloudGL.ok()) return false;
    /* o.hold (px from the top): put the underside THERE. Draw, measure, lower or raise the base by the miss, draw again;
       the scene is static, so this is paid once.
       o.topMin (px): AND THE WHOLE CLOUD IS SHOWN (user 2026-09-29, of a crown cut flat under the summary: "should we be
       clipping them like this? should the cloud show its full height?"). The layer begins under the summary and the
       mass ran out of its top. The heap is squashed (its lobes keep their size, they stack less high) until the crown
       is topMin below the layer's top edge */
    if (o.hold != null && o.baseUp != null && !o._pass){
      var lift = Math.max(0, o.lift || 0), sq = 1, got = null, res = false, tm = o.topMin == null ? 0 : o.topMin;
      /* THE FITTING IS DONE SMALL (2026-09-29): the passes that only find the outline draw the main mass alone, one GPU
         pixel a unit on a canvas 393 wide -- a ninth of the pixels and a fifth of the draws; the picture itself is
         drawn once, at the end. Fitted at full size, a rain hero was six whole renders */
      var mc = document.createElement('canvas'), mk = 393 / o.W; mc.width = 393; mc.height = Math.max(1, Math.round(o.H * mk));
      var mx = mc.getContext('2d', { willReadFrequently: true }), mo = Object.assign({}, o, { dpr: mk });
      for (var pass = 0; pass < 6; pass++){
        mx.setTransform(1, 0, 0, 1, 0, 0); mx.clearRect(0, 0, mc.width, mc.height);
        res = window.bvHeroGL(mx, Object.assign({}, mo, { _pass: 1, _measure: 1, lift: lift, squash: sq, baseUp: o.baseUp - lift }));
        if (!res) return false;
        got = underside(mx, mo); if (got == null) break;
        var miss = o.hold - got.bottom, over = tm - got.top;
        if ((Math.abs(miss) < 3 && over < 3) || pass === 5) break;
        var nl = Math.max(0, lift + miss), ns = sq;
        if (over >= 3) ns = Math.max(0.3, sq * Math.max(0.5, ((got.bottom - got.top) - over * 1.15) / Math.max(20, got.bottom - got.top)));
        if (nl === lift && ns === sq) break; lift = nl; sq = ns;
      }
      res = window.bvHeroGL(ctx, Object.assign({}, o, { _pass: 1, lift: lift, squash: sq, baseUp: o.baseUp - lift }));
      if (!res) return false;
      return { bottom: got ? got.bottom : null, top: got ? got.top : null, lift: lift, squash: sq };
    }
    var W = 393, H = Math.round(393 * o.H / o.W), st = o.state, night = !!o.night, R = rng(o.seed || 7);
    var ppu = o._measure ? 1 : Math.min(3, Math.max(1.5, o.W / 393 * (o.dpr || 1) * 0.75));
    ctx.save(); ctx.setTransform(o.W / W * (o.dpr || 1), 0, 0, o.W / W * (o.dpr || 1), 0, 0);
    try {
      if (st === 'partly' || st === 'fog'){
        if (!window.bvSky2){ return false; }
        var types = st === 'partly' ? [{ genus: 'Cumulus', species: 'mediocris', layer: 'low', cover: 38 }] : [{ genus: 'Fog', species: 'moderate', layer: 'low', cover: 100 }];
        var ok2 = bvSky2(ctx, { W: W, H: H, hz: 6, sa: night ? -20 : 40, types: types, ppu: ppu, dens: W / 220 });
        if (ok2 && night){ ctx.save(); ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = st === 'fog' ? 'rgba(120,135,165,.45)' : 'rgba(70,90,135,.42)'; ctx.fillRect(0, 0, W, H); ctx.restore(); }   /* moonlit: cool blue-grey, not the dark brown the night palette gave */
        return ok2;
      }
      var L = LOOK[st]; if (!L) return false;
      var base = o.baseUp == null ? H * 0.42 : o.baseUp * W / o.W;   /* where the drops spawn, in scene units, from the bottom */
      var lift = Math.max(0, (o.lift || 0) * W / o.W), sq = o.squash == null ? 1 : o.squash, tmU = (o.topMin || 0) * W / o.W;              /* how far the base was lowered to hold the readout: the mass is that much TALLER, its top and the far clouds stay */
      var shd = night ? L.shd.map(function(v){ return v * 0.32; }) : L.shd, lit = night ? [0.42, 0.46, 0.58] : L.lit;
      var common = { W: W, H: H, ppu: ppu, t: (o.seed || 7) * 3, night: night ? 1 : 0, sunDir: night ? [0.2, 0.95] : [-0.25, 0.97], sunCol: lit, shdCol: shd, ground: 0, band: OFF, ns: 0.62,
        tex: o.tex == null ? 1 : o.tex, texP: o.texP, texQ: o.texQ, texB: L.full ? null : base };   /* the hero's own texture (cloud_gl uTex) */
      /* a tall panel (a phone's) grows the lobes by sqrt(tall): the relief on them grows with them, or the same wrinkles sit
         on bigger, gentler lobes and take over -- measured on a 393 x 620 panel, the cloud went back to crumpled paper */
      var tallK = Math.sqrt(Math.max(1, H / 220) + lift / 60);
      if (common.tex && !L.full){ common.ns = 0.62 / tallK; if (!common.texQ) common.texQ = [13, 2.8, 1.3 * tallK, 1.3]; }
      /* THE DECK: rows of lobes from the base up past the top, bigger and flatter with height, so it reads as one ceiling
         seen from below -- lumpy undersides, a lit upper body */
      var sc = function(v, a){ return 'rgba(' + Math.round(v[0] * 255) + ',' + Math.round(v[1] * 255) + ',' + Math.round(v[2] * 255) + ',' + a + ')'; };
      var b0 = L.full ? H * 0.34 : base, P = [];
      if (L.full){
        /* OVERCAST: the ceiling in RANKS receding toward the horizon, as the old SVG deck was built -- the nearest rank high,
           big and lumpy, each further one lower, smaller and hazier, a thin lighter seam of sky-glow between them. Each rank is
           its own call (a separate layer at its own depth) */
        var ranks = [[H + 10, H * 0.56, 30, 1], [H * 0.6, H * 0.42, 20, 0.92], [H * 0.45, H * 0.31, 13, 0.85], [H * 0.33, H * 0.24, 8, 0.78]];
        ranks.forEach(function(rk, ri){ var Q = [];
          /* NO MORE LOBES THAN THE RENDERER TAKES (2026-09-29). bvCloudGL draws 48 puffs a call and the rest were cut: on
             a desktop panel (184 units tall) the nearest rank wants ~56, on a phone's (760 tall) 150, and it came out as a
             field of separate dark pills. The lobes grow, 5% at a time, until the rank fits -- a tall panel is a ceiling
             seen from closer */
          var rr0 = rk[2] * L.rMul, need = function(q){ return Math.ceil((rk[0] - rk[1]) / (q * 0.8)) * ((W + 1.5 * q) / (1.25 * q)) + (W + q) / (1.1 * q); };
          for (var gi = 0; gi < 40 && need(rr0) > 46; gi++) rr0 *= 1.05;
          for (var yy = rk[0]; yy > rk[1]; yy -= rr0 * 0.8) for (var xx = -rr0 * 0.5 + R() * rr0; xx < W + rr0; xx += rr0 * (1.0 + 0.5 * R())) Q.push([xx, yy + (R() - 0.5) * rr0 * 0.5, rr0 * (0.7 + 0.5 * R()), 0.85 + 0.15 * R()]);
          for (var xb2 = R() * rr0; xb2 < W + rr0; xb2 += rr0 * (0.8 + 0.6 * R())) Q.push([xb2, rk[1] + rr0 * 0.1 - R() * R() * rr0 * 0.6, rr0 * (0.45 + 0.35 * R()), 0.8]);   /* the rank's torn underside */
          Q.sort(function(a, b){ return b[3] - a[3]; });
          var fade = rk[3];
          /* distance flattens and hazes a rank: less relief, less contrast (lit and shade both drift to the horizon's grey) */
          var hz = 1 - fade, hzc = night ? [0.2, 0.22, 0.27] : [0.6, 0.63, 0.68];
          bvCloudGL(ctx, Object.assign({}, common, { puffs: Q.slice(0, 48), lean: 0, strat: Math.min(1, hz * 4.5), base: 0, h: 1, hw: 1, cx: 0, dens: 1, ns: ri === 0 ? 0.5 : 0.62 * (34 / rk[2]) * 0.5,
            sunCol: lit.map(function(v, ci){ return v + (hzc[ci] + 0.12 - v) * hz * 3; }), shdCol: shd.map(function(v, ci){ return v + (hzc[ci] - v) * hz * 3; }) })); });
        P = null;
      } else {
        /* THE RAIN CLOUD, as the hero has always framed it: ONE great mass across the middle, its base where the drops start --
           a flat-ish, lumpy underside, heaped and lit above, the edges torn -- now drawn as a real cloud */
        var tall = Math.max(1, H / 220), cx0 = W * 0.5, hw0 = W * (0.36 + 0.05 * (L.rMul - 1) * 4) * (tall > 1.5 ? 1.25 : 1), ht = ((L.tower ? 70 : 52) * L.rMul * tall + lift) * sq;   /* a tall phone panel: the mass grows with it */
        tall = tall + lift / 60;                                      /* and its lobes with the mass */
        for (var rr = 0; rr < 5; rr++){ var f2 = rr / 4, y2 = b0 + 6 + ht * f2, half = hw0 * Math.sqrt(1 - f2 * f2 * 0.85), r2 = (15 + 10 * (1 - Math.abs(f2 - 0.4))) * L.rMul * Math.sqrt(tall);
          for (var x2 = cx0 - half + R() * r2 * 0.5; x2 < cx0 + half; x2 += r2 * (0.9 + 0.5 * R())) P.push([x2, y2 + (R() - 0.5) * r2 * 0.6, r2 * (0.75 + 0.5 * R()), 0.85 + 0.15 * R()]); }
        for (var xh = cx0 - hw0 * 1.05; xh < cx0 + hw0 * 1.05; xh += 16 + R() * 18) P.push([xh, b0 + 3 - R() * R() * 12, 7 + R() * 9, 0.7 + 0.25 * R()]);   /* the torn, uneven base */
        /* THE CROWN (2026-09-29): a row of separate heads along the top, each its own size and height, so the outline is
           heaped -- a cloud's -- and not one smooth loaf. Weight 1: they are kept when the list is cut to 48 */
        if (common.tex){ var nT = o.turrets == null ? 5 : o.turrets, R2 = rng((o.seed || 7) * 31 + 5);
          for (var ti = 0; ti < nT; ti++){ var u = (ti + 0.2 + 0.6 * R2()) / nT * 2 - 1, rt = (17 + 13 * R2()) * L.rMul * Math.sqrt(tall) * (1 - 0.35 * u * u);
            P.push([cx0 + u * hw0 * 0.86, b0 + 6 + ht * Math.sqrt(Math.max(0.05, 1 - u * u * 0.85)) * (0.68 + 0.26 * R2()) , rt, 1]); }
          /* the storm's tower, in the SAME field: heads stacked up from the crown, leaning a little, so it is the cloud's
             own growth and is lit with it -- the separate column in front read as a pillar stood against the cloud */
          if (L.tower) for (var tj = 0; tj < 4; tj++){ var tr = (31 - tj * 3.5) * L.rMul * Math.sqrt(tall);
            P.push([cx0 + 6 + tj * 5, Math.min(H - tmU - tr * 1.25 - 4, b0 + 6 + ht * (0.75 + 0.36 * tj * L.tower)), tr, 1]); } }   /* its head stays inside the panel: cut by the top edge it was a flat lid */
      }
      if (P){ P.sort(function(a, b){ return b[3] - a[3]; }); P = P.slice(0, 48);
      bvCloudGL(ctx, Object.assign({}, common, { puffs: P, lean: 0, strat: 0, base: 0, h: 1, hw: 1, cx: 0, dens: 1 })); }
      if (o._measure) return true;                                    /* the outline is all a fitting pass is for */
      /* seen from below, a rain cloud is darkest at its base: tone the cloud pixels only */
      var yB = H - b0, g1 = ctx.createLinearGradient(0, yB - (L.full ? H : 90), 0, yB + 30);
      g1.addColorStop(0, sc(shd, 0)); g1.addColorStop(1, sc(shd.map(function(v){ return v * 0.75; }), L.full ? 0.22 : 0.45));
      if (!L.full){ ctx.save(); ctx.globalCompositeOperation = 'source-atop'; ctx.fillStyle = g1; ctx.fillRect(0, 0, W, yB + 40); ctx.restore(); }   /* past the hanging lobes: a lighter lip under the toned base read as a line */
      /* FAR CLOUDS, low on either side (the old scene's far precip): small separate masses, hazier */
      if (!L.full) [[0.1, 0.8], [0.9, 0.85], [0.03, 0.55], [0.97, 0.6]].forEach(function(fc, i){ var Q = [], fx = W * fc[0], fy = (b0 + lift) * fc[1] - 6, fr = 8 + R() * 5;
        for (var m = 0; m < 7; m++){ var mu = (m - 3) / 3; Q.push([fx + mu * fr * 2.4 + (R() - 0.5) * 5, fy + (1 - mu * mu) * fr * 0.9 + R() * 3, fr * (0.75 + 0.45 * R()) * (1 - 0.3 * Math.abs(mu)), 0.85]); }    /* a small heaped cloud, not a lens */
        bvCloudGL(ctx, Object.assign({}, common, { puffs: Q, lean: 0, strat: 0, base: 0, h: 1, hw: 1, cx: 0, dens: 0.8, ns: 0.62, tex: 0, sunCol: lit.map(function(v){ return v * 0.94; }) })); });   /* far and small: the old flat heaps (the rounder lobes strung them into beads) */
      /* A TOWER through it for the heavy states: the storm's own body, rising off the top */
      if (L.tower && !common.tex){ bvCloudGL(ctx, Object.assign({}, common, { cx: W * 0.5, base: base - 4, h: (H - base) * 1.3, hw: 46 * L.tower, lean: 0.3, anvil: 0, rain: 0, rag: 3.5, dens: 1, ns: 0.5 })); }
      return true;
    } finally { ctx.restore(); }
  };
})();

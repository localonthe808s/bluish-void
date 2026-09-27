/* bvSeaGL -- THE BASIN's SURF sea on the GPU (2026-09-27, user: "go for it", after the sea lab at _maplab/sealab/).
   The map lab still solves the swell per pixel (travel time bent over the depths, shoaling, the islands' shadows); this
   draws it: long crests as shades of the water's own blue (no white paint), wind cat's-paws and glassy slicks from the
   live wind, river plumes after rain, and breakers placed on the real seafloor -- NOAA CUDEM fetched for the view, a wave
   breaking where the water is shallower than its Komar & Gaughan breaker depth. Everything the lab learned is kept:
   the survey's shoreline sits inland of the drawn beach (slope laid out from the map's own waterline), 0-filled survey
   tiles are holes, the site's water mask is blocky (cleaned against the drawn map), text and icons are not coast.
   Returns false when WebGL is unavailable, and the caller keeps its CPU drawing. */
(function(){
  var VS = 'attribute vec2 p; varying vec2 vUv; void main(){ vUv = vec2(p.x * .5 + .5, .5 - p.y * .5); gl_Position = vec4(p, 0., 1.); }';
  var FS = [
  'precision highp float;',
  'varying vec2 vUv;',
  'uniform sampler2D t1, t2, t3, t4, t5, nz, dt, dp, wm;',
  'uniform vec2 uRes;',
  'uniform float uT, uTV, uAmp, uW2, uR2, uCr, uCw, uTr, uTx, uFo, uDrift, uMpp, uWind, uEx, uBrk, uRag, uPl, uZone, uDbg, uLpx, uHb0, uWd;',
  'uniform vec2 uDir, uWdir;',
  'uniform vec2 uM[4], uDc[4];',                            /* river mouths, in pixels, and each one\u2019s downcoast way */
  'uniform float uMn;',
  'float NZ(vec2 cr){ return texture2D(nz, (cr + .5) / 256.).r; }',
  'float h(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }',
  'float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f); return mix(mix(h(i), h(i + vec2(1., 0.)), f.x), mix(h(i + vec2(0., 1.)), h(i + vec2(1., 1.)), f.x), f.y); }',
  'float fbm(vec2 p){ float s = 0., a = .5; for (int i = 0; i < 4; i++){ s += a * vn(p); p = p * 2.03 + 17.3; a *= .5; } return s; }',
  'void over(inout vec4 c, vec3 col, float a){ a = clamp(a, 0., 1.); c = vec4(col * a + c.rgb * (1. - a), a + c.a * (1. - a)); }',
  'void main(){',
  '  float wet = texture2D(wm, vUv).r;',   /* the drawn map\u2019s own water: the site\u2019s mask is blocky round Palos Verdes */
  '  if (wet < .5){ gl_FragColor = vec4(0.); return; }',
  '  vec4 A = texture2D(t1, vUv), B = texture2D(t2, vUv), C = texture2D(t3, vUv), E = texture2D(t4, vUv);',
  '  float wl = (A.r * 65280. + A.g * 255.) / 65535. * 384., uu = (B.r * 65280. + B.g * 255.) / 65535. * 2464., wl2 = (E.r * 65280. + E.g * 255.) / 65535. * 384.;',
  /* exposure was solved on an 8-px grid: blur it here, or its cells show as squares in the shade */
  '  vec2 e8 = 5. / uRes; float LIs = (A.b * 2. + texture2D(t1, vUv + vec2(e8.x, 0.)).b + texture2D(t1, vUv - vec2(e8.x, 0.)).b + texture2D(t1, vUv + vec2(0., e8.y)).b + texture2D(t1, vUv - vec2(0., e8.y)).b) / 6. * 2.;',
  '  float LI = LIs, AM = B.b * 2.5, BR = C.r, SP = C.g, SH = C.b * 1.5, A2 = E.b * 2.5;',
  '  vec2 px = vUv * uRes, m = px * uMpp;',                /* m: metres on the ground */
  '  float cyc = uT / uTV, wt = 6.2832 * cyc, gE = cyc * .5 * 16. / 6., gL = cyc * 16. / 1.6;',
  /* SETS AND SHORT CRESTS: the same noise as before, pushed to contrast -- a set, then a lull; crests in staggered pieces */
  '  float env = smoothstep(.2, .8, texture2D(nz, vec2(uu / 14. + 31., (wl - cyc * .5) / 7.) / 16.).r) * 1.45 + .15;',   /* sets: a few waves deep, many wide */
  /* LONG CRESTS: a groundswell's crest runs on for many wavelengths from above, fading in and out slowly -- the old
     fraction-of-a-wavelength pieces lined up into a checkerboard. One noise cell here is 12 wavelengths along a crest */
  '  float len = .35 + .65 * smoothstep(.25, .75, texture2D(nz, vec2(uu / 12. + 97., (wl - cyc) / 2.5) / 16.).r);',
  '  float hgt = clamp(AM, .3, 2.2), s = sin(6.2832 * wl - wt);',
  /* NO SECOND CREST TRAIN (user 2026-09-26: "rows perpendicular to the coast ... evenly spaced, checkerboarding"): two perfectly
     regular trains summed print an exact interference lattice -- worse here because the short swell is stretched to a drawable
     wavelength. The crossing swell lives on only as the gentle irregularity of the sets. */
  '  if (uW2 < 0.){ float q2 = .45 * uW2 * clamp(A2, .3, 2.2) / hgt; s = clamp((s + q2 * sin(6.2832 * wl2 - wt * uR2)) / (1. + .6 * q2), -1., 1.); }',
  /* EXPOSURE, stronger: the islands and Palos Verdes leave the water behind them visibly calmer */
  '  float ex = pow(clamp(LI / .9, 0., 2.), 1. + uEx);',
  '  float a = ex * env * len * uAmp * (.55 + .75 * hgt);',
  '  vec4 c = vec4(0.);',
  '  float dz = texture2D(dt, vUv).r * 60., calmIn = smoothstep(uZone * .6, uZone * 1.8, dz);',   /* inside the break the swell is foam, not crests */
  /* WIND: cat’s-paws and slicks. Gusts roughen patches a few hundred metres across that drift downwind; between them the
     water lies glassy and a shade brighter. None of it under ~2 m/s: a calm morning is glass. */
  '  float wk = smoothstep(1.5, 7., uWind);',
  '  vec2 wv = uWdir * uT * (6. + uWind * 2.);',
  '  float gust = fbm((m - wv) / 420.) * .7 + fbm((m - wv * 1.4) / 150. + 7.) * .3;',
  '  float paw = smoothstep(.42, .66, gust) * wk;',
  '  float slick = (1. - smoothstep(.30, .46, gust)) * (1. - wk * .5);',
  '  float rip = vn((m - wv * 1.2) / max(9., uMpp * 2.6) * vec2(1., 2.2)) - .5;',                     /* fine chop inside the paws */
  '  over(c, vec3(.01, .05, .15), paw * (.16 + .22 * max(0., -rip * 2.)) * uTx);',
  '  over(c, vec3(.50, .70, .90), paw * max(0., rip) * .30 * uTx);',
  '  over(c, vec3(.42, .64, .88), slick * .10 * uTx);',
  /* the swell: trough shade and crest tone, as before */
  '  if (s < 0.) over(c, vec3(.01, .05, .13), (-s) * .30 * a * (1. - .5 * SP) * uTr * calmIn);',
  '  if (s > 0.){ float s2 = s * s, lit = s2 * (1. - SP + SP * s2 * s2) * (.36 + .10 * SP) * a * (hgt > 1. ? 1. + (hgt - 1.) * .5 : 1.);',
  '    over(c, mix(vec3(.50, .72, .92), vec3(.91, .96, 1.), uCw), lit * 1.25 * uCr * (1. - paw * .35) * calmIn); }',
  /* THE BREAK (user 2026-09-26: "improve the crashing of the waves"). Each crest reaching the break line turns into a white
     lip, rolls in toward the sand as a bore of whitewater, and leaves a lace of foam that thins and breaks up until the next
     crest arrives. The break line sits where the waves are big enough to break (bigger sets break further out); sandbars
     break it into patches, and the rips between them stay dark. Distance to the sand is measured, in px (dz). */
  '  float bd = min(min(px.x, uRes.x - px.x), min(px.y, uRes.y - px.y)), frame = smoothstep(10., 28., bd);',
  /* THE BREAK ON THE REAL SEAFLOOR (NOAA CUDEM, ~3 m, sampled per pixel): a wave breaks where the water is shallower than
     its breaker height / 0.78. The breaker grows with the swell reaching this stretch and with the set, so big sets break on
     the outer bar or reef while the small ones reach the shore; points and reefs break wherever their shelf is shallow
     enough, far from the sand if need be; a deep rip channel stays dark by itself. */
  '  vec4 Pd = texture2D(dp, vUv); float dep = (Pd.r * 65280. + Pd.g * 255.) / 65535.; dep = dep * dep * 60.;',
  '  float fw = 0.;',
  '  vec2 ex1 = 1. / uRes; vec2 gr = vec2(texture2D(dt, vUv + vec2(ex1.x * 7., 0.)).r - texture2D(dt, vUv - vec2(ex1.x * 7., 0.)).r, texture2D(dt, vUv + vec2(0., ex1.y * 7.)).r - texture2D(dt, vUv - vec2(0., ex1.y * 7.)).r);',   /* a wide gradient: the offshore direction must not jitter pixel to pixel */
  '  vec2 nrm0 = length(gr) > 1e-5 ? normalize(gr) : vec2(0.), off = vUv + nrm0 * 35. * ex1;',
  /* exposure averaged over a 25 px patch offshore: the exposure was solved on an 8 px grid and, read at one point, its blocks
     came through as sawtooth triangles in the break (Palos Verdes) */
  '  float LIo = 0., nW = 0.; for (int i = -3; i <= 3; i++) for (int j = -3; j <= 3; j++){ vec2 q = off + nrm0 * 12. * ex1 + vec2(float(i), float(j)) * 11. * ex1; float w = texture2D(wm, q).r; LIo += texture2D(t1, q).b * w; nW += w; }',
  '  LIo = LIo / max(nW, 1.) * 2.;',   /* 7x7 over ~70 px offshore, water only: the light was built on the 250 m grid and comes in blocks at the shore */
  '  float expo = clamp(LIo * 1.2, 0., 1.);',
  '  float Hb = uHb0 * pow(max(expo, .02), .8) * (.7 + .45 * env);',                  /* the breaker here, this set */
  '  float hb = Hb / .78 * uWd;',                                                       /* the depth it breaks in (widened for the view) */
  '  if (dep < hb * 1.3 && Hb > .12){',
  '    float inz = 1. - smoothstep(hb * .85, hb * 1.1, dep);',
  '    float en = clamp(.45 + .55 * expo, 0., 1.) * clamp(Hb / .9, .25, 1.2) * frame * smoothstep(.06, .3, LIs);',   /* the swell that reaches THIS spot: harbour basins behind their breakwaters stay still */
  '    float wlc = dot(px, uDir) / uLpx * .4 - dz / uLpx;',                             /* each breaker sweeps along the beach and rolls in */
  '    float age = fract(cyc - wlc + .25);',
  '    float lip = (1. - smoothstep(0., .13, age)) * (1. - smoothstep(0., hb * .35, abs(dep - hb * .95))) * (.7 + .3 * len);',
  '    float lace = smoothstep(.2 + age * .35, .62 + age * .35, fbm(px / 5. + vec2(uT * .05, -uT * .08) * 6.));',
  '    float bore = exp(-age * 2.2) * inz;',
  '    fw = (lip * 1.1 + bore * (.62 + .38 * lace) * .95) * en;',
  '    fw += (1. - smoothstep(.6, 3., dz)) * (.35 + .65 * exp(-age * 2.4)) * en * .8 * inz;',   /* the swash up the sand */
  '    fw *= uBrk;',
  '  }',
  '  over(c, vec3(.93, .97, 1.), fw * uFo);',
  /* AFTER RAIN: brown runoff fanning out of the river mouths, torn at its edge, drifting downcoast */
  '  if (uPl > .01){',
  '    float pl = 0.;',
  '    for (int k = 0; k < 4; k++){ if (float(k) >= uMn) break;',
  '      vec2 dc = uDc[k];',
  '      vec2 d = (px - uM[k]) * uMpp - dc * 1100. * uPl;',
  /* hugging the shore: stretched along the coast, narrow across it (runoff is lighter than seawater and the current turns it) */
  '      vec2 q = vec2(dot(d, dc) / 2.4, dot(d, vec2(-dc.y, dc.x)));',
  '      float r = length(q) / (1500. * uPl + 300.);',
  '      pl = max(pl, (1. - smoothstep(.25, 1., r + (fbm(m / 380. + float(k) * 9.) - .5) * .7)));',
  '    }',
  '    over(c, mix(vec3(.50, .44, .30), vec3(.66, .52, .31), smoothstep(.3, .9, pl)), pl * (.45 + .4 * pl) * min(1., uPl * 1.6));',   /* tan-brown, darker and greener at the thin edge */
  '  }',
  '  if (uDbg > .5) c = vec4(clamp(dep / 6., 0., 1.), clamp(expo, 0., 1.), clamp(Hb / 2., 0., 1.), 1.);',
  '  gl_FragColor = c;',
  '}'].join('\n');;
  var MOUTHS = [[34.0320, -118.6810, 0.97, 0.24], [33.9625, -118.4590, 0.45, 0.89], [33.7610, -118.2045, 0.55, 0.83], [33.7430, -118.1150, 0.7, 0.7]];
  var TUNE = { uCr: 1.0, uCw: 0.25, uTr: 1.0, uTx: 1.0, uFo: 1.0, uSp: 1.0, uEx: 0.8, uBrk: 1.0, uRag: 1.0 };
  var ENV = window._bvSeaEnv = window._bvSeaEnv || { wind: 4, wdir: 250, rain72: 0, at: 0 };
  function envLoad(){
    if (Date.now() - ENV.at < 20 * 60000) return; ENV.at = Date.now();
    fetch('https://api.open-meteo.com/v1/forecast?latitude=33.9&longitude=-118.55&current=wind_speed_10m,wind_direction_10m&hourly=precipitation&past_days=3&forecast_days=1&wind_speed_unit=ms&precipitation_unit=inch&timezone=GMT')
      .then(function(r){ return r.json(); }).then(function(j){
        ENV.wind = +j.current.wind_speed_10m; ENV.wdir = +j.current.wind_direction_10m;
        var now = Date.now(), r = 0; j.hourly.time.forEach(function(t, i){ var ms = Date.parse(t + ':00Z'); if (ms <= now && ms > now - 72 * 3600000) r += +j.hourly.precipitation[i] || 0; });
        ENV.rain72 = r; }).catch(function(){ ENV.at = Date.now() - 15 * 60000; });
  }
  /* chamfer distance (3-4) to the nearest 0 cell, and optionally the value carried from that cell */
  function chamfer(RW, RH, isSeed, carry){
    var N = RW * RH, d = new Float32Array(N), v = carry ? new Float32Array(N) : null, BIG = 1e9, k, x, y;
    for (k = 0; k < N; k++){ d[k] = isSeed(k) ? 0 : BIG; if (v) v[k] = carry[k]; }
    var rel = function(k, j, c){ if (d[j] + c < d[k]){ d[k] = d[j] + c; if (v) v[k] = v[j]; } };
    for (y = 0; y < RH; y++) for (x = 0; x < RW; x++){ k = y * RW + x; if (!d[k]) continue;
      if (x > 0) rel(k, k - 1, 3); if (y > 0){ rel(k, k - RW, 3); if (x > 0) rel(k, k - RW - 1, 4); if (x < RW - 1) rel(k, k - RW + 1, 4); } }
    for (y = RH - 1; y >= 0; y--) for (x = RW - 1; x >= 0; x--){ k = y * RW + x; if (!d[k]) continue;
      if (x < RW - 1) rel(k, k + 1, 3); if (y < RH - 1){ rel(k, k + RW, 3); if (x < RW - 1) rel(k, k + RW + 1, 4); if (x > 0) rel(k, k + RW - 1, 4); } }
    for (k = 0; k < N; k++) d[k] /= 3;
    return { d: d, v: v };
  }
  /* separable box blur, three passes ~ gaussian of radius r */
  function blur(a, RW, RH, r){
    var t = new Float32Array(a.length), o = new Float32Array(a), x, y;
    for (var p = 0; p < 3; p++){
      for (y = 0; y < RH; y++){ var s = 0, row = y * RW; for (x = -r; x <= r; x++) s += o[row + Math.min(RW - 1, Math.max(0, x))];
        for (x = 0; x < RW; x++){ t[row + x] = s / (2 * r + 1); s += o[row + Math.min(RW - 1, x + r + 1)] - o[row + Math.max(0, x - r)]; } }
      for (x = 0; x < RW; x++){ var s2 = 0; for (y = -r; y <= r; y++) s2 += t[Math.min(RH - 1, Math.max(0, y)) * RW + x];
        for (y = 0; y < RH; y++){ o[y * RW + x] = s2 / (2 * r + 1); s2 += t[Math.min(RH - 1, y + r + 1) * RW + x] - t[Math.max(0, y - r) * RW + x]; } }
    }
    return o;
  }
  /* connected components of a boolean grid (4-way); returns labels */
  function label(m, RW, RH){
    var L = new Int32Array(m.length), n = 0, st = [];
    for (var k0 = 0; k0 < m.length; k0++){ if (!m[k0] || L[k0]) continue; n++; L[k0] = n; st.push(k0);
      while (st.length){ var k = st.pop(), x = k % RW;
        if (x > 0 && m[k - 1] && !L[k - 1]){ L[k - 1] = n; st.push(k - 1); } if (x < RW - 1 && m[k + 1] && !L[k + 1]){ L[k + 1] = n; st.push(k + 1); }
        if (k >= RW && m[k - RW] && !L[k - RW]){ L[k - RW] = n; st.push(k - RW); } if (k < m.length - RW && m[k + RW] && !L[k + RW]){ L[k + RW] = n; st.push(k + RW); } } }
    return L;
  }
  function tex(gl, unit, w, h, data, linear, repeat){
    var t = gl.createTexture(); gl.activeTexture(gl.TEXTURE0 + unit); gl.bindTexture(gl.TEXTURE_2D, t);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, linear ? gl.LINEAR : gl.NEAREST); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, linear ? gl.LINEAR : gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, repeat ? gl.REPEAT : gl.CLAMP_TO_EDGE); gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, repeat ? gl.REPEAT : gl.CLAMP_TO_EDGE);
    gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1); gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, data); return t;
  }
  var ctxCache = null;
  /* o: { cv (the webgl canvas), RW, RH, N, IDX, PH, UU, LI, AM, BR, SP, SH, PH2, A2, NZ, water (canvas), map (canvas, may be tainted),
          consts {amp, w2, r2, TV, lead, mpp (ground m per px), geo {w,e,n,s}}, stale() } */
  window.bvSeaGL = function(o){
    var cv = o.cv, gl = cv._gl || cv.getContext('webgl', { premultipliedAlpha: true, alpha: true, antialias: false });
    if (!gl) return false;
    if (!cv._gl){
      var sh = function(t, src){ var s = gl.createShader(t); gl.shaderSource(s, src); gl.compileShader(s); if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)){ window._bvSeaErr = gl.getShaderInfoLog(s); return null; } return s; };
      var vs = sh(gl.VERTEX_SHADER, VS), fs = sh(gl.FRAGMENT_SHADER, FS); if (!vs || !fs) return false;
      var pr = gl.createProgram(); gl.attachShader(pr, vs); gl.attachShader(pr, fs); gl.linkProgram(pr); if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) return false;
      gl.useProgram(pr);
      var b = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, b); gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
      var l = gl.getAttribLocation(pr, 'p'); gl.enableVertexAttribArray(l); gl.vertexAttribPointer(l, 2, gl.FLOAT, false, 0, 0);
      var U = {}; ['uRes', 'uT', 'uTV', 'uAmp', 'uW2', 'uR2', 'uCr', 'uCw', 'uTr', 'uTx', 'uFo', 'uDrift', 'uDir', 'uMpp', 'uWind', 'uWdir', 'uEx', 'uBrk', 'uRag', 'uPl', 'uM', 'uMn', 'uDc', 'uZone', 'uDbg', 'uLpx', 'uHb0', 'uWd'].forEach(function(k){ U[k] = gl.getUniformLocation(pr, k); });
      ['t1', 't2', 't3', 't4', 't5', 'nz', 'dt', 'dp', 'wm'].forEach(function(k, i){ gl.uniform1i(gl.getUniformLocation(pr, k), i); });
      cv._gl = gl; cv._pr = pr; cv._U = U;
      cv.addEventListener('webglcontextlost', function(e){ e.preventDefault(); cv._gl = null; });
    }
    gl = cv._gl; var U = cv._U; gl.useProgram(cv._pr);
    envLoad();
    var RW = o.RW, RH = o.RH, N = RW * RH, C = o.consts, k, i;
    /* the swell field, packed as the lab's bake packs it */
    var q16 = function(v, per){ var f = ((v % per) + per) % per / per; return Math.min(65535, Math.round(f * 65535)); };
    var b8 = function(v, sc){ return Math.max(0, Math.min(255, Math.round(v / sc * 255))); };
    var T1 = new Uint8Array(N * 4), T2 = new Uint8Array(N * 4), T3 = new Uint8Array(N * 4), T4 = new Uint8Array(N * 4), T5 = new Uint8Array(N * 4);
    for (k = 0; k < o.N; k++){ var p = o.IDX[k], q = p * 4, w = q16(o.PH[k] / (2 * Math.PI), 384), u = q16(o.UU[k], 2464), w2 = q16(o.PH2[k] / (2 * Math.PI), 384);
      T1[q] = w >> 8; T1[q + 1] = w & 255; T1[q + 2] = b8(o.LI[k], 2);
      T2[q] = u >> 8; T2[q + 1] = u & 255; T2[q + 2] = b8(o.AM[k], 2.5);
      T3[q] = b8(o.BR[k], 1); T3[q + 1] = b8(o.SP[k], 1); T3[q + 2] = b8(o.SH[k], 1.5);
      T4[q] = w2 >> 8; T4[q + 1] = w2 & 255; T4[q + 2] = b8(o.A2[k], 2.5); T5[q] = 255; }
    for (k = 3; k < N * 4; k += 4){ T1[k] = T2[k] = T3[k] = T4[k] = T5[k] = 255; }
    var NZb = new Uint8Array(65536 * 4); for (k = 0; k < 65536; k++){ var nv = Math.round(o.NZ[k] * 255); NZb[k * 4] = NZb[k * 4 + 1] = NZb[k * 4 + 2] = nv; NZb[k * 4 + 3] = 255; }
    tex(gl, 0, RW, RH, T1); tex(gl, 1, RW, RH, T2); tex(gl, 2, RW, RH, T3); tex(gl, 3, RW, RH, T4); tex(gl, 4, RW, RH, T5); tex(gl, 5, 256, 256, NZb, true, true);
    /* THE WATER MASK, cleaned against the drawn map: the site's mask minus clearly drawn land that is joined to the site's
       own land (labels and buoy icons floating on the sea are not coast); falls back to the site's mask if the map is tainted */
    var sea = new Uint8Array(N), wmData = null;
    for (k = 0; k < o.N; k++) sea[o.IDX[k]] = 1;
    try {
      var mc = document.createElement('canvas'); mc.width = RW; mc.height = RH; var mg = mc.getContext('2d', { willReadFrequently: true }); mg.drawImage(o.map, 0, 0, RW, RH);
      var px = mg.getImageData(0, 0, RW, RH).data, land = new Uint8Array(N), bgw = new Uint8Array(N);
      for (k = 0; k < N; k++){ var r = px[k * 4], g = px[k * 4 + 1], bl = px[k * 4 + 2];
        land[k] = (r > bl + 15) || ((g > bl + 10) && (g > r)) || (r > 150 && g > 150 && bl > 150) ? 1 : 0;
        bgw[k] = (bl > r + 35 && bl > g + 10 && bl > 60) ? 1 : 0; }
      var lj = new Uint8Array(N); for (k = 0; k < N; k++) lj[k] = land[k] || !sea[k] ? 1 : 0;
      var LL = label(lj, RW, RH), keepL = {}; for (k = 0; k < N; k++) if (!sea[k]) keepL[LL[k]] = 1;
      var w0 = new Uint8Array(N); for (k = 0; k < N; k++) w0[k] = (sea[k] || bgw[k]) && !(land[k] && keepL[LL[k]]) ? 1 : 0;
      var LW = label(w0, RW, RH), keepW = {}; for (k = 0; k < N; k++) if (w0[k] && sea[k]) keepW[LW[k]] = 1;
      for (k = 0; k < N; k++) w0[k] = w0[k] && keepW[LW[k]] ? 1 : 0;
      wmData = w0;
    } catch (e){ wmData = sea; }
    var WM = new Uint8Array(N * 4); for (k = 0; k < N; k++){ WM[k * 4] = wmData[k] * 255; WM[k * 4 + 3] = 255; }
    tex(gl, 8, RW, RH, WM);
    /* distance to the sand */
    var DZ = chamfer(RW, RH, function(k){ return !wmData[k]; }).d;
    var DT = new Uint8Array(N * 4); for (k = 0; k < N; k++){ DT[k * 4] = Math.min(255, Math.round(DZ[k] / 60 * 255)); DT[k * 4 + 3] = 255; }
    tex(gl, 6, RW, RH, DT, true);
    /* THE SEAFLOOR: a provisional slope until NOAA answers, then CUDEM, prepared as the lab prepares it */
    var mppPx = C.mpp;
    var depTex = function(dep){ var D = new Uint8Array(N * 4); for (var k = 0; k < N; k++){ var d = Math.max(0, Math.min(60, dep[k])), qq = Math.round(Math.sqrt(d / 60) * 65535); D[k * 4] = qq >> 8; D[k * 4 + 1] = qq & 255; D[k * 4 + 3] = 255; } tex(gl, 7, RW, RH, D); };
    var prov = new Float32Array(N); for (k = 0; k < N; k++) prov[k] = wmData[k] ? DZ[k] * mppPx / 44 : 0; depTex(prov);   /* a 1:44 beach until the survey lands */
    var G = C.geo, R = 6378137, X = function(lon){ return lon * Math.PI / 180 * R; }, Y = function(lat){ return R * Math.log(Math.tan(Math.PI / 4 + lat * Math.PI / 360)); };
    var ckey = [G.w, G.e, G.n, G.s, RW, RH].map(function(v){ return (+v).toFixed(5); }).join(',');
    var useDepth = function(a){
      if (o.stale()) return;
      var seaC = new Uint8Array(N); for (k = 0; k < N; k++) seaC[k] = a[k] < -0.35 ? 1 : 0;
      var dzC = chamfer(RW, RH, function(k){ return !(seaC[k] || a[k] < 0); }).d;
      var num = new Float32Array(N), den = new Float32Array(N);
      for (k = 0; k < N; k++) if (seaC[k] && dzC[k] > 3 && dzC[k] < 25){ num[k] = -a[k]; den[k] = dzC[k]; }
      num = blur(num, RW, RH, 12); den = blur(den, RW, RH, 12);
      var sl = [], slope = new Float32Array(N);
      for (k = 0; k < N; k++){ slope[k] = den[k] > 1e-3 ? num[k] / den[k] : NaN; if (wmData[k] && isFinite(slope[k]) && DZ[k] < 20) sl.push(slope[k]); }
      sl.sort(function(p, q){ return p - q; }); var med = sl.length ? sl[sl.length >> 1] : mppPx / 44;
      var near = chamfer(RW, RH, function(k){ return !!seaC[k]; }, (function(){ var c = new Float32Array(N); for (var j = 0; j < N; j++) c[j] = -a[j]; return c; })()).v;
      var dep = new Float32Array(N);
      for (k = 0; k < N; k++){ if (!wmData[k]) continue; var s = isFinite(slope[k]) ? slope[k] : med, wt = Math.max(0, Math.min(1, (DZ[k] - 25) / 20));
        dep[k] = (1 - wt) * s * DZ[k] + wt * Math.max(0, near[k]); }
      depTex(dep);
    };
    ctxCache = ctxCache || {};
    if (ctxCache[ckey]) useDepth(ctxCache[ckey]);
    else fetch('https://gis.ngdc.noaa.gov/arcgis/rest/services/DEM_mosaics/DEM_all/ImageServer/exportImage?bbox=' + [X(G.w), Y(G.s), X(G.e), Y(G.n)].join(',')
        + '&bboxSR=3857&imageSR=3857&size=' + RW + ',' + RH + '&format=bip&pixelType=F32&interpolation=RSP_BilinearInterpolation&f=image')
      .then(function(r){ return r.arrayBuffer(); }).then(function(ab){ if (ab.byteLength < N * 4) return; var a = new Float32Array(ab.slice(0, N * 4)); ctxCache[ckey] = a; useDepth(a); })
      .catch(function(){ window._bvSeaDepthErr = Date.now(); });
    /* the constants */
    var th = (C.lead.dir + 180) * Math.PI / 180, Tsw = Math.max(5, Math.min(22, C.lead.tp || 10)), Hs0 = C.lead.hs || 0.8;
    var Hb0 = 0.39 * Math.pow(9.81, 0.2) * Math.pow(Tsw * Hs0 * Hs0, 0.4);
    gl.uniform2f(U.uRes, RW, RH); gl.uniform1f(U.uAmp, C.amp); gl.uniform1f(U.uW2, C.w2); gl.uniform1f(U.uR2, C.r2);
    gl.uniform2f(U.uDir, Math.sin(th), -Math.cos(th)); gl.uniform1f(U.uMpp, mppPx);
    gl.uniform1f(U.uLpx, Math.max(9.81 * Tsw * Tsw / (2 * Math.PI), 7 * mppPx) / mppPx);
    gl.uniform1f(U.uHb0, Hb0); gl.uniform1f(U.uWd, Math.max(1, (mppPx > 45 ? 4.5 : 11) / (Hb0 / 0.78 * 44 / mppPx)));
    gl.uniform1f(U.uZone, Math.max(9, (45 + 75 * Hs0) / mppPx));
    var DC = [], M = [], my = function(la){ return Math.log(Math.tan(Math.PI / 4 + la * Math.PI / 360)); };
    MOUTHS.forEach(function(q){ var x = (q[1] - G.w) / (G.e - G.w) * RW, y = (my(G.n) - my(q[0])) / (my(G.n) - my(G.s)) * RH;
      if (x > -200 && y > -200 && x < RW + 200 && y < RH + 200 && M.length < 8){ M.push(x, y); DC.push(q[2], q[3]); } });
    var mf = new Float32Array(8); mf.set(M); gl.uniform2fv(U.uM, mf); gl.uniform1f(U.uMn, M.length / 2); var df = new Float32Array(8); df.set(DC); gl.uniform2fv(U.uDc, df);
    ['uCr', 'uCw', 'uTr', 'uTx', 'uFo', 'uEx', 'uBrk', 'uRag'].forEach(function(k){ gl.uniform1f(U[k], TUNE[k]); });
    gl.uniform1f(U.uDbg, 0);
    var t0 = performance.now();
    return function draw(now){
      if (!cv._gl) return false;
      gl.useProgram(cv._pr);
      gl.viewport(0, 0, cv.width, cv.height);
      gl.uniform1f(U.uT, (now - t0) / 1000); gl.uniform1f(U.uTV, C.TV); gl.uniform1f(U.uDrift, 0.6);
      var wd = (ENV.wdir + 180) * Math.PI / 180; gl.uniform1f(U.uWind, ENV.wind); gl.uniform2f(U.uWdir, Math.sin(wd), -Math.cos(wd));
      gl.uniform1f(U.uPl, Math.min(1, ENV.rain72 / 0.5));
      gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT); gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
      return true;
    };
  };
})();

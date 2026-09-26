/* bvCloudGL -- a volumetric-looking cumulus for the front scenes, drawn on the GPU (2026-09-25, prototype).
   User: "can you watch this [NCAR's CM1 cumulus congestus, rendered in Blender] and consider how our clouds can look more
   realistic like this?" ... "does it need to be 3D?" -- No. The view is a fixed side cut, so a 2D DENSITY field is enough;
   what made the NCAR render real is LIGHT THROUGH the density, and that can be marched across a plane too:
     - density: the tower's shape (flat base, leaning column, round top, anvil) eroded by domain-warped fbm at five
       scales -- lobes made of lobes, the cauliflower -- whose pattern rises with time (the boil)
     - light: marched toward the sun (self-shadow: thick cores and the underside go dark) and upward (sky light), warm
       sun on the tops, cool violet-grey in the shade, thin edges lit through (they glow instead of going grey)
     - rain: a streaky veil from the base, slanting, fading toward the ground
   One shared WebGL canvas renders every cloud and is copied into the caller's 2D canvas (browsers cap GL contexts).
   Units are the scene's own: x 0..224, y measured UP from the bottom of the 104-unit scene. */
(function(){
  var VS = 'attribute vec2 a; varying vec2 v; void main(){ v = a * 0.5 + 0.5; gl_Position = vec4(a, 0., 1.); }';
  /* ONLY THE CLOUD'S OWN BOX is shaded (2026-09-26: ten scenes at once ran 10 fps, GPU-bound -- most of every pass was sky):
     the quad covers the box, and only that rectangle is copied back */
  var FS = [
    'precision highp float;',
    'varying vec2 v;',
    'uniform vec2 uWH; uniform float uT, uCx, uBase, uH, uHW, uLean, uAnv, uAnvR, uAnvL, uRain, uNight, uFlash, uGround, uDens, uMode, uN;',
    'uniform vec4 uP[48];',
    'uniform vec2 uSunDir; uniform vec3 uSunCol;',
    'float h1(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }',
    'vec2 h2(vec2 p){ return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)))) * 43758.5453); }',
    'float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);',
    '  return mix(mix(h1(i), h1(i + vec2(1., 0.)), f.x), mix(h1(i + vec2(0., 1.)), h1(i + vec2(1., 1.)), f.x), f.y); }',
    /* STREAKS WITHOUT BLINDS: value noise stretched hard along its own grid lines each stretched cell up into a row -- the
       high decks and the anvil came out striped like venetian blinds. Rotated a few degrees and warped first, streaks wander. */
    'vec2 rot(vec2 p){ return vec2(p.x * .985 + p.y * .174, -p.x * .174 + p.y * .985); }',
    'float fbm(vec2 p){ float s = 0., a = .5; for (int i = 0; i < 4; i++){ s += a * vn(p); p = p * 2.03 + vec2(1.7, 9.2); a *= .5; } return s; }',
    /* CAULIFLOWER = DOMES (2026-09-25, from NCAR's frames): cellular noise where every cell is a rounded dome; the light then
       finds each one -- lit crown, soft shade under -- which smooth noise (fog-like blobs) never gives. Cells drift, so it boils */
    'float dome(vec2 p){ vec2 i = floor(p), f = fract(p); float md = 9.;',
    '  for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++){ vec2 g = vec2(float(x), float(y)); vec2 o = h2(i + g);',
    '    o = .5 + .38 * sin(uT * .25 + 6.2831 * o); vec2 r = g + o - f; md = min(md, dot(r, r)); }',
    '  return max(0., 1. - md * 1.45); }',
    'float tower(vec2 p){',
    '  float best = -1.;',
    '  for (int i = 0; i < 9; i++){ float fi = float(i);',
    '    float k = fract((fi + .5) / 9. + uT * .012);',
    '    float r = uHW * (.52 + .30 * h1(vec2(fi, 3.)) + .18 * sin(k * 3.14));',
    '    float cy = uBase + r * .55 + k * max(uH - r * 1.1, 0.);',
    '    float ax = uCx - uLean * k * uH * .28 + uHW * .42 * (h1(vec2(fi, 7.)) - .5) * 2.;',
    '    vec2 d = (p - vec2(ax, cy)) / vec2(r * 1.05, r); best = max(best, 1. - dot(d, d)); }',
    '  vec2 cc = (p - vec2(uCx - uLean * uH * .28, uBase + uH - uHW * .55)) / vec2(uHW * .95, uHW * .75);',
    '  best = max(best, 1. - dot(cc, cc));',
    '  return best; }',
    /* LAYER MODE (uMode 1): the cloud the lifted warm air makes ahead of a warm front, along a stalled or occluded one -- its
       shape is the scene's own puffs (x, y up, r, weight), so the physics that placed them still decides where it is */
    /* a SMOOTH union: max() left a crease between every pair of neighbours -- the shelf read as a twisted rope */
    'float puffs(vec2 p){ float K = uLean > 5. ? 1.4 : 6.; float acc = 0.; for (int i = 0; i < 48; i++){ if (float(i) >= uN) break; vec4 q = uP[i];',
    /* NO PANCAKES (user 2026-09-26: "do the deck puffs"): a lone small anchor drawn 2.7x wider than tall was a flat disc.
       Small anchors are ROUND puffs (1.15 x .95) -- an upward bulge made lollipops on stalks --; only the big ones stretch wide to merge into a deck */
    '  float big = smoothstep(4.5, 9., q.z);',
    '  vec2 dd = p - q.xy;',
    '  vec2 d = dd / (uLean > 5. ? vec2(q.z * 2.3, q.z * .55) : vec2(q.z * mix(1.15, 1.95, big), q.z * mix(.95, .72, big))); acc += exp(K * ((1. - dot(d, d)) * q.w - 1.)); }',
    '  return acc > 0. ? 1. + log(acc) / K : -1.; }',   /* wide, flat: they merge into a deck */
    'float anvil(vec2 p){ if (uAnv < .01) return -1.; float ax2 = uCx - uLean * uH * .28; float ux = p.x - ax2; float R = ux > 0. ? uAnvR : uAnvL; float r2 = abs(ux) / max(R, 1.);',
    '  float th = (2.5 + 5.5 * (1. - r2)) * uAnv; float cy2 = uBase + uH - 1.5; float dy = (p.y - cy2) / max(th, .6); return (1. - r2 * r2) - dy * dy; }',
    /* the height of the surface: the lobes' shape, then domes at two sizes rising through it; the anvil is ice -- smooth and
       fibrous, stretched along the wind, no domes */
    'float hgt(vec2 p){',
    '  if (uMode > .5){ vec2 q1 = p + vec2(-uT * .35, 0.); float s1 = puffs(p);',
    '    if (s1 < -1.) return -1.;',
    '    float hi = smoothstep(58., 82., p.y), lo = 1. - smoothstep(30., 46., p.y);',
    '    if (uLean > 5.){ float ctr = 0.; for (int i = 0; i < 48; i++){ if (float(i) >= uN) break; ctr += uP[i].y; } ctr /= max(uN, 1.);',
    '      float under = 1. - smoothstep(ctr - 2., ctr + 1., p.y);',                          /* the underside is ragged scud */
    '      return s1 * .95 - .05 + under * (fbm(vec2(p.x * .5 - uT * .3, p.y * .9)) - .55) * .55; }',   /* the top stays laminar */   /* the SHELF: one laminar wedge -- no domes, no fibres, no noise (it roped) */   /* the SHELF (flagged lean 9): laminar and smooth -- no domes, no fibres */   /* high: thin ice, fibrous; low: rain cloud, smooth */
    '    float lumps = (.17 * dome(q1 * .12) + .08 * dome(q1 * .31 + 3.7)) * (1. - hi) * (1. - .6 * lo);',
    '    vec2 pq = rot(p) + 3. * vec2(vn(p * .07), vn(p * .07 + 9.));',
    '    float fibr = (fbm(pq * vec2(.04, .28) + vec2(-uT * .04, 0.)) - .5) * .5 * hi;',
    '    return s1 * .9 * (1. - .35 * hi) + lumps + fibr + (fbm(q1 * .08) - .5) * .12 * lo - .12; }',   /* flatter lumps: a deck, not towers */
    '  float s = tower(p), a = anvil(p);',
    '  vec2 q = p + vec2(0., -uT * .7);',
    '  float d1 = dome(q * .105), d2 = dome(q * .26 + 3.7), d3 = dome(q * .62 + 9.1);',   /* lobes a quarter to a third of the tower, smaller ones on them */
    '  float tw = s * .9 + .42 * d1 + .16 * d2 + .06 * d3 - .27;',
    /* THE ANVIL IS ICE (2026-09-26): fibrous and streaky along the wind, fraying toward its downwind tip, and pouched underneath
       -- mammatus -- where the sinking ice air hangs in lobes. No cauliflower up here. */
    '  float an = -1.;',
    '  if (a > -1.){ float ax2 = uCx - uLean * uH * .28, ux = p.x - ax2, R = ux > 0. ? uAnvR : uAnvL, rr = abs(ux) / max(R, 1.), cy2 = uBase + uH - 1.5;',
    '    vec2 pr = rot(p) + 2.5 * vec2(vn(p * .08), vn(p * .08 + 5.));',
    '    float fib = fbm(pr * vec2(.045, .30) + vec2(-uT * .05, 0.)) - .5, str = vn(vec2(pr.x * .06 - uT * .04, pr.y * .45)) - .5;',
    '    an = a * .9 + fib * .45 + str * .14 - smoothstep(.55, 1., rr) * (.25 + .5 * fbm(p * .2 + 7.));',
    '    if (ux > 0. && rr > .12 && rr < .8 && p.y < cy2){ float mm = pow(max(0., sin(p.x * .55 - uT * .15 + 2. * vn(p * .1))), 3.); an += mm * .22 * smoothstep(0., .2, uAnv) * (1. - smoothstep(.55, .8, rr)) * smoothstep(cy2 - 8., cy2 - 3., p.y); } }',   /* a soft edge, not a cut: the cut drew a ladder under the anvil */
    '  return mix(-1., max(tw, an), smoothstep(uBase - .4, uBase + .9, p.y)); }',   /* below the base: OUTSIDE (-1), not 0 -- 0 passed the threshold and veiled the whole band under it */
    'void main(){',
    '  vec2 p = v * uWH;',
    '  float H0 = hgt(p);',
    '  vec4 col = vec4(0.);',
    '  if (H0 > -.02){',
    '    float e = .35;',
    '    float gx = hgt(p + vec2(e, 0.)) - hgt(p - vec2(e, 0.)), gy = hgt(p + vec2(0., e)) - hgt(p - vec2(0., e));',
    '    vec3 N = normalize(vec3(-gx * (uLean > 5. ? 1.2 : 6.5), -gy * (uLean > 5. ? 1.2 : 6.5), 1.));',   /* the domes are gentle slopes: a larger normal scale so each one catches the light */
    '    vec3 L3 = normalize(vec3(uSunDir, .45));',
    '    float dif = pow(dot(N, L3) * .5 + .5, 1.6);',                             /* half-Lambert: mostly lit, soft falloff */
    '    float crev = smoothstep(-.05, .35, H0);',
    /* THE FORM, lit as one mass: the tower's own shape (no domes), a wide step -- sun side cream-white, far side and
       underside grey, the way the whole NCAR cloud shades before its lobes do */
    '    float E = 2.4; float bx, by;',
    '    if (uMode > .5){ bx = puffs(p + vec2(E, 0.)) - puffs(p - vec2(E, 0.)); by = puffs(p + vec2(0., E)) - puffs(p - vec2(0., E)); }',
    '    else { bx = tower(p + vec2(E, 0.)) - tower(p - vec2(E, 0.)); by = tower(p + vec2(0., E)) - tower(p - vec2(0., E)); }',
    '    vec3 NB = normalize(vec3(-bx * 1.3, -by * 1.3, 1.));',
    '    float form = dot(NB, L3) * .5 + .5;',                        /* shallow = between lobes: the creases */
    '    float jit = h1(p * 37.1); float acc = 0.; vec2 L = normalize(vec2(-.5, .86));',
    '    L = normalize(uSunDir);',
    '    for (int i = 0; i < 6; i++){ float hh = hgt(p + L * (2. + (float(i) + jit) * 3.)); acc += clamp(hh * 3., 0., 1.); }',
    '    float Ts = exp(-acc * .26);',                                    /* the mass shades itself, gently */
    '    float hb = clamp((p.y - uBase) / max(uH, 1.), 0., 1.);',
    '    vec3 sunC = uSunCol;',   /* cream in the sun */
    '    vec3 shdC = mix(vec3(.50, .52, .60), vec3(.08, .10, .16), uNight);',
    '    vec3 c = mix(shdC, sunC, clamp(dif * (.45 + .55 * Ts) * (.62 + .38 * crev) * (.55 + .75 * form), 0., 1.));',
    '    if (uMode < .5) c *= mix(.66, 1., smoothstep(0., .22, hb));',                    /* the base: darker, flat */
    '    if (uFlash > 0.){ float fl = exp(-length((p - vec2(uCx - 4., uBase + uH * .45)) / vec2(uHW * 1.3, uH * .6))); c += vec3(1., .98, .86) * fl * uFlash * 1.2; }',
    '    float a = smoothstep(-.02, .09, H0) * uDens;',
    '    if (uMode > .5){ float hi2 = smoothstep(58., 82., p.y), lo2 = 1. - smoothstep(30., 46., p.y); a *= 1. - .45 * hi2; c = mix(c, c * .78, lo2 * .6); c = mix(c, sunC, hi2 * .25); }',                   /* a crisp, rounded outline */
    '    col = vec4(c, a);',
    '  }',
    /* RAIN: a pale fibrous curtain hanging from INSIDE the cloud's lower part, thinning toward the ground */
    '  if (uRain > 0. && p.y > uGround && p.y < uBase + uH * .45){',
    '    float ax = uCx - uHW * .35 + (uBase - p.y) * .18;',
    '    float xw = 1. - smoothstep(uHW * .30, uHW * 1.0, abs(p.x - ax));   /* never smoothstep(hi, lo): undefined in GLSL -- it drew a veil across the whole width */',
    '    float st = vn(vec2(p.x * 1.6 + p.y * .12, p.y * .035 + uT * .9)) * .6 + vn(vec2(p.x * 4.1, p.y * .06 + uT * 1.6)) * .4;',
    '    float top = 1. - smoothstep(uBase + uH * .1, uBase + uH * .45, p.y), bot = .35 + .65 * smoothstep(uGround, uBase, p.y);',
    '    float ra = clamp(uRain * xw * top * bot * (.3 + .9 * st) * .75, 0., .88);',
    '    vec3 rc = mix(mix(vec3(.90, .89, .92), vec3(.56, .58, .64), smoothstep(.7, 1.1, uRain)), vec3(.40, .44, .55), uNight) * (.85 + .15 * st);',   /* pale; darker under a heavy storm */   /* pale, as NCAR draws it */
    '    col = vec4(mix(col.rgb, rc, ra * (p.y < uBase ? 1. : .55)), max(col.a, ra));',
    '  }',
    '  gl_FragColor = vec4(col.rgb * col.a, col.a);',
    '}'
  ].join('\n');
  var GL = null;
  function init(){
    if (GL) return GL.ok ? GL : null;
    GL = { ok: false };
    try {
      var c = document.createElement('canvas'), g = c.getContext('webgl', { premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: true });
      if (!g) return null;
      var sh = function(t, s){ var o = g.createShader(t); g.shaderSource(o, s); g.compileShader(o); if (!g.getShaderParameter(o, g.COMPILE_STATUS)) throw new Error(g.getShaderInfoLog(o)); return o; };
      var pr = g.createProgram(); g.attachShader(pr, sh(g.VERTEX_SHADER, VS)); g.attachShader(pr, sh(g.FRAGMENT_SHADER, FS)); g.linkProgram(pr);
      if (!g.getProgramParameter(pr, g.LINK_STATUS)) throw new Error(g.getProgramInfoLog(pr));
      g.useProgram(pr);
      var b = g.createBuffer(); g.bindBuffer(g.ARRAY_BUFFER, b); g.bufferData(g.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), g.STATIC_DRAW);
      var loc = g.getAttribLocation(pr, 'a'); g.enableVertexAttribArray(loc); g.vertexAttribPointer(loc, 2, g.FLOAT, false, 0, 0);
      var U = {}; ['uWH', 'uT', 'uCx', 'uBase', 'uH', 'uHW', 'uLean', 'uAnv', 'uAnvR', 'uAnvL', 'uRain', 'uNight', 'uFlash', 'uGround', 'uDens', 'uMode', 'uN', 'uP', 'uSunDir', 'uSunCol'].forEach(function(n){ U[n] = g.getUniformLocation(pr, n); });
      GL = { ok: true, c: c, g: g, U: U };
    } catch (e){ GL = { ok: false, err: String(e) }; if (window.console) console.warn('bvCloudGL off:', e); return null; }
    return GL;
  }
  /* draw one cloud into a 2D context. o: {W,H (scene units), ppu (GL pixels per unit), t, cx, base (up), h, hw, lean,
     anvil 0..1, anvR, anvL, rain 0..1, night 0..1, flash 0..1, ground (up), dens}. Returns false when WebGL is unavailable. */
  window.bvCloudGL = function(ctx, o){
    var G = init(); if (!G) return false;
    var ppu = Math.min(o.ppu || 3, window.innerWidth <= 480 ? 2 : 3);   /* phones: 2 GPU pixels a unit, the pictures are smaller there anyway */
    var W = o.W || 224, H = o.H || 104, pw = Math.round(W * ppu), ph = Math.round(H * ppu);
    if (G.c.width !== pw || G.c.height !== ph){ G.c.width = pw; G.c.height = ph; }
    var g = G.g, U = G.U;
    g.viewport(0, 0, pw, ph); g.clearColor(0, 0, 0, 0); g.clear(g.COLOR_BUFFER_BIT);
    g.uniform2f(U.uWH, W, H); g.uniform1f(U.uT, o.t || 0); g.uniform1f(U.uCx, o.cx); g.uniform1f(U.uBase, o.base); g.uniform1f(U.uH, o.h);
    g.uniform1f(U.uHW, o.hw); g.uniform1f(U.uLean, o.lean == null ? 1 : o.lean); g.uniform1f(U.uAnv, o.anvil || 0); g.uniform1f(U.uAnvR, o.anvR || 60); g.uniform1f(U.uAnvL, o.anvL || 25);
    g.uniform1f(U.uRain, o.rain || 0); g.uniform1f(U.uNight, o.night || 0); g.uniform1f(U.uFlash, o.flash || 0); g.uniform1f(U.uGround, o.ground == null ? 18 : o.ground); g.uniform1f(U.uDens, o.dens == null ? 1 : o.dens);
    /* layer mode: o.puffs = [[x, yUp, r, w], ...] up to 48 */
    var P = o.puffs || [], arr = new Float32Array(48 * 4);
    for (var i = 0; i < Math.min(48, P.length); i++){ arr[i * 4] = P[i][0]; arr[i * 4 + 1] = P[i][1]; arr[i * 4 + 2] = P[i][2]; arr[i * 4 + 3] = P[i][3]; }
    var sd = o.sunDir || [-0.5, 0.75], sc = o.sunCol || [1.04 - 0.52 * (o.night || 0), 0.98 - 0.42 * (o.night || 0), 0.90 - 0.22 * (o.night || 0)];
    g.uniform2f(U.uSunDir, sd[0], sd[1]); g.uniform3f(U.uSunCol, sc[0], sc[1], sc[2]);
    g.uniform1f(U.uMode, P.length ? 1 : 0); g.uniform1f(U.uN, Math.min(48, P.length)); g.uniform4fv(U.uP, arr);
    /* the box, in scene units: a tower from its base to above its anvil, or the puffs' extent, with room for the lobes */
    var bx0, bx1, by0, by1, pad = 6;
    if (P.length){ bx0 = 1e9; bx1 = -1e9; by0 = 1e9; by1 = -1e9; P.forEach(function(q){ var rr = q[2] * 2.2 + pad; bx0 = Math.min(bx0, q[0] - rr); bx1 = Math.max(bx1, q[0] + rr); by0 = Math.min(by0, q[1] - q[2] - pad); by1 = Math.max(by1, q[1] + q[2] + pad); }); }
    else { var sp = Math.max(o.hw * 1.6, o.anvil ? Math.max(o.anvR || 0, o.anvL || 0) : 0) + pad; bx0 = o.cx - sp - (o.lean || 0) * o.h * 0.3; bx1 = o.cx + sp;
      by0 = (o.rain ? (o.ground == null ? 18 : o.ground) : o.base - 3); by1 = o.base + o.h + (o.anvil ? 10 : 0) + o.hw * 0.8 + pad; }
    bx0 = Math.max(0, bx0); bx1 = Math.min(W, bx1); by0 = Math.max(0, by0); by1 = Math.min(H, by1);
    if (bx1 <= bx0 || by1 <= by0) return true;
    var nx0 = bx0 / W * 2 - 1, nx1 = bx1 / W * 2 - 1, ny0 = by0 / H * 2 - 1, ny1 = by1 / H * 2 - 1;
    g.bufferData(g.ARRAY_BUFFER, new Float32Array([nx0, ny0, nx1, ny0, nx0, ny1, nx1, ny1]), g.DYNAMIC_DRAW);
    g.drawArrays(g.TRIANGLE_STRIP, 0, 4);
    var sx = Math.floor(bx0 / W * pw), sw = Math.ceil(bx1 / W * pw) - sx, sy = Math.floor((1 - by1 / H) * ph), sh = Math.ceil((1 - by0 / H) * ph) - sy;
    if (sw > 0 && sh > 0){ ctx.save(); ctx.imageSmoothingEnabled = true; ctx.imageSmoothingQuality = 'high'; ctx.drawImage(G.c, sx, sy, sw, sh, sx / pw * W, sy / ph * H, sw / pw * W, sh / ph * H); ctx.restore();
      if (o.also) o.also.drawImage(G.c, sx, sy, sw, sh, sx / pw * W, sy / ph * H, sw / pw * W, sh / ph * H); }   /* o.also: a second 2D target (the sea's reflection) */
    return true;
  };
  window.bvCloudGL.ok = function(){ return !!init(); };   /* the scenes ask this, and paint their own clouds when it is false */
  window.bvCloudGL.status = function(){ var G = init(); return G ? 'on' : ('off' + (GL && GL.err ? ': ' + GL.err : '')); };
})();

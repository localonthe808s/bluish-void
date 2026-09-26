/* bvSky2 -- the golden-hour sky, rendered ONCE on the GPU (2026-09-26).
   User: "they're not good yet, keep iterating, i dont think we need to animate the golden hour artworks". Static means the
   whole sky can be one expensive pass: every cloud composited together (no stacked boxes), light marched toward the low
   sun through the real density, haze toward the horizon, and detail that scales with each cloud so a far cumulus is a
   small whole cumulus. Cells (cumulus, altocumulus / stratocumulus puffs) come from the CPU in perspective; the sheets
   (cirrus, cirrocumulus, stratus / altostratus / nimbostratus) are procedural bands.
   Sky units: W x H, y UP from the bottom; hz = horizon. */
(function(){
  var MAXC = 200;   /* cells live in a float TEXTURE (2 texels each): uniform arrays that large fail on phones */
  var VS = 'attribute vec2 a; varying vec2 v; void main(){ v = a * .5 + .5; gl_Position = vec4(a, 0., 1.); }';
  var FS = [
    'precision highp float;',
    'varying vec2 v;',
    'uniform vec2 uWH; uniform float uHz, uNC, uDark;',
    'uniform sampler2D uTex;',
    'vec4 CC(int i){ return texture2D(uTex, vec2((float(i) * 2. + .5) / ' + (MAXC * 2) + '., .5)); }',
    'vec4 KK(int i){ return texture2D(uTex, vec2((float(i) * 2. + 1.5) / ' + (MAXC * 2) + '., .5)); }',      /* cell: cx, yBase, halfW, h | kind (0 cu, 1 puff), seed, alpha, flat */
    'uniform vec4 uCi; uniform vec4 uCc; uniform vec4 uSh; uniform vec4 uSh2;',  /* bands: y0, y1, cover, on */
    'uniform vec2 uSun; uniform vec3 uSunC, uAmbC, uShdC, uHazeC;',
    'float h1(vec2 p){ return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }',
    'vec2 h2(vec2 p){ return fract(sin(vec2(dot(p, vec2(127.1, 311.7)), dot(p, vec2(269.5, 183.3)))) * 43758.5453); }',
    'float vn(vec2 p){ vec2 i = floor(p), f = fract(p); f = f * f * (3. - 2. * f);',
    '  return mix(mix(h1(i), h1(i + vec2(1., 0.)), f.x), mix(h1(i + vec2(0., 1.)), h1(i + vec2(1., 1.)), f.x), f.y); }',
    'float fbm(vec2 p){ float s = 0., a = .5; for (int i = 0; i < 5; i++){ s += a * vn(p); p = p * 2.03 + vec2(1.7, 9.2); a *= .5; } return s; }',
    'float dome(vec2 p){ vec2 i = floor(p), f = fract(p); float md = 9.;',
    '  for (int y = -1; y <= 1; y++) for (int x = -1; x <= 1; x++){ vec2 g = vec2(float(x), float(y)); vec2 o = .5 + .38 * sin(6.2831 * h2(i + g)); vec2 r = g + o - f; md = min(md, dot(r, r)); }',
    '  return max(0., 1. - md * 1.45); }',
    /* ONE CELL: several rounded HEADS of different heights on a flat base (a cumulus silhouette), cauliflower on them,
       all in the cell's own units so a far cloud is a small whole one. kind 0 cumulus (tall heads), 1 puff (low, wide),
       2 cumulonimbus (a tower narrowing upward under a wide flat anvil) */
    'float cell(vec2 p, vec4 c, vec4 k){',
    '  vec2 q = (p - vec2(c.x, c.y)) / vec2(c.z, c.w);',
    '  if (abs(q.x) > 1.5 || q.y < -1.2 || q.y > 2.) return -1.;',   /* -1, not 0: 0 passes the soft threshold and each cell box drew a faint rectangle */
    '  vec2 s = (p - vec2(c.x, c.y)) / c.z * 2.2 + k.y * 17.;',
    '  float body = -1.;',
    '  if (k.x > 3.5){',   /* the STORM BASE (kind 4): a dark ragged underside with scud hanging off it, over the tower's ruler-flat cut */
    '    float slab = 1. - q.x * q.x * q.x * q.x;',
    '    float yb = -.30 + (fbm(vec2(q.x * 3.5, k.y * 5.)) - .5) * 1.0 + (fbm(vec2(q.x * 11., k.y * 7.)) - .5) * .35;',
    '    body = min(slab, min((q.y - yb) * 3.5, (1. - q.y) * 2.5));',
    '    for (int i = 0; i < 6; i++){ float fi = float(i), xi = (h1(vec2(fi, k.y + 4.)) - .5) * 1.5, yi = -.40 - .32 * h1(vec2(k.y, fi + 9.)), ri = .06 + .07 * h1(vec2(fi + 3., k.y));',
    '      vec2 dd = vec2((q.x - xi) / (ri * 1.8), (q.y - yi) / (ri * c.z / c.w)); body = max(body, (1. - dot(dd, dd)) * .8); }',   /* scud: torn, wider than tall */
    '  } else if (k.x < .5){',                                                   /* CUMULUS: heads on a soft flat base */
    '    for (int i = 0; i < 5; i++){ float fi = float(i), xi = (h1(vec2(k.y, fi)) - .5) * 1.1, ri = .38 + .30 * h1(vec2(fi, k.y + 3.)), hi = .55 + .45 * h1(vec2(fi + 7., k.y));',
    '      vec2 dd = vec2((q.x - xi) / (ri * .85), (q.y - .18 - hi * .5) / (hi * .5)); body = max(body, 1. - dot(dd, dd)); }',
    '    vec2 sk = vec2(q.x / .88, (q.y - .22) / .28); body = max(body, (1. - dot(sk, sk)) * .8);',   /* a broad skirt the heads sit on: rounded corners, not a boxy cut */
    '    body = min(body, smoothstep(-.06, .14, q.y) * 2. - 1.);',        /* the flat base, softened */
    '  } else if (k.x < 1.5){',                                          /* PUFF: a rounded blob of 4-6 lobes, bottom rounded too */
    '    for (int i = 0; i < 9; i++){ float fi = float(i), xi = (h1(vec2(k.y, fi)) - .5) * 1.5, yi = (h1(vec2(fi, k.y + 1.)) - .5) * .7, ri = .22 + .32 * h1(vec2(fi, k.y + 3.)) * (1. - .5 * abs(xi));',
    '      vec2 dd = vec2((q.x - xi) / ri, (q.y - .45 - yi) / (ri * 1.15)); body = max(body, 1. - dot(dd, dd)); }',
    '    body = min(body, (q.y + .15) * 3.);',   /* a flatter underside than top */
    '  } else {',                                                        /* CUMULONIMBUS: a column narrowing upward under a wide anvil */
    '    vec2 qa = vec2(q.x, q.y * c.w / c.z);',                          /* round lobes: both axes in half-widths */
    '    float top = c.w / c.z;',
    '    if (k.x < 2.5) for (int i = 0; i < 14; i++){ float fi = float(i), yi = (.04 + fi * .066) * top, xi = (h1(vec2(fi, k.y + 2.)) - .5) * .6 * (1. - fi / 20.), ri = (.30 + .18 * h1(vec2(k.y, fi + 5.))) * (1.15 - .35 * fi / 14.);',
    '      vec2 dd = (qa - vec2(xi, yi)) / ri; body = max(body, 1. - dot(dd, dd)); }',   /* a tower of boiling heads, not a pillar */
    '    if (k.x < 2.5){ vec2 sk = vec2(q.x / .8, (qa.y - .14) / .22); body = max(body, (1. - dot(sk, sk)) * .8); }',   /* kind 3: the ANVIL alone, behind bvCloudGL's tower */   /* a broad dark base */
    '    body = min(body, smoothstep(-.03, .05, q.y) * 2. - 1.);',
    '    float ax = q.x > 0. ? q.x / (k.x > 2.5 ? 1.3 : 1.4) : q.x / (k.x > 2.5 ? .72 : .75), ath = (k.x > 2.5 ? .13 : .075) * (1. - .75 * ax * ax) + .02;',   /* anvil: thick over the updraft, tapering, sheared downwind */
    '    float ay = (q.y - .98 - .03 * ax) / ath; float an = (1. - ax * ax) * .9 - ay * ay;   /* x*x, never pow(x, 2.): pow of a negative base is undefined in GLSL and ate the anvil */',
    '    if (k.x < 2.5){ vec2 od = vec2(q.x / .22, (qa.y - top * 1.04) / .2); an = max(an, 1. - dot(od, od)); }',   /* the overshooting top */
    '    body = max(body, an + (fbm(s * vec2(.5, 2.5)) - .5) * .5 * smoothstep(.3, 1., abs(ax)));',   /* fibrous where it thins */
    '  }',
    '  if (k.x > 2.5 && k.x < 3.5){',
    /* the ANVIL SHEET: smooth under the lid, fibrous (ice) downwind. It sits BEHIND the tower; where they meet, the tower's
       own renderer draws a crown of turrets in front (see the storm passes), so the join has one texture and one light */
    '    float tx = q.x + .254;',
    '    body = min(body, (1.06 - q.y) * 9.);',
    '    float fib = fbm(vec2(q.x * 3., q.y * 26.) + k.y * 9.);',
    '    float sheet = body + (fib - .5) * .45 * smoothstep(.1, .9, abs(q.x)) + (fbm(s * .8) - .5) * .18;',
    '    float da = mix(-1., sheet, smoothstep(-.40, -.05, tx));',   /* upwind of the updraft the crown (bvCloudGL puffs, drawn in front) is the cloud: no sheet poking out the back */
    '    da -= 2. * (smoothstep(1.15, 1.45, abs(q.x)) + (1. - smoothstep(-1.15, -.85, q.y)));',
    '    return da * k.z;',
    '  }',
    '  float inside = smoothstep(-.35, .1, body);',                        /* the cauliflower stays on the cloud: no fins */
    '  float d = body + inside * (.30 * dome(s) + .13 * dome(s * 2.3 + 2.) + .05 * dome(s * 5.1 + 5.) - .20);',
    '  float rim = smoothstep(-.55, -.15, body) * (1. - smoothstep(.0, .5, body));',   /* fray only near the outline: noise at the box edge cut straight lines */
    '  d += rim * (fbm(s * 1.7 + 3.) - .52) * .55;',   /* the outline frays: the SVG art never has a clean pill edge */
    '  d -= 2. * (smoothstep(1.15, 1.45, abs(q.x)) + smoothstep(1.6, 1.95, q.y) + (1. - smoothstep(-1.15, -.85, q.y)));',   /* fade out before the clip box: no straight cuts */
    '  return d * k.z;',   /* UNCLAMPED: the lighting reads its slope (a clamped field is flat inside -- the pink fill) */
    '}',
    'float sheets(vec2 p){',
    '  float d = 0.;',
    '  if (uCi.w > .5 && p.y > uCi.x && p.y < uCi.y){',                    /* CIRRUS: fibres curling along the wind, hooked at the ends */
    '    float b = smoothstep(uCi.x, uCi.x + 8., p.y) * (1. - smoothstep(uCi.y - 10., uCi.y, p.y));',
    '    vec2 w = vec2(fbm(p * .025), fbm(p * .025 + 7.)) * 18.;',
    '    vec2 f = (p + w) * vec2(.012, .16);',   /* long streaks: an elongated low frequency, warped so they curl */
    '    float fib = fbm(f) * .7 + fbm(f * vec2(2.3, 1.1) + 3.) * .3;',
    '    float patchy = smoothstep(1. - uCi.z, 1. - uCi.z + .35, fbm(p * vec2(.012, .05) + 11.));',
    '    d = max(d, smoothstep(.52, .78, fib) * patchy * b * .7); }',
    '  if (uCc.w > .5 && p.y > uCc.x && p.y < uCc.y){',                    /* CIRROCUMULUS: fine grains in ripples, patchy, finer toward the horizon */
    '    float b = smoothstep(uCc.x, uCc.x + 45., p.y) * (.55 + .45 * fbm(vec2(p.x * .02, 3.))) * (1. - smoothstep(uCc.y - 14., uCc.y, p.y));',
    '    float fy = clamp((p.y - uCc.x) / max(uCc.y - uCc.x, 1.), 0., 1.);',
    '    vec2 w = vec2(fbm(p * .03), fbm(p * .03 + 5.)) * 6.;',
    /* NOT a lattice of equal spots (the user: "leopard clouds"): fine grains strung along wavy RIPPLE ROWS, grain size and
       spacing varying, in small patches over a faint veil. Fixed scales blended by height (a y-varying scale shears) */
    '    float rF = sin((p.y + w.y * 1.4) * 1.25 + fbm(p * vec2(.05, .02)) * 9.), rN = sin((p.y + w.y * 1.4) * .75 + fbm(p * vec2(.04, .02) + 2.) * 9.);',
    '    float rip = mix(rF, rN, smoothstep(.2, .9, fy)) * .5 + .5;',
    '    float gF = dome((p + w) * vec2(.66, 1.05)), gN = mix(dome((p + w) * vec2(.42, .64) + 3.), dome((p + w) * vec2(.30, .46) + 9.), smoothstep(.45, .65, fbm(p * .025 + 21.)));',   /* overhead, some runs coarser than others */
    '    float run = smoothstep(.05, .75, rip) * smoothstep(.36, .62, fbm(p * vec2(.07, .25) + 13.));',
    '    float gr = mix(gF, gN, smoothstep(.2, .9, fy)) * run * (.7 + .6 * fbm(p * .12 + 7.));',
    '    float patchy = smoothstep(.56 - uCc.z * .2, .74 - uCc.z * .2, fbm(p * vec2(.03, .07) + 4.));',
    '    float veil = smoothstep(.45, .7, fbm(p * vec2(.02, .05) + 4.)) * 0.;   /* the veil read as a mauve smudge */',
    /* only the round centre of each grain, on a wide ramp: soft separate dots, not a cobblestone mesh */
    '    float halo = run * patchy * .2;',   /* a soft bed under each run: the flecks sit in a glow, not on bare sky */
    '    d = max(d, (max(smoothstep(.22, .95, gr) * .85 * patchy, halo) + veil) * b); }',
    '  if (uSh.w > .5){',                                                  /* STRATUS / ALTOSTRATUS / NIMBOSTRATUS: a soft sheet */
    '    float mid = (uSh.x + uSh.y) * .5, th = (uSh.y - uSh.x) * .5;',
    '    float out_ = abs(p.y - mid) - th - (fbm(vec2(p.x * .045, 1.)) - .5) * 14.;',   /* the edge wobbles in SKY UNITS: a wobble relative to a tall deck dripped flames */
    '    d = max(d, smoothstep(6., -8., out_ + (fbm(p * .05) - .5) * 8.) * uSh.z); }',
    '  if (uSh2.w > .5){',
    '    float mid = (uSh2.x + uSh2.y) * .5, th = (uSh2.y - uSh2.x) * .5;',
    '    float s = 1. - abs(p.y - mid) / max(th * (1. + (fbm(vec2(p.x * .03, 5.)) - .5) * .8), 1.);',
    '    d = max(d, smoothstep(0., .35, s + (fbm(p * .035 + 9.) - .5) * .5) * uSh2.z); }',
    '  return d;',
    '}',
    'float field(vec2 p){ float d = -1.; for (int i = 0; i < ' + MAXC + '; i++){ if (float(i) >= uNC) break; vec4 c = CC(i); if (abs(p.x - c.x) > c.z * 1.6 || p.y < c.y - c.w * 1.3 || p.y > c.y + c.w * 2.1) continue; d = max(d, cell(p, c, KK(i))); } return d; }',
    'uniform vec4 uRain;',   /* storm rain: cx, half width, cloud-base y, strength */
    'float rainD(vec2 p){',   /* soft slanted CURTAINS, not hard stripes */
    '  if (uRain.w <= 0.) return 0.;',
    '  float dx = (p.x - uRain.x - (uRain.z - p.y) * .06) / uRain.y;   /* a slight slant, and it stays under the cloud */',
    '  if (abs(dx) > 1.4 || p.y > uRain.z + 4. || p.y < uHz - 2.) return 0.;',
    '  float side = 1. - smoothstep(.45, 1.25, abs(dx + (fbm(vec2(p.y * .04, 3.)) - .5) * .5));',
    '  float veil = .35 + .65 * smoothstep(.3, .7, fbm(vec2(p.x * .18 + p.y * .035, p.y * .01 + 5.)));',
    '  float top = smoothstep(uRain.z + 4., uRain.z - 8., p.y), bot = (.55 + .45 * smoothstep(uHz - 2., uHz + 22., p.y)) * smoothstep(uHz - .5, uHz + 3., p.y);   /* ends at the horizon, not in the ground */',
    '  return side * veil * top * bot * uRain.w;',
    '}',
    'uniform vec4 uCrease;',   /* cx, half width, y of the anvil underside, strength */
    'float creaseV(vec2 p){ if (uCrease.w <= 0.) return 0.; float ex = 1. - smoothstep(uCrease.y * .6, uCrease.y * 1.05, abs(p.x - uCrease.x)); return ex * smoothstep(uCrease.z - 16., uCrease.z - 1., p.y) * (1. - smoothstep(uCrease.z - 1., uCrease.z + 3., p.y)) * uCrease.w; }',
    'float dens(vec2 p){ return max(sheets(p), smoothstep(-.16, .5, field(p))); }',   /* soft edges, as the SVG art has */
    'void main(){',
    '  vec2 p = v * uWH;',
    '  if (p.y < uHz - 2.){ gl_FragColor = vec4(0.); return; }',
    '  float d0 = dens(p);',
    '  float rd = rainD(p); vec3 rc = mix(vec3(.36, .35, .42), uShdC * .6, .3);',
    '  float cr = creaseV(p); vec3 cc = uShdC * .55;',
    '  if (d0 < .004){ vec4 o = vec4(rc * rd, rd); o = vec4(cc * cr, cr) + o * (1. - cr); gl_FragColor = o; return; }',
    '  vec2 L = normalize(uSun - p); float jit = h1(p * 31.7), acc = 0.;',
    '  L = normalize(vec2(L.x, max(L.y, .25)));',   /* the light comes up from below but not sideways across the sky -- long level marches cut shadow wedges between clouds */
    '  for (int i = 0; i < 10; i++) acc += dens(p + L * (.8 + (float(i) + jit) * 1.3));',
    '  float Ts = exp(-acc * .30);',                                         /* light that reaches this point through the cloud */
    '  float e = .7; float gx = field(p + vec2(e, 0.)) - field(p - vec2(e, 0.)), gy = field(p + vec2(0., e)) - field(p - vec2(0., e));',
    '  vec3 N = normalize(vec3(-gx * 8., -gy * 8., 1.));   /* steep: the lobes must read as separate rounded heads */',
    '  float lam = max(0., dot(N, normalize(vec3(L, .35)))) * .75 + .25;',
    '  float up = clamp(N.y * .5 + .5, 0., 1.);',                            /* faces toward the sky get sky light */
    '  float sunAng = length(p - uSun) / max(uWH.x, 1.);',
    '  float silver = (1. - smoothstep(.0, .45, d0)) * exp(-sunAng * 4.) * .6;',   /* thin edges near the sun glow */
    '  float lit = clamp((.25 + .75 * Ts) * lam * 1.2, 0., 1.);',
    '  vec3 c = mix(uShdC * 1.12, uSunC * 1.1, smoothstep(-.15, .7, lit)) + uAmbC * up * .18;',
    '  float low = exp(-max(0., p.y - uSun.y) / 60.) * exp(-abs(p.x - uSun.x) / (uWH.x * .8));',
    '  c += vec3(.22, .07, -.06) * (1. - up) * low * (1. - uAmbC.b * .3);',   /* undersides facing the low sun catch fire */   /* a real lit side and a real shade side */
    '  c *= .95 + .1 * fbm(p * .9);',
    '  c = mix(c, vec3(.29, .29, .33) * (.8 + .45 * fbm(p * vec2(.03, .08))), uDark * smoothstep(uHz + 10., uHz + 60., p.y));',   /* nimbostratus: a dark deck, only its low edge catching the light */   /* grain: the SVG art is textured, not airbrushed */   /* cream overall, shading gentle -- the SVG art reads luminous */
    '  c += uSunC * silver;',
    '  float hz = exp(-max(0., p.y - uHz) / 28.);',                          /* haze: low clouds melt into the horizon */
    '  c = mix(c, uHazeC, hz * .55);',
    '  c = mix(c, uHazeC * 1.18, (1. - smoothstep(uHz + 20., uHz + 150., p.y)) * .30 * (1. - uDark));',   /* lower clouds take the horizon's warmth */
    '  float a = clamp(d0 * 1.25, 0., 1.) * (1. - hz * .35);',
    '  if (uRain.w > 0.){ float bz = (1. - smoothstep(uRain.y * .9, uRain.y * 1.6, abs(p.x - uRain.x))) * (1. - smoothstep(uRain.z + 2., uRain.z + 20., p.y)); c = mix(c, c * vec3(.60, .58, .64), bz * .85); }',   /* the base in its own shadow */
    '  gl_FragColor = vec4(c * a, a) + (vec4(cc * cr, cr) + vec4(rc * rd, rd) * (1. - cr)) * (1. - a);',
    '}'
  ].join('\n');
  var GL = null;
  function init(){
    if (GL) return GL.ok ? GL : null;
    GL = { ok: false };
    try {
      var c = document.createElement('canvas'), g = c.getContext('webgl', { premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: true });
      if (!g || !g.getExtension('OES_texture_float')) return null;
      var sh = function(t, s){ var o = g.createShader(t); g.shaderSource(o, s); g.compileShader(o); if (!g.getShaderParameter(o, g.COMPILE_STATUS)) throw new Error(g.getShaderInfoLog(o)); return o; };
      var pr = g.createProgram(); g.attachShader(pr, sh(g.VERTEX_SHADER, VS)); g.attachShader(pr, sh(g.FRAGMENT_SHADER, FS)); g.linkProgram(pr);
      if (!g.getProgramParameter(pr, g.LINK_STATUS)) throw new Error(g.getProgramInfoLog(pr));
      g.useProgram(pr);
      var b = g.createBuffer(); g.bindBuffer(g.ARRAY_BUFFER, b); g.bufferData(g.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), g.STATIC_DRAW);
      var loc = g.getAttribLocation(pr, 'a'); g.enableVertexAttribArray(loc); g.vertexAttribPointer(loc, 2, g.FLOAT, false, 0, 0);
      var U = {}; ['uCrease', 'uRain', 'uWH', 'uHz', 'uNC', 'uTex', 'uCi', 'uCc', 'uSh', 'uSh2', 'uDark', 'uSun', 'uSunC', 'uAmbC', 'uShdC', 'uHazeC'].forEach(function(n){ U[n] = g.getUniformLocation(pr, n); });
      GL = { ok: true, c: c, g: g, U: U };
    } catch (e){ GL = { ok: false, err: String(e) }; if (window.console) console.warn('bvSky2 off:', e); return null; }
    return GL;
  }
  function rng(seed){ var s = seed >>> 0 || 1; return function(){ s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }
  /* light by sun altitude; the sun sits on the horizon at golden hour, a little right of centre */
  function light(sa, W, hz){
    var sx = W * 0.62;
    if (sa > 12) return { sun: [W * 0.3, hz + 400], sc: [1.05, 1.0, 0.95], amb: [0.55, 0.66, 0.85], shd: [0.52, 0.56, 0.66], haze: [0.78, 0.84, 0.92] };
    if (sa > 0){ var k = sa / 12; return { sun: [sx, hz + 4 + 60 * k], sc: [1.07, 0.96 + 0.03 * k, 0.82 + 0.12 * k], amb: [0.46, 0.42, 0.48], shd: [0.74 + 0.02 * k, 0.58 + 0.06 * k, 0.52 + 0.1 * k], haze: [0.95, 0.66, 0.46] }; }   /* cream-peach lit, rose shade: the SVG art's warmth */
    if (sa > -6){ var b = -sa / 6; return { sun: [sx, hz - 10 - 20 * b], sc: [1.06 - 0.16 * b, 0.86 - 0.16 * b, 0.72 - 0.1 * b], amb: [0.34, 0.30, 0.34], shd: [0.68 - 0.14 * b, 0.52 - 0.1 * b, 0.48 - 0.08 * b], haze: [0.80, 0.52, 0.42] }; }   /* peach-rose dimming, never lilac (the SVG keeps blue hour warm) */
    return { sun: [W * 0.4, hz + 160], sc: [0.40, 0.44, 0.56], amb: [0.10, 0.12, 0.20], shd: [0.07, 0.08, 0.13], haze: [0.14, 0.15, 0.24] };
  }
  /* types -> cells + bands */
  function compose(o, W, H, hz){
    var sky = H - hz, C = [], K = [], bands = { ci: [0, 0, 0, 0], cc: [0, 0, 0, 0], sh: [0, 0, 0, 0], sh2: [0, 0, 0, 0] };
    var add = function(cx, yb, hw, h, kind, a){ if (C.length >= MAXC) return; C.push([cx, yb, hw, h]); K.push([kind, Math.random() * 0 + (C.length * 0.137) % 1, a == null ? 1 : a, 0]); };
    /* perspective: a row at height f (0 horizon .. 1 overhead) is placed at y and scaled by s */
    var rowY = function(f, top){ return hz + (top - hz) * Math.pow(f, 1.35); };
    (o.types || []).forEach(function(ty, ti){
      var c = Math.max(0, Math.min(100, ty.cover || 0)) / 100, R = rng(97 + ti * 131), g = ty.genus;
      if (g === 'Cirrus') bands.ci = [hz + sky * 0.52, H - 4, 0.25 + 0.65 * c, 1];
      else if (g === 'Cirrostratus') bands.sh2 = [hz + sky * 0.70, H - 6, 0.35 + 0.3 * c, 1];
      else if (g === 'Cirrocumulus') bands.cc = [hz + sky * 0.14, H - 6, 0.3 + 0.6 * c, 1];
      else if (g === 'Altostratus') bands.sh2 = [hz + sky * 0.45, hz + sky * 0.72, 0.5 + 0.4 * c, 1];
      else if (g === 'Stratus'){ if (!bands.ns) bands.sh = [hz + 4, hz + sky * 0.24, 0.8 + 0.2 * c, 1]; }
      else if (g === 'Nimbostratus'){ bands.ns = 1; bands.sh = [hz + sky * 0.14, H + sky * 0.9, 0.97, 1]; }   /* the deck covers the sky; a lit gap stays at the horizon. Stratus under it must not overwrite it */
      else if (g === 'Cumulus' || g === 'Cumulonimbus'){
        var n = g === 'Cumulonimbus' ? 1 : Math.round(10 + 30 * c);
        if (g === 'Cumulonimbus') add(W * 0.46, hz + 8, 72, sky * 0.68, 2, 1);
        for (var i = 0; i < n && g !== 'Cumulonimbus'; i++){
          var f = i === 0 ? 0.9 : Math.pow(R(), 2.0), s = 0.2 + 1.05 * f;   /* one near cloud, a crowd of far ones */                 /* most are far and small */
          add(R() * W, rowY(f * 0.4, H) + 2, (18 + 22 * c) * s * (0.8 + 0.5 * R()), (15 + 22 * c) * s * (0.7 + 0.6 * R()), 0, 1);
        }
      } else if (g === 'Altocumulus' || g === 'Stratocumulus'){
        var ac = g === 'Altocumulus', rows = ac ? 10 : 6, top = ac ? hz + sky * 0.9 : hz + sky * 0.62;
        /* MASSES, NOT A GRID: patches scattered in perspective, big and merging overhead, flattening into wide strands at the
           horizon; each patch sometimes a clump of 2-3 cells so they merge like the SVG art */
        var nP = Math.round((ac ? 60 : 40) * (0.35 + 0.8 * c));
        for (var pI = 0; pI < nP && C.length < MAXC; pI++){
          var fr = Math.pow(R(), 1.3), yy = rowY(fr, top), s2 = 0.22 + 0.9 * fr;
          var hw = (ac ? 20 : 26) * s2 * (0.7 + 0.6 * R()), flat = 1 - fr;                /* toward the horizon: wider and flatter */
          var hh = hw * (ac ? 0.72 : 0.5) * (1 - 0.55 * flat), cx0 = R() * W, nC = R() < 0.4 ? 1 : 2 + Math.floor(R() * 2);
          for (var m = 0; m < nC && C.length < MAXC; m++) add(cx0 + (m - (nC - 1) / 2) * hw * 1.1 + (R() - 0.5) * hw * 0.4, yy + (R() - 0.5) * hh * 0.6, hw * (1 + flat * 1.3) * (0.7 + 0.4 * R()), hh * (0.8 + 0.4 * R()), 1, 0.95);
        }
      }
    });
    /* a storm owns its part of the sky: mid-level puffs that would sit on the anvil are dropped */
    var cb = C.findIndex(function(c, i){ return K[i][0] === 2; }), cbX = cb >= 0 ? C[cb][0] : o.stormX;
    if (cbX != null){ var C2 = [], K2 = []; C.forEach(function(c, i){ if (K[i][0] === 1 && Math.abs(c[0] - cbX) < 100 && c[1] > hz + sky * 0.42) return; C2.push(c); K2.push(K[i]); }); C = C2; K = K2; }
    if (o.anvil){ C.push(o.anvil); K.push([3, 0.37, 1, 0]); }
    if (o.base){ C.push(o.base); K.push([4, 0.61, 0.97, 0]); }
    return { C: C, K: K, bands: bands };
  }
  /* THE STORM is the front scenes' own tower (bvCloudGL in cloud_gl.js: cauliflower, sheared anvil, NCAR rain shaft) --
     the user: "our cumulonimbus looked better than this". The sky draws in three passes so the storm sits between layers:
     high + mid behind it, the storm, then the low clouds in front. */
  function stormLight(sa){
    if (sa > 12) return { d: [-0.5, 0.8], c: [1.04, 0.99, 0.93], s: [0.56, 0.58, 0.66], n: 0 };
    if (sa > 0){ var k = Math.min(1, sa / 12); return { d: [0.95 - 1.45 * k, -0.12 + 0.92 * k], c: [1.22 - 0.18 * k, 0.86 + 0.13 * k, 0.66 + 0.27 * k], s: [0.66 - 0.10 * k, 0.48 + 0.10 * k, 0.52 + 0.14 * k], n: 0 }; }
    if (sa > -6){ var b = -sa / 6; return { d: [0.9, -0.35], c: [1.10 - 0.3 * b, 0.78 - 0.2 * b, 0.64 - 0.12 * b], s: [0.42 - 0.12 * b, 0.32 - 0.1 * b, 0.34 - 0.08 * b], n: 0.3 * b }; }
    return { d: [0.2, 0.9], c: [0.50, 0.54, 0.68], s: [0.08, 0.10, 0.16], n: 1 };
  }
  window.bvSky2 = function(ctx, o){
    var types = o.types || [], cbT = types.filter(function(t){ return t.genus === 'Cumulonimbus'; })[0];
    if (cbT && window.bvCloudGL && bvCloudGL.ok() && !o._pass){
      var W0 = o.W || 220, H0 = o.H || 232, hz0 = o.hz == null ? 40 : o.hz, sky0 = H0 - hz0, sx = W0 * 0.46, L = stormLight(o.sa == null ? 3 : o.sa);
      var isLow = function(t){ return t.layer === 'low' || t.layer === 'deep'; };
      var r = bvSky2(ctx, Object.assign({}, o, { _pass: 1, stormX: sx, types: types.filter(function(t){ return !isLow(t) && t !== cbT; }) }));
      bvCloudGL(ctx, { W: W0, H: H0, ppu: o.ppu || 4, t: 7, ns: 0.62, ground: hz0, night: L.n, sunDir: L.d, sunCol: L.c, shdCol: L.s,
        cx: sx, base: hz0 + 18, h: sky0 * 0.62, hw: 33, lean: 0.35, anvil: 1, anvR: 100, anvL: 58, anvT: 2.1, rain: 0, rag: 7, dens: 1 });   /* the anvil in the SAME field as the tower: one shape, one texture, one light -- every separate anvil read as pasted on. anvT thickens it for this scale; anvR runs it off-frame downwind */   /* hw 38: about 1.6 tall to 1 wide, a mature storm's body (it measured 2.4 : 1 at hw 28); rain is the sky pass's soft curtains */   /* a SMALL flare of its own (its full anvil is a thin plate at this size): the crown spreads into the soft anvil drawn behind, so the two join instead of a band pasted across the tower */   /* the front card's proportions (hw 16 : anvR 70 : anvL 32 at its scale) */
      bvSky2(ctx, Object.assign({}, o, { _pass: 1, stormX: sx, rain: [sx + 33 * 0.14, 33 * 0.68, hz0 + 19, 0.85]   /* under the base as MEASURED (x 73..139, centre ~106 for sx 101, hw 38): centred on it, inside its width */, types: types.filter(function(t){ return isLow(t) && t !== cbT; }) }));   /* the anvil IN FRONT, opaque, swallowing the crown: the tower hits the lid and spreads */
      return r;
    }
    var G = init(); if (!G) return false;
    var W = o.W || 220, H = o.H || 232, hz = o.hz == null ? 40 : o.hz, ppu = o.ppu || 4;
    var pw = Math.round(W * ppu), ph = Math.round(H * ppu);
    if (G.c.width !== pw || G.c.height !== ph){ G.c.width = pw; G.c.height = ph; }
    var g = G.g, U = G.U, Lg = light(o.sa == null ? 3 : o.sa, W, hz), S = compose(o, W, H, hz);
    g.viewport(0, 0, pw, ph); g.clearColor(0, 0, 0, 0); g.clear(g.COLOR_BUFFER_BIT);
    var T = new Float32Array(MAXC * 2 * 4);
    S.C.forEach(function(c, i){ T.set(c, i * 8); T.set(S.K[i], i * 8 + 4); });
    if (!G.tex){ G.tex = g.createTexture(); }
    g.bindTexture(g.TEXTURE_2D, G.tex);
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_MIN_FILTER, g.NEAREST); g.texParameteri(g.TEXTURE_2D, g.TEXTURE_MAG_FILTER, g.NEAREST);
    g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_S, g.CLAMP_TO_EDGE); g.texParameteri(g.TEXTURE_2D, g.TEXTURE_WRAP_T, g.CLAMP_TO_EDGE);
    g.texImage2D(g.TEXTURE_2D, 0, g.RGBA, MAXC * 2, 1, 0, g.RGBA, g.FLOAT, T);
    g.uniform1i(U.uTex, 0);
    g.uniform2f(U.uWH, W, H); g.uniform1f(U.uHz, hz); g.uniform1f(U.uNC, S.C.length);
    
    g.uniform4fv(U.uCi, S.bands.ci); g.uniform4fv(U.uCc, S.bands.cc); g.uniform4fv(U.uSh, S.bands.sh); g.uniform4fv(U.uSh2, S.bands.sh2);
    g.uniform1f(U.uDark, S.bands.ns ? 1 : 0); g.uniform4fv(U.uRain, o.rain || [0, 0, 0, 0]); g.uniform4fv(U.uCrease, o.crease || [0, 0, 0, 0]); g.uniform2f(U.uSun, Lg.sun[0], Lg.sun[1]); g.uniform3fv(U.uSunC, Lg.sc); g.uniform3fv(U.uAmbC, Lg.amb); g.uniform3fv(U.uShdC, Lg.shd); g.uniform3fv(U.uHazeC, Lg.haze);
    g.drawArrays(g.TRIANGLE_STRIP, 0, 4);
    ctx.drawImage(G.c, 0, 0, W, H);
    return true;
  };
})();

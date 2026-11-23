/* bvSky3D -- THE VOLUMETRIC HERO SKIES (2026-11-23; user: "lets go live with them", after the cloud lab
   _cloudlab/volumetric_lab.html, where every scene was built and judged beside the old one).
   One WebGL2 renderer, a recipe per cloud type: rays marched through a 3-D cloud field lit by the real sun (or the moon), with
   multiple scattering, a baked 64^3 noise volume, a true pinhole camera; precipitation drawn in depth on its own canvas (snow,
   rain, drizzle, sleet, heavy rain, freezing rain, hail) and the storm's own lightning; clear day = single-scattering sky graded to
   the dashboard's own colors; clear night = twilight (with the Earth's shadow) and horizon extinction over the night photo.
   The page's moon and sun are drawn by the page: no disc here. Fails safe: any WebGL trouble -> ok() is false and the hero keeps
   its old clouds (hero_gl.js). The SHADERS are copied verbatim from the lab -- change them there first, then copy here.
   API:  bvSky3D.ok()                       WebGL2 present and the shaders built
         bvSky3D.sync(host, o)              o = { state, code, night, sunAlt, eve, pal:[4 hex] }  -> true if it drew the sky
         bvSky3D.stop()                     remove its canvases, stop the loop
         bvSky3D.stats()                    { fps, w, h, scene } */
(function(){
'use strict';
var REDUCED = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
var PHONE = !!(window.matchMedia && matchMedia('(pointer: coarse)').matches) || window.innerWidth < 700;
var cv = document.createElement('canvas'), px = document.createElement('canvas'), ext = document.createElement('canvas');
cv.className = 'hero-s3d'; px.className = 'hero-s3d-px'; ext.className = 'hero-s3d-ext';
cv.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:0;';
px.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:0;';
ext.style.cssText = 'position:absolute;left:0;top:0;width:100%;height:100%;pointer-events:none;z-index:0;mix-blend-mode:multiply;';
var gl = null, gp = null, OK = false, BROKEN = false;
try { gl = cv.getContext('webgl2', { antialias: false, premultipliedAlpha: false, preserveDrawingBuffer: true }); gp = px.getContext('webgl2', { premultipliedAlpha: true, alpha: true }); } catch(e){}
var VS = '#version 300 es\nout vec2 vUV; void main(){ vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2)); vUV = p; gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0); }';
var FS = [
'#version 300 es',
'precision highp float;',
'in vec2 vUV; out vec4 o;',
'uniform vec2 uRes; uniform float uTime, uCover, uGlow, uNight, uB0, uB1, uType, uPit, uFrame, uFlash, uE0, uAtmo, uPalK, uTwi, uHail; uniform vec3 uP0, uP1, uP2, uP3; uniform vec3 uL, uFP; uniform highp sampler3D uN;',
'float nz(vec3 p){ return texture(uN, p).r; }',
'bool isT(float k){ return abs(uType - k) < 0.5; }',
/* ONE RENDERER, A RECIPE PER CLOUD TYPE (uType): 0 stratocumulus deck (overcast); 1 cumulus (partly cloudy); 2 nimbostratus (rain);
   3 cumulonimbus (thunderstorm: one tower and its anvil); 4 fog (the camera inside it); 5 snow deck (nimbostratus, paler) */
'float smin(float a, float b, float k){ float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0); return mix(b, a, h) - k * h * (1.0 - h); }',
'float sdRC(vec3 q, float r, float h0, float h1, float rr){ vec2 d = vec2(length(q.xz) - r + rr, max(h0 - q.y, q.y - h1) + rr); return min(max(d.x, d.y), 0.0) + length(max(d, 0.0)) - rr; }   /* a rounded cylinder */',
'const vec3 SC = vec3(-7.0, 0.0, 40.0);   /* centered on the whole cloud (flanking line left, anvil right), close enough to fill the panel */   /* the storm cell: left of center, 60 km away, so its anvil streams off to the right */',
'float dens(vec3 p, int oct){',
'  vec3 w = vec3(uTime * 0.03, 0.0, uTime * 0.01);',
/* THE THUNDERSTORM, BUILT FROM SHAPES (user 2026-11-23: "improve thunderstorm shapes"): the main updraft tower with an overshooting
   dome punching above the anvil; a flanking line of smaller towers stepping down on the side away from the anvil; a wedge anvil
   with a flat top at the tropopause, thinning downwind, lumpy underneath; a flat dark base; rain shaft under the core, downwind.
   Rounded cylinders merged with a smooth union; big rounded billows (cauliflower) carved into the surface, not fine fuzz */
'  if (isT(3.0)){',
'    float y = p.y; if (y < 0.0 || y > 15.5) return 0.0; vec3 q = p - SC;',
'    float b1 = nz((p + w) * 0.07), b2 = oct > 1 ? nz((p + w) * 0.16) : 0.5, b3 = oct > 3 ? nz((p + w) * 0.5) : 0.5;',
'    float s1 = smoothstep(0.25, 0.75, b1), s2 = smoothstep(0.3, 0.7, b2);',
'    float bil = s1 * s1 * 3.2 + s2 * 1.0 + (b3 - 0.5) * 0.3;   /* smooth rounded lumps (ridged noise made a crest of spikes) */',
'    float s = sdRC(q, 6.0, 1.2, 9.8, 4.6);                                         /* the main updraft: heavily rounded, a domed top, no straight edges */',
'    s = smin(s, sdRC(q - vec3(2.6, 0.0, -1.5), 4.6, 1.2, 11.2, 3.8), 2.2);        /* a second turret beside it, rising higher */',
'    s = smin(s, length(q - vec3(1.8, 12.9, -0.8)) - 3.4, 1.8);                     /* the overshooting top, a dome clear above the anvil */',
'    s = smin(s, sdRC(q - vec3(-10.5, 0.0, 2.0), 4.2, 1.2, 8.2, 2.6), 1.8);        /* the flanking line, stepping down away from the anvil */',
'    s = smin(s, sdRC(q - vec3(-17.5, 0.0, 3.5), 3.3, 1.2, 6.0, 2.2), 1.5);',
'    s = smin(s, sdRC(q - vec3(-23.0, 0.0, 4.5), 2.5, 1.2, 4.2, 1.8), 1.2);',
'    float ax = q.x - 2.0, top = 12.0 - max(ax, 0.0) * 0.03, bot = 9.0 + max(ax, 0.0) * 0.08;   /* the anvil: flat top, thinning and its underside rising downwind */',
'    float wid = (5.5 + max(ax, 0.0) * 0.2) * (1.0 - 0.45 * smoothstep(10.0, 19.0, ax)), zc = max(ax, 0.0) * 0.18;   /* thinning toward its end */               /* it fans out AWAY from us (+z), so perspective does not lift its far end */',
'    float an = max(max(abs(q.z - zc) - wid, y - top), max(bot - y, max(-ax - 4.0, ax - 19.0 + (b1 - 0.5) * 7.0)));   /* a frayed, uneven end, not a square cut */',
'    an += (b2 - 0.5) * 1.0 * smoothstep(top - 0.6, bot, y);                       /* lumpy underneath, flat on top */',
'    s = smin(s, an, 1.6);',
'    float am = smoothstep(8.6, 9.6, y) * smoothstep(1.0, 5.0, ax);                 /* in the anvil the billows are gentle: it is one smooth sheet */',
'    float d = mix(-s + bil - 1.5, -s * 1.6 + 0.5 + (b2 - 0.5) * 0.8 + (b3 - 0.5) * 0.3, am);   /* the anvil: a dense smooth sheet */',
'    float body = smoothstep(0.0, 0.9, d) * smoothstep(1.1, 1.35, y);',
'    float shaft = y < 1.6 ? smoothstep(6.5, 2.0, length(q.xz - vec2(3.0, 0.0))) * (0.16 + 0.22 * uHail) * (0.5 + 0.9 * b3) : 0.0;   /* hail: a denser, whiter curtain */   /* rain under the core, downwind */',
'    return max(body, shaft); }',
'  float h = (p.y - uB0) / (uB1 - uB0);',
'  if (isT(4.0)){',
'    if (p.y < 0.0 || p.y > uB1) return 0.0;',
'    float wisp = nz((p + w * 2.5) * vec3(0.3, 1.5, 0.3)), fine = nz((p + w * 3.0) * vec3(1.1, 3.0, 1.1));',
'    return smoothstep(1.0, 0.1, h) * (0.12 + 1.1 * wisp * wisp + 0.3 * fine) * 0.7; }   /* wisps you can see drift by */',
'  if (h < -0.3 || h > 1.0) return 0.0;',
'  if (isT(0.0)){',
'    float cells = nz((p + w) * vec3(0.06, 0.12, 0.06));',
'    float lump = oct > 1 ? nz((p + w * 1.2) * vec3(0.24, 0.4, 0.24)) : 0.5;',
'    float fine = oct > 3 ? nz((p + w * 1.5) * vec3(0.8, 1.2, 0.8)) : 0.5;',
'    float hb = h + (lump - 0.5) * 0.45;',
'    float shape = smoothstep(0.0, 0.18, hb) * smoothstep(1.0, 0.45, h);',
'    float c = cells * 0.72 + lump * 0.38 + fine * 0.14 - 0.12;',
'    float big = nz((p + w * 0.6) * vec3(0.012, 0.02, 0.012));',
'    float thr = mix(0.66, 0.36, uCover) + (0.5 - big) * 0.28;',
'    return smoothstep(thr, thr + 0.1, c) * shape; }',
'  if (isT(1.0)){',
'    if (h < 0.0) return 0.0;',
'    float cells = nz((p + w) * vec3(0.085, 0.035, 0.085));',
'    float big = nz((p + w * 0.5) * vec3(0.018, 0.01, 0.018));',
'    float lump = oct > 1 ? nz((p + w * 1.15) * vec3(0.42, 0.42, 0.42)) : 0.5;',
'    float fine = oct > 3 ? nz((p + w * 1.3) * vec3(1.4, 1.4, 1.4)) : 0.5;',
'    float foot = cells * 1.25 + big * 0.35 - mix(1.12, 0.62, uCover);',
'    float d = foot * 1.9 - h * h * 0.9 - (lump - 0.5) * (0.35 + 0.5 * h) - (fine - 0.5) * 0.08;',
'    return smoothstep(0.0, 0.1, d) * smoothstep(0.0, 0.03, h); }',
/* 2 rain and 5 snow: the nimbostratus deck */
'  float big = nz((p + w) * vec3(0.03, 0.05, 0.03));',
'  float lump = oct > 1 ? nz((p + w * 1.3) * vec3(0.15, 0.3, 0.15)) : 0.5;',
'  float fine = oct > 3 ? nz((p + w * 1.6) * vec3(0.6, 0.9, 0.6)) : 0.5;',
'  if (h < 0.0){ float sc = smoothstep(0.6, 0.72, fine * 0.55 + lump * 0.6) * smoothstep(-0.3, -0.08, h) * smoothstep(0.08, -0.02, h); return sc * 0.7 * (isT(5.0) ? 0.5 : 1.0); }',
'  float hb = h + (lump - 0.5) * 0.22 + (fine - 0.5) * 0.12;',
'  float shape = smoothstep(0.0, 0.08, hb) * smoothstep(1.0, 0.55, h);',
'  float c = big * 0.95 + lump * 0.4 + 0.02;',
'  return clamp((c - (1.0 - uCover) * 0.8 - 0.35) * 2.4, 0.0, 1.0) * shape * 0.9; }',
/* ATMOSPHERIC SCATTERING (user 2026-11-23, for clear day): single scattering through a real atmosphere -- Rayleigh (air: blue
   scatters most) and Mie (haze: a bright forward glow around the sun) -- marched from the ground to space, each step lit by sunlight
   that has itself crossed the air. Deep blue overhead, paler toward the horizon, reddening on its own as the sun gets low */
'const float RE = 6360.0, RA = 6420.0, HR = 7.994, HM = 1.2, BM = 3.5e-3;   /* clean air: the textbook 21e-3 haze read as a milky, polluted day */ const vec3 BR = vec3(5.8e-3, 13.5e-3, 33.1e-3), BO = vec3(0.65e-3, 1.881e-3, 0.085e-3);   /* BO: ozone absorbs orange -- without it the sky turns greenish, worst near sunset */',
'vec2 rsi(vec3 o, vec3 d, float r){ float b = dot(o, d), c = dot(o, o) - r * r, h = b * b - c; if (h < 0.0) return vec2(1e9, -1e9); h = sqrt(h); return vec2(-b - h, -b + h); }',
'vec3 trans(vec3 p, vec3 L){ vec2 eh = rsi(p, L, RE); if (eh.x > 0.0 && eh.x < 1e8) return vec3(0.0);   /* the Earth\u2019s shadow: after sunset the low air is unlit, the high air still lit -- twilight */\n' +
'  float ln = rsi(p, L, RA).y, ds = ln / 8.0, oR = 0.0, oM = 0.0; for (int j = 0; j < 8; j++){ float hh = length(p + L * (ds * (float(j) + 0.5))) - RE; oR += exp(-hh / HR) * ds; oM += exp(-hh / HM) * ds; } return exp(-((BR + BO) * oR + BM * 1.1 * oM)); }',
'vec3 atmo(vec3 rd, vec3 L){ vec3 o = vec3(0.0, RE + 0.05, 0.0); float ln = rsi(o, rd, RA).y, ds = ln / 16.0, oR = 0.0, oM = 0.0; vec3 sR = vec3(0.0), sM = vec3(0.0);',
'  for (int i = 0; i < 16; i++){ vec3 p = o + rd * (ds * (float(i) + 0.5)); float hh = length(p) - RE, dR = exp(-hh / HR) * ds, dM = exp(-hh / HM) * ds; oR += dR; oM += dM;',
'    vec3 T = exp(-((BR + BO) * oR + BM * 1.1 * oM)) * trans(p, L); sR += T * dR; sM += T * dM; }',
'  float mu = dot(rd, L), g = 0.76, pR = 3.0 / (16.0 * 3.14159) * (1.0 + mu * mu), pM = 3.0 / (8.0 * 3.14159) * ((1.0 - g * g) * (1.0 + mu * mu)) / ((2.0 + g * g) * pow(1.0 + g * g - 2.0 * g * mu, 1.5));',
'  return 15.0 * (sR * BR * pR + sM * BM * pM); }',
'float hg(float c, float g){ float g2 = g * g; return (1.0 - g2) / (12.566 * pow(1.0 + g2 - 2.0 * g * c, 1.5)); }',
'void main(){',
'  bool DECK = isT(2.0) || isT(5.0), STORM = isT(3.0), FOG = isT(4.0), SNOW = isT(5.0);',
'  vec2 uv = vUV;',
/* A TRUE PERSPECTIVE (user 2026-11-23: "partly cloudy looks a little squished horizontally ... too tall"): the old mapping spread
   83 degrees across the width but as little as 17 up the height, so clouds stood twice too tall. Now a pinhole camera: 80 degrees
   across, the height from the panel's own shape, tilted up so the bottom edge sits 2 degrees above the horizon */
'  float asp = uRes.x / uRes.y, tH = uPit, tV = tH / asp, e0 = uE0 + atan(tV);   /* uE0: the bottom edge above the horizon (lower for the storm, so its base shows) */   /* uPit: tan of half the width\u2019s view, per scene (a longer lens for cumulus and the storm) */',
'  vec3 dc = normalize(vec3((uv.x - 0.5) * 2.0 * tH, (uv.y - 0.5) * 2.0 * tV, 1.0));',
'  float ce = cos(e0), se = sin(e0); vec3 rd = vec3(dc.x, dc.y * ce + dc.z * se, -dc.y * se + dc.z * ce);',
'  vec3 L = normalize(uL); float mu = dot(rd, L);',
/* TWILIGHT for the clear night (user 2026-11-23): only the light of the sky after sunset, from the same scattering as the day,
   added over the night photo (the canvas is screen-blended); black = no change, so it fades out by itself as the sun sinks */
'  if (uTwi > 0.5){ vec3 c = atmo(rd, L) * 9.0;',
'    float se = max(rd.y, 0.02), X = 1.0 / (se + 0.025 * exp(-11.0 * se)); c += vec3(0.0016, 0.002, 0.003) * min(X, 12.0);   /* the horizon is brighter at night: more air glowing and scattering */',
'    c = 1.0 - exp(-c * 1.4); c = pow(c, vec3(1.0 / 2.2)); o = vec4(c, 1.0); return; }',
/* the sky behind */
'  vec3 skyN = mix(vec3(0.03, 0.042, 0.075), vec3(0.01, 0.015, 0.035), uv.y) + vec3(0.08, 0.05, 0.025) * uGlow * pow(1.0 - uv.y, 3.0);',
'  vec3 skyD = DECK ? (SNOW ? mix(vec3(0.62, 0.64, 0.68), vec3(0.50, 0.53, 0.58), uv.y) : mix(vec3(0.46, 0.49, 0.54), vec3(0.36, 0.39, 0.45), uv.y))',
'           : STORM ? mix(vec3(0.36, 0.42, 0.50), vec3(0.14, 0.22, 0.36), uv.y) : mix(vec3(0.68, 0.78, 0.90), vec3(0.30, 0.48, 0.78), uv.y);',
'  vec3 sky = mix(skyD, skyN, uNight) + vec3(0.55, 0.6, 0.8) * uFlash * 0.08;',
'  vec3 Lc = mix(vec3(1.0, 0.97, 0.92) * 2.6, vec3(0.62, 0.70, 0.85) * 0.55, uNight);',
/* NO MOON OR SUN IN THE SKY (user 2026-11-23: "our photos should not have a moon, we already feature the moon in a predictable spot on
   the page"): the page draws its own moon and sun; here they only light the clouds. A faint broad brightening toward the sun by day stays */
'  sky += (DECK ? 0.0 : 1.0) * (1.0 - uNight) * Lc * pow(max(mu, 0.0), 12.0) * 0.06;',
'  bool AT = uAtmo > 0.5 && uNight < 0.5; vec3 hzA = vec3(0.0);',
'  if (AT){ sky = atmo(rd, L); Lc = 3.0 * trans(vec3(0.0, RE + 1.8, 0.0), L); hzA = atmo(normalize(vec3(rd.x, 0.03, rd.z)), L); }   /* the sky, the sunlight that reaches the clouds, and the haze, all from the same air */',
/* where to march */
'  float t0, t1; int N;',
'  if (STORM){ vec2 rx = rd.xz; float l2 = dot(rx, rx), tc = dot(SC.xz, rx) / l2, hw = 40.0 / sqrt(l2); t0 = max(0.05, tc - hw); t1 = min(tc + hw, 15.5 / rd.y); N = 80; }',
'  else if (FOG){ t0 = 0.0; t1 = min(uB1 / rd.y, 5.0); N = 40; }',
'  else if (isT(6.0)){ t0 = 0.0; t1 = 0.0; N = 0; }   /* clear: no clouds at all */',
'  else { float lo = uB0 - 0.3 * (uB1 - uB0); t0 = max(lo, 0.05) / rd.y; t1 = uB1 / rd.y; t1 = t0 + min(t1 - t0, DECK ? 9.0 : 14.0); N = DECK ? 36 : 48; }',
'  float len = max(t1 - t0, 0.0), dt = len / float(N);',
'  float jit = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453 + uFrame * 0.618034);',
'  float T = 1.0; vec3 C = vec3(0.0);',
'  vec3 glowC = (SNOW ? vec3(1.0, 0.76, 0.64) : vec3(1.0, 0.74, 0.52))   /* a clean warm glow: the deeper orange read as mud-brown at night */ * (FOG ? 0.32 : DECK ? 0.2 : 0.07) * uGlow * uNight;   /* fog and low decks catch the city light; snow reflects it pinker */',
'  vec3 ambTop = STORM ? mix(vec3(0.42, 0.47, 0.56), vec3(0.03, 0.045, 0.08), uNight) : mix(DECK ? (SNOW ? vec3(0.50, 0.52, 0.56) : vec3(0.30, 0.32, 0.36)) : FOG ? vec3(0.62, 0.66, 0.72) : vec3(0.55, 0.62, 0.75), vec3(0.03, 0.045, 0.08), uNight);',
'  float dk = uCover > 0.97 && isT(2.0) ? 0.7 : 1.0;   /* heavy rain: the thickest, darkest deck */',
'  vec3 ambBot = STORM ? mix(vec3(0.09, 0.10, 0.13), vec3(0.008, 0.01, 0.016), uNight) + glowC : mix(DECK ? (SNOW ? vec3(0.36, 0.37, 0.40) : vec3(0.17, 0.18, 0.21)) : FOG ? vec3(0.50, 0.52, 0.56) : vec3(0.30, 0.33, 0.40), vec3(0.012, 0.015, 0.024), uNight) + glowC;',
'  float ls = STORM ? 0.3 : FOG ? 0.06 : isT(1.0) ? 0.09 : DECK ? 0.35 : 0.12, sg = STORM ? 7.0 : FOG ? 3.2 : DECK ? 16.0 : 12.0;',
'  if (len > 0.0) for (int i = 0; i < 80; i++){ if (i >= N) break;',
'    float t = t0 + (float(i) + jit) * dt; vec3 p = rd * t; float d = dens(p, 5); if (d < 0.003) continue;',
'    float od = 0.0; for (int j = 1; j <= 3; j++){ od += dens(p + L * (ls * float(j * j)), 2); }',
'    float sig = sg * d, powder = 1.0 - exp(-3.0 * d);',
'    float hh = STORM ? clamp((p.y - 1.0) / 10.0, 0.0, 1.0) : FOG ? 0.5 : clamp((p.y - uB0) / (uB1 - uB0), 0.0, 1.0);',
'    vec3 ms = vec3(0.0); float aa = 1.0, bb = 1.0, cc = 1.0; for (int k = 0; k < 3; k++){ ms += aa * Lc * mix(hg(mu * cc, 0.6), hg(mu * cc, -0.25), 0.3) * exp(-od * 2.2 * bb); aa *= 0.55; bb *= 0.45; cc *= 0.6; }',
'    float thick = DECK ? (0.35 + 0.95 * exp(-od * 1.6)) : (0.55 + 0.45 * exp(-od * 0.8));',
'    float scud = (DECK && p.y < uB0) ? 0.6 : 1.0;',
'    vec3 S = dk * (ms * powder * mix(6.0, 2.6, uNight) * (DECK ? 0.35 : FOG ? 0.45 : 1.0) + mix(ambBot, ambTop, hh) * thick) * scud;',
'    if (STORM) S += vec3(0.75, 0.82, 1.0) * uFlash * 9.0 * exp(-length(p - uFP) * 0.55);   /* lightning lights the cloud from inside */',
'    float a = exp(-sig * dt); C += T * (1.0 - a) * S; T *= a; if (T < 0.02) break; }',
'  if (!STORM && !FOG && len > 0.0 && t1 - t0 < (uB1 / rd.y - t0) - 0.01 && !isT(1.0)) T *= 0.35;',
/* haze toward the horizon */
'  float fog = 1.0 - exp(-max(t0, 0.0) * (SNOW ? 0.2 : DECK ? 0.16 : STORM ? 0.006 : 0.045));   /* a storm 60 km off is seen through clean air: keep its contrast */',
'  vec3 hz = mix(SNOW ? vec3(0.70, 0.72, 0.76) : DECK ? vec3(0.40, 0.43, 0.48) : vec3(0.58, 0.63, 0.70), vec3(0.035, 0.042, 0.058) + vec3(0.05, 0.03, 0.015) * uGlow, uNight);',
'  if (AT) hz = hzA;',
'  vec3 col = C + T * sky; col = mix(col, hz, fog * (AT ? 0.6 : 0.85));',
'  col = 1.0 - exp(-col * mix(1.35, 2.4, uNight)); col = pow(col, vec3(1.0 / 2.2));',
'  if (AT){ float lu = dot(col, vec3(0.299, 0.587, 0.114)); col = clamp(mix(vec3(lu), col, 1.45), 0.0, 1.0);',
'    if (uPalK > 0.5){ float y = 1.0 - uv.y; vec3 pal = y < 0.42 ? mix(uP0, uP1, y / 0.42) : y < 0.72 ? mix(uP1, uP2, (y - 0.42) / 0.3) : mix(uP2, uP3, (y - 0.72) / 0.28);',
'      col = mix(col, pal + max(col - vec3(lu), 0.0) * 0.6, 0.78 * T); } }   /* PALETTE: the dashboard\u2019s colors in the open sky, the physics\u2019 glow kept */   /* beauty over textbook: the physics gives the shape of the sky, the grade gives it the color */',
'  o = vec4(col, 1.0); }'
].join('\n');
var FSP = ['#version 300 es', 'precision highp float;', 'in vec2 vUV; out vec4 o;', 'uniform vec2 uRes; uniform float uTime, uKind, uNight, uWind; uniform vec4 uBolt;   /* x, top y (0..1 of the panel), strength, seed */\n' +
'uniform vec3 uMask;   /* storms: precipitation only between x0 and x1 (0..1), below y; z<0 = everywhere */',
'bool K(float k){ return abs(uKind - k) < 0.5; }',
'float h21(vec2 p){ p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }',
'float n1(float x, float sd){ float i = floor(x), f = fract(x); return mix(h21(vec2(i, sd)), h21(vec2(i + 1.0, sd)), f); }   /* piecewise straight: jagged */',
'float bolt(vec2 u, float x0, float y0, float sd, float w){ if (u.y > y0) return 0.0; float k = (y0 - u.y) / max(y0, 0.01);',
'  float x = x0 + (n1(u.y * 14.0, sd) - 0.5) * 0.05 + (n1(u.y * 45.0, sd + 3.0) - 0.5) * 0.018 + k * (n1(sd, 9.0) - 0.5) * 0.05;',
'  float d = abs(u.x - x) * uRes.x / uRes.y; return smoothstep(w, 0.0, d) + 0.35 * smoothstep(w * 7.0, 0.0, d); }   /* a bright core and its glow */',
'void main(){ vec2 fc = gl_FragCoord.xy / uRes.y; float acc = 0.0, accS = 0.0; bool SN = K(1.0), DZ = K(3.0), SL = K(4.0), HV = K(5.0), FZ = K(6.0), HL = K(7.0);',
'  int NL = SN ? 7 : SL ? 6 : DZ ? 6 : HL ? 4 : 5;',
'  for (int L = 0; L < 7; L++){ if (L >= NL) break; float fl = float(L), near = 1.0 - fl / float(NL);',
'    float sc = HL ? 6.0 + fl * 4.0 : SN ? 5.0 + fl * 4.5 : DZ ? 16.0 + fl * 9.0 : HV ? 7.0 + fl * 5.0 : 9.0 + fl * 7.0;   /* cells per screen height: far layers smaller */',
'    bool pel = SL && mod(fl, 2.0) < 0.5;                                   /* sleet: ice pellets in alternate layers, rain in the others */',
'    float v = HL ? 1.6 + 1.6 * near : SN ? 0.10 + 0.20 * near : pel ? 0.55 + 0.6 * near : DZ ? 0.45 + 0.5 * near : 1.1 + 1.4 * near;   /* fall speed, screen heights per second */',
'    float dr = uWind * (SN ? 0.08 + 0.1 * near : 0.25);',
'    vec2 q = fc * sc; q.y += uTime * v * sc; q.x += uTime * dr * sc;',
'    if (!SN && !pel) q.x += q.y * (HL ? 0.06 : DZ ? 0.1 : HV ? 0.24 : 0.18);              /* rain slants with the wind */',
'    vec2 id = floor(q), f = fract(q) - 0.5; float h = h21(id + fl * 19.7);',
'    if (h > (HL ? 0.22 : SN ? 0.55 + 0.25 * (1.0 - near) : DZ ? 0.6 : HV ? 0.62 : pel ? 0.4 : 0.35)) continue;',
'    vec2 off = (vec2(h21(id + 3.1), h21(id + 7.7)) - 0.5) * 0.6;',
'    if (SN) off.x += sin(uTime * (0.8 + h) + h * 6.283) * 0.16;            /* each flake sways */',
'    vec2 d = f - off; float a;',
'    if (SN){ float r = (0.05 + 0.07 * h21(id + 1.3)) * (0.7 + 0.5 * near); a = smoothstep(r, r * (0.2 + 0.5 * near), length(d)); a *= 0.45 + 0.55 * near; }',
/* HAIL (user 2026-11-23: "fix hail, idk if that should look like rain and sleet"): big white stones, a mix of sizes, sparse, falling
   faster than rain -- each a bright core with a short streak above it (motion), across the whole view: it is hailing here */
'    else if (HL){ float r = (0.045 + 0.05 * h21(id + 1.3)) * (0.6 + 0.6 * near);',
'      float core = smoothstep(r, r * 0.55, length(d));                                              /* a round stone, not a teardrop */',
'      float st = smoothstep(r * 0.32, 0.0, abs(d.x)) * smoothstep(r * 5.0, r, d.y) * step(0.0, d.y) * 0.22;   /* a faint thin streak above it: its speed */',
'      a = max(core, st) * (0.55 + 0.45 * near); accS += a; a = 0.0; }',
'    else if (pel){ float r = (0.03 + 0.03 * h21(id + 1.3)) * (0.8 + 0.4 * near); a = smoothstep(r, r * 0.5, length(vec2(d.x, d.y * 0.7))) * (0.5 + 0.45 * near); accS += a; a = 0.0; }   /* small hard pellets */',
'    else if (DZ){ float k = length(vec2(d.x * 10.0, d.y * 2.4)); a = smoothstep(0.42, 0.0, k) * (0.2 + 0.32 * near); }   /* drizzle: fine short streaks */',
'    else { float k = length(vec2(d.x * (HV ? 11.0 : 14.0), d.y * (HV ? 0.7 : 0.9))); a = smoothstep(0.42, 0.0, k) * (HV ? 0.26 + 0.38 * near : 0.18 + 0.3 * near); }',
'    acc += a; }',
'  acc = clamp(acc, 0.0, 1.0); accS = clamp(accS, 0.0, 1.0);',
'  if (uMask.z > 0.0){ float m = smoothstep(uMask.x - 0.04, uMask.x + 0.03, vUV.x) * smoothstep(uMask.y + 0.04, uMask.y - 0.03, vUV.x) * smoothstep(uMask.z + 0.02, uMask.z - 0.05, vUV.y); acc *= m; accS *= m; }   /* rain falls only under the storm */',
'  vec3 c = SN ? mix(vec3(0.97, 0.98, 1.0), vec3(0.78, 0.80, 0.86), uNight) : FZ ? mix(vec3(0.86, 0.94, 1.0), vec3(0.62, 0.70, 0.80), uNight) : mix(vec3(0.85, 0.88, 0.93), vec3(0.55, 0.58, 0.66), uNight);   /* freezing rain: an icy blue-white cast */',
'  vec3 cs = HL ? mix(vec3(0.97, 0.98, 1.0), vec3(0.80, 0.83, 0.90), uNight) : mix(vec3(0.93, 0.96, 1.0), vec3(0.72, 0.76, 0.84), uNight);',
'  float B = uBolt.z > 0.0 ? clamp(bolt(vUV, uBolt.x, uBolt.y, uBolt.w, 0.0022) + 0.6 * bolt(vUV, uBolt.x, uBolt.y * 0.8, uBolt.w + 5.0, 0.0014) * step(0.5, fract(uBolt.w * 0.37)), 0.0, 1.0) * uBolt.z : 0.0;   /* sometimes a branch */',
'  vec3 cb = vec3(0.86, 0.9, 1.0);',
'  float A = clamp(acc + accS + B, 0.0, 1.0); o = vec4(c * acc + cs * accS + cb * B, A); }'].join('\n');
function mk(g, vs, fs){ var sh = function(t, s){ var x = g.createShader(t); g.shaderSource(x, s); g.compileShader(x); if (!g.getShaderParameter(x, g.COMPILE_STATUS)) throw new Error(g.getShaderInfoLog(x)); return x; };
  var p = g.createProgram(); g.attachShader(p, sh(g.VERTEX_SHADER, vs)); g.attachShader(p, sh(g.FRAGMENT_SHADER, fs)); g.linkProgram(p); if (!g.getProgramParameter(p, g.LINK_STATUS)) throw new Error(g.getProgramInfoLog(p)); return p; }
var P, PP, U = {}, PU = {}, NT;
function build(){ if (OK || BROKEN) return OK;
  try {
    if (!gl || !gp) throw new Error('no webgl2');
    P = mk(gl, VS, FS); PP = mk(gp, VS, FSP);
    var NS = 64, vol = new Uint8Array(NS * NS * NS);
    (function(){ function lat(o){ var a = new Float32Array(o * o * o); for (var i = 0; i < a.length; i++) a[i] = Math.random(); return a; }
  var oct = [[4, .5], [8, .27], [16, .15], [32, .08]].map(function(q){ return { n: q[0], w: q[1], g: lat(q[0]) }; });
  function smp(L, x, y, z){ var n = L.n, fx = x * n, fy = y * n, fz = z * n, x0 = Math.floor(fx), y0 = Math.floor(fy), z0 = Math.floor(fz), tx = fx - x0, ty = fy - y0, tz = fz - z0;
    tx = tx * tx * (3 - 2 * tx); ty = ty * ty * (3 - 2 * ty); tz = tz * tz * (3 - 2 * tz); var g = L.g, I = function(a, b, c){ return g[((a % n + n) % n) + ((b % n + n) % n) * n + ((c % n + n) % n) * n * n]; };
    var c00 = I(x0, y0, z0) + (I(x0 + 1, y0, z0) - I(x0, y0, z0)) * tx, c10 = I(x0, y0 + 1, z0) + (I(x0 + 1, y0 + 1, z0) - I(x0, y0 + 1, z0)) * tx,
        c01 = I(x0, y0, z0 + 1) + (I(x0 + 1, y0, z0 + 1) - I(x0, y0, z0 + 1)) * tx, c11 = I(x0, y0 + 1, z0 + 1) + (I(x0 + 1, y0 + 1, z0 + 1) - I(x0, y0 + 1, z0 + 1)) * tx;
    var c0 = c00 + (c10 - c00) * ty, c1 = c01 + (c11 - c01) * ty; return c0 + (c1 - c0) * tz; }
  for (var z = 0; z < NS; z++) for (var y = 0; y < NS; y++) for (var x = 0; x < NS; x++){ var s = 0; oct.forEach(function(L){ s += L.w * smp(L, x / NS, y / NS, z / NS); }); vol[x + y * NS + z * NS * NS] = Math.max(0, Math.min(255, Math.round(s * 255))); } })();
    NT = gl.createTexture(); gl.bindTexture(gl.TEXTURE_3D, NT); gl.pixelStorei(gl.UNPACK_ALIGNMENT, 1); gl.texImage3D(gl.TEXTURE_3D, 0, gl.R8, NS, NS, NS, 0, gl.RED, gl.UNSIGNED_BYTE, vol);
    ['TEXTURE_WRAP_S', 'TEXTURE_WRAP_T', 'TEXTURE_WRAP_R'].forEach(function(k){ gl.texParameteri(gl.TEXTURE_3D, gl[k], gl.REPEAT); });
    gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MIN_FILTER, gl.LINEAR); gl.texParameteri(gl.TEXTURE_3D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    ['uRes', 'uTime', 'uCover', 'uGlow', 'uNight', 'uL', 'uN', 'uB0', 'uB1', 'uType', 'uPit', 'uFrame', 'uFlash', 'uFP', 'uE0', 'uAtmo', 'uTwi', 'uHail', 'uPalK', 'uP0', 'uP1', 'uP2', 'uP3'].forEach(function(k){ U[k] = gl.getUniformLocation(P, k); });
    ['uRes', 'uTime', 'uKind', 'uNight', 'uWind', 'uBolt', 'uMask'].forEach(function(k){ PU[k] = gp.getUniformLocation(PP, k); });
    OK = true;
  } catch(e){ BROKEN = true; OK = false; try { console.warn('[sky3d] off:', e && e.message); } catch(_){} }
  return OK; }
/* the recipes, by the hero's state (day / night), as judged in the lab */
var R = {
  'clear-day':   [{ type: 6, B0: 1.2, B1: 3.1, cover: 0, glow: 0, az: -0.5, px: 0, atmo: 1 }, null],
  'mainly':      [{ type: 1, B0: 1.2, B1: 3.1, cover: .05, glow: 0, az: -0.5, px: 0, atmo: 1 }, null],
  'clear-night': [null, { type: 6, B0: 1.2, B1: 3.1, cover: 0, glow: 0, az: 0.3, px: 0, twi: 1 }],
  'overcast':    [{ type: 0, B0: 1.1, B1: 2.4, cover: .86, glow: 0, az: -0.45, px: 0 }, { type: 0, B0: 1.1, B1: 2.4, cover: .8, glow: .25, el: 34, az: 0.42, px: 0 }],
  'partly':      [{ type: 1, B0: 1.2, B1: 3.1, cover: .33, glow: 0, az: -0.55, px: 0 }, { type: 1, B0: 1.2, B1: 3.1, cover: .33, glow: .3, el: 38, az: 0.38, px: 0 }],
  'fog':         [{ type: 4, B0: 0, B1: 0.24, cover: 1, glow: 0, az: -0.3, px: 0 }, { type: 4, B0: 0, B1: 0.24, cover: 1, glow: .5, el: 24, az: 0.35, px: 0 }],
  'drizzle':     [{ type: 2, B0: 0.45, B1: 1.9, cover: .8, glow: 0, az: -0.4, px: 3 }, { type: 2, B0: 0.45, B1: 1.9, cover: .8, glow: .35, el: 34, az: 0.42, px: 3 }],
  'rain':        [{ type: 2, B0: 0.6, B1: 3.4, cover: .92, glow: 0, az: -0.4, px: 2 }, { type: 2, B0: 0.6, B1: 3.4, cover: .92, glow: .35, el: 34, az: 0.42, px: 2 }],
  'rain-heavy':  [{ type: 2, B0: 0.4, B1: 4.0, cover: 1, glow: 0, az: -0.4, px: 5 }, { type: 2, B0: 0.4, B1: 4.0, cover: 1, glow: .4, el: 34, az: 0.42, px: 5 }],
  'freezing':    [{ type: 2, B0: 0.5, B1: 3.2, cover: .95, glow: 0, az: -0.4, px: 6 }, { type: 2, B0: 0.5, B1: 3.2, cover: .95, glow: .35, el: 34, az: 0.42, px: 6 }],
  'snow':        [{ type: 5, B0: 0.7, B1: 3.2, cover: .9, glow: 0, az: -0.4, px: 1 }, { type: 5, B0: 0.7, B1: 3.2, cover: .9, glow: .3, el: 30, az: 0.4, px: 1 }],
  'sleet':       [{ type: 5, B0: 0.6, B1: 3.0, cover: .92, glow: 0, az: -0.4, px: 4 }, { type: 5, B0: 0.6, B1: 3.0, cover: .92, glow: .3, el: 30, az: 0.4, px: 4 }],
  'storm':       [{ type: 3, B0: 1, B1: 12, cover: 1, glow: 0, az: -0.75, px: 2 }, { type: 3, B0: 1, B1: 12, cover: 1, glow: .3, el: 30, az: -0.6, px: 2 }],
  'storm-hail':  [{ type: 3, B0: 1, B1: 12, cover: 1, glow: 0, az: -0.7, px: 7, hail: 1 }, { type: 3, B0: 1, B1: 12, cover: 1, glow: .3, el: 30, az: -0.6, px: 7, hail: 1 }]
};
var S = { sc: null, host: null, t: 40, frame: 0, fresh: 1, auto: 1, sunAlt: 35, night: 0, pal: null, seen: true, fps: 0, key: '' }, raf = 0, last = 0, fr = 0, f0 = 0;
try { new IntersectionObserver(function(es){ S.seen = es[es.length - 1].isIntersecting; if (S.seen) kick(); }).observe(cv); } catch(e){}
document.addEventListener('visibilitychange', function(){ if (!document.hidden) kick(); });
function kick(){ if (!raf && S.sc) raf = requestAnimationFrame(frame); }
function hx(h){ h = String(h || '#000000'); return [parseInt(h.slice(1, 3), 16) / 255, parseInt(h.slice(3, 5), 16) / 255, parseInt(h.slice(5, 7), 16) / 255]; }
function extinction(){ var h = 160, g = ext.getContext('2d'); ext.width = 1; ext.height = h; var tH = 0.84, tV = tH / ((ext.clientWidth || 700) / (ext.clientHeight || 275)), e0 = 0.035 + Math.atan(tV);
  for (var y = 0; y < h; y++){ var v = 1 - (y + 0.5) / h, el = e0 + Math.atan((v - 0.5) * 2 * tV), se = Math.max(0.02, Math.sin(el)), X = 1 / (se + 0.025 * Math.exp(-11 * se));
    var c = [0.14, 0.22, 0.36].map(function(k){ return Math.round(255 * (0.5 + 0.5 * Math.pow(10, -0.4 * k * (Math.min(X, 8) - 1)))); }); g.fillStyle = 'rgb(' + c.join(',') + ')'; g.fillRect(0, y, 1, 1); } }
function frame(now){
  raf = 0; if (!S.sc) return;
  /* the hero rebuilds its box (the clear-day builder waits for layout, then rewrites it): put the layers back */
  if (!cv.isConnected || ((S.sc.px || S.sc.type === 3) && (!px.isConnected || px.previousSibling !== S.host))){ var h2 = (S.host && S.host.isConnected) ? S.host : document.getElementById('hero-wx'); if (!h2) return; S.host = h2; attach(); }
  if (document.hidden || !S.seen) return;                                   /* asleep while hidden or scrolled away */
  raf = requestAnimationFrame(frame);
  if (now - last < 32) return; var dt = Math.min(100, now - last); last = now;   /* 30 fps */
  if (!REDUCED) S.t += dt / 1000;
  var sc = S.sc, cw = cv.clientWidth || 1, ch = cv.clientHeight || 1;
  /* the hero is big: the cloud layer renders at a capped resolution and is scaled up (clouds are soft); phones lower */
  var k = Math.min(PHONE ? 0.35 : 0.5, (PHONE ? 380 : 620) / cw) * S.auto, w = Math.max(64, Math.round(cw * k)), h = Math.max(24, Math.round(ch * k));
  var twiOff = sc.twi && S.sunAlt < -18.5;                                  /* full night: no twilight left to draw */
  if (cv.width !== w || cv.height !== h){ cv.width = w; cv.height = h; S.fresh = 1; }
  S.frame++;
  if (!twiOff){
    gl.viewport(0, 0, w, h); gl.useProgram(P);
    var elD = sc.twi ? Math.max(-18, Math.min(0, S.sunAlt)) : S.night ? (sc.el || 34) : Math.max(3, S.sunAlt), el = elD * Math.PI / 180, az = sc.az * (S.eve && !S.night ? -1 : 1);
    gl.uniform2f(U.uRes, w, h); gl.uniform1f(U.uTime, S.t); gl.uniform1f(U.uCover, sc.cover); gl.uniform1f(U.uGlow, sc.glow); gl.uniform1f(U.uNight, sc.twi ? 1 : S.night ? 1 : 0);
    gl.uniform1f(U.uB0, sc.B0); gl.uniform1f(U.uB1, sc.B1); gl.uniform1f(U.uType, sc.type); gl.uniform1f(U.uPit, sc.type === 1 ? 0.6 : sc.type === 3 ? 0.66 : 0.84); gl.uniform1f(U.uE0, sc.type === 3 ? 0.009 : 0.035);
    gl.uniform1f(U.uAtmo, sc.atmo ? 1 : 0); gl.uniform1f(U.uTwi, sc.twi ? 1 : 0); gl.uniform1f(U.uHail, sc.hail ? 1 : 0);
    var pal = sc.atmo && S.pal && S.pal.length === 4; gl.uniform1f(U.uPalK, pal ? 1 : 0);
    if (pal){ gl.uniform3fv(U.uP0, hx(S.pal[0])); gl.uniform3fv(U.uP1, hx(S.pal[1])); gl.uniform3fv(U.uP2, hx(S.pal[2])); gl.uniform3fv(U.uP3, hx(S.pal[3])); }
    if (sc.type === 3){ if (!S.fl || S.t > S.fl.next){ S.fl = { seed: Math.random() * 100, t0: S.t, next: S.t + 3 + Math.random() * 6, p: [-7 + (Math.random() - .5) * 8, 2.5 + Math.random() * 7, 40 + (Math.random() - .5) * 8] }; }
      var fa = S.t - S.fl.t0, fv = fa < 0.45 ? Math.max(0, 1 - fa / 0.45) * (0.6 + 0.4 * Math.abs(Math.sin(fa * 47))) : 0; gl.uniform1f(U.uFlash, fv); S.flv = fv; gl.uniform3f(U.uFP, S.fl.p[0], S.fl.p[1], S.fl.p[2]); S.fast = fv > 0 ? 6 : Math.max(0, (S.fast || 0) - 1); }
    else { gl.uniform1f(U.uFlash, 0); S.flv = 0; }
    gl.uniform1f(U.uFrame, S.frame % 64);
    if (S.fresh){ gl.disable(gl.BLEND); S.fresh = 0; } else { gl.enable(gl.BLEND); gl.blendColor(0, 0, 0, S.fast > 0 ? 0.6 : 0.3); gl.blendFunc(gl.CONSTANT_ALPHA, gl.ONE_MINUS_CONSTANT_ALPHA); }
    gl.uniform3f(U.uL, Math.sin(az) * Math.cos(el), Math.sin(el), Math.cos(az) * Math.cos(el)); gl.activeTexture(gl.TEXTURE0); gl.bindTexture(gl.TEXTURE_3D, NT); gl.uniform1i(U.uN, 0); gl.drawArrays(gl.TRIANGLES, 0, 3);
  }
  cv.style.visibility = twiOff ? 'hidden' : '';
  /* LEGIBILITY: the hero's readout is white text over the sky; bright day decks and fog are dimmed a little (a CSS filter on the
     canvas, so the shaders stay the lab's) */
  var dim = (!S.night && !sc.atmo && !sc.twi) ? (sc.type === 4 ? 0.72 : 0.85) : 1, fl = dim < 1 ? 'brightness(' + dim + ')' : ''; if (cv.style.filter !== fl) cv.style.filter = fl;
  precip();
  fr++; if (now - f0 > 1000){ S.fps = fr; S.slow = fr < 18 ? (S.slow || 0) + 1 : 0; if (S.slow >= 3 && S.auto > 0.5){ S.auto *= 0.85; S.slow = 0; } else if (fr > 28 && S.auto < 1) S.auto = Math.min(1, S.auto * 1.1); fr = 0; f0 = now; }
}
function precip(){ var sc = S.sc, k = sc.px || 0;
  if (!k && sc.type !== 3){ px.style.display = 'none'; return; } px.style.display = '';
  var dpr = Math.min(1.5, window.devicePixelRatio || 1), w = Math.round((px.clientWidth || 1) * dpr), h = Math.round((px.clientHeight || 1) * dpr); if (px.width !== w || px.height !== h){ px.width = w; px.height = h; }
  gp.viewport(0, 0, w, h); gp.clearColor(0, 0, 0, 0); gp.clear(gp.COLOR_BUFFER_BIT); gp.useProgram(PP);
  gp.uniform2f(PU.uRes, w, h); gp.uniform1f(PU.uTime, S.t); gp.uniform1f(PU.uKind, k); gp.uniform1f(PU.uNight, S.night); gp.uniform1f(PU.uWind, 0.6);
  place(); var Hh = (S.host && S.host.offsetHeight) || px.clientHeight || 1, Ht = Hh + EXT, toC = function(yh){ return (EXT + yh * Hh) / Ht; };   /* hero-frame height fraction -> this taller canvas */
  var tH = 0.66, asp = (px.clientWidth || 1) / Hh, tV = tH / asp, e0 = 0.009 + Math.atan(tV), sxp = function(X, Z){ return 0.5 + (X / Z) / (2 * tH); }, syp = function(Y, Z){ return toC(0.5 + Math.tan(Math.atan2(Y, Z) - e0) / (2 * tV)); };
  if (sc.type === 3 && k !== 7) gp.uniform3f(PU.uMask, sxp(-33, 40), sxp(-1, 40), syp(2.0, 40)); else gp.uniform3f(PU.uMask, 0, 0, -1);
  var bz = [0, 0, 0, 0]; if (sc.type === 3 && S.fl && S.flv > 0.05){ var X = S.fl.p[0] + 2, Z = S.fl.p[2], el = Math.atan2(3.5, Z) - e0; bz = [0.5 + (X / Z) / (2 * tH), toC(Math.max(0.05, 0.5 + Math.tan(el) / (2 * tV))), S.flv, S.fl.seed]; }
  gp.uniform4f(PU.uBolt, bz[0], bz[1], bz[2], bz[3]); gp.drawArrays(gp.TRIANGLES, 0, 3); }
function attach(){ var host = S.host, sc = S.sc; if (!host || !sc) return;
  /* the layers: clouds at the bottom of the hero (the clear night: screen-blended over its photo, extinction under it);
     precipitation over the hero's SVG */
  var svg = host.querySelector(':scope > svg');
  if (sc.twi){
    cv.style.mixBlendMode = 'screen';
    if (svg){ if (ext.parentNode !== host || ext.previousSibling !== svg) host.insertBefore(ext, svg.nextSibling); if (cv.parentNode !== host || cv.previousSibling !== ext) host.insertBefore(cv, ext.nextSibling); }
    else { if (cv.parentNode !== host) host.appendChild(cv); }
    requestAnimationFrame(extinction);
  } else {
    cv.style.mixBlendMode = ''; if (ext.parentNode) ext.parentNode.removeChild(ext);
    if (cv.parentNode !== host || host.firstChild !== cv) host.insertBefore(cv, host.firstChild);
  }
  /* PRECIPITATION OUTSIDE THE MIRROR (user 2026-11-23: the hero's -webkit-box-reflect reflected the rain, which then fell upward): it
     sits just after the hero box, over it, and runs EXT px below its edge with a fade -- the rain falls on into the hours */
  var par = host.parentNode;
  if ((sc.px || sc.type === 3) && par){ if (px.parentNode !== par || px.previousSibling !== host) par.insertBefore(px, host.nextSibling); place(); }
  else if (px.parentNode) px.parentNode.removeChild(px);
}
var EXT = 120;   /* = the mirror's fade (FADE in index.html's _bvHorizonMask) */
function place(){ var host = S.host; if (!host) return; var t = host.offsetTop, h = host.offsetHeight; if (S.pt === t && S.ph === h) return; S.pt = t; S.ph = h;
  var m = 'linear-gradient(to bottom,#000 0,#000 ' + h + 'px,transparent ' + (h + EXT) + 'px)';
  px.style.cssText = 'position:absolute;left:0;right:0;top:' + t + 'px;height:' + (h + EXT) + 'px;width:100%;pointer-events:none;z-index:0;-webkit-mask-image:' + m + ';mask-image:' + m + ';'; }
function stop(){ S.sc = null; S.key = ''; [cv, px, ext].forEach(function(c){ if (c.parentNode) c.parentNode.removeChild(c); }); if (raf){ cancelAnimationFrame(raf); raf = 0; } }
function sync(host, o){
  if (!host || !o || !build()){ stop(); return false; }
  var st = o.state, key = st === 'clear-day' && o.code === 1 ? 'mainly' : st, pair = R[key];
  var sc = pair && pair[o.night ? 1 : 0];
  if (!sc){ stop(); return false; }
  var k2 = key + '|' + (o.night ? 1 : 0);
  if (S.key !== k2){ S.key = k2; S.fresh = 1; S.fl = null; }
  S.sc = sc; S.host = host; S.sunAlt = +o.sunAlt; if (!isFinite(S.sunAlt)) S.sunAlt = o.night ? -20 : 35; S.eve = !!o.eve; S.night = o.night ? 1 : 0; S.pal = o.pal || null;
  attach();
  kick(); return true;
}
window.bvSky3D = { ok: function(){ return build(); }, sync: sync, stop: stop, stats: function(){ return { fps: S.fps, w: cv.width, h: cv.height, scene: S.key, auto: S.auto }; } };
/* this file loads after the page's inline scripts: once it is here, have the hero lay itself out again (full panel, new sky) */
try { if (typeof window._updateHeroWx === 'function' && window._lastWxCode != null) setTimeout(function(){ try { window._updateHeroWx(window._lastWxCode, window._lastWxNight); } catch(e){} }, 0); } catch(e){}
})();

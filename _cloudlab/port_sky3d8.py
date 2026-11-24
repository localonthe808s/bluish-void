"""PORT THE LAB TO THE SITE (2026-11-24): builds ../sky3d8.js from volumetric_lab.html (the master: shaders, scene rows, noise) +
lightning.js (bundled) + sky3d8_tpl.js (the site engine). Run after any lab edit:  python3 _cloudlab/port_sky3d8.py
Then syntax-check (node --check sky3d8.js) and bump ?v= on the script tag in index.html."""
import json, os, re, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
lab = open(os.path.join(HERE, 'volumetric_lab.html')).read()
tpl = open(os.path.join(HERE, 'sky3d8_tpl.js')).read()

def block(start, end_pat):
    a = lab.index(start); b = lab.index(end_pat, a) + len(end_pat); return lab[a:b]

fs2 = block('var FS2 = [', "].join('\\n');")
fsp3 = block('var FSP3 = [', "].join('\\n');")
noise = lab[lab.index('var NS = 64, vol = new Float32Array'):lab.index('var NT = gl.createTexture()')]
def arr(after):
    a = lab.index('[', lab.index(after)); b = lab.index("].join('\\n')", a) + 1; return lab[a:b] + ".join('\\n')"
resolve = arr('gl.attachShader(RSV, sh(gl.FRAGMENT_SHADER, ')
present = arr('gl.attachShader(PRS, sh(gl.FRAGMENT_SHADER, ')
# the scene rows (subtypes + weather) as JSON, evaluated by node
a1 = lab.index("['s-ci-fib'"); b1 = lab.index("].map(function(r){ return { k: r[0], label: 'SUBTYPE", a1)
a2 = lab.index("['s-ns-rn'"); b2 = lab.index("].map(function(r){ return { k: r[0], label: 'SUBTYPE", a2)
js = "console.log(JSON.stringify([" + lab[a1:b1] + "].concat([" + lab[a2:b2] + "])))"
rows = subprocess.run(['node', '-e', js], capture_output=True, text=True, check=True).stdout.strip()
lightning = open(os.path.join(HERE, 'lightning.js')).read()
lightning += '\n' + open(os.path.join(HERE, 'geese.js')).read()   # the geese ride along (flock.js's controller runs them on the v8 skies)

out = (tpl.replace('/*@FS2@*/', fs2).replace('/*@FSP3@*/', fsp3).replace('/*@RESOLVE@*/', resolve).replace('/*@PRESENT@*/', present)
          .replace('/*@ROWS@*/', rows).replace('/*@NOISE@*/', json.dumps(noise)).replace('/*@LIGHTNING@*/', lightning))
for k in ['FS2', 'FSP3', 'RESOLVE', 'PRESENT', 'ROWS', 'NOISE', 'LIGHTNING']: assert '/*@' + k + '@*/' not in out, k
out += r'''
/* THE SWITCH: v8 is THE DEFAULT for everyone, phones included, since 2026-11-24 (user: "go for it"). ?s3d8=0 in the address turns it off
   (v7 again). Where v8 cannot run (no WebGL2), v7 keeps every sky. */
(function(){ var on = !/[?&]s3d8=0/.test(location.search); if (!on || !window.bvSky3D8 || !window.bvSky3D8.ok()) return; var v7 = window.bvSky3D, v8 = window.bvSky3D8; window.bvSky3D7 = v7; v8.early();   /* LAUNCH STEPS 2 + 3: start compiling and building the noise now, in the background */
  window.bvSky3D = { ok: function(){ return v8.ok() || !!(v7 && v7.ok()); },
    sync: function(h, o){ if (v7) v7.stop(); return v8.sync(h, o); },   /* clear nights too, since 11-24 */
    stop: function(){ v8.stop(); if (v7) v7.stop(); }, stats: function(){ return v8.stats(); } };
  try { if (typeof window._updateHeroWx === 'function' && window._lastWxCode != null) setTimeout(function(){ try { window._updateHeroWx(window._lastWxCode, window._lastWxNight); } catch(e){} }, 0); } catch(e){} })();
'''
dst = os.path.join(ROOT, 'sky3d8.js'); open(dst, 'w').write(out)
r = subprocess.run(['node', '--check', dst], capture_output=True, text=True)
print('wrote', dst, len(out), 'bytes;', 'syntax OK' if r.returncode == 0 else 'SYNTAX ERROR\n' + r.stderr[:800])
sys.exit(r.returncode)

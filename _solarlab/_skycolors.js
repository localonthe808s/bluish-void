/* AUTO-EXTRACTED from index.html — the site's atmospheric sky colour engine
   (_SKY_DB altitude-keyed gradients + _tlSkyColors interpolator). */
var window_shim = window;
var SKY_DB = window._SKY_DB = {
          // ═══════════════════════════════════════════════════════════
          // ATMOSPHERIC SKY COLOR DATABASE v2
          // Calibrated from: Rayleigh/Mie scattering physics, real
          // sunset photography color sampling, NOAA twilight definitions,
          // and airmass optical depth calculations.
          //
          // Format: [zenith, upperSky(60°), lowerSky(30°), horizon(0°)]
          // Colors are for CLEAR sky — modifiers blend over these.
          //
          // Key physics:
          //   Airmass = 1/sin(altitude): 38x at 0°, 11x at 5°, 6x at 10°
          //   Rayleigh scattering ∝ λ⁻⁴ → blue scattered 9.4x more than red
          //   At airmass >10 (sa<5°), nearly all blue/violet is removed
          //   from direct beam → horizon turns orange/red
          //   Ozone Chappuis band absorbs orange → blue hour gets bluer
          //   Post-sunset purple: stratospheric aerosols scatter red + blue = purple
          // ═══════════════════════════════════════════════════════════
          
          // ── DEEP NIGHT (sa ≤ -18°) ──
          // Zero scattered sunlight. Airglow only (~0.001 lux).
          '-20': ['#020208','#030310','#040415','#05051a'],
          '-18': ['#030310','#040418','#050520','#060625'],
          
          // ── ASTRONOMICAL TWILIGHT (-18° to -12°) ──
          // Sun illuminates upper stratosphere only. Ozone UV absorption
          // creates subtle deep blue glow at horizon. Stars to mag 6 visible.
          '-16': ['#040414','#060624','#080835','#0c0c42'],
          '-14': ['#050518','#080830','#0c0c45','#121255'],
          '-12': ['#060620','#0a0a3a','#101055','#181865'],
          
          // ── NAUTICAL TWILIGHT (-12° to -6°) ──
          // Horizon line clearly defined. Venus/Jupiter visible.
          // Deep cobalt blue intensifies. First warm glow at -8°.
          '-11': ['#070724','#0c0c42','#141460','#1e1e70'],
          '-10': ['#080828','#0e0e4a','#181868','#242478'],
          '-9':  ['#0a0a30','#121255','#1e1e72','#2a2a80'],
          '-8':  ['#0c0c35','#151560','#24247a','#323288'],
          '-7':  ['#0e0e3a','#181868','#2a2a82','#383890'],
          '-6':  ['#101040','#1c1c70','#30308a','#404098'],
          
          // ── BLUE HOUR (-6° to -2°) ──
          // Ozone Chappuis absorption peak: absorbs orange/red → enriches blue.
          // This is why blue hour is BLUER than regular twilight.
          // Earth shadow (dark band opposite sun) visible rising.
          '-5':  ['#111148','#1e2078','#343892','#44489a'],
          '-4':  ['#131550','#222880','#3a4098','#4a50a0'],
          
          // ── CIVIL TWILIGHT / GOLDEN TRANSITION (-3° to 0°) ──
          // Sun just below horizon. Venus belt (pink band) opposite sun.
          // Horizon glows orange-amber. Zenith transitions from cobalt to indigo.
          '-3':  ['#151858','#283088','#4a4898','#685888'],
          '-2':  ['#182060','#2e3890','#5a5090','#8a6078'],
          '-1':  ['#1a2568','#354098','#704c80','#b46048'],
          '0':   ['#1c2a70','#3a489c','#8a5468','#d87030'],
          
          // ── GOLDEN HOUR: DEEP SUNSET (0° to 3°) ──
          // Airmass 38x→19x. Direct beam is deep orange to red.
          // Zenith: rich cobalt blue (short-wave scattering peak).
          // Upper sky: desaturating blue with violet tinge.
          // Lower sky: peach/salmon (scattered warm light mixing with blue).
          // Horizon: vivid orange-amber to coral flame.
          '1':   ['#1e3078','#4050a0','#a06858','#e07830'],
          '2':   ['#223880','#4858a8','#b07858','#e88838'],
          '3':   ['#284088','#5268b0','#b88860','#e09040'],
          
          // ── GOLDEN HOUR: WARM LIGHT (3° to 6°) ──
          // Airmass 11x→6x. Blue returning to lower sky.
          // Horizon still warm golden. Upper sky brightening.
          // Classic "golden hour" warmth on landscape.
          '4':   ['#2e4890','#5870b5','#a89068','#d89850'],
          '5':   ['#3450a0','#6078b8','#90987a','#c89858'],
          '6':   ['#3858a8','#6880c0','#7a9890','#b09868'],
          
          // ── EARLY DAYTIME (6° to 15°) ──
          // Blue sky establishing rapidly. Warm horizon glow fading.
          // Airmass 6x→4x. Blue saturation increasing each degree.
          '8':   ['#2a60b0','#4880c0','#60a0b8','#88a8a8'],
          '10':  ['#2268b8','#3888c8','#4898c0','#6aa8b8'],
          '12':  ['#1e68bc','#3288ca','#4098c2','#5ca0ba'],
          '15':  ['#1a64c0','#2c80cc','#3890c4','#4a98be'],
          
          // ── FULL DAYTIME (15° to 60°+) ──
          // Pure Rayleigh blue. Zenith deepest. Horizon slightly desaturated
          // due to long optical path (more multiple scattering → whitening).
          // Humidity/aerosols affect horizon whitening (handled by modifiers).
          '20':  ['#1860c2','#2878cc','#3488c8','#4498c4'],
          '25':  ['#165cc5','#2674ce','#3284ca','#4294c6'],
          '30':  ['#1458c8','#2470d0','#3080cc','#3e90c8'],
          '40':  ['#1254ca','#226cd2','#2e7cce','#3c8cca'],
          '50':  ['#1050cc','#2068d4','#2c78d0','#3a88cc'],
          '60':  ['#0e4ece','#1e64d6','#2a74d2','#3884ce']
        };
var _h2r=function(h){return [parseInt(h.slice(1,3),16),parseInt(h.slice(3,5),16),parseInt(h.slice(5,7),16)];};
          var _r2h=function(r,g,b){return '#'+((1<<24)+(Math.round(r)<<16)+(Math.round(g)<<8)+Math.round(b)).toString(16).slice(1);};
          var _lx=function(a,b,t){t=t<0?0:t>1?1:t;var A=_h2r(a),B=_h2r(b);return _r2h(A[0]+(B[0]-A[0])*t,A[1]+(B[1]-A[1])*t,A[2]+(B[2]-A[2])*t);};
          var _bl=function(base,tgt,t){return [_lx(base[0],tgt[0],t),_lx(base[1],tgt[1],t),_lx(base[2],tgt[2],t),_lx(base[3],tgt[3],t)];};
          var _s2l=function(u){u/=255;return u<=0.04045?u/12.92:Math.pow((u+0.055)/1.055,2.4);};
          var _l2s=function(u){var v=u<=0.0031308?12.92*u:1.055*Math.pow(u<0?0:u,1/2.4)-0.055;return v*255;};
          var _hOk=function(h){var R=_s2l(parseInt(h.slice(1,3),16)),G=_s2l(parseInt(h.slice(3,5),16)),B=_s2l(parseInt(h.slice(5,7),16));var l=Math.cbrt(0.4122214708*R+0.5363325363*G+0.0514459929*B),m=Math.cbrt(0.2119034982*R+0.6806995451*G+0.1073969566*B),s=Math.cbrt(0.0883024619*R+0.2817188376*G+0.6299787005*B);return [0.2104542553*l+0.7936177850*m-0.0040720468*s,1.9779984951*l-2.4285922050*m+0.4505937099*s,0.0259040371*l+0.7827717662*m-0.8086757660*s];};
          var _okR=function(L,A,Bb){var l_=L+0.3963377774*A+0.2158037573*Bb,m_=L-0.1055613458*A-0.0638541728*Bb,s_=L-0.0894841775*A-1.2914855480*Bb;var l=l_*l_*l_,m=m_*m_*m_,s=s_*s_*s_;return [_l2s(4.0767416621*l-3.3077115913*m+0.2309699292*s),_l2s(-1.2684380046*l+2.6097574011*m-0.3413193965*s),_l2s(-0.0041960863*l-0.7034186147*m+1.7076147010*s)];};
          var _cB=function(v){return v<0?0:v>255?255:v;};
          var _sm=function(e0,e1,x){var t=(x-e0)/(e1-e0);t=t<0?0:t>1?1:t;return t*t*(3-2*t);};
          // sky colour engine (port of the lab)
          window._tlSkyColors=function(sa,c,isEve){
            var DB=window._SKY_DB; if(!DB) return ['#0a0820','#12103a','#1a1848','#20204a'];
            var K=window._tlDBK; if(!K){K=Object.keys(DB).map(Number).sort(function(a,b){return a-b;});window._tlDBK=K;}
            var cL=c.cL||0,cM=c.cM||0,cH=c.cH||0,rh=c.rh==null?50:c.rh,visMi=(c.vis==null?30000:c.vis)/1609.34,pr=c.pr||0,sn=c.sn||0;
            var cl=Math.max(K[0],Math.min(K[K.length-1],sa)),lo=K[0],hi=K[K.length-1];
            for(var k=0;k<K.length-1;k++){if(cl>=K[k]&&cl<=K[k+1]){lo=K[k];hi=K[k+1];break;}}
            var g1=DB[String(lo)],g2=DB[String(hi)],t=(hi===lo)?0:(cl-lo)/(hi-lo);
            var sky=[_lx(g1[0],g2[0],t),_lx(g1[1],g2[1],t),_lx(g1[2],g2[2],t),_lx(g1[3],g2[3],t)];
            var gO=['#404858','#4a5468','#546070','#586478'],gM=['#3a4a68','#4a5a78','#506080','#586888'],dg=_sm(-3,4,sa);
            if(sn>0){sky=_bl(sky,['#586878','#6a7888','#7a8898','#8890a0'],Math.min(0.8,sn/2));}
            else{var ca=_sm(20,100,cL),ra=Math.max(0,Math.min(1,pr/1.2));sky=_bl(sky,_bl(gM,gO,ca),Math.min(0.85,ca*0.68+ra*0.18)*dg);}
            sky=_bl(sky,['#3a4868','#4a5a80','#5a6a90','#5a7090'],Math.min(0.35,_sm(30,100,cM)*0.35)*dg);
            sky=_bl(sky,['#4a6098','#5a70a8','#6a80b0','#6888b0'],Math.min(0.25,_sm(25,100,cH)*0.25)*dg);
            sky=_bl(sky,['#3a5890','#4a6898','#5a78a0','#6888a8'],Math.min(0.30,_sm(65,100,rh)*0.30)*_sm(1,6,sa));
            sky=_bl(sky,['#586878','#687888','#788890','#889098'],Math.min(0.50,_sm(8,0,visMi)*0.50)*dg);
            var nh=Math.max(0,1-Math.abs(sa-1)/9);
            var cat=nh*Math.max(0,1-Math.abs((cM+cH)/2-55)/55)*(1-_sm(90,100,cL));
            if(cat>0.02){sky[3]=_lx(sky[3],isEve?'#ff5a26':'#ff7a34',cat*0.34);sky[2]=_lx(sky[2],isEve?'#ff8a54':'#ffab62',cat*0.30);sky[1]=_lx(sky[1],'#c86e92',cat*0.20);}
            var dk=_sm(82,100,cL)*Math.max(0,1-Math.abs(sa)/4);
            if(dk>0.02){sky[3]=_lx(sky[3],isEve?'#a8663f':'#b0784a',dk*0.55);sky[2]=_lx(sky[2],'#8a6c58',dk*0.30);}
            if(isEve){var w=sa>=-1?Math.max(0,1-(sa+1)/9):Math.max(0,1+(sa+1)/11);if(w>0){sky[3]=_lx(sky[3],'#e85226',w*0.40);sky[2]=_lx(sky[2],'#c0586a',w*0.27);sky[1]=_lx(sky[1],'#5a3a70',w*0.13);}}
            if(isEve){var wP=Math.max(0,1-Math.abs(sa+5)/5);sky[2]=_lx(sky[2],'#4a2858',wP*0.22);sky[3]=_lx(sky[3],'#5a3058',wP*0.22);var wB=Math.max(0,1-Math.abs(sa+3)/4);sky[0]=_lx(sky[0],'#3a2a55',wB*0.22);sky[1]=_lx(sky[1],'#8a5a82',wB*0.26);}
            return sky;
          };
window._tlSkyColorsFn = window._tlSkyColors;

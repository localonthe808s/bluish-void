// WEB PUSH, OUR OWN (2026-10-13, user: "lets make a way to have the web version push alerts"). ntfy.sh refused the
// worker's alerts with "daily message quota reached" -- it counts publishers by IP and Cloudflare's egress is shared --
// so the alerts now also go straight to the BLUISH home-screen app on the phone through the browser's own push service
// (Apple's for iPhone, Google's for Chrome). Nothing in between: the worker signs each request with our VAPID key
// (RFC 8292) and encrypts the message for that one phone (RFC 8291, aes128gcm). WebCrypto only, no libraries.
//
// env.VAPID_JWK  -- the P-256 private key as a JWK (secret). Its public half (x, y) is what the page subscribes with.
// Subscriptions live in KV under PUSH_KEY: [{ endpoint, keys: { p256dh, auth }, at, ua }].

export const PUSH_KEY = 'push:subs';
const enc = new TextEncoder();

export function b64u(buf) {
  const b = buf instanceof Uint8Array ? buf : new Uint8Array(buf);
  let s = '';
  for (let i = 0; i < b.length; i++) s += String.fromCharCode(b[i]);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}
export function unb64u(s) {
  s = String(s).replace(/-/g, '+').replace(/_/g, '/');
  while (s.length % 4) s += '=';
  const bin = atob(s), out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
const cat = (...parts) => {
  const n = parts.reduce((a, p) => a + p.length, 0), out = new Uint8Array(n);
  let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};

/* the public key the page subscribes with: 0x04 || x || y, base64url */
export function vapidPublic(jwk) {
  return b64u(cat(new Uint8Array([4]), unb64u(jwk.x), unb64u(jwk.y)));
}

/* VAPID: a short-lived ES256 JWT naming the push service's origin, signed with our key. WebCrypto's ECDSA output is
   already the raw r||s that JWS wants. */
async function vapidAuth(endpoint, jwk) {
  const aud = new URL(endpoint).origin;
  const head = b64u(enc.encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const body = b64u(enc.encode(JSON.stringify({ aud, exp: Math.floor(Date.now() / 1000) + 12 * 3600, sub: 'https://bluishvoid.com' })));
  const key = await crypto.subtle.importKey('jwk', { kty: 'EC', crv: 'P-256', x: jwk.x, y: jwk.y, d: jwk.d, ext: true },
    { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  const sig = await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key, enc.encode(`${head}.${body}`));
  return `vapid t=${head}.${body}.${b64u(sig)}, k=${vapidPublic(jwk)}`;
}

async function hkdf(salt, ikm, info, bytes) {
  const k = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  return new Uint8Array(await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, k, bytes * 8));
}

/* RFC 8291: ECDH with the phone's key, the phone's auth secret folded in, one aes128gcm record */
export async function encryptFor(sub, payload) {
  const uaPub = unb64u(sub.keys.p256dh), auth = unb64u(sub.keys.auth);
  const as = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const asPub = new Uint8Array(await crypto.subtle.exportKey('raw', as.publicKey));
  const uaKey = await crypto.subtle.importKey('raw', uaPub, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const shared = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: uaKey }, as.privateKey, 256));
  const ikm = await hkdf(auth, shared, cat(enc.encode('WebPush: info\0'), uaPub, asPub), 32);
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, enc.encode('Content-Encoding: nonce\0'), 12);
  const aes = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, aes,
    cat(enc.encode(payload), new Uint8Array([2]))));              // 0x02: the last (and only) record
  const rs = new Uint8Array([0, 0, 16, 0]);                        // record size 4096
  return cat(salt, rs, new Uint8Array([asPub.length]), asPub, ct);
}

/* one push to one phone. Returns the push service's status: 201 delivered to the service, 404/410 = the subscription
   is gone (the phone unsubscribed or reinstalled) and should be dropped. */
export async function pushOne(sub, msg, jwk, urgency) {
  if (msg && msg.title) msg = Object.assign({}, msg, { title: String(msg.title).toUpperCase() });   /* every title in capitals (user 2026-10-14) */
  const body = await encryptFor(sub, JSON.stringify(msg));
  const r = await fetch(sub.endpoint, { method: 'POST', body, headers: {
    'Authorization': await vapidAuth(sub.endpoint, jwk),
    'Content-Encoding': 'aes128gcm', 'Content-Type': 'application/octet-stream',
    'TTL': '43200', 'Urgency': urgency || 'high' } });
  return { status: r.status, text: r.ok ? '' : (await r.text()).slice(0, 200) };
}

/* every subscribed phone in the audience; dead subscriptions are pruned. msg = { title, body, tag, url }.
   audience: 'owner' (default -- your positions, jobs) | 'all' (owner + viewers: dark flow, settlement) | an endpoint
   string (that one phone, for SEND A TEST). Subscriptions carry role 'owner' or 'viewer' (2026-10-13, user: "dont share
   my kalshi on the site" -> "only I see it"). */
export async function pushAll(env, msg, urgency, audience) {
  if (!env.VAPID_JWK || !env.OBS) return { sent: 0, failed: 0, note: 'not configured' };
  const jwk = typeof env.VAPID_JWK === 'string' ? JSON.parse(env.VAPID_JWK) : env.VAPID_JWK;
  const subs = (await env.OBS.get(PUSH_KEY, { type: 'json' })) || [];
  if (!subs.length) return { sent: 0, failed: 0, note: 'no phones subscribed' };
  let sent = 0, failed = 0; const keep = [], errs = [];
  const aud = audience || 'owner';
  const wants = (x) => aud === 'all' ? true : aud === 'owner' ? (x.role || 'owner') === 'owner' : x.endpoint === aud;
  for (const s of subs) {
    if (!wants(s)) { keep.push(s); continue; }
    try {
      const r = await pushOne(s, msg, jwk, urgency);
      if (r.status === 404 || r.status === 410) continue;           // gone: drop it
      keep.push(s);
      if (r.status >= 200 && r.status < 300) sent++; else { failed++; errs.push(`${r.status} ${r.text}`); }
    } catch (e) { keep.push(s); failed++; errs.push(String(e)); }
  }
  if (keep.length !== subs.length) await env.OBS.put(PUSH_KEY, JSON.stringify(keep));
  if (errs.length) console.log(`[push] ${errs.join(' | ')}`);
  return { sent, failed };
}

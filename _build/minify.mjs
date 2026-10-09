#!/usr/bin/env node
// Build step for GitHub Pages: minify the inline <script> and <style> blocks of
// index.html with esbuild. The SOURCE keeps its comments; only the published copy
// is minified. Measured 2026-10-09: 7.5 MB raw / 2.2 MB gzip -> ~1.4 MB gzip.
//
//   node _build/minify.mjs index.html dist/index.html
//
// What it touches: inline <script> blocks without src= and without a non-JS type=,
// and inline <style> blocks. Nothing else in the markup changes (inline handlers,
// style= attributes, whitespace all stay), so the page's DOM is byte-for-byte the
// same shape as the source.
//
// Safety: esbuild never renames top-level symbols when it is not bundling, so every
// global the 21 scripts share (and the inline onclick= handlers reach) keeps its
// name; only names private to a function or IIFE are shortened. The script fails the
// build if a block fails to parse after minification, if the number of blocks
// changes, if a `</script` would end a block early, or if any of a list of globals
// the page cannot work without has gone missing.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { dirname } from 'node:path';
import { createRequire } from 'node:module';
import { gzipSync } from 'node:zlib';

const require = createRequire(import.meta.url);
const esbuild = require('esbuild');

const [src, out] = process.argv.slice(2);
if (!src || !out) { console.error('usage: minify.mjs <in.html> <out.html>'); process.exit(2); }

const html = await readFile(src, 'utf8');

// Names the page publishes on window (window.NAME = ...) are property names, which a
// minifier never touches; checking them is cheap insurance that a block was not dropped.
// (Function declarations cannot be checked statically: the page writes many at column
// zero inside closures, and those are private and legitimately renamed. The real check
// is the runtime one: diff Object.keys(window) between the plain and the minified page.)
const MUST_KEEP = new Set();
for (const m of html.matchAll(/\bwindow\.([A-Za-z_$][\w$]*)\s*=[^=]/g)) MUST_KEEP.add(m[1]);
let scripts = 0, styles = 0, skipped = 0;
const warnings = [];

async function js(code, where) {
  const r = await esbuild.transform(code, {
    loader: 'js', minify: true, target: 'es2019', charset: 'utf8', legalComments: 'none', logLevel: 'silent',
  });
  for (const w of r.warnings) warnings.push(`${where}: ${w.text}`);
  let o = r.code;
  // a "</script" inside a string literal would end the block early in HTML
  o = o.replace(/<\/script/gi, '<\\/script');
  // round-trip parse check of the minified output
  await esbuild.transform(o, { loader: 'js', logLevel: 'silent' });
  return o;
}

async function css(code, where) {
  const r = await esbuild.transform(code, { loader: 'css', minify: true, charset: 'utf8', logLevel: 'silent' });
  for (const w of r.warnings) warnings.push(`${where}: ${w.text}`);
  return r.code.replace(/<\/style/gi, '<\\/style');
}

// Replace sequentially (async) so each block is processed exactly once.
const re = /<(script|style)\b([^>]*)>([\s\S]*?)<\/\1>/gi;
let result = '', last = 0, m;
while ((m = re.exec(html))) {
  const [whole, tag, attrs, body] = m;
  const line = html.slice(0, m.index).split('\n').length;
  let replacement = whole;
  if (tag.toLowerCase() === 'script') {
    const hasSrc = /\ssrc\s*=/i.test(attrs);
    const typeM = /\stype\s*=\s*["']?([^"'\s>]+)/i.exec(attrs);
    const type = typeM ? typeM[1].toLowerCase() : '';
    const isJs = !type || type === 'text/javascript' || type === 'application/javascript' || type === 'module';
    if (hasSrc || !isJs || !body.trim()) { skipped++; }
    else { scripts++; replacement = `<script${attrs}>${await js(body, `script@${line}`)}</script>`; }
  } else {
    if (!body.trim()) { skipped++; }
    else { styles++; replacement = `<style${attrs}>${await css(body, `style@${line}`)}</style>`; }
  }
  result += html.slice(last, m.index) + replacement;
  last = m.index + whole.length;
}
result += html.slice(last);

// ---- checks
const count = (s, r) => (s.match(r) || []).length;
const fail = (msg) => { console.error('MINIFY FAILED: ' + msg); process.exit(1); };
// the JS itself may contain '<scr'+'ipt' strings that constant-fold, so count whole
// blocks the way the HTML parser sees them, not opening tags
const blocks = (s) => count(s, /<(script|style)\b[^>]*>[\s\S]*?<\/\1>/gi);
if (blocks(result) !== blocks(html)) fail(`block count changed (${blocks(result)} vs ${blocks(html)})`);
if (count(result, /<\/script>/gi) !== count(html, /<\/script>/gi)) fail('</script> count changed');
const missing = [...MUST_KEEP].filter((name) => !result.includes('window.' + name) && !result.includes('.' + name + '='));
if (missing.length) fail(`${missing.length} window.* names missing: ${missing.slice(0, 8).join(', ')}`);
console.log(`${MUST_KEEP.size} window.* names verified present`);
if (result.length > html.length * 0.9) fail(`output barely smaller (${result.length} vs ${html.length}); minify did not run`);

await mkdir(dirname(out), { recursive: true });
await writeFile(out, result);
const gz = (s) => gzipSync(Buffer.from(s)).length;
console.log(`minified ${scripts} scripts + ${styles} styles (${skipped} blocks left alone)`);
console.log(`raw  ${(html.length / 1e6).toFixed(2)} MB -> ${(result.length / 1e6).toFixed(2)} MB`);
console.log(`gzip ${(gz(html) / 1e6).toFixed(2)} MB -> ${(gz(result) / 1e6).toFixed(2)} MB`);
if (warnings.length) { console.log(`${warnings.length} esbuild warnings (first 10):`); for (const w of warnings.slice(0, 10)) console.log('  ' + w); }

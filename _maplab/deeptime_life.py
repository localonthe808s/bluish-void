#!/usr/bin/env python3
"""
LIFE SILHOUETTES for DEEP TIME (2026-11-02; inspired by Pan Terra's "A Correlated History of Earth" wall chart, which gives
each age its plants and animals -- that chart is copyrighted, so nothing is taken from it). The figures come from PhyloPic
(phylopic.org): silhouettes under CC0 or CC BY only (share-alike and no-derivative ones are skipped), each looked up by
name and checked against the taxon PhyloPic resolved it to, downloaded at 256 px, with the attribution kept in the manifest.

    python3 _maplab/deeptime_life.py out      # out/deeptime/life/<slug>.png + index.json
"""
import json, os, re, sys, time, urllib.parse, urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else 'out'
DIR = os.path.join(OUT, 'deeptime', 'life'); os.makedirs(DIR, exist_ok=True)
API = 'https://api.phylopic.org'
UA = {'User-Agent': 'bluishvoid-deeptime-life (https://bluishvoid.com)'}
OK_LICENSES = ('publicdomain/zero', 'publicdomain/mark', 'licenses/by/')

# [slug, search names (first that resolves to a matching taxon wins), must-match regex on the resolved taxon, kind, from Ma, to Ma, label]
WANT = [
    # plants
    ['cyanobacteria', ['Cyanobacteria', 'Nostoc'], r'Cyanobacteria|Nostoc', 'plant', 3500, 0, 'cyanobacteria'],
    ['liverwort', ['Marchantia', 'Marchantiophyta'], r'Marchantia', 'plant', 470, 0, 'liverworts'],
    ['psilophyton', ['Psilophyton', 'Rhynia'], r'Psilophyton|Rhynia', 'plant', 419, 359, 'early vascular plants'],
    ['fern', ['Asplenium', 'Polypodiales', 'Pteridophyta'], r'Asplenium|Polypod|Pterid', 'plant', 390, 0, 'ferns'],
    ['lepidodendron', ['Lepidodendron', 'Sigillaria'], r'Lepidodendron|Sigillaria', 'plant', 359, 252, 'scale trees'],
    ['horsetail', ['Equisetum', 'Calamites'], r'Equisetum|Calamites', 'plant', 359, 0, 'horsetails'],
    ['cycad', ['Cycas', 'Cycadales'], r'Cycas|Cycad', 'plant', 299, 0, 'cycads'],
    ['ginkgo', ['Ginkgo biloba', 'Ginkgo'], r'Ginkgo', 'plant', 270, 0, 'ginkgoes'],
    ['conifer', ['Pinus sylvestris', 'Pinus', 'Araucaria'], r'Pinus|Araucaria', 'plant', 310, 0, 'conifers'],
    ['magnolia', ['Magnolia grandiflora', 'Magnolia'], r'Magnolia', 'plant', 130, 0, 'flowering plants'],
    ['palm', ['Arecaceae', 'Cocos nucifera'], r'Areca|Cocos|Phoenix', 'plant', 80, 0, 'palms'],
    ['grass', ['Poaceae', 'Zea mays', 'Anomochloa'], r'Poaceae|Zea|Anomochloa|Oryza', 'plant', 66, 0, 'grasses'],
    ['oak', ['Quercus robur', 'Quercus'], r'Quercus', 'plant', 56, 0, 'oaks'],
    # animals
    ['dickinsonia', ['Dickinsonia'], r'Dickinsonia', 'animal', 635, 539, 'Dickinsonia'],
    ['anomalocaris', ['Anomalocaris canadensis', 'Anomalocaris'], r'Anomalocaris', 'animal', 539, 485, 'Anomalocaris'],
    ['trilobite', ['Trilobita', 'Fallotaspis', 'Olenellus'], r'Trilobit|Fallotaspis|Olenellus|Phacops', 'animal', 539, 252, 'trilobites'],
    ['eurypterid', ['Eurypterus', 'Eurypterida'], r'Eurypter', 'animal', 467, 252, 'sea scorpions'],
    ['dunkleosteus', ['Dunkleosteus'], r'Dunkleosteus', 'animal', 382, 358, 'Dunkleosteus'],
    ['tiktaalik', ['Tiktaalik roseae', 'Tiktaalik', 'Ichthyostega'], r'Tiktaalik|Ichthyostega', 'animal', 375, 359, 'the first walkers'],
    ['meganeura', ['Meganeura', 'Meganeuropsis'], r'Meganeur', 'animal', 305, 299, 'giant dragonflies'],
    ['dimetrodon', ['Dimetrodon'], r'Dimetrodon', 'animal', 295, 272, 'Dimetrodon'],
    ['lystrosaurus', ['Lystrosaurus'], r'Lystrosaurus', 'animal', 254, 247, 'Lystrosaurus'],
    ['coelophysis', ['Coelophysis', 'Plateosaurus'], r'Coelophysis|Plateosaurus', 'animal', 216, 201, 'the first dinosaurs'],
    ['stegosaurus', ['Stegosaurus'], r'Stegosaurus', 'animal', 155, 145, 'Stegosaurus'],
    ['brachiosaurus', ['Brachiosaurus', 'Diplodocus'], r'Brachiosaurus|Diplodocus', 'animal', 157, 145, 'sauropods'],
    ['archaeopteryx', ['Archaeopteryx'], r'Archaeopteryx', 'animal', 150, 145, 'Archaeopteryx'],
    ['tyrannosaurus', ['Tyrannosaurus'], r'Tyrannosaurus', 'animal', 68, 66, 'Tyrannosaurus'],
    ['triceratops', ['Triceratops'], r'Triceratops', 'animal', 68, 66, 'Triceratops'],
    ['mosasaurus', ['Mosasaurus'], r'Mosasaur', 'animal', 82, 66, 'mosasaurs'],
    ['basilosaurus', ['Basilosaurus'], r'Basilosaurus', 'animal', 41, 34, 'Basilosaurus'],
    ['paraceratherium', ['Paraceratherium'], r'Paraceratherium', 'animal', 34, 23, 'Paraceratherium'],
    ['megalodon', ['Otodus megalodon', 'Carcharocles megalodon'], r'megalodon|Otodus|Carcharocles', 'animal', 23, 3.6, 'megalodon'],
    ['smilodon', ['Smilodon'], r'Smilodon', 'animal', 2.5, 0.01, 'Smilodon'],
    ['mammoth', ['Mammuthus primigenius', 'Mammuthus'], r'Mammuthus', 'animal', 2.6, 0.004, 'mammoths'],
    ['human', ['Homo sapiens'], r'Homo sapiens', 'animal', 0.3, 0, 'Homo sapiens'],
]


def get(url, binary=False):
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return r.read() if binary else json.load(r)
        except Exception as e:
            time.sleep(3 * (k + 1)); last = e
    raise last


def build():
    try:
        return get(API + '/').get('build')
    except Exception:
        j = get(API + '/images?build=1'); return j.get('build')


def find(bld, name, must):
    j = get(API + '/images?build=%s&filter_name=%s&embed_items=true&page=0' % (bld, urllib.parse.quote(name.lower())))
    for it in ((j.get('_embedded') or {}).get('items') or []):
        L = it.get('_links') or {}; node = ((L.get('specificNode') or {}).get('title') or '')
        lic = (L.get('license') or {}).get('href') or ''
        if not re.search(must, node, re.I) or not any(k in lic for k in OK_LICENSES):
            continue
        ras = [r.get('href') for r in (L.get('rasterFiles') or []) if r.get('href')]
        if not ras:
            continue
        pick = ras[0]
        for r in ras:                                        # the 256-ish one
            if re.search(r'/\d{3}x\d{3}|256', r):
                pick = r
        return {'uuid': it.get('uuid'), 'node': node, 'license': lic, 'by': it.get('attribution') or '', 'raster': pick, 'src': (L.get('self') or {}).get('href')}
    return None


def main():
    bld = build(); print('phylopic build', bld)
    man = {'built': time.strftime('%Y-%m-%dT%H:%MZ', time.gmtime()), 'source': 'PhyloPic (phylopic.org), CC0 and CC BY silhouettes', 'items': []}
    for slug, names, must, kind, f, t, label in WANT:
        hit = None
        for nm in names:
            try:
                hit = find(bld, nm, must)
            except Exception as e:
                print('  ', nm, 'lookup failed', e)
            if hit:
                break
            time.sleep(0.4)
        if not hit:
            print('%-16s MISSING' % slug); continue
        png = get(hit['raster'], binary=True)
        with open(os.path.join(DIR, slug + '.png'), 'wb') as fh:
            fh.write(png)
        man['items'].append({'slug': slug, 'label': label, 'kind': kind, 'from': f, 'to': t, 'node': hit['node'], 'license': hit['license'], 'by': hit['by'], 'uuid': hit['uuid'], 'file': 'deeptime/life/' + slug + '.png'})
        print('%-16s %-30s %-28s %s' % (slug, hit['node'][:30], hit['license'].replace('https://creativecommons.org/', ''), (hit['by'] or 'public domain')[:34]))
        time.sleep(0.4)
    json.dump(man, open(os.path.join(DIR, 'index.json'), 'w'), separators=(',', ':'))
    print('wrote', len(man['items']), 'silhouettes to', DIR)


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""VOLCANO LIVE CAMERAS (user 2026-11-08: "can you confirm we have found all volcano public cams" -> "yes").

Every official volcano camera we may show, keyed by Smithsonian GVP volcano number (the site's volcano cards carry it as v.n):
  USGS   the volcview ashcam catalog (HVO, AVO, CVO, CalVO, YVO in one list, each camera tagged with its GVP number). Kept: a frame in
         the last 24 h, not an FAA weathercam (faaInd Y, no stated licence), owned by USGS or the National Park Service (externalUrl
         empty or on usgs.gov / nps.gov; ski resorts, WSDOT and the like dropped). Public domain. Fixed URLs current(-medium).jpg.
  GEONET New Zealand's volcano cameras, fixed latest URLs. CC BY 3.0 NZ.
  INGV   INGV Osservatorio Etneo, Etna / Stromboli / Vulcano. The frame URL is computed in the browser (UTC, one frame per 3 min). CC BY 4.0.
  JMA    Japan Meteorological Agency, 91 cameras on 49 volcanoes; the browser reads the camera's page for the newest frame (CORS open).
         Public Data License 1.0 (CC BY 4.0 compatible). Credit: Source: Japan Meteorological Agency website.
Not shown (licence forbids reuse, http only, or no stable image): SGC Colombia, CENAPRED / Webcams de Mexico, IPGP (Piton de la
Fournaise, Pelee), VMGD Vanuatu, KB GS RAS and KVERT Kamchatka, PHIVOLCS, MAGMA Indonesia, Mila / RUV (Iceland eruption streams),
MVO Montserrat; and the licence-silent Central / South American observatories. Survey: 2026-11-08.

Out: R2 volcano/cams_v1.json   python3 vcams_bake.py OUT.json
"""
import json, re, sys, time, urllib.parse, urllib.request
UA = {'User-Agent': 'Mozilla/5.0 (bluishvoid.com volcano cameras)'}
CAT = 'https://volcview.wr.usgs.gov/ashcam-api/webcamApi/webcams'
OK_HOSTS = ('usgs.gov', 'nps.gov')
GEONET = [(242030, 'raoulisland', 'RAOUL ISLAND'), (241080, 'ngauruhoe', 'NGAURUHOE FROM THE WEST'), (241080, 'ngauruhoetongariro', 'NGAURUHOE AND TONGARIRO'),
          (241080, 'tongariro', 'TONGARIRO FROM THE NORTH'), (241080, 'tongarirotemaaricrater', 'TE MAARI CRATER'), (241100, 'ruapehunorth', 'RUAPEHU NORTH'),
          (241100, 'ruapehusouth', 'RUAPEHU SOUTH'), (241100, 'ruapehueast', 'RUAPEHU EAST'), (241030, 'taranaki', 'FROM NEW PLYMOUTH'),
          (241040, 'whakatane', 'FROM WHAKATANE'), (241040, 'tekaha', 'FROM TE KAHA')]
INGV = [(211060, 'Ecv', 'FROM CATANIA'), (211060, 'Emov', 'MONTAGNOLA'), (211060, 'Emot', 'MONTAGNOLA THERMAL'), (211060, 'Env', 'NICOLOSI'), (211060, 'Ent', 'NICOLOSI THERMAL'),
        (211060, 'Emv', 'EAST FLANK'), (211060, 'Emct', 'MONTE CAGLIATO THERMAL'), (211060, 'Epvh', 'HIGH RESOLUTION'),
        (211040, 'Scv', 'STROMBOLI'), (211040, 'Sct', 'STROMBOLI THERMAL'), (211040, 'Spct', 'PIZZO THERMAL'),
        (211050, 'Vlv', 'VULCANO'), (211050, 'Vlvh', 'VULCANO HIGH RESOLUTION'), (211050, 'Vvt', 'VULCANO THERMAL')]
JMA = [[285080, [["10401", "104_82002710"], ["10402", "104_82002774"], ["10403", "104_82003070"]]], [285070, [["10501", "105_820027D8"], ["10502", "105_820028A0"]]], [285060, [["10701", "107_82002904"], ["10702", "107_82002968"]]], [285050, [["10801", "108_820029CC"], ["10802", "108_82002AF8"]]], [285040, [["10901", "109_82002B5C"]]], [285034, [["11101", "111_82002C88"], ["11102", "111_82002CEC"]]], [285030, [["11201", "112_82002D50"], ["11202", "112_82002DB4"]]], [285020, [["11301", "113_82002E18"], ["11302", "113_82002E7C"], ["11303", "113_82002F44"]]], [285011, [["11401", "114_82002FA8"], ["11402", "114_8200300C"]]], [283270, [["20201", "202_82004E20"]]], [283280, [["20301", "203_82004E84"], ["20302", "203_82004EE8"]]], [283271, []], [283260, [["20501", "205_82005014"]]], [283240, [["20701", "207_82005078"], ["20702", "207_820050DC"], ["20703", "207_820058AC"]]], [283220, [["20901", "209_820057E4"]]], [283210, [["21001", "210_820052D0"]]], [283190, [["21201", "212_82005398"], ["21204", "212_82005910"]]], [283180, [["21301", "213_82005528"]]], [283170, [["21401", "214_82005654"], ["21402", "214_820056B8"]]], [283160, [["21501", "215_8200571C"], ["21502", "215_82005780"]]], [283150, [["30101", "301_82007530"], ["30102", "301_82007594"]]], [283140, [["30201", "302_820075F8"], ["30202", "302_82008A48"]]], [283120, [["30501", "305_820076C0"], ["30502", "305_8200765C"], ["30504", "305_82008AAC"]]], [283110, [["30601", "306_820078B4"], ["30602", "306_82007850"]]], [283090, [["30701", "307_82007B70"]]], [283080, [["30901", "309_820089E4"]]], [283070, [["31001", "310_82007DC8"]]], [283060, [["31101", "311_82007E2C"]]], [283040, [["31201", "312_82007E90"], ["31202", "312_82007FBC"]]], [283050, [["31301", "313_82008020"]]], [283030, [["31401", "314_82008084"]]], [283020, [["31501", "315_820081B0"], ["31502", "315_82008278"], ["31504", "315_82008B10"]]], [283010, [["31601", "316_820082DC"], ["31602", "316_82008340"]]], [284010, [["31701", "317_820083A4"], ["31702", "317_82008408"]]], [284020, [["31801", "318_820084D0"]]], [284030, [["31901", "319_82008534"]]], [284040, [["32001", "320_82008598"], ["32002", "320_82008660"], ["32003", "320_820086C4"]]], [284050, [["32101", "321_8200878C"]]], [284060, [["32201", "322_820087F0"]]], [282130, [["51301", "513_8200D28C"]]], [282120, [["50201", "502_8200C350"], ["50202", "502_8200C3B4"], ["50203", "502_8200D2F0"]]], [282110, [["50301", "503_8200C418"], ["50302", "503_8200D354"], ["50303", "503_8200D5AC"]]], [282100, [["50401", "504_8200C544"]]], [282090, [["50501", "505_8200C60C"], ["50502", "505_8200C670"], ["50507", "505_8200C6D4"], ["50508", "505_8200C800"], ["50504", "505_8200C8C8"], ["50505", "505_8200C738"], ["50506", "505_8200C92C"]]], [282080, [["50601", "506_8200C990"], ["50602", "506_8200C9F4"], ["50603", "506_8200CA58"]]], [282060, [["50801", "508_8200CCB0"]]], [282050, [["50901", "509_8200CD78"], ["50902", "509_8200D1C4"]]], [282040, [["51001", "510_8200D6D8"], ["51002", "510_8200D73C"]]], [282030, [["51101", "511_8200CF08"], ["51102", "511_8200CF6C"]]]]
SRC = {'usgs': ['U.S. GEOLOGICAL SURVEY', 'https://volcview.wr.usgs.gov/', 'PUBLIC DOMAIN'],
       'nps': ['NATIONAL PARK SERVICE VIA USGS', 'https://volcview.wr.usgs.gov/', 'PUBLIC DOMAIN'],
       'geonet': ['GEONET / EARTH SCIENCES NEW ZEALAND', 'https://www.geonet.org.nz/volcano/cameras', 'CC BY 3.0 NZ'],
       'ingv': ['INGV OSSERVATORIO ETNEO', 'https://www.ct.ingv.it/index.php/monitoraggio-e-sorveglianza/telecamere', 'CC BY 4.0'],
       'jma': ['JAPAN METEOROLOGICAL AGENCY', 'https://www.data.jma.go.jp/vois/data/obs/volcam/volcam.php', 'SOURCE: JMA WEBSITE']}


def main(out):
    now = time.time(); V = {}
    cams = json.load(urllib.request.urlopen(urllib.request.Request(CAT, headers=UA), timeout=90))['webcams']
    keep = []
    for w in cams:
        if not w.get('vnum') or w.get('faaInd') == 'Y' or w.get('hasImages') != 'Y': continue
        ts = w.get('lastImageTimestamp') or 0
        if now - ts > 86400: continue
        host = urllib.parse.urlparse(w.get('externalUrl') or '').netloc
        if host and not host.endswith(OK_HOSTS): continue
        keep.append((int(w['vnum']), -ts, 'nps' if host.endswith('nps.gov') else 'usgs', w))
    keep.sort(key=lambda k: (k[0], k[2] != 'usgs', k[1]))
    for n, _, src, w in keep:
        L = V.setdefault(str(n), [])
        if len(L) >= 8: continue
        nm = (w.get('webcamName') or w['webcamCode']).replace('-cam', '').upper()
        # "CVO St. Helens (GUAC, East Crater)" -> "GUAC, EAST CRATER": the strip already names the volcano and the observatory
        nm = re.sub(r'^(CVO|AVO|HVO|YVO|CALVO)\s+', '', nm)
        vn = (w.get('vName') or '').upper(); bare = re.sub(r'^(MOUNT|MT\.?)\s+', '', vn)
        m = re.search(r'[(\[]([^)\]]+)[)\]]\s*$', nm)
        if m: nm = m.group(1)   # "ST. HELENS (GUAC, EAST CRATER)" -> the part in brackets
        else:
            for pre in (vn, bare):
                if pre and nm.startswith(pre): nm = nm[len(pre):]; break
        nm = nm.strip(' -').strip()
        nm = nm.replace('-', ' ').strip() or vn
        L.append([src, 'u', w['currentMediumImageUrl'], nm, w['currentImageUrl']])
    for n, cid, cap in GEONET:
        V.setdefault(str(n), []).append(['geonet', 'u', 'https://images.geonet.org.nz/volcano/cameras/latest/m-%s.jpg' % cid, cap, 'https://images.geonet.org.nz/volcano/cameras/latest/%s.jpg' % cid])
    for n, cam, cap in INGV: V.setdefault(str(n), []).append(['ingv', 'ingv', cam, cap])
    for n, cl in JMA:
        for i, (vc, d) in enumerate(cl): V.setdefault(str(n), []).append(['jma', 'jma', [vc, d], 'JMA CAMERA %d' % (i + 1)])
    j = {'built': int(now), 'src': SRC, 'v': V}
    json.dump(j, open(out, 'w'), separators=(',', ':'))
    print('volcanoes', len(V), 'cameras', sum(len(x) for x in V.values()), 'usgs kept', len(keep))


if __name__ == '__main__':
    main(sys.argv[1])

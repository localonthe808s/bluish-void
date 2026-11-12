#!/usr/bin/env python3
"""THE HISTORIC SATELLITES' FIRST PICTURES (2026-10-23, user: "there should be a group for historic / past satellites, these
wont need latest photos, can we show ERTS and TIROS - first satellites, i would love to show their first or most important
photos"). Curated, public-domain frames from Wikimedia Commons (NASA, NOAA, USGS originals), each vetted on a contact sheet:
duplicates of one frame (TIROS-1's first picture exists as three prints) keep the most original copy.

  tiros1  TIROS-1, the first weather satellite (1960): the raw first recorded frame, the famous print, the four-frame sheet
  erts1   ERTS-1 / Landsat 1 (1972): first light over Dallas-Fort Worth, the first cloud-free scene, Alaska's glaciers, the
          Bay Area, the 1973 Mississippi flood, Los Angeles

Writes _solarlab/probes/<set>_NN.webp (long side 900 px) and merges the sets into _solarlab/probes/probes.json (the probe
archive's manifest; build_probe_archive.py keeps sets it does not own), plus the heroes _solarlab/sprites/{tiros1,erts1}.webp.

    python3 _solarlab/build_historic.py
"""
import io, json, time, urllib.parse, urllib.request
from pathlib import Path
from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / 'probes'
UA = {'User-Agent': 'bluishvoid.com historic satellites (https://bluishvoid.com)'}   # the project only, never a personal contact

SETS = {
    'tiros1': [
        ('Celebrating 61 Years of Watching Weather from Space (NESDIS 2021-04-01 the real first TIROS-1 image).png',
         'The first recorded frame, 13:31 UTC, April 1, 1960', '1960-04-01', 'TIROS-1 TV camera 2', 'NOAA / CIMSS'),
        ('1960- First “television” picture of Earth from space (TIROS-1).jpg',
         'First television picture from space, April 1, 1960', '1960-04-01', 'TIROS-1 TV camera', 'NASA'),
        ('First television images of Earth from space; northeastern North America.jpg',
         'Northeastern North America, the first day’s pictures', '1960-04-01', 'TIROS-1 TV camera', 'NASA'),
    ],
    'erts1': [
        ('Landsat 1 First Light Image (1972-07-25).jpg',
         'First light: Dallas–Fort Worth, July 25, 1972', '1972-07-25', 'ERTS-1 multispectral scanner', 'USGS'),
        ('Landsat 1 image of Ouachita Mountains (1972-07-25).jpg',
         'The first cloud-free scene: the Ouachita Mountains', '1972-07-25', 'ERTS-1 multispectral scanner', 'USGS EROS'),
        ('First Glimpse of Alaska’s Glaciers from Landsat (Landsat 1, 1972-07-31).jpg',
         'Alaska’s glaciers, six days in', '1972-07-31', 'ERTS-1 multispectral scanner', 'USGS'),
        ('ERTS-1 San Francisco (ARC-1972-AC78-1116).jpg',
         'The San Francisco Bay Area', '1972', 'ERTS-1 multispectral scanner', 'NASA Ames'),
        ('Morganza Spillway, Louisiana 5 May 1973.jpg',
         'The 1973 Mississippi flood at the Morganza Spillway', '1973-05-05', 'ERTS-1 multispectral scanner', 'NASA / USGS'),
        ('Landsat 1 image of Los Angeles (PIA02988).jpg',
         'Los Angeles and its basin', '1972', 'ERTS-1 multispectral scanner', 'NASA/JPL'),
    ],
    # (user 2026-10-23: "TIROS 9 first full world weather / LANDSAT / ERTS / SEASAT")
    'tiros9': [
        ("The World's Weather Spac0024-repair.jpg",
         'The first complete view of the world\u2019s weather, Feb 13, 1965 \u2014 450 pictures in one', '1965-02-13', 'TIROS-9 TV cameras', 'NOAA Photo Library'),
        ('Betsy from TIROS IX Spac0008-repair.jpg',
         'Hurricane Betsy, 1965', '1965', 'TIROS-9 TV camera', 'NOAA Photo Library'),
        ('TIROS IX Ross Sea Ice Shelf Spac0155-repair.jpg',
         'Antarctica\u2019s Ross Ice Shelf, orbit 22', '1965-01-23', 'TIROS-9 TV camera', 'NOAA Photo Library'),
        ('Cut-off North Pacific low as seen on pass 129 by TIROS-9 (2268-496).jpg',
         'A cut-off low spinning over the North Pacific, pass 129', '1965-02-01', 'TIROS-9 TV camera', 'NOAA'),
    ],
    'seasat': [
        ('url:https://images-assets.nasa.gov/image/PIA18137/PIA18137~medium.jpg|https://images.nasa.gov/details/PIA18137',
         'The Massachusetts coast: waves and currents on the open sea, Aug 27, 1978', '1978-08-27', 'Seasat synthetic aperture radar', 'NASA/JPL-Caltech'),
        ('Seasat picture of Los Angeles.jpg',
         'Los Angeles by radar, 1978', '1978', 'Seasat synthetic aperture radar', 'NASA/JPL'),
        ('Seasat - (Chesapeake Bay region) LOC 81694423.jpg',
         'The Chesapeake Bay region, Sep 25, 1978', '1978-09-25', 'Seasat synthetic aperture radar', 'NASA/JPL (Library of Congress)'),
    ],
}
# MORE OF EACH (user 2026-10-23: "are there more photos and videos you can add to TIROS and LANDSAT/SEASAT")
SETS.update({
    'tiros_years': [
        ('video:1960-11-24 Tiros II Weatherman Satellite.webm|0|83',
         'The newsreel: TIROS II launches and sends its pictures down, November 1960', '1960-11-24', 'Universal-International News', 'Universal Newsreel (CC0)'),
        ('Hurricane Esther by TIROS 3 (July 1961).jpg',
         'Hurricane Esther: the first hurricane found from space, Sep 1961', '1961-09-10', 'TIROS-3 TV camera', 'NASA'),
        ('Tiros 3 and Hurricane Anna (Jul. 17, 1961).jpg',
         'The cloud mass that became Hurricane Anna, Jul 17, 1961', '1961-07-17', 'TIROS-3 TV camera', 'NOAA'),
        ('Typhoon Ruth TIROS V 18 aug 1962.jpg',
         'Typhoon Ruth and its eye, Aug 18, 1962', '1962-08-18', 'TIROS-5 TV camera', 'NOAA'),
        ('TIROS 5 Eddy patterns (July 1962)-repair.jpg',
         'Eddies in the clouds downwind of the Canary Islands, 1962', '1962-07', 'TIROS-5 TV camera', 'NOAA Photo Library'),
        ('Jet stream clouds south of Cape Blanc, north Atlantic coast of Africa photographed by TIROS VIII (2268-162).jpg',
         'Jet-stream clouds off West Africa', '1964', 'TIROS-8 TV camera', 'NOAA'),
        ('Cloud streets in Gulf of Mexico after frontal passage TIROS X pass 3039-3038 (2268-306).jpg',
         'Cloud streets over the Gulf of Mexico after a cold front', '1965', 'TIROS-10 TV camera', 'NOAA'),
        ('TIROS 5 contrails (May 5, 1963)-repair.jpg',
         'Jet contrails south of San Diego, May 5, 1963', '1963-05-05', 'TIROS-5 TV camera', 'NOAA Photo Library'),
    ],
    'landsat_world': [
        ('Landsat 1 and 2 (mosaic of 75 false color photos).png',
         'The Upper Midwest, hand-laid from 75 pictures', '1972-1976', 'Landsat 1 and 2 multispectral scanners', 'USGS EROS'),
        ('Florida, satellite image mosaic - NASA ERTS-1 imagery-1973 LOC 79695190.jpg',
         'The first satellite map of all of Florida, 1973', '1973', 'ERTS-1 multispectral scanner', 'USGS (Library of Congress)'),
        ('Earth Shots – Cairo, Egypt (Landsat 1, 1972-08-31).png',
         'Cairo and the Nile, Aug 31, 1972', '1972-08-31', 'Landsat 1 multispectral scanner', 'USGS'),
        ('Earth Shots – Phoenix, Arizona (Landsat 1, 1972-10-16).png',
         'Phoenix before the sprawl, Oct 16, 1972', '1972-10-16', 'Landsat 1 multispectral scanner', 'USGS'),
        ('Earth Shots – Bahrain (Landsat 1, 1972-09-03).png',
         'Bahrain, Sep 3, 1972', '1972-09-03', 'Landsat 1 multispectral scanner', 'USGS'),
    ],
})
# ALL OF THEM (user 2026-10-23: "all, keep adding the tabs and were going to split them up after")
SETS.update({
    'explorer6': [
        ('First satellite photo - Explorer VI.jpg', 'The first photograph of Earth from orbit, Aug 14, 1959', '1959-08-14', 'Explorer 6 TV scanner', 'NASA'),
        ('Explanatory Image of the First Explorer VI Picture of Earth - GPN-2002-000201.jpg', 'What it shows: sunlit clouds over the central Pacific, mapped', '1959-08-14', 'Explorer 6 TV scanner', 'NASA'),
        ('video:1959-08-10 Explorer VI.webm|0|70', 'The newsreel: the \u201cpaddle-wheel moon\u201d launches, August 1959', '1959-08-10', 'Universal-International News', 'Universal Newsreel (CC0)'),
    ],
    'ats1': [
        ('1966- First view of Earth and the Moon together (ATS-1).jpg', 'Earth and the Moon in one frame', '1966', 'ATS-1 spin-scan cloud camera', 'NASA'),
        ('ATS-1 (Earth full disk), 1966.jpg', 'The first whole Earth from geostationary orbit, Dec 11, 1966', '1966-12-11', 'ATS-1 spin-scan cloud camera', 'NASA'),
    ],
    'ats3': [
        ('ATSIII 10NOV67 153107.jpg', 'The first color picture of the whole Earth, Nov 10, 1967', '1967-11-10', 'ATS-3 color spin-scan camera', 'NASA'),
        ('Hurricanes Camille and Debbie, ATS III satellite, August 17, 1969.jpg', 'Hurricanes Camille and Debbie at once, Aug 17, 1969', '1969-08-17', 'ATS-3 spin-scan camera', 'NOAA'),
        ('Celebrate Earth Day With These GOES Satellite Images (NESDIS 2019-04-22 19700422-ATSIII-firstearthday).jpg', 'The Americas on the first Earth Day, Apr 22, 1970', '1970-04-22', 'ATS-3 spin-scan camera', 'NOAA NESDIS'),
        ('Applications Technology Satellite 3 (ATS-3) image of the western hemisphere (2282-78).jpg', 'The western hemisphere, gridded, Jul 21, 1970', '1970-07-21', 'ATS-3 spin-scan camera', 'NOAA'),
    ],
    'lo1': [
        ('First View of Earth from Moon.jpg', 'The first picture of Earth from the Moon, Aug 23, 1966', '1966-08-23', 'Lunar Orbiter 1 camera', 'NASA'),
        ('First View of Earth from Moon - reprocessed wide.jpg', 'The same frame, restored from the original tapes in 2008', '1966-08-23', 'Lunar Orbiter 1 camera', 'NASA / LOIRP'),
        ('Earthrise 23 Aug 1966.jpg', 'Earthrise over the Moon\u2019s limb, the full strip', '1966-08-23', 'Lunar Orbiter 1 camera', 'NASA'),
    ],
    'planck': [   # user 2026-11-12: "do soviet ones with enough photos, same with ESA"
        ('Plank Molecular Clouds.jpg', 'The first all-sky map of carbon monoxide: the Milky Way’s molecular clouds', '2012-02-13', 'HFI', 'ESA/NASA/Planck Collaboration, public domain'),
        ('Galaxy clusters connected by gas bridge node full image 2.jpg', 'A bridge of hot gas linking two galaxy clusters, in orange', '2012-11-20', 'HFI/LFI', 'ESA Planck Collaboration, CC BY-SA 3.0'),
        ('Cosmic Microwave Background (CMB).jpeg', 'The whole sky in the oldest light: the cosmic microwave background', '2013-03-21', 'HFI/LFI', 'ESA and the Planck Collaboration, CC BY 4.0'),
        ('The core of the Shapley Supercluster.jpg', 'Gas between the galaxy clusters of the Shapley Supercluster, in blue', '2013-10-21', 'HFI/LFI with ROSAT and DSS', 'ESA & Planck Collaboration / ROSAT / DSS, CC BY-SA 3.0'),
    ],
    'herschel': [   # user 2026-11-12: "do soviet ones with enough photos, same with ESA"
        ('Infrared Image of Dark Cloud in Aquila.jpg', 'Some 700 forming stars in dusty filaments of a dark cloud in Aquila', '2009-12-16', 'PACS + SPIRE', 'ESA / SPIRE / PACS / P. André (CEA Saclay), public domain'),
        ('Embryonic Stars in the Rosette Nebula.jpg', 'Dusty cocoons of massive embryonic stars in the Rosette cloud', '2010-04-12', 'PACS + SPIRE', 'ESA and the PACS, SPIRE & HSC Consortia, public domain'),
        ('The Galactic Bubble RCW 120.jpg', 'The bubble RCW 120, a newborn giant star in its wall', '2010-05-06', 'PACS + SPIRE', 'ESA/PACS/SPIRE/HOBYS, public domain'),
        ('Herschel Image of Andromeda Galaxy.jpg', 'Cold dust tracing the rings of star birth in Andromeda', '2011-01-05', 'PACS + SPIRE', 'ESA/Herschel/PACS/SPIRE/J. Fritz, U. Gent, public domain'),
        ('Herschel’s view of a star nursery ESA384009.jpg', 'A tangle of filaments in Rho Ophiuchi, 440 light-years away', '2017-09-18', 'PACS + SPIRE', 'ESA/Herschel/NASA/JPL-Caltech, CC BY-SA 3.0 IGO'),
    ],
    'smart1': [   # user 2026-11-12: "do soviet ones with enough photos, same with ESA"
        ('SMART-1’s view of a waning Earth ESA213471.jpg', 'Earth, turning and waning, from about 124,000 miles', '2004-11-01', 'AMIE', 'ESA/Space-X (Space Exploration Institute), CC BY-SA 3.0 IGO'),
        ('SMART-1 approaches the Moon ESA232678.jpg', 'The Moon on approach, from 373,000 and then 37,000 miles', '2004-11-12', 'AMIE', 'ESA/Space-X, CC BY-SA 3.0 IGO'),
        ('Pythagoras impact crater ESA213440.jpg', 'Pythagoras, a 75-mile crater with a central peak', '2004-12-29', 'AMIE', 'ESA/Space-X, CC BY-SA 3.0 IGO'),
        ('The lunar north pole - SMART-1 mosaic ESA226382.jpg', 'About 30 frames stitched into a mosaic of the Moon’s north pole', '2007-12-10', 'AMIE', 'ESA/Space-X, CC BY-SA 3.0 IGO'),
    ],
    'rosetta': [   # user 2026-11-12: "do soviet ones with enough photos, same with ESA"
        ('Comet 67P True color.jpg', 'Comet 67P in natural color, nearly coal-black, from 75 miles', '2014-08-06', 'OSIRIS narrow-angle camera', 'ESA/Rosetta/MPS for OSIRIS Team, CC BY-SA 4.0'),
        ('Comet 67P on 19 September 2014 NavCam mosaic.jpg', 'The two-lobed “rubber duck” nucleus from 17.8 miles', '2014-09-19', 'NAVCAM', 'ESA/Rosetta/NAVCAM, CC BY-SA 3.0 IGO'),
        ('OSIRIS spots Philae drifting across the comet - Flickr - europeanspaceagency.jpg', 'Philae drifting across the comet after its first touchdown', '2014-11-12', 'OSIRIS narrow-angle camera', 'ESA/Rosetta/MPS for OSIRIS Team, CC BY-SA 4.0'),
        ('Comet 67P on 12 August 2015 (20300571683).jpg', 'Jets streaming from the nucleus a day before perihelion', '2015-08-12', 'NAVCAM', 'ESA/Rosetta/NAVCAM, CC BY-SA 2.0'),
        ('Philae found (36151637845).jpg', 'Philae found, wedged in a dark crack, from 1.7 miles', '2016-09-02', 'OSIRIS narrow-angle camera', 'ESA/Rosetta/MPS for OSIRIS Team; ESA/Rosetta/NavCam, CC BY-SA 2.0'),
        ('Comet from 16 km (29902697052).jpg', 'Cliffs and boulders from 10 miles up, on the final descent', '2016-09-30', 'OSIRIS narrow-angle camera', 'ESA/Rosetta/MPS for OSIRIS Team, CC BY-SA 4.0'),
    ],
    'huygens': [   # user 2026-11-12: "do soviet ones with enough photos, same with ESA"
        ('Mercator region by huygens.jpg', 'Titan’s ridges and channels, flattened panorama from 6 miles up', '2005-01-14', 'DISR descent imager', 'ESA/NASA/JPL/University of Arizona, public domain'),
        ('Huygens shoreline.jpg', 'Bright uplands cut by channels meet a dark plain', '2005-01-14', 'DISR descent imager', 'NASA/JPL/ESA/University of Arizona, public domain'),
        ('HRICoastLineMoasic H.jpg', 'Branching channels draining off a high ridge', '2005-01-14', 'DISR descent imager', 'ESA/NASA/JPL/University of Arizona, public domain'),
        ('Huygens fish-eye view of Titan.jpg', 'Fish-eye view of the landing region from about 3 miles up', '2005-01-14', 'DISR descent imager', 'ESA/NASA/JPL/University of Arizona, public domain'),
        ('Huygens surface color.jpg', 'The surface of Titan: rounded pebbles under an orange sky', '2005-01-14', 'DISR descent imager', 'ESA/NASA/JPL/University of Arizona, public domain'),
    ],
    'mir': [   # user 2026-11-12: "do soviet ones with enough photos, same with ESA"
        ('Astronaut Gibson Shakes Hands with Cosmonaut Dezhurov - GPN-2002-000062.jpg', 'Gibson and Dezhurov shake hands at the first shuttle docking', '1995-06-29', '35 mm camera, STS-71 crew', 'NASA, public domain'),
        ('Atlantis docked to MIR - GPN-2000-001315.jpg', 'Atlantis docked to Mir, seen from a Soyuz fly-around', '1995-07-04', 'Mir-19 crew, from their Soyuz', 'NASA, public domain'),
        ('Interior of Mir Core Module.jpg', 'Yury Onufrienko floats through the core module', '1996-03-25', '35 mm camera, STS-76 crew aboard Mir', 'NASA, public domain'),
        ('Fernandina NM22-723-69.jpg', 'The Galapagos volcanoes, photographed from Mir', '1996-10-16', 'Hasselblad, 250 mm lens, Mir-22 crew', 'NASA, public domain'),
        ('Christmas 1997 on the Mir Space Station.jpg', 'Solovyev, Wolf and Vinogradov at Christmas aboard Mir', '1997-12-25', 'Mir-24 crew', 'NASA, public domain'),
        ('Mir space station 12 June 1998.jpg', 'Mir from Discovery on the last shuttle fly-around', '1998-06-08', 'STS-91 crew aboard Discovery', 'NASA, public domain'),
    ],
    'luna': [   # user 2026-11-12: "do soviet ones with enough photos, same with ESA"
        ('Luna 3 moon.jpg', 'The first full view of the Moon’s far side', '1959-10-07', 'Yenisey-2 camera', 'OKB-1 / USSR via NASA NSSDCA, public domain'),
        ('Close-up of the far side of the Moon from Luna 3.png', 'A narrow-angle frame of the far side, near Mare Smythii', '1959-10-07', 'Yenisey-2 camera, narrow-angle lens', 'OKB-1 / USSR via NASA NSSDCA, public domain'),
        ('First Photo from the Surface of the Moon.jpg', 'Luna 9: the first photo from the Moon’s surface, Ocean of Storms', '1966-02-04', 'Luna 9 panoramic camera', 'USSR via NASA NSSDCA, public domain'),
    ],
    'venera': [   # user 2026-11-12: "our mission archives doesnt show the VENERA missions"
        ('Foto de Venera 9.png', 'The first photograph from the surface of another planet, Oct 22, 1975', '1975-10-22', 'Venera 9 lander camera', 'Reprocessed by Ted Stryk, public domain'),
        ('Venera10surface.gif', 'Venera 10 on Venus, three days later', '1975-10-25', 'Venera 10 lander camera', 'USSR Academy of Sciences, public domain'),
        ('V13 vg261 262.tif', 'The first color pictures from Venus, Mar 1, 1982', '1982-03-01', 'Venera 13 lander camera', 'USSR / NASA, public domain'),
    ],
    'goes': [
        ('First image from GOES Spac0041.jpg', 'The first picture from a GOES satellite, Oct 25, 1975', '1975-10-25', 'GOES-1 VISSR', 'NOAA Photo Library'),
        ('SMS-II full disc infrared image showing parade of tropical storms marching tothe west across the eastern Pacific Ocean (2268-406).jpg', 'A parade of storms across the eastern Pacific, in infrared', '1975-09-26', 'SMS-2 VISSR, infrared', 'NOAA'),
    ],
    'nimbus7': [
        ('Southern Hemisphere Ozone Hole, 1979 (50700749826).png', 'Ozone over Antarctica, 1979 \u2014 the record the ozone hole was measured against', '1979', 'Nimbus-7 TOMS', 'NASA'),
        ('First Composite Image of the Global Biosphere (16469728119).jpg', 'The first picture of the whole planet\u2019s life, land and sea', '1980', 'Nimbus-7 CZCS with NOAA AVHRR', 'NASA'),
        ('Czcswestofflorida.png', 'Ocean color off west Florida, 1978', '1978', 'Nimbus-7 Coastal Zone Color Scanner', 'NASA'),
        ('Tasmania 27nov81.png', 'Plankton blooms round Tasmania, Nov 27, 1981', '1981-11-27', 'Nimbus-7 Coastal Zone Color Scanner', 'NASA'),
        ('video:Visualization of 3D Ozone Data- Nimbus-7 SBUV (SVS129).webm|9|72', 'The ozone layer, layer by layer, October 1985', '1985-10', 'Nimbus-7 SBUV (NASA SVS)', 'NASA SVS'),
    ],
    'corona': [
        ('CORONA first image.jpg', 'The first picture from a spy satellite: Mys Shmidta airfield, Aug 18, 1960', '1960-08-18', 'CORONA KH-1 panoramic camera', 'NRO / USGS'),
        ('Baikonur Cosmodrome imaged by a KH-4 on 1962-05-30.jpg', 'Baikonur Cosmodrome, May 30, 1962', '1962-05-30', 'CORONA KH-4, ~25 ft resolution', 'NRO / USGS'),
        ('Satellite image of Singapore (Corona, KH-4, mission 9053) - 19630401.jpg', 'Singapore, Apr 1, 1963', '1963-04-01', 'CORONA KH-4', 'NRO / USGS'),
        ('Beijing Subway in Construction - satellite image (1967-09-20).jpg', 'Beijing\u2019s first subway being dug, Sep 20, 1967', '1967-09-20', 'CORONA', 'NRO / USGS'),
        ('Kennedy Space Center imaged by a KH-4B on 1968-11-18 - DS1105-2240DA011.jpg', 'Kennedy Space Center as Apollo 8 was readied, Nov 18, 1968', '1968-11-18', 'CORONA KH-4B, ~6 ft resolution', 'NRO / USGS'),
        ('C-119J satellite catching gear.jpg', 'How the film came home: caught in midair by a C-119', '1960s', 'U.S. Air Force', 'U.S. Air Force'),
    ],
})
SETS['tiros9'].append(('Iceland with sea ice to the north (A), a frontal band to the south (E), and parallel bands of cumuliform clouds to the east (B) - TIROS IX photograph (2282-53).jpg',
                       'Iceland, its sea ice, a front and cloud streets, Mar 22, 1965', '1965-03-22', 'TIROS-9 TV camera', 'NOAA'))
# ARCHIVAL FILM (user 2026-10-23: "look for more cool archival footage"): one '<key>_film' set per tab, silent clips cut from
# Commons films after a contact-sheet pass (_film sets show under THE ARCHIVE as ARCHIVAL FILM)
SETS.update({
    'ats3_film': [
        ('video:The First Color Movie of the Planet Earth.webm|66|140', 'The first color movie of the whole Earth, 1967 \u00b7 the film has faded to red', '1967', 'ATS-3 color spin-scan camera', 'NCAR Archives (CC BY 3.0)'),
    ],
    'corona_film': [
        ('video:CORONA lifecycle video.ogv|10|62', 'Launch, orbit and the film capsule\u2019s release', 'c. 1960s', 'NRO film', 'NRO \u00b7 public domain'),
        ('video:CORONA lifecycle video.ogv|64|116', 'The capsule\u2019s parachute caught in midair by an Air Force plane', 'c. 1960s', 'NRO film', 'NRO \u00b7 public domain'),
    ],
    'lo1_film': [
        ('video:The Lunar Orbiter- A Spacecraft to Advance Lunar Exploration.webm|270|330', 'How the pictures came home: film developed on board, scanned and radioed to Earth', '1966', 'NASA / Boeing film', 'NASA STI \u00b7 public domain'),
        ('video:Close Up of the Moon, A Look at Lunar Orbiter (ca. 1966).webm|475|545', 'The Moon as Lunar Orbiter saw it', 'c. 1966', 'NASA film (National Archives)', 'NASA via National Archives \u00b7 public domain'),
    ],
    'erts1_film': [
        ('video:Las Vegas 1972-2021.webm|0|68', 'Las Vegas and Lake Mead, 1972 to 2021', '1972-2021', 'Landsat 1 through 8', 'NASA Goddard \u00b7 public domain'),
        ('video:Dalhart, Texas 1972-2011.ogv|0|42', 'Dalhart, Texas: square fields turn to irrigation circles, 1972 to 2011', '1972-2011', 'Landsat 1 through 7', 'NASA Goddard \u00b7 public domain'),
        ('video:48 Years of Alaska\'s Glaciers E4Zc KuXMkA.webm|12|47', 'Alaska\u2019s glaciers since the 1970s', '1972-2019', 'Landsat 1 through 8', 'NASA Goddard \u00b7 public domain'),
    ],
    'cassini_film': [
        ('video:PIA21047 - Saturn Rotation Cassini.ogv|0|41', 'Saturn turning, 44 hours in one stare, April 2016', '2016-04-25', 'Cassini wide-angle camera', 'NASA/JPL-Caltech/SSI \u00b7 public domain'),
        ('video:PIA14947 Saturn Hurricane Movie.ogv|13|26', 'The hurricane at Saturn\u2019s north pole, Nov 27, 2012', '2012-11-27', 'Cassini narrow-angle camera', 'NASA/JPL-Caltech/SSI/Hampton \u00b7 public domain'),
        ('video:PIA21441 - Cassini\'s \'Porthole\' Movie of Saturn, Figure 1.ogv|0|21', 'Diving over Saturn\u2019s clouds on the first Grand Finale orbit, Apr 26, 2017', '2017-04-26', 'Cassini wide-angle camera', 'NASA/JPL-Caltech/SSI/Hampton \u00b7 public domain'),
    ],
    'juno_film': [
        ('video:Juno flyby of Jupiter, Perijove 16 (PIA22906).webm|0|54', 'A close pass over Jupiter, Oct 29, 2018', '2018-10-29', 'JunoCam', 'NASA/JPL-Caltech/SwRI/MSSS/Gerald Eichst\u00e4dt \u00b7 public domain'),
    ],
})
# LAGEOS (user 2026-11-04: "can we make an archive tab for the LAGEOS satellite?"): the mirror ball, its launch, Sagan's plaque, LAGEOS 2
SETS['lageos'] = [
    # the satellite itself, not the people (user 2026-11-04: "dont show the astronauts, show more of the satellite itself, the old ones are cool and scifi")
    ('url:https://nssdc.gsfc.nasa.gov/planetary/image/lageos_illus.jpg|https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=1976-039A', 'Marshall\u2019s 1974 painting: a laser from Earth lighting the mirror ball', '1974', 'NASA illustration MSFC-74-PD-3300', 'NASA/Marshall'),
    ('LAGEOS-NASA.jpg', 'The satellite: 426 mirrors on a two-foot ball', '1976', 'NASA photograph', 'NASA'),
    ('url:https://nssdc.gsfc.nasa.gov/planetary/image/lageos.jpg|https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=1976-039A', 'Setting the mirrors, one by one, in the clean room', '1976', 'NASA photograph', 'NASA'),
    ('url:https://nssdc.gsfc.nasa.gov/planetary/image/lageos_1_plaque.jpg|https://nssdc.gsfc.nasa.gov/nmc/spacecraft/display.action?id=1976-039A', 'Carl Sagan\u2019s plaque on board: the continents 268 million years ago, today, and 8.4 million years ahead', '1976', 'plaque by Carl Sagan', 'NASA NSSDCA'),
    ('LAGEOS-1 encapsulation.jpg', 'LAGEOS 1 in the nose of its Delta rocket, Vandenberg, 1976', '1976', 'NASA photograph', 'NASA'),
]
# MORE (user 2026-11-04: "can you find more photos for LAGEOS"): LAGEOS 2 and its flight; the stations that range it
SETS['lageos2'] = [
    ('url:https://ilrs.gsfc.nasa.gov/images/lageosII.jpg|https://ilrs.gsfc.nasa.gov/missions/satellite_missions/current_missions/lag2_general.html', 'LAGEOS 2 on its mount before flight', '1992', 'NASA photograph', 'NASA ILRS'),
    ("STS052-80-008 - STS-052 - STS-52 deployment of LAGEOS-IRIS spacecraft from OV-102's payload bay - DPLA - cb8debdf995c92d10077a3422a6cd869.jpg",
     'Raised out of Columbia\u2019s payload bay on its Italian booster', '1992-10-23', 'STS-52 crew photograph', 'NASA'),
    ('STS-52 LAGEOS-II deployment.jpg', 'Released: LAGEOS 2 leaves Columbia', '1992-10-23', 'STS-52 crew photograph', 'NASA'),
    ("STS052-80-033 - STS-052 - STS-52 deployment of LAGEOS-IRIS spacecraft from OV-102's payload bay - DPLA - 9a8cf17a0f5c4cf2aa4429d106fedc92.jpg",
     'Climbing away above the shuttle', '1992-10-23', 'STS-52 crew photograph', 'NASA'),
    ('STS052-80-044 - STS-052 - STS-52 LAGEOS-IRIS spacecraft drifting over the Earth - DPLA - e62214e86d42e80b7c9865e8c93792ed.jpg',
     'The speck drifting away over Earth, bound for 3,600 miles up', '1992-10-23', 'STS-52 crew photograph', 'NASA'),
]
SETS['lageos_ground'] = [
    ('Goddard Spaceflight Center Laser Ranging Facility.jpg', 'NASA Goddard\u2019s laser ranging station, Greenbelt, Maryland', '2010-09-27', 'NASA photograph', 'NASA'),
    ('Milky Way and NASA Satellite Laser Ranging at HartRAO - Gauteng, South Africa - 11 Aug. 2013.jpg', 'NASA\u2019s laser at HartRAO, South Africa, crossing the Milky Way', '2013-08-11', 'photograph', 'Meraj Chhaya \u00b7 CC BY 2.0'),
    ('Wettzell Laser Ranging System.jpg', 'The Wettzell laser ranging telescope, Bavaria', '2008-09-13', 'photograph', 'H. Raab \u00b7 CC BY-SA 3.0'),
    ('Mount Stromlo satellite laser ranging facility 02.jpg', 'Mount Stromlo laser ranging, Canberra', '2014-09-17', 'photograph', 'Mitch Ames \u00b7 CC BY-SA 4.0'),
]
HEROES = {'planck': 'Model of the Planck Satellite.jpg', 'herschel': 'Model of the Herschel space telescope.jpg', 'smart1': 'SMART-1 is packed as it will be for launch ESA228534.jpg', 'rosetta': 'Rosetta Electrical Qualification Model at ESOC.jpg', 'huygens': 'Huygens Titan Lander (5951413737).jpg', 'mir': 'Mir STS-89.jpg', 'luna': 'Luna-9 (Memorial Museum of Astronautics).JPG', 'venera': 'Cut-away model of a Soviet Venera 12 lander.jpg', 'lageos': 'Laser Geodynamics Satellite I (5278072466).jpg', 'tiros1': 'TIROS-1 satellite.png', 'erts1': 'Landsat-1.jpg', 'tiros9': 'TIROS IX Spac0021-repair.jpg', 'seasat': 'Seasat in orbit.jpg',
          'explorer6': 'Explorer 6 paddles up.jpg', 'ats1': 'Applications Technology Satellite 1 (ATS 1).jpg', 'ats3': 'Applications Technology Satellite 3 (ATS 3).png',
          'lo1': 'Lunar Orbiter.jpg', 'goes': 'SMS 1 satellite.jpg', 'nimbus7': 'Nimbus rendering.jpg', 'corona': 'Kh-4b corona.jpg'}


def publish(path):
    """PHOTOS LIVE ON R2 (user 2026-10-23: "move the other archive photos to cloudflare too"): the picture goes up as
    probes/<name>-<sha1[:8]>.webp with a year-long immutable cache (a re-bake changes the hash, so never a stale copy), the
    local file is deleted, and the manifest stores the hashed name (the page reads cdn.bluishvoid.com/probes/<file>)."""
    import hashlib, subprocess
    h = hashlib.sha1(path.read_bytes()).hexdigest()[:8]; name = path.stem + '-' + h + '.webp'
    subprocess.run(['rclone', 'copyto', str(path), 'r2:bluishvoid-bg/probes/' + name, '--s3-no-check-bucket',
                    '--header-upload', 'Cache-Control: public, max-age=31536000, immutable', '--header-upload', 'Content-Type: image/webp'], check=True)
    path.unlink()
    return name


def uploaded(e):
    import re
    return bool(re.search(r'-[0-9a-f]{8}\.webp$', e.get('file', '')))


def info(titles):
    u = ('https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=url&iiurlwidth=1280&format=json&titles='
         + urllib.parse.quote('|'.join('File:' + t for t in titles)))
    j = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60))
    out = {}
    for p in j['query']['pages'].values():
        ii = (p.get('imageinfo') or [{}])[0]
        out[p['title'][5:]] = (ii.get('thumburl') or ii.get('url'), ii.get('descriptionurl'))
    return out


def fetch(url):
    for i in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=90).read()
        except Exception:
            time.sleep(15 * (i + 1))                                  # Commons answers 429 to a quick burst
    raise RuntimeError('could not fetch ' + url)


def save(raw, path, side):
    im = Image.open(io.BytesIO(raw))
    if im.mode in ('I;16', 'I;16B', 'I'):   # 16-bit grayscale: convert('RGB') clips it to white (Luna 3 close-up, 11-12)
        im = im.point(lambda v: v / 256).convert('L')
    im = im.convert('RGB'); im.thumbnail((side, side), Image.LANCZOS)
    im.save(path, 'WEBP', quality=82, method=6)


def main():
    man = json.loads((OUT / 'probes.json').read_text())
    names = [t.split('|')[0][6:] if t.startswith('video:') else t for s in SETS.values() for t, *_ in s if not t.startswith('url:')] + list(HEROES.values())
    I = {}
    for k in range(0, len(names), 10): I.update(info(names[k:k + 10]))
    for key, rows in SETS.items():
        have = man['sets'].get(key) or []
        if len(have) == len(rows) and all(uploaded(e) for e in have):
            print(key, 'kept'); continue                              # already baked: Commons rate-limits quick bursts
        entries = []
        for n, (t, title, date, inst, credit) in enumerate(rows, 1):
            if t.startswith('video:'):
                # A NEWSREEL CLIP: the satellite's part only, silent H.264 (the panel's videos autoplay muted, with no controls)
                import subprocess
                name, a, b = t[6:].split('|')
                q = json.load(urllib.request.urlopen(urllib.request.Request('https://commons.wikimedia.org/w/api.php?action=query&prop=videoinfo&viprop=url|derivatives&format=json&titles='
                              + urllib.parse.quote('File:' + name), headers=UA), timeout=60))['query']['pages'].popitem()[1]['videoinfo'][0]
                ds = sorted([d for d in q.get('derivatives', []) if 'webm' in d.get('type', '') and 360 <= d.get('height', 0) <= 720], key=lambda d: d['height'])
                src = OUT / ('_' + key + '.webm'); src.write_bytes(fetch(ds[-1]['src'] if ds else q['url']))
                f = '%s_%02d.mp4' % (key, n); poster = '%s_%02d.webp' % (key, n)
                subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', a, '-to', b, '-i', str(src), '-an', '-vf', 'scale=640:-2', '-c:v', 'libx264', '-crf', '26',
                                '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(OUT / f)], check=True)
                png = OUT / ('_' + key + '.png')
                subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-ss', '%.1f' % min(22, (float(b) - float(a)) / 2), '-i', str(OUT / f), '-frames:v', '1', str(png)], check=True)
                save(png.read_bytes(), OUT / poster, 900); png.unlink(); poster = publish(OUT / poster)
                src.unlink()
                # THE CLIP LIVES ON R2 (user 2026-10-23: "should archive clips be saved on cloudflare" -> yes): uploaded under a
                # versioned name with a year-long immutable cache (bump VER to replace one), then deleted here; only the
                # poster stays in the repo
                VER = 'v1'
                subprocess.run(['rclone', 'copyto', str(OUT / f), 'r2:bluishvoid-bg/archive/%s-%s.mp4' % (f[:-4], VER), '--s3-no-check-bucket',
                                '--header-upload', 'Cache-Control: public, max-age=31536000, immutable', '--header-upload', 'Content-Type: video/mp4'], check=True)
                (OUT / f).unlink(); f = 'https://cdn.bluishvoid.com/archive/%s-%s.mp4' % (f[:-4], VER)
                entries.append({'file': poster, 'video': f, 'title': title, 'date': date, 'target': 'Earth', 'instrument': inst,
                                'credit': credit, 'source_url': q['descriptionurl']})
                print(key, f, title); continue
            url, page = t[4:].split('|') if t.startswith('url:') else I[t]; f = '%s_%02d.webp' % (key, n)
            save(fetch(url), OUT / f, 900); time.sleep(3); f = publish(OUT / f)
            entries.append({'file': f, 'title': title, 'date': date, 'target': 'Earth', 'instrument': inst,
                            'credit': credit if '\u00b7' in credit else credit + ' · public domain', 'source_url': page})   # a credit naming its own licence keeps it
            print(key, f, title)
        man['sets'][key] = entries
    for key, t in HEROES.items():
        if (HERE / 'sprites' / (key + '.webp')).exists(): continue
        url, _ = I[t]; save(fetch(url), HERE / 'sprites' / (key + '.webp'), 700); time.sleep(3)
        print('hero', key)
    (OUT / 'probes.json').write_text(json.dumps(man, indent=1, ensure_ascii=False))


if __name__ == '__main__':
    main()

"""Plan des territoires précalculé pour la carte (chargement rapide, mêmes données que le KMZ).

La carte lisait territoires_chasse.kmz (18 Mo de KML) à chaque ouverture : décompression puis analyse XML
dans la WebView, 8 à 9 s sur tablette. Ce script fait ce travail une fois, sur le PC :
  assets/plan/territoires.bin   points en microdegrés, Int32 petit-boutiste, paires (latitude, longitude)
  assets/plan/territoires.json  pour chaque territoire : id, nom, province, catégorie et anneaux (début, longueur)
Règles reprises à l'identique de map.js (loadKMZ / readRing) ; la catégorie est calculée par territory-geometry.js
lui-même (Node), pour rester exactement celle de l'application.
Les coordonnées du plan ont au plus 6 décimales : le stockage en microdegrés est sans perte.

Usage : python tools/build-plan-binary.py   (relancé par tools/update-plan.py après chaque nouveau plan)
"""
import json
import math
import re
import struct
import subprocess
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'app/src/main/assets'
KMZ = ASSETS / 'territoires_chasse.kmz'
OUT = ASSETS / 'plan'


def local(tag):
    return tag.rsplit('}', 1)[-1]


def children(node, name):
    return [c for c in node if local(c.tag) == name]


def descendants(node, name):
    return [c for c in node.iter() if c is not node and local(c.tag) == name]


def text_content(node):
    return ''.join(node.itertext()) if node is not None else ''


def read_ring(boundary):
    """map.js researchRing : premier <coordinates>, points « lng,lat[,alt] », valeurs finies et dans les bornes."""
    if boundary is None:
        return []
    coords = descendants(boundary, 'coordinates')
    raw = text_content(coords[0]).strip() if coords else ''
    if not raw:
        return []
    ring = []
    for item in re.split(r'\s+', raw):
        parts = item.split(',')
        try:
            lng, lat = float(parts[0]), float(parts[1]) if len(parts) > 1 else float('nan')
        except ValueError:
            continue
        if math.isfinite(lat) and math.isfinite(lng) and abs(lat) <= 90 and abs(lng) <= 180:
            ring.append((lat, lng))
    return ring


def micro(value):
    scaled = round(value * 1_000_000)
    if abs(scaled / 1_000_000 - value) > 1e-9:
        sys.exit(f'Coordonnée à plus de 6 décimales : {value!r} (stockage en microdegrés impossible sans perte)')
    return scaled


def placemarks(kml_root):
    """Placemarks dans l'ordre du document, avec la chaîne « folder » de map.js (dossiers du plus proche au plus lointain)."""
    found = []

    def walk(node, folders):
        name = local(node.tag)
        if name == 'Placemark':
            found.append((node, ''.join(folders)))
            return
        if name == 'Folder':
            label = next((text_content(c) for c in node if local(c.tag) == 'name'), 'undefined')
            folders = [' ' + label] + folders
        for child in node:
            walk(child, folders)

    walk(kml_root, [])
    return found


def main():
    with zipfile.ZipFile(KMZ) as zf:
        kml_name = next(n for n in zf.namelist() if n.lower().endswith('.kml'))
        root = ET.fromstring(zf.read(kml_name))
    entries, points = [], []
    for index, (pm, folder) in enumerate(placemarks(root)):
        # map.js : getElementsByTagName('name')[0], premier <name> descendant dans l'ordre du document.
        raw_name = text_content(next(iter(descendants(pm, 'name')), None)).strip() or 'Territoire'
        description = text_content(next(iter(descendants(pm, 'description')), None))
        polygons = []
        for polygon in descendants(pm, 'Polygon'):
            outer = read_ring(next(iter(descendants(polygon, 'outerBoundaryIs')), None))
            if len(outer) < 3:
                continue
            holes = [r for r in (read_ring(b) for b in descendants(polygon, 'innerBoundaryIs')) if len(r) >= 3]
            rings = []
            for ring in [outer] + holes:
                rings.append([len(points), len(ring)])
                points.extend((micro(lat), micro(lng)) for lat, lng in ring)
            polygons.append(rings)
        if not polygons:
            continue
        holder = re.search(r'^AMODIATAIR:\s*(.+)$', description, re.I | re.M)
        province = re.search(r'^PROVINCE:\s*(.+)$', description, re.I | re.M)
        entries.append({'id': pm.get('id') or f'zone-{index}', 'name': holder.group(1).strip() if holder else raw_name,
                        'province': province.group(1).strip() if province else '', 'p': polygons,
                        '_category': [raw_name, description, folder]})

    # Catégorie calculée par le code de l'application (territory-geometry.js).
    script = ("const g=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>"
              "process.stdout.write(JSON.stringify(JSON.parse(s).map(a=>g.category(a[0],a[1],a[2])))));")
    result = subprocess.run(['node', '-e', script, str(ASSETS / 'territory-geometry.js')], check=True,
                            input=json.dumps([e.pop('_category') for e in entries]).encode(), capture_output=True)
    for entry, category in zip(entries, json.loads(result.stdout)):
        entry['category'] = category

    OUT.mkdir(exist_ok=True)
    (OUT / 'territoires.bin').write_bytes(b''.join(struct.pack('<ii', lat, lng) for lat, lng in points))
    (OUT / 'territoires.json').write_text(json.dumps({'version': 1, 'points': len(points), 'territories': entries},
                                                     ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'{len(entries)} territoires, {len(points)} points -> {OUT}')
    # Chevauchements lots / réserves, calculés une fois ici avec le code de map.js (3 s épargnées à l'ouverture).
    subprocess.run(['node', str(ROOT / 'tools/plan-overlaps.cjs')], check=True)
    write_version()


def write_version():
    """Empreinte du plan (plan/version.json) : l'app la compare à celle publiée sur GitHub pour savoir
    si un plan plus récent existe. Même contenu → même identifiant ; la date sert à ne jamais revenir en arrière."""
    import datetime, hashlib
    digest = hashlib.sha256((OUT / 'territoires.json').read_bytes() + (OUT / 'territoires.bin').read_bytes()).hexdigest()
    index = json.loads((OUT / 'territoires.json').read_text(encoding='utf-8'))
    zones = len(index['territories'])
    reserves = sum(1 for t in index['territories'] if t.get('category') in ('Réserve', 'Jeu A', 'Jeu B'))
    version = {'id': digest, 'date': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
               'zones': zones, 'reserves': reserves}
    (OUT / 'version.json').write_text(json.dumps(version, ensure_ascii=False), encoding='utf-8')
    print(f'Version du plan : {digest[:12]} ({zones} zones, {reserves} réserves)')


if __name__ == '__main__':
    main()

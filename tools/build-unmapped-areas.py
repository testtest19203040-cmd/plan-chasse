"""Generate a display-only gap overlay; never infer hunting permission from absent data.
Rebuild when territoires_chasse.kmz changes.
Deps: shapely==2.1.2, pyshp==2.3.1 installed under .artifacts/geo-tools.
Input: Natural Earth 5.1.1 admin-0 countries ZIP under .artifacts.
"""
import hashlib, io, json, sys, zipfile
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".artifacts/geo-tools"))
import shapefile
from shapely import make_valid
from shapely.geometry import shape, Polygon, mapping
from shapely.ops import unary_union

plan = ROOT / "app/src/main/assets/territoires_chasse.kmz"
with zipfile.ZipFile(ROOT / ".artifacts/ne_10m_admin_0_countries.zip") as archive:
    def component(ext):
        return io.BytesIO(archive.read(next(n for n in archive.namelist() if n.endswith(ext))))
    reader = shapefile.Reader(shp=component(".shp"), shx=component(".shx"), dbf=component(".dbf"), encoding="utf-8")
    # Requested presentation footprint: both source features dissolved, with no internal border.
    selected = [make_valid(shape(r.shape.__geo_interface__)) for r in reader.iterShapeRecords()
                if r.record.as_dict()["ADM0_A3"] in ("MAR", "SAH")]
    assert len(selected) == 2, "Unexpected source footprint"
    footprint = unary_union(selected)

ns = {"k": "http://www.opengis.net/kml/2.2"}
with zipfile.ZipFile(plan) as archive:
    tree = ET.fromstring(archive.read(next(n for n in archive.namelist() if n.lower().endswith(".kml"))))
def ring(element):
    return [tuple(map(float, token.split(",")[:2])) for token in element.text.split()]
territories = []
for polygon in tree.findall(".//k:Polygon", ns):
    outer = polygon.find("k:outerBoundaryIs/k:LinearRing/k:coordinates", ns)
    holes = polygon.findall("k:innerBoundaryIs/k:LinearRing/k:coordinates", ns)
    outer_ring = ring(outer)
    if len(outer_ring) < 3: continue
    inner_rings = [coords for hole in holes if len(coords := ring(hole)) >= 3]
    territories.append(make_valid(Polygon(outer_ring, inner_rings)))
covered = unary_union(territories)
gaps = make_valid(footprint.difference(covered))
assert gaps.is_valid and not gaps.is_empty
assert gaps.intersection(covered).area < 1e-8, "Grey overlaps a plan territory"
assert gaps.difference(footprint).area < 1e-8, "Grey extends outside footprint"
assert footprint.difference(unary_union([covered, gaps])).area < 1e-8, "Coverage incomplete"
data = {
    "type": "Feature",
    "properties": {
        "kind": "outside_imported_plan",
        "huntingPermission": "unknown",
        "name": "Zone hors du plan — statut de chasse à vérifier",
        "source": "Natural Earth admin-0 countries 5.1.1, 1:10m; custom dissolved display footprint",
        "sourceUrl": "https://www.naturalearthdata.com/downloads/10m-cultural-vectors/10m-admin-0-countries/",
        "planSha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "precisionNote": "Generalized display boundary, not a regulatory or cadastral boundary."
    },
    "geometry": mapping(gaps)
}
output = ROOT / "app/src/main/assets/unmapped-areas.geojson"
output.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
print(json.dumps({"planPolygons":len(territories),"greyPolygons":len(gaps.geoms) if hasattr(gaps,"geoms") else 1,"assetBytes":output.stat().st_size,"geometryChecks":"passed"}))

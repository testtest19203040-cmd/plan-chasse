"""
Export des zones de chasse (Amodiations de chasse, Jeux de reserve, etc.)
depuis le service ArcGIS de l'Agence Nationale des Eaux et Forets
vers un fichier KMZ ouvrable dans Google Earth / une appli Android.

INSTALLATION (une seule fois) :
    pip install requests simplekml

UTILISATION :
    python export_kmz_chasse.py

Copie du script du propriétaire (D:/project/PLANCHASSE), avec nouvelles tentatives en cas de coupure.
Utilisé par tools/update-plan.py ; écrit territoires_chasse.kmz dans le dossier courant.
"""

import requests
import simplekml
import urllib3

# Certains réseaux (antivirus, proxy d'entreprise) interceptent le HTTPS et
# cassent la vérification du certificat. On désactive donc la vérification
# stricte pour ce site public - risque acceptable ici, données publiques.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
VERIFY_SSL = False

# Le serveur coupe parfois la connexion : nouvelles tentatives automatiques (copie locale du script).
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
_session = requests.Session()
_session.mount("https://", HTTPAdapter(max_retries=Retry(total=8, connect=8, read=8, backoff_factor=2,
    status_forcelist=(429, 500, 502, 503, 504), allowed_methods=("GET",))))
_plain_get = requests.get
def _get(*args, **kwargs):
    for attempt in range(6):
        try:
            return _session.get(*args, **kwargs)
        except requests.exceptions.ConnectionError:
            if attempt == 5:
                raise
            import time; time.sleep(5 * (attempt + 1))
requests.get = _get

BASE = "https://sigdef.eauxetforets.gov.ma/server/rest/services/AMODIATIONS/TMP_AMODIATIONS/MapServer"

# Tolérance de simplification des contours, en degrés.
# 0.0001° ~ 11 m : invisible à l'usage normal (chasse/navigation),
# mais réduit énormément le nombre de points -> fichier bien plus léger.
SIMPLIFY_EPSILON = 0.0001

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Referer": "https://sigdef.eauxetforets.gov.ma/",
}


def _perpendicular_distance(pt, start, end):
    x, y = pt
    x1, y1 = start
    x2, y2 = end
    if (x1, y1) == (x2, y2):
        return ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
    num = abs((y2 - y1) * x - (x2 - x1) * y + x2 * y1 - y2 * x1)
    den = ((y2 - y1) ** 2 + (x2 - x1) ** 2) ** 0.5
    return num / den


def rdp_simplify(points, epsilon):
    """Simplification de Douglas-Peucker (pure Python, itérative, sans
    dépendance). Réduit le nombre de points d'un contour tout en gardant
    sa forme globale. epsilon est en degrés (0.0001° ~ 11 m)."""
    if len(points) < 3:
        return points

    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]

    while stack:
        start_i, end_i = stack.pop()
        if end_i - start_i < 2:
            continue
        start, end = points[start_i], points[end_i]
        dmax = 0.0
        index = start_i
        for i in range(start_i + 1, end_i):
            d = _perpendicular_distance(points[i], start, end)
            if d > dmax:
                index = i
                dmax = d
        if dmax > epsilon:
            keep[index] = True
            stack.append((start_i, index))
            stack.append((index, end_i))

    return [pt for pt, k in zip(points, keep) if k]


def fetch_all_features(url):
    """Récupère toutes les entités d'une couche, au format JSON natif Esri.

    Ce serveur ArcGIS (assez ancien) ne supporte pas la pagination moderne
    (resultOffset/resultRecordCount). On récupère donc d'abord la liste des
    identifiants (objectIds), puis on interroge par lots (IN (...))."""

    # 1. Récupérer tous les identifiants d'entités
    id_params = {
        "where": "1=1",
        "returnIdsOnly": "true",
        "f": "json",
    }
    resp = requests.get(
        url, headers=HEADERS, params=id_params, timeout=60, verify=VERIFY_SSL
    )
    resp.raise_for_status()
    id_data = resp.json()
    if "error" in id_data:
        raise RuntimeError(id_data["error"])

    object_ids = id_data.get("objectIds") or []
    id_field = id_data.get("objectIdFieldName", "OBJECTID")

    if not object_ids:
        # Pas d'ids -> essai simple direct (petites couches)
        params = {"where": "1=1", "outFields": "*", "f": "json", "outSR": 4326}
        resp = requests.get(
            url, headers=HEADERS, params=params, timeout=120, verify=VERIFY_SSL
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data.get("features", [])

    # 2. Interroger par lots de 200 identifiants
    all_features = []
    batch_size = 200
    for i in range(0, len(object_ids), batch_size):
        batch = object_ids[i : i + batch_size]
        where = f"{id_field} IN ({','.join(str(b) for b in batch)})"
        params = {
            "where": where,
            "outFields": "*",
            "f": "json",
            "outSR": 4326,
        }
        resp = requests.get(
            url, headers=HEADERS, params=params, timeout=120, verify=VERIFY_SSL
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        all_features.extend(data.get("features", []))

    return all_features


def main():
    print("Connexion au service ArcGIS...")
    r = requests.get(f"{BASE}?f=json", headers=HEADERS, timeout=30, verify=VERIFY_SSL)
    r.raise_for_status()
    data = r.json()
    layers = data.get("layers", [])

    if not layers:
        print("Aucune couche trouvée. Vérifiez l'URL du service.")
        return

    print(f"{len(layers)} couches trouvées :")
    for l in layers:
        print(f"  - id {l['id']}: {l['name']} ({l.get('geometryType', '?')})")

    kml = simplekml.Kml()
    exported_any = False

    # Styles partagés (un seul par couche, réutilisé pour toutes ses zones,
    # au lieu d'un style dupliqué pour chacune des ~2000 zones - c'est ce
    # qui faisait exploser la taille du fichier).
    style_amodiations = simplekml.Style()
    style_amodiations.polystyle.fill = 1
    style_amodiations.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.green)
    style_amodiations.linestyle.color = simplekml.Color.green
    style_amodiations.linestyle.width = 1

    style_reserve = simplekml.Style()
    style_reserve.polystyle.fill = 1
    style_reserve.polystyle.color = simplekml.Color.changealphaint(100, simplekml.Color.violet)
    style_reserve.linestyle.color = simplekml.Color.violet
    style_reserve.linestyle.width = 1

    for layer in layers:
        # On ne garde que les couches de type polygone (zones),
        # on saute les routes/points/localités.
        if layer.get("geometryType") != "esriGeometryPolygon":
            continue

        lid = layer["id"]
        lname = layer["name"]
        shared_style = style_amodiations if lid == 8 else style_reserve
        print(f"\nExport de la couche : {lname} (id {lid})...")

        url = f"{BASE}/{lid}/query"
        try:
            features = fetch_all_features(url)
        except Exception as e:
            print(f"  -> Erreur lors de la récupération : {e}")
            continue

        if not features:
            print("  -> Aucune donnée trouvée pour cette couche.")
            continue

        folder = kml.newfolder(name=lname)
        count = 0

        for feat in features:
            geom = feat.get("geometry")
            if not geom or "rings" not in geom:
                continue
            attrs = feat.get("attributes", {}) or {}
            name = str(
                attrs.get("NOM")
                or attrs.get("Nom")
                or attrs.get("nom")
                or attrs.get("NAME")
                or attrs.get("Name")
                or lname
            )
            # Description allégée : on garde seulement les champs utiles
            # (on saute les valeurs vides et les champs techniques Shape_*
            # qui n'apportent rien et alourdissent le fichier).
            desc = "\n".join(
                f"{k}: {v}"
                for k, v in attrs.items()
                if v not in (None, "") and not k.startswith("Shape_")
            )

            rings = geom["rings"]
            if not rings:
                continue

            # Précision à 6 décimales (~11 cm) : largement suffisant, et
            # bien plus compact que la précision brute (jusqu'à 17 chiffres)
            # renvoyée par le serveur.
            def r(pt):
                return (round(pt[0], 6), round(pt[1], 6))

            # Simplification : premier anneau = contour extérieur,
            # les suivants = trous (cas rare pour ces zones).
            # On réduit d'abord le nombre de points (Douglas-Peucker),
            # c'est ce qui fait le plus gagner en taille de fichier.
            outer = rdp_simplify([r(pt) for pt in rings[0]], SIMPLIFY_EPSILON)
            pol = folder.newpolygon(name=name, description=desc)
            pol.outerboundaryis = outer
            if len(rings) > 1:
                pol.innerboundaryis = [
                    rdp_simplify([r(pt) for pt in ring], SIMPLIFY_EPSILON)
                    for ring in rings[1:]
                ]
            pol.style = shared_style
            count += 1

        print(f"  -> {count} zones ajoutées.")
        exported_any = True

    if exported_any:
        out = "territoires_chasse.kmz"
        kml.savekmz(out)
        print(f"\n✅ Terminé ! Fichier généré : {out}")
        print("Transférez ce fichier sur votre téléphone et ouvrez-le avec Google Earth.")
    else:
        print("\nAucune couche polygonale exportée.")


if __name__ == "__main__":
    main()

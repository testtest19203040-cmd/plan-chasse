"""Prépare un plan KMZ exporté du serveur de l'ANEF pour l'application Chasseur.

Usage : python tools/build-plan-kmz.py EXPORT_ANEF.kmz PLAN_APP.kmz

- Donne à chaque zone un identifiant STABLE (le même à chaque export), fondé sur ses données officielles :
    lot      -> lot-<type>-<province>-<amodiataire>      ex. lot-association-el-jadida-rmilia
    réserve  -> res-<numéro>                              ex. res-4b-ej
  Les adhésions, responsables et statuts de territoire enregistrés dans Firebase restent ainsi rattachés
  à la bonne zone d'un export à l'autre (les OBJECTID de l'ANEF changent à chaque publication).
- En cas de doublon (même amodiataire deux fois), ajoute la position du centre : -c32.735_-8.830.
- Vérifie que le plan contient des lots ET des réserves (refuse un export incomplet).
"""
import io, re, sys, unicodedata, zipfile


def slug(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', text).strip('-') or 'x'


def field(desc, key):
    m = re.search(r'(?im)^\s*' + key + r':\s*(.+?)\s*$', desc)
    return m.group(1).strip() if m else ''


def centre(body):
    m = re.search(r'<coordinates>(.*?)</coordinates>', body, re.S)
    pts = [tuple(map(float, p.split(',')[:2])) for p in m.group(1).split()] if m else [(0, 0)]
    return sum(p[1] for p in pts) / len(pts), sum(p[0] for p in pts) / len(pts)


def main(src, dst):
    zin = zipfile.ZipFile(src)
    kml_name = [n for n in zin.namelist() if n.lower().endswith('.kml')][0]
    kml = zin.read(kml_name).decode('utf-8')
    placemarks = list(re.finditer(r'<Placemark(\s+id="[^"]*")?>(.*?)</Placemark>', kml, re.S))
    keys, lots, reserves = [], 0, 0
    for m in placemarks:
        body = m.group(2)
        desc = (re.search(r'<description>(.*?)</description>', body, re.S) or [None, ''])[1] if re.search(r'<description>(.*?)</description>', body, re.S) else ''
        if field(desc, 'AMODIATAIR'):
            lots += 1
            keys.append('lot-' + '-'.join(slug(v) for v in (field(desc, 'TYPE'), field(desc, 'PROVINCE'), field(desc, 'AMODIATAIR'))))
        else:
            reserves += 1
            name = (re.search(r'<name>(.*?)</name>', body, re.S) or [None, ''])[1] if re.search(r'<name>(.*?)</name>', body, re.S) else ''
            keys.append('res-' + slug(field(desc, 'Num') or name))
    if lots == 0 or reserves == 0:
        sys.exit(f'Plan incomplet : {lots} lots, {reserves} réserves. Relancez l’export.')
    # Doublons : on distingue par le centre de la zone.
    counts = {}
    for k in keys:
        counts[k] = counts.get(k, 0) + 1
    final = []
    for k, m in zip(keys, placemarks):
        if counts[k] > 1:
            lat, lon = centre(m.group(2))
            k = f'{k}-c{lat:.3f}_{lon:.3f}'
        final.append(k)
    # Réécriture des balises Placemark avec l'identifiant stable ; une zone publiée deux fois
    # à l'identique par l'ANEF (même nom, même position) n'est gardée qu'une fois.
    out, last, seen, copies = [], 0, set(), 0
    for k, m in zip(final, placemarks):
        out.append(kml[last:m.start()])
        if k in seen:
            copies += 1
        else:
            seen.add(k)
            out.append(f'<Placemark id="{k}">' + m.group(2) + '</Placemark>')
        last = m.end()
    out.append(kml[last:])
    with zipfile.ZipFile(dst, 'w', zipfile.ZIP_DEFLATED) as zout:
        zout.writestr('doc.kml', ''.join(out).encode('utf-8'))
        for n in zin.namelist():
            if n != kml_name:
                zout.writestr(n, zin.read(n))
    print(f'Plan prêt : {dst} — {lots - copies} lots, {reserves} réserves ; {copies} copie(s) identique(s) retirée(s).')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])

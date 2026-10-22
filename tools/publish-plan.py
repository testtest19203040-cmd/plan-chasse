"""Publication automatique du plan de chasse pour la mise à jour des applications (sans nouvelle version des stores).

    python tools/publish-plan.py --from-assets   # publie le plan actuellement intégré dans l'app (premier envoi)
    python tools/publish-plan.py --ci            # chaque nuit (GitHub Actions) : export ANEF, contrôles, publication si changé

Le plan est déposé dans la release « plan-data » du dépôt public, avec manifest.json :
    {"format": 1, "id": "<sha256>", "date": "...Z", "zones": N, "reserves": N,
     "files": {"plan/territoires.bin": {"asset": "territoires.bin.gz", "sha256": "...", "size": N}, ...}}
L'app lit le manifeste au premier lancement de chaque jour, télécharge les fichiers, vérifie les empreintes
puis remplace son plan. Les empreintes portent sur les fichiers décompressés.

Garde-fous (--ci) : aucune publication si l'export est incomplet, si une réserve disparaît, si plus de 2 % des
zones disparaissent, ou si le nombre de zones / réserves tombe sous un minimum. Le job échoue alors : GitHub
envoie un e-mail au propriétaire du dépôt, qui vérifie à la main.
"""
import gzip, hashlib, json, os, re, shutil, subprocess, sys, tempfile, urllib.request, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'app/src/main/assets'
REPO = os.environ.get('PLAN_REPO', 'testtest19203040-cmd/plan-chasse')
TAG = 'plan-data'
RELEASE_URL = f'https://github.com/{REPO}/releases/download/{TAG}/'
# Fichiers du plan dans l'app (chemin relatif aux assets) -> nom de l'asset publié.
FILES = {
    'plan/territoires.bin': 'territoires.bin.gz',
    'plan/territoires.json': 'territoires.json.gz',
    'unmapped-areas.geojson': 'unmapped-areas.geojson.gz',
    'territoires_chasse.kmz': 'territoires_chasse.kmz',
}
MIN_ZONES, MIN_RESERVES, MAX_REMOVED_SHARE = 1500, 300, 0.02


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(args, **kw):
    print('>', ' '.join(str(a) for a in args), flush=True)
    subprocess.run(args, check=True, cwd=ROOT, env=dict(os.environ, PYTHONIOENCODING='utf-8'), **kw)


def kmz_zones(path):
    """Identifiants stables et catégorie (réserve ou lot) de chaque zone du KMZ préparé par build-plan-kmz.py."""
    with zipfile.ZipFile(path) as z:
        kml = z.read(next(n for n in z.namelist() if n.lower().endswith('.kml'))).decode('utf-8')
    return {m.group(1): m.group(1).startswith('res-') for m in re.finditer(r'<Placemark[^>]*\bid="([^"]+)"', kml)}


def previous_manifest():
    try:
        with urllib.request.urlopen(RELEASE_URL + 'manifest.json', timeout=60) as r:
            return json.loads(r.read().decode('utf-8'))
    except Exception as error:
        print(f'Pas de plan publié lisible ({error}) : premier envoi.')
        return None


def build_manifest(out_dir):
    version = json.loads((ASSETS / 'plan/version.json').read_text(encoding='utf-8'))
    manifest = {'format': 1, 'id': version['id'], 'date': version['date'], 'zones': version['zones'],
                'reserves': version['reserves'], 'files': {}}
    for path, asset in FILES.items():
        source = ASSETS / path
        target = out_dir / asset
        if asset.endswith('.gz'):
            with open(source, 'rb') as src, gzip.open(target, 'wb', compresslevel=9) as dst:
                shutil.copyfileobj(src, dst)
        else:
            shutil.copy2(source, target)
        manifest['files'][path] = {'asset': asset, 'sha256': sha256(source), 'size': source.stat().st_size}
    (out_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    return manifest


def publish(out_dir):
    gh = shutil.which('gh') or r'C:\Program Files\GitHub CLI\gh.exe'
    exists = subprocess.run([gh, 'release', 'view', TAG, '-R', REPO], capture_output=True).returncode == 0
    if not exists:
        run([gh, 'release', 'create', TAG, '-R', REPO, '--title', 'Plan de chasse (mise à jour automatique)',
             '--notes', 'Plan lu par l’application au premier lancement de chaque jour. Ne pas supprimer.', '--latest=false'])
    # Les fichiers d'abord, le manifeste en dernier : une app ne voit jamais un manifeste sans ses fichiers.
    assets = [out_dir / a for a in FILES.values()]
    run([gh, 'release', 'upload', TAG, '-R', REPO, '--clobber', *assets])
    run([gh, 'release', 'upload', TAG, '-R', REPO, '--clobber', out_dir / 'manifest.json'])


def safety_checks(new_kmz, old_kmz):
    new = kmz_zones(new_kmz)
    zones, reserves = len(new), sum(new.values())
    problems = []
    if zones < MIN_ZONES: problems.append(f'{zones} zones seulement (minimum {MIN_ZONES})')
    if reserves < MIN_RESERVES: problems.append(f'{reserves} réserves seulement (minimum {MIN_RESERVES})')
    if old_kmz:
        old = kmz_zones(old_kmz)
        removed = [z for z in old if z not in new]
        lost_reserves = [z for z in removed if old[z]]
        if lost_reserves: problems.append(f'{len(lost_reserves)} réserve(s) disparue(s) : {", ".join(lost_reserves[:10])}')
        if len(removed) > MAX_REMOVED_SHARE * len(old):
            problems.append(f'{len(removed)} zones disparues sur {len(old)} (plus de {MAX_REMOVED_SHARE:.0%})')
        print(f'Zones : {len(old)} -> {zones} ; disparues : {len(removed)} ; nouvelles : {len([z for z in new if z not in old])}')
    return problems


def ci():
    work = Path(tempfile.mkdtemp(prefix='plan-'))
    previous = previous_manifest()
    old_kmz = None
    if previous:
        old_kmz = work / 'precedent.kmz'
        urllib.request.urlretrieve(RELEASE_URL + 'territoires_chasse.kmz', old_kmz)
    # Export dans le dossier de travail (le script écrit territoires_chasse.kmz dans le dossier courant).
    subprocess.run([sys.executable, str(ROOT / 'tools/anef-export.py')], check=True, cwd=work,
                   env=dict(os.environ, PYTHONIOENCODING='utf-8'))
    plan = work / 'plan-app.kmz'
    run([sys.executable, ROOT / 'tools/build-plan-kmz.py', work / 'territoires_chasse.kmz', plan])
    problems = safety_checks(plan, old_kmz)
    if problems:
        print('\nPUBLICATION BLOQUÉE — vérification manuelle nécessaire :')
        for p in problems: print(' -', p)
        sys.exit(2)
    shutil.copy2(plan, ASSETS / 'territoires_chasse.kmz')
    run([sys.executable, ROOT / 'tools/build-unmapped-areas.py'])
    run([sys.executable, ROOT / 'tools/build-plan-binary.py'])
    version = json.loads((ASSETS / 'plan/version.json').read_text(encoding='utf-8'))
    if previous and previous.get('id') == version['id']:
        print('Plan identique au plan publié : rien à publier.')
        return
    out = work / 'publication'
    out.mkdir()
    manifest = build_manifest(out)
    publish(out)
    print(f'Nouveau plan publié : {manifest["id"][:12]} ({manifest["zones"]} zones, {manifest["reserves"]} réserves).')


def from_assets():
    out = Path(tempfile.mkdtemp(prefix='plan-pub-'))
    previous = previous_manifest()
    version = json.loads((ASSETS / 'plan/version.json').read_text(encoding='utf-8'))
    if previous and previous.get('id') == version['id']:
        print('Ce plan est déjà publié.')
        return
    problems = safety_checks(ASSETS / 'territoires_chasse.kmz', None)
    if problems:
        sys.exit('Plan de l’app incohérent : ' + '; '.join(problems))
    manifest = build_manifest(out)
    publish(out)
    print(f'Plan publié : {manifest["id"][:12]} ({manifest["zones"]} zones, {manifest["reserves"]} réserves).')


if __name__ == '__main__':
    if '--ci' in sys.argv: ci()
    elif '--from-assets' in sys.argv: from_assets()
    else: print(__doc__)

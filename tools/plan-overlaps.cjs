// Chevauchements lots / zones restreintes précalculés pour la carte (étape de tools/build-plan-binary.py).
// Même calcul que computeLotOverlaps() dans map.js : les fonctions samplePoints() et la règle de sélection
// sont relues dans map.js, contains() vient de territory-geometry.js. Résultat : champ « o » (indices des zones
// chevauchées) sur chaque lot loué, et « overlaps: true » à la racine de assets/plan/territoires.json.
const fs = require('fs');
const path = require('path');

const assets = path.join(__dirname, '..', 'app', 'src', 'main', 'assets');
const geometry = require(path.join(assets, 'territory-geometry.js'));
const source = fs.readFileSync(path.join(assets, 'map.js'), 'utf8');
function grab(name) {
    const start = source.indexOf(name);
    if (start < 0) throw new Error(name + ' introuvable dans map.js');
    let depth = 0;
    for (let k = source.indexOf('{', start); k < source.length; k++) {
        if (source[k] === '{') depth++;
        else if (source[k] === '}' && --depth === 0) return source.slice(start, k + 1);
    }
    throw new Error(name + ' incomplet');
}
const samplePoints = new Function(grab('function samplePoints') + '\nreturn samplePoints;')();
const leased = new Set(JSON.parse(source.match(/const LEASED_LOTS=new Set\((\[[^\]]*\])\)/)[1].replace(/'/g, '"')));

const indexFile = path.join(assets, 'plan', 'territoires.json');
const index = JSON.parse(fs.readFileSync(indexFile, 'utf8'));
const buffer = fs.readFileSync(path.join(assets, 'plan', 'territoires.bin'));
const values = new Int32Array(buffer.buffer, buffer.byteOffset, buffer.byteLength / 4);
const ring = ([start, length]) => {
    const out = new Array(length);
    for (let k = 0, v = start * 2; k < length; k++, v += 2) out[k] = [values[v] / 1e6, values[v + 1] / 1e6];
    return out;
};
const entries = index.territories.map(t => {
    const polygons = t.p.map(rings => rings.map(ring));
    let south = Infinity, north = -Infinity, west = Infinity, east = -Infinity;
    polygons.forEach(rings => rings.forEach(r => r.forEach(([lat, lng]) => {
        south = Math.min(south, lat); north = Math.max(north, lat); west = Math.min(west, lng); east = Math.max(east, lng);
    })));
    return {t, polygons, category: t.category, bounds: {south, north, west, east}};
});
// LatLngBounds.intersects de Leaflet (bords inclus).
const intersects = (a, b) => b.north >= a.south && b.south <= a.north && b.east >= a.west && b.west <= a.east;

const restricted = entries.map((e, i) => [e, i]).filter(([e]) => e.category === 'Réserve' || e.category === 'Jeu A' || e.category === 'Jeu B');
let lots = 0, withOverlap = 0;
entries.forEach(lot => {
    delete lot.t.o;
    if (!leased.has(lot.category)) return;
    lots++;
    const lotPts = samplePoints(lot.polygons, 40);
    const overlaps = restricted.filter(([z]) => intersects(z.bounds, lot.bounds) && (
        lotPts.some(p => geometry.contains(z.polygons, p[0], p[1])) ||
        samplePoints(z.polygons, 80).some(p => geometry.contains(lot.polygons, p[0], p[1])))).map(([, i]) => i);
    lot.t.o = overlaps;
    if (overlaps.length) withOverlap++;
});
index.overlaps = true;
fs.writeFileSync(indexFile, JSON.stringify(index));
console.log(`${lots} lots loués, ${withOverlap} avec chevauchement`);

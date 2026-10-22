// Extrait de la carte de l'application : seule fonction utilisée par tools/plan-overlaps.cjs.
function samplePoints(polygons, max) {
    const ring = polygons[0]?.[0] || [];
    const step = Math.max(1, Math.floor(ring.length / max));
    const pts = [];
    for (let i = 0; i < ring.length; i += step) pts.push(ring[i]);
    return pts;
}

(function(root) {
    function inRing(lat, lng, ring) {
        let inside = false;
        for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
            const a = ring[i], b = ring[j];
            if ((a[0] > lat) !== (b[0] > lat) && lng < (b[1] - a[1]) * (lat - a[0]) / (b[0] - a[0]) + a[1]) inside = !inside;
        }
        return inside;
    }
    function contains(polygons, lat, lng) {
        return polygons.some(rings => inRing(lat, lng, rings[0]) && !rings.slice(1).some(hole => inRing(lat, lng, hole)));
    }
    function category(name, description, folder) {
        const text = (name + ' ' + folder).toLowerCase();
        const type = (description.match(/^TYPE:\s*(.+)$/im)?.[1] || '').trim().toLowerCase();
        if (type === 'rp' || /\brp\b|réserves? permanentes?|reserves? permanentes?|réserve biologique|reserve biologique/.test(text)) return 'Réserve';
        if (/jeu\s*b/i.test(type + ' ' + text)) return 'Jeu B';
        if (/soci[eé]t[eé]|sarl/.test(type)) return 'Société';
        if (/didactique/.test(type + ' ' + text)) return 'Lot didactique';
        if (/immeuble|rural/.test(type)) return 'Immeuble rural';
        if (/provincial/.test(type)) return 'Lot provincial';
        if (/association/.test(type) || /amodiation/.test(text)) return 'Association';
        return 'Territoire';
    }
    const api = { inRing, contains, category };
    if (typeof module !== 'undefined') module.exports = api;
    else root.TerritoryGeometry = api;
})(typeof window !== 'undefined' ? window : globalThis);

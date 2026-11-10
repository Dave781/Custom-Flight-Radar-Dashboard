// Map style: a quiet dark basemap, so the planes are the brightest thing on screen.

export const COLORS = {
    water: '#06111e',
    land: '#1b222c',
    green: '#1a2923',
    aerodrome: '#242d3b',
    runway: '#5b6a83',
    highway: '#3a4658',
    majorRoad: '#283140',
    cityLabel: '#8591a4',
    waterLabel: '#3f6690',
    ring: 'rgba(255, 255, 255, 0.14)',
    ringLabel: 'rgba(255, 255, 255, 0.42)',
    airportLabel: '#a9b8cf',
    approach: 'rgba(160, 180, 210, 0.16)',
    halo: 'rgba(8, 12, 18, 0.9)',
};

const NAME = ['coalesce', ['get', 'name:en'], ['get', 'name']];
const GREEN_KINDS = ['national_park', 'park', 'protected_area', 'nature_reserve', 'forest', 'wood',
    'golf_course', 'cemetery'];

function basemapLayers() {
    const C = COLORS;
    return [
        { id: 'earth', type: 'fill', source: 'basemap', 'source-layer': 'earth',
          filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': C.land } },
        { id: 'landcover', type: 'fill', source: 'basemap', 'source-layer': 'landcover',
          filter: ['in', 'kind', 'forest', 'scrub', 'grassland'],
          paint: { 'fill-color': C.green, 'fill-opacity': ['interpolate', ['linear'], ['zoom'], 5, 0.7, 8, 0.35] } },
        { id: 'green', type: 'fill', source: 'basemap', 'source-layer': 'landuse',
          filter: ['in', 'kind', ...GREEN_KINDS], paint: { 'fill-color': C.green } },
        { id: 'aerodrome', type: 'fill', source: 'basemap', 'source-layer': 'landuse',
          filter: ['==', 'kind', 'aerodrome'], paint: { 'fill-color': C.aerodrome } },
        { id: 'water', type: 'fill', source: 'basemap', 'source-layer': 'water',
          filter: ['==', '$type', 'Polygon'], paint: { 'fill-color': C.water } },
        { id: 'river', type: 'line', source: 'basemap', 'source-layer': 'water', minzoom: 9,
          filter: ['all', ['==', '$type', 'LineString'], ['==', 'kind', 'river']],
          paint: { 'line-color': C.water, 'line-width': ['interpolate', ['linear'], ['zoom'], 9, 0.8, 13, 2.5] } },
        { id: 'pier', type: 'fill', source: 'basemap', 'source-layer': 'landuse', minzoom: 11,
          filter: ['==', 'kind', 'pier'], paint: { 'fill-color': C.land } },
        { id: 'runway-area', type: 'fill', source: 'basemap', 'source-layer': 'landuse', minzoom: 10,
          filter: ['in', 'kind', 'runway', 'taxiway'],
          paint: { 'fill-color': C.runway, 'fill-opacity': 0.55 } },
        { id: 'road-major', type: 'line', source: 'basemap', 'source-layer': 'roads', minzoom: 9.5,
          filter: ['==', 'kind', 'major_road'],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': C.majorRoad, 'line-width': ['interpolate', ['linear'], ['zoom'], 9.5, 0.4, 13, 2] } },
        { id: 'road-highway', type: 'line', source: 'basemap', 'source-layer': 'roads', minzoom: 6,
          filter: ['all', ['==', 'kind', 'highway'], ['!has', 'is_link']],
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': C.highway, 'line-width': ['interpolate', ['linear'], ['zoom'], 6, 0.5, 10, 1.3, 13, 3.2] } },
        { id: 'runway-line', type: 'line', source: 'basemap', 'source-layer': 'roads', minzoom: 10,
          filter: ['==', 'kind_detail', 'runway'],
          paint: { 'line-color': C.runway, 'line-width': ['interpolate', ['linear'], ['zoom'], 10, 1.5, 13, 9] } },
    ];
}

function basemapLabels() {
    const C = COLORS;
    return [
        { id: 'label-lake', type: 'symbol', source: 'basemap', 'source-layer': 'water', minzoom: 8.5,
          filter: ['all', ['==', '$type', 'Point'], ['in', 'kind', 'lake', 'water']],
          layout: { 'text-field': NAME, 'text-font': ['Noto Sans Italic'], 'text-size': 10.5,
                    'text-letter-spacing': 0.08, 'text-max-width': 6, 'text-padding': 40 },
          paint: { 'text-color': C.waterLabel } },
        { id: 'label-city', type: 'symbol', source: 'basemap', 'source-layer': 'places',
          // Zoomed out, only the big cities are named.
          filter: ['all', ['==', ['get', 'kind'], 'locality'],
              ['>=', ['coalesce', ['get', 'population_rank'], 0], ['step', ['zoom'], 9, 8.8, 7, 10.5, 0]]],
          layout: {
              'text-field': NAME,
              'text-font': ['Noto Sans Medium'],
              'text-transform': 'uppercase',
              'text-letter-spacing': 0.12,
              'text-size': ['interpolate', ['linear'], ['coalesce', ['get', 'population_rank'], 5], 5, 9.5, 11, 12.5],
              'text-max-width': 8,
              'text-padding': 26,
              'symbol-sort-key': ['-', 20, ['coalesce', ['get', 'population_rank'], 0]],
          },
          paint: { 'text-color': C.cityLabel, 'text-halo-color': C.halo, 'text-halo-width': 1.4 } },
        { id: 'label-sea', type: 'symbol', source: 'basemap', 'source-layer': 'water',
          filter: ['all', ['==', '$type', 'Point'], ['in', 'kind', 'sea', 'ocean', 'bay', 'strait', 'fjord']],
          layout: { 'text-field': NAME, 'text-font': ['Noto Sans Italic'], 'text-size': 11.5,
                    'text-letter-spacing': 0.12, 'text-max-width': 7, 'text-padding': 12 },
          paint: { 'text-color': C.waterLabel } },
    ];
}

function overlayLayers() {
    const C = COLORS;
    return [
        { id: 'rings', type: 'line', source: 'rings',
          paint: { 'line-color': C.ring, 'line-width': 1, 'line-dasharray': [2, 4] } },
        { id: 'approach', type: 'line', source: 'approach',
          paint: { 'line-color': C.approach, 'line-width': 1, 'line-dasharray': [6, 5] } },
        { id: 'runways', type: 'line', source: 'runways', maxzoom: 10.5,
          layout: { 'line-cap': 'butt' },
          paint: { 'line-color': C.runway, 'line-width': ['interpolate', ['linear'], ['zoom'], 7, 1.2, 10.5, 2.6] } },
        { id: 'trails', type: 'line', source: 'trails',
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: {
              'line-color': ['get', 'color'],
              'line-opacity': ['*', ['get', 'o'], ['case', ['get', 'sel'], 0.95, 0.5]],
              'line-width': ['case', ['get', 'sel'], 2.4, 1.4],
          } },
        { id: 'ring-labels', type: 'symbol', source: 'ring-labels',
          layout: { 'text-field': ['get', 'label'], 'text-font': ['Noto Sans Regular'], 'text-size': 10,
                    'text-allow-overlap': true, 'text-ignore-placement': true },
          paint: { 'text-color': C.ringLabel, 'text-halo-color': C.halo, 'text-halo-width': 1.5 } },
        { id: 'airport-labels', type: 'symbol', source: 'airports',
          filter: ['<=', ['get', 'minzoom'], ['zoom']],
          layout: {
              'text-field': ['get', 'code'],
              'text-font': ['Noto Sans Medium'],
              'text-size': ['case', ['<=', ['get', 'rank'], 1], 12, 10.5],
              'text-letter-spacing': 0.06,
              'text-offset': [0, 0.9],
              'text-anchor': 'top',
              'text-padding': 6,
              'symbol-sort-key': ['get', 'rank'],
          },
          paint: { 'text-color': C.airportLabel, 'text-halo-color': C.halo, 'text-halo-width': 1.6 } },
        { id: 'planes', type: 'symbol', source: 'planes',
          layout: {
              'icon-image': ['get', 'image'],
              'icon-size': ['interpolate', ['linear'], ['zoom'],
                  7, ['*', 0.72, ['get', 'size']],
                  10, ['get', 'size'],
                  13, ['*', 1.3, ['get', 'size']]],
              'icon-rotate': ['get', 'track'],
              'icon-rotation-alignment': 'map',
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'symbol-sort-key': ['get', 'sort'],
          } },
    ];
}

const EMPTY = { type: 'FeatureCollection', features: [] };

export function buildStyle(cfg) {
    const sources = {
        rings: { type: 'geojson', data: EMPTY },
        'ring-labels': { type: 'geojson', data: EMPTY },
        approach: { type: 'geojson', data: EMPTY },
        runways: { type: 'geojson', data: EMPTY },
        airports: { type: 'geojson', data: EMPTY },
        trails: { type: 'geojson', data: EMPTY },
        planes: { type: 'geojson', data: EMPTY },
    };
    let layers = [{ id: 'background', type: 'background',
                    paint: { 'background-color': cfg.has_map ? COLORS.water : COLORS.land } }];
    if (cfg.has_map) {
        sources.basemap = { type: 'vector', url: `pmtiles://${location.origin}/map.pmtiles` };
        layers = layers.concat(basemapLayers(), basemapLabels());
    }
    return {
        version: 8,
        glyphs: `${location.origin}/static/fonts/{fontstack}/{range}.pbf`,
        sources,
        layers: layers.concat(overlayLayers()),
    };
}

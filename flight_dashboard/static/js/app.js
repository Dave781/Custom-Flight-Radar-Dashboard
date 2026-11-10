// Flight radar front end: live map, flight card, today's numbers, alerts.

import * as maplibregl from '/static/vendor/maplibre-gl.mjs';
import { buildStyle } from './style.js';
import {
    ICONS, ICON_PIXEL_RATIO, EMERGENCY_COLOR, ALTITUDE_GRADIENT_CSS,
    altitudeBand, altitudeColor, bandColor, drawIcon, silhouetteSvg,
} from './icons.js';

const cfg = window.RADAR_CONFIG;
const $ = id => document.getElementById(id);

const POLL_MS = 1000;
const PIN_SECONDS = 60;            // a tapped plane stays selected this long
const VIEW_RESET_SECONDS = 45;     // an untouched map returns to the home view
const OFFLINE_AFTER_FAILURES = 5;
const SWITCH_MARGIN_DEG = 8;       // how much higher in the sky another plane must be to take over
const MAX_POSITION_AGE_S = 8;
const APPROACH_MI = 9;
const TRAIL_GAP_SECONDS = 45;    // a longer silence breaks the trail instead of drawing a straight line
const MI_PER_DEG_LAT = 69.0;
const KT_TO_MI_PER_S = 1.15078 / 3600;
const EMERGENCY_SQUAWKS = { '7500': 'Hijack', '7600': 'Radio failure', '7700': 'Emergency' };

const state = {
    planes: new Map(),       // hex -> latest aircraft record
    trails: new Map(),       // hex -> [[lon, lat, altitude, time], ...]
    details: new Map(),      // "hex|callsign" -> { route, photo }
    selected: null,
    pinned: false,
    lastTouch: 0,
    viewMoved: false,
    serverNow: 0,
    failures: 0,
    receiver: null,
    dimMode: 'auto',
    moreOpen: false,
    emergencyShown: null,
};
let map;
let selMarker;
let selLabel;

// ---------- geometry ----------

const milesPerDegLon = lat => MI_PER_DEG_LAT * Math.cos(lat * Math.PI / 180);

function offsetPoint([lon, lat], miles, bearingDeg) {
    const b = bearingDeg * Math.PI / 180;
    return [lon + miles * Math.sin(b) / milesPerDegLon(lat), lat + miles * Math.cos(b) / MI_PER_DEG_LAT];
}

function circle(center, miles, steps = 96) {
    const ring = [];
    for (let i = 0; i <= steps; i++) ring.push(offsetPoint(center, miles, i * 360 / steps));
    return ring;
}

function bearing([lon1, lat1], [lon2, lat2]) {
    const dx = (lon2 - lon1) * milesPerDegLon(lat1);
    const dy = (lat2 - lat1) * MI_PER_DEG_LAT;
    return (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
}

// Sun height above the horizon in degrees (low-precision almanac formula).
function sunAltitude(date, lat, lon) {
    const rad = Math.PI / 180;
    const d = (date.getTime() - Date.UTC(2000, 0, 1, 12)) / 86400000;
    const g = (357.529 + 0.98560028 * d) * rad;
    const L = (280.459 + 0.98564736 * d + 1.915 * Math.sin(g) + 0.020 * Math.sin(2 * g)) * rad;
    const e = (23.439 - 0.00000036 * d) * rad;
    const ra = Math.atan2(Math.cos(e) * Math.sin(L), Math.cos(L));
    const dec = Math.asin(Math.sin(e) * Math.sin(L));
    const gmst = (18.697374558 + 24.06570982441908 * d) % 24;
    const hourAngle = (gmst * 15 + lon) * rad - ra;
    return Math.asin(Math.sin(lat * rad) * Math.sin(dec)
        + Math.cos(lat * rad) * Math.cos(dec) * Math.cos(hourAngle)) / rad;
}

// ---------- formatting ----------

const fmtInt = n => (typeof n === 'number' ? Math.round(n).toLocaleString('en-US') : '–');

function fmtDuration(seconds) {
    if (seconds < 90) return `${Math.round(seconds)} s`;
    if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
    return `${Math.round(seconds / 3600)} h`;
}

// Database names often arrive in capitals ("BOEING 737-990"). Make them readable.
function tidyName(text) {
    if (!text) return '';
    if (text !== text.toUpperCase() || text.length <= 4) return text;
    return text.toLowerCase().replace(/(^|[\s\-/(])([a-z])/g, (m, a, b) => a + b.toUpperCase())
        .replace(/\b(Llc|Inc|Usa|Ii|Iii|Kg)\b/g, w => w.toUpperCase());
}

// Callsigns come off the radio, so they are escaped before going into markup.
const escapeHtml = text => String(text).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

const isEmergency = ac => Boolean(EMERGENCY_SQUAWKS[ac.squawk]);
const altitudeOf = ac => (typeof ac.altitude_baro === 'number' ? ac.altitude_baro : null);
const colorOf = ac => (isEmergency(ac) ? EMERGENCY_COLOR : altitudeColor(altitudeOf(ac)));

// ---------- map ----------

function viewPadding() {
    const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
    const portrait = innerWidth <= 640 && innerHeight > innerWidth;
    if (portrait) return { top: 4 * rem, left: rem, right: rem, bottom: innerHeight * 0.42 };
    return { top: 3.2 * rem, left: 19.5 * rem, right: 1.2 * rem, bottom: 1.2 * rem };
}

function homeView(animate) {
    if (!cfg.home) return;
    const west = offsetPoint(cfg.home, cfg.range_mi, 270);
    const east = offsetPoint(cfg.home, cfg.range_mi, 90);
    const north = offsetPoint(cfg.home, cfg.range_mi, 0);
    const south = offsetPoint(cfg.home, cfg.range_mi, 180);
    map.fitBounds([[west[0], south[1]], [east[0], north[1]]],
        { padding: viewPadding(), duration: animate ? 900 : 0 });
    state.viewMoved = false;
}

function initMap() {
    const canvas = document.createElement('canvas');
    if (!canvas.getContext('webgl2') && !canvas.getContext('webgl')) {
        state.noWebGL = true;      // the map cannot draw; say so instead of showing a blank screen
        return;
    }
    if (cfg.has_map) {
        const protocol = new pmtiles.Protocol();
        maplibregl.addProtocol('pmtiles', protocol.tile);
    }
    map = new maplibregl.Map({
        container: 'map',
        style: buildStyle(cfg),
        center: cfg.home || [-98, 39],
        zoom: cfg.home ? 9 : 3,
        minZoom: 5,
        maxZoom: 13.5,
        dragRotate: false,
        pitchWithRotate: false,
        touchPitch: false,
        attributionControl: false,
        fadeDuration: 150,
    });
    map.touchZoomRotate.disableRotation();
    map.keyboard.disable();
    map.addControl(new maplibregl.AttributionControl({
        compact: true,
        customAttribution: cfg.has_map ? '© OpenStreetMap, Protomaps' : '',
    }), 'bottom-left');
    document.querySelector('.maplibregl-ctrl-attrib')?.classList.remove('maplibregl-compact-show');

    map.on('load', () => {
        homeView(false);
        drawRings();
        loadAirports();
        if (cfg.home) {
            const dot = document.createElement('div');
            dot.className = 'home-dot';
            new maplibregl.Marker({ element: dot }).setLngLat(cfg.home).addTo(map);
        }
        start();
    });

    const touched = () => { state.lastTouch = Date.now(); };
    map.on('movestart', e => { if (e.originalEvent) { state.viewMoved = true; touched(); } });
    map.on('click', e => {
        touched();
        const r = 22;
        const hits = map.queryRenderedFeatures(
            [[e.point.x - r, e.point.y - r], [e.point.x + r, e.point.y + r]], { layers: ['planes'] });
        if (!hits.length) {
            state.pinned = false;
            choose();
            render();
            return;
        }
        let best = hits[0];
        let bestDist = Infinity;
        for (const f of hits) {
            const p = map.project(f.geometry.coordinates);
            const dist = Math.hypot(p.x - e.point.x, p.y - e.point.y);
            if (dist < bestDist) { best = f; bestDist = dist; }
        }
        state.selected = best.properties.hex;
        state.pinned = true;
        render();
    });
    addEventListener('resize', () => { if (!state.viewMoved) homeView(false); });

    const el = document.createElement('div');
    el.className = 'sel';
    el.innerHTML = '<div class="sel-ring"></div><div class="sel-label"></div>';
    selLabel = el.querySelector('.sel-label');
    selMarker = new maplibregl.Marker({ element: el });
}

function drawRings() {
    if (!cfg.home) return;
    map.getSource('rings').setData({
        type: 'FeatureCollection',
        features: cfg.rings_mi.map(mi => ({
            type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: circle(cfg.home, mi) },
        })),
    });
    map.getSource('ring-labels').setData({
        type: 'FeatureCollection',
        features: cfg.rings_mi.map(mi => ({
            type: 'Feature',
            properties: { label: `${mi} mi` },
            geometry: { type: 'Point', coordinates: offsetPoint(cfg.home, mi, 135) },
        })),
    });
}

async function loadAirports() {
    if (!cfg.has_airports) return;
    let airports;
    try {
        airports = await (await fetch('/api/airports')).json();
    } catch { return; }
    const labels = [];
    const runways = [];
    const approach = [];
    for (const ap of airports) {
        const major = ap.type === 'large_airport' || ap.type === 'medium_airport';
        if (!major && !ap.runways.length && ap.type !== 'seaplane_base') continue;
        let rank = 3;
        let minzoom = 10.2;
        if (ap.type === 'large_airport') { rank = 0; minzoom = 0; }
        else if (ap.type === 'medium_airport') { rank = 1; minzoom = ap.scheduled ? 0 : 8.2; }
        else if (ap.iata) { rank = 2; minzoom = 9.2; }
        labels.push({
            type: 'Feature',
            properties: { code: ap.code, rank, minzoom },
            geometry: { type: 'Point', coordinates: [ap.lon, ap.lat] },
        });
        for (const [lat1, lon1, lat2, lon2] of ap.runways) {
            const a = [lon1, lat1];
            const b = [lon2, lat2];
            runways.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [a, b] } });
            if (major) {
                const heading = bearing(a, b);
                approach.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString',
                    coordinates: [offsetPoint(a, APPROACH_MI, heading + 180), a] } });
                approach.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString',
                    coordinates: [b, offsetPoint(b, APPROACH_MI, heading)] } });
            }
        }
    }
    map.getSource('airports').setData({ type: 'FeatureCollection', features: labels });
    map.getSource('runways').setData({ type: 'FeatureCollection', features: runways });
    map.getSource('approach').setData({ type: 'FeatureCollection', features: approach });
}

// ---------- data ----------

async function start() {
    try {
        const trails = await (await fetch('/api/trails')).json();
        for (const [hex, points] of Object.entries(trails)) state.trails.set(hex, points);
    } catch { /* trails rebuild themselves from live data */ }
    poll();
    setInterval(tick, 1000);
}

async function poll() {
    let data = null;
    try {
        const response = await fetch('/api/aircraft', { cache: 'no-store' });
        if (!response.ok) throw new Error(response.status);
        data = await response.json();
        state.failures = 0;
    } catch {
        state.failures += 1;
        renderAlerts();
    }
    if (data) onData(data);
    setTimeout(poll, POLL_MS);
}

function onData(data) {
    state.receiver = data.receiver || null;
    state.serverNow = data.timestamp || Date.now() / 1000;
    state.dataError = data.error || null;

    const seen = new Set();
    for (const ac of data.aircraft || []) {
        const hex = (ac.hex || '').toLowerCase();
        if (!hex) continue;
        seen.add(hex);
        state.planes.set(hex, ac);
        const trail = state.trails.get(hex) || [];
        const last = trail[trail.length - 1];
        if (!last || last[0] !== ac.lon || last[1] !== ac.lat) {
            trail.push([ac.lon, ac.lat, altitudeOf(ac), state.serverNow]);
        }
        const cutoff = state.serverNow - cfg.trail_seconds;
        while (trail.length && trail[0][3] < cutoff) trail.shift();
        state.trails.set(hex, trail);
    }
    for (const hex of [...state.planes.keys()]) {
        if (!seen.has(hex)) { state.planes.delete(hex); state.trails.delete(hex); }
    }

    choose();
    render();
    showEmergency();
    renderToday(data.today);
    renderAlerts();
}

// Where the plane is now: the last report, moved forward by its age.
function drawnPosition(ac) {
    const age = Math.min(ac.seen_pos ?? 0, MAX_POSITION_AGE_S);
    if (!age || typeof ac.ground_speed !== 'number' || typeof ac.heading !== 'number') return [ac.lon, ac.lat];
    return offsetPoint([ac.lon, ac.lat], ac.ground_speed * KT_TO_MI_PER_S * age, ac.heading);
}

// ---------- selection ----------

// Left alone, the card follows the plane highest in the sky, the one you would look up and see.
function choose() {
    const current = state.planes.get(state.selected);
    if (state.pinned && current) return;
    state.pinned = false;

    let best = null;
    for (const ac of state.planes.values()) {
        if (isEmergency(ac)) { best = ac; break; }
        if (ac.distance_mi == null || ac.distance_mi > cfg.range_mi) continue;
        if (!best || (ac.elevation_deg ?? 0) > (best.elevation_deg ?? 0)) best = ac;
    }
    if (!cfg.home && !best) best = state.planes.values().next().value || null;

    if (current && best && current !== best && !isEmergency(best)
        && current.distance_mi != null && current.distance_mi <= cfg.range_mi
        && (best.elevation_deg ?? 0) < (current.elevation_deg ?? 0) + SWITCH_MARGIN_DEG) {
        return;     // not enough of a change to swap the card
    }
    state.selected = best ? best.hex.toLowerCase() : null;
}

// An emergency far from the antenna would be off the screen. Widen the view to show it.
function showEmergency() {
    const ac = [...state.planes.values()].find(isEmergency);
    const hex = ac ? ac.hex.toLowerCase() : null;
    if (hex === state.emergencyShown) return;
    state.emergencyShown = hex;
    if (!ac || !cfg.home) { if (!state.viewMoved) homeView(true); return; }
    if (map.getBounds().contains([ac.lon, ac.lat])) return;
    const reach = Math.max(cfg.range_mi, ac.distance_mi * 1.15);
    const west = offsetPoint(cfg.home, reach, 270);
    const east = offsetPoint(cfg.home, reach, 90);
    const north = offsetPoint(cfg.home, reach, 0);
    const south = offsetPoint(cfg.home, reach, 180);
    map.fitBounds([[west[0], south[1]], [east[0], north[1]]], { padding: viewPadding(), duration: 900 });
}

function tick() {
    const idle = (Date.now() - state.lastTouch) / 1000;
    if (state.pinned && idle > PIN_SECONDS) { state.pinned = false; choose(); render(); }
    if (state.viewMoved && idle > VIEW_RESET_SECONDS && !state.emergencyShown) homeView(true);
    applyDim();
}

// ---------- rendering ----------

// Plane icons are drawn the first time a shape and altitude band is needed.
function iconFor(kind, band) {
    const name = `${kind}-${band}`;
    if (!map.hasImage(name)) {
        map.addImage(name, drawIcon(kind, bandColor(band)), { pixelRatio: ICON_PIXEL_RATIO });
    }
    return name;
}

function render() {
    renderMap();
    renderCard();
}

function renderMap() {
    const planes = [];
    const trails = [];
    for (const [hex, ac] of state.planes) {
        const selected = hex === state.selected;
        const kind = ICONS[ac.icon] ? ac.icon : 'jet';
        const position = drawnPosition(ac);
        planes.push({
            type: 'Feature',
            properties: {
                hex,
                image: iconFor(kind, isEmergency(ac) ? 'em' : altitudeBand(altitudeOf(ac))),
                track: ac.heading ?? 0,
                size: ICONS[kind].size * (selected ? 1.2 : 1),
                sort: selected ? 1 : 0,
            },
            geometry: { type: 'Point', coordinates: position },
        });

        // The trail is cut into short pieces so each can fade with its age.
        const points = state.trails.get(hex) || [];
        const CHUNK = 4;
        let start = 0;
        for (let i = 1; i <= points.length; i++) {
            const gap = i < points.length && points[i][3] - points[i - 1][3] > TRAIL_GAP_SECONDS;
            const last = i === points.length;
            if (!gap && !last && i - start < CHUNK) continue;
            const part = points.slice(start, last || gap ? i : i + 1);
            const line = part.map(p => [p[0], p[1]]);
            if (last) line.push(position);
            if (line.length > 1) {
                const mid = part[part.length >> 1];
                const fresh = Math.max(0, 1 - (state.serverNow - mid[3]) / cfg.trail_seconds);
                trails.push({
                    type: 'Feature',
                    properties: {
                        color: isEmergency(ac) ? EMERGENCY_COLOR : altitudeColor(mid[2]),
                        o: Math.pow(fresh, 1.7),
                        sel: selected,
                    },
                    geometry: { type: 'LineString', coordinates: line },
                });
            }
            start = i;
        }
    }
    map.getSource('planes').setData({ type: 'FeatureCollection', features: planes });
    map.getSource('trails').setData({ type: 'FeatureCollection', features: trails });

    const ac = state.planes.get(state.selected);
    if (ac) {
        selMarker.setLngLat(drawnPosition(ac)).addTo(map);
        selMarker.getElement().style.setProperty('--accent', colorOf(ac));
        if (selLabel.textContent !== ac.callsign) selLabel.textContent = ac.callsign;
    } else {
        selMarker.remove();
    }
}

function setText(id, text) {
    const el = $(id);
    if (el.textContent !== text) el.textContent = text;
}

function renderCard() {
    const ac = state.planes.get(state.selected);
    $('card').hidden = !ac;
    const empty = $('empty');
    empty.hidden = Boolean(ac) || !cfg.home;
    if (!ac) {
        setText('empty', state.planes.size ? `Nothing within ${cfg.range_mi} mi` : 'No planes in range');
        return;
    }
    const color = colorOf(ac);
    $('card').style.setProperty('--accent', color);

    setText('callsign', ac.callsign);
    const badge = $('badge');
    const emergency = EMERGENCY_SQUAWKS[ac.squawk];
    const label = emergency ? ac.squawk : ac.aircraft_class === 'military' ? 'MIL'
        : ac.aircraft_class === 'heavy' ? 'HEAVY' : '';
    badge.hidden = !label;
    badge.textContent = label;
    badge.className = emergency ? 'emergency' : ac.aircraft_class;
    $('pin').hidden = !state.pinned;

    const details = detailsFor(ac);
    const operator = ac.airline || (details && details.route && details.route.airline) || '';
    setText('who', [tidyName(operator), tidyName(ac.aircraft_type)].filter(Boolean).join(' · '));

    const route = details && details.route;
    $('route').hidden = !route;
    if (route) {
        setText('route-from', route.origin.code);
        setText('route-to', route.destination.code);
        $('route').title = `${route.origin.city || route.origin.name} to ${route.destination.city || route.destination.name}`;
    }

    setText('alt', fmtInt(altitudeOf(ac)));
    const vs = $('vs');
    const rate = typeof ac.vertical_rate === 'number' ? ac.vertical_rate : 0;
    vs.textContent = rate > 100 ? '↑' : rate < -100 ? '↓' : '';
    vs.className = `vs ${rate > 100 ? 'up' : rate < -100 ? 'down' : ''}`;
    setText('spd', fmtInt(ac.ground_speed));

    const look = $('look');
    look.hidden = ac.bearing_deg == null;
    if (ac.bearing_deg != null) {
        $('compass-arrow').style.transform = `rotate(${ac.bearing_deg}deg)`;
        setText('look-dir', ac.bearing_cardinal || '');
        setText('look-up', ac.elevation_deg != null ? `${ac.elevation_deg}° up` : '');
    }

    setText('m-reg', ac.registration || '–');
    setText('m-age', ac.built ? String(ac.built).slice(0, 4) : '–');
    setText('m-squawk', ac.squawk || '–');
    setText('m-vrate', typeof ac.vertical_rate === 'number'
        ? `${rate > 0 ? '+' : ''}${fmtInt(rate)} fpm` : '–');
    setText('m-heading', typeof ac.heading === 'number' ? `${Math.round(ac.heading)}°` : '–');
    setText('m-dist', ac.distance_mi != null ? `${ac.distance_mi.toFixed(1)} mi` : '–');

    renderPhoto(ac, details && details.photo);
}

function renderPhoto(ac, photo) {
    const link = $('photo');
    const img = $('photo-img');
    const silhouette = $('silhouette');
    const kind = ICONS[ac.icon] ? ac.icon : 'jet';
    if (silhouette.dataset.kind !== kind) {
        silhouette.dataset.kind = kind;
        silhouette.innerHTML = silhouetteSvg(kind);
    }
    if (!photo) {
        link.hidden = true;
        silhouette.hidden = false;
        img.removeAttribute('src');
        img.dataset.src = '';
        return;
    }
    if (img.dataset.src !== photo.src) {
        // Keep the silhouette up until the picture has loaded.
        img.dataset.src = photo.src;
        link.hidden = true;
        silhouette.hidden = false;
        img.onload = () => {
            if (img.dataset.src !== photo.src) return;
            link.hidden = false;
            silhouette.hidden = true;
        };
        img.onerror = () => { link.hidden = true; silhouette.hidden = false; };
        img.src = photo.src;
        link.href = photo.link || '#';
        setText('photo-by', photo.by ? `© ${photo.by}` : '');
    }
}

// Route and photo come from outside services, so ask once per aircraft and callsign.
function detailsFor(ac) {
    if (!cfg.lookups) return null;
    const key = `${ac.hex}|${ac.callsign}`;
    if (state.details.has(key)) return state.details.get(key);
    state.details.set(key, null);
    const query = new URLSearchParams({ callsign: ac.callsign, lat: ac.lat, lon: ac.lon });
    if (altitudeOf(ac) != null) query.set('alt', altitudeOf(ac));
    fetch(`/api/flight/${ac.hex}?${query}`)
        .then(r => r.json())
        .then(d => { state.details.set(key, d); if (state.selected === ac.hex.toLowerCase()) renderCard(); })
        .catch(() => { setTimeout(() => state.details.delete(key), 30000); });
    if (state.details.size > 400) state.details.delete(state.details.keys().next().value);
    return null;
}

function renderToday(today) {
    const box = $('today');
    const show = Boolean(today && today.count);
    box.hidden = !show;
    document.body.classList.toggle('has-today', show);
    if (!show) return;
    setText('t-count', fmtInt(today.count));
    const fill = (boxId, id, record) => {
        $(boxId).hidden = !record;
        if (!record) return;
        setText(id, fmtInt(record.value));
        $(boxId).title = `${$(boxId).title.split(':')[0]}: ${record.callsign}`;
    };
    fill('t-far-box', 't-far', today.farthest);
    fill('t-high-box', 't-high', today.highest);
    fill('t-fast-box', 't-fast', today.fastest);
}

function renderAlerts() {
    const alerts = [];
    if (state.noWebGL) {
        alerts.push(['setup', 'This browser cannot draw the map. Turn on WebGL (hardware acceleration) and reload.']);
    } else if (!cfg.home) {
        alerts.push(['setup', 'Set <code>HOME_LAT</code> and <code>HOME_LON</code> in <code>.env</code>, then restart.']);
    } else if (!cfg.has_map) {
        alerts.push(['setup', 'No map yet. Run <code>python3 download_map.py</code>, then restart.']);
    }
    for (const ac of state.planes.values()) {
        if (isEmergency(ac)) alerts.push(['danger', escapeHtml(`${ac.squawk} · ${ac.callsign} · ${EMERGENCY_SQUAWKS[ac.squawk]}`)]);
    }
    if (state.failures >= OFFLINE_AFTER_FAILURES) {
        alerts.push(['warn', 'Dashboard offline']);
    } else if (state.receiver && state.receiver.state === 'down') {
        alerts.push(['warn', `Decoder offline · ${fmtDuration(state.receiver.quiet_seconds)}`]);
    } else if (state.receiver && state.receiver.state === 'stalled') {
        alerts.push(['warn', `No signal · ${fmtDuration(state.receiver.quiet_seconds)}`]);
    }
    const html = alerts.map(([kind, text]) => `<div class="alert ${kind}">${text}</div>`).join('');
    const box = $('alerts');
    if (box.dataset.html !== html) {
        box.dataset.html = html;
        box.innerHTML = html;
    }
}

// ---------- night dimming ----------

// Kiosk launchers often screenshot a page just after opening it to confirm that it drew.
// A dimmed, empty map is close to a flat dark screen, so dimming waits until that check is over.
const DIM_DELAY_MS = 90000;

function applyDim() {
    let dim = state.dimMode === 'on';
    if (state.dimMode === 'auto' && cfg.home) {
        dim = sunAltitude(new Date(), cfg.home[1], cfg.home[0]) < -4;
    }
    if (performance.now() < DIM_DELAY_MS) dim = false;
    document.body.classList.toggle('dimmed', dim);
    $('btn-dim').classList.toggle('on', dim);
    setText('dim-mode', state.dimMode === 'auto' ? 'A' : '');
}

function initControls() {
    try { state.dimMode = localStorage.getItem('dimMode') || 'auto'; } catch { /* private mode */ }
    $('btn-dim').addEventListener('click', () => {
        state.dimMode = { auto: 'on', on: 'off', off: 'auto' }[state.dimMode];
        try { localStorage.setItem('dimMode', state.dimMode); } catch { /* private mode */ }
        applyDim();
    });
    $('btn-home').addEventListener('click', () => { if (map) homeView(true); });
    $('pin').addEventListener('click', () => { state.pinned = false; choose(); render(); });
    $('more-btn').addEventListener('click', () => {
        state.moreOpen = !state.moreOpen;
        $('more').hidden = !state.moreOpen;
        $('more-btn').setAttribute('aria-expanded', String(state.moreOpen));
        state.lastTouch = Date.now();
    });
    document.documentElement.style.setProperty('--alt-gradient', ALTITUDE_GRADIENT_CSS);
    applyDim();
}

// ?scale=1.25 makes everything a quarter larger, for screens read from across a room.
const scale = Number(new URLSearchParams(location.search).get('scale'));
if (scale > 0.5 && scale < 4) document.documentElement.style.fontSize = `${16 * scale}px`;

initControls();
initMap();
renderAlerts();
// For poking at the page from the browser console, e.g. radar.select('aca948').
window.radar = {
    map,
    state,
    select(hex) { state.selected = hex; state.pinned = true; state.lastTouch = Date.now(); render(); },
};

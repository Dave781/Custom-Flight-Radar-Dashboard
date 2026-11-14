// Plane silhouettes and the altitude color scale.

// Top-down outlines in a 32 x 32 box, nose pointing up.
const JET = 'M16 2.2c.9 0 1.6 1.5 1.6 3.6v6.3l10.9 6.6c.3.2.5.5.5.9v1.2c0 .3-.3.5-.6.4l-10.8-3.3v6.1l3.1 2.4c.2.2.3.4.3.7v.9c0 .3-.3.5-.6.4L16 27.2l-4.4 1.6c-.3.1-.6-.1-.6-.4v-.9c0-.3.1-.5.3-.7l3.1-2.4v-6.1L3.6 21.6c-.3.1-.6-.1-.6-.4V20c0-.4.2-.7.5-.9l10.9-6.6V5.8c0-2.1.7-3.6 1.6-3.6z';

export const ICONS = {
    jet: { fill: JET, size: 0.82 },
    heavy: {
        fill: 'M16 1c1.1 0 1.9 1.7 1.9 4v6.6l12.3 7.4c.5.3.8.8.8 1.4v1.3c0 .4-.4.7-.8.6L18 18.6v6.6l3.9 2.7c.3.2.5.6.5 1v.8c0 .4-.4.7-.8.5L16 28.5l-5.6 1.7c-.4.1-.8-.1-.8-.5v-.8c0-.4.2-.8.5-1l3.9-2.7v-6.6L1.8 22.3c-.4.1-.8-.2-.8-.6v-1.3c0-.6.3-1.1.8-1.4l12.3-7.4V5c0-2.3.8-4 1.9-4z'
            + 'M8.3 12.8h1.7v3.4H8.3zM22 12.8h1.7v3.4H22zM4.6 15.2h1.6v3.2H4.6zM25.8 15.2h1.6v3.2h-1.6z',
        size: 1.0,
    },
    prop: {
        fill: 'M16 3c.9 0 1.5.9 1.5 2.4V10h11.2c.7 0 1.3.6 1.3 1.3v1.9c0 .7-.6 1.3-1.3 1.3H17.5l-.5 9.5h4c.6 0 1 .4 1 1v1.2c0 .6-.4 1-1 1h-4.3l-.7 1.8-.7-1.8H11c-.6 0-1-.4-1-1V25c0-.6.4-1 1-1h4l-.5-9.5H3.3c-.7 0-1.3-.6-1.3-1.3v-1.9c0-.7.6-1.3 1.3-1.3h11.2V5.4C14.5 3.9 15.1 3 16 3z',
        size: 0.7,
    },
    helicopter: {
        fill: 'M16 6.5c2.4 0 4 2.3 4 5.7 0 2.9-1.2 5.2-2.9 6.1l-.3 8.2h3c.5 0 .9.4.9.9s-.4.9-.9.9h-7.6c-.5 0-.9-.4-.9-.9s.4-.9.9-.9h3l-.3-8.2c-1.7-.9-2.9-3.2-2.9-6.1 0-3.4 1.6-5.7 4-5.7z',
        stroke: 'M5 1.5l22 21M27 1.5l-22 21',
        size: 0.74,
    },
    military: {
        fill: 'M16 1.5c.8 0 1.4 1.2 1.6 3l.9 7.5 10.2 9.6c.3.3.5.7.5 1.1v1.5c0 .4-.3.6-.7.5l-9.6-2.4-.4 3.4 3 2.3c.3.2.4.5.4.8v.7c0 .4-.4.6-.7.5L16 28.8l-5.2 1.2c-.3.1-.7-.1-.7-.5v-.7c0-.3.1-.6.4-.8l3-2.3-.4-3.4-9.6 2.4c-.4.1-.7-.1-.7-.5v-1.5c0-.4.2-.8.5-1.1L13.5 12l.9-7.5c.2-1.8.8-3 1.6-3z',
        size: 0.86,
    },
};

// Altitude in feet -> color. Low is warm, high is cool, and every stop is bright
// enough to read on the dark map.
const STOPS = [
    [0, [255, 140, 66]],
    [3000, [255, 190, 50]],
    [8000, [244, 224, 77]],
    [14000, [123, 216, 143]],
    [22000, [46, 196, 182]],
    [32000, [78, 168, 222]],
    [42000, [179, 136, 235]],
];
export const BAND_FT = 1000;
export const EMERGENCY_COLOR = '#ff453a';
const UNKNOWN_COLOR = '#c5ccd6';

export function altitudeColor(feet) {
    if (typeof feet !== 'number' || Number.isNaN(feet)) return UNKNOWN_COLOR;
    const ft = Math.max(STOPS[0][0], Math.min(STOPS[STOPS.length - 1][0], feet));
    for (let i = 1; i < STOPS.length; i++) {
        if (ft <= STOPS[i][0]) {
            const [a, ca] = STOPS[i - 1];
            const [b, cb] = STOPS[i];
            const k = (ft - a) / (b - a);
            const mix = j => Math.round(ca[j] + (cb[j] - ca[j]) * k);
            return `rgb(${mix(0)}, ${mix(1)}, ${mix(2)})`;
        }
    }
    return UNKNOWN_COLOR;
}

// Icons are drawn once per (shape, altitude band) and cached by the map.
export function altitudeBand(feet) {
    if (typeof feet !== 'number' || Number.isNaN(feet)) return 'x';
    return String(Math.max(0, Math.min(42, Math.round(feet / BAND_FT))));
}

export function bandColor(band) {
    if (band === 'em') return EMERGENCY_COLOR;
    if (band === 'x') return UNKNOWN_COLOR;
    return altitudeColor(Number(band) * BAND_FT);
}

export const ALTITUDE_GRADIENT_CSS =
    `linear-gradient(90deg, ${STOPS.filter(s => s[0] <= 40000).map(s => `rgb(${s[1].join(',')}) ${(s[0] / 400).toFixed(1)}%`).join(', ')}, ${altitudeColor(40000)} 100%)`;

const BOX = 32;
const PIXELS = 80;            // drawn size
export const ICON_PIXEL_RATIO = 2;

export function drawIcon(kind, color) {
    const icon = ICONS[kind] || ICONS.jet;
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = PIXELS;
    const ctx = canvas.getContext('2d');
    const scale = (PIXELS - 16) / BOX;
    ctx.translate(8, 8);
    ctx.scale(scale, scale);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    const fill = new Path2D(icon.fill);

    // Dark edge so the plane reads against roads, trails, and other planes.
    ctx.shadowColor = 'rgba(0, 0, 0, 0.6)';
    ctx.shadowBlur = 5;
    ctx.strokeStyle = 'rgba(6, 10, 15, 0.95)';
    ctx.lineWidth = 2.4;
    ctx.stroke(fill);
    ctx.shadowBlur = 0;
    ctx.fillStyle = color;
    ctx.fill(fill);

    if (icon.stroke) {
        const blades = new Path2D(icon.stroke);
        ctx.strokeStyle = 'rgba(6, 10, 15, 0.9)';
        ctx.lineWidth = 3.4;
        ctx.stroke(blades);
        ctx.strokeStyle = color;
        ctx.lineWidth = 1.7;
        ctx.stroke(blades);
    }
    return ctx.getImageData(0, 0, PIXELS, PIXELS);
}

export function silhouetteSvg(kind) {
    const icon = ICONS[kind] || ICONS.jet;
    const blades = icon.stroke
        ? `<path d="${icon.stroke}" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/>`
        : '';
    return `<svg viewBox="0 0 32 32" style="color:inherit"><path d="${icon.fill}"/>${blades}</svg>`;
}

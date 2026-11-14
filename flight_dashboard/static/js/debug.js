// Details page: receiver numbers, setup status, the max-age setting, and every contact's raw fields.

const $ = id => document.getElementById(id);
const dash = '–';
const num = (v, digits = 0) => (typeof v === 'number'
    ? v.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : dash);
const text = v => (v === null || v === undefined || v === '' ? dash : String(v));
const escapeHtml = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

function fmtDuration(seconds) {
    if (seconds < 90) return `${Math.round(seconds)} s`;
    if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
    return `${Math.round(seconds / 3600)} h`;
}

function renderReceiver(receiver) {
    const pill = $('d-state');
    if (!receiver) { pill.textContent = ''; return; }
    const labels = {
        ok: 'Receiving',
        stalled: `No signal · ${fmtDuration(receiver.quiet_seconds)}`,
        down: `Decoder offline · ${fmtDuration(receiver.quiet_seconds)}`,
    };
    pill.textContent = labels[receiver.state] || receiver.state;
    pill.className = `pill ${receiver.state === 'ok' ? 'ok' : 'warn'}`;
    $('d-rate').textContent = num(receiver.rate);
}

function renderToday(today) {
    if (!today) return;
    $('d-today').textContent = num(today.count);
    const record = (id, r, unit) => {
        $(id).textContent = r ? `${num(r.value)} ${unit}` : dash;
        $(`${id}-who`).textContent = r ? r.callsign : '';
    };
    record('d-far', today.farthest, 'mi');
    record('d-high', today.highest, 'ft');
    record('d-fast', today.fastest, 'kt');
}

function renderRows(aircraft) {
    $('d-now').textContent = num(aircraft.length);
    if (!aircraft.length) {
        $('rows').innerHTML = '<tr><td class="none" colspan="17">No contacts</td></tr>';
        return;
    }
    $('rows').innerHTML = aircraft.map(ac => {
        const emergency = ['7500', '7600', '7700'].includes(ac.squawk);
        const cells = [
            ['strong', text(ac.callsign)],
            ['', text(ac.icao_hex)],
            ['', text(ac.registration)],
            ['', text(ac.typecode || ac.aircraft_type)],
            ['r', num(ac.altitude_baro)],
            ['r', num(ac.altitude_gps)],
            ['r', num(ac.ground_speed)],
            ['r', typeof ac.heading === 'number' ? `${Math.round(ac.heading)}°` : dash],
            ['r', num(ac.vertical_rate)],
            ['', text(ac.squawk)],
            ['r', num(ac.distance_mi, 1)],
            ['r', ac.bearing_deg != null ? `${Math.round(ac.bearing_deg)}° ${ac.bearing_cardinal16 || ''}` : dash],
            ['r', ac.elevation_deg != null ? `${ac.elevation_deg}°` : dash],
            ['r', num(ac.rssi, 1)],
            ['r', num(ac.messages)],
            ['r', num(ac.seen, 1)],
            ['', `${ac.lat.toFixed(4)}, ${ac.lon.toFixed(4)}`],
        ];
        return `<tr class="${emergency ? 'emergency' : ''}">${cells.map(([cls, v]) =>
            `<td class="${cls}">${escapeHtml(v)}</td>`).join('')}</tr>`;
    }).join('');
}

function renderSetup(status) {
    const c = status.config;
    const file = (info, fix) => (info
        ? [`${info.size}, downloaded ${info.updated}`, false]
        : [`missing. Run <code>${fix}</code>`, true]);
    const rows = [
        ['Data source', [status.source ? escapeHtml(status.source) : 'aircraft.json not found', !status.source]],
        ['Antenna location', [c.home ? 'set' : 'not set. Add <code>HOME_LAT</code> and <code>HOME_LON</code> to <code>.env</code>', !c.home]],
        ['Map', file(status.map_file, 'python3 download_map.py')],
        ['Airports', file(status.airports_file, 'python3 download_map.py')],
        ['Aircraft database', status.aircraft_db
            ? [`${num(status.aircraft_db)} airframes`, false]
            : ['missing. Run <code>python3 download_db.py</code>', true]],
        ['Route and photo lookups', [c.lookups ? 'on' : 'off', false]],
        ['Map range', [`${c.range_mi} mi, rings at ${c.rings_mi.join(', ')}`, false]],
        ['No-signal alert after', [fmtDuration(status.stall_seconds), false]],
    ];
    $('setup').innerHTML = rows.map(([k, [v, bad]]) =>
        `<dt>${k}</dt><dd class="${bad ? 'bad' : ''}">${v}</dd>`).join('');
}

async function pollAircraft() {
    try {
        const data = await (await fetch('/api/aircraft', { cache: 'no-store' })).json();
        renderReceiver(data.receiver);
        renderToday(data.today);
        renderRows(data.aircraft || []);
    } catch { /* keep the last rows on a dropped request */ }
    setTimeout(pollAircraft, 2000);
}

async function pollStatus() {
    try {
        renderSetup(await (await fetch('/api/status', { cache: 'no-store' })).json());
    } catch { /* try again next round */ }
    setTimeout(pollStatus, 15000);
}

async function initThreshold() {
    const slider = $('threshold');
    const label = $('threshold-value');
    const show = v => { label.textContent = `${v} s`; };
    try {
        const current = await (await fetch('/api/settings/seen-threshold')).json();
        slider.value = current.seen_threshold;
        show(current.seen_threshold);
    } catch { /* leave the default */ }
    slider.addEventListener('input', () => show(slider.value));
    slider.addEventListener('change', () => {
        fetch('/api/settings/seen-threshold', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value: Number(slider.value) }),
        });
    });
}

initThreshold();
pollAircraft();
pollStatus();

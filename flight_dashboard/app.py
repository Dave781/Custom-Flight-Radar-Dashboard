#!/usr/bin/env python3
"""
ADS-B Flight Dashboard
Reads local dump1090 aircraft data and displays overhead flights
Enriches data with aircraft database lookups
"""

from flask import Flask, render_template, jsonify, request, send_file, abort
import json
import os
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from demo import DEMO_HOME, demo_snapshot
from geo import bearing_deg, distance_mi, elevation_deg
from lookups import Lookups, route_is_plausible
from tracker import Tracker

app = Flask(__name__)

def _load_dotenv(path):
    """Minimal .env loader (KEY=VALUE lines) so the app needs no extra dependency."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ.setdefault(key.strip(), value.strip().strip('"\''))
    except FileNotFoundError:
        pass


def _env_float(name):
    value = os.environ.get(name, '').strip()
    try:
        return float(value) if value else None
    except ValueError:
        return None


_load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

# Configuration
DEMO_MODE = os.environ.get('DEMO_MODE', 'false').lower() == 'true'
DEMO_SCENARIO = os.environ.get('DEMO_SCENARIO', '')    # emergency, stalled, or empty
seen_threshold = int(os.environ.get('SEEN_THRESHOLD', 120))
DASHBOARD_TITLE = os.environ.get('DASHBOARD_TITLE', "Dave's ADS-B Radar")

# Antenna location: set HOME_LAT / HOME_LON in the environment or in .env
# (kept out of source so the antenna's position isn't published).
HOME_LAT = _env_float('HOME_LAT')
HOME_LON = _env_float('HOME_LON')
if DEMO_MODE and (HOME_LAT is None or HOME_LON is None):
    HOME_LAT, HOME_LON = DEMO_HOME
HOME_SET = HOME_LAT is not None and HOME_LON is not None
if not HOME_SET:
    print("WARNING: HOME_LAT/HOME_LON not set; the map, distance and bearing will be blank. "
          "Copy .env.example to .env and fill them in.")

# Map view
MAP_RANGE_MI = float(os.environ.get('MAP_RANGE_MI', 25))      # miles from the antenna to the screen edge
RANGE_RINGS_MI = [float(x) for x in os.environ.get('RANGE_RINGS_MI', '5,10,20').split(',') if x.strip()]
TRAIL_SECONDS = int(os.environ.get('TRAIL_SECONDS', 300))
STALL_SECONDS = int(os.environ.get('STALL_SECONDS', 180))     # no new messages for this long = receiver stalled
MAP_CLOSE_SECONDS = int(os.environ.get('MAP_CLOSE_SECONDS', 60))   # untouched map returns to the main view; 0 = stay open

# Route and photo lookups (adsbdb.com, planespotters.net). Set LOOKUPS=false to stay offline.
LOOKUPS_ENABLED = os.environ.get('LOOKUPS', 'true').lower() == 'true'
CONTACT_URL = os.environ.get('CONTACT_URL', 'https://github.com/Dave781/Custom-Flight-Radar-Dashboard')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
AIRCRAFT_DB_FILE = os.path.join(DATA_DIR, 'aircraft_db.json')
MAP_FILE = os.path.join(DATA_DIR, 'map.pmtiles')
AIRPORTS_FILE = os.path.join(DATA_DIR, 'airports.json')
DUMP1090_DIR = "/run/dump1090"

# dump1090-fa stores aircraft data here
AIRCRAFT_JSON_PATHS = [
    "/run/dump1090-fa/aircraft.json",
    "/run/dump1090/aircraft.json",
    "/var/run/dump1090-fa/aircraft.json",
]

# Airline ICAO codes to names
AIRLINE_NAMES = {
    'UAL': 'United Airlines', 'DAL': 'Delta Air Lines', 'AAL': 'American Airlines',
    'SWA': 'Southwest Airlines', 'JBU': 'JetBlue Airways', 'ASA': 'Alaska Airlines',
    'FFT': 'Frontier Airlines', 'NKS': 'Spirit Airlines', 'HAL': 'Hawaiian Airlines',
    'VRD': 'Virgin America', 'SKW': 'SkyWest Airlines', 'RPA': 'Republic Airways',
    'ENY': 'Envoy Air', 'PDT': 'Piedmont Airlines', 'AWI': 'Air Wisconsin',
    'BAW': 'British Airways', 'DLH': 'Lufthansa', 'AFR': 'Air France',
    'KLM': 'KLM', 'UAE': 'Emirates', 'QTR': 'Qatar Airways', 'SIA': 'Singapore Airlines',
    'ANA': 'All Nippon Airways', 'JAL': 'Japan Airlines', 'CPA': 'Cathay Pacific',
    'ACA': 'Air Canada', 'QFA': 'Qantas', 'VIR': 'Virgin Atlantic',
}

# Load aircraft database
aircraft_db = {}

def setup_dump1090_directory():
    """Ensure /run/dump1090 directory exists with proper permissions"""
    try:
        # Check if directory exists
        if not os.path.exists(DUMP1090_DIR):
            print(f"[SETUP] Creating {DUMP1090_DIR}")
            # Need sudo to create in /run
            subprocess.run(['sudo', 'mkdir', '-p', DUMP1090_DIR], 
                         check=True, capture_output=True)
        
        # Ensure fr24 user owns it (needed for dump1090 to write)
        try:
            result = subprocess.run(['sudo', 'chown', 'fr24:fr24', DUMP1090_DIR], 
                                  check=True, capture_output=True)
            print(f"[SETUP] Set ownership of {DUMP1090_DIR} to fr24:fr24")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"[SETUP] Warning: Could not set fr24 ownership (may not be needed)")
        
        # Make readable by others so Flask app can read it
        try:
            subprocess.run(['sudo', 'chmod', '755', DUMP1090_DIR], 
                         check=True, capture_output=True)
            print(f"[SETUP] Set permissions on {DUMP1090_DIR} to 755")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"[SETUP] Warning: Could not set directory permissions")
        
        print(f"[SETUP] {DUMP1090_DIR} is ready")
        return True
    except Exception as e:
        print(f"[SETUP] Error setting up {DUMP1090_DIR}: {e}")
        print(f"[SETUP] The directory may need manual setup with:")
        print(f"       sudo mkdir -p {DUMP1090_DIR}")
        print(f"       sudo chown fr24:fr24 {DUMP1090_DIR}")
        print(f"       sudo chmod 755 {DUMP1090_DIR}")
        return False

def load_aircraft_db():
    global aircraft_db
    if os.path.exists(AIRCRAFT_DB_FILE):
        try:
            with open(AIRCRAFT_DB_FILE, 'r') as f:
                aircraft_db = json.load(f)
            print(f"[LOAD] Loaded {len(aircraft_db)} aircraft from database")
        except Exception as e:
            print(f"[LOAD] Failed to load aircraft database: {e}")

def find_aircraft_json():
    """Find the aircraft.json file from dump1090"""
    for path in AIRCRAFT_JSON_PATHS:
        if os.path.exists(path):
            return path
    return None

def get_airline_name(callsign):
    """Extract airline name from callsign"""
    if not callsign or len(callsign) < 3:
        return None
    prefix = callsign[:3].upper()
    return AIRLINE_NAMES.get(prefix)

def calculate_age(built_year):
    """Calculate aircraft age from built year"""
    if not built_year:
        return None
    try:
        year = int(built_year[:4]) if len(built_year) >= 4 else int(built_year)
        return datetime.now().year - year
    except:
        return None

def get_aircraft_data():
    """Read aircraft data from local dump1090 JSON file"""
    if DEMO_MODE:
        return demo_snapshot(time.time(), DEMO_SCENARIO)

    json_path = find_aircraft_json()

    if not json_path:
        return {"error": "aircraft.json not found. Run with DEMO_MODE=true to test.", "aircraft": [], "now": 0}

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"error": str(e), "aircraft": [], "now": 0}

HEAVY_TYPECODES = {
    'B741', 'B742', 'B744', 'B748', 'BLCF', 'B762', 'B763', 'B764', 'B772', 'B773', 'B77L', 'B77W',
    'B778', 'B779', 'B788', 'B789', 'B78X', 'A306', 'A310', 'A332', 'A333', 'A338', 'A339', 'A342',
    'A343', 'A345', 'A346', 'A359', 'A35K', 'A388', 'MD11', 'DC10', 'A124', 'A225', 'IL76', 'A400',
    'C5', 'C5M', 'C17', 'K35R', 'KC10', 'E3TF', 'E3CF', 'E6', 'B52',
}
HELICOPTER_TYPECODES = {
    'A109', 'A119', 'A139', 'A169', 'AS32', 'AS50', 'AS55', 'AS65', 'B06', 'B06T', 'B205', 'B212',
    'B407', 'B412', 'B429', 'B430', 'B47G', 'B505', 'BK17', 'EC20', 'EC25', 'EC30', 'EC35', 'EC45',
    'EC55', 'EC75', 'EN28', 'EN48', 'G2CA', 'H47', 'H53', 'H60', 'H64', 'H500', 'MD52', 'MD60',
    'R22', 'R44', 'R66', 'S61', 'S76', 'S92', 'UH1', 'V22',
}
PROP_TYPECODES = {
    'AA5', 'AC11', 'AT43', 'AT45', 'AT72', 'AT75', 'AT76', 'B190', 'B350', 'BE20', 'BE30', 'BE33',
    'BE35', 'BE36', 'BE55', 'BE58', 'BE99', 'BE9L', 'BL8', 'C130', 'C150', 'C152', 'C162', 'C170',
    'C172', 'C177', 'C180', 'C182', 'C185', 'C2', 'C206', 'C208', 'C210', 'C30J', 'C310', 'C340',
    'C402', 'C404', 'C414', 'C421', 'C72R', 'C82R', 'CH7A', 'COL3', 'COL4', 'DA20', 'DA40', 'DA42',
    'DA62', 'DH2T', 'DH3T', 'DH8A', 'DH8B', 'DH8C', 'DH8D', 'DHC2', 'DHC3', 'DHC6', 'E120', 'E2',
    'EVOT', 'G115', 'GLAS', 'KODI', 'LNC4', 'M20P', 'M20T', 'M7', 'P210', 'P28A', 'P28B', 'P28R',
    'P3', 'P32R', 'P46T', 'P68', 'PA12', 'PA18', 'PA22', 'PA24', 'PA31', 'PA32', 'PA34', 'PA38',
    'PA44', 'PA46', 'PC12', 'PC6T', 'RV10', 'RV12', 'RV6', 'RV7', 'RV8', 'S22T', 'SF34', 'SR20',
    'SR22', 'SW4', 'T206', 'T210', 'TBM7', 'TBM8', 'TBM9',
}
CARDINALS_8 = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
CARDINALS_16 = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
                'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW']


def is_military_hex(hex_upper):
    """Military blocks of the ICAO 24-bit address space (US, UK, Australia)."""
    try:
        value = int(hex_upper, 16)
    except ValueError:
        return False
    return (0xAE0000 <= value <= 0xAEFFFF          # US military
            or 0xADF000 <= value <= 0xADFFFF       # US military
            or 0x43C000 <= value <= 0x43CFFF       # UK military
            or 0x7CF800 <= value <= 0x7CFFFE)      # Australian military


def pick_icon(is_military, typecode, adsb_category):
    """Which silhouette the map draws: military, helicopter, heavy, prop, or jet."""
    category = (adsb_category or '').upper()
    if is_military:
        return 'military'
    if typecode in HELICOPTER_TYPECODES or category == 'A7':
        return 'helicopter'
    if typecode in HEAVY_TYPECODES or category == 'A5':
        return 'heavy'
    if typecode in PROP_TYPECODES or category in ('A1', 'B1', 'B4'):
        return 'prop'
    return 'jet'


def enrich_aircraft(aircraft):
    """Add computed fields and database lookups to aircraft data"""
    enriched = []

    for ac in aircraft:
        # Skip aircraft without position
        if 'lat' not in ac or 'lon' not in ac:
            continue

        # Skip aircraft not seen recently
        if ac.get('seen', 0) > seen_threshold:
            continue

        hex_code = ac.get('hex', '').lower()
        callsign = ac.get('flight', '').strip()

        # Basic fields
        ac['callsign'] = callsign or hex_code.upper() or 'Unknown'
        ac['icao_hex'] = hex_code.upper()
        ac['altitude_baro'] = ac.get('alt_baro', ac.get('altitude', None))
        ac['altitude_gps'] = ac.get('alt_geom', None)
        ac['ground_speed'] = ac.get('gs', ac.get('speed', None))
        ac['heading'] = ac.get('track', ac.get('heading', None))
        ac['vertical_rate'] = ac.get('baro_rate', ac.get('vert_rate', 0))
        ac['squawk'] = ac.get('squawk', None)
        ac['rssi'] = ac.get('rssi', None)
        ac['seen'] = ac.get('seen', 0)
        ac['messages'] = ac.get('messages', 0)

        # Vertical status
        vr = ac['vertical_rate']
        if isinstance(vr, (int, float)):
            if vr > 100:
                ac['vertical_status'] = 'CLIMBING'
                ac['vertical_icon'] = '↑'
            elif vr < -100:
                ac['vertical_status'] = 'DESCENDING'
                ac['vertical_icon'] = '↓'
            else:
                ac['vertical_status'] = 'LEVEL'
                ac['vertical_icon'] = '→'
        else:
            ac['vertical_status'] = 'UNKNOWN'
            ac['vertical_icon'] = '?'

        # Database lookup
        # (demo aircraft carry their own record, so demo mode needs no database)
        db_info = ac.pop('_db', None) or aircraft_db.get(hex_code, {})
        adsb_category = ac.get('category')          # ADS-B emitter category, e.g. "A3"
        ac['registration'] = db_info.get('registration') or None
        ac['manufacturer'] = db_info.get('manufacturer') or None
        ac['model'] = db_info.get('model') or None
        ac['typecode'] = db_info.get('typecode') or None
        ac['operator_icao'] = db_info.get('operator') or None
        ac['owner'] = db_info.get('owner') or None
        ac['built'] = db_info.get('built') or None
        ac['category'] = db_info.get('category') or None

        # Computed fields
        ac['airline'] = get_airline_name(callsign) or db_info.get('owner') or None
        ac['age'] = calculate_age(db_info.get('built'))
        if HOME_SET:
            ac['distance_mi'] = round(distance_mi(HOME_LAT, HOME_LON, ac['lat'], ac['lon']), 1)
            # Bearing from antenna to aircraft
            bearing = bearing_deg(HOME_LAT, HOME_LON, ac['lat'], ac['lon'])
            ac['bearing_deg'] = round(bearing, 1)
            ac['bearing_cardinal'] = CARDINALS_8[int((bearing + 22.5) / 45) % 8]          # 8-point
            ac['bearing_cardinal16'] = CARDINALS_16[int((bearing + 11.25) / 22.5) % 16]   # 16-point
            # Angle above the horizon: where to look in the sky
            altitude = ac['altitude_baro'] if isinstance(ac['altitude_baro'], (int, float)) else None
            elevation = elevation_deg(ac['distance_mi'], altitude)
            ac['elevation_deg'] = round(elevation) if elevation is not None else None
        else:
            ac['distance_mi'] = None
            ac['bearing_deg'] = ac['bearing_cardinal'] = ac['bearing_cardinal16'] = None
            ac['elevation_deg'] = None

        # Aircraft type display string
        if ac['manufacturer'] and ac['model']:
            ac['aircraft_type'] = f"{ac['manufacturer']} {ac['model']}"
        elif ac['model']:
            ac['aircraft_type'] = ac['model']
        elif ac['typecode']:
            ac['aircraft_type'] = ac['typecode']
        else:
            ac['aircraft_type'] = None

        # Aircraft classification: military, heavy, or normal
        typecode_upper = (ac['typecode'] or '').upper()
        is_military = is_military_hex(hex_code)
        is_heavy = typecode_upper in HEAVY_TYPECODES
        ac['icon'] = pick_icon(is_military, typecode_upper, adsb_category)

        ac['is_military'] = is_military
        ac['is_heavy'] = is_heavy
        if is_military:
            ac['aircraft_class'] = 'military'
        elif is_heavy:
            ac['aircraft_class'] = 'heavy'
        else:
            ac['aircraft_class'] = 'normal'

        enriched.append(ac)

    # Sort by distance if available, fall back to signal strength
    enriched.sort(key=lambda x: (x['distance_mi'] is None, x.get('distance_mi') or 9999, -(x.get('rssi') or -999)))
    return enriched

def asset_version():
    """Newest edit time of our own page files, used to bust the browser cache after a deploy."""
    newest = 0
    for folder in ('static/js', 'static/css', 'templates'):
        path = os.path.join(BASE_DIR, folder)
        for name in os.listdir(path):
            newest = max(newest, os.path.getmtime(os.path.join(path, name)))
    return int(newest)


def client_config():
    return {
        'title': DASHBOARD_TITLE,
        'home': [HOME_LON, HOME_LAT] if HOME_SET else None,
        'range_mi': MAP_RANGE_MI,
        'rings_mi': RANGE_RINGS_MI,
        'trail_seconds': TRAIL_SECONDS,
        'has_map': os.path.exists(MAP_FILE),
        'has_airports': os.path.exists(AIRPORTS_FILE),
        'lookups': LOOKUPS_ENABLED,
        'demo_mode': DEMO_MODE,
        'close_seconds': MAP_CLOSE_SECONDS,
    }


@app.route('/')
def index():
    """Main view: the primary target and the list of all contacts"""
    return render_template('index.html')

@app.route('/map')
def map_view():
    """Expanded view: the live map, opened from the MAP button on the main view"""
    return render_template('map.html', title=DASHBOARD_TITLE, config=client_config(), v=asset_version())

@app.route('/debug')
def debug():
    """Raw contact table, receiver numbers, and settings"""
    return render_template('debug.html', title=DASHBOARD_TITLE, v=asset_version())

@app.route('/api/aircraft')
def api_aircraft():
    """API endpoint for aircraft data"""
    data = get_aircraft_data()

    if 'error' in data and data['error']:
        data['receiver'] = tracker.receiver_status()
        data['today'] = tracker.today()
        return jsonify(data)

    aircraft = enrich_aircraft(data.get('aircraft', []))

    return jsonify({
        'aircraft': aircraft,
        'total': len(aircraft),
        'timestamp': data.get('now', 0),
        'updated': datetime.now().strftime('%H:%M:%S'),
        'demo_mode': DEMO_MODE,
        'seen_threshold': seen_threshold,
        'dashboard_title': DASHBOARD_TITLE,
        'receiver': tracker.receiver_status(),
        'today': tracker.today(),
    })

@app.route('/api/trails')
def api_trails():
    """Recent track of every aircraft: {hex: [[lon, lat, altitude, time], ...]}"""
    return jsonify(tracker.trails_snapshot())

@app.route('/api/flight/<hex_code>')
def api_flight(hex_code):
    """Route and photo for one aircraft. Looked up when the page selects it."""
    callsign = request.args.get('callsign', '')
    route_job = lookup_pool.submit(lookups.route, callsign)
    photo_job = lookup_pool.submit(lookups.photo, hex_code)
    route, photo = route_job.result(), photo_job.result()
    if route:
        try:
            lat, lon = float(request.args['lat']), float(request.args['lon'])
            altitude = float(request.args['alt']) if request.args.get('alt') else None
        except (KeyError, ValueError):
            route = None
        else:
            if not route_is_plausible(route, lat, lon, altitude):
                route = None
    return jsonify({'route': route, 'photo': photo})

@app.route('/api/airports')
def api_airports():
    if not os.path.exists(AIRPORTS_FILE):
        return jsonify([])
    return send_file(AIRPORTS_FILE, mimetype='application/json', max_age=3600)

@app.route('/api/status')
def api_status():
    """What the debug page shows about the install."""
    def file_info(path):
        if not os.path.exists(path):
            return None
        size = os.path.getsize(path)
        return {'size': f'{size / 1e6:.1f} MB' if size >= 1e6 else f'{size / 1e3:.0f} KB',
                'updated': datetime.fromtimestamp(os.path.getmtime(path)).strftime('%m/%d/%Y')}
    return jsonify({
        'config': client_config(),
        'receiver': tracker.receiver_status(),
        'today': tracker.today(),
        'aircraft_db': len(aircraft_db),
        'map_file': file_info(MAP_FILE),
        'airports_file': file_info(AIRPORTS_FILE),
        'source': 'demo' if DEMO_MODE else find_aircraft_json(),
        'stall_seconds': STALL_SECONDS,
    })

@app.route('/map.pmtiles')
def map_tiles():
    """The basemap. The browser reads it with HTTP range requests."""
    if not os.path.exists(MAP_FILE):
        abort(404)
    return send_file(MAP_FILE, mimetype='application/octet-stream', conditional=True, max_age=3600)

@app.route('/api/settings/seen-threshold', methods=['GET', 'POST'])
def api_seen_threshold():
    global seen_threshold
    if request.method == 'POST':
        value = request.json.get('value')
        if isinstance(value, int) and 10 <= value <= 300:
            seen_threshold = value
    return jsonify({'seen_threshold': seen_threshold})

# Load database on startup
load_aircraft_db()

tracker = Tracker(get_aircraft_data, (HOME_LAT, HOME_LON) if HOME_SET else None,
                  TRAIL_SECONDS, STALL_SECONDS,
                  os.path.join(DATA_DIR, 'today-demo.json' if DEMO_MODE else 'today.json'))
lookups = Lookups(os.path.join(DATA_DIR, 'lookup_cache.json'), CONTACT_URL, LOOKUPS_ENABLED)
lookup_pool = ThreadPoolExecutor(max_workers=4)
if DEMO_MODE:
    # Fill the trails so the demo map is not empty for its first few minutes.
    _now = time.time()
    for _t in range(TRAIL_SECONDS, 0, -2):
        tracker.sample(demo_snapshot(_now - _t), _now - _t)
tracker.start()

if __name__ == '__main__':
    print("=" * 50)
    print("  ADS-B FLIGHT DASHBOARD")
    print("=" * 50)
    if DEMO_MODE:
        print("  MODE: DEMO (sample data)")
    else:
        print("  MODE: LIVE (dump1090 data)")
        # Setup dump1090 directory
        setup_dump1090_directory()
    print(f"  DATABASE: {len(aircraft_db)} aircraft loaded")
    if not os.path.exists(MAP_FILE):
        print("  MAP: not downloaded yet. Run: python3 download_map.py")
    port = int(os.environ.get('PORT', 8080))
    print(f"  URL: http://localhost:{port}")
    print("=" * 50)
    # HOST picks the address to listen on, e.g. one interface's IP. The default is every IPv4 address.
    app.run(host=os.environ.get('HOST', '0.0.0.0'), port=port, debug=False)

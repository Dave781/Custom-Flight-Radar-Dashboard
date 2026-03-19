#!/usr/bin/env python3
"""
ADS-B Flight Dashboard
Reads local dump1090 aircraft data and displays overhead flights
Enriches data with aircraft database lookups
"""

from flask import Flask, render_template, jsonify, request
import json
import math
import os
import random
import subprocess
import stat
from datetime import datetime
from pathlib import Path

app = Flask(__name__)

# Configuration
DEMO_MODE = os.environ.get('DEMO_MODE', 'false').lower() == 'true'
seen_threshold = int(os.environ.get('SEEN_THRESHOLD', 120))
DASHBOARD_TITLE = os.environ.get('DASHBOARD_TITLE', "Dave's ADS-B Radar")

# Antenna location (Shoreline, WA)
HOME_LAT = 47.650923
HOME_LON = -122.346385
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
AIRCRAFT_DB_FILE = os.path.join(DATA_DIR, 'aircraft_db.json')
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

def haversine_distance(lat1, lon1, lat2, lon2):
    """Calculate great-circle distance in miles between two lat/lon points"""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return round(R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)), 1)

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

def get_demo_data():
    """Generate demo data with real aircraft hex codes"""
    # Real aircraft hex codes that exist in the database
    sample_flights = [
        {"hex": "a0a0a0", "flight": "DAL1412", "lat": 47.4502, "lon": -122.3088, "alt_baro": 1375, "gs": 127, "track": 180, "baro_rate": -768, "squawk": "1200", "rssi": -3.2, "seen": 2, "messages": 1542, "alt_geom": 1425},
        {"hex": "a6b3c4", "flight": "UAL2294", "lat": 47.5012, "lon": -122.2901, "alt_baro": 32000, "gs": 445, "track": 270, "baro_rate": 0, "squawk": "4521", "rssi": -5.1, "seen": 5, "messages": 892, "alt_geom": 32150},
        {"hex": "a1c2d3", "flight": "AAL847", "lat": 47.4221, "lon": -122.3567, "alt_baro": 18500, "gs": 320, "track": 45, "baro_rate": 1800, "squawk": "7234", "rssi": -8.4, "seen": 1, "messages": 2341, "alt_geom": 18650},
        {"hex": "a9b8c7", "flight": "SWA1823", "lat": 47.3890, "lon": -122.4012, "alt_baro": 38000, "gs": 480, "track": 90, "baro_rate": 0, "squawk": "5765", "rssi": -12.1, "seen": 8, "messages": 445, "alt_geom": 38200},
        {"hex": "a4d5e6", "flight": "ASA512", "lat": 47.5234, "lon": -122.2456, "alt_baro": 8500, "gs": 210, "track": 315, "baro_rate": -2200, "squawk": "3342", "rssi": -6.7, "seen": 3, "messages": 1123, "alt_geom": 8600},
        {"hex": "a7e8f9", "flight": "JBU915", "lat": 47.4678, "lon": -122.3234, "alt_baro": 25000, "gs": 390, "track": 135, "baro_rate": 500, "squawk": "2341", "rssi": -9.2, "seen": 4, "messages": 789, "alt_geom": 25100},
    ]

    # Randomize slightly for realism
    for ac in sample_flights:
        ac['alt_baro'] += random.randint(-200, 200)
        ac['gs'] += random.randint(-5, 5)
        ac['seen'] = random.randint(1, 8)
        ac['baro_rate'] += random.randint(-50, 50)

    return {"aircraft": sample_flights, "now": datetime.now().timestamp()}

def get_aircraft_data():
    """Read aircraft data from local dump1090 JSON file"""
    if DEMO_MODE:
        return get_demo_data()

    json_path = find_aircraft_json()

    if not json_path:
        return {"error": "aircraft.json not found. Run with DEMO_MODE=true to test.", "aircraft": [], "now": 0}

    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        return {"error": str(e), "aircraft": [], "now": 0}

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
        db_info = aircraft_db.get(hex_code, {})
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
        ac['distance_mi'] = haversine_distance(HOME_LAT, HOME_LON, ac['lat'], ac['lon'])

        # Aircraft type display string
        if ac['manufacturer'] and ac['model']:
            ac['aircraft_type'] = f"{ac['manufacturer']} {ac['model']}"
        elif ac['model']:
            ac['aircraft_type'] = ac['model']
        elif ac['typecode']:
            ac['aircraft_type'] = ac['typecode']
        else:
            ac['aircraft_type'] = None

        enriched.append(ac)

    # Sort by distance if available, fall back to signal strength
    enriched.sort(key=lambda x: (x['distance_mi'] is None, x.get('distance_mi') or 9999, -(x.get('rssi') or -999)))
    return enriched

@app.route('/')
def index():
    """Main dashboard page"""
    return render_template('index.html')

@app.route('/api/aircraft')
def api_aircraft():
    """API endpoint for aircraft data"""
    data = get_aircraft_data()

    if 'error' in data and data['error']:
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
    })

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
    port = int(os.environ.get('PORT', 8080))
    print(f"  URL: http://localhost:{port}")
    print("=" * 50)
    app.run(host='0.0.0.0', port=port, debug=False)

"""
Demo traffic for DEMO_MODE=true.

Each flight follows a fixed path around Seattle and repeats, so the map,
trails, and flight card can be tried without a receiver. Set DEMO_SCENARIO
to emergency, stalled, or empty to see those states. Registrations and
ICAO hex codes are real airframes, which lets route and photo lookups work.
"""

import math

from geo import bearing_deg, distance_mi

DEMO_HOME = (47.6062, -122.3321)   # downtown Seattle

# Waypoints are (lat, lon, altitude_ft, ground_speed_kt).
_SEA_FINAL = (47.470, -122.310, 600, 145)
FLIGHTS = [
    {'hex': 'aca948', 'flight': 'ASA7', 'squawk': '3524', 'category': 'A3', 'offset': 0,
     'db': {'registration': 'N915AK', 'manufacturer': 'Boeing', 'model': '737-9', 'typecode': 'B39M',
            'owner': 'Alaska Airlines', 'built': '2021'},
     'path': [(48.10, -122.30, 9000, 250), (47.80, -122.31, 5000, 210), (47.62, -122.31, 3200, 180), _SEA_FINAL]},
    {'hex': 'a4b0bb', 'flight': 'DAL166', 'squawk': '2271', 'category': 'A5', 'offset': 260,
     'db': {'registration': 'N401DZ', 'manufacturer': 'Airbus', 'model': 'A330-941', 'typecode': 'A339',
            'owner': 'Delta Air Lines', 'built': '2019'},
     'path': [(47.80, -123.60, 20000, 340), (47.95, -122.90, 13000, 300), (48.00, -122.40, 8500, 250),
              (47.80, -122.31, 5000, 210), _SEA_FINAL]},
    {'hex': '406d77', 'flight': 'BAW49', 'squawk': '6012', 'category': 'A5', 'offset': 540,
     'db': {'registration': 'G-ZBKA', 'manufacturer': 'Boeing', 'model': '787-9', 'typecode': 'B789',
            'owner': 'British Airways', 'built': '2015'},
     'path': [(48.30, -121.60, 17000, 320), (48.05, -122.05, 11000, 280), (47.90, -122.28, 8000, 240),
              (47.70, -122.31, 4500, 200), _SEA_FINAL]},
    {'hex': '86e7bc', 'flight': 'ANA117', 'squawk': '1463', 'category': 'A5', 'offset': 90,
     'db': {'registration': 'JA873A', 'manufacturer': 'Boeing', 'model': '787-9', 'typecode': 'B789',
            'owner': 'All Nippon Airways', 'built': '2015'},
     'path': [(47.43, -122.31, 1500, 170), (47.25, -122.33, 6000, 250), (47.20, -122.55, 10000, 290),
              (47.45, -122.85, 17000, 330), (47.90, -123.30, 24000, 400)]},
    {'hex': 'acfbfd', 'flight': 'ASA65', 'squawk': '4417', 'category': 'A3', 'offset': 400,
     'db': {'registration': 'N936AK', 'manufacturer': 'Boeing', 'model': '737-9', 'typecode': 'B39M',
            'owner': 'Alaska Airlines', 'built': '2022'},
     'path': [(47.43, -122.31, 1500, 170), (47.26, -122.32, 6500, 250), (47.30, -122.60, 11000, 290),
              (47.70, -122.75, 18000, 340), (48.30, -123.00, 26000, 410)]},
    {'hex': 'a817b1', 'flight': 'QXE2024', 'squawk': '5230', 'category': 'A3', 'offset': 150,
     'db': {'registration': 'N620QX', 'manufacturer': 'Embraer', 'model': 'E175', 'typecode': 'E75L',
            'owner': 'Horizon Air', 'built': '2017'},
     'path': [(47.05, -122.20, 13000, 300), (47.45, -122.10, 9000, 270), (47.75, -122.15, 5000, 220),
              (47.90, -122.28, 700, 135)]},
    {'hex': 'a0c3fc', 'flight': 'ABX3111', 'squawk': '3261', 'category': 'A5', 'offset': 330,
     'db': {'registration': 'N1489A', 'manufacturer': 'Boeing', 'model': '767-300F', 'typecode': 'B763',
            'owner': 'Prime Air', 'built': '1994'},
     'path': [(47.75, -122.62, 5000, 220), (47.64, -122.43, 2500, 170), (47.545, -122.315, 300, 135)]},
    {'hex': 'abf4df', 'flight': 'N87KA', 'squawk': '1200', 'category': 'A1', 'offset': 40,
     'db': {'registration': 'N87KA', 'manufacturer': 'de Havilland Canada', 'model': 'DHC-3 Turbine Otter',
            'typecode': 'DH3T', 'owner': 'Kenmore Air', 'built': '1957'},
     'path': [(47.629, -122.339, 100, 70), (47.68, -122.41, 1200, 105), (47.95, -122.60, 1500, 115),
              (48.25, -122.80, 1500, 115)]},
    {'hex': 'ad3869', 'flight': 'N951AL', 'squawk': '1200', 'category': 'A7', 'offset': 0,
     'db': {'registration': 'N951AL', 'manufacturer': 'Agusta', 'model': 'A109E Power', 'typecode': 'A109',
            'owner': 'Air Methods', 'built': '2005'},
     'path': [(47.53, -122.30, 800, 90), (47.60, -122.33, 1000, 100), (47.655, -122.305, 1000, 100),
              (47.62, -122.25, 1000, 100), (47.54, -122.29, 700, 90)]},
    {'hex': 'ae07e0', 'flight': 'RCH283', 'squawk': '4301', 'category': 'A5', 'offset': 200,
     'db': {'registration': '94-0066', 'manufacturer': 'Boeing', 'model': 'C-17A Globemaster III',
            'typecode': 'C17', 'owner': 'United States Air Force', 'built': '1995'},
     'path': [(47.14, -122.48, 4000, 230), (47.45, -122.52, 10000, 280), (47.90, -122.55, 14000, 300),
              (48.30, -122.60, 16000, 320)]},
    {'hex': 'aa8c98', 'flight': 'BOE1', 'squawk': '2634', 'category': 'A5', 'offset': 620,
     'db': {'registration': 'N779XW', 'manufacturer': 'Boeing', 'model': '777-9', 'typecode': 'B779',
            'owner': 'Boeing Company', 'built': '2019'},
     'path': [(47.906, -122.282, 1000, 170), (48.15, -122.45, 8000, 260), (48.30, -123.00, 16000, 320),
              (47.90, -123.60, 22000, 380)]},
    {'hex': 'a12239', 'flight': 'N172SP', 'squawk': '1200', 'category': 'A1', 'offset': 480,
     'db': {'registration': 'N172SP', 'manufacturer': 'Cessna', 'model': '172', 'typecode': 'C172',
            'owner': 'Private', 'built': '1978'},
     'path': [(47.493, -122.216, 500, 80), (47.60, -122.25, 2000, 100), (47.75, -122.26, 2500, 105),
              (47.90, -122.20, 2500, 105)]},
    {'hex': 'abaf6e', 'flight': 'GTI8104', 'squawk': '7145', 'category': 'A5', 'offset': 100,
     'db': {'registration': 'N852GT', 'manufacturer': 'Boeing', 'model': '747-8F', 'typecode': 'B748',
            'owner': 'Polar Air Cargo', 'built': '2012'},
     'path': [(48.40, -121.90, 36000, 480), (47.00, -122.90, 36000, 480)]},
]

GAP_SECONDS = 320   # pause between repeats of a flight, longer than the trail


def _prepare(flight):
    legs = []
    total = 0.0
    path = flight['path']
    for a, b in zip(path, path[1:]):
        miles = distance_mi(a[0], a[1], b[0], b[1])
        knots = (a[3] + b[3]) / 2
        seconds = miles / (knots * 1.15078) * 3600
        legs.append((total, seconds, a, b))
        total += seconds
    flight['_legs'] = legs
    flight['_duration'] = total


for _f in FLIGHTS:
    _prepare(_f)


def _state(flight, t):
    period = flight['_duration'] + GAP_SECONDS
    tau = (t + flight['offset']) % period
    if tau >= flight['_duration']:
        return None
    for start, seconds, a, b in flight['_legs']:
        if tau <= start + seconds:
            k = (tau - start) / seconds
            lat = a[0] + (b[0] - a[0]) * k
            lon = a[1] + (b[1] - a[1]) * k
            alt = a[2] + (b[2] - a[2]) * k
            gs = a[3] + (b[3] - a[3]) * k
            rate = (b[2] - a[2]) / seconds * 60
            dist = distance_mi(DEMO_HOME[0], DEMO_HOME[1], lat, lon)
            return {
                'hex': flight['hex'],
                'flight': flight['flight'],
                'lat': round(lat, 5),
                'lon': round(lon, 5),
                'alt_baro': int(round(alt / 25) * 25),
                'alt_geom': int(round(alt / 25) * 25) + 75,
                'gs': round(gs, 1),
                'track': round(bearing_deg(a[0], a[1], b[0], b[1]), 1),
                'baro_rate': int(round(rate / 64) * 64),
                'squawk': flight['squawk'],
                'category': flight['category'],
                'rssi': round(-3 - 12 * math.log10(1 + dist), 1),
                'seen': round(0.1 + (hash((flight['hex'], int(t))) % 12) / 10, 1),
                'seen_pos': 0.4,
                'messages': int(tau * 6),
                '_db': flight['db'],
            }
    return None


def demo_snapshot(t, scenario=''):
    """
    Aircraft list in dump1090 format for wall-clock time t.

    scenario tries out a state that is rare in real life:
      emergency  one flight squawks 7700
      stalled    the decoder runs but no new messages arrive
      empty      no aircraft at all
    """
    aircraft = [s for s in (_state(f, t) for f in FLIGHTS) if s]
    messages = int(t * 350) % 2_000_000_000
    if scenario == 'emergency':
        for ac in aircraft:
            if ac['flight'] == 'BAW49':
                ac['squawk'] = '7700'
    elif scenario == 'stalled':
        messages = 1000
    elif scenario == 'empty':
        aircraft = []
    return {'now': t, 'messages': messages, 'aircraft': aircraft}

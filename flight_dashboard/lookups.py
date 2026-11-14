"""
Route and photo lookups for the selected aircraft.

  route  adsbdb.com, by callsign
  photo  planespotters.net, by ICAO hex

Answers are cached in memory and in data/lookup_cache.json, so each callsign
or airframe is asked for at most once per cache period.
"""

import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

from geo import cross_track_mi, distance_mi

ROUTE_URL = 'https://api.adsbdb.com/v0/callsign/{}'
PHOTO_URL = 'https://api.planespotters.net/pub/photos/hex/{}'
TIMEOUT_SECONDS = 5
HIT_TTL = 24 * 3600
MISS_TTL = 6 * 3600
ERROR_TTL = 120
MAX_ENTRIES = 5000

# Airline-style callsigns only (ASA7, QXE2024, BAW49C). Tail numbers have no route.
AIRLINE_CALLSIGN = re.compile(r'^[A-Z]{3}[0-9][0-9A-Z]{0,4}$')

# A route is shown only if the aircraft is somewhere that route would put it.
LOW_ALTITUDE_FT = 12000
NEAR_AIRPORT_MI = 75       # below LOW_ALTITUDE_FT, one end of the route must be this close
LEG_SLACK_MI = 100         # in cruise, how far past either end of the leg is still accepted
CORRIDOR_MI = 250          # in cruise, how far to the side of the direct path is still accepted

class Lookups:
    def __init__(self, cache_file, contact_url, enabled=True):
        self.cache_file = cache_file
        self.user_agent = f'Custom-Flight-Radar-Dashboard/2.0 (+{contact_url})'
        self.enabled = enabled
        self.lock = threading.Lock()
        self.cache = {}
        self._dirty = False
        self._load()

    # ---- cache ----

    def _load(self):
        try:
            with open(self.cache_file) as f:
                self.cache = json.load(f)
        except (OSError, ValueError):
            self.cache = {}

    def _save(self):
        with self.lock:
            if not self._dirty:
                return
            if len(self.cache) > MAX_ENTRIES:
                newest = sorted(self.cache.items(), key=lambda kv: kv[1]['t'])[-MAX_ENTRIES // 2:]
                self.cache = dict(newest)
            snapshot = dict(self.cache)
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
            tmp = self.cache_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(snapshot, f)
            os.replace(tmp, self.cache_file)
        except OSError as e:
            print(f'[LOOKUP] could not save cache: {e}')

    def _cached(self, key, fetch):
        now = time.time()
        with self.lock:
            entry = self.cache.get(key)
        if entry and now < entry['t'] + entry['ttl']:
            return entry['v']
        try:
            value = fetch()
            ttl = HIT_TTL if value else MISS_TTL
        except Exception as e:
            print(f'[LOOKUP] {key}: {e}')
            value, ttl = None, ERROR_TTL
        with self.lock:
            self.cache[key] = {'t': now, 'ttl': ttl, 'v': value}
            self._dirty = True
        self._save()
        return value

    def _get_json(self, url):
        request = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                return json.load(response)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None            # unknown callsign or airframe: a real answer, cache it
            raise

    # ---- route ----

    def route(self, callsign):
        callsign = (callsign or '').strip().upper()
        if not self.enabled or not AIRLINE_CALLSIGN.match(callsign):
            return None
        return self._cached(f'route:{callsign}', lambda: self._fetch_route(callsign))

    def _fetch_route(self, callsign):
        data = self._get_json(ROUTE_URL.format(callsign))
        flight = ((data or {}).get('response') or {})
        flight = flight.get('flightroute') if isinstance(flight, dict) else None
        if not flight:
            return None

        def airport(a):
            return {'code': a.get('iata_code') or a.get('icao_code'), 'city': a.get('municipality'),
                    'name': a.get('name'), 'lat': a.get('latitude'), 'lon': a.get('longitude')}

        origin, destination = airport(flight['origin']), airport(flight['destination'])
        if not origin['code'] or not destination['code']:
            return None
        return {'origin': origin, 'destination': destination,
                'airline': (flight.get('airline') or {}).get('name')}

    # ---- photo ----

    def photo(self, hex_code):
        hex_code = (hex_code or '').strip().upper()
        if not self.enabled or not re.match(r'^[0-9A-F]{6}$', hex_code):
            return None
        return self._cached(f'photo:{hex_code}', lambda: self._fetch_photo(hex_code))

    def _fetch_photo(self, hex_code):
        data = self._get_json(PHOTO_URL.format(hex_code))
        photos = (data or {}).get('photos') or []
        if not photos:
            return None
        p = photos[0]
        image = p.get('thumbnail_large') or p.get('thumbnail') or {}
        if not image.get('src'):
            return None
        return {'src': image['src'], 'link': p.get('link'), 'by': p.get('photographer')}


def route_is_plausible(route, lat, lon, altitude_ft):
    """
    Callsign-to-route tables go stale, and one flight number can cover several legs.
    Hide a route when the aircraft is nowhere near where that route would take it.
    """
    try:
        o, d = route['origin'], route['destination']
        to_origin = distance_mi(lat, lon, o['lat'], o['lon'])
        to_destination = distance_mi(lat, lon, d['lat'], d['lon'])
    except (KeyError, TypeError):
        return False
    if altitude_ft is not None and altitude_ft < LOW_ALTITUDE_FT:
        return min(to_origin, to_destination) <= NEAR_AIRPORT_MI
    leg = distance_mi(o['lat'], o['lon'], d['lat'], d['lon'])
    if max(to_origin, to_destination) > leg + LEG_SLACK_MI:
        return False
    return cross_track_mi(lat, lon, o['lat'], o['lon'], d['lat'], d['lon']) <= CORRIDOR_MI

"""
Background sampler.

Reads the aircraft list once a second and keeps three things the page needs
beyond the current snapshot:

  trails    the last few minutes of each aircraft's track
  receiver  whether messages are still arriving
  today     planes seen, farthest, highest, and fastest since local midnight
"""

import json
import os
import threading
import time
from collections import deque
from datetime import datetime

from geo import distance_mi

# Readings outside these limits are treated as decode glitches.
MAX_ALTITUDE_FT = 60000
MAX_SPEED_KT = 800
MAX_DISTANCE_MI = 350
MIN_TRAIL_STEP_SECONDS = 2
SAVE_EVERY_SECONDS = 60
STALE_SECONDS = 30


class Tracker:
    def __init__(self, read_snapshot, home, trail_seconds, stall_seconds, state_file):
        self.read_snapshot = read_snapshot
        self.home = home
        self.trail_seconds = trail_seconds
        self.stall_seconds = stall_seconds
        self.state_file = state_file
        self.lock = threading.Lock()
        self.trails = {}                 # hex -> deque of (t, lon, lat, altitude)
        self.started = time.time()
        self.last_total = None
        self.last_increase = time.time()
        self.last_data_time = 0
        self.rate_window = deque(maxlen=12)
        self.day = None
        self.seen = set()
        self.records = {}
        self._last_save = 0
        self._load()

    # ---- sampling ----

    def start(self):
        threading.Thread(target=self._run, name='tracker', daemon=True).start()

    def _run(self):
        while True:
            try:
                self.sample(self.read_snapshot(), time.time())
            except Exception as e:                      # keep sampling whatever happens
                print(f'[TRACKER] {e}')
            time.sleep(1)

    def sample(self, data, now):
        aircraft = data.get('aircraft') or []
        with self.lock:
            self._roll_day(now)
            self._update_receiver(data, now)
            for ac in aircraft:
                if 'lat' not in ac or 'lon' not in ac:
                    continue
                if ac.get('seen_pos', ac.get('seen', 0)) > 15:
                    continue                            # position too old to trust
                hex_code = (ac.get('hex') or '').lower()
                if not hex_code:
                    continue
                altitude = ac.get('alt_baro', ac.get('altitude'))
                altitude = altitude if isinstance(altitude, (int, float)) else None
                self._add_trail_point(hex_code, now, ac['lon'], ac['lat'], altitude)
                self._update_today(ac, hex_code, altitude)
            self._prune(now)
        if now - self._last_save > SAVE_EVERY_SECONDS:
            self._save()
            self._last_save = now

    def _add_trail_point(self, hex_code, now, lon, lat, altitude):
        trail = self.trails.setdefault(hex_code, deque())
        if trail:
            t, last_lon, last_lat, _ = trail[-1]
            if now - t < MIN_TRAIL_STEP_SECONDS or (last_lon == lon and last_lat == lat):
                return
        trail.append((round(now, 1), lon, lat, altitude))

    def _prune(self, now):
        cutoff = now - self.trail_seconds
        for hex_code in list(self.trails):
            trail = self.trails[hex_code]
            while trail and trail[0][0] < cutoff:
                trail.popleft()
            if not trail:
                del self.trails[hex_code]

    def _update_receiver(self, data, now):
        if data.get('error'):
            return
        self.last_data_time = data.get('now') or now
        total = data.get('messages')
        if not isinstance(total, (int, float)):
            # Older decoders have no running total. Fall back to the per-aircraft counts.
            total = sum(a.get('messages', 0) for a in data.get('aircraft') or [])
        if self.last_total is not None and total > self.last_total:
            self.last_increase = now
        self.rate_window.append((now, total))
        self.last_total = total

    def _update_today(self, ac, hex_code, altitude):
        self.seen.add(hex_code)
        name = (ac.get('flight') or '').strip() or hex_code.upper()
        speed = ac.get('gs', ac.get('speed'))
        if altitude is not None and 0 < altitude <= MAX_ALTITUDE_FT:
            self._record('highest', altitude, name)
        if isinstance(speed, (int, float)) and 0 < speed <= MAX_SPEED_KT:
            self._record('fastest', speed, name)
        if self.home:
            miles = distance_mi(self.home[0], self.home[1], ac['lat'], ac['lon'])
            if miles <= MAX_DISTANCE_MI:
                self._record('farthest', miles, name)

    def _record(self, key, value, name):
        best = self.records.get(key)
        if not best or value > best['value']:
            self.records[key] = {'value': round(value, 1), 'callsign': name}

    def _roll_day(self, now):
        day = datetime.fromtimestamp(now).strftime('%Y-%m-%d')
        if day != self.day:
            self.day = day
            self.seen = set()
            self.records = {}

    # ---- persistence, so a restart does not reset the day ----

    def _load(self):
        try:
            with open(self.state_file) as f:
                state = json.load(f)
        except (OSError, ValueError):
            return
        if state.get('day') == datetime.now().strftime('%Y-%m-%d'):
            self.day = state['day']
            self.seen = set(state.get('seen', []))
            self.records = state.get('records', {})

    def _save(self):
        with self.lock:
            state = {'day': self.day, 'seen': sorted(self.seen), 'records': self.records}
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            tmp = self.state_file + '.tmp'
            with open(tmp, 'w') as f:
                json.dump(state, f)
            os.replace(tmp, self.state_file)
        except OSError as e:
            print(f'[TRACKER] could not save {self.state_file}: {e}')

    # ---- views ----

    def trails_snapshot(self):
        with self.lock:
            return {h: [[lon, lat, alt, t] for t, lon, lat, alt in trail]
                    for h, trail in self.trails.items() if len(trail) > 1}

    def receiver_status(self, now=None):
        """state is 'ok', 'stalled' (decoder runs but hears nothing), or 'down' (no fresh data file)."""
        now = now or time.time()
        with self.lock:
            quiet = now - self.last_increase
            rate = None
            if len(self.rate_window) >= 2:
                (t0, m0), (t1, m1) = self.rate_window[0], self.rate_window[-1]
                if t1 > t0 and m1 >= m0:
                    rate = round((m1 - m0) / (t1 - t0), 1)
            data_age = now - self.last_data_time if self.last_data_time else now - self.started
        if data_age > STALE_SECONDS:
            return {'state': 'down', 'quiet_seconds': int(data_age), 'rate': rate}
        if quiet > self.stall_seconds:
            return {'state': 'stalled', 'quiet_seconds': int(quiet), 'rate': rate}
        return {'state': 'ok', 'quiet_seconds': int(quiet), 'rate': rate}

    def today(self):
        with self.lock:
            return {
                'count': len(self.seen),
                'farthest': self.records.get('farthest'),
                'highest': self.records.get('highest'),
                'fastest': self.records.get('fastest'),
            }

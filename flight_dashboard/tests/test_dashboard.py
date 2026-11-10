"""
Tests for the parts that are easy to get wrong.

Run from flight_dashboard/:
    venv/bin/python -m unittest discover -s tests
No receiver or network is needed.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ['DEMO_MODE'] = 'true'
os.environ['LOOKUPS'] = 'false'          # tests never call outside services
os.environ.pop('DEMO_SCENARIO', None)

import app as dashboard                   # noqa: E402
import demo                               # noqa: E402
import download_map                       # noqa: E402
from geo import bearing_deg, cross_track_mi, distance_mi, elevation_deg   # noqa: E402
from lookups import AIRLINE_CALLSIGN, Lookups, route_is_plausible          # noqa: E402
from tracker import Tracker               # noqa: E402

AIRPORTS = {
    'SEA': (47.4502, -122.3088), 'JFK': (40.6413, -73.7781), 'SFO': (37.619, -122.375),
    'PDX': (45.5887, -122.598), 'HND': (35.5494, 139.7798), 'MIA': (25.7959, -80.287),
    'CVG': (39.0488, -84.6678),
}


def route(origin, destination):
    return {'origin': {'lat': AIRPORTS[origin][0], 'lon': AIRPORTS[origin][1]},
            'destination': {'lat': AIRPORTS[destination][0], 'lon': AIRPORTS[destination][1]}}


class Geometry(unittest.TestCase):
    def test_distance(self):
        self.assertAlmostEqual(distance_mi(*AIRPORTS['SEA'], *AIRPORTS['PDX']), 129, delta=2)

    def test_bearing(self):
        self.assertAlmostEqual(bearing_deg(47.0, -122.0, 48.0, -122.0), 0, delta=0.1)
        self.assertAlmostEqual(bearing_deg(47.0, -122.0, 47.0, -121.0), 90, delta=1)

    def test_elevation(self):
        self.assertAlmostEqual(elevation_deg(1, 5280), 45, delta=0.1)
        self.assertIsNone(elevation_deg(None, 1000))

    def test_cross_track(self):
        # Spokane is close to the direct path from New York to Seattle.
        self.assertLess(cross_track_mi(47.6, -117.5, *AIRPORTS['JFK'], *AIRPORTS['SEA']), 150)


class RoutePlausibility(unittest.TestCase):
    def test_arrival_near_destination(self):
        self.assertTrue(route_is_plausible(route('JFK', 'SEA'), 47.6, -122.3, 3000))

    def test_wrong_leg_low_over_seattle(self):
        self.assertFalse(route_is_plausible(route('SFO', 'PDX'), 47.63, -122.32, 3450))
        self.assertFalse(route_is_plausible(route('CVG', 'MIA'), 47.64, -122.44, 2600))

    def test_wrong_leg_in_cruise(self):
        self.assertFalse(route_is_plausible(route('SFO', 'PDX'), 47.63, -122.32, 36000))

    def test_departure_climbing_out(self):
        self.assertTrue(route_is_plausible(route('SEA', 'HND'), 47.7, -123.1, 20000))

    def test_cruise_along_the_path(self):
        self.assertTrue(route_is_plausible(route('JFK', 'SEA'), 47.6, -117.5, 36000))

    def test_missing_coordinates(self):
        self.assertFalse(route_is_plausible({'origin': {}, 'destination': {}}, 47, -122, 1000))

    def test_only_airline_callsigns_are_looked_up(self):
        self.assertTrue(AIRLINE_CALLSIGN.match('ASA7'))
        self.assertTrue(AIRLINE_CALLSIGN.match('BAW49C'))
        self.assertFalse(AIRLINE_CALLSIGN.match('N172SP'))
        lookups = Lookups(os.path.join(tempfile.mkdtemp(), 'cache.json'), 'https://example.com', enabled=True)
        self.assertIsNone(lookups.route('N172SP'))      # returns before any network call
        self.assertIsNone(lookups.photo('not-hex'))


class TrackerTests(unittest.TestCase):
    def make(self, stall_seconds=180):
        state_file = os.path.join(tempfile.mkdtemp(), 'today.json')
        return Tracker(lambda: {}, demo.DEMO_HOME, 300, stall_seconds, state_file), state_file

    def test_trails_and_today(self):
        tracker, _ = self.make()
        now = time.time()
        for t in range(300, 0, -2):
            tracker.sample(demo.demo_snapshot(now - t), now - t)
        trails = tracker.trails_snapshot()
        self.assertGreater(len(trails), 5)
        for points in trails.values():
            self.assertLessEqual(points[-1][3] - points[0][3], 300)
        today = tracker.today()
        self.assertGreater(today['count'], 5)
        self.assertGreater(today['highest']['value'], 30000)
        self.assertEqual(tracker.receiver_status(now)['state'], 'ok')

    def test_stalled_when_messages_stop(self):
        tracker, _ = self.make(stall_seconds=60)
        now = time.time()
        frozen = demo.demo_snapshot(now, 'stalled')
        for t in range(0, 120, 5):
            tracker.sample(dict(frozen, now=now + t), now + t)
        self.assertEqual(tracker.receiver_status(now + 120)['state'], 'stalled')

    def test_down_when_data_stops(self):
        tracker, _ = self.make()
        now = time.time()
        tracker.sample(demo.demo_snapshot(now), now)
        self.assertEqual(tracker.receiver_status(now + 90)['state'], 'down')

    def test_glitches_do_not_set_records(self):
        tracker, _ = self.make()
        now = time.time()
        bad = {'now': now, 'messages': 5, 'aircraft': [
            {'hex': 'abc123', 'flight': 'BAD1', 'lat': 10.0, 'lon': 10.0, 'alt_baro': 126000, 'gs': 2400}]}
        tracker.sample(bad, now)
        today = tracker.today()
        self.assertIsNone(today['highest'])
        self.assertIsNone(today['fastest'])
        self.assertIsNone(today['farthest'])

    def test_today_survives_a_restart(self):
        tracker, state_file = self.make()
        now = time.time()
        tracker.sample(demo.demo_snapshot(now), now)
        tracker._save()
        again = Tracker(lambda: {}, demo.DEMO_HOME, 300, 180, state_file)
        self.assertEqual(again.today()['count'], tracker.today()['count'])


class MapDownload(unittest.TestCase):
    def test_tile_ids(self):
        ids = [download_map.zxy_to_tileid(*zxy) for zxy in
               [(0, 0, 0), (1, 0, 0), (1, 0, 1), (1, 1, 1), (1, 1, 0), (2, 0, 0)]]
        self.assertEqual(ids, [0, 1, 2, 3, 4, 5])

    def test_directory_round_trip(self):
        entries = [[5, 1, 0, 10], [6, 2, 10, 20], [9, 1, 10, 20], [10, 1, 300, 7]]
        decoded = download_map.parse_directory(download_map.build_directory(entries))
        self.assertEqual([list(e) for e in decoded], entries)

    def test_header_round_trip(self):
        keys = ['root_offset', 'root_length', 'meta_offset', 'meta_length', 'leaf_offset', 'leaf_length',
                'data_offset', 'data_length', 'addressed', 'entries', 'contents', 'clustered',
                'internal_compression', 'tile_compression', 'tile_type', 'min_zoom', 'max_zoom',
                'min_lon', 'min_lat', 'max_lon', 'max_lat', 'center_zoom', 'center_lon', 'center_lat']
        header = {k: i + 1 for i, k in enumerate(keys)}
        raw = download_map.build_header(header)
        self.assertEqual(len(raw), download_map.HEADER_LEN)
        self.assertEqual(download_map.parse_header(raw), header)

    def test_wanted_tiles_cover_the_box(self):
        ids = download_map.wanted_tile_ids((-123.0, 47.0, -122.0, 48.0), 8)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIn(0, ids)


class Classification(unittest.TestCase):
    def test_military_ranges(self):
        self.assertTrue(dashboard.is_military_hex('AE07E0'))
        self.assertTrue(dashboard.is_military_hex('43C123'))
        self.assertFalse(dashboard.is_military_hex('406D77'))    # British Airways 787
        self.assertFalse(dashboard.is_military_hex('ACA948'))
        self.assertFalse(dashboard.is_military_hex('zzzzzz'))

    def test_icons(self):
        self.assertEqual(dashboard.pick_icon(True, 'C17', 'A5'), 'military')
        self.assertEqual(dashboard.pick_icon(False, 'A109', None), 'helicopter')
        self.assertEqual(dashboard.pick_icon(False, '', 'A7'), 'helicopter')
        self.assertEqual(dashboard.pick_icon(False, 'B789', 'A5'), 'heavy')
        self.assertEqual(dashboard.pick_icon(False, 'C172', 'A1'), 'prop')
        self.assertEqual(dashboard.pick_icon(False, 'B39M', 'A3'), 'jet')
        self.assertEqual(dashboard.pick_icon(False, '', None), 'jet')


class Api(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = dashboard.app.test_client()

    def test_pages(self):
        home = self.client.get('/')
        self.assertEqual(home.status_code, 200)
        self.assertIn(b'Primary Target', home.data)
        self.assertIn(b'href="/map"', home.data)          # the MAP button
        self.assertNotIn(b'googleapis', home.data)        # fonts are served from here
        expanded = self.client.get('/map')
        self.assertEqual(expanded.status_code, 200)
        self.assertIn(b'id="btn-close" href="/"', expanded.data)
        self.assertIn(b'"close_seconds"', expanded.data)
        self.assertEqual(self.client.get('/debug').status_code, 200)

    def test_aircraft(self):
        data = self.client.get('/api/aircraft').get_json()
        self.assertGreater(data['total'], 3)
        self.assertIn(data['receiver']['state'], ('ok', 'stalled', 'down'))
        self.assertIn('count', data['today'])
        for ac in data['aircraft']:
            self.assertIn(ac['icon'], ('jet', 'heavy', 'prop', 'helicopter', 'military'))
            self.assertNotIn('_db', ac)
            self.assertIsNotNone(ac['distance_mi'])
            self.assertTrue(0 <= ac['elevation_deg'] <= 90)

    def test_trails(self):
        trails = self.client.get('/api/trails').get_json()
        self.assertGreater(len(trails), 3)
        lon, lat, _altitude, _time = next(iter(trails.values()))[0]
        self.assertTrue(-180 <= lon <= 180 and -90 <= lat <= 90)

    def test_flight_lookup_is_empty_when_lookups_are_off(self):
        data = self.client.get('/api/flight/aca948?callsign=ASA7&lat=47.6&lon=-122.3').get_json()
        self.assertEqual(data, {'route': None, 'photo': None})

    def test_status_and_settings(self):
        status = self.client.get('/api/status').get_json()
        self.assertEqual(status['source'], 'demo')
        self.assertEqual(self.client.post('/api/settings/seen-threshold', json={'value': 60}).get_json(),
                         {'seen_threshold': 60})
        self.client.post('/api/settings/seen-threshold', json={'value': 120})

    def test_map_supports_range_requests(self):
        if not os.path.exists(dashboard.MAP_FILE):
            self.assertEqual(self.client.get('/map.pmtiles').status_code, 404)
            return
        response = self.client.get('/map.pmtiles', headers={'Range': 'bytes=0-126'})
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.data[:7], b'PMTiles')
        response.close()


if __name__ == '__main__':
    unittest.main()

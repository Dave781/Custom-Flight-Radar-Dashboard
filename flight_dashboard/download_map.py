#!/usr/bin/env python3
"""
Download the basemap and airport data for the area around the antenna.

Writes two files into data/ (gitignored):
  map.pmtiles    vector map tiles cut from the Protomaps daily planet build
  airports.json  airports and runways from OurAirports

Uses only the standard library. Run it once, and again whenever you move
the antenna or want fresher map data:

    python3 download_map.py                 # uses HOME_LAT / HOME_LON from .env
    python3 download_map.py --lat 47.6 --lon -122.3 --radius 80
"""

import argparse
import csv
import gzip
import io
import json
import math
import os
import struct
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, 'data')
BUILDS_URL = 'https://build-metadata.protomaps.dev/builds.json'
BUILD_BASE = 'https://build.protomaps.com/'
AIRPORTS_URL = 'https://davidmegginson.github.io/ourairports-data/airports.csv'
RUNWAYS_URL = 'https://davidmegginson.github.io/ourairports-data/runways.csv'
USER_AGENT = 'Custom-Flight-Radar-Dashboard (+https://github.com/Dave781/Custom-Flight-Radar-Dashboard)'

HEADER_LEN = 127
ROOT_BUDGET = 16384 - HEADER_LEN   # header + root directory must fit in the first 16 KB
MERGE_GAP = 128 * 1024             # fetch two byte ranges as one if the gap is smaller than this
MI_PER_DEG_LAT = 69.0


# ---------- HTTP ----------

def fetch(url, start=None, length=None, retries=4):
    headers = {'User-Agent': USER_AGENT}
    if start is not None:
        headers['Range'] = f'bytes={start}-{start + length - 1}'
    last = None
    for _ in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
                return r.read()
        except Exception as e:  # network hiccup: try again
            last = e
    raise RuntimeError(f'download failed: {url}: {last}')


# ---------- PMTiles v3 ----------

HEADER_FMT = '<7sB11Q4B2B4iB2i'


def parse_header(buf):
    f = struct.unpack(HEADER_FMT, buf[:HEADER_LEN])
    if f[0] != b'PMTiles' or f[1] != 3:
        raise RuntimeError('not a PMTiles v3 archive')
    keys = ['root_offset', 'root_length', 'meta_offset', 'meta_length', 'leaf_offset',
            'leaf_length', 'data_offset', 'data_length', 'addressed', 'entries', 'contents',
            'clustered', 'internal_compression', 'tile_compression', 'tile_type',
            'min_zoom', 'max_zoom', 'min_lon', 'min_lat', 'max_lon', 'max_lat',
            'center_zoom', 'center_lon', 'center_lat']
    return dict(zip(keys, f[2:]))


def build_header(h):
    return struct.pack(
        HEADER_FMT, b'PMTiles', 3,
        h['root_offset'], h['root_length'], h['meta_offset'], h['meta_length'],
        h['leaf_offset'], h['leaf_length'], h['data_offset'], h['data_length'],
        h['addressed'], h['entries'], h['contents'],
        h['clustered'], h['internal_compression'], h['tile_compression'], h['tile_type'],
        h['min_zoom'], h['max_zoom'], h['min_lon'], h['min_lat'], h['max_lon'], h['max_lat'],
        h['center_zoom'], h['center_lon'], h['center_lat'])


def read_varint(buf, pos):
    result = shift = 0
    while True:
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not b & 0x80:
            return result, pos
        shift += 7


def write_varint(out, value):
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)


def parse_directory(raw):
    """Return a list of (tile_id, run_length, offset, length)."""
    buf = gzip.decompress(raw)
    n, pos = read_varint(buf, 0)
    ids, runs, lengths, offsets = [], [], [], []
    last = 0
    for _ in range(n):
        d, pos = read_varint(buf, pos)
        last += d
        ids.append(last)
    for _ in range(n):
        v, pos = read_varint(buf, pos)
        runs.append(v)
    for _ in range(n):
        v, pos = read_varint(buf, pos)
        lengths.append(v)
    for i in range(n):
        v, pos = read_varint(buf, pos)
        offsets.append(offsets[i - 1] + lengths[i - 1] if v == 0 and i > 0 else v - 1)
    return list(zip(ids, runs, offsets, lengths))


def build_directory(entries):
    out = bytearray()
    write_varint(out, len(entries))
    last = 0
    for e in entries:
        write_varint(out, e[0] - last)
        last = e[0]
    for e in entries:
        write_varint(out, e[1])
    for e in entries:
        write_varint(out, e[3])
    for i, e in enumerate(entries):
        if i > 0 and e[2] == entries[i - 1][2] + entries[i - 1][3]:
            write_varint(out, 0)
        else:
            write_varint(out, e[2] + 1)
    return gzip.compress(bytes(out), mtime=0)


def zxy_to_tileid(z, x, y):
    """Hilbert-curve tile id used by PMTiles."""
    base = (4 ** z - 1) // 3
    n = 1 << z
    d = 0
    s = n >> 1
    while s > 0:
        rx = 1 if x & s else 0
        ry = 1 if y & s else 0
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x = s - 1 - x
                y = s - 1 - y
            x, y = y, x
        s >>= 1
    return base + d


def lonlat_to_tile(lon, lat, z):
    n = 1 << z
    x = int((lon + 180.0) / 360.0 * n)
    lat_r = math.radians(max(min(lat, 85.0511), -85.0511))
    y = int((1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n)
    return min(max(x, 0), n - 1), min(max(y, 0), n - 1)


def wanted_tile_ids(bbox, max_zoom):
    min_lon, min_lat, max_lon, max_lat = bbox
    ids = []
    for z in range(0, max_zoom + 1):
        x0, y0 = lonlat_to_tile(min_lon, max_lat, z)
        x1, y1 = lonlat_to_tile(max_lon, min_lat, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                ids.append(zxy_to_tileid(z, x, y))
    return sorted(ids)


def locate_tiles(url, header, root, wanted):
    """Walk root and leaf directories. Return {tile_id: (offset, length)} for wanted ids that exist."""
    import bisect
    found = {}
    cache = {}

    def walk(entries, ids):
        starts = [e[0] for e in entries]
        by_leaf = {}
        for tid in ids:
            i = bisect.bisect_right(starts, tid) - 1
            if i < 0:
                continue
            e = entries[i]
            if e[1] == 0:                       # pointer to a leaf directory
                by_leaf.setdefault(i, []).append(tid)
            elif tid < e[0] + e[1]:
                found[tid] = (e[2], e[3])
        for i, sub in by_leaf.items():
            e = entries[i]
            key = (e[2], e[3])
            if key not in cache:
                cache[key] = parse_directory(fetch(url, header['leaf_offset'] + e[2], e[3]))
            walk(cache[key], sub)

    walk(root, wanted)
    return found


def extract_pmtiles(url, bbox, max_zoom, out_path):
    head = fetch(url, 0, 16384)
    src = parse_header(head)
    root = parse_directory(head[src['root_offset']:src['root_offset'] + src['root_length']])
    max_zoom = min(max_zoom, src['max_zoom'])

    wanted = wanted_tile_ids(bbox, max_zoom)
    print(f'  {len(wanted)} tiles wanted (zoom 0 to {max_zoom}), reading the index...')
    found = locate_tiles(url, src, root, wanted)

    # Unique source blobs, sorted by position, merged into a small number of range requests.
    blobs = sorted(set(found.values()))
    ranges = []
    for off, ln in blobs:
        if ranges and off - (ranges[-1][0] + ranges[-1][1]) <= MERGE_GAP:
            ranges[-1][1] = off + ln - ranges[-1][0]
        else:
            ranges.append([off, ln])
    total = sum(r[1] for r in ranges)
    print(f'  {len(found)} tiles found, downloading {total / 1e6:.1f} MB in {len(ranges)} requests...')

    with ThreadPoolExecutor(max_workers=8) as pool:
        chunks = list(pool.map(lambda r: fetch(url, src['data_offset'] + r[0], r[1]), ranges))

    # Lay the blobs out back to back in the new file.
    data = bytearray()
    new_offset = {}
    ri = 0
    for off, ln in blobs:
        while off >= ranges[ri][0] + ranges[ri][1]:
            ri += 1
        start = off - ranges[ri][0]
        new_offset[(off, ln)] = len(data)
        data += chunks[ri][start:start + ln]

    entries = []
    for tid in sorted(found):
        off = new_offset[found[tid]]
        ln = found[tid][1]
        if entries and entries[-1][2] == off and entries[-1][0] + entries[-1][1] == tid:
            entries[-1][1] += 1                 # same blob as the previous tile: extend the run
        else:
            entries.append([tid, 1, off, ln])

    root_bytes = build_directory(entries)
    leaves = b''
    if len(root_bytes) > ROOT_BUDGET:
        size = 2048
        while True:
            leaves = bytearray()
            pointers = []
            for i in range(0, len(entries), size):
                leaf = build_directory(entries[i:i + size])
                pointers.append([entries[i][0], 0, len(leaves), len(leaf)])
                leaves += leaf
            root_bytes = build_directory(pointers)
            if len(root_bytes) <= ROOT_BUDGET:
                break
            size *= 2

    meta = fetch(url, src['meta_offset'], src['meta_length'])
    min_lon, min_lat, max_lon, max_lat = bbox
    h = dict(src)
    h['root_offset'] = HEADER_LEN
    h['root_length'] = len(root_bytes)
    h['meta_offset'] = h['root_offset'] + h['root_length']
    h['meta_length'] = len(meta)
    h['leaf_offset'] = h['meta_offset'] + h['meta_length']
    h['leaf_length'] = len(leaves)
    h['data_offset'] = h['leaf_offset'] + h['leaf_length']
    h['data_length'] = len(data)
    h['addressed'] = len(found)
    h['entries'] = len(entries)
    h['contents'] = len(blobs)
    h['clustered'] = 0
    h['min_zoom'] = 0
    h['max_zoom'] = max_zoom
    h['min_lon'], h['min_lat'] = int(min_lon * 1e7), int(min_lat * 1e7)
    h['max_lon'], h['max_lat'] = int(max_lon * 1e7), int(max_lat * 1e7)
    h['center_zoom'] = min(9, max_zoom)
    h['center_lon'] = int((min_lon + max_lon) / 2 * 1e7)
    h['center_lat'] = int((min_lat + max_lat) / 2 * 1e7)

    tmp = out_path + '.part'
    with open(tmp, 'wb') as f:
        f.write(build_header(h))
        f.write(root_bytes)
        f.write(meta)
        f.write(leaves)
        f.write(data)
    os.replace(tmp, out_path)
    return os.path.getsize(out_path)


# ---------- airports ----------

def miles_between(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 3958.8 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_airports(lat, lon, radius_mi, out_path):
    keep_types = {'large_airport', 'medium_airport', 'small_airport', 'seaplane_base'}
    airports = {}
    rows = csv.DictReader(io.StringIO(fetch(AIRPORTS_URL).decode('utf-8')))
    for row in rows:
        if row['type'] not in keep_types:
            continue
        alat, alon = to_float(row['latitude_deg']), to_float(row['longitude_deg'])
        if alat is None or alon is None or miles_between(lat, lon, alat, alon) > radius_mi:
            continue
        airports[row['ident']] = {
            'ident': row['ident'],
            'code': row['iata_code'] or row['local_code'] or row['ident'],
            'iata': row['iata_code'] or None,
            'name': row['name'],
            'type': row['type'],
            'scheduled': row['scheduled_service'] == 'yes',
            'lat': round(alat, 5),
            'lon': round(alon, 5),
            'runways': [],
        }
    rows = csv.DictReader(io.StringIO(fetch(RUNWAYS_URL).decode('utf-8')))
    for row in rows:
        ap = airports.get(row['airport_ident'])
        if not ap or row['closed'] == '1':
            continue
        ends = [to_float(row[k]) for k in
                ('le_latitude_deg', 'le_longitude_deg', 'he_latitude_deg', 'he_longitude_deg')]
        if None in ends:
            continue
        ap['runways'].append([round(v, 5) for v in ends])
    result = sorted(airports.values(), key=lambda a: a['ident'])
    with open(out_path, 'w') as f:
        json.dump(result, f, separators=(',', ':'))
    return len(result), sum(1 for a in result if a['runways'])


# ---------- main ----------

def load_dotenv():
    try:
        with open(os.path.join(HERE, '.env')) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"\''))
    except FileNotFoundError:
        pass


def main():
    load_dotenv()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--lat', type=float, default=to_float(os.environ.get('HOME_LAT')))
    p.add_argument('--lon', type=float, default=to_float(os.environ.get('HOME_LON')))
    p.add_argument('--radius', type=float, default=float(os.environ.get('MAP_RADIUS_MI', 80)),
                   help='miles of map around the antenna (default 80)')
    p.add_argument('--maxzoom', type=int, default=int(os.environ.get('MAP_MAX_ZOOM', 12)),
                   help='deepest zoom level to store (default 12)')
    p.add_argument('--skip-map', action='store_true')
    p.add_argument('--skip-airports', action='store_true')
    args = p.parse_args()
    if args.lat is None or args.lon is None:
        sys.exit('Set HOME_LAT and HOME_LON in .env, or pass --lat and --lon.')

    os.makedirs(DATA_DIR, exist_ok=True)
    dlat = args.radius / MI_PER_DEG_LAT
    dlon = args.radius / (MI_PER_DEG_LAT * math.cos(math.radians(args.lat)))
    bbox = (args.lon - dlon, args.lat - dlat, args.lon + dlon, args.lat + dlat)

    if not args.skip_map:
        builds = json.loads(fetch(BUILDS_URL))
        build = sorted(b['key'] for b in builds)[-1]
        print(f'Map: cutting {args.radius:.0f} mi around the antenna from Protomaps build {build}')
        size = extract_pmtiles(BUILD_BASE + build, bbox, args.maxzoom,
                               os.path.join(DATA_DIR, 'map.pmtiles'))
        print(f'  wrote data/map.pmtiles ({size / 1e6:.1f} MB)')

    if not args.skip_airports:
        print('Airports: reading OurAirports')
        n, with_runways = build_airports(args.lat, args.lon, args.radius,
                                         os.path.join(DATA_DIR, 'airports.json'))
        print(f'  wrote data/airports.json ({n} airports, {with_runways} with runway data)')


if __name__ == '__main__':
    main()
